"""Route tests for /api/llm/event-cluster-analysis* (SPEC §8.1)."""

import asyncio
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from httpserver.routes import event_cluster_analysis as eca_routes
from httpserver.routes.event_cluster_analysis import router
from httpserver.services.case_analysis.schema import ensure_cluster_analysis_schema


def _events_db(tmp_path):
    path = tmp_path / "events.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE events (id INTEGER PRIMARY KEY, timestamp INTEGER, event_type TEXT, "
            "file_path TEXT, description TEXT, llm_summary TEXT, llm_analyzed_at INTEGER)"
        )
        conn.executemany(
            "INSERT INTO events (id, timestamp, event_type, file_path, description) VALUES (?, ?, ?, ?, ?)",
            [
                (1, 120, "MODIFIED", "/foo/a.txt", "d"),
                (2, 130, "MODIFIED", "/foo/b.txt", "d"),
                (3, 5000, "CREATED", "/foo/c.txt", "d"),
            ],
        )
        conn.commit()
    return str(path)


class _FakeManager:
    def __init__(self, events_db):
        self._events_db = events_db

        class _Backend:
            def __init__(self, outer):
                self._outer = outer

            async def get_task(self, task_id):
                if task_id == "missing":
                    return None
                return {"output_events_db": self._outer._events_db, "case_description": "case"}

        self.cpp_backend = _Backend(self)
        self.llm_service = None
        self.graphiti_service = None


@pytest.fixture(autouse=True)
def _enable_event_llm(monkeypatch):
    """These tests exercise the run path's own behavior; the MVP gate
    (mvp-phase1-acceptance §4.1, default off) is covered in
    test_mvp_feature_gates.py."""
    from httpserver.config import get_settings

    monkeypatch.setattr(get_settings(), "event_llm_analysis_enabled", True)


@pytest.fixture
def client(monkeypatch, tmp_path):
    events_db = _events_db(tmp_path)
    manager = _FakeManager(events_db)
    monkeypatch.setattr("httpserver.services.get_service_manager", lambda: manager)
    app = FastAPI()
    app.include_router(router, prefix="/api/llm")
    yield TestClient(app), manager, events_db
    eca_routes._run_jobs.clear()


def test_estimate_returns_ladder_and_recommendation(client):
    tc, _, _ = client
    response = tc.post("/api/llm/event-cluster-analysis/estimate", json={"task_id": "task-1"})

    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["budget"] >= 1
    buckets = [e["bucket_seconds"] for e in body["estimates"]]
    assert buckets == sorted(set(buckets))
    assert buckets[0] == 60 and buckets[-1] == 2592000
    # Tiny fixture: the smallest window already fits the budget.
    assert body["recommended_bucket_seconds"] == 60
    assert body["warning"] is None


def test_estimate_rejects_missing_task(client):
    tc, _, _ = client
    response = tc.post("/api/llm/event-cluster-analysis/estimate", json={"task_id": "missing"})
    assert response.status_code == 404


def test_run_rejects_out_of_range_bucket(client):
    tc, _, _ = client
    response = tc.post(
        "/api/llm/event-cluster-analysis/run",
        json={"task_id": "task-1", "bucket_seconds": 99999999},
    )
    assert response.status_code == 422


def test_run_returns_job_and_completes(client, monkeypatch):
    tc, manager, events_db = client

    async def _fake_run(self, task_id, events_db_arg, case_description="",
                        bucket_seconds=None, progress_callback=None):
        return {
            "run_id": 1, "task_id": task_id, "bucket_seconds": bucket_seconds or 60,
            "bucket_epoch_offset": 0, "cluster_total": 2, "analyzed": 2,
            "skipped_fresh": 0, "failed": 0, "warning": None, "results": [],
        }

    monkeypatch.setattr(
        "httpserver.services.case_analysis.cluster_analyzer.ClusterAnalyzer.run_analysis",
        _fake_run,
    )

    response = tc.post("/api/llm/event-cluster-analysis/run", json={"task_id": "task-1"})
    assert response.status_code == 200, response.json()
    job_id = response.json()["job_id"]

    import time

    status = None
    deadline = time.time() + 5
    while time.time() < deadline:
        detail = tc.get(f"/api/llm/event-cluster-analysis/run/{job_id}")
        assert detail.status_code == 200
        status = detail.json()
        if status["status"] != "running":
            break
        time.sleep(0.05)
    assert status["status"] == "completed"
    assert status["summary"]["cluster_total"] == 2


def test_run_status_unknown_job_is_404(client):
    tc, _, _ = client
    assert tc.get("/api/llm/event-cluster-analysis/run/nope").status_code == 404


def test_analyses_query_filters_and_latest_only(client):
    tc, _, events_db = client
    ensure_cluster_analysis_schema(events_db)
    with sqlite3.connect(events_db) as conn:
        conn.execute(
            "INSERT INTO event_cluster_analyses (task_id, bucket_seconds, bucket_index, "
            "event_type, parent_directory, member_count, member_min_id, member_max_id, "
            "members_hash, summary, trigger_source, created_at) VALUES "
            "('task-1', 60, 2, 'MODIFIED', '/foo/', 2, 1, 2, 'h', 'v1', 'pipeline', 1)"
        )
        conn.execute(
            "INSERT INTO event_cluster_analyses (task_id, bucket_seconds, bucket_index, "
            "event_type, parent_directory, member_count, member_min_id, member_max_id, "
            "members_hash, summary, trigger_source, created_at) VALUES "
            "('task-1', 60, 2, 'MODIFIED', '/foo/', 2, 1, 2, 'h2', 'v2', 'timeline_manual', 2)"
        )
        conn.execute(
            "INSERT INTO event_cluster_analyses (task_id, bucket_seconds, bucket_index, "
            "event_type, parent_directory, member_count, member_min_id, member_max_id, "
            "members_hash, summary, trigger_source, created_at) VALUES "
            "('task-1', 300, 1, 'CREATED', '/foo/', 1, 3, 3, 'h3', 'other', 'task_run', 3)"
        )
        conn.commit()

    response = tc.get(
        "/api/llm/event-cluster-analyses",
        params={"task_id": "task-1", "latest_only": "true"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    summaries = {r["summary"] for r in body["records"]}
    assert summaries == {"v2", "other"}

    filtered = tc.get(
        "/api/llm/event-cluster-analyses",
        params={"task_id": "task-1", "bucket_seconds": 300},
    ).json()
    assert filtered["total"] == 1
    assert filtered["records"][0]["summary"] == "other"
