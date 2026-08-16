"""Phase C cross-stage integration: accepted Analysis → Event dirty
(C10 §1 variants, §9, E6/E7).

Proves both temporal directions of the C7b propagation invariant at the
persistence layer: accept-then-link and link-then-accept both leave the
Event dirty; rejected/invalid never propagate; the dirty bump is idempotent.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from httpserver.services.evidence import ResolvedEvidence
from httpserver.services.investigation import (
    AnalysisReviewDecision,
    InvestigationRepository,
    SecondaryAnalysisStatus,
)

PROMPT_V3 = "investigation-evidence-analysis:v3"
KEY = "file:/case/a.txt"


def _task_repo(tmp_path: Path, task_id: str):
    files_db = str(tmp_path / "files.db")
    conn = sqlite3.connect(files_db)
    conn.execute(
        """CREATE TABLE files (
            path TEXT, name TEXT, extension TEXT, category TEXT, type TEXT, size INTEGER,
            mtime INTEGER, ctime INTEGER, is_deleted INTEGER, md5 TEXT,
            llm_summary TEXT, llm_description TEXT, llm_keywords TEXT,
            llm_analyzed_at INTEGER, llm_model_used TEXT,
            scene_type TEXT, scene_priority INTEGER, scene_relevant INTEGER)"""
    )
    conn.execute(
        "INSERT INTO files (path, llm_description, size) VALUES (?,?,?)",
        ("/case/a.txt", "d", 1),
    )
    conn.commit()
    conn.close()
    repo = InvestigationRepository(tmp_path / "investigation.db", task_id)
    snapshot = repo.capture_if_absent(ResolvedEvidence(
        task_id=task_id, evidence_key=KEY, evidence_type="file",
        normalized_path="/case/a.txt", source_db=files_db,
    ))
    return repo, snapshot


def _decided(repo, snapshot, decision):
    analysis = repo.create_analysis(snapshot, prompt_version=PROMPT_V3)
    repo.transition(analysis.analysis_id, SecondaryAnalysisStatus.running)
    repo.complete_analysis_for_review(
        analysis.analysis_id, description="d", summary="s",
        model="m", candidates=[],
    )
    if decision is None:
        return repo.get_analysis(analysis.analysis_id)
    return repo.review_analysis(
        analysis.analysis_id, decision=decision, reviewer="analyst"
    )


def test_link_then_accept_marks_event_dirty(tmp_path):
    """§1 main chain step 7-9: link Evidence, then accept → dirty."""
    repo, snapshot = _task_repo(tmp_path, "A")
    event = repo.create_event("E1", created_by="a")
    repo.link_event_evidence(event.event_id, KEY, linked_by="a")
    assert repo.get_event(event.event_id).needs_refresh is False

    _decided(repo, snapshot, AnalysisReviewDecision.accepted)

    updated = repo.get_event(event.event_id)
    assert updated.needs_refresh is True
    assert updated.current_version == 1  # dirty ≠ new narrative


def test_accept_then_link_still_marks_event_dirty(tmp_path):
    """§1 variant A: accept BEFORE the link → the later link is born dirty."""
    repo, snapshot = _task_repo(tmp_path, "A")
    _decided(repo, snapshot, AnalysisReviewDecision.accepted)

    event = repo.create_event("E1", created_by="a")
    repo.link_event_evidence(event.event_id, KEY, linked_by="a")

    assert repo.get_event(event.event_id).needs_refresh is True


def test_rejected_and_unreviewed_never_mark_events_dirty(tmp_path):
    repo, snapshot = _task_repo(tmp_path, "A")
    event = repo.create_event("E1", created_by="a")
    repo.link_event_evidence(event.event_id, KEY, linked_by="a")

    _decided(repo, snapshot, AnalysisReviewDecision.rejected)
    _decided(repo, snapshot, None)  # review_pending

    assert repo.get_event(event.event_id).needs_refresh is False


def test_dirty_bump_is_idempotent_per_clean_to_dirty_transition(tmp_path):
    """§9: already-dirty keeps its updated_at on a later accepted version."""
    repo, snapshot = _task_repo(tmp_path, "A")
    event = repo.create_event("E1", created_by="a")
    repo.link_event_evidence(event.event_id, KEY, linked_by="a")

    _decided(repo, snapshot, AnalysisReviewDecision.accepted)
    first_bump = repo.get_event(event.event_id).updated_at
    assert repo.get_event(event.event_id).needs_refresh is True

    _decided(repo, snapshot, AnalysisReviewDecision.accepted)  # second accept

    still = repo.get_event(event.event_id)
    assert still.needs_refresh is True
    assert still.updated_at == first_bump  # one bump per clean→dirty change


def test_unlinked_event_stays_clean_when_other_events_are_dirty(tmp_path):
    """E6: propagation flows only through the authoritative link table."""
    repo, snapshot = _task_repo(tmp_path, "A")
    linked = repo.create_event("linked", created_by="a")
    unlinked = repo.create_event("unlinked", created_by="a")
    repo.link_event_evidence(linked.event_id, KEY, linked_by="a")

    _decided(repo, snapshot, AnalysisReviewDecision.accepted)

    assert repo.get_event(linked.event_id).needs_refresh is True
    assert repo.get_event(unlinked.event_id).needs_refresh is False
