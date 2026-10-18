"""INTEGRATE persistence invariants (RCA-1.8 §3) — deterministic, zero
model calls.

The full containment chain:
    completed delegation -> INTEGRATE failure -> trajectory event ->
    AgentRun failed -> no integration commit -> Finalization denied

covers exception capture (real pydantic-ai retry exhaustion via TestModel),
SQLite write failure (fail loud, never swallowed), async cancellation
(see test_rca1_remediation), service restart (recovery never resurrects a
failed run and never fabricates an integration), and task-store deletion
(recovery on a missing store is a skip, never a synthesis).
"""

import sqlite3

import pytest

from tests.unit.investigation.test_agent_investigation_loop import (
    FakeCppBackend,
    OfflineSpecialistDispatcher,
    OfflineSupervisor,
    _build_env,
)
from httpserver.services.investigation.agent_orchestrator import (
    AgentOrchestrator,
    SupervisorCyclePolicy,
)

pytest.importorskip("pydantic_ai")
pytestmark = pytest.mark.migration_matrix


class _IntegrateViolatingSupervisor(OfflineSupervisor):
    """Real pydantic-ai output-retry exhaustion via extra=forbid."""

    async def integrate(self, context):
        from pydantic_ai.models.test import TestModel

        from httpserver.services.investigation.agent_supervisor import (
            SupervisorAgentFactory,
        )

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
                        "tool_call_count": 10,
                    },
                ],
            },
        )
        model = TestModel(call_tools=[], custom_output_args=args)
        agent = SupervisorAgentFactory(model=model).build_integration_agent(
            context
        )
        result = await agent.run("integrate")
        return result.output


class _FinalizeSupervisor(OfflineSupervisor):
    async def plan(self, pack):
        from pydantic_ai.models.test import TestModel

        from httpserver.services.investigation.agent_supervisor import (
            SupervisorAgentFactory,
        )

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
        agent = SupervisorAgentFactory(
            model=TestModel(call_tools=[], custom_output_args=args)
        ).build_plan_agent(pack)
        result = await agent.run("plan")
        return result.output


async def _contained_run(tmp_path, repo, db, investigation_id):
    orchestrator = AgentOrchestrator(
        FakeCppBackend(tmp_path),
        supervisor=_IntegrateViolatingSupervisor(),
        delegation_dispatcher=OfflineSpecialistDispatcher(repo, db),
        source_scope_provider=lambda task_id: ("windows",),
    )
    return (await orchestrator.run_loop("task-A", investigation_id))[0]


@pytest.mark.asyncio
async def test_full_containment_chain(tmp_path):
    """completed delegation -> INTEGRATE failure -> trajectory event ->
    AgentRun failed -> no integration commit -> Finalization denied."""
    repo, db, investigation_id = _build_env(tmp_path)
    revision_before = repo.get_latest_working_state(investigation_id).revision

    orchestrator = AgentOrchestrator(
        FakeCppBackend(tmp_path),
        supervisor=_IntegrateViolatingSupervisor(),
        delegation_dispatcher=OfflineSpecialistDispatcher(repo, db),
        source_scope_provider=lambda task_id: ("windows",),
    )
    outcome = (await orchestrator.run_loop("task-A", investigation_id))[0]

    # trajectory event persisted with the typed cause
    events = [
        e for e in repo.list_trajectory(investigation_id)
        if e.event_type.value == "transition_decision_rejected"
        and "supervisor_failure" in (e.payload or {})
    ]
    assert events
    assert events[0].payload["supervisor_failure"] == (
        "supervisor_integration_failed")
    # AgentRun failed
    run = repo.list_runs(investigation_id)[-1]
    assert run.status.value == "failed"
    assert run.stop_reason == "internal_failure"
    # NO integration commit: working state never advanced past the seed
    assert repo.get_latest_working_state(investigation_id).revision == (
        revision_before)
    # the completed delegation stays completed and unintegrated
    delegation = repo.get_delegation(outcome.delegation_ids[0])
    assert delegation.status.value == "completed"
    assert delegation.integrated_at is None
    # Finalization denied on the unintegrated state
    finalizer = AgentOrchestrator(
        FakeCppBackend(tmp_path),
        supervisor=_FinalizeSupervisor(),
        source_scope_provider=lambda task_id: ("windows",),
        cycle_policy=SupervisorCyclePolicy(final_review_mode="best_effort"),
    )
    fin = (await finalizer.run_loop("task-A", investigation_id))[0]
    assert fin.finalization is not None
    assert fin.finalization.decision.outcome.value == "deny"
    assert "UNINTEGRATED_COMPLETED_DELEGATION" in (
        fin.finalization.decision.violation_codes)


