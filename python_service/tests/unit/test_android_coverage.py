import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient

from httpserver.routes import evidence_intake as route
from httpserver.services.android_coverage import read_coverage


def test_task_owned_android_coverage_distinguishes_parsed_from_missing(tmp_path):
    db = tmp_path / "android.db"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE wechat_messages(id INTEGER PRIMARY KEY, source_path TEXT)")
        con.execute("INSERT INTO wechat_messages(source_path) VALUES ('data/data/com.tencent.mm/account-a/EnMicroMsg.db')")
        con.execute("CREATE TABLE android_source_coverage(artifact_kind TEXT, source_path TEXT, status TEXT, detail TEXT)")
        con.executemany("INSERT INTO android_source_coverage VALUES (?,?,?,?)", [
            ("wechat", "data/data/com.tencent.mm/account-a/EnMicroMsg.db", "parsed", "done"),
            ("sms", "data/data/telephony/mmssms.db", "not_found_or_unreadable", "not proof of absence"),
        ])
    result = read_coverage({"id": "task-a", "android_source": "dir", "output_files_db": str(db)})
    assert result["available"] is True
    assert result["coverage_recorded"] is True
    assert result["artifact_counts"]["wechat_messages"] == 1
    assert {item["status"] for item in result["sources"]} == {"parsed", "not_found_or_unreadable"}
    assert result["warnings"]


def test_legacy_android_db_reports_unknown_coverage(tmp_path):
    db = tmp_path / "android.db"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE sms_messages(id INTEGER PRIMARY KEY)")
    result = read_coverage({"id": "task-b", "android_source": "tsk", "output_raw_db": str(tmp_path / "raw.db")})
    assert result["available"] is True
    assert result["coverage_recorded"] is False
    assert result["artifact_counts"]["sms_messages"] == 0


def test_untrusted_metadata_path_outside_task_store_is_ignored(tmp_path):
    outside = tmp_path / "outside" / "android.db"
    outside.parent.mkdir()
    with sqlite3.connect(outside) as con:
        con.execute("CREATE TABLE wechat_messages(id INTEGER PRIMARY KEY)")
    task = {
        "id": "task-c", "android_source": "dir",
        "output_files_db": str(tmp_path / "trusted" / "files.db"),
        "metadata": {"android_db": str(outside)},
    }
    assert read_coverage(task)["available"] is False


def test_coverage_route_rejects_missing_task(monkeypatch):
    async def missing(_task_id):
        from httpserver.services.task_store import TaskStoreError, TASK_NOT_FOUND
        raise TaskStoreError(TASK_NOT_FOUND, "task not found")
    monkeypatch.setattr(route, "get_task_record", missing)
    app = FastAPI()
    app.include_router(route.router, prefix="/api/evidence-intake")
    client = TestClient(app)
    assert client.get("/api/evidence-intake/tasks/absent/android-coverage").status_code == 404
