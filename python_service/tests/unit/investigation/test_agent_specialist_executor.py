"""P4A-2 tests: execution envelope, failure mapping, executor behaviour.

All agent executions run offline through pydantic_ai FunctionModel/TestModel;
provider failures are simulated with typed exceptions.
"""

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from httpserver.services.investigation.agent_capabilities import (
    ArtifactFamilyRegistry,
    build_source_capability_manifest,
)
from httpserver.services.investigation.agent_context import (
    ContextAssembler,
    EvidenceDigestItem,
    ProfileDigest,
    SpecialistContextPack,
)
from httpserver.services.investigation.agent_deps import ForensicAgentDeps
from httpserver.services.investigation.agent_profiles import default_profiles
from httpserver.services.investigation.agent_runtime import (
    AgentRuntimeRepository,
    AgentTrajectoryEventType,
    DelegationStatus,
)
from httpserver.services.investigation.agent_skills import SkillRegistry
from httpserver.services.investigation.agent_specialist_executor import (
    AgentRunPolicy,
    DelegationExecutionEnvelope,
    DelegationFailureCode,
    DispatchStatus,
    SkillBinding,
    SpecialistDelegationExecutor,
    build_execution_envelope,
    map_provider_exception,
    model_config_digest_from_adapter_config,
    verify_envelope_bindings,
)
from httpserver.services.investigation.agent_specialist_result import (
    AssertionClass,
    SpecialistClaimCandidate,
    SpecialistResultV1,
    SpecialistResultValidator,
)
from httpserver.services.investigation.agent_tools.adapters import (
    build_read_only_registry,
)
from httpserver.services.investigation.agent_tools.observations import (
    AgentObservationSink,
)
from httpserver.services.investigation.repository import (
    SUPPORTED_SCHEMA_VERSION,
    InvestigationRepository,
)
from httpserver.services.investigation.paths import investigation_db_path_for_task

pytest.importorskip("pydantic_ai")
pytestmark = pytest.mark.migration_matrix


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------


TASK = {
    "id": "task-A",
    "image_name": "disk.E01",
    "status": "done",
    "scenarios": ["windows"],
    "scenario_databases": {"windows": "/fake/windows.db"},
    "output_files_db": "/fake/task-A_files.db",
    "output_events_db": "/fake/task-A_events.db",
}


class FakeCppBackend:
    def __init__(self, task=TASK):
        self._task = task

    async def get_task(self, task_id, **kwargs):
        if self._task is None or self._task.get("id") != task_id:
            return None
        return self._task


class _NullServices:
    def __getattr__(self, name):
        raise AssertionError("services must not be touched offline")


class _FakeReadService:
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


class _FakeInvestigationService:
    async def resolve_evidence(self, task_id, evidence_key):
        return None

    async def effective_event_claims(self, task_id, event_id):
        return []


class _FakeExecutor:
    async def list_analyses(self, task_id, key):
        return []

    async def list_all_analyses(self, task_id):
        return {}


def _offline_services():
    return SimpleNamespace(
        cpp_backend=SimpleNamespace(
            get_task=None,
            get_task_files_paginated=None,
            get_task_events=None,
        ),
        investigation_service=_FakeInvestigationService(),
        investigation_read_service=_FakeReadService(),
        investigation_event_service=SimpleNamespace(),
        secondary_analysis_executor=_FakeExecutor(),
    )


def _registry_builder(runtime, observation_sink=None):
    from httpserver.services.investigation.agent_tools.observations import (
        AgentObservationSink as Sink,
    )

    return build_read_only_registry(
        _offline_services(),
        observation_sink=observation_sink or Sink(runtime),
    )


class FakeSettings:
    llm_text_base_url = "http://localhost:9"
    llm_endpoint = "/v1/chat/completions"
    llm_api_key = "test-key"
    llm_text_model = "offline-model"
    llm_thinking_mode = ""
    llm_thinking_body = {}
    llm_timeout_seconds = 5.0
    llm_text_temperature = None
    llm_text_max_tokens = None


