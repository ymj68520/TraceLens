from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from httpserver.routes import timeline_summary as routes
from httpserver.services.timeline_sources import TimelineSource, SourceChanged, SourceUnavailable
from httpserver.services.timeline_summary import SummaryFilters, RecordSelection, summarize


def epoch(day=1, hour=14):
    return datetime(2026, 1, day, hour, tzinfo=timezone.utc).timestamp()


def events_source(tmp_path, rows=None):
    path = tmp_path / "events.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE events(id INTEGER, timestamp, event_type, file_path, description, event_source, event_category)")
        db.executemany("INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?)", rows or [
            (1, epoch(1), "LOGIN_SUCCESS", "/same/a", "登录", "LINUX_SYSLOG", "USER_ACTIVITY"),
            (2, epoch(2), "LOGIN_SUCCESS", "/same/b", "登录", "LINUX_SYSLOG", "USER_ACTIVITY"),
            (3, epoch(3), "MODIFIED", "/same/a", "文件修改", "FILE_SYSTEM", "FILE_OPERATION"),
            (4, 0, "OTHER", "/missing", "无时间", "SYSTEM", "SYSTEM_ACTIVITY"),
            (5, "bad", "OTHER", "/invalid", "坏时间", "SYSTEM", "SYSTEM_ACTIVITY"),
            (6, epoch(3), "DELETED", "/inferred", "推定删除", "FILE_SYSTEM", "FILE_OPERATION"),
            (7, epoch(3), "ANDROID_ARTIFACT", "/processing", "导入时间", "ANDROID_LOG", "APPLICATION_EVENT"),
        ])
    return TimelineSource(path, "events", "task-T")


def messages_source(tmp_path, rows=None):
    path = tmp_path / "messages.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE message(msgId, msgSvrId, createTime, isSend, talker, type, content)")
        db.executemany("INSERT INTO message VALUES (?, ?, ?, ?, ?, ?, ?)", rows or [
            (1, 100, epoch(1) * 1000, 1, "alice", 1, "同一消息"),
            (2, 100, epoch(1) * 1000, 1, "alice", 1, "同一消息"),
            (3, 101, epoch(2) * 1000, 0, "alice", 1, "收到"),
            (4, 102, epoch(3) * 1000, 7, "alice", 1, "未知方向"),
            (5, 103, epoch(4) * 1000, 0, "alice", 10000, "系统消息"),
            (6, 104, None, 1, "bob", 1, "无时间"),
        ])
    return TimelineSource(path, "wechat_import", "abcdef123456")


def record_options(result):
    return {"expected_version": result["context"]["source_version"],
            "expected_summary": result["context"]["context_id"]}


def test_hours_recurrence_metadata_and_nonactivity_times(tmp_path):
    source = events_source(tmp_path)
    result = summarize(source, SummaryFilters())
    c = result["context"]
    assert c["counts"]["valid_records"] == 3
    assert c["counts"]["missing_records"] == c["counts"]["invalid_records"] == 1
    assert c["counts"]["inferred_records"] == c["counts"]["processing_records"] == 1
    assert result["hours"][22]["count"] == 3
    assert result["repeated_hours"][0]["observed_days"] == 3
    assert result["hours"][22]["observed_day_denominator"] == 3
    assert c["filters"]["timezone"] == "Asia/Shanghai"
    assert c["statistics_version"] == "timeline-summary:v1"
    assert c["deduplication"]["rule"] == "same-source-original-id-and-payload:v1"
    for group in ("hours", "daily", "heatmap", "repeated_hours", "weekdays"):
        assert all(r["context_id"] == c["context_id"] for r in result[group])
    assert result["communication"]["available"] is False


def test_scoped_query_and_drilldown_match_and_are_read_only(tmp_path):
    source = events_source(tmp_path)
    before = source.path.read_bytes()
    filters = SummaryFilters(event_type="LOGIN_SUCCESS")
    result = summarize(source, filters)
    rows = summarize(source, filters, selection=RecordSelection(hour=22), **record_options(result))
    assert rows["total"] == result["hours"][22]["count"] == 2
    assert [r["original_id"] for r in rows["records"]] == ["1", "2"]
    assert rows["records"][0]["record_ref"] == "events:1"
    assert len(rows["records"][0]["record_sha256"]) == 64
    assert rows["records"][0]["timestamp_raw"] == epoch(1)
    assert source.path.read_bytes() == before
    assert set(p.name for p in tmp_path.iterdir()) == {"events.db"}


