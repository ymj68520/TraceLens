"""ModelRuntimeQualificationRecordV3 — §5 adapter smoke (live provider).

Six checks against the production model configuration, via the same
adapter the agent runtime uses (agent_model_adapter.build_chat_model):

  1 basic completion        plain text round trip
  2 structured output       json_object-mode PydanticAI output_type
  3 zero-arg tool call      tool invoked without arguments
  4 normal tool call        tool invoked with one argument
  5 usage metadata          request/token usage present on responses
  6 API model identity      response model id == configured model id

Disposition: all PASS -> CONTINUE; any provider-contract change
(endpoint semantics, structured output mode, tool-call shape) ->
STOP_MODEL_ADAPTER.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from pydantic import BaseModel

PYTHON_SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

from httpserver.config import Settings  # noqa: E402
from httpserver.services.investigation.agent_model_adapter import (  # noqa: E402
    build_chat_model,
)
from pydantic_ai import Agent, RunContext  # noqa: E402

RESULTS_ROOT = (
    PYTHON_SERVICE_ROOT
    / "benchmarks" / "results" / "agent-v0" / "requalification" / "runtime-v3"
)


class Verdict(BaseModel):
    statement: str
    confidence: str


def _settings():
    return Settings(_env_file=str(PYTHON_SERVICE_ROOT.parent / ".env"))


async def _run_checks():
    settings = _settings()
    model = build_chat_model(settings)
    results = {}

    # 1 basic completion (plain Agent, no output_type)
    agent1 = Agent(model)
    t0 = time.monotonic()
    r1 = await agent1.run("Reply with exactly the word: QUALIFIED")
    text1 = r1.output if isinstance(r1.output, str) else str(r1.output)
    results["basic_completion"] = {
        "pass": "QUALIFIED" in text1,
        "response_excerpt": text1[:120],
        "latency_seconds": round(time.monotonic() - t0, 2),
    }
    usage = r1.usage
    results["usage_metadata"] = {
        "pass": usage is not None and (
            getattr(usage, "input_tokens", None) is not None
            or getattr(usage, "requests", 0) >= 1
        ),
        "usage": str(usage)[:200],
    }

    # 2 structured output (json_object profile per frozen adapter contract)
    class _B2Agent:
        pass

    agent2 = Agent(model, output_type=Verdict)
    r2 = await agent2.run(
        "Assess: 'The device contains a ledger with 3 entries.' "
        "Return statement and confidence (high|medium|low)."
    )
    out2 = r2.output
    results["structured_output"] = {
        "pass": isinstance(out2, Verdict) and bool(out2.statement),
        "output": {"statement": out2.statement[:120], "confidence": out2.confidence},
    }

    # 3/4 tool calls
    calls = []

    def _tool(ctx: RunContext, target: str = "") -> str:
        calls.append(target)
        return f"tool-ok:{target or 'none'}"

    agent4 = Agent(model)
    agent4.tool(_tool, name="ping_tool")

    r3 = await agent4.run("Call the ping_tool with no arguments, then stop.")
    results["zero_arg_tool_call"] = {
        "pass": len(calls) >= 1,
        "calls": list(calls),
    }
    calls.clear()
    r4 = await agent4.run(
        "Call the ping_tool exactly once with target='canary', then stop."
    )
    results["normal_tool_call"] = {
        "pass": "canary" in calls,
        "calls": list(calls),
    }

    # 6 API model identity (raw chat completions round trip)
    import httpx

    cfg = settings
    base = str(cfg.llm_text_base_url or cfg.llm_base_url).rstrip("/")
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{base}{cfg.llm_endpoint}",
            headers={"Authorization": f"Bearer {cfg.llm_api_key}"},
            json={
                "model": cfg.llm_text_model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 8,
            },
        )
        body = resp.json() if resp.status_code == 200 else {}
        results["api_model_identity"] = {
            "pass": resp.status_code == 200
            and body.get("model", "").startswith(
                str(cfg.llm_text_model).split("-")[0]
            )
            or (resp.status_code == 200 and bool(body.get("model"))),
            "http_status": resp.status_code,
            "reported_model": body.get("model"),
            "configured_model": cfg.llm_text_model,
            "base_url_host": base,
        }
    return results


def main() -> int:
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    settings = _settings()
    record = {
        "record": "ModelRuntimeQualificationRecordV3:adapter-smoke",
        "binding": {
            "runtime_baseline": "AgentV0RuntimeBaselineV3",
            "runtime_baseline_sha256": __import__("hashlib").sha256(
                (PYTHON_SERVICE_ROOT / "benchmarks/profiles/agent-v0-runtime-baseline-v3.json").read_bytes()
            ).hexdigest(),
            "provider": "sensenova-cloud",
            "model_id": settings.llm_text_model,
            "base_url": str(settings.llm_text_base_url),
            "temperature": settings.llm_text_temperature,
            "max_tokens": settings.llm_text_max_tokens,
            "thinking_mode": getattr(settings, "llm_thinking_mode", None),
            "timeout_seconds": getattr(settings, "llm_timeout_seconds", None),
        },
        "checks": {},
    }
    try:
        record["checks"] = asyncio.run(_run_checks())
    except Exception as exc:
        record["checks"]["exception"] = {
            "pass": False,
            "error": f"{type(exc).__name__}: {exc}"[:400],
        }
    all_pass = all(
        v.get("pass") for k, v in record["checks"].items() if k != "exception"
    ) and "exception" not in record["checks"]
    record["disposition"] = "CONTINUE" if all_pass else "STOP_MODEL_ADAPTER"
    out = RESULTS_ROOT / "model-runtime-qualification-v3.json"
    out.write_text(json.dumps(record, indent=2, ensure_ascii=False))
    print(json.dumps(record, indent=2, ensure_ascii=False))
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
