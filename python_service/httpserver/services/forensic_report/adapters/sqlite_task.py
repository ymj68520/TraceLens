from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote

from ..ids import stable_record_id
from ..models import AdapterContext, CategorySpec, DataState, ProbeResult, ReportRecord, Severity


class SqliteTaskReportAdapter:
    """Expose structured file evidence from a task's read-only files database."""

    name = "sqlite_task_files"
    platform = "forensics"
    _file_fields = (
        "name", "path", "size", "extension", "category", "type", "mtime", "ctime",
        "is_deleted", "md5", "scene_type", "scene_priority", "scene_relevant",
    )
    _fallback_limit = 500

    def probe(self, context: AdapterContext) -> ProbeResult:
        path = self._files_db(context)
        if not path.is_file():
            return ProbeResult(available=False, reason="files database is missing")
        try:
            with self._connect(path) as conn:
                table = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'files'"
                ).fetchone()
            return ProbeResult(
                available=table is not None,
                reason=None if table is not None else "files table is missing",
            )
        except sqlite3.Error as exc:
            return ProbeResult(available=False, reason=str(exc))

    def categories(self, context: AdapterContext) -> list[CategorySpec]:
        path = self._files_db(context)
        if not path.is_file():
            return []
        try:
            with self._connect(path) as conn:
                if not self._table_exists(conn, "files"):
                    return []
                if not self._has_rows(conn, "files"):
                    return []
                return [CategorySpec(
                    category_id="evidence.files",
                    platform=self.platform,
                    title="文件证据",
                    renderer="table",
                    source_table="files",
                    page_size=50,
                    searchable_fields=[
                        "name", "path", "category", "extension", "scene_type",
                    ],
                )]
        except sqlite3.Error:
            return []

    def iter_records(
        self, context: AdapterContext, category: CategorySpec
    ) -> Iterator[ReportRecord]:
        if category.source_table != "files":
            return
        path = self._files_db(context)
        if not path.is_file():
            return
        with self._connect(path) as conn:
            columns = self._columns(conn, "files")
            selected = [name for name in self._file_fields if name in columns]
            if not selected:
                return
            query = (
                f'SELECT id, {self._column_list(selected)} FROM "files" '
                "ORDER BY id LIMIT ?"
            )
            for row in conn.execute(query, (self._fallback_limit,)):
                record_id, *values = row
                data = dict(zip(selected, values))
                yield self._record(
                    context,
                    source_id=record_id,
                    title=data.get("path") or data.get("name") or f"文件 {record_id}",
                    source_path=data.get("path"),
                    fields=data,
                    timestamp=data.get("mtime") or data.get("ctime"),
                    data_state=(
                        DataState.DELETED
                        if data.get("is_deleted")
                        else DataState.EXISTING
                    ),
                    is_relevant=bool(
                        data.get("scene_relevant") or data.get("scene_priority", 0)
                    ),
                    severity=self._severity(data.get("scene_priority")),
                    hashes={"md5": data["md5"]} if data.get("md5") else {},
                )

    def _record(
        self,
        context: AdapterContext,
        *,
        source_id: Any,
        title: str,
        fields: dict[str, Any],
        source_path: str | None,
        timestamp: Any,
        data_state: DataState,
        severity: Severity,
        is_relevant: bool,
        hashes: dict[str, str],
    ) -> ReportRecord:
        category = "evidence.files"
        source_table = "files"
        return ReportRecord(
            record_id=stable_record_id(
                context.evidence_id,
                self.platform,
                category,
                source_table,
                str(source_id),
            ),
            category=category,
            title=str(title),
            timestamp=self._int_or_none(timestamp),
            source_path=source_path,
            source_table=source_table,
            source_record_id=str(source_id),
            data_state=data_state,
            severity=severity,
            is_relevant=is_relevant,
            hashes=hashes,
            fields=fields,
        )

    @staticmethod
    def _files_db(context: AdapterContext) -> Path:
        return Path(context.db_paths.get("files", ""))

    @staticmethod
    def _connect(path: Path) -> sqlite3.Connection:
        uri = f"file:{quote(str(path.resolve()), safe='/')}?mode=ro"
        return sqlite3.connect(uri, uri=True, timeout=10)

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone() is not None

    @staticmethod
    def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
        return {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}

    @staticmethod
    def _column_list(columns: list[str]) -> str:
        return ", ".join(f'"{column}"' for column in columns)

    @staticmethod
    def _has_rows(conn: sqlite3.Connection, table: str) -> bool:
        return conn.execute(f'SELECT 1 FROM "{table}" LIMIT 1').fetchone() is not None

    @staticmethod
    def _int_or_none(value: Any) -> int | None:
        try:
            return int(value) if value is not None and value != "" else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _severity(priority: Any) -> Severity:
        try:
            value = int(priority or 0)
        except (TypeError, ValueError):
            value = 0
        if value >= 100:
            return Severity.CRITICAL
        if value >= 75:
            return Severity.HIGH
        if value >= 50:
            return Severity.MEDIUM
        if value >= 25:
            return Severity.LOW
        return Severity.INFO


def build_default_adapters() -> list[SqliteTaskReportAdapter]:
    return [SqliteTaskReportAdapter()]
