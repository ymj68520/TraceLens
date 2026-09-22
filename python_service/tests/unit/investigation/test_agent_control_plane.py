"""P2-1 control plane tests: AgentWorkingStateV1, StateTransitionPolicy,
AttentionBuilder, NoProgressDetector.

Covers P2 §51 (policy authority), §52 (attention), §53 (no-progress) plus the
typed working state contract.  Everything here is deterministic: no LLM, no
network, no DB writes.
"""

import pytest
from pydantic import ValidationError

from httpserver.services.investigation.agent_attention import (
    AttentionActionType,
    AttentionBand,
    AttentionBuilder,
    AttentionEligibility,
    AttentionPolicyConfig,
    DelegationRuntimeView,
)
from httpserver.services.investigation.agent_progress import (
    NoProgressDetector,
    NoProgressPolicyConfig,
)
from httpserver.services.investigation.agent_transitions import (
    AddEntityReference,
    AddFindingReference,
    AddPendingProposalReference,
    ContradictionStatus,
    ContradictionTransition,
    CoverageStatus,
    CoverageTransition,
    CreateContradiction,
    CreateHypothesis,
    CreateQuestion,
    EvidenceRefStatus,
    EvidenceRelevanceStatus,
    EvidenceRelevanceTransition,
    FindingRefCheck,
    HypothesisStatus,
    HypothesisTransition,
    ModifyScope,
    QUESTION_BLOCKER_REQUIRED,
    QUESTION_CLOSURE_BASIS_REQUIRED,
    QUESTION_CLOSURE_VERIFICATION_REQUIRED,
    QUESTION_DISPOSITION_REQUIRED,
    QUESTION_ILLEGAL_STATUS_TRANSITION,
    QUESTION_NOT_FOUND,
    REQUIRED_QUESTION_CANNOT_DEFER,
    QUESTION_SUPERSESSION_PROVENANCE_REQUIRED,
    CONTRADICTION_REFS_REQUIRED,
    CONTRADICTION_NOT_FOUND,
    CRITICAL_CONTRADICTION_BASIS_REQUIRED,
    COVERAGE_BASIS_REQUIRED,
    COVERAGE_LIMITATION_REQUIRED,
    COVERAGE_UNAVAILABLE_WITHOUT_CAPABILITY_BASIS,
    COVERAGE_NOT_APPLICABLE_BASIS_REQUIRED,
    COVERAGE_DIMENSION_NOT_FOUND,
    EVIDENCE_REF_CROSS_TASK,
    EVIDENCE_REF_INVALID,
    FINDING_REF_NOT_FOUND,
    HYPOTHESIS_NOT_FOUND,
    REVIEW_STATE_NOT_AGENT_WRITABLE,
    SCOPE_MUTATION_NOT_ALLOWED,
    STATE_REVISION_CONFLICT,
    StateTransitionPolicy,
    TransitionBatch,
    TransitionDecisionStatus,
    TransitionPolicyContext,
    QuestionTransition,
)
from httpserver.services.investigation.agent_working_state import (
    AgentWorkingStateV1,
    BudgetState,
    Contradiction,
    ContradictionSeverity,
    CoverageDimension,
    DirectiveDigest,
    EvidenceRelevanceStatus,
    EvidenceWorkingSetItem,
    Hypothesis,
    PendingVerification,
    ProgressState,
    QuestionDisposition,
    QuestionPriority,
    QuestionRelation,
    QuestionRelationType,
    QuestionSource,
    QuestionStatus,
    WorkingQuestion,
    WORKING_STATE_SCHEMA_VERSION,
    working_state_from_json,
    working_state_to_json,
)


# ---------- helpers ----------

def _resolver(status_by_key=None):
    table = status_by_key or {}

    def resolve(key: str) -> EvidenceRefStatus:
        if not key.startswith(("file:/", "cluster:v1:")):
            return EvidenceRefStatus.malformed
        return table.get(key, EvidenceRefStatus.resolved)

    return resolve


