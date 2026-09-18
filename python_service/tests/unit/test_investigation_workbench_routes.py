"""HTTP contract tests for the Workbench bootstrap route (C9a).

Regression: POST /{task_id}/bootstrap used to be a stub that returned the
overview without invoking the cluster-seed service, so the workbench stayed
empty for every task. These tests pin the wiring: the route must await
``manager.investigation_seed_service.bootstrap`` before returning the
overview, GET must never seed, and failures map through the shared
``_error`` handler.
"""

from unittest.mock import AsyncMock, Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from httpserver.routes import investigation_workbench
from httpserver.services.investigation.models import EventEvidenceLink


class _FakeEvent(BaseModel):
    event_id: str
    title: str
    summary: str = ""
    review_status: str = "draft"


def _manager():
    manager = Mock()
    seed = Mock()
    seed.bootstrap = AsyncMock(return_value={})
    manager.investigation_seed_service = seed
    manager.investigation_read_service = Mock(
        list_evidence=AsyncMock(return_value=[])
    )
    manager.investigation_event_service = Mock(
        list_events=AsyncMock(
            return_value=[_FakeEvent(event_id="ev-1", title="cluster title")]
        ),
        event_presentation=AsyncMock(
            return_value={
                "ev-1": {
                    "start_time": 1700000000,
                    "end_time": 1700000120,
                    "evidence_count": 1,
                    "cluster_seed": True,
                    "links": [
                        {
                            "evidence_key": "cluster:v1:28333333:CREATED",
                            "evidence_type": "event_cluster",
                            "title": "CREATED 聚类（2 个事件）",
                            "timestamp": 1700000000,
                            "start_time": 1700000000,
                            "end_time": 1700000120,
                            "initial_summary": None,
                            "analysis_status": None,
                        }
                    ],
                }
            }
        ),
    )
    manager.report_evidence_service = Mock(list=AsyncMock(return_value=[]))
    manager.investigation_graph_service = Mock(
        get_graph=AsyncMock(return_value={"nodes": [], "links": []})
    )
    manager.secondary_analysis_executor = Mock(
        list_analyses=AsyncMock(return_value=[]),
        list_task_analyses=AsyncMock(return_value=[]),
    )
    manager.cpp_backend = Mock(
        get_task=AsyncMock(return_value={"id": "T1", "status": "completed"})
    )
    return manager


def _client(manager):
    app = FastAPI()
    app.include_router(
        investigation_workbench.router, prefix="/api/investigation/workbench"
    )
    app.dependency_overrides[investigation_workbench._manager] = lambda: manager
    return TestClient(app)


def test_bootstrap_seeds_then_returns_overview():
    manager = _manager()
    response = _client(manager).post(
        "/api/investigation/workbench/T1/bootstrap",
        json={"mode": "cluster_seed"},
    )
    assert response.status_code == 200
    body = response.json()
    manager.investigation_seed_service.bootstrap.assert_awaited_once_with("T1")
    assert body["event_count"] == 1
    event = body["events"][0]
    assert event["id"] == "ev-1"
    # Legacy-vocabulary presentation fields are projected from the strict
    # read-only pass (never fabricated store state).
    assert event["start_time"] == 1700000000
    assert event["end_time"] == 1700000120
    assert event["evidence_count"] == 1
    assert event["source"] == "cluster_seed"
    assert body["initialized"] is True
    assert body["task"]["id"] == "T1"


def test_overview_reads_analyses_in_one_task_scoped_call():
    """The overview must not call the per-evidence analyses read per item:
    each call re-resolved the task (a C++ get_task round trip), which made
    every page load an N+1 storm against the backend."""
    manager = _manager()
    response = _client(manager).get("/api/investigation/workbench/T1")
    assert response.status_code == 200
    manager.secondary_analysis_executor.list_task_analyses.assert_awaited_once_with("T1")
    manager.secondary_analysis_executor.list_analyses.assert_not_awaited()


def test_event_evidence_links_carry_display_fields():
    manager = _manager()
    link = EventEvidenceLink(
        task_id="T1",
        event_id="ev-1",
        evidence_key="cluster:v1:28333333:CREATED",
        linked_at="2026-09-18T00:00:00",
        linked_by="cluster_seed",
    )
    manager.investigation_event_service.list_event_evidence = AsyncMock(
        return_value=[link]
    )
    response = _client(manager).get(
        "/api/investigation/workbench/T1/events/ev-1/evidence"
    )
    assert response.status_code == 200
    item = response.json()["evidence"][0]
    assert item["evidence_type"] == "event_cluster"
    assert item["title"] == "CREATED 聚类（2 个事件）"
    assert item["timestamp"] == 1700000000


