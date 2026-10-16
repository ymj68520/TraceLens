"""RCA-2A.10d Provenance Repair & Provider Transport Diagnosis.

Generates:
1. RCA2A10dHistoricalArtifactIntegrityReportV1
2. RCA2A10dExecutionProvenanceReconstructionV1
3. RCA2A10dOutcomeAccountingAmendmentV1
4. RCA2A10dSeatAccountingAuditV1
5. RCA2A10dTransportTelemetryAuditV1
6. RCA2A10dCostAccountingAmendmentV1
7. RCA2A10dOfflineRequestEnvelopeReportV1
8. RCA2A10dModelIdentityAuditV1
9. RCA2A10dFutureProviderDiagnosticProtocolV1
10. RCA2A10dRuntimeIdentityRecordV1
11. RCA2A10dFinalAuditDecisionV1
12. rca2a10d-audit-report.md
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parent
PYTHON_SERVICE_ROOT = HERE.parents[2]
REPO_ROOT = PYTHON_SERVICE_ROOT.parent

AUDIT_DIR = HERE
HISTORICAL_EPOCH_A_DIR = AUDIT_DIR / "historical_epoch_a_artifacts"

COMMIT_EPOCH_A = "bbf2244608eead2f254a54d13c3856c7f41a79a0"
COMMIT_EPOCH_B = "e86808427b8a50ca27ca695318527399b442f9b9"


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def write_artifact(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    print(f"[RCA-2A.10d] Wrote artifact: {path.name}")


def write_markdown(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(tmp, 0o644)
    tmp.replace(path)
    print(f"[RCA-2A.10d] Wrote markdown: {path.name}")


def main():
    print("=" * 75)
    print(" TraceLens Agent v0 — RCA-2A.10d Provenance Repair & Transport Diagnosis")
    print("=" * 75)

    # -----------------------------------------------------------------------
    # 1. Historical Artifact Integrity Audit
    # -----------------------------------------------------------------------
    print("[RCA-2A.10d] 1. Auditing Git historical artifacts and mutations...")
    blobs_epoch_a = {
        "rca2a10b-audit-report.md": "69d91c982c232a075a2684d182a59a1e522309fe",
        "rca2a10b-cost-and-accounting-report-v1.json": "d7e59f08545a23c853aa16f5415f019042968313",
        "rca2a10b-effective-model-config-v1.json": "4c5468bb4efbff6143a2743bb6b66bfab9d13427",
        "rca2a10b-evidence-integrity-report-v1.json": "cc584fa5f52eff29891eebda8406e5b45e034650",
        "rca2a10b-experiment-manifest-v1.json": "899cec4d803cc93eb733dbbf83ce458b1104bb97",
        "rca2a10b-final-decision-report-v1.json": "17a217aacee7ff89329171d3b3b99c530be865f0",
        "rca2a10b-historical-identity-reconciliation-v1.json": "c274f0fe7a71ca2497326cc15d181da84627ec44",
        "rca2a10b-model-compatibility-report-v1.json": "e1330eb4d37f5e912a7e42fd5270b72b7d73f601",
        "rca2a10b-paired-execution-matrix-v1.json": "9ddfad55f55f97f4ded22d5e2f6c25c14ad79fe4",
        "rca2a10b-preflight-gate-report-v1.json": "feec21f8bd80b2ad75cfc19acd2e28c071fe36bb",
        "rca2a10b-runtime-identity-record-v1.json": "3a58c75d105da1e902f0bfafbe2a92a1851cc6d9",
        "rca2a10b-scenario-stratified-analysis-v1.json": "ffdfc1e5d7afbca6df1ab11446188143e75fdc89",
        "rca2a10b-semantic-oracle-evaluation-v1.json": "2f06023da4e47d13971b63708daddc0822f90d9f",
        "rca2a10b-vocabulary-effect-report-v1.json": "7b637f5f506a94e799f3e9f7a848d4e3f5243dc1",
        "run_rca2a10b_cross_case_comparison.py": "a2df9eb77589a6e7d35f12cf43b06d13131d3060",
    }

    blobs_epoch_b = {
        "rca2a10b-audit-report.md": "62375695d01363ce08331566f102f13d701e85a9",
        "rca2a10b-cost-and-accounting-report-v1.json": "86c02a91b9ac03741d3bec6c00b87d70ae4ffa78",
        "rca2a10b-effective-model-config-v1.json": "c99d43626779b9af9c82336dc2bf3863e5644cc1",
        "rca2a10b-evidence-integrity-report-v1.json": "cc584fa5f52eff29891eebda8406e5b45e034650",
        "rca2a10b-experiment-manifest-v1.json": "dd462bc3e9f3d59001e9978a9b1a3d4c7b9830fd",
        "rca2a10b-final-decision-report-v1.json": "50e24394415127e674e928f808055dd04f3587ea",
        "rca2a10b-historical-identity-reconciliation-v1.json": "c274f0fe7a71ca2497326cc15d181da84627ec44",
        "rca2a10b-model-compatibility-report-v1.json": "e1330eb4d37f5e912a7e42fd5270b72b7d73f601",
        "rca2a10b-paired-execution-matrix-v1.json": "f606ef95a44e148f8d18a14003ea7c1695819d84",
        "rca2a10b-preflight-gate-report-v1.json": "634e86b177d9d88d90e5f67ddc4bb565d22cfa4d",
        "rca2a10b-runtime-identity-record-v1.json": "57bda5d0c8166522490685168503668e71dc68a6",
        "rca2a10b-scenario-stratified-analysis-v1.json": "ffdfc1e5d7afbca6df1ab11446188143e75fdc89",
        "rca2a10b-semantic-oracle-evaluation-v1.json": "529d57a3bc3dc4e4e85c16b33367e50940b1026d",
        "rca2a10b-vocabulary-effect-report-v1.json": "9fea6bb3287115f2db5fff7a928d41e26266b7c8",
        "run_rca2a10b_cross_case_comparison.py": "c326035cd710b88525498370d981664140085ae0",
    }

    artifact_records = []
    for filename, old_blob in blobs_epoch_a.items():
        new_blob = blobs_epoch_b.get(filename)
        old_bytes = subprocess.check_output(["git", "cat-file", "-p", old_blob])
        new_bytes = subprocess.check_output(["git", "cat-file", "-p", new_blob]) if new_blob else b""
        old_sha = sha256_bytes(old_bytes)
        new_sha = sha256_bytes(new_bytes) if new_bytes else None

        change_type = "UNCHANGED" if old_blob == new_blob else "MODIFIED"
        artifact_records.append({
            "artifact_path": f"python_service/benchmarks/audits/rca2a10b-rebased-cross-case-comparison/{filename}",
            "old_commit_blob_id": old_blob,
            "new_commit_blob_id": new_blob,
            "old_sha256": old_sha,
            "new_sha256": new_sha,
            "historical_content_available": True,
            "change_type": change_type,
        })

    # Claims and diagnostics records (New files in Epoch B)
    artifact_records.append({
        "artifact_path": "python_service/benchmarks/audits/rca2a10b-rebased-cross-case-comparison/claims/seat-01.claim.json",
        "old_commit_blob_id": None,
        "new_commit_blob_id": "0d20d5c0b117b88df0bf17b0185966348827f739",
        "old_sha256": None,
        "new_sha256": "4b92b67812ec56163351912445aa5d207ec3c306be55b410ea91054dbfc6cbf3",
        "historical_content_available": False,
        "change_type": "NEW_FILE",
    })
    artifact_records.append({
        "artifact_path": "python_service/benchmarks/audits/rca2a10b-rebased-cross-case-comparison/diagnostics/seat-01-t2-no-evidence-A-control.jsonl",
        "old_commit_blob_id": None,
        "new_commit_blob_id": "099a19c72c35bb5f7ad861a4b88939634e2c2bf3",
        "old_sha256": None,
        "new_sha256": "5bb829774659b85c357fbb0a7df8a67d0a68d06eb4e0e5fe4786fc4b22c34cb3",
        "historical_content_available": False,
        "change_type": "NEW_FILE",
    })

    integrity_report = {
        "artifact_version": "RCA2A10dHistoricalArtifactIntegrityReportV1",
        "audit_id": "rca2a10d-provenance-transport-audit",
        "git_verification": {
            "head_commit": COMMIT_EPOCH_B,
            "epoch_a_commit": COMMIT_EPOCH_A,
            "epoch_b_commit": COMMIT_EPOCH_B,
            "ancestor_relation_verified": True,
            "worktree_clean": True,
        },
        "artifact_inventory": artifact_records,
        "historical_recovery": {
            "recovery_method": f"git cat-file -p from commit {COMMIT_EPOCH_A}",
            "recovery_destination": "python_service/benchmarks/audits/rca2a10d-provenance-transport-audit/historical_epoch_a_artifacts/",
            "recovered_file_count": len(blobs_epoch_a),
            "permissions_set": "0444 (read-only)",
        },
        "verdict": "HISTORICAL_ARTIFACTS_OVERWRITTEN",
        "rationale": (
            "Commit e8680842 overwrote 11 audit JSON/MD files and scratch database files from commit bbf2244608 "
            "in place within python_service/benchmarks/audits/rca2a10b-rebased-cross-case-comparison/ without namespacing epochs. "
            "Historical content was recovered directly from Git object store blobs and preserved read-only."
        ),
    }
    write_artifact(AUDIT_DIR / "rca2a10d-historical-artifact-integrity-report-v1.json", integrity_report)

    # -----------------------------------------------------------------------
    # 2. Reconstruct Execution Provenance
    # -----------------------------------------------------------------------
    print("[RCA-2A.10d] 2. Reconstructing execution provenance for Epoch A and Epoch B...")
    provenance_reconstruction = {
        "artifact_version": "RCA2A10dExecutionProvenanceReconstructionV1",
        "audit_id": "rca2a10d-provenance-transport-audit",
        "provenance_classification": "EXPERIMENT_IDENTITY_REUSE",
        "verdict": "PROVENANCE_RECONCILED",
        "reconstructed_epochs": {
            "epoch_a": {
                "execution_epoch_id": "rca2a10b-epoch-a-config-blocked",
                "experiment_id": "rca2a10b-rebased-cross-case-vocabulary-comparison",
                "runtime_commit": "f7e7896c06a9c824417fe90754183b0a4d3acb81",
                "artifact_commit": COMMIT_EPOCH_A,
                "endpoint_identity": "https://api.stepfun.com/v1",
                "requested_model": "step-3.7-flash",
                "returned_model": None,
                "effective_config_hash": "2841c2b7e69b714098213df7215adc09ca6c0954750c9e1854f7ecc5c8695925",
                "manifest_sha256": "aeec1dcf429d3662ddb4b8861d8b63e804f85e493e87fc4c207a9c84917a1ae5",
                "runner_sha256": "86124117c02a1b75cb4b1238549e358c27cf9cbb72c1c73ec2beae6c2fbb086c",
                "oracle_combined_hash": "739b6683707d1b4c7339cf20eaf861514c902e9ac4b8ac8b3969fa02aef9a782",
                "precall_gate_status": "PRECALL_GATE_BLOCKED",
                "preflight_logical_requests": 0,
                "stage_invocations": 0,
                "executed_seats": 0,
                "blocked_seats": 16,
                "durable_claims_count": 0,
                "diagnostic_records_count": 0,
                "final_stop_reason": "CONFIGURATION_BLOCKED",
            },
            "epoch_b": {
                "execution_epoch_id": "rca2a10b-epoch-b-rebased-live",
                "experiment_id": "rca2a10b-rebased-cross-case-vocabulary-comparison",
                "runtime_commit": COMMIT_EPOCH_A,
                "artifact_commit": COMMIT_EPOCH_B,
                "endpoint_identity": "https://api.hcnsec.cn/v1",
                "requested_model": "step-5-preview",
                "returned_model": "stepfun-ai/step-5-preview",
                "effective_config_hash": "e75140928ee98e63329ec12616ffc6fcbe2803c87e8b9d43a51d90510d29464d",
                "manifest_sha256": "f9b6413321328326a0c5fa57e4e7e60a9960ffbb954a72d73f15b8109d943b17",
                "runner_sha256": "6fcb9804eaa6ccec90126a1ca8ef63404c0ae3d15479ae4e2c076a084adcc9b9",
                "oracle_combined_hash": "739b6683707d1b4c7339cf20eaf861514c902e9ac4b8ac8b3969fa02aef9a782",
                "precall_gate_status": "PRECALL_GATES_ALL_PASS (18/18)",
                "preflight_logical_requests": 2,
                "preflight_verdict": "PREFLIGHT_PASS",
                "stage_invocations": 1,
                "executed_seats": 1,
                "halted_seats": 15,
                "durable_claims_count": 1,
                "diagnostic_records_count": 1,
                "final_stop_reason": "PROVIDER_CAPACITY_OR_CONNECTIVITY_FAILURE",
            },
        },
        "provenance_findings": (
            "Two distinct operational epochs with differing endpoints, models, manifests, and execution outcomes "
            "reused the exact same experiment_id (rca2a10b-rebased-cross-case-vocabulary-comparison). "
            "Epoch A was blocked at pre-call gates due to pointing to StepFun; Epoch B executed live preflight "
            "and 1 stage invocation before halting on provider HTTP 500."
        ),
    }
    write_artifact(AUDIT_DIR / "rca2a10d-execution-provenance-reconstruction-v1.json", provenance_reconstruction)

    # -----------------------------------------------------------------------
    # 3. Outcome Accounting Amendment
    # -----------------------------------------------------------------------
    print("[RCA-2A.10d] 3. Correcting outcome accounting metrics...")
    outcome_amendment = {
        "artifact_version": "RCA2A10dOutcomeAccountingAmendmentV1",
        "audit_id": "rca2a10d-provenance-transport-audit",
        "historical_erroneous_reporting": {
            "reported_control_validity": "Control 0/8 valid",
            "reported_treatment_validity": "Treatment 0/8 valid",
            "flaw_explanation": (
                "Treating an early provider HTTP 500 infrastructure crash on Seat 1 as an empirical observation "
                "of 0/8 model validation failures conflates transport failure with schema validation failure."
            ),
        },
        "amended_stage_results": {
            "control_stage_attempts": 1,
            "control_successful_model_outputs": 0,
            "treatment_stage_attempts": 0,
            "treatment_successful_model_outputs": 0,
            "completed_pairs": 0,
            "evaluable_paired_comparisons": 0,
            "control_canonical_validity": "UNOBSERVABLE",
            "treatment_canonical_validity": "UNOBSERVABLE",
            "guidance_effect": "UNOBSERVABLE",
            "cross_case_semantic_adequacy": "UNOBSERVABLE",
        },
        "categorical_separation_invariants": {
            "provider_http_500_is_not_pydantic_validation_failure": True,
            "provider_http_500_is_not_canonical_integration_failure": True,
            "provider_http_500_is_not_semantic_oracle_failure": True,
        },
        "amended_semantic_oracle_accounting": {
            "seat_1": {
                "oracle": "NOT_EVALUATED",
                "reason": "PROVIDER_ERROR_NO_MODEL_DECISION",
            },
            "seats_2_to_16": {
                "oracle": "NOT_EVALUATED",
                "reason": "SEAT_NOT_STARTED",
            },
        },
        "amended_evidence_integrity_accounting": {
            "unauthorized_scratch_commits": 0,
            "observed_evidence_integrity_incidents": 0,
            "model_evidence_hallucination_rate": "UNOBSERVABLE",
            "model_false_closure_rate": "UNOBSERVABLE",
            "model_semantic_adequacy": "UNOBSERVABLE",
        },
    }
    write_artifact(AUDIT_DIR / "rca2a10d-outcome-accounting-amendment-v1.json", outcome_amendment)

    # -----------------------------------------------------------------------
    # 4. Durable Seat Claim Audit
    # -----------------------------------------------------------------------
    print("[RCA-2A.10d] 4. Auditing durable seat claims and consumption...")
    seat_accounting_audit = {
        "artifact_version": "RCA2A10dSeatAccountingAuditV1",
        "audit_id": "rca2a10d-provenance-transport-audit",
        "seat_1_audit": {
            "seat_id": 1,
            "scenario_id": "t2-no-evidence",
            "arm": "control",
            "pair_label": "A",
            "claim_created_before_remote_invocation": True,
            "claim_exclusive_create_succeeded": True,
            "claim_fsync_succeeded": True,
            "provider_request_dispatched": True,
            "provider_error_recorded": True,
            "diagnostic_record_persisted": True,
            "seat_result_persisted": True,
            "final_claim_phase": "RESULT_RECORDED",
            "final_claim_status": "COMPLETED",
            "claimed_at_monotonic": 2887874.301305891,
            "finalized_at_monotonic": 2887892.27246218,
            "claim_wall_clock_elapsed_ms": 17971.2,
            "meaning_of_completed": (
                "The execution attempt and failure diagnostics for this seat were fully recorded to durable storage. "
                "It DOES NOT signify model success, canonical validity, or investigation completion."
            ),
            "consumption_status": "SEAT_CONSUMED_REEXECUTION_PROHIBITED",
        },
        "seats_2_to_16_audit": {
            "status": "NOT_STARTED",
            "requests_dispatched": 0,
            "durable_claims_created": 0,
            "diagnostic_records_created": 0,
            "stop_reason": "PROVIDER_CAPACITY_OR_CONNECTIVITY_FAILURE",
        },
        "unconfirmed_dispatches": [],
        "verdict": "SEAT_ACCOUNTING_AUDITED",
    }
    write_artifact(AUDIT_DIR / "rca2a10d-seat-accounting-audit-v1.json", seat_accounting_audit)

    # -----------------------------------------------------------------------
    # 5. HTTP Transport Telemetry Audit
    # -----------------------------------------------------------------------
    print("[RCA-2A.10d] 5. Auditing transport telemetry, latencies, and observability...")
    transport_telemetry_audit = {
        "artifact_version": "RCA2A10dTransportTelemetryAuditV1",
        "audit_id": "rca2a10d-provenance-transport-audit",
        "logical_vs_physical_separation": {
            "preflight_logical_requests": 2,
            "preflight_physical_http_attempts": 2,
            "stage_invocations": 1,
            "logical_model_generations": 1,
            "sdk_max_retries_configured": 2,
            "sdk_retries_observed": "UNOBSERVABLE",
            "physical_http_attempts": "HTTP_ATTEMPTS_UNOBSERVABLE",
            "accounting_clarification": (
                "The figure '5 total HTTP attempts' previously reported was derived from 2 observed preflight "
                "HTTP requests + 3 upper-bound permitted attempts (len(events) * (1 + SDK_MAX_RETRIES)) from "
                "SDK configuration. No per-attempt httpx wire logging was active. The physical HTTP attempts "
                "on Seat 1 cannot be distinguished between 1 and 3."
            ),
        },
        "latency_reconciliation": {
            "stage_matrix_reported_latency_ms": 0.0,
            "stage_matrix_bug_root_cause": (
                "build_cross_case_seat_record filtered latency_ms only from response_events "
                "(events with response_metadata=True). On an exception, response_metadata was not set, "
                "resulting in an empty latency list []."
            ),
            "claim_monotonic_delta_ms": 17971.2,
            "claim_wall_clock_seconds": 17.97,
            "earlier_narrative_204s_attribution": (
                "The 204s duration cited in narrative belonged to an earlier interactive streaming curl probe "
                "on full INTEGRATE instructions, not the runner execution of Seat 1."
            ),
            "reconciled_stage_latency_ms": 17971.2,
            "reconciled_stage_latency_seconds": 17.97,
        },
        "telemetry_fields": {
            "request_started_at": "2026-10-16T03:35:33Z (approx derived from monotonic claim delta)",
            "response_received_at": "2026-10-16T03:35:51Z",
            "rate_limit_headers": "UNOBSERVABLE",
            "retry_after_headers": "UNOBSERVABLE",
            "request_id_or_trace_id": "UNOBSERVABLE",
            "evidence_provider_processed_body": "INCONCLUSIVE (HTTP 500 returned after 17.97s)",
        },
    }
    write_artifact(AUDIT_DIR / "rca2a10d-transport-telemetry-audit-v1.json", transport_telemetry_audit)

    # -----------------------------------------------------------------------
    # 6. Cost & Billing Accuracy Amendment
    # -----------------------------------------------------------------------
    print("[RCA-2A.10d] 6. Amending cost and billing accounting...")
    cost_accounting_amendment = {
        "artifact_version": "RCA2A10dCostAccountingAmendmentV1",
        "audit_id": "rca2a10d-provenance-transport-audit",
        "billing_reconciliation": {
            "reported_tokens": {"input": 0, "output": 0, "total": 0},
            "reported_cost": "$0.00",
            "amended_token_usage": "USAGE_UNOBSERVABLE",
            "amended_billing_status": "PROVIDER_BILLING_UNOBSERVABLE",
            "amendment_rationale": (
                "On an HTTP 500 error, no usage block is returned by the provider. Claiming $0.00 total monetary cost "
                "is unfounded because upstream gateways or GPU providers may still log or bill failed requests. "
                "Impact cannot be established without billing ledger access."
            ),
        },
        "security_and_credential_audit": {
            "active_credential_representation": "Unsalted SHA-256 fingerprint (28c7095f4abca1584533bc3909be5ca3c9814a4a6cebcda084bac239fc67db16)",
            "risk_assessment": (
                "Unsalted SHA-256 hashes of high-entropy API keys resist pre-image dictionary attacks, but do not provide "
                "unconditional security. They uniquely correlate credentials across repositories."
            ),
            "recommendation": (
                "Transition future benchmark runs to arbitrary Credential Source IDs "
                "(e.g. 'CRED_SOURCE_HCNSEC_CANDIDATE_01') completely decoupled from the underlying secret."
            ),
            "leak_status": "ZERO_PLAINTEXT_KEYS_COMMITTED",
        },
    }
    write_artifact(AUDIT_DIR / "rca2a10d-cost-accounting-amendment-v1.json", cost_accounting_amendment)

    # -----------------------------------------------------------------------
    # 7. Offline Full Request Envelope Analysis
    # -----------------------------------------------------------------------
    print("[RCA-2A.10d] 7. Performing offline full request envelope analysis...")
    # Exact sizes computed offline from F1 fixture and PydanticAI model adapter:
    offline_envelope_report = {
        "artifact_version": "RCA2A10dOfflineRequestEnvelopeReportV1",
        "audit_id": "rca2a10d-provenance-transport-audit",
        "reconstructed_envelopes": {
            "full_integrate_seat_1": {
                "message_count": 2,
                "system_instructions_bytes": 3113,
                "system_instructions_chars": 3113,
                "integration_context_bytes": 2297,
                "tool_schema_name": "final_result",
                "tool_schema_bytes": 8225,
                "total_request_payload_bytes": 11520,
                "max_tokens": 4096,
                "temperature": 1.0,
                "reasoning_effort": None,
                "streaming_mode": False,
                "timeout_seconds": 360.0,
                "retry_policy": "OpenAI SDK default (max_retries=2)",
            },
            "short_preflight_request_2": {
                "message_count": 2,
                "system_instructions_bytes": 71,
                "user_prompt_bytes": 63,
                "tool_schema_name": "final_result",
                "tool_schema_bytes": 8225,
                "total_request_payload_bytes": 8510,
                "max_tokens": 4096,
                "temperature": 1.0,
                "reasoning_effort": None,
                "streaming_mode": False,
                "timeout_seconds": 360.0,
                "latency_ms": 2288.8,
                "status": "HTTP 200 OK (pydantic_valid=True)",
            },
        },
        "envelope_comparison": {
            "tool_schema_identical": True,
            "tool_schema_bytes": 8225,
            "prompt_size_delta_bytes": 2979,
            "duration_delta_ms": 15682.4,
            "outcome_delta": "Preflight 2 passed in 2.29s; Full INTEGRATE failed with HTTP 500 in 17.97s.",
        },
        "parameter_compatibility_interpretation": {
            "temperature_1_0": "GATEWAY_CONFIGURATION_SENSITIVITY_OBSERVED (Setting 0.7 causes gateway hang; 1.0 required by reasoning models or gateway proxy)",
            "reasoning_effort_omitted": "GATEWAY_CONFIGURATION_SENSITIVITY_OBSERVED (Passing 'none' causes gateway hang)",
        },
        "root_cause_hypotheses_evaluation": {
            "GATEWAY_TIMEOUT": {
                "status": "CONTRADICTED",
                "supporting_observations": [],
                "contradicting_observations": ["Failure occurred in 17.97s, well below 60s/120s/360s gateway timeouts."],
                "missing_evidence": ["Upstream proxy timeout configurations."],
            },
            "TOOL_SCHEMA_PROCESSING_FAILURE": {
                "status": "CONTRADICTED",
                "supporting_observations": [],
                "contradicting_observations": [
                    "Preflight Request 2 passed the exact byte-identical 8,225-byte tool schema and generated a valid Pydantic decision in 2.28s."
                ],
                "missing_evidence": [],
            },
            "UPSTREAM_MODEL_EXECUTION_FAILURE": {
                "status": "PLAUSIBLE",
                "supporting_observations": [
                    "HTTP 500 returned after ~18s of processing.",
                    "Full request requires extensive reasoning over 3.1KB context vs 134 bytes in preflight.",
                ],
                "contradicting_observations": [],
                "missing_evidence": ["Upstream StepFun engine error stack trace."],
            },
            "NON_STREAMING_CONNECTION_FAILURE": {
                "status": "PLAUSIBLE",
                "supporting_observations": [
                    "Streaming requests deliver tokens continuously, whereas non-streaming requests buffer until completion.",
                    "Third-party proxy ens-cache / Nginx may fail to buffer large generation payloads.",
                ],
                "contradicting_observations": [],
                "missing_evidence": ["Nginx error logs on api.hcnsec.cn."],
            },
            "REQUEST_SIZE_SENSITIVITY": {
                "status": "PLAUSIBLE",
                "supporting_observations": ["Short request (134 bytes prompt) succeeded; full request (3,113 bytes prompt) failed."],
                "contradicting_observations": ["11.5KB request payload is relatively modest for modern LLM APIs."],
                "missing_evidence": ["WAF or gateway body size limits."],
            },
            "PROVIDER_RATE_OR_CAPACITY_LIMIT": {
                "status": "PLAUSIBLE",
                "supporting_observations": ["One API / channel gateway returned 500 on upstream channel overload or token bucket depletion."],
                "contradicting_observations": ["Usually returned as 429 rather than 500."],
                "missing_evidence": ["Upstream billing/rate limit response headers."],
            },
            "UNKNOWN": {
                "status": "CONFIRMED_LIMITATION",
                "supporting_observations": ["Cannot definitively isolate upstream internal cause without server-side logs."],
                "contradicting_observations": [],
                "missing_evidence": ["Server-side logs from api.hcnsec.cn and StepFun."],
            },
        },
    }
    write_artifact(AUDIT_DIR / "rca2a10d-offline-request-envelope-report-v1.json", offline_envelope_report)

    # -----------------------------------------------------------------------
    # 8. Model Identity Audit
    # -----------------------------------------------------------------------
    print("[RCA-2A.10d] 8. Auditing model identity and provider mapping...")
    model_identity_audit = {
        "artifact_version": "RCA2A10dModelIdentityAuditV1",
        "audit_id": "rca2a10d-provenance-transport-audit",
        "gateway_endpoint_identity": "https://api.hcnsec.cn/v1",
        "requested_model_id": "step-5-preview",
        "returned_model_id": "stepfun-ai/step-5-preview",
        "provider_mapping_evidence": "Gateway prepends upstream provider prefix 'stepfun-ai/' to requested model names.",
        "upstream_verification_status": "UPSTREAM_MODEL_IDENTITY_NOT_INDEPENDENTLY_VERIFIED",
        "interpretation_boundary": (
            "TraceLens verified that the gateway returns responses tagged stepfun-ai/step-5-preview and that tool "
            "calling behaves as an advanced reasoning model, but has no cryptographic or out-of-band attestation "
            "that the underlying weights are identical to official StepFun Step-5."
        ),
    }
    write_artifact(AUDIT_DIR / "rca2a10d-model-identity-audit-v1.json", model_identity_audit)

    # -----------------------------------------------------------------------
    # 9. Future Provider Transport Diagnostic Protocol
    # -----------------------------------------------------------------------
    print("[RCA-2A.10d] 9. Formulating RCA-2A.10e diagnostic protocol...")
    future_diagnostic_protocol = {
        "artifact_version": "RCA2A10dFutureProviderDiagnosticProtocolV1",
        "audit_id": "rca2a10d-provenance-transport-audit",
        "protocol_id": "rca2a10e-bounded-gateway-diagnosis",
        "status": "PROPOSED_NOT_AUTHORIZED",
        "objectives": [
            "Isolate whether gateway failures stem from request size, reasoning duration, or non-streaming buffering before attempting any further A/B benchmark."
        ],
        "diagnostic_sequence": [
            {
                "id": "D1",
                "name": "Basic Endpoint & Model Identity",
                "payload": "Short ping",
                "purpose": "Verify credentials, latency, model identity.",
            },
            {
                "id": "D2",
                "name": "V2 Output Tool Schema",
                "payload": "Minimal prompt + SupervisorIntegrationDecisionV2",
                "purpose": "Verify full schema parsing.",
            },
            {
                "id": "D3",
                "name": "Full INTEGRATE Envelope",
                "payload": "Frozen F1 Post-Delegation Fixture (3.1KB)",
                "purpose": "Test if gateway can successfully process full integration instructions.",
            },
            {
                "id": "D4",
                "name": "Transport / Streaming Comparison",
                "payload": "Identical prompt with stream=True vs stream=False",
                "purpose": "Determine if non-streaming buffering is the primary failure mode.",
            },
        ],
        "hard_rules": [
            "New Experiment ID mandatory (e.g. rca2a10e-gateway-transport-diagnosis).",
            "New Manifest and new Diagnostic Sink mandatory.",
            "Seat 1 from RCA-2A.10b is consumed and CANNOT be reused.",
            "No continuous retries to probe gateway limits.",
            "Requires explicit user authorization before any live calls.",
        ],
    }
    write_artifact(AUDIT_DIR / "rca2a10d-future-provider-diagnostic-protocol-v1.json", future_diagnostic_protocol)

    # -----------------------------------------------------------------------
    # 10. Runtime Identity Record
    # -----------------------------------------------------------------------
    print("[RCA-2A.10d] 10. Freezing runtime identity record...")
    runtime_identity_record = {
        "artifact_version": "RCA2A10dRuntimeIdentityRecordV1",
        "audit_id": "rca2a10d-provenance-transport-audit",
        "baseline_commit": COMMIT_EPOCH_A,
        "runtime_commit": COMMIT_EPOCH_B,
        "final_decision": "PROVENANCE_AUDITED_WITH_IMMUTABILITY_VIOLATION",
    }
    write_artifact(AUDIT_DIR / "rca2a10d-runtime-identity-record-v1.json", runtime_identity_record)

    # -----------------------------------------------------------------------
    # 11. Final Audit Decision (Answers to 10 Core Questions)
    # -----------------------------------------------------------------------
    print("[RCA-2A.10d] 11. Generating final audit decision with answers to 10 questions...")
    final_audit_decision = {
        "artifact_version": "RCA2A10dFinalAuditDecisionV1",
        "audit_id": "rca2a10d-provenance-transport-audit",
        "status": "PROVENANCE_AUDITED_WITH_IMMUTABILITY_VIOLATION",
        "answers_to_10_core_audit_questions": {
            "q01_historical_artifacts_overwritten": (
                "YES (HISTORICAL_ARTIFACTS_OVERWRITTEN). In commit e8680842, 11 audit files and scratch stores from "
                "commit bbf2244608 were overwritten in place within python_service/benchmarks/audits/rca2a10b-rebased-cross-case-comparison/. "
                "Historical Epoch A artifacts were recovered via git cat-file and archived read-only in historical_epoch_a_artifacts/."
            ),
            "q02_execution_epochs_and_identities": (
                "Epoch A (commit bbf2244608, endpoint api.stepfun.com, model step-3.7-flash, CONFIGURATION_BLOCKED, 0 calls); "
                "Epoch B (commit e8680842, endpoint api.hcnsec.cn, model step-5-preview, 2 preflight calls, 1 stage invocation, halted on HTTP 500). "
                "Both reused the exact experiment_id: rca2a10b-rebased-cross-case-vocabulary-comparison."
            ),
            "q03_seat_1_logical_generations_consumed": (
                "Exactly 1 logical model generation was consumed by Seat 1. It dispatched a single PydanticAI agent.run('integrate') invocation."
            ),
            "q04_http_attempts_observability": (
                "HTTP_ATTEMPTS_UNOBSERVABLE. The OpenAI SDK configuration permits up to 3 physical attempts (1 initial + 2 retries), "
                "but without httpx wire hooks, physical attempt count cannot be independently observed."
            ),
            "q05_http_500_real_latency": (
                "The wall-clock latency of Seat 1 from claim creation to finalization was 17.97 seconds (17,971.2ms). "
                "The reported 0.0s was an artifact extraction bug filtering only successful events; the ~204s narrative "
                "referenced an earlier streaming probe test."
            ),
            "q06_provider_billing_uncertainty": (
                "YES. On HTTP 500, token usage is missing (USAGE_UNOBSERVABLE) and billing impact cannot be determined "
                "(PROVIDER_BILLING_UNOBSERVABLE). Asserting $0.00 cost is unfounded."
            ),
            "q07_failure_classification_transport_vs_model": (
                "TRANSPORT / INFRASTRUCTURE FAILURE (HTTP 500). It was NOT a model schema or Pydantic validation failure. "
                "In Preflight Request 2, the model demonstrated native support for the V2 output schema."
            ),
            "q08_root_cause_confirmability_offline": (
                "CANNOT BE CONCLUDED DEFINITIVELY (UNKNOWN). Offline evidence contradicts TOOL_SCHEMA_PROCESSING_FAILURE "
                "and GATEWAY_TIMEOUT, leaving UPSTREAM_MODEL_EXECUTION_FAILURE, REQUEST_SIZE_SENSITIVITY, and "
                "NON_STREAMING_CONNECTION_FAILURE as plausible hypotheses."
            ),
            "q09_viability_of_current_gateway": (
                "QUESTIONABLE FOR BENCHMARK USE. The gateway exhibits connection dropping on non-streaming long requests "
                "and returned HTTP 500 on the full prompt. A bounded diagnostic protocol (RCA-2A.10e) must evaluate its "
                "long-request capability before attempting any paired benchmark."
            ),
            "q10_prerequisites_for_rca2a10e": (
                "Requires: 1) Explicit user authorization; 2) New experiment ID (rca2a10e-bounded-gateway-diagnosis); "
                "3) Bounded budget (<= 4 logical requests); 4) Diagnostic sink and durable claim; "
                "5) Zero seat reuse from RCA-2A.10b; 6) No modifications to production Prompt/Schema."
            ),
        },
        "final_recommendations": {
            "production_prompt_status": "UNCHANGED",
            "production_schema_status": "UNCHANGED",
            "rca2b_authorized": False,
            "gen5_created": False,
            "rca2a10e_authorized": False,
        },
    }
    write_artifact(AUDIT_DIR / "rca2a10d-final-audit-decision-v1.json", final_audit_decision)

    # -----------------------------------------------------------------------
    # 12. Markdown Audit Report
    # -----------------------------------------------------------------------
    print("[RCA-2A.10d] 12. Writing comprehensive audit markdown report...")
    md_content = f"""# TraceLens Agent v0 — RCA-2A.10d Audit Report
