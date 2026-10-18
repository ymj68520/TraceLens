"""Evidence availability model (P8A §8-§11, §88).

Three separate layers, never collapsed:

    ground_truth        — what the truth author knows exists
    parser_reachable    — what the installed parsers can actually surface
    agent_discoverable  — what canonical tools/services expose to the Agent

Agent recall's denominator is parser-reachable critical evidence
(§30); ground-truth critical reachability is reported SEPARATELY so a
parser gap is never booked as an Agent reasoning failure.
"""

from __future__ import annotations

from dataclasses import dataclass

from .truth_manifest import (
    EvidenceCriticality,
    ReachabilityManifestV1,
    ReachabilityStatus,
    TruthManifestV1,
)

__all__ = [
    "AvailabilitySummary",
    "compute_availability_summary",
    "parser_reachable_critical_ids",
    "resolve_reachability_record",
]


def resolve_reachability_record(
    *,
    truth_evidence_id: str,
    resolved_evidence_keys: tuple[str, ...],
    parser_reachable: bool,
    agent_discoverable: bool,
    unavailable_reason: str = "",
):
    """Build one reachability record with the §8/§10/§11 layer rules:

    - parser expectation ``unavailable`` forces parser_unreachable;
    - agent discoverability implies parser reachability;
    - resolved status requires actual keys.
    """
    from .truth_manifest import EvidenceReachabilityRecordV1

    if parser_reachable and not agent_discoverable:
        status = ReachabilityStatus.tool_not_exposed
        unavailable_reason = unavailable_reason or (
            "no canonical tool exposes this evidence"
        )
    elif not parser_reachable:
        status = ReachabilityStatus.parser_unavailable
        unavailable_reason = unavailable_reason or (
            "parser cannot surface this evidence"
        )
    elif resolved_evidence_keys:
        status = ReachabilityStatus.resolved
    else:
        status = ReachabilityStatus.unresolved
        unavailable_reason = unavailable_reason or (
            "reachability unresolved at case preparation"
        )
    return EvidenceReachabilityRecordV1(
        truth_evidence_id=truth_evidence_id,
        resolved_evidence_keys=tuple(sorted(set(resolved_evidence_keys))),
        parser_reachable=parser_reachable,
        agent_discoverable=agent_discoverable,
        status=status,
        unavailable_reason=unavailable_reason,
    )


@dataclass(frozen=True)
class AvailabilitySummary:
    """Per-criticality layer counts (§8: layers are computed separately)."""

    critical_ground_truth: int
    critical_parser_reachable: int
    critical_agent_discoverable: int
    supporting_ground_truth: int
    supporting_parser_reachable: int
    supporting_agent_discoverable: int
    irrelevant_ground_truth: int
    irrelevant_parser_reachable: int
    irrelevant_agent_discoverable: int

    @property
    def critical_ground_truth_reachability(self) -> float:
        """§30: ground-truth critical reachability, reported separately so
        parser gaps stay visible (never merged into agent recall)."""
        if self.critical_ground_truth == 0:
            return 1.0
        return (
            self.critical_parser_reachable / self.critical_ground_truth
        )


def compute_availability_summary(
    truth_manifest: TruthManifestV1,
    reachability: ReachabilityManifestV1,
) -> AvailabilitySummary:
    """Deterministic layer counts per criticality (§88)."""
    by_id = {
        record.truth_evidence_id: record for record in reachability.records
    }
    counts: dict[str, list[int]] = {
        EvidenceCriticality.critical.value: [0, 0, 0],
        EvidenceCriticality.supporting.value: [0, 0, 0],
        EvidenceCriticality.irrelevant.value: [0, 0, 0],
    }
    for item in truth_manifest.all_evidence_items():
        bucket = counts[item.criticality.value]
        bucket[0] += 1
        record = by_id.get(item.truth_evidence_id)
        if record is None:
            continue
        if record.parser_reachable:
            bucket[1] += 1
        if record.agent_discoverable:
            bucket[2] += 1
    return AvailabilitySummary(
        critical_ground_truth=counts["critical"][0],
        critical_parser_reachable=counts["critical"][1],
        critical_agent_discoverable=counts["critical"][2],
        supporting_ground_truth=counts["supporting"][0],
        supporting_parser_reachable=counts["supporting"][1],
        supporting_agent_discoverable=counts["supporting"][2],
        irrelevant_ground_truth=counts["irrelevant"][0],
        irrelevant_parser_reachable=counts["irrelevant"][1],
        irrelevant_agent_discoverable=counts["irrelevant"][2],
    )


def parser_reachable_critical_ids(
    truth_manifest: TruthManifestV1,
    reachability: ReachabilityManifestV1,
) -> frozenset[str]:
    """The §30 recall DENOMINATOR: truth ids of critical items that are
    parser-reachable.  Ground-truth-only critical items are excluded so a
    parser limitation is never booked as an Agent discovery failure."""
    by_id = {
        record.truth_evidence_id: record for record in reachability.records
    }
    return frozenset(
        item.truth_evidence_id
        for item in truth_manifest.critical_evidence
        if item.truth_evidence_id in by_id
        and by_id[item.truth_evidence_id].parser_reachable
    )
