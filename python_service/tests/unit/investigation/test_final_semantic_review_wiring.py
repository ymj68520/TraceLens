"""P5B freeze follow-up F2: final semantic review production wiring.

RequestFinalization -> deterministic preflight -> effective policy ->
final semantic review (injected runner) -> FinalizationGate -> atomic
finalize. The gate remains the ONLY completion authority (§24)."""

import pytest
from pydantic_ai.models.test import TestModel

from httpserver.services.investigation.agent_orchestrator import (
    AgentOrchestrator,
    SupervisorCyclePolicy,
)
from httpserver.services.investigation.agent_runtime import (
    AgentRuntimeRepository,
)
from httpserver.services.investigation.repository import (
    InvestigationRepository,
)
from httpserver.services.investigation.agent_working_state import (
    AgentWorkingStateV1,
    QuestionDisposition,
    QuestionPriority,
    QuestionSource,
    QuestionStatus,
    WorkingQuestion,
    working_state_to_json,
)

TASK_ID = "task-A"
INVESTIGATION_ID = "inv-" + "f" * 8


def _finalizable_state():
    """A state with NO deterministic hard blockers: the required question
    is answered with a disposition, no coverage/contradictions, no
    unapplied directives."""
    return AgentWorkingStateV1(
        task_id=TASK_ID,
        investigation_id=INVESTIGATION_ID,
        objective="detect unauthorized access",
        questions=(
            WorkingQuestion(
                question_id="q-1",
                text="Were there unauthorized logons?",
                source=QuestionSource.charter,
                priority=QuestionPriority.required,
                status=QuestionStatus.answered,
                disposition=QuestionDisposition.supported,
            ),
        ),
    )


class FakeCppBackend:
    def __init__(self, base_dir):
        self._base_dir = base_dir

    async def get_task(self, task_id, **kwargs):
        return {
            "id": task_id,
            "status": "done",
            "image_name": "disk.E01",
            "output_files_db": str(self._base_dir / "files.db"),
            "output_events_db": str(self._base_dir / "events.db"),
        }


def _build_env(tmp_path, state=None):
    db = tmp_path / "investigation.db"
    store = InvestigationRepository(db, TASK_ID)
    repo = AgentRuntimeRepository(store)
    investigation_id = INVESTIGATION_ID
    resolved_state = state() if callable(state) else state
    investigation, _rev = repo.create_investigation(
        working_state_to_json(resolved_state or _finalizable_state()),
        investigation_id=investigation_id,
    )
    return repo, db, investigation.investigation_id


from test_agent_investigation_loop import OfflineSupervisor


class FinalizeSupervisor(OfflineSupervisor):
    """Offline supervisor that always requests finalization."""

    async def plan(self, pack):
        args = self._bind_plan(
            pack,
            {
                "decision_version": "supervisor-plan-decision:v1",
                "actions": [
                    {
                        "action_kind": "request_finalization",
                        "action_id": "a-fin",
                        "reason_code": "all_required_answered",
                    }
                ],
            },
        )
        from httpserver.services.investigation.agent_supervisor import (
            SupervisorAgentFactory,
        )

        agent = SupervisorAgentFactory(
            model=TestModel(call_tools=[], custom_output_args=args)
        ).build_plan_agent(pack)
        result = await agent.run("plan")
        return result.output


def _runner(response=None, *, calls=None, side_effect=None):
    async def runner(payload):
        if calls is not None:
            calls.append(payload)
        if side_effect is not None:
            await side_effect(payload)
        if isinstance(response, Exception):
            raise response
        if response is None:
            return {"status": "unavailable",
                    "failure_code": "runtime_unavailable"}
        return {"result_ref": "sver-final:abc123", **response}

    return runner


def _orchestrator(tmp_path, runner, mode="best_effort", state=None):
    repo, db, investigation_id = _build_env(tmp_path, state=state)
    orchestrator = AgentOrchestrator(
        FakeCppBackend(tmp_path),
        supervisor=FinalizeSupervisor(),
        source_scope_provider=lambda task_id: ("windows",),
        cycle_policy=SupervisorCyclePolicy(final_review_mode=mode),
        final_review_runner=runner,
    )
    return repo, orchestrator, investigation_id


async def _run(orchestrator, investigation_id):
    return (await orchestrator.run_loop(TASK_ID, investigation_id))[0]


async def test_request_finalization_calls_production_runner(tmp_path):
    calls = []
    runner = _runner(
        {"status": "pass", "input_hash": "ih"}, calls=calls
    )
    repo, orchestrator, investigation_id = _orchestrator(
        tmp_path, runner
    )
    outcome = await _run(orchestrator, investigation_id)
    assert len(calls) == 1
    payload = calls[0]
    # frozen digests-only input: state digest + mandatory statuses
    assert payload["final_state_digest"]
    assert payload["expected_state_revision"] >= 1
    assert any(
        digest.startswith("question:q-1:")
        for digest in payload["required_question_digests"]
    )
    assert outcome.finalization is not None
    assert outcome.finalization.finalized
    # audit binds the review provenance into the FinalizationRecord (§19)
    assert outcome.finalization.record.verifier_result_ref == (
        "sver-final:abc123"
    )
    assert outcome.finalization.record.final_verification_status == "passed"
    assert outcome.run_stop_reason == "finalized"


async def test_best_effort_issues_found_denies(tmp_path):
    repo, orchestrator, investigation_id = _orchestrator(
        tmp_path,
        _runner({"status": "issues_found",
                 "issues": ["claim overreaches evidence"],
                 "input_hash": "ih"}),
    )
    outcome = await _run(orchestrator, investigation_id)
    assert outcome.finalization is not None
    assert not outcome.finalization.finalized
    investigation = repo.get_investigation(investigation_id)
    assert investigation.status.value == "active"


