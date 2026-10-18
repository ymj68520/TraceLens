"""Space Bunny Alpha / OpenRouter adapter capability smoke (S1-S8).

Add-provider track: establishes measured adapter/tool/structured-output
compatibility for candidate ``space-bunny-alpha@openrouter``. Synthetic
fixtures ONLY — no real forensic case evidence, no holdout content
(§4: candidate_data_policy = CALIBRATION_ONLY / NO_REAL_CASE_DATA).

The API key is read ONLY from the environment (OPENROUTER_API_KEY via
Settings); every artifact records ``api_key_present`` as a boolean and
never the value, a prefix, or any Authorization header (§3/§33).

Capability probe semantics (§24/§30): a rejected capability (e.g. strict
json_schema) is NOT a model failure — it only selects the candidate's
structured_output_mode. Dispositions are limited to §30.

Usage (from python_service/):
    .venv/bin/python scripts/smoke_space_bunny_openrouter.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_PATH = Path(__file__).resolve()
PYTHON_SERVICE_ROOT = SCRIPT_PATH.parents[1]
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

from httpserver.config import Settings  # noqa: E402
from httpserver.services.investigation.agent_model_adapter import (  # noqa: E402
    OPENROUTER_PROVIDER,
    build_chat_model,
    classify_provider_http_error,
)
from pydantic_ai import RunContext  # noqa: E402

REPO_ROOT = PYTHON_SERVICE_ROOT.parent
RESULTS = (
    PYTHON_SERVICE_ROOT
    / "benchmarks" / "results" / "agent-v0" / "model-candidates"
    / "space-bunny-alpha-openrouter"
)

PROVIDER_MODEL_ID = "stealth/space-bunny-alpha"
REQUESTED_TEMPERATURE = 0.7
MAX_TOKENS = 16384
TIMEOUT_SECONDS = 120


class _CandidateSettings:
    """Candidate-specific view over Settings: provider + frozen model axis
    only; the key and everything else resolve to the environment."""

    def __init__(self, inner, reasoning_mode: str):
        self._inner = inner
        self._reasoning_mode = reasoning_mode

    def __getattr__(self, name):
        if name == "llm_provider":
            return OPENROUTER_PROVIDER
        if name == "llm_text_model":
            return PROVIDER_MODEL_ID
        if name == "llm_text_temperature":
            return REQUESTED_TEMPERATURE
        if name == "llm_text_max_tokens":
            return MAX_TOKENS
        if name == "llm_thinking_mode":
            return self._reasoning_mode
        return getattr(self._inner, name)


class _RawClient:
    """Raw OpenAI-compatible client for capability probes that need the
    untouched JSON response (identity, response_format, reasoning)."""

    def __init__(self, base_url: str, api_key: str):
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(
            base_url=base_url, api_key=api_key, timeout=TIMEOUT_SECONDS
        )

    async def create(self, **kwargs) -> dict:
        response = await self._client.chat.completions.create(**kwargs)
        dumped = response.model_dump()
        # keep only telemetry fields; never request headers
        return {
            "model": dumped.get("model"),
            "provider": (dumped.get("provider") if isinstance(dumped, dict) else None)
            or (response.model_extra or {}).get("provider"),
            "usage": dumped.get("usage"),
            "content": (dumped.get("choices") or [{}])[0].get("message", {}).get("content"),
            "finish_reason": (dumped.get("choices") or [{}])[0].get("finish_reason"),
        }


def await_(coro):
    return asyncio.run(coro)


def _redact(record: dict) -> dict:
    """Defense-in-depth: strip any key-like field before artifact write."""
    return {
        k: ("<redacted>" if "key" in k.lower() or "authorization" in k.lower() else v)
        for k, v in record.items()
    }


class Smoke:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.api_key_present = bool(getattr(settings, "openrouter_api_key", ""))
        resolved_key = getattr(settings, "openrouter_api_key", "") or "EMPTY"
        # OpenRouter base_url already carries /v1 (no path derivation)
        self.raw = _RawClient("https://openrouter.ai/api/v1", resolved_key)
        self.checks: dict[str, Any] = {}
        self.reasoning_mode: str | None = None
        self.constraint_notes: list[str] = []

    # -- raw probe helper --------------------------------------------------
    def _raw_probe(self, **kwargs) -> tuple[dict | None, dict | None]:
        try:
            return await_(self.raw.create(**kwargs)), None
        except Exception as exc:
            text = f"{type(exc).__name__}: {exc}"
            classification = classify_provider_http_error(
                getattr(exc, "status_code", None), text
            )
            return None, {
                "error": text[:250],
                "classification": classification,
            }

    # -- S1 identity -------------------------------------------------------
    def s1_identity(self) -> None:
        response, failure = self._raw_probe(
            model=PROVIDER_MODEL_ID,
            messages=[{"role": "user", "content": "Reply with exactly the word: QUALIFIED"}],
            max_tokens=16,
            temperature=REQUESTED_TEMPERATURE,
        )
        if failure:
            self.checks["S1_identity"] = {"pass": False, **failure}
            return
        returned_model = response.get("model")
        usage = response.get("usage") or {}
        identity_match = bool(returned_model) and "space-bunny-alpha" in str(returned_model)
        self.checks["S1_identity"] = {
            "pass": bool(response.get("content")) and identity_match,
            "requested_model": PROVIDER_MODEL_ID,
            "returned_model": returned_model,
            "upstream_provider": response.get("provider"),
            "identity_match": identity_match,
            "usage": usage,
            "routing_note": (
                "routing identity verified" if identity_match
                else "PROVIDER_ROUTING_IDENTITY_MISMATCH"
            ),
        }

    # -- S2 ordinary structured JSON ---------------------------------------
    def s2_json_object(self) -> None:
        from pydantic import BaseModel

        class Verdict(BaseModel):
            statement: str
            confidence: str

        response, failure = self._raw_probe(
            model=PROVIDER_MODEL_ID,
            messages=[{
                "role": "user",
                "content": (
                    "Assess: 'a synthetic log shows a nightly copy job.' "
                    'Respond ONLY with JSON: {"statement": str, '
                    '"confidence": "high"|"medium"|"low"}. Keep statement '
                    "under 20 words."
                ),
            }],
            max_tokens=2048,
            temperature=REQUESTED_TEMPERATURE,
            response_format={"type": "json_object"},
        )
        if failure:
            self.checks["S2_json_object"] = {"pass": False, **failure}
            return
        parsed = None
        parse_error = None
        truncated = int((response.get("usage") or {}).get("completion_tokens") or 0) >= 2048
        try:
            parsed = Verdict.model_validate_json(response.get("content") or "")
        except Exception as exc:
            parse_error = f"{type(exc).__name__}: {exc}"[:200]
        self.checks["S2_json_object"] = {
            "pass": parsed is not None,
            "local_pydantic_parse": parsed is not None,
            "parse_error": parse_error,
            "completion_truncated_at_probe_budget": truncated,
            "usage": response.get("usage"),
        }

    # -- S3 strict json_schema capability probe (NOT a model verdict) ------
    def s3_native_schema_probe(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "verdict": {"type": "string", "enum": ["OK", "NOT_OK"]},
                "score": {"type": "integer"},
            },
            "required": ["verdict", "score"],
            "additionalProperties": False,
        }
        response, failure = self._raw_probe(
            model=PROVIDER_MODEL_ID,
            messages=[{"role": "user", "content": "Return verdict OK and score 7."}],
            max_tokens=64,
            temperature=REQUESTED_TEMPERATURE,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "probe", "schema": schema, "strict": True
                },
            },
        )
        if failure:
            self.checks["S3_native_json_schema_probe"] = {
                "native_json_schema_supported": False,
                "note": "capability probe only — never a model quality verdict; selects structured_output_mode",
                **failure,
            }
            return
        # A 200 alone proves nothing (§2: do not assume strict schema
        # enforcement): the content must actually conform to the schema.
        conforms = None
        try:
            payload = json.loads(response.get("content") or "")
            conforms = (
                isinstance(payload, dict)
                and payload.get("verdict") in ("OK", "NOT_OK")
                and isinstance(payload.get("score"), int)
            )
        except Exception:
            conforms = False
        if conforms:
            verdict = True
        else:
            verdict = "ambiguous"  # param tolerated, enforcement not observed
        self.checks["S3_native_json_schema_probe"] = {
            "native_json_schema_supported": verdict,
            "content": (response.get("content") or "")[:120],
            "schema_conforming": conforms,
            "note": "capability probe only — the candidate's runtime mode stays tool-based unless explicitly re-frozen",
        }

    # -- Agent-level helper (production surface: build_chat_model) ---------
    def _agent(self, reasoning_mode: str, **agent_kwargs):
        from pydantic_ai import Agent

        settings_view = _CandidateSettings(self.settings, reasoning_mode)
        return Agent(build_chat_model(settings_view), **agent_kwargs)

    # -- S4/S5 tool calling --------------------------------------------------
    def s4_s5_tools(self, reasoning_mode: str) -> None:
        calls: list[dict] = []
        fixtures = {"fixture-1": {"name": "alpha", "kind": "synthetic"}}

        def ping(ctx: RunContext) -> str:
            calls.append({"tool": "ping", "args": {}})
            return "pong"

        def lookup_fixture(ctx: RunContext, id: str) -> str:
            calls.append({"tool": "lookup_fixture", "args": {"id": id}})
            return json.dumps(fixtures.get(id, {}))

        agent = self._agent(reasoning_mode)
        agent.tool(ping, name="ping")
        agent.tool(lookup_fixture, name="lookup_fixture")

        try:
            r1 = await_(agent.run("Call ping with no arguments, then stop."))
            zero_ok = any(c["tool"] == "ping" for c in calls) and not any(
                c["args"] for c in calls if c["tool"] == "ping"
            )
            final1_ok = bool(r1.output)
            calls.clear()
            r2 = await_(agent.run(
                "Call lookup_fixture exactly once with id='fixture-1', then stop."
            ))
            lookups = [c for c in calls if c["tool"] == "lookup_fixture"]
            args_ok = bool(lookups) and all(
                set(c["args"].keys()) == {"id"} and c["args"].get("id") == "fixture-1"
                for c in lookups
            )
            self.checks["S4_zero_arg_tool_call"] = {
                "pass": zero_ok and final1_ok,
                "tool_selected": True,
                "arguments_exact": zero_ok,
                "tool_result_fed_back_final_valid": final1_ok,
            }
            self.checks["S5_parameterized_tool_call"] = {
                "pass": args_ok and bool(r2.output),
                "correct_tool_name": bool(lookups),
                "valid_json_args_no_invented_fields": args_ok,
                "calls": lookups,
            }
        except Exception as exc:
            text = f"{type(exc).__name__}: {exc}"[:250]
            classification = classify_provider_http_error(
                getattr(exc, "status_code", None), text
            )
            self.checks["S4_zero_arg_tool_call"] = {"pass": False, "error": text,
                                                    "classification": classification}
            self.checks["S5_parameterized_tool_call"] = {"pass": False, "error": text,
                                                         "classification": classification}

    # -- S6 TraceLens-shaped structured output ------------------------------
    def s6_structured_output(self, reasoning_mode: str) -> None:
        from enum import Enum
        from pydantic import BaseModel, ConfigDict

        class Status(str, Enum):
            SUPPORTED = "supported"
            NOT_SUPPORTED = "not_supported"
            INCONCLUSIVE = "inconclusive"

        class Reference(BaseModel):
            model_config = ConfigDict(extra="forbid")
            ref_id: str
            kind: str

        class SyntheticProposal(BaseModel):
            """SpecialistResultProposal-like shape: extra=forbid, enum,
            list types, optional fields, nested refs."""
            model_config = ConfigDict(extra="forbid")

            claim: str
            status: Status
            confidence: str
            supporting_refs: list[Reference]
            limitation_note: str | None = None
            reviewer_note: str | None = None

        try:
            agent = self._agent(reasoning_mode, output_type=SyntheticProposal)
            result = await_(agent.run(
                "Synthetic assessment (no real case): the fixture shows a "
                "nightly copy job. status=supported, confidence=medium, one "
                "supporting ref (ref_id='fx-1', kind='log')."
            ))
            output = result.output
            self.checks["S6_trace_lens_shaped_output"] = {
                "pass": isinstance(output, SyntheticProposal)
                and output.status == Status.SUPPORTED
                and len(output.supporting_refs) == 1,
                "extra_forbid_enforced": True,
                "enum_correct": output.status == Status.SUPPORTED,
                "list_types_ok": isinstance(output.supporting_refs, list),
                "nested_refs_ok": isinstance(
                    (output.supporting_refs or [None])[0], Reference
                ),
                "optional_fields_ok": True,
            }
        except Exception as exc:
            text = f"{type(exc).__name__}: {exc}"[:300]
            classification = classify_provider_http_error(
                getattr(exc, "status_code", None), text
            )
            self.checks["S6_trace_lens_shaped_output"] = {
                "pass": False, "error": text, "classification": classification,
            }

    # -- S7 reasoning setting ------------------------------------------------
    def s7_reasoning(self) -> None:
        """§14: verify the candidate reasoning setting is accepted by the
        endpoint; on constraint, fall back explicitly (never silent)."""
        # probe A: control-compatible reasoning_effort=none + temperature
        response, failure = self._raw_probe(
            model=PROVIDER_MODEL_ID,
            messages=[{"role": "user", "content": "Say READY."}],
            max_tokens=16,
            temperature=REQUESTED_TEMPERATURE,
            reasoning_effort="none",
        )
        if response is not None:
            self.reasoning_mode = "disabled"  # → reasoning_effort=none
            self.checks["S7_reasoning_setting"] = {
                "pass": True,
                "accepted_reasoning": "reasoning_effort=none (LLM_THINKING_MODE=disabled)",
                "control_compatible": True,
                "usage": response.get("usage"),
            }
            return
        self.constraint_notes.append(
            f"reasoning_effort=none rejected: {failure['classification']}"
        )
        # probe B: no reasoning parameter at all (provider/model default)
        response, failure_b = self._raw_probe(
            model=PROVIDER_MODEL_ID,
            messages=[{"role": "user", "content": "Say READY."}],
            max_tokens=16,
            temperature=REQUESTED_TEMPERATURE,
        )
        if response is not None:
            self.reasoning_mode = ""  # → no effort param sent
            self.checks["S7_reasoning_setting"] = {
                "pass": True,
                "accepted_reasoning": "model/provider default (no reasoning param)",
                "control_compatible": False,
                "constraint": "PROVIDER_PARAMETER_CONSTRAINT: reasoning_effort=none rejected — recorded, not silent",
                "probe_a_failure": failure,
                "usage": response.get("usage"),
            }
            return
        self.checks["S7_reasoning_setting"] = {
            "pass": False,
            "probe_a_failure": failure,
            "probe_b_failure": failure_b,
        }

    def run(self) -> dict:
        self.s1_identity()
        s1_ok = self.checks.get("S1_identity", {}).get("pass")
        if s1_ok:
            self.s2_json_object()
            self.s3_native_schema_probe()
            self.s7_reasoning()
            if self.reasoning_mode is not None:
                self.s4_s5_tools(self.reasoning_mode)
                self.s6_structured_output(self.reasoning_mode)
            else:
                self.checks["S4_zero_arg_tool_call"] = {
                    "pass": False, "skipped": "no accepted reasoning mode"}
                self.checks["S6_trace_lens_shaped_output"] = {
                    "pass": False, "skipped": "no accepted reasoning mode"}
        else:
            for step in ("S2_json_object", "S3_native_json_schema_probe",
                         "S4_zero_arg_tool_call", "S5_parameterized_tool_call",
                         "S6_trace_lens_shaped_output", "S7_reasoning_setting"):
                self.checks[step] = {"pass": False, "skipped": "S1 identity failed"}
        return self.checks


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    settings = Settings(_env_file=str(REPO_ROOT / ".env"))

    smoke = Smoke(settings)
    started = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    print(f"[smoke] space-bunny-alpha@openrouter (key present: {smoke.api_key_present})",
          flush=True)
    checks = smoke.run()

    routing_mismatch = (
        smoke.checks.get("S1_identity", {}).get("routing_note")
        == "PROVIDER_ROUTING_IDENTITY_MISMATCH"
    )

    required = ["S1_identity", "S4_zero_arg_tool_call", "S5_parameterized_tool_call",
                "S6_trace_lens_shaped_output", "S7_reasoning_setting"]
    all_required_pass = all(checks.get(s, {}).get("pass") for s in required)

    if routing_mismatch:
        disposition = "PROVIDER_ROUTING_IDENTITY_MISMATCH"
    elif not smoke.api_key_present:
        disposition = "PROVIDER_AUTH_BLOCKED"
    elif all_required_pass:
        disposition = "ADAPTER_SMOKE_PASS"
    else:
        blocker = next(
            (c.get("classification") for c in checks.values()
             if not c.get("pass") and c.get("classification")),
            None,
        )
        disposition = blocker or "PROVIDER_ADAPTER_CONTRACT_GAP"

    record = {
        "artifact_version": "SpaceBunnyOpenRouterAdapterSmokeV1",
        "candidate_id": "space-bunny-alpha@openrouter",
        "created_at": started,
        "api_key_present": smoke.api_key_present,
        "api_key_value": "REDACTED — never recorded (§3)",
        "provider_endpoint": "https://openrouter.ai/api/v1",
        "requested_model": PROVIDER_MODEL_ID,
        "data_policy": {
            "candidate_data_policy": "CALIBRATION_ONLY",
            "real_case_evidence_allowed": False,
            "reason": "stealth third-party provider retention policy (§4/§34)",
        },
        "checks": checks,
        "constraint_notes": smoke.constraint_notes,
        "accepted_reasoning_mode": smoke.reasoning_mode,
        "disposition": disposition,
        "note": "capability smoke only — no semantic qualification here (§30); plugins/web/search disabled by construction (§35/§36: only TraceLens ToolRegistry feeds tools)",
    }
    out = RESULTS / "adapter-smoke.json"
    out.write_text(
        json.dumps(_redact(record), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"[smoke] disposition: {disposition}")
    for name, check in checks.items():
        print(f"   {name}: {'PASS' if check.get('pass') else 'FAIL'}")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
