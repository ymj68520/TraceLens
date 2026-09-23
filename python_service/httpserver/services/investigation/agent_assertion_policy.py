"""Deterministic AssertionPolicy (P5B §26-§33, §48, §54-§58, §64).

The policy is NOT an agent and does no case-semantics reasoning. It only:

    enforces ceilings, downgrades, blocks, denies canonical publication,
    and requires verification

exactly as its versioned starter registry says.  The exact
deterministic_only / semantic_required / semantic_on_demand taxonomy is
TBD in the architecture: this registry is a conservative, versioned,
P8-calibratable STARTER, explicitly not a permanently frozen taxonomy
(§27/§56/§12-of-docs).

Two-stage flow (§55):

    AssertionPolicy.preflight(proposal, grounding) -> VerificationRequirement
    [ SemanticVerifier runs only if required/optional and available ]
    AssertionPolicy.finalize(proposal, grounding, verification) -> disposition

Conservative defaults (§28/§57): an unknown semantic type is
semantic_required with an unverified ceiling of HYPOTHESIS - never
deterministic_only, never FACT.  A verifier can never raise strength
(§33): the proposal's own assertion class is part of the ceiling, so
"sufficient" preserves at most the requested class and never upgrades
HYPOTHESIS -> FACT.  Provider failure (§48) is a runtime fact: for
semantic_required claims it BLOCKS (never lowers the verification
standard to keep a strong finding).
"""

from __future__ import annotations

import hashlib
import enum
from typing import Optional

from pydantic import BaseModel, ConfigDict

from .agent_claims import ProposedClaimV1
from .agent_grounding import GroundingResultV1, GroundingStatus
from .agent_runtime import canonical_state_json
from .agent_specialist_result import AssertionClass
from .agent_verification import (
    SemanticVerificationResultV1,
    SemanticVerificationStatus,
)

ASSERTION_POLICY_VERSION = "assertion-policy:v1"

_ASSERTION_RANK = {
    AssertionClass.HYPOTHESIS: 0,
    AssertionClass.INFERENCE: 1,
    AssertionClass.FACT: 2,
}


def _min_class(left: AssertionClass, right: AssertionClass) -> AssertionClass:
    return left if _ASSERTION_RANK[left] <= _ASSERTION_RANK[right] else right


class VerificationRequirement(str, enum.Enum):
    REQUIRED = "required"
    OPTIONAL = "optional"
    NOT_REQUIRED = "not_required"


