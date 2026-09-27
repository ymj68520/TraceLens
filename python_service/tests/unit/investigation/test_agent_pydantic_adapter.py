"""P3-1 offline tests: PydanticAI dependency pin, model adapter, deps, toolset bridge.

Everything runs offline through pydantic_ai TestModel / FunctionModel —
no network, no API key, no real provider.
"""

import json
from typing import Any, Iterable, Mapping

import pytest
from pydantic import BaseModel, ConfigDict

from httpserver.services.investigation.agent_deps import ForensicAgentDeps
from httpserver.services.investigation.agent_model_adapter import (
    PYDANTIC_AI_PINNED_VERSION,
    ModelAdapterError,
    build_chat_model,
    derive_openai_base_url,
    resolve_adapter_config,
)
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
    validate_model_visible_schema,
)
from httpserver.services.investigation.agent_tools.pydantic_bridge import (
    build_pydantic_toolset,
)

try:
    import pydantic_ai
    from pydantic_ai import Agent
    from pydantic_ai.messages import (
        ModelMessage,
        ModelRequest,
        ModelResponse,
        RetryPromptPart,
        TextPart,
        ToolCallPart,
        ToolReturnPart,
    )
    from pydantic_ai.models.function import FunctionModel
    from pydantic_ai.models.test import TestModel

    PYDANTIC_AI_AVAILABLE = True
except ImportError:  # pragma: no cover
    PYDANTIC_AI_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not PYDANTIC_AI_AVAILABLE, reason="pydantic-ai-slim not installed"
)


# ---------------------------------------------------------------------------
# fixtures / fakes
# ---------------------------------------------------------------------------


class FakeSettings:
    """Shape-compatible stand-in for httpserver.config.Settings LLM fields."""

    def __init__(self, **overrides):
        self.llm_text_base_url = "https://api.deepseek.com"
        self.llm_endpoint = "/v1/chat/completions"
        self.llm_api_key = "sk-secret-test-key"
        self.llm_text_model = "deepseek-flash"
        self.llm_thinking_mode = "disabled"
        self.llm_timeout_seconds = 30.0
        self.llm_text_temperature = 0.2
        self.llm_text_max_tokens = 4096
        for key, value in overrides.items():
            setattr(self, key, value)


class ProbeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str


class ProbeOutput(BaseModel):
    summary: str


def _probe_definition(tool_id: str = "probe_tool") -> ForensicToolDefinition:
    return ForensicToolDefinition(
        tool_id=tool_id,
        version="1",
        title="Probe tool",
        description="offline probe tool",
        input_model=ProbeInput,
        output_model=ProbeOutput,
        category=ToolCategory.EVIDENCE,
        access=ToolAccess.READ,
        scope_kind=ToolScopeKind.EVIDENCE,
        evidence_behavior=EvidenceBehavior.EVIDENCE_PRODUCING,
        cost_class=ToolCostClass.CHEAP,
        pagination_kind=ToolPaginationKind.NONE,
    )


class FakeRegistry:
    """Registry stand-in implementing the bridge protocol."""

    def __init__(self, definitions: Iterable[ForensicToolDefinition]):
        self._definitions = {d.tool_id: d for d in definitions}
        self.calls: list[tuple[str, Mapping[str, Any]]] = []

    def iter_definitions(self):
        return list(self._definitions.values())

    def resolve_definition(self, tool_id: str) -> ForensicToolDefinition:
        return self._definitions[tool_id]

    async def execute(self, context, tool_id: str, args: Mapping[str, Any]):
        self.calls.append((tool_id, dict(args)))
        return {"summary": f"executed {tool_id}", "query": args.get("query")}


def _make_context(allowed: Iterable[str]) -> ForensicToolContext:
    return ForensicToolContext(
        task_id="task-1",
        investigation_id="inv-1",
        run_id="run-1",
        allowed_tool_ids=frozenset(allowed),
    )


class _RunCtxStub:
    max_retries = 1


def _ctx_stub() -> Any:
    return _RunCtxStub()


def _make_deps(registry: FakeRegistry, context: ForensicToolContext) -> ForensicAgentDeps:
    return ForensicAgentDeps(
        task_id=context.task_id,
        investigation_id=context.investigation_id,
        run_id=context.run_id,
        allowed_tool_ids=frozenset(tool_id for tool_id in context.allowed_tool_ids),
        tool_registry=registry,
        tool_context=context,
    )


# ---------------------------------------------------------------------------
# dependency pin (P3-E2)
# ---------------------------------------------------------------------------


def test_installed_pydantic_ai_matches_pin():
    assert pydantic_ai.__version__ == PYDANTIC_AI_PINNED_VERSION


# ---------------------------------------------------------------------------
# model adapter (P3-E3, §51)
# ---------------------------------------------------------------------------


def test_existing_config_converted_correctly():
    config = resolve_adapter_config(FakeSettings())
    assert config.model_name == "deepseek-flash"
    assert config.base_url == "https://api.deepseek.com/v1"
    assert config.reasoning_effort == "none"
    assert config.max_tokens == 4096


