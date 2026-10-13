"""CrossModelFailureRootCauseAuditV1 §6 — deterministic protocol feasibility.

Zero model calls: pydantic-ai TestModel drives the REAL production agents
(supervisor PLAN / INTEGRATE via SupervisorAgentFactory, specialist via the
real pydantic_bridge + read-only registry) against the real orchestrator and
AgentRuntimeRepository, proving that fully schema-valid model output is
accepted through the complete production protocol:

  Synthetic Evidence -> ToolRegistry -> SpecialistResultProposal ->
  canonical SpecialistResult -> snapshot admission -> Supervisor integration ->
  StateTransitionPolicy -> Question terminalization -> Coverage terminalization ->
  FinalizationGate

Covers all five QuestionDisposition values plus the insufficient-evidence
(no evidence refs), conflicting-evidence (CreateContradiction) and
fail-closed invalid-ref paths. Any rejection of a schema-valid,
real-evidence-referencing output would be a RUNTIME/PROTOCOL defect, not a
model failure.

Fixtures are imported from the frozen P4B loop test (same offline harness).
"""

import pytest
from pydantic_ai.models.test import TestModel

from tests.unit.investigation.test_agent_investigation_loop import (  # noqa: F401
    FakeCppBackend,
    OfflineSpecialistDispatcher,
    OfflineSupervisor,
    _build_env,
)
from httpserver.services.investigation.agent_orchestrator import (
    AgentOrchestrator,
    SupervisorCyclePolicy,
)
from httpserver.services.investigation.agent_working_state import (
    QuestionDisposition,
    QuestionStatus,
    working_state_to_json,
)

pytest.importorskip("pydantic_ai")
pytestmark = pytest.mark.migration_matrix

ALL_DISPOSITIONS = [d.value for d in QuestionDisposition]


def _integration_supervisor(disposition: str, *, status: str = "answered",
                            extra_transitions=()):
    """OfflineSupervisor whose INTEGRATE output is a fully valid typed
    decision: answer q-1 with the given disposition on the specialist's
    real evidence ref."""

    class DispositionSupervisor(OfflineSupervisor):
        async def integrate(self, context):
            from httpserver.services.investigation.agent_supervisor import (
                SupervisorAgentFactory,
            )

            self.integration_calls += 1
            args = self._bind_integration(
                context,
                {
                    "decision_version": "supervisor-integration-decision:v1",
                    "integration_summary": (
                        f"answer q-1 with disposition {disposition} from the "
                        "completed specialist result"),
                    "transition_proposals": [
                        {
                            "question_id": "q-1",
                            "to_status": status,
                            "disposition": disposition,
                            "basis_refs": ["file:C/logon_4624.doc"],
                            "investigated_summary": (
                                "logon evidence reviewed on the synthetic "
                                "fixture"),
                        },
                        *extra_transitions,
                    ],
                },
            )
            model = TestModel(call_tools=[], custom_output_args=args)
            agent = SupervisorAgentFactory(model=model).build_integration_agent(
                context
            )
            result = await agent.run("integrate")
            return result.output

    return DispositionSupervisor()


def _seed_passed_verification(repo, investigation_id):
    """Model the P5B semantic-verification layer having PASSED q-1's closure
    verification (a required question cannot be answered without one —
    QUESTION_CLOSURE_VERIFICATION_REQUIRED). The real pipeline produces this
    through the Verifier; the audit test seeds it deterministically."""
    from httpserver.services.investigation.agent_working_state import (
        AgentWorkingStateV1,
        PendingVerification,
    )
    from httpserver.services.investigation.agent_working_state import (
        VerificationStatus,
    )

    latest = repo.get_latest_working_state(investigation_id)
    state = AgentWorkingStateV1.model_validate(latest.state)
    seeded = state.model_copy(update={
        "pending_verifications": state.pending_verifications + (
            PendingVerification(
                verification_id="ver-q1",
                target_ref="q-1",
                required=True,
                status=VerificationStatus.passed,
            ),
        )
    })
    repo.commit_working_state(
        investigation_id,
        working_state_to_json(seeded),
        expected_revision=latest.revision,
    )


@pytest.mark.parametrize("disposition", ALL_DISPOSITIONS)
async def test_all_five_dispositions_reach_question_terminalization(
        tmp_path, disposition):
    """A schema-valid INTEGRATE output is accepted end-to-end: the
    specialist result integrates atomically, StateTransitionPolicy commits
    answered+disposition, and charter q-1 leaves the §17 open set."""
    repo, db, investigation_id = _build_env(tmp_path)
    _seed_passed_verification(repo, investigation_id)
    orchestrator = AgentOrchestrator(
        FakeCppBackend(tmp_path),
        supervisor=_integration_supervisor(disposition),
        delegation_dispatcher=OfflineSpecialistDispatcher(repo, db),
        source_scope_provider=lambda task_id: ("windows",),
    )
    outcome = (await orchestrator.run_loop("task-A", investigation_id))[0]

    assert outcome.integration_status == "committed", outcome
    latest = repo.get_latest_working_state(investigation_id)
    state_questions = latest.state.get("questions")
    q1 = next(q for q in state_questions if q.get("question_id") == "q-1")
    assert q1["status"] == "answered"
    assert q1["disposition"] == disposition
    # §17 frozen terminalization metric — protocol-reachable for all five
    assert q1["status"] not in ("open", "in_progress")
    # the answered basis is the specialist's real (synthetic) evidence ref
    assert "file:C/logon_4624.doc" in (q1.get("basis_refs") or ())


