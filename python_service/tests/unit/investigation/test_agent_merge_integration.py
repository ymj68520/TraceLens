"""P4B-2 tests: MergeGuard (§38), FailureDigest, IntegrationContextPack (§39),
and the integration decision validator (§40)."""

import pytest
from pydantic import ValidationError

from httpserver.services.investigation.agent_integration import (
    FailureDigest,
    FreshResultEnvelope,
    FrozenDelegationDependencies,
    IntegrationContextPack,
    IntegrationDecisionValidator,
    IntegrationViolationCode,
    MergeGuard,
    P4B_ALLOWED_TRANSITION_TYPES,
    StaleResultDigest,
    SupervisorIntegrationDecisionV1,
    build_integration_context,
)
from httpserver.services.investigation.agent_specialist_result import (
    AssertionClass,
    SpecialistClaimCandidate,
    SpecialistResultV1,
)
from httpserver.services.investigation.agent_transitions import (
    AddEntityReference,
    AddFindingReference,
    AddPendingProposalReference,
    CoverageTransition,
    CreateQuestion,
    CreateHypothesis,
    ModifyScope,
    QuestionTransition,
)
from httpserver.services.investigation.agent_working_state import (
    AgentWorkingStateV1,
    CoverageDimension,
    CoverageStatus,
    Hypothesis,
    HypothesisStatus,
    QuestionPriority,
    QuestionSource,
    QuestionStatus,
    WorkingQuestion,
)

pytestmark = pytest.mark.migration_matrix


def _state(**overrides) -> AgentWorkingStateV1:
    question = WorkingQuestion(
        question_id="q-1",
        text="unauthorized logons?",
        source=QuestionSource.charter,
        priority=QuestionPriority.required,
    )
    fields = dict(
        task_id="task-A",
        investigation_id="inv-A",
        questions=(question,),
    )
    fields.update(overrides)
    return AgentWorkingStateV1(**fields)


def _deps(**overrides) -> FrozenDelegationDependencies:
    fields = dict(
        delegation_id="deleg-A",
        question_id="q-1",
        source_scope_ids=("windows",),
        based_on_state_revision=7,
        evidence_refs=("file:C/observed.doc",),
    )
    fields.update(overrides)
    return FrozenDelegationDependencies(**fields)


# ---------------------------------------------------------------------------
# §38 MergeGuard matrix — the key rule: old revision alone is NEVER stale
# ---------------------------------------------------------------------------


def test_old_revision_with_unchanged_dependencies_is_fresh():
    verdict = MergeGuard().evaluate(
        _deps(based_on_state_revision=7),
        current_state=_state(),
        current_state_revision=10,  # N+3 while the delegation ran
    )
    assert verdict.fresh
    assert verdict.reason_codes == ()


def test_question_answered_is_stale():
    answered = _state().questions[0].model_copy(
        update={"status": QuestionStatus.answered}
    )
    verdict = MergeGuard().evaluate(
        _deps(),
        current_state=_state(questions=(answered,)),
        current_state_revision=8,
    )
    assert verdict.stale
    assert "MERGE_STALE_QUESTION_INACTIVE" in verdict.reason_codes


def test_question_unknown_is_stale():
    verdict = MergeGuard().evaluate(
        _deps(question_id="q-ghost"),
        current_state=_state(),
        current_state_revision=8,
    )
    assert verdict.stale
    assert "MERGE_STALE_QUESTION_UNKNOWN" in verdict.reason_codes


def test_bound_source_scope_revoked_is_stale():
    verdict = MergeGuard().evaluate(
        _deps(),
        current_state=_state(),
        current_state_revision=8,
        granted_scope_ids=("linux",),  # windows revoked
    )
    assert verdict.stale
    assert "MERGE_STALE_SOURCE_SCOPE_CHANGED" in verdict.reason_codes


def test_unrelated_scope_added_stays_fresh():
    verdict = MergeGuard().evaluate(
        _deps(),
        current_state=_state(),
        current_state_revision=8,
        granted_scope_ids=("windows", "linux"),  # scope added, none revoked
    )
    assert verdict.fresh


def test_referenced_evidence_invalidated_is_stale():
    guard = MergeGuard(
        evidence_invalidation_checker=lambda ref: ref == "file:C/observed.doc"
    )
    verdict = guard.evaluate(
        _deps(),
        current_state=_state(),
        current_state_revision=8,
        granted_scope_ids=("windows",),
    )
    assert verdict.stale
    assert "MERGE_STALE_EVIDENCE_INVALIDATED" in verdict.reason_codes