class _OutputModel(BaseModel):
    """Tool input contract for the offline fake tool."""

    model_config = ConfigDict(extra="forbid")

    query: str


def _build_pack(question_id="q-1") -> SpecialistContextPack:
    assembler = ContextAssembler(
        skill_registry=SkillRegistry.with_defaults(),
        family_registry=ArtifactFamilyRegistry.with_defaults(),
        profiles=default_profiles(),
        tool_schema_hash="hash-offline",
    )
    return assembler.build(
        task=TASK,
        run_identity={
            "task_id": "task-A",
            "investigation_id": "inv-A",
            "run_id": "run-A",
        },
        question="unusual logons?",
        source_scope_id="windows",
        question_id=question_id,
        coverage_dimension_ids=("authentication",),
        table_lister=lambda _p: frozenset({"registry_values", "event_log_entries", "user_accounts"}),
    )


@pytest.fixture()
def runtime_env(tmp_path):
    db_path = tmp_path / "investigation.db"
    store = InvestigationRepository(db_path, "task-A")
    repo = AgentRuntimeRepository(store)
    investigation, revision = repo.create_investigation({"objective": "p4a"})
    run = repo.start_run(investigation.investigation_id)
    repo.mark_run_running(run.run_id)
    return repo, db_path, investigation, run, revision


def _admit_delegation(repo, run, question_ref="q-1") -> str:
    from httpserver.services.investigation.agent_runtime import DelegationSpec

    delegations = repo.admit_delegations(
        run.run_id,
        [
            DelegationSpec(
                question_ref=question_ref,
                based_on_state_revision=1,
                idempotency_key=f"deleg-key-{question_ref}",
            )
        ],
    )
    return delegations[0].delegation_id


def _make_envelope(
    runtime_env, *, registry, question_id="q-1"
) -> DelegationExecutionEnvelope:
    repo, _db, investigation, run, revision = runtime_env
    pack = _build_pack(question_id=question_id)
    # bind the pack to the real run identity
    pack = pack.model_copy(
        update={
            "investigation_id": investigation.investigation_id,
            "run_id": run.run_id,
            "delegation_id": "deleg-A",
        }
    )
    digest = model_config_digest_from_adapter_config(
        SimpleNamespace(
            model_dump=lambda: {
                "base_url": "http://localhost:9/v1",
                "model_name": "offline-model",
                "thinking_extra_body": {},
            }
        )
    )
    return build_execution_envelope(
        pack,
        registry,
        question_text="unusual logons?",
        based_on_state_revision=revision.revision,
        skill_bindings=(
            SkillBinding(skill_id="windows.authentication", version="1"),
        ),
        model_config_digest=digest,
    )


def _executor(runtime_env, *, agent_runner) -> SpecialistDelegationExecutor:
    """Executor whose model runs the given offline runner."""

    repo, db_path, investigation, run, revision = runtime_env

    class OfflineModel:
        """pydantic_ai Model stand-in driven by `agent_runner`."""

        def __init__(self, runner):
            self._runner = runner

        # pydantic_ai Agent accepts a Model instance; we bypass Agent entirely
        # by patching build path — see executor override below.

    class OfflineExecutor(SpecialistDelegationExecutor):
        def _build_agent(self, pack, registry):
            return _OfflineAgent(self._runner)

        def _get_model(self):
            return object()

    executor = OfflineExecutor(
        cpp_backend=FakeCppBackend(),
        settings=FakeSettings(),
        tool_services=_NullServices(),
        registry_builder=_registry_builder,
        investigation_db_path_for_task=lambda task: db_path,
    )
    executor._runner = agent_runner
    return executor


class _OfflineAgent:
    """Duck-typed Agent: exercises the real registry toolset once, then
    returns a SpecialistResultV1 produced by the runner hook."""

    def __init__(self, runner):
        self._runner = runner

    async def run(self, prompt, *, deps, usage_limits=None):
        self.last_deps = deps
        toolset = None
        # exercise one real read-only tool through the deps-bound registry so
        # ToolObservations are produced exactly as in production
        registry = deps.tool_registry
        context = deps.tool_context
        await registry.execute(
            context,
            "search_evidence",
            {"query": "logon"},
        )
        result, usage = self._runner(deps, context)
        self.usage = usage
        self.result = result
        # mimic pydantic_ai AgentRunResult: usage is a method
        return SimpleNamespace(
            output=result, usage=lambda: usage, response=None
        )


