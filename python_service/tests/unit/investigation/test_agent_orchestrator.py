"""P2-3 tests: AgentOrchestrator deterministic shell + ServiceManager
recovery wiring.

Covers P2 §41-§43 (PLAN/EXECUTE/INTEGRATE/EVALUATE scaffolding with fake
transitions), §44/§45 (ServiceManager startup recovery wiring) and §56.
No PydanticAI, no LLM, no real agent execution anywhere.
"""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from httpserver.services.investigation import (
    AgentInvestigationStatus,
    AgentRunStatus,
    AgentRuntimeConflictError,
    AgentRuntimeRepository,
    DelegationSpec,
    DelegationStatus,
    InvestigationRepository,
    InvestigationPauseReason,
    RunStopReason,
)
from httpserver.services.investigation.agent_finalization import (
    FinalizationOutcome,
    FinalizationRequest,
    FinalReviewMode,
    FinalSemanticReview,
    FinalSemanticReviewStatus,
    REVIEW_UNAVAILABLE,
)
from httpserver.services.investigation.agent_orchestrator import (
    AgentOrchestrator,
    AgentOrchestratorError,
    ControlAction,
    ControlActionType,
    TransitionDecisionStatus,
)
from httpserver.services.investigation.agent_transitions import (
    CreateQuestion,
    QuestionTransition,
    STATE_REVISION_CONFLICT,
    TransitionBatch,
)
from httpserver.services.investigation.agent_progress import NoProgressPolicyConfig
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


# ---------- fake trusted backend ----------

class FakeCppBackend:
    """Trusted task lookup only — mirrors the executor-facing surface."""

    def __init__(self, tasks: dict[str, dict]):
        self.tasks = tasks
        self.settings = SimpleNamespace(cpp_recovery_timeout=1.0)
        self.list_tasks_calls = 0

    async def get_task(self, task_id, **kwargs):
        return self.tasks.get(task_id)

    async def list_tasks(self, *, page=1, page_size=100, **kwargs):
        self.list_tasks_calls += 1
        ids = list(self.tasks)
        start = (page - 1) * page_size
        window = ids[start : start + page_size]
        return {"tasks": [{"id": tid} for tid in window]}


def _make_task(task_id: str, workspace: Path) -> dict:
    task_dir = workspace / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    return {"id": task_id, "output_files_db": str(task_dir / "files.db")}


@pytest.fixture()
def workspace(tmp_path) -> Path:
    return tmp_path


@pytest.fixture()
def runtime(workspace):
    """A real store for task A plus a matching trusted fake backend."""
    task = _make_task("A", workspace)
    backend = FakeCppBackend({"A": task})
    return backend, workspace


async def _seed_typable_investigation(orchestrator, task_id="A"):
    state = AgentWorkingStateV1(
        task_id=task_id,
        investigation_id=f"inv_seed_{task_id}",
        questions=(
            WorkingQuestion(
                question_id="Q1", text="persistence?",
                source=QuestionSource.charter,
                priority=QuestionPriority.required,
            ),
        ),
    )
    investigation, revision = await orchestrator.create_investigation(
        task_id, state
    )
    run = await orchestrator.admit_run(task_id, investigation.investigation_id)
    return investigation, revision, run


# ---------- PLAN: prepare_cycle ----------

@pytest.mark.asyncio
async def test_prepare_cycle_builds_attention_and_audits(runtime):
    backend, _ = runtime
    orchestrator = AgentOrchestrator(backend)
    investigation, revision, run = await _seed_typable_investigation(orchestrator)

    preparation = await orchestrator.prepare_cycle("A", investigation.investigation_id)
    assert preparation.state_revision == revision.revision
    assert preparation.active_run_id == run.run_id
    item_ids = [i.item_id for i in preparation.attention_set.items]
    assert "question:Q1" in item_ids

    store = AgentRuntimeRepository(
        InvestigationRepository(
            Path(backend.tasks["A"]["output_files_db"]).parent
            / "investigation.db",
            "A",
        )
    )
    events = store.list_trajectory(investigation.investigation_id)
    assert events[-1].event_type.value == "attention_compiled"
    assert events[-1].payload["state_revision"] == revision.revision
    assert events[-1].payload["attention_hash"] == (
        preparation.attention_set.attention_hash
    )


