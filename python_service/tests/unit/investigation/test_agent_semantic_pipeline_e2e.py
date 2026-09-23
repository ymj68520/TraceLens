"""P5B §68-§72: end-to-end offline semantic claim pipeline, high-risk
downgrade, contradiction, and the closure/finalization boundaries."""

import pytest

from httpserver.services.investigation.agent_assertion_policy import (
    AssertionPolicy,
    AssertionSemanticType,
    VerificationAvailability,
)
from httpserver.services.investigation.agent_claims import ProposedClaimV1
from httpserver.services.investigation.agent_findings import (
    finding_from_disposition,
)
from httpserver.services.investigation.agent_grounding import (
    DeterministicGroundingValidator,
    GroundingStatus,
    EvidenceRefPolicy,
)
from httpserver.services.investigation.agent_support_bundle import (
    SupportBundleBuilder,
)
from httpserver.services.investigation.agent_verification import (
    FinalSemanticReviewContextV1,
    FinalSemanticReviewOutputV1,
    FinalSemanticReviewValidator,
    SemanticVerificationMode,
    SemanticVerificationStatus,
    SemanticVerifierAgent,
    VerifierFailureCode,
    process_claim_verification,
)
from httpserver.services.investigation.agent_specialist_result import (
    AssertionClass,
)

TASK_ID = "task-A"
INVESTIGATION_ID = "inv-" + "e" * 8

_RESOLVABLE = {"file:C/a.doc", "file:C/b.doc"}


async def _resolver(task_id, ref):
    return {"source_mtime": 1} if ref in _RESOLVABLE else None


def _proposal(assertion=AssertionClass.INFERENCE, text="logon cluster "
              "indicates shared use", refs=("file:C/a.doc",)):
    return ProposedClaimV1(
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        proposal_id="",
        text=text,
        assertion_class=assertion,
        evidence_refs=refs,
        input_hash="",
    )


def _repo(tmp_path):
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
                objective="e2e",
            )
        ),
        investigation_id=INVESTIGATION_ID,
    )
    return repo


async def _ground_and_bundle(repo, proposal):
    grounding = await DeterministicGroundingValidator(
        policy=EvidenceRefPolicy()
    ).validate(
        proposal,
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        allowed_evidence_ids=frozenset(_RESOLVABLE),
        evidence_resolver=_resolver,
    )
    repo.record_claim_proposals(INVESTIGATION_ID, [proposal.to_row()])
    repo.record_grounding_results(
        INVESTIGATION_ID, [{
            "grounding_id": grounding.grounding_id,
            "proposal_id": grounding.proposal_id,
            "grounding_policy_version": 1,
            "input_assertion_class": grounding.input_assertion_class.value,
            "effective_assertion_class":
                grounding.effective_assertion_class.value,
            "status": grounding.status.value,
            "valid_evidence_refs": grounding.valid_evidence_refs,
            "invalid_evidence_refs": grounding.invalid_evidence_refs,
            "invisible_evidence_refs": grounding.invisible_evidence_refs,
            "disallowed_ref_types": grounding.disallowed_ref_types,
            "warnings": grounding.warnings,
            "limitations": grounding.limitations,
            "validator_version": grounding.validator_version,
            "input_hash": grounding.input_hash,
        }]
    )
    bundle = await SupportBundleBuilder().build(
        grounding, proposal, task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID, evidence_resolver=_resolver,
    )
    repo.record_support_bundles(INVESTIGATION_ID, [bundle.to_row()])
    return grounding, bundle


def _verifier(status: SemanticVerificationStatus, context):
    """Offline verifier whose TestModel answers with one status and the
    exact frozen identity (a compliant model echoes the context)."""
    from pydantic_ai.models.test import TestModel

    output_args = {
        "result_version": "semantic-verification-result:v1",
        "verification_id": context.verification_id,
        "mode": "claim_sufficiency",
        "task_id": context.task_id,
        "investigation_id": context.investigation_id,
        "proposal_id": context.proposal_id,
        "proposal_hash": context.proposal_hash,
        "support_bundle_id": context.support_bundle_id,
        "support_bundle_hash": context.support_bundle_hash,
        "status": status.value,
        "supported_parts": (
            [] if status is SemanticVerificationStatus.CONTRADICTED
            else ["logon record"]
        ),
        "unsupported_parts": (
            ["intent"] if status is SemanticVerificationStatus.PARTIALLY_SUFFICIENT
            else []
        ),
        "contradicting_evidence_refs": (
            ["file:C/b.doc"]
            if status is SemanticVerificationStatus.CONTRADICTED else []
        ),
        "recommended_assertion_class": "INFERENCE",
    }
    return SemanticVerifierAgent(
        mode=SemanticVerificationMode.claim_sufficiency,
        model=TestModel(custom_output_args=output_args),
        model_name="test-model",
        model_config_hash="cfg",
    )


