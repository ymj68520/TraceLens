"""RCA-2A.1 — Proposal equivalence hardening, retry feedback boundary,
affordance projection and model-facing information comparison.

Offline only; zero model calls (TestModel + capture_run_messages).

§1 three SEPARATELY-reported equivalence dimensions (never a single PASS):
    ACCEPTANCE_SET_EQUIVALENCE   old accept => new accept, same canonical
    REJECTION_SET_EQUIVALENCE    old reject => new reject
    EXECUTION_BEHAVIOR_EQUIVALENCE new accept => old accept for the
                                 equivalent semantic action (anti-superset)
§2 exhaustive status x kind and field matrices (full enumeration — the
   domain is finite, so enumeration beats sampling)
§3 multi-action atomicity (all-or-nothing preserved)
§4 A1-H availability discipline for the uniform update
§5 retry feedback boundary scenarios A-E
§6 option A (resolver fail-closed) vs option B (in-band validation)
"""

import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError
from pydantic_ai import capture_run_messages
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.models.test import TestModel
from pydantic_ai.messages import RetryPromptPart

PYTHON_SERVICE_ROOT = Path(__file__).resolve().parents[3]
for p in (str(PYTHON_SERVICE_ROOT),):
    if p not in sys.path:
        sys.path.insert(0, p)

from benchmarks.contracts.experimental.integration_proposal_v1 import (  # noqa: E402
    ProposalViolation,
    StrictUpdateAction,
    SupervisorIntegrationProposalV1,
    SupervisorIntegrationProposalV1Strict,
    infer_handle_kind,
    proposal_affordances,
    resolve_proposal_to_canonical,
    resolve_strict_proposal_to_canonical,
)
from tests.unit.benchmarks.test_integration_proposal_equivalence import (  # noqa: E402
    EVIDENCE_REF,
    _context,
    _state,
)
from httpserver.services.investigation.agent_integration_v2 import (  # noqa: E402
    CoverageStatus,
    ContradictionStatus,
    EvidenceRelevanceStatus,
    HypothesisStatus,
    QuestionStatus,
    SupervisorIntegrationDecisionV2,
    UpdateContradictionActionV2,
    UpdateCoverageActionV2,
    UpdateEvidenceRelevanceActionV2,
    UpdateHypothesisActionV2,
    UpdateQuestionActionV2,
    availability_projection,
    resolve_integration_proposal_v2,
)
from httpserver.services.investigation.agent_reference_bindings import (  # noqa: E402
    build_integration_binding_table,
)

pytest.importorskip("pydantic_ai")
pytestmark = pytest.mark.migration_matrix


KIND_STATUS = {
    "question": (QuestionStatus, UpdateQuestionActionV2, "Q1"),
    "evidence": (EvidenceRelevanceStatus, UpdateEvidenceRelevanceActionV2, "E1"),
    "hypothesis": (HypothesisStatus, UpdateHypothesisActionV2, "H1"),
    "contradiction": (ContradictionStatus, UpdateContradictionActionV2, "X1"),
    "coverage": (CoverageStatus, UpdateCoverageActionV2, "COV1"),
}
KIND_HANDLE_FIELD = {
    "question": "question_handle",
    "evidence": "evidence_handle",
    "hypothesis": "hypothesis_handle",
    "contradiction": "contradiction_handle",
    "coverage": "coverage_handle",
}
PROPOSAL_HANDLE = {"Q": "Q1", "E": "E1", "H": "H1", "X": "X1", "COV": "COV1"}


def _env():
    state = _state()
    context = _context(state)
    table = build_integration_binding_table(context, state)
    return state, context, table


@pytest.fixture
def env():
    return _env()


def _old_update(kind, status, extra=None):
    enum_cls, action_cls, handle = KIND_STATUS[kind]
    kwargs = {KIND_HANDLE_FIELD[kind]: handle, "to_status": status}
    kwargs.update(extra or {})
    return action_cls(**kwargs)


def _new_update(kind, status, extra=None):
    payload = {"action": "update", "target_handle": PROPOSAL_HANDLE[
        {"question": "Q", "evidence": "E", "hypothesis": "H",
         "contradiction": "X", "coverage": "COV"}[kind]],
        "to_status": status}
    payload.update(extra or {})
    return payload


