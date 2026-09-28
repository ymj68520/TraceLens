"""A graph fact must trace only to source episodes and files of its task."""

import sqlite3
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from httpserver.services.graphiti_parts._query import GraphitiQueryMixin
from httpserver.services.graphiti_relation_trace import (
    enrich_relationship_trace,
    read_task_source_file,
)
from httpserver.routes.graphiti_endpoints import _trace


@pytest.mark.asyncio
async def test_graph_relations_expose_task_scoped_ids_and_episode_trace():
    query = GraphitiQueryMixin()
    query._run_read_query = AsyncMock(side_effect=[
        [{"id": "node-a", "name": "A", "labels": ["Entity"], "summary": ""},
         {"id": "node-b", "name": "B", "labels": ["Entity"], "summary": ""}],
        [{"id": "edge-a", "source": "node-a", "target": "node-b", "label": "USES_FILE"}],
        [{"id": "edge-a", "source_id": "node-a", "source_name": "A",
          "target_id": "node-b", "target_name": "B", "label": "USES_FILE",
          "fact": "A uses B", "episode_ids": ["episode-a"], "created_at": None}],
        [{"id": "episode-a", "name": "文件分析: /case/a.txt",
          "content": "file_path: /case/a.txt\nanalysis: A uses B",
          "source_description": "LLM分析结果 - /case/a.txt"}],
    ])

    _nodes, links = await query.get_graph_data("task-a", 50)
    trace = await query.get_relationship_trace("task-a", "edge-a")

    assert links == [{"id": "edge-a", "source": "node-a", "target": "node-b", "label": "USES_FILE"}]
    assert trace["episodes"][0]["content"].startswith("file_path: /case/a.txt")
    assert trace["fact"] == "A uses B"
    graph_edge_query = query._run_read_query.call_args_list[1]
    trace_query = query._run_read_query.call_args_list[2]
    episode_query = query._run_read_query.call_args_list[3]
    assert "r.group_id = $gid" in graph_edge_query.args[0]
    assert "r.group_id = $gid" in trace_query.args[0]
    assert "Episodic {group_id: $gid}" in episode_query.args[0]


@pytest.mark.asyncio
async def test_foreign_relationship_is_not_found():
    query = GraphitiQueryMixin()
    query._run_read_query = AsyncMock(return_value=[])
    assert await query.get_relationship_trace("task-a", "foreign-edge") is None
    query._run_read_query.assert_awaited_once()


@pytest.mark.asyncio
async def test_trace_has_real_extracted_preview_only_for_exact_task_file(tmp_path):
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    db = task_dir / "files.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE files (path TEXT, size INTEGER, md5 TEXT)")
        conn.execute("INSERT INTO files VALUES (?,?,?)", ("/case/a.txt", 18, ""))
        conn.execute("INSERT INTO files VALUES (?,?,?)", ("/case/b.pb", 14, ""))
    extracted = task_dir / "extracted_files" / "case" / "a.txt"
    extracted.parent.mkdir(parents=True)
    extracted.write_text("source text for A\n", encoding="utf-8")
    binary = task_dir / "extracted_files" / "case" / "b.pb"
    binary.write_bytes(b"\x08\x07sha256/abc\x00\x01")
    manager = Mock()
    manager.cpp_backend.get_task = AsyncMock(return_value={
        "id": "task-a", "output_files_db": str(db),
        "extraction_directory": str(task_dir / "extracted_files"),
    })
    trace = {"id": "edge-a", "episodes": [
        {"id": "episode-a", "source_description": "LLM分析结果 - /case/a.txt",
         "content": "file_path: /case/a.txt\nanalysis: generated description"},
        {"id": "episode-b", "source_description": "LLM分析结果 - /case/foreign.txt",
         "content": "file_path: /case/foreign.txt"},
    ]}

    result = await enrich_relationship_trace(trace, "task-a", manager)

    owned, foreign = result["episodes"]
    assert owned["evidence_key"] == "file:/case/a.txt"
    assert owned["original_preview"]["available"] is True
    assert owned["original_preview"]["text"] == "source text for A\n"
    assert owned["original_preview"]["source"] == "extracted_copy"
    assert foreign["evidence_key"] is None
    assert foreign["original_preview"]["available"] is False

    manager.investigation_read_service.get_snapshot = AsyncMock(return_value=None)
    source = await read_task_source_file("task-a", "file:/case/a.txt", manager)
    assert source["evidence_key"] == "file:/case/a.txt"
    assert source["original_preview"]["text"] == "source text for A\n"
    assert source["snapshot"] is None
    binary_source = await read_task_source_file("task-a", "file:/case/b.pb", manager)
    assert binary_source["original_preview"]["kind"] == "binary"
    assert "sha256/abc" in binary_source["original_preview"]["printable_strings"]


def test_relationship_trace_route_rejects_foreign_or_invalid_id(monkeypatch):
    manager = Mock()
    manager.graphiti_service.get_relationship_trace = AsyncMock(return_value=None)
    monkeypatch.setattr(_trace, "get_service_manager", lambda: manager)
    app = FastAPI()
    app.include_router(_trace.router, prefix="/api/graphiti")
    client = TestClient(app)
    bad = client.get("/api/graphiti/relationships/not-a-uuid/trace", params={"task_id": "A"})
    missing = client.get(
        "/api/graphiti/relationships/11111111-1111-1111-1111-111111111111/trace",
        params={"task_id": "A"},
    )
    assert bad.status_code == 400
    assert missing.status_code == 404
    manager.graphiti_service.get_relationship_trace.assert_awaited_once_with(
        "A", "11111111-1111-1111-1111-111111111111"
    )
