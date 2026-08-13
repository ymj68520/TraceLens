"""Tests for InvestigationRepository (Phase C4a): capture, idempotency,
concurrency, immutability, fail-closed schema, and read-time consistency.

Covers invariants S1-S9. Uses real tmp sqlite (files.db / events.db) and the
shared-mutable investigation.db to exercise true DB-level guarantees.
"""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from httpserver.services.evidence import EvidenceNotFoundError, EvidenceStoreError, ResolvedEvidence
from httpserver.services.investigation import (
    FileSnapshotPayload,
    InvestigationRepository,
    SUPPORTED_SCHEMA_VERSION,
    canonical_json,
)


# ---------- fixtures ----------

def _make_files_db(db_path, rows):
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE files (
            path TEXT, name TEXT, extension TEXT, category TEXT, type TEXT, size INTEGER,
            mtime INTEGER, ctime INTEGER, is_deleted INTEGER, md5 TEXT,
            llm_summary TEXT, llm_description TEXT, llm_keywords TEXT,
            llm_analyzed_at INTEGER, llm_model_used TEXT,
            scene_type TEXT, scene_priority INTEGER, scene_relevant INTEGER)"""
    )
    for r in rows:
        conn.execute(
            "INSERT INTO files (path,name,extension,category,type,size,mtime,ctime,is_deleted,md5,"
            "llm_summary,llm_description,llm_keywords,llm_analyzed_at,llm_model_used,"
            "scene_type,scene_priority,scene_relevant) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                r.get("path"), r.get("name"), r.get("extension"), r.get("category"), r.get("type"),
                r.get("size"), r.get("mtime"), r.get("ctime"), r.get("is_deleted"), r.get("md5"),
                r.get("llm_summary"), r.get("llm_description"), r.get("llm_keywords"),
                r.get("llm_analyzed_at"), r.get("llm_model_used"),
                r.get("scene_type"), r.get("scene_priority"), r.get("scene_relevant"),
            ),
        )
    conn.commit()
    conn.close()


def _make_events_db(db_path, events):
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE events (timestamp INTEGER, event_type TEXT, file_path TEXT)")
    for e in events:
        conn.execute(
            "INSERT INTO events (timestamp,event_type,file_path) VALUES (?,?,?)",
            (e["timestamp"], e["event_type"], e.get("file_path", "")),
        )
    conn.commit()
    conn.close()


def _file_resolved(fdb, task_id="A", path="/case/report.docx"):
    return ResolvedEvidence(
        task_id=task_id, evidence_key=f"file:{path}", evidence_type="file",
        normalized_path=path, source_db=fdb,
    )


def _cluster_resolved(edb, task_id="A", minute=100, event_type="CREATED"):
    return ResolvedEvidence(
        task_id=task_id, evidence_key=f"cluster:v1:{minute}:{event_type}", evidence_type="cluster",
        version="v1", unix_minute=minute, event_type=event_type,
        cluster_start=6000, cluster_end=6000, event_count=1, representative_timestamp=6000,
        source_db=edb,
    )


def _count_snapshots(idb):
    conn = sqlite3.connect(idb)
    n = conn.execute("SELECT COUNT(*) FROM evidence_snapshots").fetchone()[0]
    conn.close()
    return n


# ---------- capture basics ----------

def test_file_capture_then_idempotent(tmp_path):
    fdb, idb = str(tmp_path / "files.db"), str(tmp_path / "investigation.db")
    _make_files_db(fdb, [{"path": "/case/report.docx", "llm_description": "DESC", "size": 7}])
    repo = InvestigationRepository(idb, "A")
    resolved = _file_resolved(fdb)

    first = repo.capture_if_absent(resolved)
    second = repo.capture_if_absent(resolved)

    assert first.evidence_key == second.evidence_key
    assert first.captured_at == second.captured_at      # same snapshot
    assert _count_snapshots(idb) == 1
    assert first.payload.initial_description == "DESC"


def test_cluster_capture_recomputes_at_capture_time(tmp_path):
    edb, idb = str(tmp_path / "events.db"), str(tmp_path / "investigation.db")
    _make_events_db(edb, [{"timestamp": 6000, "event_type": "CREATED"}])
    repo = InvestigationRepository(idb, "A")
    resolved = _cluster_resolved(edb)  # carries stale event_count=1

    # add more events to the same cluster BEFORE capture
    conn = sqlite3.connect(edb)
    conn.executemany(
        "INSERT INTO events (timestamp,event_type,file_path) VALUES (?,?,?)",
        [(6010, "CREATED", "/a"), (6020, "CREATED", "/b")],
    )
    conn.commit()
    conn.close()

    snap = repo.capture_if_absent(resolved)
    assert snap.payload.event_count == 3               # capture-time recomputation
    assert snap.payload.initial_summary is None         # S7


def test_cluster_deleted_before_capture_raises(tmp_path):
    edb, idb = str(tmp_path / "events.db"), str(tmp_path / "investigation.db")
    _make_events_db(edb, [{"timestamp": 6000, "event_type": "CREATED"}])
    repo = InvestigationRepository(idb, "A")
    resolved = _cluster_resolved(edb)

    conn = sqlite3.connect(edb)
    conn.execute("DELETE FROM events")
    conn.commit()
    conn.close()

    with pytest.raises(EvidenceNotFoundError):
        repo.capture_if_absent(resolved)
    assert _count_snapshots(idb) == 0


# ---------- S1: existing snapshot no longer needs source ----------

def test_S1_source_row_deleted_returns_existing(tmp_path):
    fdb, idb = str(tmp_path / "files.db"), str(tmp_path / "investigation.db")
    _make_files_db(fdb, [{"path": "/case/report.docx"}])
    repo = InvestigationRepository(idb, "A")
    resolved = _file_resolved(fdb)
    first = repo.capture_if_absent(resolved)

    conn = sqlite3.connect(fdb)
    conn.execute("DELETE FROM files WHERE path='/case/report.docx'")
    conn.commit()
    conn.close()

    second = repo.capture_if_absent(resolved)
    assert second.evidence_key == first.evidence_key
    assert second.captured_at == first.captured_at


def test_S1_source_db_removed_returns_existing(tmp_path):
    fdb, idb = str(tmp_path / "files.db"), str(tmp_path / "investigation.db")
    _make_files_db(fdb, [{"path": "/case/report.docx"}])
    repo = InvestigationRepository(idb, "A")
    resolved = _file_resolved(fdb)
    first = repo.capture_if_absent(resolved)

    Path(fdb).rename(fdb + ".gone")  # source DB gone

    second = repo.capture_if_absent(resolved)  # existing fast path; does not open files.db
    assert second.evidence_key == first.evidence_key


# ---------- S2: task binding ----------

def test_S2_cross_task_rejected_no_write(tmp_path):
    fdb = str(tmp_path / "files.db")
    _make_files_db(fdb, [{"path": "/case/report.docx"}])
    idb_b = str(tmp_path / "B_investigation.db")
    resolved_a = _file_resolved(fdb, task_id="A")
    repo_b = InvestigationRepository(idb_b, "B")

    with pytest.raises(ValueError):
        repo_b.capture_if_absent(resolved_a)
    assert _count_snapshots(idb_b) == 0


# ---------- S3: concurrency ----------

def test_S3_concurrent_capture_single_row(tmp_path):
    fdb, idb = str(tmp_path / "files.db"), str(tmp_path / "investigation.db")
    _make_files_db(fdb, [{"path": "/case/report.docx"}])
    resolved = _file_resolved(fdb)

    def worker(_):
        # each worker creates its own repository (exercises concurrent init too)
        return InvestigationRepository(idb, "A").capture_if_absent(resolved)

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(worker, range(16)))

    assert len(results) == 16
    assert all(r.evidence_key == "file:/case/report.docx" for r in results)
    assert _count_snapshots(idb) == 1


# ---------- S4: no UPDATE ----------

def test_S4_update_trigger_aborts(tmp_path):
    fdb, idb = str(tmp_path / "files.db"), str(tmp_path / "investigation.db")
    _make_files_db(fdb, [{"path": "/case/report.docx"}])
    repo = InvestigationRepository(idb, "A")
    repo.capture_if_absent(_file_resolved(fdb))

    conn = sqlite3.connect(idb)
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("UPDATE evidence_snapshots SET snapshot_json='{}'")
    unchanged = conn.execute("SELECT snapshot_json FROM evidence_snapshots").fetchone()[0]
    conn.close()
    assert unchanged != "{}"


# ---------- S6: schema version ----------

def test_schema_init_creates_objects_and_version(tmp_path):
    idb = str(tmp_path / "investigation.db")
    InvestigationRepository(idb, "A")
    conn = sqlite3.connect(idb)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SUPPORTED_SCHEMA_VERSION
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='evidence_snapshots'"
    ).fetchone()
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='trigger' AND name='trg_evsnap_no_update'"
    ).fetchone()
    indexes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"idx_evsnap_path", "idx_evsnap_cluster", "idx_evsnap_task"} <= indexes
    conn.close()


def test_S6_unsupported_version_fail_closed(tmp_path):
    idb = str(tmp_path / "investigation.db")
    Path(idb).write_bytes(b"")
    conn = sqlite3.connect(idb)
    conn.execute("PRAGMA user_version = 999")
    conn.commit()
    conn.close()
    with pytest.raises(EvidenceStoreError):
        InvestigationRepository(idb, "A")


def test_S6_v1_but_corrupt_schema_fail_closed(tmp_path):
    idb = str(tmp_path / "investigation.db")
    InvestigationRepository(idb, "A")  # init properly
    conn = sqlite3.connect(idb)
    conn.execute("DROP TABLE evidence_snapshots")  # remove trigger too
    conn.execute(
        "CREATE TABLE evidence_snapshots "
        "(id INTEGER PRIMARY KEY, task_id TEXT, evidence_key TEXT, evidence_type TEXT, "
        "snapshot_json TEXT, captured_at INTEGER)"  # missing columns + no UNIQUE
    )
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()
    with pytest.raises(EvidenceStoreError):
        InvestigationRepository(idb, "A")


# ---------- S9: row<->payload identity consistency ----------

def test_S9_identity_mismatch_raises(tmp_path):
    idb = str(tmp_path / "investigation.db")
    InvestigationRepository(idb, "A")  # init schema
    payload_json = canonical_json(FileSnapshotPayload(normalized_path="/B/x"))
    conn = sqlite3.connect(idb)
    conn.execute(
        "INSERT INTO evidence_snapshots "
        "(task_id,evidence_key,evidence_type,normalized_path,unix_minute,event_type,snapshot_json,captured_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        ("A", "file:/x", "file", "/A", None, None, payload_json, 123),
    )
    conn.commit()
    conn.close()

    with pytest.raises(EvidenceStoreError):
        InvestigationRepository(idb, "A").get_snapshot("file:/x")


# ---------- CHECK constraint: DB-level identity shape ----------

def test_CHECK_rejects_file_row_without_path(tmp_path):
    idb = str(tmp_path / "investigation.db")
    InvestigationRepository(idb, "A")
    conn = sqlite3.connect(idb)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO evidence_snapshots "
            "(task_id,evidence_key,evidence_type,normalized_path,unix_minute,event_type,snapshot_json,captured_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            ("A", "file:/x", "file", None, None, None, "{}", 123),  # file but path NULL
        )
    conn.close()


# ---------- S8: deterministic JSON ----------

def test_S8_deterministic_snapshot_json(tmp_path):
    import json
    fdb, idb = str(tmp_path / "files.db"), str(tmp_path / "investigation.db")
    _make_files_db(fdb, [{"path": "/case/report.docx", "llm_description": "DESC"}])
    InvestigationRepository(idb, "A").capture_if_absent(_file_resolved(fdb))

    conn = sqlite3.connect(idb)
    stored = conn.execute("SELECT snapshot_json FROM evidence_snapshots").fetchone()[0]
    conn.close()

    redumped = canonical_json(FileSnapshotPayload.model_validate(json.loads(stored)))
    assert redumped == stored  # canonical, stable under re-dump
