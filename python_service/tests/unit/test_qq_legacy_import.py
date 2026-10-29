"""Tests for legacy mobile QQ 4.x account database imports (pre-NTQQ).

Covers the device-id XOR obfuscation reversal and the import -> graph.db
chain with a synthetic ``<uin>.db`` carrying the same tables as a real
acquisition (Friends / TroopInfo / TroopMemberInfo / mr_troop_*_New), plus
the CompatibleInfo.cfg harvest used to recover the device id from an image.
"""

import os
import sqlite3

import pytest

from httpserver.services import qq_legacy
from httpserver.services.qq_import_service import QQImportService

DEVICE_ID = "a00000420ce2b6"
OWNER_UIN = "2950002133"


def _xor_bytes(value: str) -> bytes:
    key = DEVICE_ID.encode()
    raw = value.encode("utf-8")
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))


def _xor(value: str) -> bytes:
    """Ciphertext as stored by the legacy client (TEXT columns, raw bytes)."""
    return _xor_bytes(value)


@pytest.fixture
def legacy_db(tmp_path):
    """A synthetic pre-NTQQ account database + sibling WeChat cfg."""
    db_path = tmp_path / "com.tencent.mobileqq" / "databases"
    db_path.mkdir(parents=True)
    mm = tmp_path / "com.tencent.mm" / "MicroMsg"
    mm.mkdir(parents=True)
    _write_compatible_info_cfg(mm / "CompatibleInfo.cfg")

    path = db_path / f"{OWNER_UIN}.db"
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE Friends (
            _id INTEGER PRIMARY KEY, uin TEXT, name TEXT, remark TEXT,
            groupid INTEGER, faceid INTEGER
        );
        CREATE TABLE TroopInfo (
            _id INTEGER PRIMARY KEY, troopuin TEXT, troopname TEXT
        );
        CREATE TABLE TroopMemberInfo (
            _id INTEGER PRIMARY KEY, troopuin TEXT, memberuin TEXT, alias TEXT
        );
        CREATE TABLE recent (
            _id INTEGER PRIMARY KEY, uin TEXT, time INTEGER, type INTEGER
        );
        """
    )
    con.execute("INSERT INTO Friends VALUES (1, ?, ?, '', 0, 1)",
                (_xor("10086"), _xor("测试好友")))
    con.execute("INSERT INTO Friends VALUES (2, ?, ?, ?, 0, 2)",
                (_xor(OWNER_UIN), _xor("自己"), _xor("备注名")))
    con.execute("INSERT INTO Friends VALUES (3, ?, ?, '', 0, 3)",
                (_xor("95588"), _xor(" Connie... ")))
    con.execute("INSERT INTO TroopInfo VALUES (1, ?, ?)",
                (_xor("138572917"), _xor("测试群")))
    con.execute("INSERT INTO TroopMemberInfo VALUES (1, ?, ?, '')",
                (_xor("138572917"), _xor("10086")))
    con.execute("INSERT INTO TroopMemberInfo VALUES (2, ?, ?, ?)",
                (_xor("138572917"), _xor(OWNER_UIN), _xor("群名片")))
    # one roaming group-chat table keyed by md5("138572917")
    con.execute(
        "CREATE TABLE mr_troop_274729BD2282459A939B5AB6B52CEE6C_New ("
        "_id INTEGER PRIMARY KEY, frienduin TEXT, senderuin TEXT, msgData TEXT, "
        "time INTEGER, msgtype INTEGER, issend INTEGER)"
    )
    con.execute(
        "INSERT INTO mr_troop_274729BD2282459A939B5AB6B52CEE6C_New "
        "VALUES (1, ?, ?, ?, 1395307323, -1000, 0)",
        (_xor("138572917"), _xor("10086"), _xor("所以老师要好好教导下")),
    )
    con.execute(
        "INSERT INTO mr_troop_274729BD2282459A939B5AB6B52CEE6C_New "
        "VALUES (2, ?, ?, ?, 1395307325, -1000, 1)",
        (_xor("138572917"), _xor(OWNER_UIN), _xor("傻孩子")),
    )
    # private roaming messages: mr_friend_<md5(peer)>
    import hashlib
    friend_md5 = hashlib.md5(b"10086").hexdigest().upper()
    con.execute(
        f"CREATE TABLE mr_friend_{friend_md5}_New ("
        "_id INTEGER PRIMARY KEY, frienduin TEXT, senderuin TEXT, msgData TEXT, "
        "time INTEGER, msgtype INTEGER, issend INTEGER)"
    )
    con.execute(
        f"INSERT INTO mr_friend_{friend_md5}_New VALUES (1, ?, ?, ?, 1395400000, -1000, 0)",
        (_xor("10086"), _xor("10086"), _xor("在吗")),
    )
    con.execute(
        f"INSERT INTO mr_friend_{friend_md5}_New VALUES (2, ?, ?, ?, 1395400060, -1000, 1)",
        (_xor("10086"), _xor(OWNER_UIN), _xor("在的，什么事")),
    )
    con.commit()
    con.close()
    return str(path)


def _write_compatible_info_cfg(path) -> None:
    """Minimal Java-serialized HashMap with Integer(258)->device-id string."""
    data = bytearray()
    data += b"\xac\xed\x00\x05"                      # stream magic/version
    data += b"\x73\x72\x00\x11" + b"java.util.HashMap"
    data += b"\x05\x07\xda\xc1\xc3\x16\x60\xd1\x03\x00\x01\x46\x00\x0a"
    data += b"loadFactor"
    data += b"\x78\x70\x3f\x40\x00\x00"
    data += b"\x77\x08\x00\x00\x00\x01"              # block data, 1 entry
    data += b"\x73\x72\x00\x11" + b"java.lang.Integer"
    data += b"\x12\xe2\xa0\xa4\xf7\x81\x87\x38\x02\x00\x01\x49\x00\x05"
    data += b"value"
    data += b"\x78\x70\x00\x00\x01\x02"              # Integer(258)
    text = DEVICE_ID.encode()
    data += b"\x74" + len(text).to_bytes(2, "big") + text
    path.write_bytes(bytes(data))


# ---------------------------------------------------------------------------
# detection / key resolution
# ---------------------------------------------------------------------------


def test_looks_legacy_qq4_detects_account_db(legacy_db):
    assert qq_legacy.looks_legacy_qq4(legacy_db)


def test_looks_legacy_qq4_rejects_other_databases(tmp_path):
    plain = tmp_path / "plain.db"
    con = sqlite3.connect(plain)
    con.execute("CREATE TABLE t (a)")
    con.commit()
    con.close()
    assert not qq_legacy.looks_legacy_qq4(str(plain))
    assert not qq_legacy.looks_legacy_qq4(str(tmp_path / "missing.db"))


def test_harvest_device_id_from_sibling_cfg(legacy_db):
    candidates = qq_legacy._harvest_device_ids(legacy_db)
    assert DEVICE_ID in candidates


def test_resolve_device_id_picks_valid_key(legacy_db):
    device_id, how = qq_legacy.resolve_device_id(legacy_db)
    assert device_id == DEVICE_ID
    assert "CompatibleInfo" in how


def test_resolve_device_id_prefers_explicit(legacy_db):
    device_id, _ = qq_legacy.resolve_device_id(
        legacy_db, "000000000000000"
    )
    # the explicit candidate fails validation (uins stop being digits), so the
    # harvest fallback wins
    assert device_id == DEVICE_ID


# ---------------------------------------------------------------------------
# extraction
# ---------------------------------------------------------------------------


def test_extract_all_decodes_uins_and_messages(legacy_db):
    device_id, _ = qq_legacy.resolve_device_id(legacy_db)
    data = qq_legacy.extract_all(legacy_db, device_id)
    assert data["owner_uin"] == OWNER_UIN
    uins = {f["uin"] for f in data["friends"]}
    assert {"10086", OWNER_UIN, "95588"} <= uins
    assert [t["uin"] for t in data["troops"]] == ["138572917"]
    members = {(m["troop"], m["member"]) for m in data["members"]}
    assert ("138572917", "10086") in members
    assert ("138572917", OWNER_UIN) in members


def test_non_text_message_types_keep_binary_out_of_content(legacy_db):
    con = sqlite3.connect(legacy_db)
    con.execute(
        "INSERT INTO mr_troop_274729BD2282459A939B5AB6B52CEE6C_New "
        "VALUES (3, ?, ?, ?, 1395307330, -2000, 0)",
        (_xor("138572917"), _xor("10086"), b"\x00\x01\x02proto"),
    )
    con.commit()
    rows = qq_legacy._read_messages(
        con, "mr_troop_274729BD2282459A939B5AB6B52CEE6C_New",
        DEVICE_ID.encode(), group_uin="138572917",
    )
    non_text = [r for r in rows if r["msg_type"] == -2000]
    assert non_text and non_text[0]["sender"] == "10086"
    assert non_text[0]["peer"] == "138572917"
    assert non_text[0]["content"] == ""          # binary stays out
    con.close()


# ---------------------------------------------------------------------------
# import service end-to-end
# ---------------------------------------------------------------------------


def test_legacy_import_creates_graph_db_and_reads(legacy_db):
    svc = QQImportService()
    summary = svc._create_import_sync({"db_path": legacy_db, "name": "老QQ"})
    assert summary["status"] == "ready", summary
    assert summary["format"] == "legacy_qq4"
    assert summary["stats"]["messages"] >= 0

    import_id = summary["import_id"]
    overview = svc._overview_sync(import_id)
    assert overview["owner"]["username"] == OWNER_UIN
    assert overview["decryption"]["scheme"].startswith("XOR")

    sessions = svc._sessions_sync(import_id)
    kinds = {s["kind"] for s in sessions}
    assert "group" in kinds

    messages = svc._messages_sync(
        import_id, talker=None, keyword=None, msg_type=None,
        start_ts=None, end_ts=None, limit=50, offset=0,
    )
    assert messages["total"] == 4
    texts = [m["content_display"] for m in messages["messages"]]
    assert "所以老师要好好教导下" in texts
    assert "傻孩子" in texts
    private = [m for m in messages["messages"] if not m["is_group"]]
    assert len(private) == 2
    assert {m["talker"] for m in private} == {"10086"}
    sent_private = [m for m in private if m["direction"] == "send"]
    assert sent_private and sent_private[0]["content_display"] == "在的，什么事"
    received = [m for m in private if m["direction"] == "receive"]
    assert received and received[0]["sender"] == "10086"

    sessions = svc._sessions_sync(import_id)
    private_sessions = [s for s in sessions if s["kind"] == "private"]
    assert any(s["talker"] == "10086" and s["msg_count"] == 2
               for s in private_sessions)

    keyword = svc._messages_sync(
        import_id, talker=None, keyword="傻孩子", msg_type=None,
        start_ts=None, end_ts=None, limit=10, offset=0,
    )
    assert keyword["total"] == 1

    contacts = svc._contacts_sync(import_id)
    usernames = {c["username"] for c in contacts}
    assert "10086" in usernames

    rooms = svc._chatrooms_sync(import_id)
    assert any(r["chatroom_name"] == "138572917" for r in rooms)
    assert rooms and rooms[0]["member_count"] == 2


def test_legacy_import_without_device_id_fails_with_hint(tmp_path):
    con = sqlite3.connect(tmp_path / f"{OWNER_UIN}.db")
    con.execute("CREATE TABLE Friends (uin TEXT, name TEXT)")
    con.execute("CREATE TABLE TroopMemberInfo (troopuin TEXT, memberuin TEXT)")
    con.commit()
    con.close()
    svc = QQImportService()
    summary = svc._create_import_sync({"db_path": str(tmp_path / f"{OWNER_UIN}.db")})
    assert summary["status"] == "failed"
    assert "设备ID" in (summary["error"] or "")
