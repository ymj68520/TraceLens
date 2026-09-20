"""WeChat forensic import service.

Imports an Android WeChat account database (EnMicroMsg.db, encrypted or
already decrypted) into a self-contained forensic workspace, then exposes
human-readable queries (sessions / messages / contacts / chatrooms / search)
over the native WeChat schema (message, rcontact, chatroom, userinfo).

Design notes:
  - Every import lives under ``<project_root>/build/data/wechat_imports/<id>/``
    with ``meta.json`` (import manifest), ``source/`` (original files, kept
    untouched), the decrypted ``EnMicroMsg.db`` and copied media thumbnails.
  - The decrypted DB is never modified. A separate ``graph.db`` carries the
    normalized ``wechat_*`` tables consumed by the existing WeChat analysis
    (relationship graph) pipeline.
  - All display fields are resolved server-side (nicknames/remarks/chatroom
    names, message type labels, decoded message bodies) so the UI never has
    to show raw wxid/protobuf/XML blobs.
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import get_data_root, get_project_root, get_settings
from . import wechat_decrypt

logger = logging.getLogger(__name__)

# UTC+8 display for WeChat timestamps (device timezone in this dataset).
_CN_TZ = timezone(timedelta(hours=8))

SQLITE_MAGIC = b"SQLite format 3\x00"

IMPORT_ROOT_NAME = "wechat_imports"

# Well-known functional/system accounts that are not real persons.
_SYSTEM_ACCOUNTS = {
    "weixin", "filehelper", "newsapp", "fmessage", "tmessage", "qmessage",
    "qqmail", "floatbottle", "shakeapp", "lbsapp", "voip", "voipapp",
    "voiceinputapp", "voicevoipapp", "medianote", "qqsync", "masssendapp",
    "feedsapp", "weibo", "officialaccounts", "service_officialaccounts",
    "notifymessage", "downloaderapp", "appbrand_notify_message",
    "appbrandcustomerservicemsg", "opencustomerservicemsg", "linkedinplugin",
    "facebookapp", "qqfriend", "schedule_message", "BrandEcsTemplateMsg@fakeuser",
}

_MSG_TYPE_LABELS = {
    1: "文本", 3: "图片", 34: "语音", 42: "名片", 43: "视频", 47: "动画表情",
    48: "位置", 49: "分享/应用", 50: "语音通话", 10000: "系统消息", 10002: "撤回",
}

_APPMSG_SUBTYPE_LABELS = {
    1: "图文链接", 2: "图片", 3: "音乐", 4: "视频", 5: "链接", 6: "文件",
    7: "表情", 19: "聊天记录", 33: "小程序", 36: "小程序", 57: "引用回复",
    63: "视频号直播", 87: "群直播", 88: "视频号名片", 2000: "转账", 2001: "红包",
    2003: "红包封面",
}


# =============================================================================
# Paths / registry
# =============================================================================


def import_root() -> str:
    data_root = get_data_root()
    root = data_root / IMPORT_ROOT_NAME
    root.mkdir(parents=True, exist_ok=True)
    return str(root)


def _import_dir(import_id: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{12}", import_id or ""):
        raise ValueError("invalid import id")
    return os.path.join(import_root(), import_id)


def _meta_path(import_id: str) -> str:
    return os.path.join(_import_dir(import_id), "meta.json")


def _read_meta(import_id: str) -> Dict[str, Any]:
    with open(_meta_path(import_id), "r", encoding="utf-8") as f:
        return json.load(f)


def _write_meta(import_id: str, meta: Dict[str, Any]) -> None:
    meta["updated_at"] = int(time.time() * 1000)
    with open(_meta_path(import_id), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def list_imports() -> List[Dict[str, Any]]:
    items = []
    root = import_root()
    for entry in sorted(os.listdir(root)):
        meta_file = os.path.join(root, entry, "meta.json")
        if not os.path.isfile(meta_file):
            continue
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        items.append(_meta_summary(meta))
    items.sort(key=lambda m: m.get("created_at", 0), reverse=True)
    return items


def _meta_summary(meta: Dict[str, Any]) -> Dict[str, Any]:
    owner = meta.get("owner") or {}
    stats = meta.get("stats") or {}
    return {
        "import_id": meta.get("import_id"),
        "name": meta.get("name", ""),
        "status": meta.get("status"),
        "created_at": meta.get("created_at"),
        "owner_username": owner.get("username", ""),
        "owner_nickname": owner.get("nickname", ""),
        "uin": meta.get("key_material", {}).get("uin"),
        "message_count": stats.get("messages", 0),
        "contact_count": stats.get("contacts", 0),
        "chatroom_count": stats.get("chatrooms", 0),
        "decryption": meta.get("decryption", {}),
        "error": meta.get("error"),
    }


# =============================================================================
# Import pipeline
# =============================================================================


class WeChatImportService:
    """Import + query pipeline for WeChat account databases."""

    def __init__(self) -> None:
        # graph.db 自愈重建的并发防护（进程内一次）
        self._graph_locks: Dict[str, threading.Lock] = {}
        self._graph_healed: set = set()

    async def create_import(
        self,
        db_path: str,
        name: str = "",
        password: str = "",
        wal_path: Optional[str] = None,
        media_dir: Optional[str] = None,
        key_material: Optional[Dict[str, str]] = None,
        backup_source: str = "",
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(
            self._create_import_sync,
            db_path, name, password, wal_path, media_dir,
            key_material or {}, backup_source,
        )

    def _create_import_sync(
        self,
        db_path: str,
        name: str,
        password: str,
        wal_path: Optional[str],
        media_dir: Optional[str],
        key_material: Dict[str, str],
        backup_source: str,
    ) -> Dict[str, Any]:
        if not os.path.isfile(db_path):
            raise FileNotFoundError(f"database file not found: {db_path}")
        # auto-detect WAL companion when not given explicitly
        if not wal_path and os.path.isfile(db_path + "-wal"):
            wal_path = db_path + "-wal"

        import_id = uuid.uuid4().hex[:12]
        wdir = _import_dir(import_id)
        os.makedirs(os.path.join(wdir, "source"), exist_ok=True)

        meta: Dict[str, Any] = {
            "import_id": import_id,
            "name": name or os.path.basename(os.path.dirname(db_path)),
            "status": "importing",
            "created_at": int(time.time() * 1000),
            "backup_source": backup_source,
            "key_material": {
                "uin": key_material.get("uin", ""),
                "imei": key_material.get("imei", ""),
                "wxid": key_material.get("wxid", ""),
                "account_dir": key_material.get("account_dir", ""),
            },
            "decryption": {},
            "owner": {},
            "stats": {},
            "thumbs": [],
        }

        # 1. preserve originals
        src_copy = os.path.join(wdir, "source", os.path.basename(db_path))
        shutil.copy2(db_path, src_copy)
        wal_copy = None
        if wal_path and os.path.isfile(wal_path):
            wal_copy = os.path.join(wdir, "source", os.path.basename(db_path) + "-wal")
            shutil.copy2(wal_path, wal_copy)

        # 2. decrypt (or verify plaintext)
        out_db = os.path.join(wdir, "EnMicroMsg.db")
        try:
            pwd_bytes = password.encode() if password else b""
            if not pwd_bytes:
                # derive candidates from key material if possible
                hit = wechat_decrypt.detect_scheme(src_copy, b"")
                if hit is None:
                    candidates = []
                    uin = key_material.get("uin", "")
                    if uin:
                        candidates = wechat_decrypt.derive_candidates(
                            uin,
                            key_material.get("imei") or wechat_decrypt.FIXED_IMEI,
                            key_material.get("wxid", ""),
                        )
                    for cand in candidates:
                        if wechat_decrypt.detect_scheme(src_copy, cand["password"].encode()):
                            pwd_bytes = cand["password"].encode()
                            meta["decryption"]["formula"] = cand["formula"]
                            break
                    else:
                        raise wechat_decrypt.WeChatDecryptError(
                            "no password given and none could be derived from key material"
                        )
            result = wechat_decrypt.decrypt_file(src_copy, out_db, pwd_bytes, wal_copy)
        except wechat_decrypt.WeChatDecryptError as e:
            meta["status"] = "failed"
            meta["error"] = f"decryption failed: {e}"
            _write_meta(import_id, meta)
            return _meta_summary(meta)

        meta["decryption"] = {
            "scheme": result["scheme"],
            "params": result["params"],
            "pages": result.get("pages", 0),
            "password_given": bool(password),
            "formula": meta["decryption"].get("formula", ""),
        }

        # 3. merge WAL into the main file so single-file reads stay complete
        try:
            wechat_decrypt.merge_wal(out_db)
        except sqlite3.Error as e:
            logger.warning("WAL checkpoint failed for %s: %s", import_id, e)

        verify = wechat_decrypt.verify_db(out_db)
        meta["decryption"]["integrity"] = verify.get("integrity")
        if verify.get("integrity") != "ok":
            meta["status"] = "failed"
            meta["error"] = f"integrity check failed: {verify.get('integrity')}"
            _write_meta(import_id, meta)
            return _meta_summary(meta)

        # 4. parse owner / contacts / chatrooms / stats
        try:
            self._enrich_meta(import_id, out_db, meta)
        except sqlite3.Error as e:
            meta["status"] = "failed"
            meta["error"] = f"database parse failed: {e}"
            _write_meta(import_id, meta)
            return _meta_summary(meta)

        # 5. copy media thumbnails if a media root is provided
        if media_dir:
            meta["thumbs"] = self._copy_media(media_dir, wdir)

        # 6. build the normalized graph.db for the relationship-analysis pipeline
        try:
            self._build_graph_db(import_id, out_db, os.path.join(wdir, "graph.db"), meta)
        except sqlite3.Error as e:
            logger.warning("graph.db build failed for %s: %s", import_id, e)

        meta["status"] = "ready"
        _write_meta(import_id, meta)
        return _meta_summary(meta)

    # ------------------------------------------------------------------ #
    # import sub-steps
    # ------------------------------------------------------------------ #

    def _enrich_meta(self, import_id: str, db_path: str, meta: Dict[str, Any]) -> None:
        con = self._connect_path(db_path)
        try:
            owner = self._owner_from_conn(con)
            if not owner.get("username"):
                owner["username"] = meta.get("key_material", {}).get("wxid", "")
            km = meta.get("key_material", {})
            owner["uin"] = int(km["uin"]) if str(km.get("uin", "")).isdigit() else None
            owner["imei"] = km.get("imei", "")
            meta["owner"] = owner

            stats = {
                "messages": con.execute("SELECT COUNT(*) FROM message").fetchone()[0],
                "contacts": con.execute("SELECT COUNT(*) FROM rcontact").fetchone()[0],
                "chatrooms": con.execute("SELECT COUNT(*) FROM chatroom").fetchone()[0],
            }
            row = con.execute(
                "SELECT MIN(createTime), MAX(createTime) FROM message"
            ).fetchone()
            # Store in milliseconds for consistency with the read paths.
            stats["first_msg_ts"] = _to_ms(row[0])
            stats["last_msg_ts"] = _to_ms(row[1])
            stats["private_msgs"] = con.execute(
                "SELECT COUNT(*) FROM message WHERE talker NOT LIKE '%@chatroom'"
            ).fetchone()[0]
            stats["group_msgs"] = con.execute(
                "SELECT COUNT(*) FROM message WHERE talker LIKE '%@chatroom'"
            ).fetchone()[0]
            meta["stats"] = stats
        finally:
            con.close()

    def _copy_media(self, media_dir: str, wdir: str) -> List[str]:
        """Copy WeChat thumbnail/image files (image2 tree) into the import."""
        thumbs: List[str] = []
        dest_root = os.path.join(wdir, "media")
        total_bytes = 0
        for sub in ("image2", "avatar"):
            sub_src = os.path.join(media_dir, sub)
            if not os.path.isdir(sub_src):
                continue
            for root, _dirs, files in os.walk(sub_src):
                for fn in files:
                    src = os.path.join(root, fn)
                    rel = os.path.relpath(src, media_dir)
                    dst = os.path.join(dest_root, rel)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    try:
                        shutil.copy2(src, dst)
                        total_bytes += os.path.getsize(src)
                        thumbs.append(rel)
                    except OSError as e:
                        logger.warning("media copy failed %s: %s", src, e)
                    if total_bytes > 2 * 1024 ** 3:  # 2GB safety cap
                        return thumbs
        return thumbs

    def _build_graph_db(
        self, import_id: str, src_db: str, graph_db: str, meta: Dict[str, Any]
    ) -> None:
        """Produce graph.db with normalized wechat_* tables.

        The existing WeChat relationship-analysis service reads these exact
        tables, so the imported dataset plugs into /wechat-graph unchanged.
        """
        if os.path.exists(graph_db):
            os.remove(graph_db)
        src = self._connect_path(src_db)
        dst = sqlite3.connect(graph_db)
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
            owner = meta.get("owner") or {}
            dst.execute(
                "INSERT OR REPLACE INTO wechat_owner_info (username, nickname, uin, imei) "
                "VALUES (?,?,?,?)",
                (owner.get("username", ""), owner.get("nickname", ""),
                 owner.get("uin"), owner.get("imei", "")),
            )

            names = self._name_map(src, owner.get("username", ""))

            for row in src.execute("SELECT * FROM rcontact"):
                username = self._col(row, "username", "")
                if not username or "@chatroom" in username:
                    continue
                dst.execute(
                    "INSERT OR IGNORE INTO wechat_contacts "
                    "(username, nickname, remark, avatar_path, type, chatroom_flag) "
                    "VALUES (?,?,?,?,?,?)",
                    (
                        username,
                        self._col(row, "nickname", "") or "",
                        self._col(row, "conRemark", "") or "",
                        "",
                        self._col(row, "type", 0),
                        self._col(row, "chatroomFlag", 0) or 0,
                    ),
                )

            for row in src.execute("SELECT * FROM chatroom"):
                name = self._col(row, "chatroomname", "")
                if not name:
                    continue
                dst.execute(
                    "INSERT OR IGNORE INTO wechat_chatrooms "
                    "(chatroom_name, owner, member_list, member_count, create_time) "
                    "VALUES (?,?,?,?,?)",
                    (
                        name,
                        self._col(row, "roomowner", "") or "",
                        self._col(row, "memberlist", "") or "",
                        self._col(row, "membercount", 0) or 0,
                        self._col(row, "addtime", 0) or 0,
                    ),
                )

            # Column sets vary across EnMicroMsg versions (the demo dataset
            # has only talker/content/createTime/type/isSend): select what
            # actually exists and fall back to rowid for the message id.
            msg_cols = {r[1] for r in src.execute("PRAGMA table_info(message)")}
            select_fields = ["rowid AS msgId" if c == "msgId" else c
                             for c in ("msgId", "talker", "content", "createTime", "type", "isSend")
                             if c in msg_cols or c == "msgId"]
            field_names = [f.split(" AS ")[-1] for f in select_fields]
            for row in src.execute(
                f"SELECT {', '.join(select_fields)} FROM message"
            ):
                values = dict(zip(field_names, row))
                talker = values.get("talker") or ""
                content = values.get("content") or ""
                ts = values.get("createTime")
                mtype = values.get("type")
                is_send = values.get("isSend") or 0
                content = content or ""
                sender, chatroom, text = "", "", content
                if "@chatroom" in talker:
                    chatroom = talker
                    m = re.match(r"^([^\s:]{1,64}):\n", content)
                    if m:
                        sender, text = m.group(1), content[m.end():]
                    else:
                        sender = talker
                    receiver = talker
                else:
                    if is_send == 1:
                        sender, receiver = owner.get("username", ""), talker
                    else:
                        sender, receiver = talker, owner.get("username", "")
                decoded = decode_message_content(mtype, text, owner.get("username", ""))
                media = decoded.get("media") or {}
                dst.execute(
                    "INSERT INTO wechat_messages (sender, receiver, content, timestamp, "
                    "media_url, media_type, msg_type, is_send, chatroom_name, "
                    "sender_nickname, talker) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        sender, receiver, decoded.get("content_display", text),
                        _to_ms(ts), media.get("thumb_url"), media.get("kind"),
                        mtype, is_send, chatroom or None, names.get(sender, ""), talker,
                    ),
                )
            dst.commit()
        finally:
            src.close()
            dst.close()

    # ------------------------------------------------------------------ #
    # graph.db self-heal（导入期建图失败时读侧兜底重建）
    # ------------------------------------------------------------------ #

    async def ensure_graph_db(self, import_id: str) -> None:
        """Read-time self-heal: rebuild graph.db when it carries no messages.

        Import-time graph.db construction is best-effort（失败仅记日志）, so an
        import can end up with schema-only tables and a permanently empty
        relationship tab. The decrypted EnMicroMsg.db is the source of truth
        and graph.db is derived data, so regenerate it lazily; at most one
        attempt per import per process keeps a permanently failing rebuild
        from turning into a per-request storm.
        """
        await asyncio.to_thread(self._ensure_graph_db_sync, import_id)

    def _ensure_graph_db_sync(self, import_id: str) -> None:
        if import_id in self._graph_healed:
            return
        try:
            graph_db = self._graph_db_path(import_id)
            src_db = os.path.join(_import_dir(import_id), "EnMicroMsg.db")
            if not os.path.isfile(src_db):
                return
            if self._graph_db_nonempty(graph_db):
                return
            lock = self._graph_locks.setdefault(import_id, threading.Lock())
            with lock:
                if self._graph_db_nonempty(graph_db):
                    return
                if not self._source_has_messages(src_db):
                    return
                logger.warning(
                    "graph.db empty for import %s; rebuilding from decrypted source",
                    import_id,
                )
                self._build_graph_db(import_id, src_db, graph_db, _read_meta(import_id))
        except Exception as e:
            logger.warning("graph.db self-heal failed for import %s: %s", import_id, e)
        finally:
            self._graph_healed.add(import_id)

    @staticmethod
    def _graph_db_nonempty(graph_db: str) -> bool:
        """True when graph.db exists and already carries at least one message."""
        if not os.path.isfile(graph_db):
            return False
        try:
            con = sqlite3.connect(f"file:{graph_db}?mode=ro", uri=True)
        except sqlite3.Error:
            return False
        try:
            table = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='wechat_messages'"
            ).fetchone()
            return bool(table) and bool(
                con.execute("SELECT 1 FROM wechat_messages LIMIT 1").fetchone()
            )
        except sqlite3.Error:
            return False
        finally:
            con.close()

    @staticmethod
    def _source_has_messages(src_db: str) -> bool:
        try:
            con = sqlite3.connect(f"file:{src_db}?mode=ro", uri=True)
        except sqlite3.Error:
            return False
        try:
            return bool(con.execute("SELECT 1 FROM message LIMIT 1").fetchone())
        except sqlite3.Error:
            return False
        finally:
            con.close()

    # ------------------------------------------------------------------ #
    # connections & lookups
    # ------------------------------------------------------------------ #

    @staticmethod
    def _col(row: sqlite3.Row, name: str, default=None):
        """Safe column accessor for SELECT * rows (schema varies per version)."""
        try:
            value = row[name]
            return default if value is None else value
        except (IndexError, KeyError):
            return default

    def _connect(self, import_id: str) -> sqlite3.Connection:
        wdir = _import_dir(import_id)
        db = os.path.join(wdir, "EnMicroMsg.db")
        if not os.path.isfile(db):
            raise FileNotFoundError(f"import {import_id} has no decrypted database")
        return self._connect_path(db)

    def _graph_db_path(self, import_id: str) -> str:
        """Normalized wechat_* database consumed by the analysis pipeline."""
        return os.path.join(_import_dir(import_id), "graph.db")

    @staticmethod
    def _connect_path(db_path: str) -> sqlite3.Connection:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        return con

    @staticmethod
    def _owner_from_conn(con: sqlite3.Connection) -> Dict[str, Any]:
        owner = {"username": "", "nickname": ""}
        try:
            for uid, key in ((2, "username"), (4, "nickname")):
                row = con.execute(
                    "SELECT value FROM userinfo WHERE id=?", (uid,)
                ).fetchone()
                if row:
                    owner[key] = row[0] or ""
        except sqlite3.OperationalError:
            pass
        return owner

    def _name_map(self, con: sqlite3.Connection, owner_username: str) -> Dict[str, str]:
        """username -> best display name (remark > nickname > chatroom name)."""
        names: Dict[str, str] = {}
        try:
            for row in con.execute("SELECT * FROM rcontact"):
                username = self._col(row, "username", "")
                if username:
                    names[username] = (
                        self._col(row, "conRemark", "")
                        or self._col(row, "nickname", "")
                        or username
                    )
            for row in con.execute("SELECT * FROM chatroom"):
                name = self._col(row, "chatroomname", "")
                if name:
                    names[name] = (
                        self._col(row, "displayname", "")
                        or self._col(row, "chatroomnick", "")
                        or name
                    )
            names[owner_username] = self._owner_from_conn(con).get("nickname") or owner_username
        except sqlite3.OperationalError as e:
            logger.warning("name map partial: %s", e)
        return names

    # ------------------------------------------------------------------ #
    # public queries
    # ------------------------------------------------------------------ #

    async def get_meta(self, import_id: str) -> Dict[str, Any]:
        meta = _read_meta(import_id)
        return _meta_summary(meta)

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
            names = self._name_map(con, (meta.get("owner") or {}).get("username", ""))
            type_stats = [
                {"base_type": r[0] & 0xFFFF, "count": r[1]}
                for r in con.execute(
                    "SELECT type, COUNT(*) FROM message GROUP BY type ORDER BY 2 DESC"
                )
            ]
            for item in type_stats:
                item["label"] = _MSG_TYPE_LABELS.get(item["base_type"], "其他")
            day_stats = [
                {"date": r[0], "count": r[1]}
                for r in con.execute(
                    # createTime units vary across sources (seconds per the
                    # WeChat convention vs milliseconds from some backups);
                    # normalize to seconds before the unixepoch conversion.
                    "SELECT date(CASE WHEN createTime > 10000000000 "
                    "THEN createTime/1000 ELSE createTime END, "
                    "'unixepoch', '+8 hours') d, COUNT(*) "
                    "FROM message GROUP BY d ORDER BY d"
                )
            ]
            top_sessions = []
            for r in con.execute(
                "SELECT talker, COUNT(*) c, MIN(createTime), MAX(createTime) "
                "FROM message GROUP BY talker ORDER BY c DESC LIMIT 8"
            ):
                top_sessions.append({
                    "talker": r[0],
                    "display_name": names.get(r[0], r[0]),
                    "count": r[1],
                    "first_ts": _to_ms(r[2]),
                    "last_ts": _to_ms(r[3]),
                })
            stats = dict(meta.get("stats") or {})
            # Older metas may hold raw seconds; normalize like the rest of the
            # read paths so the overview card renders the intended dates.
            stats["first_msg_ts"] = _to_ms(stats.get("first_msg_ts"))
            stats["last_msg_ts"] = _to_ms(stats.get("last_msg_ts"))
            return {
                "meta": _meta_summary(meta),
                "owner": meta.get("owner") or {},
                "key_material": meta.get("key_material") or {},
                "decryption": meta.get("decryption") or {},
                "stats": stats,
                "type_stats": type_stats,
                "day_stats": day_stats,
                "top_sessions": top_sessions,
                "thumb_count": len(meta.get("thumbs") or []),
            }
        finally:
            con.close()

    async def sessions(self, import_id: str) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(self._sessions_sync, import_id)

    def _sessions_sync(self, import_id: str) -> List[Dict[str, Any]]:
        meta = _read_meta(import_id)
        owner_username = (meta.get("owner") or {}).get("username", "")
        con = self._connect(import_id)
        try:
            names = self._name_map(con, owner_username)
            room_members: Dict[str, int] = {
                self._col(r, "chatroomname", ""): self._col(r, "membercount", 0) or 0
                for r in con.execute("SELECT * FROM chatroom")
            }
            result = []
            for r in con.execute(
                """
                SELECT talker, COUNT(*) c, MIN(createTime), MAX(createTime)
                FROM message GROUP BY talker ORDER BY MAX(createTime) DESC
                """
            ):
                talker, count = r[0], r[1]
                kind = _talker_kind(talker)
                last = con.execute(
                    "SELECT content, type, isSend FROM message WHERE talker=? "
                    "ORDER BY createTime DESC LIMIT 1",
                    (talker,),
                ).fetchone()
                preview = ""
                if last:
                    decoded = decode_message_content(
                        last[1], _strip_group_prefix(last[0] or "", talker)[1], owner_username
                    )
                    preview = decoded["content_display"][:60]
                result.append({
                    "talker": talker,
                    "kind": kind,
                    "display_name": names.get(talker) or talker,
                    "msg_count": count,
                    "member_count": room_members.get(talker),
                    "first_ts": _to_ms(r[2]),
                    "last_ts": _to_ms(r[3]),
                    "last_preview": preview,
                })
            return result
        finally:
            con.close()

    async def messages(
        self,
        import_id: str,
        talker: Optional[str] = None,
        msg_type: Optional[int] = None,
        keyword: Optional[str] = None,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(
            self._messages_sync, import_id, talker, msg_type, keyword,
            start_ts, end_ts, limit, offset,
        )

    def _messages_sync(
        self,
        import_id: str,
        talker: Optional[str],
        msg_type: Optional[int],
        keyword: Optional[str],
        start_ts: Optional[int],
        end_ts: Optional[int],
        limit: int,
        offset: int,
    ) -> Dict[str, Any]:
        meta = _read_meta(import_id)
        owner_username = (meta.get("owner") or {}).get("username", "")
        wdir = _import_dir(import_id)
        con = self._connect(import_id)
        try:
            names = self._name_map(con, owner_username)
            # Schema-tolerant room names: imported datasets vary (the demo
            # EnMicroMsg chatroom table has no displayname/chatroomnick), so
            # use SELECT * + _col instead of naming columns that may not exist.
            room_names = {}
            try:
                for row in con.execute("SELECT * FROM chatroom"):
                    name = self._col(row, "chatroomname", "")
                    if name:
                        room_names[name] = (
                            self._col(row, "displayname", "")
                            or self._col(row, "chatroomnick", "")
                            or name
                        )
            except sqlite3.OperationalError:
                pass
            where, params = [], []
            if talker:
                where.append("talker = ?")
                params.append(talker)
            if msg_type is not None:
                where.append("(type & 65535) = ?")
                params.append(msg_type)
            if keyword:
                where.append("content LIKE ?")
                params.append(f"%{keyword}%")
            if start_ts is not None:
                where.append("createTime >= ?")
                params.append(start_ts)
            if end_ts is not None:
                where.append("createTime <= ?")
                params.append(end_ts)
            clause = f"WHERE {' AND '.join(where)}" if where else ""
            total = con.execute(
                f"SELECT COUNT(*) FROM message {clause}", params
            ).fetchone()[0]

            # Column sets vary across EnMicroMsg versions (the demo dataset
            # has only talker/content/createTime/type/isSend): select what
            # actually exists and fall back to rowid for the message id.
            msg_cols = {r[1] for r in con.execute("PRAGMA table_info(message)")}
            select_fields = ["rowid AS msgId" if c == "msgId" else c
                             for c in ("msgId", "talker", "content", "createTime", "type", "isSend", "imgPath")
                             if c in msg_cols or c == "msgId"]
            field_names = [f.split(" AS ")[-1] for f in select_fields]
            rows = con.execute(
                f"""
                SELECT {', '.join(select_fields)}
                FROM message {clause}
                ORDER BY createTime ASC LIMIT ? OFFSET ?
                """,
                params + [limit, offset],
            ).fetchall()

            available = set(meta.get("thumbs") or [])
            messages = []
            for row in rows:
                values = dict(zip(field_names, row))
                msg_id = values.get("msgId")
                tk = values.get("talker") or ""
                content = values.get("content") or ""
                ts = values.get("createTime")
                mtype = values.get("type")
                is_send = values.get("isSend")
                img_path = values.get("imgPath") or ""
                sender, text = _strip_group_prefix(content, tk)
                is_group = "@chatroom" in tk
                if is_group and not sender:
                    sender = tk
                if not is_group:
                    sender = owner_username if is_send == 1 else tk
                decoded = decode_message_content(mtype, text, owner_username)
                media = decoded.get("media") or {}
                if media.get("kind") == "image" and img_path:
                    rel = _thumb_relpath(img_path, media.get("md5"))
                    if rel and rel in available:
                        media["thumb_url"] = (
                            f"/api/wechat/forensics/imports/{import_id}/media/{rel}"
                        )
                        media["local_path"] = os.path.join(wdir, "media", rel)
                decoded["media"] = media or None
                messages.append({
                    "id": msg_id,
                    "talker": tk,
                    "session_name": room_names.get(tk) or names.get(tk) or tk,
                    "is_group": is_group,
                    "sender": sender,
                    "sender_name": names.get(sender) or sender,
                    "is_owner_sender": sender == owner_username and is_send == 1,
                    "direction": "send" if is_send == 1 else "receive",
                    "type_code": mtype,
                    "base_type": mtype & 0xFFFF,
                    "type_label": _MSG_TYPE_LABELS.get(mtype & 0xFFFF, "其他"),
                    "timestamp_ms": _to_ms(ts),
                    "time_display": _fmt_ts(ts),
                    "content_display": decoded["content_display"],
                    "media": decoded["media"],
                    "referenced": decoded.get("referenced"),
                })
            return {
                "messages": messages,
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        finally:
            con.close()

    async def contacts(self, import_id: str) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(self._contacts_sync, import_id)

    def _contacts_sync(self, import_id: str) -> List[Dict[str, Any]]:
        meta = _read_meta(import_id)
        owner_username = (meta.get("owner") or {}).get("username", "")
        con = self._connect(import_id)
        try:
            msg_counts = {
                r[0]: r[1]
                for r in con.execute(
                    "SELECT talker, COUNT(*) FROM message GROUP BY talker"
                )
            }
            result = []
            # SELECT * keeps this tolerant across WeChat schema versions;
            # optional columns (alias/verifyFlag/...) are read defensively.
            for row in con.execute("SELECT * FROM rcontact ORDER BY username"):
                username = self._col(row, "username", "")
                if not username:
                    continue
                alias = self._col(row, "alias", "")
                remark = self._col(row, "conRemark", "")
                nickname = self._col(row, "nickname", "")
                ctype = self._col(row, "type", 0) or 0
                kind = _contact_kind(username, ctype)
                result.append({
                    "username": username,
                    "alias": alias,
                    "remark": remark,
                    "nickname": nickname,
                    "display_name": remark or nickname or alias or username,
                    "kind": kind,
                    "contact_type": ctype,
                    "verify_flag": self._col(row, "verifyFlag", 0) or 0,
                    "msg_count": msg_counts.get(username, 0),
                    "is_owner": username == owner_username,
                })
            return result
        finally:
            con.close()

    async def chatrooms(self, import_id: str) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(self._chatrooms_sync, import_id)

    def _chatrooms_sync(self, import_id: str) -> List[Dict[str, Any]]:
        meta = _read_meta(import_id)
        owner_username = (meta.get("owner") or {}).get("username", "")
        con = self._connect(import_id)
        try:
            names = self._name_map(con, owner_username)
            room_extra = _chatroom_roomdata_names(con)
            msg_counts = {
                r[0]: r[1]
                for r in con.execute(
                    "SELECT talker, COUNT(*) FROM message "
                    "WHERE talker LIKE '%@chatroom' GROUP BY talker"
                )
            }
            result = []
            for row in con.execute("SELECT * FROM chatroom"):
                name = self._col(row, "chatroomname", "")
                if not name:
                    continue
                display = self._col(row, "displayname", "") or self._col(row, "chatroomnick", "")
                owner_wxid = self._col(row, "roomowner", "")
                memberlist = self._col(row, "memberlist", "") or ""
                members = [m for m in memberlist.split(";") if m]
                member_names = []
                for m in members:
                    member_names.append(
                        names.get(m) or room_extra.get(name, {}).get(m) or m
                    )
                result.append({
                    "chatroom_name": name,
                    "display_name": display or name,
                    "owner": owner_wxid,
                    "owner_name": names.get(owner_wxid, owner_wxid),
                    "member_count": self._col(row, "membercount", 0) or len(members),
                    "members": [
                        {"username": m, "display_name": dn}
                        for m, dn in zip(members, member_names)
                    ],
                    "create_time": _fmt_ts(self._col(row, "addtime")) if self._col(row, "addtime") else "",
                    "modify_time": _fmt_ts(self._col(row, "modifytime")) if self._col(row, "modifytime") else "",
                    "notice": self._col(row, "chatroomnotice", "") or "",
                    "msg_count": msg_counts.get(name, 0),
                })
            return result
        finally:
            con.close()

    def media_path(self, import_id: str, rel_path: str) -> Optional[str]:
        """Resolve a media file inside an import (path-traversal safe)."""
        wdir = _import_dir(import_id)
        base = os.path.realpath(os.path.join(wdir, "media"))
        target = os.path.realpath(os.path.join(base, rel_path))
        if not target.startswith(base + os.sep) or not os.path.isfile(target):
            return None
        return target


# =============================================================================
# message decoding (native schema -> human readable)
# =============================================================================


def _to_ms(ts: Optional[int]) -> Optional[int]:
    """Normalize second/millisecond timestamps to milliseconds."""
    if not ts:
        return ts
    return ts * 1000 if ts < 10_000_000_000 else ts


def _fmt_ts(ts: Optional[int]) -> str:
    ts = _to_ms(ts)
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(ts / 1000, _CN_TZ).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return ""


def _talker_kind(talker: str) -> str:
    if "@chatroom" in talker:
        return "group"
    if talker.startswith("gh_"):
        return "official"
    if talker in _SYSTEM_ACCOUNTS or talker.endswith("@weclaw") \
            or talker.endswith("@fakeuser") or talker.endswith("@stranger"):
        return "system"
    return "private"


def _contact_kind(username: str, ctype: int) -> str:
    if "@chatroom" in username:
        return "群聊"
    if username.startswith("gh_"):
        return "公众号"
    if username in _SYSTEM_ACCOUNTS or username.endswith(("@fakeuser", "@weclaw", "@stranger")):
        return "系统/功能账号"
    if ctype == 33:
        return "系统/功能账号"
    if ctype in (3, 4):
        return "好友"
    if ctype == 0:
        return "群聊" if "@chatroom" in username else "其他"
    return "其他"


def _strip_group_prefix(content: str, talker: str) -> tuple:
    """Split the ``senderid:\\n`` prefix used in group messages."""
    if "@chatroom" in talker:
        m = re.match(r"^([^\s:\n]{1,64}):\n", content)
        if m:
            return m.group(1), content[m.end():]
    return "", content


def _xml_find(text: str, tag: str) -> Optional[str]:
    m = re.search(rf"<{re.escape(tag)}[^>]*>(.*?)</{re.escape(tag)}>", text, re.S)
    return m.group(1).strip() if m else None


def _xml_attr(text: str, tag: str, attr: str) -> Optional[str]:
    m = re.search(rf"<{re.escape(tag)}[^>]*{re.escape(attr)}=\"([^\"]*)\"", text)
    return m.group(1) if m else None


def decode_message_content(mtype: int, text: str, owner_username: str) -> Dict[str, Any]:
    """Decode a native WeChat message body into display-friendly fields."""
    base = mtype & 0xFFFF
    out: Dict[str, Any] = {"content_display": "", "media": None, "referenced": None}

    if base == 1:
        out["content_display"] = text
    elif base == 3:  # image
        md5 = _xml_attr(text, "img", "md5") or _xml_attr(text, "img", "aeskey")
        out["media"] = {
            "kind": "image",
            "md5": _xml_attr(text, "img", "md5"),
            "aeskey": _xml_attr(text, "img", "aeskey"),
            "cdn_url": _xml_attr(text, "img", "cdnmidimgurl") or _xml_attr(text, "img", "cdnthumburl"),
            "width": _xml_attr(text, "img", "cdnthumbwidth"),
            "height": _xml_attr(text, "img", "cdnthumbheight"),
            "length": _xml_attr(text, "img", "length"),
        }
        out["content_display"] = "[图片]"
    elif base == 34:  # voice
        sec = _xml_attr(text, "voicemsg", "voicelength")
        secs = int(sec) // 1000 if sec and sec.isdigit() else 0
        out["media"] = {"kind": "voice", "duration_sec": secs}
        out["content_display"] = f"[语音 {secs}″]" if secs else "[语音]"
    elif base == 42:
        nick = _xml_attr(text, "contact", "nickname") or "未知"
        out["content_display"] = f"[名片] {nick}"
    elif base == 43:
        out["media"] = {"kind": "video"}
        out["content_display"] = "[视频]"
    elif base == 47:  # emoji / animated sticker
        md5 = None
        m = re.search(r"^[^\s]*?:?0:\d+:([0-9a-f]{32})", text)
        out["media"] = {"kind": "emoji", "md5": m.group(1) if m else None}
        out["content_display"] = "[动画表情]"
    elif base == 48:
        label = _xml_find(text, "label") or "未知位置"
        out["content_display"] = f"[位置] {label}"
    elif base == 49:
        _decode_appmsg(text, out)
    elif base == 50:
        out["content_display"] = "[语音通话]"
    elif base == 10000:
        out["content_display"] = text.strip()
    elif base == 10002:
        out["content_display"] = "[撤回] " + text.strip()
    else:
        preview = re.sub(r"\s+", " ", text)[:80]
        out["content_display"] = f"[未知类型 {base}] {preview}"
    return out


def _decode_appmsg(text: str, out: Dict[str, Any]) -> None:
    subtype_raw = _xml_find(text, "type") or "1"
    try:
        subtype = int(subtype_raw)
    except ValueError:
        subtype = 1
    title = (_xml_find(text, "title") or "").strip()
    des = (_xml_find(text, "des") or "").strip()
    url = (_xml_find(text, "url") or "").strip()
    label = _APPMSG_SUBTYPE_LABELS.get(subtype, f"应用消息({subtype})")

    if subtype == 57:  # quote-reply
        ref_content = _xml_find(text, "content")
        # refermsg may be CDATA-wrapped
        m = re.search(r"<refermsg>(.*?)</refermsg>", text, re.S)
        ref = ""
        if m:
            ref_block = m.group(1)
            ref_sender = _xml_find(ref_block, "displayname") or ""
            ref_text = _xml_find(ref_block, "content") or ""
            ref_text = re.sub(r"<!\[CDATA\[|\]\]>", "", ref_text or "").strip()
            ref = f"{ref_sender}: {ref_text}" if ref_sender else ref_text
        out["referenced"] = ref[:200] if ref else None
        out["content_display"] = title or "[引用回复]"
        return
    if subtype == 6:  # file
        size = _xml_find(text, "totallen")
        out["media"] = {"kind": "file", "size": size}
        out["content_display"] = f"[文件] {title}"
        return
    if subtype == 2000:
        out["content_display"] = f"[转账] {title or '微信转账'}"
        return
    if subtype == 2001:
        out["content_display"] = f"[红包] {title or '微信红包'}"
        return
    parts = [f"[{label}]"]
    if title:
        parts.append(title)
    if des and des != title:
        parts.append(des)
    out["content_display"] = " ".join(parts)
    if url:
        out["media"] = {"kind": "link", "url": url}


def _thumb_relpath(img_path: Optional[str], md5: Optional[str]) -> Optional[str]:
    """Map THUMBNAIL_DIRPATH://th_<hash> (or an md5) to image2/<a>/<b>/th_<hash>."""
    h = None
    if img_path:
        m = re.search(r"th_([0-9a-f]{16,})", img_path)
        if m:
            h = m.group(1)
    if not h:
        h = md5
    if not h:
        return None
    return f"image2/{h[:2]}/{h[2:4]}/th_{h}"