@pytest.mark.asyncio
async def test_prepare_cycle_requires_typed_state(runtime):
    backend, workspace = runtime
    orchestrator = AgentOrchestrator(backend)
    # an investigation whose state is NOT a typed v1 payload fails closed
    store = AgentRuntimeRepository(
        InvestigationRepository(
            Path(workspace / "A" / "investigation.db"), "A"
        )
    )
    investigation, _ = store.create_investigation({"not": "typed"})
    with pytest.raises(Exception):
        await orchestrator.prepare_cycle("A", investigation.investigation_id)


# ---------- EXECUTE: action admission (validation only) ----------

@pytest.mark.asyncio
async def test_action_admission_validates_and_rejects(runtime):
    backend, _ = runtime
    orchestrator = AgentOrchestrator(backend)
    investigation, revision, run = await _seed_typable_investigation(orchestrator)

    result = await orchestrator.validate_action_batch(
        "A",
        investigation.investigation_id,
        (
            ControlAction(
                action_type=ControlActionType.delegate_source,
                question_id="Q1",
            ),
            ControlAction(
                action_type=ControlActionType.direct_read,
                question_id="Q404",
            ),
            ControlAction(
                action_type=ControlActionType.delegate_correlation,
                question_id="Q1",
            ),
        ),
        expected_revision=revision.revision,
    )
    assert len(result.admitted) == 1
    assert result.admitted[0].action_type is ControlActionType.delegate_source
    codes = {
        action.action.action_type.value: action.violation_codes
        for action in result.rejected
    }
    assert "QUESTION_NOT_FOUND" in codes["direct_read"]
    # duplicate in-flight delegation fingerprint for the same question
    assert "DUPLICATE_ACTIVE_DELEGATION" in codes["delegate_correlation"]

    # stale expected revision fails closed for every action
    stale = await orchestrator.validate_action_batch(
        "A",
        investigation.investigation_id,
        (ControlAction(action_type=ControlActionType.direct_read),),
        expected_revision=revision.revision + 3,
    )
    assert not stale.admitted
    assert all(
        STATE_REVISION_CONFLICT in action.violation_codes
        for action in stale.rejected
    )


@pytest.mark.asyncio
async def test_admitted_actions_are_never_executed(runtime):
    """P2 admission means 'legal' — no delegation rows are created by
    validation; a future P4 executor owns execution."""
    backend, _ = runtime
    orchestrator = AgentOrchestrator(backend)
    investigation, revision, run = await _seed_typable_investigation(orchestrator)
    result = await orchestrator.validate_action_batch(
        "A",
        investigation.investigation_id,
        (ControlAction(
            action_type=ControlActionType.delegate_source, question_id="Q1"
        ),),
        expected_revision=revision.revision,
    )
    assert len(result.admitted) == 1
    store = AgentRuntimeRepository(
        InvestigationRepository(
            Path(backend.tasks["A"]["output_files_db"]).parent
            / "investigation.db",
            "A",
        )
    )
    assert store.list_delegations(run.run_id) == []


# ---------- INTEGRATE: transitions through the policy ----------

@pytest.mark.asyncio
async def test_integrate_accepts_batch_and_commits_one_revision(runtime):
    backend, _ = runtime
    orchestrator = AgentOrchestrator(backend)
    investigation, revision, run = await _seed_typable_investigation(orchestrator)

    batch = TransitionBatch(transitions=(
        CreateQuestion(question=WorkingQuestion(
            question_id="Q2", text="exfil path?",
            source=QuestionSource.supervisor_discovery,
            priority=QuestionPriority.high,
        )),
    ))
    result = await orchestrator.integrate_transitions(
        "A", investigation.investigation_id, batch,
        expected_revision=revision.revision,
        operation_key="op-1",
    )
    assert result.status is TransitionDecisionStatus.accepted
    assert result.state_revision == revision.revision + 1

    store = AgentRuntimeRepository(
        InvestigationRepository(
            Path(backend.tasks["A"]["output_files_db"]).parent
            / "investigation.db",
            "A",
        )
    )
    events = [
        e.event_type.value
        for e in store.list_trajectory(investigation.investigation_id)
    ]
    assert "transition_decision_validated" in events
    assert "working_state_integrated" in events
    # W12: exactly one revision increment for the semantic commit
    assert store.get_latest_working_state(
        investigation.investigation_id
    ).revision == revision.revision + 1

    # operation-key replay is idempotent and creates no revision
    replay = await orchestrator.integrate_transitions(
        "A", investigation.investigation_id, batch,
        expected_revision=revision.revision,
        operation_key="op-1",
    )
    assert replay.status is TransitionDecisionStatus.accepted
    assert replay.state_revision == revision.revision + 1