def test_bound_directive_changed_is_stale_but_new_directive_is_not():
    deps = _deps(directive_digests=("digest-orig",))
    changed = MergeGuard().evaluate(
        deps,
        current_state=_state(),
        current_state_revision=8,
        current_directive_digests={"d1": "digest-CHANGED"},
    )
    _ = changed
    assert changed.stale
    assert "MERGE_STALE_DIRECTIVE_CHANGED" in changed.reason_codes

    fresh_with_new_directive = MergeGuard().evaluate(
        deps,
        current_state=_state(),
        current_state_revision=8,
        current_directive_digests={
            "d1": "digest-orig",
            "d2": "digest-new-unrelated",
        },
    )
    assert fresh_with_new_directive.fresh


def test_bound_hypothesis_rejected_is_stale():
    hypothesis = Hypothesis(
        hypothesis_id="h-1",
        text="insider involvement",
        status=HypothesisStatus.rejected,
    )
    verdict = MergeGuard().evaluate(
        _deps(hypothesis_refs=("h-1",)),
        current_state=_state(hypotheses=(hypothesis,)),
        current_state_revision=8,
    )
    assert verdict.stale
    assert "MERGE_STALE_ASSUMPTION_INVALIDATED" in verdict.reason_codes


def test_failure_digest_is_not_evidence():
    digest = FailureDigest(
        delegation_id="deleg-B",
        question_id="q-2",
        terminal_status="failed",
        failure_code="agent_billing_unavailable",
        failure_summary="provider returned billing/402",
    )
    serialized = digest.model_dump()
    # a runtime failure never masquerades as an evidence statement
    assert "evidence" not in str(serialized).lower().replace(
        "evidence absence", ""
    )
    assert digest.terminal_status == "failed"


# ---------------------------------------------------------------------------
# §39 IntegrationContextPack
# ---------------------------------------------------------------------------


def _result(ref="file:C/logon.doc") -> SpecialistResultV1:
    return SpecialistResultV1(
        delegation_id="deleg-A",
        question_id="q-1",
        summary="findings",
        claim_candidates=(
            SpecialistClaimCandidate(
                candidate_id="c-1",
                text="observed logon",
                assertion_class=AssertionClass.INFERENCE,
                evidence_refs=(ref,),
            ),
        ),
        evidence_refs=(ref,),
    )


def test_integration_context_contents_and_determinism():
    fresh = FreshResultEnvelope(
        delegation_id="deleg-A",
        question_id="q-1",
        source_scope_id="windows",
        result=_result(),
        result_hash="hash-a",
    )
    context = build_integration_context(
        task_id="task-A",
        investigation_id="inv-A",
        run_id="run-A",
        state=_state(),
        state_revision=9,
        state_hash="s-hash",
        fresh_results=[fresh],
        stale_result_digests=[
            StaleResultDigest(
                delegation_id="deleg-S", result_hash="hash-s",
                reason_codes=("MERGE_STALE_QUESTION_INACTIVE",),
            )
        ],
        failure_digests=[
            FailureDigest(
                delegation_id="deleg-B", terminal_status="failed",
                failure_code="agent_timeout",
            )
        ],
        attention_refs=("question:q-1",),
    )
    assert context.input_hash() == build_integration_context(
        task_id="task-A",
        investigation_id="inv-A",
        run_id="run-A",
        state=_state(),
        state_revision=9,
        state_hash="s-hash",
        fresh_results=[fresh],
        stale_result_digests=[
            StaleResultDigest(
                delegation_id="deleg-S", result_hash="hash-s",
                reason_codes=("MERGE_STALE_QUESTION_INACTIVE",),
            )
        ],
        failure_digests=[
            FailureDigest(
                delegation_id="deleg-B", terminal_status="failed",
                failure_code="agent_timeout",
            )
        ],
        attention_refs=("question:q-1",),
    ).input_hash()
    # fresh result included; stale excluded from the semantic set but kept
    # as digest; failure enters as FailureDigest
    assert context.fresh_results[0].result_hash == "hash-a"
    assert context.stale_result_digests[0].delegation_id == "deleg-S"
    assert context.failure_digests[0].failure_code == "agent_timeout"
    assert "question:q-1" in context.state_slice_digests


# ---------------------------------------------------------------------------
# §40 integration decision validator
# ---------------------------------------------------------------------------


