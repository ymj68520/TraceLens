"""WhatsApp forensics (WhatsApp 取证) import service.

Imports an iOS WhatsApp backup dataset (``ChatStorage.sqlite`` plus the sibling
``ContactsV2.sqlite`` / ``CallHistory.sqlite``) and normalises it into the same
``graph.db`` schema the WeChat and QQ panels already read, so WhatsApp sits
alongside them as a third platform instead of getting a parallel UI.

The iOS stores are Core Data tables:

  ZWAMESSAGE   Z_PK, ZISFROMME, ZMESSAGEDATE, ZTEXT, ZCHATSESSION, ZMESSAGETYPE
  ZWACHATSESSION  Z_PK, ZPARTNERNAME, ZCONTACTJID, ZLASTMESSAGEDATE

``ZMESSAGEDATE`` is an Apple-epoch timestamp; WhatsApp uses seconds here, but
the value is classified by magnitude so a millisecond store still lands right.

Nothing is ever written back to the evidence files: the source database is
opened read-only and the normalised copy lives under ``whatsapp_imports``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from ..config import get_data_root

logger = logging.getLogger(__name__)

# Apple's reference date (2001-01-01T00:00:00Z) in Unix seconds.
APPLE_EPOCH_OFFSET = 978307200

# WhatsApp message kinds, per ZWAMESSAGE.ZMESSAGETYPE / ZFLAGS. The panel shows
# these labels directly, so keep them human-readable.
MESSAGE_TYPE_LABELS = {
    0: "文本",
    1: "图片",
    2: "语音",
    3: "视频",
    4: "位置",
    5: "名片",
    6: "群成员变动",
    7: "链接/媒体",
    8: "文档",
    10: "系统消息",
    14: "贴纸",
}

MAX_MESSAGES = 2_000_000


# --------------------------------------------------------------------------- #
# storage helpers (mirror the wechat/qq import layout)
# --------------------------------------------------------------------------- #

def import_root() -> str:
    root = get_data_root() / "whatsapp_imports"
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
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_meta(import_id: str, meta: Dict[str, Any]) -> None:
    with open(_meta_path(import_id), "w", encoding="utf-8") as handle:
        json.dump(meta, handle, ensure_ascii=False, indent=2)


def _meta_summary(meta: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "import_id": meta.get("import_id", ""),
        "name": meta.get("name", ""),
        "status": meta.get("status", ""),
        "error": meta.get("error"),
        "created_at": meta.get("created_at"),
        "backup_source": meta.get("backup_source", ""),
        "format": meta.get("format", "ios_whatsapp"),
        "message_count": (meta.get("stats") or {}).get("total_messages", 0),
        "owner": meta.get("owner") or {},
        "stats": meta.get("stats") or {},
    }


def list_imports() -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    root = import_root()
    for entry in sorted(os.listdir(root), reverse=True):
        path = os.path.join(root, entry, "meta.json")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                result.append(_meta_summary(json.load(handle)))
        except (json.JSONDecodeError, OSError):
            continue
    return result


# --------------------------------------------------------------------------- #
# timestamp handling
# --------------------------------------------------------------------------- #

def apple_to_unix(raw: Any) -> int:
    """Convert an Apple-epoch timestamp to Unix seconds.

    iOS Core Data stores seconds since 2001-01-01; some axes store
    milliseconds or the raw Unix value. The magnitude decides, because a
    wrong guess shifts every timeline entry by 31 years.
    """
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 0
    if value <= 0:
        return 0
    # Unix seconds in this era are >= 1.2e9; anything smaller is Apple-epoch
    # seconds (a 2023 value reads ~7.15e8).
    if value >= 1_200_000_000:
        # Milliseconds from the Unix epoch (or Apple epoch ms).
        if value > 100_000_000_000_000:
            return value // 1_000_000_000 + APPLE_EPOCH_OFFSET
        if value > 100_000_000_000:
            return value // 1000
        return value
    return value + APPLE_EPOCH_OFFSET


# --------------------------------------------------------------------------- #
# source discovery
# --------------------------------------------------------------------------- #

def _open_readonly(path: str) -> sqlite3.Connection:
    uri = "file:" + path.replace("?", "%3f").replace("#", "%23") + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=10)
    connection.execute("PRAGMA query_only=ON")
    return connection


def _table_names(connection: sqlite3.Connection) -> set:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }


def _resolve_sources(db_path: str) -> Dict[str, Optional[str]]:
    """Locate ChatStorage.sqlite and its siblings.

    ``db_path`` may point at the ChatStorage file itself or at the directory
    that holds it (an extracted WhatsApp backup root).
    """
    if os.path.isdir(db_path):
        directory = db_path
        chat = os.path.join(directory, "ChatStorage.sqlite")
    else:
        directory = os.path.dirname(os.path.abspath(db_path))
        chat = db_path
    if not os.path.isfile(chat):
        raise FileNotFoundError(f"ChatStorage.sqlite not found at {db_path}")
    siblings = {
        "chat": chat,
        "contacts": os.path.join(directory, "ContactsV2.sqlite"),
        "calls": os.path.join(directory, "CallHistory.sqlite"),
        "media": os.path.join(directory, "Media"),
    }
    for key in ("contacts", "calls"):
        if not os.path.isfile(siblings[key]):
            siblings[key] = None
    return siblings


# --------------------------------------------------------------------------- #
# normalisation into graph.db
# --------------------------------------------------------------------------- #

GRAPH_SCHEMA = """
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
    avatar_path TEXT, type INTEGER, chatroom_flag INTEGER DEFAULT 0,
    mobile TEXT
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
CREATE INDEX idx_wa_messages_time ON wechat_messages(timestamp);
CREATE INDEX idx_wa_messages_talker ON wechat_messages(talker);
"""


def _jid_to_number(jid: str) -> str:
    """Reduce a WhatsApp JID to the displayable address.

    ``8613800138000@s.whatsapp.net`` -> ``8613800138000``;
    ``123-456@g.us`` stays as the group id.
    """
    if not jid:
        return ""
    value = jid.split("@", 1)[0]
    return value


def _is_group_jid(jid: str) -> bool:
    return str(jid or "").endswith("@g.us")


def _build_graph_db(chat_db: str, contacts_db: Optional[str],
                    calls_db: Optional[str], graph_db: str,
                    media_root: Optional[str]) -> Dict[str, Any]:
    """Write the normalised graph.db and return parsing statistics."""
    tmp_db = f"{graph_db}.{uuid.uuid4().hex}.building"
    stats: Dict[str, Any] = {
        "total_messages": 0,
        "c2c_messages": 0,
        "group_messages": 0,
        "sessions": 0,
        "contacts": 0,
        "groups": 0,
        "calls": 0,
        "media_messages": 0,
    }

    source = _open_readonly(chat_db)
    try:
        tables = _table_names(source)
        if "ZWAMESSAGE" not in tables:
            raise ValueError("ChatStorage.sqlite has no ZWAMESSAGE table")

        # Sessions carry the display name and the counterpart JID.
        sessions: Dict[int, Dict[str, Any]] = {}
        if "ZWACHATSESSION" in tables:
            for row in source.execute(
                "SELECT Z_PK, ZPARTNERNAME, ZCONTACTJID, ZLASTMESSAGEDATE "
                "FROM ZWACHATSESSION"
            ):
                sessions[int(row[0])] = {
                    "partner": row[1] or "",
                    "jid": row[2] or "",
                    "last": row[3] or 0,
                }
        stats["sessions"] = len(sessions)

        # Read every message, newest last so the timeline reads forwards.
        columns = _table_columns(source, "ZWAMESSAGE")
        has_flags = "ZFLAGS" in columns
        has_type = "ZMESSAGETYPE" in columns
        select = (
            "SELECT Z_PK, ZISFROMME, ZMESSAGEDATE, ZTEXT, ZCHATSESSION, "
            "ZFROMJID, ZTOJID, ZPUSHNAME"
            + (", ZMESSAGETYPE" if has_type else ", 0")
            + (", ZFLAGS" if has_flags else ", 0")
            + " FROM ZWAMESSAGE ORDER BY ZMESSAGEDATE ASC LIMIT ?"
        )
        rows = source.execute(select, (MAX_MESSAGES,)).fetchall()
    finally:
        source.close()

    target = sqlite3.connect(tmp_db)
    try:
        # The target is a throwaway normalisation file, not evidence: trade
        # per-row durability for throughput. Thousands of messages otherwise
        # spend most of their runtime in fsync.
        target.execute("PRAGMA journal_mode=OFF")
        target.execute("PRAGMA synchronous=OFF")
        target.execute("PRAGMA temp_store=MEMORY")
        target.execute("PRAGMA cache_size=-64000")
        target.executescript(GRAPH_SCHEMA)
        for row in rows:
            primary_key, from_me, message_date, text, session_key = row[0], row[1], row[2], row[3], row[4]
            from_jid, to_jid, push_name = row[5], row[6], row[7]
            message_type = row[8] if has_type else 0
            flags = row[9] if has_flags else 0

            session = sessions.get(int(session_key or 0), {})
            partner = session.get("partner") or ""
            session_jid = session.get("jid") or ""
            is_group = _is_group_jid(session_jid)

            # Counterpart identity: prefer the session JID, fall back to the
            # message-level JIDs so orphaned messages still get a talker.
            talker = session_jid or (from_jid if from_me else to_jid) or partner
            # ZPUSHNAME is an encrypted push name (base64 ciphertext), not a
            # display name, so it must never be shown as an identity. Fall back
            # to the readable session partner name instead.
            sender = "me" if from_me else (partner or _jid_to_number(from_jid))
            receiver = (partner or _jid_to_number(to_jid)) if from_me else "me"
            if is_group:
                # In a group the sender is the member JID; the talker is the group.
                if not from_me:
                    sender = _jid_to_number(from_jid) or partner
                receiver = partner or _jid_to_number(session_jid)

            content = text or ""
            # Type 6 (group membership churn) carries no text; keep the label so
            # the row is not silently blank in the panel.
            if not content:
                content = MESSAGE_TYPE_LABELS.get(int(message_type or 0), "")

            media_type = ""
            if int(message_type or 0) in (1, 2, 3, 4, 5, 8, 14):
                media_type = MESSAGE_TYPE_LABELS.get(int(message_type or 0), "")
                stats["media_messages"] += 1

            target.execute(
                "INSERT INTO wechat_messages(sender, receiver, content, timestamp,"
                " media_url, media_type, msg_type, is_send, chatroom_name,"
                " sender_nickname, talker) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    sender,
                    receiver,
                    content,
                    apple_to_unix(message_date),
                    "",
                    media_type,
                    int(message_type or 0),
                    1 if from_me else 0,
                    partner if is_group else "",
                    # ZPUSHNAME is encrypted push-name ciphertext, not a
                    # display name; storing it would put base64 noise in the
                    # identity column.
                    "",
                    talker,
                ),
            )
            stats["total_messages"] += 1
            if is_group:
                stats["group_messages"] += 1
            else:
                stats["c2c_messages"] += 1
            del primary_key, flags

        # Contacts: one row per session counterpart, enriched from ContactsV2.
        contact_rows: Dict[str, Dict[str, Any]] = {}
        if contacts_db:
            contact_rows = _read_contacts(contacts_db)

        for session in sessions.values():
            jid = session.get("jid") or ""
            number = _jid_to_number(jid)
            label = session.get("partner") or number
            if not label:
                continue
            is_group = _is_group_jid(jid)
            if is_group:
                # Store the group JID in `owner` so readers can map the JID that
                # appears as message.talker back to this readable group name.
                target.execute(
                    "INSERT OR IGNORE INTO wechat_chatrooms(chatroom_name, owner,"
                    " member_list, member_count, create_time) VALUES(?,?,?,?,?)",
                    (label, jid, "", 0, 0),
                )
                stats["groups"] += 1
                continue
            known = contact_rows.get(number, {})
            target.execute(
                "INSERT OR IGNORE INTO wechat_contacts(username, nickname, remark,"
                " avatar_path, type, chatroom_flag, mobile) VALUES(?,?,?,?,?,?,?)",
                (
                    number or label,
                    known.get("name") or label,
                    label if known.get("name") and known.get("name") != label else "",
                    "",
                    1,
                    0,
                    number,
                ),
            )
            stats["contacts"] += 1

        # WhatsApp call events are a separate store; surface them as messages of
        # type 9 so they sit on the same timeline instead of being dropped.
        if calls_db:
            stats["calls"] = _append_calls(calls_db, target)

        target.execute(
            "INSERT OR IGNORE INTO wechat_owner_info(username, nickname, uin, imei)"
            " VALUES(?,?,?,?)",
            ("", "WhatsApp 机主", 0, ""),
        )
        target.commit()
    finally:
        target.close()

    os.replace(tmp_db, graph_db)
    return stats


def _table_columns(connection: sqlite3.Connection, table: str) -> set:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def _read_contacts(path: str) -> Dict[str, Dict[str, Any]]:
    """Map phone number -> display name from ContactsV2.sqlite."""
    result: Dict[str, Dict[str, Any]] = {}
    try:
        connection = _open_readonly(path)
    except sqlite3.Error:
        return result
    try:
        tables = _table_names(connection)
        if "ZWAADDRESSBOOKCONTACT" not in tables:
            return result
        columns = _table_columns(connection, "ZWAADDRESSBOOKCONTACT")
        name_column = "ZWHATSAPPID" if "ZWHATSAPPID" in columns else None
        for row in connection.execute(
            "SELECT Z_PK, ZPHONENUMBER, ZGIVENNAME, ZFAMILYNAME FROM ZWAADDRESSBOOKCONTACT"
            if {"ZPHONENUMBER", "ZGIVENNAME", "ZFAMILYNAME"} <= columns
            else "SELECT Z_PK, '' , '' , '' FROM ZWAADDRESSBOOKCONTACT"
        ):
            number = _jid_to_number(row[1] or "")
            if not number:
                continue
            name = " ".join(part for part in (row[2], row[3]) if part).strip()
            result[number] = {"name": name, "jid": name_column or ""}
    except sqlite3.Error:
        pass
    finally:
        connection.close()
    return result


def _append_calls(path: str, target: sqlite3.Connection) -> int:
    """Insert WhatsApp call events as timeline messages. Returns the count."""
    try:
        connection = _open_readonly(path)
    except sqlite3.Error:
        return 0
    inserted = 0
    try:
        tables = _table_names(connection)
        if "ZWACDCALLEVENT" not in tables:
            return 0
        participants: Dict[int, str] = {}
        if "ZWACDCALLEVENTPARTICIPANT" in tables:
            for row in connection.execute(
                "SELECT Z_FOK_1PARTICIPANTS, ZJIDSTRING FROM ZWACDCALLEVENTPARTICIPANT"
            ):
                if row[0] is not None and row[1]:
                    participants.setdefault(int(row[0]), str(row[1]))

        columns = _table_columns(connection, "ZWACDCALLEVENT")
        has_duration = "ZDURATION" in columns
        has_outcome = "ZOUTCOME" in columns
        select = (
            "SELECT Z_PK, ZDATE"
            + (", ZDURATION" if has_duration else ", 0")
            + (", ZOUTCOME" if has_outcome else ", 0")
            + ", ZGROUPJIDSTRING FROM ZWACDCALLEVENT ORDER BY ZDATE ASC"
        )
        for row in connection.execute(select):
            primary_key, date_value = row[0], row[1]
            duration = row[2] if has_duration else 0
            outcome = row[3] if has_outcome else 0
            group_jid = row[4]
            counterpart = participants.get(int(primary_key or 0), "") or (group_jid or "")
            try:
                seconds = int(float(duration or 0))
            except (TypeError, ValueError):
                seconds = 0
            label = f"WhatsApp 通话 · {seconds} 秒" if seconds else "WhatsApp 通话"
            target.execute(
                "INSERT INTO wechat_messages(sender, receiver, content, timestamp,"
                " media_url, media_type, msg_type, is_send, chatroom_name,"
                " sender_nickname, talker) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "me",
                    _jid_to_number(counterpart),
                    label,
                    apple_to_unix(date_value),
                    "",
                    "通话",
                    9,
                    0,
                    "",
                    "",
                    counterpart,
                ),
            )
            inserted += 1
            del outcome
    except sqlite3.Error:
        pass
    finally:
        connection.close()
    return inserted


# --------------------------------------------------------------------------- #
# query helpers
# --------------------------------------------------------------------------- #

class WhatsAppImportService:
    def _graph_db_path(self, import_id: str) -> str:
        return os.path.join(_import_dir(import_id), "graph.db")

    def _connect(self, import_id: str) -> sqlite3.Connection:
        path = self._graph_db_path(import_id)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"graph.db not found for import {import_id}")
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)

    def _owner(self) -> Dict[str, Any]:
        return {"username": "", "nickname": "WhatsApp 机主", "uin": 0, "imei": ""}

    def create_import(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        db_path = str(payload.get("db_path") or "").strip()
        if not db_path:
            raise ValueError("db_path is required")

        sources = _resolve_sources(db_path)
        import_id = uuid.uuid4().hex[:12]
        directory = _import_dir(import_id)
        os.makedirs(directory, exist_ok=True)

        meta: Dict[str, Any] = {
            "import_id": import_id,
            "name": payload.get("name") or os.path.basename(db_path),
            "status": "parsing",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "backup_source": payload.get("backup_source") or db_path,
            "format": "ios_whatsapp",
            "owner": self._owner(),
        }
        _write_meta(import_id, meta)

        try:
            stats = _build_graph_db(
                sources["chat"], sources["contacts"], sources["calls"],
                os.path.join(directory, "graph.db"), sources.get("media"),
            )
            meta.update(
                {
                    "status": "ready",
                    "stats": stats,
                    "sources": {
                        "chat": sources["chat"],
                        "contacts": sources["contacts"],
                        "calls": sources["calls"],
                    },
                }
            )
        except Exception as error:  # noqa: BLE001 - surfaced through meta.status
            logger.error("WhatsApp import failed: %s", error, exc_info=True)
            meta.update({"status": "failed", "error": str(error)})
            _write_meta(import_id, meta)
            raise
        _write_meta(import_id, meta)
        return _meta_summary(meta)

    def get_import(self, import_id: str) -> Dict[str, Any]:
        return _meta_summary(_read_meta(import_id))

    def delete_import(self, import_id: str) -> None:
        directory = _import_dir(import_id)
        if not os.path.isdir(directory):
            raise FileNotFoundError(f"import not found: {import_id}")
        for entry in os.listdir(directory):
            os.remove(os.path.join(directory, entry))
        os.rmdir(directory)

    def overview(self, import_id: str) -> Dict[str, Any]:
        meta = _read_meta(import_id)
        connection = self._connect(import_id)
        try:
            type_stats = [
                {
                    "base_type": row[0],
                    "count": row[1],
                    "label": MESSAGE_TYPE_LABELS.get(row[0], f"类型{row[0]}"),
                }
                for row in connection.execute(
                    "SELECT msg_type, COUNT(*) FROM wechat_messages "
                    "GROUP BY msg_type ORDER BY COUNT(*) DESC"
                )
            ]
            day_stats = [
                {"date": row[0], "count": row[1]}
                for row in connection.execute(
                    "SELECT date(timestamp, 'unixepoch', '+8 hours') AS d, COUNT(*) "
                    "FROM wechat_messages GROUP BY d ORDER BY d"
                )
                if row[0]
            ]
            sessions = self.sessions(import_id)
            return {
                "meta": _meta_summary(meta),
                "owner": meta.get("owner") or self._owner(),
                "key_material": {},
                "decryption": {
                    "scheme": "none",
                    "integrity": "ok",
                    "formula": "",
                },
                "stats": meta.get("stats") or {},
                "type_stats": type_stats,
                "day_stats": day_stats,
                "top_sessions": sorted(sessions, key=lambda item: -item["msg_count"])[:8],
            }
        finally:
            connection.close()

    def sessions(self, import_id: str) -> List[Dict[str, Any]]:
        connection = self._connect(import_id)
        try:
            rows = connection.execute(
                "SELECT talker, COUNT(*) AS c, MAX(timestamp), "
                "  SUM(CASE WHEN is_send = 1 THEN 1 ELSE 0 END) "
                "FROM wechat_messages WHERE talker <> '' "
                "GROUP BY talker ORDER BY c DESC"
            ).fetchall()
            names = {
                str(row[0]): str(row[1] or "")
                for row in connection.execute(
                    "SELECT username, nickname FROM wechat_contacts"
                )
            }
            groups = {
                str(row[0]): str(row[1] or "")
                for row in connection.execute(
                    "SELECT chatroom_name, chatroom_name FROM wechat_chatrooms"
                )
            }
            # Group display names: wechat_chatrooms keys on the readable name and
            # carries the group JID in `owner`, while messages use the JID as
            # talker. Build the JID -> name bridge here.
            group_names: Dict[str, str] = {}
            for name, jid in connection.execute(
                "SELECT chatroom_name, owner FROM wechat_chatrooms"
            ):
                if jid:
                    group_names[str(jid)] = str(name)
            result = []
            for talker, count, last, sent in rows:
                label = names.get(str(talker)) or groups.get(str(talker)) or str(talker)
                is_group = _is_group_jid(str(talker)) or str(talker) in groups
                if str(talker) in group_names:
                    label = group_names[str(talker)]
                    is_group = True
                last_text = connection.execute(
                    "SELECT content FROM wechat_messages WHERE talker = ? "
                    "ORDER BY timestamp DESC LIMIT 1",
                    (talker,),
                ).fetchone()
                result.append(
                    {
                        "talker": str(talker),
                        "display_name": label,
                        "msg_count": count,
                        "sent_count": int(sent or 0),
                        "last_timestamp": int(last or 0),
                        "last_message": (last_text or [""])[0],
                        "is_group": is_group,
                    }
                )
            return result
        finally:
            connection.close()

    def messages(self, import_id: str, *, talker: str = "", msg_type: Optional[int] = None,
                 keyword: str = "", start: Optional[int] = None,
                 end: Optional[int] = None, page: int = 1,
                 page_size: int = 50) -> Dict[str, Any]:
        connection = self._connect(import_id)
        try:
            clauses: List[str] = []
            params: List[Any] = []
            if talker:
                clauses.append("talker = ?")
                params.append(talker)
            if msg_type is not None:
                clauses.append("msg_type = ?")
                params.append(int(msg_type))
            if keyword:
                clauses.append("content LIKE ?")
                params.append(f"%{keyword}%")
            if start is not None:
                clauses.append("timestamp >= ?")
                params.append(int(start))
            if end is not None:
                clauses.append("timestamp <= ?")
                params.append(int(end))
            where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

            total = connection.execute(
                f"SELECT COUNT(*) FROM wechat_messages{where}", params
            ).fetchone()[0]
            page = max(int(page or 1), 1)
            page_size = min(max(int(page_size or 50), 1), 200)
            offset = (page - 1) * page_size
            rows = connection.execute(
                "SELECT id, sender, receiver, content, timestamp, media_type, "
                "msg_type, is_send, talker, sender_nickname "
                f"FROM wechat_messages{where} ORDER BY timestamp DESC "
                "LIMIT ? OFFSET ?",
                params + [page_size, offset],
            ).fetchall()
            records = [
                {
                    "id": row[0],
                    "sender": row[1],
                    "receiver": row[2],
                    "content": row[3],
                    "timestamp": row[4],
                    "media_type": row[5],
                    "msg_type": row[6],
                    "msg_type_label": MESSAGE_TYPE_LABELS.get(row[6], f"类型{row[6]}"),
                    "is_send": bool(row[7]),
                    "talker": row[8],
                    "sender_nickname": row[9],
                }
                for row in rows
            ]
            return {
                "total": total,
                "page": page,
                "page_size": page_size,
                "records": records,
            }
        finally:
            connection.close()

    def contacts(self, import_id: str) -> List[Dict[str, Any]]:
        connection = self._connect(import_id)
        try:
            return [
                {
                    "username": row[0],
                    "nickname": row[1],
                    "remark": row[2],
                    "mobile": row[3],
                    "chatroom_flag": bool(row[4]),
                }
                for row in connection.execute(
                    "SELECT username, nickname, remark, mobile, chatroom_flag "
                    "FROM wechat_contacts ORDER BY nickname"
                )
            ]
        finally:
            connection.close()

    def chatrooms(self, import_id: str) -> List[Dict[str, Any]]:
        connection = self._connect(import_id)
        try:
            rows = connection.execute(
                "SELECT chatroom_name, owner, member_list, member_count, create_time "
                "FROM wechat_chatrooms ORDER BY chatroom_name"
            ).fetchall()
            result = []
            for row in rows:
                name, jid = row[0], row[1]
                # Messages store the group JID as talker, so count by JID when
                # the room carries one and fall back to the readable name.
                talker_key = jid or name
                count = connection.execute(
                    "SELECT COUNT(*) FROM wechat_messages WHERE talker = ?",
                    (talker_key,),
                ).fetchone()[0]
                if not count and name != talker_key:
                    count = connection.execute(
                        "SELECT COUNT(*) FROM wechat_messages WHERE talker = ?",
                        (name,),
                    ).fetchone()[0]
                result.append(
                    {
                        "chatroom_name": name,
                        "owner": jid or "",
                        "member_list": row[2] or "",
                        "member_count": row[3] or 0,
                        "create_time": row[4] or 0,
                        "msg_count": count,
                    }
                )
            return result
        finally:
            connection.close()


_service: Optional[WhatsAppImportService] = None


def get_whatsapp_import_service() -> WhatsAppImportService:
    global _service
    if _service is None:
        _service = WhatsAppImportService()
    return _service