class VerificationAvailability(str, enum.Enum):
    """§48: whether the verifier runtime actually produced a result."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class ClaimDecision(str, enum.Enum):
    """§31 disposition vocabulary. accepted/rejected do NOT exist here —
    those belong to the human Analyst Review alone."""

    ELIGIBLE_REVIEW_PENDING = "eligible_review_pending"
    DOWNGRADE_TO_HYPOTHESIS = "downgrade_to_hypothesis"
    INSUFFICIENT = "insufficient"
    CONTRADICTED = "contradicted"
    BLOCKED_VERIFICATION_REQUIRED = "blocked_verification_required"
    INVALID = "invalid"


class AssertionSemanticType(str, enum.Enum):
    """§30 versioned semantic-type starter set. Classification is
    deterministic: typed correlation relation families map explicitly,
    everything else is UNKNOWN and takes the conservative default."""

    DETERMINISTIC_ARTIFACT_STATEMENT = "deterministic_artifact_statement"
    CO_OCCURRENCE = "co_occurrence"
    INFRASTRUCTURE_RELATION = "infrastructure_relation"
    TEMPORAL_RELATION = "temporal_relation"
    IDENTIFIER_MATCH = "identifier_match"
    ACCOUNT_RELATION = "account_relation"

    # §29 high-risk starter set (semantic_required + deterministic ceiling)
    CAUSALITY = "causality"
    ATTACK_CHAIN = "attack_chain"
    ACTOR_ATTRIBUTION = "actor_attribution"
    UNAUTHORIZED_MALICIOUS_INTENT = "unauthorized_malicious_intent"
    SAME_REAL_WORLD_ENTITY = "same_real_world_entity"
    DATA_EXFILTRATION_CONCLUSION = "data_exfiltration_conclusion"
    PERSISTENCE_INTERPRETATION = "persistence_interpretation"
    CREDENTIAL_COMPROMISE = "credential_compromise"
    ANTI_FORENSICS_INTENT = "anti_forensics_intent"
    CROSS_DEVICE_BEHAVIOR_MERGE = "cross_device_behavior_merge"

    UNKNOWN = "unknown"


_RELATION_FAMILY_TO_SEMANTIC_TYPE = {
    "same_content_hash": (
        AssertionSemanticType.DETERMINISTIC_ARTIFACT_STATEMENT
    ),
    "structured_co_occurrence": AssertionSemanticType.CO_OCCURRENCE,
    "url_domain_structure": AssertionSemanticType.INFRASTRUCTURE_RELATION,
    "temporal_overlap": AssertionSemanticType.TEMPORAL_RELATION,
    "normalized_identifier_match": AssertionSemanticType.IDENTIFIER_MATCH,
    "composite_account_match": AssertionSemanticType.ACCOUNT_RELATION,
}


class VerificationMode(str, enum.Enum):
    DETERMINISTIC_ONLY = "deterministic_only"
    SEMANTIC_REQUIRED = "semantic_required"
    SEMANTIC_ON_DEMAND = "semantic_on_demand"


class AssertionRule(BaseModel):
    """§56 versioned policy rule."""

    model_config = ConfigDict(frozen=True)

    rule_id: str
    version: str = "1"
    semantic_type: AssertionSemanticType
    verification_mode: VerificationMode
    max_assertion_without_verification: AssertionClass
    max_assertion_after_sufficient: AssertionClass
    high_risk: bool = False
    limitations: tuple[str, ...] = ()


_CONSERVATIVE_RULE = AssertionRule(
    rule_id="rule.unknown.conservative",
    semantic_type=AssertionSemanticType.UNKNOWN,
    verification_mode=VerificationMode.SEMANTIC_REQUIRED,
    max_assertion_without_verification=AssertionClass.HYPOTHESIS,
    max_assertion_after_sufficient=AssertionClass.INFERENCE,
    high_risk=True,
    limitations=(
        "unknown semantic type: conservative default until the type is "
        "classified by an explicit deterministic rule",
    ),
)


def _rule(
    rule_id, semantic_type, mode, max_unverified, max_sufficient,
    high_risk=False, limitations=(),
) -> AssertionRule:
    return AssertionRule(
        rule_id=rule_id,
        semantic_type=semantic_type,
        verification_mode=mode,
        max_assertion_without_verification=max_unverified,
        max_assertion_after_sufficient=max_sufficient,
        high_risk=high_risk,
        limitations=limitations,
    )


class AssertionPolicyRegistry(BaseModel):
    """Starter registry (§27/§56): versioned, auditable, explicitly NOT
    the permanent exact architecture taxonomy."""

    model_config = ConfigDict(frozen=True)

    policy_version: str = ASSERTION_POLICY_VERSION
    rules: tuple[AssertionRule, ...] = ()
    conservative_rule: AssertionRule = _CONSERVATIVE_RULE

    def rule_for(self, semantic_type: AssertionSemanticType) -> AssertionRule:
        for rule in self.rules:
            if rule.semantic_type is semantic_type:
                return rule
        return self.conservative_rule

    def registry_hash(self) -> str:
        payload = {
            "policy_version": self.policy_version,
            "rules": [rule.model_dump(mode="json") for rule in self.rules],
            "conservative_rule": self.conservative_rule.model_dump(
                mode="json"
            ),
        }
        return hashlib.sha256(
            canonical_state_json(payload).encode("utf-8")
        ).hexdigest()

    @classmethod
    def with_starter_rules(cls) -> "AssertionPolicyRegistry":
        """Starter table: low-risk deterministic artifact statements may go
        without a verifier (INFERENCE cap); on-demand types keep an
        INFERENCE unverified cap with a safe downgrade if the verifier is
        absent; every §29 high-risk type is semantic_required with a
        HYPOTHESIS unverified ceiling. P8 calibrates."""
        return cls(rules=tuple([
            _rule(
                "rule.deterministic_artifact_statement",
                AssertionSemanticType.DETERMINISTIC_ARTIFACT_STATEMENT,
                VerificationMode.DETERMINISTIC_ONLY,
                AssertionClass.INFERENCE, AssertionClass.FACT,
                limitations=("typed digest/artifact equality statements",),
            ),
            _rule(
                "rule.co_occurrence",
                AssertionSemanticType.CO_OCCURRENCE,
                VerificationMode.DETERMINISTIC_ONLY,
                AssertionClass.INFERENCE, AssertionClass.FACT,
                limitations=("artifact-explicit co-recorded values",),
            ),
            _rule(
                "rule.infrastructure_relation",
                AssertionSemanticType.INFRASTRUCTURE_RELATION,
                VerificationMode.DETERMINISTIC_ONLY,
                AssertionClass.INFERENCE, AssertionClass.FACT,
            ),
            _rule(
                "rule.temporal_relation",
                AssertionSemanticType.TEMPORAL_RELATION,
                VerificationMode.SEMANTIC_ON_DEMAND,
                AssertionClass.HYPOTHESIS, AssertionClass.INFERENCE,
                limitations=("temporal proximity is never causal",),
            ),
            _rule(
                "rule.identifier_match",
                AssertionSemanticType.IDENTIFIER_MATCH,
                VerificationMode.SEMANTIC_ON_DEMAND,
                AssertionClass.INFERENCE, AssertionClass.FACT,
            ),
            _rule(
                "rule.account_relation",
                AssertionSemanticType.ACCOUNT_RELATION,
                VerificationMode.SEMANTIC_ON_DEMAND,
                AssertionClass.INFERENCE, AssertionClass.FACT,
                limitations=("never a same-person assertion",),
            ),
            *(
                _rule(
                    f"rule.highrisk.{semantic_type.value}",
                    semantic_type,
                    VerificationMode.SEMANTIC_REQUIRED,
                    AssertionClass.HYPOTHESIS, AssertionClass.INFERENCE,
                    high_risk=True,
                    limitations=("§29 high-risk assertion class",),
                )
                for semantic_type in (
                    AssertionSemanticType.CAUSALITY,
                    AssertionSemanticType.ATTACK_CHAIN,
                    AssertionSemanticType.ACTOR_ATTRIBUTION,
                    AssertionSemanticType.UNAUTHORIZED_MALICIOUS_INTENT,
                    AssertionSemanticType.SAME_REAL_WORLD_ENTITY,
                    AssertionSemanticType.DATA_EXFILTRATION_CONCLUSION,
                    AssertionSemanticType.PERSISTENCE_INTERPRETATION,
                    AssertionSemanticType.CREDENTIAL_COMPROMISE,
                    AssertionSemanticType.ANTI_FORENSICS_INTENT,
                    AssertionSemanticType.CROSS_DEVICE_BEHAVIOR_MERGE,
                )
            ),
        ]))


class ClaimDispositionV1(BaseModel):
    """§31 immutable policy outcome for one claim proposal."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    disposition_version: str = "claim-disposition:v1"

    disposition_id: str
    task_id: str
    investigation_id: str

    proposal_id: str
    proposal_hash: str

    grounding_id: str
    grounding_hash: Optional[str] = None
    verification_id: Optional[str] = None
    verification_hash: Optional[str] = None

    requested_assertion_class: AssertionClass
    effective_assertion_class: AssertionClass

    semantic_type: AssertionSemanticType

    decision: ClaimDecision

    reasons: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    policy_registry_hash: str
    policy_version: str
    rule_id: str

    input_hash: str = ""

    def to_row(self) -> dict:
        return {
            "disposition_id": self.disposition_id,
            "proposal_id": self.proposal_id,
            "proposal_hash": self.proposal_hash,
            "grounding_id": self.grounding_id,
            "grounding_hash": self.grounding_hash,
            "verification_id": self.verification_id,
            "verification_hash": self.verification_hash,
            "requested_assertion_class":
                self.requested_assertion_class.value,
            "effective_assertion_class":
                self.effective_assertion_class.value,
            "semantic_type": self.semantic_type.value,
            "decision": self.decision.value,
            "reasons": tuple(self.reasons),
            "limitations": tuple(self.limitations),
            "policy_registry_hash": self.policy_registry_hash,
            "policy_version": self.policy_version,
            "rule_id": self.rule_id,
            "input_hash": self.input_hash,
        }


