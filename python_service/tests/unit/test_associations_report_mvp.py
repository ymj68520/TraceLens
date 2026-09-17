"""Tests for the MVP report-page association endpoints.

- GET /api/associations/file-events   (report file tag → related events, no LLM)
- GET /api/associations/file-timeline (filtered files × four timestamps, axis min→max)

Endpoints are called directly with a mocked service_manager whose
cpp_backend.get_task returns temp DB paths (same pattern as test_associations.py).
"""

import json
import sqlite3
from unittest.mock import patch

import pytest

from httpserver.routes.associations import get_file_events, get_file_timeline


T0 = 1_700_000_000


def _make_events_db(db_path, rows):
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE events (
            id INTEGER PRIMARY KEY, timestamp INTEGER, event_type TEXT,
            description TEXT, file_path TEXT, priority TEXT, severity TEXT,
            event_source TEXT, event_category TEXT)"""
    )
    for r in rows:
        conn.execute(
            "INSERT INTO events (timestamp, event_type, description, file_path,"
            " priority, severity, event_source, event_category) VALUES (?,?,?,?,?,?,?,?)",
            (
                r["timestamp"], r["event_type"], r.get("description"),
                r["file_path"], r.get("priority"), r.get("severity"),
                r.get("event_source"), r.get("event_category"),
            ),
        )
    conn.commit()
    conn.close()
    return str(db_path)


def _make_raw_db(db_path, rows):
    """rows: list of dicts (path, name, size, crtime, mtime, atime, ctime)."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE files (
            path TEXT PRIMARY KEY, name TEXT, size INTEGER,
            crtime INTEGER, mtime INTEGER, atime INTEGER, ctime INTEGER)"""
    )
    for r in rows:
        conn.execute(
            "INSERT INTO files (path, name, size, crtime, mtime, atime, ctime)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                r["path"], r.get("name"), r.get("size", 0),
                r.get("crtime"), r.get("mtime"), r.get("atime"), r.get("ctime"),
            ),
        )
    conn.commit()
    conn.close()
    return str(db_path)


def _make_files_db(db_path, filtered_files, task_id="T1"):
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE case_analysis (task_id TEXT PRIMARY KEY,"
        " case_description TEXT, filtered_files TEXT, case_report TEXT,"
        " created_at TEXT, updated_at TEXT)"
    )
    conn.execute(
        "INSERT INTO case_analysis (task_id, filtered_files) VALUES (?,?)",
        (task_id, json.dumps(filtered_files)),
    )
    conn.commit()
    conn.close()
    return str(db_path)


def _manager_with(task_info):
    class _Backend:
        async def get_task(self, task_id):
            return dict(task_info)

    from types import SimpleNamespace

    return SimpleNamespace(cpp_backend=_Backend())


async def test_file_events_exact_path_match(tmp_path):
    events_db = _make_events_db(
        tmp_path / "events.db",
        [
            {"timestamp": T0, "event_type": "MODIFIED", "file_path": "/case/a.txt", "description": "d1"},
            {"timestamp": T0 + 5, "event_type": "CREATED", "file_path": "/case/a.txt", "description": "d2"},
            {"timestamp": T0 + 9, "event_type": "MODIFIED", "file_path": "/case/other.txt", "description": "x"},
        ],
    )
    manager = _manager_with({"output_events_db": events_db})
    with patch("httpserver.services.get_service_manager", lambda: manager):
        resp = await get_file_events(task_id="T1", path="/case/a.txt", limit=200)
    assert resp["success"] is True
    assert resp["matched_by"] == "exact_path"
    assert [e["event_type"] for e in resp["events"]] == ["MODIFIED", "CREATED"]
    assert resp["total_count"] == 2


async def test_file_events_basename_fallback(tmp_path):
    events_db = _make_events_db(
        tmp_path / "events.db",
        [
            {"timestamp": T0, "event_type": "ACCESSED", "file_path": "/other/a.txt"},
            {"timestamp": T0 + 1, "event_type": "MODIFIED", "file_path": "/deep/nested/a.txt"},
        ],
    )
    manager = _manager_with({"output_events_db": events_db})
    with patch("httpserver.services.get_service_manager", lambda: manager):
        resp = await get_file_events(task_id="T1", path="/elsewhere/a.txt", limit=200)
    assert resp["matched_by"] == "basename"
    assert resp["total_count"] == 2


async def test_file_events_unknown_task_raises_404(tmp_path):
    class _Backend:
        async def get_task(self, task_id):
            return None

    from types import SimpleNamespace
    from fastapi import HTTPException

    manager = SimpleNamespace(cpp_backend=_Backend())
    with patch("httpserver.services.get_service_manager", lambda: manager):
        with pytest.raises(HTTPException) as excinfo:
            await get_file_events(task_id="missing", path="/a.txt")
    assert excinfo.value.status_code == 404


async def test_file_timeline_scope_filter_and_axis(tmp_path):
    raw_db = _make_raw_db(
        tmp_path / "raw.db",
        [
            {"path": "/case/a.txt", "name": "a.txt", "size": 10,
             "crtime": T0 + 100, "mtime": T0 + 200, "atime": T0 + 300, "ctime": T0 + 400},
            {"path": "/case/b.txt", "name": "b.txt", "size": 20,
             "crtime": T0 - 50, "mtime": T0 + 900, "atime": None, "ctime": None},
            {"path": "/case/excluded.txt", "name": "excluded.txt", "size": 30,
             "crtime": T0 - 9999, "mtime": T0, "atime": T0, "ctime": T0},
        ],
    )
    files_db = _make_files_db(tmp_path / "files.db", ["/case/a.txt", "/case/b.txt"])
    manager = _manager_with({"output_raw_db": raw_db, "output_files_db": files_db})
    with patch("httpserver.services.get_service_manager", lambda: manager):
        resp = await get_file_timeline(task_id="T1", limit=2000)
    assert resp["success"] is True
    assert [f["path"] for f in resp["files"]] == ["/case/b.txt", "/case/a.txt"]
    assert resp["axis"] == {"start": T0 - 50, "end": T0 + 900}
    # b.txt has NULL atime/ctime: earliest/latest ignore them
    assert resp["files"][0]["earliest"] == T0 - 50


async def test_file_timeline_empty_scope_returns_all(tmp_path):
    raw_db = _make_raw_db(
        tmp_path / "raw.db",
        [
            {"path": "/x/1.txt", "name": "1.txt", "size": 1,
             "crtime": None, "mtime": T0, "atime": T0 + 1, "ctime": None},
            {"path": "/x/no-times.bin", "name": "no-times.bin", "size": 2,
             "crtime": None, "mtime": None, "atime": None, "ctime": None},
        ],
    )
    manager = _manager_with({"output_raw_db": raw_db, "output_files_db": ""})
    with patch("httpserver.services.get_service_manager", lambda: manager):
        resp = await get_file_timeline(task_id="T1", limit=2000)
    assert resp["total_count"] == 1
    assert resp["files"][0]["path"] == "/x/1.txt"
    assert resp["axis"] == {"start": T0, "end": T0 + 1}
