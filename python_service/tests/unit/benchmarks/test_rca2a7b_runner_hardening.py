"""Tests for RCA-2A.7b Runner Hardening, Diagnostic Sink Idempotency, and Parity Closure."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "benchmarks/audits/rca2a7b-runner-hardening/diagnostic_sink_hardening.py"
import sys
SPEC = importlib.util.spec_from_file_location("diagnostic_sink_hardening", MODULE_PATH)
sink_mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sink_mod
assert SPEC and SPEC.loader
SPEC.loader.exec_module(sink_mod)

PARITY_PATH = ROOT / "benchmarks/audits/rca2a7b-runner-hardening/cross_arm_parity.py"
PARITY_SPEC = importlib.util.spec_from_file_location("cross_arm_parity", PARITY_PATH)
parity_mod = importlib.util.module_from_spec(PARITY_SPEC)
sys.modules[PARITY_SPEC.name] = parity_mod
assert PARITY_SPEC and PARITY_SPEC.loader
PARITY_SPEC.loader.exec_module(parity_mod)

RUNNER_PATH = ROOT / "benchmarks/audits/rca2a7b-runner-hardening/runner.py"
RUNNER_SPEC = importlib.util.spec_from_file_location("runner", RUNNER_PATH)
runner_mod = importlib.util.module_from_spec(RUNNER_SPEC)
sys.modules[RUNNER_SPEC.name] = runner_mod
assert RUNNER_SPEC and RUNNER_SPEC.loader
RUNNER_SPEC.loader.exec_module(runner_mod)

SIM_PATH = ROOT / "benchmarks/audits/rca2a7b-runner-hardening/simulation.py"
SIM_SPEC = importlib.util.spec_from_file_location("simulation", SIM_PATH)
sim_mod = importlib.util.module_from_spec(SIM_SPEC)
sys.modules[SIM_SPEC.name] = sim_mod
assert SIM_SPEC and SIM_SPEC.loader
SIM_SPEC.loader.exec_module(sim_mod)

create_exclusive_diagnostic_sink = sink_mod.create_exclusive_diagnostic_sink
read_and_validate_sink_entries = sink_mod.read_and_validate_sink_entries
execute_or_verify_readiness_probe = sink_mod.execute_or_verify_readiness_probe
DiagnosticSinkError = sink_mod.DiagnosticSinkError
DiagnosticSinkCollisionError = sink_mod.DiagnosticSinkCollisionError
DiagnosticSinkWriteError = sink_mod.DiagnosticSinkWriteError
DiagnosticDataQualityError = sink_mod.DiagnosticDataQualityError
ProbeVerificationResult = sink_mod.ProbeVerificationResult

audit_historical_rca2a7_cross_arm_differences = parity_mod.audit_historical_rca2a7_cross_arm_differences
build_cloned_pair_fixtures = parity_mod.build_cloned_pair_fixtures
verify_pair_parity = parity_mod.verify_pair_parity

NetworkSpy = sim_mod.NetworkSpy
simulate_e1_all_legal = sim_mod.simulate_e1_all_legal
simulate_e2_retry_success = sim_mod.simulate_e2_retry_success
simulate_e3_retry_exhausted = sim_mod.simulate_e3_retry_exhausted
simulate_e4_policy_fail = sim_mod.simulate_e4_policy_fail
simulate_e5_provider_timeout = sim_mod.simulate_e5_provider_timeout
simulate_e6_provider_429 = sim_mod.simulate_e6_provider_429
simulate_e7_model_identity_mismatch = sim_mod.simulate_e7_model_identity_mismatch
simulate_e8_diagnostic_sink_failure = sim_mod.simulate_e8_diagnostic_sink_failure
simulate_e9_fabricated_handle = sim_mod.simulate_e9_fabricated_handle
simulate_e10_identity_drift = sim_mod.simulate_e10_identity_drift
simulate_e11_scratch_commit_failure = sim_mod.simulate_e11_scratch_commit_failure
simulate_e12_unexpected_runner_exception = sim_mod.simulate_e12_unexpected_runner_exception
simulate_e13_duplicate_seat_execution = sim_mod.simulate_e13_duplicate_seat_execution
simulate_e14_mid_run_interruption = sim_mod.simulate_e14_mid_run_interruption
compute_paired_metrics = runner_mod.compute_paired_metrics


def _make_sample_entry(
    stage: str = "SUPERVISOR_INTEGRATE",
    schema_hash: str = "a214ec4f5e81fcbb",
    tool_name: str = "final_result",
    extra: dict | None = None,
) -> dict:
    base = {
        "ts": "2026-10-15T12:00:00+00:00",
        "stage": stage,
        "normalized_failure_code": "model_output_retry_exhausted",
        "classified": True,
        "exception_class": "UnexpectedModelBehavior",
        "exception_module": "pydantic_ai.exceptions",
        "cause_class_chain": ["pydantic_core._pydantic_core.ValidationError"],
        "provider_status": None,
        "retry_attempts": 1,
        "validation_error_details": [
            {"type": "enum", "loc": ["actions", "0", "UpdateQuestionActionV2", "to_status"]}
        ],
        "schema_hash": schema_hash,
        "tool_name": tool_name,
        "context": {"run_id": "run_test123"},
    }
    if extra:
        base.update(extra)
    return base


def test_s1_first_probe(tmp_path: Path):
    """S1: First probe creates sink exclusively (0600) and writes exactly 1 record."""
    sink_path = tmp_path / "probe_s1.jsonl"
    probe_id = "probe-pair-01-c"

    def probe_fn(sink):
        sink.record_failure(_make_sample_entry())

    res = execute_or_verify_readiness_probe(sink_path, probe_id, probe_fn)

    assert res.mode == "CREATED_AND_RECORDED"
    assert res.passed is True
    assert res.entries_count == 1
    assert res.sink_mode_octal == "0o600"
    assert sink_path.exists()

    lines = sink_path.read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["stage"] == "SUPERVISOR_INTEGRATE"


def test_s2_repeated_probe_identity(tmp_path: Path):
    """S2: Repeated probe identity does not append duplicate line; remains idempotent."""
    sink_path = tmp_path / "probe_s2.jsonl"
    probe_id = "probe-pair-02-t"

    call_count = 0

    def probe_fn(sink):
        nonlocal call_count
        call_count += 1
        sink.record_failure(_make_sample_entry())

    # First call
    res1 = execute_or_verify_readiness_probe(sink_path, probe_id, probe_fn)
    assert res1.mode == "CREATED_AND_RECORDED"
    assert call_count == 1

    # Second call (repeated probe identity)
    res2 = execute_or_verify_readiness_probe(sink_path, probe_id, probe_fn)
    assert res2.mode == "VERIFIED_EXISTING_READONLY"
    assert res2.passed is True
    assert res2.entries_count == 1
    assert call_count == 1  # probe_fn was NOT called again!

    lines = sink_path.read_text().splitlines()
    assert len(lines) == 1  # Still exactly 1 line, no duplicate!


def test_s3_interrupted_gate_recovery(tmp_path: Path):
    """S3: Interrupted gate recovery verifies existing artifacts without appending."""
    sink_path = tmp_path / "probe_s3.jsonl"
    sink = create_exclusive_diagnostic_sink(sink_path)
    entry = _make_sample_entry()
    sink.record_failure(entry)

    # Simulate resuming gate
    def probe_fn(_):
        pytest.fail("probe_fn must not be called during recovery")

    res = execute_or_verify_readiness_probe(sink_path, "probe-pair-03-c", probe_fn)
    assert res.mode == "VERIFIED_EXISTING_READONLY"
    assert res.passed is True
    assert res.entries_count == 1
    assert res.details["appended_new_lines"] is False


def test_s4_existing_sink_read_only_verification(tmp_path: Path):
    """S4: Existing sink read-only verification validates fields and rejects invalid schema."""
    sink_path = tmp_path / "probe_s4.jsonl"
    sink = create_exclusive_diagnostic_sink(sink_path)
    # Write invalid schema entry
    sink.record_failure(_make_sample_entry(schema_hash="invalid_hash"))

    with pytest.raises(DiagnosticDataQualityError, match="SINK_SCHEMA_HASH_MISMATCH"):
        read_and_validate_sink_entries(sink_path)


def test_s5_exclusive_create_collision(tmp_path: Path):
    """S5: Exclusive create collision raises DiagnosticSinkCollisionError."""
    sink_path = tmp_path / "probe_s5.jsonl"
    sink_path.write_text("existing\n")

    with pytest.raises(DiagnosticSinkCollisionError, match="SINK_EXISTS_COLLISION"):
        create_exclusive_diagnostic_sink(sink_path)


def test_s6_sink_write_failure(tmp_path: Path):
    """S6: Corrupted JSON or empty sink fails loudly as data quality failure."""
    sink_path = tmp_path / "probe_s6.jsonl"
    sink_path.touch(mode=0o600)
    os.chmod(sink_path, 0o600)

    # Empty sink
    with pytest.raises(DiagnosticDataQualityError, match="SINK_EMPTY"):
        read_and_validate_sink_entries(sink_path)

    # Corrupt JSON line
    sink_path.write_text("NOT_VALID_JSON\n")
    with pytest.raises(DiagnosticDataQualityError, match="SINK_CORRUPT_JSON"):
        read_and_validate_sink_entries(sink_path)


def test_s7_valid_model_retry_emits_distinct_observations(tmp_path: Path):
    """S7: Legitimate model retries in an execution sink record distinct observations."""
    sink_path = tmp_path / "execution_s7.jsonl"
    sink = create_exclusive_diagnostic_sink(sink_path)

    attempt1 = _make_sample_entry(extra={"retry_attempts": 0, "ts": "2026-10-15T12:00:01+00:00"})
    attempt2 = _make_sample_entry(extra={"retry_attempts": 1, "ts": "2026-10-15T12:00:02+00:00"})

    sink.record_failure(attempt1)
    sink.record_failure(attempt2)

    entries = read_and_validate_sink_entries(sink_path)
    assert len(entries) == 2
    assert entries[0]["retry_attempts"] == 0
    assert entries[1]["retry_attempts"] == 1
    assert entries[0]["ts"] != entries[1]["ts"]


def test_s8_sanitized_output_and_file_permissions(tmp_path: Path):
    """S8: File permissions are 0600 and raw authorization markers are rejected."""
    sink_path = tmp_path / "probe_s8.jsonl"
    sink = create_exclusive_diagnostic_sink(sink_path)

    mode = sink_path.stat().st_mode & 0o777
    assert mode == 0o600

    # Test rejection of forbidden credential marker
    sink.record_failure({"stage": "SUPERVISOR_INTEGRATE", "schema_hash": "a214ec4f5e81fcbb",
                         "tool_name": "final_result", "validation_error_details": [{"loc": []}],
                         "leak": "Bearer secret_api_key_123"})
    with pytest.raises(DiagnosticDataQualityError, match="SINK_SECURITY_LEAK"):
        read_and_validate_sink_entries(sink_path)


def test_historical_rca2a7_cross_arm_difference_classification():
    """Verify that all historical cross-arm differences in RCA-2A.7 are ephemeral/provenance only."""
    report_path = (
        ROOT
        / "benchmarks/audits/rca2a7-stepfun-vocabulary-comparison/rca2a7-preflight-gate-report-v1.json"
    )
    audit = audit_historical_rca2a7_cross_arm_differences(report_path)

    assert audit["artifact_version"] == "RCA2A7HistoricalCrossArmAuditV1"
    assert len(audit["pairs"]) == 4

    for pair_key, pair_data in audit["pairs"].items():
        assert pair_data["actions_identical"] is True
        assert pair_data["handle_domains_identical"] is True
        assert pair_data["has_semantic_differences"] is False
        assert pair_data["has_unexplained_differences"] is False
        # Every difference must be ALLOWED_EPHEMERAL_IDENTITY or CONTENT_EQUIVALENT_PROVENANCE
        for diff in pair_data["differences"]:
            assert diff["classification"] in (
                "ALLOWED_EPHEMERAL_IDENTITY",
                "CONTENT_EQUIVALENT_PROVENANCE",
            )


@pytest.mark.asyncio
async def test_cloned_pair_cross_arm_parity(tmp_path: Path):
    """Verify that cloned scratch fixtures achieve exact cross-arm canonical parity."""
    h_c, h_t, meta = await build_cloned_pair_fixtures(
        pair_id=1, base_dir=tmp_path / "parity_test", with_evidence=False
    )

    report = await verify_pair_parity(pair_id=1, harness_control=h_c, harness_treatment=h_t)

    assert report["parity_pass"] is True
    assert report["verdict"] == "PARITY_PASS"
    assert report["canonical_control_hash"] == report["canonical_treatment_hash"]
    assert report["instructions_exact_suffix"] is True
    assert report["projection_equal"] is True
    assert report["schema_equal"] is True
    assert report["model_settings_equal"] is True
    assert report["input_contract_equal"] is True
    assert report["schema_hash"] == "a214ec4f5e81fcbb"
    assert report["field_level_differences"] == []
    assert len(report["normalized_identity_mapping"]) > 0


@pytest.mark.asyncio
async def test_e1_simulation_all_legal(tmp_path: Path):
    """E1: All 8 seats legal. 8/8 succeed, commits independent."""
    spy = NetworkSpy()
    matrix = await simulate_e1_all_legal(tmp_path, spy)

    assert matrix["stage_invocations_scheduled"] == 8
    assert matrix["stage_invocations_started"] == 8
    assert matrix["stage_invocations_finished"] == 8
    assert matrix["stage_invocations_executed"] == 8
    assert matrix["logical_model_generations"] == 8
    assert matrix["stop_reason"] is None
    assert matrix["observation_tag"] == "SYNTHETIC_TEST_OBSERVATIONS"

    for seat in matrix["seats"]:
        assert seat["status"] == "EXECUTED"
        assert seat["stage_layers"]["scratch_commit_success"] is True
        assert seat["stage_layers"]["canonical_integration_valid"] is True
        assert seat["evidence_integrity"]["model_generated_evidence_id_accepted"] is False

    metrics = compute_paired_metrics(matrix)
    assert metrics["paired_counts"]["both_valid"] == 4
    assert metrics["total_executed_seats"] == 8
    assert metrics["total_unstarted_seats"] == 0


@pytest.mark.asyncio
async def test_e2_simulation_retry_success(tmp_path: Path):
    """E2: First generation invalid enum, second generation legal. Output retry accounted."""
    spy = NetworkSpy()
    matrix = await simulate_e2_retry_success(tmp_path, spy)

    assert matrix["stage_invocations_executed"] == 8
    # Pair 1 Control retried and succeeded
    c1 = next(x for x in matrix["seats"] if x["pair_id"] == 1 and x["arm"] == "control")
    assert c1["pydantic_output_retries"] == 1
    assert c1["logical_model_generations"] == 2
    assert c1["retry_self_correction"] is True
    assert c1["stage_layers"]["canonical_integration_valid"] is True


@pytest.mark.asyncio
async def test_e3_simulation_retry_exhausted(tmp_path: Path):
    """E3: Output retry exhausted. Schema failure on one arm does not halt experiment."""
    spy = NetworkSpy()
    matrix = await simulate_e3_retry_exhausted(tmp_path, spy)

    assert matrix["stage_invocations_executed"] == 8
    c1 = next(x for x in matrix["seats"] if x["pair_id"] == 1 and x["arm"] == "control")
    assert c1["stage_layers"]["pydantic_parse_success"] is False
    assert c1["stage_layers"]["exception_class"] == "UnexpectedModelBehavior"
    assert c1["pydantic_output_retries"] == 1
    assert c1["logical_model_generations"] == 2

    # Treatment in Pair 1 succeeded
    t1 = next(x for x in matrix["seats"] if x["pair_id"] == 1 and x["arm"] == "treatment")
    assert t1["stage_layers"]["canonical_integration_valid"] is True

    metrics = compute_paired_metrics(matrix)
    assert metrics["paired_counts"]["treatment_win"] == 1


@pytest.mark.asyncio
async def test_e4_simulation_policy_fail(tmp_path: Path):
    """E4: Pydantic PASS, Policy FAIL. Cannot be misrecorded as canonical valid."""
    spy = NetworkSpy()
    matrix = await simulate_e4_policy_fail(tmp_path, spy)

    c1 = next(x for x in matrix["seats"] if x["pair_id"] == 1 and x["arm"] == "control")
    assert c1["stage_layers"]["pydantic_parse_success"] is True
    assert c1["stage_layers"]["transition_validation_success"] is False
    assert c1["stage_layers"]["canonical_integration_valid"] is False
    assert c1["stage_layers"]["scratch_commit_success"] is False


@pytest.mark.asyncio
async def test_e5_simulation_provider_timeout(tmp_path: Path):
    """E5: Provider timeout halts remaining seats, recorded with typed attribution."""
    spy = NetworkSpy()
    matrix = await simulate_e5_provider_timeout(tmp_path, spy)

    assert matrix["stop_reason"] == "PROVIDER_CAPACITY_OR_CONNECTIVITY_FAILURE"
    t1 = next(x for x in matrix["seats"] if x["pair_id"] == 1 and x["arm"] == "treatment")
    assert "MockTimeoutError" in t1["provider_error_classes"]
    assert "PROVIDER_TIMEOUT" in t1["provider_error_classifications"]

    # Remaining seats (pair 2, 3, 4) unstarted
    unstarted = [x for x in matrix["seats"] if x["status"] == "NOT_STARTED"]
    assert len(unstarted) == 6
    for s in unstarted:
        assert s["logical_model_generations"] == 0


@pytest.mark.asyncio
async def test_e6_simulation_provider_429(tmp_path: Path):
    """E6: Provider 429 rate limit halts remaining seats."""
    spy = NetworkSpy()
    matrix = await simulate_e6_provider_429(tmp_path, spy)

    assert matrix["stop_reason"] == "PROVIDER_CAPACITY_OR_CONNECTIVITY_FAILURE"
    c1 = next(x for x in matrix["seats"] if x["pair_id"] == 1 and x["arm"] == "control")
    assert "MockRateLimitError" in c1["provider_error_classes"]
    assert "PROVIDER_QUOTA_BLOCKED" in c1["provider_error_classifications"]


@pytest.mark.asyncio
async def test_e7_simulation_model_identity_mismatch(tmp_path: Path):
    """E7: Model identity mismatch triggers immediate STOP."""
    spy = NetworkSpy()
    matrix = await simulate_e7_model_identity_mismatch(tmp_path, spy)

    assert matrix["stop_reason"] == "MODEL_IDENTITY_MISMATCH"
    c1 = next(x for x in matrix["seats"] if x["pair_id"] == 1 and x["arm"] == "control")
    assert c1["returned_identity_exact"] is False


@pytest.mark.asyncio
async def test_e8_simulation_diagnostic_sink_failure(tmp_path: Path):
    """E8: Diagnostic sink failure causes immediate data quality stop."""
    spy = NetworkSpy()
    matrix = await simulate_e8_diagnostic_sink_failure(tmp_path, spy)

    assert matrix["stop_reason"] == "DIAGNOSTIC_INSTRUMENTATION_FAILURE"


@pytest.mark.asyncio
async def test_e9_simulation_fabricated_handle(tmp_path: Path):
    """E9: Fabricated evidence handle fails closed and stops remaining seats."""
    spy = NetworkSpy()
    matrix = await simulate_e9_fabricated_handle(tmp_path, spy)

    assert matrix["stop_reason"] == "FABRICATED_EVIDENCE_OR_BASIS_HANDLE"
    c1 = next(x for x in matrix["seats"] if x["pair_id"] == 1 and x["arm"] == "control")
    assert c1["field_scan_totals"]["fabricated_evidence_like_identifier"] >= 1


@pytest.mark.asyncio
async def test_e10_simulation_identity_drift(tmp_path: Path):
    """E10: Source identity drift stops before first seat invocation."""
    spy = NetworkSpy()
    matrix = await simulate_e10_identity_drift(tmp_path, spy)

    assert matrix["stop_reason"] == "EXPERIMENT_IDENTITY_DRIFT"
    assert matrix["stage_invocations_started"] == 0
    assert matrix["stage_invocations_executed"] == 0
    assert matrix["logical_model_generations"] == 0


@pytest.mark.asyncio
async def test_e11_simulation_scratch_commit_failure(tmp_path: Path):
    """E11: Scratch commit failure does not report success or pollute other arm."""
    spy = NetworkSpy()
    matrix = await simulate_e11_scratch_commit_failure(tmp_path, spy)

    c1 = next(x for x in matrix["seats"] if x["pair_id"] == 1 and x["arm"] == "control")
    assert c1["stage_layers"]["scratch_commit_success"] is False
    assert c1["stage_layers"]["canonical_integration_valid"] is False


@pytest.mark.asyncio
async def test_e12_simulation_unexpected_runner_exception(tmp_path: Path):
    """E12: Unexpected runner exception recorded as infrastructure failure."""
    spy = NetworkSpy()
    matrix = await simulate_e12_unexpected_runner_exception(tmp_path, spy)

    assert "UNEXPECTED_EXCEPTION" in str(matrix["stop_reason"])


@pytest.mark.asyncio
async def test_e13_simulation_duplicate_seat_execution(tmp_path: Path):
    """E13: Duplicate seat execution prohibited."""
    spy = NetworkSpy()
    matrix = await simulate_e13_duplicate_seat_execution(tmp_path, spy)

    assert matrix["stop_reason"] == "DIAGNOSTIC_INSTRUMENTATION_FAILURE"


@pytest.mark.asyncio
async def test_e14_simulation_mid_run_interruption(tmp_path: Path):
    """E14: Mid-run interruption preserves executed facts; unstarted seats are NOT_STARTED."""
    spy = NetworkSpy()
    matrix = await simulate_e14_mid_run_interruption(tmp_path, spy)

    assert matrix["stop_reason"] == "SIMULATED_INTERRUPTION"
    executed = [x for x in matrix["seats"] if x["status"] == "EXECUTED"]
    unstarted = [x for x in matrix["seats"] if x["status"] == "NOT_STARTED"]
    assert len(executed) == 3
    assert len(unstarted) == 5

    metrics = compute_paired_metrics(matrix)
    assert metrics["paired_counts"]["incomplete_pair"] >= 2


def test_paired_metrics_classification_coverage():
    """Verify paired metrics classification for all outcomes."""
    mock_matrix = {
        "seats": [
            # Pair 1: Treatment win
            {"pair_id": 1, "arm": "control", "status": "EXECUTED", "stage_layers": {"canonical_integration_valid": False}},
            {"pair_id": 1, "arm": "treatment", "status": "EXECUTED", "stage_layers": {"canonical_integration_valid": True}},
            # Pair 2: Control win
            {"pair_id": 2, "arm": "treatment", "status": "EXECUTED", "stage_layers": {"canonical_integration_valid": False}},
            {"pair_id": 2, "arm": "control", "status": "EXECUTED", "stage_layers": {"canonical_integration_valid": True}},
            # Pair 3: Both valid
            {"pair_id": 3, "arm": "treatment", "status": "EXECUTED", "stage_layers": {"canonical_integration_valid": True}},
            {"pair_id": 3, "arm": "control", "status": "EXECUTED", "stage_layers": {"canonical_integration_valid": True}},
            # Pair 4: Both invalid
            {"pair_id": 4, "arm": "control", "status": "EXECUTED", "stage_layers": {"canonical_integration_valid": False}},
            {"pair_id": 4, "arm": "treatment", "status": "EXECUTED", "stage_layers": {"canonical_integration_valid": False}},
        ]
    }
    metrics = compute_paired_metrics(mock_matrix)
    counts = metrics["paired_counts"]
    assert counts["treatment_win"] == 1
    assert counts["control_win"] == 1
    assert counts["both_valid"] == 1
    assert counts["both_invalid"] == 1
    assert counts["incomplete_pair"] == 0