def _run_old(env, actions):
    state, context, table = env
    return resolve_integration_proposal_v2(
        SupervisorIntegrationDecisionV2(actions=actions), table, context,
        state)


def _run_new(env, action_payloads):
    state, context, table = env
    proposal = SupervisorIntegrationProposalV1(actions=action_payloads)
    canonical = resolve_proposal_to_canonical(proposal)
    return resolve_integration_proposal_v2(canonical, table, context, state)


# ---------------------------------------------------------------------------
# §1/§2 — exhaustive status x kind matrix (three dimensions)
# ---------------------------------------------------------------------------


def test_status_kind_matrix_full_enumeration():
    """Every (kind, to_status) combination in the finite domain:
    own-status combos must accept on both paths with byte-equal canonical
    decisions (ACCEPTANCE + EXECUTION dimensions); cross-kind and invalid
    statuses must reject on both paths (REJECTION dimension)."""
    env = _env()
    all_statuses = {
        "question": [m.value for m in QuestionStatus],
        "evidence": [m.value for m in EvidenceRelevanceStatus],
        "hypothesis": [m.value for m in HypothesisStatus],
        "contradiction": [m.value for m in ContradictionStatus],
        "coverage": [m.value for m in CoverageStatus],
    }
    invalid_statuses = ["Answered", "bogus", "", "COVERED", "in progress"]
    acceptance = rejections = execution = 0
    mismatches = []
    for kind, (enum_cls, _, _) in KIND_STATUS.items():
        for status in all_statuses[kind] + invalid_statuses:
            own = status in all_statuses[kind]
            # OLD: can the production contract express this pair?
            try:
                old_action = _old_update(kind, status)
                old_parse_ok = True
            except Exception:
                old_parse_ok = False
            # NEW draft: proposal layer then canonical resolve
            try:
                new_canonical = resolve_proposal_to_canonical(
                    SupervisorIntegrationProposalV1(
                        actions=[_new_update(kind, status)]))
                new_resolve_ok = True
            except ProposalViolation:
                new_canonical = None
                new_resolve_ok = False
            if own:
                assert old_parse_ok and new_resolve_ok, (
                    f"own-status combo must accept: {kind}/{status}")
                old_decision, _ = _run_old(env, [old_action])
                new_decision, _ = _run_new(env, [_new_update(kind, status)])
                assert old_decision is not None and new_decision is not None
                assert (old_decision.model_dump() == new_decision.model_dump())
                acceptance += 1
                execution += 1
            else:
                assert (not old_parse_ok) and (not new_resolve_ok), (
                    f"cross-kind/invalid status must reject: "
                    f"{kind}/{status!r} old_parse={old_parse_ok} "
                    f"new={new_resolve_ok}")
                rejections += 1
    assert mismatches == []
    # the three dimensions are asserted separately above; publish counts
    matrix = {
        "ACCEPTANCE_SET_EQUIVALENCE": {"verified_combos": acceptance},
        "REJECTION_SET_EQUIVALENCE": {"verified_combos": rejections},
        "EXECUTION_BEHAVIOR_EQUIVALENCE": {"verified_combos": execution},
    }
    (Path(PYTHON_SERVICE_ROOT) / "benchmarks" / "audits"
     / "cross-model-root-cause-audit-v1" / "proposal-constraint-matrix-v1.json"
     ).write_text(json.dumps({
         "artifact_version": "ProposalConstraintMatrixV1",
         "method": "FULL ENUMERATION of the finite (kind, to_status) domain "
                   "(5 kinds x own+cross+invalid statuses) plus field matrices "
                   "in test_rca2a1_hardening.py — no sampling",
         "kinds": {k: {"legal_statuses": [m.value for m in v[0]],
                       "handle": v[2]} for k, v in KIND_STATUS.items()},
         "invalid_status_probes": invalid_statuses,
         "dimensions": matrix,
     }, indent=1) + "\n", encoding="utf-8")


