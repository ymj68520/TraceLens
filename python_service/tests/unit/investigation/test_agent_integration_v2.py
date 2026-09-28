"""A1 contract v2 tests — trusted reference bindings + handle-based
supervisor proposals (spec §29–§36).

§29 binding table (determinism, scope, unknown/wrong-kind/stale handles,
duplicate-canonical dedup)
§30 trusted identity absent from the v2 model schema
§31 evidence binding (E-handle -> canonical key; E999/raw key rejected)
§32 question disposition (semantic gates PRESERVED through the resolved
    proposal — the unchanged StateTransitionPolicy still rejects)
§33 coverage handles (exact canonical dimension; no free-form creation)
§34 delegation handles (exact fresh result; foreign context fails)
§35 policy reuse (resolved v2 decisions flow through the UNCHANGED
    IntegrationDecisionValidator + StateTransitionPolicy — no fast path)
§36 audit round-trip (raw v2 + table + resolution record + canonical
    decision re-validate hash-consistently)
plus an orchestrator-level v2 wiring test (real resolver, real gates,
fake v2 supervisor; PLAN→EXECUTE→INTEGRATE→EVALUATE committed).
"""

import json

import pytest
from pydantic import ValidationError

from httpserver.services.investigation.agent_integration import (
    FreshResultEnvelope,
    IntegrationContextPack,
    IntegrationDecisionValidator,
)
from httpserver.services.investigation.agent_integration_v2 import (
    INTEGRATION_DECISION_VERSION_V2,
    PLAN_DECISION_VERSION_V2,
    ResolutionViolationCode,
    SupervisorIntegrationDecisionV2,
    SupervisorPlanDecisionV2,
    UpdateCoverageActionV2,
    UpdateEvidenceRelevanceActionV2,
    UpdateQuestionActionV2,
    render_integration_context_v2,
    resolve_integration_proposal_v2,
    resolve_plan_proposal_v2,
)
from httpserver.services.investigation.agent_reference_bindings import (
    BindingKind,
    build_integration_binding_table,
    build_plan_binding_table,
)
from httpserver.services.investigation.agent_specialist_result import (
    SpecialistResultV1,
)
from httpserver.services.investigation.agent_supervisor import (
    AttentionItemDigest,
    QuestionIndexEntry,
    SupervisorPlanDecisionV1,
    SupervisorPlanDecisionValidator,
    SupervisorPlanningContextPack,
)
from httpserver.services.investigation.agent_transitions import (
    EvidenceRefStatus,
    StateTransitionPolicy,
    TransitionBatch,
    TransitionPolicyContext,
)
from httpserver.services.investigation.agent_working_state import (
    AgentWorkingStateV1,
    CoverageDimension,
    CoverageStatus,
    QuestionDisposition,
    QuestionPriority,
    QuestionSource,
    QuestionStatus,
    WorkingQuestion,
)

pytestmark = pytest.mark.migration_matrix

TASK = "task-A"
INV = "inv-cccccccc"
RUN = "run-0001"
STATE_HASH = "a" * 64
E1_KEY = "file:C/logon_4624.doc"
E2_KEY = "file:C/logon_4625.doc"


def _state(**overrides):
    base = dict(
        task_id=TASK,
        investigation_id=INV,
        questions=(
            WorkingQuestion(
                question_id="q-1",
                text="Were there unauthorized logons?",
                source=QuestionSource.charter,
                priority=QuestionPriority.high,
            ),
            WorkingQuestion(
                question_id="q-2",
                text="Which account performed the transfers?",
                source=QuestionSource.charter,
                priority=QuestionPriority.high,
            ),
        ),
        coverage=(
            CoverageDimension(
                dimension_id="logon_activity", required=True
            ),
        ),
    )
    base.update(overrides)
    return AgentWorkingStateV1(**base)


def _context(**overrides):
    base = dict(
        task_id=TASK,
        investigation_id=INV,
        run_id=RUN,
        state_revision=3,
        state_hash=STATE_HASH,
        state_slice_digests=("question:q-1", "question:q-2"),
        relevant_evidence_refs=(E1_KEY, E2_KEY),
    )
    base.update(overrides)
    return IntegrationContextPack(**base)


