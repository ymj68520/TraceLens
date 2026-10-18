"""Multi-candidate adapter smoke (post-Gen4 model track, §10-§11).

Runs the six frozen §5 checks against each candidate model id on the
SAME endpoint/config, changing ONLY the model identity. Zero benchmark
cases; a few live provider calls per candidate.
"""

from __future__ import annotations

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
)
from pydantic import BaseModel  # noqa: E402
from pydantic_ai import Agent, RunContext  # noqa: E402

RESULTS = (
    PYTHON_SERVICE_ROOT
    / "benchmarks" / "results" / "agent-v0" / "model-candidates"
)

CANDIDATES = [
    "deepseek-v4.1-flash",
    "deepseek-v4-pro",
    "deepseek-v4-flash",
    "kimi-k3",
    "glm-5.2",
    "sensenova-u1.5-lite",
    "sensenova-u1-fast",
]


class Verdict(BaseModel):
    statement: str
    confidence: str


def smoke(model_name: str) -> dict:
    settings = Settings(_env_file=str(PYTHON_SERVICE_ROOT.parent / ".env"))
    model = build_chat_model(settings, model_name=model_name)
    checks = {}
    try:
        agent = Agent(model)
        t0 = time.monotonic()
        r = await_(agent.run("Reply with exactly the word: QUALIFIED"))
        text = r.output if isinstance(r.output, str) else str(r.output)
        checks["basic_completion"] = {
            "pass": "QUALIFIED" in text,
            "latency_s": round(time.monotonic() - t0, 1),
        }
        usage = r.usage
        checks["usage_metadata"] = {
            "pass": usage is not None,
            "usage": str(usage)[:120],
        }

        agent2 = Agent(model, output_type=Verdict)
        r2 = await_(agent2.run(
            "Assess: 'log shows a scheduled nightly job copied files.' "
            "Return statement + confidence (high|medium|low)."
        ))
        checks["structured_output"] = {
            "pass": isinstance(r2.output, Verdict) and bool(r2.output.statement),
            "confidence": getattr(r2.output, "confidence", None),
        }

        calls = []

        def _tool(ctx: RunContext, target: str = "") -> str:
            calls.append(target)
            return f"tool-ok:{target or 'none'}"

        agent4 = Agent(model)
        agent4.tool(_tool, name="ping_tool")
        await_(agent4.run("Call ping_tool with no arguments, then stop."))
        zero_ok = len(calls) >= 1
        calls.clear()
        await_(agent4.run(
            "Call ping_tool exactly once with target='canary', then stop."
        ))
        checks["tool_calls"] = {
            "pass": zero_ok and "canary" in calls,
            "calls": list(calls),
        }
    except Exception as exc:
        checks["exception"] = {
            "pass": False,
            "error": f"{type(exc).__name__}: {exc}"[:250],
        }
    checks["all_pass"] = all(
        v.get("pass") for k, v in checks.items() if k != "exception"
    ) and "exception" not in checks
    return checks


def await_(coro):
    import asyncio

    return asyncio.run(coro)


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    report = {"artifact_version": "CandidateAdapterSmokeV1", "candidates": {}}
    for name in CANDIDATES:
        print(f"[smoke] {name} ...", flush=True)
        report["candidates"][name] = smoke(name)
        print(f"   -> {'PASS' if report['candidates'][name]['all_pass'] else 'FAIL'} "
              f"{json.dumps(report['candidates'][name], ensure_ascii=False)[:160]}")
    out = RESULTS / "candidate-adapter-smoke.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    passing = [n for n, c in report["candidates"].items() if c["all_pass"]]
    print("passing:", passing)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
