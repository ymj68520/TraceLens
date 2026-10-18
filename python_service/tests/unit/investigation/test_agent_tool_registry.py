"""P3-2 registry tests (work order §52): hashing, permissions, pipeline guards,
observation persistence, deterministic replay."""

import sqlite3
from typing import Any, Mapping

import pytest
from pydantic import BaseModel, ConfigDict

from httpserver.services.investigation.agent_runtime import AgentRuntimeRepository
from httpserver.services.investigation.agent_tools.context import (
    ForensicToolContext,
    ToolBudgetPolicy,
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
from httpserver.services.investigation.agent_tools.errors import (
    ToolErrorCode,
    ToolExecutionError,
)
from httpserver.services.investigation.agent_tools.observations import (
    AgentObservationSink,
)
from httpserver.services.investigation.agent_tools.registry import (
    REGISTRY_VERSION,
    ForensicToolRegistry,
    ToolExecutionOutcome,
)

from httpserver.services.investigation.repository import InvestigationRepository

pytestmark = pytest.mark.migration_matrix


class EchoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    source_scope_id: str | None = None


class EchoOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_count: int = 0
    items: tuple[str, ...] = ()


def echo_definition(tool_id: str = "echo_tool", **overrides) -> ForensicToolDefinition:
    fields = dict(
        tool_id=tool_id,
        version="1",
        title="Echo",
        description="echo adapter",
        input_model=EchoInput,
        output_model=EchoOutput,
        category=ToolCategory.EVIDENCE,
        access=ToolAccess.READ,
        scope_kind=ToolScopeKind.EVIDENCE,
        evidence_behavior=EvidenceBehavior.EVIDENCE_PRODUCING,
        cost_class=ToolCostClass.CHEAP,
        pagination_kind=ToolPaginationKind.NONE,
    )
    fields.update(overrides)
    return ForensicToolDefinition(**fields)


def make_registry(
    adapter=None, *, sink=None, evidence_ref_validator=None, **overrides
) -> ForensicToolRegistry:
    registry = ForensicToolRegistry(
        observation_sink=sink,
        evidence_ref_validator=evidence_ref_validator,
    )

    async def default_adapter(invocation) -> ToolExecutionOutcome:
        return ToolExecutionOutcome(
            summary="echo done",
            result=EchoOutput(result_count=1, items=("x",)),
            evidence_refs=invocation.args and ("file:C/x.txt",) or (),
        )

    registry.register(echo_definition(**overrides), adapter or default_adapter)
    return registry


def make_context(**overrides) -> ForensicToolContext:
    fields = dict(
        task_id="task-A",
        investigation_id="inv-A",
        run_id="run-A",
        allowed_tool_ids=frozenset({"echo_tool"}),
    )
    fields.update(overrides)
    return ForensicToolContext(**fields)


@pytest.fixture()
def runtime(tmp_path):
    store = InvestigationRepository(tmp_path / "investigation.db", "task-A")
    repo = AgentRuntimeRepository(store)
    investigation, _revision = repo.create_investigation({"objective": "t"})
    run = repo.start_run(investigation.investigation_id)
    repo.mark_run_running(run.run_id)
    return repo, investigation.investigation_id, run.run_id


# ---------------------------------------------------------------------------
# hashing (P3-E7)
# ---------------------------------------------------------------------------


def test_registry_schema_hash_deterministic_and_versioned():
    first = make_registry()
    second = make_registry()
    assert first.registry_version == REGISTRY_VERSION
    assert first.schema_hash() == second.schema_hash()


def test_registry_hash_changes_on_contract_change():
    base = make_registry()
    changed = make_registry(version="2")
    assert base.schema_hash() != changed.schema_hash()
    description_changed = make_registry()
    other = make_registry()
    other.register(
        echo_definition("other_tool"),
        _noop_adapter,
    )
    assert description_changed.schema_hash() != other.schema_hash()


async def _noop_adapter(invocation) -> ToolExecutionOutcome:
    return ToolExecutionOutcome(summary="noop", result=EchoOutput())


# ---------------------------------------------------------------------------
# registration permissions (P3-E8)
# ---------------------------------------------------------------------------


def test_only_read_tools_can_register():
    registry = ForensicToolRegistry()
    registry.register(echo_definition(), _noop_adapter)
    for access in (ToolAccess.PROPOSE, ToolAccess.MUTATE):
        with pytest.raises(ValueError, match="read-only"):
            registry.register(echo_definition("writer", access=access), _noop_adapter)
    assert all(d.access == ToolAccess.READ for d in registry.iter_definitions())


def test_unknown_tool_rejected():
    registry = make_registry()
    with pytest.raises(ToolExecutionError) as excinfo:
        registry.resolve_definition("ghost")
    assert excinfo.value.code == ToolErrorCode.TOOL_NOT_FOUND


async def test_unknown_tool_execution_rejected():
    registry = make_registry()
    with pytest.raises(ToolExecutionError) as execinfo:
        await registry.execute(make_context(), "ghost", {})
    assert execinfo.value.code == ToolErrorCode.TOOL_NOT_FOUND


# ---------------------------------------------------------------------------
# pipeline guards (P3-E6)
# ---------------------------------------------------------------------------


async def test_tool_not_allowed_for_run():
    registry = make_registry()
    context = make_context(allowed_tool_ids=frozenset({"other"}))
    with pytest.raises(ToolExecutionError) as excinfo:
        await registry.execute(context, "echo_tool", {"query": "x"})
    assert excinfo.value.code == ToolErrorCode.TOOL_NOT_ALLOWED


async def test_agent_type_restriction():
    registry = make_registry(
        allowed_agent_types=("specialist",),
    )
    context = make_context(agent_type="supervisor")
    with pytest.raises(ToolExecutionError) as excinfo:
        await registry.execute(context, "echo_tool", {"query": "x"})
    assert excinfo.value.code == ToolErrorCode.TOOL_AGENT_NOT_ALLOWED
    allowed = make_context(agent_type="specialist")
    await registry.execute(allowed, "echo_tool", {"query": "x"})


async def test_invalid_args_rejected_before_adapter():
    calls: list[Any] = []

    async def adapter(invocation) -> ToolExecutionOutcome:
        calls.append(invocation)
        return ToolExecutionOutcome(summary="s", result=EchoOutput())

    registry = make_registry(adapter=adapter)
    with pytest.raises(ToolExecutionError) as excinfo:
        await registry.execute(
            make_context(), "echo_tool", {"query": "x", "intruder": 1}
        )
    assert excinfo.value.code == ToolErrorCode.TOOL_INPUT_INVALID
    assert calls == []  # adapter never ran


async def test_scope_denied_before_adapter():
    calls: list[Any] = []

    async def adapter(invocation) -> ToolExecutionOutcome:
        calls.append(invocation)
        return ToolExecutionOutcome(summary="s", result=EchoOutput())

    registry = make_registry(adapter=adapter)
    context = make_context(source_scope_ids=("windows",))
    await registry.execute(context, "echo_tool", {"query": "x", "source_scope_id": "windows"})
    with pytest.raises(ToolExecutionError) as excinfo:
        await registry.execute(
            context, "echo_tool", {"query": "x", "source_scope_id": "android"}
        )
    assert excinfo.value.code == ToolErrorCode.TOOL_SCOPE_DENIED
    assert len(calls) == 1  # only the in-scope call reached the adapter


async def test_adapter_failure_normalized_without_path_leak():
    async def adapter(invocation):
        raise RuntimeError("db unlock failed at /srv/secret/path/investigation.db")

    registry = make_registry(adapter=adapter)
    with pytest.raises(ToolExecutionError) as excinfo:
        await registry.execute(make_context(), "echo_tool", {"query": "x"})
    assert excinfo.value.code == ToolErrorCode.TOOL_ADAPTER_FAILED
    assert "/srv/secret/path" not in str(excinfo.value)
    assert excinfo.value.details == {"exception_type": "RuntimeError"}


# ---------------------------------------------------------------------------
# evidence-ref validation (P3-E11)
# ---------------------------------------------------------------------------


async def test_invalid_evidence_ref_rejects_result_without_persistence():
    sink_calls: list[Any] = []

    class RecordingSink:
        def record(self, definition, record, evidence_refs, *, context):
            sink_calls.append(record)

    async def adapter(invocation) -> ToolExecutionOutcome:
        return ToolExecutionOutcome(
            summary="s",
            result=EchoOutput(),
            evidence_refs=("not-a-valid-ref",),
        )

    registry = make_registry(adapter=adapter, sink=RecordingSink())
    with pytest.raises(ToolExecutionError) as excinfo:
        await registry.execute(make_context(), "echo_tool", {"query": "x"})
    assert excinfo.value.code == ToolErrorCode.EVIDENCE_REF_INVALID
    assert sink_calls == []


async def test_cross_task_evidence_ref_rejects_result():
    async def adapter(invocation) -> ToolExecutionOutcome:
        return ToolExecutionOutcome(
            summary="s",
            result=EchoOutput(),
            evidence_refs=("file:C/other_task_file.txt",),
        )

    task_keys = {"file:C/ours.txt"}

    def validator(ref, context):
        if ref not in task_keys:
            raise ValueError("not in this task's key space")

    registry = make_registry(adapter=adapter, evidence_ref_validator=validator)
    with pytest.raises(ToolExecutionError) as excinfo:
        await registry.execute(make_context(), "echo_tool", {"query": "x"})
    assert excinfo.value.code == ToolErrorCode.EVIDENCE_REF_CROSS_TASK


# ---------------------------------------------------------------------------
# observation persistence + duplicate/budget guards (P3-E12)
# ---------------------------------------------------------------------------


async def test_observation_persisted_once_and_duplicate_guard(runtime):
    repo, investigation_id, run_id = runtime
    context = make_context(
        investigation_id=investigation_id,
        run_id=run_id,
        allowed_tool_ids=frozenset({"echo_tool"}),
        budget=ToolBudgetPolicy(max_duplicate_calls=1),
    )
    registry = make_registry(sink=AgentObservationSink(repo))
    result = await registry.execute(context, "echo_tool", {"query": "x"})
    assert result["observation"] == "recorded"
    observations = repo.list_tool_observations(investigation_id)
    assert len(observations) == 1
    assert observations[0].tool_id == "echo_tool"
    assert observations[0].evidence_refs == ("file:C/x.txt",)

    with pytest.raises(ToolExecutionError) as excinfo:
        await registry.execute(context, "echo_tool", {"query": "x"})
    assert excinfo.value.code == ToolErrorCode.TOOL_DUPLICATE_CALL
    assert len(repo.list_tool_observations(investigation_id)) == 1


async def test_observation_budget_exhaustion(runtime):
    repo, investigation_id, run_id = runtime
    context = make_context(
        investigation_id=investigation_id,
        run_id=run_id,
        allowed_tool_ids=frozenset({"echo_tool"}),
        budget=ToolBudgetPolicy(
            max_duplicate_calls=5, max_observations_per_run=1
        ),
    )
    registry = make_registry(sink=AgentObservationSink(repo))
    await registry.execute(context, "echo_tool", {"query": "one"})
    with pytest.raises(ToolExecutionError) as excinfo:
        await registry.execute(context, "echo_tool", {"query": "two"})
    assert excinfo.value.code == ToolErrorCode.TOOL_BUDGET_EXCEEDED


async def test_tool_call_writes_observation_and_trajectory_pair(runtime):
    """P3 freeze follow-up (F2): one successful call = one observation + one
    ``tool_observation_recorded`` trajectory event, payload pointing at the
    exact observation_id."""
    repo, investigation_id, run_id = runtime
    context = make_context(investigation_id=investigation_id, run_id=run_id)
    registry = make_registry(sink=AgentObservationSink(repo))
    await registry.execute(context, "echo_tool", {"query": "x"})

    observations = repo.list_tool_observations(investigation_id)
    assert len(observations) == 1
    events = [
        t for t in repo.list_trajectory(investigation_id)
        if t.event_type.value == "tool_observation_recorded"
    ]
    assert len(events) == 1
    payload = events[0].payload
    assert payload["observation_id"] == observations[0].observation_id
    assert payload["tool_id"] == "echo_tool"
    assert payload["tool_version"] == "1"
    assert payload["tool_schema_hash"]
    assert payload["evidence_ref_count"] == 1
    assert payload["result_count"] == 1
    assert payload["truncated"] is False
    # action trace, not a second observation store: no payload data copy
    assert "data" not in payload
    assert "summary" not in payload
    assert "evidence_refs" not in payload


async def test_idempotent_replay_deterministic_after_guard_reset(runtime):
    repo, investigation_id, run_id = runtime
    context = make_context(
        investigation_id=investigation_id,
        run_id=run_id,
        budget=ToolBudgetPolicy(max_duplicate_calls=1),
    )
    registry = make_registry(sink=AgentObservationSink(repo))
    await registry.execute(context, "echo_tool", {"query": "x"})
    with pytest.raises(ToolExecutionError):
        await registry.execute(context, "echo_tool", {"query": "x"})
    registry.reset_run_bookkeeping("task-A", investigation_id, run_id)
    result = await registry.execute(context, "echo_tool", {"query": "x"})
    assert result["observation"] == "recorded"
