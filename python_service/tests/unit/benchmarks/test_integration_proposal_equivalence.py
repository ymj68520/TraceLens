"""RCA-2A §6 — semantic equivalence between the production INTEGRATE
contract (SupervisorIntegrationDecisionV2) and the EXPERIMENTAL
IntegrationProposalContractDraftV1 (offline only; zero model calls).

Method: for each legal action the SAME frozen binding table / context /
state feed two paths —
    old:  SupervisorIntegrationDecisionV2 -> resolve_integration_proposal_v2
    new:  SupervisorIntegrationProposalV1 -> resolve_proposal_to_canonical
          -> resolve_integration_proposal_v2 (UNCHANGED canonical path)
and the resolved canonical v1 decisions (or violation sets) must match.

The proposals flow into the UNCHANGED binding table, validator, policy and
gate — the proposal layer adds reject-classes, never accept-classes.
"""

import sys
from pathlib import Path

import pytest

PYTHON_SERVICE_ROOT = Path(__file__).resolve().parents[3]
for p in (str(PYTHON_SERVICE_ROOT),):
    if p not in sys.path:
        sys.path.insert(0, p)

from benchmarks.contracts.experimental.integration_proposal_v1 import (  # noqa: E402
    ProposalViolation,
    SupervisorIntegrationProposalV1,
    resolve_proposal_to_canonical,
)
from httpserver.services.investigation.agent_integration import (  # noqa: E402
    IntegrationContextPack,
)
from httpserver.services.investigation.agent_integration_v2 import (  # noqa: E402
    AddFindingReferenceActionV2,
    AddPendingProposalReferenceActionV2,
    CreateContradictionActionV2,
    CreateHypothesisActionV2,
    CreateQuestionActionV2,
    EvidenceRelevanceStatus,
    SupervisorIntegrationDecisionV2,
    UpdateContradictionActionV2,
    UpdateCoverageActionV2,
    UpdateEvidenceRelevanceActionV2,
    UpdateHypothesisActionV2,
    UpdateQuestionActionV2,
    resolve_integration_proposal_v2,
)
from httpserver.services.investigation.agent_reference_bindings import (  # noqa: E402
    build_integration_binding_table,
    context_state_question_ids,
)
from httpserver.services.investigation.agent_working_state import (  # noqa: E402
    AgentWorkingStateV1,
    Contradiction,
    ContradictionSeverity,
    ContradictionStatus,
    CoverageDimension,
    CoverageStatus,
    Hypothesis,
    HypothesisStatus,
    QuestionDisposition,
    QuestionPriority,
    QuestionSource,
    QuestionStatus,
    working_state_to_json,
)
from httpserver.services.investigation.agent_runtime import (  # noqa: E402
    state_hash_of,
)

pytest.importorskip("pydantic_ai")

EVIDENCE_REF = "file:C/logon_4624.doc"


def _state() -> AgentWorkingStateV1:
    from httpserver.services.investigation.agent_working_state import (
        QuestionPriority as QP,
        QuestionSource as QS,
        WorkingQuestion,
    )

    return AgentWorkingStateV1(
        task_id="task-A",
        investigation_id="inv-equiv",
        objective="equivalence fixture",
        questions=(
            WorkingQuestion(
                question_id="q-1",
                text="Were there unauthorized logons?",
                source=QS.charter,
                priority=QP.required,
            ),
        ),
        coverage=(
            CoverageDimension(dimension_id="dim-core", required=True),
        ),
        hypotheses=(
            Hypothesis(hypothesis_id="hyp-1", text="scripted exfiltration"),
        ),
        contradictions=(
            Contradiction(
                contradiction_id="con-1",
                severity=ContradictionSeverity.low,
            ),
        ),
        finding_refs=("finding:f-1",),
        pending_proposal_refs=("proposal:p-1",),
    )


def _context(state: AgentWorkingStateV1) -> IntegrationContextPack:
    return IntegrationContextPack(
        task_id="task-A",
        investigation_id="inv-equiv",
        run_id="run-equiv",
        state_revision=1,
        state_hash=state_hash_of(working_state_to_json(state)),
        state_slice_digests=(
            f"question:{q}" for q in ("q-1",)
        ),
        relevant_evidence_refs=(EVIDENCE_REF,),
    )


