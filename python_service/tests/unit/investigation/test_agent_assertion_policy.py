"""P5B §64 AssertionPolicy tests: conservative defaults, high-risk gating,
no automatic strength increase, deterministic dispositions."""

import pytest

from httpserver.services.investigation.agent_assertion_policy import (
    AssertionPolicy,
    AssertionSemanticType,
    ClaimDecision,
    VerificationAvailability,
    VerificationRequirement,
)
from httpserver.services.investigation.agent_claims import ProposedClaimV1
from httpserver.services.investigation.agent_grounding import (
    GroundingResultV1,
    GroundingStatus,
)
from httpserver.services.investigation.agent_specialist_result import (
    AssertionClass,
)
from httpserver.services.investigation.agent_verification import (
    SemanticVerificationMode,
    SemanticVerificationResultV1,
    SemanticVerificationStatus,
)

TASK_ID = "task-A"
INVESTIGATION_ID = "inv-" + "a" * 8


def _proposal(assertion=AssertionClass.FACT, text="user intentionally "
              "exfiltrated file X"):
    return ProposedClaimV1(
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        proposal_id="",
        text=text,
        assertion_class=assertion,
        evidence_refs=("file:C/a.doc",),
        input_hash="",
    )


def _grounding(status=GroundingStatus.GROUNDED):
    return GroundingResultV1(
        grounding_id=f"grnd-{status.value}",
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        proposal_id="prop-1",
        input_assertion_class=AssertionClass.FACT,
        effective_assertion_class=AssertionClass.FACT,
        status=status,
        valid_evidence_refs=("file:C/a.doc",),
        validator_version="v",
        input_hash="gh",
    )


def _verification(status, recommended=AssertionClass.INFERENCE):
    return SemanticVerificationResultV1(
        verification_id=f"sver-{status.value}",
        mode=SemanticVerificationMode.claim_sufficiency,
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        proposal_id="prop-1",
        proposal_hash="ph",
        support_bundle_id="b",
        support_bundle_hash="bh",
        status=status,
        supported_parts=("logon",),
        recommended_assertion_class=recommended,
        input_hash="vh",
    )


_POLICY = AssertionPolicy()


def test_unknown_type_is_conservative():
    semantic_type = AssertionPolicy.classify()
    assert semantic_type is AssertionSemanticType.UNKNOWN
    assert _POLICY.preflight(semantic_type) is (
        VerificationRequirement.REQUIRED
    )
    disposition = _POLICY.finalize(
        _proposal(), _grounding(), semantic_type=semantic_type,
        verification_availability=VerificationAvailability.UNAVAILABLE,
    )
    assert disposition.decision is ClaimDecision.BLOCKED_VERIFICATION_REQUIRED
    assert disposition.effective_assertion_class is AssertionClass.HYPOTHESIS


def test_high_risk_fact_without_verifier_is_blocked():
    semantic_type = AssertionSemanticType.DATA_EXFILTRATION_CONCLUSION
    assert _POLICY.preflight(semantic_type) is (
        VerificationRequirement.REQUIRED
    )
    disposition = _POLICY.finalize(
        _proposal(assertion=AssertionClass.FACT), _grounding(),
        semantic_type=semantic_type,
        verification_availability=VerificationAvailability.UNAVAILABLE,
    )
    assert disposition.decision is ClaimDecision.BLOCKED_VERIFICATION_REQUIRED


def test_sufficient_verifier_cannot_raise_hypothesis_to_fact():
    semantic_type = AssertionSemanticType.DETERMINISTIC_ARTIFACT_STATEMENT
    disposition = _POLICY.finalize(
        _proposal(assertion=AssertionClass.HYPOTHESIS,
                  text="a small observation"),
        _grounding(), semantic_type=semantic_type,
        verification=_verification(SemanticVerificationStatus.SUFFICIENT),
        verification_availability=VerificationAvailability.AVAILABLE,
    )
    assert disposition.effective_assertion_class is (
        AssertionClass.HYPOTHESIS
    )
    assert disposition.decision is ClaimDecision.ELIGIBLE_REVIEW_PENDING


