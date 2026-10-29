"""Mobile communication records are reportable evidence.

A mobile-only case has no `files` table: without these kinds the report would
either be empty or fall back to file-system material that does not exist.
"""

from __future__ import annotations

import asyncio
import sqlite3
from unittest.mock import AsyncMock

from httpserver.services.android_artifact_reader import artifact_detail, list_artifacts
from httpserver.services.android_result_sets import freeze_selected_result
from httpserver.services.evidence.resolver import EvidenceResolver
from httpserver.services.investigation.acquisition import _acquire_android_artifact


def build_mobile_db(path):
    with sqlite3.connect(path) as con:
        con.executescript("""
            CREATE TABLE call_logs(id INTEGER PRIMARY KEY, number TEXT, date INTEGER,
                duration INTEGER, type INTEGER, name TEXT, geocoded_location TEXT,
                date_seconds INTEGER);
            CREATE TABLE sms_messages(id INTEGER PRIMARY KEY, thread_id INTEGER, address TEXT,
                person TEXT, date INTEGER, date_sent INTEGER, read INTEGER, status INTEGER,
                type INTEGER, body TEXT, service_center TEXT, date_seconds INTEGER);
            CREATE TABLE wechat_messages(id INTEGER PRIMARY KEY, source_path TEXT, sender TEXT,
                receiver TEXT, content TEXT, timestamp INTEGER, media_url TEXT, media_type TEXT,
                msg_type INTEGER DEFAULT 1, is_send INTEGER DEFAULT 0, chatroom_name TEXT,
                sender_nickname TEXT, talker TEXT);
            CREATE TABLE wechat_contacts(id INTEGER PRIMARY KEY, username TEXT UNIQUE,
                nickname TEXT, remark TEXT, avatar_path TEXT, type INTEGER,
                chatroom_flag INTEGER DEFAULT 0, mobile TEXT);
        """)
        con.execute("INSERT INTO call_logs VALUES "
                    "(1,'13800138000',1700000000000,65,1,'张三','北京',1700000000)")
        con.execute("INSERT INTO sms_messages VALUES "
                    "(1,1,'13800138000','张三',1700000000000,0,1,0,1,'晚点到','',1700000000)")
        con.execute("INSERT INTO wechat_messages VALUES "
                    "(1,'','wxid_owner','wxid_zhangsan','今晚见',1700000000000,'','',1,1,'','','')")
        con.execute("INSERT INTO wechat_contacts VALUES "
                    "(1,'wxid_zhangsan','张三','张三','',1,0,'13800138000')")


def _task(tmp_path, source="miui-backup"):
    db = tmp_path / "android.db"
    build_mobile_db(db)
    return {"id": "mobile-fixture", "output_files_db": str(db), "android_source": source,
            "metadata": {"android_db": str(db)}}


def _capture(task, kind, row_id):
    detail = artifact_detail(task, kind, row_id)
    frozen = freeze_selected_result(
        task, kind, row_id,
        expected_row_hash=detail["record_hash"],
        expected_source_revision=detail["source_revision"])
    key = f"android_artifact:v1:{task['id']}:{frozen['result_set_id']}:{kind}:{row_id}"
    cpp = AsyncMock()
    cpp.get_task = AsyncMock(return_value=task)
    snapshot = _acquire_android_artifact(
        asyncio.run(EvidenceResolver(cpp).resolve_evidence(task["id"], key)))
    return key, snapshot


def test_call_log_is_readable_and_snapshottable(tmp_path):
    task = _task(tmp_path)
    listing = list_artifacts(task, "calls")
    assert listing["total"] == 1
    assert listing["records"][0]["number"] == "13800138000"

    key, snapshot = _capture(task, "calls", 1)
    assert snapshot.artifact_kind == "calls"
    assert snapshot.normalized_fields["number"] == "13800138000"
    assert snapshot.normalized_fields["duration"] == 65
    # The normalized seconds column is what cross-source ordering uses.
    assert snapshot.normalized_fields["date_seconds"] == 1700000000
    assert snapshot.raw_timestamp == 1700000000
    assert key.startswith("android_artifact:v1:mobile-fixture:")


def test_im_message_is_readable_and_keeps_direction(tmp_path):
    task = _task(tmp_path)
    listing = list_artifacts(task, "im")
    assert listing["total"] == 1

    _, snapshot = _capture(task, "im", 1)
    assert snapshot.artifact_kind == "im"
    assert snapshot.normalized_fields["content"] == "今晚见"
    assert snapshot.normalized_fields["is_send"] == 1
    assert snapshot.normalized_fields["sender"] == "wxid_owner"
    assert snapshot.timestamp_unit == "epoch_ms"


def test_im_contact_carries_the_linking_phone(tmp_path):
    task = _task(tmp_path)
    _, snapshot = _capture(task, "im_contacts", 1)
    assert snapshot.normalized_fields["username"] == "wxid_zhangsan"
    assert snapshot.normalized_fields["mobile"] == "13800138000"


def test_mobile_seeding_covers_communication_tables(tmp_path):
    """A MIUI/Meiya task must produce report evidence without a files table."""
    from httpserver.services.investigation.report_evidence import ReportEvidenceService

    task = _task(tmp_path)
    cpp = AsyncMock()
    cpp.get_task = AsyncMock(return_value=task)
    service = ReportEvidenceService(cpp)

    seeded = asyncio.run(service.seed_analyzed_files(task["id"], added_by="pipeline"))
    assert seeded["mobile_seeded"] == 4  # 1 call + 1 sms + 1 im + 1 im_contact

    items = asyncio.run(service.list(task["id"]))
    kinds = {item.evidence_key.split(":")[4] for item in items}
    assert kinds == {"calls", "sms", "im", "im_contacts"}

    # Idempotent: a second seed adds nothing.
    again = asyncio.run(service.seed_analyzed_files(task["id"], added_by="pipeline"))
    assert again["mobile_seeded"] == 0


def test_meiya_task_is_covered_too(tmp_path):
    from httpserver.services.investigation.report_evidence import ReportEvidenceService

    task = _task(tmp_path, source="meiya")
    cpp = AsyncMock()
    cpp.get_task = AsyncMock(return_value=task)
    service = ReportEvidenceService(cpp)
    seeded = asyncio.run(service.seed_analyzed_files(task["id"], added_by="pipeline"))
    assert seeded["mobile_seeded"] == 4


def test_unified_package_task_is_covered(tmp_path):
    from httpserver.services.investigation.report_evidence import ReportEvidenceService

    task = _task(tmp_path, source="mobile-evidence")
    cpp = AsyncMock()
    cpp.get_task = AsyncMock(return_value=task)
    service = ReportEvidenceService(cpp)
    seeded = asyncio.run(service.seed_analyzed_files(task["id"], added_by="pipeline"))
    assert seeded["mobile_seeded"] == 4
