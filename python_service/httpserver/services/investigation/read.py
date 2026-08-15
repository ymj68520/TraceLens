"""Read-only Investigation Workbench data service (Phase C9a).

Exposes the frozen read projections the Workbench shell needs -- evidence
list, the single captured Snapshot of one evidence (Initial Analysis source),
and the exact historical claims of one analysis version.

C9a boundaries: this service never captures, creates, transitions, reviews,
links, or refreshes anything.  All reads go through the strictly read-only
``InvestigationGraphReader`` (mode=ro + query_only, B2), a missing store is
"no findings" (empty/None), and a corrupt/unsupported store fails closed
(EvidenceStoreError -> 503), mirroring the C8b graph semantics.
"""

from __future__ import annotations

import asyncio

from ..evidence.exceptions import EvidenceNotFoundError
from .graph_reader import InvestigationGraphReader
from .models import AnalysisClaim, EvidenceSnapshot, EvidenceSummary
from .paths import investigation_db_path_for_task


class InvestigationReadService:
    """Task-scoped, strictly read-only Workbench data facade (C9a)."""

    def __init__(self, cpp_backend):
        self._cpp_backend = cpp_backend

    async def _reader_for(
        self, task_id: str
    ) -> InvestigationGraphReader | None:
        task = await self._cpp_backend.get_task(task_id)
        if not isinstance(task, dict) or task.get("id") != task_id:
            raise EvidenceNotFoundError("task not found")
        db_path = investigation_db_path_for_task(task)
        if not db_path.exists():
            # A task without an investigation.db yet has no findings; the GET
            # never creates or migrates the store (B2).
            return None
        return InvestigationGraphReader(db_path, task_id)

    async def list_evidence(self, task_id: str) -> list[EvidenceSummary]:
        reader = await self._reader_for(task_id)
        if reader is None:
            return []
        return await asyncio.to_thread(reader.list_evidence)

    async def get_snapshot(
        self, task_id: str, evidence_key: str
    ) -> EvidenceSnapshot | None:
        """Return the captured Snapshot of one canonical evidence key.

        Read-only: an evidence that was never captured is ``None`` (404); this
        never captures on demand.  The Initial Analysis shown by the
        Workbench comes from this snapshot payload, never from a re-read of
        ``files.db``.
        """
        reader = await self._reader_for(task_id)
        if reader is None:
            return None
        return await asyncio.to_thread(reader.latest_snapshot, evidence_key)

    async def list_analysis_claims(
        self, task_id: str, analysis_id: str
    ) -> list[AnalysisClaim] | None:
        """Exact persisted claims of one exact analysis version.

        ``None`` means the analysis_id does not belong to this task (404);
        an empty list means the analysis exists but produced no claims.
        """
        reader = await self._reader_for(task_id)
        if reader is None:
            return None
        claims = await asyncio.to_thread(reader.claims_for_analysis, analysis_id)
        return None if claims is None else list(claims)


__all__ = ["InvestigationReadService"]