def _fresh_env(result_hash="f" * 64):
    result = SpecialistResultV1(
        delegation_id="del-777",
        summary="logon cluster observed",
        claim_candidates=(
            {
                "candidate_id": "c-1",
                "text": "logon cluster observed",
                "assertion_class": "INFERENCE",
                "evidence_refs": [E1_KEY],
                "limitations": [],
            },
        ),
        execution_digest={"tool_call_count": 0, "observation_count": 0},
    )
    return FreshResultEnvelope(
        delegation_id="del-777",
        question_id="q-1",
        source_scope_id="windows",
        result=result,
        result_hash=result_hash,
    )


# ---------------------------------------------------------------------------
# §29 binding table
# ---------------------------------------------------------------------------


def test_same_frozen_context_deterministic_table():
    table_a = build_integration_binding_table(_context(), _state())
    table_b = build_integration_binding_table(_context(), _state())
    assert table_a.binding_table_id == table_b.binding_table_id
    assert table_a.table_hash() == table_b.table_hash()
    assert [b.handle for b in table_a.bindings] == [
        b.handle for b in table_b.bindings
    ]


def test_different_task_scope_different_table():
    other = build_integration_binding_table(
        _context(task_id="task-B"), _state(task_id="task-B")
    )
    mine = build_integration_binding_table(_context(), _state())
    assert other.binding_table_id != mine.binding_table_id


def test_duplicate_canonical_evidence_one_stable_handle():
    table = build_integration_binding_table(_context(), _state())
    e_handles = [
        b for b in table.bindings if b.kind is BindingKind.evidence
    ]
    keys = [b.canonical_ref for b in e_handles]
    assert len(keys) == len(set(keys))
    handle_of_first = table.handle_of(BindingKind.evidence, E1_KEY)
    assert table.handle_of(BindingKind.evidence, E1_KEY) == handle_of_first
    assert handle_of_first is not None


def test_handle_kinds_are_explicit_and_scoped():
    table = build_integration_binding_table(
        _context(fresh_results=(_fresh_env(),)), _state()
    )
    assert table.by_handle("Q1").canonical_ref == "q-1"
    assert table.by_handle("COV1").canonical_ref == "logon_activity"
    assert table.by_handle("D1").canonical_ref == "del-777"
    # handles never appear twice
    handles = [b.handle for b in table.bindings]
    assert len(handles) == len(set(handles))


# ---------------------------------------------------------------------------
# §30 trusted identity absent from model schema
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    [
        "task_id",
        "investigation_id",
        "run_id",
        "based_on_state_revision",
        "based_on_state_hash",
        "attention_hash",
        "source_result_ids",
        "source_result_hashes",
        "transition_proposals",
    ],
)
def test_v2_integration_schema_has_no_trusted_identity_fields(field):
    assert field not in SupervisorIntegrationDecisionV2.model_fields


@pytest.mark.parametrize(
    "field",
    [
        "task_id",
        "investigation_id",
        "run_id",
        "based_on_state_revision",
        "based_on_state_hash",
        "attention_hash",
    ],
)
def test_v2_plan_schema_has_no_trusted_identity_fields(field):
    assert field not in SupervisorPlanDecisionV2.model_fields


def test_v2_model_rejects_identity_fields_as_extra():
    with pytest.raises(ValidationError):
        SupervisorIntegrationDecisionV2(
            decision_version=INTEGRATION_DECISION_VERSION_V2,
            task_id=TASK,
        )
    with pytest.raises(ValidationError):
        SupervisorPlanDecisionV2(
            decision_version=PLAN_DECISION_VERSION_V2,
            attention_hash="x" * 64,
        )


# ---------------------------------------------------------------------------
# §31 evidence binding
# ---------------------------------------------------------------------------


def test_evidence_handle_resolves_to_canonical_key():
    table = build_integration_binding_table(_context(), _state())
    decision = SupervisorIntegrationDecisionV2(
        actions=(
            UpdateEvidenceRelevanceActionV2(
                evidence_handle="E1",
                to_status="relevant",
                related_question_handles=("Q1",),
            ),
        )
    )
    canonical, record = resolve_integration_proposal_v2(
        decision, table, _context(), _state()
    )
    assert record.ok
    proposal = canonical.transition_proposals[0]
    assert proposal.evidence_key == E1_KEY
    assert proposal.related_question_ids == ("q-1",)


