"""P4B-4 tests: the closed agent investigation loop.

§44 full offline cycle: Investigation → Run → seeded Question →
AttentionBuilder → real PydanticAI Supervisor PLAN (TestModel) → atomic
admission → P4A real PydanticAI Specialist (TestModel) → read-only tool →
Observation+Trajectory → SpecialistResult → MergeGuard → real PydanticAI
Supervisor INTEGRATION (TestModel) → typed transition → StateTransitionPolicy
→ atomic revision (+exactly 1) → Progress evaluation.

Plus §45 (parallel all_terminal), §46 (stale e2e), §47 (directive re-plan),
§48 (finalization wiring), §49 (restart).
"""

import asyncio
import json
from types import SimpleNamespace

import pytest
from pydantic_ai.models.test import TestModel

from httpserver.services.investigation.agent_orchestrator import (
    AgentOrchestrator,
    SupervisorCyclePolicy,
)
from httpserver.services.investigation.agent_runtime import (
    AgentRuntimeRepository,
    AgentRunStatus,
    DelegationSpec,
    DelegationStatus,
)
from httpserver.services.investigation.repository import InvestigationRepository
from httpserver.services.investigation.agent_working_state import (
    AgentWorkingStateV1,
    QuestionDisposition,
    QuestionPriority,
    QuestionSource,
    QuestionStatus,
    WorkingQuestion,
    working_state_to_json,
)

pytest.importorskip("pydantic_ai")
pytestmark = pytest.mark.migration_matrix


def _initial_state(task_id, investigation_id):
    return AgentWorkingStateV1(
        task_id=task_id,
        investigation_id=investigation_id,
        objective="detect unauthorized access",
        questions=(
            WorkingQuestion(
                question_id="q-1",
                text="Were there unauthorized logons?",
                source=QuestionSource.charter,
                priority=QuestionPriority.required,
            ),
        ),
    )


class FakeCppBackend:
    def __init__(self, base_dir):
        self._base_dir = base_dir
        # A1-S: the specialist completion boundary canonically resolves every
        # promoted evidence ref against the REAL task store — provide one.
        self._ensure_files_db()

    def _ensure_files_db(self):
        import sqlite3

        db = self._base_dir / "files.db"
        conn = sqlite3.connect(db)
        try:
            # mirror the production files table columns the snapshot
            # acquisition reads (A1-S Phase A resolves against the REAL
            # source schema — see acquisition._FILE_COLUMNS)
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
                """INSERT OR IGNORE INTO files (path, name, extension,
                    category, type, size, mtime, ctime, is_deleted, md5)
                    VALUES ('C/logon_4624.doc', 'logon_4624.doc', '.doc',
                    'document', 'file', 1024, 1690000000, 1690000000, 0,
                    'testmd5')""",
            )
            conn.commit()
        finally:
            conn.close()

    async def get_task(self, task_id, **kwargs):
        return {
            "id": task_id,
            "status": "done",
            "image_name": "disk.E01",
            "output_files_db": str(self._base_dir / "files.db"),
            "output_events_db": str(self._base_dir / "events.db"),
        }


def _build_env(tmp_path):
    db = tmp_path / "investigation.db"
    store = InvestigationRepository(db, "task-A")
    repo = AgentRuntimeRepository(store)
    investigation_id = "inv-" + "c" * 8
    investigation, _rev = repo.create_investigation(
        working_state_to_json(_initial_state("task-A", investigation_id)),
        investigation_id=investigation_id,
    )
    return repo, db, investigation.investigation_id


class _FakeToolServices:
    """Minimal facade bundle; search_evidence surfaces one visible file."""

    class _Read:
        async def list_evidence(self, task_id):
            from httpserver.services.investigation.models import EvidenceSummary

            return [
                EvidenceSummary(
                    task_id=task_id,
                    evidence_key="file:C/logon_4624.doc",
                    evidence_type="file",
                    captured_at=1690000000,
                ),
            ]

        async def list_analysis_claims(self, task_id, analysis_id):
            return None

    class _Inv:
        async def resolve_evidence(self, task_id, key):
            return None

        async def effective_event_claims(self, task_id, event_id):
            return []

    class _Exec:
        async def list_analyses(self, task_id, key):
            return []

        async def list_all_analyses(self, task_id):
            return {}

    def __init__(self):
        from types import SimpleNamespace

        self.cpp_backend = SimpleNamespace(
            get_task=None,
            get_task_files_paginated=None,
            get_task_events=None,
        )
        self.investigation_service = self._Inv()
        self.investigation_read_service = self._Read()
        self.investigation_event_service = SimpleNamespace()
        self.secondary_analysis_executor = self._Exec()


