"""Frozen report generation execution (Phase R2c).

Executes one admitted generation end-to-end under the R2c invariants:

- R2C1/R2C2 the LLM sees ONLY the persisted envelope (verbatim user prompt);
- R2C3 the persisted envelope is re-canonicalized and hash-verified first;
- R2C4 every emitted citation must fit the frozen report evidence boundary
  and the exact frozen analysis/claim identities;
- R2C5 the report version is allocated only inside the successful
  publication transaction (R2b Option B);
- R2C6 failures never leave a Viewer-visible version;
- R2C7 later Report Evidence/analysis changes cannot touch a running
  generation (its input is already frozen bytes).

Independent executor: SecondaryAnalysisExecutor / EventRefreshExecutor are
not extended, only mirrored.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import httpx
from pydantic import ValidationError

from ..evidence.exceptions import EvidenceStoreError
from ..investigation.acquisition import canonical_json
from .generation_prompts import (
    REPORT_GENERATION_ENVELOPE_COMPAT,
    build_report_generation_user_prompt,
    get_report_generation_prompt,
)
from .generation_structured import (
    StructuredReportOutputError,
    parse_structured_report_response,
)
from .generation_writer import GenerationReportWriter, new_generation_report_id
from .models import (
    CitationManifestEntry,
    GenerationReportManifest,
    ReportGenerationEnvelopeV1,
    ReportGenerationInput,
    ScopeType,
    StructuredReportResponse,
)
from .repository import ReportRepository

logger = logging.getLogger(__name__)


def _classify_generation_error(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, httpx.ReadTimeout):
        return "llm_timeout", "LLM request timed out"
    if isinstance(exc, httpx.ConnectError):
        return "llm_connection_error", "LLM service unreachable"
    if isinstance(exc, httpx.HTTPStatusError):
        return "llm_http_error", "LLM request failed"
    return "execution_error", "report generation execution failed"


class ReportCitationInvalidError(ValueError):
    """An emitted citation violates the frozen report provenance boundary."""


def validate_report_citations(
    response: StructuredReportResponse, envelope: ReportGenerationEnvelopeV1
) -> None:
    """Validate every citation against the persisted envelope only.

    Evidence boundary: only ``allowed_report_evidence_ids`` (narrower than
    the task's evidence). Analysis: only the exact frozen
    ``bound_analysis.analysis_id`` (never a newer/review-pending/foreign
    analysis, never auto-attached for original-only evidence). Claim: only
    a claim_id persisted inside that frozen analysis (exact identity, never
    matched by text). No live DB or latest-anything lookup happens here.
    """
    items = {
        item.evidence_key: item
        for item in (*envelope.main_evidence, *envelope.appendix_evidence)
    }
    for citation in response.citations:
        item = items.get(citation.evidence_key)
        if item is None:
            raise ReportCitationInvalidError(
                "citation references evidence outside the report boundary"
            )
        bound = item.bound_analysis
        if citation.analysis_id is None:
            if citation.claim_id is not None:
                raise ReportCitationInvalidError(
                    "citation claim requires the frozen analysis binding"
                )
            continue
        if bound is None or citation.analysis_id != bound.analysis_id:
            raise ReportCitationInvalidError(
                "citation analysis does not match the frozen binding"
            )
        if citation.claim_id is not None and citation.claim_id not in {
            claim.claim_id for claim in bound.claims
        }:
            raise ReportCitationInvalidError(
                "citation claim does not belong to the frozen analysis"
            )


def build_citation_manifest(
    response: StructuredReportResponse, envelope: ReportGenerationEnvelopeV1
) -> tuple[CitationManifestEntry, ...]:
    """Copy exact persisted identity + frozen provenance into the manifest.

    Entries carry only identity and audit metadata (captured_at / analysis
    version / claim type) -- never narrative payload. The Viewer (R2d) reads
    this and never re-derives citation provenance.
    """
    items = {
        item.evidence_key: item
        for item in (*envelope.main_evidence, *envelope.appendix_evidence)
    }
    entries = []
    for citation in response.citations:
        item = items[citation.evidence_key]  # validated before this runs
        bound = item.bound_analysis
        analysis = (
            bound
            if bound is not None and citation.analysis_id == bound.analysis_id
            else None
        )
        claim = None
        if analysis is not None and citation.claim_id is not None:
            claim = next(
                (
                    c
                    for c in analysis.claims
                    if c.claim_id == citation.claim_id
                ),
                None,
            )
        entries.append(
            CitationManifestEntry(
                citation_id=citation.citation_id,
                evidence_key=citation.evidence_key,
                analysis_id=citation.analysis_id,
                claim_id=citation.claim_id,
                evidence_captured_at=item.snapshot.captured_at,
                analysis_version=analysis.version if analysis else None,
                claim_type=claim.claim_type if claim else None,
            )
        )
    entries.sort(key=lambda entry: entry.citation_id)
    return tuple(entries)


def read_generation_strict(
    db_path, generation_id: str
) -> ReportGenerationInput | None:
    """Exact-ID strict read of one generation row (GET path, R2c §23).

    mode=ro + query_only: never creates the store, never migrates, never
    self-heals. A missing store/table is ``None``; corruption fails closed.
    """
    path = Path(db_path)
    if not path.is_file():
        return None
    uri = f"file:{quote(str(path))}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA query_only = ON")
            table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='report_generation_inputs'"
            ).fetchone()
            if table is None:
                return None
            row = conn.execute(
                "SELECT * FROM report_generation_inputs "
                "WHERE generation_id = ?",
                (generation_id,),
            ).fetchone()
            return (
                ReportRepository._to_generation_model(row) if row else None
            )
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        raise EvidenceStoreError(
            "report generation store is unavailable"
        ) from exc


class ReportGenerationExecutor:
    """Execute admitted generations: claim -> verify -> LLM -> validate ->
    publish -> complete. Independent of the other executors."""

    def __init__(
        self,
        repository: ReportRepository,
        writer: GenerationReportWriter,
        llm_service,
    ):
        self._repository = repository
        self._writer = writer
        self._llm_service = llm_service
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._admission_lock = asyncio.Lock()
        self._accepting = True

    async def initialize(self) -> None:
        """Restart recovery: stale admitted/running -> failed(service_restart).

        No auto replay: the LLM may already have run, and re-running it would
        produce unpredictable duplicate output.
        """
        stale = await asyncio.to_thread(self._repository.list_stale_generations)
        for row in stale:
            await asyncio.to_thread(
                self._repository.fail_generation,
                row.generation_id,
                error_code="service_restart",
                error_message="report generation interrupted by service restart",
            )

    async def submit(self, generation_id: str) -> None:
        """Schedule one admitted generation; scheduling failure is durable.

        Any failure to hand the row to a worker (including shutdown races)
        terminalizes the row ``execution_schedule_failed`` -- an orphan
        ``admitted`` row must never remain user-visible.
        """
        scheduled = False
        async with self._admission_lock:
            if self._accepting:
                worker = self._execute(generation_id)
                try:
                    task = asyncio.create_task(worker)
                except Exception:
                    worker.close()  # dispose the un-awaited coroutine
                    task = None
                else:
                    self._tasks[generation_id] = task
                    task.add_done_callback(
                        lambda done, gid=generation_id: self._on_task_done(gid, done)
                    )
                    scheduled = True
        if not scheduled:
            await self._fail(
                generation_id,
                "execution_schedule_failed",
                "report generation could not be scheduled",
            )

    async def shutdown(self) -> None:
        """Cancel tracked workers and durably fail non-terminal rows."""
        async with self._admission_lock:
            self._accepting = False
            tracked = dict(self._tasks)
        for task in tracked.values():
            task.cancel()
        if tracked:
            await asyncio.gather(*tracked.values(), return_exceptions=True)
        for generation_id in tracked:
            try:
                await asyncio.to_thread(
                    self._repository.fail_generation,
                    generation_id,
                    error_code="service_shutdown",
                    error_message="report generation cancelled during service shutdown",
                )
            except Exception:
                logger.exception(
                    "Failed to record generation shutdown: %s", generation_id
                )
        async with self._admission_lock:
            self._tasks.clear()

    async def _execute(self, generation_id: str) -> None:
        claimed = False
        model: str | None = None
        try:
            row = await asyncio.to_thread(
                self._repository.claim_generation, generation_id
            )
            if row is None:
                return  # concurrent loser: no LLM, no failure write
            claimed = True

            # R2C3: re-canonicalize and hash-verify the persisted envelope.
            try:
                envelope = ReportGenerationEnvelopeV1.model_validate_json(
                    row.input_envelope_json
                )
            except ValidationError:
                await self._fail(
                    generation_id,
                    "input_integrity_error",
                    "stored generation input failed integrity validation",
                )
                return
            canonical = canonical_json(envelope)
            actual_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            if (
                canonical != row.input_envelope_json
                or not hmac.compare_digest(actual_hash, row.input_hash)
            ):
                await self._fail(
                    generation_id,
                    "input_integrity_error",
                    "stored generation input failed integrity validation",
                )
                return
            compat = REPORT_GENERATION_ENVELOPE_COMPAT.get(
                envelope.schema_version, frozenset()
            )
            if (
                envelope.schema_version not in REPORT_GENERATION_ENVELOPE_COMPAT
                or row.prompt_version not in compat
                or envelope.prompt_version != row.prompt_version
            ):
                await self._fail(
                    generation_id,
                    "unsupported_input_contract",
                    "generation input contract is unsupported",
                )
                return

            system_prompt, user_template = get_report_generation_prompt(
                row.prompt_version
            )
            user_prompt = build_report_generation_user_prompt(
                user_template, envelope
            )
            if self._llm_service is None:
                await self._fail(
                    generation_id,
                    "llm_unavailable",
                    "LLM service is not initialized",
                )
                return
            result = await self._llm_service.chat_completion(
                system_prompt, user_prompt
            )
            model = result.get("model") or None
            content = result.get("content", "")
            if not content:
                await self._fail(
                    generation_id,
                    "llm_empty_response",
                    "LLM returned empty response",
                    model=model,
                )
                return
            try:
                response = parse_structured_report_response(content)
            except StructuredReportOutputError:
                logger.exception(
                    "Structured report output invalid: %s", generation_id
                )
                await self._fail(
                    generation_id,
                    "structured_output_invalid",
                    "structured report response is invalid",
                    model=model,
                )
                return
            try:
                validate_report_citations(response, envelope)
            except ReportCitationInvalidError:
                logger.exception(
                    "Report citations violate the frozen boundary: %s",
                    generation_id,
                )
                await self._fail(
                    generation_id,
                    "citation_invalid",
                    "report citations violate the frozen evidence boundary",
                    model=model,
                )
                return

            # R2C5: publish first (atomic os.replace), then allocate the
            # version + complete the generation in one transaction -- a
            # version is only ever visible together with its manifest.
            try:
                report_id = new_generation_report_id()
                manifest = GenerationReportManifest(
                    report_id=report_id,
                    scope_type=ScopeType.TASK,
                    scope_id=row.task_id,
                    task_id=row.task_id,
                    generation_id=generation_id,
                    title=response.title,
                    prompt_version=row.prompt_version,
                    input_hash=row.input_hash,
                    model=model or "unknown",
                    generated_at=datetime.now(timezone.utc).isoformat(),
                    sections=response.sections,
                    citations=build_citation_manifest(response, envelope),
                )
                final_dir = await asyncio.to_thread(
                    self._writer.publish,
                    task_id=row.task_id,
                    report_id=report_id,
                    manifest=manifest,
                )
                completed = await asyncio.to_thread(
                    self._repository.complete_generation_publication,
                    generation_id,
                    report_id=report_id,
                    title=response.title,
                    # Relative to the report root, matching the A-chain
                    # convention: the stored path is display metadata only
                    # (reads resolve the layout through the writer), and it
                    # must not disclose absolute server filesystem paths.
                    manifest_path=str(
                        final_dir.relative_to(self._writer.report_root)
                    ),
                    model=model or "unknown",
                )
                if completed.status != "completed":  # pragma: no cover
                    raise RuntimeError(
                        "unexpected report generation completion state"
                    )
            except Exception:
                logger.exception(
                    "Report generation publication failed: %s", generation_id
                )
                await self._fail(
                    generation_id,
                    "publication_error",
                    "report publication failed",
                    model=model,
                )
        except asyncio.CancelledError:
            if claimed:
                self._repository.fail_generation(
                    generation_id,
                    error_code="service_shutdown",
                    error_message="report generation cancelled during service shutdown",
                    model=model,
                )
            raise
        except Exception as exc:
            if claimed:
                logger.exception(
                    "Report generation execution failed: %s", generation_id
                )
                await self._fail(
                    generation_id, *_classify_generation_error(exc), model=model
                )

    async def _fail(
        self,
        generation_id: str,
        error_code: str,
        error_message: str,
        *,
        model: str | None = None,
    ) -> None:
        try:
            await asyncio.to_thread(
                self._repository.fail_generation,
                generation_id,
                error_code=error_code,
                error_message=error_message,
                model=model,
            )
        except Exception:
            logger.exception(
                "Failed to persist report generation failure: %s", generation_id
            )

    def _on_task_done(self, generation_id: str, task: asyncio.Task[None]) -> None:
        try:
            exception = task.exception()
        except asyncio.CancelledError:
            exception = None
        if exception is not None:
            logger.error(
                "Report generation task failed: %s",
                generation_id,
                exc_info=exception,
            )
        asyncio.create_task(self._discard(generation_id))

    async def _discard(self, generation_id: str) -> None:
        async with self._admission_lock:
            self._tasks.pop(generation_id, None)


__all__ = [
    "ReportCitationInvalidError",
    "ReportGenerationExecutor",
    "build_citation_manifest",
    "read_generation_strict",
    "validate_report_citations",
]
