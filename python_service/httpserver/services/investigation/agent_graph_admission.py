"""GraphAdmissionPolicy — the deterministic graph safety boundary
(P6A §13-§20, §47-§48, §50-§51).

The policy is NOT an agent and calls no model (§13). Agents and the
Supervisor may only PROPOSE candidates; this policy is the sole authority
that turns a proposal into ``admit`` / ``defer`` / ``not_admitted``
(§14 vocabulary — deliberately NOT accepted/rejected, which belong to
Analyst Review).

The exact admission table is architecture TBD/CALIBRATION (§16): this is
a versioned STARTER policy. Hard boundaries below are NOT calibration
(§11): Analyst Notes, Case Context, agent reasoning, ungrounded
hypotheses, ToolObservation/verifier/supervisor prose and raw LLM text
can never become graph facts.

``admit`` means only "allowed to materialize" (§18) — it says nothing
about Graphiti write success or graph queryability; those live in the
materialization manifest lifecycle.
"""

from __future__ import annotations

import hashlib
import enum
from typing import Callable, Mapping, Optional

from pydantic import BaseModel, ConfigDict

from .agent_graph_candidate import GraphCandidateV1
from .agent_runtime import canonical_state_json

GRAPH_ADMISSION_POLICY_VERSION = "graph-admission-policy:v1"

# Provisional budget seams (§48) — config, P8 calibrates the numbers.
DEFAULT_MAX_ACTIVE_MATERIALIZATIONS = 50
DEFAULT_MAX_EPISODE_UNITS = 16
DEFAULT_MAX_CANDIDATES_PER_CYCLE = 32


class GraphAdmissionDecision(enum.Enum):
    ADMIT = "admit"
    DEFER = "defer"
    NOT_ADMITTED = "not_admitted"


class GraphBudgetPolicy(BaseModel):
    """§48 deterministic budget seam; exhaustion DEFERS, never refuses."""

    model_config = ConfigDict(frozen=True)

    max_active_materializations: int = DEFAULT_MAX_ACTIVE_MATERIALIZATIONS
    max_episode_units: int = DEFAULT_MAX_EPISODE_UNITS
    max_candidates_per_cycle: int = DEFAULT_MAX_CANDIDATES_PER_CYCLE


class ReasonCode:
    """Stable reason codes recorded on every decision."""

    ADMITTED = "ADMITTED_PROVENANCE_COMPLETE"
    PROVENANCE_MISSING = "PROVENANCE_MISSING"
    KIND_UNKNOWN = "CANDIDATE_KIND_UNKNOWN"
    CROSS_TASK = "CROSS_TASK_PROVENANCE"
    FINDING_REJECTED = "FINDING_REJECTED"
    FINDING_UNKNOWN = "FINDING_STATUS_UNKNOWN"
    UNGROUNDED_HYPOTHESIS = "UNGROUNDED_HYPOTHESIS"
    FORBIDDEN_SOURCE = "FORBIDDEN_SOURCE_ONLY"
    REVIEW_PENDING_UNVERIFIED = "REVIEW_PENDING_LACKS_VERIFICATION"
    BUDGET_EXHAUSTED = "GRAPH_BUDGET_EXHAUSTED"
    EVIDENCE_MISSING = "EVIDENCE_NO_LONGER_RESOLVES"


class GraphBudgetState(BaseModel):
    """Snapshot of current graph load, supplied by the caller."""

    model_config = ConfigDict(frozen=True)

    active_or_queued_materializations: int = 0