def test_field_matrix_none_missing_empty_and_foreign(tmp_path):
    """None / missing / empty-string semantics per kind, and foreign-field
    rejection (fail-closed, no silent drop)."""
    # "" on a FOREIGN field is treated as absence (no violation), matching
    # the draft's empty-default rule; None likewise; missing likewise.
    for foreign in (
        {"disposition": None}, {"disposition": ""},
        {"investigated_summary": None}, {"investigated_summary": ""},
        {"capability_basis": None}, {"capability_basis": ""},
    ):
        env = _env()
        decision, _ = _run_new(env, [
            {"action": "update", "target_handle": "E1",
             "to_status": "irrelevant", **foreign}])
        assert decision is not None
    # a NON-empty foreign value is a hard violation
    with pytest.raises(ProposalViolation):
        _run_new(_env(), [
            {"action": "update", "target_handle": "E1",
             "to_status": "irrelevant",
             "investigated_summary": "real content"}])
    # "" on an OWN field passes through exactly as the old contract does
    env = _env()
    old = _run_old(env, [UpdateQuestionActionV2(
        question_handle="Q1", to_status=QuestionStatus.in_progress,
        investigated_summary="")])
    new = _run_new(env, [{"action": "update", "target_handle": "Q1",
                          "to_status": "in_progress",
                          "investigated_summary": ""}])
    assert old[0].model_dump() == new[0].model_dump()
    # wrong types are parse-rejected on BOTH paths (pydantic str discipline)
    with pytest.raises(Exception):
        UpdateQuestionActionV2(
            question_handle="Q1", to_status=123)
    with pytest.raises(Exception):
        SupervisorIntegrationProposalV1(actions=[
            {"action": "update", "target_handle": "Q1", "to_status": 123}])


def test_basis_disposition_combinations(env):
    """basis x disposition combos on question updates resolve identically
    on both paths (explicit-empty basis keeps the A1 §26 fail-closed
    semantics)."""
    combos = [
        {"disposition": "supported", "basis_handles": ["E1"]},
        {"disposition": "supported"},                      # no basis yet
        {"disposition": "inconclusive", "basis_handles": []},  # explicit empty
    ]
    for combo in combos:
        payload = {"action": "update", "target_handle": "Q1",
                   "to_status": "answered", **combo}
        old = _run_old(env, [UpdateQuestionActionV2(
            question_handle="Q1", to_status=QuestionStatus.answered,
            **{k: (tuple(v) if isinstance(v, list) else v)
               for k, v in combo.items()})])
        new = _run_new(env, [payload])
        assert (old[0] is None) == (new[0] is None)
        if old[0] is not None:
            assert old[0].model_dump() == new[0].model_dump()


# ---------------------------------------------------------------------------
# §3 — multi-action atomicity
# ---------------------------------------------------------------------------


