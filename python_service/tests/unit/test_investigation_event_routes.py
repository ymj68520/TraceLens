"""HTTP contract tests for the C7a Investigation Event API."""

from unittest.mock import AsyncMock, Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from httpserver.routes import investigation
from httpserver.services.evidence import (
    EvidenceNotFoundError,
    EvidenceStoreError,
    InvalidEvidenceKeyError,
)
from httpserver.services.investigation import (
    EventEvidenceLink,
    InvestigationEvent,
    InvestigationEventConflictError,
    InvestigationEventVersion,
)


def _event(**overrides):
    base = dict(
        event_id="ie_1",
        task_id="A",
        needs_refresh=False,
        current_version=1,
        title="事件",
        summary="叙述",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    base.update(overrides)
    return InvestigationEvent(**base)


def _link(**overrides):
    base = dict(
        task_id="A",
        event_id="ie_1",
        evidence_key="file:/case/a.txt",
        linked_at="2026-01-01T00:00:01+00:00",
        linked_by="analyst",
    )
    base.update(overrides)
    return EventEvidenceLink(**base)


def _version():
    return InvestigationEventVersion(
        task_id="A",
        event_id="ie_1",
        version=1,
        title="事件",
        summary="叙述",
        created_at="2026-01-01T00:00:00+00:00",
        created_by="analyst",
    )


def _client(service):
    app = FastAPI()
    app.include_router(investigation.router, prefix="/api/investigation")
    app.dependency_overrides[investigation.get_investigation_event_service] = lambda: service
    return TestClient(app)


def test_create_event_201_and_passes_exact_fields():
    service = Mock()
    service.create_event = AsyncMock(return_value=_event())
    response = _client(service).post(
        "/api/investigation/events",
        json={
            "task_id": "A",
            "title": "事件",
            "summary": "叙述",
            "created_by": "analyst",
        },
    )
    assert response.status_code == 201
    assert response.json()["event_id"] == "ie_1"
    assert response.json()["current_version"] == 1
    service.create_event.assert_awaited_once_with(
        "A", title="事件", summary="叙述", created_by="analyst"
    )


def test_create_event_strict_request_rejects_state_fields():
    service = Mock()
    service.create_event = AsyncMock()
    client = _client(service)
    for extra in ("needs_refresh", "current_version", "status", "version", "event_id"):
        body = {
            "task_id": "A", "title": "t", "created_by": "a", extra: "hack",
        }
        response = client.post("/api/investigation/events", json=body)
        assert response.status_code == 422, extra
    service.create_event.assert_not_called()


def test_list_events_200_and_needs_refresh_passthrough():
    service = Mock()
    service.list_events = AsyncMock(return_value=[_event(needs_refresh=True)])
    response = _client(service).get(
        "/api/investigation/events", params={"task_id": "A", "needs_refresh": "true"}
    )
    assert response.status_code == 200
    assert response.json()[0]["needs_refresh"] is True
    service.list_events.assert_awaited_once_with("A", needs_refresh=True)


def test_get_event_and_versions():
    service = Mock()
    service.get_event = AsyncMock(return_value=_event())
    service.list_event_versions = AsyncMock(return_value=[_version()])
    client = _client(service)

    detail = client.get("/api/investigation/events/ie_1", params={"task_id": "A"})
    assert detail.status_code == 200
    assert detail.json()["title"] == "事件"

    versions = client.get("/api/investigation/events/ie_1/versions", params={"task_id": "A"})
    assert versions.status_code == 200
    assert versions.json()[0]["version"] == 1


def test_link_evidence_success_and_error_mapping():
    service = Mock()
    service.link_event_evidence = AsyncMock(return_value=_link())
    client = _client(service)

    ok = client.post(
        "/api/investigation/events/ie_1/evidence",
        json={"task_id": "A", "evidence_key": "file:/case/a.txt", "linked_by": "analyst"},
    )
    assert ok.status_code == 200
    assert ok.json()["evidence_key"] == "file:/case/a.txt"
    service.link_event_evidence.assert_awaited_once_with(
        "A", "ie_1", "file:/case/a.txt", linked_by="analyst"
    )

    cases = (
        (InvalidEvidenceKeyError("bad"), 400, "invalid evidence key"),
        (EvidenceNotFoundError("missing"), 404, "investigation event or evidence not found"),
        (InvestigationEventConflictError("dup"), 409, "event evidence link already exists"),
        (EvidenceStoreError("db"), 503, "evidence store unavailable"),
    )
    for error, status_code, detail in cases:
        service.link_event_evidence = AsyncMock(side_effect=error)
        response = _client(service).post(
            "/api/investigation/events/ie_1/evidence",
            json={"task_id": "A", "evidence_key": "file:/x", "linked_by": "a"},
        )
        assert response.status_code == status_code
        assert response.json()["detail"] == detail


def test_link_strict_request_rejects_state_and_extra_fields():
    service = Mock()
    service.link_event_evidence = AsyncMock()
    client = _client(service)
    for extra in ("needs_refresh", "status", "linked_at", "event_id"):
        body = {
            "task_id": "A", "evidence_key": "file:/x", "linked_by": "a", extra: "hack",
        }
        response = client.post("/api/investigation/events/ie_1/evidence", json=body)
        assert response.status_code == 422, extra
    service.link_event_evidence.assert_not_called()


def test_list_event_evidence_200_and_404():
    service = Mock()
    service.list_event_evidence = AsyncMock(return_value=[_link()])
    response = _client(service).get(
        "/api/investigation/events/ie_1/evidence", params={"task_id": "A"}
    )
    assert response.status_code == 200
    assert response.json()[0]["event_id"] == "ie_1"

    service.list_event_evidence = AsyncMock(side_effect=EvidenceNotFoundError("x"))
    response = _client(service).get(
        "/api/investigation/events/ie_missing/evidence", params={"task_id": "A"}
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "investigation event not found"


def test_event_dependency_unavailable_maps_503(monkeypatch):
    app = FastAPI()
    app.include_router(investigation.router, prefix="/api/investigation")

    class UnavailableManager:
        @property
        def investigation_event_service(self):
            raise RuntimeError("manager is initializing")

    monkeypatch.setattr(investigation, "get_service_manager", lambda: UnavailableManager())
    response = TestClient(app).post(
        "/api/investigation/events",
        json={"task_id": "A", "title": "t", "created_by": "a"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "investigation event service is unavailable"


def test_event_routes_registered():
    from httpserver.main import _register_routes

    app = FastAPI()
    _register_routes(app)
    paths = app.openapi()["paths"]
    for path in (
        "/api/investigation/events",
        "/api/investigation/events/{event_id}",
        "/api/investigation/events/{event_id}/versions",
        "/api/investigation/events/{event_id}/evidence",
    ):
        assert path in paths
