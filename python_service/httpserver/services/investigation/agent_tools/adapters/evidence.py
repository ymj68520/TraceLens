"""Evidence discovery / hydration / related-evidence tools (P3 §20).

search_evidence      discovery facade -> EvidenceDigest page (never raw rows)
get_evidence         hydration via the read-only resolver facade
find_related_evidence cluster member files (facade-backed); file->cluster
                     association has no facade yet and is reported as a
                     limitation instead of being faked.
"""

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from ....evidence.exceptions import InvalidEvidenceKeyError
from ....evidence.keys import parse_evidence_key
from ..errors import ToolErrorCode, ToolExecutionError
from ..registry import ToolExecutionOutcome
from .base import ToolCatalogConfig, bounded_page_size
from .services import ForensicToolServices


# ---------------------------------------------------------------------------
# search_evidence
# ---------------------------------------------------------------------------


class SearchEvidenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Optional[str] = Field(default=None)  # "file" | "cluster"
    query: Optional[str] = None  # substring against evidence_key
    page_size: Optional[int] = None
    page_token: Optional[int] = None  # offset-based deterministic paging


class EvidenceDigest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_key: str
    kind: str
    captured_at: int | None = None
    analysis_review_state: str | None = None


class SearchEvidenceOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: tuple[EvidenceDigest, ...] = ()
    result_count: int = 0
    total_count: int = 0
    truncated: bool = False
    continuation: str | None = None
    warnings: tuple[str, ...] = ()


def build_search_evidence_tool(
    services: ForensicToolServices, config: ToolCatalogConfig
):
    async def adapter(invocation) -> ToolExecutionOutcome:
        args: SearchEvidenceInput = invocation.args
        task_id = invocation.context.task_id
        if args.kind not in (None, "file", "cluster"):
            raise ToolExecutionError(
                ToolErrorCode.TOOL_INPUT_INVALID,
                "kind must be 'file' or 'cluster' when provided",
            )
        summaries = await services.investigation_read_service.list_evidence(task_id)
        digests: list[EvidenceDigest] = []
        for summary in summaries:
            if args.kind and summary.evidence_type != args.kind:
                continue
            if args.query and args.query.lower() not in summary.evidence_key.lower():
                continue
            review_state = None
            if summary.selected_analysis is not None:
                review_state = summary.selected_analysis.review_state
            digests.append(
                EvidenceDigest(
                    evidence_key=summary.evidence_key,
                    kind=summary.evidence_type,
                    captured_at=summary.captured_at,
                    analysis_review_state=review_state,
                )
            )
        digests.sort(key=lambda item: item.evidence_key)
        total = len(digests)
        offset = int(args.page_token or 0)
        page_size = bounded_page_size(args.page_size, config)
        page = digests[offset : offset + page_size]
        continuation = (
            str(offset + page_size) if offset + page_size < total else None
        )
        return ToolExecutionOutcome(
            summary=f"{len(page)} evidence items matched (of {total})",
            result=SearchEvidenceOutput(
                items=tuple(page),
                result_count=len(page),
                total_count=total,
                truncated=continuation is not None,
                continuation=continuation,
            ),
            evidence_refs=tuple(item.evidence_key for item in page),
            limitations=("digests only; hydrate individual evidence with get_evidence",),
        )

    from ..definitions import (
        EvidenceBehavior,
        ForensicToolDefinition,
        ToolAccess,
        ToolCategory,
        ToolCostClass,
        ToolPaginationKind,
        ToolScopeKind,
    )

    definition = ForensicToolDefinition(
        tool_id="search_evidence",
        version="1",
        title="Search captured evidence",
        description=(
            "Lists captured Evidence for this task as digests (evidence_key, "
            "kind, capture time, analysis review state). Returns digests only; "
            "use get_evidence to hydrate one item. Deterministic order, "
            "bounded page size, offset continuation."
        ),
        input_model=SearchEvidenceInput,
        output_model=SearchEvidenceOutput,
        category=ToolCategory.EVIDENCE,
        access=ToolAccess.READ,
        scope_kind=ToolScopeKind.EVIDENCE,
        evidence_behavior=EvidenceBehavior.EVIDENCE_PRODUCING,
        cost_class=ToolCostClass.CHEAP,
        pagination_kind=ToolPaginationKind.PAGE_TOKEN,
    )
    return definition, adapter


# ---------------------------------------------------------------------------
# get_evidence
# ---------------------------------------------------------------------------


class GetEvidenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_key: str
    hydration_level: str = "digest"  # "digest" | "preview"


class GetEvidenceOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_key: str
    kind: str
    title: str | None = None
    timestamp: int | None = None
    start_time: int | None = None
    end_time: int | None = None
    metadata: dict[str, Any] = {}
    content_preview: str | None = None
    md5: str | None = None
    size: int | None = None
    extension: str | None = None
    is_deleted: bool = False
    related_evidence_keys: tuple[str, ...] = ()
    initial_summary: str | None = None
    initial_description: str | None = None
    warnings: tuple[str, ...] = ()