def test_multi_action_atomicity(env):
    """valid+valid, valid+invalid, invalid+valid, duplicate and conflicting
    updates: order semantics identical; no partial acceptance anywhere."""
    state, context, table = env

    # valid + valid: order preserved in the canonical decisions
    old = _run_old(env, [
        UpdateQuestionActionV2(question_handle="Q1",
                               to_status=QuestionStatus.in_progress),
        UpdateEvidenceRelevanceActionV2(evidence_handle="E1",
                                        to_status=EvidenceRelevanceStatus.irrelevant),
    ])
    new = _run_new(env, [
        {"action": "update", "target_handle": "Q1",
         "to_status": "in_progress"},
        {"action": "update", "target_handle": "E1",
         "to_status": "irrelevant"},
    ])
    assert old[0].model_dump() == new[0].model_dump()
    assert [t.question_id for t in old[0].transition_proposals[:1]] == ["q-1"]

    # valid + invalid: ALL-OR-NOTHING — the old path rejects the whole
    # decision; the new path fails fast at the proposal layer (same
    # outcome: nothing is accepted, nothing is committed)
    # schema-invalid status: the draft fails fast at the proposal layer
    with pytest.raises(ProposalViolation):
        _run_new(env, [
            {"action": "update", "target_handle": "Q1",
             "to_status": "bogus"},
        ])
    # resolve-only-invalid (unknown handle E99): the proposal layer accepts
    # (prefix legal) and the UNCHANGED canonical resolve rejects the whole
    # decision — all-or-nothing preserved
    old = _run_old(env, [
        UpdateQuestionActionV2(question_handle="Q1",
                               to_status=QuestionStatus.in_progress),
        UpdateEvidenceRelevanceActionV2(evidence_handle="E99",
                                        to_status=EvidenceRelevanceStatus.irrelevant),
    ])
    assert old[0] is None
    new = _run_new(env, [
        {"action": "update", "target_handle": "Q1",
         "to_status": "in_progress"},
        {"action": "update", "target_handle": "E99",
         "to_status": "irrelevant"},
    ])
    assert new[0] is None
    assert sorted(v.code.value for v in old[1].violations) == (
        sorted(v.code.value for v in new[1].violations))
    # schema-invalid + valid likewise (fail fast, nothing accepted)
    with pytest.raises(ProposalViolation):
        _run_new(env, [
            {"action": "update", "target_handle": "E1",
             "to_status": "bogus"},
            {"action": "update", "target_handle": "Q1",
             "to_status": "in_progress"},
        ])

    # duplicate updates on the same operand: both paths resolve to two
    # transitions in order (the downstream policy owns the conflict)
    old = _run_old(env, [
        UpdateQuestionActionV2(question_handle="Q1",
                               to_status=QuestionStatus.in_progress),
        UpdateQuestionActionV2(question_handle="Q1",
                               to_status=QuestionStatus.answered),
    ])
    new = _run_new(env, [
        {"action": "update", "target_handle": "Q1",
         "to_status": "in_progress"},
        {"action": "update", "target_handle": "Q1",
         "to_status": "answered"},
    ])
    assert (old[0] is None) == (new[0] is None)
    if old[0] is not None:
        assert len(new[0].transition_proposals) == len(
            old[0].transition_proposals)

    # conflicting updates (answered + in_progress on one operand): the
    # resolver layer is order-faithful on both paths; policy owns conflicts
    old = _run_old(env, [
        UpdateQuestionActionV2(question_handle="Q1",
                               to_status=QuestionStatus.answered),
        UpdateQuestionActionV2(question_handle="Q1",
                               to_status=QuestionStatus.in_progress),
    ])
    new = _run_new(env, [
        {"action": "update", "target_handle": "Q1",
         "to_status": "answered"},
        {"action": "update", "target_handle": "Q1",
         "to_status": "in_progress"},
    ])
    assert (old[0] is None) == (new[0] is None)

    # determinism/purity: running the same new-path resolution twice yields
    # identical output (no hidden state, no snapshot drift)
    first = _run_new(env, [{"action": "update", "target_handle": "Q1",
                            "to_status": "in_progress"}])
    second = _run_new(env, [{"action": "update", "target_handle": "Q1",
                             "to_status": "in_progress"}])
    assert first[0].model_dump() == second[0].model_dump()


# ---------------------------------------------------------------------------
# §4 — A1-H availability discipline for the uniform update
# ---------------------------------------------------------------------------


