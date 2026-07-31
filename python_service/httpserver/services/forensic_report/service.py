from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Iterable

from .models import AdapterWarning, ReportStatus, ScopeType
from .ids import safe_segment
from .search_index import SnapshotSearchIndex

logger = logging.getLogger(__name__)


class ForensicReportService:
    """Coordinates durable report metadata with in-process generation handles."""

    def __init__(
        self,
        repository: Any,
        resolver: Any,
        writer: Any,
        adapters: Iterable[Any],
    ):
        self.repository = repository
        self.resolver = resolver
        self.writer = writer
        self.adapters = list(adapters)
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._workers: dict[str, asyncio.Task[Path]] = {}
        self._starts: set[asyncio.Task[Any]] = set()
        self._lifecycle_lock = asyncio.Lock()
        self._accepting_starts = True
        self._shutdown_task: asyncio.Task[None] | None = None

    async def initialize(self) -> None:
        async with self._lifecycle_lock:
            shutdown_task = self._shutdown_task
        if shutdown_task is not None:
            await asyncio.shield(shutdown_task)
            async with self._lifecycle_lock:
                if self._shutdown_task is shutdown_task:
                    self._shutdown_task = None
                    self._accepting_starts = True
        await self.resume_unfinished()

    async def shutdown(self) -> None:
        async with self._lifecycle_lock:
            if self._shutdown_task is None:
                self._accepting_starts = False
                self._shutdown_task = asyncio.create_task(self._drain_shutdown())
            shutdown_task = self._shutdown_task
        await asyncio.shield(shutdown_task)

    async def _drain_shutdown(self) -> None:
        async with self._lifecycle_lock:
            starts = tuple(self._starts)
        for start in starts:
            start.cancel()
        if starts:
            await asyncio.gather(*starts, return_exceptions=True)

        while True:
            async with self._lifecycle_lock:
                pending = tuple(self._tasks.items())
            if not pending:
                return
            for _, task in pending:
                if not task.done():
                    task.cancel()
            await asyncio.gather(
                *(task for _, task in pending), return_exceptions=True
            )
            async with self._lifecycle_lock:
                for report_id, task in pending:
                    if self._tasks.get(report_id) is task:
                        self._tasks.pop(report_id, None)

    async def resume_unfinished(self) -> None:
        for version in self.repository.list_unfinished():
            self._fail_if_unfinished(
                version.report_id,
                "service_restart",
                "generation interrupted by service restart; create a new version",
            )

    async def start(self, scope_type: ScopeType, scope_id: str):
        if scope_type is ScopeType.CASE:
            raise NotImplementedError("case report generation is not implemented")

        current = asyncio.current_task()
        if current is None:  # pragma: no cover - async entry always owns a task
            raise RuntimeError("report start requires an asyncio task")
        async with self._lifecycle_lock:
            if not self._accepting_starts:
                raise RuntimeError("report service is not accepting new starts")
            self._starts.add(current)
        try:
            resolved = await self._resolve(scope_type, scope_id)
            async with self._lifecycle_lock:
                if not self._accepting_starts:
                    raise RuntimeError("report service is not accepting new starts")
                version = self.repository.create_version(
                    scope_type, scope_id, resolved.title, resolved.task_ids
                )
                task = asyncio.create_task(self._generate(version.report_id, resolved))
                self._tasks[version.report_id] = task
                task.add_done_callback(
                    lambda completed: self._discard_completed(version.report_id, completed)
                )
                return version
        finally:
            async with self._lifecycle_lock:
                self._starts.discard(current)

    async def _resolve(self, scope_type: ScopeType, scope_id: str):
        if scope_type is ScopeType.TASK:
            return await self.resolver.resolve_task(scope_id)
        raise NotImplementedError("case report generation is not implemented")

    async def _generate(self, report_id: str, resolved: Any) -> None:
        stage = "snapshot"
        worker: asyncio.Task[Path] | None = None
        try:
            self.repository.mark_generating(report_id, stage)
            version = self.repository.get(report_id)
            if version is None:  # pragma: no cover - repository guarantees creation
                raise KeyError(report_id)
            worker = asyncio.create_task(
                asyncio.to_thread(
                    self.writer.write,
                    version=version,
                    title=resolved.title,
                    case_description=resolved.case_description,
                    evidence=resolved.evidence,
                    contexts=resolved.contexts,
                    adapters=self.adapters,
                    analysis=resolved.analysis,
                )
            )
            async with self._lifecycle_lock:
                self._workers[report_id] = worker
            final_dir = await asyncio.shield(worker)
            final_dir = Path(final_dir)
            manifest_path = self._confined_report_path(
                final_dir / "manifest.json", final_dir
            )
            manifest = json.loads(manifest_path.read_text("utf-8"))
            self.repository.mark_ready(
                report_id,
                str(manifest_path.relative_to(self._report_root())),
                [
                    AdapterWarning.model_validate(item)
                    for item in manifest.get("warnings", [])
                ],
            )
        except asyncio.CancelledError:
            if worker is not None:
                try:
                    await self._await_worker_cleanup(worker)
                except Exception:
                    logger.exception("Snapshot worker failed while shutting down %s", report_id)
            self._fail_if_unfinished(
                report_id,
                "shutdown",
                "generation cancelled during service shutdown",
            )
            raise
        except Exception as exc:
            logger.exception("Report generation failed for %s", report_id)
            self._fail_if_unfinished(report_id, stage, str(exc))
            raise
        finally:
            if worker is not None:
                async with self._lifecycle_lock:
                    if self._workers.get(report_id) is worker:
                        self._workers.pop(report_id, None)

    async def _await_worker_cleanup(self, worker: asyncio.Task[Path]) -> None:
        cleanup = asyncio.current_task()
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                if cleanup is None:  # pragma: no cover - async cleanup owns a task
                    raise
                cleanup.uncancel()

    def _discard_completed(self, report_id: str, task: asyncio.Task[None]) -> None:
        async def discard() -> None:
            async with self._lifecycle_lock:
                if self._tasks.get(report_id) is task:
                    self._tasks.pop(report_id, None)

        try:
            exception = task.exception()
        except asyncio.CancelledError:
            exception = None
        if exception is not None:
            logger.error(
                "Report task failed unexpectedly: %s",
                report_id,
                exc_info=(type(exception), exception, exception.__traceback__),
            )
        asyncio.create_task(discard())

    def _fail_if_unfinished(self, report_id: str, stage: str, error: str) -> None:
        try:
            self.repository.mark_failed(report_id, stage, error)
        except (KeyError, ValueError):
            # A concurrent terminal transition wins and must remain immutable.
            return
        except Exception:
            logger.exception("Failed to record report generation failure for %s", report_id)

    def get_status(self, report_id: str):
        return self.repository.get(report_id)

    def list_versions(self, scope_type: ScopeType, scope_id: str):
        return self.repository.list_versions(scope_type, scope_id)

    def _report_root(self) -> Path:
        return Path(self.writer.report_root).resolve()

    def _expected_ready_dir(self, version: Any) -> Path:
        manifest_path = Path(version.manifest_path or "")
        if manifest_path.is_absolute() or manifest_path.name != "manifest.json":
            raise ValueError("report path must remain confined to report root")
        return (self._report_root() / manifest_path).parent

    @staticmethod
    def _reject_symlinks(path: Path, root: Path) -> None:
        try:
            relative = path.relative_to(root)
        except ValueError as exc:
            raise ValueError("report path must remain confined to report root") from exc
        current = root
        if current.is_symlink():
            raise ValueError("report path must remain confined to report root")
        for segment in relative.parts:
            current /= segment
            if current.is_symlink():
                raise ValueError("report path must remain confined to report root")

    def _confined_report_path(
        self, path: Path, report_dir: Path, *, must_exist: bool = True
    ) -> Path:
        self._reject_symlinks(path, report_dir)
        try:
            resolved = path.resolve(strict=must_exist)
            resolved.relative_to(report_dir)
        except (OSError, ValueError) as exc:
            raise ValueError("report path must remain confined to report root") from exc
        return resolved

    def _ready_manifest_path(self, report_id: str) -> Path:
        version = self.repository.get(report_id)
        if version is None:
            raise KeyError(report_id)
        if version.status is not ReportStatus.READY:
            raise RuntimeError(f"report is not ready: {version.status.value}")
        if not version.manifest_path:
            raise ValueError("ready report has no manifest path")
        report_dir = self._expected_ready_dir(version)
        relative = Path(version.manifest_path)
        manifest_path = self._report_root() / relative
        confined = self._confined_report_path(manifest_path, report_dir)
        expected_report_dir = (
            self._report_root()
            / version.scope_type.value
            / safe_segment(version.scope_id)
            / safe_segment(version.report_id)
        )
        if report_dir != expected_report_dir:
            # Compatibility with legacy pre-slug paths is permitted only when
            # their directory segment still identifies this exact report ID.
            if report_dir.name != version.report_id:
                raise ValueError("report path must remain confined to report root")
        return confined

    def _ready_dir(self, report_id: str) -> Path:
        return self._ready_manifest_path(report_id).parent

    def get_manifest_path(self, report_id: str) -> Path:
        return self._ready_manifest_path(report_id)

    def get_page_path(self, report_id: str, category_id: str, page: int) -> Path:
        manifest_path = self._ready_manifest_path(report_id)
        manifest = json.loads(manifest_path.read_text("utf-8"))
        category = next(
            (
                item
                for item in manifest.get("categories", [])
                if item.get("category_id") == category_id
            ),
            None,
        )
        if category is None or page < 1 or page > len(category.get("page_paths", [])):
            raise KeyError(f"unknown category page: {category_id}/{page}")
        relative = Path(category["page_paths"][page - 1])
        if relative.is_absolute():
            raise ValueError("report path must remain confined to report root")
        return self._confined_report_path(manifest_path.parent / relative, manifest_path.parent)

    def search(self, report_id: str, query: str, offset: int, limit: int):
        ready_dir = self._ready_dir(report_id)
        search_path = self._confined_report_path(
            ready_dir / "search.sqlite3", ready_dir, must_exist=False
        )
        if not search_path.is_file():
            raise FileNotFoundError("report search index is missing")
        return SnapshotSearchIndex.open_readonly(search_path).search(query, offset, limit)
