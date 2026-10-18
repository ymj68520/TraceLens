"""Timeline tools (P3 §20).

search_timeline          backend-owned event page; each event carries its
                         canonical cluster:v1 key derived server-side — the
                         model can never construct cluster keys itself.
find_temporal_neighbors  bounded time-window query around an anchor.
"""

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from ....evidence.exceptions import InvalidEvidenceKeyError
from ....evidence.keys import parse_evidence_key
from ..errors import ToolErrorCode, ToolExecutionError
from ..registry import ToolExecutionOutcome
from .base import (
    ToolCatalogConfig,
    bounded_page_size,
    cluster_key_for_event,
)
from .services import ForensicToolServices


class _EventDigest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str | None = None
    event_type: str
    timestamp: int | None = None
    file_path: str | None = None
    description: str | None = None
    cluster_evidence_key: str | None = None


def _digest_event(row: dict[str, Any]) -> _EventDigest:
    return _EventDigest(
        event_id=str(row["id"]) if row.get("id") is not None else None,
        event_type=str(row.get("event_type") or ""),
        timestamp=row.get("timestamp"),
        file_path=row.get("file_path"),
        description=row.get("description"),
        cluster_evidence_key=cluster_key_for_event(
            row.get("timestamp"), row.get("event_type")
        ),
    )


# ---------------------------------------------------------------------------
# search_timeline
# ---------------------------------------------------------------------------


class SearchTimelineInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: Optional[str] = None
    start_time: Optional[int] = None  # epoch seconds
    end_time: Optional[int] = None
    page_size: Optional[int] = None
    page_token: Optional[int] = None


class SearchTimelineOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: tuple[_EventDigest, ...] = ()
    result_count: int = 0
    total_count: int = 0
    truncated: bool = False
    continuation: str | None = None


def build_search_timeline_tool(
    services: ForensicToolServices, config: ToolCatalogConfig
):
    async def adapter(invocation) -> ToolExecutionOutcome:
        args: SearchTimelineInput = invocation.args
        task_id = invocation.context.task_id
        result = await services.cpp_backend.get_task_events(
            task_id,
            event_type=args.event_type,
            start_time=args.start_time,
            end_time=args.end_time,
            page=int(args.page_token or 1),
            page_size=bounded_page_size(args.page_size, config),
        )
        rows = list(result.get("events") or [])
        rows.sort(key=lambda row: (row.get("timestamp") or 0, str(row.get("id") or "")))
        total = int(result.get("total_count") or 0)
        digests = tuple(_digest_event(row) for row in rows)
        page_size = bounded_page_size(args.page_size, config)
        page = int(args.page_token or 1)
        continuation = str(page + 1) if page * page_size < total else None
        return ToolExecutionOutcome(
            summary=f"{len(digests)} timeline events (total {total})",
            result=SearchTimelineOutput(
                items=digests,
                result_count=len(digests),
                total_count=total,
                truncated=continuation is not None,
                continuation=continuation,
            ),
            evidence_refs=tuple(
                item.cluster_evidence_key
                for item in digests
                if item.cluster_evidence_key
            ),
            limitations=(
                "cluster evidence keys are derived server-side; hydrate with get_evidence",
            ),
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
        tool_id="search_timeline",
        version="1",
        title="Search the forensic timeline",
        description=(
            "Queries raw timeline events with optional event-type and time "
            "filters. Each event carries its canonical cluster evidence key; "
            "hydrate clusters with get_evidence. Bounded, deterministic pages."
        ),
        input_model=SearchTimelineInput,
        output_model=SearchTimelineOutput,
        category=ToolCategory.TIMELINE,
        access=ToolAccess.READ,
        scope_kind=ToolScopeKind.TIMELINE,
        evidence_behavior=EvidenceBehavior.EVIDENCE_PRODUCING,
        cost_class=ToolCostClass.STANDARD,
        pagination_kind=ToolPaginationKind.PAGE_TOKEN,
    )
    return definition, adapter


# ---------------------------------------------------------------------------
# find_temporal_neighbors
# ---------------------------------------------------------------------------


class FindTemporalNeighborsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    anchor_timestamp: Optional[int] = None  # epoch seconds
    anchor_evidence_key: Optional[str] = None  # derives the anchor time
    window_seconds: Optional[int] = None
    event_type: Optional[str] = None


class FindTemporalNeighborsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    anchor_timestamp: int
    window_seconds: int
    items: tuple[_EventDigest, ...] = ()
    result_count: int = 0
    truncated: bool = False


def build_find_temporal_neighbors_tool(
    services: ForensicToolServices, config: ToolCatalogConfig
):
    async def adapter(invocation) -> ToolExecutionOutcome:
        args: FindTemporalNeighborsInput = invocation.args
        task_id = invocation.context.task_id
        anchor = args.anchor_timestamp
        if anchor is None and args.anchor_evidence_key:
            try:
                parse_evidence_key(args.anchor_evidence_key)
            except InvalidEvidenceKeyError:
                raise ToolExecutionError(
                    ToolErrorCode.EVIDENCE_REF_INVALID,
                    "malformed anchor evidence key",
                ) from None
            resolved = await services.investigation_service.resolve_evidence(
                task_id, args.anchor_evidence_key
            )
            if resolved is None:
                raise ToolExecutionError(
                    ToolErrorCode.EVIDENCE_REF_INVALID,
                    "anchor evidence key did not resolve in this task scope",
                )
            anchor = resolved.get("start_time") or resolved.get("timestamp")
        if anchor is None:
            raise ToolExecutionError(
                ToolErrorCode.TOOL_INPUT_INVALID,
                "provide anchor_timestamp or anchor_evidence_key",
            )
        anchor = int(anchor)
        window = min(
            int(args.window_seconds or config.default_temporal_window_seconds),
            config.max_temporal_window_seconds,
        )
        result = await services.cpp_backend.get_task_events(
            task_id,
            event_type=args.event_type,
            start_time=anchor - window,
            end_time=anchor + window,
            page=1,
            page_size=config.max_page_size,
        )
        rows = list(result.get("events") or [])
        rows.sort(key=lambda row: (abs((row.get("timestamp") or 0) - anchor),
                                   row.get("timestamp") or 0,
                                   str(row.get("id") or "")))
        digests = tuple(_digest_event(row) for row in rows)
        return ToolExecutionOutcome(
            summary=(
                f"{len(digests)} events within ±{window}s of {anchor}"
            ),
            result=FindTemporalNeighborsOutput(
                anchor_timestamp=anchor,
                window_seconds=window,
                items=digests,
                result_count=len(digests),
                truncated=len(rows) >= config.max_page_size,
            ),
            evidence_refs=tuple(
                item.cluster_evidence_key
                for item in digests
                if item.cluster_evidence_key
            ),
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
        tool_id="find_temporal_neighbors",
        version="1",
        title="Find temporally adjacent events",
        description=(
            "Returns events within a bounded time window around a timestamp "
            "or evidence item, nearest first. Reuses the timeline query "
            "semantics; bounded window and page size."
        ),
        input_model=FindTemporalNeighborsInput,
        output_model=FindTemporalNeighborsOutput,
        category=ToolCategory.TIMELINE,
        access=ToolAccess.READ,
        scope_kind=ToolScopeKind.TIMELINE,
        evidence_behavior=EvidenceBehavior.EVIDENCE_PRODUCING,
        cost_class=ToolCostClass.STANDARD,
        pagination_kind=ToolPaginationKind.NONE,
    )
    return definition, adapter
