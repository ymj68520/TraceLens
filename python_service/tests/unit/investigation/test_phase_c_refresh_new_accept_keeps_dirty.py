"""Phase C cross-stage integration: admission-window staleness survives
refresh completion (C10 §11 S2/S3, E9).

The refresh must never swallow new staleness accepted AFTER its admission:
S3 (dirty at admission, A2 accepted during execution) and S2 (clean at
admission, A1 accepted during execution) both end completed with
needs_refresh=1. Simulated by accepting the newer analysis inside the fake
LLM call, i.e. strictly between claim and completion.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from httpserver.services.evidence import ResolvedEvidence
from httpserver.services.investigation import (
    AnalysisReviewDecision,
    EventRefreshExecutor,
    EventRefreshStatus,
    InvestigationRepository,
    SecondaryAnalysisStatus,
)

PROMPT_V3 = "investigation-evidence-analysis:v3"
KEY = "file:/case/a.txt"


class _FakeCppBackend:
    def __init__(self, task_dir: Path):
        self._task_dir = task_dir

    async def get_task(self, task_id):
        return {
            "id": task_id,
            "output_files_db": str(self._task_dir / "files.db"),
            "output_events_db": str(self._task_dir / "events.db"),
        }


def _repo(tmp_path: Path):
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
    repo = InvestigationRepository(tmp_path / "investigation.db", "A")
    snapshot = repo.capture_if_absent(ResolvedEvidence(
        task_id="A", evidence_key=KEY, evidence_type="file",
        normalized_path="/case/a.txt", source_db=files_db,
    ))
    return repo, snapshot


def _accepted(repo, snapshot):
    analysis = repo.create_analysis(snapshot, prompt_version=PROMPT_V3)
    repo.transition(analysis.analysis_id, SecondaryAnalysisStatus.running)
    repo.complete_analysis_for_review(
        analysis.analysis_id, description="d", summary="s",
        model="m", candidates=[],
    )
    return repo.review_analysis(
        analysis.analysis_id, decision=AnalysisReviewDecision.accepted,
        reviewer="analyst",
    )


async def _run_refresh(repo, event, during_execution=None):
    refresh = repo.create_event_refresh(event.event_id, requested_by="analyst")

    async def fake_chat(system_prompt, user_prompt):
        if during_execution is not None:
            during_execution()
        return {
            "content": '{"title":"t","summary":"refreshed"}',
            "model": "transport-model",
        }

    llm = Mock()
    llm.chat_completion = AsyncMock(side_effect=fake_chat)
    executor = EventRefreshExecutor(_FakeCppBackend(repo.db_path.parent), llm, Mock())
    await executor._execute(refresh.refresh_id, "A", repo.db_path)
    return repo.get_event_refresh(refresh.refresh_id)


@pytest.mark.asyncio
async def test_s3_accept_during_execution_keeps_event_dirty(tmp_path):
    """§1 variant B: dirty with A1; A2 accepted during the refresh run."""
    repo, snapshot = _repo(tmp_path)
    event = repo.create_event("E1", created_by="a")
    repo.link_event_evidence(event.event_id, KEY, linked_by="a")
    _accepted(repo, snapshot)  # A1 → dirty
    assert repo.get_event(event.event_id).needs_refresh is True

    result = await _run_refresh(
        repo, event, during_execution=lambda: _accepted(repo, snapshot)
    )

    assert result.status is EventRefreshStatus.completed
    assert result.produced_version == 2
    # E9: the completed refresh did NOT swallow the new accepted analysis.
    assert repo.get_event(event.event_id).needs_refresh is True


@pytest.mark.asyncio
async def test_s2_clean_admission_then_accept_ends_dirty(tmp_path):
    """S2: event clean at admission; acceptance lands during execution."""
    repo, snapshot = _repo(tmp_path)
    event = repo.create_event("E1", created_by="a")
    repo.link_event_evidence(event.event_id, KEY, linked_by="a")
    # No accepted analysis yet → link does NOT dirty the event.
    assert repo.get_event(event.event_id).needs_refresh is False

    result = await _run_refresh(
        repo, event, during_execution=lambda: _accepted(repo, snapshot)
    )

    assert result.status is EventRefreshStatus.completed
    assert repo.get_event(event.event_id).needs_refresh is True


@pytest.mark.asyncio
async def test_clean_admission_without_change_stays_clean_after_refresh(tmp_path):
    """R8 companion: an explicitly refreshed clean event stays clean."""
    repo, snapshot = _repo(tmp_path)
    event = repo.create_event("E1", created_by="a")
    repo.link_event_evidence(event.event_id, KEY, linked_by="a")

    result = await _run_refresh(repo, event)

    assert result.status is EventRefreshStatus.completed
    assert result.produced_version == 2
    assert repo.get_event(event.event_id).needs_refresh is False


@pytest.mark.asyncio
async def test_base_version_change_fails_without_overwriting_narrative(tmp_path):
    """Concurrent version production → base_version_changed, history intact.

    Admission enforces one in-flight refresh per event, so the rival version
    is produced directly while our refresh sits between admission and claim
    (the exact window the completion guard exists for).
    """
    repo, snapshot = _repo(tmp_path)
    event = repo.create_event("E1", created_by="a")
    repo.link_event_evidence(event.event_id, KEY, linked_by="a")
    _accepted(repo, snapshot)
    refresh = repo.create_event_refresh(event.event_id, requested_by="a")
    assert refresh.base_version == 1

    # A rival version 2 lands during execution (before our claim completes).
    with sqlite3.connect(repo.db_path) as conn:
        conn.execute(
            "INSERT INTO investigation_event_versions "
            "(task_id,event_id,version,title,summary,created_at,created_by) "
            "VALUES (?,?,?,?,?,?,NULL)",
            ["A", event.event_id, 2, "rival", "rival narrative", "2026-08-14T00:00:00+00:00"],
        )
        conn.commit()

    llm = Mock()
    llm.chat_completion = AsyncMock(return_value={
        "content": '{"title":"loser","summary":"loser narrative"}',
        "model": "transport-model",
    })
    executor = EventRefreshExecutor(_FakeCppBackend(repo.db_path.parent), llm, Mock())
    await executor._execute(refresh.refresh_id, "A", repo.db_path)

    stale = repo.get_event_refresh(refresh.refresh_id)
    assert stale.status is EventRefreshStatus.failed
    assert stale.error_code == "base_version_changed"
    versions = repo.list_event_versions(event.event_id)
    assert [v.version for v in versions] == [1, 2]
    assert versions[1].summary == "rival narrative"  # loser did not overwrite
