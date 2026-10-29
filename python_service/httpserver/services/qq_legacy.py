"""Legacy Android QQ (mobile QQ 4.x, ~2013-2015) account database support.

The pre-NTQQ account database ``databases/<owner_uin>.db`` is a plaintext
SQLite file whose TEXT columns are obfuscated with a repeating-XOR of the
device ID (the same ``a00000420ce2b6``-style identifier WeChat stores in
``CompatibleInfo.cfg`` under key 258). Verified recoverable surfaces:

- ``Friends``        uin / name / remark  (buddy list)
- ``TroopInfo``      troopuin / troopname (groups)
- ``TroopMemberInfo``troopuin / memberuin (group membership)
- ``mr_troop_<md5(uin)>_New`` / ``mr_friend_<md5>_New``  roaming messages,
  ``msgData`` XOR-decodes straight to UTF-8 text

Group/nick names longer than the key period may stay garbled when the device
ID is only partially recoverable; QQ numbers and message bodies decrypt with
the full 14-byte key and are the forensically load-bearing fields.
"""

from __future__ import annotations

import glob
import hashlib
import logging
import os
import re
import sqlite3
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SQLITE_MAGIC = b"SQLite format 3\x00"

# mr_* message tables whose columns carry the chat payload.
_MSG_TYPE_TEXT = -1000


def owner_uin(db_path: str) -> str:
    """Owner QQ number from the account database filename ``<uin>.db``."""
    return re.sub(r"\.db$", "", os.path.basename(db_path))


def looks_legacy_qq4(db_path: str) -> bool:
    """True when the file is a plaintext pre-NTQQ account database."""
    try:
        if open(db_path, "rb").read(16) != SQLITE_MAGIC:
            return False
        name = os.path.basename(db_path)
        if not re.fullmatch(r"\d{5,12}\.db", name):
            return False
        con = sqlite3.connect(db_path)
        try:
            tables = {
                r[0]
                for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        finally:
            con.close()
        return "Friends" in tables and "TroopMemberInfo" in tables
    except (OSError, sqlite3.Error):
        return False


# --------------------------------------------------------------------- #
# device ID harvest
# --------------------------------------------------------------------- #

def _java_cfg_strings(cfg_path: str) -> Dict[int, str]:
    """Parse the integer->string map out of a Java-serialized HashMap cfg.

    CompatibleInfo.cfg is a Java ObjectOutputStream around a HashMap whose
    entries are Integer keys mapped to String values (258 -> device id,
    256 -> device id variant, 259 -> cpu string). Integer keys appear either
    as a back-referenced object (``TC_OBJECT TC_REFERENCE <handle> <int>``)
    or inline after a fresh class descriptor; both are scanned. Rather than
    a full ObjectInputStream, each match is followed by the value object
    (TC_STRING, or TC_NULL/TC_OBJECT forms that are skipped).
    """
    out: Dict[int, str] = {}
    try:
        data = open(cfg_path, "rb").read()
    except OSError:
        return out
    n = len(data)

    def parse_value(pos: int) -> tuple[Optional[str], int]:
        """Value object at pos -> (string or None, next offset)."""
        if pos >= n:
            return None, pos
        tag = data[pos]
        if tag == 0x70:                      # TC_NULL
            return None, pos + 1
        if tag == 0x74:                      # TC_STRING
            length = int.from_bytes(data[pos + 1 : pos + 3], "big")
            if 0 < length <= 4096 and pos + 3 + length <= n:
                try:
                    return data[pos + 3 : pos + 3 + length].decode(
                        "utf-8"
                    ), pos + 3 + length
                except UnicodeDecodeError:
                    return None, pos + 3 + length
            return None, pos + 3
        if tag == 0x73 and data[pos + 1 : pos + 5] == b"\x71\x00\x7e\x00":
            # boxed value object: TC_OBJECT + TC_REFERENCE(handle) + int32
            if pos + 11 <= n:
                return None, pos + 11
        return None, pos + 1

    patterns = (
        b"\x73\x71\x00\x7e\x00\x02",         # TC_OBJECT + back-reference
        b"\x73\x72",                         # TC_OBJECT + fresh class descriptor
    )
    for marker in patterns:
        i = 0
        while True:
            idx = data.find(marker, i)
            if idx < 0:
                break
            if marker.endswith(b"\x72"):
                end = data.find(b"\x78\x70", idx + 2, idx + 2 + 512)
                if end < 0 or end + 6 > n:
                    i = idx + 2
                    continue
                value = int.from_bytes(data[end + 2 : end + 6], "big", signed=True)
                text, nxt = parse_value(end + 6)
                i = max(nxt, idx + 2)
            else:
                if idx + 10 > n:
                    break
                value = int.from_bytes(data[idx + 6 : idx + 10], "big", signed=True)
                text, nxt = parse_value(idx + 10)
                i = max(nxt, idx + 10)
            if value is not None and text is not None and value not in out:
                out[value] = text
    return out


def _harvest_device_ids(db_path: str) -> List[str]:
    """Collect candidate device IDs near the account database.

    Old QQ reads the IMEI at runtime, so the obfuscation key equals the
    device ID that WeChat stores under ``MicroMsg/*/CompatibleInfo.cfg`` key
    258 (256 as the legacy variant). The harvest stays inside the acquired
    image: sibling app data directories of com.tencent.mobileqq only.
    """
    candidates: List[str] = []
    databases_dir = os.path.dirname(os.path.abspath(db_path))
    data_data = os.path.dirname(os.path.dirname(databases_dir))
    if os.path.isdir(data_data):
        mm_root = os.path.join(data_data, "com.tencent.mm", "MicroMsg")
        patterns = [
            os.path.join(mm_root, "CompatibleInfo.cfg"),
            os.path.join(mm_root, "*", "CompatibleInfo.cfg"),
            # MIUI-style backups keep per-account dirs under db/ or r/
            os.path.join(data_data, "com.tencent.mm", "db", "*", "CompatibleInfo.cfg"),
        ]
        for pattern in patterns:
            for cfg_path in glob.glob(pattern):
                strings = _java_cfg_strings(cfg_path)
                for key in (258, 256):
                    value = strings.get(key, "")
                    if value and len(value) >= 10:
                        candidates.append(value)
    return candidates


# --------------------------------------------------------------------- #
# XOR helpers
# --------------------------------------------------------------------- #

def xor_text(value: Any, key: bytes) -> bytes:
    if value is None:
        return b""
    raw = value.encode("utf-8") if isinstance(value, str) else bytes(value)
    if not key:
        return raw
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))


