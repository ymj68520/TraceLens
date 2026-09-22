"""File-centric workbench timeline (file-timeline projection) tests.

Locks the projection contract: nodes are the files the Investigation covers
(cluster member paths + direct file: links) UNION the analyzed files
(``llm_analyzed_at IS NOT NULL`` — the file-centric fallback that keeps the
workbench populated in minimal mode with zero event links), each positioned
at the latest of its MACB timestamps with the covering Investigation Events
attached as corroborating refs; the route wires the event service through the
shared error mapping; a missing store degrades to the analyzed-files-only
projection and never materializes the store.
"""

from __future__ import annotations

import sqlite3
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from httpserver.routes import investigation_workbench
from httpserver.services.evidence import EvidenceNotFoundError, ResolvedEvidence
from httpserver.services.investigation import (
    InvestigationEventService,
    InvestigationRepository,
)
from httpserver.services.investigation.file_timeline import (
    collect_file_timeline,
    empty_file_timeline,
)


def _make_events_db(path, rows):
    """rows: (timestamp, event_type, file_path)."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp INTEGER, "
        "event_type TEXT, file_path TEXT)"
    )
    conn.executemany(
        "INSERT INTO events (timestamp, event_type, file_path) VALUES (?,?,?)", rows
    )
    conn.commit()
    conn.close()


def _make_files_db(path, rows):
    """rows: (path, name, size, mtime, ctime, llm_summary)."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE files (path TEXT, name TEXT, extension TEXT, category TEXT, "
        "type TEXT, size INTEGER, mtime INTEGER, ctime INTEGER, is_deleted INTEGER, "
        "md5 TEXT, llm_summary TEXT, llm_description TEXT, llm_keywords TEXT, "
        "llm_analyzed_at INTEGER, llm_model_used TEXT, scene_type TEXT, "
        "scene_priority INTEGER, scene_relevant INTEGER)"
    )
    conn.executemany(
        "INSERT INTO files (path, name, size, mtime, ctime, llm_summary) "
        "VALUES (?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()


def _make_raw_db(path, rows):
    """rows: (path, crtime, mtime, atime, ctime)."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE files (path TEXT, crtime INTEGER, mtime INTEGER, "
        "atime INTEGER, ctime INTEGER, is_deleted INTEGER)"
    )
    conn.executemany(
        "INSERT INTO files (path, crtime, mtime, atime, ctime) VALUES (?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()


CLUSTER_KEY = "cluster:v1:100:CREATED"


def _store(tmp_path, task_id="A"):
    events_db = str(tmp_path / "events.db")
    files_db = str(tmp_path / "files.db")
    raw_db = str(tmp_path / "raw.db")
    _make_events_db(
        events_db,
        [
            (6000, "CREATED", "/case/a.txt"),
            (6059, "CREATED", "/case/b.txt"),
            (6045, "CREATED", "/case/ghost.txt"),
        ],
    )
    _make_files_db(
        files_db,
        [
            ("/case/a.txt", "a.txt", 10, 6000, 6000, None),
            ("/case/c.txt", "c.txt", 30, 500, 400, "文件 C 的分析摘要"),
        ],
    )
    _make_raw_db(
        raw_db,
        [
            ("/case/a.txt", 6000, 12500, 12100, 12050),
            ("/case/b.txt", 6059, 6059, 6059, 6059),
        ],
    )
    task = {
        "id": task_id,
        "output_files_db": files_db,
        "output_events_db": events_db,
        "output_raw_db": raw_db,
    }
    repo = InvestigationRepository(tmp_path / "investigation.db", task_id)
    return task, repo, files_db, events_db


def _seed(store):
    task, repo, files_db, events_db = store
    cluster_snapshot = repo.capture_if_absent(
        ResolvedEvidence(
            task_id=task["id"],
            evidence_key=CLUSTER_KEY,
            evidence_type="cluster",
            version="v1",
            unix_minute=100,
            event_type="CREATED",
            cluster_start=6000,
            cluster_end=6059,
            event_count=2,
            representative_timestamp=6000,
            source_db=events_db,
        )
    )
    file_snapshot = repo.capture_if_absent(
        ResolvedEvidence(
            task_id=task["id"],
            evidence_key="file:/case/c.txt",
            evidence_type="file",
            normalized_path="/case/c.txt",
            source_db=files_db,
        )
    )
    cluster_event = repo.create_event("聚类事件", summary="簇摘要")
    file_event = repo.create_event("文件事件", summary="文件摘要")
    repo.link_event_evidence(cluster_event.event_id, CLUSTER_KEY, linked_by="cluster_seed")
    repo.link_event_evidence(
        file_event.event_id, "file:/case/c.txt", linked_by="analyst"
    )
    return {
        "cluster_event": cluster_event.event_id,
        "file_event": file_event.event_id,
        "cluster_snapshot": cluster_snapshot,
        "file_snapshot": file_snapshot,
    }


def _collect(store, **kwargs):
    task, repo, _files_db, _events_db = store
    return collect_file_timeline(
        repo.db_path, task["id"], task, **kwargs
    )


def test_cluster_members_and_direct_links_merge_into_macb_sorted_nodes(tmp_path):
    store = _store(tmp_path)
    seeded = _seed(store)
    result = _collect(store)

    paths = [item["path"] for item in result["files"]]
    # 最新 MACB 时间降序罗列，无时间的文件垫底
    assert paths == ["/case/a.txt", "/case/b.txt", "/case/c.txt", "/case/ghost.txt"]

    by_path = {item["path"]: item for item in result["files"]}
    # a.txt: raw.db 四类时间戳的最大值 12500 作为轴位置
    assert by_path["/case/a.txt"]["latest_time"] == 12500
    assert by_path["/case/a.txt"]["mtime"] == 12500
    assert by_path["/case/a.txt"]["atime"] == 12100
    assert by_path["/case/a.txt"]["event_ids"] == [seeded["cluster_event"]]
    # b.txt 只在聚类里
    assert by_path["/case/b.txt"]["latest_time"] == 6059
    assert by_path["/case/b.txt"]["event_ids"] == [seeded["cluster_event"]]
    # c.txt 直接 file: 关联，raw.db 缺失时用 files.db mtime/ctime 兜底
    assert by_path["/case/c.txt"]["latest_time"] == 500
    assert by_path["/case/c.txt"]["event_ids"] == [seeded["file_event"]]
    assert by_path["/case/c.txt"]["llm_summary"] == "文件 C 的分析摘要"

    assert result["axis"] == {"start": 500, "end": 12500}
    assert result["total_count"] == 4
    assert result["scope"]["cluster_count"] == 1


def test_cluster_member_missing_from_file_stores_stays_undated_at_bottom(tmp_path):
    store = _store(tmp_path)
    _seed(store)
    result = _collect(store)

    assert result["files"][-1]["path"] == "/case/ghost.txt"
    assert result["files"][-1]["latest_time"] is None
    assert result["scope"]["undated_file_count"] == 1


def test_limit_caps_returned_files_but_reports_total(tmp_path):
    store = _store(tmp_path)
    _seed(store)
    result = _collect(store, limit=2)

    assert len(result["files"]) == 2
    assert result["total_count"] == 4
    assert result["scope"]["limited"] is True


def test_ensure_paths_rescues_limit_truncated_files_for_deep_links(tmp_path):
    """报告引用深链：被 limit 截断的文件补回投影；文件库外路径绝不发明。"""
    store = _store(tmp_path)
    _seed(store)
    # 额外登记一个"已分析但未挂事件"的文件（典型：报告证据文件）。
    _task, _repo, files_db, _events = store
    with sqlite3.connect(files_db) as conn:
        conn.execute(
            "INSERT INTO files (path, name, size, mtime, ctime, llm_summary) "
            "VALUES ('/case/report_only.txt', 'report_only.txt', 1, 600, 500, NULL)"
        )

    result = _collect(
        store,
        limit=2,
        ensure_paths=("/case/ghost.txt", "/case/report_only.txt"),
    )

    paths = [item["path"] for item in result["files"]]
    assert paths[:2] == ["/case/a.txt", "/case/b.txt"]
    assert paths.count("/case/ghost.txt") == 1
    rescued = next(
        item for item in result["files"] if item["path"] == "/case/report_only.txt"
    )
    assert rescued["event_ids"] == []
    assert rescued["latest_time"] == 600
    assert result["scope"]["ensured_paths"] == [
        "/case/ghost.txt",
        "/case/report_only.txt",
    ]

    # 已在截断内的文件不重复；未被本调查覆盖且不在文件库的路径直接忽略。
    result = _collect(
        store, limit=2, ensure_paths=("/case/b.txt", "/case/outside.txt")
    )
    paths = [item["path"] for item in result["files"]]
    assert paths == ["/case/a.txt", "/case/b.txt"]
    assert result["scope"]["ensured_paths"] == []


def test_cluster_member_paths_capped_per_cluster(tmp_path):
    """超大分钟簇只浮出 MAX_RELATED_EVIDENCE 个最早成员文件，不淹没时间线。"""
    task_id = "A"
    events_db = str(tmp_path / "events.db")
    files_db = str(tmp_path / "files.db")
    raw_db = str(tmp_path / "raw.db")
    from httpserver.services.investigation_evidence import MAX_RELATED_EVIDENCE

    total = MAX_RELATED_EVIDENCE + 5
    _make_events_db(
        events_db,
        [(7000 + index, "CREATED", f"/case/f{index:02d}.txt") for index in range(total)],
    )
    _make_files_db(files_db, [])
    _make_raw_db(raw_db, [])
    task = {
        "id": task_id,
        "output_files_db": files_db,
        "output_events_db": events_db,
        "output_raw_db": raw_db,
    }
    repo = InvestigationRepository(tmp_path / "investigation.db", task_id)
    repo.capture_if_absent(
        ResolvedEvidence(
            task_id=task_id,
            evidence_key="cluster:v1:116:CREATED",
            evidence_type="cluster",
            version="v1",
            unix_minute=116,
            event_type="CREATED",
            cluster_start=7000,
            cluster_end=7000 + total - 1,
            event_count=total,
            representative_timestamp=7000,
            source_db=events_db,
        )
    )
    event = repo.create_event("大簇事件")
    repo.link_event_evidence(event.event_id, "cluster:v1:116:CREATED", linked_by="cluster_seed")

    result = collect_file_timeline(repo.db_path, task_id, task)
    assert result["total_count"] == MAX_RELATED_EVIDENCE
    # 只保留时间戳最早的成员文件
    assert result["files"][0]["path"] == "/case/f00.txt"
    assert result["files"][-1]["path"] == f"/case/f{MAX_RELATED_EVIDENCE - 1:02d}.txt"


def test_empty_store_projection_has_no_files(tmp_path):
    result = empty_file_timeline("A")
    assert result == {
        "task_id": "A",
        "files": [],
        "total_count": 0,
        "axis": {"start": None, "end": None},
        "scope": {
            "event_count": 0,
            "link_count": 0,
            "cluster_count": 0,
            "undated_file_count": 0,
            "limited": False,
            "ensured_paths": [],
        },
    }


def test_analyzed_files_without_links_become_event_less_nodes(tmp_path):
    """文件中心兜底:零事件关联时,已分析文件成为无事件节点(MACB 降序,
    已删除标志随行);未分析文件不出现 —— 投影绝不发明文件。"""
    events_db = str(tmp_path / "events.db")
    _make_events_db(events_db, [])
    files_db = str(tmp_path / "files.db")
    conn = sqlite3.connect(files_db)
    conn.execute(
        "CREATE TABLE files (path TEXT, name TEXT, extension TEXT, category TEXT, "
        "type TEXT, size INTEGER, mtime INTEGER, ctime INTEGER, is_deleted INTEGER, "
        "md5 TEXT, llm_summary TEXT, llm_description TEXT, llm_keywords TEXT, "
        "llm_analyzed_at INTEGER, llm_model_used TEXT, scene_type TEXT, "
        "scene_priority INTEGER, scene_relevant INTEGER)"
    )
    conn.executemany(
        "INSERT INTO files (path, name, size, mtime, ctime, llm_analyzed_at, is_deleted) "
        "VALUES (?,?,?,?,?,?,?)",
        [("/case/a.txt", "a.txt", 10, 6000, 6000, 1700000000, 0),
         ("/case/b.txt", "b.txt", 20, 500, 400, None, 0),
         ("/case/mima.txt", "mima.txt", 122, 700, 650, 1700000001, 1)],
    )
    conn.commit()
    conn.close()
    raw_db = str(tmp_path / "raw.db")
    _make_raw_db(
        raw_db,
        [("/case/a.txt", 6000, 12500, 12100, 12050),
         ("/case/mima.txt", 700, 700, 700, 700)],
    )
    task = {
        "id": "A",
        "output_files_db": files_db,
        "output_events_db": events_db,
        "output_raw_db": raw_db,
    }
    repo = InvestigationRepository(tmp_path / "investigation.db", "A")

    result = collect_file_timeline(repo.db_path, "A", task, limit=10)

    assert [item["path"] for item in result["files"]] == [
        "/case/a.txt",
        "/case/mima.txt",
    ]
    assert result["files"][0]["event_count"] == 0
    assert result["files"][1]["name"] == "mima.txt"
    assert result["total_count"] == 2
    assert result["scope"]["cluster_count"] == 0


def _service(task, db_path):
    cpp_backend = Mock()
    cpp_backend.get_task = AsyncMock(return_value=task)
    return InvestigationEventService(cpp_backend, capture_service=Mock()), cpp_backend


@pytest.mark.asyncio
async def test_service_file_timeline_missing_store_falls_back_to_analyzed_files(tmp_path):
    """缺 investigation.db:退化为纯"已分析文件"投影,只读、不物化该库。"""
    files_db = tmp_path / "files.db"
    conn = sqlite3.connect(files_db)
    conn.execute(
        "CREATE TABLE files (path TEXT, name TEXT, size INTEGER, mtime INTEGER, "
        "ctime INTEGER, llm_analyzed_at INTEGER)"
    )
    conn.executemany(
        "INSERT INTO files (path, name, size, mtime, ctime, llm_analyzed_at) "
        "VALUES (?,?,?,?,?,?)",
        [("/case/a.txt", "a.txt", 10, 6000, 6000, 1700000000),
         ("/case/b.txt", "b.txt", 20, 500, 400, None)],
    )
    conn.commit()
    conn.close()
    task = {
        "id": "A",
        "output_files_db": str(files_db),
        "output_events_db": str(tmp_path / "events.db"),
    }
    service, _ = _service(task, tmp_path / "investigation.db")
    result = await service.file_timeline("A")
    assert [item["path"] for item in result["files"]] == ["/case/a.txt"]
    assert result["files"][0]["event_ids"] == []
    assert result["files"][0]["event_count"] == 0
    assert result["files"][0]["report_status"] is None
    assert result["scope"]["link_count"] == 0
    # 只读保证:GET 绝不物化 investigation.db
    assert not (tmp_path / "investigation.db").exists()


@pytest.mark.asyncio
async def test_service_file_timeline_missing_store_nothing_analyzed_returns_empty(tmp_path):
    task = {
        "id": "A",
        "output_files_db": str(tmp_path / "files.db"),
        "output_events_db": str(tmp_path / "events.db"),
    }
    service, _ = _service(task, tmp_path / "investigation.db")
    result = await service.file_timeline("A")
    assert result == empty_file_timeline("A")


@pytest.mark.asyncio
async def test_service_file_timeline_unknown_task_raises_not_found():
    cpp_backend = Mock()
    cpp_backend.get_task = AsyncMock(return_value=None)
    service = InvestigationEventService(cpp_backend, capture_service=Mock())
    with pytest.raises(EvidenceNotFoundError):
        await service.file_timeline("missing")


@pytest.mark.asyncio
async def test_service_file_timeline_collects_projection(tmp_path):
    store = _store(tmp_path)
    task, repo, _files_db, _events_db = store
    _seed(store)
    service, _ = _service(task, repo.db_path)

    result = await service.file_timeline("A")
    assert [item["path"] for item in result["files"]] == [
        "/case/a.txt",
        "/case/b.txt",
        "/case/c.txt",
        "/case/ghost.txt",
    ]
    assert result["scope"]["event_count"] == 2


def _route_client(manager):
    app = FastAPI()
    app.include_router(
        investigation_workbench.router, prefix="/api/investigation/workbench"
    )
    app.dependency_overrides[investigation_workbench._manager] = lambda: manager
    return TestClient(app)


def test_file_timeline_route_returns_projection():
    manager = Mock()
    manager.investigation_event_service = Mock(
        file_timeline=AsyncMock(
            return_value={
                "task_id": "T1",
                "files": [{"path": "/case/a.txt", "latest_time": 12500}],
                "total_count": 1,
                "axis": {"start": 12500, "end": 12500},
                "scope": {},
            }
        )
    )
    response = _route_client(manager).get(
        "/api/investigation/workbench/T1/file-timeline"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["files"][0]["path"] == "/case/a.txt"
    manager.investigation_event_service.file_timeline.assert_awaited_once_with(
        "T1", ensure_paths=()
    )


def test_file_timeline_route_passes_ensure_path_for_deep_links():
    manager = Mock()
    manager.investigation_event_service = Mock(
        file_timeline=AsyncMock(
            return_value={
                "task_id": "T1",
                "files": [],
                "total_count": 0,
                "axis": {"start": None, "end": None},
                "scope": {"ensured_paths": []},
            }
        )
    )
    response = _route_client(manager).get(
        "/api/investigation/workbench/T1/file-timeline",
        params={"ensure_path": "/etc/passwd"},
    )
    assert response.status_code == 200
    manager.investigation_event_service.file_timeline.assert_awaited_once_with(
        "T1", ensure_paths=("/etc/passwd",)
    )


def test_file_timeline_route_maps_unknown_task_to_404():
    manager = Mock()
    manager.investigation_event_service = Mock(
        file_timeline=AsyncMock(side_effect=EvidenceNotFoundError("task not found"))
    )
    response = _route_client(manager).get(
        "/api/investigation/workbench/T1/file-timeline"
    )
    assert response.status_code == 404


def test_file_nodes_carry_report_evidence_status(tmp_path):
    """判定三态随投影下发：已判定文件带 report_status，未判定为 None。"""
    store = _store(tmp_path)
    seeded = _seed(store)
    task, repo, _files_db, _events_db = store

    repo.add_report_evidence("file:/case/c.txt", report_status="main", added_by="test")
    projection = _collect(store, limit=10)
    by_path = {item["path"]: item for item in projection["files"]}

    assert by_path["/case/c.txt"]["report_status"] == "main"
    assert by_path["/case/a.txt"]["report_status"] is None
    assert seeded["file_event"]  # sanity: 关联事件仍在
