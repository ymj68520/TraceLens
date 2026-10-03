"""PydanticAI thin model adapter (P3).

Translates the existing TraceLens LLM configuration (``httpserver.config.Settings``)
into a PydanticAI ``OpenAIChatModel``. The existing configuration remains the
single source of provider truth: no new env names, no second .env reader, no
secret copies.

TraceLens stores ``LLM_ENDPOINT`` as a *path* (``/v1/chat/completions``) that
is resolved against a per-purpose base_url (``LLM_TEXT_BASE_URL``). The OpenAI
SDK instead expects a base_url that already contains the version segment
(``.../v1``) and appends ``/chat/completions`` itself — ``derive_openai_base_url``
performs that translation deterministically.

Provider-compat quirks for the current DeepSeek-compatible endpoints are
centralized in the ``OpenAIModelProfile`` here (json_schema output is rejected
by the provider, strict tool definitions and max_completion_tokens are not
supported, one system message only). Tools/Skills/Specialists must never
carry their own provider workarounds.
"""

from typing import Any, Mapping, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.openai import OpenAIProvider

# Exact pin recorded in python_service/requirements.txt; the adapter test
# asserts the installed runtime matches so an accidental drift fails fast.
PYDANTIC_AI_PINNED_VERSION = "2.30.0"

_CHAT_COMPLETIONS_SUFFIX = "/chat/completions"

# Add-provider track: an alternative OpenAI-compatible provider selected via
# LLM_PROVIDER. OpenRouter needs no endpoint-path derivation (its base_url
# already carries the /v1 segment) and keeps its credential in a
# provider-scoped env var; everything else (profile, settings surface,
# tool-based structured output) is byte-identical to the legacy path.
OPENROUTER_PROVIDER = "openrouter"
OPENROUTER_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
GENERIC_PROVIDER = "generic"


def classify_provider_http_error(status_code: int | None, text: str = "") -> str:
    """Map a provider HTTP failure to the §18 wave taxonomy.

    Provider blocks are NEVER capability verdicts: none of these classes may
    be recorded as a Specialist/Supervisor schema failure or a semantic
    failure (frozen wave-2 invariant).
    """
    body = (text or "").lower()
    if status_code in (401, 403):
        return "PROVIDER_AUTH_BLOCKED"
    if status_code == 404:
        return "PROVIDER_MODEL_UNAVAILABLE"
    if status_code == 429 or "rate_limit" in body or "quota" in body:
        return "PROVIDER_QUOTA_BLOCKED"
    if status_code is not None and 500 <= status_code <= 599:
        return "PROVIDER_INFRA_FAILURE"
    lowered = f"{status_code or ''} {body}"
    if "timeout" in lowered or "timed out" in lowered:
        return "PROVIDER_TIMEOUT"
    return "PROVIDER_INFRA_FAILURE"


class ModelAdapterError(Exception):
    """Raised when the TraceLens LLM configuration cannot drive PydanticAI."""


def derive_openai_base_url(base_url: str, endpoint_path: str) -> str:
    """Translate TraceLens base_url + endpoint path into OpenAI SDK base_url.

    ``("https://api.deepseek.com", "/v1/chat/completions") -> "https://api.deepseek.com/v1"``
    """
    if not base_url or not base_url.strip():
        raise ModelAdapterError("LLM base_url is empty")
    endpoint = (endpoint_path or "").strip()
    base = base_url.strip().rstrip("/")
    if endpoint.startswith(("http://", "https://")):
        combined = endpoint.rstrip("/")
    elif endpoint.startswith("/"):
        combined = base + endpoint
    else:
        raise ModelAdapterError(
            "LLM_ENDPOINT must be an absolute /path or full URL ending in "
            f"{_CHAT_COMPLETIONS_SUFFIX!r}; got {endpoint!r}"
        )
    if not combined.endswith(_CHAT_COMPLETIONS_SUFFIX):
        raise ModelAdapterError(
            "LLM endpoint must end with "
            f"{_CHAT_COMPLETIONS_SUFFIX!r}; got {endpoint!r}"
        )
    return combined[: -len(_CHAT_COMPLETIONS_SUFFIX)]


class ModelAdapterConfig(BaseModel):
    """Normalized adapter inputs. Never stores the API key."""

    model_config = ConfigDict(frozen=True)

    provider: str = GENERIC_PROVIDER
    base_url: str
    model_name: str
    reasoning_effort: Optional[str] = None
    timeout_seconds: Optional[float] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None

    @field_validator("base_url")
    @classmethod
    def _check_base_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ModelAdapterError(f"LLM base_url must be http(s), got {value!r}")
        return value

    @field_validator("model_name")
    @classmethod
    def _check_model_name(cls, value: str) -> str:
        if not value.strip():
            raise ModelAdapterError("LLM model name is empty")
        return value


