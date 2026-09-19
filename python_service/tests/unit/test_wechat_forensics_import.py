"""Tests for the WeChat forensics import pipeline (微信取证).

Covers the decrypt -> normalize -> query chain with a synthetic native
EnMicroMsg.db (message/rcontact/chatroom/userinfo), including:

  - encrypted input: page-level detection, password derivation, WAL replay
  - human-readable fields: group sender extraction, type labels, chatroom
    display names, contact kinds
  - graph.db normalization compatible with the WeChat analysis pipeline
"""

import hashlib
import os
import sqlite3
import struct
import tempfile
from pathlib import Path

import pytest

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from httpserver.services import wechat_decrypt
from httpserver.services.wechat_import_service import (
    WeChatImportService,
    decode_message_content,
    _strip_group_prefix,
)

OWNER_WXID = "wxid_ownertest22"
UIN = "1583567084"
IMEI = "1234567890ABCDEF"
PASSWORD = hashlib.md5((IMEI + UIN).encode()).hexdigest()[:7]

PAGE = 1024
RESERVE = 16
KDF_ITER = 4000


# ---------------------------------------------------------------------------
# synthetic native-schema database
# ---------------------------------------------------------------------------


def _build_plain_db(path: str) -> None:
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE userinfo (id INTEGER PRIMARY KEY, type INTEGER, value TEXT);
        CREATE TABLE rcontact (
            username TEXT PRIMARY KEY, alias TEXT, conRemark TEXT, nickname TEXT,
            type INTEGER, chatroomFlag INTEGER DEFAULT 0
        );
        CREATE TABLE chatroom (
            chatroomname TEXT PRIMARY KEY, displayname TEXT, chatroomnick TEXT,
            roomowner TEXT, memberlist TEXT, membercount INTEGER, addtime INTEGER
        );
        CREATE TABLE message (
            msgId INTEGER PRIMARY KEY AUTOINCREMENT, talker TEXT, content TEXT,
            createTime INTEGER, type INTEGER, isSend INTEGER DEFAULT 0, imgPath TEXT
        );
        """
    )
    con.execute("INSERT INTO userinfo (id, value) VALUES (2, ?)", (OWNER_WXID,))
    con.execute("INSERT INTO userinfo (id, value) VALUES (4, ?)", ("取证测试机主",))
    con.executemany(
        "INSERT INTO rcontact (username, alias, conRemark, nickname, type) VALUES (?,?,?,?,?)",
        [
            ("wxid_friend01", "", "测试好友甲", "好友甲昵称", 3),
            ("wxid_friend02", "", "", "好友乙", 4),
            ("gh_pubacct", "", "", "测试公众号", 33),
        ],
    )
    con.execute(
        "INSERT INTO chatroom VALUES (?,?,?,?,?,?,?)",
        ("12345@chatroom", "测试群聊", "", "wxid_friend01",
         "wxid_friend01;wxid_friend02;" + OWNER_WXID, 3, 1780000000000),
    )
    base = 1780000000000
    messages = [
        ("wxid_friend01", "你好，测试私聊", base + 1000, 1, 0),
        (OWNER_WXID, "收到，这是机主发出的消息", base + 2000, 1, 1),
        ("12345@chatroom", "wxid_friend01:\n群里的一条消息", base + 3000, 1, 0),
        ("12345@chatroom", OWNER_WXID + ":\n机主在群里发言", base + 4000, 1, 1),
        ("12345@chatroom", "wxid_friend02:\n<msg><img aeskey=\"aa\" md5=\"ff"
         "ee001122334455667788990011223344\" cdnthumburl=\"x\" cdnthumbheight=\"100\" "
         "cdnthumbwidth=\"100\" length=\"1234\"/></msg>", base + 5000, 3, 0),
        ("12345@chatroom", "wxid_friend01:\n"
         "<msg><appmsg><title>这是链接标题</title><type>5</type></appmsg></msg>",
         base + 6000, 49, 0),
        ("weixin", "欢迎回来", base + 7000, 1, 0),
        ("12345@chatroom", "\"好友甲昵称\" 撤回了一条消息", base + 8000, 10000, 0),
    ]
    con.executemany(
        "INSERT INTO message (talker, content, createTime, type, isSend) VALUES (?,?,?,?,?)",
        messages,
    )
    con.commit()
    # Match the real EnMicroMsg.db physical layout: 1024-byte pages with a
    # 16-byte reserve region per page (SQLCipher v1).  SQLite lays cells out
    # within the usable (page_size - reserve) area only when the reserve byte
    # (DB header offset 20) is set BEFORE the final VACUUM.
    con.execute("PRAGMA page_size = 1024")
    con.execute("VACUUM")
    con.close()

    raw = bytearray(Path(path).read_bytes())
    raw[20] = RESERVE  # reserved bytes per page
    Path(path).write_bytes(bytes(raw))

    con = sqlite3.connect(path)
    con.execute("VACUUM")  # re-layout cells within usable 1008-byte area
    con.execute("PRAGMA integrity_check")
    con.close()


def _encrypt_plain(plain_path: str, enc_path: str) -> str:
    """Encrypt a plaintext SQLite db with scheme-A params; returns the salt.

    Page 1 layout: 16-byte salt + ciphertext(plaintext[16:PAGE-16]) + IV;
    other pages: ciphertext(page[:PAGE-16]) + IV.
    """
    data = Path(plain_path).read_bytes()
    assert len(data) % PAGE == 0, "pad the synthetic db to page size first"
    salt = hashlib.sha256(b"tracelens-test-salt").digest()[:16]
    key = hashlib.pbkdf2_hmac("sha1", PASSWORD.encode(), salt, KDF_ITER, 32)
    out = bytearray(salt)

    def enc_body(body: bytes) -> bytes:
        iv = os.urandom(16)
        enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
        return enc.update(body) + enc.finalize() + iv

    out += enc_body(data[16 : PAGE - RESERVE])  # page 1 body after the salt
    for off in range(PAGE, len(data), PAGE):
        out += enc_body(data[off : off + PAGE - RESERVE])
    Path(enc_path).write_bytes(bytes(out))
    return salt


# ---------------------------------------------------------------------------
# decrypt module
# ---------------------------------------------------------------------------


class TestWeChatDecrypt:
    def test_detect_scheme_plaintext(self, tmp_path):
        db = str(tmp_path / "plain.db")
        _build_plain_db(db)
        hit = wechat_decrypt.detect_scheme(db, PASSWORD.encode())
        assert hit is not None and hit[0] == "plaintext"

    def test_detect_scheme_encrypted(self, tmp_path):
        plain = str(tmp_path / "plain.db")
        _build_plain_db(plain)
        # pad to page boundary for encryption
        size = os.path.getsize(plain)
        pad = PAGE - (size % PAGE)
        if pad:
            with open(plain, "ab") as f:
                f.write(b"\x00" * pad)
        enc = str(tmp_path / "enc.db")
        _encrypt_plain(plain, enc)
        assert wechat_decrypt.detect_scheme(enc, PASSWORD.encode()) is not None
        assert wechat_decrypt.detect_scheme(enc, b"wrongpw") is None

    def test_decrypt_roundtrip(self, tmp_path):
        plain = str(tmp_path / "plain.db")
        _build_plain_db(plain)
        size = os.path.getsize(plain)
        pad = PAGE - (size % PAGE)
        if pad:
            with open(plain, "ab") as f:
                f.write(b"\x00" * pad)
        enc = str(tmp_path / "enc.db")
        _encrypt_plain(plain, enc)
        out = str(tmp_path / "out.db")
        result = wechat_decrypt.decrypt_file(enc, out, PASSWORD.encode())
        assert result["scheme"] == "A"
        check = wechat_decrypt.verify_db(out)
        assert check["integrity"] == "ok"
        assert check["message"] == 8

    def test_derive_candidates(self):
        cands = wechat_decrypt.derive_candidates(UIN, IMEI, "wxid_x")
        formulas = {c["formula"] for c in cands}
        assert "MD5(IMEI+UIN)[:7]" in formulas
        assert "MD5(UIN+IMEI+wxid)[:7]" in formulas
        main = next(c for c in cands if c["formula"] == "MD5(IMEI+UIN)[:7]")
        assert main["password"] == PASSWORD


# ---------------------------------------------------------------------------
# decoding helpers
# ---------------------------------------------------------------------------


class TestDecodeContent:
    def test_group_sender_prefix(self):
        sender, text = _strip_group_prefix("wxid_abc:\n你好", "x@chatroom")
        assert sender == "wxid_abc" and text == "你好"
        sender, text = _strip_group_prefix("纯文本", "x@chatroom")
        assert sender == "" and text == "纯文本"

    def test_type_labels(self):
        assert decode_message_content(1, "hi", OWNER_WXID)["content_display"] == "hi"
        assert decode_message_content(47, "0:0:abc::0", OWNER_WXID)["content_display"] == "[动画表情]"
        assert decode_message_content(10000, "撤回了一条消息", OWNER_WXID)["content_display"] == "撤回了一条消息"
        img = decode_message_content(3, "<msg><img md5=\"ffeeddccbbaa99887766554433221100\" aeskey=\"k\"/></msg>", OWNER_WXID)
        assert img["content_display"] == "[图片]"
        assert img["media"]["kind"] == "image"
        app = decode_message_content(49, "<msg><appmsg><title>标题</title><type>5</type></appmsg></msg>", OWNER_WXID)
        assert "标题" in app["content_display"]


# ---------------------------------------------------------------------------
# import pipeline
# ---------------------------------------------------------------------------


@pytest.fixture()
def import_workspace(tmp_path, monkeypatch):
    """Point the import registry at a temp dir and yield (service, enc_db, key_material)."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    import httpserver.services.wechat_import_service as wis

    root = tmp_path / "imports"
    monkeypatch.setattr(wis, "import_root", lambda: (os.makedirs(root, exist_ok=True), str(root))[1])

    plain = str(tmp_path / "plain.db")
    _build_plain_db(plain)
    size = os.path.getsize(plain)
    pad = PAGE - (size % PAGE)
    if pad:
        with open(plain, "ab") as f:
            f.write(b"\x00" * pad)
    enc = str(tmp_path / "EnMicroMsg.db")
    _encrypt_plain(plain, enc)

    km = {"uin": UIN, "imei": IMEI, "wxid": OWNER_WXID, "account_dir": "testdir"}
    return WeChatImportService(), enc, km