def build_get_evidence_tool(
    services: ForensicToolServices, config: ToolCatalogConfig
):
    async def adapter(invocation) -> ToolExecutionOutcome:
        args: GetEvidenceInput = invocation.args
        task_id = invocation.context.task_id
        try:
            parse_evidence_key(args.evidence_key)
        except InvalidEvidenceKeyError:
            raise ToolExecutionError(
                ToolErrorCode.EVIDENCE_REF_INVALID,
                "malformed evidence key",
            ) from None
        if args.hydration_level not in ("digest", "preview"):
            raise ToolExecutionError(
                ToolErrorCode.TOOL_INPUT_INVALID,
                "hydration_level must be 'digest' or 'preview'",
            )
        resolved = await services.investigation_service.resolve_evidence(
            task_id, args.evidence_key
        )
        if resolved is None:
            # opaque by design: never reveal whether the key exists elsewhere
            raise ToolExecutionError(
                ToolErrorCode.EVIDENCE_REF_INVALID,
                "evidence key did not resolve in this task scope",
            )
        content = None
        if args.hydration_level == "preview":
            raw = resolved.get("content")
            if isinstance(raw, str):
                content = raw[: config.max_preview_chars]
        output = GetEvidenceOutput(
            evidence_key=resolved.get("evidence_key") or args.evidence_key,
            kind=str(resolved.get("evidence_type") or "file"),
            title=resolved.get("title"),
            timestamp=resolved.get("timestamp"),
            start_time=resolved.get("start_time"),
            end_time=resolved.get("end_time"),
            metadata=dict(resolved.get("metadata") or {}),
            content_preview=content,
            md5=resolved.get("md5"),
            size=resolved.get("size"),
            extension=resolved.get("extension"),
            is_deleted=bool(resolved.get("is_deleted")),
            related_evidence_keys=tuple(
                resolved.get("related_evidence_keys") or ()
            )[: config.max_related_items],
            initial_summary=resolved.get("initial_summary"),
            initial_description=resolved.get("initial_description"),
        )
        return ToolExecutionOutcome(
            summary=f"resolved {output.kind} evidence {output.evidence_key}",
            result=output,
            evidence_refs=(output.evidence_key,),
        )

    from ..definitions import (
        EvidenceBehavior,
        ForensicToolDefinition,
        ToolAccess,
        ToolCategory,
        ToolCostClass,
        ToolPaginationKind,
        ToolScopeKind,
    )

    definition = ForensicToolDefinition(
        tool_id="get_evidence",
        version="1",
        title="Hydrate one evidence item",
        description=(
            "Resolves a canonical evidence_key (file:... or cluster:v1:...) "
            "within this task and returns its digest or bounded content "
            "preview. The key must come from search_evidence, search_timeline "
            "or find_related_evidence."
        ),
        input_model=GetEvidenceInput,
        output_model=GetEvidenceOutput,
        category=ToolCategory.EVIDENCE,
        access=ToolAccess.READ,
        scope_kind=ToolScopeKind.EVIDENCE,
        evidence_behavior=EvidenceBehavior.EVIDENCE_RESOLVING,
        cost_class=ToolCostClass.STANDARD,
        pagination_kind=ToolPaginationKind.NONE,
    )
    return definition, adapter


# ---------------------------------------------------------------------------
# find_related_evidence
# ---------------------------------------------------------------------------


class FindRelatedEvidenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_key: str


class FindRelatedEvidenceOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_key: str
    related_evidence_keys: tuple[str, ...] = ()
    result_count: int = 0
    limitations: tuple[str, ...] = ()


def build_find_related_evidence_tool(
    services: ForensicToolServices, config: ToolCatalogConfig
):
    async def adapter(invocation) -> ToolExecutionOutcome:
        args: FindRelatedEvidenceInput = invocation.args
        task_id = invocation.context.task_id
        try:
            parse_evidence_key(args.evidence_key)
        except InvalidEvidenceKeyError:
            raise ToolExecutionError(
                ToolErrorCode.EVIDENCE_REF_INVALID,
                "malformed evidence key",
            ) from None
        resolved = await services.investigation_service.resolve_evidence(
            task_id, args.evidence_key
        )
        if resolved is None:
            raise ToolExecutionError(
                ToolErrorCode.EVIDENCE_REF_INVALID,
                "evidence key did not resolve in this task scope",
            )
        related = tuple(
            (resolved.get("related_evidence_keys") or ())[: config.max_related_items]
        )
        limitations = []
        if resolved.get("evidence_type") == "file" and not related:
            limitations.append(
                "file->cluster association has no read facade yet; use "
                "find_temporal_neighbors for time-adjacent events"
            )
        output = FindRelatedEvidenceOutput(
            evidence_key=args.evidence_key,
            related_evidence_keys=related,
            result_count=len(related),
            limitations=tuple(limitations),
        )
        return ToolExecutionOutcome(
            summary=f"{len(related)} related evidence items",
            result=output,
            evidence_refs=(args.evidence_key, *related),
        )

    from ..definitions import (
        EvidenceBehavior,
        ForensicToolDefinition,
        ToolAccess,
        ToolCategory,
        ToolCostClass,
        ToolPaginationKind,
        ToolScopeKind,
    )

    definition = ForensicToolDefinition(
        tool_id="find_related_evidence",
        version="1",
        title="Find related evidence",
        description=(
            "Returns Evidence related to one canonical evidence_key "
            "(cluster member files for cluster keys). Deterministic order."
        ),
        input_model=FindRelatedEvidenceInput,
        output_model=FindRelatedEvidenceOutput,
        category=ToolCategory.EVIDENCE,
        access=ToolAccess.READ,
        scope_kind=ToolScopeKind.EVIDENCE,
        evidence_behavior=EvidenceBehavior.EVIDENCE_PRODUCING,
        cost_class=ToolCostClass.STANDARD,
        pagination_kind=ToolPaginationKind.NONE,
    )
    return definition, adapter
