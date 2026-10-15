"""RCA-2A.7c: Authorized StepFun Vocabulary Guidance Controlled Comparison.

Executes a bounded live-model controlled comparison of StepFun step-3.7-flash
comparing Control (standard V2 instructions) vs Treatment (V2 instructions + experimental vocabulary guidance).
Strictly bounded: 4 pairs, 8 seats, max 16 generations, max 3 preflight requests.
No provider fallback. No model substitution. Zero production mutations.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

# Prevent httpx proxy confusion with socksio
os.environ["all_proxy"] = ""
os.environ["ALL_PROXY"] = ""

HERE = Path(__file__).resolve().parent
PYTHON_SERVICE_ROOT = HERE.parents[2]
REPO_ROOT = PYTHON_SERVICE_ROOT.parent

# Ensure python service and audit modules are importable
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))
scripts_dir = str(PYTHON_SERVICE_ROOT / "scripts")
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)
hardening_dir = str(PYTHON_SERVICE_ROOT / "benchmarks/audits/rca2a7b-runner-hardening")
if hardening_dir not in sys.path:
    sys.path.insert(0, hardening_dir)

from benchmark_output_guard import exclusive_output_file
from cross_arm_parity import (
    build_cloned_pair_fixtures,
    verify_pair_parity,
)
from diagnostic_sink_hardening import (
    DiagnosticDataQualityError,
    create_exclusive_diagnostic_sink,
    read_and_validate_sink_entries,
)
from runner import (
    ARM_NAMES,
    PAIRS,
    REQUEST_BUDGET,
    RecordingProxyModel,
    SeatExecutionContext,
    SeatPhase,
    build_seat_record,
    code_hashes,
    compute_paired_metrics,
    git_head,
    run_eight_seats,
    sha256_file,
    sha256_json,
)
from httpserver.config import Settings
from httpserver.services.investigation.agent_failure_diagnostics import schema_hash_of
from httpserver.services.investigation.agent_integration_v2 import (
    SupervisorIntegrationDecisionV2,
)
from httpserver.services.investigation.agent_model_adapter import (
    build_chat_model,
    classify_provider_http_error,
    derive_openai_base_url,
    resolve_adapter_config,
)
from benchmarks.contracts.experimental.integration_vocabulary_guidance_v1 import (
    GUIDANCE_TEXT,
    GuidanceIntegrationAgentFactory,
    guidance_sha256,
)
from httpserver.services.investigation.agent_supervisor import (
    SupervisorAgentFactory,
)

EXPERIMENT_ID = "rca2a7c-stepfun-vocabulary-comparison"
AUTHORIZED_BASELINE = "47bd3749e5bf6da0b6ebeecc39bb85fb87ccd3e0"
AUTHORIZED_RUNNER_HASH = "ce433704050b1ee0a560cfa6d1d10af1227857c1df39b701d922391dc5ba75c9"
AUTHORIZED_GUIDANCE_HASH = guidance_sha256()  # e00c1549284cd4c5b98a24e0a7c064377a4aabcaaa74d9d344412c6247af5f29
AUTHORIZED_SCHEMA_HASH = "a214ec4f5e81fcbb"

PROVIDER = "stepfun"
MODEL = "step-3.7-flash"

FROZEN_CONFIG = {
    "provider": PROVIDER,
    "requested_model": MODEL,
    "llm_text_base_url": "https://api.stepfun.com/step_plan",
    "llm_endpoint": "/v1/chat/completions",
    "llm_text_temperature": 0.7,
    "llm_text_max_tokens": 16384,
    "llm_thinking_mode": "disabled",
    "llm_timeout_seconds": 120,
    "sdk_retry_policy": "openai SDK client default (OpenAIProvider(base_url, api_key) unchanged construction)",
    "output_retry_budget": 1,
}


def write_exclusive(path: Path, data: dict) -> None:
    with exclusive_output_file(path) as f:
        f.write(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"[RCA-2A.7c] Wrote artifact: {path.name}")


def make_frozen_stepfun_settings(identity_sink=None):
    configured = Settings(_env_file=str(REPO_ROOT / ".env"))

    class FrozenStepFunSettings:
        llm_provider = PROVIDER
        llm_text_model = MODEL
        llm_text_base_url = FROZEN_CONFIG["llm_text_base_url"]
        llm_endpoint = FROZEN_CONFIG["llm_endpoint"]
        llm_text_temperature = FROZEN_CONFIG["llm_text_temperature"]
        llm_text_max_tokens = FROZEN_CONFIG["llm_text_max_tokens"]
        llm_thinking_mode = FROZEN_CONFIG["llm_thinking_mode"]
        llm_timeout_seconds = FROZEN_CONFIG["llm_timeout_seconds"]
        llm_api_key = configured.llm_api_key
        llm_model_identity_sink = identity_sink

    return FrozenStepFunSettings()


async def run_stepfun_preflight(settings, out_path: Path) -> dict[str, Any]:
    from openai import AsyncOpenAI

    config = resolve_adapter_config(settings)
    api_key = getattr(settings, "llm_api_key", "")
    client = AsyncOpenAI(base_url=config.base_url, api_key=api_key)

    attempts = []
    preflight_ok = True
    stop_reason = None

    print("[RCA-2A.7c] Initiating bounded StepFun preflight (3 logical requests)...")
    for i in range(1, 4):
        start = time.monotonic()
        try:
            resp = await client.chat.completions.create(
                model=config.model_name,
                messages=[{"role": "user", "content": "Ping"}],
                max_tokens=256,
            )
            elapsed = round((time.monotonic() - start) * 1000, 1)
            returned_model = getattr(resp, "model", None)
            model_match = returned_model == config.model_name
            attempts.append({
                "attempt": i,
                "status": "SUCCESS",
                "status_code": 200,
                "latency_ms": elapsed,
                "requested_model": config.model_name,
                "returned_model": returned_model,
                "model_identity_match": model_match,
            })
            print(f"  Preflight {i}/3: 200 OK | model={returned_model} | latency={elapsed}ms")
            if not model_match:
                preflight_ok = False
                stop_reason = "MODEL_IDENTITY_MISMATCH"
                break
        except Exception as exc:
            elapsed = round((time.monotonic() - start) * 1000, 1)
            status_code = getattr(exc, "status_code", None)
            classification = classify_provider_http_error(status_code, str(exc))
            attempts.append({
                "attempt": i,
                "status": "FAILED",
                "status_code": status_code,
                "error_class": type(exc).__name__,
                "error_message": str(exc),
                "classification": classification,
                "latency_ms": elapsed,
            })
            print(f"  Preflight {i}/3 FAILED: {classification} ({exc})")
            preflight_ok = False
            if classification == "PROVIDER_AUTH_BLOCKED":
                stop_reason = "PROVIDER_AUTH_BLOCKED"
            elif classification == "PROVIDER_QUOTA_BLOCKED":
                stop_reason = "PROVIDER_CAPACITY_BLOCKED"
            elif classification == "PROVIDER_TIMEOUT":
                stop_reason = "PROVIDER_TIMEOUT"
            else:
                stop_reason = "CONNECTIVITY_BLOCKED"
            break

    report = {
        "artifact_version": "RCA2A7cPreflightGateReportV1",
        "experiment_id": EXPERIMENT_ID,
        "preflight_verdict": "PREFLIGHT_PASS" if preflight_ok else "PREFLIGHT_FAIL",
        "stop_reason": stop_reason,
        "attempts_executed": len(attempts),
        "requested_model": MODEL,
        "endpoint": config.base_url,
        "attempts": attempts,
    }
    write_exclusive(out_path, report)
    return report


async def main():
    print("=" * 60)
    print(" TraceLens Agent v0 — RCA-2A.7c StepFun Controlled Comparison")
    print("=" * 60)

    # 1. Baseline & Hash Verification
    head = git_head()
    current_hashes = code_hashes()
    current_guidance_hash = guidance_sha256()
    current_schema_hash = schema_hash_of(SupervisorIntegrationDecisionV2)

    print(f"Git HEAD: {head}")
    print(f"Runner Hash: {current_hashes.get('runner')}")
    print(f"Guidance Hash: {current_guidance_hash}")
    print(f"Schema Hash: {current_schema_hash}")

    if head != AUTHORIZED_BASELINE:
        raise SystemExit(f"EXPERIMENT_IDENTITY_DRIFT: HEAD {head} != {AUTHORIZED_BASELINE}")
    if current_hashes.get("runner") != AUTHORIZED_RUNNER_HASH:
        raise SystemExit(f"EXPERIMENT_IDENTITY_DRIFT: Runner hash mismatch")
    if current_guidance_hash != AUTHORIZED_GUIDANCE_HASH:
        raise SystemExit("EXPERIMENT_IDENTITY_DRIFT: Guidance hash mismatch")
    if current_schema_hash != AUTHORIZED_SCHEMA_HASH:
        raise SystemExit("EXPERIMENT_IDENTITY_DRIFT: Schema hash mismatch")

    print("[RCA-2A.7c] Baseline verification PASSED. Identity is stable.")

    # 2. Setup Scratches & Parity Verification
    scratch_base = HERE / "scratch"
    scratch_base.mkdir(parents=True, exist_ok=True)
    claims_dir = HERE / "claims"
    claims_dir.mkdir(parents=True, exist_ok=True)
    diag_dir = HERE / "diagnostics"
    diag_dir.mkdir(parents=True, exist_ok=True)

    print("[RCA-2A.7c] Initializing cloned isolated scratch stores for 4 pairs...")
    pair_fixtures = []
    pair_parities = []

    for pair_id in range(1, 5):
        pair_dir = scratch_base / f"pair_{pair_id}"
        h_c, h_t, meta = await build_cloned_pair_fixtures(
            pair_id=pair_id,
            base_dir=pair_dir,
            with_evidence=False,
            runtime_identity={
                "baseline_commit": AUTHORIZED_BASELINE,
                "experiment_id": EXPERIMENT_ID,
                "harness": f"RCA-2A.7c-Pair-{pair_id:02d}",
                "specialist_result_kind": "SYNTHETIC_SPECIALIST_RESULT",
            },
        )
        parity = await verify_pair_parity(pair_id=pair_id, harness_control=h_c, harness_treatment=h_t)
        if not parity["parity_pass"]:
            raise SystemExit(f"CROSS_ARM_PARITY_BLOCKED: Pair {pair_id} parity check failed")

        pair_parities.append(parity)

        c_input = h_c.isolated_input()
        t_input = h_t.isolated_input()

        pair_fixtures.append({
            "pair_id": pair_id,
            "arm": "control",
            "fixture_path": str(meta["control_dir"]),
            "task_id": meta["task_id"],
            "investigation_id": meta["investigation_id"],
            "run_id": meta["run_id"],
            "working_state_hash": c_input["working_state_hash"],
            "context_hash": c_input["integration_context_hash"],
            "binding_table_hash": c_input["reference_binding_table_hash"],
        })
        pair_fixtures.append({
            "pair_id": pair_id,
            "arm": "treatment",
            "fixture_path": str(meta["treatment_dir"]),
            "task_id": meta["task_id"],
            "investigation_id": meta["investigation_id"],
            "run_id": meta["run_id"],
            "working_state_hash": t_input["working_state_hash"],
            "context_hash": t_input["integration_context_hash"],
            "binding_table_hash": t_input["reference_binding_table_hash"],
        })

    print(f"[RCA-2A.7c] Cloned scratch fixtures ready. 4/4 pairs verified PARITY_PASS.")

    # 3. Freeze RCA2A7cExperimentManifestV1 BEFORE any provider call
    manifest_path = HERE / "rca2a7c-experiment-manifest-v1.json"
    manifest = {
        "artifact_version": "RCA2A7cExperimentManifestV1",
        "experiment_id": EXPERIMENT_ID,
        "authorization_status": "LIVE_MODEL_EXECUTION_AUTHORIZED",
        "baseline_commit": AUTHORIZED_BASELINE,
        "runtime_source_hashes": current_hashes,
        "stepfun_configuration": FROZEN_CONFIG,
        "guidance_sha256": AUTHORIZED_GUIDANCE_HASH,
        "output_schema_hash": AUTHORIZED_SCHEMA_HASH,
        "request_budget": REQUEST_BUDGET,
        "execution_order": [list(p) for p in PAIRS],
        "fixture_arm_records": pair_fixtures,
        "parity_audit_summary": {
            "all_pairs_parity_pass": True,
            "canonical_hash_equality": True,
            "prompt_delta_exact_guidance": True,
        },
        "stop_conditions": [
            "provider_connectivity_or_capacity_failure",
            "model_identity_mismatch",
            "experiment_identity_drift",
            "diagnostic_sink_failure",
            "seat_claim_inconsistency",
            "unexpected_runner_exception",
            "fabricated_evidence_or_basis_handle",
        ],
        "frozen_timestamp": time.time(),
    }
    write_exclusive(manifest_path, manifest)
    print("[RCA-2A.7c] Experiment manifest FROZEN.")

    # 4. Preflight Check
    settings = make_frozen_stepfun_settings()
    preflight_report_path = HERE / "rca2a7c-preflight-gate-report-v1.json"
    preflight_report = await run_stepfun_preflight(settings, preflight_report_path)

    if preflight_report["preflight_verdict"] != "PREFLIGHT_PASS":
        print(f"[RCA-2A.7c] Preflight FAILED: {preflight_report['stop_reason']}. STOPPING.")
        return

    print("[RCA-2A.7c] Preflight PASSED. Starting paired execution...")

    # 5. Live Paired Execution (8 seats)
    def live_model_factory(ctx: SeatExecutionContext):
        seat_settings = make_frozen_stepfun_settings(identity_sink=ctx.identity_sink)
        return build_chat_model(seat_settings)

    matrix = await run_eight_seats(
        pair_fixtures,
        diag_dir,
        claims_dir=claims_dir,
        model_factory=live_model_factory,
    )

    paired_metrics = compute_paired_metrics(matrix)
    matrix["paired_metrics"] = paired_metrics
    matrix["artifact_version"] = "RCA2A7cPairedExecutionMatrixV1"
    matrix["experiment_id"] = EXPERIMENT_ID
    matrix["provider"] = PROVIDER
    matrix["model"] = MODEL
    matrix["real_model_requests"] = sum(s.get("logical_model_generations", 0) for s in matrix["seats"])
    matrix["observation_tag"] = "LIVE_STEPFUN_OBSERVATIONS"

    matrix_path = HERE / "rca2a7c-paired-execution-matrix-v1.json"
    write_exclusive(matrix_path, matrix)
    print(f"[RCA-2A.7c] Paired execution matrix recorded. Stop reason: {matrix['stop_reason']}")

    # 6. Vocabulary Effect Report
    seats = matrix["seats"]
    c_seats = [s for s in seats if s["arm"] == "control"]
    t_seats = [s for s in seats if s["arm"] == "treatment"]

    c_valid = sum(bool(s.get("stage_layers", {}).get("canonical_integration_valid")) for s in c_seats)
    t_valid = sum(bool(s.get("stage_layers", {}).get("canonical_integration_valid")) for s in t_seats)

    c_completed = sum(s.get("field_scan_totals", {}).get("to_status_completed", 0) for s in c_seats)
    t_completed = sum(s.get("field_scan_totals", {}).get("to_status_completed", 0) for s in t_seats)

    c_pydantic_pass = sum(bool(s.get("final_attempt_pydantic_pass")) for s in c_seats)
    t_pydantic_pass = sum(bool(s.get("final_attempt_pydantic_pass")) for s in t_seats)

    c_tokens = sum(s.get("token_usage", {}).get("output_tokens", 0) for s in c_seats)
    t_tokens = sum(s.get("token_usage", {}).get("output_tokens", 0) for s in t_seats)

    counts = paired_metrics["paired_counts"]

    # Final Interpretation Logic
    if matrix["stop_reason"] in ("PROVIDER_CAPACITY_OR_CONNECTIVITY_FAILURE", "MODEL_IDENTITY_MISMATCH", "EXPERIMENT_IDENTITY_DRIFT"):
        interpretation_decision = "EXPERIMENT_BLOCKED"
    elif counts["treatment_win"] > counts["control_win"] and t_valid > c_valid:
        interpretation_decision = "GUIDANCE_BENEFIT_OBSERVED_ON_SAMPLE"
    elif counts["control_win"] > counts["treatment_win"]:
        interpretation_decision = "GUIDANCE_REGRESSION_OBSERVED"
    elif t_valid == c_valid and t_completed == c_completed:
        interpretation_decision = "NO_CLEAR_GUIDANCE_BENEFIT"
    else:
        interpretation_decision = "COMPARISON_INCONCLUSIVE"

    vocab_report = {
        "artifact_version": "RCA2A7cVocabularyEffectReportV1",
        "experiment_id": EXPERIMENT_ID,
        "interpretation_decision": interpretation_decision,
        "sample_size": {"pairs": 4, "total_seats": 8},
        "arm_comparisons": {
            "control": {
                "executed_seats": len(c_seats),
                "canonical_valid_count": c_valid,
                "pydantic_pass_count": c_pydantic_pass,
                "to_status_completed_count": c_completed,
                "total_output_tokens": c_tokens,
            },
            "treatment": {
                "executed_seats": len(t_seats),
                "canonical_valid_count": t_valid,
                "pydantic_pass_count": t_pydantic_pass,
                "to_status_completed_count": t_completed,
                "total_output_tokens": t_tokens,
            },
        },
        "paired_counts": counts,
        "questions_answered": {
            "1_completed_misuse_improved": t_completed < c_completed,
            "2_pydantic_pass_improved": t_pydantic_pass > c_pydantic_pass,
            "3_canonical_validity_improved": t_valid > c_valid,
            "4_extra_cost_observed": t_tokens > c_tokens,
            "5_new_errors_introduced": any(
                s.get("field_scan_totals", {}).get("fabricated_evidence_like_identifier", 0) > 0 for s in t_seats
            ),
            "6_evidence_integrity_maintained": all(
                s.get("evidence_integrity", {}).get("current_task_binding", True) for s in seats
            ),
            "7_worth_further_prompt_investigation": interpretation_decision == "GUIDANCE_BENEFIT_OBSERVED_ON_SAMPLE",
            "8_rca2b_schema_still_necessary": t_valid < 4,
        },
    }
    vocab_report_path = HERE / "rca2a7c-vocabulary-effect-report-v1.json"
    write_exclusive(vocab_report_path, vocab_report)

    # 7. Runtime Identity Record
    runtime_record = {
        "artifact_version": "RCA2A7cRuntimeIdentityRecordV1",
        "experiment_id": EXPERIMENT_ID,
        "baseline_commit": AUTHORIZED_BASELINE,
        "git_head": head,
        "provider": PROVIDER,
        "model": MODEL,
        "code_hashes": current_hashes,
        "guidance_sha256": current_guidance_hash,
        "output_schema_hash": current_schema_hash,
        "preflight_logical_requests": len(preflight_report.get("attempts", [])),
        "real_model_requests": matrix["real_model_requests"],
        "stop_reason": matrix["stop_reason"],
        "observation_mode": "LIVE_STEPFUN_STEP_3.7_FLASH",
        "interpretation_decision": interpretation_decision,
    }
    runtime_record_path = HERE / "rca2a7c-runtime-identity-record-v1.json"
    write_exclusive(runtime_record_path, runtime_record)

    print("=" * 60)
    print(f" RCA-2A.7c COMPLETE | Verdict: {interpretation_decision}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
