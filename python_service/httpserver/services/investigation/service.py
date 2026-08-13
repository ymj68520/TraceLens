"""Public Investigation capture orchestration (Phase C3).

The service is the narrow bridge between the HTTP request and C4a persistence:
request fields -> EvidenceResolver (trusted task-owned source) -> second task
liveness/path lookup -> task-bound InvestigationRepository -> Snapshot.

It accepts no client paths or database paths. The second task lookup is
intentional: it validates the current task before choosing the physical
investigation.db destination, rather than reusing stale resolver context.
"""

from __future__ import annotations

import asyncio

from ..evidence.exceptions import EvidenceNotFoundError
from .paths import investigation_db_path_for_task
from .repository import InvestigationRepository
from .models import EvidenceSnapshot


class InvestigationCaptureService:
    """Resolve and capture one task-scoped Evidence Snapshot."""

    def __init__(self, cpp_backend, evidence_resolver):
        self._cpp_backend = cpp_backend
        self._evidence_resolver = evidence_resolver

    async def capture(self, task_id: str, evidence_key: str) -> EvidenceSnapshot:
        # Resolver owns the first trusted get_task() and all Evidence DB paths.
        resolved = await self._evidence_resolver.resolve_evidence(
            task_id, evidence_key
        )

        # Deliberately perform a second lookup: current task liveness and the
        # task-scoped investigation.db destination must be checked separately.
        task = await self._cpp_backend.get_task(task_id)
        if not isinstance(task, dict) or task.get("id") != task_id:
            raise EvidenceNotFoundError(f"task not found: {task_id}")

        db_path = investigation_db_path_for_task(task)
        repository = InvestigationRepository(db_path, task_id)
        # Repository uses synchronous sqlite; keep blocking IO off the event loop.
        return await asyncio.to_thread(repository.capture_if_absent, resolved)