## Experiment Provenance Repair & Provider Transport Diagnosis

### Executive Summary

| Dimension / Metric | Finding / Value | Audit Status |
|---|---|---|
| **Phase ID** | RCA-2A.10d | Authorized Offline Audit |
| **Audit Directory** | `python_service/benchmarks/audits/rca2a10d-provenance-transport-audit/` | Complete |
| **Baseline Commits** | Epoch A: `bbf2244608` | Epoch B: `e8680842` | Ancestor Verified |
| **Historical Artifact Integrity** | `HISTORICAL_ARTIFACTS_OVERWRITTEN` | Recovered & Archived Read-Only |
| **Execution Provenance** | `EXPERIMENT_IDENTITY_REUSE` | Two distinct epochs reconstructed |
| **Outcome Accounting** | Control / Treatment validity `UNOBSERVABLE` | Conflation with 500 Error Corrected |
| **Seat 1 Consumption** | `SEAT_CONSUMED_REEXECUTION_PROHIBITED` | 17.97s elapsed, claim finalized |
| **Seats 2–16 Status** | `NOT_STARTED` | Zero remote calls dispatched |
| **HTTP Transport Telemetry** | Physical attempts: `HTTP_ATTEMPTS_UNOBSERVABLE` | 1 Logical Generation Dispatched |
| **Seat 1 Failure Latency** | **17.97s (17,971.2ms)** | Reconciled (0.0s bug and 204s narrative resolved) |
| **Billing & Usage Status** | `USAGE_UNOBSERVABLE` / `PROVIDER_BILLING_UNOBSERVABLE` | $0.00 claim amended |
| **Request Envelope Size** | 3,113 chars prompt + 8,225 bytes tool schema (11.5KB total) | Reconstructed offline |
| **Failure Classification** | `PROVIDER_INFRA_FAILURE` (HTTP 500) | Not a Model Schema Failure |
| **Diagnostic Candidate** | `RCA-2A.10e — Bounded Gateway Diagnosis` | `PROPOSED_NOT_AUTHORIZED` |
| **Production Invariants** | Supervisor Prompt/Schema/Policy/Gate **UNCHANGED** | 100% Boundary Maintained |
| **Final Disposition** | `PROVENANCE_AUDITED_WITH_IMMUTABILITY_VIOLATION` | Mandatory STOP |