@pytest.mark.asyncio
async def test_integrate_rejects_invalid_batch_fail_closed(runtime):
    backend, _ = runtime
    orchestrator = AgentOrchestrator(backend)
    investigation, revision, run = await _seed_typable_investigation(orchestrator)
    batch = TransitionBatch(transitions=(
        QuestionTransition(question_id="Q404", to_status=QuestionStatus.open),
    ))
    result = await orchestrator.integrate_transitions(
        "A", investigation.investigation_id, batch,
        expected_revision=revision.revision,
    )
    assert result.status is TransitionDecisionStatus.rejected
    assert "QUESTION_NOT_FOUND" in result.violations
    store = AgentRuntimeRepository(
        InvestigationRepository(
            Path(backend.tasks["A"]["output_files_db"]).parent
            / "investigation.db",
            "A",
        )
    )
    events = [
        e.event_type.value
        for e in store.list_trajectory(investigation.investigation_id)
    ]
    assert "transition_decision_rejected" in events
    # nothing committed
    assert store.get_latest_working_state(
        investigation.investigation_id
    ).revision == revision.revision


@pytest.mark.asyncio
async def test_integrate_stale_revision_fails_closed(runtime):
    backend, _ = runtime
    orchestrator = AgentOrchestrator(backend)
    investigation, revision, run = await _seed_typable_investigation(orchestrator)
    result = await orchestrator.integrate_transitions(
        "A", investigation.investigation_id,
        TransitionBatch(transitions=()),
        expected_revision=revision.revision + 9,
    )
    assert result.status is TransitionDecisionStatus.rejected
    assert STATE_REVISION_CONFLICT in result.violations


# ---------- EVALUATE: progress ----------

@pytest.mark.asyncio
async def test_progress_bookkeeping_and_no_progress_stop(runtime):
    backend, _ = runtime
    orchestrator = AgentOrchestrator(
        backend, no_progress_config=NoProgressPolicyConfig(threshold=2)
    )
    investigation, revision, run = await _seed_typable_investigation(orchestrator)

    # F1: progress bookkeeping never consumes a Working State revision
    first = await orchestrator.evaluate_progress("A", investigation.investigation_id)
    assert not first.no_progress_detected
    assert first.state_revision == revision.revision
    assert first.consecutive_no_progress_cycles == 1
    second = await orchestrator.evaluate_progress("A", investigation.investigation_id)
    assert second.no_progress_detected
    assert second.run_stopped
    assert second.consecutive_no_progress_cycles == 2
    assert second.state_revision == revision.revision

    store = AgentRuntimeRepository(
        InvestigationRepository(
            Path(backend.tasks["A"]["output_files_db"]).parent
            / "investigation.db",
            "A",
        )
    )
    # the working state head never moved
    assert store.get_latest_working_state(
        investigation.investigation_id
    ).revision == revision.revision
    assert store.get_run(run.run_id).status is AgentRunStatus.cancelled
    assert store.get_run(run.run_id).stop_reason is RunStopReason.no_progress
    events = [
        e.event_type.value
        for e in store.list_trajectory(investigation.investigation_id)
    ]
    # every no-progress cycle is audited in the trajectory
    assert events.count("no_progress_detected") == 2


@pytest.mark.asyncio
async def test_progress_resets_on_semantic_progress(runtime):
    backend, _ = runtime
    orchestrator = AgentOrchestrator(
        backend, no_progress_config=NoProgressPolicyConfig(threshold=2)
    )
    investigation, revision, run = await _seed_typable_investigation(orchestrator)
    first = await orchestrator.evaluate_progress("A", investigation.investigation_id)
    assert first.consecutive_no_progress_cycles == 1
    # a semantic change between revisions counts as progress
    batch = TransitionBatch(transitions=(
        CreateQuestion(question=WorkingQuestion(
            question_id="Q2", text="lateral movement?",
            source=QuestionSource.supervisor_discovery,
            priority=QuestionPriority.normal,
        )),
    ))
    integrated = await orchestrator.integrate_transitions(
        "A", investigation.investigation_id, batch,
        expected_revision=first.state_revision,
    )
    assert integrated.status is TransitionDecisionStatus.accepted
    second = await orchestrator.evaluate_progress("A", investigation.investigation_id)
    assert second.productive
    assert second.consecutive_no_progress_cycles == 0
    assert not second.no_progress_detected


