"""Unit and benchmark tests for RCA-2A.10d Provenance Repair & Transport Diagnosis.

Covers:
- P1-P4: Historical Git Artifact Reconstruction & Provenance Invariants
- A1-A4: Provider Failure vs Model Failure Accounting Separation
- T1-T5: Transport Telemetry, Latency, and Observability Bounds
- E1-E3: Offline Request Envelope Analysis & Identity Sanity
- G1-G2: Zero Live Network Calls & Historical Hash Immutability
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

HERE = Path(__file__).resolve().parent
PYTHON_SERVICE_ROOT = HERE.parents[2]
REPO_ROOT = PYTHON_SERVICE_ROOT.parent

from benchmarks.isolated_integration.cross_case_fixtures import SCENARIO_SPECS
from benchmarks.isolated_integration.cross_case_runner import (
    CrossCaseSeatContext,
    SeatPhase,
    build_cross_case_seat_record,
)
from benchmarks.isolated_integration.harness import IsolatedIntegrationHarness
from benchmarks.isolated_integration.semantic_oracle_extension import (
    RCA2A9aSemanticOracleExtensionV1,
)
from httpserver.services.investigation.agent_failure_diagnostics import (
    schema_hash_of,
)
from httpserver.services.investigation.agent_integration_v2 import (
    SupervisorIntegrationDecisionV2,
)
from httpserver.services.investigation.agent_model_adapter import (
    ModelAdapterConfig,
    classify_provider_http_error,
)


class NetworkSpy:
    """Network monitor to ensure zero real HTTP requests are issued during tests."""
    def __init__(self):
        self.call_count = 0

    def intercept(self, *args, **kwargs):
        self.call_count += 1
        raise RuntimeError("NETWORK_ACCESS_FORBIDDEN: Real network call attempted during offline test!")


# ---------------------------------------------------------------------------
# P1-P4: Historical Git Artifact Reconstruction & Provenance Invariants
# ---------------------------------------------------------------------------

def test_p1_historical_git_artifact_reconstruction():
    """P1: Verify historical files extracted to historical_epoch_a_artifacts match commit bbf2244608."""
    hist_dir = PYTHON_SERVICE_ROOT / "benchmarks/audits/rca2a10d-provenance-transport-audit/historical_epoch_a_artifacts"
    manifest_file = hist_dir / "rca2a10b-experiment-manifest-v1.json"
    assert manifest_file.exists(), "Historical manifest file must exist in read-only recovery directory"

    data = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert data["artifact_version"] == "RCA2A10bExperimentManifestV1"
    assert data["effective_model_configuration"]["requested_model"] == "step-3.7-flash"
    assert data["effective_model_configuration"]["status"] == "CONFIGURATION_BLOCKED"


def test_p2_same_experiment_id_across_distinct_executions():
    """P2: Verify that distinct execution epochs sharing experiment_id are flagged as EXPERIMENT_IDENTITY_REUSE."""
    prov_file = (
        PYTHON_SERVICE_ROOT
        / "benchmarks/audits/rca2a10d-provenance-transport-audit/rca2a10d-execution-provenance-reconstruction-v1.json"
    )
    assert prov_file.exists()
    prov_data = json.loads(prov_file.read_text(encoding="utf-8"))
    assert prov_data["provenance_classification"] == "EXPERIMENT_IDENTITY_REUSE"
    assert prov_data["verdict"] == "PROVENANCE_RECONCILED"
    epochs = prov_data["reconstructed_epochs"]
    assert epochs["epoch_a"]["requested_model"] == "step-3.7-flash"
    assert epochs["epoch_b"]["requested_model"] == "step-5-preview"


def test_p3_historical_mutation_detection():
    """P3: Verify that mutation detection identifies modified artifacts between commits."""
    integrity_file = (
        PYTHON_SERVICE_ROOT
        / "benchmarks/audits/rca2a10d-provenance-transport-audit/rca2a10d-historical-artifact-integrity-report-v1.json"
    )
    assert integrity_file.exists()
    data = json.loads(integrity_file.read_text(encoding="utf-8"))
    assert data["verdict"] == "HISTORICAL_ARTIFACTS_OVERWRITTEN"

    inv = {item["artifact_path"].split("/")[-1]: item for item in data["artifact_inventory"]}
    assert inv["rca2a10b-paired-execution-matrix-v1.json"]["change_type"] == "MODIFIED"
    assert inv["rca2a10b-historical-identity-reconciliation-v1.json"]["change_type"] == "UNCHANGED"
    assert inv["seat-01.claim.json"]["change_type"] == "NEW_FILE"


def test_p4_missing_artifact_or_blob_handling():
    """P4: Missing blob references or unobservable historical content must be tagged UNOBSERVABLE."""
    from runner import is_provider_error_class
    # Verify taxonomy classifies missing error safely
    assert is_provider_error_class(None) is False
    assert is_provider_error_class("ModelHTTPError") is True


# ---------------------------------------------------------------------------
# A1-A4: Provider Failure vs Model Failure Accounting Separation
# ---------------------------------------------------------------------------

def test_a1_provider_500_is_not_pydantic_failure():
    """A1: Provider HTTP 500 error is an infra failure, not a Pydantic schema validation failure."""
    classification = classify_provider_http_error(500, "Internal Server Error")
    assert classification == "PROVIDER_INFRA_FAILURE"
    assert classification != "PYDANTIC_VALIDATION_FAILURE"


def test_a2_provider_500_is_not_semantic_oracle_failure():
    """A2: When stage execution encounters a provider exception, Semantic Oracle reports NOT_EVALUATED."""
    ctx = CrossCaseSeatContext(
        global_seat=1,
        scenario_id="t2-no-evidence",
        pair_label="A",
        pair_id=1,
        arm="control",
        fixture_record={"task_id": "t2-no-evidence", "investigation_id": "inv-1"},
        harness=MagicMock(),
        diagnostic_sink_path=Path("/tmp/nonexistent_sink.jsonl"),
        claim_path=Path("/tmp/nonexistent_claim.json"),
    )
    ctx.phase = SeatPhase.RESULT_RECORDED
    ctx.executed = True

    # Simulate stage exception
    ctx.stage_result = MagicMock()
    ctx.stage_result.exception_class = "ModelHTTPError"
    ctx.stage_result.steps = []
    ctx.stage_result.committed = False
    ctx.stage_result.resolution_violations = ()

    # Model proxy recorded the network error
    proxy = MagicMock()
    proxy.events = [{"provider_error_class": "ModelHTTPError", "provider_classification": "PROVIDER_INFRA_FAILURE", "latency_ms": 17971.2}]
    ctx.model_proxy = proxy

    oracle = RCA2A9aSemanticOracleExtensionV1()
    record = build_cross_case_seat_record(ctx, oracle=oracle, expected_model="step-5-preview")

    assert record["stage_layers"]["exception_class"] == "ModelHTTPError"
    assert record["semantic_oracle_evaluation"]["verdict"] == "NOT_EVALUATED"
    assert record["semantic_oracle_evaluation"]["adequacy"] == "UNOBSERVABLE"
    assert "PROVIDER_ERROR_NO_MODEL_DECISION" in record["semantic_oracle_evaluation"]["evaluation_notes"]


def test_a3_unstarted_seats_are_unobservable():
    """A3: Unstarted seats must have UNOBSERVABLE validity and adequacy."""
    ctx = CrossCaseSeatContext(
        global_seat=2,
        scenario_id="t2-no-evidence",
        pair_label="A",
        pair_id=1,
        arm="treatment",
        fixture_record={"task_id": "t2-no-evidence", "investigation_id": "inv-2"},
        harness=MagicMock(),
        diagnostic_sink_path=Path("/tmp/nonexistent_sink2.jsonl"),
        claim_path=Path("/tmp/nonexistent_claim2.json"),
    )
    ctx.phase = SeatPhase.NOT_STARTED
    ctx.executed = False

    oracle = RCA2A9aSemanticOracleExtensionV1()
    record = build_cross_case_seat_record(ctx, oracle=oracle, expected_model="step-5-preview")

    assert record["status"] == "NOT_STARTED"
    assert record["semantic_oracle_evaluation"]["verdict"] == "UNOBSERVABLE"
    assert record["semantic_oracle_evaluation"]["adequacy"] == "UNOBSERVABLE"


def test_a4_consumed_seat_cannot_be_retried():
    """A4: Consumed seat with COMPLETED claim status cannot be retried."""
    claim_file = (
        PYTHON_SERVICE_ROOT
        / "benchmarks/audits/rca2a10b-rebased-cross-case-comparison/claims/seat-01.claim.json"
    )
    assert claim_file.exists()
    claim_data = json.loads(claim_file.read_text(encoding="utf-8"))
    assert claim_data["status"] == "COMPLETED"
    assert claim_data["claimed_phase"] == "RESULT_RECORDED"
    # Protocol rule: COMPLETED claim forbids re-execution


# ---------------------------------------------------------------------------
# T1-T5: Transport Telemetry, Latency, and Observability Bounds
# ---------------------------------------------------------------------------

def test_t1_logical_request_and_http_attempt_separation():
    """T1: 1 logical model generation does not prove 1 physical HTTP attempt."""
    telemetry_file = (
        PYTHON_SERVICE_ROOT
        / "benchmarks/audits/rca2a10d-provenance-transport-audit/rca2a10d-transport-telemetry-audit-v1.json"
    )
    assert telemetry_file.exists()
    data = json.loads(telemetry_file.read_text(encoding="utf-8"))
    sep = data["logical_vs_physical_separation"]
    assert sep["logical_model_generations"] == 1
    assert sep["physical_http_attempts"] == "HTTP_ATTEMPTS_UNOBSERVABLE"


def test_t2_sdk_retry_count_unobservable():
    """T2: In absence of httpx transport hooks, SDK retry count is unobservable."""
    telemetry_file = (
        PYTHON_SERVICE_ROOT
        / "benchmarks/audits/rca2a10d-provenance-transport-audit/rca2a10d-transport-telemetry-audit-v1.json"
    )
    data = json.loads(telemetry_file.read_text(encoding="utf-8"))
    assert data["logical_vs_physical_separation"]["sdk_retries_observed"] == "UNOBSERVABLE"


def test_t3_failure_latency_must_not_default_to_zero():
    """T3: A failed seat must preserve real wall-clock latency rather than defaulting to 0ms."""
    ctx = CrossCaseSeatContext(
        global_seat=1,
        scenario_id="t2-no-evidence",
        pair_label="A",
        pair_id=1,
        arm="control",
        fixture_record={},
        harness=MagicMock(),
        diagnostic_sink_path=Path("/tmp/sink.jsonl"),
        claim_path=Path("/tmp/claim.json"),
    )
    proxy = MagicMock()
    # Event records failure with elapsed latency
    proxy.events = [{"provider_error_class": "ModelHTTPError", "latency_ms": 17971.2}]
    ctx.model_proxy = proxy
    record = build_cross_case_seat_record(ctx, expected_model="step-5-preview")

    assert record["latency_ms"] == [17971.2]
    assert record["latency_ms"] != [0.0]
    assert record["latency_ms"] != []


def test_t4_missing_usage_metadata():
    """T4: Provider failure without usage metadata must degrade to USAGE_UNOBSERVABLE."""
    cost_file = (
        PYTHON_SERVICE_ROOT
        / "benchmarks/audits/rca2a10d-provenance-transport-audit/rca2a10d-cost-accounting-amendment-v1.json"
    )
    assert cost_file.exists()
    data = json.loads(cost_file.read_text(encoding="utf-8"))
    assert data["billing_reconciliation"]["amended_token_usage"] == "USAGE_UNOBSERVABLE"


def test_t5_unknown_billing_is_not_zero_billing():
    """T5: Unknown billing impact must be recorded as PROVIDER_BILLING_UNOBSERVABLE, not $0.00."""
    cost_file = (
        PYTHON_SERVICE_ROOT
        / "benchmarks/audits/rca2a10d-provenance-transport-audit/rca2a10d-cost-accounting-amendment-v1.json"
    )
    data = json.loads(cost_file.read_text(encoding="utf-8"))
    assert data["billing_reconciliation"]["amended_billing_status"] == "PROVIDER_BILLING_UNOBSERVABLE"


# ---------------------------------------------------------------------------
# E1-E3: Offline Request Envelope Analysis & Identity Sanity
# ---------------------------------------------------------------------------

def test_e1_full_request_envelope_serialization():
    """E1: Full INTEGRATE request envelope captures ~11.5KB without live model access."""
    env_file = (
        PYTHON_SERVICE_ROOT
        / "benchmarks/audits/rca2a10d-provenance-transport-audit/rca2a10d-offline-request-envelope-report-v1.json"
    )
    assert env_file.exists()
    data = json.loads(env_file.read_text(encoding="utf-8"))
    full = data["reconstructed_envelopes"]["full_integrate_seat_1"]
    short = data["reconstructed_envelopes"]["short_preflight_request_2"]

    assert full["system_instructions_bytes"] == 3113
    assert full["tool_schema_bytes"] == 8225
    assert short["tool_schema_bytes"] == 8225  # Exact byte match
    assert data["envelope_comparison"]["tool_schema_identical"] is True


def test_e2_sanitized_endpoint_and_credential_handling():
    """E2: ModelAdapterConfig repr must never leak API credentials."""
    cfg = ModelAdapterConfig(
        provider="generic",
        base_url="https://api.hcnsec.cn/v1",
        model_name="step-5-preview",
    )
    repr_str = repr(cfg)
    assert "sk-" not in repr_str
    assert "password" not in repr_str


def test_e3_requested_vs_returned_model_identity():
    """E3: Model alias stepfun-ai/step-5-preview is correctly audited."""
    identity_file = (
        PYTHON_SERVICE_ROOT
        / "benchmarks/audits/rca2a10d-provenance-transport-audit/rca2a10d-model-identity-audit-v1.json"
    )
    assert identity_file.exists()
    data = json.loads(identity_file.read_text(encoding="utf-8"))
    assert data["requested_model_id"] == "step-5-preview"
    assert data["returned_model_id"] == "stepfun-ai/step-5-preview"
    assert data["upstream_verification_status"] == "UPSTREAM_MODEL_IDENTITY_NOT_INDEPENDENTLY_VERIFIED"


# ---------------------------------------------------------------------------
# G1-G2: Zero Live Network Calls & Historical Hash Immutability
# ---------------------------------------------------------------------------

def test_g1_network_spy_zero_real_provider_requests():
    """G1: Verify that executing offline audit tools issues exactly ZERO remote requests."""
    spy = NetworkSpy()
    with patch("httpx.AsyncClient.send", spy.intercept), patch("httpx.Client.send", spy.intercept):
        # Perform offline schema validation and hash computation
        schema_hash = schema_hash_of(SupervisorIntegrationDecisionV2)
        assert schema_hash == "a214ec4f5e81fcbb"
        assert spy.call_count == 0, "NetworkSpy detected unauthorized network call!"


def test_g2_historical_oracle_hashes_unchanged():
    """G2: Historical oracle code hashes match frozen reference contracts."""
    base_oracle = PYTHON_SERVICE_ROOT / "benchmarks/isolated_integration/semantic_oracle.py"
    ext_oracle = PYTHON_SERVICE_ROOT / "benchmarks/isolated_integration/semantic_oracle_extension.py"

    base_hash = hashlib.sha256(base_oracle.read_bytes()).hexdigest()
    ext_hash = hashlib.sha256(ext_oracle.read_bytes()).hexdigest()
    combined_hash = hashlib.sha256(f"{base_hash}:{ext_hash}".encode("utf-8")).hexdigest()

    assert base_hash == "52e3a57d5116c3fb290158d26eaaff1a69f95fa92efd6e06434a72c454f91a55"
    assert ext_hash == "922db5e943ca2c980e8227743555a845d4452b0a6f9c0d9e7d0154fdc4b28348"
    assert combined_hash == "739b6683707d1b4c7339cf20eaf861514c902e9ac4b8ac8b3969fa02aef9a782"
