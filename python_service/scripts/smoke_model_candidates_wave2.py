"""Wave-2 candidate admission smoke (model candidate wave 2, §6-§7).

Runs the SIX §6 checks per candidate — basic completion, structured
output, tool call without args, tool call with args, usage accounting,
model identity — against the SAME endpoint/config, changing ONLY the
candidate's frozen provider/model configuration (§5: config frozen in
model-candidates/wave2/<cid>.model-config.json BEFORE qualification).
Every failure is classified per the §7 provider taxonomy so a quota /
auth / availability block is never recorded as a semantic rejection.
Zero benchmark cases; a few live provider calls per candidate.

Usage (from python_service/):
    .venv/bin/python scripts/smoke_model_candidates_wave2.py
"""

from __future__ import annotations

import json
import re
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

REPO_ROOT = PYTHON_SERVICE_ROOT.parent
RESULTS = (
    PYTHON_SERVICE_ROOT
    / "benchmarks" / "results" / "agent-v0" / "model-candidates" / "wave2"
)


class Verdict(BaseModel):
    statement: str
    confidence: str


class _OverrideSettings:
    """Same experiment-axis restriction as the benchmark harness view:
    only provider/model identity + provider-required compatibility
    encoding (temperature / thinking fields) may differ."""

    def __init__(self, inner, overrides: dict):
        self._inner = inner
        self._overrides = overrides

    def __getattr__(self, name):
        if name in self._overrides:
            return self._overrides[name]
        return getattr(self._inner, name)


def classify_failure(exc: Exception) -> str:
    """§7 provider failure taxonomy — quota/auth/availability/infra are
    measurement-condition blocks, never MODEL_CAPABILITY_FAILURE."""
    text = f"{type(exc).__name__}: {exc}"
    m = re.search(r"status_code:\s*(\d+)", text)
    code = int(m.group(1)) if m else None
    if code == 429 or "rate_limit" in text or "rpm exhausted" in text.lower():
        return "PROVIDER_QUOTA_BLOCKED"
    if code == 403 or "permission_denied" in text or "token plan" in text:
        return "PROVIDER_AUTH_BLOCKED"
    if code == 404 or "model is not found" in text:
        return "PROVIDER_MODEL_UNAVAILABLE"
    if code == 400:
        # provider-side request constraints (e.g. mandated temperature) are
        # endpoint infrastructure constraints on the candidate config
        return "PROVIDER_INFRA_FAILURE"
    if "timeout" in text.lower() or "connect" in text.lower():
        return "PROVIDER_INFRA_FAILURE"
    return "MODEL_CAPABILITY_FAILURE"


def await_(coro):
    import asyncio

    return asyncio.run(coro)


RETRYABLE = ("429", "rate_limit", "rpm exhausted", "tpm", "timeout")


def call_with_retry(thunk, *, attempts: int = 4, backoff_s: int = 60):
    """Retry a provider call on §7 quota/infra transients. The LAST
    exception propagates for classification; retry evidence is recorded
    by the caller via attempt_count."""
    import asyncio

    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return asyncio.run(thunk()), attempt
        except Exception as exc:
            last = exc
            text = f"{type(exc).__name__}: {exc}".lower()
            if attempt < attempts and any(k in text for k in RETRYABLE):
                print(f"      429/quota transient (attempt {attempt}), "
                      f"backing off {backoff_s}s ...", flush=True)
                time.sleep(backoff_s)
    assert last is not None
    raise last


