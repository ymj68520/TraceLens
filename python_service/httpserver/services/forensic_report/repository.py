from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .models import (
    AdapterWarning,
    ReportGenerationInput,
    ReportStatus,
    ReportVersion,
    ScopeType,
)


class ReportRepository:
    """SQLite-backed metadata storage for immutable report versions."""

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
                CREATE TABLE IF NOT EXISTS report_versions (
                    report_id TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    scope_type TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    title TEXT NOT NULL,
                    task_ids_json TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    generated_at TEXT,
                    manifest_path TEXT,
                    offline_bundle_path TEXT,
                    warnings_json TEXT NOT NULL DEFAULT '[]',
                    error TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(scope_type, scope_id, version)
                );
                CREATE INDEX IF NOT EXISTS idx_report_scope
                    ON report_versions(scope_type, scope_id, version DESC);

                -- Phase R2b: additive frozen generation admission companion.
                -- Insert-only rows; the trigger freezes identity/scope/
                -- requester/prompt version/envelope bytes/hash after
                -- admission, leaving the execution lifecycle columns free.
                -- Phase R2c adds the execution columns inline (legacy R2b
                -- stores get them via ALTER below) plus the state-machine
                -- triggers created after the column migration.
                CREATE TABLE IF NOT EXISTS report_generation_inputs (
                    generation_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    scope_type TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'admitted',
                    requested_by TEXT NOT NULL,
                    input_schema_version INTEGER NOT NULL,
                    prompt_version TEXT NOT NULL,
                    input_envelope_json TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    report_id TEXT,
                    produced_version INTEGER,
                    model TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    failed_at TEXT,
                    error_code TEXT,
                    error_message TEXT,
                    CHECK (scope_type = 'task' AND scope_id = task_id)
                );
                CREATE INDEX IF NOT EXISTS idx_report_generation_task
                    ON report_generation_inputs(task_id, created_at);
                CREATE TRIGGER IF NOT EXISTS trg_report_generation_input_frozen
                BEFORE UPDATE ON report_generation_inputs
                FOR EACH ROW
                WHEN NEW.generation_id IS NOT OLD.generation_id
                  OR NEW.task_id IS NOT OLD.task_id
                  OR NEW.scope_type IS NOT OLD.scope_type
                  OR NEW.scope_id IS NOT OLD.scope_id
                  OR NEW.requested_by IS NOT OLD.requested_by
                  OR NEW.input_schema_version IS NOT OLD.input_schema_version
                  OR NEW.prompt_version IS NOT OLD.prompt_version
                  OR NEW.input_envelope_json IS NOT OLD.input_envelope_json
                  OR NEW.input_hash IS NOT OLD.input_hash
                  OR NEW.created_at IS NOT OLD.created_at
                BEGIN
                    SELECT RAISE(ABORT, 'report generation input is immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_report_generation_input_no_delete
                BEFORE DELETE ON report_generation_inputs
                BEGIN
                    SELECT RAISE(ABORT, 'report generation input is never deleted');
                END;
                """
            )
            self._add_generation_execution_columns(conn)
            conn.executescript(
                """
                -- R2c state machine: admitted(=queued) -> running ->
                -- completed | failed, plus admitted -> failed for
                -- scheduling/restart. Terminal rows are immutable.
                CREATE TRIGGER IF NOT EXISTS trg_report_generation_status_transition
                BEFORE UPDATE OF status ON report_generation_inputs
                FOR EACH ROW
                WHEN NOT (
                    (OLD.status = 'admitted' AND NEW.status IN ('running', 'failed'))
                    OR (OLD.status = 'running' AND NEW.status IN ('completed', 'failed'))
                    OR OLD.status = NEW.status
                )
                BEGIN
                    SELECT RAISE(ABORT, 'invalid report generation status transition');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_report_generation_completed_invariants
                BEFORE UPDATE OF status ON report_generation_inputs
                FOR EACH ROW
                WHEN NEW.status = 'completed' AND (
                    NEW.report_id IS NULL OR NEW.produced_version IS NULL
                    OR NEW.model IS NULL OR NEW.completed_at IS NULL
                )
                BEGIN
                    SELECT RAISE(ABORT, 'completed report generation requires its published version');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_report_generation_failed_invariants
                BEFORE UPDATE OF status ON report_generation_inputs
                FOR EACH ROW
                WHEN NEW.status = 'failed' AND (
                    NEW.report_id IS NOT NULL OR NEW.produced_version IS NOT NULL
                    OR NEW.failed_at IS NULL
                )
                BEGIN
                    SELECT RAISE(ABORT, 'failed report generation must not reference a published version');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_report_generation_terminal_immutable
                BEFORE UPDATE ON report_generation_inputs
                FOR EACH ROW
                WHEN OLD.status IN ('completed', 'failed') AND (
                    NEW.status IS NOT OLD.status
                    OR NEW.started_at IS NOT OLD.started_at
                    OR NEW.completed_at IS NOT OLD.completed_at
                    OR NEW.failed_at IS NOT OLD.failed_at
                    OR NEW.model IS NOT OLD.model
                    OR NEW.produced_version IS NOT OLD.produced_version
                    OR NEW.report_id IS NOT OLD.report_id
                    OR NEW.error_code IS NOT OLD.error_code
                    OR NEW.error_message IS NOT OLD.error_message
                )
                BEGIN
                    SELECT RAISE(ABORT, 'terminal report generation is immutable');
                END;
                """
            )

    _GENERATION_EXECUTION_COLUMNS: tuple[tuple[str, str], ...] = (
        ("report_id", "TEXT"),
        ("produced_version", "INTEGER"),
        ("model", "TEXT"),
        ("started_at", "TEXT"),
        ("completed_at", "TEXT"),
        ("failed_at", "TEXT"),
        ("error_code", "TEXT"),
        ("error_message", "TEXT"),
    )

    def _add_generation_execution_columns(self, conn: sqlite3.Connection) -> None:
        """Additive migration for R2b-era stores (all columns nullable)."""
        existing = {
            row[1] for row in conn.execute(
                "PRAGMA table_info(report_generation_inputs)"
            )
        }
        for name, decl in self._GENERATION_EXECUTION_COLUMNS:
            if name not in existing:
                conn.execute(
                    f"ALTER TABLE report_generation_inputs "
                    f"ADD COLUMN {name} {decl}"
                )

    def create_version(
        self,
        scope_type: ScopeType,
        scope_id: str,
        title: str,
        task_ids: list[str],
    ) -> ReportVersion:
        """Allocate the next version for a scope and persist it as queued.

        ``BEGIN IMMEDIATE`` serializes version allocation across workers while
        allowing readers to continue, so the per-scope unique version cannot be
        allocated twice by concurrent writers.
        """
        report_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 AS next_version "
                "FROM report_versions WHERE scope_type = ? AND scope_id = ?",
                (scope_type.value, scope_id),
            ).fetchone()
            version = int(row["next_version"])
            conn.execute(
                """INSERT INTO report_versions
                   (report_id, version, scope_type, scope_id, status, title,
                    task_ids_json, stage, progress, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', 0, ?)""",
                (
                    report_id,
                    version,
                    scope_type.value,
                    scope_id,
                    ReportStatus.QUEUED.value,
                    title,
                    json.dumps(task_ids),
                    created_at,
                ),
            )
            conn.commit()
        created = self.get(report_id)
        if created is None:  # pragma: no cover - defensive against DB tampering
            raise RuntimeError(f"created report version {report_id} disappeared")
        return created

    def _assert_mutable(self, conn: sqlite3.Connection, report_id: str) -> None:
        row = conn.execute(
            "SELECT status FROM report_versions WHERE report_id = ?", (report_id,)
        ).fetchone()
        if row is None:
            raise KeyError(report_id)
        if row["status"] in (ReportStatus.READY.value, ReportStatus.FAILED.value):
            raise ValueError("published report version is immutable")

    @staticmethod
    def _mutable_status_params(report_id: str) -> tuple[str, str, str]:
        return (report_id, ReportStatus.READY.value, ReportStatus.FAILED.value)

    @staticmethod
    def _assert_updated(cursor: sqlite3.Cursor) -> None:
        if cursor.rowcount == 0:
            raise ValueError("published report version is immutable")

    def mark_generating(self, report_id: str, stage: str) -> None:
        with self._connect() as conn:
            self._assert_mutable(conn, report_id)
            cursor = conn.execute(
                "UPDATE report_versions SET status = ?, stage = ?, progress = 1 "
                "WHERE report_id = ? AND status NOT IN (?, ?)",
                (
                    ReportStatus.GENERATING.value,
                    stage,
                    *self._mutable_status_params(report_id),
                ),
            )
            self._assert_updated(cursor)

    def update_progress(self, report_id: str, stage: str, progress: int) -> None:
        with self._connect() as conn:
            self._assert_mutable(conn, report_id)
            cursor = conn.execute(
                "UPDATE report_versions SET stage = ?, progress = ? "
                "WHERE report_id = ? AND status NOT IN (?, ?)",
                (
                    stage,
                    max(0, min(progress, 99)),
                    *self._mutable_status_params(report_id),
                ),
            )
            self._assert_updated(cursor)

    def mark_ready(
        self, report_id: str, manifest_path: str, warnings: list[AdapterWarning]
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            self._assert_mutable(conn, report_id)
            cursor = conn.execute(
                """UPDATE report_versions
                   SET status = ?, stage = 'ready', progress = 100,
                       generated_at = ?, manifest_path = ?, warnings_json = ?
                   WHERE report_id = ? AND status NOT IN (?, ?)""",
                (
                    ReportStatus.READY.value,
                    now,
                    manifest_path,
                    json.dumps([warning.model_dump(mode="json") for warning in warnings]),
                    *self._mutable_status_params(report_id),
                ),
            )
            self._assert_updated(cursor)

    def mark_failed(self, report_id: str, stage: str, error: str) -> None:
        with self._connect() as conn:
            self._assert_mutable(conn, report_id)
            cursor = conn.execute(
                "UPDATE report_versions SET status = ?, stage = ?, error = ? "
                "WHERE report_id = ? AND status NOT IN (?, ?)",
                (
                    ReportStatus.FAILED.value,
                    stage,
                    error,
                    *self._mutable_status_params(report_id),
                ),
            )
            self._assert_updated(cursor)

    def get(self, report_id: str) -> ReportVersion | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM report_versions WHERE report_id = ?", (report_id,)
            ).fetchone()
        return self._to_model(row) if row else None

    def list_versions(
        self, scope_type: ScopeType, scope_id: str
    ) -> list[ReportVersion]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM report_versions WHERE scope_type = ? AND scope_id = ? "
                "ORDER BY version DESC",
                (scope_type.value, scope_id),
            ).fetchall()
        return [self._to_model(row) for row in rows]

    def list_unfinished(self) -> list[ReportVersion]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM report_versions WHERE status IN (?, ?) "
                "ORDER BY created_at",
                (ReportStatus.QUEUED.value, ReportStatus.GENERATING.value),
            ).fetchall()
        return [self._to_model(row) for row in rows]

    def create_generation_input(
        self,
        task_id: str,
        *,
        requested_by: str,
        input_schema_version: int,
        prompt_version: str,
        input_envelope_json: str,
        input_hash: str,
    ) -> ReportGenerationInput:
        """Persist one frozen report generation admission (R2b).

        The row is insert-only: identity, scope, requester, prompt version,
        envelope bytes, and hash are frozen by trigger after admission;
        ``status``/``report_id`` stay mutable for the R2c execution
        lifecycle.
        """
        generation_id = f"rg_{uuid.uuid4().hex}"
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO report_generation_inputs
                   (generation_id, task_id, scope_type, scope_id, status,
                    requested_by, input_schema_version, prompt_version,
                    input_envelope_json, input_hash, created_at)
                   VALUES (?, ?, ?, ?, 'admitted', ?, ?, ?, ?, ?, ?)""",
                (
                    generation_id,
                    task_id,
                    ScopeType.TASK.value,
                    task_id,
                    requested_by,
                    input_schema_version,
                    prompt_version,
                    input_envelope_json,
                    input_hash,
                    created_at,
                ),
            )
        created = self.get_generation_input(generation_id)
        if created is None:  # pragma: no cover - defensive against DB tampering
            raise RuntimeError(
                f"created report generation {generation_id} disappeared"
            )
        return created

    def get_generation_input(
        self, generation_id: str
    ) -> ReportGenerationInput | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM report_generation_inputs "
                "WHERE generation_id = ?",
                (generation_id,),
            ).fetchone()
        return self._to_generation_model(row) if row else None

    def claim_generation(self, generation_id: str) -> ReportGenerationInput | None:
        """Atomically admit -> running for exactly one worker.

        The concurrent loser gets ``None`` and must do nothing: no LLM call,
        no failure write that could clobber the winner.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                "UPDATE report_generation_inputs "
                "SET status = 'running', started_at = ? "
                "WHERE generation_id = ? AND status = 'admitted'",
                (now, generation_id),
            )
            if cursor.rowcount == 0:
                conn.rollback()
                return None
            conn.commit()
        return self.get_generation_input(generation_id)

    def fail_generation(
        self,
        generation_id: str,
        *,
        error_code: str,
        error_message: str,
        model: str | None = None,
    ) -> ReportGenerationInput | None:
        """Terminalize a non-terminal generation (audit columns only).

        ``None`` means the row is already terminal -- the caller must not
        interpret it as a failure to record. ``model`` is kept as execution
        audit metadata when already known (LLM answered, parse failed).
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                "UPDATE report_generation_inputs "
                "SET status = 'failed', failed_at = ?, error_code = ?, "
                "error_message = ?, model = COALESCE(?, model) "
                "WHERE generation_id = ? AND status IN ('admitted', 'running')",
                (now, error_code, error_message, model, generation_id),
            )
            if cursor.rowcount == 0:
                conn.rollback()
                return None
            conn.commit()
        return self.get_generation_input(generation_id)

    def complete_generation_publication(
        self,
        generation_id: str,
        *,
        report_id: str,
        title: str,
        manifest_path: str,
        model: str,
    ) -> ReportGenerationInput:
        """Atomically allocate the report version and complete the generation.

        Runs AFTER the snapshot directory has been published (os.replace):
        version allocation, the ready ``report_versions`` row, and the
        completed generation linkage commit in ONE transaction, so a version
        is only ever visible together with its published manifest, and a
        crash between publish and commit leaves at most an invisible orphan
        directory that restart recovery fails closed.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            generation_row = conn.execute(
                "SELECT task_id FROM report_generation_inputs "
                "WHERE generation_id = ?",
                (generation_id,),
            ).fetchone()
            if generation_row is None:
                conn.rollback()
                raise KeyError(generation_id)
            task_id = generation_row["task_id"]
            version_row = conn.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 AS next_version "
                "FROM report_versions WHERE scope_type = ? AND scope_id = ?",
                (ScopeType.TASK.value, task_id),
            ).fetchone()
            version = int(version_row["next_version"])
            conn.execute(
                """INSERT INTO report_versions
                   (report_id, version, scope_type, scope_id, status, title,
                    task_ids_json, stage, progress, generated_at,
                    manifest_path, warnings_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'ready', 100, ?, ?, '[]', ?)""",
                (
                    report_id,
                    version,
                    ScopeType.TASK.value,
                    task_id,
                    ReportStatus.READY.value,
                    title,
                    json.dumps([task_id]),
                    now,
                    manifest_path,
                    now,
                ),
            )
            cursor = conn.execute(
                "UPDATE report_generation_inputs "
                "SET status = 'completed', completed_at = ?, report_id = ?, "
                "produced_version = ?, model = ? "
                "WHERE generation_id = ? AND status = 'running'",
                (now, report_id, version, model, generation_id),
            )
            if cursor.rowcount == 0:
                conn.rollback()
                raise RuntimeError(
                    "report generation is not in the running state"
                )
            conn.commit()
        completed = self.get_generation_input(generation_id)
        if completed is None:  # pragma: no cover - defensive against tampering
            raise RuntimeError(
                f"completed report generation {generation_id} disappeared"
            )
        return completed

    def list_stale_generations(self) -> list[ReportGenerationInput]:
        """Non-terminal generations (restart/shutdown recovery input)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM report_generation_inputs "
                "WHERE status IN ('admitted', 'running') ORDER BY created_at"
            ).fetchall()
        return [self._to_generation_model(row) for row in rows]

    @staticmethod
    def _to_generation_model(row: sqlite3.Row) -> ReportGenerationInput:
        return ReportGenerationInput(
            generation_id=row["generation_id"],
            task_id=row["task_id"],
            scope_type=ScopeType(row["scope_type"]),
            scope_id=row["scope_id"],
            status=row["status"],
            requested_by=row["requested_by"],
            input_schema_version=row["input_schema_version"],
            prompt_version=row["prompt_version"],
            input_envelope_json=row["input_envelope_json"],
            input_hash=row["input_hash"],
            report_id=row["report_id"],
            produced_version=row["produced_version"],
            model=row["model"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            failed_at=row["failed_at"],
            error_code=row["error_code"],
            error_message=row["error_message"],
        )

    @staticmethod
    def _to_model(row: sqlite3.Row) -> ReportVersion:
        return ReportVersion(
            report_id=row["report_id"],
            version=row["version"],
            scope_type=row["scope_type"],
            scope_id=row["scope_id"],
            status=row["status"],
            title=row["title"],
            task_ids=json.loads(row["task_ids_json"]),
            stage=row["stage"],
            progress=row["progress"],
            generated_at=row["generated_at"],
            manifest_path=row["manifest_path"],
            offline_bundle_path=row["offline_bundle_path"],
            warnings=[
                AdapterWarning.model_validate(value)
                for value in json.loads(row["warnings_json"])
            ],
            error=row["error"],
        )