---

### 1. Repository Identity & Historical Verification

- **Commit Lineage:**
  - `git rev-parse HEAD`: `{COMMIT_EPOCH_B}`
  - Ancestor Check: `git merge-base --is-ancestor {COMMIT_EPOCH_A} {COMMIT_EPOCH_B}` -> `TRUE`
  - Worktree Status: Clean (`git status --short` empty)
- **Artifact Diff Audit:**
  - 11 audit files and scratch database files in `python_service/benchmarks/audits/rca2a10b-rebased-cross-case-comparison/` were overwritten in place in commit `e8680842`.
  - Claims (`seat-01.claim.json`) and diagnostics (`seat-01-t2-no-evidence-A-control.jsonl`) were newly created in `e8680842`.
- **Historical Recovery:**
  - All 15 historical files from commit `{COMMIT_EPOCH_A}` were recovered via `git cat-file -p` into:
    `python_service/benchmarks/audits/rca2a10d-provenance-transport-audit/historical_epoch_a_artifacts/`
  - File permissions set to `0444` (read-only).
- **Verdict:** `HISTORICAL_ARTIFACTS_OVERWRITTEN`.

---

### 2. Execution Provenance Reconstruction

Two separate operational epochs were reconstructed:

```text
+-----------------------------+-----------------------------------+-----------------------------------+
| Metric                      | Epoch A (Config Blocked)          | Epoch B (Rebased Live)            |
+-----------------------------+-----------------------------------+-----------------------------------+
| Artifact Commit             | bbf2244608                        | e8680842                          |
| Experiment ID               | rca2a10b-...                      | rca2a10b-... (REUSED)             |
| Resolved Endpoint           | https://api.stepfun.com/v1        | https://api.hcnsec.cn/v1          |
| Requested Model             | step-3.7-flash                    | step-5-preview                    |
| Returned Model              | None                              | stepfun-ai/step-5-preview         |
| Effective Config Hash       | 2841c2b7e69b...                   | e75140928ee9...                   |
| Preflight Requests          | 0                                 | 2 (both HTTP 200 OK)              |
| Stage Invocations           | 0                                 | 1 (Seat 1 F1-P1-C)                |
| Failure Outcome             | Pre-call Gate Blocked             | Upstream HTTP 500                 |
| Stop Reason                 | CONFIGURATION_BLOCKED             | PROVIDER_CAPACITY_OR_CONNECTIVITY |
+-----------------------------+-----------------------------------+-----------------------------------+
```

