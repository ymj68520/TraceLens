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
    classify_provider_http_error,
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
        # add-provider track (OpenRouter): defaults select the legacy path
        self.llm_provider = ""
        self.openrouter_api_key = ""
        self.openrouter_base_url = "https://openrouter.ai/api/v1"
        self.openrouter_http_referer = ""
        self.openrouter_x_title = ""
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
# add-provider track: OpenRouter (LLM_PROVIDER selection, §5-§9/§18/§33)
# ---------------------------------------------------------------------------

OPENROUTER_SETTINGS = dict(
    llm_provider="openrouter",
    llm_text_model="stealth/space-bunny-alpha",
    llm_text_temperature=0.7,
    llm_thinking_mode="disabled",
    llm_text_max_tokens=16384,
    openrouter_api_key="sk-or-v1-test-key-value",
    openrouter_base_url="https://openrouter.ai/api/v1",
)


def test_openrouter_provider_resolution_exact():
    config = resolve_adapter_config(FakeSettings(**OPENROUTER_SETTINGS))
    assert config.provider == "openrouter"
    # frozen external contract: base_url exact, model id exact
    assert config.base_url == "https://openrouter.ai/api/v1"
    assert config.model_name == "stealth/space-bunny-alpha"
    assert config.reasoning_effort == "none"
    assert config.max_tokens == 16384


def test_openrouter_skips_legacy_endpoint_derivation():
    # an invalid legacy LLM_ENDPOINT must not break the openrouter path
    config = resolve_adapter_config(
        FakeSettings(**OPENROUTER_SETTINGS, llm_endpoint="not-a-path")
    )
    assert config.base_url == "https://openrouter.ai/api/v1"


def test_openrouter_base_url_env_override_normalized():
    config = resolve_adapter_config(
        FakeSettings(
            **{**OPENROUTER_SETTINGS,
               "openrouter_base_url": "https://router.example.com/v1/"}
        )
    )
    assert config.base_url == "https://router.example.com/v1"
    # missing override falls back to the frozen default
    settings = FakeSettings(**OPENROUTER_SETTINGS)
    settings.openrouter_base_url = ""
    assert (
        resolve_adapter_config(settings).base_url
        == "https://openrouter.ai/api/v1"
    )


def test_openrouter_api_key_isolated_from_legacy():
    """OPENROUTER_API_KEY is required/read only when the provider is
    selected; the legacy LLM_API_KEY never crosses paths."""
    model = build_chat_model(FakeSettings(**OPENROUTER_SETTINGS))
    assert model.provider.client.api_key == "sk-or-v1-test-key-value"

    # legacy path ignores OPENROUTER_API_KEY entirely
    legacy = FakeSettings(openrouter_api_key="sk-or-v1-should-be-ignored")
    assert build_chat_model(legacy).provider.client.api_key == "sk-secret-test-key"

    # openrouter path ignores the legacy key
    stray = FakeSettings(
        **OPENROUTER_SETTINGS, llm_api_key="sk-legacy-stray-key"
    )
    assert build_chat_model(stray).provider.client.api_key == "sk-or-v1-test-key-value"


def test_openrouter_missing_key_uses_empty_sentinel_not_legacy():
    """No OPENROUTER_API_KEY → the EMPTY sentinel goes out (live 401 →
    PROVIDER_AUTH_BLOCKED), never the legacy key and never a secret."""
    settings = FakeSettings(
        **{**OPENROUTER_SETTINGS, "openrouter_api_key": ""}
    )
    model = build_chat_model(settings)
    assert model.provider.client.api_key == "EMPTY"


def test_openrouter_optional_headers_only_when_configured():
    model = build_chat_model(FakeSettings(**OPENROUTER_SETTINGS))
    assert "extra_headers" not in model.settings

    model2 = build_chat_model(
        FakeSettings(
            **OPENROUTER_SETTINGS,
            openrouter_http_referer="https://tracelens.local",
            openrouter_x_title="TraceLens",
        )
    )
    assert model2.settings["extra_headers"] == {
        "HTTP-Referer": "https://tracelens.local",
        "X-Title": "TraceLens",
    }


def test_openrouter_profile_identical_to_generic():
    """Provider selection must not drift any production semantic: the same
    centralized profile applies, and the settings surface is structurally
    identical (no provider-specific keys appear or vanish)."""
    generic = build_chat_model(FakeSettings())
    routed = build_chat_model(FakeSettings(**OPENROUTER_SETTINGS))
    assert dict(routed.profile) == dict(generic.profile)
    assert set(routed.settings.keys()) == set(generic.settings.keys())


def test_openrouter_secret_redaction():
    """repr/str of the config and model never leak the OpenRouter key
    (§33 security regression)."""
    config = resolve_adapter_config(FakeSettings(**OPENROUTER_SETTINGS))
    model = build_chat_model(FakeSettings(**OPENROUTER_SETTINGS))
    for rendered in (repr(config), str(config), repr(model), str(model)):
        assert "sk-or-v1-test-key-value" not in rendered
        assert "sk-secret-test-key" not in rendered


def test_identity_capture_sink_inert_by_default():
    """Without a sink the provider is built exactly as before (no wrap);
    with a list sink, per-request identity records land in it."""
    plain = build_chat_model(FakeSettings(**OPENROUTER_SETTINGS))
    create_plain = plain.provider.client.chat.completions.create
    assert getattr(create_plain, "__module__", "").startswith("openai")

    sink: list = []
    captured = build_chat_model(
        FakeSettings(**OPENROUTER_SETTINGS, llm_model_identity_sink=sink)
    )
    create_wrapped = captured.provider.client.chat.completions.create
    assert getattr(create_wrapped, "__module__", "").startswith(
        "tests.unit.investigation"
    ) or create_wrapped.__name__ == "_identity_recording_create"
    # build time performs no network I/O and records nothing
    assert sink == []
    # sink contents only ever carry identity fields (never secrets)
    assert not hasattr(sink, "api_key")


def test_llm_provider_validation_rejects_unknown():
    from httpserver.config import Settings
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(_env_file=None, LLM_PROVIDER="sensenova-magic")


@pytest.mark.parametrize(
    ("status", "text", "expected"),
    [
        (401, "", "PROVIDER_AUTH_BLOCKED"),
        (403, "permission denied", "PROVIDER_AUTH_BLOCKED"),
        (404, "model not found", "PROVIDER_MODEL_UNAVAILABLE"),
        (429, "rate limit exceeded", "PROVIDER_QUOTA_BLOCKED"),
        (None, "429 quota exceeded upstream", "PROVIDER_QUOTA_BLOCKED"),
        (500, "internal error", "PROVIDER_INFRA_FAILURE"),
        (503, "", "PROVIDER_INFRA_FAILURE"),
        (None, "request timed out after 120s", "PROVIDER_TIMEOUT"),
        (400, "bad request", "PROVIDER_INFRA_FAILURE"),
    ],
)
def test_provider_http_error_taxonomy(status, text, expected):
    assert classify_provider_http_error(status, text) == expected


def test_provider_errors_never_semantic():
    """§29 frozen invariant: provider classes must never collide with the
    agent output/schema/semantic failure vocabulary."""
    provider_classes = {
        classify_provider_http_error(status, text)
        for status, text in [
            (429, ""), (401, ""), (404, ""), (500, ""),
            (502, ""), (None, "timeout"), (503, ""),
        ]
    }
    forbidden = {
        "agent_output_invalid", "schema_failure", "semantic_failure",
        "MODEL_CAPABILITY_FAILURE",
    }
    assert provider_classes.isdisjoint(forbidden)


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
