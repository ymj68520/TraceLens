"""C7c-2 Event Refresh execution and atomic completion tests."""

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
    StructuredEventRefreshOutputError,
    parse_event_refresh_envelope,
    parse_event_refresh_response,
)

KEY = "file:/case/a.txt"


class FakeCppBackend:
    """Minimal cpp_backend answering live-task lookups for executor tests."""

    def __init__(self, task_id: str, task_dir: Path):
        self._task_id = task_id
        self._task_dir = task_dir

    async def get_task(self, task_id):
        if task_id != self._task_id:
            return None
        return {
            "id": task_id,
            "output_files_db": str(self._task_dir / "files.db"),
            "output_events_db": str(self._task_dir / "events.db"),
        }

    async def list_tasks(self, page=1, page_size=100, status=None):
        return {"tasks": [{"id": self._task_id}]}


def _repo(tmp_path: Path, task_id: str = "A"):
    files_db = tmp_path / "files.db"
    idb = tmp_path / "investigation.db"
    conn = sqlite3.connect(files_db)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS files (path TEXT, name TEXT, extension TEXT, category TEXT, type TEXT, "
        "size INTEGER, mtime INTEGER, ctime INTEGER, is_deleted INTEGER, md5 TEXT, "
        "llm_summary TEXT, llm_description TEXT, llm_keywords TEXT, llm_analyzed_at INTEGER, "
        "llm_model_used TEXT, scene_type TEXT, scene_priority INTEGER, scene_relevant INTEGER)"
    )
    conn.execute("INSERT INTO files(path,llm_description,size) VALUES('/case/a.txt','desc',1)")
    conn.commit(); conn.close()
    repo = InvestigationRepository(idb, task_id)
    snapshot = repo.capture_if_absent(ResolvedEvidence(
        task_id=task_id, evidence_key=KEY, evidence_type="file",
        normalized_path="/case/a.txt", source_db=str(files_db),
    ))
    return repo, snapshot


def _accept(repo, snapshot):
    analysis = repo.create_analysis(snapshot, prompt_version="investigation-evidence-analysis:v2")
    repo.transition(analysis.analysis_id, SecondaryAnalysisStatus.running)
    repo.transition(
        analysis.analysis_id, SecondaryAnalysisStatus.review_pending,
        description="accepted description", summary="accepted summary", model="analysis-model",
    )
    return repo.review_analysis(
        analysis.analysis_id, decision=AnalysisReviewDecision.accepted, reviewer="reviewer"
    )


def test_fail_event_refresh_preserves_dirty_and_no_version(tmp_path):
    repo, _ = _repo(tmp_path)
    event = repo.create_event("old")
    refresh = repo.create_event_refresh(event.event_id)
    repo.claim_event_refresh(refresh.refresh_id)
    failed = repo.fail_event_refresh(
        refresh.refresh_id,
        error_code="llm_empty_response",
        error_message="LLM returned empty response",
        model="m",
    )
    assert failed.status == EventRefreshStatus.failed
    assert failed.model == "m"
    assert repo.get_event(event.event_id).needs_refresh is False
    assert len(repo.list_event_versions(event.event_id)) == 1


def test_completed_and_failed_rows_are_terminal(tmp_path):
    repo, _ = _repo(tmp_path)
    event = repo.create_event("old")
    refresh = repo.create_event_refresh(event.event_id)
    repo.fail_event_refresh(refresh.refresh_id, error_code="x", error_message="y")
    assert repo.fail_event_refresh(refresh.refresh_id, error_code="z", error_message="z").error_code == "x"


def test_new_admission_is_executable_v2(tmp_path):
    repo, _ = _repo(tmp_path)
    event = repo.create_event("old title", summary="old summary")
    refresh = repo.create_event_refresh(event.event_id, requested_by="analyst")
    envelope = parse_event_refresh_envelope(refresh.input_envelope_json)
    assert envelope.schema_version == 2
    assert envelope.prompt_version == "investigation-event-refresh:v1"


