"""HTTP contract tests for the C9a Workbench read-only API surface."""

from unittest.mock import AsyncMock, Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from httpserver.routes import investigation
from httpserver.services.evidence import (
    EvidenceNotFoundError,
    EvidenceStoreError,
)
from httpserver.services.investigation import (
    AnalysisClaim,
    ClaimGroundingStatus,
    ClaimType,
    EvidenceSnapshot,
    EvidenceSummary,
    FileSnapshotPayload,
    InvestigationReadService,
    SelectedAnalysisRef,
)

KEY_A = "file:/case/a.txt"
KEY_B = "file:/case/b.txt"


def _summary(key=KEY_A, selection="default"):
    if selection == "default":
        selection = dict(
            evidence_key=key,
            analysis_id="sa_1",
            version=2,
            review_state="accepted",
            summary="accepted summary",
        )
    selected = SelectedAnalysisRef(**selection) if selection else None
    return EvidenceSummary(
        task_id="A",
        evidence_key=key,
        evidence_type="file",
        captured_at=1_700_000_000,
        selected_analysis=selected,
    )


def _snapshot(key=KEY_A):
    return EvidenceSnapshot(
        task_id="A",
        evidence_key=key,
        evidence_type="file",
        captured_at=1_700_000_000,
        payload=FileSnapshotPayload(
            normalized_path=key.removeprefix("file:"),
            initial_summary="initial summary",
            initial_description="initial description",
            initial_model="model-x",
        ),
        snapshot_id=1,
    )


def _claim(claim_id="cl_1", analysis_id="sa_1"):
    return AnalysisClaim(
        claim_id=claim_id,
        analysis_id=analysis_id,
        claim_index=0,
        claim_type=ClaimType.FACT,
        claim_text="exact persisted claim",
        grounding_status=ClaimGroundingStatus.GROUNDED,
        warnings=None,
        evidence_refs=(KEY_A,),
        created_at="2026-08-15T00:00:00+00:00",
    )


def _service_mock(**list_evidence):
    service = Mock(spec=InvestigationReadService)
    service.list_evidence = AsyncMock(**list_evidence)
    service.get_snapshot = AsyncMock()
    service.list_analysis_claims = AsyncMock()
    return service


def _client(service):
    app = FastAPI()
    app.include_router(investigation.router, prefix="/api/investigation")
    app.dependency_overrides[
        investigation.get_investigation_read_service
    ] = lambda: service
    return TestClient(app)


def test_evidence_list_200_passthrough():
    service = _service_mock(return_value=[_summary(KEY_A), _summary(KEY_B)])
    response = _client(service).get("/api/investigation/evidence", params={"task_id": "A"})
    assert response.status_code == 200
    body = response.json()
    assert [row["evidence_key"] for row in body] == [KEY_A, KEY_B]
    assert body[0]["selected_analysis"]["review_state"] == "accepted"
    assert body[0]["selected_analysis"]["analysis_id"] == "sa_1"
    service.list_evidence.assert_awaited_once_with("A")


def test_evidence_list_without_selection_state():
    service = _service_mock(return_value=[
        EvidenceSummary(
            task_id="A",
            evidence_key=KEY_A,
            evidence_type="file",
            captured_at=1,
            selected_analysis=None,
        ),
    ])
    response = _client(service).get("/api/investigation/evidence", params={"task_id": "A"})
    assert response.status_code == 200
    assert response.json()[0]["selected_analysis"] is None


def test_evidence_list_task_not_found_404():
    service = _service_mock(side_effect=EvidenceNotFoundError("task not found"))
    response = _client(service).get("/api/investigation/evidence", params={"task_id": "X"})
    assert response.status_code == 404
    assert response.json()["detail"] == "task not found"


def test_evidence_list_store_failure_503():
    service = _service_mock(side_effect=EvidenceStoreError("unavailable"))
    response = _client(service).get("/api/investigation/evidence", params={"task_id": "A"})
    assert response.status_code == 503


def test_snapshot_200_returns_frozen_initial_analysis():
    service = _service_mock()
    service.get_snapshot = AsyncMock(return_value=_snapshot())
    response = _client(service).get(
        "/api/investigation/evidence/snapshot",
        params={"task_id": "A", "evidence_key": KEY_A},
    )
    assert response.status_code == 200
    payload = response.json()["payload"]
    assert payload["initial_description"] == "initial description"
    assert payload["initial_summary"] == "initial summary"
    assert payload["initial_model"] == "model-x"
    # A12: the internal snapshot_id never serializes
    assert "snapshot_id" not in response.json()
    service.get_snapshot.assert_awaited_once_with("A", KEY_A)


def test_snapshot_canonicalizes_the_evidence_key():
    service = _service_mock()
    service.get_snapshot = AsyncMock(return_value=_snapshot())
    response = _client(service).get(
        "/api/investigation/evidence/snapshot",
        params={"task_id": "A", "evidence_key": "file:\\case\\a.txt"},
    )
    assert response.status_code == 200
    service.get_snapshot.assert_awaited_once_with("A", KEY_A)


def test_snapshot_never_captured_404():
    service = _service_mock()
    service.get_snapshot = AsyncMock(return_value=None)
    response = _client(service).get(
        "/api/investigation/evidence/snapshot",
        params={"task_id": "A", "evidence_key": KEY_B},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "evidence snapshot not found"


def test_snapshot_invalid_key_400():
    service = _service_mock()
    response = _client(service).get(
        "/api/investigation/evidence/snapshot",
        params={"task_id": "A", "evidence_key": "not-a-key"},
    )
    assert response.status_code == 400
    service.get_snapshot.assert_not_awaited()


def test_snapshot_store_failure_503():
    service = _service_mock()
    service.get_snapshot = AsyncMock(side_effect=EvidenceStoreError("corrupt"))
    response = _client(service).get(
        "/api/investigation/evidence/snapshot",
        params={"task_id": "A", "evidence_key": KEY_A},
    )
    assert response.status_code == 503


def test_claims_200_exact_analysis_only():
    service = _service_mock()
    service.list_analysis_claims = AsyncMock(return_value=[_claim()])
    response = _client(service).get(
        "/api/investigation/analyses/sa_1/claims", params={"task_id": "A"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["analysis_id"] == "sa_1"
    assert body["task_id"] == "A"
    assert body["claims"][0]["claim_id"] == "cl_1"
    assert body["claims"][0]["claim_text"] == "exact persisted claim"
    assert body["claims"][0]["evidence_refs"] == [KEY_A]
    service.list_analysis_claims.assert_awaited_once_with("A", "sa_1")


def test_claims_empty_for_claimless_analysis():
    service = _service_mock()
    service.list_analysis_claims = AsyncMock(return_value=[])
    response = _client(service).get(
        "/api/investigation/analyses/sa_9/claims", params={"task_id": "A"}
    )
    assert response.status_code == 200
    assert response.json()["claims"] == []


def test_claims_unknown_analysis_404():
    service = _service_mock()
    service.list_analysis_claims = AsyncMock(return_value=None)
    response = _client(service).get(
        "/api/investigation/analyses/sa_x/claims", params={"task_id": "A"}
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "analysis not found"


def test_claims_store_failure_503():
    service = _service_mock()
    service.list_analysis_claims = AsyncMock(side_effect=EvidenceStoreError("nope"))
    response = _client(service).get(
        "/api/investigation/analyses/sa_1/claims", params={"task_id": "A"}
    )
    assert response.status_code == 503
