from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import quote


class AnalysisChaptersAdapter:
    """Load the existing case-analysis output without interpreting its tokens."""

    def load_task(self, files_db_path: str, task_id: str) -> dict[str, Any]:
        row = self._read_task(files_db_path, task_id) if files_db_path else None
        if not row:
            return {"markdown": "", "generated_at": "", "filtered_files": []}

        filtered_files = row.get("filtered_files")
        return {
            "markdown": row.get("case_report") or "",
            "generated_at": self._timestamp(row.get("updated_at")),
            "filtered_files": filtered_files if isinstance(filtered_files, list) else [],
        }

    @staticmethod
    def _read_task(files_db_path: str, task_id: str) -> dict[str, Any] | None:
        path = Path(files_db_path)
        if not path.is_file():
            return None
        uri = f"file:{quote(str(path.resolve()), safe='/')}?mode=ro"
        try:
            with sqlite3.connect(uri, uri=True, timeout=10) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT * FROM case_analysis WHERE task_id = ?", (task_id,)
                ).fetchone()
        except sqlite3.Error:
            return None
        if row is None:
            return None
        try:
            filtered_files = json.loads(row["filtered_files"] or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            filtered_files = []
        return {
            "case_report": row["case_report"],
            "updated_at": row["updated_at"],
            "filtered_files": filtered_files,
        }

    @staticmethod
    def _timestamp(value: Any) -> str:
        return "" if value is None else str(value)