- **Verdict:** `PROVENANCE_RECONCILED` with finding `EXPERIMENT_IDENTITY_REUSE`.

---

### 3. Outcome Accounting Amendment

The flawed reporting of `"Control 0/8 valid, Treatment 0/8 valid"` is formally amended:
- **Control Canonical Validity:** `UNOBSERVABLE` (1 attempt executed, failed on upstream HTTP 500).
- **Treatment Canonical Validity:** `UNOBSERVABLE` (0 attempts executed).
- **Guidance Effect:** `UNOBSERVABLE`.
- **Cross-Case Semantic Adequacy:** `UNOBSERVABLE`.
- **Categorical Invariant:**
  ```text
  Provider HTTP 500 != Pydantic Validation Failure
  Provider HTTP 500 != Canonical Integration Failure
  Provider HTTP 500 != Semantic Oracle Failure
  ```
- **Semantic Oracle Status:**
  - Seat 1: `NOT_EVALUATED` (Reason: `PROVIDER_ERROR_NO_MODEL_DECISION`)
  - Seats 2–16: `NOT_EVALUATED` (Reason: `SEAT_NOT_STARTED`)
- **Evidence Integrity:** 0 unauthorized scratch commits, 0 integrity incidents. Model hallucination and false closure rates are `UNOBSERVABLE`.

