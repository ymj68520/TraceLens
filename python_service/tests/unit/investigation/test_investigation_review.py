"""C6 repository and service analyst review tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from httpserver.services.evidence import (
    EvidenceNotFoundError,
    EvidenceStoreError,
    ResolvedEvidence,
)
from httpserver.services.investigation import (
    AnalysisGroundingStatus,
    AnalysisReviewConflictError,
    AnalysisReviewDecision,
    ClaimCandidate,
    ClaimType,
    InvestigationRepository,
    InvestigationReviewService,
    SecondaryAnalysisStatus,
)


PROMPT_V2 = "investigation-evidence-analysis:v2"
PROMPT_V3 = "investigation-evidence-analysis:v3"


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


def _analysis(
    tmp_path: Path,
    prompt_version: str | None = PROMPT_V3,
    status: SecondaryAnalysisStatus = SecondaryAnalysisStatus.review_pending,
):
    tmp_path.mkdir(parents=True, exist_ok=True)
    files_db = str(tmp_path / "files.db")
    investigation_db = str(tmp_path / "investigation.db")
    _make_files_db(files_db)
    repo = InvestigationRepository(investigation_db, "A")
    snapshot = repo.capture_if_absent(ResolvedEvidence(
        task_id="A", evidence_key="file:/case/a.txt", evidence_type="file",
        normalized_path="/case/a.txt", source_db=files_db,
    ))
    analysis = repo.create_analysis(snapshot, prompt_version=prompt_version)
    if status in {
        SecondaryAnalysisStatus.running,
        SecondaryAnalysisStatus.review_pending,
        SecondaryAnalysisStatus.accepted,
        SecondaryAnalysisStatus.rejected,
        SecondaryAnalysisStatus.invalid,
        SecondaryAnalysisStatus.failed,
    }:
        repo.transition(analysis.analysis_id, SecondaryAnalysisStatus.running)
    if status in {
        SecondaryAnalysisStatus.review_pending,
        SecondaryAnalysisStatus.accepted,
        SecondaryAnalysisStatus.rejected,
        SecondaryAnalysisStatus.invalid,
    }:
        if prompt_version == PROMPT_V2:
            repo.transition(
                analysis.analysis_id,
                SecondaryAnalysisStatus.review_pending,
                description="desc", summary="sum", model="m",
            )
        else:
            repo.transition(
                analysis.analysis_id,
                SecondaryAnalysisStatus.review_pending,
                description="desc", summary="sum", model="m",
            )
    if status in {
        SecondaryAnalysisStatus.accepted,
        SecondaryAnalysisStatus.rejected,
        SecondaryAnalysisStatus.invalid,
    }:
        repo.transition(analysis.analysis_id, status, decided_by="prior")
    elif status == SecondaryAnalysisStatus.failed:
        repo.transition(
            analysis.analysis_id,
            status,
            error_code="x",
            error_message="x",
        )
    return investigation_db, repo, repo.get_analysis(analysis.analysis_id)


def _structured_review_pending(tmp_path: Path):
    idb, repo, analysis = _analysis(
        tmp_path,
        status=SecondaryAnalysisStatus.running,
    )
    repo.complete_analysis_for_review(
        analysis.analysis_id,
        description="desc",
        summary="sum",
        model="m",
        candidates=[ClaimCandidate(
            claim_type=ClaimType.FACT,
            claim_text="claim",
            evidence_refs=("file:/case/a.txt",),
        )],
    )
    return idb, repo, repo.get_analysis(analysis.analysis_id)


def test_review_structured_accepts_and_preserves_complete_payload(tmp_path):
    _, repo, analysis = _structured_review_pending(tmp_path)
    before = repo.get_analysis(analysis.analysis_id)
    before_claims = repo.list_claims(analysis.analysis_id)
    result = repo.review_analysis(
        analysis.analysis_id,
        decision=AnalysisReviewDecision.accepted,
        reviewer="analyst-1",
        reason="verified",
    )
    assert result.status == SecondaryAnalysisStatus.accepted
    assert result.decided_at is not None
    assert result.decided_by == "analyst-1"
    assert result.decision_reason == "verified"
    for field in (
        "analysis_id", "task_id", "evidence_key", "version", "input_hash",
        "input_envelope_json", "prompt_version", "description", "summary",
        "model", "grounding_status", "created_at", "started_at", "review_pending_at",
    ):
        assert getattr(result, field) == getattr(before, field)
    assert repo.list_claims(analysis.analysis_id) == before_claims


def test_review_structured_allows_rejected_and_invalid(tmp_path):
    for decision in (AnalysisReviewDecision.rejected, AnalysisReviewDecision.invalid):
        _, repo, analysis = _structured_review_pending(tmp_path / decision.value)
        result = repo.review_analysis(
            analysis.analysis_id, decision=decision, reviewer="analyst"
        )
        assert result.status == SecondaryAnalysisStatus(decision.value)
        assert result.grounding_status == AnalysisGroundingStatus.VALID


def test_review_legacy_v2_allows_null_grounding(tmp_path):
    _, repo, analysis = _analysis(tmp_path, PROMPT_V2)
    result = repo.review_analysis(
        analysis.analysis_id,
        decision=AnalysisReviewDecision.rejected,
        reviewer="legacy-reviewer",
    )
    assert result.status == SecondaryAnalysisStatus.rejected
    assert result.grounding_status is None


@pytest.mark.parametrize("status", [
    SecondaryAnalysisStatus.queued,
    SecondaryAnalysisStatus.running,
    SecondaryAnalysisStatus.accepted,
    SecondaryAnalysisStatus.rejected,
    SecondaryAnalysisStatus.invalid,
    SecondaryAnalysisStatus.failed,
])
def test_review_non_pending_is_conflict(tmp_path, status):
    _, repo, analysis = _analysis(tmp_path / status.value, status=status)
    with pytest.raises(AnalysisReviewConflictError):
        repo.review_analysis(
            analysis.analysis_id,
            decision=AnalysisReviewDecision.accepted,
            reviewer="analyst",
        )


def test_review_structured_integrity_failure_is_store_error_and_unchanged(tmp_path):
    _, repo, analysis = _analysis(tmp_path)
    before = repo.get_analysis(analysis.analysis_id)
    with pytest.raises(EvidenceStoreError, match="grounding"):
        repo.review_analysis(
            analysis.analysis_id,
            decision=AnalysisReviewDecision.accepted,
            reviewer="analyst",
        )
    after = repo.get_analysis(analysis.analysis_id)
    assert after.status == SecondaryAnalysisStatus.review_pending
    assert after.decided_at == before.decided_at is None


@pytest.mark.asyncio
async def test_review_service_exact_task_scope_and_missing_store(tmp_path):
    backend = Mock()
    backend.get_task = AsyncMock(return_value={
        "id": "B",
        "output_files_db": str(tmp_path / "b" / "files.db"),
    })
    service = InvestigationReviewService(backend)
    with pytest.raises(EvidenceNotFoundError):
        await service.review(
            "A", "analysis-id", decision=AnalysisReviewDecision.accepted, reviewer="x"
        )
    backend.get_task.assert_awaited_once_with("A")


def test_review_uses_same_write_transaction_for_integrity_and_transition(tmp_path, monkeypatch):
    _, repo, analysis = _structured_review_pending(tmp_path)
    original = repo._transition_with_conn
    observed = {}

    def wrapped(conn, *args, **kwargs):
        observed["in_transaction"] = conn.in_transaction
        return original(conn, *args, **kwargs)

    monkeypatch.setattr(repo, "_transition_with_conn", wrapped)
    repo.review_analysis(
        analysis.analysis_id,
        decision=AnalysisReviewDecision.accepted,
        reviewer="analyst",
    )
    assert observed["in_transaction"] is True


def test_review_exact_task_scope_rejects_other_task_in_same_db(tmp_path):
    _, repo, analysis = _structured_review_pending(tmp_path)
    other_task_repo = InvestigationRepository(repo.db_path, "B")
    with pytest.raises(EvidenceNotFoundError):
        other_task_repo.review_analysis(
            analysis.analysis_id,
            decision=AnalysisReviewDecision.accepted,
            reviewer="analyst",
        )
    assert repo.get_analysis(analysis.analysis_id).status == SecondaryAnalysisStatus.review_pending


@pytest.mark.asyncio
async def test_review_service_maps_corrupt_store_to_store_error(tmp_path):
    db_dir = tmp_path / "task"
    db_dir.mkdir()
    db_path = db_dir / "investigation.db"
    db_path.write_bytes(b"not sqlite")
    backend = Mock()
    backend.get_task = AsyncMock(return_value={
        "id": "A",
        "output_files_db": str(db_dir / "files.db"),
    })
    service = InvestigationReviewService(backend)
    with pytest.raises(EvidenceStoreError):
        await service.review(
            "A", "analysis-id", decision=AnalysisReviewDecision.accepted, reviewer="x"
        )


def test_review_unknown_contract_is_store_error(tmp_path):
    _, repo, analysis = _analysis(tmp_path, prompt_version=None)
    with pytest.raises(EvidenceStoreError, match="output contract"):
        repo.review_analysis(
            analysis.analysis_id, decision=AnalysisReviewDecision.accepted, reviewer="x"
        )