def test_affordances_mirror_availability_discipline():
    from httpserver.services.investigation.agent_working_state import (
        QuestionPriority, QuestionSource, WorkingQuestion,
    )

    base_state = _state()
    cases = {
        "no-Q": _state().model_copy(update={"questions": ()}),
        "no-COV": base_state.model_copy(update={"coverage": ()}),
        "no-H/X": base_state.model_copy(update={"hypotheses": (),
                                                "contradictions": ()}),
        "only-F/P": base_state.model_copy(update={
            "questions": (), "coverage": (), "hypotheses": (),
            "contradictions": (), "finding_refs": ("finding:f-1",),
            "pending_proposal_refs": ("proposal:p-1",)}),
        "mixed": base_state,
    }
    for name, state in cases.items():
        context = _context(state)
        # keep evidence in scope for every case (the context carries it)
        table = build_integration_binding_table(context, state)
        projection = availability_projection(table)
        afford = proposal_affordances(table)
        # identical handle counting
        assert afford["handle_counts_by_kind"] == (
            projection["handle_counts_by_kind"]), name
        # the uniform update is OFFERED for a kind iff that kind has
        # handles — the same zero-domain discipline as the production
        # availability projection
        offered_kinds = {u["prefix"] for u in afford["offered_updates"]}
        assert ("Q" in offered_kinds) == ("update_question" in
                                          projection["available_actions"]), name
        assert ("E" in offered_kinds) == ("update_evidence_relevance" in
                                          projection["available_actions"]), name
        assert ("H" in offered_kinds) == ("update_hypothesis" in
                                          projection["available_actions"]), name
        assert ("X" in offered_kinds) == ("update_contradiction" in
                                          projection["available_actions"]), name
        assert ("COV" in offered_kinds) == ("update_coverage" in
                                            projection["available_actions"]), name
        # reference-only actions mirror exactly
        assert (
            "add_finding_reference" in afford["offered_other_actions"]
        ) == (
            "add_finding_reference" in projection["available_actions"]
        )
        # each offered update carries its frozen status vocabulary
        for u in afford["offered_updates"]:
            assert u["statuses"], name


# ---------------------------------------------------------------------------
# §5 — retry feedback boundary scenarios A-E (+ option B strict)
# ---------------------------------------------------------------------------


async def _agent_run(output_type, args):
    """Run one TestModel agent with the given output type / args, capturing
    messages. Returns (raised_exc|None, messages, run_returned)."""
    import asyncio

    from pydantic_ai import Agent

    model = TestModel(call_tools=[], custom_output_args=args)
    agent = Agent(model, output_type=output_type)
    with capture_run_messages() as messages:
        try:
            await asyncio.wait_for(agent.run("integrate"), timeout=30)
            return None, messages, True
        except UnexpectedModelBehavior as exc:
            return exc, messages, False
        except ValidationError as exc:
            return exc, messages, False