def _good_result(delegation_id, question_id="q-1") -> SpecialistResultV1:
    return SpecialistResultV1(
        delegation_id=delegation_id,
        question_id=question_id,
        summary="specialist summary",
        claim_candidates=(
            SpecialistClaimCandidate(
                candidate_id="c-1",
                text="logon pattern observed",
                assertion_class=AssertionClass.INFERENCE,
                evidence_refs=("file:C/logon_4624.doc",),
            ),
        ),
        evidence_refs=("file:C/logon_4624.doc",),
    )


# ---------------------------------------------------------------------------
# envelope (P4A-E7)
# ---------------------------------------------------------------------------


def test_envelope_frozen_and_input_hash_deterministic(runtime_env):
    repo, _db, _inv, _run, _rev = runtime_env
    registry = _registry_builder(repo)
    first = _make_envelope(runtime_env, registry=registry)
    second = _make_envelope(runtime_env, registry=registry)
    assert first.context_hash == second.context_hash
    assert first.execution_input_hash() == second.execution_input_hash()
    drifted = first.model_copy(
        update={"model_config_digest": "different"}
    )
    assert drifted.execution_input_hash() != first.execution_input_hash()


def test_envelope_binds_frozen_result_contract(runtime_env):
    repo, _db, _inv, _run, _rev = runtime_env
    registry = _registry_builder(repo)
    envelope = _make_envelope(runtime_env, registry=registry)
    assert envelope.output_contract_ref == "specialist-result:v1"
    payload = envelope.model_dump()
    payload["output_contract_ref"] = "specialist-result:P4-placeholder"
    with pytest.raises(ValueError):
        DelegationExecutionEnvelope(**payload)


# ---------------------------------------------------------------------------
# failure mapping (P4A-E11)
# ---------------------------------------------------------------------------


def test_provider_failure_mapping():
    from pydantic_ai.exceptions import ModelHTTPError

    assert (
        map_provider_exception(ModelHTTPError(402, "billing"))
        is DelegationFailureCode.AGENT_BILLING_UNAVAILABLE
    )
    assert (
        map_provider_exception(ModelHTTPError(401, "auth"))
        is DelegationFailureCode.AGENT_AUTH_FAILED
    )
    assert (
        map_provider_exception(ModelHTTPError(429, "rate"))
        is DelegationFailureCode.AGENT_RATE_LIMITED
    )
    assert (
        map_provider_exception(ModelHTTPError(503, "down"))
        is DelegationFailureCode.AGENT_PROVIDER_UNAVAILABLE
    )
    assert (
        map_provider_exception(TimeoutError())
        is DelegationFailureCode.AGENT_TIMEOUT
    )
    assert (
        map_provider_exception(RuntimeError("whatever"))
        is DelegationFailureCode.AGENT_INTERNAL_FAILURE
    )
    mapped = map_provider_exception(ModelHTTPError(402, "x"))
    # a billing failure is never recorded as an evidence conclusion
    assert mapped.value == "agent_billing_unavailable"
    assert "evidence" not in mapped.value


# ---------------------------------------------------------------------------
# binding verification (§36)
# ---------------------------------------------------------------------------


def test_binding_mismatch_detected(runtime_env):
    repo, _db, _inv, _run, _rev = runtime_env
    registry = _registry_builder(repo)
    envelope = _make_envelope(runtime_env, registry=registry)
    assert verify_envelope_bindings(envelope, envelope.context_pack, registry) is None
    drifted_pack = envelope.context_pack.model_copy(
        update={"working_state_revision": 99}
    )
    assert verify_envelope_bindings(envelope, drifted_pack, registry) is not None


# ---------------------------------------------------------------------------
# executor paths
# ---------------------------------------------------------------------------


