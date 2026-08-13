"""SecondaryAnalysisExecutor: LLM execution layer for Secondary Analysis (Phase C4b-2).

Execution invariants (frozen):
  E1  queued record persisted to SQLite BEFORE background task starts
  E2  worker only executes an existing analysis_id
  E3  worker input comes ONLY from input_envelope_json (never re-resolves/re-reads source)
  E4  queued -> running persisted BEFORE the LLM call
  E5  LLM success only reaches review_pending (NEVER auto-accepted)
  E6  LLM failure writes failed + error_code/error_message; full traceback only in logger
  E7  worker does not touch other versions
  E8  SQLite is source of truth; in-memory task set is for shutdown tracking only
  E9  crash/kill stale queued/running -> initialize recovery -> failed (service_restart)
  E10 Evidence Analysis never writes to events.db / files.db
  E11 worker uses the SAME db_path that created the queued row (passed from submit)
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import httpx

from ..evidence.exceptions import EvidenceNotFoundError, EvidenceStoreError
from .models import SecondaryAnalysis, SecondaryAnalysisStatus
from .paths import investigation_db_path_for_task
from .prompts import CURRENT_PROMPT_VERSION, build_user_prompt, get_prompt
from .repository import InvestigationRepository

if TYPE_CHECKING:
    from ..cpp_backend import CppBackendService
    from ..llm.llm_service import LLMService
    from .service import InvestigationCaptureService

logger = logging.getLogger(__name__)


def _classify_llm_error(exc: Exception) -> tuple[str, str]:
    """Map an LLM exception to a stable (error_code, generic_message).

    The message is stored in the DB and returned via the public API, so it must
    never contain internal URLs, paths, or stack details. The full traceback is
    preserved separately via ``logger.exception``.
    """
    if isinstance(exc, httpx.ReadTimeout):
        return ("llm_timeout", "LLM request timed out")
    if isinstance(exc, httpx.ConnectError):
        return ("llm_connection_error", "LLM service unreachable")
    if isinstance(exc, httpx.HTTPStatusError):
        return ("llm_http_error", "LLM request failed")
    return ("execution_error", "secondary analysis execution failed")


class SecondaryAnalysisExecutor:
    """Executes versioned Secondary Analysis via LLM, with restart recovery.

    Dependencies:
        cpp_backend    -- for trusted task lookup (db_path derivation)
        llm_service    -- for LLM calls (may be None if init failed)
        capture_service -- for Evidence snapshot capture (C3 trust boundary)
    """

    def __init__(
        self,
        cpp_backend: "CppBackendService",
        llm_service: Optional["LLMService"],
        capture_service: "InvestigationCaptureService",
    ):
        self._cpp_backend = cpp_backend
        self._llm_service = llm_service
        self._capture_service = capture_service
        self._tasks: dict[str, asyncio.Task[None]] = {}  # E8: shutdown tracking
        self._task_ctx: dict[str, tuple[str, Path]] = {}  # analysis_id -> (task_id, db_path)
        self._admission_lock = asyncio.Lock()
        self._accepting = True

    # =====================================================================
    # lifecycle
    # =====================================================================

    async def initialize(self) -> None:
        """Called at ServiceManager startup. Runs restart recovery (E9)."""
        await self._recover_stale_analyses()

    async def shutdown(self) -> None:
        """Graceful shutdown: block new submits, cancel in-flight tasks.

        After cancellation, each tracked analysis is explicitly transitioned to
        ``failed`` with ``error_code="service_shutdown"``. This is the reliable
        path — the CancelledError handler in ``_execute`` is a bonus that may
        fire for mid-execution tasks, but cannot be relied upon for tasks that
        were cancelled before they started. If the process is killed before
        this completes, E9 restart recovery is the safety net.
        """
        async with self._admission_lock:
            self._accepting = False
            tracked = dict(self._tasks)
            contexts = dict(self._task_ctx)
        for task in tracked.values():
            task.cancel()
        if tracked:
            await asyncio.gather(*tracked.values(), return_exceptions=True)
        # Explicit sweep: transition any remaining non-terminal analyses.
        for analysis_id, (task_id, db_path) in contexts.items():
            try:
                repo = InvestigationRepository(db_path, task_id)
                repo.transition(
                    analysis_id,
                    SecondaryAnalysisStatus.failed,
                    error_code="service_shutdown",
                    error_message="analysis cancelled during service shutdown",
                )
            except (ValueError, EvidenceStoreError):
                pass  # already terminal (completed or already failed)
            except Exception:
                logger.exception(
                    "Failed to record shutdown for %s", analysis_id
                )
        async with self._admission_lock:
            self._tasks.clear()
            self._task_ctx.clear()

    # =====================================================================
    # public API
    # =====================================================================

    async def submit(self, task_id: str, evidence_key: str) -> SecondaryAnalysis:
        """Capture snapshot, create a queued analysis, start background execution.

        E1: the queued record is persisted BEFORE the background task starts.
        The admission lock ensures submit and shutdown are mutually exclusive
        (no new task appears after shutdown completes).
        """
        # Phase 1: capture + derive db_path (OUTSIDE the admission lock so
        # concurrent submits don't serialize on capture latency).
        snapshot = await self._capture_service.capture(task_id, evidence_key)
        task = await self._cpp_backend.get_task(task_id)
        if task is None:
            raise EvidenceNotFoundError(f"task not found: {task_id!r}")
        db_path = investigation_db_path_for_task(task)

        # Phase 2: admission lock — check accepting + E1 persist + register task.
        async with self._admission_lock:
            if not self._accepting:
                raise RuntimeError("executor is shutting down")
            repo = InvestigationRepository(db_path, task_id)
            analysis = await asyncio.to_thread(
                repo.create_analysis,
                snapshot,
                analyst_note=None,
                case_context=None,
                related_evidence=(),
                prompt_version=CURRENT_PROMPT_VERSION,
            )
            # E11: pass the SAME db_path — worker never re-derives it.
            bg_task = asyncio.create_task(
                self._execute(analysis.analysis_id, task_id, db_path)
            )
            self._tasks[analysis.analysis_id] = bg_task
            self._task_ctx[analysis.analysis_id] = (task_id, db_path)
            bg_task.add_done_callback(
                lambda completed, aid=analysis.analysis_id: self._on_task_done(aid, completed)
            )
        return analysis

    async def get_analysis(
        self, task_id: str, analysis_id: str
    ) -> Optional[SecondaryAnalysis]:
        """Query a single analysis from SQLite (E8: DB is source of truth)."""
        db_path = await self._resolve_db_path(task_id)
        if db_path is None:
            return None
        repo = InvestigationRepository(db_path, task_id)
        return await asyncio.to_thread(repo.get_analysis, analysis_id)

    async def list_analyses(
        self, task_id: str, canonical_evidence_key: str
    ) -> list[SecondaryAnalysis]:
        """Query analyses for an evidence from SQLite."""
        db_path = await self._resolve_db_path(task_id)
        if db_path is None:
            return []
        repo = InvestigationRepository(db_path, task_id)
        return await asyncio.to_thread(repo.list_analyses, canonical_evidence_key)

    # =====================================================================
    # background execution (E2-E7, E11)
    # =====================================================================

    async def _execute(
        self, analysis_id: str, task_id: str, db_path: Path
    ) -> None:
        """The background LLM execution path.

        Uses ``db_path`` directly (E11) — does NOT call get_task again.
        """
        # Construct repo synchronously (fast; always available in handlers).
        repo = InvestigationRepository(db_path, task_id)
        claimed = False
        try:
            # E2: must exist
            analysis = await asyncio.to_thread(repo.get_analysis, analysis_id)
            if analysis is None:
                logger.error("analysis not found: %s", analysis_id)
                return

            # Single-worker claim: queued -> running is the claim.
            # If another worker already claimed, ValueError -> return WITHOUT
            # calling _fail (must not touch the other worker's analysis).
            try:
                analysis = await asyncio.to_thread(
                    repo.transition, analysis_id, SecondaryAnalysisStatus.running
                )
                claimed = True
            except ValueError:
                logger.warning(
                    "analysis %s already claimed by another worker", analysis_id
                )
                return

            # === Input integrity verification (before LLM) ===
            envelope = json.loads(analysis.input_envelope_json)

            # Verify input_hash matches envelope content (tamper detection)
            actual_hash = hashlib.sha256(
                analysis.input_envelope_json.encode("utf-8")
            ).hexdigest()
            if not hmac.compare_digest(actual_hash, analysis.input_hash):
                await self._fail(
                    repo, analysis_id, "input_hash_mismatch",
                    "stored input_hash does not match envelope content",
                )
                return

            # Verify prompt_version consistency (envelope vs row)
            env_prompt_version = envelope.get("prompt_version")
            if env_prompt_version != analysis.prompt_version:
                await self._fail(
                    repo, analysis_id, "input_integrity_error",
                    "envelope prompt_version does not match row",
                )
                return
            if env_prompt_version is None:
                await self._fail(
                    repo, analysis_id, "missing_prompt_version",
                    "analysis envelope has no prompt_version",
                )
                return
            try:
                system_prompt, user_template = get_prompt(env_prompt_version)
            except ValueError:
                await self._fail(
                    repo, analysis_id, "unknown_prompt_version",
                    "unsupported prompt_version in envelope",
                )
                return

            # LLM availability
            if self._llm_service is None:
                await self._fail(
                    repo, analysis_id, "llm_unavailable",
                    "LLM service is not initialized",
                )
                return

            # E3: build prompt ONLY from envelope (never re-reads source DB)
            user_prompt = build_user_prompt(user_template, envelope)

            # LLM call with classified error handling
            try:
                result = await self._llm_service.chat_completion(
                    system_prompt, user_prompt
                )
            except Exception as exc:
                code, msg = _classify_llm_error(exc)
                logger.exception(
                    "LLM call failed for analysis %s", analysis_id
                )
                await self._fail(repo, analysis_id, code, msg)
                return

            content = result.get("content", "")
            if not content:
                await self._fail(
                    repo, analysis_id, "llm_empty_response",
                    "LLM returned empty response",
                )
                return

            description = content
            summary = description[:200].split("\n")[0] if description else ""

            # E5: success -> review_pending (NEVER accepted)
            await asyncio.to_thread(
                repo.transition,
                analysis_id,
                SecondaryAnalysisStatus.review_pending,
                description=description,
                summary=summary,
                model=result.get("model", ""),
            )

        except asyncio.CancelledError:
            # Graceful shutdown: always attempt failed transition.
            # NOTE: must use a SYNCHRONOUS transition here, not _fail (which
            # uses asyncio.to_thread). After CancelledError is caught, asyncio
            # is in a "cancelling" state — any subsequent await re-raises
            # CancelledError, which would prevent the cleanup transition from
            # completing. sqlite transition is sub-millisecond, so blocking is
            # acceptable in this path.
            # _fail semantics: idempotent — swallows illegal transitions so a
            # completed analysis (review_pending/accepted/...) stays as-is.
            try:
                repo.transition(
                    analysis_id,
                    SecondaryAnalysisStatus.failed,
                    error_code="service_shutdown",
                    error_message="analysis cancelled during service shutdown",
                )
            except (ValueError, EvidenceStoreError):
                pass  # already terminal or concurrent transition
            except Exception:
                logger.exception(
                    "Failed to record shutdown failure for %s", analysis_id
                )
            raise
        except Exception:
            # E6: only fail if we claimed (don't kill another worker's analysis)
            if claimed:
                logger.exception(
                    "Secondary analysis failed: %s", analysis_id
                )
                await self._fail(
                    repo, analysis_id, "execution_error",
                    "secondary analysis execution failed",
                )
            else:
                logger.exception(
                    "Secondary analysis pre-claim error: %s", analysis_id
                )

    # =====================================================================
    # failure recording (never raises)
    # =====================================================================

    async def _fail(
        self,
        repo: InvestigationRepository,
        analysis_id: str,
        error_code: str,
        error_message: str,
    ) -> None:
        """Write failed state. Never raises — tolerates concurrent terminal."""
        try:
            await asyncio.to_thread(
                repo.transition,
                analysis_id,
                SecondaryAnalysisStatus.failed,
                error_code=error_code,
                error_message=error_message[:500],
            )
        except (ValueError, EvidenceStoreError):
            logger.warning(
                "Could not fail analysis %s (may already be terminal)",
                analysis_id,
            )
        except Exception:
            logger.exception(
                "Failed to record failure for analysis %s", analysis_id
            )

    # =====================================================================
    # done-callback / discard
    # =====================================================================

    def _on_task_done(self, analysis_id: str, task: asyncio.Task[None]) -> None:
        """Done-callback: log unexpected exceptions (traceback preserved), then discard."""
        try:
            exception = task.exception()
        except asyncio.CancelledError:
            exception = None
        if exception is not None:
            logger.error(
                "Secondary analysis task failed unexpectedly: %s",
                analysis_id,
                exc_info=(type(exception), exception, exception.__traceback__),
            )
        asyncio.create_task(self._discard_task(analysis_id))

    async def _discard_task(self, analysis_id: str) -> None:
        async with self._admission_lock:
            self._tasks.pop(analysis_id, None)
            self._task_ctx.pop(analysis_id, None)

    # =====================================================================
    # restart recovery (E9)
    # =====================================================================

    async def _recover_stale_analyses(self) -> None:
        """Sweep all tasks' investigation.db for stale queued/running rows."""
        page = 1
        while True:
            result = await self._cpp_backend.list_tasks(page=page, page_size=100)
            tasks = result.get("tasks") or result.get("data") or []
            if not isinstance(tasks, list) or not tasks:
                break
            for task_summary in tasks:
                await self._recover_task(task_summary)
            if len(tasks) < 100:
                break
            page += 1
        logger.info("Secondary analysis restart recovery sweep complete")

    async def _recover_task(self, task_summary: dict[str, Any]) -> None:
        task_id = task_summary.get("id")
        if not task_id or not isinstance(task_id, str):
            return
        # Get the full task dict (with trusted DB paths)
        full_task = await self._cpp_backend.get_task(task_id)
        if full_task is None:
            return
        try:
            db_path = investigation_db_path_for_task(full_task)
        except EvidenceStoreError:
            return  # no trusted path for this task
        if not db_path.exists():
            return  # no investigation.db yet
        try:
            repo = InvestigationRepository(db_path, task_id)
            stale = await asyncio.to_thread(repo.list_stale_analyses)
            for analysis in stale:
                try:
                    await asyncio.to_thread(
                        repo.transition,
                        analysis.analysis_id,
                        SecondaryAnalysisStatus.failed,
                        error_code="service_restart",
                        error_message="analysis interrupted by service restart",
                    )
                    logger.info(
                        "Recovered stale analysis %s (was %s)",
                        analysis.analysis_id,
                        analysis.status.value,
                    )
                except (ValueError, EvidenceStoreError):
                    pass  # concurrent terminalization wins
        except Exception:
            logger.exception("Recovery sweep failed for task %s", task_id)

    # =====================================================================
    # helpers
    # =====================================================================

    async def _resolve_db_path(self, task_id: str) -> Optional[Path]:
        """Derive investigation.db path from a trusted task lookup."""
        task = await self._cpp_backend.get_task(task_id)
        if task is None:
            return None
        try:
            return investigation_db_path_for_task(task)
        except EvidenceStoreError:
            return None