async def test_retry_boundary_scenarios(tmp_path):
    """Scenarios A-E recorded for the boundary report: WHERE does the
    failure land — schema parse (retry feedback) or proposal resolver
    (fail-closed, after Agent.run returned)?"""
    scenarios = {}

    # A: OLD contract, enum error -> in-band retry, run raises
    exc, messages, returned = await _agent_run(
        SupervisorIntegrationDecisionV2,
        {"actions": [{"action_type": "update_evidence_relevance",
                      "evidence_handle": "E1", "to_status": "answered"}]})
    retry_prompts = [m for m in messages
                     for p in getattr(m, "parts", [])
                     if isinstance(p, RetryPromptPart)]
    scenarios["A_old_enum_error"] = {
        "schema_parse": "rejected", "retry_prompt_count": len(retry_prompts),
        "agent_run_returned": returned,
        "resolver_called": False, "committed": False,
        "terminal_exception": type(exc).__name__ if exc else None}

    # B: DRAFT proposal, illegal to_status -> parse OK, run RETURNS,
    #    resolver rejects (fail-closed at cycle level, no retry feedback)
    exc, messages, returned = await _agent_run(
        SupervisorIntegrationProposalV1,
        {"actions": [{"action": "update", "target_handle": "E1",
                      "to_status": "answered"}]})
    retry_prompts = [m for m in messages
                     for p in getattr(m, "parts", [])
                     if isinstance(p, RetryPromptPart)]
    canonical = None
    resolver_code = None
    try:
        canonical = resolve_proposal_to_canonical(
            SupervisorIntegrationProposalV1(
                actions=[{"action": "update", "target_handle": "E1",
                          "to_status": "answered"}]))
    except ProposalViolation as pv:
        resolver_code = pv.code
    scenarios["B_draft_illegal_status"] = {
        "schema_parse": "accepted", "retry_prompt_count": len(retry_prompts),
        "agent_run_returned": returned,
        "resolver_called": canonical is not None,
        "resolver_violation_code": resolver_code, "committed": False}

    # C: DRAFT proposal, cross-kind field -> parse OK, resolver rejects
    try:
        resolve_proposal_to_canonical(SupervisorIntegrationProposalV1(
            actions=[{"action": "update", "target_handle": "E1",
                      "to_status": "irrelevant",
                      "investigated_summary": "x"}]))
        resolver_code = None
    except ProposalViolation as pv:
        resolver_code = pv.code
    scenarios["C_draft_cross_kind_field"] = {
        "schema_parse": "accepted", "resolver_violation_code": resolver_code,
        "committed": False}

    # D: DRAFT proposal, unknown handle prefix -> resolver rejects
    try:
        resolve_proposal_to_canonical(SupervisorIntegrationProposalV1(
            actions=[{"action": "update", "target_handle": "Z9",
                      "to_status": "in_progress"}]))
        resolver_code = None
    except ProposalViolation as pv:
        resolver_code = pv.code
    scenarios["D_draft_unknown_handle"] = {
        "schema_parse": "accepted", "resolver_violation_code": resolver_code,
        "committed": False}

    # E: DRAFT proposal, legal action -> parse OK, resolver OK, canonical OK
    canonical = resolve_proposal_to_canonical(SupervisorIntegrationProposalV1(
        actions=[{"action": "update", "target_handle": "Q1",
                  "to_status": "in_progress"}]))
    scenarios["E_draft_legal"] = {
        "schema_parse": "accepted", "resolver_violation_code": None,
        "canonical_action": type(canonical.actions[0]).__name__,
        "committed": False}

    # Option B (STRICT): illegal status -> IN-BAND validation error ->
    # retry prompt -> bounded retries -> UnexpectedModelBehavior
    exc, messages, returned = await _agent_run(
        SupervisorIntegrationProposalV1Strict,
        {"actions": [{"action": "update", "target_handle": "E1",
                      "to_status": "answered"}]})
    retry_prompts = [m for m in messages
                     for p in getattr(m, "parts", [])
                     if isinstance(p, RetryPromptPart)]
    scenarios["B_strict_illegal_status"] = {
        "schema_parse": "rejected", "retry_prompt_count": len(retry_prompts),
        "agent_run_returned": returned,
        "resolver_called": False, "committed": False,
        "terminal_exception": type(exc).__name__ if exc else None}

    assert scenarios["A_old_enum_error"]["retry_prompt_count"] >= 1
    assert not scenarios["A_old_enum_error"]["agent_run_returned"]
    assert scenarios["B_draft_illegal_status"]["agent_run_returned"]
    assert scenarios["B_draft_illegal_status"]["retry_prompt_count"] == 0
    assert scenarios["B_draft_illegal_status"][
        "resolver_violation_code"] == "proposal_status_not_in_kind_enum"
    assert scenarios["C_draft_cross_kind_field"][
        "resolver_violation_code"] == "proposal_field_not_valid_for_kind"
    assert scenarios["D_draft_unknown_handle"][
        "resolver_violation_code"] == "proposal_unknown_handle_prefix"
    assert scenarios["E_draft_legal"]["canonical_action"] == (
        "UpdateQuestionActionV2")
    assert scenarios["B_strict_illegal_status"]["retry_prompt_count"] >= 1
    assert not scenarios["B_strict_illegal_status"]["agent_run_returned"]

    (Path(PYTHON_SERVICE_ROOT) / "benchmarks" / "audits"
     / "cross-model-root-cause-audit-v1"
     / "retry-feedback-boundary-report-v1.json").write_text(
        json.dumps({"artifact_version": "RetryFeedbackBoundaryReportV1",
                    "layer_vocabulary": {
                        "schema_parse_success": "pydantic output-tool validation passed",
                        "proposal_resolution_success": "resolve_proposal_to_canonical passed (handle-prefix/kind/enum checks)",
                        "canonical_integration_success": "resolve_integration_proposal_v2 + validator + policy accepted",
                    },
                    "scenarios": scenarios,
                    "option_A": "Agent.run -> proposal -> resolver -> invalid -> fail closed (no retry feedback for resolver-class violations)",
                    "option_B": "in-band validation (Strict variant) -> bounded output retry with structured feedback; handle EXISTENCE still resolver-side",
                    "note": "three success layers are DISTINCT; proposal parse success is never integration success",
                   }, indent=1) + "\n", encoding="utf-8")
