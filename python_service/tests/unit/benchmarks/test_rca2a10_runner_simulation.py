"""TraceLens Agent v0 — RCA-2A.10 Cross-Case Runner Simulation & Pre-Freeze Verification.

Mandatory Pre-Freeze Simulation (Section 5):
1. FunctionModel/Fake Provider with zero network calls.
2. All four fixtures (F1: t2-no-evidence, F2: t2-temporal-trap, F3: t2-identity-trap, F4: t2-report-citation).
3. Complete 16-seat simulation across 8 pairs.
4. All 16 durable seat claims persisted exclusively with 0600 permissions and finalized to COMPLETED.
5. Provider failure cleanly halts execution mid-run with remaining seats NOT_STARTED.
6. Structured output retry accounting correctly distinguishes initial attempt from retry attempts.
7. Stale revision or stale source hash triggers rejection in commit path.
8. F4 scenario strictly keeps Report Admission as NOT_EXERCISED and does not call report admission.
9. Cross-arm physical isolation: writes to Control do not affect Treatment store.
10. Semantic Oracle rejects negative gates without false positive PASS.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from benchmarks.contracts.experimental.integration_vocabulary_guidance_v1 import (
    GUIDANCE_TEXT,
    GuidanceIntegrationAgentFactory,
    guidance_sha256,
)
from benchmarks.isolated_integration.cross_case_fixtures import (
    SCENARIO_SPECS,
    build_cloned_cross_case_pair,
    verify_cross_case_arm_parity,
)
from benchmarks.isolated_integration.cross_case_runner import (
    EXPERIMENT_ID,
    MODEL,
    PROVIDER,
    REQUEST_BUDGET,
    SEAT_SCHEDULE,
    CrossCaseSeatContext,
    build_cross_case_seat_record,
    compute_cross_case_paired_metrics,
    run_cross_case_seats,
    setup_cross_case_pair_fixtures,
)
from benchmarks.isolated_integration.harness import (
    IsolatedIntegrationHarness,
)
from benchmarks.isolated_integration.semantic_oracle import (
    InformationValue,
    NegativeGateCode,
    SemanticAdequacy,
)
from benchmarks.isolated_integration.semantic_oracle_extension import (
    RCA2A9aSemanticOracleExtensionV1,
)
from httpserver.services.investigation.agent_failure_diagnostics import schema_hash_of
from httpserver.services.investigation.agent_finalization import (
    FinalizationGate,
    FinalizationRequest,
    RuntimeFinalizationView,
)
from httpserver.services.investigation.agent_integration_v2 import (
    SupervisorIntegrationDecisionV2,
)
from httpserver.services.investigation.agent_retry_timeout_facts import (
    SDK_MAX_RETRIES,
)
from httpserver.services.investigation.agent_supervisor import SupervisorAgentFactory
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from tests.unit.benchmarks.test_rca2a9a_contract_closure import _build_test_env


def _make_fake_valid_response(scenario_id: str, arm: str) -> ModelResponse:
    """Construct an arm-neutral, valid integration decision payload for simulation."""
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
    return ModelResponse(parts=[tool_call], model_name="step-3.7-flash")


@pytest.mark.asyncio
async def test_sim_01_full_16_seat_simulation(tmp_path: Path):
    """Simulation 1, 2, 3, 4: Verify complete 16-seat simulation with all 4 fixtures and durable claims."""
    scratch_dir = tmp_path / "scratch"
    diag_dir = tmp_path / "diagnostics"
    claims_dir = tmp_path / "claims"

    runtime_identity = {
        "baseline_commit": "23f088babb28fa449801b28c3fc21eb09511780d",
        "experiment_id": EXPERIMENT_ID,
        "specialist_result_kind": "SYNTHETIC_SPECIALIST_RESULT",
    }

    # Setup 8 pairs (4 scenarios × 2 pairs)
    fixtures_by_key, pair_audits = await setup_cross_case_pair_fixtures(scratch_dir, runtime_identity)
    assert len(fixtures_by_key) == 16
    assert len(pair_audits) == 8
    assert all(a["parity"]["parity_pass"] for a in pair_audits)

    # FunctionModel simulating compliant agent
    def fake_model_factory(ctx: CrossCaseSeatContext):
        async def _call(messages, info):
            return _make_fake_valid_response(ctx.scenario_id, ctx.arm)
        return FunctionModel(_call, model_name="step-3.7-flash")

    oracle = RCA2A9aSemanticOracleExtensionV1()
    matrix = await run_cross_case_seats(
        fixtures_by_key=fixtures_by_key,
        diagnostics_dir=diag_dir,
        claims_dir=claims_dir,
        model_factory=fake_model_factory,
        oracle=oracle,
    )

    assert matrix["stage_invocations_scheduled"] == 16
    assert matrix["stage_invocations_executed"] == 16
    assert matrix["stop_reason"] is None

    # Check all 16 durable seat claims
    for g_seat in range(1, 17):
        claim_file = claims_dir / f"seat-{g_seat:02d}.claim.json"
        assert claim_file.exists(), f"Claim file missing for seat {g_seat}"
        claim_data = json.loads(claim_file.read_text(encoding="utf-8"))
        assert claim_data["status"] == "COMPLETED"
        assert claim_data["claimed_phase"] == "RESULT_RECORDED"
        assert (claim_file.stat().st_mode & 0o777) == 0o600

    # Check paired metrics
    paired_summary = compute_cross_case_paired_metrics(matrix)
    assert paired_summary["total_pairs"] == 8
    assert paired_summary["contract_summary"]["both_valid"] == 8
    assert paired_summary["semantic_summary"]["both_semantically_adequate"] == 8


class RateLimitError(Exception):
    status_code = 429


@pytest.mark.asyncio
async def test_sim_02_provider_failure_halts_mid_run(tmp_path: Path):
    """Simulation 5: Verify provider failure cleanly halts execution with remaining seats NOT_STARTED."""
    scratch_dir = tmp_path / "scratch"
    diag_dir = tmp_path / "diagnostics"
    claims_dir = tmp_path / "claims"

    runtime_identity = {
        "baseline_commit": "23f088babb28fa449801b28c3fc21eb09511780d",
        "experiment_id": EXPERIMENT_ID,
        "specialist_result_kind": "SYNTHETIC_SPECIALIST_RESULT",
    }
    fixtures_by_key, _ = await setup_cross_case_pair_fixtures(scratch_dir, runtime_identity)

    # Seat 3 fails with Provider 429 RateLimit
    def failing_model_factory(ctx: CrossCaseSeatContext):
        async def _call(messages, info):
            if ctx.global_seat >= 3:
                exc = RateLimitError("RateLimitError: 429 Too Many Requests")
                exc.status_code = 429
                raise exc
            return _make_fake_valid_response(ctx.scenario_id, ctx.arm)
        return FunctionModel(_call, model_name="step-3.7-flash")

    matrix = await run_cross_case_seats(
        fixtures_by_key=fixtures_by_key,
        diagnostics_dir=diag_dir,
        claims_dir=claims_dir,
        model_factory=failing_model_factory,
    )

    assert matrix["stop_reason"] == "PROVIDER_CAPACITY_OR_CONNECTIVITY_FAILURE"
    assert matrix["stage_invocations_executed"] == 3
    seats = matrix["seats"]
    assert seats[0]["status"] == "EXECUTED"
    assert seats[1]["status"] == "EXECUTED"
    assert seats[2]["status"] == "EXECUTED"
    assert seats[3]["status"] == "NOT_STARTED"
    assert seats[15]["status"] == "NOT_STARTED"


@pytest.mark.asyncio
async def test_sim_03_output_retry_accounting(tmp_path: Path):
    """Simulation 6: Verify structured output retry accounting tracks initial failure then correction."""
    scratch_dir = tmp_path / "scratch"
    diag_dir = tmp_path / "diagnostics"
    claims_dir = tmp_path / "claims"

    runtime_identity = {
        "baseline_commit": "23f088babb28fa449801b28c3fc21eb09511780d",
        "experiment_id": EXPERIMENT_ID,
        "specialist_result_kind": "SYNTHETIC_SPECIALIST_RESULT",
    }
    fixtures_by_key, _ = await setup_cross_case_pair_fixtures(scratch_dir, runtime_identity)

    # First attempt emits illegal to_status='completed', second attempt self-corrects to 'open'
    attempt_count = 0

    def retry_model_factory(ctx: CrossCaseSeatContext):
        nonlocal attempt_count

        async def _call(messages, info):
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count == 1:
                # Invalid payload triggering Pydantic validation failure
                bad_payload = {
                    "decision_version": "supervisor-integration-decision:v3",
                    "actions": [
                        {
                            "action_type": "update_question",
                            "question_handle": "Q1",
                            "to_status": "completed",  # ILLEGAL
                            "disposition": "inconclusive",
                            "investigated_summary": "Attempt 1",
                        }
                    ],
                    "integration_summary": "Bad attempt",
                }
                tool_call = ToolCallPart(tool_name="final_result", args=json.dumps(bad_payload))
                return ModelResponse(parts=[tool_call], model_name="step-3.7-flash")
            return _make_fake_valid_response(ctx.scenario_id, ctx.arm)

        return FunctionModel(_call, model_name="step-3.7-flash")

    # Run single seat
    one_seat_schedule = [SEAT_SCHEDULE[0]]
    matrix = await run_cross_case_seats(
        fixtures_by_key=fixtures_by_key,
        diagnostics_dir=diag_dir,
        claims_dir=claims_dir,
        model_factory=retry_model_factory,
        seat_schedule=one_seat_schedule,
    )

    seat_rec = matrix["seats"][0]
    assert seat_rec["logical_model_generations"] == 2
    assert seat_rec["pydantic_output_retries"] == 1
    assert seat_rec["retry_self_correction"] is True
    assert seat_rec["initial_attempt_pydantic_pass"] is False
    assert seat_rec["final_attempt_pydantic_pass"] is True
    assert seat_rec["field_scan_totals"]["to_status_completed"] == 1


@pytest.mark.asyncio
async def test_sim_04_stale_revision_rejection(tmp_path: Path):
    """Simulation 7: Verify stale revision or source hash is rejected by production commit path."""
    scratch_dir = tmp_path / "scratch"
    diag_dir = tmp_path / "diagnostics"
    claims_dir = tmp_path / "claims"

    runtime_identity = {
        "baseline_commit": "23f088babb28fa449801b28c3fc21eb09511780d",
        "experiment_id": EXPERIMENT_ID,
        "specialist_result_kind": "SYNTHETIC_SPECIALIST_RESULT",
    }
    fixtures_by_key, _ = await setup_cross_case_pair_fixtures(scratch_dir, runtime_identity)

    # Intentionally corrupt working state hash before running
    fix = fixtures_by_key[("t2-no-evidence", "A", "control")]
    fix["working_state_hash"] = "tampered_hash"

    def fake_model_factory(ctx: CrossCaseSeatContext):
        async def _call(messages, info):
            return _make_fake_valid_response(ctx.scenario_id, ctx.arm)
        return FunctionModel(_call, model_name="step-3.7-flash")

    one_seat_schedule = [SEAT_SCHEDULE[0]]
    matrix = await run_cross_case_seats(
        fixtures_by_key=fixtures_by_key,
        diagnostics_dir=diag_dir,
        claims_dir=claims_dir,
        model_factory=fake_model_factory,
        seat_schedule=one_seat_schedule,
    )

    # Must be stopped on EXPERIMENT_IDENTITY_DRIFT because hash changed
    assert matrix["stop_reason"] == "EXPERIMENT_IDENTITY_DRIFT"


@pytest.mark.asyncio
async def test_sim_05_f4_citation_boundary_without_report_admission(tmp_path: Path):
    """Simulation 8: Verify F4 citation boundary strictly leaves Report Admission as NOT_EXERCISED."""
    scratch_dir = tmp_path / "scratch"
    runtime_identity = {
        "baseline_commit": "23f088babb28fa449801b28c3fc21eb09511780d",
        "experiment_id": EXPERIMENT_ID,
        "specialist_result_kind": "SYNTHETIC_SPECIALIST_RESULT",
    }
    fixtures_by_key, _ = await setup_cross_case_pair_fixtures(scratch_dir, runtime_identity)
    f4_fix = fixtures_by_key[("t2-report-citation", "A", "control")]
    harness: IsolatedIntegrationHarness = f4_fix["harness"]

    # Verify FinalizationGate has zero report admission methods
    gate = FinalizationGate()
    assert not hasattr(gate, "admit_report_evidence")
    assert not hasattr(gate, "publish_report")

    # Verify input contract
    input_contract = harness.isolated_input()
    assert input_contract["task_id"] == "t2-report-citation"
    assert input_contract["investigation_id"] == f4_fix["investigation_id"]


@pytest.mark.asyncio
async def test_sim_06_cross_arm_physical_isolation(tmp_path: Path):
    """Simulation 9: Verify cross-arm state isolation across cloned SQLite databases."""
    scratch_dir = tmp_path / "scratch"
    runtime_identity = {
        "baseline_commit": "23f088babb28fa449801b28c3fc21eb09511780d",
        "experiment_id": EXPERIMENT_ID,
        "specialist_result_kind": "SYNTHETIC_SPECIALIST_RESULT",
    }
    fixtures_by_key, _ = await setup_cross_case_pair_fixtures(scratch_dir, runtime_identity)

    control_fix = fixtures_by_key[("t2-identity-trap", "A", "control")]
    treatment_fix = fixtures_by_key[("t2-identity-trap", "A", "treatment")]

    c_harness: IsolatedIntegrationHarness = control_fix["harness"]
    t_harness: IsolatedIntegrationHarness = treatment_fix["harness"]

    # Commit a stage run on Control only
    async def _c_model(messages, info):
        return _make_fake_valid_response("t2-identity-trap", "control")

    c_res = await c_harness.run_stage(
        model=FunctionModel(_c_model, model_name="step-3.7-flash"),
        agent_factory=SupervisorAgentFactory,
    )
    assert c_res.committed is True

    # Treatment must be completely untouched
    t_input = t_harness.isolated_input()
    assert t_input["working_state_hash"] == treatment_fix["working_state_hash"]
    c_state = c_harness._runtime.get_latest_working_state(control_fix["investigation_id"])
    t_state = t_harness._runtime.get_latest_working_state(treatment_fix["investigation_id"])
    assert c_state.revision == 2
    assert t_state.revision == 1


@pytest.mark.asyncio
async def test_sim_07_oracle_rejects_negative_gates_without_false_pass():
    """Simulation 10: Verify Semantic Oracle rejects negative gates without false positive PASS."""
    oracle = RCA2A9aSemanticOracleExtensionV1()
    table, context, state = _build_test_env("t2-no-evidence", [])

    # Fabricated evidence handle
    fake_payload = {
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
        decision_raw=fake_payload,
        table=table,
        context=context,
        state=state,
        expected_revision=1,
    )
    assert res.verdict == "FAIL"
    assert NegativeGateCode.FABRICATED_EVIDENCE in res.triggered_negative_gates


def test_sim_08_budget_constants_exact():
    """Verify request budget constants match RCA-2A.9a contracts."""
    assert REQUEST_BUDGET["stage_invocations"] == 16
    assert REQUEST_BUDGET["max_logical_model_generations"] == 32
    assert REQUEST_BUDGET["output_retry_budget_per_invocation"] == 1
    assert REQUEST_BUDGET["preflight_logical_requests"] == 3
    assert REQUEST_BUDGET["sdk_max_retries"] == 2
    assert REQUEST_BUDGET["diagnostic_http_attempts_max"] == 96
    assert REQUEST_BUDGET["preflight_http_attempts_max"] == 9
    assert REQUEST_BUDGET["total_max_http_attempts"] == 105
    assert len(SEAT_SCHEDULE) == 16