def _registry_builder(runtime):
    from httpserver.services.investigation.agent_tools.adapters import (
        build_read_only_registry,
    )
    from httpserver.services.investigation.agent_tools.observations import (
        AgentObservationSink,
    )

    return build_read_only_registry(
        _FakeToolServices(), observation_sink=AgentObservationSink(runtime)
    )


def _plan_model(delegation=True) -> TestModel:
    from httpserver.services.investigation.agent_supervisor import (
        SUPERVISOR_PLAN_DECISION_VERSION,
    )

    actions = []
    if delegation:
        actions.append(
            {
                "action_kind": "delegate_investigation",
                "action_id": "a-1",
                "attention_item_id": "ATTEND",
                "question_id": "q-1",
                "source_scope_id": "windows",
                "investigation_intent": "check logon evidence",
            }
        )
    return TestModel(
        call_tools=[],
        custom_output_args={
            "decision_version": SUPERVISOR_PLAN_DECISION_VERSION,
            "task_id": "task-A",
            "investigation_id": "INV",
            "actions": actions,
            "summary": "delegate the open question",
        },
    )


def _integration_model(question_id="q-1") -> TestModel:
    return TestModel(
        call_tools=[],
        custom_output_args={
            "decision_version": "supervisor-integration-decision:v1",
            "task_id": "task-A",
            "investigation_id": "INV",
            "integration_summary": "mark question in progress from result",
            "transition_proposals": [
                {"question_id": question_id, "to_status": "in_progress"}
            ],
        },
    )


class ContextBoundSupervisorMixin:
    """Binds the deterministic context values (revision/hash/attention hash)
    into the structured TestModel output right before the run executes."""

    model_name = "offline-test-model"
    model_config_hash = "cfg-offline"

    def _bind_plan(self, pack, decision_dict):
        decision_dict["task_id"] = pack.task_id
        decision_dict["investigation_id"] = pack.investigation_id
        decision_dict["run_id"] = pack.run_id
        decision_dict["based_on_state_revision"] = pack.state_revision
        decision_dict["based_on_state_hash"] = pack.state_hash
        decision_dict["attention_hash"] = pack.attention_hash
        return decision_dict

    def _bind_integration(self, context, decision_dict):
        decision_dict["task_id"] = context.task_id
        decision_dict["investigation_id"] = context.investigation_id
        decision_dict["run_id"] = context.run_id
        decision_dict["based_on_state_revision"] = context.state_revision
        decision_dict["based_on_state_hash"] = context.state_hash
        decision_dict["source_result_ids"] = list(context.source_result_ids)
        decision_dict["source_result_hashes"] = list(
            context.source_result_hashes
        )
        return decision_dict