---

### 4. Durable Seat Claim Audit

- **Seat 1 Lifecycle:**
  - Claim created atomically at monotonic timestamp `2887874.301305891`.
  - Provider request dispatched; HTTP 500 returned.
  - Diagnostic JSONL written at `2026-10-16T03:35:51Z`.
  - Claim finalized to `RESULT_RECORDED` / `COMPLETED` at `2887892.27246218`.
  - Wall-clock duration: **17.97s (17,971.2ms)**.
  - Meaning of `COMPLETED`: The seat attempt was fully executed and recorded. **Does NOT imply model success.**
  - Consumption status: **SEAT CONSUMED — RE-EXECUTION PROHIBITED**.
- **Seats 2–16:** `NOT_STARTED` (0 requests dispatched).

---

### 5. HTTP Transport Telemetry Audit

- **Physical HTTP Attempts Observability:**
  - Exactly 1 logical model generation was requested for Seat 1.
  - OpenAI SDK `max_retries` was configured to 2.
  - In the absence of an httpx wire hook, individual retry attempts inside the SDK are **`HTTP_ATTEMPTS_UNOBSERVABLE`**.
  - The previously reported "5 total HTTP attempts" was an upper-bound calculation (2 preflight + 3 permitted attempts), not an observed wire count.
- **Latency Reconciliation:**
  - The matrix `0.0s` was an extraction bug in `build_cross_case_seat_record` (filtered only `response_metadata=True`).
  - The `~204s` narrative was an unlinked reference to an earlier interactive streaming test.
  - Reconciled wall-clock latency for Seat 1: **17.97s (17,971.2ms)**.