def test_unknown_evidence_handle_fails_closed():
    table = build_integration_binding_table(_context(), _state())
    decision = SupervisorIntegrationDecisionV2(
        actions=(
            UpdateEvidenceRelevanceActionV2(
                evidence_handle="E999", to_status="relevant"
            ),
        )
    )
    canonical, record = resolve_integration_proposal_v2(
        decision, table, _context(), _state()
    )
    assert canonical is None
    assert record.violations[0].code is (
        ResolutionViolationCode.HANDLE_UNKNOWN
    )


def test_raw_canonical_key_is_not_a_handle():
    table = build_integration_binding_table(_context(), _state())
    decision = SupervisorIntegrationDecisionV2(
        actions=(
            UpdateEvidenceRelevanceActionV2(
                evidence_handle=E1_KEY, to_status="relevant"
            ),
        )
    )
    canonical, record = resolve_integration_proposal_v2(
        decision, table, _context(), _state()
    )
    assert canonical is None
    assert record.violations[0].code is (
        ResolutionViolationCode.HANDLE_UNKNOWN
    )


# ---------------------------------------------------------------------------
# §32 question disposition — semantic gates PRESERVED
# ---------------------------------------------------------------------------


def _policy_ctx(state):
    return TransitionPolicyContext(
        task_id=TASK,
        investigation_id=INV,
        evidence_ref_resolver=lambda ref: (
            EvidenceRefStatus.resolved
            if ref in (E1_KEY, E2_KEY)
            else EvidenceRefStatus.not_found
        ),
        finding_ref_validator=lambda ref: True,
    )


def test_answered_with_basis_resolves_and_policy_accepts():
    table = build_integration_binding_table(_context(), _state())
    decision = SupervisorIntegrationDecisionV2(
        actions=(
            UpdateQuestionActionV2(
                question_handle="Q1",
                to_status=QuestionStatus.answered,
                disposition=QuestionDisposition.supported,
                basis_handles=("E1",),
                limitations=("scoped to logon evidence",),
                investigated_summary="logon cluster tied to evidence",
            ),
        )
    )
    canonical, record = resolve_integration_proposal_v2(
        decision, table, _context(), _state()
    )
    assert record.ok
    # the resolved proposal enters the UNCHANGED policy (§35)
    result = StateTransitionPolicy().evaluate_batch(
        _state(),
        TransitionBatch(transitions=canonical.transition_proposals),
        _policy_ctx(_state()),
    )
    assert result.status.value == "accepted"
    answered = result.new_state.question("q-1")
    assert answered.status is QuestionStatus.answered
    assert answered.basis_refs == (E1_KEY,)


def test_answered_without_basis_still_fails_closure_gate():
    table = build_integration_binding_table(_context(), _state())
    # EXPLICIT empty basis_handles resolves to () — the unchanged
    # QUESTION_CLOSURE_BASIS_REQUIRED gate must fire (A1 §14/§26)
    decision = SupervisorIntegrationDecisionV2(
        actions=(
            UpdateQuestionActionV2(
                question_handle="Q1",
                to_status=QuestionStatus.answered,
                disposition=QuestionDisposition.supported,
                basis_handles=(),
            ),
        )
    )
    canonical, record = resolve_integration_proposal_v2(
        decision, table, _context(), _state()
    )
    assert record.ok
    result = StateTransitionPolicy().evaluate_batch(
        _state(),
        TransitionBatch(transitions=canonical.transition_proposals),
        _policy_ctx(_state()),
    )
    assert result.status.value == "rejected"
    assert "QUESTION_CLOSURE_BASIS_REQUIRED" in [
        v.code for v in result.violations
    ]


def test_unknown_question_handle_fails_resolution():
    table = build_integration_binding_table(_context(), _state())
    decision = SupervisorIntegrationDecisionV2(
        actions=(
            UpdateQuestionActionV2(
                question_handle="Q7", to_status=QuestionStatus.answered
            ),
        )
    )
    canonical, record = resolve_integration_proposal_v2(
        decision, table, _context(), _state()
    )
    assert canonical is None
    assert record.violations[0].code is (
        ResolutionViolationCode.HANDLE_UNKNOWN
    )


# ---------------------------------------------------------------------------
# §33 coverage handles
# ---------------------------------------------------------------------------


