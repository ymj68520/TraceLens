"""Task-scoped Investigation Event orchestration (Phase C7a).

Read semantics: GET operations never create or initialize investigation.db —
when the task has no investigation.db yet, list returns [] and single-item
reads raise not-found. Only the create path may materialize the store.

Link ordering: the Event existence check happens BEFORE evidence capture so a
request against a nonexistent event produces no persistence side effects.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from ..evidence.exceptions import EvidenceNotFoundError, EvidenceStoreError
from .file_timeline import collect_file_timeline
from .graph_reader import InvestigationGraphReader
from .models import (
    EventEvidenceLink,
    EventRefresh,
    InvestigationEvent,
    InvestigationEventVersion,
)
from .paths import investigation_db_path_for_task
from .repository import InvestigationRepository


class InvestigationEventService:
    """Create and read Investigation Events scoped to one task."""

    def __init__(self, cpp_backend, capture_service):
        self._cpp_backend = cpp_backend
        self._capture_service = capture_service

    async def _resolve_db_path(self, task_id: str) -> Path:
        task = await self._cpp_backend.get_task(task_id)
        if not isinstance(task, dict) or task.get("id") != task_id:
            raise EvidenceNotFoundError("task not found")
        return investigation_db_path_for_task(task)

    async def _reader_for(self, task_id: str) -> InvestigationGraphReader | None:
        """Strict reader for GET paths (C10 §14/E13).

        Returns ``None`` when the task has no investigation.db yet (GET never
        creates it); the mode=ro reader never migrates or self-heals an
        existing store, unlike the write-path repository constructor.
        """
        db_path = await self._resolve_db_path(task_id)
        if not db_path.exists():
            return None
        return InvestigationGraphReader(db_path, task_id)

    async def create_event(
        self,
        task_id: str,
        *,
        title: str,
        summary: str | None = None,
        created_by: str | None = None,
    ) -> InvestigationEvent:
        db_path = await self._resolve_db_path(task_id)
        try:
            repository = InvestigationRepository(db_path, task_id)
            return await asyncio.to_thread(
                repository.create_event, title,
                summary=summary, created_by=created_by,
            )
        except sqlite3.DatabaseError as exc:
            raise EvidenceStoreError(
                "investigation event store is unavailable"
            ) from exc

    async def list_events(
        self, task_id: str, *, needs_refresh: bool | None = None
    ) -> list[InvestigationEvent]:
        reader = await self._reader_for(task_id)
        if reader is None:
            return []
        try:
            return await asyncio.to_thread(
                reader.list_events, needs_refresh=needs_refresh
            )
        except EvidenceStoreError:
            raise
        except sqlite3.DatabaseError as exc:
            raise EvidenceStoreError(
                "investigation event store is unavailable"
            ) from exc

    async def get_event(self, task_id: str, event_id: str) -> InvestigationEvent:
        reader = await self._reader_for(task_id)
        if reader is None:
            raise EvidenceNotFoundError("investigation event not found")
        try:
            event = await asyncio.to_thread(reader.get_event, event_id)
        except EvidenceStoreError:
            raise
        except sqlite3.DatabaseError as exc:
            raise EvidenceStoreError(
                "investigation event store is unavailable"
            ) from exc
        if event is None:
            raise EvidenceNotFoundError("investigation event not found")
        return event

    async def _require_event(
        self, task_id: str, event_id: str
    ) -> InvestigationRepository:
        """Resolve the task, verify the Event exists, return its repository."""
        db_path = await self._resolve_db_path(task_id)
        if not db_path.exists():
            raise EvidenceNotFoundError("investigation event not found")
        repository = InvestigationRepository(db_path, task_id)
        try:
            event = await asyncio.to_thread(repository.get_event, event_id)
        except sqlite3.DatabaseError as exc:
            raise EvidenceStoreError(
                "investigation event store is unavailable"
            ) from exc
        if event is None:
            raise EvidenceNotFoundError("investigation event not found")
        return repository

    async def event_time_bounds(self, task_id: str) -> dict:
        """Per-event derived [start_time, end_time] from linked evidence.

        Empty dict when the task has no investigation.db (GET never creates
        one); events without derivable timestamps are simply absent.
        """
        reader = await self._reader_for(task_id)
        if reader is None:
            return {}
        try:
            return await asyncio.to_thread(reader.event_time_bounds)
        except EvidenceStoreError:
            raise
        except sqlite3.DatabaseError as exc:
            raise EvidenceStoreError(
                "investigation event store is unavailable"
            ) from exc

    async def describe_event_evidence(
        self, task_id: str, event_id: str
    ) -> list[dict]:
        """Card-view projection of the event's linked evidence (titles,
        timestamps, roles derived from the frozen evidence snapshots)."""
        reader = await self._require_event_reader(task_id, event_id)
        try:
            return await asyncio.to_thread(
                reader.describe_event_evidence, event_id
            )
        except EvidenceStoreError:
            raise
        except sqlite3.DatabaseError as exc:
            raise EvidenceStoreError(
                "investigation event store is unavailable"
            ) from exc

    async def list_event_versions(
        self, task_id: str, event_id: str
    ) -> list[InvestigationEventVersion]:
        reader = await self._require_event_reader(task_id, event_id)
        try:
            return await asyncio.to_thread(reader.list_event_versions, event_id)
        except EvidenceStoreError:
            raise
        except sqlite3.DatabaseError as exc:
            raise EvidenceStoreError(
                "investigation event store is unavailable"
            ) from exc

    async def link_event_evidence(
        self,
        task_id: str,
        event_id: str,
        evidence_key: str,
        *,
        linked_by: str | None = None,
    ) -> EventEvidenceLink:
        repository = await self._require_event(task_id, event_id)

        # Resolve + capture in the SAME task (C4c precedent). Raises
        # not-found if the evidence does not exist in this task's sources.
        await self._capture_service.capture(task_id, evidence_key)

        try:
            return await asyncio.to_thread(
                repository.link_event_evidence,
                event_id, evidence_key, linked_by=linked_by,
            )
        except sqlite3.DatabaseError as exc:
            raise EvidenceStoreError(
                "investigation event store is unavailable"
            ) from exc

    async def list_event_evidence(
        self, task_id: str, event_id: str
    ) -> list[EventEvidenceLink]:
        reader = await self._require_event_reader(task_id, event_id)
        try:
            return await asyncio.to_thread(reader.list_event_evidence, event_id)
        except EvidenceStoreError:
            raise
        except sqlite3.DatabaseError as exc:
            raise EvidenceStoreError(
                "investigation event store is unavailable"
            ) from exc

    async def file_timeline(
        self, task_id: str, *, limit: int = 500, ensure_paths=()
    ) -> dict:
        """File-centric timeline projection (workbench middle axis).

        节点 = 调查覆盖的文件(直接 ``file:`` 关联 + 关联簇成员)∪ 已分析
        文件(``llm_analyzed_at IS NOT NULL``,文件中心兜底),各自定位于其
        MACB 最新时间。Read-only:investigation.db 缺失时退化为纯"已分析
        文件"投影(事件关联与判定三态为空),绝不物化该库。
        ``ensure_paths`` rescues limit-truncated files for report-citation
        deep links (node set unchanged).
        """
        task = await self._cpp_backend.get_task(task_id)
        if not isinstance(task, dict) or task.get("id") != task_id:
            raise EvidenceNotFoundError("task not found")
        db_path = investigation_db_path_for_task(task)
        try:
            return await asyncio.to_thread(
                collect_file_timeline,
                db_path,
                task_id,
                task,
                limit=limit,
                ensure_paths=ensure_paths,
            )
        except sqlite3.DatabaseError as exc:
            raise EvidenceStoreError(
                "investigation event store is unavailable"
            ) from exc

    async def resolve_db_path(self, task_id: str) -> Path:
        """Return the trusted investigation DB path for an existing task."""
        return await self._resolve_db_path(task_id)

    async def get_event_refresh(
        self, task_id: str, refresh_id: str
    ) -> EventRefresh:
        reader = await self._reader_for(task_id)
        if reader is None:
            raise EvidenceNotFoundError("event refresh not found")
        try:
            refresh = await asyncio.to_thread(reader.get_event_refresh, refresh_id)
        except EvidenceStoreError:
            raise
        except sqlite3.DatabaseError as exc:
            raise EvidenceStoreError("investigation event store is unavailable") from exc
        if refresh is None:
            raise EvidenceNotFoundError("event refresh not found")
        return refresh

    async def list_stale_event_refreshes(self, task_id: str) -> list[EventRefresh]:
        db_path = await self._resolve_db_path(task_id)
        if not db_path.exists():
            return []
        try:
            repository = InvestigationRepository(db_path, task_id)
            return await asyncio.to_thread(repository.list_stale_event_refreshes)
        except sqlite3.DatabaseError as exc:
            raise EvidenceStoreError("investigation event store is unavailable") from exc

    async def create_event_refresh(
        self, task_id: str, event_id: str, *, requested_by: str | None = None
    ) -> EventRefresh:
        """Admit one explicit refresh with frozen input (C7c-1)."""
        await self._require_event(task_id, event_id)
        db_path = await self._resolve_db_path(task_id)
        repository = InvestigationRepository(db_path, task_id)
        try:
            return await asyncio.to_thread(
                repository.create_event_refresh, event_id, requested_by=requested_by
            )
        except sqlite3.DatabaseError as exc:
            raise EvidenceStoreError(
                "investigation event store is unavailable"
            ) from exc

    async def list_event_refreshes(
        self, task_id: str, event_id: str
    ) -> list[EventRefresh]:
        reader = await self._require_event_reader(task_id, event_id)
        try:
            return await asyncio.to_thread(reader.list_event_refreshes, event_id)
        except EvidenceStoreError:
            raise
        except sqlite3.DatabaseError as exc:
            raise EvidenceStoreError(
                "investigation event store is unavailable"
            ) from exc

    async def _require_event_reader(
        self, task_id: str, event_id: str
    ) -> InvestigationGraphReader:
        """Strict-reader variant of _require_event for pure GET reads."""
        reader = await self._reader_for(task_id)
        if reader is None:
            raise EvidenceNotFoundError("investigation event not found")
        try:
            event = await asyncio.to_thread(reader.get_event, event_id)
        except EvidenceStoreError:
            raise
        except sqlite3.DatabaseError as exc:
            raise EvidenceStoreError(
                "investigation event store is unavailable"
            ) from exc
        if event is None:
            raise EvidenceNotFoundError("investigation event not found")
        return reader


__all__ = ["InvestigationEventService"]
