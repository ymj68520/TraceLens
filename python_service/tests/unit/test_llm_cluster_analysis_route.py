"""Route-level regression tests for POST /api/llm/analyze-event-cluster.

The web Timeline page submits only the backend group_descriptor (no legacy
flat fields); the endpoint must resolve cluster members from the descriptor
instead of reading unset request attributes, and an empty match must surface
as 404 rather than being swallowed into a generic 500.
"""

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from httpserver.routes import llm


def _events_db(tmp_path):
    path = tmp_path / "events.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE events (id INTEGER PRIMARY KEY, timestamp INTEGER, event_type TEXT, "
            "file_path TEXT, description TEXT, inode INTEGER, "
            "llm_summary TEXT, llm_description TEXT, llm_keywords TEXT, "
            "llm_analyzed_at INTEGER, llm_model_used TEXT, llm_is_relevant INTEGER)"
        )
        conn.executemany(
            "INSERT INTO events (id, timestamp, event_type, file_path, description) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (1, 120, "MODIFIED", "/foo/a.txt", "first"),
                (2, 121, "MODIFIED", "/foobar/b.txt", "other dir"),
                (3, 150, "MODIFIED", "/foo/c.txt", "same bucket"),
            ],
        )
        conn.commit()
    return str(path)


class _FakeManager:
    def __init__(self, events_db, llm_result):
        self._events_db = events_db
        self._llm_result = llm_result
        self.llm_calls = []

        class _Backend:
            def __init__(self, outer):
                self._outer = outer

            async def get_task(self, task_id):
                return {"output_events_db": self._outer._events_db}

        class _LLM:
            def __init__(self, outer):
                self._outer = outer

            async def analyze_event_cluster(self, event_data, prompt=None):
                self._outer.llm_calls.append({"event_data": event_data, "prompt": prompt})
                return self._outer._llm_result

        self.cpp_backend = _Backend(self)
        self.llm_service = _LLM(self)


@pytest.fixture
def client(monkeypatch, tmp_path):
    events_db = _events_db(tmp_path)
    manager = _FakeManager(
        events_db,
        {
            "analysis": {
                "summary": "summary",
                "description": "description",
                "keywords": ["foo"],
                "is_relevant": True,
            },
            "model": "test-model",
        },
    )
    monkeypatch.setattr(
        "httpserver.services.get_service_manager", lambda: manager
    )
    app = FastAPI()
    app.include_router(llm.router, prefix="/api/llm")
    yield TestClient(app), manager
    # read_timeline_group_members opens the db read-only; nothing to clean up.


DESCRIPTOR = {
    "bucket_index": 2,
    "bucket_seconds": 60,
    "event_type": "MODIFIED",
    "parent_directory": "/foo/",
}


def test_frontend_descriptor_payload_resolves_members(client):
    tc, manager = client

    response = tc.post(
        "/api/llm/analyze-event-cluster",
        json={"task_id": "task-1", "group_descriptor": DESCRIPTOR},
    )

    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["success"] is True
    assert body["model_used"] == "test-model"

    # The LLM receives the descriptor-derived cluster identity.
    assert manager.llm_calls[0]["event_data"]["event_type"] == "MODIFIED"
    assert manager.llm_calls[0]["event_data"]["time_window"] == 2
    assert "/foo/a.txt" in manager.llm_calls[0]["event_data"]["description"]
    assert "/foobar/b.txt" not in manager.llm_calls[0]["event_data"]["description"]

    # Persistence targets exactly the trusted member rows.
    with sqlite3.connect(manager._events_db) as conn:
        rows = conn.execute(
            "SELECT id, llm_summary FROM events ORDER BY id"
        ).fetchall()
    assert [r[1] for r in rows] == ["summary", None, "summary"]


def test_legacy_flat_payload_still_supported(client):
    tc, manager = client

    response = tc.post(
        "/api/llm/analyze-event-cluster",
        json={
            "task_id": "task-1",
            "time_window": 2,
            "event_type": "MODIFIED",
            "parent_directory": "/foo/",
            "bucket_seconds": 60,
        },
    )

    assert response.status_code == 200, response.json()
    assert manager.llm_calls[0]["event_data"]["time_window"] == 2


def test_empty_cluster_returns_404_not_500(client):
    tc, _ = client

    response = tc.post(
        "/api/llm/analyze-event-cluster",
        json={
            "task_id": "task-1",
            "group_descriptor": {
                "bucket_index": 999,
                "bucket_seconds": 60,
                "event_type": "MODIFIED",
                "parent_directory": "/foo/",
            },
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "No events found in this cluster"


def test_missing_descriptor_and_flat_fields_rejected(client):
    tc, _ = client

    response = tc.post(
        "/api/llm/analyze-event-cluster",
        json={"task_id": "task-1"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "cluster descriptor is required"
