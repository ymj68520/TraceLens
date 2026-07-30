from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .models import AdapterWarning, ReportStatus, ReportVersion, ScopeType


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
                """
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

    def mark_generating(self, report_id: str, stage: str) -> None:
        with self._connect() as conn:
            self._assert_mutable(conn, report_id)
            conn.execute(
                "UPDATE report_versions SET status = ?, stage = ?, progress = 1 "
                "WHERE report_id = ?",
                (ReportStatus.GENERATING.value, stage, report_id),
            )

    def update_progress(self, report_id: str, stage: str, progress: int) -> None:
        with self._connect() as conn:
            self._assert_mutable(conn, report_id)
            conn.execute(
                "UPDATE report_versions SET stage = ?, progress = ? WHERE report_id = ?",
                (stage, max(0, min(progress, 99)), report_id),
            )

    def mark_ready(
        self, report_id: str, manifest_path: str, warnings: list[AdapterWarning]
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            self._assert_mutable(conn, report_id)
            conn.execute(
                """UPDATE report_versions
                   SET status = ?, stage = 'ready', progress = 100,
                       generated_at = ?, manifest_path = ?, warnings_json = ?
                   WHERE report_id = ?""",
                (
                    ReportStatus.READY.value,
                    now,
                    manifest_path,
                    json.dumps([warning.model_dump(mode="json") for warning in warnings]),
                    report_id,
                ),
            )

    def mark_failed(self, report_id: str, stage: str, error: str) -> None:
        with self._connect() as conn:
            self._assert_mutable(conn, report_id)
            conn.execute(
                "UPDATE report_versions SET status = ?, stage = ?, error = ? "
                "WHERE report_id = ?",
                (ReportStatus.FAILED.value, stage, error, report_id),
            )

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