def test_coverage_handle_maps_to_exact_dimension():
    table = build_integration_binding_table(_context(), _state())
    decision = SupervisorIntegrationDecisionV2(
        actions=(
            UpdateCoverageActionV2(
                coverage_handle="COV1",
                to_status=CoverageStatus.covered,
                basis_handles=("E1",),
            ),
        )
    )
    canonical, record = resolve_integration_proposal_v2(
        decision, table, _context(), _state()
    )
    assert record.ok
    assert canonical.transition_proposals[0].dimension_id == "logon_activity"


def test_free_form_coverage_name_is_not_accepted():
    table = build_integration_binding_table(_context(), _state())
    decision = SupervisorIntegrationDecisionV2(
        actions=(
            UpdateCoverageActionV2(
                coverage_handle="network_activity",
                to_status=CoverageStatus.covered,
            ),
        )
    )
    canonical, record = resolve_integration_proposal_v2(
        decision, table, _context(), _state()
    )
    assert canonical is None
    assert record.violations[0].code is (
        ResolutionViolationCode.HANDLE_UNKNOWN
    )


# ---------------------------------------------------------------------------
# §34 delegation handles / §10 context mismatch
# ---------------------------------------------------------------------------


def test_delegation_handle_resolves_exact_fresh_result():
    table = build_integration_binding_table(
        _context(fresh_results=(_fresh_env(),)), _state()
    )
    assert table.by_handle("D1").canonical_ref == "del-777"


def test_binding_table_from_another_context_is_rejected():
    table = build_integration_binding_table(
        _context(fresh_results=(_fresh_env(),)), _state()
    )
    other_context = _context(state_revision=4, state_hash="b" * 64)
    decision = SupervisorIntegrationDecisionV2(
        actions=(
            UpdateQuestionActionV2(
                question_handle="Q1", to_status=QuestionStatus.in_progress
            ),
        )
    )
    canonical, record = resolve_integration_proposal_v2(
        decision, table, other_context, _state()
    )
    assert canonical is None
    assert record.violations[0].code is (
        ResolutionViolationCode.HANDLE_CONTEXT_MISMATCH
    )


# ---------------------------------------------------------------------------
# §35 policy reuse — canonical v1 decision through the existing validator
# ---------------------------------------------------------------------------


def test_resolved_decision_is_genuine_v1_and_passes_validator():
    table = build_integration_binding_table(
        _context(fresh_results=(_fresh_env(),)), _state()
    )
    decision = SupervisorIntegrationDecisionV2(
        actions=(
            UpdateQuestionActionV2(
                question_handle="Q1", to_status=QuestionStatus.in_progress
            ),
        ),
        integration_summary="advance q-1",
    )
    context = _context(fresh_results=(_fresh_env(),))
    canonical, record = resolve_integration_proposal_v2(
        decision, table, context, _state()
    )
    assert record.ok
    assert (
        canonical.decision_version == "supervisor-integration-decision:v1"
    )
    assert canonical.task_id == TASK
    assert canonical.based_on_state_revision == context.state_revision
    assert canonical.source_result_ids == ("del-777",)
    validator = IntegrationDecisionValidator()
    validation = validator.validate(context, canonical)
    assert validation.valid, validation.codes


# ---------------------------------------------------------------------------
# §36 audit round-trip
# ---------------------------------------------------------------------------


def test_audit_artifacts_round_trip_hash_consistent():
    from httpserver.services.investigation.agent_integration_v2 import (
        render_integration_context_v2,
    )

    table = build_integration_binding_table(_context(), _state())
    raw = SupervisorIntegrationDecisionV2(
        actions=(
            UpdateQuestionActionV2(
                question_handle="Q1", to_status=QuestionStatus.in_progress
            ),
        )
    )
    canonical, record = resolve_integration_proposal_v2(
        raw, table, _context(), _state()
    )
    # serialize everything the way the trajectory/commit payload does
    blob = json.dumps(
        {
            "raw_model_proposal_v2": raw.model_dump(mode="json"),
            "binding_table_id": table.binding_table_id,
            "binding_table_hash": table.table_hash(),
            "resolution_record": record.model_dump(mode="json"),
            "canonical_decision_hash": canonical.decision_hash(),
            "projection": render_integration_context_v2(
                _context(), _state(), table
            ),
        },
        sort_keys=True,
    )
    reloaded = json.loads(blob)
    assert (
        reloaded["binding_table_id"]
        == build_integration_binding_table(_context(), _state()).binding_table_id
    )
    # the reloaded raw proposal re-resolves to the same canonical hash
    raw_again = SupervisorIntegrationDecisionV2.model_validate(
        reloaded["raw_model_proposal_v2"]
    )
    canonical_again, record_again = resolve_integration_proposal_v2(
        raw_again, table, _context(), _state()
    )
    assert canonical_again.decision_hash() == canonical.decision_hash()
    assert record_again.model_dump() == record.model_dump()