def test_custom_openai_compatible_base_url_preserved():
    config = resolve_adapter_config(
        FakeSettings(llm_text_base_url="http://192.168.31.170:1234")
    )
    assert config.base_url == "http://192.168.31.170:1234/v1"


def test_derive_openai_base_url_variants():
    assert (
        derive_openai_base_url("https://api.example.com", "/v1/chat/completions")
        == "https://api.example.com/v1"
    )
    assert (
        derive_openai_base_url(
            "https://api.example.com", "https://proxy.example.com/v1/chat/completions"
        )
        == "https://proxy.example.com/v1"
    )
    assert derive_openai_base_url("http://host:1", "/chat/completions") == "http://host:1"


def test_invalid_config_fails_closed():
    with pytest.raises(ModelAdapterError):
        resolve_adapter_config(FakeSettings(llm_text_base_url=""))
    with pytest.raises(ModelAdapterError):
        resolve_adapter_config(FakeSettings(llm_text_model="  "))
    with pytest.raises(ModelAdapterError):
        resolve_adapter_config(FakeSettings(llm_endpoint="deepseek-flash"))
    with pytest.raises(ModelAdapterError):
        resolve_adapter_config(FakeSettings(llm_endpoint="/v1/responses"))
    with pytest.raises(ModelAdapterError):
        resolve_adapter_config(FakeSettings(llm_text_base_url="ftp://x"))
    # fail closed at model construction too
    with pytest.raises(ModelAdapterError):
        build_chat_model(FakeSettings(llm_endpoint="/nope"))


def test_secret_not_in_repr():
    settings = FakeSettings()
    config = resolve_adapter_config(settings)
    assert "sk-secret-test-key" not in repr(config)
    model = build_chat_model(settings)
    assert "sk-secret-test-key" not in repr(model)
    assert "sk-secret-test-key" not in str(model)


def test_provider_profile_options_centralized():
    model = build_chat_model(FakeSettings())
    profile = model.profile
    assert profile["supports_json_schema_output"] is False
    assert profile["supports_json_object_output"] is True
    assert profile["openai_supports_strict_tool_definition"] is False
    assert profile["openai_chat_supports_max_completion_tokens"] is False
    assert profile["openai_chat_supports_multiple_system_messages"] is False


def test_thinking_disabled_maps_to_reasoning_effort_none():
    """LLM_THINKING_MODE=disabled rides the OpenAI-standard
    ``openai_reasoning_effort`` setting, never a ``thinking`` body field —
    providers that reject ``thinking`` (e.g. MiMo chat completions) 400 on it."""
    model = build_chat_model(FakeSettings())
    assert model.settings.get("openai_reasoning_effort") == "none"
    assert "extra_body" not in model.settings
    # empty mode sends no effort at all (provider default reasoning)
    model_default = build_chat_model(FakeSettings(llm_thinking_mode=""))
    assert "openai_reasoning_effort" not in model_default.settings


def test_adapter_creation_does_not_start_request():
    # constructing twice offline must be side-effect free
    build_chat_model(FakeSettings())
    build_chat_model(FakeSettings(llm_text_model="other-model"))


# ---------------------------------------------------------------------------
# ForensicAgentDeps (P3-E5 foundation)
# ---------------------------------------------------------------------------


def test_deps_context_consistency_enforced():
    context = _make_context(["probe_tool"])
    registry = FakeRegistry([_probe_definition()])
    deps = _make_deps(registry, context)
    assert deps.allowed_tool_ids == context.allowed_tool_ids
    with pytest.raises(ValueError):
        ForensicAgentDeps(
            task_id="task-OTHER",
            investigation_id=context.investigation_id,
            run_id=context.run_id,
            allowed_tool_ids=frozenset({"probe_tool"}),
            tool_registry=registry,
            tool_context=context,
        )
    # deps tool surface may not exceed the trusted context surface
    with pytest.raises(ValueError):
        ForensicAgentDeps(
            task_id=context.task_id,
            investigation_id=context.investigation_id,
            run_id=context.run_id,
            allowed_tool_ids=frozenset({"probe_tool", "not_in_context"}),
            tool_registry=registry,
            tool_context=context,
        )


def test_tool_context_budget_defaults_configurable():
    context = _make_context(["probe_tool"])
    assert context.budget == ToolBudgetPolicy()
    custom = ForensicToolContext(
        task_id="t", investigation_id="i", run_id="r",
        allowed_tool_ids=frozenset({"x"}),
        budget=ToolBudgetPolicy(max_duplicate_calls=5),
    )
    assert custom.budget.max_duplicate_calls == 5


# ---------------------------------------------------------------------------
# toolset bridge (P3-E5, P3-E6 foundation)
# ---------------------------------------------------------------------------


def test_schema_audit_blocks_identity_fields():
    class EvilInput(BaseModel):
        model_config = ConfigDict(extra="forbid")
        task_id: str

    definition = _probe_definition().model_copy(
        update={"input_model": EvilInput}, deep=False
    )
    with pytest.raises(ValueError, match="task_id"):
        validate_model_visible_schema(definition)
    # clean definition passes
    validate_model_visible_schema(_probe_definition())