def test_seconds_and_milliseconds_use_explicit_source_contract(tmp_path):
    source = messages_source(tmp_path)
    shanghai = summarize(source, SummaryFilters())
    utc = summarize(source, SummaryFilters(timezone="UTC"))
    assert shanghai["hours"][22]["count"] == utc["hours"][14]["count"] == 4
    assert shanghai["context"]["scope"]["timestamp_unit"] == "milliseconds"
    assert shanghai["context"]["source_version"] == utc["context"]["source_version"]
    assert shanghai["context"]["context_id"] != utc["context"]["context_id"]


def test_local_date_boundaries_and_dst_repeated_hour(tmp_path):
    source = events_source(tmp_path, [
        (1, datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc).timestamp(), "A", "/", "", "SYSTEM", ""),
        (2, datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc).timestamp(), "A", "/", "", "SYSTEM", ""),
    ])
    filters = SummaryFilters(timezone="America/New_York", start_date="2026-11-01", end_date="2026-11-01")
    result = summarize(source, filters)
    assert result["hours"][1]["count"] == 2
    assert result["hours"][1]["observed_days"] == 1
    records = summarize(source, filters, selection=RecordSelection(hour=1), **record_options(result))
    assert records["records"][0]["timestamp_iso"].endswith("-04:00")
    assert records["records"][1]["timestamp_iso"].endswith("-05:00")


def test_date_and_epoch_filters_intersect_and_unknown_times_remain_disclosed(tmp_path):
    source = events_source(tmp_path)
    result = summarize(source, SummaryFilters(start_date="2026-01-02", end_date="2026-01-03",
                                             start_time=epoch(2), end_time=epoch(2)))
    assert result["context"]["counts"]["valid_records"] == 1
    assert result["context"]["counts"]["outside_time_records"] == 4
    assert result["context"]["counts"]["missing_records"] == 1
    assert result["context"]["counts"]["invalid_records"] == 1