# ---------------------------------------------------------------------------
# plan v2 resolution
# ---------------------------------------------------------------------------


def _plan_pack():
    return SupervisorPlanningContextPack(
        task_id=TASK,
        investigation_id=INV,
        run_id=RUN,
        state_revision=1,
        state_hash=STATE_HASH,
        attention_policy_version="attention-policy:test",
        attention_hash="c" * 64,
        attention_items=(
            AttentionItemDigest(
                item_id="question:q-1",
                band="p1_investigate",
                eligibility="eligible",
                title="q-1",
                related_question_ids=("q-1",),
                eligible_action_types=("delegate_source",),
            ),
        ),
        question_index=(
            QuestionIndexEntry(question_id="q-1", status="open"),
        ),
        source_scope_ids=("windows",),
    )


def test_plan_v2_resolution_injects_identity_and_attention_hash():
    pack = _plan_pack()
    table = build_plan_binding_table(pack)
    from httpserver.services.investigation.agent_integration_v2 import (
        DelegateInvestigationActionV2,
    )

    decision = SupervisorPlanDecisionV2(
        actions=(
            DelegateInvestigationActionV2(
                attention_handle="A1",
                question_handle="Q1",
                source_scope_id="windows",
            ),
        )
    )
    canonical, record = resolve_plan_proposal_v2(decision, table, pack)
    assert record.ok, record.violations
    assert isinstance(canonical, SupervisorPlanDecisionV1)
    assert canonical.task_id == TASK
    assert canonical.attention_hash == pack.attention_hash
    action = canonical.actions[0]
    assert action.attention_item_id == "question:q-1"
    assert action.question_id == "q-1"
    # the UNCHANGED plan validator re-checks eligibility on the RESOLVED
    # values: a valid plan now passes; an unknown handle would already
    # have failed resolution (HANDLE_UNKNOWN) — fail-closed either way.
    validation = SupervisorPlanDecisionValidator().validate(pack, canonical)
    assert validation.valid, validation.codes


# ---------------------------------------------------------------------------
# orchestrator wiring (v2 branch end-to-end, real gates, fake supervisor)
# ---------------------------------------------------------------------------


class _V2Supervisor:
    """Plan/integrate v2 supervisor: returns REAL v2 decisions built from
    the actual binding tables (no LLM)."""

    def __init__(self):
        self.plan_tables = []
        self.integration_tables = []

    async def plan_v2(self, planning_context, table):
        from httpserver.services.investigation.agent_integration_v2 import (
            DelegateInvestigationActionV2,
        )

        self.plan_tables.append(table)
        item = next(
            b
            for b in table.bindings
            if b.kind is BindingKind.attention_item
            and b.canonical_ref.startswith("question:")
        )
        question = next(
            b
            for b in table.bindings
            if b.kind is BindingKind.question
        )
        return SupervisorPlanDecisionV2(
            actions=(
                DelegateInvestigationActionV2(
                    attention_handle=item.handle,
                    question_handle=question.handle,
                    source_scope_id="windows",
                ),
            ),
        )

    async def integrate_v2(self, context, table, state):
        from httpserver.services.investigation.agent_integration_v2 import (
            UpdateQuestionActionV2,
        )

        self.integration_tables.append(table)
        question = next(
            b
            for b in table.bindings
            if b.kind is BindingKind.question
        )
        # NOTE: basis_handles deliberately omitted (keeps current value).
        # The synthetic environment has no real task evidence store, so a
        # basis ref would fail the UNCHANGED evidence resolver — which is
        # exactly the fail-closed behaviour under test elsewhere (§31).
        return SupervisorIntegrationDecisionV2(
            actions=(
                UpdateQuestionActionV2(
                    question_handle=question.handle,
                    to_status=QuestionStatus.in_progress,
                ),
            ),
            integration_summary="advance question",
        )


