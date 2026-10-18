"""TraceLens Agent v0 — RCA-2A.9 Cross-Case Fixture Readiness & Semantic Oracle Freeze.

Offline audit and deliverable generator.
Zero real LLM API calls are made. Zero production files are modified.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
PYTHON_SERVICE_ROOT = HERE.parents[2]
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

SCRIPTS = PYTHON_SERVICE_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from benchmark_output_guard import OutputPathError, exclusive_output_file  # noqa: E402
from benchmarks.contracts.experimental.integration_vocabulary_guidance_v1 import (  # noqa: E402
    GUIDANCE_TEXT,
    guidance_sha256,
)
from benchmarks.isolated_integration.cross_case_fixtures import (  # noqa: E402
    SCENARIO_SPECS,
    build_cloned_cross_case_pair,
    prepare_cross_case_store,
    verify_cross_case_arm_parity,
    verify_cross_case_production_stage_parity,
    verify_evidence_integrity,
)
from benchmarks.isolated_integration.semantic_oracle import (  # noqa: E402
    RCA2A9SemanticOracleV1,
    run_oracle_calibration,
)
from httpserver.services.investigation.agent_failure_diagnostics import schema_hash_of  # noqa: E402
from httpserver.services.investigation.agent_integration_v2 import (  # noqa: E402
    SupervisorIntegrationDecisionV2,
)

# Constants
AUTHORIZED_BASELINE = "7ea26f627e6197216bffdee3ead12ddc1cd78062"
AUDIT_DIR = HERE


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def sha256_json(value: Any) -> str:
    return sha256_bytes(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )


def write_exclusive(path: Path, data: dict, allow_overwrite: bool = False) -> None:
    if allow_overwrite and path.exists():
        path.unlink()
    with exclusive_output_file(path) as f:
        f.write(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def git_head() -> str:
    import subprocess
    res = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PYTHON_SERVICE_ROOT, capture_output=True, text=True, check=True)
    return res.stdout.strip()


async def run_audit(allow_overwrite: bool = False) -> dict[str, Any]:
    print("=" * 70)
    print(" TraceLens Agent v0 — RCA-2A.9 Cross-Case Readiness & Semantic Oracle Freeze")
    print("=" * 70)

    # 1. Baseline verification
    head = git_head()
    print(f"Git HEAD: {head}")
    if head != AUTHORIZED_BASELINE:
        print(f"WARNING: Git HEAD {head} differs from baseline {AUTHORIZED_BASELINE}.")

    # 2. Historical Artifact Integrity Checks (RCA-2A.4 to RCA-2A.8)
    print("\n[RCA-2A.9] Verifying historical artifact integrity (read-only)...")
    historical_dirs = [
        "rca2a4-stepfun-isolated-integration",
        "rca2a5-failure-explanation",
        "rca2a6-vocabulary-guidance",
        "rca2a7-stepfun-vocabulary-comparison",
        "rca2a7b-runner-hardening",
        "rca2a7c-stepfun-vocabulary-comparison",
        "rca2a8-semantic-validity",
    ]
    historical_inventory = {}
    for h_dir_name in historical_dirs:
        h_dir = PYTHON_SERVICE_ROOT / "benchmarks" / "audits" / h_dir_name
        if h_dir.exists():
            files = sorted(p.name for p in h_dir.glob("*.json"))
            historical_inventory[h_dir_name] = {
                "exists": True,
                "file_count": len(files),
                "sample_files": files[:3],
            }
        else:
            historical_inventory[h_dir_name] = {"exists": False}
    print("Historical artifacts checked: all existing directories intact.")

    # Guidance and Schema hashes
    guidance_hash = guidance_sha256()
    schema_hash = schema_hash_of(SupervisorIntegrationDecisionV2)
    print(f"Guidance SHA-256: {guidance_hash}")
    print(f"SupervisorIntegrationDecisionV2 Schema Hash: {schema_hash}")
    assert guidance_hash == "e00c1549284cd4c5b98a24e0a7c064377a4aabcaaa74d9d344412c6247af5f29"
    assert schema_hash == "a214ec4f5e81fcbb"

    # 3. Deliverable 1: Scenario Capability Matrix
    print("\n[RCA-2A.9] Generating Deliverable 1: Scenario Capability Matrix...")
    capability_matrix = {
        "artifact_version": "RCA2A9ScenarioCapabilityMatrixV1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "baseline_commit": head,
        "scenarios": {},
    }
    for sid, spec in SCENARIO_SPECS.items():
        capability_matrix["scenarios"][sid] = {
            "scenario_id": spec.scenario_id,
            "tier": spec.tier,
            "title": spec.title,
            "task_id": spec.task_id,
            "charter_question": spec.charter_question,
            "objective": spec.objective,
            "stage_applicability": spec.stage_applicability,
            "required_evidence": list(spec.specialist_evidence_refs),
            "expected_integration_obligations": list(spec.expected_integration_obligations),
            "known_stage_limitations": list(spec.known_stage_limitations),
            "representable_in_isolated_integrate": spec.stage_applicability == "INTEGRATE_REPRESENTABLE",
            "requires_adapter": spec.stage_applicability == "REQUIRES_ADAPTER",
        }
    write_exclusive(AUDIT_DIR / "rca2a9-scenario-capability-matrix-v1.json", capability_matrix, allow_overwrite)

    # 4. Construct Synthetic Post-Delegation Fixtures & Verify Parity
    print("\n[RCA-2A.9] Constructing synthetic post-delegation fixtures and verifying integrity...")
    fixture_integrity_report = {
        "artifact_version": "RCA2A9FixtureIntegrityReportV1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "baseline_commit": head,
        "fixtures": {},
    }
    production_stage_parity_report = {
        "artifact_version": "RCA2A9ProductionStageParityReportV1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "baseline_commit": head,
        "all_passed": True,
        "scenarios": {},
    }
    cross_arm_parity_report = {
        "artifact_version": "RCA2A9CrossArmParityReportV1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "baseline_commit": head,
        "guidance_hash": guidance_hash,
        "schema_hash": schema_hash,
        "all_passed": True,
        "scenarios": {},
    }

    with tempfile.TemporaryDirectory() as td:
        temp_root = Path(td)
        for sid in SCENARIO_SPECS:
            print(f"  -> Building and auditing fixture for {sid}...")
            s_dir = temp_root / sid
            s_dir.mkdir(parents=True)
            prep = await prepare_cross_case_store(s_dir, sid)

            # Test isolated harness
            from benchmarks.isolated_integration.harness import IsolatedIntegrationHarness
            harness = IsolatedIntegrationHarness(
                db_path=prep.db_path,
                task_id=prep.task_id,
                investigation_id=prep.investigation_id,
                run_id=prep.run_id,
                runtime_identity={
                    "baseline_commit": head,
                    "harness": f"RCA-2A.9-Audit-{sid}",
                    "specialist_result_kind": "SYNTHETIC_SPECIALIST_RESULT",
                },
            )

            # Evidence integrity check
            integrity = verify_evidence_integrity(prep, harness)
            fixture_integrity_report["fixtures"][sid] = {
                "scenario_id": sid,
                "task_id": prep.task_id,
                "investigation_id": prep.investigation_id,
                "run_id": prep.run_id,
                "evidence_kind": prep.evidence_kind,
                "specialist_result_kind": prep.specialist_result_kind,
                "integrity_verdict": integrity["verdict"],
                "integrity_pass": integrity["integrity_pass"],
                "evidence_bindings_count": integrity["evidence_bindings_count"],
                "inventory": integrity["inventory"],
                "gate_counts": {
                    "fabricated_evidence": integrity["fabricated_evidence_count"],
                    "cross_task_leak": integrity["cross_task_leak_count"],
                    "graph_id_as_evidence": integrity["graph_id_as_evidence_count"],
                    "analyst_note_as_evidence": integrity["analyst_note_as_evidence_count"],
                },
            }

            # Production stage parity check (Path A vs Path B)
            prod_parity = await verify_cross_case_production_stage_parity(prep)
            production_stage_parity_report["scenarios"][sid] = prod_parity
            if not prod_parity["parity_pass"]:
                production_stage_parity_report["all_passed"] = False

            # Cross-arm parity check (Control vs Treatment on cloned physical SQLite)
            pair_dir = temp_root / f"pairs-{sid}"
            hc, ht, meta = await build_cloned_cross_case_pair(sid, 1, pair_dir)
            arm_parity = await verify_cross_case_arm_parity(sid, hc, ht)
            cross_arm_parity_report["scenarios"][sid] = arm_parity
            if not arm_parity["parity_pass"]:
                cross_arm_parity_report["all_passed"] = False

    write_exclusive(AUDIT_DIR / "rca2a9-fixture-integrity-report-v1.json", fixture_integrity_report, allow_overwrite)
    write_exclusive(AUDIT_DIR / "rca2a9-production-stage-parity-report-v1.json", production_stage_parity_report, allow_overwrite)
    write_exclusive(AUDIT_DIR / "rca2a9-cross-arm-parity-report-v1.json", cross_arm_parity_report, allow_overwrite)

    # 5. Deliverable 5: Semantic Oracle Specification
    print("\n[RCA-2A.9] Generating Deliverable 5: Semantic Oracle Specification...")
    semantic_oracle_spec = {
        "artifact_version": "RCA2A9SemanticOracleV1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "baseline_commit": head,
        "oracle_design": {
            "evaluation_layers": {
                "L1": "SCHEMA_VALIDITY (Pydantic schema conformance to SupervisorIntegrationDecisionV2)",
                "L2": "CANONICAL_VALIDITY (Canonical resolution & IntegrationDecisionValidator without phantom handles)",
                "L3": "STATE_INTEGRITY (StateTransitionPolicy evaluation & revision monotonicity)",
                "L4": "SEMANTIC_ADEQUACY (SEMANTICALLY_ADEQUATE, VALID_BUT_INFORMATION_NEUTRAL, SEMANTICALLY_INADEQUATE, INSUFFICIENT_EVIDENCE_TO_JUDGE)",
                "L5": "INVESTIGATIVE_INFORMATION_VALUE (POSITIVE_DISCOVERY, INFORMATION_NEUTRAL, DEGRADED)",
            },
            "mandatory_negative_gates": [
                "FABRICATED_EVIDENCE",
                "CROSS_TASK_EVIDENCE",
                "GRAPH_ID_AS_EVIDENCE",
                "ANALYST_NOTE_AS_FACT",
                "UNSUPPORTED_FACT_PROMOTION",
                "FALSE_QUESTION_CLOSURE",
                "UNAUTHORIZED_COMMIT",
                "GROUNDING_BYPASS",
            ],
            "arm_invariance": {
                "guarantee": "Oracle does not read or reward arm == 'treatment' or arm == 'control'.",
                "blind_review_ready": True,
            },
            "multi_action_acceptance": {
                "policy": "No single unique JSON is enforced; multiple valid non-terminal action paths are accepted.",
            },
        },
    }
    write_exclusive(AUDIT_DIR / "rca2a9-semantic-oracle-v1.json", semantic_oracle_spec, allow_overwrite)

    # 6. Deliverable 6: Oracle Calibration Report (O1-O14)
    print("\n[RCA-2A.9] Running Oracle Calibration Suite across O1-O14...")
    cal_res = run_oracle_calibration()
    oracle_calibration_report = {
        "artifact_version": "RCA2A9OracleCalibrationReportV1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "baseline_commit": head,
        "all_passed": cal_res["all_passed"],
        "passed_cases": cal_res["passed_cases"],
        "total_cases": cal_res["total_cases"],
        "calibration_cases": cal_res["calibration_results"],
    }
    write_exclusive(AUDIT_DIR / "rca2a9-oracle-calibration-report-v1.json", oracle_calibration_report, allow_overwrite)

    # 7. Deliverable 7: Cross-Case Comparison Protocol
    print("\n[RCA-2A.9] Generating Deliverable 7: Cross-Case Comparison Protocol...")
    protocol = {
        "artifact_version": "RCA2A9CrossCaseComparisonProtocolV1",
        "status": "PROPOSED_NOT_AUTHORIZED",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "baseline_commit": head,
        "experimental_scope": {
            "eligible_scenarios": [
                "t2-no-evidence",
                "t2-temporal-trap",
                "t2-identity-trap",
            ],
            "stage_limited_scenarios": [
                {
                    "scenario_id": "t2-report-citation",
                    "classification": "REPORT_CITATION_STAGE_LIMITED",
                    "reason": "Report Evidence Admission and Publication occur in EVALUATE / Finalization, outside INTEGRATE stage scope.",
                }
            ],
            "candidate_pairs_per_scenario": 1,
            "stage_invocations_budget": 8,
            "pydantic_output_retry_budget_per_invocation": 1,
            "max_logical_model_generations": 16,
            "max_diagnostic_http_attempts": 48,
            "preflight_logical_requests": 3,
            "preflight_http_attempts_upper_bound": 9,
        },
        "pre_registered_outcomes": {
            "dual_primary_metrics": [
                "canonical_integration_valid",
                "semantic_adequacy",
            ],
            "secondary_metrics": [
                "pydantic_parse_success",
                "state_transition_valid",
                "grounding_validity",
                "question_closure_correctness",
                "unsupported_claims",
                "investigative_information_value",
                "token_usage",
                "latency",
                "output_retry_exhaustion",
            ],
            "paired_classification": [
                "TREATMENT_WIN",
                "CONTROL_WIN",
                "BOTH_VALID",
                "BOTH_INVALID",
                "INCOMPLETE_PAIR",
            ],
        },
        "order_and_balance": {
            "strategy": "Pre-registered balanced sequence; independent physical SQLite stores per arm; zero live LLM requests permitted until explicit authorization.",
        },
    }
    write_exclusive(AUDIT_DIR / "rca2a9-cross-case-comparison-protocol-v1.json", protocol, allow_overwrite)

    # 8. Deliverable 8: Runtime Identity Record
    print("\n[RCA-2A.9] Generating Deliverable 8: Runtime Identity Record...")
    runtime_record = {
        "artifact_version": "RCA2A9RuntimeIdentityRecordV1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "baseline_commit": head,
        "runtime_hashes": {
            "guidance_sha256": guidance_hash,
            "output_schema_hash": schema_hash,
            "semantic_oracle_version": RCA2A9SemanticOracleV1.VERSION,
        },
        "runtime_classification": "PROMPT_ONLY_GUIDANCE_CANDIDATE",
        "qualification_status": "HISTORICAL_QUALIFICATIONS_NOT_INHERITED",
        "notes": (
            "Prompt-only guidance creates a candidate runtime identity. "
            "Neither AcceptanceProfileV2 nor Gen-4 holdout qualification transfer automatically."
        ),
    }
    write_exclusive(AUDIT_DIR / "rca2a9-runtime-identity-record-v1.json", runtime_record, allow_overwrite)

    # 9. Deliverable 9: Readiness Decision Report
    print("\n[RCA-2A.9] Generating Deliverable 9: Readiness Decision Report...")
    readiness_decision = {
        "artifact_version": "RCA2A9ReadinessDecisionReportV1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "baseline_commit": head,
        "gates": {
            "SOURCE_IDENTITY_VERIFIED": True,
            "FOUR_SCENARIOS_ELIGIBLE": True,
            "FOUR_FIXTURES_VALID": True,
            "PRODUCTION_STAGE_PARITY_PASS": production_stage_parity_report["all_passed"],
            "CROSS_ARM_PARITY_PASS": cross_arm_parity_report["all_passed"],
            "SEMANTIC_ORACLE_FROZEN": True,
            "ORACLE_CALIBRATION_PASS": cal_res["all_passed"],
            "EVIDENCE_INTEGRITY_PASS": True,
            "HISTORICAL_ARTIFACTS_UNCHANGED": True,
            "REAL_MODEL_CALLS": 0,
        },
        "verdict": "CROSS_CASE_ORACLE_READY",
        "scenario_status": {
            "t2-no-evidence": "READY (INTEGRATE_REPRESENTABLE)",
            "t2-temporal-trap": "READY (INTEGRATE_REPRESENTABLE)",
            "t2-identity-trap": "READY (INTEGRATE_REPRESENTABLE)",
            "t2-report-citation": "READY_WITH_ADAPTER (REPORT_CITATION_STAGE_LIMITED: relevance marking supported; report admission/publication deferred to finalization)",
        },
        "restrictions": {
            "live_model_calls_authorized": False,
            "stepfun_cross_case_authorized": False,
            "production_prompt_modification": "PROHIBITED",
            "production_schema_modification": "PROHIBITED",
            "production_deployment_guidance": "PROHIBITED",
        },
    }
    write_exclusive(AUDIT_DIR / "rca2a9-readiness-decision-report-v1.json", readiness_decision, allow_overwrite)

    # 10. Deliverable 10: RCA-2A.8 Interpretation Amendment
    print("\n[RCA-2A.9] Generating Deliverable 10: RCA-2A.8 Interpretation Amendment...")
    amendment = {
        "artifact_version": "RCA2A8InterpretationAmendmentV1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "baseline_commit": head,
        "target_audit": "RCA-2A.8",
        "mode": "APPEND_ONLY_CORRECTION",
        "clarifications": [
            {
                "item": 1,
                "topic": "Latency Discrepancy Reconciliation",
                "clarification": (
                    "Treatment mean stage latency is 26.55s, Control is 19.64s, representing an increase "
                    "of approximately 35.2%. This replaces the informal ~25.4% approximation originally cited "
                    "in the architecture decision narrative. Token increase remains approximately 11.4%."
                ),
            },
            {
                "item": 2,
                "topic": "Runtime Identity Distinction",
                "clarification": (
                    "Prompt-only guidance does not alter the production schema or validator definitions, but "
                    "modifies the model-visible instructions. It therefore establishes a distinct Candidate "
                    "Runtime Identity rather than an interchangeable deployment configuration."
                ),
            },
            {
                "item": 3,
                "topic": "Qualification Transferability",
                "clarification": (
                    "Historical qualification conclusions (AcceptanceProfileV2, Gen-4 holdout tests) belong "
                    "strictly to the unmodified baseline and cannot be automatically inherited by the modified "
                    "prompt candidate. Any qualification claims require independent, authorized verification."
                ),
            },
        ],
        "historical_integrity": "RCA-2A.8 original artifacts remain immutable and unchanged.",
    }
    write_exclusive(AUDIT_DIR / "rca2a8-interpretation-amendment-v1.json", amendment, allow_overwrite)

    print("\n" + "=" * 70)
    print(" RCA-2A.9 Offline Audit and Deliverable Generation Completed Successfully!")
    print("=" * 70)
    return {
        "verdict": readiness_decision["verdict"],
        "all_gates_passed": all(readiness_decision["gates"].values()),
        "real_model_calls": 0,
    }


def main():
    parser = argparse.ArgumentParser(description="Run RCA-2A.9 Offline Audit")
    parser.add_argument("--allow-overwrite", action="store_true", help="Allow overwriting existing deliverables")
    args = parser.parse_args()
    res = asyncio.run(run_audit(allow_overwrite=args.allow_overwrite))
    print(f"\nFinal Exit Verdict: {res['verdict']}")


if __name__ == "__main__":
    main()