@pytest.fixture
def env():
    state = _state()
    context = _context(state)
    table = build_integration_binding_table(context, state)
    assert context_state_question_ids(context) == {"q-1"}
    return state, context, table


def _old(env, actions):
    state, context, table = env
    decision = SupervisorIntegrationDecisionV2(actions=actions)
    return resolve_integration_proposal_v2(decision, table, context, state)


def _new(env, actions):
    state, context, table = env
    proposal = SupervisorIntegrationProposalV1(actions=actions)
    canonical = resolve_proposal_to_canonical(proposal)
    return resolve_integration_proposal_v2(canonical, table, context, state)


def _assert_equivalent(old, new):
    old_decision, old_record = old
    new_decision, new_record = new
    if old_decision is None:
        assert new_decision is None, (
            f"NEW accepted where OLD rejected: {new_record}")
        assert sorted(v.code.value for v in old_record.violations) == (
            sorted(v.code.value for v in new_record.violations))
    else:
        assert new_decision is not None, (
            f"NEW rejected where OLD accepted: {new_record}")
        assert old_decision.model_dump() == new_decision.model_dump()


# ---------------------------------------------------------------------------
# §6 — all ten legal canonical actions
# ---------------------------------------------------------------------------


def test_eq_update_question_answered(env):
    old = _old(env, [UpdateQuestionActionV2(
        question_handle="Q1", to_status=QuestionStatus.answered,
        disposition=QuestionDisposition.supported,
        basis_handles=("E1",),
        investigated_summary="logon evidence reviewed")])
    new = _new(env, [{"action": "update", "target_handle": "Q1",
                      "to_status": "answered",
                      "disposition": "supported",
                      "basis_handles": ["E1"],
                      "investigated_summary": "logon evidence reviewed"}])
    _assert_equivalent(old, new)


def test_eq_update_question_in_progress_no_disposition(env):
    old = _old(env, [UpdateQuestionActionV2(
        question_handle="Q1", to_status=QuestionStatus.in_progress)])
    new = _new(env, [{"action": "update", "target_handle": "Q1",
                      "to_status": "in_progress"}])
    _assert_equivalent(old, new)


def test_eq_update_evidence_relevance(env):
    old = _old(env, [UpdateEvidenceRelevanceActionV2(
        evidence_handle="E1", to_status=EvidenceRelevanceStatus.irrelevant,
        related_question_handles=("Q1",))])
    new = _new(env, [{"action": "update", "target_handle": "E1",
                      "to_status": "irrelevant",
                      "related_question_handles": ["Q1"]}])
    _assert_equivalent(old, new)


def test_eq_update_hypothesis(env):
    old = _old(env, [UpdateHypothesisActionV2(
        hypothesis_handle="H1", to_status=HypothesisStatus.weakened)])
    new = _new(env, [{"action": "update", "target_handle": "H1",
                      "to_status": "weakened"}])
    _assert_equivalent(old, new)


def test_eq_update_contradiction(env):
    old = _old(env, [UpdateContradictionActionV2(
        contradiction_handle="X1", to_status=ContradictionStatus.explained,
        resolution_basis_handles=("E1",),
        attempted_resolution="both readings explained by the copy job")])
    new = _new(env, [{"action": "update", "target_handle": "X1",
                      "to_status": "explained",
                      "resolution_basis_handles": ["E1"],
                      "attempted_resolution": (
                          "both readings explained by the copy job")}])
    _assert_equivalent(old, new)


def test_eq_update_coverage(env):
    old = _old(env, [UpdateCoverageActionV2(
        coverage_handle="COV1", to_status=CoverageStatus.covered,
        basis_handles=("E1",), capability_basis="tool surface")])
    new = _new(env, [{"action": "update", "target_handle": "COV1",
                      "to_status": "covered", "basis_handles": ["E1"],
                      "capability_basis": "tool surface"}])
    _assert_equivalent(old, new)


def test_eq_create_question(env):
    old = _old(env, [CreateQuestionActionV2(
        text="Was the copy job scheduled?",
        source=QuestionSource.supervisor_discovery,
        priority=QuestionPriority.high, parent_question_handle="Q1")])
    new = _new(env, [{"action": "create_question",
                      "text": "Was the copy job scheduled?",
                      "source": "supervisor_discovery",
                      "priority": "high",
                      "parent_question_handle": "Q1"}])
    _assert_equivalent(old, new)


