#!/usr/bin/env python3
"""P8B Model Qualification — §5 ModelQualificationConfigV1 authoring.

Emits one frozen qualification config artifact per candidate model under
benchmarks/results/agent-v0/model-qualification/configs/.  The ONLY
experiment axis is provider/model identity plus the provider-required
compatibility encoding (§3/§4); every other field is pinned to the frozen
production configuration (runtime commit 946f325e, corpus v5).

Compatibility evidence was gathered 2026-09-28 against the live endpoint:

  DeepSeek-V4-Flash : normal chat / json_object / reasoning_effort=none all
                      HTTP 200; API reports "self-dploy/DeepSeek-V4-Flash".
  glm-5.3           : 5 requests (60s x3, 180s, 300s non-stream, 302s
                      stream) all timed out with zero bytes; provider
                      deployment non-responsive.  Classified PROVIDER/INFRA
                      per §12 — NOT a model capability verdict.
  kimi-k3           : HTTP 400 "field Temperature invalid, only 1 is
                      allowed for this model" at temperature!=1; with the
                      provider-forced temperature=1 the model responds
                      (API reports "k3").  temperature=1 is therefore
                      PROVIDER-REQUIRED compatibility encoding (§3), not a
                      tuned parameter.

The API key never enters these artifacts.

Usage (from python_service/):
    .venv/bin/python scripts/author_model_qual_configs.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PYTHON_SERVICE_ROOT = SCRIPT_PATH.parents[1]
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

REPO_ROOT = PYTHON_SERVICE_ROOT.parent
OUT_DIR = (
    PYTHON_SERVICE_ROOT
    / "benchmarks"
    / "results"
    / "agent-v0"
    / "model-qualification"
    / "configs"
)

RUNTIME_COMMIT = "946f325eeb6add1072466aed96e5e2e7e38748ed"
BASELINE_PROFILE_HASH = (
    "6dd38a0e0f68704fb881e7e1f78031d58dc54368b6188826a3262660d86b218c"
)
CREATED_AT = "2026-09-28T00:00:00+00:00"

DEEPSEEK_PROBES = [
    {"probe": "normal_chat", "http": 200, "latency_s": 3.2,
     "reported_model": "self-dploy/DeepSeek-V4-Flash", "json_ok": True},
    {"probe": "json_object", "http": 200, "latency_s": 1.2,
     "reported_model": "self-dploy/DeepSeek-V4-Flash", "json_ok": True},
    {"probe": "reasoning_effort_none", "http": 200, "latency_s": 1.2,
     "reported_model": "self-dploy/DeepSeek-V4-Flash", "json_ok": True},
]
GLM_PROBES = [
    {"probe": "normal_chat_60s", "http": None,
     "error": "TimeoutError: read timed out"},
    {"probe": "json_object_60s", "http": None,
     "error": "TimeoutError: read timed out"},
    {"probe": "reasoning_effort_none_60s", "http": None,
     "error": "TimeoutError: read timed out"},
    {"probe": "normal_chat_180s", "http": None,
     "error": "TimeoutError: read timed out"},
    {"probe": "glm_thinking_disabled_300s", "http": None,
     "error": "TimeoutError: read timed out"},
    {"probe": "stream_302s", "http": None, "first_chunk_s": None,
     "error": "connection closed after 302.5s with zero chunks"},
]
KIMI_PROBES = [
    {"probe": "normal_chat_temp0.7", "http": 400,
     "error": "field Temperature invalid, only 1 is allowed for this model"},
    {"probe": "temp1_normal_chat", "http": 200, "latency_s": 4.7,
     "reported_model": "k3", "json_ok": True},
]


def _adapter_config_hash(effective: dict) -> str:
    canonical = json.dumps(effective, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _frozen_env_settings():
    from httpserver.config import Settings

    return Settings(_env_file=str(REPO_ROOT / ".env"))


def _effective_adapter(settings, overrides: dict) -> dict:
    """The adapter view a run with these overrides would produce (the
    derivation mirrors agent_model_adapter.resolve_adapter_config)."""
    thinking_mode = overrides.get("llm_thinking_mode", "")
    return {
        "base_url": "https://api.hcnsec.cn/v1",
        "model_name": overrides["llm_text_model"],
        "reasoning_effort": "none" if thinking_mode == "disabled" else None,
        "timeout_seconds": settings.llm_timeout_seconds,
        "temperature": overrides.get(
            "llm_text_temperature", settings.llm_text_temperature
        ),
        "max_tokens": settings.llm_text_max_tokens,
    }


def main() -> int:
    settings = _frozen_env_settings()
    corpus = json.loads(
        (
            PYTHON_SERVICE_ROOT
            / "benchmarks/corpus/corpus-agent-v0-calibration.v1.json"
        ).read_text(encoding="utf-8")
    )
    common = {
        "config_schema": "ModelQualificationConfigV1",
        "provider": "hcnsec-cloud",
        "endpoint_base_url": "https://api.hcnsec.cn",
        "runtime_commit": RUNTIME_COMMIT,
        "pre_calibration_profile_hash": BASELINE_PROFILE_HASH,
        "corpus_id": corpus["corpus_id"],
        "corpus_hash": corpus["input_hash"],
        "frozen_from_env": {
            "max_tokens": settings.llm_text_max_tokens,
            "timeout_seconds": settings.llm_timeout_seconds,
            "context_window_tokens": settings.llm_context_length,
            "tool_registry": "frozen production read-only registry",
            "prompts_policies": "frozen production modules (runtime "
            "commit binding above)",
        },
        "created_at": CREATED_AT,
    }

    candidates = [
        {
            **common,
            "candidate_id": "mimo-v2.6-flash-reference",
            "role": "reference",
            "requested_model_id": "MiMo-V2.6-Flash",
            "api_reported_model_id": "MiMo-V2.6-Flash",
            "overrides": {
                "llm_text_model": "MiMo-V2.6-Flash",
                "llm_text_temperature": settings.llm_text_temperature,
                "llm_thinking_mode": settings.llm_thinking_mode,
            },
            "compatibility_encoding": {
                "reasoning_effort": "none",
                "source": "LLM_THINKING_MODE=disabled (frozen deployment "
                "config; MiMo rejects the DeepSeek-style thinking body "
                "field — measured during the canary round)",
            },
            "compatibility_probes": [
                {"probe": "frozen_baseline_24_runs", "http": 200,
                 "note": "B2/B3/B3.5 measured baseline reused as "
                 "qualification reference; no rerun (§7)"},
            ],
        },
        {
            **common,
            "candidate_id": "deepseek-v4-flash",
            "role": "q1_candidate",
            "requested_model_id": "DeepSeek-V4-Flash",
            "api_reported_model_id": "self-dploy/DeepSeek-V4-Flash",
            "overrides": {
                "llm_text_model": "DeepSeek-V4-Flash",
                "llm_text_temperature": settings.llm_text_temperature,
                # "" -> adapter sends NO reasoning field: §4 normal chat
                # configuration (provider accepts and ignores explicit
                # "none", we do not send it).
                "llm_thinking_mode": "",
            },
            "compatibility_encoding": {
                "reasoning_effort": None,
                "source": "provider default (normal chat configuration, §4)",
            },
            "compatibility_probes": DEEPSEEK_PROBES,
        },
        {
            **common,
            "candidate_id": "glm-5.3",
            "role": "q1_candidate",
            "requested_model_id": "glm-5.3",
            "api_reported_model_id": None,
            "overrides": {
                "llm_text_model": "glm-5.3",
                "llm_text_temperature": settings.llm_text_temperature,
                "llm_thinking_mode": "",
            },
            "compatibility_encoding": {
                "reasoning_effort": None,
                "source": "provider default (normal chat configuration, §4); "
                "GLM thinking-disabled body encoding also tried and "
                "equally unresponsive",
            },
            "availability_note": "endpoint deployment non-responsive: 6 "
            "probe requests (incl. stream) produced zero bytes within "
            "60-302s.  PROVIDER/INFRA classification per §12; one real "
            "production-path Q1 run retained as run-level evidence, "
            "remaining cases recorded not_run(upstream_unavailable).",
            "compatibility_probes": GLM_PROBES,
        },
        {
            **common,
            "candidate_id": "kimi-k3",
            "role": "q1_candidate",
            "requested_model_id": "kimi-k3",
            "api_reported_model_id": "k3",
            "overrides": {
                "llm_text_model": "kimi-k3",
                # Provider rejects every value except 1 (HTTP 400).
                "llm_text_temperature": 1,
                "llm_thinking_mode": "",
            },
            "compatibility_encoding": {
                "temperature": 1,
                "reasoning_effort": None,
                "source": "PROVIDER-REQUIRED compatibility encoding (§3): "
                "endpoint 400s on temperature!=1 for kimi-k3.  Not a "
                "tuned parameter.",
            },
            "compatibility_probes": KIMI_PROBES,
        },
    ]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for cand in candidates:
        effective = _effective_adapter(settings, cand["overrides"])
        cand["effective_adapter_config"] = effective
        cand["adapter_config_hash"] = _adapter_config_hash(effective)
        out = OUT_DIR / f"{cand['candidate_id']}.config.json"
        out.write_text(
            json.dumps(cand, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"wrote {out.relative_to(PYTHON_SERVICE_ROOT)}  "
              f"adapter_hash={cand['adapter_config_hash'][:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
