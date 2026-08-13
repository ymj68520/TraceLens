"""Phase B regression tests for association endpoints (cluster-files / file-clusters).

Covers directory segment matching (B2/B3/B4), candidate-truncation false negatives
in both directions (B5a/B5b), four-timestamp semantics, the per-Evidence raw→files
fallback, the LIMIT-5 directory-sample fix, backslash-path canonicalization (B1),
and the strict `< 300` boundary.

Endpoints are driven directly with a mocked service_manager whose cpp_backend.get_task
returns temp DB paths; no real LLM/C++ backend is involved.
"""

import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from httpserver.routes.associations import (
    ClusterFilesRequest,
    FileClustersRequest,
    get_cluster_related_files,
    get_file_related_clusters,
)


# ---------- DB fixtures ----------

def _make_files_db(db_path, rows):
    """rows: list of dicts (path, mtime, ctime, ...)."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE files (
            path TEXT, size INTEGER, mtime INTEGER, ctime INTEGER,
            extension TEXT, name TEXT, llm_summary TEXT, llm_description TEXT)"""
    )
    for r in rows:
        conn.execute(
            "INSERT INTO files (path,size,mtime,ctime,extension,name,llm_summary,llm_description) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (r.get("path"), r.get("size", 0), r.get("mtime"), r.get("ctime"),
             r.get("extension", ""), r.get("name", ""), r.get("llm_summary"), r.get("llm_description")),
        )
    conn.commit()
    conn.close()


def _make_raw_db(db_path, rows):
    """rows: dict path -> {atime,mtime,ctime,crtime}."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE files (
            path TEXT, atime INTEGER, mtime INTEGER, ctime INTEGER, crtime INTEGER)"""
    )
    for p, ts in rows.items():
        conn.execute(
            "INSERT INTO files (path,atime,mtime,ctime,crtime) VALUES (?,?,?,?,?)",
            (p, ts.get("atime"), ts.get("mtime"), ts.get("ctime"), ts.get("crtime")),
        )
    conn.commit()
    conn.close()


def _make_events_db(db_path, rows):
    """rows: list of dicts (timestamp, event_type, file_path, ...)."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE events (
            timestamp INTEGER, event_type TEXT, file_path TEXT,
            llm_summary TEXT, llm_description TEXT, llm_keywords TEXT, llm_is_relevant INTEGER)"""
    )
    for r in rows:
        conn.execute(
            "INSERT INTO events (timestamp,event_type,file_path,llm_summary,llm_description,llm_keywords,llm_is_relevant) "
            "VALUES (?,?,?,?,?,?,?)",
            (r["timestamp"], r["event_type"], r["file_path"],
             r.get("llm_summary"), r.get("llm_description"), r.get("llm_keywords"), r.get("llm_is_relevant")),
        )
    conn.commit()
    conn.close()


def _mock_sm(monkeypatch, files_db, raw_db, events_db):
    import httpserver.services as svc_mod

    sm = SimpleNamespace()
    sm.cpp_backend = SimpleNamespace()
    sm.cpp_backend.get_task = AsyncMock(return_value={
        "output_files_db": files_db,
        "output_raw_db": raw_db,
        "output_events_db": events_db,
    })
    monkeypatch.setattr(svc_mod, "get_service_manager", lambda: sm)


def _dbs(tmp_path, name="dbs"):
    base = tmp_path / name
    base.mkdir(exist_ok=True)
    return str(base / "files.db"), str(base / "raw.db"), str(base / "events.db")


# ---------- cluster-files tests ----------

@pytest.mark.asyncio
async def test_B2_B3_directory_match_and_segment_rejection(tmp_path, monkeypatch):
    T = 6000
    files_db, raw_db, events_db = _dbs(tmp_path)
    _make_files_db(files_db, [
        {"path": "/case/a/file.txt", "mtime": T},
        {"path": "/case/abc/file.txt", "mtime": T},      # sibling prefix, must NOT match
        {"path": "/case/a-extra/file.txt", "mtime": T},  # sibling prefix, must NOT match
        {"path": "/case/a/sub/file.txt", "mtime": T},    # nested, must match
    ])
    _make_raw_db(raw_db, {})
    _make_events_db(events_db, [])
    _mock_sm(monkeypatch, files_db, raw_db, events_db)

    req = ClusterFilesRequest(task_id="t", time_window=T // 60, event_type="MODIFIED",
                              parent_directory="/case/a", limit=10)
    resp = await get_cluster_related_files(req, settings=None)

    paths = {f["file_path"] for f in resp.files}
    assert paths == {"/case/a/file.txt", "/case/a/sub/file.txt"}