def test_eq_create_hypothesis(env):
    old = _old(env, [CreateHypothesisActionV2(
        text="nightly job masks interactive access",
        supporting_handles=("E1",))])
    new = _new(env, [{"action": "create_hypothesis",
                      "text": "nightly job masks interactive access",
                      "supporting_handles": ["E1"]}])
    _assert_equivalent(old, new)


def test_eq_create_contradiction(env):
    old = _old(env, [CreateContradictionActionV2(
        severity=ContradictionSeverity.material, refs_handles=("E1",),
        attempted_resolution="timestamp overlap")])
    new = _new(env, [{"action": "create_contradiction",
                      "severity": "material", "refs_handles": ["E1"],
                      "attempted_resolution": "timestamp overlap"}])
    _assert_equivalent(old, new)


def test_eq_add_finding_reference(env):
    old = _old(env, [AddFindingReferenceActionV2(finding_handle="F1")])
    new = _new(env, [{"action": "add_finding_reference",
                      "finding_handle": "F1"}])
    _assert_equivalent(old, new)


def test_eq_add_pending_proposal_reference(env):
    old = _old(env, [AddPendingProposalReferenceActionV2(
        proposal_handle="P1")])
    new = _new(env, [{"action": "add_pending_proposal_reference",
                      "proposal_handle": "P1"}])
    _assert_equivalent(old, new)


# ---------------------------------------------------------------------------
# §6 — old-rejects implies new-rejects (no new acceptance)
# ---------------------------------------------------------------------------


def test_neg_unknown_handle_rejected_by_both(env):
    old = _old(env, [UpdateQuestionActionV2(
        question_handle="Q99", to_status=QuestionStatus.in_progress)])
    new = _new(env, [{"action": "update", "target_handle": "Q99",
                      "to_status": "in_progress"}])
    _assert_equivalent(old, new)


def test_neg_cross_kind_basis_rejected_by_both(env):
    # basis_handles must be evidence handles: a question handle is
    # schema-illegal in the OLD contract and resolver-illegal in the NEW
    with pytest.raises(Exception):
        UpdateQuestionActionV2(
            question_handle="Q1", to_status=QuestionStatus.in_progress,
            basis_handles=("Q1",))
    with pytest.raises(ProposalViolation):
        _new(env, [{"action": "update", "target_handle": "Q1",
                    "to_status": "in_progress", "basis_handles": ["Q1"]}])


def test_neg_status_outside_kind_enum_rejected_by_both(env):
    # OLD: pydantic rejects 'answered' against the EvidenceRelevanceStatus
    # enum at parse time. NEW: the schema carries plain strings; the
    # resolver rejects with proposal_status_not_in_kind_enum. Enforcement
    # point moved, accepted set identical (documented in the report).
    with pytest.raises(Exception):
        UpdateEvidenceRelevanceActionV2(
            evidence_handle="E1", to_status="answered")
    with pytest.raises(ProposalViolation):
        _new(env, [{"action": "update", "target_handle": "E1",
                    "to_status": "answered"}])


def test_neg_question_field_on_evidence_target_is_new_rejection(env):
    """The uniform update makes cross-kind fields EXPRESSIBLE where the old
    contract's per-action schemas made them inexpressible. The resolver
    fails closed (P_FIELD_NOT_VALID_FOR_KIND) — a NEW rejection class, not
    an equivalence case; no acceptance set growth."""
    with pytest.raises(ProposalViolation) as exc:
        _new(env, [{"action": "update", "target_handle": "E1",
                    "to_status": "irrelevant",
                    "investigated_summary": "should not be allowed"}])
    assert exc.value.code == "proposal_field_not_valid_for_kind"


def test_neg_unavailable_action_stays_rejected(env):
    """F/P handles are reference-only: the old union has no update action
    for them, and the proposal resolver rejects the target kind."""
    with pytest.raises(ProposalViolation):
        _new(env, [{"action": "update", "target_handle": "F1",
                    "to_status": "covered"}])
    with pytest.raises(ProposalViolation):
        _new(env, [{"action": "update", "target_handle": "P1",
                    "to_status": "supported"}])
