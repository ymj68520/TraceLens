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
        db_path = await self._resolve_db_path(task_id)
        if not db_path.exists():
            return []
        try:
            repository = InvestigationRepository(db_path, task_id)
            return await asyncio.to_thread(
                repository.list_events, needs_refresh=needs_refresh
            )
        except sqlite3.DatabaseError as exc:
            raise EvidenceStoreError(
                "investigation event store is unavailable"
            ) from exc

    async def get_event(self, task_id: str, event_id: str) -> InvestigationEvent:
        db_path = await self._resolve_db_path(task_id)
        if not db_path.exists():
            raise EvidenceNotFoundError("investigation event not found")
        try:
            repository = InvestigationRepository(db_path, task_id)
            event = await asyncio.to_thread(repository.get_event, event_id)
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

    async def list_event_versions(
        self, task_id: str, event_id: str
    ) -> list[InvestigationEventVersion]:
        repository = await self._require_event(task_id, event_id)
        try:
            return await asyncio.to_thread(repository.list_event_versions, event_id)
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
        repository = await self._require_event(task_id, event_id)
        try:
            return await asyncio.to_thread(repository.list_event_evidence, event_id)
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
        db_path = await self._resolve_db_path(task_id)
        if not db_path.exists():
            raise EvidenceNotFoundError("event refresh not found")
        try:
            repository = InvestigationRepository(db_path, task_id)
            refresh = await asyncio.to_thread(repository.get_event_refresh, refresh_id)
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
        repository = await self._require_event(task_id, event_id)
        try:
            return await asyncio.to_thread(repository.list_event_refreshes, event_id)
        except sqlite3.DatabaseError as exc:
            raise EvidenceStoreError(
                "investigation event store is unavailable"
            ) from exc


__all__ = ["InvestigationEventService"]