def test_bootstrap_rejects_unknown_request_fields():
    manager = _manager()
    response = _client(manager).post(
        "/api/investigation/workbench/T1/bootstrap",
        json={"mode": "cluster_seed", "unexpected": 1},
    )
    assert response.status_code == 422
    manager.investigation_seed_service.bootstrap.assert_not_awaited()


def test_get_overview_never_seeds():
    manager = _manager()
    response = _client(manager).get("/api/investigation/workbench/T1")
    assert response.status_code == 200
    manager.investigation_seed_service.bootstrap.assert_not_awaited()


def test_bootstrap_seed_failure_maps_to_500():
    manager = _manager()
    manager.investigation_seed_service.bootstrap = AsyncMock(
        side_effect=RuntimeError("seed exploded")
    )
    response = _client(manager).post(
        "/api/investigation/workbench/T1/bootstrap",
        json={"mode": "cluster_seed"},
    )
    assert response.status_code == 500
    assert response.json()["detail"] == "investigation operation failed"


def test_bootstrap_unknown_task_maps_to_400():
    manager = _manager()
    manager.investigation_seed_service.bootstrap = AsyncMock(
        side_effect=KeyError("Task T1 not found")
    )
    response = _client(manager).post(
        "/api/investigation/workbench/T1/bootstrap",
        json={"mode": "cluster_seed"},
    )
    assert response.status_code == 400


def _manager_with_store(tmp_path):
    manager = _manager()
    task_dir = tmp_path / "task-dir"
    task_dir.mkdir(exist_ok=True)
    manager.investigation_event_service.get_event = AsyncMock(
        return_value=_FakeEvent(event_id="ev-1", title="cluster title")
    )
    manager.cpp_backend = Mock(
        get_task=AsyncMock(
            return_value={
                "id": "T1",
                "status": "completed",
                "output_files_db": str(task_dir / "files.db"),
            }
        )
    )
    return manager


def test_event_review_roundtrip_projects_into_event_views(tmp_path):
    manager = _manager_with_store(tmp_path)
    client = _client(manager)
    response = client.post(
        "/api/investigation/workbench/T1/events/ev-1/review",
        json={"status": "confirmed"},
    )
    assert response.status_code == 200
    assert response.json()["event"]["review_status"] == "confirmed"

    listed = client.get("/api/investigation/workbench/T1/events")
    assert listed.json()["events"][0]["review_status"] == "confirmed"

    single = client.get("/api/investigation/workbench/T1/events/ev-1")
    assert single.json()["event"]["review_status"] == "confirmed"


def test_event_review_invalid_status_maps_to_400(tmp_path):
    manager = _manager_with_store(tmp_path)
    response = _client(manager).post(
        "/api/investigation/workbench/T1/events/ev-1/review",
        json={"status": "bogus"},
    )
    assert response.status_code == 400


def test_event_review_unknown_event_maps_to_404(tmp_path):
    from httpserver.services.evidence.exceptions import EvidenceNotFoundError

    manager = _manager_with_store(tmp_path)
    manager.investigation_event_service.get_event = AsyncMock(
        side_effect=EvidenceNotFoundError("event not found")
    )
    response = _client(manager).post(
        "/api/investigation/workbench/T1/events/missing/review",
        json={"status": "confirmed"},
    )
    assert response.status_code == 404


def test_analyst_note_roundtrip(tmp_path):
    manager = _manager_with_store(tmp_path)
    client = _client(manager)
    saved = client.post(
        "/api/investigation/workbench/T1/notes",
        json={
            "target_type": "evidence",
            "target_key": "cluster:v1:1:CREATED",
            "content": "调查上下文笔记",
        },
    )
    assert saved.status_code == 200
    assert saved.json()["note"]["content"] == "调查上下文笔记"

    read = client.get(
        "/api/investigation/workbench/T1/notes",
        params={"target_type": "evidence", "target_key": "cluster:v1:1:CREATED"},
    )
    assert read.status_code == 200
    assert read.json()["note"]["content"] == "调查上下文笔记"

    missing = client.get(
        "/api/investigation/workbench/T1/notes",
        params={"target_type": "evidence", "target_key": "cluster:v1:404:CREATED"},
    )
    assert missing.status_code == 200
    assert missing.json()["note"] is None
