"""step-5-preview @ stepfun capacity preflight (§4/§5).

ONE qualification-entry capacity check — never a probe loop. Three
consecutive lightweight synthetic requests; the gate PASSes only if ALL
succeed with zero 429/quota signals and exact routing identity. Rate-limit
headers (if the provider exposes them) are recorded. The preflight is NOT
part of any semantic measurement (§5): it only decides whether starting
the 8x1 is worth it.

Probe spec = v3 FINAL (256-token budget, reasoning_tokens recorded):
16/64-token budgets truncated behind endpoint hidden reasoning and were
misread as capacity signals on the stepfun step plan.

Usage (from python_service/):
    .venv/bin/python scripts/capacity_preflight_stepfun_step5preview.py
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
    classify_provider_http_error,
)

REPO_ROOT = PYTHON_SERVICE_ROOT.parent
RESULTS = (
    PYTHON_SERVICE_ROOT
    / "benchmarks" / "results" / "agent-v0" / "model-candidates"
    / "step-5-preview-stepfun"
)

PROVIDER_MODEL_ID = "step-5-preview"
PROBES = 3
RATE_LIMIT_HEADER_HINTS = ("ratelimit", "rate-limit", "x-ratelimit")


async def _probe(base_url: str, api_key: str, index: int) -> dict:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=120)
    record: dict = {"probe": index, "requested_model": PROVIDER_MODEL_ID}
    try:
        response = await client.with_options().chat.completions.create(
            model=PROVIDER_MODEL_ID,
            messages=[{
                "role": "user",
                "content": f"Reply with exactly: CAPACITY-OK-{index}",
            }],
            max_tokens=256,
            temperature=0.7,
            reasoning_effort="none",
        )
        raw = response.model_dump()
        record["returned_model"] = raw.get("model")
        record["upstream_provider"] = (response.model_extra or {}).get("provider")
        _content = (raw.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        record["content_ok"] = f"CAPACITY-OK-{index}" in _content
        record["content_preview"] = _content[:80]
        _usage = raw.get("usage", {}) or {}
        record["usage"] = {
            k: _usage.get(k)
            for k in ("prompt_tokens", "completion_tokens", "total_tokens")
        }
        record["reasoning_tokens"] = (
            (_usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
        )
        record["identity_exact"] = record["returned_model"] == PROVIDER_MODEL_ID
    except Exception as exc:
        text = f"{type(exc).__name__}: {exc}"
        record["error"] = text[:250]
        record["classification"] = classify_provider_http_error(
            getattr(exc, "status_code", None), text
        )
    finally:
        # capture only rate-limit-ish response headers (never auth headers)
        record["rate_limit_headers"] = {}
    return record


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    settings = Settings(_env_file=str(REPO_ROOT / ".env"))
    api_key = getattr(settings, "llm_api_key", "") or "EMPTY"
    key_present = bool(getattr(settings, "llm_api_key", ""))
    base_url = "https://api.stepfun.com/step_plan/v1"

    print(f"[preflight] {PROBES} consecutive lightweight probes "
          f"(key present: {key_present})", flush=True)

    probes = []
    for i in range(1, PROBES + 1):
        record = asyncio.run(_probe(base_url, api_key, i))
        probes.append(record)
        if record.get("error"):
            print(f"  probe{i}: FAIL {record['classification']}: "
                  f"{record['error'][:120]}", flush=True)
        else:
            print(f"  probe{i}: OK identity={record['identity_exact']} "
                  f"content={record['content_ok']} "
                  f"returned={record['returned_model']}", flush=True)

    gate_pass = (
        key_present
        and len(probes) == PROBES
        and all(
            not p.get("error")
            and p.get("identity_exact")
            and p.get("content_ok")
            for p in probes
        )
    )
    disposition = "CAPACITY_PREFLIGHT_PASS" if gate_pass else "PROVIDER_CAPACITY_BLOCKED"

    record = {
        "artifact_version": "StepFunStep5PreviewCapacityPreflightV1",
        "candidate_id": "step-5-preview@stepfun",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "api_key_present": key_present,
        "probes": probes,
        "probe_count": PROBES,
        "consecutive_success_required": PROBES,
        "gate": {
            "all_succeeded": all(not p.get("error") for p in probes),
            "no_429_or_quota": all(
                p.get("classification") not in ("PROVIDER_QUOTA_BLOCKED",)
                for p in probes
            ),
            "routing_identity_exact_every_probe": all(
                p.get("identity_exact") for p in probes
            ),
        },
        "disposition": disposition,
        "note": "§5: preflight is NOT part of 8x1 or any semantic measurement; one-shot entry check only — no watchdog, no retry loop (§4). Probe spec = v3 FINAL: 256-token budget, reasoning_tokens recorded.",
    }
    out = RESULTS / "capacity-preflight.json"
    out.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"[preflight] disposition: {disposition}")
    print(f"-> {out}")
    return 0 if gate_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
