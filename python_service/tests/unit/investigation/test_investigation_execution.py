"""Tests for Secondary Analysis Execution layer (Phase C4b-2).

Covers execution invariants E1-E11, admission race, graceful shutdown,
single-worker claim, input_hash verification, prompt_version binding,
error classification/sanitization, and restart recovery.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from httpserver.services.evidence import ResolvedEvidence
from httpserver.services.investigation import (
    CURRENT_PROMPT_VERSION,
    InvestigationRepository,
    SecondaryAnalysisStatus,
)
from httpserver.services.investigation.execution import SecondaryAnalysisExecutor
from httpserver.services.investigation.prompts import (
    PROMPT_REGISTRY,
    SECONDARY_ANALYSIS_SYSTEM_V1,
    SECONDARY_ANALYSIS_USER_TEMPLATE_V1,
)


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------

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


def _file_resolved(fdb, task_id="A", path="/case/report.docx"):
    return ResolvedEvidence(
        task_id=task_id, evidence_key=f"file:{path}", evidence_type="file",
        normalized_path=path, source_db=fdb,
    )


def _setup(tmp_path, *, desc="DESC", prompt_version="investigation-evidence-analysis:v2"):
    """Create files.db + investigation.db with a captured snapshot and queued analysis."""
    fdb = str(tmp_path / "files.db")
    idb = str(tmp_path / "investigation.db")
    _make_files_db(fdb, [{"path": "/case/report.docx", "llm_description": desc, "size": 7}])
    repo = InvestigationRepository(idb, "A")
    snapshot = repo.capture_if_absent(_file_resolved(fdb))
    analysis = repo.create_analysis(snapshot, prompt_version=prompt_version)
    return fdb, idb, repo, snapshot, analysis


class FakeCppBackend:
    """Minimal cpp_backend for executor tests."""

    def __init__(self, task_id, task_dir):
        self._task_id = task_id
        self._task_dir = str(task_dir)
        self.get_task_call_count = 0

    async def get_task(self, task_id):
        self.get_task_call_count += 1
        if task_id != self._task_id:
            return None
        return {
            "id": task_id,
            "output_files_db": str(Path(self._task_dir) / "files.db"),
            "output_events_db": str(Path(self._task_dir) / "events.db"),
        }

    async def list_tasks(self, page=1, page_size=100, status=None):
        return {"tasks": [{
            "id": self._task_id,
        }]}


def _mock_llm(content="分析结果", model="test-model"):
    m = Mock()
    m.chat_completion = AsyncMock(return_value={
        "content": content, "model": model, "tokens_used": 10,
    })
    return m


def _executor(llm_service=None, cpp_backend=None, capture_service=None):
    return SecondaryAnalysisExecutor(
        cpp_backend=cpp_backend or Mock(),
        llm_service=llm_service,
        capture_service=capture_service or Mock(),
    )


EVIDENCE_KEY = "file:/case/report.docx"


# ---------------------------------------------------------------------------
# E1: queued persisted before background task
# ---------------------------------------------------------------------------

def test_E1_queued_persisted_before_background(tmp_path):
    _, idb, repo, snap, analysis = _setup(tmp_path, prompt_version=CURRENT_PROMPT_VERSION)
    assert analysis.status == SecondaryAnalysisStatus.queued
    # DB has the row
    row = InvestigationRepository(idb, "A").get_analysis(analysis.analysis_id)
    assert row is not None
    assert row.status == SecondaryAnalysisStatus.queued
    assert row.prompt_version == CURRENT_PROMPT_VERSION


# ---------------------------------------------------------------------------
# E2: worker only executes existing analysis_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_E2_nonexistent_analysis_no_crash(tmp_path):
    _, idb, _, _, _ = _setup(tmp_path)
    executor = _executor(llm_service=_mock_llm())
    # Should not raise
    await executor._execute("nonexistent-id", "A", Path(idb))


# ---------------------------------------------------------------------------
# E3: input only from envelope (never re-reads source DB)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_E3_input_from_envelope_not_source(tmp_path):
    fdb, idb, repo, snap, analysis = _setup(tmp_path, desc="ORIGINAL_DESC")
    mock_llm = _mock_llm()

    # Modify source DB AFTER analysis creation
    conn = sqlite3.connect(fdb)
    conn.execute("UPDATE files SET llm_description='MODIFIED_DESC' WHERE path='/case/report.docx'")
    conn.commit()
    conn.close()

    executor = _executor(llm_service=mock_llm)
    await executor._execute(analysis.analysis_id, "A", Path(idb))

    # LLM received ORIGINAL snapshot data, not modified
    call_kwargs = mock_llm.chat_completion.call_args
    user_prompt = call_kwargs.kwargs.get("user_prompt") or call_kwargs.args[1]
    assert "ORIGINAL_DESC" in user_prompt
    assert "MODIFIED_DESC" not in user_prompt


# ---------------------------------------------------------------------------
# E4: running transition before LLM call
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_E4_running_before_llm(tmp_path):
    _, idb, repo, snap, analysis = _setup(tmp_path)
    call_order = []

    original_transition = InvestigationRepository.transition

    def tracking_transition(self_repo, analysis_id, to, **fields):
        call_order.append(("transition", to))
        return original_transition(self_repo, analysis_id, to, **fields)

    async def tracking_chat(*args, **kwargs):
        call_order.append(("llm",))
        return {"content": "result", "model": "m", "tokens_used": 1}

    mock_llm = Mock()
    mock_llm.chat_completion = tracking_chat

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(InvestigationRepository, "transition", tracking_transition)
        executor = _executor(llm_service=mock_llm)
        await executor._execute(analysis.analysis_id, "A", Path(idb))

    # running transition must come before LLM call
    transition_idx = call_order.index(("transition", SecondaryAnalysisStatus.running))
    llm_idx = call_order.index(("llm",))
    assert transition_idx < llm_idx


# ---------------------------------------------------------------------------
# E5: success → review_pending (never accepted)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_E5_success_to_review_pending(tmp_path):
    _, idb, repo, snap, analysis = _setup(tmp_path)
    executor = _executor(llm_service=_mock_llm(content="详细分析内容"))
    await executor._execute(analysis.analysis_id, "A", Path(idb))

    result = InvestigationRepository(idb, "A").get_analysis(analysis.analysis_id)
    assert result.status == SecondaryAnalysisStatus.review_pending
    assert result.description == "详细分析内容"
    assert result.summary is not None
    assert result.model == "test-model"
    assert result.decided_at is None  # NOT accepted


# ---------------------------------------------------------------------------
# E6: LLM failure → failed + classified error_code
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_E6_llm_timeout(tmp_path):
    _, idb, repo, snap, analysis = _setup(tmp_path)
    mock_llm = Mock()
    mock_llm.chat_completion = AsyncMock(side_effect=httpx.ReadTimeout("timeout"))
    executor = _executor(llm_service=mock_llm)
    await executor._execute(analysis.analysis_id, "A", Path(idb))

    result = InvestigationRepository(idb, "A").get_analysis(analysis.analysis_id)
    assert result.status == SecondaryAnalysisStatus.failed
    assert result.error_code == "llm_timeout"
    assert "timed out" in result.error_message
    assert "timeout" not in result.error_message  # no internal detail leakage


@pytest.mark.asyncio
async def test_E6_llm_connection_error(tmp_path):
    _, idb, repo, snap, analysis = _setup(tmp_path)
    mock_llm = Mock()
    mock_llm.chat_completion = AsyncMock(
        side_effect=httpx.ConnectError("Connection refused to http://internal:1234")
    )
    executor = _executor(llm_service=mock_llm)
    await executor._execute(analysis.analysis_id, "A", Path(idb))

    result = InvestigationRepository(idb, "A").get_analysis(analysis.analysis_id)
    assert result.status == SecondaryAnalysisStatus.failed
    assert result.error_code == "llm_connection_error"
    # error_message must NOT contain the internal URL
    assert "internal" not in result.error_message
    assert "1234" not in result.error_message


@pytest.mark.asyncio
async def test_E6_generic_exception(tmp_path):
    _, idb, repo, snap, analysis = _setup(tmp_path)
    mock_llm = Mock()
    mock_llm.chat_completion = AsyncMock(side_effect=RuntimeError("secret internal path /var/secrets"))
    executor = _executor(llm_service=mock_llm)
    await executor._execute(analysis.analysis_id, "A", Path(idb))

    result = InvestigationRepository(idb, "A").get_analysis(analysis.analysis_id)
    assert result.status == SecondaryAnalysisStatus.failed
    assert result.error_code == "execution_error"
    assert "secrets" not in result.error_message  # sanitized
    assert "path" not in result.error_message


# ---------------------------------------------------------------------------
# E7: worker doesn't touch other versions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_E7_other_version_untouched(tmp_path):
    _, idb, repo, snap, analysis1 = _setup(tmp_path)
    analysis2 = repo.create_analysis(snap, prompt_version=CURRENT_PROMPT_VERSION)

    v2_hash_before = analysis2.input_hash
    v2_status_before = analysis2.status

    executor = _executor(llm_service=_mock_llm())
    await executor._execute(analysis1.analysis_id, "A", Path(idb))

    v2_after = InvestigationRepository(idb, "A").get_analysis(analysis2.analysis_id)
    assert v2_after.input_hash == v2_hash_before
    assert v2_after.status == v2_status_before


# ---------------------------------------------------------------------------
# E8: SQLite is source of truth
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_E8_status_from_db_not_memory(tmp_path):
    _, idb, repo, snap, analysis = _setup(tmp_path)
    executor = _executor(llm_service=_mock_llm())
    await executor._execute(analysis.analysis_id, "A", Path(idb))

    # Query from a brand-new repo instance (no memory)
    fresh_repo = InvestigationRepository(idb, "A")
    result = fresh_repo.get_analysis(analysis.analysis_id)
    assert result.status == SecondaryAnalysisStatus.review_pending


# ---------------------------------------------------------------------------
# E9: restart recovery
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_E9_restart_recovery(tmp_path):
    fdb, idb, repo, snap, analysis = _setup(tmp_path)
    # Create another analysis and advance to running
    analysis2 = repo.create_analysis(snap, prompt_version=CURRENT_PROMPT_VERSION)
    repo.transition(analysis2.analysis_id, SecondaryAnalysisStatus.running)

    # Also create a terminal analysis (should NOT be recovered)
    analysis3 = repo.create_analysis(snap, prompt_version=CURRENT_PROMPT_VERSION)
    repo.transition(analysis3.analysis_id, SecondaryAnalysisStatus.running)
    repo.transition(analysis3.analysis_id, SecondaryAnalysisStatus.review_pending)
    repo.transition(analysis3.analysis_id, SecondaryAnalysisStatus.accepted, decided_by="x")

    fake_cpp = FakeCppBackend("A", tmp_path)
    executor = _executor(llm_service=_mock_llm(), cpp_backend=fake_cpp)
    await executor._recover_stale_analyses()

    r1 = InvestigationRepository(idb, "A").get_analysis(analysis.analysis_id)
    r2 = InvestigationRepository(idb, "A").get_analysis(analysis2.analysis_id)
    r3 = InvestigationRepository(idb, "A").get_analysis(analysis3.analysis_id)

    assert r1.status == SecondaryAnalysisStatus.failed
    assert r1.error_code == "service_restart"
    assert r2.status == SecondaryAnalysisStatus.failed
    assert r2.error_code == "service_restart"
    # Terminal analysis untouched
    assert r3.status == SecondaryAnalysisStatus.accepted


# ---------------------------------------------------------------------------
# E10: no writes to events.db / files.db
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_E10_no_writes_to_source_dbs(tmp_path):
    fdb, idb, repo, snap, analysis = _setup(tmp_path)
    edb = str(tmp_path / "events.db")
    sqlite3.connect(edb).execute("CREATE TABLE events(ts INTEGER)").close()

    files_mtime_before = os.path.getmtime(fdb)
    events_mtime_before = os.path.getmtime(edb)

    executor = _executor(llm_service=_mock_llm())
    await executor._execute(analysis.analysis_id, "A", Path(idb))

    assert os.path.getmtime(fdb) == files_mtime_before
    assert os.path.getmtime(edb) == events_mtime_before


# ---------------------------------------------------------------------------
# E11: worker uses submit's db_path (no re-get_task)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_E11_worker_uses_passed_db_path(tmp_path):
    _, idb, _, _, analysis = _setup(tmp_path)
    fake_cpp = FakeCppBackend("A", tmp_path)
    executor = _executor(llm_service=_mock_llm(), cpp_backend=fake_cpp)

    # _execute uses db_path directly — does NOT call cpp_backend.get_task
    initial_count = fake_cpp.get_task_call_count
    await executor._execute(analysis.analysis_id, "A", Path(idb))
    assert fake_cpp.get_task_call_count == initial_count  # no new get_task calls


# ---------------------------------------------------------------------------
# Single-worker claim
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_single_worker_claim_dual_execute(tmp_path):
    _, idb, repo, snap, analysis = _setup(tmp_path)

    async def slow_chat(*args, **kwargs):
        await asyncio.sleep(0.1)
        return {"content": "result", "model": "m", "tokens_used": 1}

    mock_llm = Mock()
    mock_llm.chat_completion = AsyncMock(side_effect=slow_chat)
    executor = _executor(llm_service=mock_llm)

    # Two concurrent executions of the same analysis_id
    await asyncio.gather(
        executor._execute(analysis.analysis_id, "A", Path(idb)),
        executor._execute(analysis.analysis_id, "A", Path(idb)),
    )

    # LLM called exactly once
    assert mock_llm.chat_completion.call_count == 1

    result = InvestigationRepository(idb, "A").get_analysis(analysis.analysis_id)
    assert result.status == SecondaryAnalysisStatus.review_pending


# ---------------------------------------------------------------------------
# Input hash verification
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_input_hash_mismatch_detected(tmp_path):
    _, idb, repo, snap, analysis = _setup(tmp_path, prompt_version="investigation-evidence-analysis:v2")
    mock_llm = _mock_llm()

    # v3 trigger blocks input column UPDATEs; DROP → tamper → recreate to
    # simulate bypass/corruption and test executor defense-in-depth (hash check).
    from httpserver.services.investigation.repository import _TRIGGER_SECONDARY_NO_INPUT_UPDATE_SQL
    conn = sqlite3.connect(idb)
    conn.execute("DROP TRIGGER trg_secondary_no_input_update")
    conn.execute(
        "UPDATE secondary_analyses SET input_envelope_json = ? WHERE analysis_id = ?",
        ['{"schema_version":2,"evidence_snapshot":{}}', analysis.analysis_id],
    )
    conn.execute(_TRIGGER_SECONDARY_NO_INPUT_UPDATE_SQL)  # recreate
    conn.commit()
    conn.close()

    executor = _executor(llm_service=mock_llm)
    await executor._execute(analysis.analysis_id, "A", Path(idb))

    result = InvestigationRepository(idb, "A").get_analysis(analysis.analysis_id)
    assert result.status == SecondaryAnalysisStatus.failed
    assert result.error_code == "input_hash_mismatch"
    assert mock_llm.chat_completion.call_count == 0  # LLM never called


# ---------------------------------------------------------------------------
# prompt_version validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_prompt_version_mismatch(tmp_path):
    _, idb, repo, snap, analysis = _setup(tmp_path, prompt_version="investigation-evidence-analysis:v2")
    mock_llm = _mock_llm()

    # v3 trigger blocks prompt_version UPDATE; DROP → tamper → recreate
    from httpserver.services.investigation.repository import _TRIGGER_SECONDARY_NO_INPUT_UPDATE_SQL
    conn = sqlite3.connect(idb)
    conn.execute("DROP TRIGGER trg_secondary_no_input_update")
    conn.execute(
        "UPDATE secondary_analyses SET prompt_version = 'different:v1' WHERE analysis_id = ?",
        [analysis.analysis_id],
    )
    conn.execute(_TRIGGER_SECONDARY_NO_INPUT_UPDATE_SQL)  # recreate
    conn.commit()
    conn.close()

    executor = _executor(llm_service=mock_llm)
    await executor._execute(analysis.analysis_id, "A", Path(idb))

    result = InvestigationRepository(idb, "A").get_analysis(analysis.analysis_id)
    assert result.status == SecondaryAnalysisStatus.failed
    assert result.error_code == "input_integrity_error"


@pytest.mark.asyncio
async def test_prompt_version_none(tmp_path):
    _, idb, repo, snap, analysis = _setup(tmp_path, prompt_version=None)
    mock_llm = _mock_llm()
    executor = _executor(llm_service=mock_llm)
    await executor._execute(analysis.analysis_id, "A", Path(idb))

    result = InvestigationRepository(idb, "A").get_analysis(analysis.analysis_id)
    assert result.status == SecondaryAnalysisStatus.failed
    assert result.error_code == "missing_prompt_version"


@pytest.mark.asyncio
async def test_prompt_version_unknown(tmp_path):
    _, idb, repo, snap, analysis = _setup(tmp_path, prompt_version="bogus:v99")
    mock_llm = _mock_llm()
    executor = _executor(llm_service=mock_llm)
    await executor._execute(analysis.analysis_id, "A", Path(idb))

    result = InvestigationRepository(idb, "A").get_analysis(analysis.analysis_id)
    assert result.status == SecondaryAnalysisStatus.failed
    assert result.error_code == "unknown_prompt_version"


# ---------------------------------------------------------------------------
# LLM unavailable / empty response
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_unavailable(tmp_path):
    _, idb, repo, snap, analysis = _setup(tmp_path)
    executor = _executor(llm_service=None)  # no LLM
    await executor._execute(analysis.analysis_id, "A", Path(idb))

    result = InvestigationRepository(idb, "A").get_analysis(analysis.analysis_id)
    assert result.status == SecondaryAnalysisStatus.failed
    assert result.error_code == "llm_unavailable"


@pytest.mark.asyncio
async def test_llm_empty_response(tmp_path):
    _, idb, repo, snap, analysis = _setup(tmp_path)
    mock_llm = _mock_llm(content="")
    executor = _executor(llm_service=mock_llm)
    await executor._execute(analysis.analysis_id, "A", Path(idb))

    result = InvestigationRepository(idb, "A").get_analysis(analysis.analysis_id)
    assert result.status == SecondaryAnalysisStatus.failed
    assert result.error_code == "llm_empty_response"


# ---------------------------------------------------------------------------
# Graceful shutdown → failed(service_shutdown)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_graceful_shutdown_marks_failed(tmp_path):
    fdb, idb, repo, snap, analysis = _setup(tmp_path)

    async def slow_chat(*args, **kwargs):
        await asyncio.sleep(10)  # won't complete before shutdown
        return {"content": "x", "model": "m", "tokens_used": 1}

    mock_llm = Mock()
    mock_llm.chat_completion = AsyncMock(side_effect=slow_chat)

    fake_cpp = FakeCppBackend("A", tmp_path)
    mock_capture = Mock()
    mock_capture.capture = AsyncMock(return_value=snap)

    executor = SecondaryAnalysisExecutor(
        cpp_backend=fake_cpp, llm_service=mock_llm, capture_service=mock_capture,
    )

    # Submit creates analysis + starts background task
    submitted = await executor.submit("A", EVIDENCE_KEY)
    # Shutdown cancels the in-flight task
    await executor.shutdown()

    result = InvestigationRepository(idb, "A").get_analysis(submitted.analysis_id)
    assert result.status == SecondaryAnalysisStatus.failed
    assert result.error_code == "service_shutdown"


# ---------------------------------------------------------------------------
# Admission race: submit after shutdown → RuntimeError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_submit_after_shutdown_rejected(tmp_path):
    fdb, idb, repo, snap, analysis = _setup(tmp_path)
    fake_cpp = FakeCppBackend("A", tmp_path)
    mock_capture = Mock()
    mock_capture.capture = AsyncMock(return_value=snap)
    executor = SecondaryAnalysisExecutor(
        cpp_backend=fake_cpp, llm_service=_mock_llm(), capture_service=mock_capture,
    )

    await executor.shutdown()

    with pytest.raises(RuntimeError, match="shutting down"):
        await executor.submit("A", EVIDENCE_KEY)


# ---------------------------------------------------------------------------
# Prompt immutability (SHA-256 lock)
# ---------------------------------------------------------------------------

def test_prompt_v1_immutable_hash():
    """Lock v1 prompt text. If this fails, create a new version instead of editing."""
    expected = "fb1e5105d2c3668507e5835ce5c66dcc7b1a8fc898d9e0f96039048347e4ddc9"
    data = (SECONDARY_ANALYSIS_SYSTEM_V1 + SECONDARY_ANALYSIS_USER_TEMPLATE_V1).encode("utf-8")
    actual = hashlib.sha256(data).hexdigest()
    assert actual == expected, (
        "v1 prompt text was modified! Create a new version (v2) instead. "
        "If intentional, update the expected hash."
    )


def test_prompt_registry_has_current_version():
    assert CURRENT_PROMPT_VERSION in PROMPT_REGISTRY


# ---------------------------------------------------------------------------
# chat_completion unit tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_chat_completion_preserves_temperature_zero():
    """temperature=0.0 must not be overridden by default (falsy but valid)."""
    from httpserver.config import Settings
    from httpserver.services.llm.llm_service import LLMService

    settings = Settings()
    service = LLMService(settings)
    service._initialized = True
    service._text_client = Mock()
    service._text_client.post = AsyncMock(return_value=Mock(
        raise_for_status=Mock(),
        json=Mock(return_value={
            "choices": [{"message": {"content": "test"}}],
            "model": "m",
            "usage": {"total_tokens": 1},
        }),
    ))

    await service.chat_completion("sys", "usr", temperature=0.0)
    call_json = service._text_client.post.call_args.kwargs["json"]
    assert call_json["temperature"] == 0.0


@pytest.mark.asyncio
async def test_chat_completion_rejects_bad_model_type():
    from httpserver.config import Settings
    from httpserver.services.llm.llm_service import LLMService

    service = LLMService(Settings())
    service._initialized = True
    with pytest.raises(ValueError, match="unsupported model_type"):
        await service.chat_completion("sys", "usr", model_type="bogus")


# ---------------------------------------------------------------------------
# GET canonicalization (parse_evidence_key, not resolve)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_analysis_canonicalizes_backslash(tmp_path):
    """Backslash and forward-slash variants query the same historical analysis."""
    from httpserver.services.evidence import parse_evidence_key

    _, idb, repo, snap, analysis = _setup(tmp_path)
    fake_cpp = FakeCppBackend("A", tmp_path)
    executor = _executor(llm_service=_mock_llm(), cpp_backend=fake_cpp)

    # Canonical key is file:/case/report.docx
    # Backslash variant should canonicalize to the same
    parsed = parse_evidence_key(r"file:\case\report.docx")
    assert parsed.canonical_key == EVIDENCE_KEY

    results = await executor.list_analyses("A", parsed.canonical_key)
    assert len(results) >= 1
    assert any(r.analysis_id == analysis.analysis_id for r in results)