def _finding_validator(found_keys=None):
    found = found_keys or {}

    def validate(ref: str) -> FindingRefCheck:
        if ref.startswith("review:"):
            return FindingRefCheck(found=False, kind="review")
        if ref in found:
            return FindingRefCheck(found=True, kind=found[ref])
        return FindingRefCheck(found=False, kind=None)

    return validate


def _ctx(**overrides) -> TransitionPolicyContext:
    kwargs = dict(
        task_id="A",
        investigation_id="inv_x",
        evidence_ref_resolver=_resolver(),
        finding_ref_validator=_finding_validator(),
        verification_checker=lambda question_id: False,
    )
    kwargs.update(overrides)
    return TransitionPolicyContext(**kwargs)


POLICY = StateTransitionPolicy()


def _state(**overrides) -> AgentWorkingStateV1:
    kwargs = dict(task_id="A", investigation_id="inv_x")
    kwargs.update(overrides)
    return AgentWorkingStateV1(**kwargs)


def _eval(state, *transitions, ctx=None):
    return POLICY.evaluate_batch(
        state, TransitionBatch(transitions=list(transitions)), ctx or _ctx()
    )


def _codes(result):
    return [v.code for v in result.violations]


def _required_question(**overrides) -> WorkingQuestion:
    kwargs = dict(
        question_id="Q1",
        text="persistence?",
        source=QuestionSource.charter,
        priority=QuestionPriority.required,
    )
    kwargs.update(overrides)
    return WorkingQuestion(**kwargs)


def _answered_q() -> QuestionTransition:
    return QuestionTransition(
        question_id="Q1",
        to_status=QuestionStatus.answered,
        disposition=QuestionDisposition.supported,
        basis_refs=("file:/a.txt",),
    )


# ---------- working state contract ----------

def test_working_state_v1_version_and_identity():
    state = _state()
    assert state.schema_version == WORKING_STATE_SCHEMA_VERSION == "agent-working-state:v1"
    payload = working_state_to_json(state)
    reloaded = working_state_from_json("A", "inv_x", payload)
    assert reloaded == state
    with pytest.raises(ValueError):
        working_state_from_json("A", "inv_x", {"schema_version": "agent-working-state:v9"})
    with pytest.raises(ValueError):
        working_state_from_json("B", "inv_x", payload)  # identity mismatch


def test_working_state_rejects_broken_relations():
    with pytest.raises(ValidationError):
        _state(questions=(_required_question(relations=(
            QuestionRelation(question_id="Q404", relation_type=QuestionRelationType.blocks),
        )),))


def test_working_state_rejects_duplicate_ids():
    with pytest.raises(ValidationError):
        _state(questions=(
            _required_question(),
            _required_question(),  # duplicate question_id
        ))


def test_working_state_holds_refs_only():
    state = _state(
        questions=(_required_question(),),
        evidence_working_set=(EvidenceWorkingSetItem(
            evidence_key="file:/a.txt",
            status=EvidenceRelevanceStatus.relevant,
            related_question_ids=("Q1",),
        ),),
    )
    blob = repr(working_state_to_json(state))
    # no evidence content fields ever appear in the working state
    assert "llm_summary" not in blob and "snapshot_json" not in blob


# ---------- StateTransitionPolicy (P2 §51) ----------

def test_required_question_cannot_disappear():
    state = _state(questions=(_required_question(),))
    # no delete transition exists in the frozen family: an unknown id is the
    # only "disappearance" vector and is rejected
    result = _eval(
        state, QuestionTransition(question_id="Q404", to_status=QuestionStatus.open)
    )
    assert result.status is TransitionDecisionStatus.rejected
    assert QUESTION_NOT_FOUND in _codes(result)


def test_answered_requires_disposition():
    state = _state(questions=(_required_question(),))
    result = _eval(
        state,
        QuestionTransition(question_id="Q1", to_status=QuestionStatus.answered),
    )
    assert QUESTION_DISPOSITION_REQUIRED in _codes(result)
    assert QUESTION_CLOSURE_BASIS_REQUIRED in _codes(result)


