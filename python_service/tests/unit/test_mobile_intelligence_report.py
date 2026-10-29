"""The intelligence report must expose mobile-only chapters.

A mobile case is about calls, SMS, instant messaging and acquisition coverage.
Without these sections the reader shows an empty report, which reads as "nothing
found" rather than "nothing extracted".
"""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from httpserver.routes import intelligence_report


def build_android_db(path):
    with sqlite3.connect(path) as con:
        con.executescript("""
            CREATE TABLE contacts(id INTEGER PRIMARY KEY, display_name TEXT, phone_number TEXT,
                email TEXT, account_type TEXT, account_name TEXT);
            CREATE TABLE call_logs(id INTEGER PRIMARY KEY, number TEXT, date INTEGER,
                duration INTEGER, type INTEGER, name TEXT, geocoded_location TEXT,
                date_seconds INTEGER);
            CREATE TABLE sms_messages(id INTEGER PRIMARY KEY, thread_id INTEGER, address TEXT,
                person TEXT, date INTEGER, date_sent INTEGER, read INTEGER, status INTEGER,
                type INTEGER, body TEXT, service_center TEXT, date_seconds INTEGER);
            CREATE TABLE wechat_messages(id INTEGER PRIMARY KEY, sender TEXT, receiver TEXT,
                content TEXT, timestamp INTEGER, media_type TEXT, msg_type INTEGER,
                is_send INTEGER, chatroom_name TEXT, sender_nickname TEXT, talker TEXT);
            CREATE TABLE wechat_contacts(id INTEGER PRIMARY KEY, username TEXT UNIQUE,
                nickname TEXT, remark TEXT, avatar_path TEXT, type INTEGER,
                chatroom_flag INTEGER DEFAULT 0, mobile TEXT);
            CREATE TABLE wechat_chatrooms(id INTEGER PRIMARY KEY, chatroom_name TEXT UNIQUE,
                owner TEXT, member_list TEXT, member_count INTEGER, create_time INTEGER);
            CREATE TABLE app_notes(id INTEGER PRIMARY KEY, package_name TEXT, note_id TEXT,
                title TEXT, content TEXT, tags TEXT, is_private INTEGER, source_db TEXT);
            CREATE TABLE android_source_coverage(id INTEGER PRIMARY KEY, artifact_kind TEXT,
                source_path TEXT, status TEXT, native_status TEXT, detail TEXT,
                record_count INTEGER);
        """)
        con.execute("INSERT INTO contacts VALUES (1,'张三','13800138000','','','')")
        # Deliberately inconsistent raw units: `date` is milliseconds while
        # date_seconds is the normalized value.
        con.execute("INSERT INTO call_logs VALUES "
                    "(1,'13800138000',1700000000000,65,1,'张三','',1700000000),"
                    "(2,'13900139000',1800000000000,0,3,'李四','',1800000000)")
        con.execute("INSERT INTO sms_messages VALUES "
                    "(1,1,'13800138000','张三',1700000000000,0,1,0,1,'晚点到','',1700000000)")
        con.execute("INSERT INTO wechat_messages VALUES "
                    "(1,'wxid_owner','wxid_zhangsan','今晚见',1700000000000,'',1,1,'','','')")
        con.execute("INSERT INTO wechat_contacts VALUES "
                    "(1,'wxid_zhangsan','张三','张三','',1,0,'13800138000')")
        con.execute("INSERT INTO wechat_chatrooms VALUES "
                    "(1,'123@chatroom','wxid_zhangsan','wxid_zhangsan,wxid_lisi',2,0)")
        con.execute("INSERT INTO app_notes VALUES "
                    "(1,'com.miui.notes','n1','备忘','别忘记','',0,'notes.bak')")
        con.execute("INSERT INTO android_source_coverage VALUES "
                    "(1,'wechat','apps/com.tencent.mm/db/EnMicroMsg.db','parsed',NULL,'',10),"
                    "(2,'note','notes.bak','parsed',NULL,'',1),"
                    "(3,'contact','apps/com.android.contacts/contacts.bak','locked',NULL,'',0)")


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = tmp_path / "android.db"
    build_android_db(db)
    task = {"id": "MT", "image_path": "/cases/phone.bin",
            "output_files_db": str(db), "android_source": "miui-backup",
            "metadata": {"android_db": str(db)}}

    class _Backend:
        async def get_task(self, task_id):
            return dict(task) if task_id == "MT" else None

    monkeypatch.setattr(intelligence_report, "_resolve_task",
                        lambda task_id: _aresolve(task_id, task))
    app = FastAPI()
    app.include_router(intelligence_report.router, prefix="/api/llm")
    return TestClient(app)


async def _aresolve(task_id, task):
    if task_id != "MT":
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="task not found")
    return task, task["output_files_db"], None


def _directory(client):
    response = client.get("/api/llm/intelligence-report/MT")
    assert response.status_code == 200
    return {node["id"]: node for node in response.json()["directory"]}


def test_directory_contains_mobile_im_and_coverage_chapters(client):
    directory = _directory(client)
    for section in ("android_coverage", "im_sessions", "im_contacts", "im_groups", "notes"):
        assert section in directory, f"missing chapter {section}"
    assert directory["android_coverage"]["title"] == "数据来源与覆盖度"
    # Two parsed sources are reported as "relevant" in the directory stats.
    assert directory["android_coverage"]["stats"]["relevant"] == 2


def test_coverage_chapter_lists_locked_sources(client):
    response = client.get("/api/llm/intelligence-report/MT/records",
                          params={"category": "android_coverage"})
    assert response.status_code == 200
    records = response.json()["records"]
    statuses = {record["artifact_kind"]: record["status"] for record in records}
    assert statuses["contact"] == "locked", "a locked source must not look empty"
    assert any(record.get("_summary") for record in records)


def test_im_sessions_chapter_returns_messages(client):
    response = client.get("/api/llm/intelligence-report/MT/records",
                          params={"category": "im_sessions"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["records"][0]["content"] == "今晚见"


def test_im_contacts_chapter_exposes_the_linking_phone(client):
    response = client.get("/api/llm/intelligence-report/MT/records",
                          params={"category": "im_contacts"})
    assert response.status_code == 200
    assert response.json()["records"][0]["mobile"] == "13800138000"


def test_call_logs_order_by_normalized_seconds_not_raw_date(client):
    """`date` mixes ms and s across sources; ordering must use date_seconds."""
    response = client.get("/api/llm/intelligence-report/MT/records",
                          params={"category": "call_logs"})
    assert response.status_code == 200
    rows = response.json()["records"]
    seconds = [row["date_seconds"] for row in rows]
    assert seconds == sorted(seconds), "records must be ordered by date_seconds"
    # The raw values are still delivered unchanged (forensic traceability).
    assert any(row["date"] == 1700000000000 for row in rows)


def test_notes_chapter_reads_app_notes(client):
    response = client.get("/api/llm/intelligence-report/MT/records",
                          params={"category": "notes"})
    assert response.status_code == 200
    assert response.json()["records"][0]["title"] == "备忘"


def test_unknown_category_is_404(client):
    assert client.get("/api/llm/intelligence-report/MT/records",
                      params={"category": "telepathy"}).status_code == 404
