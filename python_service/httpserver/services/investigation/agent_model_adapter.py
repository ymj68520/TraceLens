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

    base_url: str
    model_name: str
    thinking_extra_body: Mapping[str, Any] = {}
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
    base_url = getattr(settings, "llm_text_base_url", None)
    endpoint = getattr(settings, "llm_endpoint", None)
    model_name = getattr(settings, "llm_text_model", None)
    return ModelAdapterConfig(
        base_url=derive_openai_base_url(base_url or "", endpoint or ""),
        model_name=model_name,  # type: ignore[arg-type]
        thinking_extra_body=dict(getattr(settings, "llm_thinking_body", {}) or {}),
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
    if config.thinking_extra_body:
        # DeepSeek thinking quirk (LLM_THINKING_MODE) rides as top-level body
        # field via extra_body, matching llm_service.py's `**llm_thinking_body`.
        model_settings["extra_body"] = dict(config.thinking_extra_body)

    # Mirror llm_service semantics: only send auth when a key exists. The
    # OpenAI SDK requires a non-empty string, so local no-key deployments get
    # the conventional "EMPTY" sentinel (never the real key's absence leak).
    api_key = getattr(settings, "llm_api_key", "") or "EMPTY"
    provider = OpenAIProvider(base_url=config.base_url, api_key=api_key)
    return OpenAIChatModel(
        config.model_name,
        provider=provider,
        profile=profile,
        settings=model_settings,
    )


__all__ = [
    "ModelAdapterConfig",
    "ModelAdapterError",
    "PYDANTIC_AI_PINNED_VERSION",
    "build_chat_model",
    "derive_openai_base_url",
    "resolve_adapter_config",
]
