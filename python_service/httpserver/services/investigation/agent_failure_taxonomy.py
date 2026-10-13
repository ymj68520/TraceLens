"""Canonical failure taxonomy for the agent runtime (RCA-1.2).

One type-driven classifier for model/provider failures, shared by the
supervisor containment path (RCA-1.1), the specialist delegation path and
the benchmark runner (RCA-1.5 consumers). Classification uses exception
TYPES and SDK error fields first — exception strings are never the primary
signal (audit finding F-3/F-4: string-only matching misclassified transport
timeouts and hid validation causes).

Every classification preserves the ORIGINAL exception type identity
(``exception_class`` / ``exception_module`` / ``cause_chain``) so downstream
consumers can audit the raw failure without re-parsing messages.

This module adds NO behavior change by itself: it is a pure function layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --- canonical failure codes (stable strings, RCA-1.2) -----------------------
MODEL_OUTPUT_VALIDATION_ERROR = "model_output_validation_error"
MODEL_OUTPUT_RETRY_EXHAUSTED = "model_output_retry_exhausted"
PROVIDER_RATE_LIMITED = "provider_rate_limited"
PROVIDER_REQUEST_TIMEOUT = "provider_request_timeout"
PROVIDER_CONNECTION_ERROR = "provider_connection_error"
PROVIDER_SERVER_ERROR = "provider_server_error"
PROVIDER_HTTP_ERROR = "provider_http_error"  # other non-429/5xx HTTP statuses
SUPERVISOR_INTEGRATION_FAILED = "supervisor_integration_failed"
BENCHMARK_RUNTIME_FAILURE = "benchmark_runtime_failure"

# classes that represent a real, attributable failure cause; the fallback
# code (BENCHMARK_RUNTIME_FAILURE) means "no rule matched" and MUST route to
# REVIEW_REQUIRED downstream, never to a pass-ish disposition (RCA-1.0)
ATTRIBUTED_CODES = frozenset({
    MODEL_OUTPUT_VALIDATION_ERROR,
    MODEL_OUTPUT_RETRY_EXHAUSTED,
    PROVIDER_RATE_LIMITED,
    PROVIDER_REQUEST_TIMEOUT,
    PROVIDER_CONNECTION_ERROR,
    PROVIDER_SERVER_ERROR,
    PROVIDER_HTTP_ERROR,
    SUPERVISOR_INTEGRATION_FAILED,
})


@dataclass(frozen=True)
class FailureClassification:
    """Type-derived failure identity. ``classified`` is False only for the
    BENCHMARK_RUNTIME_FAILURE fallback."""

    code: str
    classified: bool
    exception_class: str
    exception_module: str
    http_status: int | None = None
    cause_chain: tuple[str, ...] = field(default_factory=tuple)
    # supplemental metadata only — never the classification signal
    output_retry_budget_exhausted: int | None = None
    detail: str = ""

    def as_payload(self) -> dict:
        """JSON-safe projection for trajectory events / failure records."""
        payload = {
            "failure_code": self.code,
            "classified": self.classified,
            "exception_class": self.exception_class,
            "exception_module": self.exception_module,
            "cause_chain": list(self.cause_chain),
        }
        if self.http_status is not None:
            payload["http_status"] = self.http_status
        if self.output_retry_budget_exhausted is not None:
            payload["output_retry_budget_exhausted"] = (
                self.output_retry_budget_exhausted)
        if self.detail:
            payload["detail"] = self.detail
        return payload


def _qualified(exc: BaseException) -> tuple[str, str]:
    return (
        type(exc).__name__,
        type(exc).__module__,
    )


def _cause_chain(exc: BaseException) -> tuple[str, ...]:
    chain = []
    seen = 0
    cause = exc.__cause__
    while cause is not None and seen < 5:
        name, module = _qualified(cause)
        chain.append(f"{module}.{name}")
        cause = cause.__cause__
        seen += 1
    return tuple(chain)


def classify_failure(exc: BaseException) -> FailureClassification:
    """Classify one exception by TYPE (never primarily by message)."""
    exc_class, exc_module = _qualified(exc)
    cause_chain = _cause_chain(exc)

    def result(code: str, *, classified: bool = True, **kwargs) -> FailureClassification:
        return FailureClassification(
            code=code,
            classified=classified,
            exception_class=exc_class,
            exception_module=exc_module,
            cause_chain=cause_chain,
            **kwargs,
        )

    # -- pydantic-ai output layer (type identity) -----------------------------
    if exc_class == "UnexpectedModelBehavior" and exc_module.startswith("pydantic_ai"):
        # marker parsing is supplemental metadata, not the classifier
        retries = None
        text = str(exc)
        if "maximum output retries (" in text:
            try:
                retries = int(text.split("maximum output retries (", 1)[1]
                              .split(")", 1)[0])
            except (IndexError, ValueError):
                retries = None
        return result(
            MODEL_OUTPUT_RETRY_EXHAUSTED,
            output_retry_budget_exhausted=retries,
            detail="pydantic-ai structured-output retry budget exhausted",
        )
    if exc_class == "ToolFailed" and exc_module.startswith("pydantic_ai"):
        return result(
            MODEL_OUTPUT_VALIDATION_ERROR,
            detail="tool call failed after model-correctable retries",
        )
    if exc_class in ("ValidationError", "PydanticCustomError") and (
            exc_module.startswith("pydantic") or exc_module.startswith("builtins")):
        return result(
            MODEL_OUTPUT_VALIDATION_ERROR,
            detail="pydantic validation rejected the model output",
        )

    # -- openai SDK transport / HTTP layer (type identity) --------------------
    if exc_class == "APITimeoutError" and exc_module.split(".")[0] == "openai":
        return result(
            PROVIDER_REQUEST_TIMEOUT,
            detail="per-attempt timeout inside the openai SDK",
        )
    if exc_class == "APIConnectionError" and exc_module.split(".")[0] == "openai":
        return result(
            PROVIDER_CONNECTION_ERROR,
            detail="connection error inside the openai SDK",
        )

    # -- HTTP status bearing errors (SDK field, not string) -------------------
    status = getattr(exc, "status_code", None)
    if status is None:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
    if isinstance(status, int) and not isinstance(exc, (KeyboardInterrupt, SystemExit)):
        # pydantic_ai.ModelHTTPError and openai.APIStatusError both expose it
        if status == 429:
            return result(PROVIDER_RATE_LIMITED, http_status=status)
        if 500 <= status <= 599:
            return result(PROVIDER_SERVER_ERROR, http_status=status)
        if 400 <= status <= 499:
            return result(PROVIDER_HTTP_ERROR, http_status=status)

    # -- builtin timeouts (asyncio.wait_for surfaces TimeoutError) ------------
    if exc_class == "TimeoutError":
        return result(PROVIDER_REQUEST_TIMEOUT, detail="builtin timeout")

    # -- fallback: no rule matched --------------------------------------------
    return result(
        BENCHMARK_RUNTIME_FAILURE,
        classified=False,
        detail="no type-derived classification rule matched",
    )


def is_output_failure(code: str) -> bool:
    return code in (MODEL_OUTPUT_VALIDATION_ERROR, MODEL_OUTPUT_RETRY_EXHAUSTED)


def is_provider_failure(code: str) -> bool:
    return code in (
        PROVIDER_RATE_LIMITED,
        PROVIDER_REQUEST_TIMEOUT,
        PROVIDER_CONNECTION_ERROR,
        PROVIDER_SERVER_ERROR,
        PROVIDER_HTTP_ERROR,
    )


__all__ = [
    "ATTRIBUTED_CODES",
    "BENCHMARK_RUNTIME_FAILURE",
    "FailureClassification",
    "MODEL_OUTPUT_RETRY_EXHAUSTED",
    "MODEL_OUTPUT_VALIDATION_ERROR",
    "PROVIDER_CONNECTION_ERROR",
    "PROVIDER_HTTP_ERROR",
    "PROVIDER_RATE_LIMITED",
    "PROVIDER_REQUEST_TIMEOUT",
    "PROVIDER_SERVER_ERROR",
    "SUPERVISOR_INTEGRATION_FAILED",
    "classify_failure",
    "is_output_failure",
    "is_provider_failure",
]