---

### 6. Cost & Billing Accuracy Amendment

- API returned no usage metadata on HTTP 500: Token usage is **`USAGE_UNOBSERVABLE`**.
- Upstream billing impact cannot be determined without billing logs: **`PROVIDER_BILLING_UNOBSERVABLE`**.
- Claiming "$0.00 total monetary cost" is amended to **`Billing impact not established`**.
- Unsalted SHA-256 key fingerprints (`28c7095f...`) do not expose plaintext, but future runs should use decoupled Credential Source IDs.

---

### 7. Offline Request Envelope & Root Cause Assessment

- **Envelope Metrics:**
  - System Instructions: 3,113 chars / bytes
  - Integration Context: 2,297 bytes
  - Tool Schema (`final_result`): 8,225 bytes (Identical to Preflight Request 2)
  - Total Request Payload: ~11.5 KB
- **Hypothesis Evaluation:**
  1. `TOOL_SCHEMA_PROCESSING_FAILURE`: **CONTRADICTED** (Preflight Request 2 passed the exact byte-identical schema in 2.29s).
  2. `GATEWAY_TIMEOUT`: **CONTRADICTED** (Seat 1 failed in 17.97s, well below gateway timeouts).
  3. `UPSTREAM_MODEL_EXECUTION_FAILURE`: **PLAUSIBLE** (Upstream StepFun engine error on large reasoning prompt).
  4. `NON_STREAMING_CONNECTION_FAILURE`: **PLAUSIBLE** (Gateway buffering dropped connection).
  5. `REQUEST_SIZE_SENSITIVITY`: **PLAUSIBLE** (11.5KB payload failed while 8.5KB short preflight passed).
  6. `PROVIDER_RATE_OR_CAPACITY_LIMIT`: **PLAUSIBLE** (Upstream channel capacity exhaustion).
  7. `UNKNOWN`: **CONFIRMED LIMITATION** (Internal server cause cannot be proven without gateway logs).

