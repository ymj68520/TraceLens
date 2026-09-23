"""P4B-1 tests: supervisor planning context, structured PLAN decision,
deterministic validation, and the atomic decision+admission commit."""

import json

import pytest
from pydantic import ValidationError

from httpserver.services.investigation.agent_attention import AttentionBuilder
from httpserver.services.investigation.agent_runtime import (
    AgentRuntimeRepository,
    AgentTrajectoryEventType,
    DelegationSpec,
)
from httpserver.services.investigation.agent_supervisor import (
    PLAN_PHASE_CAPABILITIES,
    DelegateInvestigation,
    NoPlanAction,
    RequestFinalization,
    SupervisorPlanDecisionV1,
    SupervisorPlanDecisionValidator,
    build_supervisor_planning_context,
)
from httpserver.services.investigation.agent_working_state import (
    working_state_to_json,
)
from httpserver.services.investigation.repository import (
    SUPPORTED_SCHEMA_VERSION,
    InvestigationRepository,
)

pytestmark = pytest.mark.migration_matrix


def _state(repo, investigation_id):
    from httpserver.services.investigation.agent_working_state import (
        working_state_from_json,
    )

    latest = repo.get_latest_working_state(investigation_id)
    return working_state_from_json("task-A", investigation_id, latest.state), latest


def _state_with_question(repo, investigation_id, question_id="q-1"):
    from httpserver.services.investigation.agent_working_state import (
        QuestionPriority,
        QuestionSource,
        WorkingQuestion,
        working_state_from_json,
    )

    latest = repo.get_latest_working_state(investigation_id)
    state = working_state_from_json("task-A", investigation_id, latest.state)
    question = WorkingQuestion(
        question_id=question_id,
        text="Were there unauthorized logons?",
        source=QuestionSource.charter,
        priority=QuestionPriority.required,
    )
    updated = state.model_copy(update={"questions": (question,)})
    revision = repo.commit_working_state(
        investigation_id,
        working_state_to_json(updated),
        expected_revision=latest.revision,
    )
    return updated, revision


@pytest.fixture()
def env(tmp_path):
    from httpserver.services.investigation.agent_working_state import (
        AgentWorkingStateV1,
        working_state_to_json,
    )
    from httpserver.services.investigation.agent_runtime import (
        _new_investigation_id,
    )

    db = tmp_path / "investigation.db"
    store = InvestigationRepository(db, "task-A")
    repo = AgentRuntimeRepository(store)
    investigation_id = _new_investigation_id()
    initial = AgentWorkingStateV1(
        task_id="task-A",
        investigation_id=investigation_id,
        objective="p4b",
    )
    investigation, _rev = repo.create_investigation(
        working_state_to_json(initial),
        investigation_id=investigation_id,
    )
    run = repo.start_run(investigation.investigation_id)
    repo.mark_run_running(run.run_id)
    return repo, investigation.investigation_id, run.run_id


def _planning_context(repo, investigation_id, run_id, *, state=None, revision=None):
    state_obj, latest = _state(repo, investigation_id)
    attention = AttentionBuilder().build_full_set(
        state_obj, state_revision=latest.revision
    )
    return build_supervisor_planning_context(
        state_obj,
        state_revision=latest.revision,
        state_hash=latest.state_hash,
        attention_set=attention,
        task_id="task-A",
        run_id=run_id,
        source_scope_ids=("windows",),
    )


def _decision(pack, question_id="q-1", **overrides) -> SupervisorPlanDecisionV1:
    fields = dict(
        task_id=pack.task_id,
        investigation_id=pack.investigation_id,
        run_id=pack.run_id,
        based_on_state_revision=pack.state_revision,
        based_on_state_hash=pack.state_hash,
        attention_hash=pack.attention_hash,
        actions=(),
    )
    fields.update(overrides)
    return SupervisorPlanDecisionV1(**fields)


# ---------------------------------------------------------------------------
# planning context (P4B-E4)
# ---------------------------------------------------------------------------