def _chatroom_roomdata_names(con: sqlite3.Connection) -> Dict[str, Dict[str, str]]:
    """Best-effort extraction of member nicknames from chatroom.roomdata.

    roomdata is a protobuf blob holding (wxid, nickname) pairs; we scan it
    leniently rather than pulling in a protobuf dependency.
    """
    result: Dict[str, Dict[str, str]] = {}
    try:
        rows = con.execute("SELECT chatroomname, roomdata FROM chatroom").fetchall()
    except sqlite3.OperationalError:
        return result
    pat = re.compile(rb"(wxid_[a-z0-9_]{5,25})\x12([\x01-\x40])(.{0,64})", re.S)
    for row in rows:
        data = row[1]
        if not data:
            continue
        names: Dict[str, str] = {}
        for m in pat.finditer(data):
            length = m.group(2)[0]
            candidate = m.group(3)[:length]
            try:
                nick = candidate.decode("utf-8")
            except UnicodeDecodeError:
                continue
            if nick and not nick.isprintable():
                continue
            wxid = m.group(1).decode()
            names.setdefault(wxid, nick)
        result[row[0]] = names
    return result


# singleton
_service: Optional[WeChatImportService] = None


def get_wechat_import_service() -> WeChatImportService:
    global _service
    if _service is None:
        _service = WeChatImportService()
    return _service