@pytest.mark.asyncio
async def test_B3_empty_and_root_parent_is_unconstrained(tmp_path, monkeypatch):
    T = 6000
    files_db, raw_db, events_db = _dbs(tmp_path)
    _make_files_db(files_db, [
        {"path": "/case/a/file.txt", "mtime": T},
        {"path": "/other/file.txt", "mtime": T},
    ])
    _make_raw_db(raw_db, {})
    _make_events_db(events_db, [])
    _mock_sm(monkeypatch, files_db, raw_db, events_db)

    for parent in ("", "/"):
        req = ClusterFilesRequest(task_id="t", time_window=T // 60, event_type="MODIFIED",
                                  parent_directory=parent, limit=10)
        resp = await get_cluster_related_files(req, settings=None)
        assert {f["file_path"] for f in resp.files} == {"/case/a/file.txt", "/other/file.txt"}


@pytest.mark.asyncio
async def test_B5a_no_limit3_false_negative(tmp_path, monkeypatch):
    T = 6000
    files_db, raw_db, events_db = _dbs(tmp_path)
    # Decoys with much newer mtime (out of the ±300s window) that would fill the old
    # `ORDER BY mtime DESC LIMIT limit*3` cap; the real target is old but in-window.
    rows = [{"path": f"/case/a/decoy{i}.bin", "mtime": T + 10_000_000} for i in range(5)]
    rows.append({"path": "/case/a/target.txt", "mtime": T})
    _make_files_db(files_db, rows)
    _make_raw_db(raw_db, {})
    _make_events_db(events_db, [])
    _mock_sm(monkeypatch, files_db, raw_db, events_db)

    req = ClusterFilesRequest(task_id="t", time_window=T // 60, event_type="MODIFIED",
                              parent_directory="/case/a", limit=1)
    resp = await get_cluster_related_files(req, settings=None)

    assert {f["file_path"] for f in resp.files} == {"/case/a/target.txt"}


@pytest.mark.asyncio
async def test_four_timestamp_atime_only_via_raw(tmp_path, monkeypatch):
    T = 6000
    files_db, raw_db, events_db = _dbs(tmp_path)
    # files.db has the row (metadata) but no in-window mtime/ctime; raw.db supplies
    # atime in-window. Must still be associated (four-timestamp semantics).
    _make_files_db(files_db, [{"path": "/case/a/file.txt", "mtime": None, "ctime": None}])
    _make_raw_db(raw_db, {"/case/a/file.txt": {"atime": T, "mtime": None, "ctime": None, "crtime": None}})
    _make_events_db(events_db, [])
    _mock_sm(monkeypatch, files_db, raw_db, events_db)

    req = ClusterFilesRequest(task_id="t", time_window=T // 60, event_type="MODIFIED",
                              parent_directory="/case/a", limit=10)
    resp = await get_cluster_related_files(req, settings=None)

    assert {f["file_path"] for f in resp.files} == {"/case/a/file.txt"}


@pytest.mark.asyncio
async def test_per_path_fallback_file_in_files_but_not_raw(tmp_path, monkeypatch):
    T = 6000
    files_db, raw_db, events_db = _dbs(tmp_path)
    # file2 is in files.db (mtime in window) but absent from raw.db;
    # file1 is in raw.db (atime in window) but files.db mtime is NULL.
    _make_files_db(files_db, [
        {"path": "/case/a/file1.txt", "mtime": None, "ctime": None},
        {"path": "/case/a/file2.txt", "mtime": T, "ctime": None},
    ])
    _make_raw_db(raw_db, {"/case/a/file1.txt": {"atime": T, "mtime": None, "ctime": None, "crtime": None}})
    _make_events_db(events_db, [])
    _mock_sm(monkeypatch, files_db, raw_db, events_db)

    req = ClusterFilesRequest(task_id="t", time_window=T // 60, event_type="MODIFIED",
                              parent_directory="/case/a", limit=10)
    resp = await get_cluster_related_files(req, settings=None)

    assert {f["file_path"] for f in resp.files} == {"/case/a/file1.txt", "/case/a/file2.txt"}


@pytest.mark.asyncio
async def test_strict_boundary_diff_300_not_associated(tmp_path, monkeypatch):
    T = 6000
    files_db, raw_db, events_db = _dbs(tmp_path)
    _make_files_db(files_db, [
        {"path": "/case/a/just_out.txt", "mtime": T + 300},  # diff == 300 -> excluded
        {"path": "/case/a/just_in.txt", "mtime": T + 299},   # diff == 299 -> included
    ])
    _make_raw_db(raw_db, {})
    _make_events_db(events_db, [])
    _mock_sm(monkeypatch, files_db, raw_db, events_db)

    req = ClusterFilesRequest(task_id="t", time_window=T // 60, event_type="MODIFIED",
                              parent_directory="/case/a", limit=10)
    resp = await get_cluster_related_files(req, settings=None)

    paths = {f["file_path"] for f in resp.files}
    assert "/case/a/just_in.txt" in paths
    assert "/case/a/just_out.txt" not in paths


# ---------- file-clusters tests ----------

