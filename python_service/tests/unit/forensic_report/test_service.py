from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from httpserver.services.forensic_report.ids import safe_segment
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
        task_ids=["task-1"],
        evidence=[],
        contexts=[],
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
async def test_initialize_reopens_starts_after_a_completed_shutdown(tmp_path: Path):
    resolver = AsyncMock()
    resolver.resolve_task.return_value = _resolved_task()
    service = _service(tmp_path, resolver)

    await service.shutdown()
    await service.initialize()
    version = await service.start(ScopeType.TASK, "task-1")

    assert (await _wait_for_terminal(service, version.report_id)).status is ReportStatus.READY


@pytest.mark.concurrency
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


@pytest.mark.concurrency
@pytest.mark.asyncio
async def test_concurrent_shutdowns_share_worker_drain_and_repeated_shutdown_is_safe(
    tmp_path: Path,
):
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    class BlockingWriter:
        report_root = tmp_path / "snapshots"

        def write(self, **kwargs):
            started.set()
            assert release.wait(timeout=5)
            finished.set()
            return tmp_path / "snapshots" / "unreachable"

    resolver = AsyncMock()
    resolver.resolve_task.return_value = _resolved_task()
    service = ForensicReportService(
        repository=ReportRepository(tmp_path / "reports.db"),
        resolver=resolver,
        writer=BlockingWriter(),
        adapters=[],
    )
    version = await service.start(ScopeType.TASK, "task-1")
    await asyncio.to_thread(started.wait)

    first = asyncio.create_task(service.shutdown())
    for _ in range(10):
        await asyncio.sleep(0)
    second = asyncio.create_task(service.shutdown())
    for _ in range(10):
        await asyncio.sleep(0)
    assert not first.done()
    assert not second.done()

    release.set()
    await asyncio.gather(first, second)

    assert finished.is_set()
    assert service.get_status(version.report_id).status is ReportStatus.FAILED
    assert service._tasks == {}
    assert service._workers == {}
    await service.shutdown()


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


@pytest.mark.concurrency
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
    report_dir = (
        tmp_path
        / "snapshots"
        / "task"
        / safe_segment("task-2")
        / safe_segment(safe_version.report_id)
    )
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


@pytest.mark.asyncio
async def test_writer_failure_persists_sanitized_error_without_paths(tmp_path: Path):
    # R3 §10B: OSError str() embeds absolute filesystem paths, and the
    # persisted error is served verbatim by the version read routes -- the
    # durable failure reason must be the fixed sanitized string, with the
    # raw exception preserved only in the service log.
    class FailingWriter:
        report_root = tmp_path / "snapshots"

        def write(self, **kwargs):
            raise FileNotFoundError(
                f"[Errno 2] No such file or directory: '{tmp_path}/secrets/evidence.sqlite3'"
            )

    resolver = AsyncMock()
    resolver.resolve_task.return_value = _resolved_task()
    service = ForensicReportService(
        repository=ReportRepository(tmp_path / "reports.db"),
        resolver=resolver,
        writer=FailingWriter(),
        adapters=[],
    )
    version = await service.start(ScopeType.TASK, "task-1")
    with pytest.raises(FileNotFoundError):
        await asyncio.shield(service._tasks[version.report_id])

    failed = service.get_status(version.report_id)
    assert failed.status is ReportStatus.FAILED
    assert failed.error == "report generation failed"
    assert str(tmp_path) not in (failed.error or "")



def test_ready_manifest_paths_match_current_writer_layout_and_reject_unrelated_legacy_parent(
    tmp_path: Path,
):
    service = _service(tmp_path)
    version = service.repository.create_version(
        ScopeType.TASK, "task-1", "Task", []
    )
    writer_dir = (
        service.writer.report_root
        / version.scope_type.value
        / safe_segment(version.scope_id)
        / version.report_id
    )
    writer_dir.mkdir(parents=True)
    manifest = writer_dir / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    service.repository.mark_ready(
        version.report_id,
        str(manifest.relative_to(service.writer.report_root)),
        [],
    )

    assert service.get_manifest_path(version.report_id) == manifest.resolve()

    unrelated_version = service.repository.create_version(
        ScopeType.TASK, "task-2", "Task", []
    )
    unrelated = service.writer.report_root / "unrelated" / unrelated_version.report_id
    unrelated.mkdir(parents=True)
    unrelated_manifest = unrelated / "manifest.json"
    unrelated_manifest.write_text("{}", encoding="utf-8")
    service.repository.mark_ready(
        unrelated_version.report_id,
        str(unrelated_manifest.relative_to(service.writer.report_root)),
        [],
    )

    with pytest.raises(ValueError, match="confined"):
        service.get_manifest_path(unrelated_version.report_id)


def test_report_resource_paths_reject_cross_report_symlinks_and_invalid_search_indexes(
    tmp_path: Path,
):
    service = _service(tmp_path)
    first = service.repository.create_version(ScopeType.TASK, "task-1", "One", [])
    second = service.repository.create_version(ScopeType.TASK, "task-2", "Two", [])
    root = service.writer.report_root
    first_dir = root / "task" / safe_segment("task-1") / safe_segment(first.report_id)
    second_dir = root / "task" / safe_segment("task-2") / safe_segment(second.report_id)
    first_dir.mkdir(parents=True)
    second_dir.mkdir(parents=True)
    (second_dir / "manifest.json").write_text(
        json.dumps({"categories": [{"category_id": "contacts", "page_paths": ["page-1.json"]}]}),
        encoding="utf-8",
    )
    (second_dir / "page-1.json").write_text("{}", encoding="utf-8")
    search = second_dir / "search.sqlite3"
    search.write_bytes(b"")
    (first_dir / "manifest.json").symlink_to(second_dir / "manifest.json")
    service.repository.mark_ready(
        first.report_id,
        str((first_dir / "manifest.json").relative_to(root)),
        [],
    )

    with pytest.raises(ValueError, match="confined"):
        service.get_manifest_path(first.report_id)

    (first_dir / "manifest.json").unlink()
    (first_dir / "manifest.json").write_text(
        json.dumps({"categories": [{"category_id": "contacts", "page_paths": ["page-1.json"]}]}),
        encoding="utf-8",
    )
    (first_dir / "page-1.json").symlink_to(second_dir / "page-1.json")
    with pytest.raises(ValueError, match="confined"):
        service.get_page_path(first.report_id, "contacts", 1)

    (first_dir / "page-1.json").unlink()
    (first_dir / "search.sqlite3").symlink_to(search)
    before = search.read_bytes()
    with pytest.raises(Exception):
        service.search(first.report_id, "x", 0, 1)
    assert search.read_bytes() == before

def test_report_access_distinguishes_unknown_from_not_ready(tmp_path: Path):
    service = _service(tmp_path)
    version = service.repository.create_version(ScopeType.TASK, "task-1", "Task", [])

    assert service.get_status("missing") is None
    with pytest.raises(KeyError, match="missing"):
        service.get_manifest_path("missing")
    with pytest.raises(RuntimeError, match="not ready"):
        service.get_manifest_path(version.report_id)
