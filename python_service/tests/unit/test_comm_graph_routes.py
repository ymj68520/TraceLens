"""Route-level tests for /api/comm.

The service layer is covered by ``test_comm_graph.py``; here the FastAPI
surface is exercised: parameter validation, dataset shorthands, error mapping.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from httpserver.routes import comm_graph as routes


def epoch(day=1, hour=10):
    return int(datetime(2026, 3, day, hour, tzinfo=timezone.utc).timestamp())


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = tmp_path / "android.db"
    with sqlite3.connect(db) as conn:
        conn.executescript("""
            CREATE TABLE contacts(id INTEGER PRIMARY KEY, display_name TEXT, phone_number TEXT);
            CREATE TABLE call_logs(id INTEGER PRIMARY KEY, number TEXT, date INTEGER,
                duration INTEGER, type INTEGER, name TEXT, date_seconds INTEGER);
            CREATE TABLE sms_messages(id INTEGER PRIMARY KEY, address TEXT, person TEXT,
                date INTEGER, type INTEGER, body TEXT, date_seconds INTEGER);
        """)
        conn.execute("INSERT INTO contacts VALUES (1,'张三','13800138000')")
        conn.execute("INSERT INTO call_logs VALUES (1,'13800138000',0,30,1,'张三',?)",
                     (epoch(1),))
        conn.execute("INSERT INTO sms_messages VALUES (1,'13800138000','张三',0,1,'你好',?)",
                     (epoch(2),))

    task = {"id": "T1", "image_path": "/cases/case.bin",
            "output_files_db": str(db), "output_raw_db": str(tmp_path / "raw.db")}

    class _Backend:
        async def get_task(self, task_id):
            return dict(task) if task_id == "T1" else None

    class _Manager:
        cpp_backend = _Backend()

    monkeypatch.setattr(routes, "get_service_manager", lambda: _Manager())
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/comm")
    return TestClient(app)


def test_graph_returns_nodes_and_edges(client):
    response = client.get("/api/comm/graph", params={"task_id": "T1"})
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["nodes"], body
    assert any(edge["relation"] == "call" for edge in body["edges"])
    assert body["coverage"]["identity_policy"] == "strong_keys_only"


def test_graph_rejects_reversed_time_range(client):
    response = client.get("/api/comm/graph", params={
        "task_id": "T1", "start_time": 200, "end_time": 100})
    assert response.status_code == 422


def test_unknown_task_is_404(client):
    assert client.get("/api/comm/graph", params={"task_id": "nope"}).status_code == 404


def test_timeline_returns_chronological_records(client):
    response = client.get("/api/comm/timeline", params={"task_id": "T1"})
    assert response.status_code == 200
    body = response.json()
    stamps = [record["timestamp"] for record in body["records"]]
    assert stamps == sorted(stamps)
    assert body["coverage"]["dedup_rule"] == "dataset+record_ref:v1"


def test_timeline_rejects_unknown_kind(client):
    response = client.get("/api/comm/timeline", params={
        "task_id": "T1", "kind": "telepathy"})
    assert response.status_code == 422


def test_timeline_accepts_repeated_kind_filters(client):
    response = client.get("/api/comm/timeline",
                          params=[("task_id", "T1"), ("kind", "sms")])
    assert response.status_code == 200
    assert {record["kind"] for record in response.json()["records"]} <= {"sms"}


def test_edge_requires_both_endpoints(client):
    assert client.get("/api/comm/edge", params={"task_id": "T1"}).status_code == 422


def test_edge_rejects_unknown_relation(client):
    response = client.get("/api/comm/edge", params={
        "task_id": "T1", "source": "p_a", "target": "p_b", "relation": "soulmate"})
    assert response.status_code == 422


def test_datasets_lists_the_task_source(client):
    response = client.get("/api/comm/datasets", params={"task_id": "T1"})
    assert response.status_code == 200
    body = response.json()
    assert body["datasets"][0]["dataset_id"] == "task:T1"


def test_wx_shorthand_is_rejected_when_import_missing(client, tmp_path, monkeypatch):
    """A well-formed but unknown import id must be reported, not silently used."""
    monkeypatch.setattr(routes, "_resolve", routes._resolve)  # no-op: keep production path
    response = client.get("/api/comm/graph", params={
        "task_id": "T1", "dataset": "wx_0123456789ab"})
    assert response.status_code == 200
    body = response.json()
    assert body["coverage"]["datasets_unavailable"] == 1
    assert body["coverage"]["datasets_readable"] == 1


def test_malformed_import_id_is_422(client):
    response = client.get("/api/comm/graph", params={
        "task_id": "T1", "wechat_imports": "../../etc/passwd"})
    assert response.status_code == 422
