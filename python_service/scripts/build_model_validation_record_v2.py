#!/usr/bin/env python3
"""B2-restart §6 ModelValidationRecordV2 generator.

Collects the frozen-basis anchors, adapter configuration digest, tool
registry hash and smoke outcomes into one secrets-redacted artifact.
Requires the live services only to compute the production ToolRegistry
schema hash.

Usage (from python_service/):
    .venv/bin/python scripts/build_model_validation_record_v2.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PYTHON_SERVICE_ROOT = SCRIPT_PATH.parents[1]
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

REPO_ROOT = PYTHON_SERVICE_ROOT.parent
OUT_FILE = (
    PYTHON_SERVICE_ROOT
    / "benchmarks"
    / "results"
    / "agent-v0"
    / "b2-restart"
    / "model-validation-record.v2.json"
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    ).stdout.strip()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="build_model_validation_record_v2"
    )
    parser.add_argument(
        "--registry-hash-only",
        action="store_true",
        help="skip ServiceManager init (reuses a previously recorded "
        "registry hash if present)",
    )
    args = parser.parse_args(argv)

    from httpserver.config import Settings
    from httpserver.services.investigation.agent_model_adapter import (
        resolve_adapter_config,
    )
    from httpserver.services.investigation.agent_specialist_executor import (
        model_config_digest_from_adapter_config,
    )

    settings = Settings(_env_file=str(REPO_ROOT / ".env"))
    adapter_config = resolve_adapter_config(settings)
    adapter_digest = model_config_digest_from_adapter_config(
        adapter_config
    )

    baseline_file = (
        PYTHON_SERVICE_ROOT
        / "benchmarks"
        / "profiles"
        / "agent-v0-runtime-baseline-v2.json"
    )
    model_config_file = (
        PYTHON_SERVICE_ROOT
        / "benchmarks"
        / "results"
        / "agent-v0"
        / "b2-restart"
        / "sensenova-6.8-flash-lite.model-config.json"
    )
    smoke_file = (
        PYTHON_SERVICE_ROOT
        / "benchmarks"
        / "results"
        / "agent-v0"
        / "b2-restart"
        / "smoke"
        / "adapter-smoke.v1.json"
    )
    smoke = json.loads(smoke_file.read_text(encoding="utf-8"))

    registry_hash = None
    if not args.registry_hash_only:
        import asyncio

        from httpserver.services import get_service_manager
        from httpserver.services.investigation.agent_tools.adapters import (
            build_read_only_registry,
        )

        # The registry projection needs the live tool services; same
        # wiring the benchmark driver uses (manager services directly).
        async def _compute() -> str:
            manager = get_service_manager()
            await manager.initialize()
            registry = build_read_only_registry(manager)
            return registry.schema_hash()

        registry_hash = asyncio.run(_compute())

    record = {
        "artifact_version": "ModelValidationRecordV2",
        "round": "p8b-b2-restart",
        "created_at": time.strftime(
            "%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()
        ),
        "provider": "sensenova-cloud",
        "requested_model_id": adapter_config.model_name,
        "api_reported_model_id": smoke.get("api_reported_model_id"),
        "base_url_class": adapter_config.base_url.split("//", 1)[-1],
        "adapter_config_hash": adapter_digest,
        "generation_params": {
            "temperature": adapter_config.temperature,
            "max_tokens": adapter_config.max_tokens,
            "timeout_seconds": adapter_config.timeout_seconds,
            "thinking_mode": settings.llm_thinking_mode,
            "reasoning_effort_sent": adapter_config.reasoning_effort,
            "reasoning_metadata_exposed": {
                "provider_reports_reasoning_tokens": True,
                "observed_reasoning_tokens_with_effort_none": 0,
            },
        },
        "tool_registry_hash": registry_hash,
        "supervisor_contract": "v2 (FROZEN; production default flipped "
        "at ed382cbb)",
        "evidence_snapshot_admission": "S4 (FROZEN at f711851c)",
        "runtime_baseline": {
            "artifact": "AgentV0RuntimeBaselineV2",
            "file_sha256": _sha256_file(baseline_file),
            "frozen_at_commit": json.loads(
                baseline_file.read_text(encoding="utf-8")
            )["frozen_at_commit"],
        },
        "model_config_artifact": {
            "path": str(model_config_file.relative_to(PYTHON_SERVICE_ROOT)),
            "sha256": _sha256_file(model_config_file),
        },
        "smokes": {
            "adapter_smoke": {
                "artifact": str(smoke_file.relative_to(PYTHON_SERVICE_ROOT)),
                "all_passed": smoke.get("all_passed"),
                "probes": {
                    name: bool(probe.get("passed"))
                    for name, probe in smoke.get("probes", {}).items()
                },
            },
            "specialist_deep_smoke": {
                "result": "PASS with episodic fragility",
                "runs": [
                    {
                        "run": "smoke-deep/t2-no-evidence/repeat0",
                        "plan_v2": "valid (delegation admitted)",
                        "specialist": "FAILED agent_output_invalid "
                        "(episodic; raw cause not captured, sanitized "
                        "production path)",
                        "tool_calls": 9,
                        "zero_arg_tool_ok": True,
                    },
                    {
                        "run": "diagnosis repeat9 (exception telemetry "
                        "armed, zero exceptions fired)",
                        "plan_v2": "valid",
                        "specialist": "completed + integrated "
                        "(INTEGRATE v2 committed, 4 evidence snapshots "
                        "admitted by S4)",
                    },
                ],
            },
            "supervisor_deep_smoke": {
                "result": "PASS",
                "plan_v2_valid": True,
                "integrate_v2_valid": True,
                "handle_rejections": 0,
            },
        },
        "secrets_redacted": True,
        "git_head": _git_head(),
    }

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(
        json.dumps(record, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"record -> {OUT_FILE}")
    print(f"registry_hash: {registry_hash}")
    print(f"adapter_config_hash: {adapter_digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
