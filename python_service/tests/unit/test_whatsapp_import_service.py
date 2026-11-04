"""Unit tests for the iOS WhatsApp import service.

Fixtures build a minimal ChatStorage.sqlite (Core Data ZWAMESSAGE /
ZWACHATSESSION) plus ContactsV2 / CallHistory siblings, so the tests never
depend on case evidence.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from httpserver.services import whatsapp_import_service as wa


def _make_chat_store(path: Path, *, messages, sessions, with_type=True) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE ZWACHATSESSION(
            Z_PK INTEGER PRIMARY KEY, ZPARTNERNAME TEXT, ZCONTACTJID TEXT,
            ZLASTMESSAGEDATE INTEGER
        );
        """
    )
    type_column = ", ZMESSAGETYPE INTEGER" if with_type else ""
    connection.execute(
        "CREATE TABLE ZWAMESSAGE(Z_PK INTEGER PRIMARY KEY, ZISFROMME INTEGER,"
        " ZMESSAGEDATE INTEGER, ZTEXT TEXT, ZCHATSESSION INTEGER,"
        " ZFROMJID TEXT, ZTOJID TEXT, ZPUSHNAME TEXT" + type_column + ")"
    )
    for primary_key, partner, jid, last in sessions:
        connection.execute(
            "INSERT INTO ZWACHATSESSION VALUES(?,?,?,?)",
            (primary_key, partner, jid, last),
        )
    for row in messages:
        if with_type:
            connection.execute(
                "INSERT INTO ZWAMESSAGE(Z_PK, ZISFROMME, ZMESSAGEDATE, ZTEXT,"
                " ZCHATSESSION, ZFROMJID, ZTOJID, ZPUSHNAME, ZMESSAGETYPE)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                row,
            )
        else:
            connection.execute(
                "INSERT INTO ZWAMESSAGE(Z_PK, ZISFROMME, ZMESSAGEDATE, ZTEXT,"
                " ZCHATSESSION, ZFROMJID, ZTOJID, ZPUSHNAME) VALUES(?,?,?,?,?,?,?,?)",
                row,
            )
    connection.commit()
    connection.close()


@pytest.fixture()
def chat_dir(tmp_path: Path) -> Path:
    """A WhatsApp backup directory with chat, contacts and call stores."""
    chat = tmp_path / "ChatStorage.sqlite"
    _make_chat_store(
        chat,
        sessions=[
            (1, "+91 70502 43722", "917050243722@s.whatsapp.net", 718590014),
            (2, "Healthy Motivation", "918577977754-1490944139@g.us", 718584463),
        ],
        messages=[
            # (Z_PK, ZISFROMME, ZMESSAGEDATE, ZTEXT, ZCHATSESSION,
            #  ZFROMJID, ZTOJID, ZPUSHNAME, ZMESSAGETYPE)
            (1, 0, 715157772, "hello there", 1, "917050243722@s.whatsapp.net", None, "IGNORED=", 0),
            (2, 1, 715160000, "reply from me", 1, None, "917050243722@s.whatsapp.net", "", 0),
            (3, 0, 715170000, "group hi", 2, "85257254011@s.whatsapp.net", None, "IGNORED=", 0),
            (4, 0, 715180000, None, 2, "85257254011@s.whatsapp.net", None, "", 6),
        ],
    )

    contacts = tmp_path / "ContactsV2.sqlite"
    connection = sqlite3.connect(contacts)
    connection.execute(
        "CREATE TABLE ZWAADDRESSBOOKCONTACT(Z_PK INTEGER PRIMARY KEY,"
        " ZPHONENUMBER TEXT, ZGIVENNAME TEXT, ZFAMILYNAME TEXT)"
    )
    connection.execute("INSERT INTO ZWAADDRESSBOOKCONTACT VALUES(1,'917050243722','Test','Peer')")
    connection.commit()
    connection.close()

    calls = tmp_path / "CallHistory.sqlite"
    connection = sqlite3.connect(calls)
    connection.execute(
        "CREATE TABLE ZWACDCALLEVENT(Z_PK INTEGER PRIMARY KEY, ZDATE INTEGER,"
        " ZDURATION REAL, ZOUTCOME INTEGER, ZGROUPJIDSTRING TEXT)"
    )
    connection.execute(
        "CREATE TABLE ZWACDCALLEVENTPARTICIPANT(Z_PK INTEGER PRIMARY KEY,"
        " Z_FOK_1PARTICIPANTS INTEGER, ZJIDSTRING TEXT)"
    )
    connection.execute("INSERT INTO ZWACDCALLEVENT VALUES(1,715157772,42.0,1,'')")
    connection.execute("INSERT INTO ZWACDCALLEVENTPARTICIPANT VALUES(1,1,'917050243722@s.whatsapp.net')")
    connection.commit()
    connection.close()
    return tmp_path


# ------------------------------------------------------------------ timestamps

def test_apple_seconds_convert_to_unix():
    assert wa.apple_to_unix(715157772) == 1693464972


def test_apple_nanoseconds_convert_to_unix():
    assert wa.apple_to_unix(715157772646219008) == 1693464972


def test_unix_seconds_pass_through():
    assert wa.apple_to_unix(1693464972) == 1693464972


def test_zero_and_invalid_timestamps_are_zero():
    assert wa.apple_to_unix(0) == 0
    assert wa.apple_to_unix(-1) == 0
    assert wa.apple_to_unix(None) == 0
    assert wa.apple_to_unix("nonsense") == 0


# -------------------------------------------------------------------- import

