from __future__ import annotations

from typing import Any

from ..case_analysis.db_utils import get_case_report_from_db


class AnalysisChaptersAdapter:
    """Load the existing case-analysis output without interpreting its tokens."""

    def load_task(self, files_db_path: str, task_id: str) -> dict[str, Any]:
        row = get_case_report_from_db(files_db_path, task_id) if files_db_path else None
        if not row:
            return {"markdown": "", "generated_at": "", "filtered_files": []}

        filtered_files = row.get("filtered_files")
        return {
            "markdown": row.get("case_report") or "",
            "generated_at": self._timestamp(row.get("updated_at")),
            "filtered_files": filtered_files if isinstance(filtered_files, list) else [],
        }

    @staticmethod
    def _timestamp(value: Any) -> str:
        return "" if value is None else str(value)