class TestImportPipeline:
    def test_import_encrypted_with_derived_password(self, import_workspace):
        svc, enc, km = import_workspace
        result = svc._create_import_sync(
            enc, "测试导入", "", None, None, km, "unit-test",
        )
        assert result["status"] == "ready", result
        assert result["message_count"] == 8
        assert result["owner_username"] == OWNER_WXID
        assert result["decryption"]["scheme"] == "A"
        assert result["decryption"]["formula"] == "MD5(IMEI+UIN)[:7]"
        import_id = result["import_id"]

        # readable fields
        sessions = svc._sessions_sync(import_id)
        room = next(s for s in sessions if s["talker"] == "12345@chatroom")
        assert room["display_name"] == "测试群聊"
        assert room["kind"] == "group"

        msgs = svc._messages_sync(import_id, "12345@chatroom", None, None, None, None, 50, 0)
        group_sender = next(m for m in msgs["messages"] if m["content_display"] == "群里的一条消息")
        assert group_sender["sender"] == "wxid_friend01"
        assert group_sender["sender_name"] == "测试好友甲"
        owner_msg = next(m for m in msgs["messages"] if m["content_display"] == "机主在群里发言")
        assert owner_msg["direction"] == "send" and owner_msg["is_owner_sender"]

        img_msg = next(m for m in msgs["messages"] if m["base_type"] == 3)
        assert img_msg["type_label"] == "图片"
        assert img_msg["media"]["kind"] == "image"

        link_msg = next(m for m in msgs["messages"] if m["base_type"] == 49)
        assert "这是链接标题" in link_msg["content_display"]

        contacts = svc._contacts_sync(import_id)
        by_user = {c["username"]: c for c in contacts}
        assert by_user["wxid_friend01"]["kind"] == "好友"
        assert by_user["wxid_friend01"]["display_name"] == "测试好友甲"
        assert by_user["gh_pubacct"]["kind"] == "公众号"

        rooms = svc._chatrooms_sync(import_id)
        assert rooms[0]["display_name"] == "测试群聊"
        assert {m["display_name"] for m in rooms[0]["members"]} >= {"测试好友甲", "好友乙"}

        # graph.db is consumable by the existing analysis pipeline
        graph_db = svc._graph_db_path(import_id)
        con = sqlite3.connect(graph_db)
        assert con.execute("SELECT COUNT(*) FROM wechat_messages").fetchone()[0] == 8
        owner_row = con.execute("SELECT username, nickname FROM wechat_owner_info").fetchone()
        assert owner_row == (OWNER_WXID, "取证测试机主")
        con.close()

    def test_import_plaintext_no_password(self, import_workspace, tmp_path):
        svc, _enc, km = import_workspace
        plain = str(tmp_path / "plain_import.db")
        _build_plain_db(plain)
        result = svc._create_import_sync(plain, "明文导入", "", None, None, km, "unit-test")
        assert result["status"] == "ready"
        assert result["decryption"]["scheme"] == "plaintext"

    def test_wrong_key_material_fails(self, import_workspace):
        svc, enc, km = import_workspace
        bad_km = {**km, "uin": "9999999999"}  # derives a wrong password
        result = svc._create_import_sync(enc, "错误密钥", "", None, None, bad_km, "unit-test")
        assert result["status"] == "failed"
        assert "decryption failed" in (result["error"] or "")