def test_required_question_answer_requires_passed_verification():
    state = _state(questions=(_required_question(),))
    result = _eval(state, _answered_q())
    assert result.status is TransitionDecisionStatus.rejected
    assert QUESTION_CLOSURE_VERIFICATION_REQUIRED in _codes(result)

    passing_ctx = _ctx(verification_checker=lambda q: True)
    ok = POLICY.evaluate_batch(
        state, TransitionBatch(transitions=[_answered_q()]), passing_ctx
    )
    assert ok.status is TransitionDecisionStatus.accepted


def test_required_question_cannot_defer():
    state = _state(questions=(_required_question(),))
    result = _eval(
        state, QuestionTransition(question_id="Q1", to_status=QuestionStatus.deferred)
    )
    assert REQUIRED_QUESTION_CANNOT_DEFER in _codes(result)


def test_unresolved_requires_full_closure_basis():
    state = _state(questions=(_required_question(),))
    result = _eval(
        state, QuestionTransition(question_id="Q1", to_status=QuestionStatus.unresolved)
    )
    assert QUESTION_CLOSURE_BASIS_REQUIRED in _codes(result)
    ok = _eval(
        state,
        QuestionTransition(
            question_id="Q1", to_status=QuestionStatus.unresolved,
            basis_refs=("file:/a.txt",), limitations=("no EVTX logs",),
            investigated_summary="searched event logs",
        ),
    )
    assert ok.status is TransitionDecisionStatus.accepted


def test_blocked_requires_blocker():
    state = _state(questions=(_required_question(),))
    result = _eval(
        state, QuestionTransition(question_id="Q1", to_status=QuestionStatus.blocked)
    )
    assert QUESTION_BLOCKER_REQUIRED in _codes(result)


def test_superseded_requires_provenance():
    state = _state(questions=(_required_question(),))
    result = _eval(
        state, QuestionTransition(question_id="Q1", to_status=QuestionStatus.superseded)
    )
    assert QUESTION_SUPERSESSION_PROVENANCE_REQUIRED in _codes(result)


def test_illegal_question_status_transition():
    state = _state(questions=(_required_question(),))
    answered = _eval(state, _answered_q(), ctx=_ctx(verification_checker=lambda q: True))
    result = _eval(
        answered.new_state,
        QuestionTransition(question_id="Q1", to_status=QuestionStatus.in_progress),
    )
    assert QUESTION_ILLEGAL_STATUS_TRANSITION in _codes(result)


def test_terminal_coverage_requires_basis():
    dimension = CoverageDimension(dimension_id="usb", required=True)
    state = _state(coverage=(dimension,))
    result = _eval(
        state,
        CoverageTransition(dimension_id="usb", to_status=CoverageStatus.covered),
    )
    assert COVERAGE_BASIS_REQUIRED in _codes(result)
    partial = _eval(
        state,
        CoverageTransition(
            dimension_id="usb", to_status=CoverageStatus.partial,
            basis_refs=("file:/a.txt",),
        ),
    )
    assert COVERAGE_LIMITATION_REQUIRED in _codes(partial)
    unavailable = _eval(
        state,
        CoverageTransition(dimension_id="usb", to_status=CoverageStatus.unavailable),
    )
    assert COVERAGE_UNAVAILABLE_WITHOUT_CAPABILITY_BASIS in _codes(unavailable)
    na = _eval(
        state,
        CoverageTransition(
            dimension_id="usb", to_status=CoverageStatus.not_applicable
        ),
    )
    assert COVERAGE_NOT_APPLICABLE_BASIS_REQUIRED in _codes(na)
    ok = _eval(
        state,
        CoverageTransition(
            dimension_id="usb", to_status=CoverageStatus.covered,
            basis_refs=("file:/a.txt",),
        ),
    )
    assert ok.status is TransitionDecisionStatus.accepted


