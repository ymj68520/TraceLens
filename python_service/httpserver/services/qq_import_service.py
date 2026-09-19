"""QQ forensics (QQ 取证) import service.

Parallel to ``wechat_import_service.py``: imports an Android QQ (NTQQ)
account directory, decrypts the SQLCipher ``nt_db`` databases offline, and
builds:

- plaintext ``nt_msg.db`` (+ ``profile_info.db`` / ``group_info.db`` for
  human-readable names) kept inside the import directory, and
- a normalized ``graph.db`` carrying the same ``wechat_messages`` /
  ``wechat_contacts`` / ``wechat_chatrooms`` / ``wechat_owner_info`` tables
  the existing relationship-analysis pipeline consumes, so QQ datasets plug
  into ``/api/wechat/graph`` via a ``qq_<import_id>`` task id.

Storage layout::

    build/data/qq_imports/<import_id>/
        meta.json
        source/          original encrypted files
        nt_msg.db        decrypted chat database
        profile_info.db  decrypted contacts (optional)
        group_info.db    decrypted groups (optional)
        graph.db         normalized analysis database
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import get_data_root, get_project_root, get_settings
from . import qq_decrypt

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)

# QQ NT message segment content types (inner 45002)
QQ_CONTENT_LABELS = {
    1: "文本",
    2: "图片",
    3: "文件",
    4: "语音",
    5: "视频",
    6: "表情",
    7: "引用回复",
    8: "系统通知",
    9: "红包",
    10: "卡片",
    11: "商城表情",
    12: "位置",
}

# outer 40011 fallback labels
QQ_OUTER_LABELS = {
    2: "文本",
    9: "卡片/红包",
    10: "灰条通知",
}


# ---------------------------------------------------------------------- #
# storage helpers (mirror the wechat import layout)
# ---------------------------------------------------------------------- #

def import_root() -> str:
    root = get_data_root() / "qq_imports"
    root.mkdir(parents=True, exist_ok=True)
    return str(root)


def _import_dir(import_id: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{12}", import_id):
        raise ValueError(f"invalid import id: {import_id}")
    return os.path.join(import_root(), import_id)


def _meta_path(import_id: str) -> str:
    return os.path.join(_import_dir(import_id), "meta.json")


def _read_meta(import_id: str) -> Dict[str, Any]:
    path = _meta_path(import_id)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"import not found: {import_id}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_meta(import_id: str, meta: Dict[str, Any]) -> None:
    with open(_meta_path(import_id), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def list_imports() -> List[Dict[str, Any]]:
    result = []
    root = import_root()
    for entry in sorted(os.listdir(root), reverse=True):
        path = os.path.join(root, entry, "meta.json")
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    result.append(_meta_summary(json.load(f)))
            except (json.JSONDecodeError, OSError):
                continue
    return result


def _count_rows(db_path: str, table: str) -> Optional[int]:
    """Row count of ``table``; None when the file or the table is unusable."""
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        finally:
            con.close()
    except sqlite3.Error:
        return None


def _table_names(db_path: str) -> set:
    """Table names in a SQLite file; empty set when unreadable."""
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            return {
                row[0]
                for row in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        finally:
            con.close()
    except sqlite3.Error:
        return set()


def _meta_summary(meta: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "import_id": meta.get("import_id", ""),
        "name": meta.get("name", ""),
        "status": meta.get("status", ""),
        "error": meta.get("error"),
        "created_at": meta.get("created_at"),
        "backup_source": meta.get("backup_source", ""),
        "key_material": meta.get("key_material") or {},
        "decryption": meta.get("decryption") or {},
        "owner": meta.get("owner") or {},
        "stats": meta.get("stats") or {},
    }


# ---------------------------------------------------------------------- #
# protobuf (wire-format) decoding
# ---------------------------------------------------------------------- #

def _pb_fields(data: bytes) -> List[tuple]:
    """Minimal protobuf wire decoder: [(field, wire_type, value), ...]."""
    out: List[tuple] = []
    pos, end = 0, len(data)
    while pos < end:
        key, shift = 0, 0
        while pos < end:
            b = data[pos]
            pos += 1
            key |= (b & 0x7F) << shift
            shift += 7
            if not b & 0x80:
                break
        else:
            break
        field, wire = key >> 3, key & 7
        if wire == 0:
            v, shift = 0, 0
            while pos < end:
                b = data[pos]
                pos += 1
                v |= (b & 0x7F) << shift
                shift += 7
                if not b & 0x80:
                    break
            out.append((field, wire, v))
        elif wire == 2:
            ln, shift = 0, 0
            while pos < end:
                b = data[pos]
                pos += 1
                ln |= (b & 0x7F) << shift
                shift += 7
                if not b & 0x80:
                    break
            if pos + ln > end:
                break
            out.append((field, wire, data[pos : pos + ln]))
            pos += ln
        elif wire == 1:
            pos += 8
        elif wire == 5:
            pos += 4
        else:
            break
    return out


def decode_message_body(blob: bytes) -> Dict[str, Any]:
    """Decode the 40800 MsgBody blob into readable content.

    Returns ``{"content_type", "content_display", "media"}`` where media is
    ``{"kind": ...}`` for non-text segments.
    """
    if not blob:
        return {"content_type": 0, "content_display": "", "media": None}
    try:
        top = _pb_fields(blob)
        segments: List[bytes] = []
        for field, wire, value in top:
            if field == 40800 and wire == 2:
                segments.append(value)
        if not segments:
            # tolerate rows without the canonical wrapper
            segments = [blob]
        texts: List[str] = []
        content_type = 0
        media_kind: Optional[str] = None
        for seg in segments:
            seg_type = 0
            seg_media = 0
            seg_text = ""
            try:
                for field, wire, value in _pb_fields(seg):
                    if field == 45002 and wire == 0:
                        seg_type = value
                    elif field == 45003 and wire == 0:
                        seg_media = value
                    elif field == 45101 and wire == 2:
                        seg_text = value.decode("utf-8", "replace")
            except Exception:
                continue
            content_type = content_type or seg_type
            if seg_text:
                texts.append(seg_text)
            if seg_type == 2:
                media_kind = "image"
            elif seg_type == 5 or seg_media == 7:
                media_kind = "video"
            elif seg_type == 4 or seg_media == 2:
                media_kind = "voice"
            elif seg_type == 3 or seg_media == 11:
                media_kind = "file"
        display = "\n".join(t.strip() for t in texts if t.strip())
        if not display:
            display = QQ_CONTENT_LABELS.get(content_type, "非文本消息")
        media = {"kind": media_kind} if media_kind else None
        return {"content_type": content_type, "content_display": display, "media": media}
    except Exception as e:
        logger.debug("qq message body decode failed: %s", e)
        return {"content_type": 0, "content_display": "(无法解析)", "media": None}


# ---------------------------------------------------------------------- #
# the service
# ---------------------------------------------------------------------- #

class QQImportService:
    """Import + query pipeline for QQ NT account databases."""

    async def create_import(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await asyncio.to_thread(self._create_import_sync, payload)

    def _create_import_sync(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        db_path = (payload.get("db_path") or "").strip()
        if not db_path or not os.path.isfile(db_path):
            raise FileNotFoundError(f"database file not found: {db_path or '(none)'}")

        nt_dir = os.path.dirname(db_path)
        key = (payload.get("password") or payload.get("key") or "").strip()
        key_material = payload.get("key_material") or {}
        nt_uid = (key_material.get("nt_uid") or "").strip()
        uin = str(key_material.get("uin") or "").strip()

        import_id = uuid.uuid4().hex[:12]
        wdir = _import_dir(import_id)
        os.makedirs(os.path.join(wdir, "source"), exist_ok=True)

        meta: Dict[str, Any] = {
            "import_id": import_id,
            "name": payload.get("name") or os.path.basename(nt_dir),
            "status": "importing",
            "created_at": int(time.time() * 1000),
            "backup_source": payload.get("backup_source", ""),
            "key_material": {"nt_uid": nt_uid, "uin": uin},
            "decryption": {},
            "owner": {},
            "stats": {},
        }

        # 1. preserve originals (main db + companion dbs + WALs)
        companions = ["nt_msg.db", "profile_info.db", "group_info.db"]
        targets = {}
        for base in companions:
            src = db_path if base == "nt_msg.db" else os.path.join(nt_dir, base)
            if os.path.isfile(src):
                dst = os.path.join(wdir, "source", base)
                shutil.copy2(src, dst)
                targets[base] = src
                wal = src + "-wal"
                if os.path.isfile(wal):
                    shutil.copy2(wal, os.path.join(wdir, "source", base + "-wal"))

        # 2. resolve the key
        head = open(db_path, "rb").read(qq_decrypt.HEADER_SIZE)
        encrypted = qq_decrypt.looks_encrypted(head)
        header = qq_decrypt.parse_header(head) if encrypted else {}
        rand = header.get("rand", "") if encrypted else ""
        formula = ""
        if encrypted:
            if not key:
                if not nt_uid:
                    meta["status"] = "failed"
                    meta["error"] = "缺少密钥: 请提供 key 或 nt_uid 用于推导"
                    _write_meta(import_id, meta)
                    return _meta_summary(meta)
                if not rand:
                    meta["status"] = "failed"
                    meta["error"] = "数据库头部缺少 rand, 无法离线推导密钥"
                    _write_meta(import_id, meta)
                    return _meta_summary(meta)
                key = qq_decrypt.derive_key(nt_uid, rand)
                formula = "key = md5(md5(nt_uid) + rand)"
            if not qq_decrypt.verify_key(db_path, key):
                meta["status"] = "failed"
                meta["error"] = "密钥验证失败: 无法解密 nt_msg.db"
                _write_meta(import_id, meta)
                return _meta_summary(meta)
        else:
            # plaintext import still records header info if any
            formula = "plaintext (no key needed)"

        meta["key_material"]["rand"] = rand
        meta["key_material"]["key"] = key if encrypted else ""

        # 3. decrypt each companion database
        decrypted: Dict[str, str] = {}
        try:
            for base, src in targets.items():
                out_db = os.path.join(wdir, base)
                if encrypted:
                    stats = qq_decrypt.decrypt_file(src, out_db, key)
                    if base == "nt_msg.db":
                        meta["decryption"] = {
                            "scheme": "SQLCipher4",
                            "params": {
                                "cipher_page_size": 4096,
                                "kdf_iter": 4000,
                                "cipher_hmac_algorithm": "HMAC_SHA1",
                                "cipher_kdf_algorithm": "PBKDF2_HMAC_SHA512",
                            },
                            "header": stats.get("header"),
                            "wal": stats.get("wal"),
                            "formula": formula,
                        }
                else:
                    shutil.copy2(src, out_db)
                decrypted[base] = out_db
        except qq_decrypt.QQDecryptError as e:
            meta["status"] = "failed"
            meta["error"] = f"decryption failed: {e}"
            _write_meta(import_id, meta)
            return _meta_summary(meta)

        msg_db = decrypted.get("nt_msg.db")
        verify = qq_decrypt.verify_db(msg_db)
        meta["decryption"]["integrity"] = verify.get("integrity")
        if verify.get("integrity") != "ok":
            meta["status"] = "failed"
            meta["error"] = f"integrity check failed: {verify.get('integrity')}"
            _write_meta(import_id, meta)
            return _meta_summary(meta)

        # 4. owner / stats / name maps
        try:
            self._enrich_meta(import_id, decrypted, meta, key_material)
        except sqlite3.Error as e:
            meta["status"] = "failed"
            meta["error"] = f"database parse failed: {e}"
            _write_meta(import_id, meta)
            return _meta_summary(meta)

        # 5. normalized graph.db for the relationship-analysis pipeline
        try:
            self._build_graph_db(import_id, decrypted, os.path.join(wdir, "graph.db"), meta)
        except sqlite3.Error as e:
            logger.warning("qq graph.db build failed for %s: %s", import_id, e)

        meta["status"] = "ready"
        _write_meta(import_id, meta)
        return _meta_summary(meta)

    # ------------------------------------------------------------------ #
    # import sub-steps
    # ------------------------------------------------------------------ #

    def _name_maps(self, decrypted: Dict[str, str]) -> Dict[str, Dict[str, str]]:
        """Build uid->name and uin->name lookups from profile/buddy dbs."""
        uid_names: Dict[str, str] = {}
        uin_names: Dict[str, str] = {}
        uid_to_uin: Dict[str, str] = {}
        profile_db = decrypted.get("profile_info.db")
        if profile_db and os.path.isfile(profile_db):
            con = sqlite3.connect(profile_db)
            try:
                cols = {r[1] for r in con.execute("PRAGMA table_info(profile_info_v6)")}
                if {"1000", "1002", "20002"} <= cols:
                    for uid, uin, nick in con.execute(
                        'SELECT "1000", "1002", "20002" FROM profile_info_v6'
                    ):
                        if uid:
                            uid_to_uin[str(uid)] = str(uin or "")
                        if nick:
                            if uid:
                                uid_names[str(uid)] = nick
                            if uin:
                                uin_names[str(uin)] = nick
            except sqlite3.Error:
                pass
            finally:
                con.close()
        msg_db = decrypted.get("nt_msg.db")
        if msg_db and os.path.isfile(msg_db):
            con = sqlite3.connect(msg_db)
            try:
                for uid, uin in con.execute(
                    'SELECT "40021", "40004" FROM nt_uid_mapping_table'
                ):
                    if uid:
                        uid_to_uin[str(uid)] = str(uin or "")
            except sqlite3.Error:
                pass
            finally:
                con.close()
        return {"uid_names": uid_names, "uin_names": uin_names, "uid_to_uin": uid_to_uin}

    def _enrich_meta(
        self,
        import_id: str,
        decrypted: Dict[str, str],
        meta: Dict[str, Any],
        key_material: Dict[str, str],
    ) -> None:
        msg_db = decrypted["nt_msg.db"]
        maps = self._name_maps(decrypted)
        con = sqlite3.connect(msg_db)
        try:
            c2c = self._count(con, "c2c_msg_table")
            group = self._count(con, "group_msg_table")
            # owner identity: sent messages carry the owner's own uin/uid
            owner_uin, owner_uid, owner_nick = "", "", ""
            row = con.execute(
                'SELECT "40033", "40020", "40093", "40090" FROM c2c_msg_table '
                'WHERE "40013" IN (1,2) AND ("40033" IS NOT NULL AND "40033" != 0) LIMIT 1'
            ).fetchone()
            if row:
                owner_uin, owner_uid = str(row[0] or ""), str(row[1] or "")
                owner_nick = (row[3] or row[2] or "")
            if not owner_uin:
                row = con.execute(
                    'SELECT "40033", "40020", "40093", "40090" FROM group_msg_table '
                    'WHERE "40013" IN (1,2) AND ("40033" IS NOT NULL AND "40033" != 0) LIMIT 1'
                ).fetchone()
                if row:
                    owner_uin, owner_uid = str(row[0] or ""), str(row[1] or "")
                    owner_nick = (row[3] or row[2] or "")
            # fallback: mapping table uin<->uid
            if not owner_uid and maps["uid_to_uin"]:
                for uid, uin in maps["uid_to_uin"].items():
                    if uin == owner_uin:
                        owner_uid = uid
                        break
            if not owner_uin:
                owner_uin = str(key_material.get("uin") or "")
            if not owner_nick:
                owner_nick = maps["uin_names"].get(owner_uin, "")
            meta["owner"] = {
                "username": owner_uin,
                "nickname": owner_nick,
                "nt_uid": owner_uid or key_material.get("nt_uid", ""),
                "uin": int(owner_uin) if owner_uin.isdigit() else None,
            }

            first_ts = last_ts = None
            for table in ("c2c_msg_table", "group_msg_table"):
                r = con.execute(f'SELECT MIN("40050"), MAX("40050") FROM {table}').fetchone()
                if r and r[0]:
                    first_ts = r[0] if first_ts is None else min(first_ts, r[0])
                    last_ts = r[1] if last_ts is None else max(last_ts or 0, r[1])
            meta["stats"] = {
                "c2c_messages": c2c,
                "group_messages": group,
                "total_messages": c2c + group,
                "contacts": len(self._buddy_uins(decrypted)),
                "groups": self._count_groups(decrypted),
                "first_ts_ms": first_ts * 1000 if first_ts else None,
                "last_ts_ms": last_ts * 1000 if last_ts else None,
            }
        finally:
            con.close()

    @staticmethod
    def _count(con: sqlite3.Connection, table: str) -> int:
        try:
            return con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        except sqlite3.Error:
            return 0

    @staticmethod
    def _buddy_uins(decrypted: Dict[str, str]) -> Dict[str, str]:
        """uid->uin pairs from buddy_list/profile dbs."""
        buddies: Dict[str, str] = {}
        profile_db = decrypted.get("profile_info.db")
        if profile_db and os.path.isfile(profile_db):
            con = sqlite3.connect(profile_db)
            try:
                cols = {r[1] for r in con.execute("PRAGMA table_info(buddy_list)")}
                if {"1000", "1002"} <= cols:
                    for uid, uin in con.execute('SELECT "1000", "1002" FROM buddy_list'):
                        if uid:
                            buddies[str(uid)] = str(uin or "")
            except sqlite3.Error:
                pass
            finally:
                con.close()
        return buddies

    @staticmethod
    def _count_groups(decrypted: Dict[str, str]) -> int:
        group_db = decrypted.get("group_info.db")
        if not group_db or not os.path.isfile(group_db):
            return 0
        con = sqlite3.connect(group_db)
        try:
            cols = {r[1] for r in con.execute("PRAGMA table_info(group_list)")}
            if "60001" in cols:
                return con.execute('SELECT COUNT(*) FROM group_list').fetchone()[0]
        except sqlite3.Error:
            pass
        finally:
            con.close()
        return 0

    # ------------------------------------------------------------------ #
    # graph.db (normalized wechat_* schema consumed by the graph service)
    # ------------------------------------------------------------------ #

    def _build_graph_db(
        self,
        import_id: str,
        decrypted: Dict[str, str],
        graph_db: str,
        meta: Dict[str, Any],
    ) -> None:
        """Build the normalized graph.db.

        The file is assembled under a temp name and moved into place only on
        success: a failed build must never leave an empty graph.db behind,
        or the graph routes would serve a silent zero-node graph.
        """
        nt_db = decrypted.get("nt_msg.db")
        if not nt_db or not os.path.isfile(nt_db):
            raise sqlite3.OperationalError("decrypted nt_msg.db is missing")
        if not {"c2c_msg_table", "group_msg_table"} & _table_names(nt_db):
            raise sqlite3.OperationalError(
                "nt_msg.db missing required message tables "
                "(c2c_msg_table/group_msg_table)"
            )
        tmp_db = f"{graph_db}.{uuid.uuid4().hex}.building"
        owner = meta.get("owner") or {}
        owner_uin = owner.get("username", "")
        maps = self._name_maps(decrypted)
        uid_names, uin_names, uid_to_uin = (
            maps["uid_names"], maps["uin_names"], maps["uid_to_uin"],
        )

        def canon_uid(uid: str) -> str:
            """Map an NT uid to its QQ number when known."""
            return uid_to_uin.get(str(uid)) or str(uid)

        def display(uin: str, uid: str = "") -> str:
            return (
                uin_names.get(str(uin))
                or uid_names.get(str(uid))
                or str(uin or uid or "")
            )

        dst = sqlite3.connect(tmp_db)
        try:
            dst.executescript(
                """
                CREATE TABLE wechat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender TEXT, receiver TEXT, content TEXT,
                    timestamp INTEGER, media_url TEXT, media_type TEXT,
                    msg_type INTEGER DEFAULT 1, is_send INTEGER DEFAULT 0,
                    chatroom_name TEXT, sender_nickname TEXT, talker TEXT
                );
                CREATE TABLE wechat_contacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE, nickname TEXT, remark TEXT,
                    avatar_path TEXT, type INTEGER, chatroom_flag INTEGER DEFAULT 0
                );
                CREATE TABLE wechat_chatrooms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chatroom_name TEXT UNIQUE, owner TEXT, member_list TEXT,
                    member_count INTEGER, create_time INTEGER
                );
                CREATE TABLE wechat_owner_info (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE, nickname TEXT, uin INTEGER, imei TEXT
                );
                """
            )
            dst.execute(
                "INSERT OR REPLACE INTO wechat_owner_info (username, nickname, uin, imei) "
                "VALUES (?,?,?,?)",
                (
                    owner_uin,
                    owner.get("nickname", ""),
                    owner.get("uin"),
                    "",
                ),
            )

            # contacts: everyone actually seen in messages + buddy list;
            # profile_info_v6 caches thousands of unrelated profiles, so the
            # full uid map must not seed the graph.
            seen: Dict[str, str] = {}
            for uid, uin in self._buddy_uins(decrypted).items():
                if uin:
                    seen.setdefault(uin, uid)
            con = sqlite3.connect(decrypted["nt_msg.db"])
            try:
                for table, peer_col, uid_col in (
                    ("c2c_msg_table", "40030", "40021"),
                    ("group_msg_table", "40033", "40020"),
                ):
                    try:
                        for uin, uid in con.execute(
                            f'SELECT DISTINCT "{peer_col}", "{uid_col}" FROM {table} '
                            f'WHERE "{peer_col}" IS NOT NULL AND "{peer_col}" != 0'
                        ):
                            seen.setdefault(str(uin), str(uid or ""))
                    except sqlite3.Error:
                        continue
            finally:
                con.close()
            for uin, uid in seen.items():
                if uin == owner_uin:
                    continue
                dst.execute(
                    "INSERT OR IGNORE INTO wechat_contacts "
                    "(username, nickname, remark, avatar_path, type, chatroom_flag) "
                    "VALUES (?,?,?,?,?,?)",
                    (uin, display(uin, uid), "", "", 0, 0),
                )

            # chatrooms from group_info.db
            group_names: Dict[str, str] = {}
            group_db = decrypted.get("group_info.db")
            if group_db and os.path.isfile(group_db):
                gcon = sqlite3.connect(group_db)
                try:
                    cols = {r[1] for r in gcon.execute("PRAGMA table_info(group_list)")}
                    if {"60001", "60007"} <= cols:
                        member_col = '"60011"' if "60011" in cols else "0"
                        for gid, gname, members in gcon.execute(
                            f'SELECT "60001", "60007", {member_col} FROM group_list'
                        ):
                            gid = str(gid)
                            group_names[gid] = gname or gid
                            dst.execute(
                                "INSERT OR IGNORE INTO wechat_chatrooms "
                                "(chatroom_name, owner, member_list, member_count, create_time) "
                                "VALUES (?,?,?,?,?)",
                                (gid, "", gname or "", int(members or 0), 0),
                            )
                except sqlite3.Error:
                    pass
                finally:
                    gcon.close()

            # messages
            con = sqlite3.connect(decrypted["nt_msg.db"])
            try:
                rows = con.execute(
                    'SELECT "40001", "40033", "40020", "40030", "40050", "40011", '
                    '"40013", "40093", "40090", "40800" FROM c2c_msg_table '
                    'WHERE "40050" IS NOT NULL AND "40050" > 0'
                )
                for mid, sender_uin, sender_uid, peer_uin, ts, outer, direction, nick, card, blob in rows:
                    body = decode_message_body(blob)
                    is_send = 1 if direction in (1, 2) else 0
                    if is_send:
                        sender, receiver = owner_uin, str(peer_uin or "")
                    else:
                        sender, receiver = str(peer_uin or ""), owner_uin
                    media = body.get("media") or {}
                    dst.execute(
                        "INSERT INTO wechat_messages (sender, receiver, content, timestamp, "
                        "media_url, media_type, msg_type, is_send, chatroom_name, "
                        "sender_nickname, talker) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            sender,
                            receiver,
                            body["content_display"],
                            int(ts) * 1000,
                            None,
                            media.get("kind"),
                            int(outer or 2),
                            is_send,
                            None,
                            display(sender, sender_uid or "") if sender != owner_uin
                            else owner.get("nickname", ""),
                            str(peer_uin or ""),
                        ),
                    )
                rows = con.execute(
                    'SELECT "40001", "40033", "40020", "40030", "40050", "40011", '
                    '"40013", "40093", "40090", "40800" FROM group_msg_table '
                    'WHERE "40050" IS NOT NULL AND "40050" > 0'
                )
                for mid, sender_uin, sender_uid, group_uin, ts, outer, direction, nick, card, blob in rows:
                    body = decode_message_body(blob)
                    is_send = 1 if direction in (1, 2) else 0
                    sender = owner_uin if is_send else str(sender_uin or "")
                    chatroom = str(group_uin or "")
                    sender_name = (
                        owner.get("nickname", "")
                        if is_send
                        else (card or nick or display(sender, sender_uid or ""))
                    )
                    media = body.get("media") or {}
                    dst.execute(
                        "INSERT INTO wechat_messages (sender, receiver, content, timestamp, "
                        "media_url, media_type, msg_type, is_send, chatroom_name, "
                        "sender_nickname, talker) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            sender,
                            chatroom,
                            body["content_display"],
                            int(ts) * 1000,
                            None,
                            media.get("kind"),
                            int(outer or 2),
                            is_send,
                            chatroom,
                            sender_name,
                            chatroom,
                        ),
                    )
                dst.commit()
            finally:
                con.close()
        except BaseException:
            dst.close()
            try:
                os.remove(tmp_db)
            except OSError:
                pass
            raise
        dst.close()
        os.replace(tmp_db, graph_db)

    # ------------------------------------------------------------------ #
    # connections & lookups
    # ------------------------------------------------------------------ #

    def _connect(self, import_id: str) -> sqlite3.Connection:
        path = os.path.join(_import_dir(import_id), "nt_msg.db")
        if not os.path.isfile(path):
            raise FileNotFoundError(f"decrypted database not found for {import_id}")
        con = sqlite3.connect(path)
        con.row_factory = sqlite3.Row
        return con

    def _graph_db_path(self, import_id: str) -> str:
        path = os.path.join(_import_dir(import_id), "graph.db")
        if not re.fullmatch(r"[0-9a-f]{12}", import_id):
            raise ValueError("invalid import id")
        return path

    def ensure_graph_db(self, import_id: str) -> str:
        """Return graph.db for the import, rebuilding it when absent or empty.

        Same self-heal as the WeChat pipeline: a leftover empty graph.db made
        the relationship tab answer zero nodes even though messages existed.
        """
        path = self._graph_db_path(import_id)
        wdir = _import_dir(import_id)
        nt_db = os.path.join(wdir, "nt_msg.db")
        if os.path.exists(path) and not self._graph_db_stale(path, nt_db):
            return path
        decrypted = {
            base: os.path.join(wdir, base)
            for base in ("nt_msg.db", "profile_info.db", "group_info.db")
            if os.path.isfile(os.path.join(wdir, base))
        }
        if "nt_msg.db" not in decrypted:
            return path
        try:
            self._build_graph_db(import_id, decrypted, path, _read_meta(import_id))
            logger.info("qq graph.db rebuilt for import %s", import_id)
        except Exception as e:
            logger.warning("qq graph.db rebuild failed for %s: %s", import_id, e)
        return path

    @staticmethod
    def _graph_db_stale(graph_db: str, nt_db: str) -> bool:
        """True when graph.db exists but carries no messages while nt_msg.db does."""
        if _count_rows(graph_db, "wechat_messages"):
            return False
        have = _table_names(nt_db)
        return any(
            _count_rows(nt_db, table) for table in ("c2c_msg_table", "group_msg_table")
            if table in have
        )

    # ------------------------------------------------------------------ #
    # queries (mirrors the WeChat forensics endpoints)
    # ------------------------------------------------------------------ #

    async def get_meta(self, import_id: str) -> Dict[str, Any]:
        return _meta_summary(_read_meta(import_id))

    async def delete_import(self, import_id: str) -> bool:
        def _delete():
            wdir = _import_dir(import_id)
            if os.path.isdir(wdir):
                shutil.rmtree(wdir)
                return True
            return False

        return await asyncio.to_thread(_delete)

    async def overview(self, import_id: str) -> Dict[str, Any]:
        return await asyncio.to_thread(self._overview_sync, import_id)

    def _overview_sync(self, import_id: str) -> Dict[str, Any]:
        meta = _read_meta(import_id)
        con = self._connect(import_id)
        try:
            type_stats = []
            for r in con.execute(
                'SELECT "40011", COUNT(*) FROM group_msg_table GROUP BY "40011" '
                'UNION ALL SELECT "40011", COUNT(*) FROM c2c_msg_table GROUP BY "40011"'
            ):
                merged = next(
                    (t for t in type_stats if t["base_type"] == r[0]), None
                )
                if merged:
                    merged["count"] += r[1]
                else:
                    type_stats.append({
                        "base_type": r[0],
                        "count": r[1],
                        "label": QQ_OUTER_LABELS.get(r[0], f"类型{r[0]}"),
                    })
            type_stats.sort(key=lambda t: -t["count"])

            day_stats = [
                {"date": r[0], "count": r[1]}
                for r in con.execute(
                    'SELECT date("40050", \'unixepoch\', \'+8 hours\') d, COUNT(*) FROM ('
                    'SELECT "40050" FROM c2c_msg_table UNION ALL '
                    'SELECT "40050" FROM group_msg_table) GROUP BY d ORDER BY d'
                )
            ]

            sessions = self._sessions_sync(import_id, con)
            return {
                "meta": _meta_summary(meta),
                "owner": meta.get("owner") or {},
                "key_material": _safe_key_material(meta),
                "decryption": meta.get("decryption") or {},
                "stats": meta.get("stats") or {},
                "type_stats": type_stats,
                "day_stats": day_stats,
                "top_sessions": sorted(
                    sessions, key=lambda s: -s["msg_count"]
                )[:8],
            }
        finally:
            con.close()

    async def sessions(self, import_id: str) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(self._sessions_sync, import_id)

    def _sessions_sync(
        self, import_id: str, con: Optional[sqlite3.Connection] = None
    ) -> List[Dict[str, Any]]:
        own_con = con is None
        if own_con:
            con = self._connect(import_id)
        meta = _read_meta(import_id)
        try:
            group_names = self._group_names(import_id)
            uid_names = self._uid_display_names(import_id)
            result: List[Dict[str, Any]] = []
            # private chats: one session per peer uin
            for peer, count, first, last in con.execute(
                'SELECT "40030", COUNT(*), MIN("40050"), MAX("40050") '
                'FROM c2c_msg_table WHERE "40030" IS NOT NULL AND "40030" != 0 '
                'GROUP BY "40030" ORDER BY MAX("40050") DESC'
            ):
                talker = str(peer)
                result.append({
                    "talker": talker,
                    "kind": "private",
                    "display_name": uid_names.get(talker) or talker,
                    "msg_count": count,
                    "member_count": None,
                    "first_ts": first * 1000 if first else None,
                    "last_ts": last * 1000 if last else None,
                    "last_preview": self._last_preview(con, "c2c", talker),
                })
            # group chats: one session per group uin
            for group, count, first, last in con.execute(
                'SELECT "40030", COUNT(*), MIN("40050"), MAX("40050") '
                'FROM group_msg_table WHERE "40030" IS NOT NULL AND "40030" != 0 '
                'GROUP BY "40030" ORDER BY MAX("40050") DESC'
            ):
                talker = str(group)
                result.append({
                    "talker": talker,
                    "kind": "group",
                    "display_name": group_names.get(talker) or f"群 {talker}",
                    "msg_count": count,
                    "member_count": None,
                    "first_ts": first * 1000 if first else None,
                    "last_ts": last * 1000 if last else None,
                    "last_preview": self._last_preview(con, "group", talker),
                })
            result.sort(key=lambda s: -(s.get("last_ts") or 0))
            return result
        finally:
            if own_con:
                con.close()

    def _last_preview(self, con: sqlite3.Connection, kind: str, talker: str) -> str:
        table = "c2c_msg_table" if kind == "c2c" else "group_msg_table"
        row = con.execute(
            f'SELECT "40800" FROM {table} WHERE "40030" = ? '
            f'ORDER BY "40050" DESC LIMIT 1',
            (talker,),
        ).fetchone()
        if row and row[0]:
            return decode_message_body(row[0])["content_display"][:60]
        return ""

    def _group_names(self, import_id: str) -> Dict[str, str]:
        path = os.path.join(_import_dir(import_id), "group_info.db")
        names: Dict[str, str] = {}
        if not os.path.isfile(path):
            return names
        con = sqlite3.connect(path)
        try:
            cols = {r[1] for r in con.execute("PRAGMA table_info(group_list)")}
            if {"60001", "60007"} <= cols:
                for gid, gname in con.execute('SELECT "60001", "60007" FROM group_list'):
                    names[str(gid)] = gname or str(gid)
        except sqlite3.Error:
            pass
        finally:
            con.close()
        return names

    def _uid_display_names(self, import_id: str) -> Dict[str, str]:
        """uin -> display name from profile_info.db."""
        path = os.path.join(_import_dir(import_id), "profile_info.db")
        names: Dict[str, str] = {}
        if not os.path.isfile(path):
            return names
        con = sqlite3.connect(path)
        try:
            cols = {r[1] for r in con.execute("PRAGMA table_info(profile_info_v6)")}
            if {"1002", "20002"} <= cols:
                for uin, nick in con.execute('SELECT "1002", "20002" FROM profile_info_v6'):
                    if uin and nick:
                        names[str(uin)] = nick
        except sqlite3.Error:
            pass
        finally:
            con.close()
        return names

    async def messages(
        self,
        import_id: str,
        talker: Optional[str] = None,
        keyword: Optional[str] = None,
        msg_type: Optional[int] = None,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(
            self._messages_sync, import_id, talker, keyword, msg_type,
            start_ts, end_ts, limit, offset,
        )

    def _messages_sync(
        self,
        import_id: str,
        talker: Optional[str],
        keyword: Optional[str],
        msg_type: Optional[int],
        start_ts: Optional[int],
        end_ts: Optional[int],
        limit: int,
        offset: int,
    ) -> Dict[str, Any]:
        meta = _read_meta(import_id)
        owner = meta.get("owner") or {}
        owner_uin = owner.get("username", "")
        con = self._connect(import_id)
        try:
            group_names = self._group_names(import_id)
            uin_names = self._uid_display_names(import_id)

            def session_name(t: str, kind: str) -> str:
                if kind == "group":
                    return group_names.get(t) or f"群 {t}"
                return uin_names.get(t) or t

            messages: List[Dict[str, Any]] = []
            # fetch from both tables then merge by timestamp
            for kind, table in (("private", "c2c_msg_table"), ("group", "group_msg_table")):
                where = ['"40050" IS NOT NULL']
                params: List[Any] = []
                if talker:
                    where.append('"40030" = ?')
                    params.append(talker)
                if msg_type is not None:
                    where.append('"40011" = ?')
                    params.append(msg_type)
                if start_ts is not None:
                    where.append('"40050" >= ?')
                    params.append(start_ts // 1000)
                if end_ts is not None:
                    where.append('"40050" <= ?')
                    params.append(end_ts // 1000)
                clause = " AND ".join(where)
                rows = con.execute(
                    f'SELECT "40001", "40033", "40020", "40030", "40050", "40011", '
                    f'"40013", "40093", "40090", "40800" FROM {table} WHERE {clause} '
                    f'ORDER BY "40050" ASC',
                    params,
                ).fetchall()
                for mid, sender_uin, sender_uid, peer_uin, ts, outer, direction, nick, card, blob in rows:
                    body = decode_message_body(blob)
                    if keyword and keyword not in body["content_display"]:
                        continue
                    is_send = 1 if direction in (1, 2) else 0
                    peer = str(peer_uin or "")
                    if kind == "group":
                        sender = owner_uin if is_send else str(sender_uin or "")
                        sender_name = (
                            owner.get("nickname", "")
                            if is_send
                            else (card or nick or uin_names.get(sender, sender))
                        )
                        chatroom = peer
                    else:
                        if is_send:
                            sender, sender_name = owner_uin, owner.get("nickname", "")
                        else:
                            sender = peer
                            sender_name = uin_names.get(peer, peer)
                        chatroom = None
                    messages.append({
                        "id": mid,
                        "talker": peer,
                        "session_name": session_name(peer, kind),
                        "is_group": kind == "group",
                        "sender": sender,
                        "sender_name": sender_name or sender,
                        "is_owner_sender": bool(is_send),
                        "direction": "send" if is_send else "receive",
                        "type_code": outer,
                        "base_type": body.get("content_type") or 1,
                        "type_label": QQ_CONTENT_LABELS.get(
                            body.get("content_type"),
                            QQ_OUTER_LABELS.get(outer, f"类型{outer}"),
                        ),
                        "timestamp_ms": int(ts) * 1000 if ts else None,
                        "time_display": _fmt_ts(ts),
                        "content_display": body["content_display"],
                        "media": body.get("media"),
                        "chatroom_name": chatroom,
                    })
            messages.sort(key=lambda m: m["timestamp_ms"] or 0)
            total = len(messages)
            return {
                "messages": messages[offset : offset + limit],
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        finally:
            con.close()

    async def contacts(self, import_id: str) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(self._contacts_sync, import_id)

    def _contacts_sync(self, import_id: str) -> List[Dict[str, Any]]:
        uin_names = self._uid_display_names(import_id)
        con = self._connect(import_id)
        try:
            seen: Dict[str, int] = {}
            for uin, count in con.execute(
                'SELECT "40030", COUNT(*) FROM c2c_msg_table '
                'WHERE "40030" IS NOT NULL AND "40030" != 0 GROUP BY "40030"'
            ):
                seen[str(uin)] = count
            result = []
            for uin in sorted(seen, key=lambda u: -seen[u]):
                result.append({
                    "username": uin,
                    "nickname": uin_names.get(uin, uin),
                    "remark": "",
                    "msg_count": seen[uin],
                    "kind": "buddy",
                })
            # buddies without messages
            for uin, nick in uin_names.items():
                if uin not in seen:
                    result.append({
                        "username": uin,
                        "nickname": nick,
                        "remark": "",
                        "msg_count": 0,
                        "kind": "buddy",
                    })
            return result
        finally:
            con.close()

    async def chatrooms(self, import_id: str) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(self._chatrooms_sync, import_id)

    def _chatrooms_sync(self, import_id: str) -> List[Dict[str, Any]]:
        con = self._connect(import_id)
        group_names = self._group_names(import_id)
        try:
            result = []
            for group, count, last in con.execute(
                'SELECT "40030", COUNT(*), MAX("40050") FROM group_msg_table '
                'WHERE "40030" IS NOT NULL AND "40030" != 0 '
                'GROUP BY "40030" ORDER BY COUNT(*) DESC'
            ):
                gid = str(group)
                senders = [
                    r[0]
                    for r in con.execute(
                        'SELECT "40093" FROM group_msg_table WHERE "40030" = ? '
                        'AND "40093" IS NOT NULL AND "40093" != "" LIMIT 12',
                        (gid,),
                    )
                ]
                result.append({
                    "chatroom_name": gid,
                    "display_name": group_names.get(gid) or f"群 {gid}",
                    "member_count": None,
                    "msg_count": count,
                    "last_ts": last * 1000 if last else None,
                    "members_preview": list(dict.fromkeys(senders)),
                })
            return result
        finally:
            con.close()


def _safe_key_material(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Key material for display: mask the derived key itself."""
    km = dict(meta.get("key_material") or {})
    if km.get("key"):
        km["key"] = km["key"][:8] + "…"
    return km


def _fmt_ts(ts: Optional[int]) -> str:
    if not ts:
        return ""
    try:
        import datetime

        return datetime.datetime.fromtimestamp(
            int(ts), datetime.timezone(datetime.timedelta(hours=8))
        ).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return ""


_service: Optional[QQImportService] = None


def get_qq_import_service() -> QQImportService:
    global _service
    if _service is None:
        _service = QQImportService()
    return _service