# ---------- EVALUATE + finalize ----------

def _request(investigation, revision, **overrides):
    kwargs = dict(
        investigation_id=investigation.investigation_id,
        expected_state_revision=revision,
        review_mode=FinalReviewMode.required,
        final_semantic_review=FinalSemanticReview(
            status=FinalSemanticReviewStatus.passed
        ),
    )
    kwargs.update(overrides)
    return FinalizationRequest(**kwargs)


@pytest.mark.asyncio
async def test_finalization_deny_and_atomic_commit(runtime):
    backend, _ = runtime
    orchestrator = AgentOrchestrator(backend)
    investigation, revision, run = await _seed_typable_investigation(orchestrator)

    # the seeded required question is still open -> DENY
    decision = await orchestrator.evaluate_finalization(
        "A", _request(investigation, revision.revision)
    )
    assert decision.outcome is FinalizationOutcome.deny
    commit = await orchestrator.finalize(
        "A", _request(investigation, revision.revision)
    )
    assert not commit.finalized
    assert commit.decision.outcome is FinalizationOutcome.deny

    store = AgentRuntimeRepository(
        InvestigationRepository(
            Path(backend.tasks["A"]["output_files_db"]).parent
            / "investigation.db",
            "A",
        )
    )
    events = [
        e.event_type.value
        for e in store.list_trajectory(investigation.investigation_id)
    ]
    assert "finalization_requested" in events
    assert "finalization_denied" in events
    assert store.get_investigation(
        investigation.investigation_id
    ).status is AgentInvestigationStatus.active


@pytest.mark.asyncio
async def test_finalize_commits_record_on_pass(runtime):
    backend, _ = runtime
    orchestrator = AgentOrchestrator(backend)
    state = AgentWorkingStateV1(
        task_id="A",
        investigation_id="inv_pass",
        questions=(WorkingQuestion(
            question_id="Q1", text="persistence?",
            source=QuestionSource.charter,
            priority=QuestionPriority.required,
            status=QuestionStatus.answered,
            disposition=QuestionDisposition.not_supported,
            basis_refs=("file:/a.txt",),
        ),),
        coverage=(CoverageDimension(
            dimension_id="usb", required=True,
            status=CoverageStatus.covered,
            basis_refs=("file:/a.txt",),
        ),),
    )
    investigation, revision = await orchestrator.create_investigation("A", state)
    run = await orchestrator.admit_run("A", investigation.investigation_id)
    # F2: finalization requires a RUNNING run
    store = AgentRuntimeRepository(
        InvestigationRepository(
            Path(backend.tasks["A"]["output_files_db"]).parent
            / "investigation.db",
            "A",
        )
    )
    store.mark_run_running(run.run_id)

    commit = await orchestrator.finalize(
        "A", _request(investigation, revision.revision)
    )
    assert commit.finalized
    assert commit.record.completion_mode == "complete"
    store = AgentRuntimeRepository(
        InvestigationRepository(
            Path(backend.tasks["A"]["output_files_db"]).parent
            / "investigation.db",
            "A",
        )
    )
    assert store.get_investigation(
        investigation.investigation_id
    ).status is AgentInvestigationStatus.completed
    assert store.get_run(run.run_id).stop_reason is RunStopReason.finalized
    assert store.get_finalization(investigation.investigation_id) == commit.record
    events = [
        e.event_type.value
        for e in store.list_trajectory(investigation.investigation_id)
    ]
    assert events[-1] == "finalization_completed"


@pytest.mark.asyncio
async def test_required_review_unavailable_pauses(runtime):
    backend, _ = runtime
    orchestrator = AgentOrchestrator(backend)
    investigation, revision, run = await _seed_typable_investigation(orchestrator)
    decision = await orchestrator.evaluate_finalization(
        "A",
        _request(
            investigation,
            revision.revision,
            review_mode=FinalReviewMode.required,
            final_semantic_review=FinalSemanticReview(
                status=FinalSemanticReviewStatus.unavailable
            ),
        ),
        pause_on_required_review_unavailable=True,
    )
    assert REVIEW_UNAVAILABLE in decision.violation_codes
    store = AgentRuntimeRepository(
        InvestigationRepository(
            Path(backend.tasks["A"]["output_files_db"]).parent
            / "investigation.db",
            "A",
        )
    )
    paused = store.get_investigation(investigation.investigation_id)
    assert paused.status is AgentInvestigationStatus.paused
    assert (
        paused.pause_reason
        is InvestigationPauseReason.finalization_review_unavailable
    )