def test_unknown_coverage_dimension_rejected():
    state = _state()
    result = _eval(
        state,
        CoverageTransition(dimension_id="nope", to_status=CoverageStatus.covered),
    )
    assert COVERAGE_DIMENSION_NOT_FOUND in _codes(result)


def test_evidence_refs_must_resolve_in_task():
    state = _state(questions=(_required_question(),))
    resolver = _resolver({"file:/foreign.txt": EvidenceRefStatus.not_found})
    result = POLICY.evaluate_batch(
        state,
        TransitionBatch(transitions=[
            QuestionTransition(
                question_id="Q1", to_status=QuestionStatus.answered,
                disposition=QuestionDisposition.supported,
                basis_refs=("file:/foreign.txt",),
            ),
        ]),
        _ctx(verification_checker=lambda q: True, evidence_ref_resolver=resolver),
    )
    assert EVIDENCE_REF_CROSS_TASK in _codes(result)
    malformed_resolver = _resolver({"file:": EvidenceRefStatus.malformed})
    malformed = POLICY.evaluate_batch(
        state,
        TransitionBatch(transitions=[
            QuestionTransition(
                question_id="Q1", to_status=QuestionStatus.answered,
                disposition=QuestionDisposition.supported,
                basis_refs=("file:",),
            ),
        ]),
        _ctx(verification_checker=lambda q: True, evidence_ref_resolver=malformed_resolver),
    )
    assert EVIDENCE_REF_INVALID in _codes(malformed)


def test_evidence_relevance_transition_resolution():
    state = _state()
    ok = _eval(
        state,
        EvidenceRelevanceTransition(
            evidence_key="file:/a.txt",
            to_status=EvidenceRelevanceStatus.relevant,
        ),
    )
    assert ok.status is TransitionDecisionStatus.accepted
    missing = _eval(
        state,
        EvidenceRelevanceTransition(
            evidence_key="file:/missing.txt",
            to_status=EvidenceRelevanceStatus.relevant,
        ),
        ctx=_ctx(evidence_ref_resolver=_resolver(
            {"file:/missing.txt": EvidenceRefStatus.not_found}
        )),
    )
    assert EVIDENCE_REF_CROSS_TASK in _codes(missing)


def test_hypothesis_never_becomes_finding():
    state = _state(hypotheses=(Hypothesis(
        hypothesis_id="H1", text="usb drop",
        supporting_refs=("file:/a.txt",),
    ),))
    # no hypothesis -> finding transition exists in the frozen family; the
    # only reachable mutations are hypothesis-status ones
    result = _eval(
        state,
        HypothesisTransition(hypothesis_id="H404", to_status=HypothesisStatus.retired),
    )
    assert HYPOTHESIS_NOT_FOUND in _codes(result)
    ok = _eval(
        state,
        HypothesisTransition(hypothesis_id="H1", to_status=HypothesisStatus.supported),
    )
    assert ok.status is TransitionDecisionStatus.accepted
    created = _eval(
        state,
        CreateHypothesis(hypothesis=Hypothesis(
            hypothesis_id="H2", text="dupe check",
        )),
    )
    assert created.status is TransitionDecisionStatus.accepted


def test_critical_contradiction_rules():
    state = _state()
    no_refs = _eval(state, CreateContradiction(contradiction=Contradiction(
        contradiction_id="C1", severity=ContradictionSeverity.critical,
        refs=(),
    )))
    assert CONTRADICTION_REFS_REQUIRED in _codes(no_refs)
    created = _eval(state, CreateContradiction(contradiction=Contradiction(
        contradiction_id="C1", severity=ContradictionSeverity.critical,
        refs=("file:/a.txt", "file:/b.txt"),
    )))
    assert created.status is TransitionDecisionStatus.accepted
    # W8: no delete/reopen transitions exist; unresolved critical requires
    # full resolution basis
    thin = _eval(
        created.new_state,
        ContradictionTransition(
            contradiction_id="C1", to_status=ContradictionStatus.unresolved
        ),
    )
    assert CRITICAL_CONTRADICTION_BASIS_REQUIRED in _codes(thin)
    full = _eval(
        created.new_state,
        ContradictionTransition(
            contradiction_id="C1", to_status=ContradictionStatus.unresolved,
            resolution_basis_refs=("file:/a.txt",),
            attempted_resolution="checked both sources",
            impact="timeline ambiguity", limitation="logs rotated",
        ),
    )
    assert full.status is TransitionDecisionStatus.accepted
    missing = _eval(
        created.new_state,
        ContradictionTransition(
            contradiction_id="C404", to_status=ContradictionStatus.resolved
        ),
    )
    assert CONTRADICTION_NOT_FOUND in _codes(missing)