async def test_successful_delegation_execution(runtime_env):
    repo, _db, investigation, _run, _rev = runtime_env
    registry = _registry_builder(repo)
    delegation_id = _admit_delegation(repo, _run)
    pack = _build_pack().model_copy(
        update={
            "investigation_id": investigation.investigation_id,
            "run_id": _run.run_id,
            "delegation_id": delegation_id,
        }
    )
    envelope = build_execution_envelope(
        pack,
        registry,
        question_text="unusual logons?",
        based_on_state_revision=1,
        skill_bindings=(SkillBinding(skill_id="windows.authentication", version="1"),),
        model_config_digest="digest-1",
    )
    runner_result = _good_result(delegation_id, question_id="q-1")
    executor = _executor(
        runtime_env,
        agent_runner=lambda deps, context: (
            runner_result,
            SimpleNamespace(requests=2, input_tokens=100, output_tokens=40),
        ),
    )
    outcome = await executor.dispatch_delegation(envelope)
    assert outcome.status is DispatchStatus.COMPLETED, outcome.failure_message
    assert outcome.result_hash

    delegation = repo.get_delegation(delegation_id)
    assert delegation.status is DelegationStatus.completed
    stored = repo.get_delegation_result(delegation_id)
    assert stored is not None
    assert stored.validation_status == "valid"
    assert stored.result_hash == outcome.result_hash
    assert stored.result["summary"] == "specialist summary"
    assert stored.usage == {
        "requests": 2,
        "input_tokens": 100,
        "output_tokens": 40,
    }
    # tool audit happened through the frozen P3 contract
    observations = repo.list_tool_observations(investigation.investigation_id)
    assert observations
    trajectory = [
        t
        for t in repo.list_trajectory(investigation.investigation_id)
        if t.event_type == AgentTrajectoryEventType.tool_observation_recorded
    ]
    assert trajectory
    # P4A-E17: working state untouched
    latest = repo.get_latest_working_state(investigation.investigation_id)
    assert latest.revision == 1


async def test_invalid_result_failed_and_audited(runtime_env):
    repo, _db, investigation, _run, _rev = runtime_env
    registry = _registry_builder(repo)
    delegation_id = _admit_delegation(repo, _run)
    pack = _build_pack().model_copy(
        update={
            "investigation_id": investigation.investigation_id,
            "run_id": _run.run_id,
            "delegation_id": delegation_id,
        }
    )
    envelope = build_execution_envelope(
        pack, registry, question_text="q?",
        model_config_digest="digest-1",
    )
    # result cites invisible evidence -> validator rejects
    bad_result = _good_result(delegation_id).model_copy(
        update={"evidence_refs": ("file:C/never_seen.doc",)}
    )
    executor = _executor(
        runtime_env,
        agent_runner=lambda deps, context: (
            bad_result,
            SimpleNamespace(requests=1),
        ),
    )
    outcome = await executor.dispatch_delegation(envelope)
    assert outcome.status is DispatchStatus.FAILED
    assert outcome.failure_code == DelegationFailureCode.AGENT_OUTPUT_INVALID.value
    assert "RESULT_EVIDENCE_NOT_VISIBLE" in outcome.validation_codes
    delegation = repo.get_delegation(delegation_id)
    assert delegation.status is DelegationStatus.failed
    stored = repo.get_delegation_result(delegation_id)
    assert stored.validation_status == "invalid"


