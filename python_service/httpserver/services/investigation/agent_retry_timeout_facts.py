"""Effective retry/timeout observability facts (RCA-1.4) — RECORD ONLY.

No budget is changed by this module (audit directive RCA-1.4): it states
what IS in effect so operators stop guessing. Values are derived from the
audited code paths, not from configuration intent:

    SDK_MAX_RETRIES        openai SDK DEFAULT_MAX_RETRIES = 2 (openai/
                           _constants.py) — every logical model request
                           makes up to THREE HTTP attempts on retryable
                           transport errors (timeouts included). The agent
                           path never overrides it (OpenAIProvider is
                           constructed without max_retries).
    HTTP_ATTEMPT_TIMEOUT   LLM_TIMEOUT_SECONDS (default 120) applies PER
                           HTTP ATTEMPT via pydantic-ai model_settings
                           ['timeout'] (pydantic_ai/models/openai.py).
    AGENT_OUTPUT_RETRIES   pydantic-ai agent-level structured-output retry
                           budget: supervisor agents are built WITHOUT a
                           retries argument -> pydantic-ai default 1;
                           specialists get AgentRunPolicy.
                           max_output_retries (default 2).
    RUN_TIMEOUT            the production benchmark executor arms
                           asyncio.wait_for with
                           generation_params['timeout_seconds'] — a key
                           the frozen model identity does not carry, so
                           the run-level timeout is DISABLED in practice.

Layer vocabulary (one logical request != one HTTP attempt):
    one HTTP attempt          one chat/completions POST (<= HTTP_ATTEMPT_
                              TIMEOUT each)
    one SDK logical request   up to SDK_MAX_RETRIES+1 HTTP attempts
    one PydanticAI output     one extra SDK logical request carrying the
           retry              validation-error retry prompt
    one AgentRun              bounded cycle loop; many logical requests

Known dead configuration (documented, semantics NOT changed by RCA-1):
    LLM_MAX_RETRIES (httpserver/config.py llm_max_retries, default 3) has
    NO consumer on the agent path (audit F-5) — it belongs to the legacy
    non-agent llm_service path compatibility surface and is intentionally
    left untouched.
"""

from __future__ import annotations

from typing import Any

# openai.DEFAULT_MAX_RETRIES, mirrored to avoid importing the SDK here
SDK_MAX_RETRIES = 2


def effective_retry_timeout_facts(
    settings: Any = None,
    specialist_output_retries: int | None = None,
) -> dict:
    """Snapshot the effective retry/timeout budgets. Purely informational;
    raised nowhere, enforced nowhere."""
    timeout_s = getattr(settings, "llm_timeout_seconds", None)
    facts = {
        "artifact_version": "AgentRetryTimeoutFactsV1",
        "sdk_max_retries": SDK_MAX_RETRIES,
        "http_attempts_per_logical_request_max": SDK_MAX_RETRIES + 1,
        "http_attempt_timeout_seconds": timeout_s,
        "agent_output_retries": {
            "supervisor_plan": 1,
            "supervisor_integrate": 1,
            "specialist": (
                specialist_output_retries
                if specialist_output_retries is not None
                else 2
            ),
            "note": (
                "supervisor agents are constructed without a retries "
                "argument (pydantic-ai default 1); specialists receive "
                "AgentRunPolicy.max_output_retries"
            ),
        },
        "run_timeout": "disabled (generation_params carries no "
                       "timeout_seconds key; production_executor wait_for "
                       "is unbounded)",
        "dead_configuration": {
            "llm_max_retries": (
                "defined (config.py) with no consumer on the agent path; "
                "documented only, semantics unchanged (RCA-1.4)"
            ),
        },
    }
    return facts


__all__ = ["SDK_MAX_RETRIES", "effective_retry_timeout_facts"]
