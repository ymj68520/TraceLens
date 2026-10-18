"""P5B freeze follow-up F1: mandatory verification lifecycle tests.

The durable obligation - not a Python return value, not process memory -
is what Attention and Finalization read (via the deterministic
projection); the Working State is never written directly by P5."""

import pytest

from httpserver.services.investigation.agent_assertion_policy import (
    AssertionSemanticType,
    VerificationAvailability,
)
from httpserver.services.investigation.agent_attention import AttentionBuilder
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
    SemanticVerificationStatus,
    SemanticVerifierAgent,
    VerifierFailureCode,
    process_claim_verification,
)
from pydantic_ai.models.test import TestModel

TASK_ID = "task-A"
INVESTIGATION_ID = "inv-" + "d" * 8

_RESOLVABLE = {"file:C/a.doc"}


async def _resolver(task_id, ref):
    return {"source_mtime": 1} if ref in _RESOLVABLE else None


def _proposal(assertion=AssertionClass.FACT):
    return ProposedClaimV1(
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        proposal_id="",
        text="user intentionally exfiltrated file X",
        assertion_class=assertion,
        evidence_refs=("file:C/a.doc",),
        input_hash="",
    )


def _grounding(proposal):
    return GroundingResultV1(
        grounding_id="grnd-1",
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        proposal_id=proposal.proposal_id,
        input_assertion_class=proposal.assertion_class,
        effective_assertion_class=proposal.assertion_class,
        status=GroundingStatus.GROUNDED,
        valid_evidence_refs=("file:C/a.doc",),
        validator_version="v",
        input_hash="gh",
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
                objective="f1",
            )
        ),
        investigation_id=INVESTIGATION_ID,
    )
    return repo, db


def _verifier(status, context):
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
        "recommended_assertion_class": "INFERENCE",
    }
    return SemanticVerifierAgent(
        mode=SemanticVerificationMode.claim_sufficiency,
        model=TestModel(custom_output_args=output_args),
        model_name="test-model",
        model_config_hash="cfg",
    )


async def _run_pipeline(repo, verifier=None):
    proposal = _proposal()
    grounding = _grounding(proposal)
    repo.record_claim_proposals(INVESTIGATION_ID, [proposal.to_row()])
    repo.record_grounding_results(INVESTIGATION_ID, [{
        "grounding_id": grounding.grounding_id,
        "proposal_id": grounding.proposal_id,
        "grounding_policy_version": 1,
        "input_assertion_class": grounding.input_assertion_class.value,
        "effective_assertion_class": grounding.effective_assertion_class.value,
        "status": grounding.status.value,
        "valid_evidence_refs": grounding.valid_evidence_refs,
        "invalid_evidence_refs": (),
        "invisible_evidence_refs": (),
        "disallowed_ref_types": (),
        "warnings": (),
        "limitations": (),
        "validator_version": grounding.validator_version,
        "input_hash": grounding.input_hash,
    }])
    return await process_claim_verification(
        repo,
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        proposal=proposal,
        grounding=grounding,
        semantic_type=AssertionSemanticType.CAUSALITY,  # high risk
        verifier=verifier,
    )


def test_semantic_required_preflight_creates_durable_obligation(tmp_path):
    repo, _db = _repo(tmp_path)

    async def main():
        return await _run_pipeline(repo)  # no verifier -> unavailable

    import asyncio

    asyncio.run(main())
    obligations = repo.list_verification_obligations(INVESTIGATION_ID)
    assert len(obligations) == 1
    obligation = obligations[0]
    assert obligation["status"] == "unavailable"
    assert obligation["semantic_type"] == "causality"
    assert obligation["verification_mode"] == "semantic_required"
    assert obligation["obligation_id"].startswith("vob:")
    # deterministic identity fields bound (§4)
    assert obligation["assertion_policy_version"] == "assertion-policy:v1"
    assert obligation["rule_id"].startswith("rule.highrisk")


def test_same_proposal_replay_creates_no_duplicate_obligation(tmp_path):
    repo, _db = _repo(tmp_path)

    async def main():
        await _run_pipeline(repo)
        await _run_pipeline(repo)  # identical inputs -> same obligation id

    import asyncio

    asyncio.run(main())
    obligations = repo.list_verification_obligations(INVESTIGATION_ID)
    assert len(obligations) == 1


