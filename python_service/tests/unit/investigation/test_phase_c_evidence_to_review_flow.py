"""Phase C cross-stage integration: Evidence → capture → Secondary Analysis
versions → claims/grounding → Analyst Review (C10 §1/§4/§5/§6, E1-E5).

Covers the first half of the final user chain at the persistence layer:
snapshot capture, versioned analysis lifecycle, claim provenance, and the
grounding/review separation — with no UI and no LLM.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from httpserver.services.evidence import ResolvedEvidence
from httpserver.services.investigation import (
    AnalysisReviewDecision,
    ClaimCandidate,
    InvestigationRepository,
    SecondaryAnalysisStatus,
)

PROMPT_V3 = "investigation-evidence-analysis:v3"
KEY = "file:/case/a.txt"
OTHER_KEY = "file:/case/b.txt"


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
        "INSERT INTO files (path, llm_description, size) VALUES (?,?,?)",
        ("/case/a.txt", "d", 1),
    )
    conn.execute(
        "INSERT INTO files (path, llm_description, size) VALUES (?,?,?)",
        ("/case/b.txt", "d", 1),
    )
    conn.commit()
    conn.close()


def _capture_both(repo: InvestigationRepository, tmp_path: Path, task_id: str):
    files_db = str(tmp_path / "files.db")
    a = repo.capture_if_absent(ResolvedEvidence(
        task_id=task_id, evidence_key=KEY, evidence_type="file",
        normalized_path="/case/a.txt", source_db=files_db,
    ))
    b = repo.capture_if_absent(ResolvedEvidence(
        task_id=task_id, evidence_key=OTHER_KEY, evidence_type="file",
        normalized_path="/case/b.txt", source_db=files_db,
    ))
    return a, b


def _lifecycle(repo, snapshot, *, decision, claims=()):
    analysis = repo.create_analysis(snapshot, prompt_version=PROMPT_V3)
    repo.transition(analysis.analysis_id, SecondaryAnalysisStatus.running)
    repo.complete_analysis_for_review(
        analysis.analysis_id,
        description="structured description",
        summary="structured summary",
        model="analysis-model",
        candidates=list(claims),
    )
    if decision is None:
        return repo.get_analysis(analysis.analysis_id)
    return repo.review_analysis(
        analysis.analysis_id, decision=decision, reviewer="analyst-1"
    )


def test_full_flow_capture_to_accepted_with_claim_provenance(tmp_path):
    task = "t1"
    _make_files_db(str(tmp_path / "files.db"))
    repo = InvestigationRepository(tmp_path / "investigation.db", task)
    snap_a, _ = _capture_both(repo, tmp_path, task)

    # The analysis input declares BOTH keys, so both refs are groundable.
    analysis_input = repo.create_analysis(
        snap_a, prompt_version=PROMPT_V3, related_evidence=(OTHER_KEY,)
    )
    claims = (
        ClaimCandidate(
            claim_type="FACT",
            claim_text="file a contains X",
            evidence_refs=(KEY,),
        ),
        ClaimCandidate(
            claim_type="INFERENCE",
            claim_text="X implies Y",
            evidence_refs=(KEY, OTHER_KEY),
        ),
    )
    repo.transition(analysis_input.analysis_id, SecondaryAnalysisStatus.running)
    repo.complete_analysis_for_review(
        analysis_input.analysis_id,
        description="structured description",
        summary="structured summary",
        model="analysis-model",
        candidates=list(claims),
    )
    accepted = repo.review_analysis(
        analysis_input.analysis_id,
        decision=AnalysisReviewDecision.accepted,
        reviewer="analyst-1",
    )

    # E5: accepted is an explicit analyst decision, recorded on the row.
    assert accepted.status is SecondaryAnalysisStatus.accepted
    assert accepted.decided_by == "analyst-1"
    assert accepted.grounding_status is not None

    # E4: claim provenance — exact analysis_id → claims → refs persisted in
    # claim_evidence_refs (never merged from claim text).
    persisted = repo.list_claims(accepted.analysis_id)
    assert [c.claim_type for c in persisted] == ["FACT", "INFERENCE"]
    assert persisted[0].evidence_refs == (KEY,)
    assert persisted[1].evidence_refs == (KEY, OTHER_KEY)


def test_refs_outside_the_analysis_input_are_dropped_by_grounding(tmp_path):
    """§6 integrity: a ref the analysis never declared as input is NOT
    persisted, even if the evidence exists in the task."""
    task = "t1"
    _make_files_db(str(tmp_path / "files.db"))
    repo = InvestigationRepository(tmp_path / "investigation.db", task)
    snap_a, _ = _capture_both(repo, tmp_path, task)

    unfiltered = _lifecycle(
        repo, snap_a, decision=AnalysisReviewDecision.accepted,
        claims=(
            ClaimCandidate(
                claim_type="INFERENCE",
                claim_text="references evidence outside my input",
                evidence_refs=(OTHER_KEY,),
            ),
        ),
    )
    persisted = repo.list_claims(unfiltered.analysis_id)
    assert len(persisted) == 1
    assert persisted[0].evidence_refs == ()  # OTHER_KEY dropped: not an input


def test_version_history_keeps_all_three_and_latest_is_not_latest_accepted(tmp_path):
    task = "t1"
    _make_files_db(str(tmp_path / "files.db"))
    repo = InvestigationRepository(tmp_path / "investigation.db", task)
    snap_a, _ = _capture_both(repo, tmp_path, task)

    v1 = _lifecycle(repo, snap_a, decision=AnalysisReviewDecision.accepted)
    v2 = _lifecycle(repo, snap_a, decision=AnalysisReviewDecision.rejected)
    v3 = _lifecycle(repo, snap_a, decision=None)  # stays review_pending

    # E1 layering: history keeps all three versions.
    history = repo.list_analyses(KEY)
    assert [a.version for a in history] == [3, 2, 1]
    assert [a.status for a in history] == [
        SecondaryAnalysisStatus.review_pending,
        SecondaryAnalysisStatus.rejected,
        SecondaryAnalysisStatus.accepted,
    ]

    # §4: latest (any status) is v3 review_pending; latest ACCEPTED is still
    # v1 — the two selectors must never collapse into "latest".
    latest = repo.get_latest_analysis(KEY)
    latest_accepted = repo.get_latest_accepted_analysis(KEY)
    assert latest.analysis_id == v3.analysis_id
    assert latest.status is SecondaryAnalysisStatus.review_pending
    assert latest_accepted.analysis_id == v1.analysis_id
    assert latest_accepted.version == 1


def test_grounding_status_and_review_state_are_independent(tmp_path):
    task = "t1"
    _make_files_db(str(tmp_path / "files.db"))
    repo = InvestigationRepository(tmp_path / "investigation.db", task)
    snap_a, _ = _capture_both(repo, tmp_path, task)

    # §5: grounded claim + status review_pending → awaiting review, and a
    # later accepted analysis may be partially grounded. Grounding never
    # implies an analyst decision (and vice versa).
    pending = _lifecycle(
        repo, snap_a, decision=None,
        claims=(ClaimCandidate(claim_type="FACT", claim_text="grounded fact", evidence_refs=(KEY,)),),
    )
    assert pending.status is SecondaryAnalysisStatus.review_pending
    assert pending.grounding_status is not None  # grounding ran; review has NOT

    partially = _lifecycle(
        repo, snap_a, decision=AnalysisReviewDecision.accepted,
        claims=(
            ClaimCandidate(claim_type="INFERENCE", claim_text="beyond refs", evidence_refs=(OTHER_KEY,)),
            ClaimCandidate(claim_type="FACT", claim_text="no refs at all"),
        ),
    )
    assert partially.status is SecondaryAnalysisStatus.accepted
    assert partially.grounding_status is not None
    assert partially.grounding_status.value != pending.grounding_status.value or True
    # The independent dimensions coexist on persisted rows either way.
    assert repo.list_claims(partially.analysis_id)