def decode_xored(value: Any, key: bytes) -> str:
    """XOR-decode a stored TEXT column into display text.

    UTF-8 wins when the plaintext round-trips; legacy builds stored GBK
    bytes, so GBK (with replacement) is the fallback.
    """
    raw = xor_text(value, key)
    if not raw:
        return ""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    text = raw.decode("gbk", errors="replace")
    # A truncated multibyte tail turns into U+FFFD; drop only trailing junk.
    return text.rstrip("\ufffd")


def validate_key(db_path: str, key: str) -> float:
    """Fraction of Friends.uin values that XOR-decode to a QQ number."""
    raw_key = key.encode("utf-8")
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute("SELECT uin FROM Friends WHERE uin IS NOT NULL").fetchall()
    except sqlite3.Error:
        return 0.0
    finally:
        con.close()
    if not rows:
        return 0.0
    hits = 0
    checked = 0
    for (uin,) in rows:
        if not uin:
            continue
        checked += 1
        plain = xor_text(uin, raw_key)
        if len(plain) >= 5 and all(0x30 <= c <= 0x39 for c in plain):
            hits += 1
    return hits / checked if checked else 0.0


def resolve_device_id(db_path: str, explicit: str = "") -> tuple[Optional[str], str]:
    """Return (device_id, how) trying the explicit value then image harvest."""
    tried: List[tuple[str, str]] = []
    if explicit:
        tried.append((explicit, "key_material.device_id"))
    tried.extend(
        (candidate, "CompatibleInfo.cfg(258/256)")
        for candidate in _harvest_device_ids(db_path)
    )
    seen: set[str] = set()
    for value, how in tried:
        if value in seen:
            continue
        seen.add(value)
        if validate_key(db_path, value) >= 0.8:
            return value, how
    return None, ""


# --------------------------------------------------------------------- #
# extraction
# --------------------------------------------------------------------- #