def test_partially_sufficient_lowers_ceiling():
    semantic_type = AssertionSemanticType.DETERMINISTIC_ARTIFACT_STATEMENT
    disposition = _POLICY.finalize(
        _proposal(assertion=AssertionClass.FACT), _grounding(),
        semantic_type=semantic_type,
        verification=_verification(
            SemanticVerificationStatus.PARTIALLY_SUFFICIENT
        ),
        verification_availability=VerificationAvailability.AVAILABLE,
    )
    assert disposition.decision is ClaimDecision.DOWNGRADE_TO_HYPOTHESIS
    assert disposition.effective_assertion_class is AssertionClass.HYPOTHESIS


def test_insufficient_blocks_strong_claim():
    disposition = _POLICY.finalize(
        _proposal(assertion=AssertionClass.FACT), _grounding(),
        semantic_type=AssertionSemanticType.DETERMINISTIC_ARTIFACT_STATEMENT,
        verification=_verification(SemanticVerificationStatus.INSUFFICIENT),
        verification_availability=VerificationAvailability.AVAILABLE,
    )
    assert disposition.decision is ClaimDecision.INSUFFICIENT


def test_contradicted_prevents_positive_finding():
    disposition = _POLICY.finalize(
        _proposal(), _grounding(),
        semantic_type=AssertionSemanticType.DETERMINISTIC_ARTIFACT_STATEMENT,
        verification=_verification(
            SemanticVerificationStatus.CONTRADICTED,
        ),
        verification_availability=VerificationAvailability.AVAILABLE,
    )
    assert disposition.decision is ClaimDecision.CONTRADICTED
    # the policy never accepts/rejects: only the human does
    assert disposition.decision.value not in ("accepted", "rejected")


def test_indeterminate_prevents_unsupported_fact():
    disposition = _POLICY.finalize(
        _proposal(assertion=AssertionClass.FACT), _grounding(),
        semantic_type=AssertionSemanticType.DETERMINISTIC_ARTIFACT_STATEMENT,
        verification=_verification(SemanticVerificationStatus.INDETERMINATE),
        verification_availability=VerificationAvailability.AVAILABLE,
    )
    assert disposition.decision is ClaimDecision.DOWNGRADE_TO_HYPOTHESIS
    assert disposition.effective_assertion_class is AssertionClass.HYPOTHESIS


def test_provider_unavailable_semantic_required_blocks():
    disposition = _POLICY.finalize(
        _proposal(), _grounding(),
        semantic_type=AssertionSemanticType.SAME_REAL_WORLD_ENTITY,
        verification=None,
        verification_availability=VerificationAvailability.UNAVAILABLE,
    )
    assert disposition.decision is ClaimDecision.BLOCKED_VERIFICATION_REQUIRED


def test_on_demand_unavailable_downgrades_safely():
    # on-demand + verifier absent caps the claim at the rule ceiling:
    # FACT down to INFERENCE stays review_pending at the capped class...
    disposition = _POLICY.finalize(
        _proposal(assertion=AssertionClass.FACT), _grounding(),
        semantic_type=AssertionSemanticType.IDENTIFIER_MATCH,
        verification=None,
        verification_availability=VerificationAvailability.UNAVAILABLE,
    )
    assert disposition.decision is ClaimDecision.ELIGIBLE_REVIEW_PENDING
    assert disposition.effective_assertion_class is AssertionClass.INFERENCE
    # ...while a type whose unverified ceiling is HYPOTHESIS lands there
    disposition = _POLICY.finalize(
        _proposal(assertion=AssertionClass.FACT), _grounding(),
        semantic_type=AssertionSemanticType.TEMPORAL_RELATION,
        verification=None,
        verification_availability=VerificationAvailability.UNAVAILABLE,
    )
    assert disposition.decision is ClaimDecision.DOWNGRADE_TO_HYPOTHESIS
    assert disposition.effective_assertion_class is AssertionClass.HYPOTHESIS


def test_deterministic_only_low_risk_proceeds_without_verifier():
    semantic_type = AssertionSemanticType.DETERMINISTIC_ARTIFACT_STATEMENT
    assert _POLICY.preflight(semantic_type) is (
        VerificationRequirement.NOT_REQUIRED
    )
    disposition = _POLICY.finalize(
        _proposal(assertion=AssertionClass.INFERENCE, text="same sha256"),
        _grounding(), semantic_type=semantic_type,
        verification_availability=VerificationAvailability.UNAVAILABLE,
    )
    assert disposition.decision is ClaimDecision.ELIGIBLE_REVIEW_PENDING
    assert disposition.effective_assertion_class is (
        AssertionClass.INFERENCE
    )