def test_duplicates_require_original_identity_and_matching_payload(tmp_path):
    source = messages_source(tmp_path)
    with sqlite3.connect(source.path) as db:
        db.execute("INSERT INTO message VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (7, 100, epoch(1) * 1000, 1, "alice", 1, "冲突内容，保留"))
        db.execute("INSERT INTO message VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (8, 200, epoch(1) * 1000, 1, "alice", 1, "同一消息"))
    result = summarize(source, SummaryFilters())
    assert result["context"]["counts"]["duplicate_records"] == 1
    assert result["context"]["counts"]["identity_conflict_records"] == 1
    assert result["context"]["counts"]["valid_records"] == 6
    rows = summarize(source, SummaryFilters(), selection=RecordSelection(direction="sent"), **record_options(result))
    assert rows["total"] == result["communication"]["counts"]["sent"] == 3


def test_received_system_unknown_and_sent_are_separate(tmp_path):
    source = messages_source(tmp_path)
    result = summarize(source, SummaryFilters())
    assert result["communication"]["counts"] == {"sent": 1, "received": 1, "unknown": 1, "system": 1}
    assert any("收到消息不证明" in w for w in result["warnings"])
    narrowed = summarize(source, SummaryFilters(talker="alice", direction="received"))
    assert narrowed["context"]["counts"]["valid_records"] == 1
    assert narrowed["communication"]["counts"] == {"received": 1}


def test_dated_gaps_are_unknown_and_daily_change_uses_adjacent_calendar_day(tmp_path):
    source = messages_source(tmp_path, [
        (1, 1, epoch(1) * 1000, 1, "a", 1, "a"),
        (2, 2, epoch(3) * 1000, 1, "a", 1, "a"),
        (3, 3, epoch(4) * 1000, 1, "a", 1, "a"),
        (4, 4, epoch(4) * 1000, 1, "a", 1, "a"),
    ])
    result = summarize(source, SummaryFilters())
    assert [d["day"] for d in result["daily"]] == ["2026-01-01", "2026-01-03", "2026-01-04"]
    assert result["daily"][1]["previous_count"] is None
    assert result["daily"][1]["delta"] is None
    assert result["daily"][2]["delta"] == 1


def test_a_single_burst_does_not_establish_repeated_days(tmp_path):
    source = messages_source(tmp_path, [(i, i, epoch(1) * 1000, 1, "a", 1, "burst") for i in range(1, 50)])
    result = summarize(source, SummaryFilters())
    assert result["hours"][22]["count"] == 49
    assert result["hours"][22]["observed_days"] == 1
    assert result["repeated_hours"] == []


def test_scan_and_detail_truncation_are_explicit(tmp_path):
    source = messages_source(tmp_path)
    result = summarize(source, SummaryFilters(), scan_limit=4)
    assert result["context"]["coverage"]["truncated"] is True
    assert result["context"]["coverage"]["unscanned_records"] == 2
    assert any("截断" in w for w in result["warnings"])
    rows = summarize(source, SummaryFilters(), scan_limit=4, selection=RecordSelection(limit=1), **record_options(result))
    assert rows["total"] == 3
    assert rows["page_truncated"] is True
    assert len(rows["records"]) == 1
    assert rows["context"]["coverage"]["truncated"] is True


def test_empty_results_and_missing_sources_are_not_confused(tmp_path):
    source = events_source(tmp_path)
    result = summarize(source, SummaryFilters(event_type="not-present"))
    assert result["context"]["counts"]["valid_records"] == 0
    assert "不能判断活动规律" in result["summary"]["text"]
    assert result["hours"][0]["share"] is None
    missing = TimelineSource(tmp_path / "absent.db", "events", "task-T")
    with pytest.raises(SourceUnavailable):
        summarize(missing, SummaryFilters())
    assert not missing.path.exists()


def test_stale_source_and_changed_filter_cannot_be_drilled(tmp_path):
    source = events_source(tmp_path)
    filters = SummaryFilters()
    result = summarize(source, filters)
    with pytest.raises(SourceChanged):
        summarize(source, SummaryFilters(timezone="UTC"), selection=RecordSelection(), **record_options(result))
    with sqlite3.connect(source.path) as db:
        db.execute("UPDATE events SET description='new content' WHERE id=1")
    with pytest.raises(SourceChanged):
        summarize(source, filters, selection=RecordSelection(), **record_options(result))


def test_wal_write_invalidates_source_version(tmp_path, monkeypatch):
    # The suite-wide speed shim forces journal_mode=MEMORY on every open;
    # this test must exercise actual SQLite WAL behavior.
    monkeypatch.setattr(sqlite3, "connect", sqlite3.dbapi2.connect)
    source = events_source(tmp_path)
    with sqlite3.connect(source.path) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("UPDATE events SET description='initial WAL record' WHERE id=1")
        writer.commit()
        result = summarize(source, SummaryFilters())
        writer.execute("UPDATE events SET description='changed in WAL' WHERE id=1")
        writer.commit()
        with pytest.raises(SourceChanged):
            summarize(source, SummaryFilters(), selection=RecordSelection(), **record_options(result))


def test_foreign_scope_rejects_even_when_db_contents_match(tmp_path):
    source = events_source(tmp_path)
    result = summarize(source, SummaryFilters())
    foreign = TimelineSource(source.path, "events", "task-U")
    with pytest.raises(SourceChanged):
        summarize(foreign, SummaryFilters(), selection=RecordSelection(), **record_options(result))


@pytest.mark.parametrize("filters", [
    {"timezone": "bad/zone"}, {"start_time": 10, "end_time": 1},
    {"start_date": "2026-02-01", "end_date": "2026-01-01"},
    {"start_time": float("nan")}, {"end_time": float("inf")},
])
def test_invalid_filters_fail_closed(filters):
    with pytest.raises(ValueError):
        SummaryFilters(**filters)


def test_invalid_timestamp_values_and_syntax_do_not_become_zero_activity(tmp_path):
    values = [None, "", 0, -1, "garbage", 10**15, float("inf")]
    source = events_source(tmp_path, [(i, t, "A", "/", "", "SYSTEM", "") for i, t in enumerate(values)])
    result = summarize(source, SummaryFilters())
    assert result["context"]["counts"]["missing_records"] == 3
    assert result["context"]["counts"]["invalid_records"] == 4
    assert result["context"]["counts"]["valid_records"] == 0
    records = summarize(source, SummaryFilters(), selection=RecordSelection(quality="invalid"), **record_options(result))
    json.dumps(records, allow_nan=False)
    assert records["total"] == 4


def test_qq_raw_tables_units_direction_and_missing_table_disclosure(tmp_path):
    path = tmp_path / "qq.db"
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE group_msg_table("40001", "40050", "40013", "40033", "40011")')
        db.executemany("INSERT INTO group_msg_table VALUES (?, ?, ?, ?, ?)",
                       [(1, epoch(1), 1, "group-A", 2), (2, epoch(2), 0, "group-A", 2), (3, epoch(3), 99, "group-B", 2)])
    source = TimelineSource(path, "qq_import", "abcdef123456")
    result = summarize(source, SummaryFilters(talker="group-A"))
    assert result["communication"]["counts"] == {"sent": 1, "received": 1}
    assert result["context"]["scope"]["timestamp_unit"] == "seconds"
    assert result["context"]["coverage"]["missing_tables"] == ["c2c_msg_table"]
    assert result["hours"][22]["count"] == 2
    rows = summarize(source, SummaryFilters(talker="group-A"), selection=RecordSelection(), **record_options(result))
    assert rows["total"] == 2
    assert rows["records"][0]["record_ref"] == "group_msg_table:1"


def test_new_routes_retain_read_permission_and_are_in_inventory():
    from httpserver.services.field_security import required_permission
    inventory = json.loads((Path(__file__).resolve().parents[3] / "docs/field-protected-routes.json").read_text())
    paths = ["/api/associations/timeline-summary",
             "/api/wechat/forensics/imports/{import_id}/timeline-summary",
             "/api/qq/forensics/imports/{import_id}/timeline-summary"]
    for root in paths:
        for suffix in ("", "/records"):
            route = root + suffix
            assert required_permission("GET", route) == "read"
            assert {"method": "GET", "path": route, "permission": "read"} in inventory["python"]


def test_raw_text_is_preserved_for_ui_escaping_and_large_preview_disclosed(tmp_path):
    content = '<img src=x onerror="alert(1)">' + "a" * 9000
    source = messages_source(tmp_path, [(1, 1, epoch(1) * 1000, 1, "a", 1, content)])
    result = summarize(source, SummaryFilters())
    rows = summarize(source, SummaryFilters(), selection=RecordSelection(), **record_options(result))
    assert rows["records"][0]["content"].startswith("<img")
    assert len(rows["records"][0]["content"]) == 8000
    assert rows["records"][0]["content_truncated"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    source = events_source(tmp_path)
    async def resolve(task_id, kind):
        if task_id != "T":
            raise SourceUnavailable("missing task")
        return source
    monkeypatch.setattr(routes, "task_source", resolve)
    app = FastAPI()
    app.include_router(routes.task_router, prefix="/api/associations")
    app.include_router(routes.wechat_router, prefix="/api/wechat")
    monkeypatch.setattr(routes, "get_data_root", lambda: tmp_path)
    return TestClient(app), source


def test_http_summary_and_exact_record_read(client):
    api, _ = client
    result = api.get("/api/associations/timeline-summary", params={"task_id": "T"}).json()
    c = result["context"]
    response = api.get("/api/associations/timeline-summary/records", params={
        "task_id": "T", "hour": 22, "source_version": c["source_version"], "summary_id": c["context_id"]})
    assert response.status_code == 200
    assert response.json()["total"] == 3


@pytest.mark.parametrize("params", [
    {"timezone": "bad"}, {"start_date": "bad"}, {"direction": "outgoing"},
    {"start_time": 3, "end_time": 1}, {"arbitrary_path": "secret"},
    {"record_ref": "events:1"},
])
def test_http_invalid_filters_are_422_not_500(client, params):
    api, _ = client
    response = api.get("/api/associations/timeline-summary", params={"task_id": "T", **params})
    assert response.status_code == 422


def test_http_missing_source_and_import_path_traversal_create_no_files(client, tmp_path):
    api, _ = client
    assert api.get("/api/associations/timeline-summary?task_id=other").status_code == 404
    assert api.get("/api/wechat/forensics/imports/invalid/timeline-summary").status_code == 422
    assert api.get("/api/wechat/forensics/imports/abcdef123456/timeline-summary").status_code == 404
    assert not (tmp_path / "wechat_imports").exists()


def test_http_records_require_both_versions_and_stale_returns_409(client):
    api, source = client
    base = "/api/associations/timeline-summary"
    assert api.get(base + "/records?task_id=T").status_code == 422
    c = api.get(base + "?task_id=T").json()["context"]
    with sqlite3.connect(source.path) as db:
        db.execute("DELETE FROM events WHERE id=1")
    response = api.get(base + "/records", params={"task_id": "T", "source_version": c["source_version"], "summary_id": c["context_id"]})
    assert response.status_code == 409
