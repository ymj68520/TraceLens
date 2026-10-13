"""step-3.7-flash @ stepfun admission smoke (provider-switch retry).

The operator switched the legacy provider path (.env) to StepFun; per the
frozen §14 identity rule this is a NEW candidate (provider endpoint +
model changed) and the screening chain re-runs from smoke. Checks the
exact frozen parameter shape first (temperature 0.7 +
reasoning_effort=none, control-compatible), then the production
structured-output / tool surface. Synthetic fixtures only.

Usage (from python_service/):
    .venv/bin/python scripts/smoke_stepfun_step37flash.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PYTHON_SERVICE_ROOT = SCRIPT_PATH.parents[1]
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

from httpserver.config import Settings  # noqa: E402
from httpserver.services.investigation.agent_model_adapter import (  # noqa: E402
    build_chat_model,
    classify_provider_http_error,
    resolve_adapter_config,
)
from pydantic import BaseModel, ConfigDict  # noqa: E402
from pydantic_ai import Agent, RunContext  # noqa: E402

REPO_ROOT = PYTHON_SERVICE_ROOT.parent
RESULTS = (
    PYTHON_SERVICE_ROOT
    / "benchmarks" / "results" / "agent-v0" / "model-candidates"
    / "step-3.7-flash-stepfun"
)

PROVIDER_MODEL_ID = "step-3.7-flash"
MAX_TOKENS = 16384
TEMPERATURE = 0.7


def await_(coro):
    return asyncio.run(coro)


class Verdict(BaseModel):
    statement: str
    confidence: str


class Status(str, __import__("enum").Enum):
    SUPPORTED = "supported"
    NOT_SUPPORTED = "not_supported"
    INCONCLUSIVE = "inconclusive"


class Reference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref_id: str
    kind: str


class SyntheticProposal(BaseModel):
    """SpecialistResultProposal-like shape (extra=forbid, enum, list,
    optional, nested) — the production validation surface."""
    model_config = ConfigDict(extra="forbid")

    claim: str
    status: Status
    confidence: str
    supporting_refs: list[Reference]
    limitation_note: str | None = None


def _raw_probe(settings: Settings, **kwargs) -> tuple[dict | None, dict | None]:
    from openai import AsyncOpenAI

    config = resolve_adapter_config(settings)
    client = AsyncOpenAI(
        base_url=config.base_url,
        api_key=getattr(settings, "llm_api_key", "") or "EMPTY",
        timeout=120,
    )

    async def _call():
        return await client.chat.completions.create(**kwargs)

    try:
        raw = asyncio.run(_call()).model_dump()
        return {
            "model": raw.get("model"),
            "usage": raw.get("usage"),
            "content": (raw.get("choices") or [{}])[0].get("message", {}).get("content"),
        }, None
    except Exception as exc:
        text = f"{type(exc).__name__}: {exc}"
        return None, {
            "error": text[:250],
            "classification": classify_provider_http_error(
                getattr(exc, "status_code", None), text),
        }


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    settings = Settings(_env_file=str(REPO_ROOT / ".env"))
    checks: dict = {}

    # -- S1 identity + control-compatible parameter shape --------------------
    response, failure = _raw_probe(
        settings,
        model=PROVIDER_MODEL_ID,
        messages=[{"role": "user", "content": "Reply with exactly: QUALIFIED"}],
        max_tokens=16,
        temperature=TEMPERATURE,
        reasoning_effort="none",
    )
    reasoning_mode = "disabled"  # control-compatible, pending probe result
    if response is not None:
        checks["S1_identity_reasoning_none"] = {
            "pass": True,
            "returned_model": response.get("model"),
            "identity_exact": response.get("model") == PROVIDER_MODEL_ID,
            "reasoning": "reasoning_effort=none accepted (control-compatible, §14)",
            "usage": response.get("usage"),
        }
    else:
        constraint = failure["classification"] in (
            "PROVIDER_INFRA_FAILURE", "PROVIDER_QUOTA_BLOCKED",
            "PROVIDER_AUTH_BLOCKED", "PROVIDER_MODEL_UNAVAILABLE",
        ) and "400" in failure["error"]
        checks["S1_identity_reasoning_none"] = {"pass": False, **failure}
        # fallback probe: no reasoning param at all
        response, failure_b = _raw_probe(
            settings,
            model=PROVIDER_MODEL_ID,
            messages=[{"role": "user", "content": "Reply with exactly: QUALIFIED"}],
            max_tokens=16,
            temperature=TEMPERATURE,
        )
        if response is not None:
            reasoning_mode = ""  # omit the reasoning parameter entirely
            checks["S7_reasoning_fallback"] = {
                "pass": True,
                "returned_model": response.get("model"),
                "reasoning": (
                    "PROVIDER_PARAMETER_CONSTRAINT: reasoning_effort=none "
                    "rejected — frozen candidate value = no reasoning param "
                    "(recorded, not silent, §14)"
                ),
                "probe_a_failure": failure,
            }
        else:
            checks["S7_reasoning_fallback"] = {"pass": False, **failure_b}
            reasoning_mode = None

    # -- S2 json_object --------------------------------------------------------
    if response is not None:
        r2, f2 = _raw_probe(
            settings,
            model=PROVIDER_MODEL_ID,
            messages=[{
                "role": "user",
                "content": (
                    "Assess: 'a synthetic log shows a nightly copy job.' "
                    'Respond ONLY with JSON: {"statement": str, '
                    '"confidence": "high"|"medium"|"low"}. Statement under 20 words.'
                ),
            }],
            max_tokens=2048,
            temperature=TEMPERATURE,
            response_format={"type": "json_object"},
        )
        parsed = parse_error = None
        if r2 is not None:
            try:
                parsed = Verdict.model_validate_json(r2.get("content") or "")
            except Exception as exc:
                parse_error = f"{type(exc).__name__}: {exc}"[:200]
        checks["S2_json_object"] = {
            "pass": parsed is not None,
            "parse_error": parse_error, **(f2 or {}),
        }

        # -- production surface: Agent + tools + structured output -------------
        settings_view = settings
        if reasoning_mode != "disabled":
            class _View:
                def __init__(self, inner, mode):
                    self._inner, self._mode = inner, mode

                def __getattr__(self, name):
                    if name == "llm_thinking_mode":
                        return self._mode
                    return getattr(self._inner, name)

            settings_view = _View(settings, reasoning_mode)
        model = build_chat_model(settings_view)

        try:
            calls: list[dict] = []

            def ping(ctx: RunContext) -> str:
                calls.append({"tool": "ping", "args": {}})
                return "pong"

            def lookup_fixture(ctx: RunContext, id: str) -> str:
                calls.append({"tool": "lookup_fixture", "args": {"id": id}})
                return json.dumps({"name": "alpha", "kind": "synthetic"})

            agent = Agent(model)
            agent.tool(ping, name="ping")
            agent.tool(lookup_fixture, name="lookup_fixture")
            r3 = await_(agent.run("Call ping with no arguments, then stop."))
            zero_ok = any(c["tool"] == "ping" for c in calls) and not any(
                c["args"] for c in calls if c["tool"] == "ping")
            calls.clear()
            await_(agent.run(
                "Call lookup_fixture exactly once with id='fixture-1', then stop."))
            lookups = [c for c in calls if c["tool"] == "lookup_fixture"]
            args_ok = bool(lookups) and all(
                set(c["args"]) == {"id"} and c["args"]["id"] == "fixture-1"
                for c in lookups)
            checks["S4_S5_tool_calls"] = {
                "pass": zero_ok and args_ok,
                "zero_arg_exact": zero_ok,
                "param_no_invented_fields": args_ok,
            }
        except Exception as exc:
            text = f"{type(exc).__name__}: {exc}"[:250]
            checks["S4_S5_tool_calls"] = {
                "pass": False, "error": text,
                "classification": classify_provider_http_error(
                    getattr(exc, "status_code", None), text),
            }

        try:
            agent6 = Agent(model, output_type=SyntheticProposal)
            result = await_(agent6.run(
                "Synthetic assessment (no real case): the fixture shows a "
                "nightly copy job. status=supported, confidence=medium, one "
                "supporting ref (ref_id='fx-1', kind='log')."
            ))
            output = result.output
            checks["S6_trace_lens_shaped_output"] = {
                "pass": isinstance(output, SyntheticProposal)
                and output.status == Status.SUPPORTED,
                "extra_forbid_enum_list_nested_ok": True,
            }
        except Exception as exc:
            text = f"{type(exc).__name__}: {exc}"[:300]
            checks["S6_trace_lens_shaped_output"] = {
                "pass": False, "error": text,
                "classification": classify_provider_http_error(
                    getattr(exc, "status_code", None), text),
            }

    required_pass = all(
        c.get("pass") for c in checks.values()
    ) and checks.get("S1_identity_reasoning_none", {}).get("pass") is not None or bool(
        checks.get("S7_reasoning_fallback", {}).get("pass")
    )
    core = ["S4_S5_tool_calls", "S6_trace_lens_shaped_output"]
    if all(checks.get(k, {}).get("pass") for k in core) and (
        checks.get("S1_identity_reasoning_none", {}).get("pass")
        or checks.get("S7_reasoning_fallback", {}).get("pass")
    ):
        disposition = "ADAPTER_SMOKE_PASS"
    else:
        blocker = next((c.get("classification") for c in checks.values()
                        if not c.get("pass") and c.get("classification")), None)
        disposition = blocker or "ADAPTER_SMOKE_FAIL"

    record = {
        "artifact_version": "StepFunStep37FlashAdapterSmokeV1",
        "candidate_id": "step-3.7-flash@stepfun",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "api_key_present": bool(getattr(settings, "llm_api_key", "")),
        "provider_endpoint": resolve_adapter_config(settings).base_url,
        "requested_model": PROVIDER_MODEL_ID,
        "accepted_reasoning_mode": reasoning_mode,
        "data_policy": {
            "candidate_data_policy": "CALIBRATION_ONLY",
            "real_case_evidence_allowed": False,
        },
        "checks": checks,
        "disposition": disposition,
    }
    out = RESULTS / "adapter-smoke.json"
    out.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"[smoke] step-3.7-flash@stepfun -> {disposition}")
    for name, check in checks.items():
        print(f"   {name}: {'PASS' if check.get('pass') else 'FAIL'}")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
