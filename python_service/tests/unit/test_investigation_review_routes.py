"""HTTP contract tests for the C6 Analyst Review API."""

from unittest.mock import AsyncMock, Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from httpserver.routes import investigation
from httpserver.services.evidence import EvidenceNotFoundError, EvidenceStoreError
from httpserver.services.investigation import (
    AnalysisReviewConflictError,
    AnalysisGroundingStatus,
    SecondaryAnalysis,
    SecondaryAnalysisStatus,
)


def _analysis(status=SecondaryAnalysisStatus.review_pending):
    return SecondaryAnalysis(
        analysis_id="sa_1",
        task_id="A",
        evidence_key="file:/case/a.txt",
        snapshot_id=1,
        version=2,
        status=status,
        input_hash="hash",
        input_envelope_json="{}",
        prompt_version="investigation-evidence-analysis:v3",
        description="desc",
        summary="sum",
        model="m",
        created_at="2026-01-01T00:00:00+00:00",
        started_at="2026-01-01T00:00:01+00:00",
        review_pending_at="2026-01-01T00:00:02+00:00",
        decided_at=None,
        decided_by=None,
        decision_reason=None,
        failed_at=None,
        error_code=None,
        error_message=None,
        grounding_status=AnalysisGroundingStatus.VALID,
    )


def _client(service):
    app = FastAPI()
    app.include_router(investigation.router, prefix="/api/investigation")
    app.dependency_overrides[investigation.get_investigation_review_service] = lambda: service
    return TestClient(app)


def test_review_accepts_and_passes_exact_request_fields():
    service = Mock()
    service.review = AsyncMock(return_value=_analysis(SecondaryAnalysisStatus.accepted))
    response = _client(service).post(
        "/api/investigation/analyses/sa_1/review",
        json={
            "task_id": "A",
            "decision": "accepted",
            "reviewer": "analyst-1",
            "reason": "verified",
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert "snapshot_id" not in response.json()
    service.review.assert_awaited_once_with(
        "A",
        "sa_1",
        decision=investigation.AnalysisReviewDecision.accepted,
        reviewer="analyst-1",
        reason="verified",
    )


def test_review_supports_rejected_and_invalid():
    for decision in ("rejected", "invalid"):
        service = Mock()
        service.review = AsyncMock(return_value=_analysis(SecondaryAnalysisStatus(decision)))
        response = _client(service).post(
            "/api/investigation/analyses/sa_1/review",
            json={"task_id": "A", "decision": decision, "reviewer": "analyst"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == decision


def test_review_strict_request_rejects_internal_fields_and_invalid_values():
    service = Mock()
    service.review = AsyncMock()
    client = _client(service)
    for body in (
        {"task_id": "A", "decision": "running", "reviewer": "x"},
        {"task_id": "A", "decision": "accepted", "reviewer": "x", "status": "accepted"},
        {"task_id": "A", "decision": "accepted", "reviewer": "x", "grounding_status": "valid"},
        {"task_id": "A", "decision": "accepted", "reviewer": "x", "claims": []},
        {"task_id": "A", "decision": "accepted", "reviewer": "x", "description": "hack"},
        {"task_id": "A", "decision": "accepted", "reviewer": "",},
        {"task_id": "A", "decision": "accepted", "reviewer": "x", "reason": "r" * 4001},
    ):
        response = client.post("/api/investigation/analyses/sa_1/review", json=body)
        assert response.status_code == 422
    service.review.assert_not_called()


def test_review_maps_not_found_conflict_and_store_errors():
    cases = (
        (EvidenceNotFoundError("private path"), 404, "analysis not found"),
        (AnalysisReviewConflictError("queued"), 409, "analysis review conflict"),
        (EvidenceStoreError("private db path"), 503, "evidence store unavailable"),
    )
    for error, status_code, detail in cases:
        service = Mock()
        service.review = AsyncMock(side_effect=error)
        response = _client(service).post(
            "/api/investigation/analyses/sa_1/review",
            json={"task_id": "A", "decision": "accepted", "reviewer": "x"},
        )
        assert response.status_code == status_code
        assert response.json()["detail"] == detail
        assert "private" not in response.text


def test_review_dependency_unavailable_maps_503(monkeypatch):
    app = FastAPI()
    app.include_router(investigation.router, prefix="/api/investigation")

    class UnavailableManager:
        @property
        def investigation_review_service(self):
            raise RuntimeError("manager is initializing")

    monkeypatch.setattr(investigation, "get_service_manager", lambda: UnavailableManager())
    response = TestClient(app).post(
        "/api/investigation/analyses/sa_1/review",
        json={"task_id": "A", "decision": "accepted", "reviewer": "x"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "investigation review service is unavailable"


def test_review_route_registered():
    from httpserver.main import _register_routes

    app = FastAPI()
    _register_routes(app)
    assert "/api/investigation/analyses/{analysis_id}/review" in app.openapi()["paths"]
