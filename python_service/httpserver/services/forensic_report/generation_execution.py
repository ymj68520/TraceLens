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

from ..evidence.exceptions import EvidenceStoreError
from ..investigation.acquisition import canonical_json
from .generation_prompts import (
    REPORT_GENERATION_ENVELOPE_COMPAT,
    build_report_generation_user_prompt,
    get_report_generation_prompt,
    get_section_user_prompt_template,
    render_evidence_projection,
    render_group_inventory,
)
from .generation_structured import (
    StructuredReportOutputError,
    parse_structured_outline_response,
    parse_structured_report_response,
    parse_structured_section_response,
)
from .generation_writer import GenerationReportWriter, new_generation_report_id
from .models import (
    CitationManifestEntry,
    EnvelopeEvidenceItemV1,
    GenerationReportManifest,
    ReportGenerationEnvelopeV1,
    ReportGenerationEnvelopeV2,
    ReportGenerationInput,
    ScopeType,
    StructuredOutlineResponse,
    StructuredReportCitation,
    StructuredReportResponse,
    StructuredReportSection,
    StructuredSectionResponse,
    parse_generation_envelope,
)
from .repository import ReportRepository

logger = logging.getLogger(__name__)


class _StageFailure(Exception):
    """A recoverable pipeline stage failure with a stable error code."""

    def __init__(self, code: str, message: str, model: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.model = model


# Deterministic evidence grouping for the sectioned (v2) pipeline: ordered
# rules, first match on the lower-cased normalized path wins; deleted files
# group as recovered regardless of path. The fallback group exists so every
# adopted item stays visible in exactly one section (the terse inventory
# chapter) -- coverage is a completeness invariant, not a model choice.
_EVIDENCE_GROUP_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("script_training", "话术与培训材料", ("话术", "培训", "教材", "剧本", "包装")),
    ("recovered", "已删除与恢复文件", ("$orphanfiles",)),
    ("anti_forensics", "反取证与加密工具", ("truecrypt", "wywz", "q3ju", "shred", "粉碎", "擦除", "加密容器")),
    ("network_remote", "网络与远程访问痕迹", ("chrome", "xshell", "netsarang", "browser", "浏览器", "downloads", "remote", "teamviewer")),
    ("registry_system", "系统与注册表痕迹", ("ntuser", "usrclass", "prefetch", "registry", "system32", "windows/", "recent")),
    ("web_service", "Web 服务与站点数据", ("/www", "nginx", "mysql", "jijin", "thinkphp", "/var/log", "wwwroot", "qrcode")),
    ("sysconfig_accounts", "系统配置与账户", ("/etc", "/root", "/home", "passwd", "shadow", "bash_history")),
)
_FALLBACK_GROUP_ID = "software_inventory"
_FALLBACK_GROUP_NAME = "系统组件与软件产物"