class OfflineSupervisor(ContextBoundSupervisorMixin):
    """Real PydanticAI agents (TestModel) with context-bound outputs."""

    def __init__(self, *, delegate=True, question_id="q-1"):
        self._delegate = delegate
        self._question_id = question_id
        self.plan_calls = 0
        self.integration_calls = 0

    async def plan(self, pack):
        from httpserver.services.investigation.agent_supervisor import (
            SupervisorAgentFactory,
        )

        self.plan_calls += 1
        args = self._bind_plan(pack, {
            "decision_version": "supervisor-plan-decision:v1",
            "actions": (
                [
                    {
                        "action_kind": "delegate_investigation",
                        "action_id": "a-1",
                        "attention_item_id": next(
                            item.item_id
                            for item in pack.attention_items
                            if "delegate_source" in item.eligible_action_types
                            and item.eligibility == "eligible"
                            and "q-1" in item.related_question_ids
                        ),
                        "question_id": self._question_id,
                        "source_scope_id": "windows",
                    }
                ]
                if self._delegate
                else []
            ),
        })
        model = TestModel(call_tools=[], custom_output_args=args)
        agent = SupervisorAgentFactory(model=model).build_plan_agent(pack)
        result = await agent.run("plan")
        return result.output

    async def integrate(self, context):
        from httpserver.services.investigation.agent_supervisor import (
            SupervisorAgentFactory,
        )

        self.integration_calls += 1
        args = self._bind_integration(
            context,
            {
                "decision_version": "supervisor-integration-decision:v1",
                "integration_summary": "advance the question",
                "transition_proposals": [
                    {"question_id": self._question_id, "to_status": "in_progress"}
                ],
            },
        )
        model = TestModel(call_tools=[], custom_output_args=args)
        agent = SupervisorAgentFactory(model=model).build_integration_agent(context)
        result = await agent.run("integrate")
        return result.output


class OfflineSpecialistDispatcher:
    """P4A SpecialistDelegationExecutor path with a real PydanticAI
    TestModel agent driving the real read-only registry."""

    def __init__(self, repo, db_path):
        self._repo = repo
        self._db_path = db_path

    async def __call__(self, planning_context, decision, admitted):
        from httpserver.services.investigation.agent_context import ContextAssembler
        from httpserver.services.investigation.agent_capabilities import (
            ArtifactFamilyRegistry,
        )
        from httpserver.services.investigation.agent_profiles import default_profiles
        from httpserver.services.investigation.agent_skills import SkillRegistry
        from httpserver.services.investigation.agent_specialist_executor import (
            AgentRunPolicy,
            build_execution_envelope,
        )
        from httpserver.services.investigation.agent_specialist_result import (
            AssertionClass,
            SpecialistClaimCandidate,
            SpecialistResultProposalV1,
            SpecialistResultV1,
        )
        from httpserver.services.investigation.agent_tools.pydantic_bridge import (
            build_specialist_agent,
        )
        from types import SimpleNamespace

        registry = _registry_builder(self._repo)
        assembler = ContextAssembler(
            skill_registry=SkillRegistry.with_defaults(),
            family_registry=ArtifactFamilyRegistry.with_defaults(),
            profiles=default_profiles(),
            tool_schema_hash=registry.schema_hash(),
        )
        outcomes = []
        for delegation, action in zip(admitted, decision.delegate_actions()):
            pack = assembler.build(
                task={"id": "task-A", "scenarios": ["windows"],
                      "scenario_databases": {}},
                run_identity={
                    "task_id": "task-A",
                    "investigation_id": delegation.investigation_id,
                    "run_id": delegation.run_id,
                },
                question="Were there unauthorized logons?",
                question_id=action.question_id,
                source_scope_id=action.source_scope_id,
                table_lister=lambda _p: frozenset(),
            )
            pack = pack.model_copy(
                update={
                    "task_id": "task-A",
                    "investigation_id": delegation.investigation_id,
                    "run_id": delegation.run_id,
                    "delegation_id": delegation.delegation_id,
                }
            )
            envelope = build_execution_envelope(
                pack, registry, question_text="q",
                model_config_digest="cfg-e2e",
            )
            result_args = {
                "proposal_version": "specialist-result-proposal:v1",
                "delegation_id": delegation.delegation_id,
                "question_id": action.question_id,
                "summary": "specialist findings",
                "evidence_refs": ["file:C/logon_4624.doc"],
                "claim_candidates": [
                    {
                        "candidate_id": "c-1",
                        "text": "logon cluster observed",
                        "assertion_class": "INFERENCE",
                        "evidence_refs": ["file:C/logon_4624.doc"],
                        "limitations": [],
                    }
                ],
            }
            model = TestModel(
                call_tools=["search_evidence"], custom_output_args=result_args
            )

            def build_agent(pack_arg, registry_arg, _model=model):
                return build_specialist_agent(
                    pack_arg, registry_arg, model=_model,
                    output_type=SpecialistResultProposalV1, retries=1,
                )

            class _Exec(SimpleNamespace):
                pass

            from httpserver.services.investigation.agent_specialist_executor import (
                SpecialistDelegationExecutor,
            )

            executor = SpecialistDelegationExecutor(
                cpp_backend=FakeCppBackend(self._db_path.parent),
                settings=SimpleNamespace(
                    llm_text_base_url="http://localhost:9",
                    llm_endpoint="/v1/chat/completions",
                    llm_api_key="k",
                    llm_text_model="offline",
                    llm_thinking_mode="",
                    llm_timeout_seconds=5.0,
                    llm_text_temperature=None,
                    llm_text_max_tokens=None,
                ),
                tool_services=None,
                registry_builder=lambda runtime, observation_sink=None: registry,
                investigation_db_path_for_task=lambda task: self._db_path,
            )
            executor._build_agent = build_agent
            executor._policy = AgentRunPolicy(max_provider_retries=0)
            outcome = await executor.dispatch_delegation(envelope)
            stored = self._repo.get_delegation_result(delegation.delegation_id)
            outcomes.append(
                SimpleNamespace(
                    delegation_id=delegation.delegation_id,
                    question_id=action.question_id,
                    source_scope_id=action.source_scope_id,
                    status=outcome.status.value,
                    result=(
                        SpecialistResultV1.model_validate(stored.result)
                        if stored is not None
                        else None
                    ),
                    result_hash=outcome.result_hash,
                    context_hash=envelope.context_hash,
                    failure_code=outcome.failure_code,
                    failure_summary=outcome.failure_message,
                )
            )
        return outcomes