def _context_for(proposal, grounding, bundle_row):
    from httpserver.services.investigation.agent_verification import (
        build_claim_verification_context,
    )

    return build_claim_verification_context(
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        proposal=proposal,
        grounding=grounding,
        support_bundle_row=bundle_row,
    )


async def test_full_offline_claim_pipeline(tmp_path):
    """§70: candidate -> proposal -> grounding -> bundle -> verifier
    (TestModel) -> verification -> policy -> disposition -> review_pending
    Finding, with provenance complete and zero revision consumption."""
    repo = _repo(tmp_path)
    proposal = _proposal()
    grounding, bundle = await _ground_and_bundle(repo, proposal)
    assert grounding.status is GroundingStatus.GROUNDED

    outcome = await process_claim_verification(
        repo,
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        proposal=proposal,
        grounding=grounding,
        bundle_row=bundle.to_row(),
        semantic_type=AssertionSemanticType.IDENTIFIER_MATCH,
        verifier=_verifier(
            SemanticVerificationStatus.SUFFICIENT,
            _context_for(proposal, grounding, bundle.to_row()),
        ),
    )
    assert outcome["verification_available"] is True
    disposition = outcome["disposition"]
    assert disposition.decision.value == "eligible_review_pending"
    finding = outcome["finding"]
    assert finding is not None
    stored = repo.list_investigation_findings(INVESTIGATION_ID)
    assert len(stored) == 1
    assert stored[0]["status"] == "review_pending"
    # provenance complete: proposal -> grounding -> verification -> finding
    assert stored[0]["proposal_id"] == proposal.proposal_id
    assert stored[0]["grounding_id"] == grounding.grounding_id
    assert stored[0]["semantic_verification_id"] == (
        disposition.verification_id
    )
    # Working State untouched
    assert repo.get_working_state_revision(INVESTIGATION_ID, 2) is None
    # no accepted/rejected anywhere in the pipeline output
    assert stored[0]["status"] not in ("accepted", "rejected")
    kinds = {
        event.event_type.value
        for event in repo.list_trajectory(INVESTIGATION_ID)
    }
    assert "claim_semantic_verified" in kinds
    assert "claim_disposition_recorded" in kinds
    assert "finding_review_pending_created" in kinds


async def test_high_risk_fact_downgraded_by_verifier(tmp_path):
    """§71: FACT 'intentionally exfiltrated' + partially_sufficient can
    never produce a FACT finding - it lands as HYPOTHESIS or is blocked."""
    repo = _repo(tmp_path)
    proposal = _proposal(
        assertion=AssertionClass.FACT,
        text="User intentionally exfiltrated file X",
    )
    grounding, bundle = await _ground_and_bundle(repo, proposal)

    outcome = await process_claim_verification(
        repo,
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        proposal=proposal,
        grounding=grounding,
        bundle_row=bundle.to_row(),
        relation_family=None,  # unclassifiable prose -> UNKNOWN, high-risk
        verifier=_verifier(
            SemanticVerificationStatus.PARTIALLY_SUFFICIENT,
            _context_for(proposal, grounding, bundle.to_row()),
        ),
    )
    finding = outcome["finding"]
    disposition = outcome["disposition"]
    # UNKNOWN type + sufficient-ish verification: the disposition may be
    # eligible only at the conservative ceiling - never FACT
    if finding is not None:
        assert finding.assertion_class is not AssertionClass.FACT
    assert disposition.effective_assertion_class is not AssertionClass.FACT
    findings = repo.list_investigation_findings(INVESTIGATION_ID)
    for row in findings:
        assert row["assertion_class"] != "FACT"