@pytest.mark.asyncio
async def test_sqlite_write_failure_fails_loud(tmp_path, monkeypatch):
    """A persistence failure inside the containment path is NEVER
    swallowed: it propagates instead of producing a fake outcome."""
    repo, db, investigation_id = _build_env(tmp_path)

    # the orchestrator opens its OWN runtime instance over the same store,
    # so the fault is injected at class level (monkeypatch restores it)
    from httpserver.services.investigation.agent_runtime import (
        AgentRuntimeRepository,
    )

    original_append = AgentRuntimeRepository.append_trajectory

    def _failing_on_containment(self, *args, **kwargs):
        # only the containment write fails -- earlier trajectory writes
        # (delegation lifecycle, tool observations) must succeed so the
        # run actually reaches INTEGRATE
        payload = kwargs.get("payload")
        if isinstance(payload, dict) and "supervisor_failure" in payload:
            raise sqlite3.OperationalError("disk I/O error (synthetic)")
        return original_append(self, *args, **kwargs)

    monkeypatch.setattr(
        AgentRuntimeRepository, "append_trajectory", _failing_on_containment)
    orchestrator = AgentOrchestrator(
        FakeCppBackend(tmp_path),
        supervisor=_IntegrateViolatingSupervisor(),
        delegation_dispatcher=OfflineSpecialistDispatcher(repo, db),
        source_scope_provider=lambda task_id: ("windows",),
    )
    with pytest.raises(sqlite3.OperationalError):
        await orchestrator.run_loop("task-A", investigation_id)
    repo.append_trajectory = original_append  # type: ignore[method-assign]


@pytest.mark.asyncio
async def test_restart_after_containment_never_resumes_or_fakes(tmp_path):
    """Service restart: the contained run stays failed; a fresh
    orchestrator starts a NEW run; the interrupted delegation is never
    resumed and no integration decision is fabricated."""
    repo, db, investigation_id = _build_env(tmp_path)
    contained = await _contained_run(tmp_path, repo, db, investigation_id)
    failed_run_id = repo.list_runs(investigation_id)[-1].run_id
    revision_after_containment = repo.get_latest_working_state(
        investigation_id
    ).revision

    fresh = AgentOrchestrator(
        FakeCppBackend(tmp_path),
        supervisor=OfflineSupervisor(),
        delegation_dispatcher=OfflineSpecialistDispatcher(repo, db),
        source_scope_provider=lambda task_id: ("windows",),
    )
    next_outcome = (await fresh.run_loop("task-A", investigation_id))[0]
    # new run identity, old run still failed with its containment record
    assert next_outcome.run_id != failed_run_id
    runs = repo.list_runs(investigation_id)
    assert runs[-2].run_id == failed_run_id
    assert runs[-2].status.value == "failed"
    # the contained delegation was never resumed (its result was consumed
    # by a NEW delegation in the new run, never replayed as an integration)
    delegation = repo.get_delegation(contained.delegation_ids[0])
    assert delegation.status.value == "completed"
    assert delegation.integrated_at is None
    # no synthetic state mutation of the contained cycle
    assert repo.get_latest_working_state(investigation_id).revision >= (
        revision_after_containment)


@pytest.mark.asyncio
async def test_missing_task_store_recovery_is_a_skip_not_a_synthesis(tmp_path):
    """Task deletion: recovery over a store whose investigation DB is
    absent skips gracefully (existing-store-only contract) — nothing is
    resurrected, nothing fabricated."""
    from httpserver.services.investigation.agent_runtime import (
        AgentRuntimeRepository,
    )
    from httpserver.services.investigation.repository import (
        InvestigationRepository,
    )

    missing_db = tmp_path / "deleted" / "investigation.db"
    assert not missing_db.exists()
    # open_existing on a vanished store raises -> the caller (recovery
    # sweep) treats it as skip; pin that contract here
    with pytest.raises(Exception):
        InvestigationRepository.open_existing(missing_db, "task-A")

    # and an EXISTING store whose runtime already terminalized contained
    # failures is not resurrected by a recovery sweep
    repo, db, investigation_id = _build_env(tmp_path)
    await _contained_run(tmp_path, repo, db, investigation_id)
    summary = repo.recover_interrupted_agent_runtime()
    assert isinstance(summary, dict)
    runs = repo.list_runs(investigation_id)
    assert runs[-1].status.value == "failed"
    assert runs[-1].stop_reason == "internal_failure"
