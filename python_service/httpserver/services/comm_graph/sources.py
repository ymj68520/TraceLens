"""Resolve and read the communication sources of a task or case.

Every reader here is bounded and read-only. A source that cannot be opened is
reported in ``coverage`` instead of silently contributing zero rows: "no
messages" and "no database" are different facts in a forensic report.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

from .models import Dataset, DatasetRef, normalize_phone

MAX_ROWS_PER_SOURCE = 200_000
MAX_REF_CHARS = 400

# Tables that make a library a communication source, in priority order.
_TASK_TABLES = (
    "contacts", "call_logs", "sms_messages", "wechat_messages",
    "wechat_contacts", "wechat_chatrooms", "wechat_owner_info",
    "mobile_artifacts",
)
_IMPORT_TABLES = ("wechat_messages", "wechat_contacts", "wechat_chatrooms", "wechat_owner_info")


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{quote(str(path.resolve()), safe='/')}?mode=ro",
                           uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    # Real-case databases carry non-UTF-8 text; a single bad row must not abort
    # the whole scan.
    conn.text_factory = lambda raw: raw.decode("utf-8", "replace")
    conn.execute("PRAGMA query_only=ON")
    return conn


def _tables(conn: sqlite3.Connection) -> frozenset[str]:
    return frozenset(row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"))


def open_dataset(ref: DatasetRef) -> Dataset | None:
    """Open one source and record which tables it carries.

    ``None`` means the file is gone or unreadable; the caller reports it.
    """
    path = Path(ref.path)
    if not path.is_file() or path.is_symlink():
        return None
    try:
        with closing(_connect(path)) as conn:
            return Dataset(ref=ref, tables=_tables(conn))
    except sqlite3.DatabaseError:
        return None


def read_owner(conn: sqlite3.Connection) -> dict[str, str]:
    """Device owner identity as recorded by the IM parser."""
    if "wechat_owner_info" not in _tables(conn):
        return {}
    try:
        row = conn.execute(
            "SELECT username, nickname, uin, imei FROM wechat_owner_info LIMIT 1").fetchone()
    except sqlite3.DatabaseError:
        return {}
    if row is None:
        return {}
    return {
        "username": _text(row["username"]),
        "nickname": _text(row["nickname"]),
        "uin": _text(row["uin"]),
        "imei": _text(row["imei"]),
    }


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _int_or_none(value: object) -> int | None:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _seconds(value: object, *, unit: str) -> int | None:
    """Normalize a timestamp to epoch seconds using the source contract.

    ``ms`` sources (WeChat messages, `timestamp` columns) are divided; ``s``
    sources and already-normalized columns are used as-is.
    """
    number = _int_or_none(value)
    if number is None:
        return None
    if unit == "ms" or number > 100_000_000_000:
        return number // 1000
    return number


def _ref(dataset_id: str, table: str, row_id: object) -> str:
    text = f"{dataset_id}|{table}|{row_id}"
    return text[:MAX_REF_CHARS]


# ---------------------------------------------------------------------------
# Per-table readers. Each yields plain dicts so the aggregation step stays pure.
# ---------------------------------------------------------------------------


def read_contacts(conn: sqlite3.Connection, dataset_id: str, *, limit: int):
    if "contacts" not in _tables(conn):
        return
    statement = ("SELECT id, display_name, phone_number FROM contacts "
                 "WHERE COALESCE(display_name,'') <> '' OR COALESCE(phone_number,'') <> '' "
                 "ORDER BY id LIMIT ?")
    for row in conn.execute(statement, (limit,)):
        yield {
            "kind": "contact",
            "name": _text(row["display_name"]),
            "phone": _text(row["phone_number"]),
            "ref": _ref(dataset_id, "contacts", row["id"]),
            "dataset": dataset_id,
        }


def read_call_logs(conn: sqlite3.Connection, dataset_id: str, *, limit: int):
    if "call_logs" not in _tables(conn):
        return
    columns = _tables(conn)
    select = "id, number, date, duration, type, name"
    has_seconds = "date_seconds" in _columns_of(conn, "call_logs")
    if has_seconds:
        select += ", date_seconds"
    for row in conn.execute(f"SELECT {select} FROM call_logs ORDER BY id LIMIT ?", (limit,)):
        timestamp = _int_or_none(row["date_seconds"]) if has_seconds else None
        if timestamp is None:
            timestamp = _seconds(row["date"], unit="s")
        call_type = _int_or_none(row["type"])
        # Android call log types: 1 incoming, 2 outgoing, 3 missed, 4 voicemail,
        # 5 rejected, 6 blocked. Missed/rejected/blocked never connected.
        direction = ("received" if call_type == 1 else
                     "sent" if call_type == 2 else "unknown")
        yield {
            "kind": "call",
            "phone": _text(row["number"]),
            "name": _text(row["name"]),
            "timestamp": timestamp,
            "duration": _int_or_none(row["duration"]) or 0,
            "direction": direction,
            "connected": call_type in (1, 2),
            "ref": _ref(dataset_id, "call_logs", row["id"]),
            "dataset": dataset_id,
        }


def _columns_of(conn: sqlite3.Connection, table: str) -> frozenset[str]:
    try:
        return frozenset(row[1] for row in conn.execute(f'PRAGMA table_info("{table}")'))
    except sqlite3.DatabaseError:
        return frozenset()


def read_sms(conn: sqlite3.Connection, dataset_id: str, *, limit: int):
    if "sms_messages" not in _tables(conn):
        return
    has_seconds = "date_seconds" in _columns_of(conn, "sms_messages")
    select = "id, address, person, date, type, body" + (", date_seconds" if has_seconds else "")
    for row in conn.execute(f"SELECT {select} FROM sms_messages ORDER BY id LIMIT ?", (limit,)):
        timestamp = _int_or_none(row["date_seconds"]) if has_seconds else None
        if timestamp is None:
            timestamp = _seconds(row["date"], unit="s")
        sms_type = _int_or_none(row["type"])
        # 1 inbox (received), 2 sent, 3 draft, 4 outbox, 5 failed, 6 queued.
        direction = ("received" if sms_type == 1 else
                     "sent" if sms_type in (2, 4, 5, 6) else "unknown")
        yield {
            "kind": "sms",
            "phone": _text(row["address"]),
            "name": _text(row["person"]),
            "timestamp": timestamp,
            "direction": direction,
            "body": _text(row["body"]),
            "ref": _ref(dataset_id, "sms_messages", row["id"]),
            "dataset": dataset_id,
        }


def read_wechat_contacts(conn: sqlite3.Connection, dataset_id: str, *, limit: int,
                         phone_by_username: dict[str, str] | None = None):
    if "wechat_contacts" not in _tables(conn):
        return
    columns = _columns_of(conn, "wechat_contacts")
    select = "username, nickname, remark, chatroom_flag"
    if "mobile" in columns:
        select += ", mobile"
    for row in conn.execute(
        f"SELECT {select} FROM wechat_contacts ORDER BY id LIMIT ?", (limit,)
    ):
        username = _text(row["username"])
        if not username or "@chatroom" in username:
            continue
        mobile = _text(row["mobile"]) if "mobile" in columns else ""
        if phone_by_username is not None and mobile:
            phone_by_username[username] = mobile
        yield {
            "kind": "im_contact",
            "wxid": username,
            "name": _text(row["remark"]) or _text(row["nickname"]) or username,
            "phone": mobile,
            "ref": _ref(dataset_id, "wechat_contacts", username),
            "dataset": dataset_id,
        }


def read_wechat_messages(conn: sqlite3.Connection, dataset_id: str, *, limit: int,
                         owner_username: str):
    if "wechat_messages" not in _tables(conn):
        return
    for row in conn.execute(
        "SELECT id, sender, receiver, content, timestamp, msg_type, is_send, "
        "chatroom_name, talker, media_type FROM wechat_messages "
        "ORDER BY id LIMIT ?", (limit,)
    ):
        chatroom = _text(row["chatroom_name"])
        sender = _text(row["sender"])
        receiver = _text(row["receiver"]) or chatroom
        timestamp = _seconds(row["timestamp"], unit="ms")
        if chatroom:
            # A group message links speaker -> group hub; it is not a private
            # conversation between two people.
            if not sender:
                continue
            yield {
                "kind": "im_group",
                "sender": sender,
                "group": chatroom,
                "timestamp": timestamp,
                "content": _text(row["content"]),
                "media": bool(_text(row["media_type"])),
                "ref": _ref(dataset_id, "wechat_messages", row["id"]),
                "dataset": dataset_id,
            }
            continue
        if not sender or not receiver:
            continue
        yield {
            "kind": "im_private",
            "sender": sender,
            "receiver": receiver,
            "timestamp": timestamp,
            "content": _text(row["content"]),
            "media": bool(_text(row["media_type"])),
            "is_send": _int_or_none(row["is_send"]) or 0,
            "owner": owner_username,
            "ref": _ref(dataset_id, "wechat_messages", row["id"]),
            "dataset": dataset_id,
        }


def read_wechat_chatrooms(conn: sqlite3.Connection, dataset_id: str, *, limit: int):
    if "wechat_chatrooms" not in _tables(conn):
        return
    for row in conn.execute(
        "SELECT chatroom_name, member_list, member_count FROM wechat_chatrooms LIMIT ?",
        (limit,)
    ):
        name = _text(row["chatroom_name"])
        if not name:
            continue
        members = [m.strip() for m in _text(row["member_list"]).split(",") if m.strip()]
        yield {
            "kind": "im_group",
            "group": name,
            "members": members,
            "member_count": _int_or_none(row["member_count"]) or len(members),
            "ref": _ref(dataset_id, "wechat_chatrooms", name),
            "dataset": dataset_id,
        }


def read_mobile_artifacts(conn: sqlite3.Connection, dataset_id: str, *, limit: int):
    """IM rows recovered by the unified artifact table (Harmony/Thunder/Meiya).

    These carry native kind names, not the normalized WeChat schema, so only the
    kinds that represent a person-to-person interaction are interpreted.
    """
    if "mobile_artifacts" not in _tables(conn):
        return
    try:
        import json as _json
        for row in conn.execute(
            "SELECT id, kind, record_json, timestamp_seconds FROM mobile_artifacts "
            "WHERE kind IN ('im_message','message','chat') ORDER BY id LIMIT ?",
            (limit,)
        ):
            try:
                record = _json.loads(_text(row["record_json"]) or "{}")
            except (TypeError, ValueError):
                continue
            if not isinstance(record, dict):
                continue
            phone = _pick_phone(record)
            name = _pick(record, ("name", "nick_name", "nickname", "sender_name"))
            sender = _pick(record, ("sender", "from", "from_uin", "sender_uin"))
            peer = _pick(record, ("peer", "to", "to_uin", "receiver", "peer_uin"))
            if not (phone or sender or peer):
                continue
            yield {
                "kind": "im_artifact",
                "phone": phone,
                "name": name,
                "sender": sender,
                "receiver": peer,
                "timestamp": _int_or_none(row["timestamp_seconds"]),
                "content": _pick(record, ("content", "body", "text", "msg")),
                "ref": _ref(dataset_id, "mobile_artifacts", row["id"]),
                "dataset": dataset_id,
            }
    except sqlite3.DatabaseError:
        return


def _pick(record: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        if key in record and record[key] not in (None, ""):
            return _text(record[key])
    return ""


def _pick_phone(record: dict) -> str:
    for key in ("phone_number", "phone", "mobile", "number", "peer_number"):
        value = record.get(key)
        if isinstance(value, str) and normalize_phone(value):
            return value
    return ""


__all__ = [
    "Dataset",
    "DatasetRef",
    "MAX_ROWS_PER_SOURCE",
    "open_dataset",
    "read_call_logs",
    "read_contacts",
    "read_mobile_artifacts",
    "read_owner",
    "read_sms",
    "read_wechat_chatrooms",
    "read_wechat_contacts",
    "read_wechat_messages",
]
