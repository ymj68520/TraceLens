"""Tests for the QQ forensics import pipeline (QQ 取证).

Covers the offline key derivation, NTQQ header parsing, SQLCipher decryption
and the normalize -> query chain with a synthetic nt_msg.db, including:

  - key chain: key = md5(md5(nt_uid) + rand), path hash = md5(md5(nt_uid) +
    "nt_kernel")
  - encrypted input: custom 1024B header strip, WAL replay, plaintext export
  - human-readable fields: protobuf message body text, nicknames, group names
  - graph.db normalization compatible with the WeChat analysis pipeline
"""

import hashlib
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from httpserver.services import qq_decrypt
from httpserver.services.qq_import_service import (
    QQImportService,
    decode_message_body,
)

NT_UID = "u_TestOwnerUid00000001"
OWNER_UIN = "2874289874"
RAND = "7VklrMEZ"
KEY = qq_decrypt.derive_key(NT_UID, RAND)


# ---------------------------------------------------------------------------
# protobuf helpers (build a MsgBody blob)
# ---------------------------------------------------------------------------


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        b = value & 0x7F
        value >>= 7
        if value:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _pb_varint(field: int, value: int) -> bytes:
    return _varint((field << 3) | 0) + _varint(value)


def _pb_bytes(field: int, data: bytes) -> bytes:
    return _varint((field << 3) | 2) + _varint(len(data)) + data


def build_msg_body(text: str, content_type: int = 1) -> bytes:
    """MsgBody{ content(40800): MsgContent{45002, 45101} }."""
    seg = _pb_varint(45001, 123456) + _pb_varint(45002, content_type)
    seg += _pb_varint(45102, 0)
    if text:
        seg += _pb_bytes(45101, text.encode("utf-8"))
    return _pb_bytes(40800, seg)


def build_qq_nt_header(rand: str, timestamp: int = 1786251550) -> bytes:
    """The 1024-byte custom QQ_NT DB header (protobuf inside)."""
    pb = _pb_bytes(2, rand.encode())
    pb += _pb_bytes(3, b"1.1.0.1")
    pb += _pb_bytes(4, b"HMAC_SHA1")
    pb += _pb_varint(5, timestamp)
    head = bytearray(1024)
    head[0:16] = b"SQLite header 3\x00"
    head[16:18] = (4096).to_bytes(2, "big")
    tag = b"QQ_NT DB"
    idx = 32
    head[idx : idx + len(tag)] = tag
    pos = idx + len(tag)
    head[pos : pos + 4] = len(pb).to_bytes(4, "little")
    pos += 4
    head[pos : pos + len(pb)] = pb
    return bytes(head)


# ---------------------------------------------------------------------------
# synthetic nt_db databases
# ---------------------------------------------------------------------------