def test_scope_expansion_rejected():
    result = _eval(_state(), ModifyScope(scope_patch={"time_scope": "all"}))
    assert result.status is TransitionDecisionStatus.rejected
    assert SCOPE_MUTATION_NOT_ALLOWED in _codes(result)


def test_review_state_mutation_rejected():
    result = _eval(_state(), AddFindingReference(finding_ref="review:rev_1"))
    assert REVIEW_STATE_NOT_AGENT_WRITABLE in _codes(result)


def test_finding_ref_must_point_at_canonical_object():
    validator = _finding_validator({"ie_abc": "event", "sa_ok": "analysis"})
    state = _state()
    ok = POLICY.evaluate_batch(
        state,
        TransitionBatch(transitions=[AddFindingReference(finding_ref="ie_abc")]),
        _ctx(finding_ref_validator=validator),
    )
    assert ok.status is TransitionDecisionStatus.accepted
    missing = POLICY.evaluate_batch(
        state,
        TransitionBatch(transitions=[AddFindingReference(finding_ref="ie_404")]),
        _ctx(finding_ref_validator=validator),
    )
    assert FINDING_REF_NOT_FOUND in _codes(missing)
    duplicate = POLICY.evaluate_batch(
        ok.new_state,
        TransitionBatch(transitions=[AddFindingReference(finding_ref="ie_abc")]),
        _ctx(finding_ref_validator=validator),
    )
    assert duplicate.status is TransitionDecisionStatus.noop


def test_atomic_batch_rejection():
    """T1 valid + T2 invalid + T3 valid -> the WHOLE batch is rejected."""
    state = _state(questions=(_required_question(),))
    result = _eval(
        state,
        AddPendingProposalReference(proposal_ref="prop_1"),
        QuestionTransition(question_id="Q404", to_status=QuestionStatus.open),
        AddEntityReference(entity_ref="entity:x"),
    )
    assert result.status is TransitionDecisionStatus.rejected
    assert result.new_state is None
    assert len(result.violations) == 1
    # nothing from the valid transitions leaked
    assert state.pending_proposal_refs == ()


def test_idempotent_duplicate_is_noop():
    question = _required_question()
    state = _state(questions=(question,))
    result = _eval(state, CreateQuestion(question=question))
    assert result.status is TransitionDecisionStatus.noop
    assert result.new_state is None


def test_revision_conflict_code_is_declared():
    # the commit layer owns STATE_REVISION_CONFLICT; the policy module keeps
    # the code in one namespace for the orchestrator to map
    assert STATE_REVISION_CONFLICT == "STATE_REVISION_CONFLICT"


# ---------- AttentionBuilder (P2 §52) ----------

def _attention(state, runtime=None, config=None, revision=7):
    builder = AttentionBuilder()
    return builder.build_full_set(
        state, state_revision=revision,
        runtime=runtime or DelegationRuntimeView(),
        config=config,
    )


def _mk_question(qid, priority, relations=(), status=None, basis=()):
    kwargs = dict(
        question_id=qid, text=f"text {qid}",
        source=QuestionSource.charter, priority=priority,
        relations=relations,
    )
    if status is not None:
        kwargs["status"] = status
    if basis:
        kwargs["basis_refs"] = basis
    return WorkingQuestion(**kwargs)