def test_repository_claim_and_atomic_completion_clears_dirty(tmp_path):
    repo, snapshot = _repo(tmp_path)
    event = repo.create_event("old")
    repo.link_event_evidence(event.event_id, KEY)
    _accept(repo, snapshot)
    refresh = repo.create_event_refresh(event.event_id)
    claimed = repo.claim_event_refresh(refresh.refresh_id)
    assert claimed.status == EventRefreshStatus.running
    assert repo.claim_event_refresh(refresh.refresh_id) is None

    completed = repo.complete_event_refresh(
        refresh.refresh_id, title="new title", summary="new summary", model="refresh-model"
    )
    assert completed.status == EventRefreshStatus.completed
    assert completed.produced_version == 2
    assert completed.model == "refresh-model"
    assert repo.get_event(event.event_id).needs_refresh is False
    versions = repo.list_event_versions(event.event_id)
    assert [(v.version, v.title, v.created_by) for v in versions] == [
        (1, "old", None), (2, "new title", None)
    ]


def test_base_version_conflict_commits_failed_without_version(tmp_path):
    repo, _ = _repo(tmp_path)
    event = repo.create_event("old")
    refresh = repo.create_event_refresh(event.event_id)
    repo.claim_event_refresh(refresh.refresh_id)
    conn = sqlite3.connect(repo.db_path)
    conn.execute(
        "INSERT INTO investigation_event_versions(task_id,event_id,version,title,summary,created_at,created_by) "
        "VALUES('A',?,?,?,?,'later',NULL)",
        [event.event_id, 2, "concurrent", None],
    )
    conn.commit(); conn.close()

    result = repo.complete_event_refresh(
        refresh.refresh_id, title="must not write", summary="must not write", model="m"
    )
    assert result.status == EventRefreshStatus.failed
    assert result.error_code == "base_version_changed"
    assert repo.get_event(event.event_id).current_version == 2
    assert len(repo.list_event_versions(event.event_id)) == 2


def test_new_accepted_analysis_after_admission_keeps_dirty(tmp_path):
    repo, snapshot = _repo(tmp_path)
    event = repo.create_event("old")
    repo.link_event_evidence(event.event_id, KEY)
    first = _accept(repo, snapshot)
    refresh = repo.create_event_refresh(event.event_id)
    repo.claim_event_refresh(refresh.refresh_id)
    second = _accept(repo, snapshot)
    assert second.version > first.version
    completed = repo.complete_event_refresh(
        refresh.refresh_id, title="new", summary="new", model="m"
    )
    assert completed.status == EventRefreshStatus.completed
    assert repo.get_event(event.event_id).needs_refresh is True


@pytest.mark.parametrize("content", [
    "```json {\"title\":\"t\",\"summary\":\"s\"}```",
    "prefix {\"title\":\"t\",\"summary\":\"s\"}",
    '{"title":"t","title":"x","summary":"s"}',
    '{"title":"t","summary":NaN}',
    '{"title":"t","summary":"s","extra":1}',
    '{"title":"","summary":"s"}',
    '{"title":"t","summary":""}',
])
def test_refresh_output_is_strict(content):
    with pytest.raises(StructuredEventRefreshOutputError):
        parse_event_refresh_response(content)


@pytest.mark.asyncio
async def test_executor_consumes_frozen_envelope_and_completes(tmp_path):
    repo, _ = _repo(tmp_path)
    event = repo.create_event("old")
    refresh = repo.create_event_refresh(event.event_id)
    llm = Mock()
    llm.chat_completion = AsyncMock(return_value={
        "content": '{"title":"generated","summary":"generated summary"}',
        "model": "transport-model",
    })
    executor = EventRefreshExecutor(
        FakeCppBackend("A", tmp_path), llm, Mock()
    )
    await executor._execute(refresh.refresh_id, "A", repo.db_path)
    result = repo.get_event_refresh(refresh.refresh_id)
    assert result.status == EventRefreshStatus.completed
    assert result.model == "transport-model"
    assert repo.get_event(event.event_id).title == "generated"
    llm.chat_completion.assert_awaited_once()


def test_historical_v1_is_readable_but_not_executable(tmp_path):
    repo, _ = _repo(tmp_path)
    event = repo.create_event("old")
    refresh = repo.create_event_refresh(event.event_id)
    envelope = json.loads(refresh.input_envelope_json)
    envelope.pop("prompt_version")
    envelope["schema_version"] = 1
    historical = parse_event_refresh_envelope(
        json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    assert historical.schema_version == 1
    assert not hasattr(historical, "prompt_version")