def _build_plain_dbs(base: str) -> None:
    """Create nt_msg.db + profile_info.db + group_info.db with readable data."""
    con = sqlite3.connect(os.path.join(base, "nt_msg.db"))
    con.executescript(
        """
        CREATE TABLE "c2c_msg_table" (
            "40001" INTEGER PRIMARY KEY, "40002" INTEGER, "40003" INTEGER,
            "40010" INTEGER, "40011" INTEGER, "40013" INTEGER,
            "40020" TEXT, "40021" TEXT, "40030" INTEGER, "40033" INTEGER,
            "40050" INTEGER, "40090" TEXT, "40093" TEXT, "40800" BLOB
        );
        CREATE TABLE "group_msg_table" (
            "40001" INTEGER PRIMARY KEY, "40002" INTEGER, "40003" INTEGER,
            "40010" INTEGER, "40011" INTEGER, "40013" INTEGER,
            "40020" TEXT, "40021" TEXT, "40030" INTEGER, "40033" INTEGER,
            "40050" INTEGER, "40090" TEXT, "40093" TEXT, "40800" BLOB
        );
        CREATE TABLE "nt_uid_mapping_table" (
            "40021" TEXT, "40002" TEXT, "40003" TEXT, "40004" INTEGER
        );
        """
    )
    friend_uin, friend_uid = "2010741172", "u_TestFriend000000000001"
    group_id = "513977115"
    # private: friend -> owner
    con.execute(
        'INSERT INTO c2c_msg_table ("40001","40010","40011","40013","40020",'
        '"40021","40030","40033","40050","40093","40800") VALUES (?,?,?,?,?,?,?,?,?,?,?)',
        (1, 1, 2, 0, friend_uid, OWNER_UIN, friend_uin, friend_uin,
         1780000000, "测试好友甲", build_msg_body("你好，这是私聊文本")),
    )
    # private: owner -> friend
    con.execute(
        'INSERT INTO c2c_msg_table ("40001","40010","40011","40013","40020",'
        '"40021","40030","40033","40050","40093","40800") VALUES (?,?,?,?,?,?,?,?,?,?,?)',
        (2, 1, 2, 1, NT_UID, friend_uid, friend_uin, OWNER_UIN,
         1780000060, "机主", build_msg_body("收到，机主回复")),
    )
    # group: two members + owner send
    con.executemany(
        'INSERT INTO group_msg_table ("40001","40010","40011","40013","40020",'
        '"40021","40030","40033","40050","40090","40093","40800") VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
        [
            (11, 2, 2, 0, "u_GroupMemberA0000000001", group_id, group_id,
             "479234", 1780000120, "", "馒头", build_msg_body("群消息甲")),
            (12, 2, 2, 0, "u_GroupMemberB0000000001", group_id, group_id,
             "306656016", 1780000180, "", "TǒxIc", build_msg_body("群消息乙")),
            (13, 2, 2, 1, NT_UID, group_id, group_id, OWNER_UIN,
             1780000240, "机主群名片", "机主", build_msg_body("机主群发言")),
        ],
    )
    con.execute(
        'INSERT INTO nt_uid_mapping_table ("40021","40004") VALUES (?,?)',
        (friend_uid, friend_uin),
    )
    con.commit()
    con.close()

    con = sqlite3.connect(os.path.join(base, "profile_info.db"))
    con.executescript(
        'CREATE TABLE "profile_info_v6" ("1000" TEXT, "1002" TEXT, "20002" TEXT);'
        'CREATE TABLE "buddy_list" ("1000" TEXT, "1001" TEXT, "1002" TEXT);'
    )
    con.execute(
        'INSERT INTO profile_info_v6 ("1000","1002","20002") VALUES (?,?,?)',
        (friend_uid, friend_uin, "好友甲昵称"),
    )
    con.execute(
        'INSERT INTO buddy_list ("1000","1002") VALUES (?,?)',
        (friend_uid, friend_uin),
    )
    con.commit()
    con.close()

    con = sqlite3.connect(os.path.join(base, "group_info.db"))
    con.executescript(
        'CREATE TABLE "group_list" ("60001" TEXT, "60007" TEXT, "60011" INTEGER);'
    )
    con.execute(
        'INSERT INTO group_list ("60001","60007","60011") VALUES (?,?,?)',
        (group_id, "测试群聊", 3),
    )
    con.commit()
    con.close()


def _encrypt_db(plain_dir: str, enc_dir: str) -> None:
    """Encrypt nt_msg.db via sqlcipher with the derived key + prepend header."""
    sqlcipher3 = pytest.importorskip("sqlcipher3")
    os.makedirs(enc_dir, exist_ok=True)
    for name in ("nt_msg.db", "profile_info.db", "group_info.db"):
        src = os.path.join(plain_dir, name)
        enc = os.path.join(enc_dir, name)
        conn = sqlcipher3.connect(enc)
        conn.execute("ATTACH DATABASE ? AS plaintext KEY '';", (src,))
        conn.execute("PRAGMA cipher_page_size = 4096;")
        conn.execute(f"PRAGMA key = '{KEY}';")
        conn.execute("PRAGMA kdf_iter = 4000;")
        conn.execute("PRAGMA cipher_hmac_algorithm = HMAC_SHA1;")
        conn.execute("PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512;")
        conn.execute("SELECT sqlcipher_export('main', 'plaintext');")
        conn.execute("DETACH DATABASE plaintext;")
        conn.close()
        body = open(enc, "rb").read()
        open(enc, "wb").write(build_qq_nt_header(RAND) + body)


# ---------------------------------------------------------------------------
# tests: key derivation & header parsing
# ---------------------------------------------------------------------------


