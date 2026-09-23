"""Existing investigation semantics tools (P3 §20).

get_existing_analyses  secondary analyses with faithful review state —
                       rejected/invalid versions are never masked as active.
get_existing_claims    analysis claims / effective event claims, read-only,
                       grounding status and evidence refs preserved.
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict

from ..errors import ToolErrorCode, ToolExecutionError
from ..registry import ToolExecutionOutcome
from .base import ToolCatalogConfig
from .services import ForensicToolServices


# ---------------------------------------------------------------------------
# get_existing_analyses
# ---------------------------------------------------------------------------


class GetExistingAnalysesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_key: Optional[str] = None  # None -> all evidence of the task


class AnalysisDigest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_id: str
    evidence_key: str
    version: int
    status: str  # faithful queued/running/review_pending/accepted/rejected/invalid/failed
    grounding_status: str | None = None
    summary: str | None = None
    description: str | None = None
    created_at: str | None = None
    decision_reason: str | None = None


class GetExistingAnalysesOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: tuple[AnalysisDigest, ...] = ()
    result_count: int = 0
    truncated: bool = False
    limitations: tuple[str, ...] = ()


def _analysis_digest(analysis) -> AnalysisDigest:
    return AnalysisDigest(
        analysis_id=analysis.analysis_id,
        evidence_key=analysis.evidence_key,
        version=analysis.version,
        status=str(getattr(analysis.status, "value", analysis.status)),
        grounding_status=(
            getattr(analysis.grounding_status, "value", analysis.grounding_status)
            if analysis.grounding_status
            else None
        ),
        summary=analysis.summary,
        description=analysis.description,
        created_at=analysis.created_at,
        decision_reason=analysis.decision_reason,
    )


def build_get_existing_analyses_tool(
    services: ForensicToolServices, config: ToolCatalogConfig
):
    async def adapter(invocation) -> ToolExecutionOutcome:
        args: GetExistingAnalysesInput = invocation.args
        task_id = invocation.context.task_id
        limit = config.max_page_size
        if args.evidence_key:
            analyses = await services.secondary_analysis_executor.list_analyses(
                task_id, args.evidence_key
            )
        else:
            grouped = await services.secondary_analysis_executor.list_all_analyses(
                task_id
            )
            analyses = [
                analysis
                for key in sorted(grouped)
                for analysis in grouped[key]
            ]
        digests = [_analysis_digest(analysis) for analysis in analyses]
        truncated = len(digests) > limit
        digests = digests[:limit]
        return ToolExecutionOutcome(
            summary=f"{len(digests)} secondary analyses (faithful review state)",
            result=GetExistingAnalysesOutput(
                items=tuple(digests),
                result_count=len(digests),
                truncated=truncated,
                limitations=(
                    "statuses include rejected/invalid/failed versions; "
                    "review state is canonical, never masked",
                ),
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
        tool_id="get_existing_analyses",
        version="1",
        title="Get existing secondary analyses",
        description=(
            "Lists prior secondary analyses for one evidence item or the "
            "whole task, with exact review status (queued/running/"
            "review_pending/accepted/rejected/invalid/failed) and grounding "
            "status. Rejected versions are shown as rejected."
        ),
        input_model=GetExistingAnalysesInput,
        output_model=GetExistingAnalysesOutput,
        category=ToolCategory.INVESTIGATION_READS,
        access=ToolAccess.READ,
        scope_kind=ToolScopeKind.ANALYSIS,
        evidence_behavior=EvidenceBehavior.NON_EVIDENCE,
        cost_class=ToolCostClass.CHEAP,
        pagination_kind=ToolPaginationKind.NONE,
    )
    return definition, adapter


# ---------------------------------------------------------------------------
# get_existing_claims
# ---------------------------------------------------------------------------


class GetExistingClaimsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_id: Optional[str] = None
    event_id: Optional[str] = None


class ClaimDigest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    claim_type: str | None = None
    claim_text: str
    grounding_status: str | None = None
    status: str | None = None  # event-claim review status when available
    evidence_refs: tuple[str, ...] = ()


class GetExistingClaimsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: tuple[ClaimDigest, ...] = ()
    result_count: int = 0
    truncated: bool = False


def build_get_existing_claims_tool(
    services: ForensicToolServices, config: ToolCatalogConfig
):
    async def adapter(invocation) -> ToolExecutionOutcome:
        args: GetExistingClaimsInput = invocation.args
        task_id = invocation.context.task_id
        if bool(args.analysis_id) == bool(args.event_id):
            raise ToolExecutionError(
                ToolErrorCode.TOOL_INPUT_INVALID,
                "provide exactly one of analysis_id or event_id",
            )
        claims: list[ClaimDigest] = []
        if args.analysis_id:
            found = await services.investigation_read_service.list_analysis_claims(
                task_id, args.analysis_id
            )
            for claim in found or []:
                claims.append(
                    ClaimDigest(
                        claim_id=claim.claim_id,
                        claim_type=str(
                            getattr(claim.claim_type, "value", claim.claim_type)
                        ),
                        claim_text=claim.claim_text,
                        grounding_status=(
                            getattr(
                                claim.grounding_status,
                                "value",
                                claim.grounding_status,
                            )
                            if claim.grounding_status
                            else None
                        ),
                        evidence_refs=tuple(claim.evidence_refs),
                    )
                )
        else:
            try:
                effective = await services.investigation_service.effective_event_claims(
                    task_id, args.event_id
                )
            except KeyError:
                raise ToolExecutionError(
                    ToolErrorCode.TOOL_INPUT_INVALID,
                    "event_id did not resolve in this task scope",
                ) from None
            for claim in effective or []:
                claims.append(
                    ClaimDigest(
                        claim_id=str(claim.get("id") or claim.get("claim_id") or ""),
                        claim_type=claim.get("claim_type"),
                        claim_text=str(claim.get("claim_text") or ""),
                        grounding_status=claim.get("grounding_status"),
                        status=claim.get("status"),
                        evidence_refs=tuple(
                            str(ref)
                            for ref in (claim.get("evidence_refs") or ())
                            if ref
                        ),
                    )
                )
        truncated = len(claims) > config.max_page_size
        claims = claims[: config.max_page_size]
        return ToolExecutionOutcome(
            summary=f"{len(claims)} existing claims",
            result=GetExistingClaimsOutput(
                items=tuple(claims),
                result_count=len(claims),
                truncated=truncated,
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
        tool_id="get_existing_claims",
        version="1",
        title="Get existing claims",
        description=(
            "Reads previously recorded claims: analysis claims for one "
            "analysis_id, or effective event claims for one event_id. "
            "Review status, grounding status and evidence refs are preserved "
            "exactly as recorded."
        ),
        input_model=GetExistingClaimsInput,
        output_model=GetExistingClaimsOutput,
        category=ToolCategory.INVESTIGATION_READS,
        access=ToolAccess.READ,
        scope_kind=ToolScopeKind.CLAIM,
        evidence_behavior=EvidenceBehavior.NON_EVIDENCE,
        cost_class=ToolCostClass.CHEAP,
        pagination_kind=ToolPaginationKind.NONE,
    )
    return definition, adapter
