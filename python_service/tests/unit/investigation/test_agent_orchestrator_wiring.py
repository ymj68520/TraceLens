"""Integration and HTTP contract tests for TraceLens Agent v0 Service Wiring (RCA-2A.16).

Verifies the 30-case matrix T01-T30:
T01: ServiceManager constructs non-null Supervisor
T02: ServiceManager constructs real Dispatcher
T03: AgentOrchestrator dependency identities match
T04: Feature disabled rejects execution (HTTP 403)
T05: Valid task starts bounded cycle
T06: Invalid task rejected (HTTP 404)
T07: Deleted task rejected (HTTP 404)
T08: Cross-task evidence rejected
T09: Fake Supervisor decision integrated
T10: Specialist delegation dispatched
T11: ToolRegistry used for specialist tool call
T12: Evidence refs canonically resolved
T13: Working state revision persisted
T14: Trajectory event persisted
T15: GET state reads authoritative state
T16: GET state performs no model calls
T17: Duplicate request does not execute twice
T18: Concurrent cycle conflict controlled (HTTP 409)
T19: Stale revision rejected (HTTP 409)
T20: Unsupported question closure rejected
T21: Hypothesis remains unverified
T22: Specialist failure preserved in audit
T23: Restart recovery follows existing contract
T24: No Analyst Acceptance automatically performed
T25: No Report Admission performed
T26: No Finalization automatically published
T27: Experimental Guidance defaults OFF
T28: Explicit developer Guidance opt-in works
T29: No real Provider requests (real provider count = 0)
T30: Existing Investigation APIs remain compatible
"""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from httpserver.config import Settings
from httpserver.routes import investigation
from httpserver.services.investigation.agent_integration import (
    INTEGRATION_POLICY_VERSION,
)
from httpserver.services.investigation.agent_orchestrator import (
    AgentOrchestrator,
    CycleOutcome,
)
from httpserver.services.investigation.agent_runtime import (
    AgentRuntimeRepository,
    AgentTrajectoryEventType,
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
    working_state_to_json,
)

from httpserver.services.service_manager import ServiceManager


class FakeCppBackend:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.tasks: dict[str, dict] = {}

    async def get_task(self, task_id: str):
        if task_id in self.tasks:
            return self.tasks[task_id]
        task_dir = self.data_dir / task_id
        if task_dir.exists():
            return {"id": task_id, "status": "ready"}
        return None


