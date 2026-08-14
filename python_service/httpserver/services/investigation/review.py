"""Task-scoped analyst review orchestration for Secondary Analysis (C6)."""

from __future__ import annotations

import asyncio
import sqlite3

from ..evidence.exceptions import EvidenceNotFoundError, EvidenceStoreError
from .models import AnalysisReviewDecision, SecondaryAnalysis
from .paths import investigation_db_path_for_task
from .repository import (
    AnalysisReviewConflictError,
    InvestigationRepository,
)


class InvestigationReviewService:
    """Apply one explicit analyst decision to an exact analysis version."""

    def __init__(self, cpp_backend):
        self._cpp_backend = cpp_backend

    async def review(
        self,
        task_id: str,
        analysis_id: str,
        *,
        decision: AnalysisReviewDecision,
        reviewer: str,
        reason: str | None = None,
    ) -> SecondaryAnalysis:
        task = await self._cpp_backend.get_task(task_id)
        if not isinstance(task, dict) or task.get("id") != task_id:
            raise EvidenceNotFoundError("analysis not found")

        if not task.get("output_files_db") and not task.get("output_events_db"):
            raise EvidenceNotFoundError("analysis not found")
        db_path = investigation_db_path_for_task(task)
        if not db_path.exists():
            raise EvidenceNotFoundError("analysis not found")

        try:
            repository = InvestigationRepository(db_path, task_id)
            return await asyncio.to_thread(
                repository.review_analysis,
                analysis_id,
                decision=decision,
                reviewer=reviewer,
                reason=reason,
            )
        except sqlite3.DatabaseError as exc:
            raise EvidenceStoreError("investigation database is unavailable") from exc


__all__ = [
    "AnalysisReviewConflictError",
    "InvestigationReviewService",
]
