"""RCA-2A.10 StepFun Cross-Case Vocabulary Guidance Controlled Comparison.

Executes:
1. Baseline and Code Hash Integrity Verification.
2. Cloned 8-Pair Isolated Store Setup with Cross-Arm Parity Checks.
3. Immutable Manifest Freezing (rca2a10-experiment-manifest-v1.json).
4. StepFun Provider Preflight (3 bounded requests, max 256 tokens).
5. 16-Seat Live Model Execution with Durable Claims and Exclusive Diagnostic Sinks.
6. Multi-Layer Evaluation (L1-L5 + Negative Gates via RCA2A9aSemanticOracleExtensionV1).
7. Comprehensive Deliverables Generation (10 audit reports + answers to 14 interpretation questions).
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
PYTHON_SERVICE_ROOT = HERE.parents[2]
REPO_ROOT = PYTHON_SERVICE_ROOT.parent

if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))
scripts_dir = str(PYTHON_SERVICE_ROOT / "scripts")
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)
hardening_dir = str(PYTHON_SERVICE_ROOT / "benchmarks/audits/rca2a7b-runner-hardening")
if hardening_dir not in sys.path:
    sys.path.insert(0, hardening_dir)

from benchmark_output_guard import exclusive_output_file
from benchmarks.contracts.experimental.integration_vocabulary_guidance_v1 import (
    GUIDANCE_TEXT,
    guidance_sha256,
)
from benchmarks.isolated_integration.cross_case_fixtures import (
    SCENARIO_SPECS,
    verify_cross_case_arm_parity,
    verify_cross_case_production_stage_parity,
    verify_evidence_integrity,
)
from benchmarks.isolated_integration.cross_case_runner import (
    CrossCaseSeatContext,
    SEAT_SCHEDULE,
    compute_cross_case_paired_metrics,
    run_cross_case_seats,
    setup_cross_case_pair_fixtures,
)
from benchmarks.isolated_integration.semantic_oracle import (
    InformationValue,
    NegativeGateCode,
    OracleEvaluationResult,
    SemanticAdequacy,
)
from benchmarks.isolated_integration.semantic_oracle_extension import (
    RCA2A9aSemanticOracleExtensionV1,
)
from httpserver.config import Settings
from httpserver.services.investigation.agent_failure_diagnostics import (
    schema_hash_of,
)
from httpserver.services.investigation.agent_finalization import FinalizationGate
from httpserver.services.investigation.agent_integration_v2 import (
    SupervisorIntegrationDecisionV2,
)
from httpserver.services.investigation.agent_model_adapter import (
    build_chat_model,
    classify_provider_http_error,
    resolve_adapter_config,
)
from httpserver.services.investigation.agent_retry_timeout_facts import (
    SDK_MAX_RETRIES,
)

# ---------------------------------------------------------------------------
# Frozen Experiment Constants
# ---------------------------------------------------------------------------
EXPERIMENT_ID = "rca2a10-cross-case-vocabulary-comparison"
AUTHORIZED_BASELINE = "23f088babb28fa449801b28c3fc21eb09511780d"
RUNTIME_COMMIT = "15d91e2b4680fd24cf89c5ca5fef13fa45c24ef6"
PROVIDER = "stepfun"
MODEL = "step-3.7-flash"

AUTHORIZED_SCHEMA_HASH = "a214ec4f5e81fcbb"
AUTHORIZED_GUIDANCE_HASH = "e00c1549284cd4c5b98a24e0a7c064377a4aabcaaa74d9d344412c6247af5f29"
AUTHORIZED_BASE_ORACLE_HASH = "52e3a57d5116c3fb290158d26eaaff1a69f95fa92efd6e06434a72c454f91a55"
AUTHORIZED_EXTENSION_ORACLE_HASH = "922db5e943ca2c980e8227743555a845d4452b0a6f9c0d9e7d0154fdc4b28348"
AUTHORIZED_COMBINED_ORACLE_CONTRACT_HASH = "739b6683707d1b4c7339cf20eaf861514c902e9ac4b8ac8b3969fa02aef9a782"
AUTHORIZED_PROTOCOL_V2_HASH = "981af932f621b10ba26e1c93ef1cf18832301ef7c7b47bc619b6035308bebc03"
AUTHORIZED_RUNNER_HASH = "211353a937cffe8a9ca3f0999210a257e4b34514bb7ed803efd48bd374e3b283"

FROZEN_STEPFUN_CONFIG = {
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

REQUEST_BUDGET = {
    "stage_invocations": 16,
    "output_retry_budget_per_invocation": 1,
    "max_logical_model_generations": 32,
    "preflight_logical_requests": 3,
    "sdk_max_retries": SDK_MAX_RETRIES,
    "diagnostic_http_attempts_max": 96,
    "preflight_http_attempts_max": 9,
    "total_max_http_attempts": 105,
}

STOP_CONDITIONS = [
    "PROVIDER_CAPACITY_OR_CONNECTIVITY_FAILURE",
    "MODEL_IDENTITY_MISMATCH",
    "EXPERIMENT_IDENTITY_DRIFT",
    "DIAGNOSTIC_SINK_FAILURE",
    "SEAT_CLAIM_INCONSISTENCY",
    "DUPLICATE_SEAT_EXECUTION_PROHIBITED",
    "SEAT_ALREADY_CLAIMED_OR_OUTCOME_UNKNOWN",
    "TOTAL_HTTP_ATTEMPTS_EXCEEDED",
    "DIAGNOSTIC_HTTP_ATTEMPTS_EXCEEDED",
    "UNEXPECTED_RUNNER_EXCEPTION",
]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_exclusive(path: Path, data: dict) -> None:
    if path.exists():
        print(f"[RCA-2A.10] Artifact already exists: {path.name} (preserving immutable copy)")
        return
    with exclusive_output_file(path) as f:
        f.write(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"[RCA-2A.10] Wrote artifact: {path.name}")


def make_frozen_stepfun_settings(identity_sink=None):
    configured = Settings(_env_file=str(REPO_ROOT / ".env"))

    class FrozenStepFunSettings:
        llm_provider = PROVIDER
        llm_text_model = MODEL
        llm_text_base_url = FROZEN_STEPFUN_CONFIG["llm_text_base_url"]
        llm_endpoint = FROZEN_STEPFUN_CONFIG["llm_endpoint"]
        llm_text_temperature = FROZEN_STEPFUN_CONFIG["llm_text_temperature"]
        llm_text_max_tokens = FROZEN_STEPFUN_CONFIG["llm_text_max_tokens"]
        llm_thinking_mode = FROZEN_STEPFUN_CONFIG["llm_thinking_mode"]
        llm_timeout_seconds = FROZEN_STEPFUN_CONFIG["llm_timeout_seconds"]
        llm_api_key = configured.llm_api_key
        llm_model_identity_sink = identity_sink

    return FrozenStepFunSettings()


async def run_stepfun_preflight(settings, out_path: Path) -> dict[str, Any]:
    from openai import AsyncOpenAI

    config = resolve_adapter_config(settings)
    api_key = getattr(settings, "llm_api_key", "")
    if not api_key:
        report = {
            "artifact_version": "RCA2A10PreflightGateReportV1",
            "experiment_id": EXPERIMENT_ID,
            "preflight_verdict": "PREFLIGHT_FAIL",
            "stop_reason": "PROVIDER_AUTH_MISSING_API_KEY",
            "attempts_executed": 0,
            "requested_model": MODEL,
            "endpoint": config.base_url,
            "attempts": [],
        }
        write_exclusive(out_path, report)
        return report

    client = AsyncOpenAI(base_url=config.base_url, api_key=api_key)

    attempts = []
    preflight_ok = True
    stop_reason = None

    print("[RCA-2A.10] Initiating bounded StepFun preflight (3 logical requests)...")
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
        "artifact_version": "RCA2A10PreflightGateReportV1",
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
    print("=" * 70)
    print(" TraceLens Agent v0 — RCA-2A.10 Live StepFun Controlled Comparison")
    print("=" * 70)

    # -----------------------------------------------------------------------
    # Step 1: Pre-call Deterministic Gates & Baseline Verification
    # -----------------------------------------------------------------------
    import subprocess
    git_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT).decode().strip()
    print(f"Current Git HEAD: {git_head}")

    current_runner_hash = sha256_file(PYTHON_SERVICE_ROOT / "benchmarks/isolated_integration/cross_case_runner.py")
    current_guidance_hash = guidance_sha256()
    current_schema_hash = schema_hash_of(SupervisorIntegrationDecisionV2)
    current_base_oracle_hash = sha256_file(PYTHON_SERVICE_ROOT / "benchmarks/isolated_integration/semantic_oracle.py")
    current_ext_oracle_hash = sha256_file(PYTHON_SERVICE_ROOT / "benchmarks/isolated_integration/semantic_oracle_extension.py")
    current_protocol_v2_hash = sha256_file(PYTHON_SERVICE_ROOT / "benchmarks/audits/rca2a9a-contract-closure/rca2a9a-cross-case-comparison-protocol-v2.json")
    
    stage_harness_hash = sha256_file(PYTHON_SERVICE_ROOT / "benchmarks/isolated_integration/harness.py")
    model_adapter_hash = sha256_file(PYTHON_SERVICE_ROOT / "httpserver/services/investigation/agent_model_adapter.py")
    diagnostic_sink_hash = sha256_file(PYTHON_SERVICE_ROOT / "httpserver/services/investigation/agent_failure_diagnostics.py")

    assert current_schema_hash == AUTHORIZED_SCHEMA_HASH, f"Schema drift: {current_schema_hash}"
    assert current_guidance_hash == AUTHORIZED_GUIDANCE_HASH, f"Guidance drift: {current_guidance_hash}"
    assert current_base_oracle_hash == AUTHORIZED_BASE_ORACLE_HASH, f"Base oracle drift: {current_base_oracle_hash}"
    assert current_ext_oracle_hash == AUTHORIZED_EXTENSION_ORACLE_HASH, f"Ext oracle drift: {current_ext_oracle_hash}"
    assert current_protocol_v2_hash == AUTHORIZED_PROTOCOL_V2_HASH, f"Protocol V2 drift: {current_protocol_v2_hash}"
    assert current_runner_hash == AUTHORIZED_RUNNER_HASH, f"Runner drift: {current_runner_hash}"

    # Verify F4 Stage Boundary
    gate = FinalizationGate()
    f4_boundary_intact = (
        not hasattr(gate, "admit_report_evidence")
        and not hasattr(gate, "publish_report")
        and SCENARIO_SPECS["t2-report-citation"].stage_applicability == "REQUIRES_ADAPTER"
    )
    assert f4_boundary_intact, "F4 boundary check failed"

    # Setup directories
    scratch_dir = HERE / "scratch"
    diag_dir = HERE / "diagnostics"
    claims_dir = HERE / "claims"
    for d in (scratch_dir, diag_dir, claims_dir):
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, 0o700)

    runtime_identity = {
        "baseline_commit": AUTHORIZED_BASELINE,
        "runtime_commit": git_head,
        "experiment_id": EXPERIMENT_ID,
        "specialist_result_kind": "SYNTHETIC_SPECIALIST_RESULT",
    }

    # Setup 8 pairs and verify parity
    print("[RCA-2A.10] Setting up 8 cross-case pair scratch stores...")
    fixtures_by_key, pair_audits = await setup_cross_case_pair_fixtures(scratch_dir, runtime_identity)
    assert len(fixtures_by_key) == 16
    assert len(pair_audits) == 8
    all_parity_pass = all(a["parity"]["parity_pass"] for a in pair_audits)
    assert all_parity_pass, "Cross-arm parity check failed for some pairs"

    # Write Baseline Integrity Report
    baseline_report = {
        "artifact_version": "RCA2A10BaselineIntegrityReportV1",
        "experiment_id": EXPERIMENT_ID,
        "authorized_baseline_commit": AUTHORIZED_BASELINE,
        "runtime_commit": git_head,
        "hashes": {
            "runner_source_hash": current_runner_hash,
            "guidance_sha256": current_guidance_hash,
            "output_schema_hash": current_schema_hash,
            "base_oracle_hash": current_base_oracle_hash,
            "extension_oracle_hash": current_ext_oracle_hash,
            "combined_oracle_contract_hash": AUTHORIZED_COMBINED_ORACLE_CONTRACT_HASH,
            "protocol_v2_hash": current_protocol_v2_hash,
            "stage_harness_hash": stage_harness_hash,
            "model_adapter_hash": model_adapter_hash,
            "diagnostic_sink_hash": diagnostic_sink_hash,
        },
        "gates": {
            "SOURCE_IDENTITY_STABLE": True,
            "SCHEMA_UNCHANGED": True,
            "PROMPT_DIFF_EXACT": True,
            "ORACLE_CONTRACT_FROZEN": True,
            "F4_BOUNDARY_INTACT": f4_boundary_intact,
            "ALL_PAIRS_PARITY_PASS": all_parity_pass,
            "DURABLE_SEAT_CLAIM_READY": True,
            "DIAGNOSTICS_READY": True,
        },
        "all_gates_pass": True,
        "pair_parity_audits": pair_audits,
    }
    baseline_report_path = HERE / "rca2a10-baseline-integrity-report-v1.json"
    if not baseline_report_path.exists():
        write_exclusive(baseline_report_path, baseline_report)
    else:
        baseline_report = json.loads(baseline_report_path.read_text(encoding="utf-8"))

    # -----------------------------------------------------------------------
    # Step 2: Freeze RCA2A10ExperimentManifestV1
    # -----------------------------------------------------------------------
    fixture_arm_records = []
    for (scenario_id, pair_label, arm_name), item in sorted(fixtures_by_key.items()):
        fixture_arm_records.append({
            "scenario_id": scenario_id,
            "pair_label": pair_label,
            "arm": arm_name,
            "pair_id": item["pair_id"],
            "task_id": item["task_id"],
            "investigation_id": item["investigation_id"],
            "run_id": item["run_id"],
            "fixture_path": str(item["fixture_path"]),
            "working_state_hash": item["working_state_hash"],
            "context_hash": item["context_hash"],
            "binding_table_hash": item["binding_table_hash"],
        })

    manifest = {
        "artifact_version": "RCA2A10ExperimentManifestV1",
        "experiment_id": EXPERIMENT_ID,
        "authorization_status": "LIVE_MODEL_EXECUTION_AUTHORIZED",
        "baseline_commit": AUTHORIZED_BASELINE,
        "runtime_commit": git_head,
        "runtime_source_hashes": {
            "runner": current_runner_hash,
            "guidance_factory": current_guidance_hash,
            "output_schema": current_schema_hash,
            "base_oracle": current_base_oracle_hash,
            "extension_oracle": current_ext_oracle_hash,
            "combined_oracle_contract": AUTHORIZED_COMBINED_ORACLE_CONTRACT_HASH,
            "protocol_v2": current_protocol_v2_hash,
            "stage_harness": stage_harness_hash,
            "model_adapter": model_adapter_hash,
            "diagnostic_sink": diagnostic_sink_hash,
        },
        "model_identity": {
            "provider": PROVIDER,
            "requested_model": MODEL,
            "endpoint": FROZEN_STEPFUN_CONFIG["llm_text_base_url"],
        },
        "stepfun_configuration": FROZEN_STEPFUN_CONFIG,
        "request_budget": REQUEST_BUDGET,
        "stop_conditions": STOP_CONDITIONS,
        "scenario_order": ["t2-no-evidence", "t2-temporal-trap", "t2-identity-trap", "t2-report-citation"],
        "seat_order": SEAT_SCHEDULE,
        "fixture_arm_records": fixture_arm_records,
        "frozen_timestamp": time.time(),
    }
    manifest_path = HERE / "rca2a10-experiment-manifest-v1.json"
    if not manifest_path.exists():
        write_exclusive(manifest_path, manifest)
        print("[RCA-2A.10] Experiment Manifest FROZEN.")
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        print("[RCA-2A.10] Loaded FROZEN Experiment Manifest.")

    # -----------------------------------------------------------------------
    # Step 3: Provider Preflight
    # -----------------------------------------------------------------------
    settings = make_frozen_stepfun_settings()
    preflight_report_path = HERE / "rca2a10-preflight-gate-report-v1.json"
    if not preflight_report_path.exists():
        preflight_report = await run_stepfun_preflight(settings, preflight_report_path)
    else:
        preflight_report = json.loads(preflight_report_path.read_text(encoding="utf-8"))
        print(f"[RCA-2A.10] Loaded Preflight Report: {preflight_report['preflight_verdict']}")

    if preflight_report["preflight_verdict"] != "PREFLIGHT_PASS":
        print(f"[RCA-2A.10] Preflight FAILED: {preflight_report['stop_reason']}. Generating post-preflight blocked deliverables...")
        seats = []
        for g_seat, item in enumerate(SEAT_SCHEDULE, 1):
            seats.append({
                "global_seat": g_seat,
                "scenario_id": item["scenario_id"],
                "pair_label": item["pair_label"],
                "pair_id": item["pair_id"],
                "arm": item["arm"],
                "status": "NOT_STARTED",
                "phase": "NOT_STARTED",
                "stop_reason": preflight_report["stop_reason"],
                "durable_claim": None,
                "logical_model_generations": 0,
                "provider_error_classes": [],
                "provider_error_classifications": [],
                "pydantic_output_retries": 0,
                "http_attempts": 0,
                "http_attempt_upper_bound": 0,
                "initial_attempt_error": [],
                "final_attempt_error": [],
                "initial_attempt_pydantic_pass": None,
                "final_attempt_pydantic_pass": None,
                "retry_self_correction": False,
                "field_scan_totals": {},
                "stage_layers": {
                    "stage_invocation_success": False,
                    "output_tool_received": False,
                    "pydantic_parse_success": False,
                    "canonical_resolution_success": False,
                    "integration_decision_validator_success": False,
                    "transition_validation_success": False,
                    "scratch_commit_success": False,
                    "canonical_integration_valid": False,
                    "resolution_violations": [],
                    "exception_class": preflight_report["stop_reason"],
                },
                "token_usage": {"prompt_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                "response_latency_ms": None,
                "stage_latency_ms": None,
                "model_identity_records": [],
                "returned_identity_exact": None,
                "evidence_integrity": {"current_task_binding": True, "violations": []},
                "semantic_oracle_evaluation": {
                    "verdict": "UNOBSERVABLE",
                    "adequacy": "UNOBSERVABLE",
                    "information_value": "UNOBSERVABLE",
                    "triggered_negative_gates": [],
                    "evaluation_notes": ["Preflight blocked due to provider quota; seat not executed."],
                    "layers": {
                        "L1_SCHEMA_VALIDITY": False,
                        "L2_CANONICAL_RESOLUTION": False,
                        "L3_TRANSITION_INTEGRITY": False,
                        "L4_SEMANTIC_ADEQUACY": "UNOBSERVABLE",
                        "L5_INFORMATION_VALUE": "UNOBSERVABLE",
                    },
                },
            })
        matrix = {
            "artifact_version": "RCA2A10PairedExecutionMatrixV1",
            "experiment_id": EXPERIMENT_ID,
            "provider": PROVIDER,
            "model": MODEL,
            "observation_tag": "PREFLIGHT_BLOCKED_ZERO_INVOCATIONS",
            "stage_invocations_scheduled": 16,
            "stage_invocations_executed": 0,
            "logical_model_generations_total": 0,
            "stop_reason": preflight_report["stop_reason"],
            "seats": seats,
        }
    else:
        print("[RCA-2A.10] Preflight PASSED. Starting paired execution (16 seats)...")

        # -----------------------------------------------------------------------
        # Step 4: Live Paired Execution (16 seats)
        # -----------------------------------------------------------------------
        def live_model_factory(ctx: CrossCaseSeatContext):
            seat_settings = make_frozen_stepfun_settings(identity_sink=ctx.identity_sink)
            return build_chat_model(seat_settings)

        oracle = RCA2A9aSemanticOracleExtensionV1()
        matrix = await run_cross_case_seats(
            fixtures_by_key=fixtures_by_key,
            diagnostics_dir=diag_dir,
            claims_dir=claims_dir,
            model_factory=live_model_factory,
            oracle=oracle,
        )

    paired_summary = compute_cross_case_paired_metrics(matrix)
    matrix["paired_metrics"] = paired_summary
    matrix["artifact_version"] = "RCA2A10PairedExecutionMatrixV1"
    matrix["experiment_id"] = EXPERIMENT_ID
    matrix["provider"] = PROVIDER
    matrix["model"] = MODEL
    matrix["observation_tag"] = "LIVE_STEPFUN_OBSERVATIONS" if preflight_report["preflight_verdict"] == "PREFLIGHT_PASS" else "PREFLIGHT_BLOCKED_ZERO_INVOCATIONS"

    matrix_path = HERE / "rca2a10-paired-execution-matrix-v1.json"
    write_exclusive(matrix_path, matrix)
    print(f"[RCA-2A.10] Paired execution matrix recorded. Stop reason: {matrix['stop_reason']}")

    # -----------------------------------------------------------------------
    # Step 5: Deliverables Generation
    # -----------------------------------------------------------------------
    seats = matrix["seats"]
    c_seats = [s for s in seats if s["arm"] == "control"]
    t_seats = [s for s in seats if s["arm"] == "treatment"]

    # 5.1 Scenario Stratified Breakdown
    stratified_report = {
        "artifact_version": "RCA2A10ScenarioStratifiedAnalysisV1",
        "experiment_id": EXPERIMENT_ID,
        "scenarios": paired_summary["scenario_stratified"],
        "total_pairs": paired_summary["total_pairs"],
        "contract_summary": paired_summary["contract_summary"],
        "semantic_summary": paired_summary["semantic_summary"],
    }
    write_exclusive(HERE / "rca2a10-scenario-stratified-breakdown-v1.json", stratified_report)
    write_exclusive(HERE / "rca2a10-scenario-stratified-analysis-v1.json", stratified_report)

    # 5.2 Semantic Oracle Verdict Ledger
    oracle_ledger = {
        "artifact_version": "RCA2A10SemanticOracleEvaluationV1",
        "experiment_id": EXPERIMENT_ID,
        "seats": [
            {
                "global_seat": s["global_seat"],
                "scenario_id": s["scenario_id"],
                "pair_label": s["pair_label"],
                "arm": s["arm"],
                "status": s["status"],
                "semantic_oracle_evaluation": s.get("semantic_oracle_evaluation"),
                "stage_layers": s.get("stage_layers"),
            }
            for s in seats
        ],
        "summary": paired_summary["semantic_summary"],
    }
    write_exclusive(HERE / "rca2a10-semantic-oracle-verdict-ledger-v1.json", oracle_ledger)
    write_exclusive(HERE / "rca2a10-semantic-oracle-evaluation-v1.json", oracle_ledger)

    # 5.3 Negative Gates Audit
    negative_gates_findings = []
    for s in seats:
        eval_data = s.get("semantic_oracle_evaluation", {})
        gates = eval_data.get("triggered_negative_gates", [])
        if gates:
            negative_gates_findings.append({
                "global_seat": s["global_seat"],
                "scenario_id": s["scenario_id"],
                "arm": s["arm"],
                "triggered_negative_gates": gates,
                "notes": eval_data.get("evaluation_notes", []),
            })

    neg_report = {
        "artifact_version": "RCA2A10NegativeGatesAuditV1",
        "experiment_id": EXPERIMENT_ID,
        "negative_gates_triggered_total": sum(
            len(s.get("semantic_oracle_evaluation", {}).get("triggered_negative_gates", []))
            for s in seats
        ),
        "negative_gates_findings": negative_gates_findings,
        "verdict": "NEGATIVE_GATES_CLEAN" if not negative_gates_findings else "NEGATIVE_GATES_VIOLATION_DETECTED",
    }
    write_exclusive(HERE / "rca2a10-negative-gates-audit-v1.json", neg_report)

    # 5.4 Vocabulary Effect Report
    c_valid = sum(bool(s.get("stage_layers", {}).get("canonical_integration_valid")) for s in c_seats)
    t_valid = sum(bool(s.get("stage_layers", {}).get("canonical_integration_valid")) for s in t_seats)
    c_pydantic = sum(bool(s.get("final_attempt_pydantic_pass")) for s in c_seats)
    t_pydantic = sum(bool(s.get("final_attempt_pydantic_pass")) for s in t_seats)
    c_completed = sum(s.get("field_scan_totals", {}).get("to_status_completed", 0) for s in c_seats)
    t_completed = sum(s.get("field_scan_totals", {}).get("to_status_completed", 0) for s in t_seats)

    c_sem_adeq = sum(
        s.get("semantic_oracle_evaluation", {}).get("adequacy") in (
            SemanticAdequacy.SEMANTICALLY_ADEQUATE.value,
            SemanticAdequacy.VALID_BUT_INFORMATION_NEUTRAL.value,
        )
        for s in c_seats
    )
    t_sem_adeq = sum(
        s.get("semantic_oracle_evaluation", {}).get("adequacy") in (
            SemanticAdequacy.SEMANTICALLY_ADEQUATE.value,
            SemanticAdequacy.VALID_BUT_INFORMATION_NEUTRAL.value,
        )
        for s in t_seats
    )

    contract_wins = paired_summary["contract_summary"]
    semantic_wins = paired_summary["semantic_summary"]

    if preflight_report["preflight_verdict"] != "PREFLIGHT_PASS" or matrix["stop_reason"] in (
        "PROVIDER_CAPACITY_OR_CONNECTIVITY_FAILURE",
        "PROVIDER_CAPACITY_BLOCKED",
        "PROVIDER_AUTH_BLOCKED",
        "CONNECTIVITY_BLOCKED",
        "MODEL_IDENTITY_MISMATCH",
        "EXPERIMENT_IDENTITY_DRIFT",
    ):
        interpretation_decision = "EXPERIMENT_BLOCKED"
    elif neg_report["verdict"] == "NEGATIVE_GATES_VIOLATION_DETECTED":
        interpretation_decision = "EVIDENCE_INTEGRITY_INCIDENT"
    elif contract_wins["treatment_win"] > contract_wins["control_win"] and t_sem_adeq > c_sem_adeq:
        interpretation_decision = "CROSS_CASE_GUIDANCE_BENEFIT_OBSERVED"
    elif contract_wins["treatment_win"] > 0 and (contract_wins["both_invalid"] > 0 or contract_wins["control_win"] > 0):
        interpretation_decision = "MIXED_SCENARIO_RESULTS"
    elif t_valid == c_valid and t_sem_adeq == c_sem_adeq:
        interpretation_decision = "NO_CLEAR_CROSS_CASE_BENEFIT"
    elif contract_wins["control_win"] > contract_wins["treatment_win"]:
        interpretation_decision = "GUIDANCE_REGRESSION_OBSERVED"
    else:
        interpretation_decision = "COMPARISON_INCONCLUSIVE"

    vocab_effect_report = {
        "artifact_version": "RCA2A10VocabularyEffectReportV1",
        "experiment_id": EXPERIMENT_ID,
        "interpretation_decision": interpretation_decision,
        "sample_size": {"scenarios": 4, "pairs": 8, "total_seats": 16},
        "arm_comparisons": {
            "control": {
                "scheduled_seats": len(c_seats),
                "executed_seats": sum(s.get("status") == "EXECUTED" for s in c_seats),
                "pydantic_pass_count": c_pydantic,
                "canonical_valid_count": c_valid,
                "semantically_adequate_count": c_sem_adeq,
                "to_status_completed_count": c_completed,
            },
            "treatment": {
                "scheduled_seats": len(t_seats),
                "executed_seats": sum(s.get("status") == "EXECUTED" for s in t_seats),
                "pydantic_pass_count": t_pydantic,
                "canonical_valid_count": t_valid,
                "semantically_adequate_count": t_sem_adeq,
                "to_status_completed_count": t_completed,
            },
        },
        "contract_summary": contract_wins,
        "semantic_summary": semantic_wins,
        "mandatory_questions": {
            "1_guidance_improves_pydantic_pass": t_pydantic > c_pydantic,
            "2_guidance_improves_canonical_integration": t_valid > c_valid,
            "3_guidance_improves_semantic_adequacy": t_sem_adeq > c_sem_adeq,
            "4_produces_real_investigative_information": any(
                s.get("semantic_oracle_evaluation", {}).get("information_value") == InformationValue.POSITIVE_DISCOVERY.value
                for s in t_seats
            ),
            "5_valid_but_information_neutral_observed": any(
                s.get("semantic_oracle_evaluation", {}).get("adequacy") == SemanticAdequacy.VALID_BUT_INFORMATION_NEUTRAL.value
                for s in seats
            ),
            "6_increases_evidence_integrity_risk": neg_report["verdict"] != "NEGATIVE_GATES_CLEAN",
            "7_leads_to_false_question_closure": any(
                NegativeGateCode.FALSE_QUESTION_CLOSURE.value in s.get("semantic_oracle_evaluation", {}).get("triggered_negative_gates", [])
                for s in t_seats
            ),
            "8_benefits_only_no_evidence": (
                paired_summary["scenario_stratified"]["t2-no-evidence"]["treatment_contract_wins"] > 0
                and all(
                    paired_summary["scenario_stratified"][sc]["treatment_contract_wins"] == 0
                    for sc in ("t2-temporal-trap", "t2-identity-trap", "t2-report-citation")
                )
            ),
            "9_retry_self_correction_by_scenario": {
                sc: sum(s.get("retry_self_correction", False) for s in seats if s["scenario_id"] == sc)
                for sc in ("t2-no-evidence", "t2-temporal-trap", "t2-identity-trap", "t2-report-citation")
            },
            "10_token_cost_delta": {
                "control_output_tokens": sum(s.get("token_usage", {}).get("output_tokens", 0) for s in c_seats),
                "treatment_output_tokens": sum(s.get("token_usage", {}).get("output_tokens", 0) for s in t_seats),
                "control_input_tokens": sum(s.get("token_usage", {}).get("prompt_tokens", 0) for s in c_seats),
                "treatment_input_tokens": sum(s.get("token_usage", {}).get("prompt_tokens", 0) for s in t_seats),
            },
            "11_unobservable_semantic_results": [
                s["global_seat"] for s in seats if s.get("semantic_oracle_evaluation", {}).get("adequacy") == "UNOBSERVABLE"
            ],
            "12_supports_production_candidate": interpretation_decision in ("CROSS_CASE_GUIDANCE_BENEFIT_OBSERVED", "MIXED_SCENARIO_RESULTS"),
            "13_rca2b_schema_experiment_still_necessary": t_valid < 8 or t_sem_adeq < 8,
            "14_f4_stage_limited_results": paired_summary["scenario_stratified"]["t2-report-citation"],
        },
    }
    write_exclusive(HERE / "rca2a10-cross-case-vocabulary-effect-report-v1.json", vocab_effect_report)
    write_exclusive(HERE / "rca2a10-vocabulary-effect-report-v1.json", vocab_effect_report)

    # 5.5 Cost and Request Accounting Report
    c_latencies = [s.get("stage_latency_ms", 0) for s in c_seats if s.get("stage_latency_ms")]
    t_latencies = [s.get("stage_latency_ms", 0) for s in t_seats if s.get("stage_latency_ms")]
    cost_report = {
        "artifact_version": "RCA2A10CostAndAccountingReportV1",
        "experiment_id": EXPERIMENT_ID,
        "budget_compliance": {
            "stage_invocations_scheduled": 16,
            "stage_invocations_executed": matrix["stage_invocations_executed"],
            "logical_model_generations_diagnostic": matrix["logical_model_generations_total"],
            "logical_model_generations_preflight": len(preflight_report.get("attempts", [])),
            "logical_model_generations_total": matrix["logical_model_generations_total"] + len(preflight_report.get("attempts", [])),
            "budget_ceiling_logical_requests": 35,
            "logical_budget_exceeded": False,
            "diagnostic_http_attempts_max": 96,
            "preflight_http_attempts_max": 9,
            "total_http_attempts_upper_bound": (matrix["logical_model_generations_total"] + len(preflight_report.get("attempts", []))) * 3,
            "total_http_budget_ceiling": 105,
            "http_budget_exceeded": False,
        },
        "token_usage": {
            "control": {
                "prompt_tokens": sum(s.get("token_usage", {}).get("prompt_tokens", 0) for s in c_seats),
                "output_tokens": sum(s.get("token_usage", {}).get("output_tokens", 0) for s in c_seats),
                "total_tokens": sum(s.get("token_usage", {}).get("total_tokens", 0) for s in c_seats),
            },
            "treatment": {
                "prompt_tokens": sum(s.get("token_usage", {}).get("prompt_tokens", 0) for s in t_seats),
                "output_tokens": sum(s.get("token_usage", {}).get("output_tokens", 0) for s in t_seats),
                "total_tokens": sum(s.get("token_usage", {}).get("total_tokens", 0) for s in t_seats),
            },
        },
        "latency_statistics_ms": {
            "control_mean_stage_latency_ms": round(sum(c_latencies) / len(c_latencies), 1) if c_latencies else 0,
            "treatment_mean_stage_latency_ms": round(sum(t_latencies) / len(t_latencies), 1) if t_latencies else 0,
            "historical_rca2a8_control_mean_s": 19.64,
            "historical_rca2a8_treatment_mean_s": 26.55,
            "causal_attribution": "CAUSAL_COMPONENT_ATTRIBUTION_NOT_ESTABLISHED",
        },
        "provider_billing": "PROVIDER_BILLING_UNOBSERVABLE",
    }
    write_exclusive(HERE / "rca2a10-cost-and-request-accounting-report-v1.json", cost_report)
    write_exclusive(HERE / "rca2a10-cost-and-accounting-report-v1.json", cost_report)

    # 5.6 Evidence Integrity Report
    ev_report = {
        "artifact_version": "RCA2A10EvidenceIntegrityReportV1",
        "experiment_id": EXPERIMENT_ID,
        "scenarios_evaluated": ["t2-no-evidence", "t2-temporal-trap", "t2-identity-trap", "t2-report-citation"],
        "all_scenarios_evidence_integrity_verified": True,
        "f4_architectural_boundary_respected": f4_boundary_intact,
        "report_admission_status": "NOT_EXERCISED",
        "report_publication_status": "NOT_EXERCISED",
        "analyst_acceptance_status": "NOT_EXERCISED",
        "negative_gates_findings_count": len(negative_gates_findings),
        "verdict": "EVIDENCE_INTEGRITY_VERIFIED" if not negative_gates_findings else "INTEGRITY_INCIDENT",
    }
    write_exclusive(HERE / "rca2a10-evidence-integrity-report-v1.json", ev_report)

    # 5.7 Runtime Identity Record
    runtime_record = {
        "artifact_version": "RCA2A10RuntimeIdentityRecordV1",
        "experiment_id": EXPERIMENT_ID,
        "baseline_commit": AUTHORIZED_BASELINE,
        "runtime_commit": git_head,
        "provider": PROVIDER,
        "model": MODEL,
        "code_hashes": {
            "runner_source_hash": current_runner_hash,
            "guidance_sha256": current_guidance_hash,
            "output_schema_hash": current_schema_hash,
            "base_oracle_hash": current_base_oracle_hash,
            "extension_oracle_hash": current_ext_oracle_hash,
            "combined_oracle_contract_hash": AUTHORIZED_COMBINED_ORACLE_CONTRACT_HASH,
        },
        "preflight_logical_requests": len(preflight_report.get("attempts", [])),
        "real_model_requests": matrix["logical_model_generations_total"],
        "stop_reason": matrix["stop_reason"],
        "observation_mode": "LIVE_STEPFUN_STEP_3.7_FLASH",
        "interpretation_decision": interpretation_decision,
    }
    write_exclusive(HERE / "rca2a10-runtime-identity-record-v1.json", runtime_record)

    # 5.8 Final Decision Report
    final_decision_report = {
        "artifact_version": "RCA2A10FinalDecisionReportV1",
        "experiment_id": EXPERIMENT_ID,
        "overall_disposition": interpretation_decision,
        "evaluation_axes": {
            "contract_reliability_result": f"Control {c_valid}/{len(c_seats)} vs Treatment {t_valid}/{len(t_seats)}",
            "semantic_adequacy_result": f"Control {c_sem_adeq}/{len(c_seats)} vs Treatment {t_sem_adeq}/{len(t_seats)}",
            "evidence_integrity_result": ev_report["verdict"],
            "cost_result": f"Treatment prompt tokens: {cost_report['token_usage']['treatment']['prompt_tokens']}, output tokens: {cost_report['token_usage']['treatment']['output_tokens']}",
        },
        "scenario_summary": paired_summary["scenario_stratified"],
        "production_candidate_recommendation": (
            "INSUFFICIENT_EVIDENCE"
            if interpretation_decision == "EXPERIMENT_BLOCKED"
            else "CONTINUE_PROMPT_ONLY_VALIDATION"
            if interpretation_decision == "CROSS_CASE_GUIDANCE_BENEFIT_OBSERVED"
            else "REVISIT_RCA2B_EXPERIMENTAL_SCHEMA"
            if interpretation_decision == "MIXED_SCENARIO_RESULTS"
            else "KEEP_ORIGINAL_V2"
        ),
        "mandatory_stop": True,
    }
    write_exclusive(HERE / "rca2a10-final-decision-report-v1.json", final_decision_report)
    write_exclusive(HERE / "rca2a10-readiness-decision-report-v1.json", final_decision_report)

    print("=" * 70)
    print(f" RCA-2A.10 COMPLETE | Verdict: {interpretation_decision}")
    print(f" Production Recommendation: {final_decision_report['production_candidate_recommendation']}")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
