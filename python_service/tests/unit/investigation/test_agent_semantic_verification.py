"""P5B §17/§63 SemanticVerifier output validation, runtime failure
mapping, persistence atomicity, and the frozen-context boundary."""

import pytest

from httpserver.services.investigation.agent_specialist_result import (
    AssertionClass,
)
from httpserver.services.investigation.agent_verification import (
    SEMANTIC_VERIFICATION_CONTEXT_VERSION,
    SEMANTIC_VERIFICATION_RESULT_VERSION,
    SemanticVerificationContextV1,
    SemanticVerificationMode,
    SemanticVerificationResultV1,
    SemanticVerificationStatus,
    SemanticVerifierAgent,
    SemanticVerifierOutputValidator,
    VerifierFailureCode,
    VerificationViolationCode,
)

TASK_ID = "task-A"
INVESTIGATION_ID = "inv-" + "7" * 8


def _context(**overrides) -> SemanticVerificationContextV1:
    fields = dict(
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        mode=SemanticVerificationMode.claim_sufficiency,
        proposal_id="prop-1",
        proposal_hash="hash-p",
        grounding_id="grnd-1",
        grounding_status="grounded",
        support_bundle_id="bundle-1",
        support_bundle_hash="hash-b",
        evidence_allowlist=("file:C/a.doc", "file:C/b.doc"),
        effective_assertion_class=AssertionClass.INFERENCE,
        claim_text="a finding",
    )
    fields.update(overrides)
    return SemanticVerificationContextV1(**fields)


def _result(context: SemanticVerificationContextV1, **overrides):
    fields = dict(
        verification_id=context.verification_id,
        mode=context.mode,
        task_id=context.task_id,
        investigation_id=context.investigation_id,
        proposal_id=context.proposal_id,
        proposal_hash=context.proposal_hash,
        support_bundle_id=context.support_bundle_id,
        support_bundle_hash=context.support_bundle_hash,
        status=SemanticVerificationStatus.SUFFICIENT,
        supported_parts=("logon record",),
        recommended_assertion_class=AssertionClass.INFERENCE,
        input_hash=context.input_hash,
    )
    fields.update(overrides)
    return SemanticVerificationResultV1(**fields)


def _validator():
    return SemanticVerifierOutputValidator()


def test_valid_output_passes():
    context = _context()
    violations = _validator().validate(_result(context), context=context)
    assert violations == ()


def test_identity_proposal_bundle_mode_mismatches_rejected():
    context = _context()
    tampered = _result(context, verification_id="sver-other")
    assert (
        VerificationViolationCode.VERIFICATION_IDENTITY_MISMATCH
        in _validator().validate(tampered, context=context)
    )
    tampered = _result(context, proposal_hash="hash-other")
    assert (
        VerificationViolationCode.VERIFICATION_PROPOSAL_MISMATCH
        in _validator().validate(tampered, context=context)
    )
    tampered = _result(context, support_bundle_hash="hash-other")
    assert (
        VerificationViolationCode.VERIFICATION_BUNDLE_MISMATCH
        in _validator().validate(tampered, context=context)
    )
    tampered = _result(
        context, mode=SemanticVerificationMode.question_closure
    )
    assert (
        VerificationViolationCode.VERIFICATION_MODE_MISMATCH
        in _validator().validate(tampered, context=context)
    )


def test_contradicted_requires_refs():
    context = _context()
    violations = _validator().validate(
        _result(context, status=SemanticVerificationStatus.CONTRADICTED),
        context=context,
    )
    assert (
        VerificationViolationCode.VERIFICATION_CONTRADICTED_WITHOUT_REFS
        in violations
    )


def test_partially_sufficient_requires_unsupported_parts():
    context = _context()
    violations = _validator().validate(
        _result(
            context,
            status=SemanticVerificationStatus.PARTIALLY_SUFFICIENT,
        ),
        context=context,
    )
    assert (
        VerificationViolationCode.VERIFICATION_PARTIAL_WITHOUT_UNSUPPORTED
        in violations
    )


