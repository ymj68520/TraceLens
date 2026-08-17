"""Live-task write boundary helpers (Phase D4b).

A terminal write (completion, failure, shutdown sweep, restart recovery)
must never create or resurrect a task-owned investigation store. These
helpers revalidate task liveness through the trusted C++ registry and open
the store existing-only; when liveness or identity cannot be confirmed the
caller must discard the result without writing (fail-closed).

E11 is preserved: the submitted ``db_path`` is validated, never replaced,
and execution input is never re-resolved here.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from ..evidence.exceptions import EvidenceStoreError
from .paths import investigation_db_path_for_task
from .repository import InvestigationRepository

logger = logging.getLogger(__name__)


def open_existing_store(db_path: Path, task_id: str) -> InvestigationRepository | None:
    """Open the store existing-only; ``None`` means "do not write"."""
    try:
        return InvestigationRepository.open_existing(db_path, task_id)
    except EvidenceStoreError:
        logger.info(
            "task %s store missing at write boundary; terminal write skipped",
            task_id,
        )
        return None


async def open_live_task_store(
    cpp_backend, task_id: str, submitted_db_path: Path
) -> InvestigationRepository | None:
    """Live-task write boundary for executor terminal writes.

    - task definitively absent (registry miss) -> ``None`` (drop the result)
    - backend lookup unconfirmable (transport error) -> ``None`` (fail-closed;
      never fall back to blind construction, which could resurrect a store)
    - current trusted path != submitted path -> ``None`` (identity mismatch;
      the row belongs to the admission-time store, never the new one)
    - store missing/unsupported -> ``None`` (no mkdir, no migration)
    """
    try:
        task = await cpp_backend.get_task(task_id)
    except Exception:
        logger.warning(
            "task liveness could not be confirmed (%s); terminal write skipped",
            task_id,
        )
        return None
    if task is None:
        logger.info(
            "task %s no longer exists; terminal result discarded", task_id
        )
        return None
    try:
        current_path = investigation_db_path_for_task(task)
    except EvidenceStoreError:
        logger.warning(
            "task %s has no trusted store path; terminal write skipped", task_id
        )
        return None
    if Path(current_path) != Path(submitted_db_path):
        logger.warning(
            "task %s store identity changed (%s != %s); terminal write skipped",
            task_id,
            current_path,
            submitted_db_path,
        )
        return None
    return await asyncio.to_thread(open_existing_store, submitted_db_path, task_id)
