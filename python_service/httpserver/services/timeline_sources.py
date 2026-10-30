"""Read-only adapters for timeline statistics; no extraction or graph rebuild."""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote


class SourceChanged(ValueError):
    pass


class SourceUnavailable(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), default=str).encode()).hexdigest()


def _json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, bytes):
        return {"encoding": "hex", "value": value[:256].hex(), "truncated": len(value) > 256}
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(v) for v in value]
    return value


@dataclass(frozen=True)
class TimelineSource:
    path: Path
    kind: str
    scope_id: str

    @property
    def identity(self):
        return {"kind": self.kind, "scope_id": self.scope_id,
                "record_origin": ("derived_event_table" if self.kind == "events" else
                                  "parsed_message_table" if self.kind == "wechat_task" else
                                  "normalized_import_table" if self.kind == "qq_legacy" else "decrypted_import_table"),
                "timestamp_unit": "milliseconds"
                if self.kind in ("wechat_import", "wechat_task", "qq_legacy") else "seconds"}

    def revision(self):
        if not self.path.is_file() or self.path.is_symlink():
            raise SourceUnavailable("来源数据库不可用")
        bundle = []
        for suffix in ("", "-wal", "-journal"):
            file = Path(str(self.path) + suffix)
            if file.is_symlink():
                raise SourceUnavailable("来源数据库不能是符号链接")
            if file.exists():
                s = file.stat()
                # SQLite may chmod an existing WAL during a read-only open,
                # changing ctime without changing any database content.
                bundle.append((suffix, s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns))
        # An optimistic revision token, deliberately NOT labelled a forensic file hash.
        return digest([self.identity, str(self.path.resolve()), bundle])

    def connect(self):
        conn = sqlite3.connect(f"file:{quote(str(self.path.resolve()), safe='/')}?mode=ro",
                               uri=True, timeout=10)
        try:
            conn.row_factory = sqlite3.Row
            # Real-case databases carry non-UTF-8 text (legacy encoded filenames);
            # strict decoding would abort the whole scan on one row.
            conn.text_factory = lambda raw: raw.decode("utf-8", "replace")
            deadline = time.monotonic() + 30
            conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 10_000)
            conn.execute("PRAGMA query_only=ON")
            conn.execute("BEGIN")
        except Exception:
            conn.close()
            raise
        return conn

    @staticmethod
    def semantic_revision(conn):
        """Content-level guard for the in-scan check: WAL checkpointing by
        concurrent readers leaves data/schema version untouched, so harmless
        file churn no longer fails the summary."""
        return (conn.execute("PRAGMA data_version").fetchone()[0],
                conn.execute("PRAGMA schema_version").fetchone()[0])

    def tables(self, conn):
        available = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        expected = {
            "events": ("events",),
            "wechat_import": ("message",),
            "wechat_task": ("wechat_messages",),
            "qq_import": ("c2c_msg_table", "group_msg_table"),
            # 老版QQ（pre-NTQQ）导入没有 nt_msg.db，只有归一化 graph.db
            "qq_legacy": ("wechat_messages",),
        }[self.kind]
        tables = [t for t in expected if t in available]
        if not tables:
            raise SourceUnavailable("当前来源缺少可统计的记录表")
        return tables, [t for t in expected if t not in available]

    def rows(self, conn, table, filters, limit):
        columns = {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}
        if self.kind == "events":
            required = {"id", "timestamp", "event_type"}
            fields = ("id", "timestamp", "event_type", "file_path", "inode", "description",
                      "event_source", "event_category")
            mapping = {"event_type": "event_type", "event_source": "event_source"}
        elif self.kind == "wechat_import":
            required = {"msgId", "createTime", "isSend", "talker", "type"}
            fields = ("msgId", "msgSvrId", "createTime", "isSend", "talker", "type", "content")
            mapping = {"talker": "talker"}
        elif self.kind in ("wechat_task", "qq_legacy"):
            required = {"id", "timestamp", "is_send", "talker", "msg_type"}
            fields = ("id", "timestamp", "is_send", "talker", "msg_type", "content", "sender", "receiver")
            mapping = {"talker": "talker"}
        else:
            peer = "40033" if table == "group_msg_table" else "40030"
            required = {"40001", "40050", "40013", peer, "40011"}
            fields = tuple(dict.fromkeys(("40001", "40050", "40013", peer, "40011", "40800")))
            mapping = {"talker": peer}
        if not required <= columns:
            raise SourceUnavailable("来源表结构不完整，无法确认时间或收发方向")
        select = ", ".join(f'"{c}"' for c in fields if c in columns)
        where, args = [], []
        for param, column in mapping.items():
            value = getattr(filters, param)
            if value:
                if column not in columns:
                    raise SourceUnavailable("当前来源不支持该筛选字段")
                where.append(f'"{column}" = ?')
                args.append(value)
        clause = " WHERE " + " AND ".join(where) if where else ""
        total = conn.execute(f'SELECT COUNT(*) FROM "{table}"{clause}', args).fetchone()[0]
        cursor = conn.execute(f'SELECT rowid AS "__rowid", {select} FROM "{table}"{clause} '
                              'ORDER BY rowid LIMIT ?', (*args, limit))
        return total, cursor

    def normalize(self, table, raw):
        r = dict(raw)
        reference = f"{table}:{r['__rowid']}"
        if self.kind == "events":
            event_type = r["event_type"]
            source = r.get("event_source") or "UNKNOWN"
            basis = ("processing" if event_type in ("ANDROID_ARTIFACT", "WINDOWS_ARTIFACT", "LINUX_ARTIFACT")
                     else "inferred" if event_type == "DELETED" and source in ("FILE_SYSTEM", "UNKNOWN")
                     else "file_metadata" if source in ("FILE_SYSTEM", "UNKNOWN") and event_type in (
                         "CREATED", "MODIFIED", "ACCESSED", "CHANGED") else "recorded")
            return {"record_ref": reference, "original_id": str(r["id"]), "timestamp_raw": r["timestamp"],
                    "direction": "not_applicable", "talker": "", "event_type": event_type,
                    "event_source": source, "time_basis": basis, "file_path": r.get("file_path"),
                    "content": str(r.get("description") or ""), "raw": r,
                    "dedup_key": [table, r["id"]], "payload": {k: v for k, v in r.items() if k != "__rowid"}}
        if self.kind == "wechat_import":
            timestamp, flag, talker, code = r["createTime"], r["isSend"], r["talker"], r["type"]
            original = r["msgId"]
            server_id = str(r.get("msgSvrId") or "")
            stable_id = ["server", server_id] if server_id not in ("", "0", "-1") else ["local", original]
            content = str(r.get("content") or "")
            payload = {k: v for k, v in r.items() if k not in ("__rowid", "msgId", "msgSvrId")}
            system = isinstance(code, int) and code & 65535 in (10000, 10002)
        elif self.kind in ("wechat_task", "qq_legacy"):
            timestamp, flag, talker, code = r["timestamp"], r["is_send"], r["talker"], r["msg_type"]
            original = r["id"]
            stable_id = ["derived_row", original]
            content = str(r.get("content") or "")
            payload = {k: v for k, v in r.items() if k != "__rowid"}
            system = isinstance(code, int) and code & 65535 in (10000, 10002)
        else:
            timestamp, flag, code = r["40050"], r["40013"], r["40011"]
            talker = r["40033"] if table == "group_msg_table" else r["40030"]
            original = r["40001"]
            stable_id = ["message", original]
            blob = r.get("40800") or b""
            if not isinstance(blob, bytes):
                blob = str(blob).encode()
            content = ""
            payload = {k: v for k, v in r.items() if k not in ("__rowid", "40800")}
            payload["body_sha256"] = hashlib.sha256(blob).hexdigest()
            # Only decode individual returned records, never every statistics row.
            r = {**payload, "__rowid": r["__rowid"], "_body": blob}
            system = code == 10
        sent = (1, 2) if self.kind == "qq_import" else (1,)
        direction = "system" if system else "sent" if flag in sent else "received" if flag == 0 else "unknown"
        return {"record_ref": reference, "original_id": str(original), "timestamp_raw": timestamp,
                "direction": direction, "talker": str(talker or ""), "event_type": str(code),
                "event_source": "QQ" if self.kind in ("qq_import", "qq_legacy") else "WECHAT",
                "time_basis": "message", "content": content, "raw": r,
                "dedup_key": [table, str(talker or ""), *stable_id], "payload": payload}

    def present(self, record):
        body = record["content"]
        if self.kind == "qq_import":
            from .qq_import_service import decode_message_body
            try:
                body = decode_message_body(record["raw"].get("_body", b"")).get("content_display", "")
            except (ValueError, TypeError, KeyError):
                body = "消息正文无法解码，保留原始记录定位及内容哈希。"
        return _json_safe({k: v for k, v in {
            **record, "content": str(body)[:8000], "content_truncated": len(str(body)) > 8000,
            "raw_fields": {k: v for k, v in record["raw"].items()
                           if k not in ("_body", "content", "description", "__rowid")},
            "record_sha256": digest(record["payload"]),
        }.items() if k not in ("raw", "payload", "dedup_key")})