async def test_contradiction_prevents_positive_finding(tmp_path):
    """§72: a contradicted verification produces no positive canonical
    Finding; the P4 Contradiction transition authority is untouched."""
    repo = _repo(tmp_path)
    # the proposal must actually cite the contradicting evidence for the
    # verifier to be allowed to reference it (§10 allowlist rule)
    proposal = _proposal(refs=("file:C/a.doc", "file:C/b.doc"))
    grounding, bundle = await _ground_and_bundle(repo, proposal)
    outcome = await process_claim_verification(
        repo,
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        proposal=proposal,
        grounding=grounding,
        bundle_row=bundle.to_row(),
        semantic_type=AssertionSemanticType.IDENTIFIER_MATCH,
        verifier=_verifier(
            SemanticVerificationStatus.CONTRADICTED,
            _context_for(proposal, grounding, bundle.to_row()),
        ),
    )
    assert outcome["disposition"].decision.value == "contradicted"
    assert outcome["finding"] is None
    assert repo.list_investigation_findings(INVESTIGATION_ID) == []


async def test_verifier_unavailable_never_fabricates_results(tmp_path):
    repo = _repo(tmp_path)
    proposal = _proposal()
    grounding, bundle = await _ground_and_bundle(repo, proposal)
    outcome = await process_claim_verification(
        repo,
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        proposal=proposal,
        grounding=grounding,
        bundle_row=bundle.to_row(),
        semantic_type=AssertionSemanticType.DETERMINISTIC_ARTIFACT_STATEMENT,
        verifier=None,  # required/optional without a runtime -> explicit
    )
    failures = repo.list_semantic_verification_failures(INVESTIGATION_ID)
    # on-demand with no runtime: safe ceiling behavior, no fabricated row
    assert not any(
        row["status"] == "sufficient"
        for row in repo.list_semantic_verifications(INVESTIGATION_ID)
    )
    assert outcome["verification_available"] is False
    assert failures == []


# ---------------------------------------------------------------------------
# §68/§69 closure + finalization boundaries
# ---------------------------------------------------------------------------


def test_final_review_issues_found_requires_issues():
    context = FinalSemanticReviewContextV1(
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        final_state_digest="state-digest",
        required_question_digests=("q:1:answered",),
        mandatory_verification_statuses=("passed",),
    )
    validator = FinalSemanticReviewValidator()
    ok = FinalSemanticReviewOutputV1(
        verification_id=context.verification_id,
        mode=SemanticVerificationMode.finalization_review,
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        status="pass",
        input_hash=context.input_hash,
    )
    assert validator.validate(ok, context=context) == ()
    bad = FinalSemanticReviewOutputV1(
        verification_id=context.verification_id,
        mode=SemanticVerificationMode.finalization_review,
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        status="issues_found",
        issues=(),
        input_hash=context.input_hash,
    )
    assert "FINAL_REVIEW_ISSUES_REQUIRED" in validator.validate(
        bad, context=context
    )
    forged = FinalSemanticReviewOutputV1(
        verification_id="sver-forged",
        mode=SemanticVerificationMode.finalization_review,
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        status="pass",
        input_hash="hash-forged",
    )
    violations = validator.validate(forged, context=context)
    assert "FINAL_REVIEW_IDENTITY_MISMATCH" in violations
    assert "FINAL_REVIEW_INPUT_HASH_MISMATCH" in violations


def test_question_closure_output_is_recommendation_only():
    """§69: the closure review output has NO state-write surface — no
    QuestionTransition, no repo writer; the field itself is a bool."""
    fields = set()
    from httpserver.services.investigation.agent_verification import (
        QuestionClosureReviewV1,
    )

    fields = set(QuestionClosureReviewV1.model_fields)
    assert "closure_supported" in fields
    assert not any("transition" in name for name in fields)
    # runtime context carries no writer either
    import inspect
    import httpserver.services.investigation.agent_verification as mod

    source = inspect.getsource(mod)
    assert "QuestionTransition(" not in source
    assert "commit_working_state" not in source


def test_finalizer_gate_unaffected_by_verifier_pass():
    """§68 hard rule: a verifier 'pass' can never bypass the deterministic
    FinalizationGate - the gate reads state.pending_verifications only,
    and this phase introduces no bypass path (the orchestrator does not
    import the verification module at all)."""
    import inspect
    import httpserver.services.investigation.agent_orchestrator as orch

    source = inspect.getsource(orch)
    assert "agent_verification" not in source
    assert "process_claim_verification" not in source