def test_pending_obligation_is_attention_p1_blocker(tmp_path):
    repo, _db = _repo(tmp_path)

    async def main():
        await _run_pipeline(repo)

    import asyncio

    asyncio.run(main())
    state = repo.get_working_state_revision(INVESTIGATION_ID, 1).state
    from httpserver.services.investigation.agent_working_state import (
        working_state_from_json,
    )

    parsed = working_state_from_json(TASK_ID, INVESTIGATION_ID, state)
    view = repo.project_verification_obligations(INVESTIGATION_ID, parsed)
    attention = AttentionBuilder().build_full_set(
        view, state_revision=1,
    )
    blockers = [
        item for item in attention.items
        if item.band.value == "p1_correctness_blocker"
        and item.item_id.startswith("verification:")
    ]
    assert blockers, "pending mandatory verification must be a P1 blocker"
    # no verifier runtime was provided, so the obligation lands
    # unavailable - still a P1 blocker (F1 §7)
    assert blockers[0].reason_codes in (
        ("BLOCKING_MANDATORY_VERIFICATION_PENDING",),
        ("MANDATORY_VERIFICATION_UNAVAILABLE",),
    )


def test_pending_obligation_denies_finalization(tmp_path):
    repo, _db = _repo(tmp_path)

    async def main():
        await _run_pipeline(repo)

    import asyncio

    asyncio.run(main())
    from httpserver.services.investigation.agent_finalization import (
        FinalReviewMode,
        FinalSemanticReview,
        FinalSemanticReviewStatus,
        FinalizationRequest,
    )

    proposal = _proposal()
    request = FinalizationRequest(
        investigation_id=INVESTIGATION_ID,
        expected_state_revision=1,
        review_mode=FinalReviewMode.best_effort,
        final_semantic_review=FinalSemanticReview(
            status=FinalSemanticReviewStatus.passed
        ),
        run_id=None,
        requested_by="supervisor",
    )
    latest = repo.get_latest_working_state(INVESTIGATION_ID)
    assert latest.revision == request.expected_state_revision
    decision = repo._repo._gate_or_none() if False else None
    # production path: FinalizationGate via the orchestrator's evaluate
    from httpserver.services.investigation.agent_finalization import (
        FinalizationGate,
    )
    from httpserver.services.investigation.agent_working_state import (
        working_state_from_json,
    )

    state = working_state_from_json(
        TASK_ID, INVESTIGATION_ID, latest.state
    )
    state = repo.project_verification_obligations(
        INVESTIGATION_ID, state
    )
    decision = FinalizationGate().evaluate(
        TASK_ID, state, request,
        _runtime_view(),
    )
    assert decision.outcome.value == "deny"
    assert "MANDATORY_VERIFICATION_BLOCKING" in decision.violation_codes


def _runtime_view():
    from httpserver.services.investigation.agent_finalization import (
        RuntimeFinalizationView,
    )

    return RuntimeFinalizationView(
        investigation_status="active",
        store_ok=True,
    )