def test_planning_context_deterministic_and_bound(env):
    repo, investigation_id, run_id = env
    first = _planning_context(repo, investigation_id, run_id)
    second = _planning_context(repo, investigation_id, run_id)
    assert first.input_hash() == second.input_hash()
    assert first.context_version == "supervisor-planning-context:v1"
    assert first.phase_capabilities == PLAN_PHASE_CAPABILITIES
    assert first.state_revision >= 1


def test_planning_context_changes_with_state(env):
    repo, investigation_id, run_id = env
    before = _planning_context(repo, investigation_id, run_id)
    _state_with_question(repo, investigation_id)
    after = _planning_context(repo, investigation_id, run_id)
    assert after.input_hash() != before.input_hash()
    assert after.state_revision == before.state_revision + 1


def test_validator_detects_active_questions(env):
    repo, investigation_id, run_id = env
    _state_with_question(repo, investigation_id, "q-1")
    pack = _planning_context(repo, investigation_id, run_id)
    assert any(e.question_id == "q-1" and e.status == "open" for e in pack.question_index)


# ---------------------------------------------------------------------------
# decision validation (P4B-E6, §36)
# ---------------------------------------------------------------------------


def _eligible_decision(pack, question_id="q-1") -> SupervisorPlanDecisionV1:
    item = next(
        item
        for item in pack.attention_items
        if "delegate_source" in item.eligible_action_types
        and item.eligibility == "eligible"
        and item.related_question_ids
    )
    return _decision(
        pack,
        actions=(
            DelegateInvestigation(
                action_id="a-1",
                attention_item_id=item.item_id,
                question_id=question_id,
                source_scope_id="windows",
                investigation_intent="verify logon activity",
            ),
        ),
    )


def test_valid_eligible_item_passes(env):
    repo, investigation_id, run_id = env
    _state_with_question(repo, investigation_id, "q-1")
    pack = _planning_context(repo, investigation_id, run_id)
    validation = SupervisorPlanDecisionValidator().validate(
        pack, _eligible_decision(pack)
    )
    assert validation.valid, validation.codes


def test_stale_state_revision_denied(env):
    repo, investigation_id, run_id = env
    _state_with_question(repo, investigation_id, "q-1")
    pack = _planning_context(repo, investigation_id, run_id)
    decision = _eligible_decision(pack)
    stale = decision.model_copy(
        update={"based_on_state_revision": pack.state_revision + 3}
    )
    validation = SupervisorPlanDecisionValidator().validate(pack, stale)
    assert not validation.valid
    assert "PLAN_STATE_REVISION_STALE" in validation.codes


def test_attention_hash_mismatch_denied(env):
    repo, investigation_id, run_id = env
    _state_with_question(repo, investigation_id, "q-1")
    pack = _planning_context(repo, investigation_id, run_id)
    decision = _eligible_decision(pack)
    drifted = decision.model_copy(update={"attention_hash": "wrong"})
    validation = SupervisorPlanDecisionValidator().validate(pack, drifted)
    assert not validation.valid
    assert "PLAN_ATTENTION_HASH_MISMATCH" in validation.codes


def test_unknown_question_denied(env):
    repo, investigation_id, run_id = env
    _state_with_question(repo, investigation_id, "q-1")
    pack = _planning_context(repo, investigation_id, run_id)
    validation = SupervisorPlanDecisionValidator().validate(
        pack, _eligible_decision(pack, question_id="q-ghost")
    )
    assert not validation.valid
    assert "PLAN_QUESTION_UNKNOWN" in validation.codes


