"""P3 freeze follow-up F1: the registry pipeline order is directly pinned.

A spy subclass records every pipeline step invocation; a successful run must
show the exact frozen order, and each rejection must stop the pipeline
without consuming downstream state (no budget, no duplicate fingerprint,
no adapter call, no persistence).
"""

import pytest
from pydantic import BaseModel, ConfigDict

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
    NoopObservationSink,
)
from httpserver.services.investigation.agent_tools.registry import (
    ForensicToolRegistry,
    ToolExecutionOutcome,
)

EXPECTED_SUCCESS_ORDER = [
    "resolve",
    "permission",
    "scope",
    "input",
    "budget",
    "duplicate",
    "adapter",
    "normalize",
    "evidence_refs",
    "persist",
    "compact",
]


class EchoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    source_scope_id: str | None = None


class EchoOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_count: int = 1


def echo_definition(**overrides) -> ForensicToolDefinition:
    fields = dict(
        tool_id="echo_tool",
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


class SpyRegistry(ForensicToolRegistry):
    """Records each frozen pipeline step, then delegates to the real one."""

    def __init__(self, *args, adapter=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.order: list[str] = []
        self.adapter_calls = 0
        self._adapter = adapter

        async def default_adapter(invocation) -> ToolExecutionOutcome:
            return ToolExecutionOutcome(
                summary="echo",
                result=EchoOutput(),
                evidence_refs=("file:C/x.txt",),
            )

        self.register(echo_definition(), adapter or default_adapter)

    def _step_resolve(self, tool_id):
        self.order.append("resolve")
        return super()._step_resolve(tool_id)

    def _step_check_permission(self, definition, context, tool_id):
        self.order.append("permission")
        return super()._step_check_permission(definition, context, tool_id)

    def _step_check_scope(self, args, context):
        self.order.append("scope")
        return super()._step_check_scope(args, context)

    def _step_validate_input(self, definition, args):
        self.order.append("input")
        return super()._step_validate_input(definition, args)

    def _step_check_budget(self, run_key, context):
        self.order.append("budget")
        return super()._step_check_budget(run_key, context)

    def _step_check_duplicate(self, definition, validated, run_key, context):
        self.order.append("duplicate")
        return super()._step_check_duplicate(
            definition, validated, run_key, context
        )

    async def _step_run_adapter(self, definition, context, validated):
        self.order.append("adapter")
        self.adapter_calls += 1
        return await super()._step_run_adapter(definition, context, validated)

    def _step_normalize_output(self, definition, outcome):
        self.order.append("normalize")
        return super()._step_normalize_output(definition, outcome)

    def _step_validate_evidence_refs(self, outcome, context):
        self.order.append("evidence_refs")
        return super()._step_validate_evidence_refs(outcome, context)

    def _step_persist(self, definition, record, evidence_refs, context, run_key):
        self.order.append("persist")
        return super()._step_persist(
            definition, record, evidence_refs, context, run_key
        )

    def _step_compact_result(self, definition, outcome, record):
        self.order.append("compact")
        return super()._step_compact_result(definition, outcome, record)


def make_context(**overrides) -> ForensicToolContext:
    fields = dict(
        task_id="task-A",
        investigation_id="inv-A",
        run_id="run-A",
        source_scope_ids=("windows",),
        allowed_tool_ids=frozenset({"echo_tool"}),
    )
    fields.update(overrides)
    return ForensicToolContext(**fields)


async def test_successful_run_follows_frozen_pipeline_order():
    registry = SpyRegistry()
    result = await registry.execute(make_context(), "echo_tool", {"query": "x"})
    assert registry.order == EXPECTED_SUCCESS_ORDER
    assert result["observation"] == "recorded"


async def test_scope_denied_stops_before_input_validation_and_consumes_nothing():
    registry = SpyRegistry()
    with pytest.raises(ToolExecutionError) as excinfo:
        await registry.execute(
            make_context(),
            "echo_tool",
            {"query": "x", "source_scope_id": "android"},
        )
    assert excinfo.value.code == ToolErrorCode.TOOL_SCOPE_DENIED
    # frozen order: scope (3) validated before input (4) and budget (5)
    assert registry.order == ["resolve", "permission", "scope"]
    assert registry.adapter_calls == 0
    assert registry._run_observation_counts == {}
    assert registry._run_fingerprints == {}


async def test_schema_invalid_stops_after_input_step_and_consumes_nothing():
    registry = SpyRegistry()
    with pytest.raises(ToolExecutionError) as excinfo:
        await registry.execute(
            make_context(), "echo_tool", {"query": "x", "intruder": 1}
        )
    assert excinfo.value.code == ToolErrorCode.TOOL_INPUT_INVALID
    assert registry.order == ["resolve", "permission", "scope", "input"]
    assert registry.adapter_calls == 0
    assert registry._run_observation_counts == {}
    assert registry._run_fingerprints == {}


async def test_valid_scoped_request_then_budget_and_duplicate_apply():
    registry = SpyRegistry(
        adapter=None,
        observation_sink=NoopObservationSink(),
        duplicate_call_policy=lambda context: 1,
    )
    context = make_context()
    await registry.execute(
        context, "echo_tool", {"query": "x", "source_scope_id": "windows"}
    )
    # the in-scope request passed scope first, then budget/duplicate applied
    assert registry.order[:6] == [
        "resolve", "permission", "scope", "input", "budget", "duplicate",
    ]
    assert registry.adapter_calls == 1
    with pytest.raises(ToolExecutionError) as excinfo:
        await registry.execute(
            context, "echo_tool", {"query": "x", "source_scope_id": "windows"}
        )
    assert excinfo.value.code == ToolErrorCode.TOOL_DUPLICATE_CALL


async def test_unauthorized_tool_nothing_downstream_executes():
    registry = SpyRegistry()
    with pytest.raises(ToolExecutionError) as excinfo:
        await registry.execute(
            make_context(allowed_tool_ids=frozenset({"other"})),
            "echo_tool",
            {"query": "x"},
        )
    assert excinfo.value.code == ToolErrorCode.TOOL_NOT_ALLOWED
    assert registry.order == ["resolve", "permission"]
    assert registry.adapter_calls == 0
    assert registry._run_observation_counts == {}
    assert registry._run_fingerprints == {}