class TestGraphDbAtomicAndHeal:
    """graph.db 构建失败不得留下空文件；缺失/空残留须能在读取路径自愈。

    背景：构建中断曾留下空 graph.db，图谱路由把它当有效数据返回 200 + 零节点
    （前端显示「未发现聊天记录关系数据」），而会话/消息 Tab 一切正常。
    """

    def test_failed_build_leaves_no_graph_db(self, tmp_path):
        svc = WeChatImportService()
        src = str(tmp_path / "bad.db")
        con = sqlite3.connect(src)
        con.execute("CREATE TABLE rcontact (username TEXT)")  # 缺 message 表
        con.commit()
        con.close()
        graph_db = str(tmp_path / "graph.db")
        with pytest.raises(sqlite3.OperationalError, match="missing required tables"):
            svc._build_graph_db("deadbeefdead", src, graph_db, {"owner": {}})
        assert not os.path.exists(graph_db)

    def test_failed_build_removes_temp_file(self, tmp_path, monkeypatch):
        import httpserver.services.wechat_import_service as wis

        svc = WeChatImportService()
        src = str(tmp_path / "plain.db")
        _build_plain_db(src)
        monkeypatch.setattr(
            wis, "decode_message_content",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        graph_db = str(tmp_path / "graph.db")
        with pytest.raises(RuntimeError, match="boom"):
            svc._build_graph_db(
                "deadbeefdead", src, graph_db, {"owner": {"username": OWNER_WXID}},
            )
        assert not os.path.exists(graph_db)
        assert not [p for p in os.listdir(tmp_path) if ".building" in p]

    def test_ensure_graph_db_heals_and_keeps(self, import_workspace):
        svc, enc, km = import_workspace
        result = svc._create_import_sync(enc, "演示导入", "", None, None, km, "unit-test")
        assert result["status"] == "ready"
        graph_db = svc._graph_db_path(result["import_id"])

        # 空残留（旧缺陷现场）→ 重建回全部消息
        con = sqlite3.connect(graph_db)
        con.execute("DELETE FROM wechat_messages")
        con.commit()
        con.close()
        healed = svc.ensure_graph_db(result["import_id"])
        con = sqlite3.connect(healed)
        assert con.execute("SELECT COUNT(*) FROM wechat_messages").fetchone()[0] == 8
        con.close()

        # 缺失 → 重建
        os.remove(graph_db)
        assert svc.ensure_graph_db(result["import_id"]) == graph_db
        con = sqlite3.connect(graph_db)
        assert con.execute("SELECT COUNT(*) FROM wechat_messages").fetchone()[0] == 8
        con.close()

        # 完好 → 原样返回，不触发重建
        before = os.path.getmtime(graph_db)
        assert svc.ensure_graph_db(result["import_id"]) == graph_db
        assert os.path.getmtime(graph_db) == before

    def test_ensure_without_decrypted_source_is_noop(self, import_workspace):
        svc, enc, km = import_workspace
        result = svc._create_import_sync(enc, "无源导入", "", None, None, km, "unit-test")
        graph_db = svc._graph_db_path(result["import_id"])
        wdir = os.path.dirname(graph_db)
        os.remove(graph_db)
        os.remove(os.path.join(wdir, "EnMicroMsg.db"))
        assert svc.ensure_graph_db(result["import_id"]) == graph_db
        assert not os.path.exists(graph_db)