def test_out_of_bundle_evidence_ref_is_invalid_even_if_real():
    context = _context()
    violations = _validator().validate(
        _result(
            context,
            status=SemanticVerificationStatus.CONTRADICTED,
            contradicting_evidence_refs=("file:C/never-exposed.doc",),
        ),
        context=context,
    )
    assert (
        VerificationViolationCode.VERIFICATION_EVIDENCE_REF_OUTSIDE_BUNDLE
        in violations
    )
    # an in-bundle contradicting ref is fine
    ok = _validator().validate(
        _result(
            context,
            status=SemanticVerificationStatus.CONTRADICTED,
            contradicting_evidence_refs=("file:C/b.doc",),
        ),
        context=context,
    )
    assert ok == ()


def test_no_confidence_and_no_disposition_fields_exist():
    """§63: the frozen result contract has no numeric confidence and no
    accepted/rejected field — structurally impossible to emit."""
    fields = set(SemanticVerificationResultV1.model_fields)
    assert not any("confidence" in name for name in fields)
    assert "accepted" not in fields and "rejected" not in fields
    assert "decision" not in fields
    assert fields >= {
        "supported_parts", "unsupported_parts",
        "contradicting_evidence_refs", "alternative_explanations",
        "missing_evidence", "recommended_assertion_class",
    }


def test_context_is_frozen_and_deterministic():
    first = _context()
    second = _context()
    assert first.input_hash == second.input_hash
    assert first.verification_id == second.verification_id
    reordered = _context(
        evidence_allowlist=("file:C/b.doc", "file:C/a.doc")
    )
    assert reordered.input_hash == first.input_hash  # set-like canonical
    assert (
        first.context_version == SEMANTIC_VERIFICATION_CONTEXT_VERSION
    )


async def test_verifier_offline_run_binds_runtime_facts():
    """TestModel run: the model output never controls identity/provenance —
    the agent re-binds them from the frozen context and validates."""
    from pydantic_ai.models.test import TestModel

    context = _context()
    output_args = {
        "result_version": SEMANTIC_VERIFICATION_RESULT_VERSION,
        "verification_id": "sver-forged",
        "mode": "claim_sufficiency",
        "task_id": "task-forged",
        "investigation_id": "inv-forged",
        "proposal_id": "prop-forged",
        "proposal_hash": "hash-forged",
        "support_bundle_id": "bundle-forged",
        "support_bundle_hash": "hash-forged",
        "status": "sufficient",
        "supported_parts": ["logon record"],
        "recommended_assertion_class": "INFERENCE",
    }
    agent = SemanticVerifierAgent(
        mode=SemanticVerificationMode.claim_sufficiency,
        model=TestModel(custom_output_args=output_args),
        model_name="test-model",
        model_config_hash="cfg-hash",
    )
    outcome = await agent.run(context)
    assert not isinstance(outcome, object.__class__)  # sanity
    from httpserver.services.investigation.agent_verification import (
        VerifierFailure,
    )

    assert isinstance(outcome, VerifierFailure)
    assert outcome.failure_code is VerifierFailureCode.OUTPUT_INVALID
    assert "VERIFICATION_IDENTITY_MISMATCH" in outcome.detail

    # a compliant TestModel output passes and carries runtime-bound facts
    compliant_args = dict(output_args)
    compliant_args.update({
        "verification_id": context.verification_id,
        "task_id": context.task_id,
        "investigation_id": context.investigation_id,
        "proposal_id": context.proposal_id,
        "proposal_hash": context.proposal_hash,
        "support_bundle_id": context.support_bundle_id,
        "support_bundle_hash": context.support_bundle_hash,
    })
    agent = SemanticVerifierAgent(
        mode=SemanticVerificationMode.claim_sufficiency,
        model=TestModel(custom_output_args=compliant_args),
        model_name="test-model",
        model_config_hash="cfg-hash",
    )
    result = await agent.run(context)
    assert result.status is SemanticVerificationStatus.SUFFICIENT
    assert result.verification_id == context.verification_id
    assert result.proposal_id == context.proposal_id
    assert result.model == "test-model"
    assert result.model_config_hash == "cfg-hash"


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
                objective="verif",
            )
        ),
        investigation_id=INVESTIGATION_ID,
    )
    return repo


