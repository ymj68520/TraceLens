"""Deterministic offline test battery for RCA-2A.11 runner simulation (A through P).

Verifies without any real network traffic:
A. 16-seat normal execution
B. Provider failure on seat 1
C. Provider failure after a completed pair
D. Output Retry self-correction
E. Output Retry exhaustion
F. Canonical resolution rejection
G. Semantic Oracle negative gate
H. Stale revision rejection
I. Stale source hash rejection
J. Cross-arm DB isolation
K. Experiment ID collision
L. Crash after durable claim
M. Unknown outcome cannot rerun
N. Runtime identity drift
O. Report Admission not exercised
P. Diagnostic sink write failure
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any
import pytest

from benchmarks.contracts.experimental.integration_vocabulary_guidance_v1 import (
    guidance_sha256,
)
from benchmarks.isolated_integration.cross_case_fixtures import (
    build_cloned_cross_case_pair,
)
from benchmarks.isolated_integration.cross_case_runner import (
    SEAT_SCHEDULE,
    CrossCaseSeatContext,
    compute_cross_case_paired_metrics,
    run_cross_case_seats,
    setup_cross_case_pair_fixtures,
)
from benchmarks.isolated_integration.harness import IsolatedIntegrationHarness
from benchmarks.isolated_integration.rca2a11_cross_case_runner import (
    AUTHORIZED_BASE_ORACLE_HASH,
    AUTHORIZED_BASE_URL,
    AUTHORIZED_BASELINE,
    AUTHORIZED_COMBINED_ORACLE_CONTRACT_HASH,
    AUTHORIZED_EXTENSION_ORACLE_HASH,
    AUTHORIZED_GUIDANCE_HASH,
    AUTHORIZED_MODEL,
    AUTHORIZED_PROVIDER,
    AUTHORIZED_SCHEMA_HASH,
    EXPERIMENT_ID,
    HISTORICAL_EPOCH_A_HASHES,
    HISTORICAL_RCA2A10E_HASHES,
    HISTORICAL_RCA2A10F_HASHES,
    HISTORICAL_RCA2A10G_HASHES,
    RCA2A11CrossCaseOrchestrator,
    verify_effective_config_gate,
    verify_git_clean_ancestor_gate,
    verify_historical_artifact_hashes,
    verify_oracle_contract_gate,
    verify_schema_and_guidance_gate,
)
from benchmarks.isolated_integration.semantic_oracle import (
    NegativeGateCode,
)
from benchmarks.isolated_integration.semantic_oracle_extension import (
    RCA2A9aSemanticOracleExtensionV1,
)
from httpserver.services.investigation.agent_failure_diagnostics import schema_hash_of
from httpserver.services.investigation.agent_finalization import FinalizationGate
from httpserver.services.investigation.agent_integration_v2 import (
    SupervisorIntegrationDecisionV2,
)
from httpserver.services.investigation.agent_supervisor import SupervisorAgentFactory
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from tests.unit.benchmarks.test_rca2a9a_contract_closure import _build_test_env


def _make_fake_valid_response(scenario_id: str, arm: str) -> ModelResponse:
    if scenario_id == "t2-no-evidence":
        payload = {
            "decision_version": "supervisor-integration-decision:v3",
            "actions": [
                {
                    "action_type": "update_question",
                    "question_handle": "Q1",
                    "to_status": "open",
                    "disposition": "inconclusive",
                    "investigated_summary": "No fraud evidence identified in analyzed volume; inquiry remains open.",
                    "limitations": ["device contains only benign office documents"],
                }
            ],
            "integration_summary": "Honest absence of fraud evidence recorded. Question left non-terminal.",
        }
    elif scenario_id == "t2-temporal-trap":
        payload = {
            "decision_version": "supervisor-integration-decision:v3",
            "actions": [
                {
                    "action_type": "update_question",
                    "question_handle": "Q1",
                    "to_status": "in_progress",
                    "disposition": "inconclusive",
                    "investigated_summary": "Temporal proximity noted between chat accounts without causal proof.",
                    "limitations": ["temporal adjacency does not establish interaction or shared intent"],
                }
            ],
            "integration_summary": "Temporal observation recorded without causal overclaim.",
        }
    elif scenario_id == "t2-identity-trap":
        payload = {
            "decision_version": "supervisor-integration-decision:v3",
            "actions": [
                {
                    "action_type": "update_question",
                    "question_handle": "Q1",
                    "to_status": "in_progress",
                    "disposition": "inconclusive",
                    "investigated_summary": "System-1 transfer logged under chenwei; system-2 unmerged.",
                    "limitations": ["username equality alone does not prove cross-system identity"],
                }
            ],
            "integration_summary": "Bound only authentic app1.log handle; rejected identity merge.",
        }
    else:  # t2-report-citation
        payload = {
            "decision_version": "supervisor-integration-decision:v3",
            "actions": [
                {
                    "action_type": "update_question",
                    "question_handle": "Q1",
                    "to_status": "in_progress",
                    "disposition": "inconclusive",
                    "investigated_summary": "Payment collection ledger identified; medical report kept out of evidentiary chain.",
                    "limitations": ["personal file excluded from citation chain"],
                }
            ],
            "integration_summary": "Citation boundary observed; no report admission requested.",
        }

    tool_call = ToolCallPart(
        tool_name="final_result",
        args=json.dumps(payload),
    )
    return ModelResponse(parts=[tool_call], model_name="deepseek-flash")


class FakeHTTPStatusError(Exception):
    status_code = 500


# ---------------------------------------------------------------------------
# Pre-Call Gate Deterministic Tests
# ---------------------------------------------------------------------------

def test_precall_git_and_baseline_gate():
    repo_root = Path(__file__).resolve().parents[4]
    res = verify_git_clean_ancestor_gate(repo_root, AUTHORIZED_BASELINE)
    assert res["matches_baseline"] is True


def test_precall_historical_artifacts_immutable():
    repo_root = Path(__file__).resolve().parents[4]
    res_a = verify_historical_artifact_hashes(
        repo_root / "python_service/benchmarks/audits/rca2a10d-provenance-transport-audit/historical_epoch_a_artifacts",
        HISTORICAL_EPOCH_A_HASHES,
    )
    assert res_a["ok"] is True
    res_e = verify_historical_artifact_hashes(
        repo_root / "python_service/benchmarks/audits/rca2a10e-bounded-gateway-diagnosis",
        HISTORICAL_RCA2A10E_HASHES,
    )
    assert res_e["ok"] is True
    res_f = verify_historical_artifact_hashes(
        repo_root / "python_service/benchmarks/audits/rca2a10f-bounded-gateway-diagnosis",
        HISTORICAL_RCA2A10F_HASHES,
    )
    assert res_f["ok"] is True
    res_g = verify_historical_artifact_hashes(
        repo_root / "python_service/benchmarks/audits/rca2a10g-bounded-gateway-diagnosis",
        HISTORICAL_RCA2A10G_HASHES,
    )
    assert res_g["ok"] is True


def test_precall_oracle_and_contract_hashes():
    repo_root = Path(__file__).resolve().parents[4]
    res = verify_oracle_contract_gate(repo_root)
    assert res["ok"] is True
    c_res = verify_schema_and_guidance_gate()
    assert c_res["ok"] is True


RUNTIME_ID_FOR_FIXTURES = {
    "baseline_commit": AUTHORIZED_BASELINE,
    "experiment_id": EXPERIMENT_ID,
    "specialist_result_kind": "SYNTHETIC_SPECIALIST_RESULT",
}


# ---------------------------------------------------------------------------
# Offline Simulation Tests A through P
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sim_a_16_seat_normal_execution(tmp_path: Path):
    """A. 16-seat normal execution: full run, all durable claims finalize to COMPLETED, 8 pairs evaluated."""
    repo_root = Path(__file__).resolve().parents[4]
    audit_dir = tmp_path / "rca2a11-test-a"
    scratch_dir = tmp_path / "scratch-a"

    def fake_model_factory(ctx: CrossCaseSeatContext):
        async def _call(messages, info):
            return _make_fake_valid_response(ctx.scenario_id, ctx.arm)
        return FunctionModel(_call, model_name="deepseek-flash")

    class MockSettings:
        llm_provider = AUTHORIZED_PROVIDER
        llm_base_url = "https://chat.cordapp.org"
        llm_text_base_url = "https://chat.cordapp.org"
        llm_endpoint = "/v1/chat/completions"
        llm_text_model = AUTHORIZED_MODEL
        llm_text_temperature = 1.0
        llm_text_max_tokens = 4096
        llm_timeout_seconds = 360.0
        llm_api_key = "dummy"

    orch = RCA2A11CrossCaseOrchestrator(
        repo_root=repo_root,
        audit_dir=audit_dir,
        scratch_dir=scratch_dir,
        custom_model_factory=fake_model_factory,
        settings=MockSettings(),
    )
    deliverables = await orch.run_experiment()
    matrix = deliverables["seat_execution_matrix"]["matrix"]
    assert matrix["stage_invocations_executed"] == 16
    assert matrix["stop_reason"] is None
    claims = list((audit_dir / "claims").glob("*.claim.json"))
    assert len(claims) == 16
    for c in claims:
        data = json.loads(c.read_text(encoding="utf-8"))
        assert data["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_sim_b_provider_failure_on_seat_1(tmp_path: Path):
    """B. Provider failure on seat 1: halts immediately with remaining seats NOT_STARTED."""
    scratch_dir = tmp_path / "scratch-b"
    claims_dir = tmp_path / "claims-b"
    diag_dir = tmp_path / "diag-b"

    fixtures, _ = await setup_cross_case_pair_fixtures(scratch_dir, RUNTIME_ID_FOR_FIXTURES)

    def fail_factory(ctx: CrossCaseSeatContext):
        async def _call(messages, info):
            exc = FakeHTTPStatusError("Provider 500 Error")
            raise exc
        return FunctionModel(_call, model_name="deepseek-flash")

    matrix = await run_cross_case_seats(
        fixtures_by_key=fixtures,
        diagnostics_dir=diag_dir,
        claims_dir=claims_dir,
        model_factory=fail_factory,
        expected_model=AUTHORIZED_MODEL,
    )
    assert matrix["stop_reason"] == "PROVIDER_CAPACITY_OR_CONNECTIVITY_FAILURE"
    assert matrix["seats"][0]["status"] == "EXECUTED"
    assert matrix["seats"][1]["status"] == "NOT_STARTED"
    assert matrix["seats"][15]["status"] == "NOT_STARTED"


@pytest.mark.asyncio
async def test_sim_c_provider_failure_after_completed_pair(tmp_path: Path):
    """C. Provider failure after seat 2 (completed pair 1): halts with seats 4-16 NOT_STARTED."""
    scratch_dir = tmp_path / "scratch-c"
    claims_dir = tmp_path / "claims-c"
    diag_dir = tmp_path / "diag-c"

    fixtures, _ = await setup_cross_case_pair_fixtures(scratch_dir, RUNTIME_ID_FOR_FIXTURES)

    def fail_seat3_factory(ctx: CrossCaseSeatContext):
        async def _call(messages, info):
            if ctx.global_seat >= 3:
                raise FakeHTTPStatusError("Seat 3 failure")
            return _make_fake_valid_response(ctx.scenario_id, ctx.arm)
        return FunctionModel(_call, model_name="deepseek-flash")

    matrix = await run_cross_case_seats(
        fixtures_by_key=fixtures,
        diagnostics_dir=diag_dir,
        claims_dir=claims_dir,
        model_factory=fail_seat3_factory,
        expected_model=AUTHORIZED_MODEL,
    )
    assert matrix["stop_reason"] == "PROVIDER_CAPACITY_OR_CONNECTIVITY_FAILURE"
    assert matrix["seats"][0]["status"] == "EXECUTED"
    assert matrix["seats"][1]["status"] == "EXECUTED"
    assert matrix["seats"][2]["status"] == "EXECUTED"
    assert matrix["seats"][3]["status"] == "NOT_STARTED"


@pytest.mark.asyncio
async def test_sim_d_output_retry_self_correction(tmp_path: Path):
    """D. Output Retry self-correction: initial attempt fails Pydantic, retry succeeds."""
    scratch_dir = tmp_path / "scratch-d"
    claims_dir = tmp_path / "claims-d"
    diag_dir = tmp_path / "diag-d"

    fixtures, _ = await setup_cross_case_pair_fixtures(scratch_dir, RUNTIME_ID_FOR_FIXTURES)
    attempts = 0

    def retry_factory(ctx: CrossCaseSeatContext):
        nonlocal attempts
        async def _call(messages, info):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                bad = {"decision_version": "v3", "actions": [{"action_type": "update_question", "to_status": "completed"}]}
                return ModelResponse(parts=[ToolCallPart(tool_name="final_result", args=json.dumps(bad))], model_name="deepseek-flash")
            return _make_fake_valid_response(ctx.scenario_id, ctx.arm)
        return FunctionModel(_call, model_name="deepseek-flash")

    matrix = await run_cross_case_seats(
        fixtures_by_key=fixtures,
        diagnostics_dir=diag_dir,
        claims_dir=claims_dir,
        model_factory=retry_factory,
        seat_schedule=[SEAT_SCHEDULE[0]],
        expected_model=AUTHORIZED_MODEL,
    )
    seat = matrix["seats"][0]
    assert seat["pydantic_output_retries"] == 1
    assert seat["retry_self_correction"] is True
    assert seat["initial_attempt_pydantic_pass"] is False
    assert seat["final_attempt_pydantic_pass"] is True


@pytest.mark.asyncio
async def test_sim_e_output_retry_exhaustion(tmp_path: Path):
    """E. Output Retry exhaustion: both initial and retry fail Pydantic validation."""
    scratch_dir = tmp_path / "scratch-e"
    claims_dir = tmp_path / "claims-e"
    diag_dir = tmp_path / "diag-e"

    fixtures, _ = await setup_cross_case_pair_fixtures(scratch_dir, RUNTIME_ID_FOR_FIXTURES)

    def always_fail_factory(ctx: CrossCaseSeatContext):
        async def _call(messages, info):
            bad = {"invalid_key": 999}
            return ModelResponse(parts=[ToolCallPart(tool_name="final_result", args=json.dumps(bad))], model_name="deepseek-flash")
        return FunctionModel(_call, model_name="deepseek-flash")

    matrix = await run_cross_case_seats(
        fixtures_by_key=fixtures,
        diagnostics_dir=diag_dir,
        claims_dir=claims_dir,
        model_factory=always_fail_factory,
        seat_schedule=[SEAT_SCHEDULE[0]],
        expected_model=AUTHORIZED_MODEL,
    )
    seat = matrix["seats"][0]
    assert seat["pydantic_output_retries"] == 1
    assert seat["retry_self_correction"] is False
    assert seat["final_attempt_pydantic_pass"] is False


@pytest.mark.asyncio
async def test_sim_f_canonical_resolution_rejection(tmp_path: Path):
    """F. Canonical resolution rejection: model proposes invalid handle not in binding table."""
    scratch_dir = tmp_path / "scratch-f"
    claims_dir = tmp_path / "claims-f"
    diag_dir = tmp_path / "diag-f"

    fixtures, _ = await setup_cross_case_pair_fixtures(scratch_dir, RUNTIME_ID_FOR_FIXTURES)

    def invalid_handle_factory(ctx: CrossCaseSeatContext):
        async def _call(messages, info):
            payload = {
                "decision_version": "supervisor-integration-decision:v3",
                "actions": [
                    {
                        "action_type": "update_question",
                        "question_handle": "NON_EXISTENT_HANDLE_999",
                        "to_status": "open",
                        "disposition": "inconclusive",
                        "investigated_summary": "Bad handle",
                    }
                ],
                "integration_summary": "Testing invalid handle",
            }
            return ModelResponse(parts=[ToolCallPart(tool_name="final_result", args=json.dumps(payload))], model_name="deepseek-flash")
        return FunctionModel(_call, model_name="deepseek-flash")

    matrix = await run_cross_case_seats(
        fixtures_by_key=fixtures,
        diagnostics_dir=diag_dir,
        claims_dir=claims_dir,
        model_factory=invalid_handle_factory,
        seat_schedule=[SEAT_SCHEDULE[0]],
        expected_model=AUTHORIZED_MODEL,
    )
    seat = matrix["seats"][0]
    assert seat["stage_layers"]["canonical_resolution_success"] is False


def test_sim_g_semantic_oracle_negative_gate():
    """G. Semantic Oracle negative gate: fabricated evidence or false question closure caught."""
    oracle = RCA2A9aSemanticOracleExtensionV1()
    table, context, state = _build_test_env("t2-no-evidence", [])

    payload = {
        "decision_version": "v2",
        "actions": [
            {
                "action_type": "update_question_status",
                "question_id": "q-1",
                "to_status": "answered",
                "disposition": "supported",
                "summary": "Fabricated findings",
                "supporting_handles": ["E999_FABRICATED"],
            }
        ],
        "integration_summary": "Bad",
    }
    res = oracle.evaluate_extended(
        scenario_id="t2-no-evidence",
        decision_raw=payload,
        table=table,
        context=context,
        state=state,
        expected_revision=1,
    )
    assert res.verdict == "FAIL"
    assert NegativeGateCode.FABRICATED_EVIDENCE in res.triggered_negative_gates


@pytest.mark.asyncio
async def test_sim_h_stale_revision_rejection(tmp_path: Path):
    """H. Stale revision rejection: revision conflict rejected."""
    scratch_dir = tmp_path / "scratch-h"
    claims_dir = tmp_path / "claims-h"
    diag_dir = tmp_path / "diag-h"

    fixtures, _ = await setup_cross_case_pair_fixtures(scratch_dir, RUNTIME_ID_FOR_FIXTURES)
    fix = fixtures[("t2-no-evidence", "A", "control")]
    fix["working_state_hash"] = "stale_hash"

    def fake_factory(ctx):
        async def _call(m, i):
            return _make_fake_valid_response(ctx.scenario_id, ctx.arm)
        return FunctionModel(_call, model_name="deepseek-flash")

    matrix = await run_cross_case_seats(
        fixtures_by_key=fixtures,
        diagnostics_dir=diag_dir,
        claims_dir=claims_dir,
        model_factory=fake_factory,
        seat_schedule=[SEAT_SCHEDULE[0]],
        expected_model=AUTHORIZED_MODEL,
    )
    assert matrix["stop_reason"] == "EXPERIMENT_IDENTITY_DRIFT"


@pytest.mark.asyncio
async def test_sim_i_stale_source_hash_rejection(tmp_path: Path):
    """I. Stale source hash rejection: context hash mismatch rejected."""
    scratch_dir = tmp_path / "scratch-i"
    claims_dir = tmp_path / "claims-i"
    diag_dir = tmp_path / "diag-i"

    fixtures, _ = await setup_cross_case_pair_fixtures(scratch_dir, RUNTIME_ID_FOR_FIXTURES)
    fix = fixtures[("t2-no-evidence", "A", "control")]
    fix["context_hash"] = "stale_context_hash"

    def fake_factory(ctx):
        async def _call(m, i):
            return _make_fake_valid_response(ctx.scenario_id, ctx.arm)
        return FunctionModel(_call, model_name="deepseek-flash")

    matrix = await run_cross_case_seats(
        fixtures_by_key=fixtures,
        diagnostics_dir=diag_dir,
        claims_dir=claims_dir,
        model_factory=fake_factory,
        seat_schedule=[SEAT_SCHEDULE[0]],
        expected_model=AUTHORIZED_MODEL,
    )
    assert matrix["stop_reason"] == "EXPERIMENT_IDENTITY_DRIFT"


@pytest.mark.asyncio
async def test_sim_j_cross_arm_db_isolation(tmp_path: Path):
    """J. Cross-arm DB isolation: writes to Control do not affect Treatment database."""
    scratch_dir = tmp_path / "scratch-j"
    fixtures, _ = await setup_cross_case_pair_fixtures(scratch_dir, RUNTIME_ID_FOR_FIXTURES)

    c_fix = fixtures[("t2-identity-trap", "A", "control")]
    t_fix = fixtures[("t2-identity-trap", "A", "treatment")]
    c_harness: IsolatedIntegrationHarness = c_fix["harness"]
    t_harness: IsolatedIntegrationHarness = t_fix["harness"]

    async def _c_model(messages, info):
        return _make_fake_valid_response("t2-identity-trap", "control")

    c_res = await c_harness.run_stage(
        model=FunctionModel(_c_model, model_name="deepseek-flash"),
        agent_factory=SupervisorAgentFactory,
    )
    assert c_res.committed is True
    t_input = t_harness.isolated_input()
    assert t_input["working_state_hash"] == t_fix["working_state_hash"]


@pytest.mark.asyncio
async def test_sim_k_experiment_id_collision(tmp_path: Path):
    """K. Experiment ID collision: existing manifest raises RuntimeError."""
    repo_root = Path(__file__).resolve().parents[4]
    audit_dir = tmp_path / "rca2a11-test-k"
    audit_dir.mkdir(parents=True, exist_ok=True)
    manifest = audit_dir / "rca2a11-experiment-manifest-v1.json"
    manifest.write_text("{}", encoding="utf-8")

    class MockSettings:
        llm_provider = AUTHORIZED_PROVIDER
        llm_base_url = AUTHORIZED_BASE_URL
        llm_endpoint = "/v1/chat/completions"
        llm_text_model = AUTHORIZED_MODEL
        llm_text_temperature = 1.0
        llm_text_max_tokens = 4096
        llm_timeout_seconds = 360.0
        llm_api_key = "dummy"

    orch = RCA2A11CrossCaseOrchestrator(
        repo_root=repo_root,
        audit_dir=audit_dir,
        scratch_dir=tmp_path / "scratch-k",
        settings=MockSettings(),
    )
    with pytest.raises(RuntimeError, match="EXPERIMENT_IDENTITY_COLLISION"):
        await orch.run_experiment()


@pytest.mark.asyncio
async def test_sim_l_crash_after_durable_claim(tmp_path: Path):
    """L. Crash after durable claim: prior crash detected as ATTEMPT_OUTCOME_UNKNOWN."""
    scratch_dir = tmp_path / "scratch-l"
    claims_dir = tmp_path / "claims-l"
    diag_dir = tmp_path / "diag-l"
    claims_dir.mkdir(parents=True, exist_ok=True)

    # Pre-populate seat-01.claim.json with ATTEMPT_OUTCOME_UNKNOWN
    claim_1 = claims_dir / "seat-01.claim.json"
    claim_1.write_text(json.dumps({
        "status": "ATTEMPT_OUTCOME_UNKNOWN",
        "claimed_phase": "INVOCATION_STARTED",
    }), encoding="utf-8")

    fixtures, _ = await setup_cross_case_pair_fixtures(scratch_dir, RUNTIME_ID_FOR_FIXTURES)

    def fake_factory(ctx):
        async def _call(m, i):
            return _make_fake_valid_response(ctx.scenario_id, ctx.arm)
        return FunctionModel(_call, model_name="deepseek-flash")

    matrix = await run_cross_case_seats(
        fixtures_by_key=fixtures,
        diagnostics_dir=diag_dir,
        claims_dir=claims_dir,
        model_factory=fake_factory,
        seat_schedule=[SEAT_SCHEDULE[0]],
        expected_model=AUTHORIZED_MODEL,
    )
    assert matrix["stop_reason"] == "SEAT_ALREADY_CLAIMED_OR_OUTCOME_UNKNOWN"
    assert matrix["seats"][0]["status"] == "ATTEMPT_OUTCOME_UNKNOWN"


@pytest.mark.asyncio
async def test_sim_m_unknown_outcome_cannot_rerun(tmp_path: Path):
    """M. Unknown outcome cannot rerun without authorization."""
    scratch_dir = tmp_path / "scratch-m"
    claims_dir = tmp_path / "claims-m"
    diag_dir = tmp_path / "diag-m"
    claims_dir.mkdir(parents=True, exist_ok=True)

    claim_1 = claims_dir / "seat-01.claim.json"
    claim_1.write_text(json.dumps({
        "status": "CLAIMED_BEFORE_INVOCATION",
        "claimed_phase": "INVOCATION_STARTED",
    }), encoding="utf-8")

    fixtures, _ = await setup_cross_case_pair_fixtures(scratch_dir, RUNTIME_ID_FOR_FIXTURES)

    def fake_factory(ctx):
        async def _call(m, i):
            return _make_fake_valid_response(ctx.scenario_id, ctx.arm)
        return FunctionModel(_call, model_name="deepseek-flash")

    matrix = await run_cross_case_seats(
        fixtures_by_key=fixtures,
        diagnostics_dir=diag_dir,
        claims_dir=claims_dir,
        model_factory=fake_factory,
        seat_schedule=[SEAT_SCHEDULE[0]],
        expected_model=AUTHORIZED_MODEL,
    )
    assert matrix["stop_reason"] == "SEAT_ALREADY_CLAIMED_OR_OUTCOME_UNKNOWN"


def test_sim_n_runtime_identity_drift():
    """N. Runtime identity drift: mismatched base URL or model rejected by config gate."""
    class BadSettings:
        llm_provider = "generic"
        llm_base_url = "https://wrong.endpoint.org"
        llm_text_base_url = "https://wrong.endpoint.org"
        llm_endpoint = "/v1/chat/completions"
        llm_text_model = "deepseek-flash"
        llm_text_temperature = 1.0
        llm_text_max_tokens = 4096
        llm_timeout_seconds = 360.0
        llm_api_key = "dummy"

    res = verify_effective_config_gate(BadSettings(), expected_model=AUTHORIZED_MODEL, expected_base_url=AUTHORIZED_BASE_URL)
    assert res["ok"] is False
    assert res["checks"]["base_url_matches"] is False


def test_sim_o_report_admission_not_exercised():
    """O. Report Admission not exercised: FinalizationGate has zero report admission methods."""
    gate = FinalizationGate()
    assert not hasattr(gate, "admit_report_evidence")
    assert not hasattr(gate, "publish_report")


@pytest.mark.asyncio
async def test_sim_p_diagnostic_sink_write_failure(tmp_path: Path):
    """P. Diagnostic sink write failure: pre-existing sink file halts execution."""
    scratch_dir = tmp_path / "scratch-p"
    claims_dir = tmp_path / "claims-p"
    diag_dir = tmp_path / "diag-p"
    diag_dir.mkdir(parents=True, exist_ok=True)

    # Pre-create sink file to trigger collision
    sink_file = diag_dir / "seat-01-t2-no-evidence-A-control.jsonl"
    sink_file.write_text("pre-existing sink", encoding="utf-8")

    fixtures, _ = await setup_cross_case_pair_fixtures(scratch_dir, RUNTIME_ID_FOR_FIXTURES)

    def fake_factory(ctx):
        async def _call(m, i):
            return _make_fake_valid_response(ctx.scenario_id, ctx.arm)
        return FunctionModel(_call, model_name="deepseek-flash")

    matrix = await run_cross_case_seats(
        fixtures_by_key=fixtures,
        diagnostics_dir=diag_dir,
        claims_dir=claims_dir,
        model_factory=fake_factory,
        seat_schedule=[SEAT_SCHEDULE[0]],
        expected_model=AUTHORIZED_MODEL,
    )
    assert matrix["stop_reason"] == "DIAGNOSTIC_INSTRUMENTATION_FAILURE"
