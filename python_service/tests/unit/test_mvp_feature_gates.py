"""MVP feature-gate tests (docs/specs/mvp-phase1-acceptance.md §4).

The phase-1 acceptance build ships with events carrying no LLM analysis,
events excluded from report evidence, and combined-case / workbench-LLM
features disabled. These tests pin the gates in their default (MVP) state;
per-feature behavior tests enable the flags in their own fixtures.
"""

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from httpserver.config import get_settings
from httpserver.routes import event_cluster_analysis as eca_routes
from httpserver.routes import investigation_workbench
from httpserver.routes.event_cluster_analysis import router as eca_router
from httpserver.routes.multi_analysis import router as multi_router
from httpserver.routes.system import router as system_router
from httpserver.routes.investigation_workbench import (
    _manager,
    router as workbench_router,
)


@pytest.fixture(autouse=True)
def _mvp_defaults(monkeypatch):
    """Pin all MVP switches to their shipping (disabled) defaults."""
    settings = get_settings()
    monkeypatch.setattr(settings, "event_llm_analysis_enabled", False, raising=False)
    monkeypatch.setattr(settings, "combined_case_enabled", False, raising=False)
    monkeypatch.setattr(settings, "workbench_llm_enabled", False, raising=False)


# ---------------------------------------------------------------------------
# event LLM analysis disabled
# ---------------------------------------------------------------------------

def test_analyze_event_cluster_returns_503():
    from httpserver.routes.llm_endpoints import _analysis

    app = FastAPI()
    app.include_router(_analysis.router, prefix="/api/llm")
    client = TestClient(app)
    resp = client.post(
        "/api/llm/analyze-event-cluster", json={"task_id": "t1"}
    )
    assert resp.status_code == 503
    assert "MVP" in resp.json()["detail"]


def test_event_cluster_analysis_run_returns_503(tmp_path, monkeypatch):
    app = FastAPI()
    app.include_router(eca_router, prefix="/api/llm")
    client = TestClient(app)
    resp = client.post(
        "/api/llm/event-cluster-analysis/run", json={"task_id": "t1"}
    )
    assert resp.status_code == 503
    assert "MVP" in resp.json()["detail"]
    # no background job may have been registered
    assert eca_routes._run_jobs == {}


def test_event_cluster_analysis_estimate_stays_available(tmp_path, monkeypatch):
    """estimate is pure SQL (no LLM) and keeps working in the MVP."""
    events_db = tmp_path / "events.db"
    with sqlite3.connect(events_db) as conn:
        conn.execute(
            "CREATE TABLE events (id INTEGER PRIMARY KEY, timestamp INTEGER,"
            " event_type TEXT, file_path TEXT, llm_analyzed_at INTEGER)"
        )
        conn.execute(
            "INSERT INTO events (timestamp, event_type, file_path) VALUES"
            " (120, 'MODIFIED', '/a'), (130, 'MODIFIED', '/b')"
        )

    class _Backend:
        async def get_task(self, task_id):
            return {"output_events_db": str(events_db)}

    class _Manager:
        cpp_backend = _Backend()

    monkeypatch.setattr("httpserver.services.get_service_manager", lambda: _Manager())
    app = FastAPI()
    app.include_router(eca_router, prefix="/api/llm")
    client = TestClient(app)
    resp = client.post("/api/llm/event-cluster-analysis/estimate", json={"task_id": "t1"})
    assert resp.status_code == 200
    assert "estimates" in resp.json()


# ---------------------------------------------------------------------------
# combined case disabled
# ---------------------------------------------------------------------------

def test_create_case_returns_503():
    app = FastAPI()
    app.include_router(multi_router)
    client = TestClient(app)
    resp = client.post(
        "/api/llm/cases", json={"name": "case", "task_ids": []}
    )
    assert resp.status_code == 503
    assert "MVP" in resp.json()["detail"]


def test_multi_image_analysis_returns_503():
    app = FastAPI()
    app.include_router(multi_router)
    client = TestClient(app)
    resp = client.post(
        "/api/llm/multi-image-analysis",
        json={
            "case_id": "c1",
            "task_ids": ["t1"],
            "files_db_paths": ["/tmp/files.db"],
            "case_description": "d",
        },
    )
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# workbench LLM disabled
# ---------------------------------------------------------------------------

def test_workbench_secondary_analysis_returns_503():
    app = FastAPI()
    app.include_router(workbench_router, prefix="/api/investigation/workbench")
    app.dependency_overrides[_manager] = lambda: object()
    try:
        client = TestClient(app)
        resp = client.post(
            "/api/investigation/workbench/t1/evidence/analyze",
            json={"evidence_key": "file:/a.txt"},
        )
        assert resp.status_code == 503
        assert "MVP" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_workbench_event_refresh_returns_503():
    app = FastAPI()
    app.include_router(workbench_router, prefix="/api/investigation/workbench")
    app.dependency_overrides[_manager] = lambda: object()
    try:
        client = TestClient(app)
        resp = client.post(
            "/api/investigation/workbench/t1/events/e1/refresh", json={}
        )
        assert resp.status_code == 503
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# events are never report evidence
# ---------------------------------------------------------------------------

def test_report_evidence_rejects_cluster_key():
    from fastapi import HTTPException

    from httpserver.routes.report_evidence import _canonical_key

    with pytest.raises(HTTPException) as excinfo:
        _canonical_key("cluster:v1:28331457:CREATED")
    assert excinfo.value.status_code == 422


def test_report_evidence_accepts_file_key():
    from httpserver.routes.report_evidence import _canonical_key

    assert _canonical_key("file:/case/a.txt").startswith("file:")


def test_bootstrap_skips_cluster_seeding_in_mvp(tmp_path):
    """With the default flags, bootstrap initializes the overview but seeds
    nothing — even when legacy analyzed clusters exist in events.db."""
    import asyncio

    from httpserver.services.investigation_service import InvestigationService
    from tests.unit.test_investigation_seed_bootstrap import (
        _make_task_dbs,
        _service,
    )

    files_db, events_db = _make_task_dbs(tmp_path)
    service = _service(tmp_path, files_db, events_db)
    overview = asyncio.run(service.bootstrap("T1"))
    assert overview["seeded_clusters"] == 0
    assert overview["new_events"] == 0


# ---------------------------------------------------------------------------
# feature flag surface
# ---------------------------------------------------------------------------

def test_system_features_endpoint_reports_defaults():
    app = FastAPI()
    app.include_router(system_router, prefix="/api/system")
    client = TestClient(app)
    resp = client.get("/api/system/features")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "event_llm_analysis_enabled": False,
        "combined_case_enabled": False,
        "workbench_llm_enabled": False,
    }