def resolve_adapter_config(settings: Any) -> ModelAdapterConfig:
    """Project TraceLens ``Settings`` onto adapter inputs (single config source)."""
    provider = (
        getattr(settings, "llm_provider", "") or GENERIC_PROVIDER
    ).strip().lower() or GENERIC_PROVIDER
    model_name = getattr(settings, "llm_text_model", None)
    # LLM_THINKING_MODE is a DeepSeek-shaped top-level ``thinking`` body
    # field. The PydanticAI chat path has no such field; the OpenAI-standard
    # equivalent is ``openai_reasoning_effort``. ``disabled`` maps to "none"
    # (reasoning off, temperature honored); ``enabled`` is not representable
    # on the chat path, so it degrades to no explicit effort (provider
    # default) and raises nothing.
    thinking_mode = (getattr(settings, "llm_thinking_mode", "") or "").strip().lower()
    reasoning_effort: Optional[str] = "none" if thinking_mode == "disabled" else None
    if provider == OPENROUTER_PROVIDER:
        # OpenRouter contract: base_url already contains the /v1 segment; the
        # legacy LLM_ENDPOINT path derivation does not apply.
        base_url = (
            getattr(settings, "openrouter_base_url", "")
            or OPENROUTER_DEFAULT_BASE_URL
        ).strip().rstrip("/")
    else:
        base_url = derive_openai_base_url(
            getattr(settings, "llm_text_base_url", "") or "",
            getattr(settings, "llm_endpoint", "") or "",
        )
    return ModelAdapterConfig(
        provider=provider,
        base_url=base_url,
        model_name=model_name,  # type: ignore[arg-type]
        reasoning_effort=reasoning_effort,
        timeout_seconds=getattr(settings, "llm_timeout_seconds", None),
        temperature=getattr(settings, "llm_text_temperature", None),
        max_tokens=getattr(settings, "llm_text_max_tokens", None),
    )


def build_chat_model(settings: Any, *, model_name: Optional[str] = None) -> OpenAIChatModel:
    """Build a PydanticAI ``OpenAIChatModel`` from TraceLens configuration.

    Performs no network I/O. Raises ``ModelAdapterError`` (fail-closed) when
    the configuration cannot drive an OpenAI-compatible endpoint.
    """
    config = resolve_adapter_config(settings)
    if model_name is not None:
        config = config.model_copy(update={"model_name": model_name})

    # Provider quirks centralized here (P3 contract): DeepSeek-compatible
    # endpoints 400 on json_schema structured output, do not support strict
    # tool definitions or max_completion_tokens, and accept one system message.
    profile: Mapping[str, Any] = OpenAIModelProfile(
        supports_json_schema_output=False,
        supports_json_object_output=True,
        openai_supports_strict_tool_definition=False,
        openai_chat_supports_max_completion_tokens=False,
        openai_chat_supports_multiple_system_messages=False,
    )

    model_settings = OpenAIChatModelSettings(timeout=config.timeout_seconds)
    if config.temperature is not None:
        model_settings["temperature"] = config.temperature
    if config.max_tokens is not None:
        model_settings["max_tokens"] = config.max_tokens
    if config.reasoning_effort is not None:
        # DeepSeek-style LLM_THINKING_MODE=disabled maps to the OpenAI-standard
        # reasoning_effort ("none"): reasoning off, temperature honored.
        model_settings["openai_reasoning_effort"] = config.reasoning_effort

    if config.provider == OPENROUTER_PROVIDER:
        # Provider-scoped credential: OPENROUTER_API_KEY only; the legacy
        # LLM_API_KEY is never consulted on this path (and vice versa). The
        # optional attribution headers ride the per-request extra_headers
        # extension point — no client construction surgery.
        api_key = getattr(settings, "openrouter_api_key", "") or "EMPTY"
        extra_headers = {
            name: value
            for name, value in (
                ("HTTP-Referer", getattr(settings, "openrouter_http_referer", "")),
                ("X-Title", getattr(settings, "openrouter_x_title", "")),
            )
            if value
        }
        if extra_headers:
            model_settings["extra_headers"] = extra_headers
    else:
        # Mirror llm_service semantics: only send auth when a key exists. The
        # OpenAI SDK requires a non-empty string, so local no-key deployments
        # get the conventional "EMPTY" sentinel (never the real key's absence
        # leak).
        api_key = getattr(settings, "llm_api_key", "") or "EMPTY"

    # Opt-in per-request routing-identity telemetry (§1 of the screening
    # gate): when the caller supplies a list-like sink, every chat
    # completion response's model identity is appended to it. Inert by
    # default (None) — production behavior is byte-identical without it,
    # and the wrapper never alters the response.
    identity_sink = getattr(settings, "llm_model_identity_sink", None)
    if identity_sink is not None:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(base_url=config.base_url, api_key=api_key)
        upstream_create = client.chat.completions.create
        requested_model = config.model_name

        async def _identity_recording_create(**kwargs):
            response = await upstream_create(**kwargs)
            try:
                identity_sink.append({
                    "requested_model": requested_model,
                    "returned_model": getattr(response, "model", None),
                    "upstream_provider": (getattr(response, "model_extra", None) or {}).get("provider"),
                })
            except Exception:  # telemetry is never request-fatal
                pass
            return response

        client.chat.completions.create = _identity_recording_create
        provider = OpenAIProvider(openai_client=client)
    else:
        provider = OpenAIProvider(base_url=config.base_url, api_key=api_key)
    return OpenAIChatModel(
        config.model_name,
        provider=provider,
        profile=profile,
        settings=model_settings,
    )


__all__ = [
    "GENERIC_PROVIDER",
    "ModelAdapterConfig",
    "ModelAdapterError",
    "OPENROUTER_DEFAULT_BASE_URL",
    "OPENROUTER_PROVIDER",
    "PYDANTIC_AI_PINNED_VERSION",
    "build_chat_model",
    "classify_provider_http_error",
    "derive_openai_base_url",
    "resolve_adapter_config",
]