def test_key_derivation_chain():
    assert qq_decrypt.uid_hash(NT_UID) == hashlib.md5(NT_UID.encode()).hexdigest()
    assert qq_decrypt.path_hash(NT_UID) == hashlib.md5(
        (hashlib.md5(NT_UID.encode()).hexdigest() + "nt_kernel").encode()
    ).hexdigest()
    assert qq_decrypt.derive_key(NT_UID, RAND) == hashlib.md5(
        (hashlib.md5(NT_UID.encode()).hexdigest() + RAND).encode()
    ).hexdigest()
    assert len(KEY) == 32


def test_header_parse():
    hdr = build_qq_nt_header(RAND)
    info = qq_decrypt.parse_header(hdr)
    assert info["present"] is True
    assert info["rand"] == RAND
    assert info["version"] == "1.1.0.1"
    assert info["hmac_algorithm"] == "HMAC_SHA1"
    assert info["timestamp"] == 1786251550
    # plaintext sqlite has no custom header
    assert qq_decrypt.parse_header(b"SQLite format 3\x00" + b"\x00" * 100)["present"] is False


def test_message_body_decode():
    body = decode_message_body(build_msg_body("你好世界"))
    assert body["content_display"] == "你好世界"
    assert body["content_type"] == 1
    assert body["media"] is None
    img = decode_message_body(build_msg_body("", content_type=2))
    assert img["media"] == {"kind": "image"}
    assert decode_message_body(b"")["content_display"] == ""


# ---------------------------------------------------------------------------
# tests: decryption
# ---------------------------------------------------------------------------


@pytest.fixture()
def qq_dirs(tmp_path: Path):
    plain = tmp_path / "plain"
    enc = tmp_path / "enc"
    plain.mkdir()
    _build_plain_dbs(str(plain))
    _encrypt_db(str(plain), str(enc))
    return plain, enc, tmp_path


def test_verify_key_roundtrip(qq_dirs):
    plain, enc, _ = qq_dirs
    assert qq_decrypt.verify_key(str(enc / "nt_msg.db"), KEY) is True
    assert qq_decrypt.verify_key(str(enc / "nt_msg.db"), "0" * 32) is False
    # plaintext files validate without a key
    assert qq_decrypt.verify_key(str(plain / "nt_msg.db"), "") is True


def test_decrypt_file(qq_dirs):
    plain, enc, tmp = qq_dirs
    out = tmp / "decrypted.db"
    stats = qq_decrypt.decrypt_file(str(enc / "nt_msg.db"), str(out), KEY)
    assert stats["header"]["rand"] == RAND
    assert qq_decrypt.verify_db(str(out))["integrity"] == "ok"
    con = sqlite3.connect(out)
    n = con.execute('SELECT COUNT(*) FROM "group_msg_table"').fetchone()[0]
    con.close()
    assert n == 3


def test_decrypt_wrong_key(qq_dirs):
    plain, enc, tmp = qq_dirs
    out = tmp / "bad.db"
    with pytest.raises(qq_decrypt.QQDecryptError):
        qq_decrypt.decrypt_file(str(enc / "nt_msg.db"), str(out), "f" * 32)
    assert not out.exists()


# ---------------------------------------------------------------------------
# tests: import service end-to-end
# ---------------------------------------------------------------------------


@pytest.fixture()
def import_env(qq_dirs, monkeypatch):
    plain, enc, tmp = qq_dirs
    storage = tmp / "storage"
    storage.mkdir()
    monkeypatch.setattr(
        "httpserver.services.qq_import_service.import_root",
        lambda: str(storage),
    )
    return enc


