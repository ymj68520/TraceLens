"""Contract tests for GET /api/db/tasks/{task_id}/events.

Regression: the C++ comprehensive timeline returns ``timeline`` rows whose
``timestamp`` is a unix-seconds int, but ``EventRecord.timestamp`` was
declared ``str`` — every real payload failed pydantic validation and the
endpoint 500'd. The model now carries unix seconds (what the frontend
``Timeline`` page multiplies by 1000) with tolerant coercion.
"""

from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from httpserver.routes import database


def _cpp_event(ts, path="/case/a.txt", event_type="CREATED"):
    return {
        "cluster_count": 1,
        "description": "File created",
        "end_timestamp": ts,
        "event_type": event_type,
        "file_path": path,
        "file_size": 262,
        "file_type": "REG",
        "inode": 3508,
        "timestamp": ts,
    }


@pytest.fixture
def manager(monkeypatch):
    manager = Mock()
    manager.cpp_backend = Mock()
    manager.cpp_backend.get_task_events = AsyncMock(
        return_value={
            "events": [
                _cpp_event(1787419698),                        # int, like C++
                _cpp_event("1787419700", path="/case/b.txt"),  # legacy numeric str
                _cpp_event(None, path="/case/c.txt"),          # unusable -> 0
            ],
            "total_count": 3,
        }
    )
    monkeypatch.setattr(
        "httpserver.services.get_service_manager", lambda: manager
    )
    app = FastAPI()
    app.include_router(database.router, prefix="/api/db")
    return manager, TestClient(app)


def test_task_events_accept_unix_second_ints(manager):
    _, client = manager
    response = client.get("/api/db/tasks/T1/events")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["total_count"] == 3
    timestamps = [event["timestamp"] for event in body["events"]]
    assert timestamps == [1787419698, 1787419700, 0]
    assert all(isinstance(ts, int) for ts in timestamps)


def test_task_events_passes_filters_to_backend(manager):
    _, client = manager
    response = client.get(
        "/api/db/tasks/T1/events",
        params={"event_type": "CREATED", "page": 2, "page_size": 25},
    )
    assert response.status_code == 200
    assert response.json()["page"] == 2
    manager[0].cpp_backend.get_task_events.assert_awaited_once_with(
        task_id="T1",
        event_type="CREATED",
        start_time=None,
        end_time=None,
        page=2,
        page_size=25,
    )


def test_coerce_epoch_seconds_variants():
    assert database._coerce_epoch_seconds(1787419698) == 1787419698
    assert database._coerce_epoch_seconds(1787419698.9) == 1787419698
    assert database._coerce_epoch_seconds(" 1787419698 ") == 1787419698
    assert database._coerce_epoch_seconds(None) == 0
    assert database._coerce_epoch_seconds("not-a-timestamp") == 0
    assert database._coerce_epoch_seconds(True) == 0
