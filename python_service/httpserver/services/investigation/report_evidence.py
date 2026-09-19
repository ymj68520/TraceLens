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
import json
import time
import sqlite3
from pathlib import Path

from ..evidence.exceptions import EvidenceNotFoundError, EvidenceStoreError
from ..evidence.resolver import EvidenceResolver
from ..investigation_persistence import InvestigationPersistence
from . import workbench_state
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
        if workbench_state.store_is_uninitialized(db_path):
            # Side-table-only artifact (see workbench_state): no bindings;
            # the next bootstrap initializes the store in place.
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
        explicit accepted-analysis binding).

        MVP (mvp-phase1-acceptance §6): with event seeding disabled there is
        no workbench event chain to capture the snapshot through, so a plain
        ``file:`` evidence is snapshotted here on first sight — the capture
        stays immutable (first-write-wins), exactly as on the event path.
        """
        db_path = await self._resolve_task_db(task_id)
        if evidence_key.startswith("file:"):
            try:
                resolved = await EvidenceResolver(self._cpp_backend).resolve_evidence(
                    task_id, evidence_key
                )
                path = resolved.normalized_path or ""
                with sqlite3.connect(
                    f"file:{resolved.source_db}?mode=ro", uri=True
                ) as conn:
                    conn.row_factory = sqlite3.Row
                    row = conn.execute(
                        "SELECT * FROM files WHERE path = ?", (path,)
                    ).fetchone()
                row_dict = dict(row) if row is not None else {}
                snapshot_json = json.dumps(
                    {
                        "evidence_type": "file",
                        "normalized_path": path,
                        "name": row_dict.get("name"),
                        "extension": row_dict.get("extension"),
                        "category": row_dict.get("category"),
                        "type": row_dict.get("type"),
                        "size": row_dict.get("size"),
                        "md5": row_dict.get("md5"),
                        "mtime": row_dict.get("mtime"),
                        "ctime": row_dict.get("ctime"),
                        "is_deleted": row_dict.get("is_deleted"),
                        "initial_summary": row_dict.get("llm_summary"),
                        "initial_description": row_dict.get("llm_description"),
                        "initial_keywords": row_dict.get("llm_keywords"),
                        "initial_model": row_dict.get("llm_model_used"),
                        "initial_analyzed_at": row_dict.get("llm_analyzed_at"),
                        "scene_type": row_dict.get("scene_type"),
                        "scene_priority": row_dict.get("scene_priority"),
                        "scene_relevant": row_dict.get("scene_relevant"),
                    },
                    ensure_ascii=False,
                )
                # Insert straight into the repository-v7 evidence_snapshots
                # table (columns: id, task_id, evidence_key, evidence_type,
                # normalized_path, snapshot_json, captured_at) — first write
                # wins, immutable afterwards.
                with sqlite3.connect(str(db_path), timeout=30) as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute(
                        "INSERT OR IGNORE INTO evidence_snapshots "
                        "(task_id, evidence_key, evidence_type, "
                        " normalized_path, snapshot_json, captured_at) "
                        "VALUES (?, ?, 'file', ?, ?, ?)",
                        (
                            task_id,
                            resolved.evidence_key,
                            path,
                            snapshot_json,
                            int(time.time()),
                        ),
                    )
                    conn.commit()
            except EvidenceNotFoundError:
                raise
            except Exception as exc:
                raise EvidenceStoreError(
                    f"cannot capture evidence snapshot: {exc}"
                ) from exc
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