@pytest.mark.asyncio
async def test_B1_backslash_request_path_resolves_timestamps(tmp_path, monkeypatch):
    T = 6000
    files_db, raw_db, events_db = _dbs(tmp_path)
    _make_files_db(files_db, [])
    _make_raw_db(raw_db, {"/case/a/file.txt": {"atime": None, "mtime": T, "ctime": None, "crtime": None}})
    _make_events_db(events_db, [{"timestamp": T, "event_type": "MODIFIED", "file_path": "/case/a/evt.txt"}])
    _mock_sm(monkeypatch, files_db, raw_db, events_db)

    # Backslash request path must canonicalize to hit the raw.db lookup.
    req = FileClustersRequest(task_id="t", file_path="\\case\\a\\file.txt", limit=10)
    resp = await get_file_related_clusters(req, settings=None)

    assert resp.total_count == 1
    assert resp.clusters[0]["matched_time"] is not None  # time-based match (timestamps found)


@pytest.mark.asyncio
async def test_B4_directory_mismatch_excluded_even_when_time_matches(tmp_path, monkeypatch):
    T = 6000
    files_db, raw_db, events_db = _dbs(tmp_path)
    _make_files_db(files_db, [])
    _make_raw_db(raw_db, {"/case/a/file.txt": {"atime": None, "mtime": T, "ctime": None, "crtime": None}})
    _make_events_db(events_db, [{"timestamp": T, "event_type": "MODIFIED", "file_path": "/other/evt.txt"}])
    _mock_sm(monkeypatch, files_db, raw_db, events_db)

    req = FileClustersRequest(task_id="t", file_path="/case/a/file.txt", limit=10)
    resp = await get_file_related_clusters(req, settings=None)

    assert resp.total_count == 0  # time matched but directory did not -> excluded (B4)


@pytest.mark.asyncio
async def test_B5b_no_limit10_false_negative(tmp_path, monkeypatch):
    T = 6000
    files_db, raw_db, events_db = _dbs(tmp_path)
    _make_files_db(files_db, [])
    _make_raw_db(raw_db, {"/case/a/file.txt": {"atime": None, "mtime": T, "ctime": None, "crtime": None}})
    # 11 newer decoy clusters (out of the file's ±300s window) that would fill the old
    # `ORDER BY representative DESC LIMIT limit*10` cap, plus one in-window target cluster.
    events = [
        {"timestamp": T + 10_000_000 + i, "event_type": "MODIFIED", "file_path": f"/case/a/d{i}"}
        for i in range(11)
    ]
    events.append({"timestamp": T, "event_type": "MODIFIED", "file_path": "/case/a/target"})
    _make_events_db(events_db, events)
    _mock_sm(monkeypatch, files_db, raw_db, events_db)

    req = FileClustersRequest(task_id="t", file_path="/case/a/file.txt", limit=1)
    resp = await get_file_related_clusters(req, settings=None)

    # Only the in-window target cluster survives; it would be dropped by the old DESC LIMIT.
    windows = {c["time_window"] for c in resp.clusters}
    assert (T // 60) in windows
    assert resp.total_count == 1


@pytest.mark.asyncio
async def test_directory_predicate_uses_full_cluster_paths_not_sample5(tmp_path, monkeypatch):
    T = 6000
    files_db, raw_db, events_db = _dbs(tmp_path)
    _make_files_db(files_db, [])
    _make_raw_db(raw_db, {"/case/a/file.txt": {"atime": None, "mtime": T, "ctime": None, "crtime": None}})
    # One cluster whose target directory (/case/a) only appears in the 6th+ distinct path;
    # the old `SELECT DISTINCT file_path ... LIMIT 5` sample would miss it.
    events = [{"timestamp": T, "event_type": "MODIFIED", "file_path": f"/other/p{i}"} for i in range(6)]
    events.append({"timestamp": T, "event_type": "MODIFIED", "file_path": "/case/a/late"})
    _make_events_db(events_db, events)
    _mock_sm(monkeypatch, files_db, raw_db, events_db)

    req = FileClustersRequest(task_id="t", file_path="/case/a/file.txt", limit=10)
    resp = await get_file_related_clusters(req, settings=None)

    assert resp.total_count == 1  # full-path directory predicate finds /case/a


@pytest.mark.asyncio
async def test_file_clusters_segment_directory_matching(tmp_path, monkeypatch):
    T = 6000
    files_db, raw_db, events_db = _dbs(tmp_path)
    _make_files_db(files_db, [])
    _make_raw_db(raw_db, {"/case/abc/file.txt": {"atime": None, "mtime": T, "ctime": None, "crtime": None}})
    # Cluster directory is /case/a ; file is /case/abc/... -> segment mismatch -> excluded.
    _make_events_db(events_db, [{"timestamp": T, "event_type": "MODIFIED", "file_path": "/case/a/evt.txt"}])
    _mock_sm(monkeypatch, files_db, raw_db, events_db)

    req = FileClustersRequest(task_id="t", file_path="/case/abc/file.txt", limit=10)
    resp = await get_file_related_clusters(req, settings=None)

    assert resp.total_count == 0