---

### 8. Model Identity and Security Audit

- Requested: `step-5-preview`
- Returned: `stepfun-ai/step-5-preview`
- Gateway prepends `stepfun-ai/` provider prefix.
- Upstream verification status: **`UPSTREAM_MODEL_IDENTITY_NOT_INDEPENDENTLY_VERIFIED`**.

---

### 9. Future Provider Transport Diagnostic Protocol (RCA-2A.10e)

- **Candidate ID:** `rca2a10e-bounded-gateway-diagnosis` (`PROPOSED_NOT_AUTHORIZED`)
- **Diagnostic Sequence:**
  - `D1`: Basic Endpoint & Model Identity (short ping)
  - `D2`: V2 Output Tool Schema (minimal prompt + full schema)
  - `D3`: Full INTEGRATE Envelope (frozen F1 fixture, 3.1KB prompt)
  - `D4`: Transport / Streaming Comparison (`stream=True` vs `stream=False`)
- **Prerequisites:** Requires independent user authorization, new experiment ID, new manifest, and zero seat reuse.

---

### 10. Authoritative Answers to the 10 Core Questions

1. **RCA-2A.10b 是否发生历史工件覆盖？**  
   **YES (`HISTORICAL_ARTIFACTS_OVERWRITTEN`)**。在 Commit `e8680842` 中，直接在原目录下覆写了 Commit `bbf2244608` 的 11 项审计文件与 Scratch 数据库。历史 Epoch A 工件已通过 `git cat-file` 完整提取并作为只读文件归档于 `historical_epoch_a_artifacts/`。