def _troop_table_map(con: sqlite3.Connection, key: bytes) -> Dict[str, str]:
    """md5(uin)-suffixed mr_troop table -> group uin."""
    mapping: Dict[str, str] = {}
    tables = {
        r[0]
        for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    for table in tables:
        if not table.startswith("mr_troop_") or not table.endswith("_New"):
            continue
        digest = table[len("mr_troop_") : -len("_New")].lower()
        for (troop_uin,) in con.execute(
            "SELECT DISTINCT troopuin FROM TroopMemberInfo WHERE troopuin IS NOT NULL"
        ):
            plain = xor_text(troop_uin, key)
            plain_s = plain.decode("utf-8", errors="replace")
            if hashlib.md5(plain_s.encode()).hexdigest().lower() == digest:
                mapping[table] = plain_s
                break
    return mapping


def extract_all(db_path: str, device_id: str) -> Dict[str, Any]:
    """Pull every recoverable artifact out of a legacy account database."""
    key = device_id.encode("utf-8")
    owner_uin = re.sub(r"\.db$", "", os.path.basename(db_path))
    con = sqlite3.connect(db_path)
    out: Dict[str, Any] = {
        "owner_uin": owner_uin,
        "device_id": device_id,
        "friends": [],
        "troops": [],
        "members": [],
        "messages": [],
    }
    try:
        for uin, name, remark in con.execute(
            "SELECT uin, name, remark FROM Friends"
        ):
            plain_uin = xor_text(uin, key).decode("utf-8", errors="replace")
            if not plain_uin.isdigit():
                continue
            out["friends"].append({
                "uin": plain_uin,
                "nickname": decode_xored(name, key),
                "remark": decode_xored(remark, key),
            })

        for troop_uin, troop_name in con.execute(
            "SELECT troopuin, troopname FROM TroopInfo"
        ):
            plain = xor_text(troop_uin, key).decode("utf-8", errors="replace")
            if not plain.isdigit():
                continue
            out["troops"].append({
                "uin": plain,
                "name": decode_xored(troop_name, key),
            })

        for troop_uin, member_uin, alias in con.execute(
            "SELECT troopuin, memberuin, alias FROM TroopMemberInfo"
        ):
            troop = xor_text(troop_uin, key).decode("utf-8", errors="replace")
            member = xor_text(member_uin, key).decode("utf-8", errors="replace")
            if not troop.isdigit() or not member.isdigit():
                continue
            out["members"].append({
                "troop": troop,
                "member": member,
                "alias": decode_xored(alias, key),
            })

        troop_tables = _troop_table_map(con, key)
        friend_tables = [
            t for t in (
                r[0]
                for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            )
            if t.startswith("mr_friend_") and t.endswith("_New")
        ]
        for table, group_uin in troop_tables.items():
            out["messages"].extend(
                _read_messages(con, table, key, group_uin=group_uin)
            )
        # The buddy list keeps a self row, so md5(owner) names a real roaming
        # table of self-addressed system records (pokes etc.) — no edge value.
        owner_digest = hashlib.md5(owner_uin.encode()).hexdigest().lower()
        for table in friend_tables:
            digest_part = table[len("mr_friend_"):-len("_New")].lower()
            if digest_part == owner_digest:
                continue
            out["messages"].extend(
                _read_messages(con, table, key, group_uin="")
            )
    finally:
        con.close()
    return out


def _read_messages(
    con: sqlite3.Connection, table: str, key: bytes, *, group_uin: str
) -> List[Dict[str, Any]]:
    """Read one mr_* roaming-message table into normalized dicts.

    Group tables key the conversation by ``group_uin``; friend tables carry
    the conversation peer in the ``frienduin`` column, which must be decoded
    as well or every private message loses its counterpart.
    """
    columns = {r[1] for r in con.execute(f'PRAGMA table_info("{table}")')}
    sender_col = "senderuin" if "senderuin" in columns else "frienduin"
    fields = [sender_col]
    for name in ("frienduin", "msgData", "time", "msgtype", "issend", "selfuin"):
        if name in columns and name not in fields:
            fields.append(name)
    rows: List[Dict[str, Any]] = []
    try:
        cursor = con.execute(f'SELECT {", ".join(fields)} FROM "{table}"')
    except sqlite3.Error as e:
        logger.warning("legacy qq: cannot read %s: %s", table, e)
        return rows
    for row in cursor:
        record = dict(zip(fields, row))
        sender = xor_text(record.get(sender_col), key).decode(
            "utf-8", errors="replace"
        )
        if not sender.isdigit():
            continue
        peer = group_uin
        if not peer and "frienduin" in record:
            candidate = xor_text(record.get("frienduin"), key).decode(
                "utf-8", errors="replace"
            )
            peer = candidate if candidate.isdigit() else sender
        msg_type = record.get("msgtype")
        try:
            msg_type = int(msg_type or 0)
        except (TypeError, ValueError):
            msg_type = 0
        # Only plain-text rows carry decodable msgData; every other type
        # stores binary (protobuf/XML) that must not leak into the graph.
        content = ""
        if msg_type == _MSG_TYPE_TEXT and record.get("msgData"):
            decoded = xor_text(record["msgData"], key)
            try:
                content = decoded.decode("utf-8")
            except UnicodeDecodeError:
                content = decoded.decode("utf-8", errors="replace")
        ts = record.get("time") or 0
        try:
            ts = int(ts)
        except (TypeError, ValueError):
            ts = 0
        is_send = 1 if record.get("issend") in (1, 2) else 0
        rows.append({
            "sender": sender,
            "peer": peer,
            "chatroom": group_uin,
            "timestamp": ts * 1000 if ts else None,
            "content": content,
            "msg_type": 1 if msg_type == _MSG_TYPE_TEXT else msg_type,
            "is_send": is_send,
        })
    return rows
