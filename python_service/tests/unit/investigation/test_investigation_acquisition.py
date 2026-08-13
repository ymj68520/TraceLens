"""Tests for snapshot acquisition (build_snapshot_candidate).

Verifies file/cluster candidates are read mode=ro at build time (capture-time
state), with no LLM, and that missing source -> EvidenceNotFoundError.
"""

import sqlite3

import pytest

from httpserver.services.evidence import EvidenceNotFoundError, ResolvedEvidence
from httpserver.services.investigation import build_snapshot_candidate


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
                r.get("path"), r.get("name"), r.get("extension"), r.get("category"),
                r.get("type"), r.get("size"), r.get("mtime"), r.get("ctime"),
                r.get("is_deleted"), r.get("md5"), r.get("llm_summary"), r.get("llm_description"),
                r.get("llm_keywords"), r.get("llm_analyzed_at"), r.get("llm_model_used"),
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


def test_file_candidate_freezes_files_db_content(tmp_path):
    fdb = str(tmp_path / "files.db")
    _make_files_db(fdb, [{
        "path": "/case/report.docx", "name": "report.docx", "size": 1234, "md5": "abc",
        "llm_description": "DESC", "llm_model_used": "m", "llm_analyzed_at": 5,
    }])
    resolved = ResolvedEvidence(
        task_id="A", evidence_key="file:/case/report.docx", evidence_type="file",
        normalized_path="/case/report.docx", source_db=fdb,
    )

    candidate = build_snapshot_candidate(resolved)

    assert candidate.evidence_type == "file"
    assert candidate.normalized_path == "/case/report.docx"
    assert candidate.payload.size == 1234
    assert candidate.payload.md5 == "abc"
    assert candidate.payload.initial_description == "DESC"   # frozen as-is, not generated
    assert candidate.payload.initial_model == "m"
    assert candidate.payload.initial_analyzed_at == 5


def test_file_candidate_missing_row_raises_not_found(tmp_path):
    fdb = str(tmp_path / "files.db")
    _make_files_db(fdb, [{"path": "/other"}])
    resolved = ResolvedEvidence(
        task_id="A", evidence_key="file:/case/report.docx", evidence_type="file",
        normalized_path="/case/report.docx", source_db=fdb,
    )
    with pytest.raises(EvidenceNotFoundError):
        build_snapshot_candidate(resolved)


def test_cluster_candidate_recomputes_aggregate(tmp_path):
    edb = str(tmp_path / "events.db")
    _make_events_db(edb, [
        {"timestamp": 6000, "event_type": "CREATED"},
        {"timestamp": 6010, "event_type": "CREATED"},
        {"timestamp": 6030, "event_type": "CREATED"},
    ])
    # resolved carries a STALE event_count=1 to prove the candidate recomputes
    resolved = ResolvedEvidence(
        task_id="A", evidence_key="cluster:v1:100:CREATED", evidence_type="cluster",
        version="v1", unix_minute=100, event_type="CREATED",
        cluster_start=6000, cluster_end=6000, event_count=1, representative_timestamp=6000,
        source_db=edb,
    )

    candidate = build_snapshot_candidate(resolved)

    assert candidate.evidence_type == "cluster"
    assert candidate.payload.event_count == 3            # recomputed from events.db, not stale 1
    assert candidate.payload.cluster_start == 6000
    assert candidate.payload.cluster_end == 6030
    assert candidate.payload.initial_summary is None      # S7
    assert candidate.payload.initial_description is None


def test_cluster_candidate_missing_cluster_raises_not_found(tmp_path):
    edb = str(tmp_path / "events.db")
    _make_events_db(edb, [{"timestamp": 6000, "event_type": "MODIFIED"}])
    resolved = ResolvedEvidence(
        task_id="A", evidence_key="cluster:v1:100:CREATED", evidence_type="cluster",
        version="v1", unix_minute=100, event_type="CREATED",
        cluster_start=6000, cluster_end=6000, event_count=1, representative_timestamp=6000,
        source_db=edb,
    )
    with pytest.raises(EvidenceNotFoundError):
        build_snapshot_candidate(resolved)