def test_priority_bands_and_mapping():
    state = _state(
        directive_refs=(DirectiveDigest(directive_ref="dir_1", applied=False),),
        pending_verifications=(PendingVerification(
            verification_id="V1", target_ref="Q404", required=True, blocking=True,
        ),),
        questions=(
            _mk_question("Qreq", QuestionPriority.required),
            _mk_question("Qhigh", QuestionPriority.high),
            _mk_question("Qnorm", QuestionPriority.normal),
            _mk_question("Qexp", QuestionPriority.exploratory, basis=("file:/a",)),
        ),
        coverage=(CoverageDimension(dimension_id="cov_req", required=True),),
        contradictions=(Contradiction(
            contradiction_id="Cmat", severity=ContradictionSeverity.material,
            refs=("file:/a",),
        ),),
    )
    attention = _attention(state)
    bands = {i.item_id: i.band for i in attention.items}
    assert bands["directive:dir_1"] is AttentionBand.p0_control
    assert bands["verification:V1"] is AttentionBand.p1_correctness_blocker
    assert bands["question:Qreq"] is AttentionBand.p2_investigation_obligation
    assert bands["coverage:cov_req"] is AttentionBand.p2_investigation_obligation
    assert bands["question:Qhigh"] is AttentionBand.p3_active_progress
    assert bands["contradiction:Cmat"] is AttentionBand.p3_active_progress
    assert bands["question:Qnorm"] is AttentionBand.p4_supporting_opportunistic
    assert bands["question:Qexp"] is AttentionBand.p5_exploratory


def test_critical_contradiction_and_blocking_verification_share_p1():
    state = _state(
        pending_verifications=(PendingVerification(
            verification_id="V1", target_ref="Q1", required=True, blocking=True,
        ),),
        contradictions=(Contradiction(
            contradiction_id="Ccrit", severity=ContradictionSeverity.critical,
            refs=("file:/a",),
        ),),
    )
    attention = _attention(state)
    p1 = [i for i in attention.items if i.band is AttentionBand.p1_correctness_blocker]
    assert {i.item_id for i in p1} == {
        "verification:V1", "contradiction:Ccrit",
    }
    # calibration boundary: same band, deterministic tie-break by item_id,
    # no architecture-level winner between them
    assert [i.item_id for i in p1] == sorted(i.item_id for i in p1)


def test_refless_exploratory_lead_cannot_enter_attention():
    state = _state(questions=(
        _mk_question("Qexp", QuestionPriority.exploratory),  # no basis refs
    ))
    attention = _attention(state)
    assert all(
        item.intrinsic_priority != QuestionPriority.exploratory
        for item in attention.items
    )
    assert not [i for i in attention.items if i.item_id == "question:Qexp"]


def test_blocks_priority_propagation_only():
    state = _state(questions=(
        _mk_question("Q1", QuestionPriority.required),
        _mk_question("Q9", QuestionPriority.normal, relations=(
            QuestionRelation(question_id="Q1", relation_type=QuestionRelationType.blocks),
        )),
        _mk_question("Q2", QuestionPriority.normal, relations=(
            QuestionRelation(question_id="Q1", relation_type=QuestionRelationType.supports),
        )),
        _mk_question("Q3", QuestionPriority.normal, relations=(
            QuestionRelation(question_id="Q1", relation_type=QuestionRelationType.explores),
        )),
    ))
    attention = _attention(state)
    bands = {i.item_id: i.band for i in attention.items}
    # Q9 blocks required Q1 -> effective band inherited
    assert bands["question:Q9"] is AttentionBand.p2_investigation_obligation
    # supports/explores never propagate
    assert bands["question:Q2"] is AttentionBand.p4_supporting_opportunistic
    assert bands["question:Q3"] is AttentionBand.p4_supporting_opportunistic
    # Q1 itself is blocked while Q9 is open
    q1 = next(i for i in attention.items if i.item_id == "question:Q1")
    assert q1.eligibility is AttentionEligibility.blocked
    assert q1.blocked_by == ("Q9",)


