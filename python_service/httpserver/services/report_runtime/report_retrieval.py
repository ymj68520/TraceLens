"""Report Retrieval Plan + deterministic retrieval planning (P7A §20-§28).

The retrieval planner is NOT an Investigator (§20): given one ChapterSpec
and the frozen planning context it decides *what the chapter needs* --
anchors, accepted semantic basis, graph navigation intent, deterministic
expansion scopes -- and nothing else.  It creates no Finding, no Claim,
no Working State write; a plan naming an evidence ref that later fails
resolution simply never reaches a ContextPack (§53: plan != execution).

Graph navigation is recorded as *intent* only (§21): the plan carries the
P6 report-mode query text and budget; graph results are never Evidence
(§25) and graph ids never become citations (§26).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, model_validator

from .canonical import sha256_hex
from .report_outline import ReportPlanningContextV1

RETRIEVAL_PLAN_VERSION = "report-retrieval-plan:v1"
RETRIEVAL_POLICY_VERSION = "report-retrieval-policy:v1"
DEDUP_POLICY_VERSION = "report-dedup-policy:v1"

RETRIEVAL_PLAN_ID_PREFIX = "rrpl:"

AnchorRefKind = Literal[
    "report_evidence", "accepted_finding", "accepted_event",
    "accepted_analysis",
]

# §22 anchor priority, frozen for the starter policy
ANCHOR_PRIORITY: tuple[AnchorRefKind, ...] = (
    "report_evidence",
    "accepted_finding",
    "accepted_event",
    "accepted_analysis",
)

_KIND_PREFIXES = {
    "report_evidence": None,  # any evidence-key vocabulary member
    "accepted_finding": "finding:",
    "accepted_event": "event:",
    "accepted_analysis": "sa_",
}


class GraphQueryIntentV1(BaseModel):
    """§21: navigation intent only -- never a result, never an Evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    intent_id: str
    query_text: str
    mode: Literal["report"] = "report"
    max_objects: int = 8