async def test_provider_402_maps_to_billing_failure(runtime_env):
    repo, _db, investigation, _run, _rev = runtime_env
    registry = _registry_builder(repo)
    delegation_id = _admit_delegation(repo, _run)
    pack = _build_pack().model_copy(
        update={
            "investigation_id": investigation.investigation_id,
            "run_id": _run.run_id,
            "delegation_id": delegation_id,
        }
    )
    envelope = build_execution_envelope(
        pack, registry, question_text="q?", model_config_digest="d"
    )

    from pydantic_ai.exceptions import ModelHTTPError

    class FailingAgent:
        async def run(self, prompt, *, deps, usage_limits=None):
            raise ModelHTTPError(402, "Insufficient Balance")

    class FailingExecutor(_executor(runtime_env, agent_runner=None).__class__):
        pass

    executor = _executor(runtime_env, agent_runner=None)
    executor._build_agent = lambda pack, registry: FailingAgent()
    executor._policy = AgentRunPolicy(max_provider_retries=0)

    outcome = await executor.dispatch_delegation(envelope)
    assert outcome.status is DispatchStatus.FAILED
    assert (
        outcome.failure_code
        == DelegationFailureCode.AGENT_BILLING_UNAVAILABLE.value
    )
    delegation = repo.get_delegation(delegation_id)
    assert delegation.status is DelegationStatus.failed
    assert delegation.failure_code == "agent_billing_unavailable"
    assert repo.get_delegation_result(delegation_id) is None


async def test_cancel_before_start_never_calls_agent(runtime_env):
    repo, _db, investigation, _run, _rev = runtime_env
    registry = _registry_builder(repo)
    delegation_id = _admit_delegation(repo, _run)
    repo.request_delegation_cancel(delegation_id)
    pack = _build_pack().model_copy(
        update={
            "investigation_id": investigation.investigation_id,
            "run_id": _run.run_id,
            "delegation_id": delegation_id,
        }
    )
    envelope = build_execution_envelope(
        pack, registry, question_text="q?", model_config_digest="d"
    )
    calls = {"n": 0}

    def runner(deps, context):
        calls["n"] += 1
        return _good_result(delegation_id), None

    executor = _executor(runtime_env, agent_runner=runner)
    outcome = await executor.dispatch_delegation(envelope)
    assert outcome.status is DispatchStatus.CANCELLED
    assert calls["n"] == 0
    assert repo.get_delegation(delegation_id).status is DelegationStatus.cancelled
    # no result row, working state untouched
    assert repo.get_delegation_result(delegation_id) is None
    assert repo.get_latest_working_state(investigation.investigation_id).revision == 1


async def test_late_output_after_cancel_is_cancelled(runtime_env):
    repo, _db, investigation, _run, _rev = runtime_env
    registry = _registry_builder(repo)
    delegation_id = _admit_delegation(repo, _run)
    pack = _build_pack().model_copy(
        update={
            "investigation_id": investigation.investigation_id,
            "run_id": _run.run_id,
            "delegation_id": delegation_id,
        }
    )
    envelope = build_execution_envelope(
        pack, registry, question_text="q?", model_config_digest="d"
    )

    class CancelDuringRunAgent:
        async def run(self, prompt, *, deps, usage_limits=None):
            # the operator cancels while the agent works
            repo.request_delegation_cancel(delegation_id)
            await registry.execute(
                deps.tool_context, "search_evidence", {"query": "x"}
            )
            return SimpleNamespace(
                output=_good_result(delegation_id),
                usage=lambda: SimpleNamespace(requests=1),
                response=None,
            )

    executor = _executor(runtime_env, agent_runner=None)
    executor._build_agent = lambda pack, registry: CancelDuringRunAgent()
    outcome = await executor.dispatch_delegation(envelope)
    assert outcome.status is DispatchStatus.CANCELLED
    # late semantic result is NOT persisted as a valid completed result
    assert repo.get_delegation_result(delegation_id) is None
    assert repo.get_delegation(delegation_id).status is DelegationStatus.cancelled
    assert repo.get_latest_working_state(investigation.investigation_id).revision == 1