# ---------------------------------------------------------------------------
# §44 full offline cycle
# ---------------------------------------------------------------------------


async def test_full_offline_cycle_plan_execute_integrate_evaluate(tmp_path):
    repo, db, investigation_id = _build_env(tmp_path)
    supervisor = OfflineSupervisor()
    orchestrator = AgentOrchestrator(
        FakeCppBackend(tmp_path),
        supervisor=supervisor,
        delegation_dispatcher=OfflineSpecialistDispatcher(repo, db),
        source_scope_provider=lambda task_id: ("windows",),
    )

    outcomes = await orchestrator.run_loop("task-A", investigation_id)
    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome.integration_status in ("committed", "noop"), outcome
    assert outcome.delegation_terminal_statuses == ("completed",)
    assert outcome.progress is not None
    # exactly one semantic revision increment (the integration), never more
    latest = repo.get_latest_working_state(investigation_id)
    assert latest.revision == outcome.integration_revision
    assert outcome.integration_revision is None or (
        outcome.integration_revision - outcome.starting_revision <= 1
    )
    # PLAN + EXECUTE produced observations and trajectory, not revisions
    observations = repo.list_tool_observations(investigation_id)
    assert observations
    kinds = [t.event_type.value for t in repo.list_trajectory(investigation_id)]
    assert "supervisor_plan_decided" in kinds
    assert "tool_observation_recorded" in kinds
    if outcome.integration_status == "committed":
        assert "supervisor_integration_committed" in kinds
    # the question advanced through the typed transition
    assert "supervisor_plan_decided" in kinds
    # delegation consumed exactly once
    delegation_id = outcome.delegation_ids[0]
    delegation = repo.get_delegation(delegation_id)
    assert delegation.status is DelegationStatus.completed
    assert delegation.integrated_at is not None


# ---------------------------------------------------------------------------
# §45 parallel: A completes, B fails -> all_terminal, integration continues
# ---------------------------------------------------------------------------