def group_report_evidence(
    envelope: ReportGenerationEnvelopeV2,
) -> list[tuple[str, str, list[EnvelopeEvidenceItemV1]]]:
    """Partition main+appendix evidence into ordered deterministic groups.

    Rule order is the chapter hint order; each item lands in exactly one
    group (first match wins, deleted-file check before path rules). Empty
    groups are dropped so the outline only ever sees inhabited groups.
    """
    groups: dict[str, list[EnvelopeEvidenceItemV1]] = {}
    for item in (*envelope.main_evidence, *envelope.appendix_evidence):
        path = item.snapshot.payload.normalized_path.lower()
        if item.snapshot.payload.is_deleted:
            group_id = "recovered"
        else:
            group_id = _FALLBACK_GROUP_ID
            for candidate, _name, needles in _EVIDENCE_GROUP_RULES:
                if any(needle in path for needle in needles):
                    group_id = candidate
                    break
        groups.setdefault(group_id, []).append(item)
    # rebuild in rule order, then fallback last
    ordered: list[tuple[str, str, list[EnvelopeEvidenceItemV1]]] = []
    seen: set[str] = set()
    for gid, name, _needles in _EVIDENCE_GROUP_RULES:
        items = groups.pop(gid, [])
        if items:
            ordered.append((gid, name, items))
            seen.add(gid)
    fallback_items = groups.pop(_FALLBACK_GROUP_ID, [])
    if fallback_items:
        ordered.append((_FALLBACK_GROUP_ID, _FALLBACK_GROUP_NAME, fallback_items))
    return ordered


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

    def has_report_version(self, task_id: str) -> bool:
        """True when any report version already exists for the task.

        Read-only guard for the pipeline-tail auto generation: a task that
        already produced a report (auto or analyst-triggered) is never
        auto-generated again, whatever the ingestion replay history is.
        """
        return bool(
            self._repository.list_versions(ScopeType.TASK, task_id)
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
            # The bytes carry their schema_version; dispatch to the matching
            # strict model so v1 rows keep executing their recorded contract.
            try:
                envelope = parse_generation_envelope(row.input_envelope_json)
            except ValueError:
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

            if self._llm_service is None:
                await self._fail(
                    generation_id,
                    "llm_unavailable",
                    "LLM service is not initialized",
                )
                return
            try:
                if envelope.schema_version >= 2:
                    response, model = await self._generate_sectioned(envelope)
                else:
                    response, model = await self._generate_single_shot(envelope)
            except _StageFailure as exc:
                await self._fail(generation_id, exc.code, exc.message, model=exc.model)
                return
            except Exception:
                logger.exception(
                    "Report generation execution failed: %s", generation_id
                )
                raise
            model = model or None

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

    async def _generate_single_shot(
        self, envelope: ReportGenerationEnvelopeV1
    ) -> tuple[StructuredReportResponse, str | None]:
        """v1 contract: one call, the whole envelope as the user prompt."""
        system_prompt, user_template = get_report_generation_prompt(
            envelope.prompt_version
        )
        user_prompt = build_report_generation_user_prompt(user_template, envelope)
        result = await self._llm_service.chat_completion(system_prompt, user_prompt)
        model = result.get("model") or None
        content = result.get("content", "")
        if not content:
            raise _StageFailure(
                "llm_empty_response", "LLM returned empty response", model=model
            )
        try:
            return parse_structured_report_response(content), model
        except StructuredReportOutputError:
            logger.exception("Structured report output invalid")
            raise _StageFailure(
                "structured_output_invalid",
                "structured report response is invalid",
                model=model,
            ) from None

    async def _generate_sectioned(
        self, envelope: ReportGenerationEnvelopeV2
    ) -> tuple[StructuredReportResponse, str | None]:
        """v2 contract: outline once, then one call per planned section.

        Every stage sees the hash-verified envelope's case description; each
        section prompt carries only its own groups' deterministic evidence
        projection, and per-section citation scopes are subsets of the
        frozen envelope boundary so the global validation still gates the
        assembled report.
        """
        system_prompt, outline_template = get_report_generation_prompt(
            envelope.prompt_version
        )
        section_template = get_section_user_prompt_template(envelope.prompt_version)
        groups = group_report_evidence(envelope)
        if not groups:  # admission already rejects empty evidence sets
            raise _StageFailure(
                "no_report_evidence", "task has no report evidence"
            )
        items_by_group = {gid: items for gid, name, items in groups}
        groups_brief = "\n\n".join(
            render_group_inventory(gid, name, items) for gid, name, items in groups
        )

        # Stage 1: outline.
        outline_prompt = outline_template.format(
            task_id=envelope.task_id,
            case_description=envelope.case_description.strip() or "(未提供)",
            groups_brief=groups_brief,
            fallback_group=_FALLBACK_GROUP_ID,
            fallback_name=_FALLBACK_GROUP_NAME,
        )
        result = await self._llm_service.chat_completion(
            system_prompt, outline_prompt
        )
        model = result.get("model") or None
        outline = await asyncio.to_thread(
            self._parse_outline, result.get("content", ""), groups, model
        )
        sections = outline.sections

        # Stage 2: one call per section.
        all_keys = list(envelope.allowed_report_evidence_ids)
        merged_sections: list[StructuredReportSection] = []
        merged_citations: list[StructuredReportCitation] = []
        counter = 0
        outline_brief = "\n".join(
            f"{i}. {s.heading}：{s.brief}" for i, s in enumerate(sections, start=1)
        )
        for index, section in enumerate(sections, start=1):
            if index == 1:
                scope_keys = all_keys
                projection = groups_brief
            else:
                scope_items = [
                    item
                    for gid in section.group_ids
                    for item in items_by_group.get(gid, [])
                ]
                scope_keys = [item.evidence_key for item in scope_items]
                if scope_keys:
                    projection = render_evidence_projection(scope_items)
                else:
                    scope_keys = all_keys
                    projection = groups_brief
            section_prompt = section_template.format(
                task_id=envelope.task_id,
                case_description=envelope.case_description.strip() or "(未提供)",
                section_no=index,
                section_total=len(sections),
                outline_brief=outline_brief,
                heading=section.heading,
                brief=section.brief,
                allowed_ids="\n".join(scope_keys) or "none",
                projection=projection,
            )
            result = await self._llm_service.chat_completion(
                system_prompt, section_prompt
            )
            model = result.get("model") or model
            response = await asyncio.to_thread(
                self._parse_section,
                result.get("content", ""),
                set(scope_keys),
                index,
                model,
            )
            section_ids: list[str] = []
            for citation in response.citations:
                counter += 1
                new_id = f"c{counter:03d}"
                section_ids.append(new_id)
                merged_citations.append(
                    StructuredReportCitation(
                        citation_id=new_id,
                        evidence_key=citation.evidence_key,
                        analysis_id=None,
                        claim_id=None,
                    )
                )
            merged_sections.append(
                StructuredReportSection(
                    heading=response.heading,
                    content=response.content,
                    citation_ids=tuple(section_ids),
                )
            )
        return (
            StructuredReportResponse(
                title=outline.title,
                sections=tuple(merged_sections),
                citations=tuple(merged_citations),
            ),
            model,
        )

    def _parse_outline(
        self,
        content: str,
        groups: list[tuple[str, str, list[EnvelopeEvidenceItemV1]]],
        model: str | None,
    ) -> StructuredOutlineResponse:
        """Parse + deterministically repair the outline.

        Repairs only ever tighten toward the completeness contract (every
        group covered exactly by its assigned sections, background chapter
        evidence-free); they are logged and deterministic, never creative.
        """
        try:
            outline = parse_structured_outline_response(content)
        except StructuredReportOutputError:
            logger.exception("Outline output invalid")
            raise _StageFailure(
                "outline_invalid",
                "outline response is invalid",
                model=model,
            ) from None
        known = {gid for gid, _name, _items in groups}
        sections = list(outline.sections)

        # Background chapter (first) never carries evidence groups.
        if sections and sections[0].group_ids:
            logger.warning(
                "Outline gave the background chapter groups %s; stripped",
                sections[0].group_ids,
            )
            sections[0] = sections[0].model_copy(update={"group_ids": ()})
        # Drop references to unknown groups.
        repaired = []
        for section in sections:
            kept = tuple(gid for gid in section.group_ids if gid in known)
            if kept != section.group_ids:
                logger.warning(
                    "Outline section %r referenced unknown groups; dropped",
                    section.heading,
                )
                section = section.model_copy(update={"group_ids": kept})
            repaired.append(section)
        sections = repaired
        # The fallback inventory group must be covered exactly once.
        owners = [
            i
            for i, section in enumerate(sections)
            if _FALLBACK_GROUP_ID in section.group_ids
        ]
        for extra in owners[1:]:
            logger.warning(
                "Outline covered the fallback group %d times; kept first",
                len(owners),
            )
            kept = tuple(
                gid
                for gid in sections[extra].group_ids
                if gid != _FALLBACK_GROUP_ID
            )
            sections[extra] = sections[extra].model_copy(update={"group_ids": kept})
        # Every group must be covered somewhere; unassigned ones append to
        # the last section so adopted evidence never silently vanishes.
        assigned = {gid for section in sections for gid in section.group_ids}
        missing = sorted(known - assigned)
        if missing:
            logger.warning(
                "Outline left groups unassigned; appended to last section: %s",
                missing,
            )
            last = sections[-1]
            sections[-1] = last.model_copy(
                update={"group_ids": tuple(last.group_ids) + tuple(missing)}
            )
        return outline.model_copy(update={"sections": tuple(sections)})

    def _parse_section(
        self,
        content: str,
        scope: set[str],
        index: int,
        model: str | None,
    ) -> StructuredSectionResponse:
        try:
            response = parse_structured_section_response(content)
        except StructuredReportOutputError:
            logger.exception("Section %d output invalid", index)
            raise _StageFailure(
                "section_invalid",
                f"section {index} response is invalid",
                model=model,
            ) from None
        seen: set[str] = set()
        for citation in response.citations:
            if citation.analysis_id is not None or citation.claim_id is not None:
                raise _StageFailure(
                    "section_invalid",
                    f"section {index} cited a non-null analysis/claim identity",
                    model=model,
                )
            if citation.citation_id in seen:
                raise _StageFailure(
                    "section_invalid",
                    f"section {index} reused citation_id {citation.citation_id}",
                    model=model,
                )
            seen.add(citation.citation_id)
            if citation.evidence_key not in scope:
                raise _StageFailure(
                    "citation_invalid",
                    f"section {index} cited evidence outside its section scope",
                    model=model,
                )
        return response

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
