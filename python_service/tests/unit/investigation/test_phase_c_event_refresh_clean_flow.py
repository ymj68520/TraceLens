"""Phase C cross-stage integration: explicit Event Refresh converges clean
(C10 §1 steps 10-13, §10, §12, E8).

S1: dirty Event (linked evidence has an accepted analysis, nothing changes
during execution) → refresh executes from the frozen envelope only →
completed → immutable v2 → needs_refresh=0. Proven end-to-end through the
real EventRefreshExecutor with a fake transport LLM.
"""

from __future__ import annotations

import json
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


def _dirty_repo(tmp_path: Path):
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
    event = repo.create_event("E1", summary="v1 narrative", created_by="a")
    repo.link_event_evidence(event.event_id, KEY, linked_by="a")

    analysis = repo.create_analysis(snapshot, prompt_version=PROMPT_V3)
    repo.transition(analysis.analysis_id, SecondaryAnalysisStatus.running)
    repo.complete_analysis_for_review(
        analysis.analysis_id, description="d", summary="s",
        model="m", candidates=[],
    )
    repo.review_analysis(
        analysis.analysis_id, decision=AnalysisReviewDecision.accepted,
        reviewer="analyst",
    )
    assert repo.get_event(event.event_id).needs_refresh is True
    return repo, event


@pytest.mark.asyncio
async def test_s1_dirty_refresh_completes_writes_v2_and_clears_dirty(tmp_path):
    repo, event = _dirty_repo(tmp_path)
    refresh = repo.create_event_refresh(event.event_id, requested_by="analyst")

    llm = Mock()
    llm.chat_completion = AsyncMock(return_value={
        "content": '{"title":"E1 refreshed","summary":"v2 narrative"}',
        "model": "transport-model",
    })
    executor = EventRefreshExecutor(_FakeCppBackend(tmp_path), llm, Mock())
    await executor._execute(refresh.refresh_id, "A", repo.db_path)

    # §10: the LLM saw the frozen envelope only — one call, built from the
    # persisted input (no re-resolve, no live re-selection).
    llm.chat_completion.assert_awaited_once()
    system_prompt, user_prompt = llm.chat_completion.await_args.args
    envelope = json.loads(refresh.input_envelope_json)
    assert envelope["event_id"] in user_prompt

    result = repo.get_event_refresh(refresh.refresh_id)
    assert result.status is EventRefreshStatus.completed
    assert result.produced_version == 2
    assert result.model == "transport-model"

    # E8: v1 kept verbatim, v2 appended — history is append-only.
    versions = repo.list_event_versions(event.event_id)
    assert [v.version for v in versions] == [1, 2]
    assert versions[0].summary == "v1 narrative"
    assert versions[1].summary == "v2 narrative"

    # §1 step 13: the authoritative server state decides — clean now.
    updated = repo.get_event(event.event_id)
    assert updated.needs_refresh is False
    assert updated.current_version == 2
    assert updated.title == "E1 refreshed"

    # §12: the completed refresh is the provenance of version 2.
    assert result.base_version == 1
    assert result.input_hash
    assert repo.get_event(event.event_id).event_id == envelope["event_id"]


def test_version_rows_reject_update_and_delete_at_db_level(tmp_path):
    """E8 hard guarantee: triggers, not conventions, protect the history."""
    repo, event = _dirty_repo(tmp_path)
    with sqlite3.connect(repo.db_path) as conn:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(
                "UPDATE investigation_event_versions SET summary='tampered' "
                "WHERE event_id = ?", [event.event_id],
            )
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(
                "DELETE FROM investigation_event_versions WHERE event_id = ?",
                [event.event_id],
            )