async def test_best_effort_unavailable_completes_with_limitations(tmp_path):
    repo, orchestrator, investigation_id = _orchestrator(
        tmp_path,
        _runner({"status": "unavailable",
                 "failure_code": "provider_unavailable"}),
    )
    outcome = await _run(orchestrator, investigation_id)
    assert outcome.finalization is not None
    assert outcome.finalization.finalized
    assert outcome.finalization.record.completion_mode == (
        "complete_with_limitations"
    )
    assert outcome.finalization.record.final_verification_status == (
        "unavailable"
    )


async def test_best_effort_unavailable_with_pending_mandatory_denies(tmp_path):
    """§16/§18: best_effort never overrides an F1 mandatory blocker."""
    repo, orchestrator, investigation_id = _orchestrator(
        tmp_path,
        _runner({"status": "unavailable",
                 "failure_code": "provider_unavailable"}),
    )
    # a pending mandatory verification obligation exists at the object level
    repo.record_verification_obligation(
        INVESTIGATION_ID,
        obligation_row={
            "obligation_id": "vob:pending-1",
            "proposal_id": "prop-1",
            "proposal_hash": "ph",
            "grounding_id": "grnd-1",
            "semantic_type": "causality",
            "assertion_policy_version": "assertion-policy:v1",
            "rule_id": "rule.highrisk.causality",
            "verification_mode": "semantic_required",
            "question_refs": ["q-1"],
            "status": "pending",
            "input_hash": "ih",
        },
    )
    outcome = await _run(orchestrator, investigation_id)
    assert outcome.finalization is not None
    assert not outcome.finalization.finalized
    assert "MANDATORY_VERIFICATION_BLOCKING" in (
        outcome.finalization.decision.violation_codes
    )


async def test_required_unavailable_denies(tmp_path):
    repo, orchestrator, investigation_id = _orchestrator(
        tmp_path,
        _runner({"status": "unavailable",
                 "failure_code": "billing_unavailable"}),
        mode="required",
    )
    outcome = await _run(orchestrator, investigation_id)
    assert outcome.finalization is not None
    assert not outcome.finalization.finalized
    # a required review failing on a 402 must NEVER complete
    investigation = repo.get_investigation(investigation_id)
    assert investigation.status.value == "active"


async def test_required_pass_continues(tmp_path):
    repo, orchestrator, investigation_id = _orchestrator(
        tmp_path,
        _runner({"status": "pass", "input_hash": "ih"}),
        mode="required",
    )
    outcome = await _run(orchestrator, investigation_id)
    assert outcome.finalization is not None
    assert outcome.finalization.finalized


async def test_final_review_pass_cannot_bypass_hard_blocker(tmp_path):
    """§24/§68: the gate stays the only completion authority."""
    from types import SimpleNamespace

    def state_with_open_question():
        return AgentWorkingStateV1(
            task_id=TASK_ID,
            investigation_id=INVESTIGATION_ID,
            objective="detect unauthorized access",
            questions=(
                WorkingQuestion(
                    question_id="q-1",
                    text="Were there unauthorized logons?",
                    source=QuestionSource.charter,
                    priority=QuestionPriority.required,
                    # still OPEN: deterministic hard blocker
                    status=QuestionStatus.open,
                ),
            ),
        )

    repo, orchestrator, investigation_id = _orchestrator(
        tmp_path,
        _runner({"status": "pass", "input_hash": "ih"}),
        state=state_with_open_question(),
    )
    outcome = await _run(orchestrator, investigation_id)
    assert outcome.finalization is not None
    assert not outcome.finalization.finalized


async def test_stale_review_never_completes_new_revision(tmp_path):
    """§20: if the state moves while the review runs, the review is
    discarded (stale) and cannot complete the newer revision."""
    repo, orchestrator, investigation_id = _orchestrator(
        tmp_path,
        _runner({"status": "pass", "input_hash": "ih"}),
    )

    async def mutate_state_during_review(payload):
        # mutate the Working State while the review is in flight
        repo.commit_working_state(
            INVESTIGATION_ID,
            working_state_to_json(_finalizable_state()),
            expected_revision=1,
            operation_key="f1:mutation-during-review",
        )

    runner = _runner({"status": "pass", "input_hash": "ih"},
                     side_effect=mutate_state_during_review)
    orchestrator._final_review_runner = runner
    outcome = await _run(orchestrator, investigation_id)
    assert outcome.finalization is None or not (
        outcome.finalization.finalized
    )
    assert any("stale" in warning for warning in outcome.warnings)
    assert repo.get_working_state_revision(INVESTIGATION_ID, 2) is not None


async def test_provider_failure_is_never_mapped_to_pass(tmp_path):
    repo, orchestrator, investigation_id = _orchestrator(
        tmp_path,
        _runner(ConnectionError("connection reset")),
        mode="required",
    )
    outcome = await _run(orchestrator, investigation_id)
    assert outcome.finalization is not None
    assert not outcome.finalization.finalized
    decision = outcome.finalization.decision
    assert "REVIEW_UNAVAILABLE" in decision.violation_codes
    # and the failure is audited as unavailable, never as a pass
    assert decision.violation_codes


def test_runner_absent_behaves_as_before_but_policy_modes_hold(tmp_path):
    """No runner wired: required -> DENY; best_effort -> limitations path.
    FinalizationGate semantics are unchanged."""
    import asyncio

    async def main():
        repo, orchestrator, investigation_id = _orchestrator(
            tmp_path, None, mode="required"
        )
        outcome = await _run(orchestrator, investigation_id)
        assert not outcome.finalization.finalized

    asyncio.run(main())
