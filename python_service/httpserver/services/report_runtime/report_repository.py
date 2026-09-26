"""Report-runtime persistence on the existing report artifact store.

Ownership decision (P7A §48, driven by the repository investigation):
outline versions, chapter specs, retrieval plans, and frozen context packs
belong to the **report artifact plane** and therefore live in the existing
``reports.db`` (the R2 report persistence owner), NOT in
``investigation.db``.  Their refs point exactly back at task /
investigation / finalization / evidence / canonical semantics.

Storage is append-only: nothing is ever UPDATEd or DELETEd (§50); an
outline edit creates a new version row (§15); identical deterministic
artifacts replay to the same content-addressed id and are stored once
(§62 idempotency).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from .report_admission import ReportRuntimeAdmissionV1
from .report_chapter import ChapterSpecV1
from .report_outline import ReportOutlinePlanV1

REPORT_RUNTIME_SCHEMA_VERSION = 1


class ReportRuntimeRepository:
    """Append-only persistence for P7A planning artifacts in reports.db."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS report_runtime_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS report_runtime_admissions (
                    admission_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    investigation_id TEXT NOT NULL,
                    finalization_id TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                -- Outline versions: append-only; an analyst edit inserts a
                -- new revision row (parent_outline_id), never an UPDATE.
                CREATE TABLE IF NOT EXISTS report_outline_versions (
                    outline_id TEXT NOT NULL,
                    outline_revision INTEGER NOT NULL,
                    task_id TEXT NOT NULL,
                    investigation_id TEXT NOT NULL,
                    finalization_id TEXT NOT NULL,
                    parent_outline_id TEXT,
                    planner_kind TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (outline_id, outline_revision)
                );
                CREATE INDEX IF NOT EXISTS idx_report_outline_task
                    ON report_outline_versions(task_id, investigation_id,
                                               created_at);

                CREATE TABLE IF NOT EXISTS report_chapter_specs (
                    chapter_spec_id TEXT PRIMARY KEY,
                    outline_id TEXT NOT NULL,
                    outline_revision INTEGER NOT NULL,
                    chapter_id TEXT NOT NULL,
                    generation_mode TEXT NOT NULL,
                    context_stage TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    ordering_hint INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_report_chapter_outline
                    ON report_chapter_specs(outline_id, outline_revision,
                                            ordering_hint);

                CREATE TABLE IF NOT EXISTS report_retrieval_plans (
                    retrieval_plan_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    investigation_id TEXT NOT NULL,
                    outline_id TEXT NOT NULL,
                    chapter_id TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_report_retrieval_chapter
                    ON report_retrieval_plans(task_id, outline_id,
                                              chapter_id);

                CREATE TABLE IF NOT EXISTS report_context_packs (
                    context_pack_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    investigation_id TEXT NOT NULL,
                    outline_id TEXT NOT NULL,
                    chapter_id TEXT NOT NULL,
                    generation_mode TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_report_packs_chapter
                    ON report_context_packs(task_id, outline_id,
                                            chapter_id);
                """
            )
            # ordering_hint ships in the P7A-1 base schema (one store
            # generation; no migration path needed for planning rows).

    # -- admissions ---------------------------------------------------------

    def record_report_runtime_admission(
        self, admission: ReportRuntimeAdmissionV1
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO report_runtime_admissions
                   (admission_id, task_id, investigation_id, finalization_id,
                    input_hash, payload_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    admission.admission_id,
                    admission.task_id,
                    admission.investigation_id,
                    admission.finalization_id,
                    admission.input_hash,
                    admission.model_dump_json(),
                    admission.created_at,
                ),
            )

    def get_report_runtime_admission(
        self, admission_id: str
    ) -> Optional[ReportRuntimeAdmissionV1]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM report_runtime_admissions "
                "WHERE admission_id = ?",
                (admission_id,),
            ).fetchone()
        return (
            ReportRuntimeAdmissionV1.model_validate_json(row["payload_json"])
            if row
            else None
        )

    # -- outline versions ----------------------------------------------------

    def record_outline_version(
        self, plan: ReportOutlinePlanV1
    ) -> None:
        """Insert-only outline persistence; replay of an identical
        semantic outline is a no-op (§62)."""
        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO report_outline_versions
                   (outline_id, outline_revision, task_id, investigation_id,
                    finalization_id, parent_outline_id, planner_kind,
                    input_hash, payload_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    plan.outline_id,
                    plan.outline_revision,
                    plan.task_id,
                    plan.investigation_id,
                    plan.finalization_id,
                    plan.parent_outline_id,
                    plan.planner_kind,
                    plan.input_hash,
                    plan.model_dump_json(),
                    plan.created_at,
                ),
            )

    def get_outline(
        self, outline_id: str, outline_revision: int = 1
    ) -> Optional[ReportOutlinePlanV1]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM report_outline_versions "
                "WHERE outline_id = ? AND outline_revision = ?",
                (outline_id, outline_revision),
            ).fetchone()
        return (
            ReportOutlinePlanV1.model_validate_json(row["payload_json"])
            if row
            else None
        )

    def list_outlines(
        self, task_id: str, investigation_id: str
    ) -> list[ReportOutlinePlanV1]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM report_outline_versions "
                "WHERE task_id = ? AND investigation_id = ? "
                "ORDER BY created_at, outline_revision",
                (task_id, investigation_id),
            ).fetchall()
        return [
            ReportOutlinePlanV1.model_validate_json(row["payload_json"])
            for row in rows
        ]

    # -- chapter specs --------------------------------------------------------

    def record_chapter_specs(self, specs: tuple[ChapterSpecV1, ...]) -> None:
        with self._connect() as conn:
            for spec in specs:
                conn.execute(
                    """INSERT OR IGNORE INTO report_chapter_specs
                       (chapter_spec_id, outline_id, outline_revision,
                        chapter_id, generation_mode, context_stage,
                        input_hash, payload_json, created_at, ordering_hint)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        spec.input_hash,
                        spec.outline_id,
                        spec.outline_revision,
                        spec.chapter_id,
                        spec.generation_mode,
                        spec.context_stage,
                        spec.input_hash,
                        spec.model_dump_json(),
                        spec.created_at,
                        spec.ordering,
                    ),
                )

    def list_chapter_specs(
        self, outline_id: str, outline_revision: int
    ) -> list[ChapterSpecV1]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM report_chapter_specs "
                "WHERE outline_id = ? AND outline_revision = ? "
                "ORDER BY ordering_hint, chapter_spec_id",
                (outline_id, outline_revision),
            ).fetchall()
        return [
            ChapterSpecV1.model_validate_json(row["payload_json"])
            for row in rows
        ]


__all__ = ["REPORT_RUNTIME_SCHEMA_VERSION", "ReportRuntimeRepository"]
