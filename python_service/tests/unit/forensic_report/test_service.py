from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from httpserver.services.forensic_report.models import ReportStatus, ScopeType
from httpserver.services.forensic_report.repository import ReportRepository
from httpserver.services.forensic_report.service import ForensicReportService
from httpserver.services.forensic_report.snapshot_writer import SnapshotWriter
from httpserver.services.forensic_report.source_resolver import ResolvedScope


def _resolved_task() -> ResolvedScope:
    return ResolvedScope(
        scope_type=ScopeType.TASK,
        scope_id="task-1",
        title="Task report",
        case_description="",
        task_ids=["task-1"],
        evidence=[],
        contexts=[],
        analysis={},
    )


def _service(tmp_path: Path, resolver: AsyncMock | None = None) -> ForensicReportService:
    return ForensicReportService(
        repository=ReportRepository(tmp_path / "reports.db"),
        resolver=resolver or AsyncMock(),
        writer=SnapshotWriter(tmp_path / "snapshots", "test"),
        adapters=[],
    )


async def _wait_for_terminal(
    service: ForensicReportService, report_id: str
):
    task = service._tasks[report_id]
    await asyncio.shield(task)
    status = service.get_status(report_id)
    assert status is not None
    return status


@pytest.mark.asyncio
async def test_generation_reaches_ready_and_is_recoverable_from_repository(tmp_path: Path):
    resolver = AsyncMock()
    resolver.resolve_task.return_value = _resolved_task()
    service = _service(tmp_path, resolver)

    await service.initialize()
    version = await service.start(ScopeType.TASK, "task-1")

    status = await _wait_for_terminal(service, version.report_id)
    assert status.status is ReportStatus.READY
    assert service.repository.get(version.report_id).manifest_path.endswith("manifest.json")
    await service.shutdown()


@pytest.mark.asyncio
async def test_initialize_fails_interrupted_versions_with_restart_reason(tmp_path: Path):
    service = _service(tmp_path)
    queued = service.repository.create_version(ScopeType.TASK, "queued", "Queued", [])
    generating = service.repository.create_version(
        ScopeType.TASK, "generating", "Generating", []
    )
    service.repository.mark_generating(generating.report_id, "snapshot")

    await service.initialize()

    for version in (queued, generating):
        recovered = service.get_status(version.report_id)
        assert recovered.status is ReportStatus.FAILED
        assert recovered.stage == "service_restart"
        assert recovered.error == (
            "generation interrupted by service restart; create a new version"
        )


@pytest.mark.asyncio
async def test_shutdown_marks_cancelled_generation_failed_without_overwriting_terminal(
    tmp_path: Path,
):
    resolver = AsyncMock()
    resolver.resolve_task.return_value = _resolved_task()
    service = _service(tmp_path, resolver)
    version = await service.start(ScopeType.TASK, "task-1")

    await service.shutdown()

    status = service.get_status(version.report_id)
    assert status.status is ReportStatus.FAILED
    assert status.stage == "shutdown"


@pytest.mark.asyncio
async def test_shutdown_preserves_a_concurrent_terminal_transition(tmp_path: Path):
    service = _service(tmp_path)
    version = service.repository.create_version(ScopeType.TASK, "task-1", "Task", [])
    terminal = asyncio.Event()

    async def finish_as_ready():
        await terminal.wait()

    task = asyncio.create_task(finish_as_ready())
    service._tasks[version.report_id] = task
    service.repository.mark_ready(version.report_id, "task/manifest.json", [])
    terminal.set()

    await service.shutdown()

    assert service.get_status(version.report_id).status is ReportStatus.READY


@pytest.mark.asyncio
async def test_ready_paths_reject_corrupt_manifest_and_page_traversal(tmp_path: Path):
    service = _service(tmp_path)
    version = service.repository.create_version(ScopeType.TASK, "task-1", "Task", [])
    service.repository.mark_ready(version.report_id, "../outside/manifest.json", [])

    with pytest.raises(ValueError, match="confined"):
        service.get_manifest_path(version.report_id)

    safe_version = service.repository.create_version(ScopeType.TASK, "task-2", "Task", [])
    report_dir = tmp_path / "snapshots" / "task" / "task-2" / safe_version.report_id
    report_dir.mkdir(parents=True)
    (report_dir / "manifest.json").write_text(
        json.dumps(
            {
                "categories": [
                    {
                        "category_id": "contacts",
                        "page_paths": ["../../outside.json"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    service.repository.mark_ready(
        safe_version.report_id,
        str((report_dir / "manifest.json").relative_to(service.writer.report_root)),
        [],
    )

    with pytest.raises(ValueError, match="confined"):
        service.get_page_path(safe_version.report_id, "contacts", 1)

    with pytest.raises(FileNotFoundError, match="search index"):
        service.search(safe_version.report_id, "contact", 0, 10)
    assert not (report_dir / "search.sqlite3").exists()


def test_report_access_distinguishes_unknown_from_not_ready(tmp_path: Path):
    service = _service(tmp_path)
    version = service.repository.create_version(ScopeType.TASK, "task-1", "Task", [])

    assert service.get_status("missing") is None
    with pytest.raises(KeyError, match="missing"):
        service.get_manifest_path("missing")
    with pytest.raises(RuntimeError, match="not ready"):
        service.get_manifest_path(version.report_id)
