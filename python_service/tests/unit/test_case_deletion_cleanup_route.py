"""Route-level tests for DELETE /api/llm/cases/{case_id} (deletion-cleanup hardening).

Case deletion used to only proxy the C++ record delete, orphaning the
case-level Neo4j graph (group_id == case_id) and the cross-image case
analysis DB directory ``<data>/cases/<case_id>/``. The endpoint must now
purge both (best-effort, reported per item) after the C++ record is gone.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from httpserver.config import get_settings
from httpserver.routes import multi_analysis

CASE_ID = "844c321a-bcc1-4229-bead-80c295163163"


class _Manager:
    """Service-manager double recording graph/jobs interactions."""

    def __init__(self, graph_error=None):
        self.graphiti_service = SimpleNamespace(
            delete_task_graph=AsyncMock(
                side_effect=graph_error, return_value=not graph_error
            )
        )
        self.ingestion_job_manager = SimpleNamespace(
            cancel_jobs_for_task=AsyncMock(return_value=1)
        )


def _client(monkeypatch, tmp_path, manager, cpp_status=200, cpp_body=None):
    recorded = {}

    response = httpx.Response(
        cpp_status, json=cpp_body if cpp_body is not None else {"success": True}
    )

    class _FakeAsyncClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def delete(self, url, **kwargs):
            recorded["url"] = url
            return response

    monkeypatch.setattr(
        multi_analysis.httpx, "AsyncClient", _FakeAsyncClient
    )
    monkeypatch.setattr(
        "httpserver.services.get_service_manager", lambda: manager
    )
    monkeypatch.setattr(multi_analysis, "get_data_root", lambda: Path(tmp_path))

    app = FastAPI()
    app.include_router(multi_analysis.router)
    app.dependency_overrides[get_settings] = lambda: SimpleNamespace(
        cpp_backend_url="http://cpp.test:9"
    )
    return TestClient(app), manager, recorded


@pytest.fixture
def case_dir(tmp_path):
    d = Path(tmp_path) / "cases" / CASE_ID
    d.mkdir(parents=True)
    (d / f"{CASE_ID}.db").write_bytes(b"sqlite")
    return d


def test_delete_purges_graph_and_case_dir(monkeypatch, tmp_path, case_dir):
    tc, manager, recorded = _client(monkeypatch, tmp_path, _Manager())

    resp = tc.delete(f"/api/llm/cases/{CASE_ID}")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["graph_deleted"] is True
    assert body["case_data_removed"] is True
    assert recorded["url"] == f"http://cpp.test:9/api/cases/{CASE_ID}"

    manager.graphiti_service.delete_task_graph.assert_awaited_once_with(CASE_ID)
    manager.ingestion_job_manager.cancel_jobs_for_task.assert_awaited_once_with(CASE_ID)
    assert not case_dir.exists()


def test_cpp_404_short_circuits_before_cleanup(monkeypatch, tmp_path, case_dir):
    tc, manager, recorded = _client(
        monkeypatch, tmp_path, _Manager(), cpp_status=404
    )

    resp = tc.delete(f"/api/llm/cases/{CASE_ID}")

    assert resp.status_code == 404
    manager.graphiti_service.delete_task_graph.assert_not_awaited()
    manager.ingestion_job_manager.cancel_jobs_for_task.assert_not_awaited()
    assert case_dir.exists()  # untouched


def test_graph_failure_still_removes_case_dir(monkeypatch, tmp_path, case_dir):
    tc, manager, _ = _client(
        monkeypatch, tmp_path, _Manager(graph_error=RuntimeError("neo4j down"))
    )

    resp = tc.delete(f"/api/llm/cases/{CASE_ID}")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["graph_deleted"] is False
    assert body["case_data_removed"] is True
    assert not case_dir.exists()


def test_hostile_id_cannot_escape_cases_root(monkeypatch, tmp_path, case_dir):
    tc, manager, _ = _client(monkeypatch, tmp_path, _Manager())

    # FastAPI path params do not match "/", so a traversal id lands as a
    # routing 404 before any cleanup runs.
    resp = tc.delete("/api/llm/cases/..%2F..%2Fetc")
    assert resp.status_code == 404

    # An id that does reach the helper must be hex/dashes only — dots are
    # rejected, so nothing outside <data>/cases/<id>/ can ever be removed.
    resp2 = tc.delete("/api/llm/cases/....")
    assert resp2.status_code == 200
    assert resp2.json()["case_data_removed"] is False


def test_missing_case_dir_reports_false(monkeypatch, tmp_path):
    tc, manager, _ = _client(monkeypatch, tmp_path, _Manager())

    resp = tc.delete(f"/api/llm/cases/{CASE_ID}")

    assert resp.status_code == 200
    assert resp.json()["case_data_removed"] is False