class _SlimDispatcher:
    """Persists a minimal valid SpecialistResult and reports completed."""

    def __init__(self, repo):
        self._repo = repo

    async def __call__(self, planning_context, decision, admitted):
        from httpserver.services.investigation.agent_orchestrator import (
            DelegationExecutionSummary,
        )
        from httpserver.services.investigation.agent_specialist_result import (
            SpecialistResultV1,
        )

        summaries = []
        for delegation, action in zip(admitted, decision.delegate_actions()):
            result = SpecialistResultV1(
                delegation_id=delegation.delegation_id,
                summary="logon cluster observed",
                claim_candidates=(
                    {
                        "candidate_id": "c-1",
                        "text": "logon cluster observed",
                        "assertion_class": "INFERENCE",
                        "evidence_refs": [E1_KEY],
                        "limitations": [],
                    },
                ),
                execution_digest={
                    "tool_call_count": 1,
                    "observation_count": 1,
                },
            )
            self._repo.start_delegation(delegation.delegation_id)
            self._repo.complete_delegation_with_result(
                delegation.delegation_id,
                result_version="specialist-result:v1",
                result=result.model_dump(mode="json"),
                result_hash=result.result_hash(),
                context_hash="ctx-test",
            )
            summaries.append(
                DelegationExecutionSummary(
                    delegation_id=delegation.delegation_id,
                    question_id=action.question_id,
                    source_scope_id=action.source_scope_id,
                    status="completed",
                    result=result,
                    result_hash=result.result_hash(),
                    context_hash="ctx-test",
                )
            )
        return summaries


@pytest.mark.migration_matrix
async def test_orchestrator_v2_branch_commits_through_real_gates(tmp_path):
    from httpserver.services.investigation.agent_orchestrator import (
        AgentOrchestrator,
    )
    from httpserver.services.investigation.agent_runtime import (
        AgentRuntimeRepository,
    )
    from httpserver.services.investigation.repository import (
        InvestigationRepository,
    )
    from httpserver.services.investigation.agent_working_state import (
        working_state_to_json,
    )

    db = tmp_path / "investigation.db"
    store = InvestigationRepository(db, TASK)
    repo = AgentRuntimeRepository(store)
    investigation, _ = repo.create_investigation(
        working_state_to_json(_state()),
        investigation_id=INV,
    )
    investigation_id = investigation.investigation_id

    class _Backend:
        async def get_task(self, task_id, **kwargs):
            return {
                "id": task_id,
                "status": "done",
                "image_name": "disk.E01",
                "output_files_db": str(tmp_path / "files.db"),
                "output_events_db": str(tmp_path / "events.db"),
            }

    supervisor = _V2Supervisor()
    orchestrator = AgentOrchestrator(
        _Backend(),
        supervisor=supervisor,
        delegation_dispatcher=_SlimDispatcher(repo),
        source_scope_provider=lambda task_id: ("windows",),
        supervisor_contract_version="v2",
    )
    outcomes = await orchestrator.run_loop(TASK, investigation_id)
    assert outcomes, "expected at least one cycle outcome"
    committed = [
        o for o in outcomes if o.integration_status == "committed"
    ]
    assert committed, [
        (o.integration_status, o.integration_violation_codes)
        for o in outcomes
    ]
    # audit provenance: plan + integration binding tables recorded
    assert len(supervisor.plan_tables) >= 1
    assert len(supervisor.integration_tables) >= 1
    # the resolved transition landed in the working state
    latest = repo.get_latest_working_state(investigation_id)
    in_progress = [q for q in latest.state["questions"]
                   if q["status"] == "in_progress"]
    assert in_progress
    # trajectory carries the v2 contract provenance on the integration
    events = [
        e for e in repo.list_trajectory(investigation_id)
        if e.event_type.value == "supervisor_integration_committed"
    ]
    assert events
    committed_payload = events[0].payload or {}
    committed_decision = committed_payload.get("decision") or {}
    assert committed_decision.get("integration_contract_version") == "v2"
    assert committed_decision.get("binding_table_id", "").startswith("rbt:")
    assert committed_decision.get("resolution_record", {}).get("ok") is True
    assert "raw_model_proposal_v2" in committed_decision
