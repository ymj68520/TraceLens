"""C7b propagation tests: accepted Analysis → Investigation Event
needs_refresh (invariants P1-P10)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from httpserver.services.evidence import ResolvedEvidence
from httpserver.services.investigation import (
    AnalysisReviewConflictError,
    AnalysisReviewDecision,
    InvestigationRepository,
    SecondaryAnalysisStatus,
)


PROMPT_V1 = "investigation-evidence-analysis:v1"
PROMPT_V2 = "investigation-evidence-analysis:v2"
PROMPT_V3 = "investigation-evidence-analysis:v3"
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
    conn.execute(
        "INSERT INTO files (path,llm_description,size) VALUES (?,?,?)",
        ("/case/a.txt", "d", 1),
    )
    conn.commit()
    conn.close()


def _task_repo(tmp_path: Path, task_id: str):
    tmp_path.mkdir(parents=True, exist_ok=True)
    files_db = str(tmp_path / f"{task_id}_files.db")
    investigation_db = str(tmp_path / f"{task_id}_investigation.db")
    _make_files_db(files_db)
    repo = InvestigationRepository(investigation_db, task_id)
    snapshot = repo.capture_if_absent(ResolvedEvidence(
        task_id=task_id, evidence_key=KEY, evidence_type="file",
        normalized_path="/case/a.txt", source_db=files_db,
    ))
    return repo, snapshot


def _accepted(repo, snapshot, *, prompt=PROMPT_V3, decision=AnalysisReviewDecision.accepted):
    """analysis → review_pending → review decision (structured or legacy)."""
    analysis = repo.create_analysis(snapshot, prompt_version=prompt)
    repo.transition(analysis.analysis_id, SecondaryAnalysisStatus.running)
    if prompt == PROMPT_V3:
        repo.complete_analysis_for_review(
            analysis.analysis_id,
            description="d", summary="s", model="m", candidates=[],
        )
    else:
        repo.transition(
            analysis.analysis_id,
            SecondaryAnalysisStatus.review_pending,
            description="d", summary="s", model="m",
        )
    return repo.review_analysis(
        analysis.analysis_id, decision=decision, reviewer="analyst"
    )


def _review_pending(repo, snapshot, *, prompt=PROMPT_V3):
    analysis = repo.create_analysis(snapshot, prompt_version=prompt)
    repo.transition(analysis.analysis_id, SecondaryAnalysisStatus.running)
    if prompt == PROMPT_V3:
        repo.complete_analysis_for_review(
            analysis.analysis_id,
            description="d", summary="s", model="m", candidates=[],
        )
    else:
        repo.transition(
            analysis.analysis_id,
            SecondaryAnalysisStatus.review_pending,
            description="d", summary="s", model="m",
        )
    return repo.get_analysis(analysis.analysis_id)


# ---------------------------------------------------------------------------
# P2/P4: accepted marks exactly the explicitly linked events
# ---------------------------------------------------------------------------

def test_P2_accepted_marks_only_linked_events(tmp_path):
    repo, snapshot = _task_repo(tmp_path, "A")
    linked = repo.create_event("E1", created_by="a")
    unrelated = repo.create_event("E2", created_by="a")
    repo.link_event_evidence(linked.event_id, KEY)
    clean_before = repo.get_event(unrelated.event_id).updated_at

    result = _accepted(repo, snapshot)
    assert result.status == SecondaryAnalysisStatus.accepted

    dirty = repo.get_event(linked.event_id)
    assert dirty.needs_refresh is True
    assert dirty.updated_at != dirty.created_at  # bumped

    clean = repo.get_event(unrelated.event_id)
    assert clean.needs_refresh is False
    assert clean.updated_at == clean_before

    # Consistency: propagation scope == authoritative reverse lookup.
    assert [e.event_id for e in repo.list_events_for_evidence(KEY)] == [linked.event_id]
    assert [e.event_id for e in repo.list_events(needs_refresh=True)] == [linked.event_id]


def test_P3_rejected_and_invalid_do_not_propagate(tmp_path):
    for decision in (AnalysisReviewDecision.rejected, AnalysisReviewDecision.invalid):
        repo, snapshot = _task_repo(tmp_path / decision.value, "A")
        event = repo.create_event("E", created_by="a")
        repo.link_event_evidence(event.event_id, KEY)
        result = _accepted(repo, snapshot, decision=decision)
        assert result.status == SecondaryAnalysisStatus(decision.value)
        assert repo.get_event(event.event_id).needs_refresh is False


def test_P2_accepted_with_zero_links_is_noop(tmp_path):
    repo, snapshot = _task_repo(tmp_path, "A")
    result = _accepted(repo, snapshot)  # no events at all
    assert result.status == SecondaryAnalysisStatus.accepted
    assert repo.list_events(needs_refresh=True) == []


# ---------------------------------------------------------------------------
# P6: idempotent within a dirty cycle
# ---------------------------------------------------------------------------

def test_P6_repeat_accepted_keeps_updated_at(tmp_path):
    repo, snapshot = _task_repo(tmp_path, "A")
    event = repo.create_event("E", created_by="a")
    repo.link_event_evidence(event.event_id, KEY)
    _accepted(repo, snapshot)
    dirty_at = repo.get_event(event.event_id).updated_at
    assert repo.get_event(event.event_id).needs_refresh is True

    second = _review_pending(repo, snapshot)  # new analysis version
    repo.review_analysis(
        second.analysis_id, decision=AnalysisReviewDecision.accepted, reviewer="a2"
    )
    after = repo.get_event(event.event_id)
    assert after.needs_refresh is True
    assert after.updated_at == dirty_at  # no bump within the dirty cycle


# ---------------------------------------------------------------------------
# P10: same-transaction atomicity
# ---------------------------------------------------------------------------

def test_P10_review_propagation_failure_rolls_back_everything(tmp_path, monkeypatch):
    repo, snapshot = _task_repo(tmp_path, "A")
    event = repo.create_event("E", created_by="a")
    repo.link_event_evidence(event.event_id, KEY)
    analysis = _review_pending(repo, snapshot)

    def fail(repo_self, conn, evidence_key, now):
        raise RuntimeError("injected propagation failure")

    monkeypatch.setattr(
        InvestigationRepository, "_mark_related_events_dirty", fail
    )
    with pytest.raises(RuntimeError, match="injected"):
        repo.review_analysis(
            analysis.analysis_id,
            decision=AnalysisReviewDecision.accepted,
            reviewer="x",
        )

    # Reopen from disk: no half-applied state anywhere.
    reopened = InvestigationRepository(repo.db_path, "A")
    assert reopened.get_analysis(analysis.analysis_id).status \
        == SecondaryAnalysisStatus.review_pending
    assert reopened.get_analysis(analysis.analysis_id).decided_at is None
    assert reopened.get_event(event.event_id).needs_refresh is False


def test_P10_link_propagation_failure_rolls_back_link(tmp_path, monkeypatch):
    repo, snapshot = _task_repo(tmp_path, "A")
    _accepted(repo, snapshot)  # evidence already accepted
    event = repo.create_event("E", created_by="a")

    def fail(repo_self, conn, event_id, evidence_key, now):
        raise RuntimeError("injected link failure")

    monkeypatch.setattr(
        InvestigationRepository, "_mark_event_dirty_if_evidence_accepted", fail
    )
    with pytest.raises(RuntimeError, match="injected"):
        repo.link_event_evidence(event.event_id, KEY)

    reopened = InvestigationRepository(repo.db_path, "A")
    assert reopened.list_event_evidence(event.event_id) == []  # no link row
    assert reopened.get_event(event.event_id).needs_refresh is False


# ---------------------------------------------------------------------------
# P5: link established after acceptance
# ---------------------------------------------------------------------------

def test_P5_link_after_accept_marks_event_dirty(tmp_path):
    repo, snapshot = _task_repo(tmp_path, "A")
    _accepted(repo, snapshot)  # accepted BEFORE the relation exists
    event = repo.create_event("E", created_by="a")

    assert repo.get_event(event.event_id).needs_refresh is False
    repo.link_event_evidence(event.event_id, KEY)
    dirty = repo.get_event(event.event_id)
    assert dirty.needs_refresh is True
    assert dirty.updated_at != dirty.created_at


def test_P5_link_without_accepted_analysis_stays_clean(tmp_path):
    repo, snapshot = _task_repo(tmp_path, "A")
    _review_pending(repo, snapshot)  # accepted does NOT exist yet
    event = repo.create_event("E", created_by="a")
    repo.link_event_evidence(event.event_id, KEY)
    assert repo.get_event(event.event_id).needs_refresh is False


# ---------------------------------------------------------------------------
# P1: transition() cannot bypass review_analysis
# ---------------------------------------------------------------------------

def test_P1_transition_to_review_terminal_is_rejected(tmp_path):
    repo, snapshot = _task_repo(tmp_path, "A")
    analysis = _review_pending(repo, snapshot)
    for target in (
        SecondaryAnalysisStatus.accepted,
        SecondaryAnalysisStatus.rejected,
        SecondaryAnalysisStatus.invalid,
    ):
        with pytest.raises(ValueError, match="requires review_analysis"):
            repo.transition(analysis.analysis_id, target, decided_by="x")
    assert repo.get_analysis(analysis.analysis_id).status \
        == SecondaryAnalysisStatus.review_pending


# ---------------------------------------------------------------------------
# legacy contract + task isolation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("prompt", [PROMPT_V1, PROMPT_V2])
def test_legacy_accepted_also_propagates(tmp_path, prompt):
    repo, snapshot = _task_repo(tmp_path / prompt, "A")
    event = repo.create_event("E", created_by="a")
    repo.link_event_evidence(event.event_id, KEY)
    result = _accepted(repo, snapshot, prompt=prompt)
    assert result.status == SecondaryAnalysisStatus.accepted
    assert repo.get_event(event.event_id).needs_refresh is True


def test_task_isolation_same_canonical_key(tmp_path):
    repo_a, snapshot_a = _task_repo(tmp_path / "A", "A")
    repo_b, snapshot_b = _task_repo(tmp_path / "B", "B")
    event_a = repo_a.create_event("EA", created_by="a")
    event_b = repo_b.create_event("EB", created_by="a")
    repo_a.link_event_evidence(event_a.event_id, KEY)
    repo_b.link_event_evidence(event_b.event_id, KEY)

    _accepted(repo_a, snapshot_a)

    assert repo_a.get_event(event_a.event_id).needs_refresh is True
    assert repo_b.get_event(event_b.event_id).needs_refresh is False
    assert repo_b.list_events(needs_refresh=True) == []


# ---------------------------------------------------------------------------
# P7: narrative untouched by propagation
# ---------------------------------------------------------------------------

def test_P7_propagation_preserves_narrative_and_versions(tmp_path):
    repo, snapshot = _task_repo(tmp_path, "A")
    event = repo.create_event("Título", summary="resumen", created_by="a")
    repo.link_event_evidence(event.event_id, KEY)
    before_versions = repo.list_event_versions(event.event_id)

    _accepted(repo, snapshot)

    after = repo.get_event(event.event_id)
    assert after.title == "Título"
    assert after.summary == "resumen"
    assert after.current_version == 1
    assert repo.list_event_versions(event.event_id) == before_versions