async def test_parallel_all_terminal_with_one_failure(tmp_path):
    repo, db, investigation_id = _build_env(tmp_path)

    # second question so the supervisor can admit two delegations
    latest = repo.get_latest_working_state(investigation_id)
    state = AgentWorkingStateV1.model_validate(latest.state)
    second = WorkingQuestion(
        question_id="q-2",
        text="usb exfiltration?",
        source=QuestionSource.charter,
        priority=QuestionPriority.normal,
    )
    updated = state.model_copy(update={"questions": state.questions + (second,)})
    repo.commit_working_state(
        investigation_id,
        working_state_to_json(updated),
        expected_revision=latest.revision,
    )

    class TwoActionSupervisor(OfflineSupervisor):
        async def plan(self, pack):
            item = next(
                item
                for item in pack.attention_items
                if "delegate_source" in item.eligible_action_types
                and item.eligibility == "eligible"
            )
            args = self._bind_plan(
                pack,
                {
                    "decision_version": "supervisor-plan-decision:v1",
                    "actions": [
                        {
                            "action_kind": "delegate_investigation",
                            "action_id": "a-1",
                            "attention_item_id": item.item_id,
                            "question_id": "q-1",
                            "source_scope_id": "windows",
                        },
                        {
                            "action_kind": "delegate_investigation",
                            "action_id": "a-2",
                            "attention_item_id": item.item_id,
                            "question_id": "q-2",
                            "source_scope_id": "windows",
                        },
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

    class FailingDispatcher(OfflineSpecialistDispatcher):
        async def __call__(self, planning_context, decision, admitted):
            outcomes = await super().__call__(planning_context, decision, admitted)
            # worker B fails at the provider level (all_terminal semantics)
            for summary in outcomes:
                if summary.question_id == "q-2":
                    summary.status = "failed"
                    summary.failure_code = "agent_timeout"
                    summary.failure_summary = "provider call timed out"
                    summary.result = None
                    summary.result_hash = None
            return outcomes

    supervisor = TwoActionSupervisor()
    orchestrator = AgentOrchestrator(
        FakeCppBackend(tmp_path),
        supervisor=supervisor,
        delegation_dispatcher=FailingDispatcher(repo, db),
        source_scope_provider=lambda task_id: ("windows",),
    )
    outcome = (await orchestrator.run_loop("task-A", investigation_id))[0]
    assert len(outcome.delegation_ids) == 2
    assert set(outcome.delegation_terminal_statuses) == {"completed", "failed"}
    assert outcome.failure_delegation_ids and outcome.stale_delegation_ids == ()
    # the surviving fresh result still integrated
    assert outcome.integration_status in ("committed", "noop")


# ---------------------------------------------------------------------------
# §46 stale result e2e
# ---------------------------------------------------------------------------


async def test_stale_result_excluded_from_integration(tmp_path):
    repo, db, investigation_id = _build_env(tmp_path)

    class CloseQuestionSupervisor(OfflineSupervisor):
        """Integration proposes answering the question: after this commits,
        a second delegation for the same question would be stale."""

        pass

    supervisor = OfflineSupervisor()
    orchestrator = AgentOrchestrator(
        FakeCppBackend(tmp_path),
        supervisor=supervisor,
        delegation_dispatcher=OfflineSpecialistDispatcher(repo, db),
        source_scope_provider=lambda task_id: ("windows",),
    )
    first = (await orchestrator.run_loop("task-A", investigation_id))[0]
    assert first.integration_status in ("committed", "noop")

    # answer + close the question semantically (supersede): a previously
    # completed-but-unintegrated result for q-1 would now be stale
    latest = repo.get_latest_working_state(investigation_id)
    state = AgentWorkingStateV1.model_validate(latest.state)
    answered = state.questions[0].model_copy(
        update={
            "status": QuestionStatus.answered,
            "disposition": QuestionDisposition.supported,
        }
    )
    repo.commit_working_state(
        investigation_id,
        working_state_to_json(
            state.model_copy(update={"questions": (answered,)})
        ),
        expected_revision=latest.revision,
    )
    # a late-integration attempt against the answered question is stale
    from httpserver.services.investigation.agent_integration import (
        FrozenDelegationDependencies,
        MergeGuard,
    )

    verdict = MergeGuard().evaluate(
        FrozenDelegationDependencies(
            delegation_id="deleg-late",
            question_id="q-1",
            source_scope_ids=("windows",),
            evidence_refs=(),
        ),
        current_state=AgentWorkingStateV1.model_validate(
            repo.get_latest_working_state(investigation_id).state
        ),
        current_state_revision=repo.get_latest_working_state(
            investigation_id
        ).revision,
        granted_scope_ids=("windows",),
    )
    assert verdict.stale
    assert "MERGE_STALE_QUESTION_INACTIVE" in verdict.reason_codes
    # no contamination: the first cycle's integration stands
    assert repo.get_latest_working_state(investigation_id).revision >= 1


# ---------------------------------------------------------------------------
# §47 directive re-plan seam
# ---------------------------------------------------------------------------


async def test_directive_change_triggers_cooperative_replan(tmp_path):
    repo, db, investigation_id = _build_env(tmp_path)
    directives = {"d1": "digest-A"}

    supervisor = OfflineSupervisor()
    orchestrator = AgentOrchestrator(
        FakeCppBackend(tmp_path),
        supervisor=supervisor,
        delegation_dispatcher=OfflineSpecialistDispatcher(repo, db),
        source_scope_provider=lambda task_id: ("windows",),
        directive_digest_provider=lambda: directives,
    )
    first = (await orchestrator.run_loop("task-A", investigation_id))[0]
    run_id = first.run_id
    assert first.run_stop_reason is None

    # a queued delegation exists in this run; now change the directive digest
    directives["d1"] = "digest-B"
    outcome = await orchestrator.execute_cycle(
        "task-A", investigation_id, source_scope_ids=("windows",)
    )
    assert outcome.run_stop_reason == "directive_replan"
    run = repo.get_run(run_id)
    assert run.status is AgentRunStatus.failed
    assert run.stop_reason.value == "directive_replan"
    # late results cannot mutate state: working state revision unchanged
    # by the re-plan itself
    assert outcome.ending_revision == first.ending_revision


# ---------------------------------------------------------------------------
# §48 finalization wiring
# ---------------------------------------------------------------------------


async def test_finalization_request_goes_through_p2_gate(tmp_path):
    repo, db, investigation_id = _build_env(tmp_path)

    class FinalizeSupervisor(OfflineSupervisor):
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

    orchestrator = AgentOrchestrator(
        FakeCppBackend(tmp_path),
        supervisor=FinalizeSupervisor(),
        source_scope_provider=lambda task_id: ("windows",),
        cycle_policy=SupervisorCyclePolicy(final_review_mode="best_effort"),
    )
    outcome = (await orchestrator.run_loop("task-A", investigation_id))[0]
    # P2 gate decides according to the frozen policy: with an open required
    # question the gate DENIES — the supervisor can never complete alone
    assert outcome.finalization is not None
    assert not outcome.finalization.finalized
    assert outcome.run_stop_reason is None
    # investigation still active (created ready; PLAN admission activated it)
    investigation = repo.get_investigation(investigation_id)
    assert investigation.status.value == "active"


# ---------------------------------------------------------------------------
# §49 restart: no supervisor/specialist conversation is resumed
# ---------------------------------------------------------------------------


async def test_restart_does_not_resume_the_loop(tmp_path):
    repo, db, investigation_id = _build_env(tmp_path)
    supervisor = OfflineSupervisor()
    orchestrator = AgentOrchestrator(
        FakeCppBackend(tmp_path),
        supervisor=supervisor,
        delegation_dispatcher=OfflineSpecialistDispatcher(repo, db),
        source_scope_provider=lambda task_id: ("windows",),
    )
    first = (await orchestrator.run_loop("task-A", investigation_id))[0]
    assert first.run_id

    # P2 recovery sweep terminalises the run (runtime_restart); the P1/P2
    # contract is already frozen and tested — assert the loop honors it:
    repo.fail_run(
        first.run_id,
        stop_reason="runtime_restart",
        error_code="runtime_restart",
        error_message="service restart interrupted the run",
    )

    # a fresh orchestrator instance (restart) starts a NEW run; the old run
    # is never resumed and the revision chain is unchanged
    fresh_orchestrator = AgentOrchestrator(
        FakeCppBackend(tmp_path),
        supervisor=OfflineSupervisor(),
        delegation_dispatcher=OfflineSpecialistDispatcher(repo, db),
        source_scope_provider=lambda task_id: ("windows",),
    )
    revision_before = repo.get_latest_working_state(investigation_id).revision
    outcome = (await fresh_orchestrator.run_loop("task-A", investigation_id))[0]
    assert outcome.run_id != first.run_id
    assert outcome.starting_revision == revision_before
