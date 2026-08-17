"""D4b task-deletion write-boundary tests.

Deterministic race-oriented coverage for the live-task write boundary:
a task deleted during (or right after) LLM execution must never have its
directory or investigation.db resurrected by a terminal write.
"""

from __future__ import annotations

import asyncio
import shutil
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from httpserver.services.evidence import ResolvedEvidence
from httpserver.services.investigation import (
    EventRefreshExecutor,
    EventRefreshStatus,
    InvestigationRepository,
    SecondaryAnalysisExecutor,
    SecondaryAnalysisStatus,
)
from httpserver.services.investigation.repository import InvestigationRepository as Repo

KEY = "file:/case/a.txt"


class DeletableCppBackend:
    """Fake registry: answers live lookups until the task is deleted."""

    def __init__(self, task_id: str, task_dir: Path):
        self._task_id = task_id
        self._task_dir = task_dir
        self._deleted = False
        self.on_get_task = None  # optional test hook (TOCTOU injection)

    def delete_task(self):
        self._deleted = True

    async def get_task(self, task_id):
        if self.on_get_task is not None:
            self.on_get_task()
        if self._deleted or task_id != self._task_id:
            return None
        return {
            "id": task_id,
            "output_files_db": str(self._task_dir / "files.db"),
            "output_events_db": str(self._task_dir / "events.db"),
        }

    async def list_tasks(self, page=1, page_size=100, status=None):
        if self._deleted:
            return {"tasks": []}
        return {"tasks": [{"id": self._task_id}]}


class OtherDirCppBackend(DeletableCppBackend):
    """Registry resolves the task to a DIFFERENT directory than submitted."""

    def __init__(self, task_id: str, task_dir: Path, other_dir: Path):
        super().__init__(task_id, task_dir)
        self._other_dir = other_dir

    async def get_task(self, task_id):
        if self.on_get_task is not None:
            self.on_get_task()
        if self._deleted or task_id != self._task_id:
            return None
        return {
            "id": task_id,
            "output_files_db": str(self._other_dir / "files.db"),
            "output_events_db": str(self._other_dir / "events.db"),
        }


def _make_files_db(task_dir: Path):
    files_db = task_dir / "files.db"
    conn = sqlite3.connect(files_db)
    conn.execute(
        "CREATE TABLE files (path TEXT, name TEXT, extension TEXT, category TEXT, type TEXT, "
        "size INTEGER, mtime INTEGER, ctime INTEGER, is_deleted INTEGER, md5 TEXT, "
        "llm_summary TEXT, llm_description TEXT, llm_keywords TEXT, llm_analyzed_at INTEGER, "
        "llm_model_used TEXT, scene_type TEXT, scene_priority INTEGER, scene_relevant INTEGER)"
    )
    conn.execute(
        "INSERT INTO files(path,llm_description,size) VALUES('/case/a.txt','desc',1)"
    )
    conn.commit()
    conn.close()
    return files_db


def _setup_secondary(task_dir: Path, task_id: str = "A"):
    files_db = _make_files_db(task_dir)
    repo = InvestigationRepository(task_dir / "investigation.db", task_id)
    snapshot = repo.capture_if_absent(ResolvedEvidence(
        task_id=task_id, evidence_key=KEY, evidence_type="file",
        normalized_path="/case/a.txt", source_db=str(files_db),
    ))
    analysis = repo.create_analysis(snapshot, prompt_version="investigation-evidence-analysis:v2")
    return repo, analysis


def _setup_refresh(task_dir: Path, task_id: str = "A"):
    repo, snapshot = _setup_secondary(task_dir, task_id)
    event = repo.create_event("old narrative")
    refresh = repo.create_event_refresh(event.event_id)
    return repo, event, refresh


def _blocking_llm():
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_chat(*args, **kwargs):
        started.set()
        await release.wait()
        return {"content": "结果", "model": "m", "tokens_used": 1}

    llm = Mock()
    llm.chat_completion = AsyncMock(side_effect=slow_chat)
    return llm, started, release


# ---------------------------------------------------------------------------
# §9: delete during LLM — no resurrection (Secondary Analysis)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_secondary_delete_during_llm_never_resurrects(tmp_path):
    task_dir = tmp_path / "A"
    task_dir.mkdir()
    repo, analysis = _setup_secondary(task_dir)

    fake_cpp = DeletableCppBackend("A", task_dir)
    llm, started, release = _blocking_llm()
    executor = SecondaryAnalysisExecutor(fake_cpp, llm, Mock())

    worker = asyncio.create_task(
        executor._execute(analysis.analysis_id, "A", repo.db_path)
    )
    await started.wait()  # worker is inside the LLM call

    fake_cpp.delete_task()
    shutil.rmtree(task_dir)
    assert not task_dir.exists()

    release.set()
    await worker

    assert not task_dir.exists()
    assert not (task_dir / "investigation.db").exists()


