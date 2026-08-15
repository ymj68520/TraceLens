"""Task-local append-only storage for assembled Final Reports."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from .final_report_assembly import (
    FINAL_REPORT_ASSEMBLED,
    FinalReportPublication,
    FinalReportVersion,
)


class FinalReportRepository:
    """Store only successful immutable report versions and publication facts."""

    def __init__(
        self,
        db_path: Path | str,
        *,
        ensure_schema: bool = True,
        read_only: bool = False,
    ):
        self.db_path = Path(db_path)
        self.read_only = read_only
        if ensure_schema:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        if self.read_only:
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
                CREATE TABLE IF NOT EXISTS final_report_versions (
                    report_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    report_version INTEGER NOT NULL,
                    report_schema_version TEXT NOT NULL,
                    assembly_rule_version TEXT NOT NULL,
                    report_dataset_hash TEXT NOT NULL,
                    citation_graph_hash TEXT NOT NULL,
                    section_plan_hash TEXT NOT NULL,
                    sections_json TEXT NOT NULL,
                    citation_manifest_json TEXT NOT NULL,
                    claim_manifest_json TEXT NOT NULL,
                    validation_status TEXT NOT NULL,
                    validation_errors_json TEXT NOT NULL DEFAULT '[]',
                    validation_warnings_json TEXT NOT NULL DEFAULT '[]',
                    final_report_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    markdown_text TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    UNIQUE(task_id, report_version)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_final_report_versions_scope
                ON final_report_versions(task_id, report_version DESC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS final_report_publications (
                    publication_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    report_id TEXT NOT NULL,
                    report_version INTEGER NOT NULL,
                    final_report_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    published_at INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    UNIQUE(task_id, report_id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_final_report_publications_scope
                ON final_report_publications(task_id, published_at DESC)
                """
            )
            conn.commit()

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def create_assembled(self, report: FinalReportVersion) -> FinalReportVersion:
        if self.read_only:
            raise RuntimeError("read-only final report repository")
        if report.status != FINAL_REPORT_ASSEMBLED:
            raise ValueError("only assembled reports can be persisted")
        if report.validation_status != "valid":
            raise ValueError("only valid assembled reports can be persisted")
        report_id = report.report_id or str(uuid.uuid4())
        created_at = int(time.time())
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT COALESCE(MAX(report_version), 0) + 1 AS next_version
                FROM final_report_versions
                WHERE task_id = ?
                """,
                (report.task_id,),
            ).fetchone()
            report_version = int(row["next_version"])
            persisted = report.model_copy(update={
                "report_id": report_id,
                "report_version": report_version,
                "created_at": created_at,
            })
            if persisted.final_report_hash != persisted.compute_hash():
                raise ValueError("final report hash does not match canonical content")
            conn.execute(
                """
                INSERT INTO final_report_versions (
                    report_id, task_id, report_version,
                    report_schema_version, assembly_rule_version,
                    report_dataset_hash, citation_graph_hash, section_plan_hash,
                    sections_json, citation_manifest_json, claim_manifest_json,
                    validation_status, validation_errors_json,
                    validation_warnings_json, final_report_hash, status,
                    markdown_text, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    persisted.report_id,
                    persisted.task_id,
                    persisted.report_version,
                    persisted.report_schema_version,
                    persisted.assembly_rule_version,
                    persisted.report_dataset_hash,
                    persisted.citation_graph_hash,
                    persisted.section_plan_hash,
                    self._json([section.model_dump(mode="json") for section in persisted.sections]),
                    self._json([
                        citation.model_dump(mode="json")
                        for citation in persisted.citation_manifest
                    ]),
                    self._json([
                        claim.model_dump(mode="json")
                        for claim in persisted.claim_manifest
                    ]),
                    persisted.validation_status,
                    self._json([
                        error.model_dump(mode="json")
                        for error in persisted.validation_errors
                    ]),
                    self._json([
                        warning.model_dump(mode="json")
                        for warning in persisted.validation_warnings
                    ]),
                    persisted.final_report_hash,
                    persisted.status,
                    persisted.markdown_text,
                    persisted.created_at,
                ),
            )
            conn.commit()
        result = self.get(persisted.report_id)
        if result is None:  # pragma: no cover
            raise RuntimeError(f"final report {persisted.report_id} disappeared")
        return result

    def get(self, report_id: str) -> Optional[FinalReportVersion]:
        with self._connect() as conn:
            try:
                row = conn.execute(
                    "SELECT * FROM final_report_versions WHERE report_id = ?",
                    (report_id,),
                ).fetchone()
            except sqlite3.OperationalError as exc:
                if "no such table" not in str(exc):
                    raise
                row = None
        return self._to_report(row) if row else None

    def get_for_task(
        self, task_id: str, report_id: str
    ) -> Optional[FinalReportVersion]:
        with self._connect() as conn:
            try:
                row = conn.execute(
                    """
                    SELECT * FROM final_report_versions
                    WHERE task_id = ? AND report_id = ?
                    """,
                    (task_id, report_id),
                ).fetchone()
            except sqlite3.OperationalError as exc:
                if "no such table" not in str(exc):
                    raise
                row = None
        return self._to_report(row) if row else None

    def get_for_task_strict(
        self, task_id: str, report_id: str
    ) -> Optional[FinalReportVersion]:
        """Read one exact report while preserving storage errors."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM final_report_versions
                WHERE task_id = ? AND report_id = ?
                """,
                (task_id, report_id),
            ).fetchone()
        return self._to_report(row) if row else None

    def list_reports(self, task_id: str) -> List[FinalReportVersion]:
        with self._connect() as conn:
            try:
                rows = conn.execute(
                    """
                    SELECT * FROM final_report_versions
                    WHERE task_id = ?
                    ORDER BY report_version DESC
                    """,
                    (task_id,),
                ).fetchall()
            except sqlite3.OperationalError as exc:
                if "no such table" not in str(exc):
                    raise
                rows = []
        return [self._to_report(row) for row in rows]

    def publish(
        self,
        task_id: str,
        report_id: str,
        *,
        final_report_hash: str,
    ) -> FinalReportPublication:
        if self.read_only:
            raise RuntimeError("read-only final report repository")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            report = conn.execute(
                """
                SELECT report_id, task_id, report_version, final_report_hash, status
                FROM final_report_versions
                WHERE task_id = ? AND report_id = ?
                """,
                (task_id, report_id),
            ).fetchone()
            if report is None:
                conn.rollback()
                raise KeyError(report_id)
            if report["status"] != FINAL_REPORT_ASSEMBLED:
                conn.rollback()
                raise ValueError("final report is not assembled")
            if report["final_report_hash"] != final_report_hash:
                conn.rollback()
                raise ValueError("final report hash mismatch")
            existing = conn.execute(
                """
                SELECT * FROM final_report_publications
                WHERE task_id = ? AND report_id = ?
                """,
                (task_id, report_id),
            ).fetchone()
            if existing is not None:
                conn.commit()
                return self._to_publication(existing)
            now = int(time.time())
            publication = FinalReportPublication(
                publication_id=str(uuid.uuid4()),
                task_id=task_id,
                report_id=report_id,
                report_version=report["report_version"],
                final_report_hash=report["final_report_hash"],
                status="published",
                published_at=now,
                created_at=now,
            )
            conn.execute(
                """
                INSERT INTO final_report_publications (
                    publication_id, task_id, report_id, report_version,
                    final_report_hash, status, published_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    publication.publication_id,
                    publication.task_id,
                    publication.report_id,
                    publication.report_version,
                    publication.final_report_hash,
                    publication.status,
                    publication.published_at,
                    publication.created_at,
                ),
            )
            conn.commit()
        return publication

    def get_publication(
        self, task_id: str, report_id: str
    ) -> Optional[FinalReportPublication]:
        with self._connect() as conn:
            try:
                row = conn.execute(
                    """
                    SELECT * FROM final_report_publications
                    WHERE task_id = ? AND report_id = ?
                    """,
                    (task_id, report_id),
                ).fetchone()
            except sqlite3.OperationalError as exc:
                if "no such table" not in str(exc) or self.read_only:
                    raise
                row = None
        return self._to_publication(row) if row else None

    @classmethod
    def read_only(cls, db_path: Path | str) -> "FinalReportRepository":
        """Open report history without creating tables or writing recovery state."""
        return cls(db_path, ensure_schema=False, read_only=True)

    @staticmethod
    def _to_report(row: sqlite3.Row) -> FinalReportVersion:
        from .final_report_assembly import (
            FinalReportAssemblyError,
            FinalReportClaim,
            FinalReportCitation,
            FinalReportSection,
        )

        return FinalReportVersion(
            report_id=row["report_id"],
            task_id=row["task_id"],
            report_version=row["report_version"],
            report_schema_version=row["report_schema_version"],
            assembly_rule_version=row["assembly_rule_version"],
            report_dataset_hash=row["report_dataset_hash"],
            citation_graph_hash=row["citation_graph_hash"],
            section_plan_hash=row["section_plan_hash"],
            sections=[
                FinalReportSection.model_validate(item)
                for item in json.loads(row["sections_json"] or "[]")
            ],
            citation_manifest=[
                FinalReportCitation.model_validate(item)
                for item in json.loads(row["citation_manifest_json"] or "[]")
            ],
            claim_manifest=[
                FinalReportClaim.model_validate(item)
                for item in json.loads(row["claim_manifest_json"] or "[]")
            ],
            validation_status=row["validation_status"],
            validation_errors=[
                FinalReportAssemblyError.model_validate(item)
                for item in json.loads(row["validation_errors_json"] or "[]")
            ],
            validation_warnings=[
                FinalReportAssemblyError.model_validate(item)
                for item in json.loads(row["validation_warnings_json"] or "[]")
            ],
            final_report_hash=row["final_report_hash"],
            status=row["status"],
            markdown_text=row["markdown_text"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _to_publication(row: sqlite3.Row) -> FinalReportPublication:
        return FinalReportPublication(
            publication_id=row["publication_id"],
            task_id=row["task_id"],
            report_id=row["report_id"],
            report_version=row["report_version"],
            final_report_hash=row["final_report_hash"],
            status=row["status"],
            published_at=row["published_at"],
            created_at=row["created_at"],
        )