async def test_binding_change_fails_closed(runtime_env):
    repo, _db, investigation, _run, _rev = runtime_env
    registry = _registry_builder(repo)
    delegation_id = _admit_delegation(repo, _run)
    pack = _build_pack().model_copy(
        update={
            "investigation_id": investigation.investigation_id,
            "run_id": _run.run_id,
            "delegation_id": delegation_id,
        }
    )
    envelope = build_execution_envelope(
        pack, registry, question_text="q?", model_config_digest="d"
    )
    # the live registry surface changes after the envelope was frozen
    from httpserver.services.investigation.agent_tools.registry import (
        ForensicToolRegistry,
        ToolExecutionOutcome,
    )
    from httpserver.services.investigation.agent_tools.definitions import (
        EvidenceBehavior,
        ForensicToolDefinition,
        ToolAccess,
        ToolCategory,
        ToolCostClass,
        ToolPaginationKind,
        ToolScopeKind,
    )

    class ExtraInput(BaseModel):
        model_config = ConfigDict(extra="forbid")
        q: str

    class ExtraOutput(BaseModel):
        model_config = ConfigDict(extra="forbid")
        note: str = "x"

    drifted = _registry_builder(repo)
    async def extra_adapter(invocation):
        return ToolExecutionOutcome(summary="s", result=ExtraOutput())

    drifted.register(
        ForensicToolDefinition(
            tool_id="surprise_tool",
            version="1",
            title="t",
            description="d",
            input_model=ExtraInput,
            output_model=ExtraOutput,
            category=ToolCategory.EVIDENCE,
            access=ToolAccess.READ,
            scope_kind=ToolScopeKind.EVIDENCE,
            evidence_behavior=EvidenceBehavior.NON_EVIDENCE,
            cost_class=ToolCostClass.CHEAP,
            pagination_kind=ToolPaginationKind.NONE,
        ),
        extra_adapter,
    )
    envelope = envelope.model_copy(
        update={"tool_registry_hash": drifted.schema_hash()}
    )
    executor = _executor(runtime_env, agent_runner=None)
    outcome = await executor.dispatch_delegation(envelope)
    assert outcome.status is DispatchStatus.FAILED
    assert (
        outcome.failure_code
        == DelegationFailureCode.INPUT_CONTRACT_CHANGED.value
    )
    assert repo.get_delegation(delegation_id).status is DelegationStatus.failed


async def test_task_vanished_is_skipped_without_terminal_write(runtime_env):
    repo, _db, investigation, _run, _rev = runtime_env
    registry = _registry_builder(repo)
    delegation_id = _admit_delegation(repo, _run)
    pack = _build_pack().model_copy(
        update={
            "investigation_id": investigation.investigation_id,
            "run_id": _run.run_id,
            "delegation_id": delegation_id,
        }
    )
    envelope = build_execution_envelope(
        pack, registry, question_text="q?", model_config_digest="d"
    )
    executor = _executor(runtime_env, agent_runner=None)
    executor._cpp_backend = FakeCppBackend(task=None)
    outcome = await executor.dispatch_delegation(envelope)
    assert outcome.status is DispatchStatus.SKIPPED
    assert outcome.skipped_reason == "task_unavailable"
    # delegation still queued, untouched
    assert repo.get_delegation(delegation_id).status is DelegationStatus.queued


# ---------------------------------------------------------------------------
# bounded parallelism (§53) + restart (§54)
# ---------------------------------------------------------------------------


def _concurrency_runner(max_seen):
    async def run(self, prompt, *, deps, usage_limits=None):
        max_seen["current"] += 1
        max_seen["peak"] = max(max_seen["peak"], max_seen["current"])
        try:
            await asyncio.sleep(0.05)
            await deps.tool_registry.execute(
                deps.tool_context, "search_evidence", {"query": "logon"}
            )
            context = deps.tool_context
            return SimpleNamespace(
                output=_good_result(
                    context.delegation_id, question_id=context.question_id
                ),
                usage=lambda: None,
                response=None,
            )
        finally:
            max_seen["current"] -= 1

    return run


def _envelope_for(repo_env_pack_delegation, registry):
    pack, delegation_id = repo_env_pack_delegation
    return build_execution_envelope(
        pack, registry, question_text="q?", model_config_digest="d"
    )