def test_import_normalises_chat_contacts_and_calls(chat_dir: Path):
    service = wa.WhatsAppImportService()
    result = service.create_import({"db_path": str(chat_dir), "name": "fixture"})

    assert result["status"] == "ready"
    stats = result["stats"]
    # 4 chat messages + 1 call event surfaced as a message.
    assert stats["total_messages"] == 4
    assert stats["c2c_messages"] == 2
    assert stats["group_messages"] == 2
    assert stats["sessions"] == 2
    assert stats["groups"] == 1
    assert stats["calls"] == 1

    import_id = result["import_id"]
    messages = service.messages(import_id, page_size=100)
    assert messages["total"] == 5  # 4 messages + 1 call

    records = {m["content"]: m for m in messages["records"] if m["content"]}
    assert "hello there" in records
    assert records["hello there"]["is_send"] is False
    assert records["reply from me"]["is_send"] is True
    # Apple-epoch seconds converted to Unix seconds.
    assert records["hello there"]["timestamp"] == 1693464972


def test_group_membership_message_keeps_a_label(chat_dir: Path):
    service = wa.WhatsAppImportService()
    result = service.create_import({"db_path": str(chat_dir)})
    messages = service.messages(result["import_id"], page_size=100)
    # Type 6 carries no text; the parser substitutes the type label so the row
    # is not silently blank.
    assert any(m["content"] == "群成员变动" for m in messages["records"])


def test_pushname_ciphertext_is_not_used_as_identity(chat_dir: Path):
    service = wa.WhatsAppImportService()
    result = service.create_import({"db_path": str(chat_dir)})
    messages = service.messages(result["import_id"], page_size=100)
    for message in messages["records"]:
        # ZPUSHNAME in a real store is base64 ciphertext; it must never surface
        # as a display name.
        assert "IGNORED=" not in message["sender"]
        assert "IGNORED=" not in message["sender_nickname"]


def test_sessions_expose_readable_group_names(chat_dir: Path):
    service = wa.WhatsAppImportService()
    result = service.create_import({"db_path": str(chat_dir)})
    sessions = service.sessions(result["import_id"])
    by_name = {s["display_name"]: s for s in sessions}
    assert "Healthy Motivation" in by_name
    assert by_name["Healthy Motivation"]["is_group"] is True
    assert by_name["Healthy Motivation"]["msg_count"] == 2


def test_contacts_come_from_sessions_and_address_book(chat_dir: Path):
    service = wa.WhatsAppImportService()
    result = service.create_import({"db_path": str(chat_dir)})
    contacts = service.contacts(result["import_id"])
    numbers = {c["mobile"] for c in contacts}
    assert "917050243722" in numbers


def test_messages_filter_by_keyword(chat_dir: Path):
    service = wa.WhatsAppImportService()
    result = service.create_import({"db_path": str(chat_dir)})
    filtered = service.messages(result["import_id"], keyword="group hi")
    assert filtered["total"] == 1
    assert filtered["records"][0]["content"] == "group hi"


def test_messages_filter_by_talker(chat_dir: Path):
    service = wa.WhatsAppImportService()
    result = service.create_import({"db_path": str(chat_dir)})
    filtered = service.messages(
        result["import_id"], talker="917050243722@s.whatsapp.net", page_size=100
    )
    # Two chat messages plus the call event on the same peer.
    assert filtered["total"] == 3


def test_overview_reports_type_and_day_stats(chat_dir: Path):
    service = wa.WhatsAppImportService()
    result = service.create_import({"db_path": str(chat_dir)})
    overview = service.overview(result["import_id"])
    assert overview["stats"]["total_messages"] == 4
    assert overview["day_stats"]
    assert overview["type_stats"]
    assert overview["decryption"]["scheme"] == "none"


def test_import_accepts_the_chat_file_directly(chat_dir: Path):
    service = wa.WhatsAppImportService()
    result = service.create_import({"db_path": str(chat_dir / "ChatStorage.sqlite")})
    assert result["status"] == "ready"
    assert result["stats"]["total_messages"] == 4


def test_import_without_contacts_or_calls_still_works(tmp_path: Path):
    chat = tmp_path / "ChatStorage.sqlite"
    _make_chat_store(
        chat,
        sessions=[(1, "Peer", "123@s.whatsapp.net", 715157772)],
        messages=[(1, 0, 715157772, "hi", 1, "123@s.whatsapp.net", None, "", 0)],
    )
    service = wa.WhatsAppImportService()
    result = service.create_import({"db_path": str(tmp_path)})
    assert result["status"] == "ready"
    assert result["stats"]["calls"] == 0
    assert result["stats"]["total_messages"] == 1


def test_missing_chat_store_raises(tmp_path: Path):
    service = wa.WhatsAppImportService()
    with pytest.raises(FileNotFoundError):
        service.create_import({"db_path": str(tmp_path)})


def test_missing_required_field_raises(chat_dir: Path):
    service = wa.WhatsAppImportService()
    with pytest.raises(ValueError):
        service.create_import({"name": "no path"})


def test_store_without_zwamessage_is_rejected(tmp_path: Path):
    (tmp_path / "ChatStorage.sqlite").write_bytes(b"")
    connection = sqlite3.connect(tmp_path / "ChatStorage.sqlite")
    connection.execute("CREATE TABLE Other(x INTEGER)")
    connection.commit()
    connection.close()
    service = wa.WhatsAppImportService()
    with pytest.raises(ValueError):
        service.create_import({"db_path": str(tmp_path)})


def test_delete_import_removes_the_directory(chat_dir: Path):
    service = wa.WhatsAppImportService()
    result = service.create_import({"db_path": str(chat_dir)})
    import_id = result["import_id"]
    service.delete_import(import_id)
    with pytest.raises(FileNotFoundError):
        service.get_import(import_id)
