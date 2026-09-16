"""HTTP contract tests for the Workbench bootstrap route (C9a).

Regression: POST /{task_id}/bootstrap used to be a stub that returned the
overview without invoking the cluster-seed service, so the workbench stayed
empty for every task. These tests pin the wiring: the route must await
``manager.investigation_seed_service.bootstrap`` before returning the
overview, GET must never seed, and failures map through the shared
``_error`` handler.
"""

from unittest.mock import AsyncMock, Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from httpserver.routes import investigation_workbench


class _FakeEvent(BaseModel):
    event_id: str
    title: str
    summary: str = ""
    review_status: str = "draft"


def _manager():
    manager = Mock()
    seed = Mock()
    seed.bootstrap = AsyncMock(return_value={})
    manager.investigation_seed_service = seed
    manager.investigation_read_service = Mock(
        list_evidence=AsyncMock(return_value=[])
    )
    manager.investigation_event_service = Mock(
        list_events=AsyncMock(
            return_value=[_FakeEvent(event_id="ev-1", title="cluster title")]
        )
    )
    manager.report_evidence_service = Mock(list=AsyncMock(return_value=[]))
    manager.investigation_graph_service = Mock(
        get_graph=AsyncMock(return_value={"nodes": [], "links": []})
    )
    manager.secondary_analysis_executor = Mock(
        list_analyses=AsyncMock(return_value=[])
    )
    manager.cpp_backend = Mock(
        get_task=AsyncMock(return_value={"id": "T1", "status": "completed"})
    )
    return manager


def _client(manager):
    app = FastAPI()
    app.include_router(
        investigation_workbench.router, prefix="/api/investigation/workbench"
    )
    app.dependency_overrides[investigation_workbench._manager] = lambda: manager
    return TestClient(app)


def test_bootstrap_seeds_then_returns_overview():
    manager = _manager()
    response = _client(manager).post(
        "/api/investigation/workbench/T1/bootstrap",
        json={"mode": "cluster_seed"},
    )
    assert response.status_code == 200
    body = response.json()
    manager.investigation_seed_service.bootstrap.assert_awaited_once_with("T1")
    assert body["event_count"] == 1
    assert body["events"][0]["id"] == "ev-1"
    assert body["initialized"] is True
    assert body["task"]["id"] == "T1"


def test_bootstrap_rejects_unknown_request_fields():
    manager = _manager()
    response = _client(manager).post(
        "/api/investigation/workbench/T1/bootstrap",
        json={"mode": "cluster_seed", "unexpected": 1},
    )
    assert response.status_code == 422
    manager.investigation_seed_service.bootstrap.assert_not_awaited()


def test_get_overview_never_seeds():
    manager = _manager()
    response = _client(manager).get("/api/investigation/workbench/T1")
    assert response.status_code == 200
    manager.investigation_seed_service.bootstrap.assert_not_awaited()


def test_bootstrap_seed_failure_maps_to_500():
    manager = _manager()
    manager.investigation_seed_service.bootstrap = AsyncMock(
        side_effect=RuntimeError("seed exploded")
    )
    response = _client(manager).post(
        "/api/investigation/workbench/T1/bootstrap",
        json={"mode": "cluster_seed"},
    )
    assert response.status_code == 500
    assert response.json()["detail"] == "investigation operation failed"


def test_bootstrap_unknown_task_maps_to_400():
    manager = _manager()
    manager.investigation_seed_service.bootstrap = AsyncMock(
        side_effect=KeyError("Task T1 not found")
    )
    response = _client(manager).post(
        "/api/investigation/workbench/T1/bootstrap",
        json={"mode": "cluster_seed"},
    )
    assert response.status_code == 400