def test_intrinsic_priority_stays_separate_from_effective_band():
    state = _state(questions=(
        _mk_question("Q1", QuestionPriority.required),
        _mk_question("Q9", QuestionPriority.exploratory, basis=("file:/a",), relations=(
            QuestionRelation(question_id="Q1", relation_type=QuestionRelationType.blocks),
        )),
    ))
    attention = _attention(state)
    q9 = next(i for i in attention.items if i.item_id == "question:Q9")
    assert q9.band is AttentionBand.p2_investigation_obligation  # effective
    assert q9.intrinsic_priority is QuestionPriority.exploratory  # intrinsic


def test_deterministic_coalescing_question_and_coverage():
    state = _state(
        questions=(_mk_question("Q7", QuestionPriority.required),),
        coverage=(CoverageDimension(
            dimension_id="persistence", required=True,
            related_question_ids=("Q7",),
        ),),
    )
    attention = _attention(state)
    item_ids = [i.item_id for i in attention.items]
    assert "coverage:persistence" not in item_ids
    assert "question:Q7" in item_ids


def test_verification_coalescing():
    state = _state(
        questions=(_mk_question("Q1", QuestionPriority.high),),
        pending_verifications=(PendingVerification(
            verification_id="V1", target_ref="Q1", required=True, blocking=True,
        ),),
    )
    attention = _attention(state)
    by_id = {i.item_id: i for i in attention.items}
    assert "verification:V1" in by_id  # standalone blocker
    q1 = by_id["question:Q1"]
    assert q1.related_verification_ids == ("V1",)
    assert q1.band is AttentionBand.p1_correctness_blocker  # raised by blocker


def test_same_state_same_attention_set_and_hash():
    state = _state(
        questions=(_mk_question("Q1", QuestionPriority.required),),
        coverage=(CoverageDimension(dimension_id="cov", required=False),),
    )
    first = _attention(state, revision=3)
    second = _attention(state, revision=3)
    other_revision = _attention(state, revision=4)
    assert first == second
    assert first.attention_hash == second.attention_hash
    assert other_revision.attention_hash == first.attention_hash  # content-only hash
    assert other_revision.state_revision == 4


def test_action_types_are_investigation_level_only():
    state = _state(questions=(_mk_question("Q1", QuestionPriority.required),))
    attention = _attention(state)
    allowed = {a.value for i in attention.items for a in i.eligible_action_types}
    assert allowed <= {
        AttentionActionType.delegate_source.value,
        AttentionActionType.delegate_correlation.value,
        AttentionActionType.request_verification.value,
        AttentionActionType.direct_read.value,
        AttentionActionType.create_question.value,
        AttentionActionType.request_finalize.value,
    }
    assert not any("evtx" in a or "prefetch" in a for a in allowed)


def test_window_is_configurable_and_conservative_by_default():
    state = _state(questions=(
        _mk_question("Q1", QuestionPriority.required),
        _mk_question("Q2", QuestionPriority.normal),
        _mk_question("Q3", QuestionPriority.normal),
        _mk_question("Qexp", QuestionPriority.exploratory, basis=("file:/a",)),
    ))
    builder = AttentionBuilder()
    full = builder.build_full_set(state, state_revision=1)
    # no config -> nothing is cut
    assert builder.build_window(full) == full
    windowed = builder.build_window(
        full, AttentionPolicyConfig(window_size=3, exploration_allowance=1)
    )
    ids = [i.item_id for i in windowed.items]
    assert "question:Q1" in ids              # P2 obligations always kept
    # window_size bounds the P0-P4 fill (1 obligation + 2 normal); the
    # exploration allowance is an independent P5 quota on top
    assert len(ids) == 4
    assert "question:Qexp" in ids            # exploration allowance kept one P5