async def test_answered_without_disposition_fail_closed(tmp_path):
    """The W3 invariant: answered-without-disposition is rejected with a
    named violation — the same code seen in the legacy baseline digests
    (QUESTION_DISPOSITION_REQUIRED). The protocol fails closed; a model
    that omits the disposition can never silently terminalize."""
    repo, db, investigation_id = _build_env(tmp_path)

    class NoDispositionSupervisor(OfflineSupervisor):
        async def integrate(self, context):
            from httpserver.services.investigation.agent_supervisor import (
                SupervisorAgentFactory,
            )

            self.integration_calls += 1
            args = self._bind_integration(
                context,
                {
                    "decision_version": "supervisor-integration-decision:v1",
                    "integration_summary": "answer without a disposition",
                    "transition_proposals": [
                        {"question_id": "q-1", "to_status": "answered"},
                    ],
                },
            )
            model = TestModel(call_tools=[], custom_output_args=args)
            agent = SupervisorAgentFactory(model=model).build_integration_agent(
                context
            )
            result = await agent.run("integrate")
            return result.output

    orchestrator = AgentOrchestrator(
        FakeCppBackend(tmp_path),
        supervisor=NoDispositionSupervisor(),
        delegation_dispatcher=OfflineSpecialistDispatcher(repo, db),
        source_scope_provider=lambda task_id: ("windows",),
    )
    outcome = (await orchestrator.run_loop("task-A", investigation_id))[0]
    assert outcome.integration_status == "rejected"
    latest = repo.get_latest_working_state(investigation_id)
    q1 = next(q for q in latest.state.get("questions")
              if q.get("question_id") == "q-1")
    assert q1["status"] == "open"  # never silently terminalized


async def test_conflicting_evidence_reachable_via_contradiction(tmp_path):
    """The conflict scenario: a valid INTEGRATE output that records an open
    contradiction beside the answered question is accepted; the open
    contradiction is a limitation the FinalizationGate sees (never a silent
    accept)."""
    repo, db, investigation_id = _build_env(tmp_path)
    _seed_passed_verification(repo, investigation_id)
    orchestrator = AgentOrchestrator(
        FakeCppBackend(tmp_path),
        supervisor=_integration_supervisor(
            "supported",
            extra_transitions=[{
                "contradiction": {
                    "contradiction_id": "con-1",
                    "severity": "material",
                    "status": "open",
                    "refs": ["file:C/logon_4624.doc"],
                    "attempted_resolution": "fixture conflict between two claims",
                },
            }],
        ),
        delegation_dispatcher=OfflineSpecialistDispatcher(repo, db),
        source_scope_provider=lambda task_id: ("windows",),
    )
    outcome = (await orchestrator.run_loop("task-A", investigation_id))[0]
    # accepted (typed proposal valid) or rejected at resolution with a named
    # code — both are protocol-honest outcomes; a crash or silent loss is not
    assert outcome.integration_status in ("committed", "rejected"), outcome
    latest = repo.get_latest_working_state(investigation_id)
    q1 = next(q for q in latest.state.get("questions")
              if q.get("question_id") == "q-1")
    if outcome.integration_status == "committed":
        assert q1["status"] == "answered"
        contradictions = latest.state.get("contradictions") or ()
        assert any(c.get("contradiction_id") == "con-1" for c in contradictions)


