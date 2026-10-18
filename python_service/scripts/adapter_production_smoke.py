"""B2-restart §3 production adapter smoke.

Drives the REAL production adapter chain (Settings -> resolve_adapter_config
-> build_chat_model -> PydanticAI -> provider) through the capability
surfaces the Agent v0 runtime depends on:

  1. basic completion (str output)
  2. structured output via the frozen provider profile (json_object path)
  3. tool calling with a required argument (args must arrive and validate)
  4. ZERO-argument tool calling (the extra=forbid production discipline
     that disqualified Qwen3.8-27B at the specialist layer)
  5. usage metadata on every probe

Model identity capture is metadata-only: the API-reported model id is
taken from one raw metadata probe and from whatever the PydanticAI
message history exposes. The API key never enters the artifact.

Usage (from python_service/):
    .venv/bin/python scripts/adapter_production_smoke.py \
        --out benchmarks/results/agent-v0/b2-restart/smoke/adapter-smoke.v1.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PYTHON_SERVICE_ROOT = SCRIPT_PATH.parents[1]
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

REPO_ROOT = PYTHON_SERVICE_ROOT.parent


# -- structured-output target (probe 2) --------------------------------------

from typing import Literal

from pydantic import BaseModel, Field


class _SmokeVerdict(BaseModel):
    """Small structured output target: enum + string + int constraints."""

    verdict: Literal["support", "refute", "not_supported"]
    rationale: str = Field(min_length=3, max_length=200)
    confidence_0_to_100: int = Field(ge=0, le=100)


# -- probes -------------------------------------------------------------------

_TOOL_CALLED: dict = {}


def _run_probe(agent, prompt: str, *, output_type=None, toolsets=None):
    import asyncio

    async def _go():
        kwargs = {}
        if output_type is not None:
            kwargs["output_type"] = output_type
        if toolsets is not None:
            kwargs["toolsets"] = toolsets
        return await agent.run(prompt, **kwargs)

    return asyncio.run(_go())


def _usage_dict(usage) -> dict:
    out = {}
    for name in (
        "requests",
        "input_tokens",
        "output_tokens",
        "details",
    ):
        value = getattr(usage, name, None)
        if value is not None:
            out[name] = value
    return out


def _message_model_names(messages) -> list:
    names = []
    for msg in messages:
        kind = getattr(msg, "kind", None)
        if kind != "response":
            continue
        reported = None
        for attr in (
            "provider_response_name",
            "model_name",
            "provider_name",
        ):
            value = getattr(msg, attr, None)
            if value:
                reported = f"{attr}={value}"
                break
        if reported:
            names.append(reported)
    return names


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="adapter_production_smoke")
    parser.add_argument(
        "--out",
        default=(
            "benchmarks/results/agent-v0/b2-restart/smoke/"
            "adapter-smoke.v1.json"
        ),
    )
    parser.add_argument(
        "--raw-identity-probe",
        action="store_true",
        default=True,
        help="also capture the API-reported model id via one raw request",
    )
    args = parser.parse_args(argv)

    from httpserver.config import Settings
    from httpserver.services.investigation.agent_model_adapter import (
        build_chat_model,
        resolve_adapter_config,
    )

    settings = Settings(_env_file=str(REPO_ROOT / ".env"))
    adapter_config = resolve_adapter_config(settings)
    model = build_chat_model(settings)

    report: dict = {
        "report_version": "adapter-production-smoke:v1",
        "round": "b2-model-requalification",
        "requested_model_id": adapter_config.model_name,
        "adapter_config": {
            # class-level endpoint description only; no secrets, no key
            "base_url_class": (
                adapter_config.base_url.split("//", 1)[-1].split("/", 1)[0]
            ),
            "reasoning_effort": adapter_config.reasoning_effort,
            "temperature": adapter_config.temperature,
            "max_tokens": adapter_config.max_tokens,
            "timeout_seconds": adapter_config.timeout_seconds,
        },
        "api_reported_model_id": None,
        "probes": {},
        "all_passed": False,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }

    # -- raw metadata probe: API-reported model identity (metadata only) --
    if args.raw_identity_probe:
        import urllib.request

        api_key = getattr(settings, "llm_api_key", "") or "EMPTY"
        body = json.dumps(
            {
                "model": adapter_config.model_name,
                "messages": [
                    {"role": "user", "content": "identity probe"}
                ],
                "max_tokens": 5,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            adapter_config.base_url.rstrip('/') + '/chat/completions',
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                req, timeout=adapter_config.timeout_seconds or 120
            ) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            report["api_reported_model_id"] = payload.get("model")
            report["raw_probe_finish"] = (payload.get("choices") or [{}])[
                0
            ].get("finish_reason")
        except Exception as exc:
            report["probes"]["raw_identity"] = {
                "passed": False,
                "error": f"{type(exc).__name__}: {exc}"[:300],
            }

    from pydantic_ai import Agent

    # probe 1: basic completion
    t0 = time.monotonic()
    try:
        basic = Agent(model, instructions="You are a terse test fixture.")
        result = _run_probe(
            basic, "Reply with exactly: ADAPTER_SMOKE_OK"
        )
        text = result.output
        report["probes"]["basic_completion"] = {
            "passed": "ADAPTER_SMOKE_OK" in str(text),
            "output": str(text)[:80],
            "usage": _usage_dict(result.usage),
            "latency_s": round(time.monotonic() - t0, 2),
        }
    except Exception as exc:
        report["probes"]["basic_completion"] = {
            "passed": False,
            "error": f"{type(exc).__name__}: {exc}"[:400],
        }

    # probe 2: structured output through the frozen provider profile
    t0 = time.monotonic()
    try:
        structured = Agent(
            model,
            instructions=(
                "You judge evidence claims. Answer only with the "
                "required structured fields."
            ),
        )
        result = _run_probe(
            structured,
            (
                "Claim: 'The suspect's laptop contains a USB script "
                "folder, verified by two independent files.' Verdict?"
            ),
            output_type=_SmokeVerdict,
        )
        verdict = result.output
        ok = (
            isinstance(verdict, _SmokeVerdict)
            and verdict.verdict
            in ("support", "refute", "not_supported")
            and isinstance(verdict.confidence_0_to_100, int)
        )
        report["probes"]["structured_output"] = {
            "passed": bool(ok),
            "output": json.loads(verdict.model_dump_json())
            if ok
            else str(verdict)[:200],
            "usage": _usage_dict(result.usage),
            "latency_s": round(time.monotonic() - t0, 2),
        }
    except Exception as exc:
        report["probes"]["structured_output"] = {
            "passed": False,
            "error": f"{type(exc).__name__}: {exc}"[:400],
        }

    # probe 3: tool calling with a required argument
    _TOOL_CALLED.clear()

    from pydantic_ai.tools import Tool

    def _record_observation(evidence_ref: str) -> str:
        _TOOL_CALLED["args"] = evidence_ref
        return f"observation recorded for {evidence_ref}"

    record_observation = Tool(
        _record_observation,
        name="record_observation",
        description="Record one evidence observation reference.",
    )

    t0 = time.monotonic()
    try:
        tool_agent = Agent(
            model,
            instructions=(
                "You must call the record_observation tool exactly "
                "once with evidence_ref set to 'file:notes.txt', then "
                "reply DONE."
            ),
            tools=[record_observation],
        )
        result = _run_probe(
            tool_agent,
            "Proceed with your instruction.",
        )
        called_ok = _TOOL_CALLED.get("args") == "file:notes.txt"
        report["probes"]["tool_call_with_args"] = {
            "passed": bool(called_ok),
            "tool_args_seen": _TOOL_CALLED.get("args"),
            "final_output": str(result.output)[:80],
            "usage": _usage_dict(result.usage),
            "latency_s": round(time.monotonic() - t0, 2),
        }
    except Exception as exc:
        report["probes"]["tool_call_with_args"] = {
            "passed": False,
            "error": f"{type(exc).__name__}: {exc}"[:400],
        }

    # probe 4: ZERO-argument tool (production extra=forbid discipline)
    _TOOL_CALLED.clear()

    def _get_task_context() -> str:
        _TOOL_CALLED["called"] = True
        return "task context: 3 files, 1 note, no events"

    get_task_context = Tool(
        _get_task_context,
        name="get_task_context",
        description="Task context summary (takes no arguments).",
    )

    t0 = time.monotonic()
    try:
        zero_agent = Agent(
            model,
            instructions=(
                "Call the get_task_context tool once (it takes no "
                "arguments — pass an empty parameter object), then "
                "summarize in one short sentence."
            ),
            tools=[get_task_context],
        )
        result = _run_probe(
            zero_agent, "Proceed with your instruction."
        )
        report["probes"]["zero_arg_tool"] = {
            "passed": bool(_TOOL_CALLED.get("called")),
            "final_output": str(result.output)[:120],
            "usage": _usage_dict(result.usage),
            "latency_s": round(time.monotonic() - t0, 2),
        }
    except Exception as exc:
        report["probes"]["zero_arg_tool"] = {
            "passed": False,
            "tool_called": bool(_TOOL_CALLED.get("called")),
            "error": f"{type(exc).__name__}: {exc}"[:400],
        }

    report["all_passed"] = all(
        p.get("passed") for p in report["probes"].values()
    )

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = PYTHON_SERVICE_ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"report -> {out_path}")
    for name, probe in report["probes"].items():
        print(
            f"  {name}: {'PASS' if probe.get('passed') else 'FAIL'}"
            + (
                f"  ({probe.get('error', '')[:120]})"
                if not probe.get("passed")
                else ""
            )
        )
    print(
        "ALL PASS" if report["all_passed"] else "SMOKE FAILED"
    )
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