async def test_bounded_parallel_execution(runtime_env):
    repo, _db, investigation, run, _rev = runtime_env
    registry = _registry_builder(repo)
    max_seen = {"current": 0, "peak": 0}
    envelopes = []
    for index in range(4):
        delegation_id = _admit_delegation(repo, run, question_ref=f"q-{index}")
        pack = _build_pack(question_id=f"q-{index}").model_copy(
            update={
                "investigation_id": investigation.investigation_id,
                "run_id": run.run_id,
                "delegation_id": delegation_id,
            }
        )
        envelopes.append(
            build_execution_envelope(
                pack, registry, question_text="q?", model_config_digest="d"
            )
        )
    executor = _executor(runtime_env, agent_runner=None)
    executor._build_agent = lambda pack, registry: type(
        "_Agent",
        (),
        {"run": _concurrency_runner(max_seen)},
    )()
    executor._policy = AgentRunPolicy(max_parallel_delegations=2)

    outcomes = await executor.execute_batch(envelopes, mode="parallel_all")
    assert all(o.status is DispatchStatus.COMPLETED for o in outcomes)
    assert max_seen["peak"] <= 2
    # E15: no worker touched the working state
    assert repo.get_latest_working_state(investigation.investigation_id).revision == 1


async def test_sequential_mode_and_worker_isolation(runtime_env):
    repo, _db, investigation, run, _rev = runtime_env
    registry = _registry_builder(repo)
    good_id = _admit_delegation(repo, run, question_ref="q-good")
    pack_good = _build_pack(question_id="q-good").model_copy(
        update={
            "investigation_id": investigation.investigation_id,
            "run_id": run.run_id,
            "delegation_id": good_id,
        }
    )
    bad_id = _admit_delegation(repo, run, question_ref="q-bad")
    pack_bad = _build_pack(question_id="q-bad").model_copy(
        update={
            "investigation_id": investigation.investigation_id,
            "run_id": run.run_id,
            "delegation_id": bad_id,
        }
    )
    good_envelope = build_execution_envelope(
        pack_good, registry, question_text="q?", model_config_digest="d"
    )
    bad_envelope = build_execution_envelope(
        pack_bad, registry, question_text="q?", model_config_digest="d"
    )

    from pydantic_ai.exceptions import ModelHTTPError

    class MixedAgent:
        async def run(self, prompt, *, deps, usage_limits=None):
            if deps.tool_context.delegation_id == bad_id:
                raise ModelHTTPError(503, "down")
            await deps.tool_registry.execute(
                deps.tool_context, "search_evidence", {"query": "logon"}
            )
            return SimpleNamespace(
                output=_good_result(
                    deps.tool_context.delegation_id,
                    question_id=deps.tool_context.question_id,
                ),
                usage=lambda: None,
                response=None,
            )

    executor = _executor(runtime_env, agent_runner=None)
    executor._build_agent = lambda pack, registry: MixedAgent()
    executor._policy = AgentRunPolicy(max_provider_retries=0)
    outcomes = await executor.execute_batch(
        [bad_envelope, good_envelope], mode="sequential"
    )
    by_id = {o.delegation_id: o for o in outcomes}
    assert by_id[bad_id].status is DispatchStatus.FAILED
    assert by_id[good_id].status is DispatchStatus.COMPLETED
    # the failed worker did not corrupt the successful one
    assert repo.get_delegation_result(good_id) is not None
    assert repo.get_latest_working_state(investigation.investigation_id).revision == 1


async def test_restart_does_not_resume_running_delegation(runtime_env):
    repo, db_path, investigation, run, _rev = runtime_env
    registry = _registry_builder(repo)
    delegation_id = _admit_delegation(repo, run)
    repo.start_delegation(delegation_id)
    assert repo.get_delegation(delegation_id).status is DelegationStatus.running

    # P2 frozen recovery: interrupted running delegation -> failed(runtime_restart)
    recovered = repo.recover_interrupted_agent_runtime()
    assert recovered
    delegation = repo.get_delegation(delegation_id)
    assert delegation.status is DelegationStatus.failed
    assert delegation.failure_code == "runtime_restart"

    # a fresh executor lifecycle must not rerun it
    executor = _executor(runtime_env, agent_runner=None)
    await executor.initialize()
    outcome = await executor.dispatch_delegation(
        build_execution_envelope(
            _build_pack().model_copy(
                update={
                    "investigation_id": investigation.investigation_id,
                    "run_id": run.run_id,
                    "delegation_id": delegation_id,
                }
            ),
            registry,
            question_text="q?",
            model_config_digest="d",
        )
    )
    assert outcome.status is DispatchStatus.SKIPPED
    assert outcome.skipped_reason.startswith("already_terminal")
    assert repo.get_latest_working_state(investigation.investigation_id).revision == 1