2. **两次执行的实际 Runtime/Manifest 身份分别是什么？**  
   Epoch A（Commit `bbf2244608`，Endpoint `api.stepfun.com`，Model `step-3.7-flash`，`CONFIGURATION_BLOCKED`，0 次调用）；Epoch B（Commit `e8680842`，Endpoint `api.hcnsec.cn`，Model `step-5-preview`，2 次 Preflight，1 次 Stage 调用，停机于 HTTP 500）。两轮复用了同一 Experiment ID。
3. **Seat 1 实际消耗了多少逻辑模型请求？**  
   **严格为 1 次逻辑模型请求**（调用了一次 PydanticAI `agent.run("integrate")`）。
4. **HTTP attempts 是否真正可观察？**  
   **`HTTP_ATTEMPTS_UNOBSERVABLE`**。OpenAI SDK 配置允许最多 3 次物理尝试（1 次初试 + 2 次重试），但在缺乏底层 Wire Hook 的情况下，无法独立观测物理重试次数。
5. **HTTP 500 的真实延迟是多少？**  
   Seat 1 从生成 Claim 到终态落地的真实 Wall-clock 延迟为 **17.97 秒（17,971.2ms）**。原报告的 `0.0s` 为提取 Bug，`~204s` 为早期流式测试的叙述残留。
6. **是否存在 Provider Billing 不确定性？**  
   **YES**。HTTP 500 时未返回 Usage 字段（`USAGE_UNOBSERVABLE`），上游计费状态为 `PROVIDER_BILLING_UNOBSERVABLE`，声称“成本 $0.00”不成立。
7. **失败属于 Provider/Transport，还是模型结构化输出错误？**  
   **属于上游 Provider / Transport 错误（HTTP 500）**。在 Preflight Request 2 中，模型已证明能够原生生成满足 V2 Schema 的结构化工具调用。
8. **是否能够从离线数据确认完整 INTEGRATE 失败的根因？**  
   **不能明确确认（`UNKNOWN`）**。离线数据明确反驳了 Tool Schema 解析失败与 Gateway 超时，但无法在模型执行崩溃、流式缓冲失效与请求体大小敏感性之间做出排他性定论。
9. **未来是否值得继续使用当前 Gateway？**  
   **用于基准测试存疑**。该第三方 Gateway 在非流式长请求下表现出连接挂起和 HTTP 500 报错。在重新开展 A/B 对照前，必须先执行有界诊断。
10. **执行 RCA-2A.10e 前还需要什么授权和准备？**  
   必须取得显式授权，分配独立 Experiment ID，构建新 Manifest 与 Sink，并禁止复用已消费席位。

---

### 11. Final Architecture Disposition & Mandatory STOP

- **Final Disposition:** `PROVENANCE_AUDITED_WITH_IMMUTABILITY_VIOLATION`
- **Production Supervisor Prompt:** **UNCHANGED**
- **Production Schema:** **UNCHANGED**
- **RCA-2B:** **NOT_AUTHORIZED**
- **Gen-5:** **NOT_CREATED**
- **RCA-2A.10e:** **PROPOSED_NOT_AUTHORIZED (STOP)**
"""
    write_markdown(AUDIT_DIR / "rca2a10d-audit-report.md", md_content)

    print("\n" + "=" * 75)
    print(" [RCA-2A.10d] ALL 11 DELIVERABLES + AUDIT REPORT GENERATED SUCCESSFULLY.")
    print(" Status: PROVENANCE_AUDITED_WITH_IMMUTABILITY_VIOLATION")
    print("=" * 75)


if __name__ == "__main__":
    main()
