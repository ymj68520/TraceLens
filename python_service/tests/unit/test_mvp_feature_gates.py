"""MVP feature-gate tests (docs/specs/mvp-phase1-acceptance.md §4).

The phase-1 acceptance build ships with events carrying no LLM analysis and
events excluded from report evidence. Combined-case gating was restored to
its pre-MVP default (enabled) on 2026-09-19 after 甲方 confirmation; the
tests below still pin the gate mechanism itself by pinning the flag off
explicitly (the env var remains the escape hatch in both directions).
Per-feature behavior tests enable the flags in their own fixtures.
"""

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from httpserver.config import get_settings
from httpserver.routes import event_cluster_analysis as eca_routes
from httpserver.routes import investigation_workbench
from httpserver.routes import oss_analysis as oss_routes
from httpserver.routes.event_cluster_analysis import router as eca_router
from httpserver.routes.multi_analysis import router as multi_router
from httpserver.routes.oss_analysis import router as oss_router
from httpserver.routes.system import router as system_router
from httpserver.routes.investigation_workbench import (
    _manager,
    router as workbench_router,
)


@pytest.fixture(autouse=True)
def _mvp_defaults(monkeypatch):
    """Pin all switches to their shipping defaults (combined case restored
    2026-09-19, everything else stays disabled)."""
    settings = get_settings()
    monkeypatch.setattr(settings, "event_llm_analysis_enabled", False, raising=False)
    monkeypatch.setattr(settings, "combined_case_enabled", True, raising=False)
    monkeypatch.setattr(settings, "workbench_llm_enabled", False, raising=False)
    monkeypatch.setattr(settings, "memory_forensics_enabled", False, raising=False)
    monkeypatch.setattr(settings, "oss_analysis_enabled", False, raising=False)


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
# combined case: gate mechanism (flag explicitly pinned off; the shipping
# default has been enabled since the 2026-09-19 restoration)
# ---------------------------------------------------------------------------

def test_combined_case_gate_blocks_when_disabled():
    settings = get_settings()
    app = FastAPI()
    app.include_router(multi_router)
    client = TestClient(app)

    settings.combined_case_enabled = False
    try:
        resp = client.post(
            "/api/llm/cases", json={"name": "case", "task_ids": []}
        )
        assert resp.status_code == 503
        assert "MVP" in resp.json()["detail"]

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
    finally:
        settings.combined_case_enabled = True


def test_combined_case_gate_open_by_default():
    """With the shipping default (enabled) the gate no longer answers 503;
    the request proceeds past admission and fails later on the (unreachable,
    monkeypatched) C++ proxy target, not at the gate."""
    settings = get_settings()
    assert settings.combined_case_enabled is True
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(settings, "cpp_backend_url", "http://127.0.0.1:1", raising=False)
    app = FastAPI()
    app.include_router(multi_router)
    client = TestClient(app)
    try:
        resp = client.post("/api/llm/cases", json={"name": "case", "task_ids": []})
        assert resp.status_code != 503
    finally:
        monkeypatch.undo()


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


def test_workbench_report_evidence_rejects_cluster_key():
    """SPEC §4.2: the workbench PUT must mirror the 422 on
    POST /api/reports/evidence -- a stored cluster row would silently 409
    every generation attempt (admission skips cluster keys)."""
    app = FastAPI()
    app.include_router(workbench_router, prefix="/api/investigation/workbench")
    app.dependency_overrides[_manager] = lambda: object()
    try:
        client = TestClient(app)
        resp = client.put(
            "/api/investigation/workbench/t1/report-evidence",
            json={"evidence_key": "cluster:v1:28331457:CREATED", "usage": "main"},
        )
        assert resp.status_code == 422
        assert "cluster" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_bootstrap_seeds_clusters_with_default_flags(tmp_path):
    """With the default MVP flags, bootstrap still seeds cluster events (it
    reuses the clusters' existing LLM analysis, never calls an LLM) so the
    workbench is not blank; the report-evidence exclusion is enforced
    downstream (cluster keys rejected at report_evidence, filtered at
    report assembly)."""
    import asyncio

    from httpserver.services.investigation_service import InvestigationService
    from tests.unit.test_investigation_seed_bootstrap import (
        _make_task_dbs,
        _service,
    )

    files_db, events_db = _make_task_dbs(tmp_path)
    service = _service(tmp_path, files_db, events_db)
    overview = asyncio.run(service.bootstrap("T1"))
    assert overview["seeded_clusters"] == 2
    assert overview["new_events"] == 2
    assert overview["event_count"] == 2


# ---------------------------------------------------------------------------
# memory forensics / OSS analysis trimmed (SPEC §4.6/§4.7, 2026-09-18)
# ---------------------------------------------------------------------------

def test_oss_ai_filter_returns_503():
    app = FastAPI()
    app.include_router(oss_router)
    client = TestClient(app)
    resp = client.post(
        "/api/forensics/oss/ai/filter",
        json={
            "task_id": "t1",
            "oss_db_path": "/tmp/oss.db",
            "case_description": "d",
        },
    )
    assert resp.status_code == 503
    assert "MVP" in resp.json()["detail"]


def test_oss_ai_analyze_returns_503():
    app = FastAPI()
    app.include_router(oss_router)
    client = TestClient(app)
    resp = client.post(
        "/api/forensics/oss/ai/analyze",
        json={
            "task_id": "t1",
            "object_ids": [1],
            "oss_db_path": "/tmp/oss.db",
            "download_dir": "/tmp/dl",
        },
    )
    assert resp.status_code == 503


def test_oss_ai_endpoints_restored_when_enabled(monkeypatch):
    """Escape hatch: the env flag reopens the endpoints (no LLM call is made —
    the request still fails later on the missing service wiring, not at the
    gate)."""
    settings = get_settings()
    monkeypatch.setattr(settings, "oss_analysis_enabled", True, raising=False)
    app = FastAPI()
    app.include_router(oss_router)
    client = TestClient(app)
    resp = client.post(
        "/api/forensics/oss/ai/filter",
        json={
            "task_id": "t1",
            "oss_db_path": "/tmp/oss.db",
            "case_description": "d",
        },
    )
    assert resp.status_code != 503


def test_oss_router_exposes_no_read_surface_beyond_ai():
    """The trimmed module must not grow new unprefixed endpoints silently."""
    paths = {route.path for route in oss_router.routes}
    assert paths == {
        "/api/forensics/oss/ai/filter",
        "/api/forensics/oss/ai/analyze",
    }


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
        "combined_case_enabled": True,
        "workbench_llm_enabled": False,
        "memory_forensics_enabled": False,
        "oss_analysis_enabled": False,
    }