class DeterministicExpansionV1(BaseModel):
    """One bounded, source-reusing expansion scope (§27).

    ``expansion_kind`` names the existing service whose association data
    the execution reuses; the executor implements the bounds.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    expansion_id: str
    expansion_kind: Literal[
        "event_evidence_links",
        "finding_evidence_provenance",
        "analysis_evidence_refs",
        "report_evidence_set",
    ]
    basis_ref: str
    max_items: int = 16


class ReportRetrievalPlanV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    plan_version: str = RETRIEVAL_PLAN_VERSION

    retrieval_plan_id: str

    task_id: str
    investigation_id: str
    finalization_id: str

    outline_id: str
    outline_revision: int
    chapter_id: str
    chapter_spec_hash: str

    anchor_refs: tuple[str, ...] = ()
    anchor_kinds: tuple[str, ...] = ()  # parallel to anchor_refs
    semantic_basis_refs: tuple[str, ...] = ()

    graph_queries: tuple[GraphQueryIntentV1, ...] = ()
    deterministic_expansions: tuple[DeterministicExpansionV1, ...] = ()

    entity_scope: tuple[str, ...] = ()
    time_scope: Optional[dict] = None

    desired_hydration_depths: tuple[str, ...] = ("digest", "structured")
    budget_policy: str = "report-retrieval-budget:v1"
    dedup_policy_version: str = DEDUP_POLICY_VERSION
    retrieval_policy_version: str = RETRIEVAL_POLICY_VERSION

    created_at: str
    input_hash: str = ""

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if not isinstance(data, dict):
            return data
        data.setdefault("plan_version", RETRIEVAL_PLAN_VERSION)
        data["anchor_refs"] = tuple(dict.fromkeys(data.get("anchor_refs", ())))
        data["anchor_kinds"] = tuple(data.get("anchor_kinds", ()))
        data["semantic_basis_refs"] = tuple(
            sorted(set(data.get("semantic_basis_refs", ())))
        )
        data["entity_scope"] = tuple(sorted(set(data.get("entity_scope", ()))))
        data["graph_queries"] = tuple(
            GraphQueryIntentV1.model_validate(item)
            for item in data.get("graph_queries", ())
        )
        data["deterministic_expansions"] = tuple(
            DeterministicExpansionV1.model_validate(item)
            for item in data.get("deterministic_expansions", ())
        )
        data.setdefault(
            "desired_hydration_depths", ("digest", "structured")
        )
        data.setdefault("time_scope", None)
        data.setdefault("budget_policy", "report-retrieval-budget:v1")
        data.setdefault("dedup_policy_version", DEDUP_POLICY_VERSION)
        data.setdefault("retrieval_policy_version", RETRIEVAL_POLICY_VERSION)
        if not data.get("created_at"):
            data["created_at"] = datetime.now(timezone.utc).isoformat()
        payload = {
            key: value
            for key, value in data.items()
            if key not in ("retrieval_plan_id", "created_at", "input_hash")
        }
        digest = sha256_hex(payload)
        data["input_hash"] = digest
        data["retrieval_plan_id"] = RETRIEVAL_PLAN_ID_PREFIX + digest[:24]
        return data


class RetrievalPlanError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _anchor_kind(ref: str, context: ReportPlanningContextV1) -> str:
    """Classify one anchor ref against the frozen context (§22 priority)."""
    if ref.startswith("finding:"):
        return "accepted_finding"
    if ref.startswith("event:"):
        return "accepted_event"
    if ref.startswith("sa_"):
        return "accepted_analysis"
    return "report_evidence"


class DeterministicReportRetrievalPlanner:
    """Plan retrieval for one ChapterSpec from the frozen context (§20-§28).

    Deterministic by construction: the same ChapterSpec + context replay
    to the same plan id.  Anchors follow §22 priority; semantic basis is
    accepted-only (§23); graph navigation is intent-only in report mode.
    """

    policy_version = RETRIEVAL_POLICY_VERSION

    def build_plan(
        self,
        *,
        context: ReportPlanningContextV1,
        chapter_spec,
    ) -> ReportRetrievalPlanV1:
        vocabulary = context.evidence_anchor_vocabulary()

        anchors: list[str] = []
        anchor_kinds: list[str] = []
        for ref in chapter_spec.required_anchor_refs:
            self._require_anchor_legal(ref, context, vocabulary)
            anchors.append(ref)
            anchor_kinds.append(_anchor_kind(ref, context))
        for ref in chapter_spec.optional_anchor_refs:
            if ref in anchors:
                continue
            self._require_anchor_legal(ref, context, vocabulary)
            anchors.append(ref)
            anchor_kinds.append(_anchor_kind(ref, context))
        # §22: report-selected evidence anchors first, then findings,
        # events, analyses -- the closed priority order.
        order = {kind: i for i, kind in enumerate(ANCHOR_PRIORITY)}
        paired = sorted(
            zip(anchors, anchor_kinds), key=lambda pair: order[pair[1]]
        )
        anchors = [ref for ref, _kind in paired]
        anchor_kinds = [kind for _ref, kind in paired]

        # §23 accepted-only semantic basis: findings must be accepted in
        # the frozen context; events pinned by exact version; analyses by
        # accepted status at context build time.
        semantic_refs: list[str] = []
        for ref in chapter_spec.required_anchor_refs:
            if ref.startswith("finding:"):
                if context.finding_review_status(ref) != "accepted":
                    raise RetrievalPlanError(
                        "semantic_ref_not_accepted",
                        f"chapter anchors an unaccepted finding: {ref}",
                    )
                semantic_refs.append(ref)
            elif ref.startswith("event:"):
                semantic_refs.append(ref)
            elif ref.startswith("sa_"):
                semantic_refs.append(ref)
        # report evidence is context, not semantic basis (§40)
        semantic_refs = sorted(set(semantic_refs))

        expansions: list[DeterministicExpansionV1] = []
        for index, ref in enumerate(semantic_refs):
            if ref.startswith("finding:"):
                kind = "finding_evidence_provenance"
            elif ref.startswith("event:"):
                kind = "event_evidence_links"
            else:
                kind = "analysis_evidence_refs"
            expansions.append(
                DeterministicExpansionV1(
                    expansion_id=f"exp_{chapter_spec.chapter_id}_{index}",
                    expansion_kind=kind,
                    basis_ref=ref,
                )
            )
        report_keys = context.report_evidence_keys()
        if report_keys:
            expansions.append(
                DeterministicExpansionV1(
                    expansion_id=f"exp_{chapter_spec.chapter_id}_rset",
                    expansion_kind="report_evidence_set",
                    basis_ref="report_evidence_set",
                    max_items=max(len(report_keys), 1),
                )
            )

        graph_queries: tuple[GraphQueryIntentV1, ...] = ()
        if chapter_spec.topic_scope:
            graph_queries = (
                GraphQueryIntentV1(
                    intent_id=f"gq_{chapter_spec.chapter_id}",
                    query_text=chapter_spec.topic_scope,
                ),
            )

        return ReportRetrievalPlanV1(
            task_id=context.task_id,
            investigation_id=context.investigation_id,
            finalization_id=context.finalization.finalization_id,
            outline_id=chapter_spec.outline_id,
            outline_revision=chapter_spec.outline_revision,
            chapter_id=chapter_spec.chapter_id,
            chapter_spec_hash=chapter_spec.input_hash,
            anchor_refs=tuple(anchors),
            anchor_kinds=tuple(anchor_kinds),
            semantic_basis_refs=tuple(semantic_refs),
            graph_queries=graph_queries,
            deterministic_expansions=tuple(expansions),
            entity_scope=chapter_spec.entity_scope,
            time_scope=chapter_spec.time_scope,
            desired_hydration_depths=("digest", "structured"),
        )

    @staticmethod
    def _require_anchor_legal(
        ref: str,
        context: ReportPlanningContextV1,
        vocabulary: frozenset,
    ) -> None:
        if ref.startswith("graph:") or ref.startswith("gm:") or (
            ref.startswith("gcand:")
        ):
            raise RetrievalPlanError(
                "graph_ref_forbidden", f"graph ids are never anchors: {ref}"
            )
        if ref.startswith("finding:"):
            status = context.finding_review_status(ref)
            if status is None:
                raise RetrievalPlanError(
                    "unknown_anchor", f"unknown finding anchor: {ref}"
                )
            if status != "accepted":
                raise RetrievalPlanError(
                    "semantic_ref_not_accepted",
                    f"finding anchor is not accepted: {ref}",
                )
            return
        if ref.startswith("event:"):
            if context.accepted_event(ref) is None:
                raise RetrievalPlanError(
                    "unknown_anchor", f"unknown event anchor: {ref}"
                )
            return
        if ref.startswith("sa_"):
            if context.accepted_analysis(ref) is None:
                raise RetrievalPlanError(
                    "unknown_anchor", f"unknown analysis anchor: {ref}"
                )
            return
        if ref in vocabulary:
            return
        raise RetrievalPlanError(
            "evidence_ref_unknown", f"unknown evidence anchor: {ref}"
        )


__all__ = [
    "ANCHOR_PRIORITY",
    "DEDUP_POLICY_VERSION",
    "DeterministicExpansionV1",
    "DeterministicReportRetrievalPlanner",
    "GraphQueryIntentV1",
    "RETRIEVAL_PLAN_VERSION",
    "RETRIEVAL_POLICY_VERSION",
    "ReportRetrievalPlanV1",
    "RetrievalPlanError",
]
