"""Task-local append-only storage for Phase 4E validation records."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from pydantic import BaseModel

from .report_final_validation import (
    FINAL_FAILED,
    FINAL_QUEUED,
    FINAL_RUNNING,
    FINAL_VALIDATION_INTERRUPTED,
    FINAL_VALIDATION_RULE_VERSION,
    FinalValidationError,
    FinalValidationResult,
    SectionRenderValidation,
    compute_validation_input_hash,
)
from .report_render_repository import ReportRenderCandidate

_FINAL_STATUSES = {"valid", "invalid", "blocked", FINAL_FAILED}
_MUTABLE_STATUSES = {FINAL_QUEUED, FINAL_RUNNING}


class ReportValidationRepository:
    """SQLite repository with immutable terminal validation history."""

    def __init__(
        self,
        db_path: Path | str,
        *,
        recover: bool = True,
        read_only: bool = False,
    ):
        self.db_path = Path(db_path)
        self.read_only = read_only
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if not read_only:
            self._ensure_schema()
            if recover:
                self._recover_interrupted()

    @classmethod
    def read_only(cls, db_path: Path | str) -> "ReportValidationRepository":
        """Open validation history without schema creation or restart recovery."""
        repository = cls.__new__(cls)
        repository.db_path = Path(db_path)
        repository.read_only = True
        return repository

    def _connect(self) -> sqlite3.Connection:
        if getattr(self, "read_only", False):
            conn = sqlite3.connect(
                f"file:{self.db_path}?mode=ro",
                uri=True,
                timeout=30,
            )
        else:
            conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS section_render_validations (
                    validation_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    section_id TEXT NOT NULL,
                    validation_version INTEGER NOT NULL,
                    validation_rule_version TEXT NOT NULL,
                    dataset_hash TEXT NOT NULL,
                    citation_graph_hash TEXT NOT NULL,
                    section_plan_hash TEXT NOT NULL,
                    render_input_hash TEXT NOT NULL,
                    render_output_hash TEXT,
                    observed_dataset_hash TEXT,
                    observed_citation_graph_hash TEXT,
                    observed_section_plan_hash TEXT,
                    observed_render_input_hash TEXT,
                    observed_render_output_hash TEXT,
                    validation_input_hash TEXT,
                    validation_result_hash TEXT,
                    status TEXT NOT NULL,
                    validation_errors_json TEXT NOT NULL DEFAULT '[]',
                    validation_warnings_json TEXT NOT NULL DEFAULT '[]',
                    coverage_json TEXT NOT NULL DEFAULT '{}',
                    error_message TEXT,
                    created_at INTEGER NOT NULL,
                    completed_at INTEGER,
                    UNIQUE(task_id, candidate_id, validation_version)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_render_validations_scope
                ON section_render_validations(
                    task_id, candidate_id, validation_version DESC
                )
                """
            )
            conn.commit()

    def _recover_interrupted(self) -> None:
        now = int(time.time())
        error_json = self._json([{
            "code": FINAL_VALIDATION_INTERRUPTED,
            "severity": "error",
            "entity_type": "validation",
            "message": "Validation was interrupted by service restart.",
        }])
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE section_render_validations
                SET status = ?, validation_errors_json = ?, error_message = ?, completed_at = ?
                WHERE status IN (?, ?)
                """ ,
                (
                    FINAL_FAILED,
                    error_json,
                    FINAL_VALIDATION_INTERRUPTED,
                    now,
                    FINAL_QUEUED,
                    FINAL_RUNNING,
                ),
            )
            conn.commit()

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def create_queued(
        self,
        task_id: str,
        candidate: ReportRenderCandidate,
        *,
        validation_rule_version: str = FINAL_VALIDATION_RULE_VERSION,
    ) -> SectionRenderValidation:
        validation_id = str(uuid.uuid4())
        created_at = int(time.time())
        provisional_input_hash = None
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT COALESCE(MAX(validation_version), 0) + 1 AS next_version
                FROM section_render_validations
                WHERE task_id = ? AND candidate_id = ?
                """,
                (task_id, candidate.candidate_id),
            ).fetchone()
            validation_version = int(row["next_version"])
            conn.execute(
                """
                INSERT INTO section_render_validations (
                    validation_id, task_id, candidate_id, section_id,
                    validation_version, validation_rule_version,
                    dataset_hash, citation_graph_hash, section_plan_hash,
                    render_input_hash, render_output_hash,
                    validation_input_hash, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    validation_id,
                    task_id,
                    candidate.candidate_id,
                    candidate.section_id,
                    validation_version,
                    validation_rule_version,
                    candidate.dataset_hash,
                    candidate.citation_graph_hash,
                    candidate.section_plan_hash,
                    candidate.render_input_hash,
                    candidate.render_output_hash,
                    provisional_input_hash,
                    FINAL_QUEUED,
                    created_at,
                ),
            )
            conn.commit()
        validation = self.get(validation_id)
        if validation is None:  # pragma: no cover
            raise RuntimeError(f"validation {validation_id} disappeared")
        return validation

    create_validation = create_queued

    def _update_mutable(
        self,
        validation_id: str,
        *,
        status: str,
        result: Optional[FinalValidationResult] = None,
        error_message: Optional[str] = None,
    ) -> None:
        if status not in _FINAL_STATUSES and status not in _MUTABLE_STATUSES:
            raise ValueError(f"unknown validation status: {status}")
        result = result or FinalValidationResult(status=status)
        errors_json = self._json([
            error.model_dump(mode="json") if isinstance(error, BaseModel) else error
            for error in result.errors
        ])
        warnings_json = self._json([
            warning.model_dump(mode="json") if isinstance(warning, BaseModel) else warning
            for warning in result.warnings
        ])
        completed_at = int(time.time()) if status in _FINAL_STATUSES else None
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE section_render_validations
                SET status = ?,
                    observed_dataset_hash = ?,
                    observed_citation_graph_hash = ?,
                    observed_section_plan_hash = ?,
                    observed_render_input_hash = ?,
                    observed_render_output_hash = ?,
                    validation_input_hash = ?,
                    validation_result_hash = ?,
                    validation_errors_json = ?,
                    validation_warnings_json = ?,
                    coverage_json = ?,
                    error_message = ?,
                    completed_at = ?
                WHERE validation_id = ? AND status IN (?, ?)
                """,
                (
                    status,
                    result.observed_dataset_hash,
                    result.observed_citation_graph_hash,
                    result.observed_section_plan_hash,
                    result.observed_render_input_hash,
                    result.observed_render_output_hash,
                    result.validation_input_hash,
                    result.validation_result_hash,
                    errors_json,
                    warnings_json,
                    self._json(result.coverage),
                    error_message if error_message is not None else result.error_message,
                    completed_at,
                    validation_id,
                    FINAL_QUEUED,
                    FINAL_RUNNING,
                ),
            )
            if cursor.rowcount == 0:
                existing = conn.execute(
                    "SELECT status FROM section_render_validations WHERE validation_id = ?",
                    (validation_id,),
                ).fetchone()
                if existing is None:
                    raise KeyError(validation_id)
                raise ValueError("terminal report validation is immutable")
            conn.commit()

    def mark_running(self, validation_id: str) -> SectionRenderValidation:
        self._update_mutable(validation_id, status=FINAL_RUNNING)
        validation = self.get(validation_id)
        if validation is None:  # pragma: no cover
            raise KeyError(validation_id)
        return validation

    def complete(
        self,
        validation_id: str,
        *,
        result: FinalValidationResult,
    ) -> SectionRenderValidation:
        if result.status not in _FINAL_STATUSES:
            raise ValueError("complete requires a terminal validation status")
        self._update_mutable(validation_id, status=result.status, result=result)
        validation = self.get(validation_id)
        if validation is None:  # pragma: no cover
            raise KeyError(validation_id)
        return validation

    def fail(self, validation_id: str, error_message: str) -> SectionRenderValidation:
        return self.complete(
            validation_id,
            result=FinalValidationResult(
                status=FINAL_FAILED,
                error_message=error_message,
            ),
        )

    def get(self, validation_id: str) -> Optional[SectionRenderValidation]:
        with self._connect() as conn:
            try:
                row = conn.execute(
                    "SELECT * FROM section_render_validations WHERE validation_id = ?",
                    (validation_id,),
                ).fetchone()
            except sqlite3.OperationalError as exc:
                if "no such table" not in str(exc):
                    raise
                row = None
        return self._to_model(row) if row else None

    def get_for_task(
        self, task_id: str, validation_id: str
    ) -> Optional[SectionRenderValidation]:
        with self._connect() as conn:
            try:
                row = conn.execute(
                    """
                    SELECT * FROM section_render_validations
                    WHERE task_id = ? AND validation_id = ?
                    """,
                    (task_id, validation_id),
                ).fetchone()
            except sqlite3.OperationalError as exc:
                if "no such table" not in str(exc):
                    raise
                row = None
        return self._to_model(row) if row else None

    def get_latest(
        self, task_id: str, candidate_id: str
    ) -> Optional[SectionRenderValidation]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM section_render_validations
                WHERE task_id = ? AND candidate_id = ?
                ORDER BY validation_version DESC LIMIT 1
                """,
                (task_id, candidate_id),
            ).fetchone()
        return self._to_model(row) if row else None

    def get_latest_valid(
        self, task_id: str, candidate_id: str
    ) -> Optional[SectionRenderValidation]:
        """Return the latest historical valid record, not current validity."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM section_render_validations
                WHERE task_id = ? AND candidate_id = ? AND status = 'valid'
                ORDER BY validation_version DESC LIMIT 1
                """,
                (task_id, candidate_id),
            ).fetchone()
        return self._to_model(row) if row else None

    def list_validations(
        self, task_id: str, candidate_id: Optional[str] = None
    ) -> List[SectionRenderValidation]:
        query = "SELECT * FROM section_render_validations WHERE task_id = ?"
        params: List[Any] = [task_id]
        if candidate_id is not None:
            query += " AND candidate_id = ?"
            params.append(candidate_id)
        query += " ORDER BY candidate_id, validation_version DESC"
        with self._connect() as conn:
            try:
                rows = conn.execute(query, params).fetchall()
            except sqlite3.OperationalError as exc:
                if "no such table" not in str(exc):
                    raise
                rows = []
        return [self._to_model(row) for row in rows]

    @staticmethod
    def _to_model(row: sqlite3.Row) -> SectionRenderValidation:
        return SectionRenderValidation(
            validation_id=row["validation_id"],
            task_id=row["task_id"],
            candidate_id=row["candidate_id"],
            section_id=row["section_id"],
            validation_version=row["validation_version"],
            validation_rule_version=row["validation_rule_version"],
            dataset_hash=row["dataset_hash"],
            citation_graph_hash=row["citation_graph_hash"],
            section_plan_hash=row["section_plan_hash"],
            render_input_hash=row["render_input_hash"],
            render_output_hash=row["render_output_hash"],
            observed_dataset_hash=row["observed_dataset_hash"],
            observed_citation_graph_hash=row["observed_citation_graph_hash"],
            observed_section_plan_hash=row["observed_section_plan_hash"],
            observed_render_input_hash=row["observed_render_input_hash"],
            observed_render_output_hash=row["observed_render_output_hash"],
            validation_input_hash=row["validation_input_hash"],
            validation_result_hash=row["validation_result_hash"],
            status=row["status"],
            validation_errors=[
                FinalValidationError.model_validate(item)
                for item in json.loads(row["validation_errors_json"] or "[]")
            ],
            validation_warnings=[
                FinalValidationError.model_validate(item)
                for item in json.loads(row["validation_warnings_json"] or "[]")
            ],
            coverage=json.loads(row["coverage_json"] or "{}"),
            error_message=row["error_message"],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        )
