"""Canonical Investigation Findings + Analyst Review handoff (P5B §34-§42,
§59-§60).

A Finding is the Agent pipeline's canonical semantic result — and its
automatic ceiling is exactly ``review_pending`` (§37).  Nothing in the
agent path can ever produce accepted/rejected: the ONLY writer of those
statuses is :class:`FindingReviewService`, a human-only entry point (§38).
Rejected findings are never deleted (§42) — the review history row plus
the guarded state machine keep the audit trail; Working State references
keep their unconfirmed status until an Analyst decides (§41).

Finding persistence consumes zero Working State revision (§45): the state
only changes later through Supervisor Integration -> AddFindingReference
-> StateTransitionPolicy, which stays the sole semantic state writer.
"""

from __future__ import annotations

import hashlib
from typing import Optional

from pydantic import BaseModel, ConfigDict, model_validator

from .agent_assertion_policy import ClaimDecision, ClaimDispositionV1
from .agent_runtime import canonical_state_json
from .agent_specialist_result import AssertionClass

INVESTIGATION_FINDING_VERSION = "investigation-finding:v1"

# the automatic ceiling: the only status the agent pipeline may write
REVIEW_PENDING = "review_pending"
REVIEW_ACCEPTED = "accepted"
REVIEW_REJECTED = "rejected"


class InvestigationFindingV1(BaseModel):
    """One canonical, review-pending semantic finding (§34)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    finding_version: str = INVESTIGATION_FINDING_VERSION

    finding_id: str
    task_id: str
    investigation_id: str

    proposal_id: str
    disposition_id: str

    text: str
    assertion_class: AssertionClass

    evidence_refs: tuple[str, ...] = ()
    relationship_refs: tuple[str, ...] = ()
    temporal_scope: Optional[dict] = None

    grounding_id: str
    semantic_verification_id: Optional[str] = None

    limitations: tuple[str, ...] = ()

    status: str = REVIEW_PENDING

    input_hash: str = ""

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if not isinstance(data, dict):
            return data
        if data.get("status") != REVIEW_PENDING:
            # the pipeline writes exactly one status; everything else is
            # the human review's business (§37)
            raise ValueError(
                "agent pipeline findings are always review_pending"
            )
        payload = {
            "task_id": data.get("task_id"),
            "investigation_id": data.get("investigation_id"),
            "proposal_id": data.get("proposal_id"),
            "disposition_id": data.get("disposition_id"),
            "assertion_class": str(data.get("assertion_class")),
            "text": str(data.get("text") or ""),
        }
        input_hash = hashlib.sha256(
            canonical_state_json(payload).encode("utf-8")
        ).hexdigest()
        data["input_hash"] = input_hash
        # §35 deterministic id: binds investigation/proposal/disposition/
        # effective assertion class, so crash+retry cannot duplicate.
        data["finding_id"] = "finding:" + hashlib.sha256(
            canonical_state_json(
                {**payload, "input_hash": input_hash}
            ).encode("utf-8")
        ).hexdigest()[:24]
        return data

    def to_row(self) -> dict:
        return {
            "finding_id": self.finding_id,
            "proposal_id": self.proposal_id,
            "disposition_id": self.disposition_id,
            "text": self.text,
            "assertion_class": self.assertion_class.value,
            "evidence_refs": tuple(self.evidence_refs),
            "relationship_refs": tuple(self.relationship_refs),
            "temporal_scope": self.temporal_scope,
            "grounding_id": self.grounding_id,
            "semantic_verification_id": self.semantic_verification_id,
            "limitations": tuple(self.limitations),
            "status": self.status,
            "input_hash": self.input_hash,
        }


def finding_from_disposition(
    disposition: ClaimDispositionV1,
    *,
    proposal,
    grounding_id: str,
    semantic_verification_id: Optional[str],
    effective_assertion_class: AssertionClass,
) -> InvestigationFindingV1:
    """Build the review-pending Finding for an eligible disposition.

    ``decision`` is re-checked here: only
    eligible_review_pending / downgrade_to_hypothesis may canonicalize,
    and always as review_pending (§37)."""
    if disposition.decision not in (
        ClaimDecision.ELIGIBLE_REVIEW_PENDING,
        ClaimDecision.DOWNGRADE_TO_HYPOTHESIS,
    ):
        raise ValueError(
            f"disposition {disposition.decision.value} may not produce a "
            "Finding"
        )
    if (
        disposition.decision is ClaimDecision.DOWNGRADE_TO_HYPOTHESIS
        and effective_assertion_class is not AssertionClass.HYPOTHESIS
    ):
        raise ValueError("downgrade disposition must land on HYPOTHESIS")
    return InvestigationFindingV1(
        task_id=disposition.task_id,
        investigation_id=disposition.investigation_id,
        finding_id="",  # derived
        proposal_id=disposition.proposal_id,
        disposition_id=disposition.disposition_id,
        text=proposal.text,
        assertion_class=effective_assertion_class,
        evidence_refs=tuple(proposal.evidence_refs),
        relationship_refs=tuple(proposal.relationship_refs),
        temporal_scope=proposal.temporal_scope,
        grounding_id=grounding_id,
        semantic_verification_id=semantic_verification_id,
        limitations=tuple(proposal.limitations),
        status=REVIEW_PENDING,
        input_hash="",  # derived
    )


class FindingReviewService:
    """§38/§59: the sole accepted/rejected authority for Findings.

    Human-only by construction: every call needs an explicit reviewer, and
    no agent component (verifier, policy, supervisor, specialist,
    correlation agent, orchestrator) imports this module (§60, tested)."""

    def review_finding(
        self,
        runtime,
        *,
        investigation_id: str,
        finding_id: str,
        decision: str,
        reviewer: str,
        note: Optional[str] = None,
    ) -> dict:
        if decision not in (REVIEW_ACCEPTED, REVIEW_REJECTED):
            raise ValueError(
                f"review decision must be accepted/rejected, got {decision!r}"
            )
        if not reviewer or not reviewer.strip():
            raise ValueError("finding review requires an explicit reviewer")
        return runtime.commit_finding_review(
            investigation_id,
            finding_id=finding_id,
            decision=decision,
            reviewer=reviewer.strip(),
            note=note,
        )


__all__ = [
    "INVESTIGATION_FINDING_VERSION",
    "FindingReviewService",
    "InvestigationFindingV1",
    "REVIEW_ACCEPTED",
    "REVIEW_PENDING",
    "REVIEW_REJECTED",
    "finding_from_disposition",
]