def load_config(candidate_id: str) -> dict | None:
    path = RESULTS / f"{candidate_id}.model-config.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def smoke(candidate_id: str) -> dict:
    config = load_config(candidate_id)
    overrides = config["overrides"] if config else {"llm_text_model": candidate_id}
    settings = Settings(_env_file=str(REPO_ROOT / ".env"))
    settings = _OverrideSettings(settings, overrides)
    model = build_chat_model(settings)

    record = {
        "candidate_id": candidate_id,
        "frozen_config": config["overrides"] if config else overrides,
        "config_frozen_before_qualification": config is not None,
        "checks": {},
    }
    checks = record["checks"]
    model_name_resp = None
    try:
        agent = Agent(model)
        t0 = time.monotonic()
        r, n_basic = call_with_retry(
            lambda: agent.run("Reply with exactly the word: QUALIFIED")
        )
        record["retry_attempts_basic_completion"] = n_basic
        model_name_resp = getattr(r.response, "model_name", None)
        text = r.output if isinstance(r.output, str) else str(r.output)
        checks["basic_completion"] = {
            "pass": "QUALIFIED" in text,
            "latency_s": round(time.monotonic() - t0, 1),
        }
        checks["model_identity"] = {
            "pass": bool(model_name_resp),
            "provider_reported_model": model_name_resp,
            "requested_model": overrides.get("llm_text_model"),
        }
        usage = r.usage
        checks["usage_accounting"] = {
            "pass": usage is not None and getattr(usage, "requests", 0) >= 1,
            "usage": str(usage)[:120],
        }

        agent2 = Agent(model, output_type=Verdict)

        def _structured():
            return agent2.run(
                "Assess: 'log shows a scheduled nightly job copied files.' "
                "Return statement + confidence (high|medium|low)."
            )

        r2, n_struct = call_with_retry(_structured)
        record["retry_attempts_structured_output"] = n_struct
        checks["structured_output"] = {
            "pass": isinstance(r2.output, Verdict) and bool(r2.output.statement),
            "confidence": getattr(r2.output, "confidence", None),
        }

        calls: list[str] = []

        def _tool(ctx: RunContext, target: str = "") -> str:
            calls.append(target)
            return f"tool-ok:{target or 'none'}"

        agent4 = Agent(model)
        agent4.tool(_tool, name="ping_tool")
        r3, n_t0 = call_with_retry(
            lambda: agent4.run("Call ping_tool with no arguments, then stop.")
        )
        record["retry_attempts_tool_call_no_args"] = n_t0
        checks["tool_call_no_args"] = {
            "pass": len(calls) >= 1,
            "calls": list(calls),
        }
        no_args_ok = len(calls) >= 1
        model_name_resp = getattr(r3.response, "model_name", None) or model_name_resp
        calls.clear()
        _, n_t1 = call_with_retry(
            lambda: agent4.run(
                "Call ping_tool exactly once with target='canary', then stop."
            )
        )
        record["retry_attempts_tool_call_with_args"] = n_t1
        checks["tool_call_with_args"] = {
            "pass": "canary" in calls,
            "calls": list(calls),
        }
    except Exception as exc:
        record["exception"] = {
            "pass": False,
            "error": f"{type(exc).__name__}: {exc}"[:250],
            "classification": classify_failure(exc),
        }
    record["all_pass"] = (
        "exception" not in record
        and all(v.get("pass") for v in checks.values())
    )
    return record


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    candidates = [
        "kimi-k3",
        "deepseek-v4-flash",
        "deepseek-v4-pro",
        "deepseek-flash",
        "sensenova-u1-fast",
        "sensenova-u1.5-lite",
        "deepseek-v4.1-flash",
    ]
    report = {
        "artifact_version": "CandidateAdapterSmokeV2",
        "wave": 2,
        "spec": "§6 six admission checks + §7 provider failure classification",
        "candidates": {},
    }
    for name in candidates:
        print(f"[smoke] {name} ...", flush=True)
        rec = smoke(name)
        report["candidates"][name] = rec
        status = "PASS" if rec["all_pass"] else (
            f"FAIL({rec.get('exception', {}).get('classification', 'checks')})"
        )
        print(f"   -> {status}", flush=True)
        time.sleep(20)  # inter-candidate cooldown: account-level TPM/RPM
    out = RESULTS / "candidate-adapter-smoke.json"
    out.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    passing = [n for n, c in report["candidates"].items() if c["all_pass"]]
    print("passing:", passing)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