# ---------------------------------------------------------------------------
# §49 offline E2E through a REAL pydantic_ai Agent + §55 audit chain
# ---------------------------------------------------------------------------


async def test_offline_e2e_real_agent_through_pydantic_ai(runtime_env):
    """ContextPack -> real PydanticAI Agent (TestModel) -> tool call through
    the frozen registry -> Observation + Trajectory -> structured
    SpecialistResultV1 -> validator -> delegation completed -> result
    persisted, with the Working State revision untouched."""
    from pydantic_ai.models.test import TestModel

    repo, _db, investigation, run, _rev = runtime_env
    registry = _registry_builder(repo)
    delegation_id = _admit_delegation(repo, run, question_ref="q-e2e")
    pack = _build_pack(question_id="q-e2e").model_copy(
        update={
            "investigation_id": investigation.investigation_id,
            "run_id": run.run_id,
            "delegation_id": delegation_id,
        }
    )
    envelope = build_execution_envelope(
        pack, registry, question_text="unusual logons?",
        based_on_state_revision=1,
        skill_bindings=(SkillBinding(skill_id="windows.authentication", version="1"),),
        model_config_digest="digest-e2e",
    )

    result_args = {
        "result_version": "specialist-result:v1",
        "delegation_id": delegation_id,
        "question_id": "q-e2e",
        "summary": "e2e specialist summary",
        "claim_candidates": [
            {
                "candidate_id": "c-1",
                "text": "logon cluster observed",
                "assertion_class": "INFERENCE",
                "evidence_refs": ["file:C/logon_4624.doc"],
                "limitations": [],
            }
        ],
        "evidence_refs": ["file:C/logon_4624.doc"],
        "execution_digest": {"tool_call_count": 0, "observation_count": 0},
    }
    model = TestModel(
        call_tools=["search_evidence"],
        custom_output_args=result_args,
    )

    def build_real_agent(pack_arg, registry_arg):
        from httpserver.services.investigation.agent_tools.pydantic_bridge import (
            build_specialist_agent,
        )

        return build_specialist_agent(
            pack_arg,
            registry_arg,
            model=model,
            output_type=SpecialistResultV1,
            retries=1,
        )

    executor = _executor(runtime_env, agent_runner=None)
    executor._build_agent = build_real_agent
    outcome = await executor.dispatch_delegation(envelope)
    assert outcome.status is DispatchStatus.COMPLETED, (
        outcome.failure_message,
        outcome.validation_codes,
    )

    stored = repo.get_delegation_result(delegation_id)
    assert stored is not None
    assert stored.validation_status == "valid"
    assert stored.result["summary"] == "e2e specialist summary"
    observations = repo.list_tool_observations(investigation.investigation_id)
    assert observations, "tool observation must exist"
    assert observations[0].evidence_refs == ("file:C/logon_4624.doc",)
    # §55 audit chain: delegation -> result -> context hash -> registry hash
    # -> observation -> trajectory -> model digest all recoverable
    delegation = repo.get_delegation(delegation_id)
    assert delegation.status is DelegationStatus.completed
    assert stored.context_hash == envelope.context_hash
    assert stored.tool_registry_hash == envelope.tool_registry_hash
    assert stored.model_config_hash == envelope.model_config_digest
    trajectory = [
        t
        for t in repo.list_trajectory(investigation.investigation_id)
        if t.event_type == AgentTrajectoryEventType.tool_observation_recorded
    ]
    assert trajectory
    assert trajectory[0].payload["observation_id"] == observations[0].observation_id
    # P4A-E17: no working state revision from agent completion
    assert repo.get_latest_working_state(investigation.investigation_id).revision == 1
