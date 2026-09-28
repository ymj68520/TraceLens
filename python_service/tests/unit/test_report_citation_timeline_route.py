"""Exact report-scoped Investigation timeline contract."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from httpserver.routes import investigation_workbench
from httpserver.services.evidence import EvidenceNotFoundError


def _manager():
    manager = Mock()
    manager.investigation_event_service.file_timeline = AsyncMock(return_value={
        "task_id": "T1",
        "files": [
            {"path": "/case/a.txt", "latest_time": 100},
            {"path": "/case/unrelated.txt", "latest_time": 300},
            {"path": "/case/b.txt", "latest_time": 200},
        ],
        "total_count": 501,
        "axis": {"start": 1, "end": 300},
        "scope": {"limited": True},
    })
    return manager


@pytest.mark.asyncio
async def test_report_timeline_contains_only_exact_cited_files(monkeypatch):
    manifest = SimpleNamespace(
        sections=(
            SimpleNamespace(citation_ids=("c001", "c002")),
            SimpleNamespace(citation_ids=("c003",)),
        ),
        citations=(
            SimpleNamespace(citation_id="c001", evidence_key="file:/case/a.txt"),
            SimpleNamespace(citation_id="c002", evidence_key="file:/case/b.txt"),
            SimpleNamespace(citation_id="c003", evidence_key="file:/case/a.txt"),
            SimpleNamespace(citation_id="unused", evidence_key="file:/case/unrelated.txt"),
        ),
    )
    strict = AsyncMock(return_value=(SimpleNamespace(report_id="rep-1"), manifest))
    monkeypatch.setattr(investigation_workbench, "_strict_report", strict)
    manager = _manager()

    result = await investigation_workbench.workbench_file_timeline(
        "T1", ensure_path="/case/unrelated.txt", report_id="rep-1", manager=manager
    )

    strict.assert_awaited_once_with("T1", "rep-1")
    manager.investigation_event_service.file_timeline.assert_awaited_once_with(
        "T1", ensure_paths=("/case/a.txt", "/case/b.txt")
    )
    assert [item["path"] for item in result["files"]] == ["/case/a.txt", "/case/b.txt"]
    assert result["citation_ids_by_path"] == {
        "/case/a.txt": ["c001", "c003"],
        "/case/b.txt": ["c002"],
    }
    assert result["total_count"] == 2
    assert result["axis"] == {"start": 100, "end": 200}
    assert result["scope"]["report_id"] == "rep-1"
    assert result["scope"]["limited"] is False


@pytest.mark.asyncio
async def test_legacy_timeline_without_report_id_is_unchanged(monkeypatch):
    strict = AsyncMock()
    monkeypatch.setattr(investigation_workbench, "_strict_report", strict)
    manager = _manager()

    result = await investigation_workbench.workbench_file_timeline(
        "T1", ensure_path="/case/b.txt", manager=manager
    )

    strict.assert_not_awaited()
    manager.investigation_event_service.file_timeline.assert_awaited_once_with(
        "T1", ensure_paths=("/case/b.txt",)
    )
    assert result["total_count"] == 501


@pytest.mark.asyncio
async def test_foreign_or_missing_report_id_never_falls_back_to_all_files(monkeypatch):
    monkeypatch.setattr(
        investigation_workbench, "_strict_report",
        AsyncMock(side_effect=EvidenceNotFoundError("report not found")),
    )
    manager = _manager()

    with pytest.raises(HTTPException) as error:
        await investigation_workbench.workbench_file_timeline(
            "T1", report_id="foreign-report", manager=manager
        )

    assert error.value.status_code == 404
    manager.investigation_event_service.file_timeline.assert_not_awaited()