async def test_successful_verifier_satisfies_obligation(tmp_path):
    repo, _db = _repo(tmp_path)
    proposal = _proposal()
    grounding = _grounding(proposal)
    repo.record_claim_proposals(INVESTIGATION_ID, [proposal.to_row()])
    repo.record_grounding_results(INVESTIGATION_ID, [{
        "grounding_id": grounding.grounding_id,
        "proposal_id": grounding.proposal_id,
        "grounding_policy_version": 1,
        "input_assertion_class": grounding.input_assertion_class.value,
        "effective_assertion_class": grounding.effective_assertion_class.value,
        "status": grounding.status.value,
        "valid_evidence_refs": grounding.valid_evidence_refs,
        "invalid_evidence_refs": (),
        "invisible_evidence_refs": (),
        "disallowed_ref_types": (),
        "warnings": (),
        "limitations": (),
        "validator_version": grounding.validator_version,
        "input_hash": grounding.input_hash,
    }])
    from httpserver.services.investigation.agent_verification import (
        build_claim_verification_context,
    )

    context = build_claim_verification_context(
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        proposal=proposal,
        grounding=grounding,
    )
    outcome = await process_claim_verification(
        repo,
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        proposal=proposal,
        grounding=grounding,
        semantic_type=AssertionSemanticType.CAUSALITY,
        verifier=_verifier(SemanticVerificationStatus.SUFFICIENT, context),
    )
    obligations = repo.list_verification_obligations(INVESTIGATION_ID)
    assert obligations[0]["status"] == "satisfied"
    assert obligations[0]["verification_id"] is not None
    # satisfied -> no verification blocker in attention
    from httpserver.services.investigation.agent_working_state import (
        working_state_from_json,
    )

    latest = repo.get_latest_working_state(INVESTIGATION_ID)
    parsed = working_state_from_json(
        TASK_ID, INVESTIGATION_ID, latest.state
    )
    view = repo.project_verification_obligations(INVESTIGATION_ID, parsed)
    attention = AttentionBuilder().build_full_set(view, state_revision=1)
    verification_blockers = [
        item for item in attention.items
        if item.item_id.startswith("verification:")
    ]
    assert verification_blockers == []


async def test_provider_failure_keeps_blocker(tmp_path):
    repo, _db = _repo(tmp_path)
    # no verifier runtime: obligation lands unavailable (blocking)
    await _run_pipeline(repo)
    obligation = repo.list_verification_obligations(INVESTIGATION_ID)[0]
    assert obligation["status"] == "unavailable"

    from httpserver.services.investigation.agent_working_state import (
        working_state_from_json,
    )

    latest = repo.get_latest_working_state(INVESTIGATION_ID)
    view = repo.project_verification_obligations(
        INVESTIGATION_ID,
        working_state_from_json(TASK_ID, INVESTIGATION_ID, latest.state),
    )
    attention = AttentionBuilder().build_full_set(view, state_revision=1)
    blockers = [
        item for item in attention.items
        if item.item_id.startswith("verification:")
    ]
    assert blockers, "unavailable mandatory verification stays a blocker"
    assert "MANDATORY_VERIFICATION_UNAVAILABLE" in blockers[0].reason_codes

    # and Finalization DENYs even under best_effort review
    from httpserver.services.investigation.agent_finalization import (
        FinalizationGate,
        FinalReviewMode,
        FinalSemanticReview,
        FinalSemanticReviewStatus,
        FinalizationRequest,
    )

    request = FinalizationRequest(
        investigation_id=INVESTIGATION_ID,
        expected_state_revision=latest.revision,
        review_mode=FinalReviewMode.best_effort,
        final_semantic_review=FinalSemanticReview(
            status=FinalSemanticReviewStatus.passed
        ),
    )
    decision = FinalizationGate().evaluate(
        TASK_ID, view, request, _runtime_view()
    )
    assert decision.outcome.value == "deny"


