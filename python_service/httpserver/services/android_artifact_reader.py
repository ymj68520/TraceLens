"""Task-scoped, read-only presentation of AndroidAnalyzer database rows.

The Investigation adapter uses this bounded reader against a task-owned frozen
result set. Existing artifact tables have no per-row original-source identity;
coverage/provenance can identify candidate input files, never prove an
original SQLite row or WAL frame.
"""

from __future__ import annotations

import sqlite3
import hashlib
import json
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

from .android_coverage import resolve_android_db

KINDS = {
    "sms": ("sms_messages", ("body", "address")),
    "contacts": ("contacts", ("display_name", "phone_number")),
    "apps": ("installed_packages", ("package_name", "version")),
    "wifi": ("wifi_networks", ("ssid", "key_mgmt")),
    "mobile": ("mobile_artifacts", ("kind", "package_name", "record_json")),
    # Communication evidence: the records a mobile-only case is about.
    "calls": ("call_logs", ("number", "name")),
    "im": ("wechat_messages", ("content", "sender", "receiver", "talker")),
    "im_contacts": ("wechat_contacts", ("username", "nickname", "remark", "mobile")),
}
SOURCE_KINDS = {"apps": "installed_apps"}


class ArtifactUnavailable(ValueError):
    pass


class ArtifactChanged(ArtifactUnavailable):
    pass


def raw_row_hash(row: dict) -> str:
    """Identity guard for one *derived* result row, including redacted fields."""
    encoded = json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def source_revision(task: dict) -> str:
    """Cheap optimistic token for android.db + WAL/journal, not a forensic hash."""
    path = resolve_android_db(task)
    if path is None:
        raise ArtifactUnavailable("task has no readable android.db")
    parts = []
    for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-journal")):
        if candidate.is_symlink():
            raise ArtifactUnavailable("source database bundle contains a symlink")
        if candidate.exists():
            stat = candidate.stat()
            parts.append((candidate.name, stat.st_dev, stat.st_ino, stat.st_size,
                          stat.st_mtime_ns, stat.st_ctime_ns))
    return hashlib.sha256(repr(parts).encode()).hexdigest()


def read_raw_row(database: Path, kind: str, row_id: int) -> dict:
    if row_id <= 0 or row_id > 2**63 - 1:
        raise ValueError("invalid artifact ID")
    with closing(sqlite3.connect(f"file:{quote(str(database.resolve()), safe='/')}?mode=ro", uri=True, timeout=10)) as con:
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only=ON")
        table, _ = _table(con, kind)
        row = con.execute(f'SELECT * FROM "{table}" WHERE id=?', (row_id,)).fetchone()
        if row is None:
            raise FileNotFoundError("Android artifact not found")
        return dict(row)


