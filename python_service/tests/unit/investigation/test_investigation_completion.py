"""C5b atomic completion and legacy/structured execution tests."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from httpserver.services.evidence import ResolvedEvidence
from httpserver.services.investigation import (
    AnalysisGroundingStatus,
    ClaimCandidate,
    ClaimType,
    InvestigationRepository,
    SecondaryAnalysisStatus,
)
from httpserver.services.investigation.execution import SecondaryAnalysisExecutor


def _make_files_db(path):
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
        ("/case/report.docx", "PRIMARY", 7),
    )
    conn.commit()
    conn.close()


def _running(tmp_path, prompt_version="investigation-evidence-analysis:v3", *, running=True):
    files_db = str(tmp_path / "files.db")
    investigation_db = str(tmp_path / "investigation.db")
    _make_files_db(files_db)
    repo = InvestigationRepository(investigation_db, "A")
    snapshot = repo.capture_if_absent(ResolvedEvidence(
        task_id="A", evidence_key="file:/case/report.docx", evidence_type="file",
        normalized_path="/case/report.docx", source_db=files_db,
    ))
    analysis = repo.create_analysis(snapshot, prompt_version=prompt_version)
    if running:
        repo.transition(analysis.analysis_id, SecondaryAnalysisStatus.running)
    return investigation_db, repo, analysis


class _FakeCpp:
    def __init__(self, task_dir):
        self._task_dir = Path(task_dir)

    async def get_task(self, task_id):
        return {
            "id": task_id,
            "output_files_db": str(self._task_dir / "files.db"),
            "output_events_db": str(self._task_dir / "events.db"),
        }


def _candidate(text="claim", refs=("file:/case/report.docx",)):
    return ClaimCandidate(claim_type=ClaimType.FACT, claim_text=text, evidence_refs=refs)


def test_atomic_completion_writes_all_result_data(tmp_path):
    idb, repo, analysis = _running(tmp_path)
    result = repo.complete_analysis_for_review(
        analysis.analysis_id,
        description="description",
        summary="summary",
        model="model-v3",
        candidates=[_candidate()],
    )
    assert result.status == SecondaryAnalysisStatus.review_pending
    assert result.description == "description"
    assert result.summary == "summary"
    assert result.model == "model-v3"
    assert result.grounding_status == AnalysisGroundingStatus.VALID
    assert len(repo.list_claims(analysis.analysis_id)) == 1


def test_atomic_completion_empty_claims_is_valid_and_write_once(tmp_path):
    idb, repo, analysis = _running(tmp_path)
    result = repo.complete_analysis_for_review(
        analysis.analysis_id,
        description="description", summary="summary", model="m", candidates=[],
    )
    assert result.grounding_status == AnalysisGroundingStatus.VALID
    assert repo.list_claims(analysis.analysis_id) == []
    with pytest.raises(ValueError):
        repo.complete_analysis_for_review(
            analysis.analysis_id,
            description="other", summary="other", model="other", candidates=[],
        )
    unchanged = repo.get_analysis(analysis.analysis_id)
    assert unchanged.description == "description"
    assert unchanged.status == SecondaryAnalysisStatus.review_pending


def test_completion_rejects_persist_claims_empty_marker(tmp_path):
    idb, repo, analysis = _running(tmp_path)
    repo.persist_claims(analysis.analysis_id, [])
    before = repo.get_analysis(analysis.analysis_id)
    with pytest.raises(ValueError, match="persisted result data|grounding"):
        repo.complete_analysis_for_review(
            analysis.analysis_id,
            description="d", summary="s", model="m", candidates=[],
        )
    after = repo.get_analysis(analysis.analysis_id)
    assert after.status == SecondaryAnalysisStatus.running
    assert after.description == before.description is None
    assert repo.list_claims(analysis.analysis_id) == []


def test_completion_rejects_existing_output(tmp_path):
    idb, repo, analysis = _running(tmp_path)
    conn = sqlite3.connect(idb)
    conn.execute(
        "UPDATE secondary_analyses SET description='old' WHERE analysis_id=?",
        [analysis.analysis_id],
    )
    conn.commit()
    conn.close()
    with pytest.raises(ValueError, match="persisted result"):
        repo.complete_analysis_for_review(
            analysis.analysis_id,
            description="new", summary="s", model="m", candidates=[],
        )
    assert repo.get_analysis(analysis.analysis_id).description == "old"


def test_completion_requires_running(tmp_path):
    idb, repo, analysis = _running(tmp_path)
    repo.transition(analysis.analysis_id, SecondaryAnalysisStatus.review_pending)
    with pytest.raises(ValueError, match="running"):
        repo.complete_analysis_for_review(
            analysis.analysis_id,
            description="d", summary="s", model="m", candidates=[],
        )


def test_completion_rollback_after_claim_insert(tmp_path, monkeypatch):
    idb, repo, analysis = _running(tmp_path)
    original = repo._validate_and_insert_claims

    def fail_after_insert(self_repo, conn, analysis_id, row, candidates, *, now):
        original(conn, analysis_id, row, candidates, now=now)
        raise RuntimeError("injected completion failure")

    monkeypatch.setattr(InvestigationRepository, "_validate_and_insert_claims", fail_after_insert)
    with pytest.raises(RuntimeError, match="injected"):
        repo.complete_analysis_for_review(
            analysis.analysis_id,
            description="d", summary="s", model="m", candidates=[_candidate()],
        )
    restored = repo.get_analysis(analysis.analysis_id)
    assert restored.status == SecondaryAnalysisStatus.running
    assert restored.description is None
    assert restored.grounding_status is None
    assert repo.list_claims(analysis.analysis_id) == []


@pytest.mark.asyncio
async def test_structured_executor_success_uses_atomic_completion(tmp_path):
    idb, repo, analysis = _running(tmp_path, running=False)
    llm = Mock()
    llm.chat_completion = AsyncMock(return_value={
        "content": '{"description":"d","summary":"s","claims":[{"claim_type":"FACT","claim_text":"c","evidence_refs":["file:/case/report.docx"]}]}',
        "model": "structured-model",
        "tokens_used": 2,
    })
    executor = SecondaryAnalysisExecutor(_FakeCpp(tmp_path), llm, Mock())
    await executor._execute(analysis.analysis_id, "A", Path(idb))
    result = repo.get_analysis(analysis.analysis_id)
    assert result.status == SecondaryAnalysisStatus.review_pending
    assert result.grounding_status == AnalysisGroundingStatus.VALID
    assert len(repo.list_claims(analysis.analysis_id)) == 1


@pytest.mark.asyncio
async def test_structured_executor_invalid_output_fails_without_claims(tmp_path):
    idb, repo, analysis = _running(tmp_path, running=False)
    llm = Mock()
    llm.chat_completion = AsyncMock(return_value={
        "content": "not json", "model": "m", "tokens_used": 1,
    })
    executor = SecondaryAnalysisExecutor(_FakeCpp(tmp_path), llm, Mock())
    await executor._execute(analysis.analysis_id, "A", Path(idb))
    result = repo.get_analysis(analysis.analysis_id)
    assert result.status == SecondaryAnalysisStatus.failed
    assert result.error_code == "structured_output_invalid"
    assert result.grounding_status is None
    assert repo.list_claims(analysis.analysis_id) == []


@pytest.mark.asyncio
async def test_legacy_v2_execution_remains_text_contract(tmp_path):
    idb, repo, analysis = _running(tmp_path, prompt_version="investigation-evidence-analysis:v2", running=False)
    llm = Mock()
    llm.chat_completion = AsyncMock(return_value={
        "content": "legacy free text", "model": "legacy-model", "tokens_used": 1,
    })
    executor = SecondaryAnalysisExecutor(_FakeCpp(tmp_path), llm, Mock())
    await executor._execute(analysis.analysis_id, "A", Path(idb))
    result = repo.get_analysis(analysis.analysis_id)
    assert result.status == SecondaryAnalysisStatus.review_pending
    assert result.description == "legacy free text"
    assert result.grounding_status is None
    assert repo.list_claims(analysis.analysis_id) == []


@pytest.mark.migration_matrix
@pytest.mark.asyncio
async def test_v2_migration_adds_grounding_column(tmp_path):
    idb = str(tmp_path / "investigation.db")
    InvestigationRepository(idb, "A")
    conn = sqlite3.connect(idb)
    conn.execute("DROP TRIGGER IF EXISTS trg_claim_refs_no_delete")
    conn.execute("DROP TRIGGER IF EXISTS trg_claim_refs_no_update")
    conn.execute("DROP TRIGGER IF EXISTS trg_claims_no_delete")
    conn.execute("DROP TRIGGER IF EXISTS trg_claims_no_update")
    conn.execute("DROP TRIGGER IF EXISTS trg_secondary_no_input_update")
    conn.execute("DROP TABLE IF EXISTS claim_evidence_refs")
    conn.execute("DROP TABLE IF EXISTS analysis_claims")
    conn.execute("ALTER TABLE secondary_analyses RENAME TO secondary_analyses_v4")
    conn.execute("""CREATE TABLE secondary_analyses (
        analysis_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, evidence_key TEXT NOT NULL,
        snapshot_id INTEGER NOT NULL REFERENCES evidence_snapshots(id) ON DELETE RESTRICT, version INTEGER NOT NULL, status TEXT NOT NULL,
        input_hash TEXT NOT NULL, input_envelope_json TEXT NOT NULL, prompt_version TEXT,
        description TEXT, summary TEXT, model TEXT, created_at TEXT NOT NULL,
        started_at TEXT, review_pending_at TEXT, decided_at TEXT, decided_by TEXT,
        decision_reason TEXT, failed_at TEXT, error_code TEXT, error_message TEXT,
        UNIQUE(task_id, evidence_key, version))""")
    conn.execute("INSERT INTO secondary_analyses SELECT analysis_id,task_id,evidence_key,snapshot_id,version,status,input_hash,input_envelope_json,prompt_version,description,summary,model,created_at,started_at,review_pending_at,decided_at,decided_by,decision_reason,failed_at,error_code,error_message FROM secondary_analyses_v4")
    conn.execute("DROP TABLE secondary_analyses_v4")
    from httpserver.services.investigation.repository import (
        _TRIGGER_SECONDARY_LEGAL_TRANSITION_SQL,
        _TRIGGER_SECONDARY_NO_TERMINAL_UPDATE_SQL,
    )
    conn.execute(_TRIGGER_SECONDARY_LEGAL_TRANSITION_SQL)
    conn.execute(_TRIGGER_SECONDARY_NO_TERMINAL_UPDATE_SQL)
    conn.execute("PRAGMA user_version = 2")
    conn.commit(); conn.close()
    InvestigationRepository(idb, "A")
    conn = sqlite3.connect(idb)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(secondary_analyses)")}
    assert "grounding_status" in cols
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 7
    conn.close()


@pytest.mark.asyncio
async def test_structured_executor_does_not_accept_llm_grounding_fields(tmp_path):
    idb, repo, analysis = _running(tmp_path, running=False)
    llm = Mock()
    llm.chat_completion = AsyncMock(return_value={
        "content": '{"description":"d","summary":"s","grounding_status":"valid","claims":[]}',
        "model": "m", "tokens_used": 1,
    })
    executor = SecondaryAnalysisExecutor(_FakeCpp(tmp_path), llm, Mock())
    await executor._execute(analysis.analysis_id, "A", Path(idb))
    result = repo.get_analysis(analysis.analysis_id)
    assert result.status == SecondaryAnalysisStatus.failed
    assert result.error_code == "structured_output_invalid"
