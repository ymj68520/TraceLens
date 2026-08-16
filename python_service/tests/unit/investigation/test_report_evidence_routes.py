"""HTTP contract tests for /api/reports/evidence (Phase R1)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from httpserver.routes import report_evidence
from httpserver.services.evidence import (
    EvidenceNotFoundError,
    EvidenceStoreError,
)
from httpserver.services.investigation import (
    AnalysisBindingConflictError,
    ReportEvidenceConflictError,
    ReportEvidenceItem,
    ReportEvidenceStatus,
)

KEY = "file:/case/a.txt"


def item(**overrides) -> ReportEvidenceItem:
    values = {
        "task_id": "A",
        "evidence_key": KEY,
        "report_status": ReportEvidenceStatus.main,
        "analysis_id": None,
        "added_by": "analyst-x",
        "created_at": "2026-08-16T00:00:00+00:00",
        "updated_at": "2026-08-16T00:00:00+00:00",
        "updated_by": "analyst-x",
        "newer_accepted_available": False,
    }
    values.update(overrides)
    return ReportEvidenceItem.model_validate(values)


class FakeReportEvidenceService:
    def __init__(self) -> None:
        self.added: list[dict] = []
        self.updated: list[dict] = []
        self.listed: list[str] = []
        self.list_result: list[ReportEvidenceItem] | Exception = []
        self.add_result: ReportEvidenceItem | Exception = item()
        self.update_result: ReportEvidenceItem | Exception = item()

    async def list(self, task_id: str) -> list[ReportEvidenceItem]:
        self.listed.append(task_id)
        if isinstance(self.list_result, Exception):
            raise self.list_result
        return self.list_result

    async def add(self, task_id, evidence_key, *, report_status,
                  analysis_id=None, added_by) -> ReportEvidenceItem:
        self.added.append({
            "task_id": task_id, "evidence_key": evidence_key,
            "report_status": report_status, "analysis_id": analysis_id,
            "added_by": added_by,
        })
        if isinstance(self.add_result, Exception):
            raise self.add_result
        return self.add_result

    async def update(self, task_id, evidence_key, *, report_status=None,
                     analysis_id=None, bind_analysis=False,
                     updated_by) -> ReportEvidenceItem:
        self.updated.append({
            "task_id": task_id, "evidence_key": evidence_key,
            "report_status": report_status, "analysis_id": analysis_id,
            "bind_analysis": bind_analysis, "updated_by": updated_by,
        })
        if isinstance(self.update_result, Exception):
            raise self.update_result
        return self.update_result


def make_client(service: FakeReportEvidenceService) -> TestClient:
    app = FastAPI()
    app.include_router(report_evidence.router, prefix="/api/reports")
    app.dependency_overrides[report_evidence.get_report_evidence_service] = (
        lambda: service
    )
    return TestClient(app)


def test_list_passes_task_and_returns_items() -> None:
    service = FakeReportEvidenceService()
    service.list_result = [item()]
    response = make_client(service).get("/api/reports/evidence?task_id=A")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["evidence_key"] == KEY
    assert body[0]["report_status"] == "main"
    assert body[0]["newer_accepted_available"] is False
    assert service.listed == ["A"]


def test_list_maps_task_and_store_errors() -> None:
    service = FakeReportEvidenceService()
    service.list_result = EvidenceNotFoundError("task not found")
    client = make_client(service)
    assert client.get("/api/reports/evidence?task_id=A").status_code == 404

    service.list_result = EvidenceStoreError("store unavailable")
    assert client.get("/api/reports/evidence?task_id=A").status_code == 503


def test_add_sends_canonical_key_and_explicit_fields() -> None:
    service = FakeReportEvidenceService()
    service.add_result = item(report_status=ReportEvidenceStatus.appendix)
    response = make_client(service).post("/api/reports/evidence", json={
        "task_id": "A",
        "evidence_key": "file:\\case\\a.txt",  # backslash canonicalized
        "report_status": "appendix",
        "added_by": "analyst-x",
    })

    assert response.status_code == 200
    assert service.added == [{
        "task_id": "A", "evidence_key": KEY,
        "report_status": "appendix", "analysis_id": None,
        "added_by": "analyst-x",
    }]
    assert response.json()["report_status"] == "appendix"


def test_add_rejects_unknown_and_extra_fields() -> None:
    client = make_client(FakeReportEvidenceService())
    assert client.post("/api/reports/evidence", json={
        "task_id": "A", "evidence_key": KEY,
        "report_status": "excluded",  # excluded only reachable via PUT
        "added_by": "x",
    }).status_code == 422
    assert client.post("/api/reports/evidence", json={
        "task_id": "A", "evidence_key": KEY,
        "report_status": "main", "added_by": "x",
        "db_path": "/etc/passwd",  # no client paths
    }).status_code == 422


def test_add_maps_conflicts_and_not_found() -> None:
    service = FakeReportEvidenceService()
    client = make_client(service)

    service.add_result = EvidenceNotFoundError("evidence snapshot not captured")
    r = client.post("/api/reports/evidence", json={
        "task_id": "A", "evidence_key": KEY,
        "report_status": "main", "added_by": "x",
    })
    assert r.status_code == 404
    assert r.json()["detail"] == "task or evidence not found"

    service.add_result = AnalysisBindingConflictError("not accepted")
    r = client.post("/api/reports/evidence", json={
        "task_id": "A", "evidence_key": KEY,
        "report_status": "main", "analysis_id": "sa_x", "added_by": "x",
    })
    assert r.status_code == 409
    assert r.json()["detail"] == "analysis binding conflict"

    service.add_result = ReportEvidenceConflictError("already exists")
    r = client.post("/api/reports/evidence", json={
        "task_id": "A", "evidence_key": KEY,
        "report_status": "main", "added_by": "x",
    })
    assert r.status_code == 409
    assert r.json()["detail"] == "report evidence already exists"


def test_add_invalid_evidence_key_is_400() -> None:
    client = make_client(FakeReportEvidenceService())
    response = client.post("/api/reports/evidence", json={
        "task_id": "A", "evidence_key": "not-a-canonical-key",
        "report_status": "main", "added_by": "x",
    })
    assert response.status_code == 400
    assert response.json()["detail"] == "invalid evidence key"


def test_update_rebind_and_status_pass_through() -> None:
    service = FakeReportEvidenceService()
    response = make_client(service).put("/api/reports/evidence", json={
        "task_id": "A",
        "evidence_key": KEY,
        "report_status": "excluded",
        "analysis_id": "sa_2",
        "updated_by": "analyst-y",
    })

    assert response.status_code == 200
    assert service.updated == [{
        "task_id": "A", "evidence_key": KEY,
        "report_status": "excluded", "analysis_id": "sa_2",
        "bind_analysis": True, "updated_by": "analyst-y",
    }]


def test_update_status_only_keeps_binding() -> None:
    service = FakeReportEvidenceService()
    response = make_client(service).put("/api/reports/evidence", json={
        "task_id": "A", "evidence_key": KEY,
        "report_status": "appendix", "updated_by": "y",
    })

    assert response.status_code == 200
    assert service.updated[0]["analysis_id"] is None
    assert service.updated[0]["bind_analysis"] is False


def test_update_requires_a_change() -> None:
    client = make_client(FakeReportEvidenceService())
    response = client.put("/api/reports/evidence", json={
        "task_id": "A", "evidence_key": KEY, "updated_by": "y",
    })
    assert response.status_code == 422
    assert response.json()["detail"] == "report_status or analysis_id is required"


def test_update_maps_not_found_and_conflict() -> None:
    service = FakeReportEvidenceService()
    client = make_client(service)

    service.update_result = EvidenceNotFoundError("report evidence not found")
    r = client.put("/api/reports/evidence", json={
        "task_id": "A", "evidence_key": KEY,
        "report_status": "main", "updated_by": "y",
    })
    assert r.status_code == 404
    assert r.json()["detail"] == "task or report evidence not found"

    service.update_result = AnalysisBindingConflictError("not accepted")
    r = client.put("/api/reports/evidence", json={
        "task_id": "A", "evidence_key": KEY,
        "analysis_id": "sa_2", "updated_by": "y",
    })
    assert r.status_code == 409
    assert r.json()["detail"] == "analysis binding conflict"