def _open(task: dict) -> sqlite3.Connection:
    path = resolve_android_db(task)
    if path is None:
        raise ArtifactUnavailable("task has no readable android.db")
    con = sqlite3.connect(f"file:{quote(str(path), safe='/')}?mode=ro", uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    return con


def _table(con: sqlite3.Connection, kind: str) -> tuple[str, tuple[str, ...]]:
    if kind not in KINDS:
        raise ArtifactUnavailable("unsupported Android artifact kind")
    table, search = KINDS[kind]
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is None:
        raise ArtifactUnavailable("artifact table is not present in this task")
    return table, search


def _safe_row(row: sqlite3.Row, kind: str) -> dict:
    value = dict(row)
    # A Wi-Fi credential is not needed for overview/search; never send it to a
    # browser while field admission/authentication is unverified.
    if kind == "wifi" and "pre_shared_key" in value:
        value["pre_shared_key"] = "[redacted]" if value["pre_shared_key"] else None
    return value


def list_artifacts(task: dict, kind: str, *, query: str = "", page: int = 1, page_size: int = 50) -> dict:
    if page < 1 or not 1 <= page_size <= 100 or len(query) > 200:
        raise ValueError("invalid pagination or query")
    with closing(_open(task)) as con:
        table, search = _table(con, kind)
        columns = {row[1] for row in con.execute(f'PRAGMA table_info("{table}")')}
        usable = [name for name in search if name in columns]
        where = " WHERE " + " OR ".join(f'"{name}" LIKE ? ESCAPE \'\\\'' for name in usable) if query and usable else ""
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        args = [f"%{escaped}%"] * len(usable) if where else []
        total = con.execute(f'SELECT COUNT(*) FROM "{table}"{where}', args).fetchone()[0]
        rows = con.execute(f'SELECT * FROM "{table}"{where} ORDER BY id LIMIT ? OFFSET ?',
                           (*args, page_size, (page - 1) * page_size)).fetchall()
        return {"task_id": task["id"], "source_type": "android_analyzer", "kind": kind,
                "total": total, "page": page, "page_size": page_size,
                "records": [_safe_row(row, kind) for row in rows]}


def artifact_detail(task: dict, kind: str, row_id: int) -> dict:
    path = resolve_android_db(task)
    if path is None:
        raise ArtifactUnavailable("task has no readable android.db")
    return artifact_detail_from_database(path, task["id"], kind, row_id, revision=source_revision(task))


def artifact_detail_from_database(database: Path, task_id: str, kind: str, row_id: int,
                                  *, revision: str | None = None) -> dict:
    if row_id <= 0 or row_id > 2**63 - 1:
        raise ValueError("invalid artifact ID")
    with closing(sqlite3.connect(f"file:{quote(str(database.resolve()), safe='/')}?mode=ro", uri=True, timeout=10)) as con:
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only=ON")
        table, _ = _table(con, kind)
        row = con.execute(f'SELECT * FROM "{table}" WHERE id=?', (row_id,)).fetchone()
        if row is None:
            raise FileNotFoundError("Android artifact not found in task")
        if kind == "mobile":
            value = dict(row)
            # Platform comes from the writing adapter's manifest row, not a
            # hardcoded vendor: the same mobile_artifacts table carries
            # HarmonyOS and OPPO (ThunderForensic) records.
            platform = "Android"
            manifest = con.execute("SELECT 1 FROM sqlite_master WHERE name='mobile_backup_manifest'").fetchone()
            if manifest:
                seen = con.execute("SELECT platform FROM mobile_backup_manifest LIMIT 1").fetchone()
                if seen and seen[0]:
                    platform = seen[0]
            source = {"platform": platform, "normalized_path": value["source_path"], "granularity": "logical_database_row",
                      "original_table": value["source_table"],
                      "original_primary_key": json.loads(value["source_key"]),
                      "sha256": value.get("source_db_sha256"), "wal_sha256": value.get("source_wal_sha256"),
                      "wal_frame": None, "verified_row_source": True,
                      "parser_version": value.get("parser_version"), "app_index": value.get("app_index")}
            if con.execute("SELECT 1 FROM sqlite_master WHERE name='android_source_provenance'").fetchone():
                original = con.execute("SELECT source_member_path,source_container,source_container_sha256 "
                                       "FROM android_source_provenance WHERE normalized_android_path=? LIMIT 2",
                                       (value["source_path"],)).fetchall()
                if len(original) == 1:
                    source.update(original_path=original[0][0], source_container=original[0][1],
                                  source_container_sha256=original[0][2])
            return {"task_id": task_id, "source_type": "android_analyzer", "kind": kind,
                    "record": value, "source": source, "source_candidates": [value["source_path"]],
                    "record_hash": raw_row_hash(value), "source_revision": revision,
                    "warning": f"来源为{platform}手机备份的解析记录；记录绑定源容器成员、表和行主键，未定位物理偏移或 WAL 帧；不代表完整手机。"}
        # Old parser tables do not carry per-row source paths/primary keys.
        # A unique coverage path is shown as a candidate only, never a proof.
        candidate_paths = []
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='android_source_coverage'").fetchone():
            candidate_paths = [item[0] for item in con.execute(
                "SELECT source_path FROM android_source_coverage WHERE artifact_kind=? "
                "AND status IN ('parsed','staged_for_parser') ORDER BY source_path",
                (SOURCE_KINDS.get(kind, kind),),
            )]
        source = None
        if len(candidate_paths) == 1:
            source = {"normalized_path": candidate_paths[0], "granularity": "candidate_file_not_row",
                      "original_table": None, "original_primary_key": None,
                      "wal_frame": None, "verified_row_source": False}
            for provenance_table, query in (
                ("android_filesystem_provenance", "SELECT filesystem_path AS original_path, file_sha256 AS sha256, "
                 "source_image_sha256, partition_name, partition_start_offset, filesystem_object_id "
                 "FROM android_filesystem_provenance WHERE normalized_android_path=? LIMIT 2"),
                ("android_source_provenance", "SELECT source_member_path AS original_path, member_sha256 AS sha256, "
                 "source_container_sha256 FROM android_source_provenance WHERE normalized_android_path=? LIMIT 2"),
            ):
                if con.execute("SELECT 1 FROM sqlite_master WHERE name=?", (provenance_table,)).fetchone():
                    matches = con.execute(query, (candidate_paths[0],)).fetchall()
                    if len(matches) == 1:
                        source.update(dict(matches[0]))
                        break
        return {"task_id": task_id, "source_type": "android_analyzer", "kind": kind,
                "record": _safe_row(row, kind), "source": source,
                "record_hash": raw_row_hash(dict(row)), "source_revision": revision,
                "source_candidates": candidate_paths,
                "warning": "旧解析器未保存逐条来源主键；候选文件不能证明该记录的原始数据库行或 WAL frame"}