def _verification_row(context, status="sufficient"):
    result = {
        "verification_id": context.verification_id,
        "status": status,
        "supported_parts": ["logon record"],
    }
    return {
        "verification_id": context.verification_id,
        "mode": context.mode.value,
        "proposal_id": context.proposal_id,
        "proposal_hash": context.proposal_hash,
        "grounding_id": context.grounding_id,
        "support_bundle_id": context.support_bundle_id,
        "support_bundle_hash": context.support_bundle_hash,
        "status": status,
        "result": result,
        "recommended_assertion_class": "INFERENCE",
        "model": "test-model",
        "prompt_version": "semantic-verifier:v1",
        "input_hash": context.input_hash,
    }


def test_verification_persistence_atomic_and_idempotent(tmp_path):
    repo = _repo(tmp_path)
    context = _context()
    row = _verification_row(context)
    outcome = repo.record_semantic_verification(
        INVESTIGATION_ID, verification_row=row
    )
    assert outcome["inserted"] is True
    stored = repo.get_semantic_verification(
        INVESTIGATION_ID, context.verification_id
    )
    assert stored["status"] == "sufficient"
    assert stored["result"]["supported_parts"] == ["logon record"]

    replay = repo.record_semantic_verification(
        INVESTIGATION_ID, verification_row=row
    )
    assert replay["inserted"] is False
    assert len(repo.list_semantic_verifications(INVESTIGATION_ID)) == 1

    events = repo.list_trajectory(INVESTIGATION_ID)
    verified = [
        event for event in events
        if event.event_type.value == "claim_semantic_verified"
    ]
    assert len(verified) == 2  # one per record call, audit only
    assert "result" not in verified[0].payload

    # CHECK violation rolls back the whole unit (no trajectory either)
    bad = _verification_row(context)
    bad["verification_id"] = "sver-bad"
    bad["status"] = "0.85_confident"  # not in the frozen vocabulary
    with pytest.raises(Exception):
        repo.record_semantic_verification(
            INVESTIGATION_ID, verification_row=bad
        )
    assert repo.get_semantic_verification(
        INVESTIGATION_ID, "sver-bad"
    ) is None
    kinds = [
        event.payload.get("verification_id")
        for event in repo.list_trajectory(INVESTIGATION_ID)
        if event.event_type.value == "claim_semantic_verified"
    ]
    assert "sver-bad" not in kinds


def test_provider_failure_is_explicit_not_indeterminate(tmp_path):
    repo = _repo(tmp_path)
    context = _context()
    failure = {
        "failure_id": "sverfail-1",
        "mode": context.mode.value,
        "proposal_id": context.proposal_id,
        "failure_code": "provider_unavailable",
        "detail": "connection reset",
        "model": "deepseek",
        "input_hash": context.input_hash,
    }
    outcome = repo.record_semantic_verification_failure(
        INVESTIGATION_ID, failure_row=failure
    )
    assert outcome["inserted"] is True
    failures = repo.list_semantic_verification_failures(INVESTIGATION_ID)
    assert len(failures) == 1
    assert failures[0]["failure_code"] == "provider_unavailable"
    # replay idempotent
    repo.record_semantic_verification_failure(
        INVESTIGATION_ID, failure_row=failure
    )
    assert len(repo.list_semantic_verification_failures(INVESTIGATION_ID)) == 1