# ---------------------------------------------------------------------------
# §10: TOCTOU — task dir deleted AFTER the live check, BEFORE the open
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_secondary_toctou_after_live_check_no_recreation(tmp_path):
    task_dir = tmp_path / "A"
    task_dir.mkdir()
    repo, analysis = _setup_secondary(task_dir)

    fake_cpp = DeletableCppBackend("A", task_dir)
    # The write-boundary lookup itself deletes the directory AFTER the
    # registry answers (the registry still reports the task as live).
    fake_cpp.on_get_task = lambda: shutil.rmtree(task_dir, ignore_errors=True)

    llm = Mock()
    llm.chat_completion = AsyncMock(return_value={
        "content": "结果", "model": "m", "tokens_used": 1,
    })
    executor = SecondaryAnalysisExecutor(fake_cpp, llm, Mock())
    await executor._execute(analysis.analysis_id, "A", repo.db_path)

    assert not task_dir.exists()
    assert not (task_dir / "investigation.db").exists()


# ---------------------------------------------------------------------------
# §11: Event Refresh deletion race
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_delete_during_llm_no_write_no_resurrection(tmp_path):
    task_dir = tmp_path / "A"
    task_dir.mkdir()
    repo, event, refresh = _setup_refresh(task_dir)

    fake_cpp = DeletableCppBackend("A", task_dir)
    llm, started, release = _blocking_llm()
    executor = EventRefreshExecutor(fake_cpp, llm, Mock())

    worker = asyncio.create_task(
        executor._execute(refresh.refresh_id, "A", repo.db_path)
    )
    await started.wait()

    fake_cpp.delete_task()
    shutil.rmtree(task_dir)

    release.set()
    await worker

    assert not task_dir.exists()
    assert not (task_dir / "investigation.db").exists()


@pytest.mark.asyncio
async def test_refresh_other_live_task_unaffected(tmp_path):
    # Task B stays live while task A is deleted mid-flight.
    dir_a = tmp_path / "A"
    dir_b = tmp_path / "B"
    dir_a.mkdir()
    dir_b.mkdir()
    repo_a, analysis_a = _setup_secondary(dir_a, "A")
    repo_b, analysis_b = _setup_secondary(dir_b, "B")

    fake_a = DeletableCppBackend("A", dir_a)
    llm, started, release = _blocking_llm()
    executor = SecondaryAnalysisExecutor(fake_a, llm, Mock())

    worker = asyncio.create_task(
        executor._execute(analysis_a.analysis_id, "A", repo_a.db_path)
    )
    await started.wait()
    fake_a.delete_task()
    shutil.rmtree(dir_a)
    release.set()
    await worker

    # B's executor (separate registry view) completes normally.
    fake_b = DeletableCppBackend("B", dir_b)
    llm_ok = Mock()
    llm_ok.chat_completion = AsyncMock(return_value={
        "content": "B 结果", "model": "m", "tokens_used": 1,
    })
    executor_b = SecondaryAnalysisExecutor(fake_b, llm_ok, Mock())
    await executor_b._execute(analysis_b.analysis_id, "B", repo_b.db_path)
    final_b = InvestigationRepository.open_existing(
        repo_b.db_path, "B"
    ).get_analysis(analysis_b.analysis_id)
    assert final_b.status == SecondaryAnalysisStatus.review_pending
    assert dir_b.exists()
    assert not dir_a.exists()


# ---------------------------------------------------------------------------
# §12: shutdown deletion race
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_shutdown_after_delete_never_recreates_store(tmp_path):
    task_dir = tmp_path / "A"
    task_dir.mkdir()
    repo, analysis = _setup_secondary(task_dir)

    fake_cpp = DeletableCppBackend("A", task_dir)
    llm, started, release = _blocking_llm()
    executor = SecondaryAnalysisExecutor(fake_cpp, llm, Mock())

    worker = asyncio.create_task(
        executor._execute(analysis.analysis_id, "A", repo.db_path)
    )
    await started.wait()
    # Simulate the executor's shutdown bookkeeping for the in-flight worker.
    async with executor._admission_lock:
        executor._tasks[analysis.analysis_id] = worker
        executor._task_ctx[analysis.analysis_id] = ("A", repo.db_path)

    fake_cpp.delete_task()
    shutil.rmtree(task_dir)
    release.set()

    await executor.shutdown()  # must complete and must not recreate anything

    assert not task_dir.exists()
    assert not (task_dir / "investigation.db").exists()