# ---------- startup recovery wiring (P2 §44/§45, §56) ----------

@pytest.mark.asyncio
async def test_initialize_runs_recovery_over_trusted_tasks(runtime):
    backend, workspace = runtime
    # seed interrupted runtime state through the store directly
    store = AgentRuntimeRepository(
        InvestigationRepository(
            Path(workspace / "A" / "investigation.db"), "A"
        )
    )
    investigation, revision = store.create_investigation({"objective": "x"})
    store.start_run(investigation.investigation_id)

    orchestrator = AgentOrchestrator(backend)
    await orchestrator.initialize()
    assert backend.list_tasks_calls >= 1
    recovered = store.get_investigation(investigation.investigation_id)
    assert recovered.status is AgentInvestigationStatus.paused
    assert recovered.pause_reason is InvestigationPauseReason.runtime_restart
    # last committed working state untouched
    assert store.get_latest_working_state(
        investigation.investigation_id
    ).revision == revision.revision
    # repeated initialize is idempotent
    await orchestrator.initialize()


@pytest.mark.asyncio
async def test_recovery_does_not_scan_filesystem_or_resurrect(tmp_path):
    """A task whose store vanished is skipped, never recreated."""
    task = _make_task("B", tmp_path)
    backend = FakeCppBackend({"B": task})
    orchestrator = AgentOrchestrator(backend)
    Path(task["output_files_db"]).unlink(missing_ok=True)  # no store at all
    await orchestrator.initialize()
    assert not (tmp_path / "B" / "investigation.db").exists()


# ---------- ServiceManager wiring ----------

@pytest.mark.asyncio
async def test_service_manager_wires_orchestrator_and_recovery(tmp_path, monkeypatch):
    from httpserver.config import Settings
    from httpserver.services.service_manager import ServiceManager

    workspace = tmp_path
    task = _make_task("A", workspace)
    store_repo = InvestigationRepository(
        Path(workspace / "A" / "investigation.db"), "A"
    )
    store = AgentRuntimeRepository(store_repo)
    investigation, revision = store.create_investigation({"objective": "x"})
    store.start_run(investigation.investigation_id)

    events: list[str] = []

    class FakeOrchestrator:
        def __init__(self, cpp_backend):
            self.cpp_backend = cpp_backend
            self.initialize_calls = 0
            self.shutdown_calls = 0

        async def initialize(self):
            self.initialize_calls += 1
            events.append("orchestrator.initialize")
            # real recovery path over the trusted backend
            await AgentOrchestrator(self.cpp_backend).initialize()

        async def shutdown(self):
            self.shutdown_calls += 1
            events.append("orchestrator.shutdown")

    class Silent:
        def __init__(self, *args, **kwargs):
            pass

        async def initialize(self):
            pass

        async def shutdown(self):
            pass

        async def close(self):
            pass

    manager = ServiceManager(Settings(FORENSIC_REPORT_DIR=str(tmp_path / "r")))

    class FakeCppBackendService(Silent):
        async def health_check(self):
            return True

    real_orchestrator = FakeOrchestrator(FakeCppBackendService.__new__(
        FakeCppBackendService
    ))
    real_orchestrator.cpp_backend.tasks = {"A": task}
    real_orchestrator.cpp_backend.settings = SimpleNamespace(
        cpp_recovery_timeout=1.0
    )

    async def fake_get_task(task_id, **kwargs):
        return {"A": task}.get(task_id)

    async def fake_list_tasks(**kwargs):
        return {"tasks": [{"id": "A"}]}

    real_orchestrator.cpp_backend.get_task = fake_get_task
    real_orchestrator.cpp_backend.list_tasks = fake_list_tasks

    monkeypatch.setattr(
        "httpserver.services.cpp_backend.CppBackendService",
        lambda settings: real_orchestrator.cpp_backend,
    )
    monkeypatch.setattr(
        "httpserver.services.graphiti_service.GraphitiService", Silent
    )
    monkeypatch.setattr("httpserver.services.llm_service.LLMService", Silent)
    monkeypatch.setattr(
        "httpserver.services.ingestion_job_manager.IngestionJobManager", Silent
    )
    monkeypatch.setattr(
        "httpserver.services.investigation.agent_orchestrator.AgentOrchestrator",
        FakeOrchestrator,
    )
    monkeypatch.setattr(
        manager, "_create_forensic_report_service",
        lambda: Silent(), raising=False,
    )
    monkeypatch.setattr(
        manager, "_create_report_generation_executor",
        lambda: Silent(), raising=False,
    )
    monkeypatch.setattr(
        manager, "_create_secondary_analysis_executor",
        lambda: Silent(), raising=False,
    )
    monkeypatch.setattr(
        manager, "_create_event_refresh_executor",
        lambda: Silent(), raising=False,
    )
    import sys as _sys
    import types as _types
    monkeypatch.setattr(
        _sys, "modules",
        {**_sys.modules,
         "graphiti_integration.migration": _types.SimpleNamespace(
             MigrationManager=lambda **_: Silent()
         )},
    )

    await manager.initialize()
    try:
        assert manager._agent_orchestrator_ready
        assert manager.agent_orchestrator is not None
        # recovery ran inside initialize, before the runtime became usable
        recovered = store.get_investigation(investigation.investigation_id)
        assert recovered.status is AgentInvestigationStatus.paused
        assert events.count("orchestrator.initialize") == 1
    finally:
        await manager.shutdown()
    assert events[-1] == "orchestrator.shutdown"
    assert manager._agent_orchestrator is None
    assert not manager._agent_orchestrator_ready