def _integration_context() -> IntegrationContextPack:
    fresh = FreshResultEnvelope(
        delegation_id="deleg-A",
        question_id="q-1",
        source_scope_id="windows",
        result=_result(),
        result_hash="hash-a",
    )
    return build_integration_context(
        task_id="task-A",
        investigation_id="inv-A",
        run_id="run-A",
        state=_state(),
        state_revision=9,
        state_hash="s-hash",
        fresh_results=[fresh],
    )


def _integration_decision(context, proposals=(), **overrides):
    fields = dict(
        task_id=context.task_id,
        investigation_id=context.investigation_id,
        run_id=context.run_id,
        based_on_state_revision=context.state_revision,
        based_on_state_hash=context.state_hash,
        source_result_ids=("deleg-A",),
        source_result_hashes=("hash-a",),
        transition_proposals=proposals,
    )
    fields.update(overrides)
    return SupervisorIntegrationDecisionV1(**fields)


def test_valid_typed_transitions_accepted():
    context = _integration_context()
    decision = _integration_decision(
        context,
        proposals=(
            QuestionTransition(
                question_id="q-1",
                to_status=QuestionStatus.in_progress,
            ),
            CreateHypothesis(
                hypothesis=Hypothesis(
                    hypothesis_id="h-9",
                    text="lateral movement suspected",
                    status=HypothesisStatus.active,
                ),
            ),
            AddPendingProposalReference(proposal_ref="deleg-A:c-1"),
        ),
    )
    validation = IntegrationDecisionValidator().validate(context, decision)
    assert validation.valid, validation.codes


def test_generic_or_unknown_payload_rejected():
    context = _integration_context()
    # a JSON-patch style dict is not a typed P2 transition: the decision
    # tuple is typed `tuple[Any, ...]` only because PydanticAI serialises
    # arbitrary structured values, so the validator is the structural gate
    decision = _integration_decision(context, proposals=({"patch": True},))
    validation = IntegrationDecisionValidator().validate(context, decision)
    assert not validation.valid
    assert "INTEGRATION_TRANSITION_TYPE_NOT_ALLOWED" in validation.codes
    decision = _integration_decision(
        context,
        proposals=(QuestionTransition(question_id="q-unknown",
                                      to_status=QuestionStatus.in_progress),),
    )
    validation = IntegrationDecisionValidator().validate(context, decision)
    assert not validation.valid
    assert "INTEGRATION_BASIS_REF_UNKNOWN" in validation.codes


def test_forbidden_p5_transitions_rejected():
    context = _integration_context()
    decision = _integration_decision(
        context,
        proposals=(AddEntityReference(entity_ref="entity:x"),),
    )
    validation = IntegrationDecisionValidator().validate(context, decision)
    assert not validation.valid
    assert "INTEGRATION_TRANSITION_TYPE_NOT_ALLOWED" in validation.codes

    decision2 = _integration_decision(
        context,
        proposals=(AddFindingReference(finding_ref="finding:1"),),
    )
    validation2 = IntegrationDecisionValidator().validate(context, decision2)
    assert not validation2.valid

    decision3 = _integration_decision(
        context,
        proposals=(ModifyScope(scope_patch={"scopes": ["*"]}),),
    )
    validation3 = IntegrationDecisionValidator().validate(context, decision3)
    assert not validation3.valid
    assert "INTEGRATION_SCOPE_MUTATION_FORBIDDEN" in validation3.codes


def test_stale_state_binding_and_hash_mismatch_rejected():
    context = _integration_context()
    decision = _integration_decision(
        context,
        based_on_state_revision=8,
    )
    validation = IntegrationDecisionValidator().validate(context, decision)
    assert not validation.valid
    assert "INTEGRATION_STATE_REVISION_STALE" in validation.codes

    decision2 = _integration_decision(
        context,
        source_result_hashes=("WRONG",),
    )
    validation2 = IntegrationDecisionValidator().validate(context, decision2)
    assert not validation2.valid
    assert "INTEGRATION_SOURCE_RESULT_HASH_MISMATCH" in validation2.codes

    decision3 = _integration_decision(
        context,
        source_result_ids=("deleg-GHOST",),
        source_result_hashes=("hash-ghost",),
    )
    validation3 = IntegrationDecisionValidator().validate(context, decision3)
    assert not validation3.valid
    assert "INTEGRATION_SOURCE_RESULT_UNKNOWN" in validation3.codes


def test_decision_hash_deterministic():
    context = _integration_context()
    decision = _integration_decision(
        context,
        proposals=(
            CoverageTransition(
                dimension_id="authentication",
                to_status=CoverageStatus.in_progress,
            ),
        ),
    )
    assert decision.decision_hash() == decision.decision_hash()