class AssertionPolicy:
    """Deterministic two-stage policy authority (§55)."""

    VERSION = ASSERTION_POLICY_VERSION

    def __init__(self, registry: Optional[AssertionPolicyRegistry] = None):
        self._registry = registry or AssertionPolicyRegistry.with_starter_rules()

    @property
    def registry(self) -> AssertionPolicyRegistry:
        return self._registry

    def registry_hash(self) -> str:
        return self._registry.registry_hash()

    @staticmethod
    def classify(
        *,
        relation_family: Optional[str] = None,
        explicit_type: Optional[AssertionSemanticType] = None,
    ) -> AssertionSemanticType:
        """§30 deterministic classification; never LLM-controlled."""
        if explicit_type is not None:
            return explicit_type
        if relation_family is not None:
            mapped = _RELATION_FAMILY_TO_SEMANTIC_TYPE.get(relation_family)
            if mapped is not None:
                return mapped
        return AssertionSemanticType.UNKNOWN

    def preflight(
        self,
        semantic_type: AssertionSemanticType,
    ) -> VerificationRequirement:
        """§54/§55: the policy decides whether verification is needed —
        never the agent itself."""
        rule = self._registry.rule_for(semantic_type)
        if rule.verification_mode is VerificationMode.DETERMINISTIC_ONLY:
            return VerificationRequirement.NOT_REQUIRED
        if rule.verification_mode is VerificationMode.SEMANTIC_REQUIRED:
            return VerificationRequirement.REQUIRED
        return VerificationRequirement.OPTIONAL

    def finalize(
        self,
        proposal: ProposedClaimV1,
        grounding: GroundingResultV1,
        *,
        semantic_type: AssertionSemanticType,
        verification: Optional[SemanticVerificationResultV1] = None,
        verification_availability: VerificationAvailability = (
            VerificationAvailability.UNAVAILABLE
        ),
    ) -> ClaimDispositionV1:
        rule = self._registry.rule_for(semantic_type)
        reasons: list[str] = []
        limitations = list(rule.limitations)
        requested = proposal.assertion_class
        verification_id: Optional[str] = None
        verification_hash: Optional[str] = None

        if grounding.status is GroundingStatus.INVALID:
            decision = ClaimDecision.INVALID
            effective = requested
            reasons.append("grounding_invalid")
        elif grounding.status is GroundingStatus.UNGROUNDED:
            decision = ClaimDecision.INSUFFICIENT
            effective = AssertionClass.HYPOTHESIS
            reasons.append("grounding_ungrounded_no_legal_evidence")
        else:
            requirement = self.preflight(semantic_type)
            verified = (
                verification is not None
                and verification_availability
                is VerificationAvailability.AVAILABLE
            )
            if verified:
                verification_id = verification.verification_id
                verification_hash = verification.input_hash
                decision, effective = self._apply_verification(
                    requested, rule, verification, reasons
                )
            elif requirement is VerificationRequirement.REQUIRED:
                # §48: a runtime failure NEVER lowers the verification
                # standard to keep a strong finding — it blocks.
                decision = ClaimDecision.BLOCKED_VERIFICATION_REQUIRED
                effective = AssertionClass.HYPOTHESIS
                reasons.append(
                    "semantic_verification_required_but_unavailable"
                )
            else:
                ceiling = rule.max_assertion_without_verification
                effective = _min_class(requested, ceiling)
                if _ASSERTION_RANK[effective] < _ASSERTION_RANK[requested]:
                    # capped below the request: downgrade_to_hypothesis only
                    # names the HYPOTHESIS landing; a cap to INFERENCE stays
                    # review_pending at the capped class
                    if effective is AssertionClass.HYPOTHESIS:
                        decision = ClaimDecision.DOWNGRADE_TO_HYPOTHESIS
                    else:
                        decision = ClaimDecision.ELIGIBLE_REVIEW_PENDING
                    reasons.append(
                        "unverified_claim_exceeds_policy_ceiling"
                        if requirement is VerificationRequirement.OPTIONAL
                        else "claim_exceeds_unverified_policy_ceiling"
                    )
                else:
                    decision = ClaimDecision.ELIGIBLE_REVIEW_PENDING
                    reasons.append("within_policy_ceiling")

        limitations.append(
            "policy only enforces ceilings; accepted/rejected belongs to "
            "the human Analyst Review"
        )
        input_payload = {
            "proposal_id": proposal.proposal_id,
            "proposal_hash": proposal.input_hash,
            "grounding_id": grounding.grounding_id,
            "grounding_hash": grounding.input_hash,
            "verification_id": verification_id,
            "verification_hash": verification_hash,
            "requested": requested.value,
            "semantic_type": semantic_type.value,
            "policy_registry_hash": self.registry_hash(),
            "policy_version": self.VERSION,
            "rule_id": rule.rule_id,
        }
        input_hash = hashlib.sha256(
            canonical_state_json(input_payload).encode("utf-8")
        ).hexdigest()
        disposition_id = "disp:" + hashlib.sha256(
            canonical_state_json({**input_payload, "input_hash": input_hash})
            .encode("utf-8")
        ).hexdigest()[:24]
        return ClaimDispositionV1(
            disposition_id=disposition_id,
            task_id=proposal.task_id,
            investigation_id=proposal.investigation_id,
            proposal_id=proposal.proposal_id,
            proposal_hash=proposal.input_hash,
            grounding_id=grounding.grounding_id,
            grounding_hash=grounding.input_hash,
            verification_id=verification_id,
            verification_hash=verification_hash,
            requested_assertion_class=requested,
            effective_assertion_class=effective,
            semantic_type=semantic_type,
            decision=decision,
            reasons=tuple(reasons),
            limitations=tuple(limitations),
            policy_registry_hash=self.registry_hash(),
            policy_version=self.VERSION,
            rule_id=rule.rule_id,
            input_hash=input_hash,
        )

    @staticmethod
    def _apply_verification(
        requested: AssertionClass,
        rule: AssertionRule,
        verification: SemanticVerificationResultV1,
        reasons: list[str],
    ) -> tuple[ClaimDecision, AssertionClass]:
        """§32/§33: verification can preserve (within ceiling) or lower;
        it can NEVER raise above the requested class."""
        status = verification.status
        if status is SemanticVerificationStatus.SUFFICIENT:
            effective = _min_class(
                requested, rule.max_assertion_after_sufficient
            )
            if _ASSERTION_RANK[effective] < _ASSERTION_RANK[requested]:
                return (
                    ClaimDecision.DOWNGRADE_TO_HYPOTHESIS
                    if effective is AssertionClass.HYPOTHESIS
                    else ClaimDecision.ELIGIBLE_REVIEW_PENDING,
                    effective,
                )
            return ClaimDecision.ELIGIBLE_REVIEW_PENDING, effective
        if status is SemanticVerificationStatus.PARTIALLY_SUFFICIENT:
            reasons.append("partially_sufficient_lowers_ceiling")
            return (
                ClaimDecision.DOWNGRADE_TO_HYPOTHESIS,
                AssertionClass.HYPOTHESIS,
            )
        if status is SemanticVerificationStatus.INSUFFICIENT:
            reasons.append("verification_insufficient")
            return ClaimDecision.INSUFFICIENT, AssertionClass.HYPOTHESIS
        if status is SemanticVerificationStatus.CONTRADICTED:
            reasons.append("verification_contradicted")
            return ClaimDecision.CONTRADICTED, AssertionClass.HYPOTHESIS
        reasons.append("verification_indeterminate")
        return (
            ClaimDecision.DOWNGRADE_TO_HYPOTHESIS,
            AssertionClass.HYPOTHESIS,
        )


__all__ = [
    "ASSERTION_POLICY_VERSION",
    "AssertionPolicy",
    "AssertionPolicyRegistry",
    "AssertionRule",
    "AssertionSemanticType",
    "ClaimDecision",
    "ClaimDispositionV1",
    "VerificationAvailability",
    "VerificationMode",
    "VerificationRequirement",
]