# ---------------------------------------------------------------------------
# §14: submit-time path != current trusted path — identity mismatch drop
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_secondary_db_path_mismatch_drops_terminal_write(tmp_path):
    dir_a = tmp_path / "A"
    dir_b = tmp_path / "B"
    dir_a.mkdir()
    dir_b.mkdir()
    repo_a, analysis = _setup_secondary(dir_a, "A")
    # Registry now resolves task A to directory B (which has its own store).
    _setup_secondary(dir_b, "A")

    fake_cpp = OtherDirCppBackend("A", dir_a, dir_b)
    llm = Mock()
    llm.chat_completion = AsyncMock(return_value={
        "content": "结果", "model": "m", "tokens_used": 1,
    })
    executor = SecondaryAnalysisExecutor(fake_cpp, llm, Mock())
    await executor._execute(analysis.analysis_id, "A", repo_a.db_path)

    # Terminal result was NOT written to the current-registry store B: its
    # own setup analysis is still queued (the worker's terminal result for
    # the admission-time store never landed there).
    repo_b = InvestigationRepository.open_existing(dir_b / "investigation.db", "A")
    b_rows = repo_b.list_analyses(KEY)
    assert len(b_rows) == 1
    assert b_rows[0].status == SecondaryAnalysisStatus.queued
    assert b_rows[0].description is None
    # ...and the admission-time store A keeps its pre-write (claimed) state.
    repo_a2 = InvestigationRepository.open_existing(repo_a.db_path, "A")
    row = repo_a2.get_analysis(analysis.analysis_id)
    assert row.status == SecondaryAnalysisStatus.running


# ---------------------------------------------------------------------------
# Live regression (§13): normal live-task flow unchanged (completion path)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_live_task_completion_still_writes(tmp_path):
    task_dir = tmp_path / "A"
    task_dir.mkdir()
    repo, analysis = _setup_secondary(task_dir)

    fake_cpp = DeletableCppBackend("A", task_dir)
    llm = Mock()
    llm.chat_completion = AsyncMock(return_value={
        "content": "结果", "model": "m", "tokens_used": 1,
    })
    executor = SecondaryAnalysisExecutor(fake_cpp, llm, Mock())
    await executor._execute(analysis.analysis_id, "A", repo.db_path)

    final = InvestigationRepository.open_existing(
        repo.db_path, "A"
    ).get_analysis(analysis.analysis_id)
    assert final.status == SecondaryAnalysisStatus.review_pending


@pytest.mark.asyncio
async def test_live_refresh_completion_still_writes(tmp_path):
    task_dir = tmp_path / "A"
    task_dir.mkdir()
    repo, event, refresh = _setup_refresh(task_dir)

    fake_cpp = DeletableCppBackend("A", task_dir)
    llm = Mock()
    llm.chat_completion = AsyncMock(return_value={
        "content": '{"title":"t1","summary":"s1"}', "model": "m",
    })
    executor = EventRefreshExecutor(fake_cpp, llm, Mock())
    await executor._execute(refresh.refresh_id, "A", repo.db_path)

    final = InvestigationRepository.open_existing(
        repo.db_path, "A"
    ).get_event_refresh(refresh.refresh_id)
    assert final.status == EventRefreshStatus.completed


# ---------------------------------------------------------------------------
# open_existing unit contract
# ---------------------------------------------------------------------------

def test_open_existing_never_creates_missing_store(tmp_path):
    from httpserver.services.evidence.exceptions import EvidenceStoreError

    missing = tmp_path / "nope" / "investigation.db"
    with pytest.raises(EvidenceStoreError):
        InvestigationRepository.open_existing(missing, "A")
    assert not missing.exists()
    assert not missing.parent.exists()


def test_open_existing_rejects_unsupported_version(tmp_path):
    from httpserver.services.evidence.exceptions import EvidenceStoreError

    db = tmp_path / "investigation.db"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA user_version = 3")
    conn.commit()
    conn.close()
    with pytest.raises(EvidenceStoreError):
        InvestigationRepository.open_existing(db, "A")
