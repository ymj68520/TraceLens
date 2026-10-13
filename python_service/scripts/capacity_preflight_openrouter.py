"""Space Bunny Alpha / OpenRouter capacity preflight (§4/§5).

ONE qualification-entry capacity check — never a probe loop. Three
consecutive lightweight synthetic requests; the gate PASSes only if ALL
succeed with zero 429/quota signals and exact routing identity. Rate-limit
headers (if the provider exposes them) are recorded. The preflight is NOT
part of any semantic measurement (§5): it only decides whether starting
the 8x1 is worth it.

Usage (from python_service/):
    .venv/bin/python scripts/capacity_preflight_openrouter.py
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
    / "space-bunny-alpha-openrouter"
)

PROVIDER_MODEL_ID = "stealth/space-bunny-alpha"
PROBES = 3
RATE_LIMIT_HEADER_HINTS = ("ratelimit", "rate-limit", "x-ratelimit")


async def _probe(base_url: str, api_key: str, index: int, max_tokens: int) -> dict:
    import httpx
    from openai import AsyncOpenAI

    record: dict = {"probe": index, "requested_model": PROVIDER_MODEL_ID}
    # §4: capture only rate-limit-ish response headers (never auth headers)
    # via an httpx response hook — the openai SDK does not retain headers.
    response_headers: dict = {}

    def _capture(response: httpx.Response) -> None:
        for name, value in response.headers.items():
            if any(hint in name.lower() for hint in RATE_LIMIT_HEADER_HINTS):
                response_headers[name] = value

    http = httpx.AsyncClient(
        timeout=120, event_hooks={"response": [_capture]}
    )
    client = AsyncOpenAI(
        base_url=base_url, api_key=api_key, timeout=120, http_client=http
    )
    try:
        response = await client.with_options().chat.completions.create(
            model=PROVIDER_MODEL_ID,
            messages=[{
                "role": "user",
                "content": f"Reply with exactly: CAPACITY-OK-{index}",
            }],
            max_tokens=max_tokens,
            temperature=0.7,
        )
        raw = response.model_dump()
        record["returned_model"] = raw.get("model")
        record["upstream_provider"] = (response.model_extra or {}).get("provider")
        record["content_ok"] = f"CAPACITY-OK-{index}" in (
            (raw.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        )
        record["usage"] = {
            k: raw.get("usage", {}).get(k)
            for k in ("prompt_tokens", "completion_tokens", "total_tokens")
        }
        record["identity_exact"] = record["returned_model"] == PROVIDER_MODEL_ID
    except Exception as exc:
        text = f"{type(exc).__name__}: {exc}"
        record["error"] = text[:250]
        record["classification"] = classify_provider_http_error(
            getattr(exc, "status_code", None), text
        )
    finally:
        record["rate_limit_headers"] = response_headers
        await http.aclose()
    return record


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="capacity_preflight_openrouter")
    parser.add_argument(
        "--out", default=str(RESULTS / "capacity-preflight.json"),
        help="artifact path (default: candidate dir capacity-preflight.json)",
    )
    parser.add_argument(
        "--probe-max-tokens", type=int, default=16,
        help="per-probe completion budget (lightweight synthetic requests)",
    )
    args = parser.parse_args()

    RESULTS.mkdir(parents=True, exist_ok=True)
    settings = Settings(_env_file=str(REPO_ROOT / ".env"))
    api_key = getattr(settings, "openrouter_api_key", "") or "EMPTY"
    key_present = bool(getattr(settings, "openrouter_api_key", ""))
    base_url = "https://openrouter.ai/api/v1"

    print(f"[preflight] {PROBES} consecutive lightweight probes "
          f"(key present: {key_present}, max_tokens={args.probe_max_tokens})",
          flush=True)

    probes = []
    for i in range(1, PROBES + 1):
        record = asyncio.run(
            _probe(base_url, api_key, i, args.probe_max_tokens)
        )
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
        "artifact_version": "OpenRouterCapacityPreflightV1",
        "candidate_id": "space-bunny-alpha@openrouter",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "api_key_present": key_present,
        "probe_spec": {
            "probe_count": PROBES,
            "max_tokens_per_probe": args.probe_max_tokens,
            "note": "lightweight synthetic echo requests; budget sized to "
                    "absorb endpoint-side hidden reasoning so truncation is "
                    "never misread as a capacity signal (§4/§5)",
        },
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
        "note": "§5: preflight is NOT part of 8x1 or any semantic measurement; one-shot entry check only — no watchdog, no retry loop (§4)",
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"[preflight] disposition: {disposition}")
    print(f"-> {out}")
    return 0 if gate_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
