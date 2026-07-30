from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace
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


async def _wait_for_terminal(service: ForensicReportService, report_id: str):
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
async def test_shutdown_waits_for_blocking_snapshot_worker(tmp_path: Path):
    started = threading.Event()
    release = threading.Event()

    class BlockingWriter:
        report_root = tmp_path / "snapshots"

        def write(self, **kwargs):
            started.set()
            assert release.wait(timeout=5)
            return tmp_path / "snapshots" / "unreachable"

    resolver = AsyncMock()
    resolver.resolve_task.return_value = _resolved_task()
    service = ForensicReportService(
        repository=ReportRepository(tmp_path / "reports.db"),
        resolver=resolver,
        writer=BlockingWriter(),
        adapters=[],
    )
    await service.start(ScopeType.TASK, "task-1")
    await asyncio.to_thread(started.wait)

    shutdown = asyncio.create_task(service.shutdown())
    for _ in range(10):
        await asyncio.sleep(0)
    assert not shutdown.done()
    release.set()
    await shutdown


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
async def test_shutdown_rejects_new_starts_and_cancels_a_start_already_resolving(tmp_path: Path):
    entered = asyncio.Event()
    release = asyncio.Event()

    async def resolve_task(task_id: str):
        entered.set()
        await release.wait()
        return _resolved_task()

    resolver = SimpleNamespace(resolve_task=resolve_task)
    service = _service(tmp_path, resolver)
    in_flight = asyncio.create_task(service.start(ScopeType.TASK, "task-1"))
    await entered.wait()

    shutdown = asyncio.create_task(service.shutdown())
    await asyncio.sleep(0)
    with pytest.raises(RuntimeError, match="not accepting"):
        await asyncio.wait_for(service.start(ScopeType.TASK, "task-2"), timeout=0.01)

    release.set()
    with pytest.raises(asyncio.CancelledError):
        await in_flight
    await shutdown
    assert service.repository.list_versions(ScopeType.TASK, "task-1") == []
    with pytest.raises(RuntimeError, match="not accepting"):
        await service.start(ScopeType.TASK, "task-3")


@pytest.mark.asyncio
async def test_case_reports_are_explicitly_unsupported_before_version_allocation(
    tmp_path: Path,
):
    service = _service(tmp_path)

    with pytest.raises(NotImplementedError, match="case report generation is not implemented"):
        await service.start(ScopeType.CASE, "case-1")

    assert service.repository.list_versions(ScopeType.CASE, "case-1") == []


@pytest.mark.asyncio
async def test_ready_paths_reject_corrupt_manifest_page_and_search_symlink(tmp_path: Path):
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
                    {"category_id": "contacts", "page_paths": ["../../outside.json"]}
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

    outside = tmp_path / "outside.sqlite3"
    outside.touch()
    (report_dir / "search.sqlite3").symlink_to(outside)
    with pytest.raises(ValueError, match="confined"):
        service.search(safe_version.report_id, "contact", 0, 10)


@pytest.mark.asyncio
async def test_original_writer_error_is_logged_when_failure_transition_breaks(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    class BrokenRepository(ReportRepository):
        def mark_failed(self, report_id: str, stage: str, error: str) -> None:
            raise RuntimeError("transition database failure")

    class FailingWriter:
        report_root = tmp_path / "snapshots"

        def write(self, **kwargs):
            raise OSError("original writer failure")

    resolver = AsyncMock()
    resolver.resolve_task.return_value = _resolved_task()
    service = ForensicReportService(
        repository=BrokenRepository(tmp_path / "reports.db"),
        resolver=resolver,
        writer=FailingWriter(),
        adapters=[],
    )
    version = await service.start(ScopeType.TASK, "task-1")
    with pytest.raises(OSError, match="original writer failure"):
        await asyncio.shield(service._tasks[version.report_id])

    assert "original writer failure" in caplog.text
    assert "transition database failure" in caplog.text


def test_report_access_distinguishes_unknown_from_not_ready(tmp_path: Path):
    service = _service(tmp_path)
    version = service.repository.create_version(ScopeType.TASK, "task-1", "Task", [])

    assert service.get_status("missing") is None
    with pytest.raises(KeyError, match="missing"):
        service.get_manifest_path("missing")
    with pytest.raises(RuntimeError, match="not ready"):
        service.get_manifest_path(version.report_id)
