"""Route contract for POST /api/reports/generate and GET generations (R2c).

Exact-ID admission/polling only; fixed-string error details; the request
carries nothing but task_id + requested_by.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from httpserver.routes import report_generation
from httpserver.services.evidence.exceptions import (
    EvidenceNotFoundError,
    EvidenceStoreError,
)
from httpserver.services.forensic_report.generation import (
    ReportGenerationInputError,
)
from httpserver.services.forensic_report.models import ReportGenerationInput


def _row(**overrides) -> ReportGenerationInput:
    payload = dict(
        generation_id="rg_1",
        task_id="A",
        scope_type="task",
        scope_id="A",
        status="admitted",
        requested_by="analyst-x",
        input_schema_version=1,
        prompt_version="final-report:v1",
        input_envelope_json="{}",
        input_hash="h" * 64,
        report_id=None,
        produced_version=None,
        model=None,
        created_at="2026",
        started_at=None,
        completed_at=None,
        failed_at=None,
        error_code=None,
        error_message=None,
    )
    payload.update(overrides)
    return ReportGenerationInput(**payload)


class FakeAdmissionService:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    async def admit(self, task_id, *, requested_by):
        self.calls.append((task_id, requested_by))
        if self.error is not None:
            raise self.error
        return self.result


class FakeExecutor:
    def __init__(self):
        self.submitted = []

    async def submit(self, generation_id):
        self.submitted.append(generation_id)


def make_client(service, executor, strict_reader, monkeypatch):
    monkeypatch.setattr(report_generation, "read_generation_strict", strict_reader)
    app = FastAPI()
    app.include_router(report_generation.router, prefix="/api/reports")
    app.dependency_overrides[report_generation.get_report_generation_admission_service] = (
        lambda: service
    )
    app.dependency_overrides[report_generation.get_report_generation_executor] = (
        lambda: executor
    )
    return TestClient(app)


def _identity_reader(row):
    def reader(db_path, generation_id):
        del db_path
        if row is not None and row.generation_id == generation_id:
            return row
        return None

    return reader


def test_generate_admits_and_submits_exact_id(monkeypatch):
    service = FakeAdmissionService(result=_row())
    executor = FakeExecutor()
    client = make_client(service, executor, _identity_reader(None), monkeypatch)

    response = client.post("/api/reports/generate", json={
        "task_id": "A", "requested_by": "analyst-x",
    })

    assert response.status_code == 202
    assert response.json()["generation_id"] == "rg_1"
    assert service.calls == [("A", "analyst-x")]
    assert executor.submitted == ["rg_1"]


def test_generate_rejects_client_controlled_fields(monkeypatch):
    service = FakeAdmissionService(result=_row())
    client = make_client(service, FakeExecutor(), _identity_reader(None), monkeypatch)

    for field, value in (
        ("evidence_keys", ["file:/a"]),
        ("analysis_ids", ["A1"]),
        ("prompt_version", "final-report:v9"),
        ("model", "gpt"),
        ("input_envelope", {}),
    ):
        response = client.post("/api/reports/generate", json={
            "task_id": "A", "requested_by": "x", field: value,
        })
        assert response.status_code == 422


def test_generate_error_mapping(monkeypatch):
    cases = [
        (ReportGenerationInputError("no_report_evidence", "m"), 409, "task has no report evidence"),
        (ReportGenerationInputError("invalid_report_evidence_binding", "m"), 409, "report evidence binding is invalid"),
        (EvidenceNotFoundError("task not found"), 404, "task not found"),
        (EvidenceStoreError("store"), 503, "report generation store is unavailable"),
    ]
    for error, status, detail in cases:
        service = FakeAdmissionService(error=error)
        client = make_client(service, FakeExecutor(), _identity_reader(None), monkeypatch)
        response = client.post("/api/reports/generate", json={
            "task_id": "A", "requested_by": "x",
        })
        assert response.status_code == status
        assert response.json()["detail"] == detail


def test_get_generation_exact_id_and_task_scope(monkeypatch):
    row = _row(status="failed", error_code="llm_timeout",
               error_message="LLM request timed out", failed_at="2026")
    client = make_client(FakeAdmissionService(), FakeExecutor(), _identity_reader(row), monkeypatch)

    ok = client.get("/api/reports/generations/rg_1", params={"task_id": "A"})
    assert ok.status_code == 200
    body = ok.json()
    assert body["status"] == "failed"
    assert body["error_code"] == "llm_timeout"
    assert body["report"] is None

    wrong_task = client.get("/api/reports/generations/rg_1", params={"task_id": "B"})
    assert wrong_task.status_code == 404
    assert wrong_task.json()["detail"] == "report generation not found"

    unknown = client.get("/api/reports/generations/rg_ghost", params={"task_id": "A"})
    assert unknown.status_code == 404


def test_get_completed_generation_embeds_manifest(monkeypatch):
    row = _row(status="completed", report_id="rep_1", produced_version=1,
               model="m", completed_at="2026")

    class FakeWriter:
        def __init__(self, root):
            pass

        def read_manifest(self, task_id, report_id):
            return {"title": "T", "report_id": report_id}

    monkeypatch.setattr(report_generation, "GenerationReportWriter", FakeWriter)
    client = make_client(FakeAdmissionService(), FakeExecutor(), _identity_reader(row), monkeypatch)

    response = client.get("/api/reports/generations/rg_1", params={"task_id": "A"})
    assert response.status_code == 200
    assert response.json()["report"] == {"title": "T", "report_id": "rep_1"}


def test_get_completed_generation_missing_manifest_is_503(monkeypatch):
    row = _row(status="completed", report_id="rep_1", produced_version=1,
               model="m", completed_at="2026")

    class BrokenWriter:
        def __init__(self, root):
            pass

        def read_manifest(self, task_id, report_id):
            raise FileNotFoundError("gone")

    monkeypatch.setattr(report_generation, "GenerationReportWriter", BrokenWriter)
    client = make_client(FakeAdmissionService(), FakeExecutor(), _identity_reader(row), monkeypatch)

    response = client.get("/api/reports/generations/rg_1", params={"task_id": "A"})
    assert response.status_code == 503
    assert response.json()["detail"] == "report generation record is unavailable"