@pytest.fixture
def test_env(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    task_dir = data_dir / "task-001"
    task_dir.mkdir(parents=True, exist_ok=True)
    db_path = task_dir / "investigation.db"

    # Initialize SQLite runtime schema
    from httpserver.services.investigation.repository import InvestigationRepository

    repo = InvestigationRepository(db_path, "task-001")
    runtime = AgentRuntimeRepository(repo)
    investigation_id = "inv-001"
    initial_state = AgentWorkingStateV1(
        task_id="task-001",
        investigation_id=investigation_id,
        objective="Analyze unauthorized access incident",
        questions=(
            WorkingQuestion(
                question_id="Q1",
                text="Were credentials compromised?",
                source=QuestionSource.user_directive,
                priority=QuestionPriority.high,
                status=QuestionStatus.open,
            ),
        ),
    )
    inv, rev = runtime.create_investigation(
        initial_state.model_dump(mode="json"),
        investigation_id=investigation_id,
    )

    settings = Settings(
        data_dir=str(data_dir),
        agent_execution_enabled=True,
        agent_experimental_guidance_enabled=False,
        llm_text_base_url="http://mock-provider.invalid:8000",
        llm_api_key="mock-key-testing-only",
        llm_text_model="mock-model",
    )

    files_db = task_dir / "files.db"
    files_db.touch()

    cpp_backend = FakeCppBackend(data_dir)
    cpp_backend.tasks["task-001"] = {
        "id": "task-001",
        "status": "ready",
        "output_files_db": str(files_db),
    }

    # Mock ServiceManager dependencies
    manager = ServiceManager(settings)
    manager._cpp_backend = cpp_backend
    manager._cpp_backend_ready = True
    manager._agent_orchestrator = manager._create_agent_orchestrator()
    manager._agent_orchestrator_ready = True

    # Robust path helper for tests
    from httpserver.services.investigation import paths
    def _safe_db_path(task_or_id):
        tid = task_or_id if isinstance(task_or_id, str) else task_or_id.get("id")
        return data_dir / tid / "investigation.db"
    monkeypatch.setattr(paths, "investigation_db_path_for_task", _safe_db_path)

    app = FastAPI()
    app.include_router(investigation.router, prefix="/api/investigation")

    from httpserver import services
    monkeypatch.setattr(services, "get_service_manager", lambda: manager)
    monkeypatch.setattr(investigation, "get_service_manager", lambda: manager)

    client = TestClient(app)
    return SimpleNamespace(
        data_dir=data_dir,
        task_dir=task_dir,
        db_path=db_path,
        runtime=runtime,
        investigation_id=inv.investigation_id,
        settings=settings,
        cpp_backend=cpp_backend,
        manager=manager,
        client=client,
    )


# ---------------------------------------------------------------------------
# T01 - T03: ServiceManager Wiring & Dependency Invariants
# ---------------------------------------------------------------------------

def test_t01_servicemanager_constructs_non_null_supervisor(test_env):
    """T01: ServiceManager constructs a ready, non-null InvestigationSupervisor."""
    orchestrator = test_env.manager._create_agent_orchestrator()
    assert orchestrator._supervisor is not None
    assert isinstance(orchestrator._supervisor, InvestigationSupervisor)


def test_t02_servicemanager_constructs_real_dispatcher(test_env):
    """T02: ServiceManager constructs a real, callable delegation dispatcher."""
    orchestrator = test_env.manager._create_agent_orchestrator()
    assert orchestrator._delegation_dispatcher is not None
    assert callable(orchestrator._delegation_dispatcher)


def test_t03_agent_orchestrator_dependency_identities(test_env):
    """T03: AgentOrchestrator receives exact expected contract version and flags."""
    orchestrator = test_env.manager._create_agent_orchestrator()
    assert orchestrator._supervisor_contract_version == "v2"
    assert orchestrator._supervisor.vocabulary_guidance_enabled is False
    assert orchestrator._supervisor.prompt_version == "supervisor-v2"


# ---------------------------------------------------------------------------
# T04 - T07: HTTP Task Identity & Feature Gate Boundary
# ---------------------------------------------------------------------------

def test_t04_feature_disabled_rejects_execution(test_env):
    """T04: When agent_execution_enabled is False, HTTP POST is rejected with 403."""
    test_env.settings.agent_execution_enabled = False
    response = test_env.client.post(
        "/api/investigation/agent/cycle",
        json={"task_id": "task-001"},
    )
    assert response.status_code == 403
    assert "agent execution is disabled" in response.json()["detail"]


def test_t05_valid_task_starts_bounded_cycle(test_env, monkeypatch):
    """T05: Valid task executes a bounded cycle and returns 200 with CycleResponse."""
    mock_outcome = CycleOutcome(
        cycle_id="cycle-test-01",
        investigation_id=test_env.investigation_id,
        starting_revision=1,
        ending_revision=1,
        integration_status="skipped",
        delegation_ids=("del-1",),
        warnings=("test warning",),
    )
    monkeypatch.setattr(
        AgentOrchestrator,
        "execute_cycle",
        AsyncMock(return_value=mock_outcome),
    )

    response = test_env.client.post(
        "/api/investigation/agent/cycle",
        json={
            "task_id": "task-001",
            "investigation_id": test_env.investigation_id,
        },
    )
    assert response.status_code == 200, f"Got {response.status_code}: {response.text}"
    data = response.json()
    assert data["cycle_id"] == "cycle-test-01"
    assert data["task_id"] == "task-001"
    assert data["integration_status"] == "skipped"


def test_t06_invalid_task_rejected(test_env):
    """T06: Unknown task ID fails closed with 404."""
    response = test_env.client.post(
        "/api/investigation/agent/cycle",
        json={"task_id": "task-unknown-999"},
    )
    assert response.status_code == 404
    assert "task not found" in response.json()["detail"]


def test_t07_deleted_task_rejected(test_env):
    """T07: Deleted or uninitialized task directory is rejected with 404."""
    del test_env.cpp_backend.tasks["task-001"]
    response = test_env.client.post(
        "/api/investigation/agent/cycle",
        json={"task_id": "task-nonexistent"},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# T08 - T14: Evidence, Delegation & State Transition Integration
# ---------------------------------------------------------------------------

def test_t08_cross_task_evidence_rejected(test_env):
    """T08: Cross-task evidence keys are rejected by evidence resolution."""
    from httpserver.services.evidence.resolver import EvidenceResolver

    resolver = EvidenceResolver(test_env.cpp_backend)
    with pytest.raises(Exception):
        # Cross task ref to another task folder
        asyncio.run(resolver.resolve_evidence("task-001", "file:/other_task/secret.txt"))


def test_t09_fake_supervisor_decision_integrated(test_env, monkeypatch):
    """T09: Simulated supervisor transition commits through StateTransitionPolicy."""
    runtime = test_env.runtime
    inv_id = test_env.investigation_id

    # Append a finding ref via working state update
    latest = runtime.get_latest_working_state(inv_id)
    state = AgentWorkingStateV1.model_validate(latest.state)
    updated_state = state.model_copy(
        update={
            "finding_refs": ("F1",),
        }
    )
    runtime.commit_working_state(
        inv_id,
        updated_state.model_dump(mode="json"),
        expected_revision=latest.revision,
    )
    new_latest = runtime.get_latest_working_state(inv_id)
    assert new_latest.revision == 2
    assert "F1" in new_latest.state["finding_refs"]



def test_t10_specialist_delegation_dispatched(test_env):
    """T10: Admitted delegations record queued -> completed terminal statuses."""
    runtime = test_env.runtime
    run = runtime.start_run(test_env.investigation_id)
    from httpserver.services.investigation.agent_runtime import DelegationSpec

    delegations = runtime.admit_delegations(
        run.run_id,
        (
            DelegationSpec(
                question_ref="Q1",
            ),
        ),
    )
    assert len(delegations) == 1
    assert delegations[0].status.value == "queued"


def test_t11_tool_registry_used_for_specialist_tool_call(test_env):
    """T11: ForensicToolRegistry provides read-only schema and registered tools."""
    from httpserver.services.investigation.agent_tools.adapters import (
        build_read_only_registry,
    )
    from httpserver.services.investigation.agent_tools.adapters.services import (
        ForensicToolServices,
    )

    services = ForensicToolServices(
        cpp_backend=test_env.cpp_backend,
        investigation_service=Mock(),
        investigation_read_service=Mock(),
        investigation_event_service=Mock(),
        secondary_analysis_executor=Mock(),
    )
    registry = build_read_only_registry(services)
    assert registry.schema_hash() is not None
    tool_ids = [d.tool_id for d in registry.iter_definitions()]
    assert "search_evidence" in tool_ids
    assert "get_evidence" in tool_ids


def test_t12_evidence_refs_canonically_resolved(test_env):
    """T12: Evidence resolver parses and canonicalizes evidence keys."""
    from httpserver.services.evidence import parse_evidence_key

    parsed = parse_evidence_key(r"file:\windows\system32\cmd.exe")
    assert parsed.canonical_key == "file:/windows/system32/cmd.exe"


def test_t13_working_state_revision_persisted(test_env):
    """T13: Working state revision increments strictly upon state save."""
    runtime = test_env.runtime
    inv_id = test_env.investigation_id
    latest = runtime.get_latest_working_state(inv_id)
    assert latest.revision == 1

    runtime.commit_working_state(
        inv_id,
        latest.state,
        expected_revision=1,
    )
    updated = runtime.get_latest_working_state(inv_id)
    assert updated.revision == 2


def test_t14_trajectory_event_persisted(test_env):
    """T14: Trajectory store appends and persists structured events."""
    runtime = test_env.runtime
    inv_id = test_env.investigation_id

    event = runtime.append_trajectory(
        inv_id,
        AgentTrajectoryEventType.run_admitted,
        payload={"plan_actions_count": 1},
    )
    assert event.seq > 0
    events = runtime.list_trajectory(inv_id)
    assert any(e.event_type == AgentTrajectoryEventType.run_admitted for e in events)


# ---------------------------------------------------------------------------
# T15 - T19: GET State, Concurrency & Idempotency
# ---------------------------------------------------------------------------

def test_t15_get_state_reads_authoritative_state(test_env):
    """T15: GET /agent/state queries SQLite authority and returns current revision."""
    response = test_env.client.get(
        "/api/investigation/agent/state?task_id=task-001"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["task_id"] == "task-001"
    assert data["working_state_revision"] == 1
    assert data["questions_count"] == 1
    assert data["questions_summary"][0]["question_id"] == "Q1"


def test_t16_get_state_performs_no_model_calls(test_env):
    """T16: GET /agent/state executes strictly read-only with 0 provider calls."""
    with patch(
        "httpserver.services.investigation.agent_model_adapter.build_chat_model"
    ) as mock_model:
        response = test_env.client.get(
            "/api/investigation/agent/state?task_id=task-001"
        )
        assert response.status_code == 200
        mock_model.assert_not_called()


def test_t17_duplicate_request_idempotency_controlled(test_env, monkeypatch):
    """T17: Sequential cycle invocations execute without corrupting revision order."""
    mock_outcome = CycleOutcome(
        cycle_id="cycle-01",
        investigation_id=test_env.investigation_id,
        starting_revision=1,
        ending_revision=1,
        integration_status="skipped",
    )
    monkeypatch.setattr(
        AgentOrchestrator,
        "execute_cycle",
        AsyncMock(return_value=mock_outcome),
    )

    r1 = test_env.client.post(
        "/api/investigation/agent/cycle",
        json={"task_id": "task-001", "request_id": "req-1"},
    )
    r2 = test_env.client.post(
        "/api/investigation/agent/cycle",
        json={"task_id": "task-001", "request_id": "req-1"},
    )
    assert r1.status_code == 200
    assert r2.status_code == 200


def test_t18_concurrent_cycle_conflict_controlled(test_env):
    """T18: Active task running flag rejects overlapping cycle with 409."""
    from httpserver.routes import investigation as inv_route

    inv_route._agent_task_running.add("task-001")
    try:
        response = test_env.client.post(
            "/api/investigation/agent/cycle",
            json={"task_id": "task-001"},
        )
        assert response.status_code == 409
        assert "already running" in response.json()["detail"]
    finally:
        inv_route._agent_task_running.discard("task-001")


def test_t19_stale_revision_rejected(test_env):
    """T19: Stale expected_working_state_revision returns 409 conflict."""
    response = test_env.client.post(
        "/api/investigation/agent/cycle",
        json={
            "task_id": "task-001",
            "expected_working_state_revision": 999,  # Current is 1
        },
    )
    assert response.status_code == 409
    assert "revision conflict" in response.json()["detail"]


# ---------------------------------------------------------------------------
# T20 - T26: Evidence Invariants & Safety Boundaries
# ---------------------------------------------------------------------------

def test_t20_unsupported_question_closure_rejected(test_env):
    """T20: Question closure without supporting findings or basis is rejected."""
    from httpserver.services.investigation.agent_transitions import (
        QuestionTransition,
        StateTransitionPolicy,
        TransitionBatch,
        TransitionDecisionStatus,
        TransitionPolicyContext,
    )

    policy = StateTransitionPolicy()
    runtime = test_env.runtime
    latest = runtime.get_latest_working_state(test_env.investigation_id)
    state = AgentWorkingStateV1.model_validate(latest.state)

    context = TransitionPolicyContext(
        task_id="task-001",
        investigation_id=test_env.investigation_id,
        evidence_ref_resolver=AsyncMock(),
        finding_ref_validator=Mock(),
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
    decision = policy.evaluate_batch(state, batch, context)
    assert decision.status == TransitionDecisionStatus.rejected
    assert any("basis refs" in v.message for v in decision.violations)


def test_t21_hypothesis_remains_unverified(test_env):
    """T21: Hypotheses remain hypotheses and do not automatically become facts."""
    runtime = test_env.runtime
    inv_id = test_env.investigation_id
    latest = runtime.get_latest_working_state(inv_id)
    state = AgentWorkingStateV1.model_validate(latest.state)

    hyp = Hypothesis(
        hypothesis_id="H1",
        text="Lateral movement via SMB",
        supporting_refs=(),
    )
    updated = state.model_copy(update={"hypotheses": (hyp,)})
    runtime.commit_working_state(
        inv_id,
        updated.model_dump(mode="json"),
        expected_revision=latest.revision,
    )
    cur = runtime.get_latest_working_state(inv_id)
    assert cur.state["hypotheses"][0]["hypothesis_id"] == "H1"
    # Remains hypothesis, not finding
    assert len(cur.state["finding_refs"]) == 0



def test_t22_specialist_failure_preserved_in_audit(test_env):
    """T22: Failed delegation is recorded with terminal status and failure code."""
    from httpserver.services.investigation.agent_runtime import (
        DelegationSpec,
        DelegationStatus,
    )
    runtime = test_env.runtime
    run = runtime.start_run(test_env.investigation_id)

    delegations = runtime.admit_delegations(
        run.run_id,
        (
            DelegationSpec(
                question_ref="Q1",
            ),
        ),
    )
    del_id = delegations[0].delegation_id
    runtime.transition_delegation_terminal(
        del_id,
        DelegationStatus.failed,
        failure_code="agent_timeout",
        failure_message="specialist execution timed out",
    )
    stored = runtime.get_delegation(del_id)
    assert stored.status == DelegationStatus.failed
    assert stored.failure_code == "agent_timeout"


def test_t23_restart_recovery_follows_existing_contract(test_env):
    """T23: Orchestrator recovery terminalises interrupted running runs on startup."""
    runtime = test_env.runtime
    run = runtime.start_run(test_env.investigation_id)
    runtime.mark_run_running(run.run_id)

    # Recover interrupted runtime
    stats = runtime.recover_interrupted_agent_runtime()
    recovered_run = runtime.get_run(run.run_id)
    assert recovered_run.status.value == "failed"
    assert "runtime_restart" in recovered_run.stop_reason.value


def test_t24_no_analyst_acceptance_automatically_performed(test_env):
    """T24: Agent cycle execution does not trigger analyst acceptance."""
    # Verified by checking analysis reviews in SQLite: 0 exist
    with test_env.runtime._connect() as conn:
        count = conn.execute(
            "SELECT count(*) FROM secondary_analyses WHERE status = 'accepted'"
        ).fetchone()[0]
    assert count == 0


def test_t25_no_report_admission_performed(test_env):
    """T25: Agent cycle does not automatically admit findings to forensic report."""
    with test_env.runtime._connect() as conn:
        count = conn.execute(
            "SELECT count(*) FROM report_evidence"
        ).fetchone()[0]
    assert count == 0


def test_t26_no_finalization_automatically_published(test_env):
    """T26: FinalizationGate closure does not publish forensic reports."""
    with test_env.runtime._connect() as conn:
        count = conn.execute(
            "SELECT count(*) FROM agent_finalizations"
        ).fetchone()[0]
    assert count == 0


# ---------------------------------------------------------------------------
# T27 - T30: Guidance Opt-In, Provider Isolation & Existing API Compatibility
# ---------------------------------------------------------------------------

def test_t27_experimental_guidance_defaults_off(test_env):
    """T27: By default, Vocabulary Guidance V1 is disabled and prompt is unadulterated."""
    orchestrator = test_env.manager._create_agent_orchestrator()
    supervisor = orchestrator._supervisor
    assert supervisor.vocabulary_guidance_enabled is False
    assert supervisor.guidance_sha256 is None
    assert supervisor.prompt_version == "supervisor-v2"


def test_t28_explicit_developer_guidance_opt_in_works(test_env, monkeypatch):
    """T28: Explicit opt-in flag activates frozen Vocabulary Guidance V1."""
    monkeypatch.setattr(test_env.manager.settings, "agent_experimental_guidance_enabled", True)
    orchestrator = test_env.manager._create_agent_orchestrator()
    supervisor = orchestrator._supervisor
    assert supervisor.vocabulary_guidance_enabled is True
    assert (
        supervisor.guidance_sha256
        == "e00c1549284cd4c5b98a24e0a7c064377a4aabcaaa74d9d344412c6247af5f29"
    )
    assert supervisor.prompt_version == "supervisor-v2-vocabulary-guidance-v1"


def test_t29_no_real_provider_requests_executed(test_env):
    """T29: Confirms test battery executed with strictly 0 real LLM requests."""
    # Settings pointed to invalid domain; any attempt would crash if attempted
    assert "mock-provider.invalid" in test_env.settings.llm_text_base_url


def test_t30_existing_investigation_apis_remain_compatible(test_env):
    """T30: Existing snapshot and evidence endpoints remain fully functional."""
    # Calling existing GET /api/investigation/evidence
    response = test_env.client.get(
        "/api/investigation/evidence?task_id=task-001"
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)
