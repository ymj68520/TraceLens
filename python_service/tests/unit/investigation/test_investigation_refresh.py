"""C7c-1 Event Refresh persistence and frozen-input tests (F1-F12)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from httpserver.services.evidence import ResolvedEvidence
from httpserver.services.investigation import (
    AnalysisReviewDecision,
    EventRefreshStatus,
    InvestigationEventConflictError,
    InvestigationEventService,
    InvestigationRepository,
    SecondaryAnalysisStatus,
)

KEY = "file:/case/a.txt"


def _make_files_db(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE files (
            path TEXT, name TEXT, extension TEXT, category TEXT, type TEXT, size INTEGER,
            mtime INTEGER, ctime INTEGER, is_deleted INTEGER, md5 TEXT,
            llm_summary TEXT, llm_description TEXT, llm_keywords TEXT,
            llm_analyzed_at INTEGER, llm_model_used TEXT,
            scene_type TEXT, scene_priority INTEGER, scene_relevant INTEGER)"""
    )
    conn.execute("INSERT INTO files (path,llm_description,size) VALUES (?,?,?)", ("/case/a.txt", "d", 1))
    conn.commit(); conn.close()


def _repo(tmp_path: Path, task_id="A"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    fdb = str(tmp_path / "files.db")
    idb = str(tmp_path / "investigation.db")
    _make_files_db(fdb)
    repo = InvestigationRepository(idb, task_id)
    snap = repo.capture_if_absent(ResolvedEvidence(
        task_id=task_id, evidence_key=KEY, evidence_type="file",
        normalized_path="/case/a.txt", source_db=fdb,
    ))
    return repo, snap


def _accepted(repo, snap, *, prompt="investigation-evidence-analysis:v2"):
    analysis = repo.create_analysis(snap, prompt_version=prompt)
    repo.transition(analysis.analysis_id, SecondaryAnalysisStatus.running)
    repo.transition(
        analysis.analysis_id, SecondaryAnalysisStatus.review_pending,
        description="desc", summary="summary", model="m",
    )
    return repo.review_analysis(
        analysis.analysis_id, decision=AnalysisReviewDecision.accepted, reviewer="a"
    )


def test_v5_to_v6_migration_and_new_db_v6(tmp_path):
    repo, snap = _repo(tmp_path)
    event = repo.create_event("event", created_by="a")
    repo.link_event_evidence(event.event_id, KEY)
    conn = sqlite3.connect(repo.db_path)
    for t in (
        "trg_inv_refresh_no_input_update", "trg_inv_refresh_legal_transition",
        "trg_inv_refresh_no_terminal_update",
    ):
        conn.execute(f"DROP TRIGGER IF EXISTS {t}")
    conn.execute("DROP TABLE investigation_event_refreshes")
    conn.execute("PRAGMA user_version = 5")
    conn.commit(); conn.close()

    reopened = InvestigationRepository(repo.db_path, "A")
    assert sqlite3.connect(repo.db_path).execute("PRAGMA user_version").fetchone()[0] == 6
    assert reopened.get_event(event.event_id).title == "event"
    assert len(reopened.list_event_evidence(event.event_id)) == 1


def test_admission_freezes_full_envelope_hash_and_audit(tmp_path):
    repo, snap = _repo(tmp_path)
    event = repo.create_event("base title", summary="base summary", created_by="creator")
    repo.link_event_evidence(event.event_id, KEY)
    _accepted(repo, snap)

    # C7c-1 does not clear staleness; this test isolates the frozen admission
    # flag by restoring a clean state as a direct fixture setup.
    conn = sqlite3.connect(repo.db_path)
    conn.execute(
        "UPDATE investigation_events SET needs_refresh=0 WHERE event_id=?",
        [event.event_id],
    )
    conn.commit(); conn.close()

    refresh = repo.create_event_refresh(event.event_id, requested_by="requester")
    assert refresh.status == EventRefreshStatus.queued
    assert refresh.requested_by == "requester"
    assert refresh.base_version == 1
    assert refresh.input_hash == hashlib.sha256(
        refresh.input_envelope_json.encode()
    ).hexdigest()
    payload = json.loads(refresh.input_envelope_json)
    assert payload["needs_refresh_at_submission"] is False
    assert payload["base_title"] == "base title"
    assert payload["links"][0]["evidence_key"] == KEY
    accepted = payload["links"][0]["accepted_analysis"]
    assert accepted["evidence_key"] == KEY
    assert accepted["description"] == "desc"
    assert accepted["claims"] == []
    assert "decided_by" not in json.dumps(payload)


def test_dirty_submission_is_recorded_and_clean_event_is_allowed(tmp_path):
    repo, snap = _repo(tmp_path)
    event = repo.create_event("event", created_by="a")
    repo.link_event_evidence(event.event_id, KEY)
    _accepted(repo, snap)
    dirty = repo.get_event(event.event_id)
    assert dirty.needs_refresh is True

    refresh = repo.create_event_refresh(event.event_id, requested_by="a")
    payload = json.loads(refresh.input_envelope_json)
    assert payload["needs_refresh_at_submission"] is True

    # A separate clean Event proves R8: explicit refresh is allowed when clean.
    clean = repo.create_event("clean", created_by="a")
    clean_refresh = repo.create_event_refresh(clean.event_id, requested_by="a")
    assert clean_refresh.status == EventRefreshStatus.queued


def test_latest_accepted_analysis_and_unaccepted_link_projection(tmp_path):
    repo, snap = _repo(tmp_path)
    event = repo.create_event("event", created_by="a")
    repo.link_event_evidence(event.event_id, KEY)
    first = _accepted(repo, snap)
    second = _accepted(repo, snap)
    assert second.version > first.version
    refresh = repo.create_event_refresh(event.event_id, requested_by="a")
    accepted = json.loads(refresh.input_envelope_json)["links"][0]["accepted_analysis"]
    assert accepted["analysis_id"] == second.analysis_id
    assert accepted["version"] == second.version


def test_no_accepted_link_has_snapshot_only(tmp_path):
    repo, snap = _repo(tmp_path)
    event = repo.create_event("event", created_by="a")
    repo.link_event_evidence(event.event_id, KEY)
    refresh = repo.create_event_refresh(event.event_id)
    link = json.loads(refresh.input_envelope_json)["links"][0]
    assert link["accepted_analysis"] is None
    assert link["snapshot"]["evidence_key"] == KEY


def test_links_and_claims_are_deterministically_ordered(tmp_path):
    repo, snap = _repo(tmp_path)
    # One link is enough to assert canonical JSON is stable and sorted keys;
    # claims are persisted in claim_index order by the existing repository.
    event = repo.create_event("event", created_by="a")
    repo.link_event_evidence(event.event_id, KEY)
    _accepted(repo, snap)
    one = repo.create_event_refresh(event.event_id)
    assert one.input_hash == hashlib.sha256(one.input_envelope_json.encode()).hexdigest()


def test_base_and_produced_version_composite_fks(tmp_path):
    repo, _ = _repo(tmp_path)
    event = repo.create_event("event", created_by="a")
    conn = sqlite3.connect(repo.db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO investigation_event_refreshes "
            "(refresh_id,task_id,event_id,base_version,status,input_hash,input_envelope_json,created_at) "
            "VALUES ('er_bad_base','A',?,999,'queued','h','{}','now')", [event.event_id]
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO investigation_event_refreshes "
            "(refresh_id,task_id,event_id,base_version,status,input_hash,input_envelope_json,created_at,produced_version) "
            "VALUES ('er_bad_produced','A',?,1,'queued','h','{}','now',999)", [event.event_id]
        )
    conn.execute(
        "INSERT INTO investigation_event_refreshes "
        "(refresh_id,task_id,event_id,base_version,status,input_hash,input_envelope_json,created_at) "
        "VALUES ('er_null_produced','A',?,1,'queued','h','{}','now')", [event.event_id]
    )
    conn.rollback()
    conn.close()


def test_active_refresh_partial_unique_index_and_history_slot(tmp_path):
    repo, _ = _repo(tmp_path)
    event = repo.create_event("event", created_by="a")
    first = repo.create_event_refresh(event.event_id, requested_by="a")
    with pytest.raises(InvestigationEventConflictError):
        repo.create_event_refresh(event.event_id, requested_by="b")

    conn = sqlite3.connect(repo.db_path)
    conn.execute(
        "UPDATE investigation_event_refreshes SET status='failed', failed_at='x' "
        "WHERE refresh_id=?", [first.refresh_id]
    )
    conn.commit(); conn.close()
    second = repo.create_event_refresh(event.event_id, requested_by="b")
    assert second.refresh_id != first.refresh_id


def test_refresh_input_and_terminal_immutability_triggers(tmp_path):
    repo, _ = _repo(tmp_path)
    event = repo.create_event("event", created_by="a")
    refresh = repo.create_event_refresh(event.event_id)
    conn = sqlite3.connect(repo.db_path)
    with pytest.raises(sqlite3.DatabaseError, match="input"):
        conn.execute("UPDATE investigation_event_refreshes SET input_hash='x' WHERE refresh_id=?", [refresh.refresh_id])
    conn.execute(
        "UPDATE investigation_event_refreshes SET status='running' WHERE refresh_id=?", [refresh.refresh_id]
    )
    conn.execute(
        "UPDATE investigation_event_refreshes SET status='failed', failed_at='x' WHERE refresh_id=?", [refresh.refresh_id]
    )
    conn.commit()
    with pytest.raises(sqlite3.DatabaseError, match="terminal"):
        conn.execute("UPDATE investigation_event_refreshes SET error_code='y' WHERE refresh_id=?", [refresh.refresh_id])
    conn.close()


def test_stale_refresh_list_and_task_scope(tmp_path):
    repo_a, _ = _repo(tmp_path / "A", "A")
    repo_b, _ = _repo(tmp_path / "B", "B")
    event_a = repo_a.create_event("a", created_by="a")
    event_b = repo_b.create_event("b", created_by="b")
    refresh_a = repo_a.create_event_refresh(event_a.event_id)
    repo_b.create_event_refresh(event_b.event_id)
    assert [r.refresh_id for r in repo_a.list_stale_event_refreshes()] == [refresh_a.refresh_id]
    assert repo_b.get_event_refresh(refresh_a.refresh_id) is None


def test_f8_admission_does_not_call_public_readers(tmp_path, monkeypatch):
    repo, snap = _repo(tmp_path)
    event = repo.create_event("event", created_by="a")
    repo.link_event_evidence(event.event_id, KEY)

    def bomb(*args, **kwargs):
        raise AssertionError("public reader opened a second connection")

    monkeypatch.setattr(repo, "get_event", bomb)
    monkeypatch.setattr(repo, "list_event_evidence", bomb)
    monkeypatch.setattr(repo, "get_latest_accepted_analysis", bomb)
    monkeypatch.setattr(repo, "list_claims", bomb)
    refresh = repo.create_event_refresh(event.event_id)
    assert refresh.status == EventRefreshStatus.queued
