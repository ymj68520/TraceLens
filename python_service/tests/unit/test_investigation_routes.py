"""HTTP contract tests for the C3 Investigation Snapshot route."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from httpserver.routes import investigation
from httpserver.services.evidence import (
    EvidenceNotFoundError,
    EvidenceStoreError,
    InvalidEvidenceKeyError,
)
from httpserver.services.investigation.models import EvidenceSnapshot, FileSnapshotPayload


def _snapshot():
    return EvidenceSnapshot(
        task_id="A",
        evidence_key="file:/case/a.txt",
        evidence_type="file",
        captured_at=123,
        payload=FileSnapshotPayload(normalized_path="/case/a.txt", name="a.txt"),
        snapshot_id=1,
    )


def _client(service):
    app = FastAPI()
    app.include_router(investigation.router, prefix="/api/investigation")
    app.dependency_overrides[investigation.get_investigation_service] = lambda: service
    return TestClient(app)


def test_success_returns_canonical_snapshot_without_source_db():
    service = Mock()
    service.capture = AsyncMock(return_value=_snapshot())
    response = _client(service).post(
        "/api/investigation/snapshots",
        json={"task_id": "A", "evidence_key": r"file:\case\a.txt"},
    )
    assert response.status_code == 200
    assert response.json()["evidence_key"] == "file:/case/a.txt"
    assert "source_db" not in response.json()
    assert "snapshot_id" not in response.json()  # A12: internal key never serialized
    service.capture.assert_awaited_once_with("A", r"file:\case\a.txt")


def test_invalid_key_maps_400():
    service = Mock()
    service.capture = AsyncMock(side_effect=InvalidEvidenceKeyError("bad"))
    response = _client(service).post(
        "/api/investigation/snapshots",
        json={"task_id": "A", "evidence_key": "bad:key"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "invalid evidence key"


def test_not_found_maps_404_without_internal_detail():
    service = Mock()
    service.capture = AsyncMock(side_effect=EvidenceNotFoundError("/private/task/path"))
    response = _client(service).post(
        "/api/investigation/snapshots",
        json={"task_id": "A", "evidence_key": "file:/x"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "evidence not found"
    assert "/private" not in response.text


def test_store_error_maps_503_without_internal_detail():
    service = Mock()
    service.capture = AsyncMock(side_effect=EvidenceStoreError("/private/store.db"))
    response = _client(service).post(
        "/api/investigation/snapshots",
        json={"task_id": "A", "evidence_key": "file:/x"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "evidence store unavailable"
    assert "/private" not in response.text


def test_missing_required_fields_are_422():
    service = Mock()
    service.capture = AsyncMock()
    client = _client(service)
    for body in ({"task_id": "A"}, {"evidence_key": "file:/x"}, {}):
        response = client.post("/api/investigation/snapshots", json=body)
        assert response.status_code == 422
    service.capture.assert_not_called()


def test_client_paths_and_other_extras_are_422_and_not_called():
    service = Mock()
    service.capture = AsyncMock()
    client = _client(service)
    for extra in ("file_path", "files_db_path", "events_db_path", "raw_db_path", "anything"):
        response = client.post(
            "/api/investigation/snapshots",
            json={"task_id": "A", "evidence_key": "file:/x", extra: "/private/db"},
        )
        assert response.status_code == 422, extra
    service.capture.assert_not_called()


def test_service_dependency_unavailable_maps_503(monkeypatch):
    app = FastAPI()
    app.include_router(investigation.router, prefix="/api/investigation")

    class UnavailableManager:
        @property
        def investigation_service(self):
            raise RuntimeError("manager is not ready")

    monkeypatch.setattr(
        investigation,
        "get_service_manager",
        lambda: UnavailableManager(),
    )
    # Use the real dependency rather than an override for this lifecycle path.
    response = TestClient(app).post(
        "/api/investigation/snapshots",
        json={"task_id": "A", "evidence_key": "file:/x"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "investigation service is unavailable"


def test_main_route_registration():
    from httpserver.main import _register_routes

    app = FastAPI()
    _register_routes(app)
    assert "/api/investigation/snapshots" in app.openapi()["paths"]