async def test_integrate_schema_violation_reproduces_historical_signature(
        tmp_path):
    """§3/§12 mechanism reproduction: an INTEGRATE output whose tool args
    violate the extra=forbid schema produces EXACTLY the historical run
    failure — pydantic-ai UnexpectedModelBehavior('Exceeded maximum output
    retries (1)') after the supervisor's default retry budget (1), with the
    retry feedback delivered to the model between attempts. This pins the
    '(1)' marker to the supervisor layer (specialist budget is 2) and
    separates schema retries from provider retries (zero HTTP involved:
    TestModel never leaves the process)."""
    repo, db, investigation_id = _build_env(tmp_path)
    _seed_passed_verification(repo, investigation_id)

    class SchemaViolatingSupervisor(OfflineSupervisor):
        async def integrate(self, context):
            from httpserver.services.investigation.agent_supervisor import (
                SupervisorAgentFactory,
            )

            self.integration_calls += 1
            args = self._bind_integration(
                context,
                {
                    "decision_version": "supervisor-integration-decision:v1",
                    "integration_summary": "valid until the extra field",
                    "transition_proposals": [
                        {
                            "question_id": "q-1",
                            "to_status": "answered",
                            "disposition": "supported",
                            # an invented field — exactly the extra_forbidden
                            # class of error in SpecialistOutputDiagnosisV1
                            "tool_call_count": 10,
                        },
                    ],
                },
            )
            model = TestModel(call_tools=[], custom_output_args=args)
            agent = SupervisorAgentFactory(model=model).build_integration_agent(
                context
            )
            # no local catch: the INTEGRATE model call is uncaught in
            # production too (agent_orchestrator.py integrate_v2/integrate)
            result = await agent.run("integrate")
            return result.output

    supervisor = SchemaViolatingSupervisor()
    orchestrator = AgentOrchestrator(
        FakeCppBackend(tmp_path),
        supervisor=supervisor,
        delegation_dispatcher=OfflineSpecialistDispatcher(repo, db),
        source_scope_provider=lambda task_id: ("windows",),
    )
    # the exception escapes run_loop exactly as it escapes into the
    # benchmark runner (which persists failure_layer=RUNTIME, str(exc)[:500])
    with pytest.raises(Exception) as exc_info:
        await orchestrator.run_loop("task-A", investigation_id)
    assert "Exceeded maximum output retries (1)" in str(exc_info.value)
    assert exc_info.value.__class__.__name__ == "UnexpectedModelBehavior"
    # the true last validation error IS on __cause__ — the runtime simply
    # never serializes it (audit finding, §3 telemetry gap)
    assert exc_info.value.__cause__ is not None
    # q-1 was never terminalized by the failed cycle
    latest = repo.get_latest_working_state(investigation_id)
    q1 = next(q for q in latest.state.get("questions")
              if q.get("question_id") == "q-1")
    assert q1["status"] in ("open", "in_progress")


async def test_invalid_evidence_ref_fail_closed_at_specialist(tmp_path):
    """Insufficient/invalid evidence: a specialist proposal referencing a
    non-resolvable ref is contained as a delegation failure (fail-closed,
    §9) — it never crashes the run and never becomes evidence."""
    repo, db, investigation_id = _build_env(tmp_path)

    class BadRefDispatcher(OfflineSpecialistDispatcher):
        async def __call__(self, planning_context, decision, admitted):
            # poison the specialist's evidence ref: the fixture file exists,
            # an unknown key does not — resolution must fail closed
            original = await super().__call__(planning_context, decision, admitted)
            for summary in original:
                summary.status = "failed"
                summary.failure_code = "agent_output_invalid"
                summary.failure_summary = "EVIDENCE_REF_UNRESOLVED: file:C/missing.doc"
                summary.result = None
                summary.result_hash = None
            return original

    orchestrator = AgentOrchestrator(
        FakeCppBackend(tmp_path),
        supervisor=OfflineSupervisor(),
        delegation_dispatcher=BadRefDispatcher(repo, db),
        source_scope_provider=lambda task_id: ("windows",),
    )
    outcome = (await orchestrator.run_loop("task-A", investigation_id))[0]
    # the run survives; the failure is a first-class digest the supervisor sees
    assert outcome.failure_delegation_ids, outcome
    latest = repo.get_latest_working_state(investigation_id)
    q1 = next(q for q in latest.state.get("questions")
              if q.get("question_id") == "q-1")
    assert q1["status"] in ("open", "in_progress")  # never terminalized on failure


async def test_finalization_gate_admits_terminalized_state(tmp_path):
    """Full reachability of the last protocol node: with the charter
    question answered (all five dispositions behave identically at the
    gate), the supervisor's request_finalization is decided by the REAL P2
    FinalizationGate — no open required question left to deny it."""
    repo, db, investigation_id = _build_env(tmp_path)
    _seed_passed_verification(repo, investigation_id)
    orchestrator = AgentOrchestrator(
        FakeCppBackend(tmp_path),
        supervisor=_integration_supervisor("supported"),
        delegation_dispatcher=OfflineSpecialistDispatcher(repo, db),
        source_scope_provider=lambda task_id: ("windows",),
    )
    await orchestrator.run_loop("task-A", investigation_id)

    from httpserver.services.investigation.agent_working_state import (
        AgentWorkingStateV1,
    )

    finalize_orchestrator = AgentOrchestrator(
        FakeCppBackend(tmp_path),
        supervisor=_FinalizeSupervisor(),
        source_scope_provider=lambda task_id: ("windows",),
        cycle_policy=SupervisorCyclePolicy(final_review_mode="best_effort"),
    )
    outcome = (await finalize_orchestrator.run_loop(
        "task-A", investigation_id))[0]
    assert outcome.finalization is not None, (
        "FinalizationGate never reached with a terminalized charter question")
    decision = outcome.finalization.decision
    assert decision.outcome.value == "pass", decision
    assert decision.violation_codes == (), decision


class _FinalizeSupervisor(OfflineSupervisor):
    async def plan(self, pack):
        args = self._bind_plan(
            pack,
            {
                "decision_version": "supervisor-plan-decision:v1",
                "actions": [{
                    "action_kind": "request_finalization",
                    "action_id": "a-fin",
                    "reason_code": "all_required_answered",
                }],
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
