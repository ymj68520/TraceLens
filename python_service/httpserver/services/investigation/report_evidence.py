"""Task-scoped Report Evidence binding orchestration (Phase R1).

The Evidence itself (canonical ``(task_id, evidence_key)`` of a captured
snapshot) is always the report source.  ``analysis_id`` is an OPTIONAL frozen
binding to one accepted Secondary Analysis of the SAME evidence, chosen and
re-chosen only by explicit analyst actions -- never a "latest accepted"
pointer, and never changed implicitly when newer versions are accepted later.

Reads go through the strictly read-only ``InvestigationGraphReader`` (C10
§14/E13 semantics: a missing store is "no report evidence", a corrupt or
unsupported store fails closed).  Writes run on the write-capable repository
inside one BEGIN IMMEDIATE transaction that performs the R1 §7 triple check
(same task, same evidence, status accepted) before touching the row.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from ..evidence.exceptions import EvidenceNotFoundError, EvidenceStoreError
from .graph_reader import InvestigationGraphReader
from .models import ReportEvidenceItem
from .paths import investigation_db_path_for_task
from .repository import InvestigationRepository


class ReportEvidenceService:
    """Explicit analyst Report Evidence actions for one task."""

    def __init__(self, cpp_backend):
        self._cpp_backend = cpp_backend

    async def _resolve_task_db(self, task_id: str) -> Path:
        """Current-task lookup + trusted investigation.db destination.

        Raises ``EvidenceNotFoundError`` when the task does not exist or has
        no trusted database path (fail-closed, never a default location).
        """
        task = await self._cpp_backend.get_task(task_id)
        if not isinstance(task, dict) or task.get("id") != task_id:
            raise EvidenceNotFoundError("task not found")
        if not task.get("output_files_db") and not task.get("output_events_db"):
            raise EvidenceNotFoundError("task not found")
        return investigation_db_path_for_task(task)

    async def list(self, task_id: str) -> list[ReportEvidenceItem]:
        """Every report_evidence row of the task (exact frozen bindings)."""
        db_path = await self._resolve_task_db(task_id)
        if not db_path.exists():
            # A task without an investigation.db has no report evidence; the
            # GET never creates or migrates the store (C10 §14).
            return []
        reader = InvestigationGraphReader(db_path, task_id)
        return await asyncio.to_thread(reader.list_report_evidence)

    async def add(
        self,
        task_id: str,
        evidence_key: str,
        *,
        report_status: str,
        analysis_id: str | None = None,
        added_by: str,
    ) -> ReportEvidenceItem:
        """Add one captured evidence to the report (main/appendix, optional
        explicit accepted-analysis binding)."""
        db_path = await self._resolve_task_db(task_id)
        if not db_path.exists():
            raise EvidenceNotFoundError(
                "evidence snapshot not captured for this task"
            )
        try:
            repository = InvestigationRepository(db_path, task_id)
            await asyncio.to_thread(
                repository.add_report_evidence,
                evidence_key,
                report_status=report_status,
                analysis_id=analysis_id,
                added_by=added_by,
            )
            item = await asyncio.to_thread(
                InvestigationGraphReader(db_path, task_id).get_report_evidence,
                evidence_key,
            )
            if item is None:  # pragma: no cover - same transaction just inserted it
                raise EvidenceStoreError("report evidence readback failed")
            return item
        except sqlite3.DatabaseError as exc:
            raise EvidenceStoreError(
                "investigation database is unavailable"
            ) from exc

    async def update(
        self,
        task_id: str,
        evidence_key: str,
        *,
        report_status: str | None = None,
        analysis_id: str | None = None,
        bind_analysis: bool = False,
        updated_by: str,
    ) -> ReportEvidenceItem:
        """Explicitly set report_status and/or (re)bind the frozen analysis."""
        db_path = await self._resolve_task_db(task_id)
        if not db_path.exists():
            raise EvidenceNotFoundError("report evidence not found")
        try:
            repository = InvestigationRepository(db_path, task_id)
            await asyncio.to_thread(
                repository.update_report_evidence,
                evidence_key,
                report_status=report_status,
                analysis_id=analysis_id,
                bind_analysis=bind_analysis,
                updated_by=updated_by,
            )
            item = await asyncio.to_thread(
                InvestigationGraphReader(db_path, task_id).get_report_evidence,
                evidence_key,
            )
            if item is None:  # pragma: no cover - row was just updated
                raise EvidenceStoreError("report evidence readback failed")
            return item
        except sqlite3.DatabaseError as exc:
            raise EvidenceStoreError(
                "investigation database is unavailable"
            ) from exc


__all__ = ["ReportEvidenceService"]