@pytest.mark.asyncio
async def test_import_creates_readable_data(import_env):
    svc = QQImportService()
    result = await svc.create_import({
        "db_path": str(import_env / "nt_msg.db"),
        "name": "测试 QQ 导入",
        "key_material": {"nt_uid": NT_UID, "uin": OWNER_UIN},
    })
    assert result["status"] == "ready", result
    assert result["decryption"]["integrity"] == "ok"
    assert result["decryption"]["scheme"] == "SQLCipher4"
    assert result["owner"]["username"] == OWNER_UIN
    assert result["stats"]["c2c_messages"] == 2
    assert result["stats"]["group_messages"] == 3

    import_id = result["import_id"]
    overview = await svc.overview(import_id)
    assert overview["owner"]["username"] == OWNER_UIN
    assert overview["key_material"]["key"].startswith(KEY[:8])

    sessions = await svc.sessions(import_id)
    kinds = {(s["kind"], s["display_name"]) for s in sessions}
    assert ("group", "测试群聊") in kinds
    assert ("private", "好友甲昵称") in kinds

    msgs = await svc.messages(import_id)
    assert msgs["total"] == 5
    texts = [m["content_display"] for m in msgs["messages"]]
    assert "你好，这是私聊文本" in texts
    assert "机主群发言" in texts
    group_msg = next(m for m in msgs["messages"] if m["is_group"])
    assert group_msg["sender_name"] == "馒头"

    contacts = await svc.contacts(import_id)
    assert any(c["nickname"] == "好友甲昵称" for c in contacts)

    rooms = await svc.chatrooms(import_id)
    assert rooms[0]["display_name"] == "测试群聊"
    assert "馒头" in rooms[0]["members_preview"]

    # graph.db plugs into the wechat_* analysis schema
    graph_db = svc._graph_db_path(import_id)
    assert os.path.isfile(graph_db)
    con = sqlite3.connect(graph_db)
    con.row_factory = sqlite3.Row
    owner = con.execute(
        "SELECT username, nickname FROM wechat_owner_info"
    ).fetchone()
    assert owner["username"] == OWNER_UIN
    msgs_n = con.execute("SELECT COUNT(*) FROM wechat_messages").fetchone()[0]
    assert msgs_n == 5
    contacts_n = con.execute(
        "SELECT COUNT(*) FROM wechat_contacts WHERE username = ?", (str(2010741172),)
    ).fetchone()[0]
    assert contacts_n == 1
    rooms_n = con.execute("SELECT COUNT(*) FROM wechat_chatrooms").fetchone()[0]
    assert rooms_n == 1
    con.close()


@pytest.mark.asyncio
async def test_graph_db_self_heal_rebuilds_empty(import_env):
    """导入期建图失败留下的 schema-only graph.db 在读侧被兜底重建。"""
    svc = QQImportService()
    result = await svc.create_import({
        "db_path": str(import_env / "nt_msg.db"),
        "name": "自愈测试",
        "key_material": {"nt_uid": NT_UID, "uin": OWNER_UIN},
    })
    assert result["status"] == "ready", result
    import_id = result["import_id"]
    graph_db = svc._graph_db_path(import_id)

    con = sqlite3.connect(graph_db)
    con.executescript(
        "DELETE FROM wechat_messages; DELETE FROM wechat_contacts; "
        "DELETE FROM wechat_chatrooms; DELETE FROM wechat_owner_info;"
    )
    con.commit()
    con.close()

    await svc.ensure_graph_db(import_id)
    con = sqlite3.connect(graph_db)
    msgs_n = con.execute("SELECT COUNT(*) FROM wechat_messages").fetchone()[0]
    rooms_n = con.execute("SELECT COUNT(*) FROM wechat_chatrooms").fetchone()[0]
    con.close()
    assert (msgs_n, rooms_n) == (5, 1)


@pytest.mark.asyncio
async def test_import_without_nt_uid_fails(import_env):
    svc = QQImportService()
    result = await svc.create_import({
        "db_path": str(import_env / "nt_msg.db"),
        "key_material": {"uin": OWNER_UIN},
    })
    assert result["status"] == "failed"
    assert "nt_uid" in (result["error"] or "")


@pytest.mark.asyncio
async def test_import_wrong_key_fails(import_env):
    svc = QQImportService()
    result = await svc.create_import({
        "db_path": str(import_env / "nt_msg.db"),
        "password": "0" * 32,
        "key_material": {"nt_uid": NT_UID},
    })
    assert result["status"] == "failed"
    assert "密钥" in (result["error"] or "") or "failed" in (result["error"] or "")


@pytest.mark.asyncio
async def test_import_plaintext_db(import_env, monkeypatch, tmp_path):
    plain = tmp_path / "plain2"
    plain.mkdir()
    _build_plain_dbs(str(plain))
    svc = QQImportService()
    result = await svc.create_import({
        "db_path": str(plain / "nt_msg.db"),
        "name": "明文导入",
        "key_material": {"uin": OWNER_UIN},
    })
    assert result["status"] == "ready", result
    msgs = await svc.messages(result["import_id"])
    assert msgs["total"] == 5