def test_closed_question_denied(env):
    from httpserver.services.investigation.agent_working_state import (
        QuestionDisposition,
        QuestionStatus,
        working_state_from_json,
    )

    repo, investigation_id, run_id = env
    state, revision = _state_with_question(repo, investigation_id, "q-1")
    open_pack = _planning_context(repo, investigation_id, run_id)
    decision = _eligible_decision(open_pack)

    answered = state.questions[0].model_copy(
        update={
            "status": QuestionStatus.answered,
            "disposition": QuestionDisposition.supported,
        }
    )
    closed_state = state.model_copy(update={"questions": (answered,)})
    repo.commit_working_state(
        investigation_id,
        working_state_to_json(closed_state),
        expected_revision=revision.revision,
    )
    # decision stays bound to the old state/attention; the current context
    # no longer carries the question as active -> stale + inactive denials
    closed_pack = _planning_context(repo, investigation_id, run_id)
    validation = SupervisorPlanDecisionValidator().validate(
        closed_pack, decision
    )
    assert not validation.valid
    assert "PLAN_STATE_REVISION_STALE" in validation.codes


def test_cross_scope_proposal_denied(env):
    repo, investigation_id, run_id = env
    _state_with_question(repo, investigation_id, "q-1")
    pack = _planning_context(repo, investigation_id, run_id)
    decision = _eligible_decision(pack)
    item = decision.delegate_actions()[0]
    offscope = DelegateInvestigation(
        action_id="a-2",
        attention_item_id=item.attention_item_id,
        question_id=item.question_id,
        source_scope_id="android",  # not granted
    )
    drifted = decision.model_copy(
        update={"actions": (offscope,)}
    )
    validation = SupervisorPlanDecisionValidator().validate(pack, drifted)
    assert not validation.valid
    assert "PLAN_SOURCE_SCOPE_NOT_ALLOWED" in validation.codes


def test_duplicate_delegation_fingerprint_denied(env):
    repo, investigation_id, run_id = env
    _state_with_question(repo, investigation_id, "q-1")
    pack = _planning_context(repo, investigation_id, run_id)
    decision = _eligible_decision(pack)
    item = decision.delegate_actions()[0]
    duplicated = decision.model_copy(
        update={
            "actions": (
                item,
                DelegateInvestigation(
                    action_id="a-2",
                    attention_item_id=item.attention_item_id,
                    question_id=item.question_id,
                    source_scope_id=item.source_scope_id,
                ),
            )
        }
    )
    validation = SupervisorPlanDecisionValidator().validate(pack, duplicated)
    assert not validation.valid
    assert "PLAN_DUPLICATE_DELEGATION" in validation.codes


def test_unsupported_action_kind_denied(env):
    repo, investigation_id, run_id = env
    pack = _planning_context(repo, investigation_id, run_id)
    decision = _decision(
        pack,
        actions=(
            DelegateInvestigation(
                action_id="a-x",
                attention_item_id="question:q-1",
                question_id="q-1",
                source_scope_id="windows",
            ).model_copy(update={"action_kind": "request_graph_admission"}),
        ),
    )
    validation = SupervisorPlanDecisionValidator().validate(pack, decision)
    assert not validation.valid
    assert "PLAN_ACTION_NOT_ALLOWED" in validation.codes


def test_ineligible_attention_item_denied(env):
    repo, investigation_id, run_id = env
    pack = _planning_context(repo, investigation_id, run_id)
    # no questions exist -> nothing eligible; any delegation must be denied
    bogus = _decision(
        pack,
        actions=(
            DelegateInvestigation(
                action_id="a-1",
                attention_item_id="question:q-1",
                question_id="q-1",
                source_scope_id="windows",
            ),
        ),
    )
    validation = SupervisorPlanDecisionValidator().validate(pack, bogus)
    assert not validation.valid
    assert "PLAN_QUESTION_UNKNOWN" in validation.codes


def test_no_action_and_finalization_require_reason(env):
    repo, investigation_id, run_id = env
    pack = _planning_context(repo, investigation_id, run_id)
    bad_noop = _decision(
        pack, actions=(NoPlanAction(action_id="a-1", reason_code=""),)
    )
    validation = SupervisorPlanDecisionValidator().validate(pack, bad_noop)
    assert not validation.valid
    good_noop = _decision(
        pack,
        actions=(
            NoPlanAction(action_id="a-1", reason_code="attention saturated"),
            RequestFinalization(
                action_id="a-2", reason_code="all_required_answered"
            ),
        ),
    )
    assert SupervisorPlanDecisionValidator().validate(pack, good_noop).valid