class GraphAdmissionPolicy(BaseModel):
    """Deterministic, versioned admission authority (starter rules)."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    policy_version: str = GRAPH_ADMISSION_POLICY_VERSION
    budget: GraphBudgetPolicy = GraphBudgetPolicy()

    def policy_hash(self) -> str:
        """§47: covers kind rules, review-status rules, verification
        requirements, forbidden-source rules and budget settings."""
        return hashlib.sha256(
            canonical_state_json({
                "policy_version": self.policy_version,
                "budget": self.budget.model_dump(),
                "forbidden_sources": True,
                "review_rules": {
                    "accepted": "admit",
                    "review_pending": "verified_admit_or_defer",
                    "rejected": "not_admitted",
                },
            }).encode("utf-8")
        ).hexdigest()

    def evaluate(
        self,
        candidate: GraphCandidateV1,
        *,
        finding_resolver: Optional[Callable[[str], Optional[Mapping]]] = None,
        budget_state: Optional[GraphBudgetState] = None,
    ) -> "GraphAdmissionDecisionV1":
        """Deterministic evaluation. Resolvers are plain callables so the
        policy stays storage-agnostic and trivially testable."""
        reasons: list[str] = []
        limitations: list[str] = []
        provenance: dict = {
            "evidence_refs": list(candidate.evidence_refs),
            "finding_refs": list(candidate.finding_refs),
            "correlation_refs": list(candidate.correlation_refs),
            "entity_occurrence_refs": list(candidate.entity_occurrence_refs),
        }

        def _not_admitted(code: str) -> "GraphAdmissionDecisionV1":
            reasons.append(code)
            return self._decision(candidate, GraphAdmissionDecision.NOT_ADMITTED,
                                  reasons, limitations, provenance)

        def _defer(code: str) -> "GraphAdmissionDecisionV1":
            reasons.append(code)
            return self._decision(candidate, GraphAdmissionDecision.DEFER,
                                  reasons, limitations, provenance)

        # §11 hard boundaries first
        if not (
            candidate.evidence_refs
            or candidate.finding_refs
            or candidate.correlation_refs
        ):
            return _not_admitted(ReasonCode.PROVENANCE_MISSING)
        if candidate.source_component.lower() in (
            "analyst_note", "case_context", "agent_reasoning",
            "llm_chain_of_thought", "provider_response",
            "supervisor_summary", "tool_observation_summary",
            "verifier_prose",
        ):
            return _not_admitted(ReasonCode.FORBIDDEN_SOURCE)

        # Finding status boundary (§12)
        for finding_ref in candidate.finding_refs:
            finding = (
                finding_resolver(finding_ref) if finding_resolver else None
            )
            if finding is None:
                return _not_admitted(ReasonCode.FINDING_UNKNOWN)
            status = finding["status"]
            if status == "rejected":
                return _not_admitted(ReasonCode.FINDING_REJECTED)
            if status == "review_pending" and not (
                finding.get("semantic_verification_id")
                or candidate.verification_refs
            ):
                # valid but lacking the required verification: deferred,
                # not refused (starter policy §17)
                limitations.append(
                    "review_pending finding lacks semantic verification"
                )
                return _defer(ReasonCode.REVIEW_PENDING_UNVERIFIED)
            provenance[f"finding_status:{finding_ref}"] = status

        # budget (§48): exhaustion defers — the candidate may be perfectly
        # legal, only the graph is full
        budget_state = budget_state or GraphBudgetState()
        if (
            budget_state.active_or_queued_materializations
            >= self.budget.max_active_materializations
        ):
            return _defer(ReasonCode.BUDGET_EXHAUSTED)

        reasons.append(ReasonCode.ADMITTED)
        return self._decision(
            candidate, GraphAdmissionDecision.ADMIT, reasons, limitations,
            provenance,
        )

    def _decision(
        self,
        candidate: GraphCandidateV1,
        decision: GraphAdmissionDecision,
        reasons: list[str],
        limitations: list[str],
        provenance: dict,
    ) -> "GraphAdmissionDecisionV1":
        input_payload = {
            "policy_version": self.policy_version,
            "policy_hash": self.policy_hash(),
            "candidate_id": candidate.candidate_id,
            "candidate_hash": candidate.input_hash,
            "decision": decision.value,
            "reasons": sorted(reasons),
        }
        input_hash = hashlib.sha256(
            canonical_state_json(input_payload).encode("utf-8")
        ).hexdigest()
        decision_id = "gadm:" + hashlib.sha256(
            canonical_state_json({**input_payload, "input_hash": input_hash})
            .encode("utf-8")
        ).hexdigest()[:24]
        return GraphAdmissionDecisionV1(
            decision_id=decision_id,
            task_id=candidate.task_id,
            investigation_id=candidate.investigation_id,
            candidate_id=candidate.candidate_id,
            candidate_hash=candidate.input_hash,
            decision=decision,
            reason_codes=tuple(sorted(reasons)),
            limitations=tuple(limitations),
            policy_version=self.policy_version,
            policy_hash=self.policy_hash(),
            resolved_provenance=provenance,
            input_hash=input_hash,
        )


class GraphAdmissionDecisionV1(BaseModel):
    """§15 immutable admission decision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_version: str = "graph-admission-decision:v1"

    decision_id: str
    task_id: str
    investigation_id: str

    candidate_id: str
    candidate_hash: str

    decision: GraphAdmissionDecision

    reason_codes: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    policy_version: str
    policy_hash: str

    resolved_provenance: dict

    input_hash: str

    def to_row(self) -> dict:
        return {
            "decision_id": self.decision_id,
            "candidate_id": self.candidate_id,
            "candidate_hash": self.candidate_hash,
            "decision": self.decision.value,
            "reason_codes": tuple(self.reason_codes),
            "limitations": tuple(self.limitations),
            "policy_version": self.policy_version,
            "policy_hash": self.policy_hash,
            "resolved_provenance": dict(self.resolved_provenance),
            "input_hash": self.input_hash,
        }


# ---------------------------------------------------------------------------
# §50 read-side contract stubs — frozen now, implemented in P6B
# ---------------------------------------------------------------------------


class GraphReaderMode(str, enum.Enum):
    """§51 frozen retrieval modes: report mode NEVER sees review_pending
    semantic context; investigation mode sees verified review_pending
    clearly marked unconfirmed."""

    INVESTIGATION = "investigation"
    REPORT = "report"


def retrieval_eligible(review_status: Optional[str], mode: GraphReaderMode,
                       *, verified: bool = False) -> bool:
    """§51 policy classification helper (frozen semantics, P6B executes
    the filtering)."""
    if review_status == "accepted":
        return True
    if review_status == "review_pending":
        return mode is GraphReaderMode.INVESTIGATION and verified
    # rejected / unknown / ungrounded: never retrieval-eligible in any mode
    return False


class GraphProvenanceEnvelope(BaseModel):
    """§52: every graph object must map back to its materialization and
    canonical provenance. P6B readers refuse envelopes without one."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    materialization_id: str
    episode_id: str
    candidate_id: str
    admission_decision_id: str
    evidence_refs: tuple[str, ...] = ()
    finding_refs: tuple[str, ...] = ()
    correlation_refs: tuple[str, ...] = ()
    review_status: Optional[str] = None


__all__ = [
    "DEFAULT_MAX_ACTIVE_MATERIALIZATIONS",
    "GRAPH_ADMISSION_POLICY_VERSION",
    "GraphAdmissionDecision",
    "GraphAdmissionDecisionV1",
    "GraphAdmissionPolicy",
    "GraphBudgetPolicy",
    "GraphBudgetState",
    "GraphProvenanceEnvelope",
    "GraphReaderMode",
    "ReasonCode",
    "retrieval_eligible",
]
