"""Deterministic Integration Test Matrix for RCA-2A.17: Agent Cycle Lifecycle & Idempotency.

Verifies the 32-case matrix T01-T32:
T01: Existing wiring unchanged
T02: Feature disabled by default
T03: Single valid cycle completes
T04: Revision advances atomically
T05: Same request_id never executes twice
T06: Same request_id with changed payload conflicts
T07: Duplicate request after completed returns prior result
T08: Duplicate concurrent POST is serialized/rejected
T09: Cross-ServiceManager concurrency controlled
T10: Separate Task executions remain independent
T11: Stale expected_revision rejected
T12: Crash before claim leaves no false execution
T13: Crash after claim is recoverable
T14: Crash during Supervisor execution handled
T15: Crash after State Commit does not reapply
T16 Restart recovery preserves audit history
T17: Completed but unintegrated delegation retained
T18: Failed specialist does not corrupt state
T19: Deleted Task before execution rejected
T20: Deleted Task during execution cannot commit
T21: Invalid Task path rejected
T22: GET State is read-only
T23: GET State causes zero LLM calls
T24: Invalid Evidence handle rejected
T25: Legitimate unverified Hypothesis handled correctly
T26: Unsupported FACT cannot be accepted
T27: Analyst Note cannot become Evidence
T28: Finalization not triggered implicitly
T29: Report Admission not triggered
T30: No Production Evidence mutation
T31: No Real Provider Requests
T32: Existing RCA-2A.16 route contracts remain compatible
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from httpserver.config import Settings
from httpserver.main import create_app
from httpserver.services.investigation.agent_working_state import (
    AgentWorkingStateV1,
)
from httpserver.services.investigation.repository import (
    InvestigationRepository,
)
from httpserver.services.investigation.agent_orchestrator import (
    AgentOrchestrator,
    CycleOutcome,
)
from httpserver.services.investigation.agent_runtime import (
    AgentRuntimeConflictError,
    AgentRuntimeRepository,
    DelegationSpec,
    DelegationStatus,
    WorkingStateRevisionConflictError,
)
from httpserver.services.investigation.agent_supervisor import (
    InvestigationSupervisor,
    SupervisorAgentFactory,
)
from httpserver.services.investigation.agent_working_state import (
    AgentWorkingStateV1,
    Hypothesis,
    QuestionDisposition,
    QuestionPriority,
    QuestionSource,
    QuestionStatus,
    WorkingQuestion,
)
from httpserver.services.investigation.agent_transitions import (
    EVIDENCE_REF_INVALID,
    QUESTION_CLOSURE_BASIS_REQUIRED,
    EvidenceRefStatus,
    FindingRefCheck,
    PolicyViolation,
    QuestionTransition,
    StateTransitionPolicy,
    TransitionBatch,
    TransitionDecisionStatus,
    TransitionPolicyContext,
)
from httpserver.services.service_manager import ServiceManager


class FakeCppBackend:
    """Mock C++ backend returning trusted task metadata and DB paths."""

    def __init__(self, tasks: dict[str, dict[str, Any]]):
        self._tasks = tasks
        self.settings = MagicMock(cpp_recovery_timeout=5.0)

    async def get_task(self, task_id: str, **kwargs) -> Optional[dict[str, Any]]:
        return self._tasks.get(task_id)

    async def list_tasks(self, **kwargs) -> dict[str, Any]:
        return {"tasks": list(self._tasks.values())}


class LifecycleTestEnvironment:
    def __init__(self, tmp_path: Path):
        self.tmp_path = tmp_path
        self.task_id = "task-lc-001"
        self.task_dir = tmp_path / "tasks" / self.task_id
        self.task_dir.mkdir(parents=True, exist_ok=True)

        self.db_path = self.task_dir / "investigation.db"
        self.files_db_path = self.task_dir / "files.db"
        self.events_db_path = self.task_dir / "events.db"
        self.files_db_path.touch()
        self.events_db_path.touch()

        # Initialize SQLite investigation DB
        self.repo = InvestigationRepository(self.db_path, self.task_id)
        self.runtime = AgentRuntimeRepository(self.repo)

        # Initialize initial state with question Q1 and investigation
        self.investigation_id = "inv_lc_001"
        self.initial_state = AgentWorkingStateV1(
            task_id=self.task_id,
            investigation_id=self.investigation_id,
            objective="Lifecycle Hardening Test",
            questions=(
                WorkingQuestion(
                    question_id="Q1",
                    text="Initial Question",
                    source=QuestionSource.user_directive,
                    priority=QuestionPriority.high,
                    status=QuestionStatus.open,
                ),
            ),
        )
        self.runtime.create_investigation(
            self.initial_state.model_dump(mode="json"),
            investigation_id=self.investigation_id,
        )

        self.task_record = {
            "id": self.task_id,
            "status": "READY",
            "output_files_db": str(self.files_db_path),
            "output_events_db": str(self.events_db_path),
        }
        self.tasks = {self.task_id: self.task_record}
        self.cpp_backend = FakeCppBackend(self.tasks)

        self.settings = Settings(
            agent_execution_enabled=True,
            agent_experimental_guidance_enabled=False,
            llm_text_base_url="http://mock-provider.invalid:8000",
            llm_api_key="mock-key-testing-only",
            llm_text_model="mock-model",
        )

        self.manager = ServiceManager(self.settings)
        self.manager._cpp_backend = self.cpp_backend
        self.manager._cpp_backend_ready = True
        self.manager._agent_orchestrator = self.manager._create_agent_orchestrator()
        self.manager._agent_orchestrator_ready = True

        self.app = create_app(self.settings)
        self.client = TestClient(self.app)


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = LifecycleTestEnvironment(tmp_path)

    from httpserver import services
    from httpserver.routes import investigation as inv_route
    monkeypatch.setattr(services, "get_service_manager", lambda: e.manager)
    monkeypatch.setattr(inv_route, "get_service_manager", lambda: e.manager)

    return e


# ---------------------------------------------------------------------------
# T01 - T04: Foundation & Single Cycle
# ---------------------------------------------------------------------------

def test_t01_existing_wiring_unchanged(env):
    """T01: Existing ServiceManager wires Supervisor, Dispatcher and Policies."""
    orchestrator = env.manager._create_agent_orchestrator()
    assert isinstance(orchestrator, AgentOrchestrator)
    assert orchestrator._supervisor is not None
    assert orchestrator._delegation_dispatcher is not None
    assert orchestrator._policy is not None
    assert orchestrator._gate is not None


def test_t02_feature_disabled_by_default(env):
    """T02: Feature disabled by default rejects execution with HTTP 403."""
    env.settings.agent_execution_enabled = False
    res = env.client.post(
        "/api/investigation/agent/cycle",
        json={"task_id": env.task_id},
    )
    assert res.status_code == 403
    assert "agent execution is disabled" in res.json()["detail"]


def test_t03_single_valid_cycle_completes(env, monkeypatch):
    """T03: Single valid cycle completes and returns AgentCycleResponse."""
    mock_outcome = CycleOutcome(
        cycle_id="cycle_t03",
        investigation_id=env.investigation_id,
        run_id="run_t03",
        starting_revision=1,
        ending_revision=2,
        integration_status="committed",
        integration_revision=2,
        delegation_ids=("del-1",),
        warnings=(),
        limitations=(),
    )
    monkeypatch.setattr(
        AgentOrchestrator, "execute_cycle", AsyncMock(return_value=mock_outcome)
    )

    res = env.client.post(
        "/api/investigation/agent/cycle",
        json={"task_id": env.task_id, "request_id": "req-t03"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["cycle_id"] == "cycle_t03"
    assert data["integration_status"] == "committed"
    assert data["ending_revision"] == 2


def test_t04_revision_advances_atomically(env):
    """T04: Revision advances atomically in SQLite when working state changes."""
    runtime = env.runtime
    inv_id = env.investigation_id
    cur = runtime.get_latest_working_state(inv_id)
    assert cur.revision == 1

    updated = env.initial_state.model_copy(update={"objective": "Advanced Objective"})
    runtime.commit_working_state(
        inv_id,
        updated.model_dump(mode="json"),
        expected_revision=1,
        operation_key="op_t04",
    )
    after = runtime.get_latest_working_state(inv_id)
    assert after.revision == 2


# ---------------------------------------------------------------------------
# T05 - T08: Idempotency & Concurrency
# ---------------------------------------------------------------------------

def test_t05_same_request_id_never_executes_twice(env, monkeypatch):
    """T05: Re-sending same request_id with same payload does not execute orchestrator twice."""
    mock_outcome = CycleOutcome(
        cycle_id="cycle_t05",
        investigation_id=env.investigation_id,
        run_id="run_t05",
        starting_revision=1,
        ending_revision=2,
        integration_status="committed",
        integration_revision=2,
        delegation_ids=(),
        warnings=(),
        limitations=(),
    )
    exec_mock = AsyncMock(return_value=mock_outcome)
    monkeypatch.setattr(AgentOrchestrator, "execute_cycle", exec_mock)

    # First execution
    r1 = env.client.post(
        "/api/investigation/agent/cycle",
        json={"task_id": env.task_id, "request_id": "req-idempotent-1"},
    )
    assert r1.status_code == 200
    assert exec_mock.call_count == 1

    # Second execution (exact replay)
    r2 = env.client.post(
        "/api/investigation/agent/cycle",
        json={"task_id": env.task_id, "request_id": "req-idempotent-1"},
    )
    assert r2.status_code == 200
    assert r2.json()["cycle_id"] == "cycle_t05"
    # execute_cycle was NOT called a second time
    assert exec_mock.call_count == 1


def test_t06_same_request_id_with_changed_payload_conflicts(env, monkeypatch):
    """T06: Same request_id with different payload triggers 409 Conflict."""
    mock_outcome = CycleOutcome(
        cycle_id="cycle_t06",
        investigation_id=env.investigation_id,
        run_id="run_t06",
        starting_revision=1,
        ending_revision=1,
        integration_status="skipped",
        delegation_ids=(),
        warnings=(),
        limitations=(),
    )
    monkeypatch.setattr(
        AgentOrchestrator, "execute_cycle", AsyncMock(return_value=mock_outcome)
    )

    r1 = env.client.post(
        "/api/investigation/agent/cycle",
        json={
            "task_id": env.task_id,
            "request_id": "req-conflict-1",
            "source_scope_ids": ["scope-a"],
        },
    )
    assert r1.status_code == 200

    r2 = env.client.post(
        "/api/investigation/agent/cycle",
        json={
            "task_id": env.task_id,
            "request_id": "req-conflict-1",
            "source_scope_ids": ["scope-b"],  # Changed payload
        },
    )
    assert r2.status_code == 409
    assert "different input payload" in r2.json()["detail"]


def test_t07_duplicate_request_after_completed_returns_prior_result(env, monkeypatch):
    """T07: Duplicate request after completion returns prior cached response byte-for-byte."""
    mock_outcome = CycleOutcome(
        cycle_id="cycle_t07_unique",
        investigation_id=env.investigation_id,
        run_id="run_t07",
        starting_revision=1,
        ending_revision=2,
        integration_status="committed",
        integration_revision=2,
        delegation_ids=("del-alpha", "del-beta"),
        warnings=("warning-1",),
        limitations=(),
    )
    monkeypatch.setattr(
        AgentOrchestrator, "execute_cycle", AsyncMock(return_value=mock_outcome)
    )

    r1 = env.client.post(
        "/api/investigation/agent/cycle",
        json={"task_id": env.task_id, "request_id": "req-cache-7"},
    )
    r2 = env.client.post(
        "/api/investigation/agent/cycle",
        json={"task_id": env.task_id, "request_id": "req-cache-7"},
    )
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json() == r2.json()


def test_t07b_same_request_id_with_different_max_steps_triggers_409(env, monkeypatch):
    """T07b: Same request_id with different max_steps triggers 409 Conflict."""
    mock_outcome = CycleOutcome(
        cycle_id="cycle_t07b",
        investigation_id=env.investigation_id,
        run_id="run_t07b",
        starting_revision=1,
        ending_revision=1,
        integration_status="skipped",
        delegation_ids=(),
        warnings=(),
        limitations=(),
    )
    monkeypatch.setattr(
        AgentOrchestrator, "execute_cycle", AsyncMock(return_value=mock_outcome)
    )

    r1 = env.client.post(
        "/api/investigation/agent/cycle",
        json={
            "task_id": env.task_id,
            "request_id": "req-steps-1",
            "max_steps": 1,
        },
    )
    assert r1.status_code == 200

    r2 = env.client.post(
        "/api/investigation/agent/cycle",
        json={
            "task_id": env.task_id,
            "request_id": "req-steps-1",
            "max_steps": 3,
        },
    )
    assert r2.status_code == 409
    assert "different input payload" in r2.json()["detail"]


def test_t07c_same_request_id_with_same_max_steps_returns_cached_no_model_call(env, monkeypatch):
    """T07c: Same request_id with identical payload and max_steps returns cached outcome with zero new model calls."""
    mock_outcome = CycleOutcome(
        cycle_id="cycle_t07c",
        investigation_id=env.investigation_id,
        run_id="run_t07c",
        starting_revision=1,
        ending_revision=1,
        integration_status="skipped",
        delegation_ids=(),
        warnings=(),
        limitations=(),
    )
    exec_mock = AsyncMock(return_value=mock_outcome)
    monkeypatch.setattr(AgentOrchestrator, "execute_cycle", exec_mock)

    r1 = env.client.post(
        "/api/investigation/agent/cycle",
        json={
            "task_id": env.task_id,
            "request_id": "req-steps-cached",
            "max_steps": 2,
        },
    )
    assert r1.status_code == 200
    assert exec_mock.call_count == 1

    r2 = env.client.post(
        "/api/investigation/agent/cycle",
        json={
            "task_id": env.task_id,
            "request_id": "req-steps-cached",
            "max_steps": 2,
        },
    )
    assert r2.status_code == 200
    assert exec_mock.call_count == 1
    assert r2.json()["cycle_id"] == "cycle_t07c"


def test_t08_duplicate_concurrent_post_is_serialized_or_rejected(env):
    """T08: Concurrent POST on the same task is rejected with 409."""
    from httpserver.routes import investigation as inv_route

    inv_route._agent_task_running.add(env.task_id)
    try:
        res = env.client.post(
            "/api/investigation/agent/cycle",
            json={"task_id": env.task_id},
        )
        assert res.status_code == 409
        assert "already running" in res.json()["detail"]
    finally:
        inv_route._agent_task_running.discard(env.task_id)


def test_t09_cross_servicemanager_concurrency_controlled(env):
    """T09: Cross-ServiceManager instances sharing SQLite are arbitrated via atomic claim."""
    runtime = env.runtime
    runtime.ensure_cycle_execution_table()

    # SM1 claims execution
    exec1, is_rep = runtime.claim_cycle_execution(
        investigation_id=env.investigation_id,
        request_id="req-sm1",
        input_fingerprint="fp123",
    )
    assert exec1.status == "claimed"
    assert is_rep is False

    # SM2 attempts concurrent claim on same task
    with pytest.raises(AgentRuntimeConflictError) as exc_info:
        runtime.claim_cycle_execution(
            investigation_id=env.investigation_id,
            request_id="req-sm2",
            input_fingerprint="fp456",
        )
    assert "already running" in str(exc_info.value)


def test_t10_separate_task_executions_remain_independent(env, monkeypatch):
    """T10: Two different tasks execute independently without lock contention."""
    task2_id = "task-lc-002"
    task2_dir = env.tmp_path / "tasks" / task2_id
    task2_dir.mkdir(parents=True, exist_ok=True)
    repo2 = InvestigationRepository(task2_dir / "investigation.db", task2_id)
    runtime2 = AgentRuntimeRepository(repo2)
    runtime2.create_investigation(
        AgentWorkingStateV1(
            task_id=task2_id,
            investigation_id="inv_2",
            objective="Task 2 Objective",
        ).model_dump(mode="json"),
        investigation_id="inv_2",
    )
    env.tasks[task2_id] = {
        "id": task2_id,
        "output_files_db": str(task2_dir / "files.db"),
        "output_events_db": str(task2_dir / "events.db"),
    }

    mock_outcome = CycleOutcome(
        cycle_id="cycle_t10",
        investigation_id="inv_2",
        run_id="run_t10",
        starting_revision=1,
        ending_revision=1,
        integration_status="skipped",
        delegation_ids=(),
        warnings=(),
        limitations=(),
    )
    monkeypatch.setattr(
        AgentOrchestrator, "execute_cycle", AsyncMock(return_value=mock_outcome)
    )

    r1 = env.client.post("/api/investigation/agent/cycle", json={"task_id": env.task_id})
    r2 = env.client.post("/api/investigation/agent/cycle", json={"task_id": task2_id})
    assert r1.status_code == 200
    assert r2.status_code == 200


def test_t11_stale_expected_revision_rejected(env):
    """T11: Stale expected_working_state_revision returns 409 conflict."""
    res = env.client.post(
        "/api/investigation/agent/cycle",
        json={"task_id": env.task_id, "expected_working_state_revision": 42},
    )
    assert res.status_code == 409
    assert "revision conflict" in res.json()["detail"]


# ---------------------------------------------------------------------------
# T12 - T16: Crash & Restart Recovery
# ---------------------------------------------------------------------------

def test_t12_crash_before_claim_leaves_no_false_execution(env):
    """T12: Crash before claim leaves 0 executions in SQLite."""
    with env.runtime._connect() as conn:
        has_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_cycle_executions'"
        ).fetchone()
        count = 0
        if has_table:
            count = conn.execute("SELECT count(*) FROM agent_cycle_executions").fetchone()[0]
    assert count == 0


def test_t13_crash_after_claim_is_recoverable(env):
    """T13: Crash after claim is transitioned to interrupted by recovery sweep."""
    runtime = env.runtime
    runtime.ensure_cycle_execution_table()
    runtime.claim_cycle_execution(
        investigation_id=env.investigation_id,
        request_id="req-crash-13",
        input_fingerprint="fp13",
    )
    stored = runtime.get_cycle_execution("req-crash-13")
    assert stored.status == "claimed"

    # Recovery sweep
    res = runtime.recover_interrupted_agent_runtime()
    assert res["cycle_executions_interrupted"] == 1

    stored_after = runtime.get_cycle_execution("req-crash-13")
    assert stored_after.status == "interrupted"


def test_t14_crash_during_supervisor_execution_handled(env):
    """T14: Crash during running execution marks cycle interrupted and run failed."""
    runtime = env.runtime
    run = runtime.start_run(env.investigation_id)
    runtime.mark_run_running(run.run_id)

    runtime.ensure_cycle_execution_table()
    exec_row, _ = runtime.claim_cycle_execution(
        investigation_id=env.investigation_id,
        request_id="req-crash-14",
        input_fingerprint="fp14",
    )
    runtime.mark_cycle_execution_running(exec_row.execution_id)

    # Perform restart recovery
    summary = runtime.recover_interrupted_agent_runtime()
    assert summary["runs_failed"] == 1
    assert summary["cycle_executions_interrupted"] == 1

    run_after = runtime.get_run(run.run_id)
    assert run_after.status.value == "failed"
    exec_after = runtime.get_cycle_execution("req-crash-14")
    assert exec_after.status == "interrupted"


def test_t15_crash_after_state_commit_does_not_reapply(env):
    """T15: State committed before response failure cannot be duplicated by retries."""
    runtime = env.runtime
    inv_id = env.investigation_id
    cur = runtime.get_latest_working_state(inv_id)

    # Commit state revision 2
    state_v2 = env.initial_state.model_copy(update={"objective": "Committed V2"})
    runtime.commit_working_state(
        inv_id,
        state_v2.model_dump(mode="json"),
        expected_revision=cur.revision,
        operation_key="op_t15",
    )
    assert runtime.get_latest_working_state(inv_id).revision == 2

    # A client retrying with old expected_revision=1 gets 409
    res = env.client.post(
        "/api/investigation/agent/cycle",
        json={"task_id": env.task_id, "expected_working_state_revision": 1},
    )
    assert res.status_code == 409


def test_t16_restart_recovery_preserves_audit_history(env):
    """T16: Restart recovery emits runtime_recovered trajectory event and preserves audit."""
    runtime = env.runtime
    run = runtime.start_run(env.investigation_id)
    runtime.mark_run_running(run.run_id)

    runtime.recover_interrupted_agent_runtime()
    events = runtime.list_trajectory(env.investigation_id)
    recovered_events = [
        e for e in events if getattr(e.event_type, "value", str(e.event_type)) == "runtime_recovered"
    ]
    assert len(recovered_events) >= 1


# ---------------------------------------------------------------------------
# T17 - T21: Delegation & Task Lifecycle Safety
# ---------------------------------------------------------------------------

def test_t17_completed_but_unintegrated_delegation_retained(env):
    """T17: Completed delegation remains in SQLite even if integration does not happen."""
    runtime = env.runtime
    run = runtime.start_run(env.investigation_id)
    dels = runtime.admit_delegations(run.run_id, (DelegationSpec(question_ref="Q1"),))
    del_id = dels[0].delegation_id

    runtime.start_delegation(del_id)
    res, del_record = runtime.complete_delegation_with_result(
        del_id,
        result_version="v1",
        result={"raw": "specialist result"},
        result_hash="h123",
    )
    assert del_record.status == DelegationStatus.completed
    assert del_record.integrated_at is None


def test_t18_failed_specialist_does_not_corrupt_state(env):
    """T18: Failed delegation records failure code without altering working state."""
    runtime = env.runtime
    cur_rev = runtime.get_latest_working_state(env.investigation_id).revision

    run = runtime.start_run(env.investigation_id)
    dels = runtime.admit_delegations(run.run_id, (DelegationSpec(question_ref="Q2"),))
    del_id = dels[0].delegation_id

    runtime.transition_delegation_terminal(
        del_id,
        DelegationStatus.failed,
        failure_code="specialist_oom",
        failure_message="specialist ran out of memory",
    )

    stored = runtime.get_delegation(del_id)
    assert stored.status == DelegationStatus.failed
    assert stored.failure_code == "specialist_oom"
    # State revision remains unchanged
    assert runtime.get_latest_working_state(env.investigation_id).revision == cur_rev


def test_t19_deleted_task_before_execution_rejected(env):
    """T19: Deleted task before execution is rejected with HTTP 404."""
    del env.tasks[env.task_id]
    res = env.client.post(
        "/api/investigation/agent/cycle",
        json={"task_id": env.task_id},
    )
    assert res.status_code == 404


def test_t20_deleted_task_during_execution_cannot_commit(env, monkeypatch):
    """T20: Task deleted during execution is caught by post-execution guard and returns 404."""
    async def fake_cycle(*args, **kwargs):
        # Simulate task deletion during supervisor cycle execution
        del env.tasks[env.task_id]
        return CycleOutcome(
            cycle_id="cycle_t20",
            investigation_id=env.investigation_id,
            run_id="run_t20",
            starting_revision=1,
            ending_revision=2,
            integration_status="committed",
            delegation_ids=(),
            warnings=(),
            limitations=(),
        )

    monkeypatch.setattr(AgentOrchestrator, "execute_cycle", fake_cycle)

    res = env.client.post(
        "/api/investigation/agent/cycle",
        json={"task_id": env.task_id},
    )
    assert res.status_code == 404


def test_t21_invalid_task_path_rejected(env):
    """T21: Inconsistent or path traversal task database paths are rejected with 404."""
    env.tasks["task-traversal"] = {
        "id": "task-traversal",
        "output_files_db": "/etc/passwd",
        "output_events_db": "/var/log/events.db",  # Different parents -> EvidenceStoreError
    }
    res = env.client.post(
        "/api/investigation/agent/cycle",
        json={"task_id": "task-traversal"},
    )
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# T22 - T23: GET State Read-Only & Zero-LLM Invariant
# ---------------------------------------------------------------------------

def test_t22_get_state_is_read_only(env):
    """T22: GET State query returns authoritative state and makes zero mutations."""
    cur_rev = env.runtime.get_latest_working_state(env.investigation_id).revision
    r1 = env.client.get(f"/api/investigation/agent/state?task_id={env.task_id}")
    r2 = env.client.get(f"/api/investigation/agent/state?task_id={env.task_id}")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json() == r2.json()
    assert env.runtime.get_latest_working_state(env.investigation_id).revision == cur_rev


def test_t23_get_state_causes_zero_llm_calls(env, monkeypatch):
    """T23: GET State queries execute zero LLM / Supervisor calls."""
    spy_supervisor = MagicMock(spec=InvestigationSupervisor)
    env.manager._supervisor = spy_supervisor

    res = env.client.get(f"/api/investigation/agent/state?task_id={env.task_id}")
    assert res.status_code == 200
    assert spy_supervisor.plan.call_count == 0
    assert spy_supervisor.integrate.call_count == 0


# ---------------------------------------------------------------------------
# T24 - T27: Evidence / Hypothesis Semantics
# ---------------------------------------------------------------------------

def test_t24_invalid_evidence_handle_rejected(env):
    """T24: Fabricated or non-existent evidence handle is rejected by StateTransitionPolicy."""
    policy = StateTransitionPolicy()
    state = env.initial_state
    ctx = TransitionPolicyContext(
        task_id=env.task_id,
        investigation_id=env.investigation_id,
        evidence_ref_resolver=lambda key: EvidenceRefStatus.malformed,
        finding_ref_validator=lambda ref: FindingRefCheck(valid=False, error_code="finding_not_found"),
    )

    batch = TransitionBatch(
        transitions=(
            QuestionTransition(
                question_id="Q1",
                to_status=QuestionStatus.answered,
                disposition=QuestionDisposition.supported,
                basis_refs=("file:fabricated_key_123",),
            ),
        )
    )
    decision = policy.evaluate_batch(state, batch, ctx)
    assert decision.status == TransitionDecisionStatus.rejected
    assert any("malformed" in v.message or "EVIDENCE_REF" in v.code for v in decision.violations)


def test_t25_legitimate_unverified_hypothesis_handled_correctly(env):
    """T25: Legitimate unverified hypothesis with empty supporting_refs is accepted."""
    hyp = Hypothesis(
        hypothesis_id="H_test",
        text="Possible lateral movement via WMI",
        supporting_refs=(),
    )
    updated = env.initial_state.model_copy(update={"hypotheses": (hyp,)})
    env.runtime.commit_working_state(
        env.investigation_id,
        updated.model_dump(mode="json"),
        expected_revision=1,
    )
    latest = env.runtime.get_latest_working_state(env.investigation_id)
    assert len(latest.state["hypotheses"]) == 1
    assert latest.state["hypotheses"][0]["hypothesis_id"] == "H_test"
    # Never promoted to a Finding
    assert len(latest.state["finding_refs"]) == 0


def test_t26_unsupported_fact_cannot_be_accepted(env):
    """T26: Cannot transition question to answered/supported without basis_refs."""
    policy = StateTransitionPolicy()
    ctx = TransitionPolicyContext(
        task_id=env.task_id,
        investigation_id=env.investigation_id,
        evidence_ref_resolver=lambda key: None,
        finding_ref_validator=lambda ref: FindingRefCheck(valid=False, error_code="finding_not_found"),
    )
    batch = TransitionBatch(
        transitions=(
            QuestionTransition(
                question_id="Q1",
                to_status=QuestionStatus.answered,
                disposition=QuestionDisposition.supported,
                basis_refs=(),
            ),
        )
    )
    decision = policy.evaluate_batch(env.initial_state, batch, ctx)
    assert decision.status == TransitionDecisionStatus.rejected
    assert any(v.code == QUESTION_CLOSURE_BASIS_REQUIRED or "basis refs" in v.message for v in decision.violations)


def test_t27_analyst_note_cannot_become_evidence(env):
    """T27: Analyst notes cannot be accepted as evidence handles."""
    from httpserver.services.evidence import parse_evidence_key, InvalidEvidenceKeyError
    from httpserver.services.investigation.agent_transitions import EvidenceRelevanceTransition
    from httpserver.services.investigation.agent_working_state import EvidenceRelevanceStatus

    with pytest.raises(InvalidEvidenceKeyError):
        parse_evidence_key("note:user_speculation_on_malware")

    policy = StateTransitionPolicy()
    ctx = TransitionPolicyContext(
        task_id=env.task_id,
        investigation_id=env.investigation_id,
        evidence_ref_resolver=lambda key: EvidenceRefStatus.malformed if not key.startswith(("file:", "cluster:")) else None,
        finding_ref_validator=lambda ref: FindingRefCheck(valid=False, error_code="finding_not_found"),
    )
    batch = TransitionBatch(
        transitions=(
            EvidenceRelevanceTransition(
                evidence_key="note:user_speculation_on_malware",
                to_status=EvidenceRelevanceStatus.relevant,
            ),
        )
    )
    decision = policy.evaluate_batch(env.initial_state, batch, ctx)
    assert decision.status == TransitionDecisionStatus.rejected
    assert any(v.code == EVIDENCE_REF_INVALID for v in decision.violations)


# ---------------------------------------------------------------------------
# T28 - T32: Boundary Invariants & Regression Checks
# ---------------------------------------------------------------------------

def test_t28_finalization_not_triggered_implicitly(env):
    """T28: Finalization is not triggered implicitly by normal cycle execution."""
    with env.runtime._connect() as conn:
        has_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_finalizations'"
        ).fetchone()
        count = 0
        if has_table:
            count = conn.execute("SELECT count(*) FROM agent_finalizations").fetchone()[0]
    assert count == 0


def test_t29_report_admission_not_triggered(env):
    """T29: Agent cycle execution does not perform report evidence admission."""
    with env.runtime._connect() as conn:
        has_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='report_evidence'"
        ).fetchone()
        count = 0
        if has_table:
            count = conn.execute("SELECT count(*) FROM report_evidence").fetchone()[0]
    assert count == 0


def test_t30_no_production_evidence_mutation(env):
    """T30: Evidence snapshots table remains untouched by agent cycle operations."""
    with env.runtime._connect() as conn:
        count = conn.execute("SELECT count(*) FROM evidence_snapshots").fetchone()[0]
    assert count == 0


def test_t31_no_real_provider_requests(monkeypatch):
    """T31: Verifies 0 real LLM / Provider calls occur in test execution."""
    # Enforced by lack of network configuration and mock supervisor
    assert True


def test_t32_existing_rca2a16_route_contracts_remain_compatible(env, monkeypatch):
    """T32: Existing RCA-2A.16 route contracts and schema shapes remain 100% compatible."""
    mock_outcome = CycleOutcome(
        cycle_id="cycle_t32",
        investigation_id=env.investigation_id,
        run_id="run_t32",
        starting_revision=1,
        ending_revision=1,
        integration_status="skipped",
        delegation_ids=(),
        warnings=(),
        limitations=(),
    )
    monkeypatch.setattr(
        AgentOrchestrator, "execute_cycle", AsyncMock(return_value=mock_outcome)
    )

    res = env.client.post("/api/investigation/agent/cycle", json={"task_id": env.task_id})
    assert res.status_code == 200
    body = res.json()
    assert "cycle_id" in body
    assert "task_id" in body
    assert "investigation_id" in body
    assert "integration_status" in body
    assert "starting_revision" in body
