"""Task-local append-only storage for Phase 4D render candidates."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from pydantic import BaseModel, Field

from .report_rendering import SectionRenderInput, SectionRenderOutput

RENDER_QUEUED = "queued"
RENDER_RUNNING = "running"
RENDER_PENDING_VALIDATION = "render_pending_validation"
RENDER_INVALID = "invalid"
RENDER_FAILED = "failed"

_MUTABLE_STATUSES = {RENDER_QUEUED, RENDER_RUNNING}
_TERMINAL_STATUSES = {
    RENDER_PENDING_VALIDATION,
    RENDER_INVALID,
    RENDER_FAILED,
}


class ReportRenderCandidate(BaseModel):
    candidate_id: str
    task_id: str
    section_id: str
    render_version: int
    dataset_hash: str
    citation_graph_hash: str
    section_plan_hash: str
    prompt_version: str
    render_input_hash: str
    render_output_hash: Optional[str] = None
    model: Optional[str] = None
    status: str
    structured_output: Optional[SectionRenderOutput] = None
    raw_llm_output: Optional[str] = None
    validation_errors: List[Dict[str, Any]] = Field(default_factory=list)
    error_message: Optional[str] = None
    created_at: int
    completed_at: Optional[int] = None

    def to_response_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")


class ReportRenderRepository:
    """SQLite repository with immutable terminal candidate history."""

    def __init__(
        self,
        db_path: Path | str,
        *,
        recover: bool = True,
        ensure_schema: bool = True,
        read_only: bool = False,
    ):
        self.db_path = Path(db_path)
        self.read_only = read_only
        if ensure_schema:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._ensure_schema()
        if recover and ensure_schema:
            self._recover_interrupted()

    def _connect(self) -> sqlite3.Connection:
        if self.read_only:
            uri = f"file:{self.db_path}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=30)
        else:
            conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS section_render_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    section_id TEXT NOT NULL,
                    render_version INTEGER NOT NULL,
                    dataset_hash TEXT NOT NULL,
                    citation_graph_hash TEXT NOT NULL,
                    section_plan_hash TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    render_input_hash TEXT NOT NULL,
                    render_output_hash TEXT,
                    model TEXT,
                    status TEXT NOT NULL,
                    structured_output_json TEXT,
                    raw_llm_output TEXT,
                    validation_errors_json TEXT NOT NULL DEFAULT '[]',
                    error_message TEXT,
                    created_at INTEGER NOT NULL,
                    completed_at INTEGER,
                    UNIQUE(task_id, section_id, render_version)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_render_candidates_scope
                ON section_render_candidates(task_id, section_id, render_version DESC)
                """
            )
            conn.commit()

    def _recover_interrupted(self) -> None:
        now = int(time.time())
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE section_render_candidates
                SET status = ?, error_message = ?, completed_at = ?
                WHERE status IN (?, ?)
                """,
                (
                    RENDER_FAILED,
                    "render candidate failed during service restart",
                    now,
                    RENDER_QUEUED,
                    RENDER_RUNNING,
                ),
            )
            conn.commit()

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def create_queued(
        self, task_id: str, section_id: str, input_data: SectionRenderInput
    ) -> ReportRenderCandidate:
        candidate_id = str(uuid.uuid4())
        created_at = int(time.time())
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT COALESCE(MAX(render_version), 0) + 1 AS next_version
                   FROM section_render_candidates
                   WHERE task_id = ? AND section_id = ?""",
                (task_id, section_id),
            ).fetchone()
            render_version = int(row["next_version"])
            conn.execute(
                """
                INSERT INTO section_render_candidates (
                    candidate_id, task_id, section_id, render_version,
                    dataset_hash, citation_graph_hash, section_plan_hash,
                    prompt_version, render_input_hash, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate_id,
                    task_id,
                    section_id,
                    render_version,
                    input_data.dataset_hash,
                    input_data.citation_graph_hash,
                    input_data.section_plan_hash,
                    input_data.prompt_version,
                    input_data.compute_hash(),
                    RENDER_QUEUED,
                    created_at,
                ),
            )
            conn.commit()
        candidate = self.get(candidate_id)
        if candidate is None:  # pragma: no cover - defensive against DB tampering
            raise RuntimeError(f"render candidate {candidate_id} disappeared")
        return candidate

    # Explicit alias for callers that do not need to know the lifecycle state.
    create_candidate = create_queued

    def _update_mutable(
        self,
        candidate_id: str,
        *,
        status: str,
        structured_output: Optional[SectionRenderOutput] = None,
        raw_llm_output: Optional[str] = None,
        model: Optional[str] = None,
        validation_errors: Optional[Iterable[Any]] = None,
        error_message: Optional[str] = None,
        render_output_hash: Optional[str] = None,
        completed_at: Optional[int] = None,
    ) -> None:
        if status not in _TERMINAL_STATUSES and status not in _MUTABLE_STATUSES:
            raise ValueError(f"unknown render status: {status}")
        output_json = (
            self._json(structured_output.canonical_content_dict())
            if structured_output is not None
            else None
        )
        errors_json = self._json([
            error.model_dump(mode="json") if isinstance(error, BaseModel) else error
            for error in (validation_errors or [])
        ])
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE section_render_candidates
                SET status = ?, render_output_hash = ?, model = ?,
                    structured_output_json = ?, raw_llm_output = ?,
                    validation_errors_json = ?, error_message = ?, completed_at = ?
                WHERE candidate_id = ? AND status IN (?, ?)
                """,
                (
                    status,
                    render_output_hash,
                    model,
                    output_json,
                    raw_llm_output,
                    errors_json,
                    error_message,
                    completed_at,
                    candidate_id,
                    RENDER_QUEUED,
                    RENDER_RUNNING,
                ),
            )
            if cursor.rowcount == 0:
                existing = conn.execute(
                    "SELECT status FROM section_render_candidates WHERE candidate_id = ?",
                    (candidate_id,),
                ).fetchone()
                if existing is None:
                    raise KeyError(candidate_id)
                raise ValueError("terminal render candidate is immutable")
            conn.commit()

    def mark_running(self, candidate_id: str) -> ReportRenderCandidate:
        self._update_mutable(candidate_id, status=RENDER_RUNNING)
        candidate = self.get(candidate_id)
        if candidate is None:  # pragma: no cover
            raise KeyError(candidate_id)
        return candidate

    def complete(
        self,
        candidate_id: str,
        *,
        status: str,
        output: Optional[SectionRenderOutput] = None,
        raw_llm_output: Optional[str] = None,
        model: Optional[str] = None,
        validation_errors: Optional[Iterable[Any]] = None,
        error_message: Optional[str] = None,
    ) -> ReportRenderCandidate:
        if status not in _TERMINAL_STATUSES:
            raise ValueError("complete requires a terminal render status")
        self._update_mutable(
            candidate_id,
            status=status,
            structured_output=output,
            raw_llm_output=raw_llm_output,
            model=model,
            validation_errors=validation_errors,
            error_message=error_message,
            render_output_hash=output.compute_hash() if output is not None else None,
            completed_at=int(time.time()),
        )
        candidate = self.get(candidate_id)
        if candidate is None:  # pragma: no cover
            raise KeyError(candidate_id)
        return candidate

    def fail(self, candidate_id: str, error_message: str) -> ReportRenderCandidate:
        return self.complete(
            candidate_id,
            status=RENDER_FAILED,
            error_message=error_message,
        )

    def get(self, candidate_id: str) -> Optional[ReportRenderCandidate]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM section_render_candidates WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
        return self._to_model(row) if row else None

    def get_for_task(
        self, task_id: str, candidate_id: str
    ) -> Optional[ReportRenderCandidate]:
        """Read one Candidate without crossing the task boundary."""
        with self._connect() as conn:
            try:
                row = conn.execute(
                    """
                    SELECT * FROM section_render_candidates
                    WHERE task_id = ? AND candidate_id = ?
                    """,
                    (task_id, candidate_id),
                ).fetchone()
            except sqlite3.OperationalError as exc:
                if "no such table" not in str(exc):
                    raise
                row = None
        return self._to_model(row) if row else None

    @classmethod
    def read_only(cls, db_path: Path | str) -> "ReportRenderRepository":
        """Open the candidate table without schema creation or recovery writes."""
        return cls(
            db_path,
            recover=False,
            ensure_schema=False,
            read_only=True,
        )

    def list_unfinished(self, task_id: Optional[str] = None) -> List[ReportRenderCandidate]:
        query = (
            "SELECT * FROM section_render_candidates "
            "WHERE status IN (?, ?)"
        )
        params: List[Any] = [RENDER_QUEUED, RENDER_RUNNING]
        if task_id is not None:
            query += " AND task_id = ?"
            params.append(task_id)
        query += " ORDER BY created_at, render_version"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._to_model(row) for row in rows]

    def get_latest(self, task_id: str, section_id: str) -> Optional[ReportRenderCandidate]:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM section_render_candidates
                   WHERE task_id = ? AND section_id = ?
                   ORDER BY render_version DESC LIMIT 1""",
                (task_id, section_id),
            ).fetchone()
        return self._to_model(row) if row else None

    def list_candidates(
        self, task_id: str, section_id: Optional[str] = None
    ) -> List[ReportRenderCandidate]:
        query = "SELECT * FROM section_render_candidates WHERE task_id = ?"
        params: List[Any] = [task_id]
        if section_id is not None:
            query += " AND section_id = ?"
            params.append(section_id)
        query += " ORDER BY section_id, render_version DESC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._to_model(row) for row in rows]

    @staticmethod
    def _to_model(row: sqlite3.Row) -> ReportRenderCandidate:
        output = None
        if row["structured_output_json"]:
            try:
                output = SectionRenderOutput.model_validate(
                    json.loads(row["structured_output_json"])
                )
            except Exception:
                # Preserve the immutable row; Phase 4E records the parse failure.
                output = None
        return ReportRenderCandidate(
            candidate_id=row["candidate_id"],
            task_id=row["task_id"],
            section_id=row["section_id"],
            render_version=row["render_version"],
            dataset_hash=row["dataset_hash"],
            citation_graph_hash=row["citation_graph_hash"],
            section_plan_hash=row["section_plan_hash"],
            prompt_version=row["prompt_version"],
            render_input_hash=row["render_input_hash"],
            render_output_hash=row["render_output_hash"],
            model=row["model"],
            status=row["status"],
            structured_output=output,
            raw_llm_output=row["raw_llm_output"],
            validation_errors=json.loads(row["validation_errors_json"] or "[]"),
            error_message=row["error_message"],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        )
