"""Independent Event Refresh execution (Phase C7c-2)."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
from pathlib import Path
from typing import Any, Optional

import httpx

from .event_refresh_structured import (
    StructuredEventRefreshOutputError,
    parse_event_refresh_response,
)
from .models import EventRefresh, EventRefreshEnvelopeV2, EventRefreshStatus, parse_event_refresh_envelope
from ..evidence.exceptions import EvidenceStoreError
from .paths import investigation_db_path_for_task
from .prompts import (
    EVENT_REFRESH_PROMPT_VERSION,
    REFRESH_ENVELOPE_PROMPT_COMPAT,
    build_event_refresh_user_prompt,
    get_event_refresh_prompt,
)
from .repository import InvestigationRepository
from .live_store import open_existing_store, open_live_task_store

logger = logging.getLogger(__name__)


def _classify_refresh_error(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, httpx.ReadTimeout):
        return "llm_timeout", "LLM request timed out"
    if isinstance(exc, httpx.ConnectError):
        return "llm_connection_error", "LLM service unreachable"
    if isinstance(exc, httpx.HTTPStatusError):
        return "llm_http_error", "LLM request failed"
    return "execution_error", "event refresh execution failed"


class EventRefreshExecutor:
    """Execute queued V2 refreshes without reselecting live investigation input."""

    def __init__(self, cpp_backend, llm_service, event_service):
        self._cpp_backend = cpp_backend
        self._llm_service = llm_service
        self._event_service = event_service
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._task_ctx: dict[str, tuple[str, Path]] = {}
        self._admission_lock = asyncio.Lock()
        self._accepting = True

    async def initialize(self) -> None:
        await self._recover_stale_refreshes()

    async def submit(
        self, task_id: str, event_id: str, *, requested_by: str | None = None
    ) -> EventRefresh:
        async with self._admission_lock:
            if not self._accepting:
                raise RuntimeError("event refresh executor is shutting down")
            db_path = await self._event_service.resolve_db_path(task_id)
            refresh = await self._event_service.create_event_refresh(
                task_id, event_id, requested_by=requested_by
            )
            try:
                task = asyncio.create_task(
                    self._execute(refresh.refresh_id, task_id, db_path)
                )
            except Exception:
                # D4b: existing-store-only — the scheduling-failure write must
                # not recreate a deleted task's store.
                repo = open_existing_store(db_path, task_id)
                if repo is not None:
                    failed = await asyncio.to_thread(
                        repo.fail_event_refresh,
                        refresh.refresh_id,
                        error_code="execution_schedule_failed",
                        error_message="event refresh could not be scheduled",
                    )
                    return failed or refresh
                return refresh
            self._tasks[refresh.refresh_id] = task
            self._task_ctx[refresh.refresh_id] = (task_id, db_path)
            task.add_done_callback(
                lambda done, rid=refresh.refresh_id: self._on_task_done(rid, done)
            )
            return refresh

    async def shutdown(self) -> None:
        async with self._admission_lock:
            self._accepting = False
            tracked = dict(self._tasks)
            contexts = dict(self._task_ctx)
        for task in tracked.values():
            task.cancel()
        if tracked:
            await asyncio.gather(*tracked.values(), return_exceptions=True)
        # D4b: each shutdown write goes through the live-task boundary; a task
        # deleted before/during shutdown is never resurrected on disk.
        for refresh_id, (task_id, db_path) in contexts.items():
            repo = await open_live_task_store(self._cpp_backend, task_id, db_path)
            if repo is None:
                continue
            try:
                await asyncio.to_thread(
                    repo.fail_event_refresh,
                    refresh_id,
                    error_code="service_shutdown",
                    error_message="event refresh cancelled during service shutdown",
                )
            except Exception:
                logger.exception("Failed to record refresh shutdown: %s", refresh_id)
        async with self._admission_lock:
            self._tasks.clear()
            self._task_ctx.clear()

    async def _execute(self, refresh_id: str, task_id: str, db_path: Path) -> None:
        """Execute one refresh from its frozen input (C7c-2).

        D4b: terminal writes go through the live-task boundary; a task deleted
        mid-flight discards the result without writing.
        """
        # D4b: worker terminal paths are existing-store-only from the first
        # access. A deleted store must never be recreated before claim/read.
        repo = InvestigationRepository.open_existing(db_path, task_id)
        claimed = False
        model: str | None = None
        try:
            refresh = await asyncio.to_thread(repo.claim_event_refresh, refresh_id)
            if refresh is None:
                return
            claimed = True
            envelope = parse_event_refresh_envelope(refresh.input_envelope_json)
            if not isinstance(envelope, EventRefreshEnvelopeV2):
                await self._fail(task_id, db_path, refresh_id, "historical_envelope", "historical refresh input is not executable")
                return
            canonical = __import__("json").dumps(
                envelope.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            actual_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            if canonical != refresh.input_envelope_json or not hmac.compare_digest(actual_hash, refresh.input_hash):
                await self._fail(task_id, db_path, refresh_id, "input_integrity_error", "stored refresh input failed integrity validation")
                return
            if envelope.prompt_version not in REFRESH_ENVELOPE_PROMPT_COMPAT.get(envelope.schema_version, frozenset()):
                await self._fail(task_id, db_path, refresh_id, "input_integrity_error", "refresh envelope prompt is incompatible")
                return
            system_prompt, user_template = get_event_refresh_prompt(envelope.prompt_version)
            if self._llm_service is None:
                await self._fail(task_id, db_path, refresh_id, "llm_unavailable", "LLM service is not initialized")
                return
            result = await self._llm_service.chat_completion(
                system_prompt,
                build_event_refresh_user_prompt(user_template, envelope),
            )
            model = result.get("model") or None
            content = result.get("content", "")
            if not content:
                await self._fail(task_id, db_path, refresh_id, "llm_empty_response", "LLM returned empty response", model=model)
                return
            try:
                response = parse_event_refresh_response(content)
            except StructuredEventRefreshOutputError:
                logger.exception("Structured Event Refresh output invalid: %s", refresh_id)
                await self._fail(task_id, db_path, refresh_id, "structured_output_invalid", "structured refresh response is invalid", model=model)
                return
            # D4b live-task write boundary: the completion write only reaches a
            # confirmed-live task through the existing-only store.
            live_repo = await open_live_task_store(
                self._cpp_backend, task_id, db_path
            )
            if live_repo is None:
                return
            completed = await asyncio.to_thread(
                live_repo.complete_event_refresh,
                refresh_id,
                title=response.title,
                summary=response.summary,
                model=model or "unknown",
            )
            if completed.status in (EventRefreshStatus.completed, EventRefreshStatus.failed):
                return
            raise RuntimeError("unexpected refresh completion state")
        except asyncio.CancelledError:
            # D4b: existing-only open; a deleted task's store cannot be
            # recreated here (full liveness check is impossible post-cancel).
            if claimed:
                live_repo = open_existing_store(db_path, task_id)
                if live_repo is not None:
                    try:
                        live_repo.fail_event_refresh(
                            refresh_id, error_code="service_shutdown",
                            error_message="event refresh cancelled during service shutdown", model=model,
                        )
                    except Exception:
                        logger.exception(
                            "Failed to record refresh shutdown: %s", refresh_id
                        )
            raise
        except Exception as exc:
            if claimed:
                logger.exception("Event Refresh execution failed: %s", refresh_id)
                await self._fail(task_id, db_path, refresh_id, *_classify_refresh_error(exc), model=model)

    async def _fail(self, task_id, db_path, refresh_id, error_code, error_message, *, model=None):
        """Write failed state through the live-task boundary (never raises)."""
        repo = await open_live_task_store(self._cpp_backend, task_id, db_path)
        if repo is None:
            return
        try:
            await asyncio.to_thread(
                repo.fail_event_refresh,
                refresh_id,
                error_code=error_code,
                error_message=error_message,
                model=model,
            )
        except Exception:
            logger.exception("Failed to persist Event Refresh failure: %s", refresh_id)

    def _on_task_done(self, refresh_id: str, task: asyncio.Task[None]) -> None:
        try:
            exception = task.exception()
        except asyncio.CancelledError:
            exception = None
        if exception is not None:
            logger.error("Event Refresh task failed: %s", refresh_id, exc_info=exception)
        asyncio.create_task(self._discard(refresh_id))

    async def _discard(self, refresh_id: str) -> None:
        async with self._admission_lock:
            self._tasks.pop(refresh_id, None)
            self._task_ctx.pop(refresh_id, None)

    async def _recover_stale_refreshes(self) -> None:
        page = 1
        while True:
            result = await self._cpp_backend.list_tasks(
                page=page,
                page_size=100,
                timeout=getattr(self._cpp_backend.settings, "cpp_recovery_timeout", 8.0),
                max_retries=1,
            )
            tasks = result.get("tasks") or result.get("data") or []
            if not tasks:
                break
            for summary in tasks:
                await self._recover_task(summary)
            if len(tasks) < 100:
                break
            page += 1

    async def _recover_task(self, summary: dict[str, Any]) -> None:
        task_id = summary.get("id")
        if not isinstance(task_id, str) or not task_id:
            return
        task = await self._cpp_backend.get_task(
            task_id,
            timeout=getattr(self._cpp_backend.settings, "cpp_recovery_timeout", 8.0),
            max_retries=1,
        )
        if task is None:
            return
        try:
            db_path = investigation_db_path_for_task(task)
        except Exception:
            return
        if not db_path.exists():
            return
        try:
            # D4b: existing-store-only — a task deleted between the registry
            # lookup and this open is skipped, never recreated.
            repo = InvestigationRepository.open_existing(db_path, task_id)
        except EvidenceStoreError:
            return
        try:
            stale = await asyncio.to_thread(repo.list_stale_event_refreshes)
            for refresh in stale:
                await asyncio.to_thread(
                    repo.fail_event_refresh,
                    refresh.refresh_id,
                    error_code="service_restart",
                    error_message="event refresh interrupted by service restart",
                )
        except Exception:
            logger.exception("Event Refresh recovery failed for task %s", task_id)


__all__ = ["EventRefreshExecutor"]