def test_decision_hash_deterministic(env):
    repo, investigation_id, run_id = env
    pack = _planning_context(repo, investigation_id, run_id)
    decision = _decision(
        pack,
        actions=(
            NoPlanAction(action_id="a-1", reason_code="waiting"),
        ),
    )
    assert decision.decision_hash() == decision.decision_hash()
    other = decision.model_copy(update={"summary": "x"})
    assert other.decision_hash() != decision.decision_hash()


# ---------------------------------------------------------------------------
# atomic admission (P4B-E7, §37)
# ---------------------------------------------------------------------------


async def test_atomic_plan_commit_persists_decision_and_delegations(env):
    repo, investigation_id, run_id = env
    _state_with_question(repo, investigation_id, "q-1")
    pack = _planning_context(repo, investigation_id, run_id)
    decision = _eligible_decision(pack)
    spec = DelegationSpec(
        question_id="q-1",
        question_ref="q-1",
        based_on_state_revision=pack.state_revision,
        idempotency_key=f"plan:{decision.decision_hash()[:16]}:q-1:windows",
    )
    event, delegations = repo.commit_supervisor_plan(
        run_id,
        decision_payload=decision.model_dump(),
        decision_hash=decision.decision_hash(),
        model_name="offline-model",
        model_config_hash="cfg",
        prompt_version="supervisor-plan:v1",
        usage={"requests": 1},
        specs=[spec],
    )
    assert event.event_type == AgentTrajectoryEventType.supervisor_plan_decided
    assert event.payload["decision_hash"] == decision.decision_hash()
    assert event.payload["decision"]["decision_version"] == "supervisor-plan-decision:v1"
    assert event.payload["model_name"] == "offline-model"
    assert len(delegations) == 1
    assert delegations[0].status.value == "queued"
    # decision and delegation share one durable trace
    trajectory = repo.list_trajectory(investigation_id)
    kinds = [t.event_type for t in trajectory]
    assert AgentTrajectoryEventType.supervisor_plan_decided in kinds
    assert AgentTrajectoryEventType.delegation_admitted in kinds


async def test_plan_commit_replay_is_idempotent(env):
    repo, investigation_id, run_id = env
    _state_with_question(repo, investigation_id, "q-1")
    pack = _planning_context(repo, investigation_id, run_id)
    decision = _eligible_decision(pack)
    spec = DelegationSpec(
        question_ref="q-1",
        based_on_state_revision=pack.state_revision,
        idempotency_key=f"plan:{decision.decision_hash()[:16]}:q-1:windows",
    )
    first_event, first_dels = repo.commit_supervisor_plan(
        run_id,
        decision_payload=decision.model_dump(),
        decision_hash=decision.decision_hash(),
        specs=[spec],
    )
    second_event, second_dels = repo.commit_supervisor_plan(
        run_id,
        decision_payload=decision.model_dump(),
        decision_hash=decision.decision_hash(),
        specs=[spec],
    )
    assert first_event.event_id == second_event.event_id
    assert len(second_dels) == 1
    assert second_dels[0].delegation_id == first_dels[0].delegation_id
    events = [
        t
        for t in repo.list_trajectory(investigation_id)
        if t.event_type == AgentTrajectoryEventType.supervisor_plan_decided
    ]
    assert len(events) == 1


def test_new_event_type_accepted_and_unknown_rejected(env, tmp_path):
    repo, investigation_id, run_id = env
    event = repo.append_trajectory(
        investigation_id,
        AgentTrajectoryEventType.supervisor_integration_committed,
        payload={"note": "v12 accepted"},
    )
    assert event.event_type.value == "supervisor_integration_committed"
    import sqlite3

    conn = sqlite3.connect(str(repo._repo.db_path))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO agent_trajectory_events "
            "(event_id, task_id, investigation_id, event_type, payload_json, created_at) "
            "VALUES ('e', 'task-A', ?, 'made_up_p4b', '{}', 'now')",
            (investigation_id,),
        )
    conn.close()