# ---------- freeze follow-up F1: revision semantics ----------

@pytest.mark.asyncio
async def test_progress_and_attention_never_move_revision(runtime):
    """Working State revisions grow only through semantic mutations:
    repeated evaluate_progress cycles and attention compilation leave the
    head revision untouched while the trajectory grows."""
    backend, _ = runtime
    orchestrator = AgentOrchestrator(backend)
    investigation, revision, run = await _seed_typable_investigation(orchestrator)

    before_events = len(orchestrator is not None and [])  # placeholder no-op
    for _ in range(3):
        evaluation = await orchestrator.evaluate_progress(
            "A", investigation.investigation_id
        )
        assert evaluation.state_revision == revision.revision
    preparation = await orchestrator.prepare_cycle("A", investigation.investigation_id)
    assert preparation.state_revision == revision.revision

    store = AgentRuntimeRepository(
        InvestigationRepository(
            Path(backend.tasks["A"]["output_files_db"]).parent
            / "investigation.db",
            "A",
        )
    )
    assert store.get_latest_working_state(
        investigation.investigation_id
    ).revision == revision.revision
    # trajectory grew (attention_compiled + no_progress audits) while the
    # semantic state stayed identical
    events = store.list_trajectory(investigation.investigation_id)
    types = [e.event_type.value for e in events]
    assert types.count("attention_compiled") >= 1
    assert types.count("no_progress_detected") >= 1


@pytest.mark.asyncio
async def test_semantic_transition_increases_revision_exactly_once(runtime):
    backend, _ = runtime
    orchestrator = AgentOrchestrator(backend)
    investigation, revision, run = await _seed_typable_investigation(orchestrator)
    batch = TransitionBatch(transitions=(
        CreateQuestion(question=WorkingQuestion(
            question_id="Q2", text="exfil path?",
            source=QuestionSource.supervisor_discovery,
            priority=QuestionPriority.high,
        )),
    ))
    result = await orchestrator.integrate_transitions(
        "A", investigation.investigation_id, batch,
        expected_revision=revision.revision,
    )
    assert result.status is TransitionDecisionStatus.accepted
    store = AgentRuntimeRepository(
        InvestigationRepository(
            Path(backend.tasks["A"]["output_files_db"]).parent
            / "investigation.db",
            "A",
        )
    )
    assert store.get_latest_working_state(
        investigation.investigation_id
    ).revision == revision.revision + 1
    committed = [
        e.event_type.value
        for e in store.list_trajectory(investigation.investigation_id)
    ]
    assert committed.count("working_state_committed") == 1


# ---------- freeze follow-up F2: finalization run state ----------

