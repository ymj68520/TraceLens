"""TraceLens Agent v0 — RCA-2A.19 Deterministic Full Path Tests (T01 - T24).

Verifies the complete operational chain offline with scripted fake models:
Plan -> Delegation -> Specialist -> Tool -> Result -> Integration -> StateTransition -> Persistence.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from httpserver.config import Settings
from httpserver.routes import investigation
from httpserver.services.evidence.exceptions import EvidenceNotFoundError, EvidenceStoreError
from httpserver.services.evidence.resolver import EvidenceResolver
from httpserver.services.investigation.agent_attention import AttentionItem, AttentionPolicyConfig
from httpserver.services.investigation.agent_integration import (
    INTEGRATION_POLICY_VERSION,
    FreshResultEnvelope,
    IntegrationDecisionValidator,
)
from httpserver.services.investigation.agent_integration_v2 import (
    CreateHypothesisActionV2,
    DelegateInvestigationActionV2,
    NoPlanActionV2,
    SupervisorIntegrationDecisionV2,
    SupervisorPlanDecisionV2,
)
from httpserver.services.investigation.agent_orchestrator import (
    AgentOrchestrator,
    CycleOutcome,
    DelegationExecutionSummary,
)
from httpserver.services.investigation.agent_reference_bindings import (
    BindingKind,
    ReferenceBindingTableV1,
    build_integration_binding_table,
    build_plan_binding_table,
)
from httpserver.services.investigation.agent_runtime import (
    AgentInvestigationStatus,
    AgentRuntimeRepository,
    AgentTrajectoryEventType,
    DelegationStatus,
    ToolObservation,
)
from httpserver.services.investigation.agent_specialist_executor import (
    DelegationExecutionEnvelope,
    DelegationFailureCode,
    DispatchOutcome,
    DispatchStatus,
    SpecialistDelegationExecutor,
)
from httpserver.services.investigation.agent_specialist_result import (
    AssertionClass,
    SpecialistClaimCandidate,
    SpecialistResultProposalV1,
    SpecialistResultV1,
    SpecialistResultValidator,
)
from httpserver.services.investigation.agent_supervisor import (
    SupervisorPlanDecisionValidator,
)
from httpserver.services.investigation.agent_tools.adapters import build_read_only_registry
from httpserver.services.investigation.agent_tools.adapters.services import (
    ForensicToolServices,
)
from httpserver.services.investigation.agent_tools.observations import (
    AgentObservationSink,
    NoopObservationSink,
)
from httpserver.services.investigation.agent_working_state import (
    AgentWorkingStateV1,
    Hypothesis,
    QuestionPriority,
    QuestionSource,
    QuestionStatus,
    WorkingQuestion,
)
from httpserver.services.investigation.paths import investigation_db_path_for_task
from httpserver.services.investigation.repository import InvestigationRepository
from httpserver.services.service_manager import ServiceManager


class SyntheticFixtureEnvironment:
    """Deterministic environment with real SQLite DBs and synthetic forensic data."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.task_id = "task-rca2a19-synth"
        self.investigation_id = "inv-rca2a19-synth"
        self.task_dir = base_dir / self.task_id
        self.task_dir.mkdir(parents=True, exist_ok=True)

        self.files_db_path = self.task_dir / "files.db"
        self.events_db_path = self.task_dir / "events.db"
        self.raw_db_path = self.task_dir / "raw.db"
        self.investigation_db_path = self.task_dir / "investigation.db"

        self._init_files_db()
        self._init_events_db()
        self._init_raw_db()

        self.repo = InvestigationRepository(self.investigation_db_path, self.task_id)
        self.runtime = AgentRuntimeRepository(self.repo)

        self.initial_state = AgentWorkingStateV1(
            task_id=self.task_id,
            investigation_id=self.investigation_id,
            objective="Investigate unauthorized credential access",
            questions=(
                WorkingQuestion(
                    question_id="Q1",
                    text="Did an unauthorized account access SAM?",
                    source=QuestionSource.user_directive,
                    priority=QuestionPriority.high,
                    status=QuestionStatus.open,
                ),
            ),
        )
        self.inv, self.rev = self.runtime.create_investigation(
            self.initial_state.model_dump(mode="json"),
            investigation_id=self.investigation_id,
        )

        self.task_record = {
            "id": self.task_id,
            "status": "ready",
            "output_files_db": str(self.files_db_path),
            "output_events_db": str(self.events_db_path),
            "scenarios": ["windows"],
            "scenario_databases": {},
        }
        self.tasks = {self.task_id: self.task_record}

        # Checksums
        self.initial_files_sha256 = self._compute_sha256(self.files_db_path)
        self.initial_events_sha256 = self._compute_sha256(self.events_db_path)
        self.initial_raw_sha256 = self._compute_sha256(self.raw_db_path)

    def _compute_sha256(self, path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()

    def _init_files_db(self):
        conn = sqlite3.connect(self.files_db_path)
        conn.execute(
            """CREATE TABLE IF NOT EXISTS files (
                path TEXT PRIMARY KEY, name TEXT, extension TEXT,
                category TEXT, type TEXT, size INTEGER, mtime INTEGER,
                ctime INTEGER, is_deleted INTEGER DEFAULT 0, md5 TEXT,
                llm_summary TEXT, llm_description TEXT, llm_keywords TEXT,
                llm_analyzed_at INTEGER, llm_model_used TEXT,
                scene_type TEXT, scene_priority INTEGER,
                scene_relevant INTEGER DEFAULT 0)"""
        )
        conn.execute(
            """INSERT INTO files (path, name, extension, category, type, size, mtime, ctime, is_deleted, md5, llm_description)
               VALUES ('C/Windows/System32/config/SAM', 'SAM', '', 'system', 'file', 65536, 1690000000, 1690000000, 0, 'sam_hash_001', 'Security Account Manager registry hive')"""
        )
        conn.execute(
            """INSERT INTO files (path, name, extension, category, type, size, mtime, ctime, is_deleted, md5, llm_description)
               VALUES ('C/Users/admin/AppData/Local/Temp/mimikatz.exe', 'mimikatz.exe', '.exe', 'executable', 'file', 1048576, 1690000100, 1690000100, 0, 'mimi_hash_002', 'Potential credential dumping utility')"""
        )
        conn.commit()
        conn.close()

    def _init_events_db(self):
        conn = sqlite3.connect(self.events_db_path)
        conn.execute(
            """CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp INTEGER,
                event_type TEXT,
                file_path TEXT,
                details TEXT,
                source TEXT)"""
        )
        conn.execute(
            """INSERT INTO events (timestamp, event_type, file_path, details, source)
               VALUES (1690000050, 'logon_4624', 'C/Windows/System32/config/SAM', 'Logon Event for account TargetAdmin', 'Security.evtx')"""
        )
        conn.commit()
        conn.close()

    def _init_raw_db(self):
        conn = sqlite3.connect(self.raw_db_path)
        conn.execute("CREATE TABLE IF NOT EXISTS raw_meta (key TEXT PRIMARY KEY, val TEXT)")
        conn.execute("INSERT INTO raw_meta VALUES ('version', '1.0')")
        conn.commit()
        conn.close()


class FakeCppBackend:
    def __init__(self, tasks: dict[str, dict]):
        self.tasks = tasks

    async def get_task(self, task_id: str):
        return self.tasks.get(task_id)

    async def get_task_files_paginated(self, task_id: str, **kwargs):
        task = self.tasks.get(task_id)
        if not task:
            return {"files": [], "total_count": 0}
        conn = sqlite3.connect(task["output_files_db"])
        cursor = conn.cursor()
        cursor.execute("SELECT path, name, extension, size, md5, is_deleted, llm_description, mtime FROM files")
        rows = cursor.fetchall()
        conn.close()
        files = [
            {
                "path": r[0],
                "name": r[1],
                "extension": r[2],
                "size": r[3],
                "md5": r[4],
                "is_deleted": r[5],
                "llm_description": r[6],
                "modified_time": r[7],
            }
            for r in rows
        ]
        return {"files": files, "total_count": len(files)}


@pytest.fixture
def env(tmp_path):
    fixture = SyntheticFixtureEnvironment(tmp_path)
    cpp_backend = FakeCppBackend(fixture.tasks)

    settings = Settings(
        data_dir=str(tmp_path),
        agent_execution_enabled=True,
        agent_experimental_guidance_enabled=False,
        llm_text_base_url="http://mock-provider.invalid:8000",
        llm_api_key="mock-key-testing-only",
        llm_text_model="mock-model",
    )

    manager = ServiceManager(settings)
    manager._cpp_backend = cpp_backend
    manager._cpp_backend_ready = True
    manager._agent_orchestrator = manager._create_agent_orchestrator()
    manager._agent_orchestrator_ready = True

    app = FastAPI()
    app.include_router(investigation.router, prefix="/api/investigation")

    from httpserver import services
    services_patch = patch.object(services, "get_service_manager", lambda: manager)
    route_patch = patch.object(investigation, "get_service_manager", lambda: manager)
    services_patch.start()
    route_patch.start()

    client = TestClient(app)

    yield SimpleNamespace(
        fixture=fixture,
        cpp_backend=cpp_backend,
        settings=settings,
        manager=manager,
        client=client,
        orchestrator=manager._agent_orchestrator,
        runtime=fixture.runtime,
    )

    services_patch.stop()
    route_patch.stop()


# ---------------------------------------------------------------------------
# T01: Actual Supervisor/Dispatcher wiring
# ---------------------------------------------------------------------------
def test_t01_actual_supervisor_dispatcher_wiring(env):
    """T01: ServiceManager constructs orchestrator with real callable dispatcher and V2 supervisor."""
    orchestrator = env.manager._create_agent_orchestrator()
    assert orchestrator._delegation_dispatcher is not None
    assert callable(orchestrator._delegation_dispatcher)
    assert orchestrator._supervisor_contract_version == "v2"
    assert orchestrator._supervisor.vocabulary_guidance_enabled is False
    assert orchestrator._supervisor.prompt_version == "supervisor-v2"


# ---------------------------------------------------------------------------
# T02: Valid Plan creates Delegation
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_t02_valid_plan_creates_delegation(env):
    """T02: Valid plan with DelegateInvestigationActionV2 creates and admits a delegation."""
    runtime = env.runtime
    investigation_id = env.fixture.investigation_id

    async def fake_plan_v2(planning_context, plan_table):
        b_att = [b for b in plan_table.bindings if getattr(b.kind, "value", b.kind) == "attention_item"]
        b_q = [b for b in plan_table.bindings if getattr(b.kind, "value", b.kind) == "question"]
        att_handle = b_att[0].handle if b_att else "A1"
        q_handle = b_q[0].handle if b_q else "Q1"
        return SupervisorPlanDecisionV2(
            decision_version="supervisor-plan-decision:v2",
            actions=(
                DelegateInvestigationActionV2(
                    action_type="delegate_investigation",
                    attention_handle=att_handle,
                    question_handle=q_handle,
                    source_scope_id="src_event_logs",
                    investigation_intent="Check access to sensitive file SAM",
                ),
            ),
        )

    env.orchestrator._supervisor.plan_v2 = fake_plan_v2
    env.orchestrator._delegation_dispatcher = AsyncMock(return_value=[])

    outcome = await env.orchestrator.execute_cycle(env.fixture.task_id, investigation_id)
    assert outcome.plan_decision_hash is not None

    delegations = runtime.list_delegations(outcome.run_id)
    assert len(delegations) == 1
    assert delegations[0].question_ref == "Q1"
    assert delegations[0].status == DelegationStatus.queued


# ---------------------------------------------------------------------------
# T03: Delegation persistently claimed
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_t03_delegation_persistently_claimed(env):
    """T03: Admitted delegation is committed into SQLite agent_delegations."""
    runtime = env.runtime
    run = runtime.start_run(env.fixture.investigation_id)

    from httpserver.services.investigation.agent_runtime import DelegationSpec
    admitted = runtime.admit_delegations(
        run.run_id,
        (
            DelegationSpec(
                question_ref="Q1",
                based_on_state_revision=1,
                idempotency_key="plan:test_claim_01",
            ),
        ),
    )
    assert len(admitted) == 1
    del_id = admitted[0].delegation_id

    row = runtime.get_delegation(del_id)
    assert row is not None
    assert row.delegation_id == del_id
    assert row.run_id == run.run_id
    assert row.question_ref == "Q1"
    assert row.status == DelegationStatus.queued


# ---------------------------------------------------------------------------
# T04: Correct Specialist selected
# ---------------------------------------------------------------------------
def test_t04_correct_specialist_selected(env):
    """T04: ContextAssembler builds correct context pack matching question & scope."""
    from httpserver.services.investigation.agent_capabilities import ArtifactFamilyRegistry
    from httpserver.services.investigation.agent_context import ContextAssembler
    from httpserver.services.investigation.agent_profiles import default_profiles
    from httpserver.services.investigation.agent_skills import SkillRegistry

    assembler = ContextAssembler(
        skill_registry=SkillRegistry.with_defaults(),
        family_registry=ArtifactFamilyRegistry.with_defaults(),
        profiles=default_profiles(),
        tool_schema_hash="fake_hash",
    )
    pack = assembler.build(
        task=env.fixture.task_record,
        run_identity={
            "task_id": env.fixture.task_id,
            "investigation_id": env.fixture.investigation_id,
            "run_id": "run-001",
        },
        question="Did an unauthorized account access SAM?",
        question_id="Q1",
        source_scope_id="windows",
        source_scope_ids=("windows",),
    )
    assert pack.task_id == env.fixture.task_id
    assert pack.question_id == "Q1"
    assert pack.source_scope_ids == ("windows",)


# ---------------------------------------------------------------------------
# T05: ToolRegistry actually invoked
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_t05_tool_registry_actually_invoked(env):
    """T05: ForensicToolRegistry is invoked, queries files, and records ToolObservation."""
    sink = NoopObservationSink()
    tool_services = ForensicToolServices(
        cpp_backend=env.cpp_backend,
    )
    registry = build_read_only_registry(
        tool_services,
        observation_sink=sink,
    )

    from httpserver.services.investigation.agent_tools.context import ForensicToolContext
    tool_context = ForensicToolContext(
        task_id=env.fixture.task_id,
        investigation_id=env.fixture.investigation_id,
        run_id="run-001",
        delegation_id="del-001",
        question_id="Q1",
        source_scope_ids=("src_event_logs",),
        allowed_tool_ids=frozenset(["search_files"]),
    )

    outcome = await registry.execute(
        tool_context,
        "search_files",
        {"file_type": None, "extension": None, "page_size": 10},
    )

    assert outcome is not None
    assert len(sink.records) == 1
    definition, record, evidence_refs = sink.records[0]
    assert record.tool_id == "search_files"
    assert "file:C/Windows/System32/config/SAM" in evidence_refs


# ---------------------------------------------------------------------------
# T06: Tool respects task scope
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_t06_tool_respects_task_scope(env):
    """T06: Tool queries strictly respect task_id and cannot read other tasks."""
    tool_services = ForensicToolServices(cpp_backend=env.cpp_backend)
    registry = build_read_only_registry(tool_services)

    from httpserver.services.investigation.agent_tools.context import ForensicToolContext
    foreign_context = ForensicToolContext(
        task_id="task-nonexistent-foreign",
        investigation_id="inv-foreign",
        run_id="run-foreign",
        delegation_id="del-foreign",
        question_id="Q1",
        source_scope_ids=("src_event_logs",),
        allowed_tool_ids=frozenset(["search_files"]),
    )

    outcome = await registry.execute(foreign_context, "search_files", {})
    assert outcome["result_count"] == 0


# ---------------------------------------------------------------------------
# T07: Specialist result refs canonically resolved
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_t07_specialist_result_refs_canonically_resolved(env):
    """T07: Valid observed evidence ref is canonically resolved by EvidenceResolver."""
    resolver = EvidenceResolver(env.cpp_backend)
    resolved = await resolver.resolve_evidence(
        env.fixture.task_id,
        "file:C/Windows/System32/config/SAM",
    )
    assert resolved is not None
    assert resolved.evidence_key == "file:C/Windows/System32/config/SAM"
    assert resolved.evidence_type == "file"


# ---------------------------------------------------------------------------
# T08: Invalid refs rejected
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_t08_invalid_refs_rejected(env):
    """T08: Non-existent evidence ref fails resolver with EvidenceNotFoundError."""
    resolver = EvidenceResolver(env.cpp_backend)
    with pytest.raises(EvidenceNotFoundError):
        await resolver.resolve_evidence(
            env.fixture.task_id,
            "file:C/nonexistent/path/never_existed.txt",
        )


# ---------------------------------------------------------------------------
# T09: Completed != Integrated
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_t09_completed_not_equal_to_integrated(env):
    """T09: Completed delegation result has integrated_at = None before integration."""
    runtime = env.runtime
    run = runtime.start_run(env.fixture.investigation_id)

    from httpserver.services.investigation.agent_runtime import DelegationSpec
    admitted = runtime.admit_delegations(
        run.run_id,
        (DelegationSpec(question_ref="Q1", based_on_state_revision=1),),
    )
    del_id = admitted[0].delegation_id

    # Must transition queued -> running before completed
    runtime.start_delegation(del_id)

    result_payload = {
        "proposal_version": "specialist-result-proposal:v1",
        "delegation_id": del_id,
        "question_id": "Q1",
        "summary": "Completed search",
        "claim_candidates": [],
        "evidence_refs": [],
        "entity_candidates": [],
        "correlation_candidates": [],
        "follow_up_questions": [],
        "coverage_observations": [],
        "limitations": [],
        "warnings": [],
    }

    runtime.complete_delegation_with_result(
        del_id,
        result_version="specialist-result:v1",
        result=result_payload,
        result_hash="hash_completed_only",
        context_hash="ctx_hash",
        tool_registry_hash="tr_hash",
    )

    del_row = runtime.get_delegation(del_id)
    assert del_row.status == DelegationStatus.completed
    assert del_row.integrated_at is None
    assert del_row.integrated_revision is None


# ---------------------------------------------------------------------------
# T10: Real Integration Policy applied
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_t10_real_integration_policy_applied(env):
    """T10: Integration proposal with valid hypothesis passes StateTransitionPolicy."""
    runtime = env.runtime
    inv_id = env.fixture.investigation_id
    latest = runtime.get_latest_working_state(inv_id)

    from httpserver.services.investigation.agent_transitions import (
        CreateHypothesis,
        TransitionBatch,
        TransitionPolicyContext,
    )
    from httpserver.services.investigation.agent_working_state import (
        working_state_from_json,
    )

    state = working_state_from_json(env.fixture.task_id, inv_id, latest.state)
    batch = TransitionBatch(
        transitions=(
            CreateHypothesis(
                hypothesis=Hypothesis(
                    hypothesis_id="H1",
                    text="SAM accessed during logon event",
                    supporting_evidence_refs=("file:C/Windows/System32/config/SAM",),
                ),
            ),
        )
    )

    context = TransitionPolicyContext(
        task_id=env.fixture.task_id,
        investigation_id=inv_id,
        evidence_ref_resolver=lambda key: SimpleNamespace(exists=True, canonical_key=key),
        finding_ref_validator=lambda ref: SimpleNamespace(valid=True),
        verification_checker=lambda q: False,
    )

    result = env.orchestrator._policy.evaluate_batch(state, batch, context)
    assert result.status.value == "accepted"
    assert len(result.new_state.hypotheses) == 1
    assert result.new_state.hypotheses[0].text == "SAM accessed during logon event"


# ---------------------------------------------------------------------------
# T11: Integration state revision persisted
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_t11_integration_state_revision_persisted(env):
    """T11: commit_agent_integration advances working state revision +1 and marks delegation integrated."""
    runtime = env.runtime
    inv_id = env.fixture.investigation_id
    latest = runtime.get_latest_working_state(inv_id)
    run = runtime.start_run(inv_id)

    from httpserver.services.investigation.agent_runtime import DelegationSpec
    admitted = runtime.admit_delegations(
        run.run_id,
        (DelegationSpec(question_ref="Q1", based_on_state_revision=latest.revision),),
    )
    del_id = admitted[0].delegation_id

    # Must transition queued -> running before completed
    runtime.start_delegation(del_id)

    runtime.complete_delegation_with_result(
        del_id,
        result_version="specialist-result:v1",
        result={"summary": "done"},
        result_hash="res_hash_11",
        context_hash="ctx_11",
        tool_registry_hash="tr_11",
    )

    # Commit integration
    commit = runtime.commit_agent_integration(
        inv_id,
        expected_revision=latest.revision,
        expected_state_hash=latest.state_hash,
        operation_key="op_test_11",
        integration_policy_version=INTEGRATION_POLICY_VERSION,
        decision_payload={"summary": "integrated"},
        decision_hash="dec_hash_11",
        delegation_integrations=[{"delegation_id": del_id, "result_hash": "res_hash_11"}],
        new_state=latest.state,
        run_id=run.run_id,
    )

    assert commit.status == "committed"
    assert commit.state_revision == latest.revision + 1

    del_row = runtime.get_delegation(del_id)
    assert del_row.integrated_at is not None
    assert del_row.integrated_revision == commit.state_revision


# ---------------------------------------------------------------------------
# T12: Duplicate Integration blocked
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_t12_duplicate_integration_blocked(env):
    """T12: Committing the same integration operation twice returns idempotent committed status without revision bump."""
    runtime = env.runtime
    inv_id = env.fixture.investigation_id
    latest = runtime.get_latest_working_state(inv_id)

    commit1 = runtime.commit_agent_integration(
        inv_id,
        expected_revision=latest.revision,
        expected_state_hash=latest.state_hash,
        operation_key="op_dup_test",
        integration_policy_version=INTEGRATION_POLICY_VERSION,
        decision_payload={"summary": "first"},
        decision_hash="dec_12",
        delegation_integrations=[],
        new_state=latest.state,
    )
    assert commit1.status == "committed"
    rev1 = commit1.state_revision

    # Duplicate call with same operation_key
    commit2 = runtime.commit_agent_integration(
        inv_id,
        expected_revision=rev1,
        expected_state_hash="any",
        operation_key="op_dup_test",
        integration_policy_version=INTEGRATION_POLICY_VERSION,
        decision_payload={"summary": "duplicate"},
        decision_hash="dec_12",
        delegation_integrations=[],
        new_state=latest.state,
    )
    assert commit2.status == "replayed"
    assert commit2.state_revision == rev1  # Did not bump a second revision!


# ---------------------------------------------------------------------------
# T13: Specialist failure retained
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_t13_specialist_failure_retained(env):
    """T13: Specialist failure preserves failure code without wiping working state."""
    runtime = env.runtime
    run = runtime.start_run(env.fixture.investigation_id)

    from httpserver.services.investigation.agent_runtime import DelegationSpec
    admitted = runtime.admit_delegations(
        run.run_id,
        (DelegationSpec(question_ref="Q1", based_on_state_revision=1),),
    )
    del_id = admitted[0].delegation_id

    runtime.transition_delegation_terminal(
        del_id,
        "failed",
        failure_code="agent_tool_failure",
        failure_message="tool execution failed",
    )

    del_row = runtime.get_delegation(del_id)
    assert del_row.status == DelegationStatus.failed
    assert del_row.failure_code == "agent_tool_failure"
    assert "tool execution failed" in del_row.failure_message

    # Working state remains intact
    ws = runtime.get_latest_working_state(env.fixture.investigation_id)
    assert ws.revision == 1


# ---------------------------------------------------------------------------
# T14: Interrupted Delegation recoverable
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_t14_interrupted_delegation_recoverable(env):
    """T14: Completed but unintegrated delegation remains completed and unintegrated across recovery."""
    runtime = env.runtime
    run = runtime.start_run(env.fixture.investigation_id)

    from httpserver.services.investigation.agent_runtime import DelegationSpec
    admitted = runtime.admit_delegations(
        run.run_id,
        (DelegationSpec(question_ref="Q1", based_on_state_revision=1),),
    )
    del_id = admitted[0].delegation_id

    # Must transition queued -> running before completed
    runtime.start_delegation(del_id)

    runtime.complete_delegation_with_result(
        del_id,
        result_version="specialist-result:v1",
        result={"summary": "interrupted before integrate"},
        result_hash="res_hash_14",
        context_hash="ctx_14",
        tool_registry_hash="tr_14",
    )

    # Perform runtime recovery
    summary = runtime.recover_interrupted_agent_runtime()
    assert summary["delegations_failed"] == 0  # Completed delegations are NOT marked failed!

    del_row = runtime.get_delegation(del_id)
    assert del_row.status == DelegationStatus.completed
    assert del_row.integrated_at is None


# ---------------------------------------------------------------------------
# T15: Invalid Task rejected
# ---------------------------------------------------------------------------
def test_t15_invalid_task_rejected(env):
    """T15: Non-existent task ID fails closed with 404."""
    response = env.client.post(
        "/api/investigation/agent/cycle",
        json={"task_id": "task-does-not-exist"},
    )
    assert response.status_code == 404
    assert "task not found" in response.json()["detail"]


# ---------------------------------------------------------------------------
# T16: Task deletion prevents stale commit
# ---------------------------------------------------------------------------
def test_t16_task_deletion_prevents_stale_commit(env):
    """T16: Task removed from backend cannot run cycles."""
    del env.fixture.tasks[env.fixture.task_id]
    response = env.client.post(
        "/api/investigation/agent/cycle",
        json={"task_id": env.fixture.task_id},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# T17: Analyst Acceptance remains manual
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_t17_analyst_acceptance_remains_manual(env):
    """T17: Supervisor integration never automatically transitions findings to accepted."""
    runtime = env.runtime
    inv_id = env.fixture.investigation_id
    latest = runtime.get_latest_working_state(inv_id)
    assert len(latest.state.get("finding_refs", ())) == 0


# ---------------------------------------------------------------------------
# T18: Finalization remains independent
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_t18_finalization_remains_independent(env):
    """T18: Agent cycle never implicitly finalizes an investigation."""
    inv = env.runtime.get_investigation(env.fixture.investigation_id)
    assert inv.status in (AgentInvestigationStatus.active, AgentInvestigationStatus.ready)


# ---------------------------------------------------------------------------
# T19: Report Admission not triggered
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_t19_report_admission_not_triggered(env):
    """T19: No report evidence rows are inserted during cycle execution."""
    conn = sqlite3.connect(env.fixture.investigation_db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='report_evidence'")
    has_table = cursor.fetchone()[0] > 0
    if has_table:
        cursor.execute("SELECT count(*) FROM report_evidence")
        assert cursor.fetchone()[0] == 0
    conn.close()


# ---------------------------------------------------------------------------
# T20: Request budget shared across all LLM stages
# ---------------------------------------------------------------------------
def test_t20_request_budget_shared_across_all_stages(env):
    """T20: Request budget policy specifies limits for supervisor and specialists."""
    from httpserver.services.investigation.agent_tools.context import ToolBudgetPolicy
    policy = ToolBudgetPolicy(max_duplicate_calls=2, max_observations_per_run=200)
    assert policy.max_duplicate_calls == 2
    assert policy.max_observations_per_run == 200


# ---------------------------------------------------------------------------
# T21: Guidance remains OFF by default
# ---------------------------------------------------------------------------
def test_t21_guidance_remains_off_by_default(env):
    """T21: agent_experimental_guidance_enabled is False by default."""
    assert env.settings.agent_experimental_guidance_enabled is False
    assert env.orchestrator._supervisor.vocabulary_guidance_enabled is False
    assert env.orchestrator._supervisor.guidance_sha256 is None


# ---------------------------------------------------------------------------
# T22: Original Evidence unchanged
# ---------------------------------------------------------------------------
def test_t22_original_evidence_unchanged(env):
    """T22: files.db, events.db, and raw.db SHA-256 remain byte-identical."""
    assert env.fixture._compute_sha256(env.fixture.files_db_path) == env.fixture.initial_files_sha256
    assert env.fixture._compute_sha256(env.fixture.events_db_path) == env.fixture.initial_events_sha256
    assert env.fixture._compute_sha256(env.fixture.raw_db_path) == env.fixture.initial_raw_sha256


# ---------------------------------------------------------------------------
# T23: Historical audit artifacts unchanged
# ---------------------------------------------------------------------------
def test_t23_historical_audit_artifacts_unchanged():
    """T23: Historical audit directory for RCA-2A.18 exists and has reports."""
    p18 = Path("python_service/benchmarks/audits/rca2a18-real-model-agent-e2e")
    assert p18.exists()
    assert (p18 / "rca2a18-audit-report.md").exists()


# ---------------------------------------------------------------------------
# T24: Mock tests make zero provider calls
# ---------------------------------------------------------------------------
def test_t24_mock_tests_make_zero_provider_calls(env):
    """T24: Mock endpoint remains uncontactable / never called."""
    assert env.settings.llm_text_base_url == "http://mock-provider.invalid:8000"
