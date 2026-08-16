"""Phase C cross-stage integration: cross-task isolation (C10 §18, E12).

Task A and Task B own separate investigation.db stores and share the same
evidence_key plus a similar event title. Every identity — snapshot,
analysis, claim, event, link, refresh — must stay task-scoped: submitting a
foreign id against the other task yields not-found/conflict, never a
cross-task read or write.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from httpserver.services.evidence import ResolvedEvidence, EvidenceNotFoundError
from httpserver.services.investigation import (
    AnalysisReviewConflictError,
    AnalysisReviewDecision,
    InvestigationEventConflictError,
    InvestigationGraphReader,
    InvestigationRepository,
    SecondaryAnalysisStatus,
)

PROMPT_V3 = "investigation-evidence-analysis:v3"
KEY = "file:/case/a.txt"  # SAME key in both tasks


def _task_repo(tmp_path: Path, task_id: str):
    root = tmp_path / task_id
    root.mkdir(parents=True, exist_ok=True)
    files_db = str(root / "files.db")
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
    repo = InvestigationRepository(root / "investigation.db", task_id)
    snapshot = repo.capture_if_absent(ResolvedEvidence(
        task_id=task_id, evidence_key=KEY, evidence_type="file",
        normalized_path="/case/a.txt", source_db=files_db,
    ))
    return repo, snapshot


def _accepted_with_claims(repo, snapshot):
    from httpserver.services.investigation import ClaimCandidate

    analysis = repo.create_analysis(snapshot, prompt_version=PROMPT_V3)
    repo.transition(analysis.analysis_id, SecondaryAnalysisStatus.running)
    repo.complete_analysis_for_review(
        analysis.analysis_id, description="d", summary="s", model="m",
        candidates=[ClaimCandidate(
            claim_type="FACT", claim_text="same text in both tasks",
            evidence_refs=(KEY,),
        )],
    )
    return repo.review_analysis(
        analysis.analysis_id, decision=AnalysisReviewDecision.accepted,
        reviewer="analyst",
    )


@pytest.fixture()
def two_tasks(tmp_path):
    repo_a, snap_a = _task_repo(tmp_path, "A")
    repo_b, snap_b = _task_repo(tmp_path, "B")

    accepted_a = _accepted_with_claims(repo_a, snap_a)
    accepted_b = _accepted_with_claims(repo_b, snap_b)
    # Same evidence_key, similar titles, different identities.
    event_a = repo_a.create_event("Same-looking event", created_by="a")
    repo_a.link_event_evidence(event_a.event_id, KEY, linked_by="a")
    event_b = repo_b.create_event("Same-looking event", created_by="b")
    repo_b.link_event_evidence(event_b.event_id, KEY, linked_by="b")
    return repo_a, repo_b, accepted_a, accepted_b, event_a, event_b


def test_analysis_and_claim_ids_never_cross_tasks(two_tasks):
    repo_a, repo_b, accepted_a, accepted_b, _, _ = two_tasks
    assert accepted_a.analysis_id != accepted_b.analysis_id

    # Same evidence_key, but each task sees only its own analyses.
    assert [a.analysis_id for a in repo_a.list_analyses(KEY)] == [accepted_a.analysis_id]
    assert [a.analysis_id for a in repo_b.list_analyses(KEY)] == [accepted_b.analysis_id]

    # Strict reader is task-scoped by construction (C10 §14).
    reader_b = InvestigationGraphReader(repo_b.db_path, "B")
    assert reader_b.get_analysis(accepted_a.analysis_id) is None
    assert reader_b.get_analysis(accepted_b.analysis_id) is not None

    # Claims never merge across tasks even with identical claim_text.
    claims_a = repo_a.list_claims(accepted_a.analysis_id)
    claims_b = repo_b.list_claims(accepted_b.analysis_id)
    assert claims_a[0].claim_id != claims_b[0].claim_id


def test_review_of_foreign_analysis_is_rejected(two_tasks):
    repo_a, repo_b, accepted_a, accepted_b, _, _ = two_tasks
    # accepted_b is already terminal in B; accepted_a is foreign to B and
    # must surface as not-found, never as a reviewable row.
    with pytest.raises(EvidenceNotFoundError):
        repo_b.review_analysis(
            accepted_a.analysis_id,
            decision=AnalysisReviewDecision.accepted,
            reviewer="b",
        )
    with pytest.raises(AnalysisReviewConflictError):
        repo_b.review_analysis(
            accepted_b.analysis_id,
            decision=AnalysisReviewDecision.accepted,
            reviewer="b",
        )


def test_event_link_and_refresh_stay_task_scoped(two_tasks):
    repo_a, repo_b, _, _, event_a, event_b = two_tasks
    # Foreign event id → not found in B (no global search by event_id):
    # write paths raise; pure reads return nothing for the foreign id.
    with pytest.raises(EvidenceNotFoundError):
        repo_b.link_event_evidence(event_a.event_id, KEY, linked_by="b")
    assert repo_b.list_event_versions(event_a.event_id) == []
    assert repo_b.list_event_evidence(event_a.event_id) == []
    with pytest.raises(EvidenceNotFoundError):
        repo_b.create_event_refresh(event_a.event_id, requested_by="b")

    # Duplicate link INSIDE a task still conflicts (409 semantics preserved).
    with pytest.raises(InvestigationEventConflictError):
        repo_a.link_event_evidence(event_a.event_id, KEY, linked_by="a")

    # Each task lists exactly its own events and links.
    assert [e.event_id for e in repo_a.list_events()] == [event_a.event_id]
    assert [e.event_id for e in repo_b.list_events()] == [event_b.event_id]


def test_graph_overlay_projection_is_isolated(two_tasks):
    repo_a, repo_b, _, _, event_a, event_b = two_tasks
    overlay_a = InvestigationGraphReader(repo_a.db_path, "A").read()
    overlay_b = InvestigationGraphReader(repo_b.db_path, "B").read()

    assert [e.event_id for e in overlay_a.events] == [event_a.event_id]
    assert [e.event_id for e in overlay_b.events] == [event_b.event_id]
    assert overlay_a.events[0].event_id != overlay_b.events[0].event_id
    # Identical claim text, distinct claim identities per task.
    assert overlay_a.claims[0].claim_id != overlay_b.claims[0].claim_id


def test_dirty_propagation_does_not_leak_across_tasks(two_tasks):
    repo_a, repo_b, _, _, event_a, event_b = two_tasks
    from httpserver.services.investigation import ClaimCandidate
    from httpserver.services.evidence import ResolvedEvidence

    a_updated_before = repo_a.get_event(event_a.event_id).updated_at

    # A NEW acceptance lands in B after both events exist.
    snap_b2 = repo_b.capture_if_absent(ResolvedEvidence(
        task_id="B", evidence_key=KEY, evidence_type="file",
        normalized_path="/case/a.txt", source_db=str(repo_b.db_path.parent / "files.db"),
    ))
    analysis = repo_b.create_analysis(snap_b2, prompt_version=PROMPT_V3)
    repo_b.transition(analysis.analysis_id, SecondaryAnalysisStatus.running)
    repo_b.complete_analysis_for_review(
        analysis.analysis_id, description="d", summary="s2", model="m",
        candidates=[ClaimCandidate(claim_type="FACT", claim_text="b-only", evidence_refs=(KEY,))],
    )
    repo_b.review_analysis(
        analysis.analysis_id, decision=AnalysisReviewDecision.accepted, reviewer="b"
    )

    # Only B's event was touched; A's store saw no write at all.
    assert repo_b.get_event(event_b.event_id).needs_refresh is True
    a_event = repo_a.get_event(event_a.event_id)
    assert a_event.updated_at == a_updated_before