@pytest.mark.asyncio
async def test_queued_run_cannot_be_finalized(runtime):
    """A queued run only holds an admission: the gate DENYs and the atomic
    commit refuses — no record, investigation unchanged, run stays queued."""
    from httpserver.services.investigation.agent_finalization import (
        FINALIZATION_RUN_NOT_RUNNING,
    )

    backend, _ = runtime
    orchestrator = AgentOrchestrator(backend)
    state = AgentWorkingStateV1(
        task_id="A",
        investigation_id="inv_queued",
        questions=(WorkingQuestion(
            question_id="Q1", text="persistence?",
            source=QuestionSource.charter,
            priority=QuestionPriority.required,
            status=QuestionStatus.answered,
            disposition=QuestionDisposition.not_supported,
            basis_refs=("file:/a.txt",),
        ),),
        coverage=(CoverageDimension(
            dimension_id="usb", required=True,
            status=CoverageStatus.covered,
            basis_refs=("file:/a.txt",),
        ),),
    )
    investigation, revision = await orchestrator.create_investigation("A", state)
    run = await orchestrator.admit_run("A", investigation.investigation_id)

    decision = await orchestrator.evaluate_finalization(
        "A", _request(investigation, revision.revision)
    )
    assert decision.outcome is FinalizationOutcome.deny
    assert FINALIZATION_RUN_NOT_RUNNING in decision.violation_codes

    commit = await orchestrator.finalize(
        "A", _request(investigation, revision.revision)
    )
    assert not commit.finalized

    store = AgentRuntimeRepository(
        InvestigationRepository(
            Path(backend.tasks["A"]["output_files_db"]).parent
            / "investigation.db",
            "A",
        )
    )
    with pytest.raises(AgentRuntimeConflictError):
        store.record_finalization(
            investigation.investigation_id,
            run_id=run.run_id,
            state_revision=revision.revision,
            state_hash=revision.state_hash,
            completion_mode="complete",
            question_dispositions={}, coverage_dispositions={},
            unresolved_contradictions=[], limitations=[],
            remaining_nonblocking_questions=[], pending_analyst_review_refs=[],
            final_verification_status="passed",
            finalization_policy_version="finalization-policy:v1",
            input_hash="h",
        )
    # nothing moved
    assert store.get_finalization(investigation.investigation_id) is None
    assert store.get_investigation(
        investigation.investigation_id
    ).status is AgentInvestigationStatus.active
    assert store.get_run(run.run_id).status is AgentRunStatus.queued


@pytest.mark.asyncio
async def test_terminal_runs_cannot_finalize(runtime):
    backend, _ = runtime
    orchestrator = AgentOrchestrator(backend)
    state = AgentWorkingStateV1(
        task_id="A",
        investigation_id="inv_term",
    )
    investigation, revision = await orchestrator.create_investigation("A", state)
    run = await orchestrator.admit_run("A", investigation.investigation_id)
    store = AgentRuntimeRepository(
        InvestigationRepository(
            Path(backend.tasks["A"]["output_files_db"]).parent
            / "investigation.db",
            "A",
        )
    )
    store.mark_run_running(run.run_id)
    store.fail_run(run.run_id, error_code="x", error_message="y")
    with pytest.raises(AgentRuntimeConflictError):
        store.record_finalization(
            investigation.investigation_id,
            run_id=run.run_id,
            state_revision=revision.revision,
            state_hash=revision.state_hash,
            completion_mode="complete",
            question_dispositions={}, coverage_dispositions={},
            unresolved_contradictions=[], limitations=[],
            remaining_nonblocking_questions=[], pending_analyst_review_refs=[],
            final_verification_status="passed",
            finalization_policy_version="finalization-policy:v1",
            input_hash="h",
        )
    second_run = await orchestrator.admit_run("A", investigation.investigation_id)
    cancelled = store.cancel_run(
        second_run.run_id, stop_reason=RunStopReason.cancelled
    )
    with pytest.raises(AgentRuntimeConflictError):
        store.record_finalization(
            investigation.investigation_id,
            run_id=cancelled.run_id,
            state_revision=revision.revision,
            state_hash=revision.state_hash,
            completion_mode="complete",
            question_dispositions={}, coverage_dispositions={},
            unresolved_contradictions=[], limitations=[],
            remaining_nonblocking_questions=[], pending_analyst_review_refs=[],
            final_verification_status="passed",
            finalization_policy_version="finalization-policy:v1",
            input_hash="h",
        )