async def test_tool_roundtrip_through_registry_with_injected_identity():
    registry = FakeRegistry([_probe_definition("search_evidence")])
    context = _make_context(["search_evidence"])
    deps = _make_deps(registry, context)
    toolset = build_pydantic_toolset(registry, context)

    async def drive_model(messages: list[ModelMessage], info) -> ModelResponse:
        last = messages[-1]
        if any(isinstance(p, ToolReturnPart) for p in getattr(last, "parts", [])):
            for part in last.parts:
                if isinstance(part, ToolReturnPart):
                    return ModelResponse(
                        parts=[TextPart(content=json.dumps(part.content))]
                    )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="search_evidence",
                    args={"query": "harbor"},
                )
            ]
        )

    agent = Agent(
        FunctionModel(drive_model),
        deps_type=ForensicAgentDeps,
        toolsets=[toolset],
    )
    result = await agent.run("find evidence", deps=deps)
    # the registry received the trusted context, not model-controlled identity
    assert registry.calls == [("search_evidence", {"query": "harbor"})]
    assert "executed search_evidence" in result.output


async def test_toolset_exposes_only_allowed_tool_ids():
    registry = FakeRegistry(
        [_probe_definition("tool_allowed"), _probe_definition("tool_hidden")]
    )
    context = _make_context(["tool_allowed"])
    deps = _make_deps(registry, context)
    toolset = build_pydantic_toolset(registry, context)

    captured: dict[str, Any] = {}

    def drive_model(messages: list[ModelMessage], info) -> ModelResponse:
        captured["tool_names"] = sorted(t.name for t in info.function_tools)
        return ModelResponse(parts=[TextPart(content="done")])

    agent = Agent(
        FunctionModel(drive_model),
        deps_type=ForensicAgentDeps,
        toolsets=[toolset],
    )
    await agent.run("list tools", deps=deps)
    assert captured["tool_names"] == ["tool_allowed"]


async def test_model_cannot_pass_identity_in_tool_args():
    """extra='forbid' input models reject model-injected identity fields."""
    registry = FakeRegistry([_probe_definition("search_evidence")])
    context = _make_context(["search_evidence"])
    deps = _make_deps(registry, context)
    toolset = build_pydantic_toolset(registry, context)

    state = {"phase": 0}

    async def drive_model(messages: list[ModelMessage], info) -> ModelResponse:
        state["phase"] += 1
        if state["phase"] == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="search_evidence",
                        args={"query": "x", "task_id": "evil-task"},
                    )
                ]
            )
        retry_parts = [
            p
            for m in messages
            for p in getattr(m, "parts", [])
            if isinstance(p, RetryPromptPart)
        ]
        assert retry_parts, "expected a retry prompt after schema rejection"
        return ModelResponse(parts=[TextPart(content="gave up")])

    agent = Agent(
        FunctionModel(drive_model),
        deps_type=ForensicAgentDeps,
        toolsets=[toolset],
    )
    await agent.run("try evil args", deps=deps)
    # the registry adapter must never have executed with identity args
    assert registry.calls == []


async def test_model_visible_schema_has_no_identity_fields():
    registry = FakeRegistry([_probe_definition("search_evidence")])
    toolset = build_pydantic_toolset(registry, _make_context(["search_evidence"]))
    tools = await toolset.get_tools(_ctx_stub())
    schema = tools["search_evidence"].tool_def.parameters_json_schema
    for forbidden in ("task_id", "investigation_id", "run_id", "db_path", "sql"):
        assert forbidden not in schema.get("properties", {})


async def test_unknown_tool_absent_even_if_allowed():
    registry = FakeRegistry([_probe_definition("real_tool")])
    context = _make_context(["real_tool", "ghost_tool"])
    toolset = build_pydantic_toolset(registry, context)
    tools = await toolset.get_tools(_ctx_stub())
    assert sorted(tools) == ["real_tool"]


# ---------------------------------------------------------------------------
# structured output + offline test models (§10, §11)
# ---------------------------------------------------------------------------


class AdapterProbeResult(BaseModel):
    """Test-only probe contract (P3 §10) — never a P4 domain type."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    note: str


async def test_structured_output_validation_offline():
    agent = Agent(
        TestModel(call_tools=[]),
        deps_type=ForensicAgentDeps,
        output_type=AdapterProbeResult,
    )
    registry = FakeRegistry([_probe_definition()])
    deps = _make_deps(registry, _make_context(["probe_tool"]))
    result = await agent.run("probe", deps=deps)
    assert isinstance(result.output, AdapterProbeResult)


async def test_testmodel_calls_tools_through_bridge():
    registry = FakeRegistry([_probe_definition("probe_tool")])
    deps = _make_deps(registry, _make_context(["probe_tool"]))
    agent = Agent(
        TestModel(call_tools="all", custom_output_text="done"),
        deps_type=ForensicAgentDeps,
        toolsets=[build_pydantic_toolset(registry, deps.tool_context)],
    )
    await agent.run("call tools", deps=deps)
    assert len(registry.calls) == 1
    assert registry.calls[0][0] == "probe_tool"