def test_budget_exhaustion_suppresses_exploratory():
    state = _state(
        questions=(
            _mk_question("Qexp", QuestionPriority.exploratory, basis=("file:/a",)),
        ),
        budget_state=BudgetState(exhausted=True),
    )
    attention = _attention(state)
    item = next(i for i in attention.items if i.item_id == "question:Qexp")
    assert item.eligibility is AttentionEligibility.suppressed


def test_delegation_in_flight_is_annotated():
    state = _state(questions=(_mk_question("Q1", QuestionPriority.high),))
    attention = _attention(
        state, runtime=DelegationRuntimeView(
            run_active=True, in_flight_question_refs=("Q1",)
        )
    )
    item = next(i for i in attention.items if i.item_id == "question:Q1")
    assert "DELEGATION_IN_FLIGHT" in item.reason_codes


# ---------- NoProgressDetector (P2 §53) ----------

def test_progress_signals():
    base = _state(questions=(_mk_question("Q1", QuestionPriority.required),))
    advanced = _state(questions=(_mk_question(
        "Q1", QuestionPriority.required, status=QuestionStatus.in_progress,
    ),))
    detector = NoProgressDetector()
    snapshot = detector.evaluate(base, advanced, previous_revision=1, current_revision=2)
    assert snapshot.productive
    assert "QUESTION_ADVANCED" in snapshot.reason_codes

    evidence_progress = _state(
        evidence_working_set=(EvidenceWorkingSetItem(
            evidence_key="file:/new.txt",
            status=EvidenceRelevanceStatus.high_value,
        ),),
    )
    snapshot2 = detector.evaluate(base, evidence_progress)
    assert "NEW_RELEVANT_EVIDENCE" in snapshot2.reason_codes

    coverage_progress = _state(coverage=(CoverageDimension(
        dimension_id="usb", status=CoverageStatus.covered,
        basis_refs=("file:/a",),
    ),))
    snapshot3 = detector.evaluate(_state(), coverage_progress)
    assert "COVERAGE_ADVANCED" in snapshot3.reason_codes

    finding_progress = _state(finding_refs=("ie_abc",))
    snapshot4 = detector.evaluate(_state(), finding_progress)
    assert "NEW_FINDING_REF" in snapshot4.reason_codes

    contradiction_progress = _state(contradictions=(Contradiction(
        contradiction_id="C1", severity=ContradictionSeverity.low,
        refs=("file:/a",), status=ContradictionStatus.resolved,
    ),))
    snapshot5 = detector.evaluate(_state(), contradiction_progress)
    assert "CONTRADICTION_CHANGED" in snapshot5.reason_codes


def test_noise_and_repeats_are_not_progress():
    base = _state(questions=(_mk_question("Q1", QuestionPriority.required),))
    same = _state(questions=(_mk_question("Q1", QuestionPriority.required),))
    bookkeeping = _state(
        questions=(_mk_question("Q1", QuestionPriority.required),),
        progress_state=ProgressState(
            completed_cycles=5, consecutive_no_progress_cycles=3
        ),
    )
    detector = NoProgressDetector()
    assert not detector.evaluate(base, same).productive
    # progress_state/budget_state bookkeeping is excluded from the diff
    assert not detector.evaluate(base, bookkeeping).productive


def test_threshold_from_config_not_hardcoded():
    detector = NoProgressDetector()
    base = _state()
    snapshot = detector.evaluate(base, _state())
    assert not snapshot.productive
    one = detector.verdict(
        snapshot, NoProgressPolicyConfig(threshold=1), consecutive_no_progress_cycles=0
    )
    assert one.no_progress_detected
    two_first = detector.verdict(
        snapshot, NoProgressPolicyConfig(threshold=2), consecutive_no_progress_cycles=0
    )
    assert not two_first.no_progress_detected
    two_second = detector.verdict(
        snapshot, NoProgressPolicyConfig(threshold=2), consecutive_no_progress_cycles=1
    )
    assert two_second.no_progress_detected
    with pytest.raises(ValidationError):
        NoProgressPolicyConfig(threshold=0)
