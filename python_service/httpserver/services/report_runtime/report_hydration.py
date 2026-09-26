"""Evidence roles, hydration depths, ranking, budget (P7A §29-§38).

The pack distinguishes *context role* (anchor / supporting /
retrieved_context) from `report_evidence.status` (main / appendix /
excluded): entering a pack never changes a Report Evidence row (§7/§29).

Hydration has exactly three frozen depths (§30-§31); ranking is
deterministic-first (§36); budget is configurable and its exhaustion
truncates deterministically and records a limitation — mandatory anchors
are never silently dropped (§37/§38).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Literal, Optional

from .canonical import sha256_hex
from .report_dedup import EvidenceIndependence

EvidenceRole = Literal["anchor", "supporting", "retrieved_context"]

HydrationDepth = Literal["digest", "structured", "detailed"]

HYDRATION_POLICY_VERSION = "report-hydration-policy:v1"
BUDGET_POLICY_VERSION = "report-retrieval-budget:v1"
RANKING_POLICY_VERSION = "report-evidence-ranking:v1"

# §31 starter defaults (P8 calibration; never architecture constants)
ROLE_DEFAULT_DEPTH: dict[EvidenceRole, HydrationDepth] = {
    "anchor": "structured",
    "supporting": "structured",
    "retrieved_context": "digest",
}


@dataclass(frozen=True)
class RetrievalBudgetV1:
    """§37: all values configurable; nothing frozen at architecture level."""

    max_evidence_items: int = 24
    max_detailed_items: int = 4
    max_context_chars: int = 48_000
    max_graph_expansion: int = 8


@dataclass
class BudgetAccounting:
    """Deterministic budget consumption record for one pack build."""

    budget: RetrievalBudgetV1
    limitations: list[str] = field(default_factory=list)
    truncated_refs: list[str] = field(default_factory=list)
    detailed_count: int = 0
    context_chars: int = 0


@dataclass(frozen=True)
class RankedCandidate:
    """One deduped evidence candidate with its deterministic rank input."""

    independence: EvidenceIndependence
    role: EvidenceRole
    rank_score: float
    rank_reasons: tuple[str, ...] = ()


def rank_candidates(
    candidates: Iterable[tuple[EvidenceIndependence, EvidenceRole]],
    *,
    report_evidence_status: Optional[dict[str, str]] = None,
    accepted_semantic_refs: tuple[str, ...] = (),
    entity_scope: tuple[str, ...] = (),
    graph_distance: Optional[dict[str, int]] = None,
) -> list[RankedCandidate]:
    """§36 deterministic-first ranking.

    Inputs are stable, reproducible facts about each candidate; no LLM
    participates.  Sort key (descending score, then ref for total order):

    - role: anchor 3.0, supporting 2.0, retrieved_context 1.0
    - report evidence status: main +0.5, appendix +0.25
    - direct accepted-semantic support +0.4
    - entity-scope match +0.3
    - graph navigation distance: 1/dist (bounded, closer is better)
    """
    report_evidence_status = report_evidence_status or {}
    graph_distance = graph_distance or {}
    semantic_support = set(accepted_semantic_refs)
    ranked: list[RankedCandidate] = []
    for independence, role in candidates:
        score = {"anchor": 3.0, "supporting": 2.0, "retrieved_context": 1.0}[
            role
        ]
        reasons = [f"role:{role}"]
        status = report_evidence_status.get(independence.root_evidence_key)
        if status == "main":
            score += 0.5
            reasons.append("report_evidence:main")
        elif status == "appendix":
            score += 0.25
            reasons.append("report_evidence:appendix")
        if independence.root_evidence_key in semantic_support or (
            independence.evidence_ref in semantic_support
        ):
            score += 0.4
            reasons.append("accepted_semantic_support")
        if any(
            scope and scope in independence.root_evidence_key
            for scope in entity_scope
        ) or any(scope and scope in independence.evidence_ref for scope in entity_scope):
            score += 0.3
            reasons.append("entity_scope_match")
        distance = graph_distance.get(independence.evidence_ref)
        if distance is not None and distance > 0:
            score += min(1.0 / distance, 0.5)
            reasons.append(f"graph_distance:{distance}")
        ranked.append(
            RankedCandidate(
                independence=independence,
                role=role,
                rank_score=round(score, 4),
                rank_reasons=tuple(reasons),
            )
        )
    ranked.sort(key=lambda item: (-item.rank_score, item.independence.evidence_ref))
    return ranked


def apply_budget(
    ranked: list[RankedCandidate],
    *,
    required_anchor_refs: Iterable[str],
    budget: Optional[RetrievalBudgetV1] = None,
    depth_overrides: Optional[dict[str, HydrationDepth]] = None,
) -> tuple[list[RankedCandidate], BudgetAccounting]:
    """§37/§38 deterministic truncation.

    Mandatory anchors that are present in the ranked list are NEVER
    dropped: budget exhaustion first sheds retrieved_context, then
    supporting, and only then raises ``BUDGET_EXHAUSTED_ANCHORS`` (the
    caller decides blocked vs incomplete).  Every dropped ref is recorded
    as a limitation — never a silent loss.
    """
    budget = budget or RetrievalBudgetV1()
    accounting = BudgetAccounting(budget=budget)
    required = list(dict.fromkeys(required_anchor_refs))

    kept: list[RankedCandidate] = []
    kept_refs: set[str] = set()

    # 1. mandatory anchors first, unconditionally
    for candidate in ranked:
        if candidate.independence.evidence_ref in required or (
            candidate.independence.root_evidence_key in required
        ):
            kept.append(candidate)
            kept_refs.add(candidate.independence.evidence_ref)
            kept_refs.add(candidate.independence.root_evidence_key)

    # 2. fill remaining slots in rank order
    for candidate in ranked:
        if candidate in kept:
            continue
        if len(kept) >= budget.max_evidence_items:
            accounting.truncated_refs.append(
                candidate.independence.evidence_ref
            )
            continue
        kept.append(candidate)
        kept_refs.add(candidate.independence.evidence_ref)
        kept_refs.add(candidate.independence.root_evidence_key)

    # 3. downgrade/limit detailed depth
    depth_overrides = depth_overrides or {}
    for candidate in kept:
        depth = depth_overrides.get(
            candidate.independence.evidence_ref,
            ROLE_DEFAULT_DEPTH[candidate.role],
        )
        if depth == "detailed":
            if accounting.detailed_count >= budget.max_detailed_items:
                accounting.limitations.append(
                    f"DETAILED_DEPTH_BUDGET_EXCEEDED:"
                    f"{candidate.independence.evidence_ref}"
                )
            else:
                accounting.detailed_count += 1

    if accounting.truncated_refs:
        accounting.limitations.append(
            "EVIDENCE_BUDGET_TRUNCATED:" + ",".join(accounting.truncated_refs)
        )
    missing_required = [
        ref for ref in required if ref not in kept_refs
    ]
    if missing_required:
        accounting.limitations.append(
            "BUDGET_EXHAUSTED_ANCHORS:" + ",".join(sorted(missing_required))
        )
    return kept, accounting


__all__ = [
    "BUDGET_POLICY_VERSION",
    "BudgetAccounting",
    "HYDRATION_POLICY_VERSION",
    "HydrationDepth",
    "EvidenceRole",
    "RANKING_POLICY_VERSION",
    "RankedCandidate",
    "RetrievalBudgetV1",
    "ROLE_DEFAULT_DEPTH",
    "apply_budget",
    "rank_candidates",
]