def test_ungrounded_grounding_cannot_canonicalize():
    disposition = _POLICY.finalize(
        _proposal(), _grounding(GroundingStatus.UNGROUNDED),
        semantic_type=AssertionSemanticType.DETERMINISTIC_ARTIFACT_STATEMENT,
        verification_availability=VerificationAvailability.UNAVAILABLE,
    )
    assert disposition.decision is ClaimDecision.INSUFFICIENT


def test_invalid_grounding_is_invalid():
    disposition = _POLICY.finalize(
        _proposal(), _grounding(GroundingStatus.INVALID),
        semantic_type=AssertionSemanticType.DETERMINISTIC_ARTIFACT_STATEMENT,
        verification_availability=VerificationAvailability.UNAVAILABLE,
    )
    assert disposition.decision is ClaimDecision.INVALID


def test_same_inputs_and_registry_are_deterministic():
    kwargs = dict(
        semantic_type=AssertionSemanticType.DETERMINISTIC_ARTIFACT_STATEMENT,
        verification_availability=VerificationAvailability.UNAVAILABLE,
    )
    first = _POLICY.finalize(_proposal(), _grounding(), **kwargs)
    second = _POLICY.finalize(_proposal(), _grounding(), **kwargs)
    assert first.disposition_id == second.disposition_id
    assert first.input_hash == second.input_hash
    assert first.policy_registry_hash == _POLICY.registry_hash()


def test_registry_change_changes_disposition():
    from httpserver.services.investigation.agent_assertion_policy import (
        AssertionPolicyRegistry,
        AssertionRule,
        VerificationMode,
    )

    kwargs = dict(
        semantic_type=AssertionSemanticType.DETERMINISTIC_ARTIFACT_STATEMENT,
        verification_availability=VerificationAvailability.UNAVAILABLE,
    )
    proposal, grounding = _proposal(), _grounding()
    starter = AssertionPolicy().finalize(proposal, grounding, **kwargs)
    from httpserver.services.investigation.agent_assertion_policy import (
        _rule,
    )

    hardened = AssertionPolicy(
        AssertionPolicyRegistry(rules=tuple([
            _rule(
                "rule.deterministic_artifact_statement",
                AssertionSemanticType.DETERMINISTIC_ARTIFACT_STATEMENT,
                VerificationMode.SEMANTIC_REQUIRED,
                AssertionClass.HYPOTHESIS, AssertionClass.INFERENCE,
                high_risk=True,
            ),
        ]))
    )
    changed = hardened.finalize(proposal, grounding, **kwargs)
    assert starter.policy_registry_hash != changed.policy_registry_hash
    assert starter.disposition_id != changed.disposition_id
    assert changed.decision is ClaimDecision.BLOCKED_VERIFICATION_REQUIRED


def test_disposition_persistence_idempotent(tmp_path):
    from httpserver.services.investigation.agent_runtime import (
        AgentRuntimeRepository,
    )
    from httpserver.services.investigation.agent_working_state import (
        AgentWorkingStateV1,
        working_state_to_json,
    )
    from httpserver.services.investigation.repository import (
        InvestigationRepository,
    )

    db = tmp_path / "investigation.db"
    repo = AgentRuntimeRepository(InvestigationRepository(db, TASK_ID))
    repo.create_investigation(
        working_state_to_json(
            AgentWorkingStateV1(
                task_id=TASK_ID, investigation_id=INVESTIGATION_ID,
                objective="disp",
            )
        ),
        investigation_id=INVESTIGATION_ID,
    )
    disposition = _POLICY.finalize(
        _proposal(), _grounding(),
        semantic_type=AssertionSemanticType.DETERMINISTIC_ARTIFACT_STATEMENT,
        verification_availability=VerificationAvailability.UNAVAILABLE,
    )
    first = repo.record_claim_dispositions(
        INVESTIGATION_ID, [disposition.to_row()]
    )
    assert first["inserted_count"] == 1
    second = repo.record_claim_dispositions(
        INVESTIGATION_ID, [disposition.to_row()]
    )
    assert second["inserted_count"] == 0
    stored = repo.list_claim_dispositions(INVESTIGATION_ID)
    assert len(stored) == 1
    assert stored[0]["decision"] == disposition.decision.value
    events = repo.list_trajectory(INVESTIGATION_ID)
    recorded = [
        event for event in events
        if event.event_type.value == "claim_disposition_recorded"
    ]
    assert recorded and "decision" not in recorded[0].payload
