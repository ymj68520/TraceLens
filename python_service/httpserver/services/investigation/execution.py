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
from ..evidence.keys import parse_evidence_key
from .models import SecondaryAnalysis, SecondaryAnalysisStatus, parse_analysis_input_envelope
from .paths import investigation_db_path_for_task
from .prompts import (
    CURRENT_PROMPT_VERSION,
    ENVELOPE_PROMPT_COMPAT,
    PROMPT_OUTPUT_CONTRACT,
    build_user_prompt,
    get_prompt,
)
from .graph_reader import InvestigationGraphReader
from .live_store import open_existing_store, open_live_task_store
from .repository import InvestigationRepository
from .structured import StructuredOutputError, parse_structured_analysis_response

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
        # D4b: each write goes through the live-task boundary, so a task
        # deleted before/during shutdown is never resurrected on disk.
        for analysis_id, (task_id, db_path) in contexts.items():
            repo = await open_live_task_store(self._cpp_backend, task_id, db_path)
            if repo is None:
                continue
            try:
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

    async def submit(
        self,
        task_id: str,
        evidence_key: str,
        *,
        analyst_note: Optional[str] = None,
        case_context: Optional[str] = None,
        related_evidence: tuple[str, ...] = (),
    ) -> SecondaryAnalysis:
        """Capture snapshot, create a queued analysis, start background execution.

        E1: the queued record is persisted BEFORE the background task starts.
        The admission lock ensures submit and shutdown are mutually exclusive
        (no new task appears after shutdown completes).

        C4c: analyst_note / case_context / related_evidence are frozen into the
        envelope at create time. Related evidence keys are canonicalized,
        deduplicated, self-references removed, and deterministically sorted
        (same logical input → same input_hash). Each is resolved + captured
        in the SAME task before create_analysis.
        """
        # Phase 1: capture primary + related evidence (OUTSIDE the admission lock).
        snapshot = await self._capture_service.capture(task_id, evidence_key)

        # Canonicalize related evidence: parse → dedupe → discard primary → sort.
        primary_key = snapshot.evidence_key
        canonical_related: set[str] = set()
        for raw_key in related_evidence:
            parsed = parse_evidence_key(raw_key)
            canonical_related.add(parsed.canonical_key)
        canonical_related.discard(primary_key)
        ordered_related = tuple(sorted(canonical_related))

        # CCTX3/CCTX4: resolve + capture each related evidence in the SAME task.
        for rel_key in ordered_related:
            await self._capture_service.capture(task_id, rel_key)

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
                analyst_note=analyst_note,
                case_context=case_context,
                related_evidence=ordered_related,
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
        """Query a single analysis from SQLite (E8: DB is source of truth).

        C10 §14/E13: GET reads go through the strict mode=ro reader -- the
        write-path repository constructor would CREATE the store here when
        the task has no investigation.db yet.
        """
        db_path = await self._resolve_db_path(task_id)
        if db_path is None or not db_path.exists():
            return None
        reader = InvestigationGraphReader(db_path, task_id)
        return await asyncio.to_thread(reader.get_analysis, analysis_id)

    async def list_analyses(
        self, task_id: str, canonical_evidence_key: str
    ) -> list[SecondaryAnalysis]:
        """Query analyses for an evidence from SQLite (strict reader)."""
        db_path = await self._resolve_db_path(task_id)
        if db_path is None or not db_path.exists():
            return []
        reader = InvestigationGraphReader(db_path, task_id)
        return await asyncio.to_thread(reader.list_analyses, canonical_evidence_key)

    # =====================================================================
    # background execution (E2-E7, E11)
    # =====================================================================

    async def _execute(
        self, analysis_id: str, task_id: str, db_path: Path
    ) -> None:
        """The background LLM execution path.

        Uses ``db_path`` directly (E11) — execution input never re-resolves the
        task or source DB. D4b adds a live-task write boundary: terminal writes
        revalidate liveness/identity and open the store existing-only, so a
        task deleted mid-flight is never resurrected by a completion or
        failure write.
        """
        # D4b: worker terminal paths are existing-store-only from the first
        # access. A deleted store must never be recreated before claim/read.
        repo = InvestigationRepository.open_existing(db_path, task_id)
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
                # Another worker already claimed this analysis. Do not execute
                # or fail it: the winner owns the running row.
                logger.warning(
                    "analysis %s already claimed by another worker", analysis_id
                )
                return

            # === Input integrity verification (before LLM) ===
            envelope = parse_analysis_input_envelope(analysis.input_envelope_json)

            # Verify input_hash matches envelope content (tamper detection)
            actual_hash = hashlib.sha256(
                analysis.input_envelope_json.encode("utf-8")
            ).hexdigest()
            if not hmac.compare_digest(actual_hash, analysis.input_hash):
                await self._fail(
                    task_id, db_path, analysis_id, "input_hash_mismatch",
                    "stored input_hash does not match envelope content",
                )
                return

            # Verify prompt_version consistency (envelope vs row)
            env_prompt_version = envelope.prompt_version
            if env_prompt_version != analysis.prompt_version:
                await self._fail(
                    task_id, db_path, analysis_id, "input_integrity_error",
                    "envelope prompt_version does not match row",
                )
                return
            if env_prompt_version is None:
                await self._fail(
                    task_id, db_path, analysis_id, "missing_prompt_version",
                    "analysis envelope has no prompt_version",
                )
                return
            try:
                system_prompt, user_template = get_prompt(env_prompt_version)
            except ValueError:
                await self._fail(
                    task_id, db_path, analysis_id, "unknown_prompt_version",
                    "unsupported prompt_version in envelope",
                )
                return
            # C4c: envelope schema ↔ prompt version 1:1 compatibility
            allowed_prompts = ENVELOPE_PROMPT_COMPAT.get(envelope.schema_version, frozenset())
            if env_prompt_version not in allowed_prompts:
                await self._fail(
                    task_id, db_path, analysis_id, "input_integrity_error",
                    "envelope schema/prompt version mismatch",
                )
                return
            output_contract = PROMPT_OUTPUT_CONTRACT.get(env_prompt_version)
            if output_contract is None:
                await self._fail(
                    task_id, db_path, analysis_id, "unknown_prompt_version",
                    "unsupported prompt_version in envelope",
                )
                return

            # LLM availability
            if self._llm_service is None:
                await self._fail(
                    task_id, db_path, analysis_id, "llm_unavailable",
                    "LLM service is not initialized",
                )
                return

            # E3: build prompt ONLY from typed envelope (never re-reads source DB)
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
                await self._fail(task_id, db_path, analysis_id, code, msg)
                return

            content = result.get("content", "")
            if not content:
                await self._fail(
                    task_id, db_path, analysis_id, "llm_empty_response",
                    "LLM returned empty response",
                )
                return

            # D4b live-task write boundary: completion writes only reach a
            # confirmed-live task through the existing-only store. A task
            # deleted during the LLM call discards the result without writing.
            live_repo = await open_live_task_store(
                self._cpp_backend, task_id, db_path
            )
            if live_repo is None:
                return
            if output_contract == "legacy_text":
                description = content
                summary = description[:200].split("\n")[0]
                # Historical v1/v2 output contract: no Claims/Grounding.
                await asyncio.to_thread(
                    live_repo.transition,
                    analysis_id,
                    SecondaryAnalysisStatus.review_pending,
                    description=description,
                    summary=summary,
                    model=result.get("model", ""),
                )
            elif output_contract == "structured_claims_v1":
                try:
                    response = parse_structured_analysis_response(content)
                except StructuredOutputError:
                    logger.exception("Structured LLM response invalid for analysis %s", analysis_id)
                    await self._fail(
                        task_id, db_path, analysis_id, "structured_output_invalid",
                        "structured LLM response is invalid",
                    )
                    return
                await asyncio.to_thread(
                    live_repo.complete_analysis_for_review,
                    analysis_id,
                    description=response.description,
                    summary=response.summary,
                    model=result.get("model", ""),
                    candidates=response.claims,
                )
            else:
                raise RuntimeError("unknown output contract")

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
            # D4b: existing-only open; a deleted task's store cannot be
            # recreated here (full liveness check is impossible post-cancel).
            live_repo = open_existing_store(db_path, task_id)
            if live_repo is None:
                raise
            try:
                live_repo.transition(
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
                    task_id, db_path, analysis_id, "execution_error",
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
        task_id: str,
        db_path: Path,
        analysis_id: str,
        error_code: str,
        error_message: str,
    ) -> None:
        """Write failed state through the live-task boundary.

        Never raises — tolerates concurrent terminal writes and skips the
        write entirely when task liveness or store identity cannot be
        confirmed (D4b fail-closed).
        """
        repo = await open_live_task_store(self._cpp_backend, task_id, db_path)
        if repo is None:
            return
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
            # D4b: existing-store-only — a task deleted between the registry
            # lookup and this open is skipped, never recreated.
            repo = InvestigationRepository.open_existing(db_path, task_id)
        except EvidenceStoreError:
            return
        try:
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