async def test_safe_downgrade_is_explicit_terminal_nonblocking(tmp_path):
    repo, _db = _repo(tmp_path)
    # high-risk claim, no verifier -> blocked disposition... but a claim
    # the policy caps at HYPOTHESIS anyway resolves safely:
    from httpserver.services.investigation.agent_assertion_policy import (
        AssertionPolicy,
    )

    proposal = _proposal(assertion=AssertionClass.FACT)
    grounding = _grounding(proposal)
    repo.record_claim_proposals(INVESTIGATION_ID, [proposal.to_row()])
    repo.record_grounding_results(INVESTIGATION_ID, [{
        "grounding_id": grounding.grounding_id,
        "proposal_id": grounding.proposal_id,
        "grounding_policy_version": 1,
        "input_assertion_class": grounding.input_assertion_class.value,
        "effective_assertion_class": grounding.effective_assertion_class.value,
        "status": grounding.status.value,
        "valid_evidence_refs": grounding.valid_evidence_refs,
        "invalid_evidence_refs": (),
        "invisible_evidence_refs": (),
        "disallowed_ref_types": (),
        "warnings": (),
        "limitations": (),
        "validator_version": grounding.validator_version,
        "input_hash": grounding.input_hash,
    }])
    policy = AssertionPolicy()
    outcome = await process_claim_verification(
        repo,
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        proposal=proposal,
        grounding=grounding,
        semantic_type=AssertionSemanticType.CAUSALITY,
        verifier=None,
        policy=policy,
    )
    # semantic_required + unavailable -> blocked, obligation stays blocking
    disposition = outcome["disposition"]
    assert disposition.decision.value == "blocked_verification_required"
    obligation = repo.list_verification_obligations(INVESTIGATION_ID)[0]
    assert obligation["status"] == "unavailable"

    # a later safe resolution (registry no longer requires verification)
    # must terminate the obligation explicitly, never delete it
    from httpserver.services.investigation.agent_assertion_policy import (
        AssertionPolicyRegistry,
        VerificationMode,
        _rule,
    )

    relaxed_policy = AssertionPolicy(
        AssertionPolicyRegistry(rules=tuple([
            _rule(
                "rule.causality.relaxed",
                AssertionSemanticType.CAUSALITY,
                VerificationMode.DETERMINISTIC_ONLY,
                AssertionClass.HYPOTHESIS, AssertionClass.INFERENCE,
            ),
        ]))
    )
    outcome2 = await process_claim_verification(
        repo,
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        proposal=proposal,
        grounding=grounding,
        semantic_type=AssertionSemanticType.CAUSALITY,
        verifier=None,
        policy=relaxed_policy,
    )
    assert outcome2["disposition"].decision.value == "downgrade_to_hypothesis"
    obligation = repo.list_verification_obligations(INVESTIGATION_ID)[0]
    assert obligation["status"] == "safely_downgraded"
    assert obligation["disposition_id"] is not None
    # and the projected state no longer blocks finalization
    from httpserver.services.investigation.agent_working_state import (
        working_state_from_json,
    )

    latest = repo.get_latest_working_state(INVESTIGATION_ID)
    view = repo.project_verification_obligations(
        INVESTIGATION_ID,
        working_state_from_json(TASK_ID, INVESTIGATION_ID, latest.state),
    )
    attention = AttentionBuilder().build_full_set(view, state_revision=1)
    assert [
        item for item in attention.items
        if item.item_id.startswith("verification:")
    ] == []


def test_restart_expires_running_obligation_not_deletes_it(tmp_path):
    repo, db = _repo(tmp_path)

    async def main():
        await _run_pipeline(repo)  # obligation -> unavailable
        repo.advance_verification_obligation(
            INVESTIGATION_ID,
            repo.list_verification_obligations(INVESTIGATION_ID)[0][
                "obligation_id"
            ],
            to_status=__import__(
                "httpserver.services.investigation.agent_runtime",
                fromlist=["VerificationObligationStatus"],
            ).VerificationObligationStatus.running,
        )

    import asyncio

    asyncio.run(main())
    assert repo.list_verification_obligations(
        INVESTIGATION_ID, status="running"
    )
    expired = repo.expire_running_verification_obligations()
    assert expired == 1
    obligation = repo.list_verification_obligations(INVESTIGATION_ID)[0]
    assert obligation["status"] == "failed"
    assert obligation["failure_code"] == "runtime_restart"
    # full recovery path also reports it
    recovery = repo.recover_interrupted_agent_runtime()
    assert "obligations_expired" in recovery


def test_working_state_revision_untouched_by_obligations(tmp_path):
    repo, _db = _repo(tmp_path)

    async def main():
        await _run_pipeline(repo)

    import asyncio

    asyncio.run(main())
    assert repo.get_working_state_revision(INVESTIGATION_ID, 1) is not None
    assert repo.get_working_state_revision(INVESTIGATION_ID, 2) is None


def test_no_direct_working_state_bypass_in_p5_modules():
    """F1 §6: agent_verification must never touch the Working State
    writers - the control plane stays the only semantic writer."""
    import inspect
    import httpserver.services.investigation.agent_verification as mod

    source = inspect.getsource(mod)
    assert "commit_working_state" not in source
    assert "pending_verifications=" not in source
