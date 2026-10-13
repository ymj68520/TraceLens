"""Structured failure diagnostics sink (RCA-1.3).

Optional, DEFAULT-OFF structured capture of agent-stage model failures,
covering SUPERVISOR_PLAN, SUPERVISOR_INTEGRATE and SPECIALIST. Replaces the
unmaintainable global monkey-patch approach of
``scripts/diagnose_specialist_output.py`` with an explicit injection point:
call sites hand the sink a FailureClassification (agent_failure_taxonomy)
plus stage context; the sink sanitizes and serializes.

Captured per event (audit §3 evidence-availability gaps):
    stage, ts, exception_class/module, normalized_failure_code,
    cause_class_chain, retry_attempts, validation_error_type/location,
    tool_name, schema_hash, request_latency_ms, provider_status

Hard redaction rules (audit directive RCA-1.3):
    - never API keys / Authorization headers (never touched at all);
    - never real-case Evidence bodies (no tool results, no evidence text);
    - never model-private reasoning content;
    - no full prompt/response dumps;
    - pydantic ValidationError details are reduced to error TYPE and
      schema LOCATION (field paths + indices) — the offending ``input``
      values are dropped, so no model output text can leak through the
      one channel that structurally carries it.

Enable explicitly via settings (LLM_FAILURE_DIAGNOSTICS=1 +
LLM_FAILURE_DIAGNOSTICS_PATH=...) or by constructing
JsonlFailureDiagnosticSink directly in tests.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Protocol

from .agent_failure_taxonomy import FailureClassification

STAGE_SUPERVISOR_PLAN = "SUPERVISOR_PLAN"
STAGE_SUPERVISOR_INTEGRATE = "SUPERVISOR_INTEGRATE"
STAGE_SPECIALIST = "SPECIALIST"

STAGES = (STAGE_SUPERVISOR_PLAN, STAGE_SUPERVISOR_INTEGRATE, STAGE_SPECIALIST)


class FailureDiagnosticSink(Protocol):
    def record_failure(self, entry: dict) -> None: ...


class JsonlFailureDiagnosticSink:
    """Append-only JSONL sink. Write errors are never fatal to the caller
    (telemetry must not turn a failure into a different failure)."""

    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def record_failure(self, entry: dict) -> None:
        try:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001 — diagnostics are never fatal
            pass


class ListFailureDiagnosticSink:
    """In-memory sink for deterministic tests."""

    def __init__(self) -> None:
        self.entries: list[dict] = []

    def record_failure(self, entry: dict) -> None:
        self.entries.append(entry)


def failure_diagnostics_sink(settings: Any = None) -> FailureDiagnosticSink | None:
    """Resolve the sink from settings (``llm_failure_diagnostics`` +
    ``llm_failure_diagnostics_path``), falling back to the environment
    (``LLM_FAILURE_DIAGNOSTICS`` / ``LLM_FAILURE_DIAGNOSTICS_PATH``).
    Returns None when disabled — the default."""
    enabled = False
    path = None
    if settings is not None:
        enabled = bool(getattr(settings, "llm_failure_diagnostics", False))
        path = getattr(settings, "llm_failure_diagnostics_path", "") or None
    if not enabled:
        enabled = os.environ.get("LLM_FAILURE_DIAGNOSTICS", "") in (
            "1", "true", "True", "yes")
        path = os.environ.get("LLM_FAILURE_DIAGNOSTICS_PATH") or path
    if not enabled or not path:
        return None
    return JsonlFailureDiagnosticSink(path)


def schema_hash_of(output_type: Any) -> str | None:
    """Deterministic short hash of the structured-output schema — identity
    of the CONTRACT that failed, never the payload that failed it."""
    try:
        schema = json.dumps(output_type.model_json_schema(), sort_keys=True)
        return hashlib.sha256(schema.encode("utf-8")).hexdigest()[:16]
    except Exception:  # noqa: BLE001 — diagnostics are never fatal
        return None


def _validation_error_details(exc: BaseException) -> list[dict]:
    """Reduce a pydantic ValidationError to type+location only.

    ``errors()`` entries carry the offending ``input`` value — model output
    text — which is structurally the one place real content could leak.
    It is dropped here, always.
    """
    details = []
    cause = exc.__cause__ or exc
    errors = getattr(cause, "errors", None)
    if callable(errors):
        try:
            for err in errors():
                if not isinstance(err, dict):
                    continue
                details.append({
                    "type": str(err.get("type")),
                    "loc": [str(part) for part in (err.get("loc") or ())],
                })
        except Exception:  # noqa: BLE001
            return []
    return details[:8]


def build_failure_entry(
    *,
    stage: str,
    exc: BaseException,
    classification: FailureClassification,
    output_schema_hash: str | None = None,
    tool_name: str | None = None,
    retry_attempts: int | None = None,
    request_latency_ms: float | None = None,
    context: dict | None = None,
) -> dict:
    """Assemble one sanitized diagnostics entry. ``context`` may carry
    stage bookkeeping (ids, counters) — never payloads."""
    entry: dict = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "stage": stage,
        "normalized_failure_code": classification.code,
        "classified": classification.classified,
        "exception_class": classification.exception_class,
        "exception_module": classification.exception_module,
        "cause_class_chain": list(classification.cause_chain),
        "provider_status": classification.http_status,
        "validation_error_details": _validation_error_details(exc),
    }
    if output_schema_hash is not None:
        entry["schema_hash"] = output_schema_hash
    if tool_name is not None:
        entry["tool_name"] = tool_name
    if retry_attempts is not None:
        entry["retry_attempts"] = retry_attempts
    if request_latency_ms is not None:
        entry["request_latency_ms"] = round(request_latency_ms, 1)
    if context:
        entry["context"] = context
    return entry


__all__ = [
    "FailureDiagnosticSink",
    "JsonlFailureDiagnosticSink",
    "ListFailureDiagnosticSink",
    "STAGES",
    "STAGE_SPECIALIST",
    "STAGE_SUPERVISOR_INTEGRATE",
    "STAGE_SUPERVISOR_PLAN",
    "build_failure_entry",
    "failure_diagnostics_sink",
    "schema_hash_of",
]
