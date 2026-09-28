"""D3b soft-retirement contract for legacy case-analysis generation."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from httpserver.routes import case_analysis, multi_analysis
from httpserver.routes.case_analysis_endpoints import _case


RETIRED_DETAIL = "legacy case analysis generation has been retired; use report generation"


def _client():
    app = FastAPI()
    app.include_router(case_analysis.router, prefix="/api/llm")
    return TestClient(app)


def test_case_analysis_post_returns_retired_without_scheduling(monkeypatch):
    calls = []

    def fail_if_called(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("retired writer must not be invoked")

    monkeypatch.setattr(_case, "_get_case_analysis_service", fail_if_called)
    monkeypatch.setattr(_case.asyncio, "create_task", fail_if_called)
    monkeypatch.setattr(_case, "_analysis_jobs", {})

    response = _client().post(
        "/api/llm/case-analysis",
        json={"task_id": "task-1"},
    )

    assert response.status_code == 410
    assert response.json()["detail"] == RETIRED_DETAIL
    assert calls == []
    assert _case._analysis_jobs == {}


def test_legacy_status_job_returns_retired_contract(monkeypatch):
    monkeypatch.setattr(
        _case,
        "_analysis_jobs",
        {"legacy-job": {"status": "running"}},
    )

    response = _client().get("/api/llm/case-analysis/legacy-job")

    assert response.status_code == 410
    assert response.json()["detail"] == RETIRED_DETAIL


def test_cross_image_completion_requires_matching_persisted_report():
    class Service:
        def __init__(self, report):
            self.report = report

        def get_cross_image_report(self, case_id):
            assert case_id == "case-1"
            return self.report

    result = {"steps": {"report": {"report": "Combined evidence report"}}}
    multi_analysis.require_persisted_cross_image_report(
        Service({"case_report": "Combined evidence report"}), "case-1", result
    )
    with pytest.raises(multi_analysis.MissingCrossImageReport, match="not persisted"):
        multi_analysis.require_persisted_cross_image_report(Service(None), "case-1", result)
    with pytest.raises(multi_analysis.MissingCrossImageReport, match="not persisted"):
        multi_analysis.require_persisted_cross_image_report(
            Service({"case_report": "Old report"}), "case-1", result
        )
    with pytest.raises(multi_analysis.MissingCrossImageReport, match="generation failed"):
        multi_analysis.require_persisted_cross_image_report(
            Service({"case_report": "Old report"}),
            "case-1",
            {"steps": {"report": {"error": "LLM unavailable", "report": "报告生成失败：LLM unavailable"}}},
        )
