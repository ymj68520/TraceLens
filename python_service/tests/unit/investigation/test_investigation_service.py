"""Tests for InvestigationCaptureService (Phase C3 orchestration)."""

import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from httpserver.services.evidence import (
    EvidenceNotFoundError,
    EvidenceStoreError,
    ResolvedEvidence,
)
from httpserver.services.investigation import InvestigationCaptureService


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
        "INSERT INTO files(path,name,size) VALUES(?,?,?)", ("/case/a.txt", "a.txt", 1)
    )
    conn.commit()
    conn.close()


def _resolved(db_path, task_id="A"):
    return ResolvedEvidence(
        task_id=task_id,
        evidence_key="file:/case/a.txt",
        evidence_type="file",
        normalized_path="/case/a.txt",
        source_db=db_path,
    )


@pytest.mark.asyncio
async def test_capture_uses_resolver_then_second_task_lookup(tmp_path):
    files_db = str(tmp_path / "files.db")
    _make_files_db(files_db)
    task = {"id": "A", "output_files_db": files_db}
    backend = SimpleNamespace(get_task=AsyncMock(side_effect=[task, task]))
    resolver = Mock()

    async def resolve_with_trusted_lookup(task_id, evidence_key):
        trusted_task = await backend.get_task(task_id)
        assert trusted_task["id"] == task_id
        return _resolved(files_db)

    resolver.resolve_evidence = AsyncMock(side_effect=resolve_with_trusted_lookup)

    result = await InvestigationCaptureService(backend, resolver).capture("A", "file:/case/a.txt")

    assert result.evidence_key == "file:/case/a.txt"
    assert backend.get_task.await_count == 2
    resolver.resolve_evidence.assert_awaited_once_with("A", "file:/case/a.txt")


@pytest.mark.asyncio
async def test_capture_second_task_lookup_missing_fails_before_repository(tmp_path):
    files_db = str(tmp_path / "files.db")
    _make_files_db(files_db)
    backend = SimpleNamespace(get_task=AsyncMock(side_effect=[{"id": "A", "output_files_db": files_db}, None]))
    resolver = Mock()

    async def resolve_with_trusted_lookup(task_id, evidence_key):
        trusted_task = await backend.get_task(task_id)
        assert trusted_task["id"] == task_id
        return _resolved(files_db)

    resolver.resolve_evidence = AsyncMock(side_effect=resolve_with_trusted_lookup)

    with pytest.raises(EvidenceNotFoundError):
        await InvestigationCaptureService(backend, resolver).capture("A", "file:/case/a.txt")
    assert not (tmp_path / "investigation.db").exists()


@pytest.mark.asyncio
async def test_capture_task_directory_failure_propagates(tmp_path):
    files_db = str(tmp_path / "files.db")
    _make_files_db(files_db)
    backend = SimpleNamespace(get_task=AsyncMock(side_effect=[
        {"id": "A", "output_files_db": files_db, "output_events_db": str(tmp_path / "other" / "events.db")},
        {"id": "A", "output_files_db": files_db, "output_events_db": str(tmp_path / "other" / "events.db")},
    ]))
    resolver = Mock()
    resolver.resolve_evidence = AsyncMock(return_value=_resolved(files_db))

    with pytest.raises(EvidenceStoreError):
        await InvestigationCaptureService(backend, resolver).capture("A", "file:/case/a.txt")


@pytest.mark.asyncio
async def test_capture_resolver_errors_propagate_without_second_lookup():
    backend = SimpleNamespace(get_task=AsyncMock())
    resolver = Mock()
    resolver.resolve_evidence = AsyncMock(side_effect=EvidenceStoreError("source unavailable"))

    with pytest.raises(EvidenceStoreError):
        await InvestigationCaptureService(backend, resolver).capture("A", "file:/x")
    backend.get_task.assert_not_awaited()
