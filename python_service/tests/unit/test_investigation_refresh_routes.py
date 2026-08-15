"""HTTP contract tests for C7c-1 Event Refresh admission/history."""

from unittest.mock import AsyncMock, Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from httpserver.routes import investigation
from httpserver.services.evidence import EvidenceNotFoundError, EvidenceStoreError
from httpserver.services.investigation import (
    EventRefresh,
    EventRefreshStatus,
    InvestigationEventConflictError,
)


def _refresh(status=EventRefreshStatus.queued):
    return EventRefresh(
        refresh_id="er_1",
        task_id="A",
        event_id="ie_1",
        base_version=1,
        status=status,
        requested_by="analyst",
        input_hash="hash",
        input_envelope_json='{"schema_version":1}',
        created_at="2026-01-01T00:00:00+00:00",
    )


def _client(service):
    app = FastAPI()
    app.include_router(investigation.router, prefix="/api/investigation")
    app.dependency_overrides[investigation.get_event_refresh_executor] = lambda: service
    app.dependency_overrides[investigation.get_investigation_event_service] = lambda: service
    return TestClient(app)


def test_create_refresh_201_and_passes_request_fields():
    service = Mock()
    service.submit = AsyncMock(return_value=_refresh())
    response = _client(service).post(
        "/api/investigation/events/ie_1/refresh",
        json={"task_id": "A", "requested_by": "analyst"},
    )
    assert response.status_code == 201
    assert response.json()["refresh_id"] == "er_1"
    service.submit.assert_awaited_once_with(
        "A", "ie_1", requested_by="analyst"
    )


def test_list_refresh_history_200():
    service = Mock()
    service.list_event_refreshes = AsyncMock(return_value=[_refresh()])
    response = _client(service).get(
        "/api/investigation/events/ie_1/refreshes", params={"task_id": "A"}
    )
    assert response.status_code == 200
    assert response.json()[0]["status"] == "queued"
    service.list_event_refreshes.assert_awaited_once_with("A", "ie_1")


def test_refresh_strict_request_rejects_internal_fields():
    service = Mock()
    service.submit = AsyncMock()
    client = _client(service)
    for extra in ("status", "input_hash", "needs_refresh", "event_id", "base_version"):
        response = client.post(
            "/api/investigation/events/ie_1/refresh",
            json={"task_id": "A", "requested_by": "a", extra: "hack"},
        )
        assert response.status_code == 422, extra
    service.submit.assert_not_called()


def test_refresh_maps_404_409_503():
    cases = (
        (EvidenceNotFoundError("missing"), 404, "investigation event not found"),
        (InvestigationEventConflictError("active"), 409, "event refresh already in progress"),
        (EvidenceStoreError("db"), 503, "evidence store unavailable"),
    )
    for error, status, detail in cases:
        service = Mock()
        service.submit = AsyncMock(side_effect=error)
        response = _client(service).post(
            "/api/investigation/events/ie_1/refresh",
            json={"task_id": "A", "requested_by": "a"},
        )
        assert response.status_code == status
        assert response.json()["detail"] == detail


def test_refresh_history_maps_not_found_and_store():
    for error, status, detail in (
        (EvidenceNotFoundError("missing"), 404, "investigation event not found"),
        (EvidenceStoreError("db"), 503, "evidence store unavailable"),
    ):
        service = Mock()
        service.list_event_refreshes = AsyncMock(side_effect=error)
        response = _client(service).get(
            "/api/investigation/events/ie_1/refreshes", params={"task_id": "A"}
        )
        assert response.status_code == status
        assert response.json()["detail"] == detail


def test_refresh_routes_registered():
    from httpserver.main import _register_routes

    app = FastAPI()
    _register_routes(app)
    paths = app.openapi()["paths"]
    assert "/api/investigation/events/{event_id}/refresh" in paths
    assert "/api/investigation/events/{event_id}/refreshes" in paths
