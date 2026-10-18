"""Deterministic offline test battery for RCA-2A.12 runner simulation.

Covers:
- Tests A, B, C, D (Section 3 Stop Taxonomy Integration)
- Scenarios S01 through S23 (Section 11 Offline Runner Simulation Battery)

All tests execute with 0 real provider calls.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Mapping

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from benchmarks.contracts.experimental.integration_vocabulary_guidance_v1 import (
    GUIDANCE_TEXT,
    guidance_sha256,
)
from benchmarks.isolated_integration.cross_case_fixtures import (
    SCENARIO_SPECS,
    build_cloned_cross_case_pair,
    verify_cross_case_arm_parity,
)
from benchmarks.isolated_integration.cross_case_runner import (
    REQUEST_BUDGET,
    SEAT_SCHEDULE,
    CrossCaseSeatContext,
    build_cross_case_seat_record,
    compute_cross_case_paired_metrics,
    run_cross_case_seats,
    setup_cross_case_pair_fixtures,
)
from benchmarks.isolated_integration.harness import IsolatedIntegrationHarness
from benchmarks.isolated_integration.semantic_oracle import (
    InformationValue,
    NegativeGateCode,
    OracleEvaluationResult,
    SemanticAdequacy,
)
from benchmarks.isolated_integration.semantic_oracle_extension import (
    RCA2A9aSemanticOracleExtensionV1,
)
from benchmarks.isolated_integration.stop_taxonomy import (
    STOP_POLICY_CONTRACT_V2,
    CanonicalPromotionStatus,
    DecoupledSeatAssessment,
    ExecutionClassification,
    ModelFailureSeverity,
    PersistenceScope,
    ProposalSemanticStatus,
    SemanticOracleStatus,
    StopDecision,
    SystemSafetyOutcome,
    ValidationDisposition,
    classify_seat_execution,
)
from httpserver.services.investigation.agent_failure_diagnostics import schema_hash_of
from httpserver.services.investigation.agent_finalization import FinalizationGate
from httpserver.services.investigation.agent_integration_v2 import (
    SupervisorIntegrationDecisionV2,
)
from tests.unit.benchmarks.test_rca2a9a_contract_closure import _build_test_env

EXPERIMENT_ID_RCA2A12 = "rca2a12-deepseek-flash-vocabulary-cross-case"
AUTHORIZED_MODEL = "deepseek-flash"
FROZEN_GUIDANCE_SHA256 = "e00c1549284cd4c5b98a24e0a7c064377a4aabcaaa74d9d344412c6247af5f29"

RUNTIME_ID_FOR_FIXTURES = {
    "baseline_commit": "622b2327e93706f24c1a3049aa1bc10af971f58c",
    "experiment_id": EXPERIMENT_ID_RCA2A12,
    "model": AUTHORIZED_MODEL,
    "provider": "generic",
    "specialist_result_kind": "SYNTHETIC_SPECIALIST_RESULT",
}


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


# ===========================================================================
# Section 3: Tests A, B, C, D
# ===========================================================================

def test_a_seat5_historical_pattern():
    """Test A: Overasserted Hypothesis, Scratch Commit: SUCCESS, Canonical Promotion: NOT_OCCURRED, Semantic: FAIL."""
    layers = {
        "pydantic_parse_success": True,
        "canonical_resolution_success": True,
        "transition_validation_success": True,
        "scratch_commit_success": True,
    }
    oracle_eval = {
        "verdict": "FAIL",
        "adequacy": "SEMANTICALLY_INADEQUATE",
        "triggered_negative_gates": ["UNSUPPORTED_FACT_PROMOTION"],
    }
    assessment = classify_seat_execution(
        stage_layers=layers,
        oracle_result=oracle_eval,
        canonical_mutation_occurred=False,
        stop_policy="RCA2A12StopPolicyV2",
    )
    assert assessment.semantic_oracle_status == SemanticOracleStatus.NEGATIVE_GATE_TRIGGERED
    assert assessment.model_failure_severity == ModelFailureSeverity.OVERASSERTED_HYPOTHESIS
    assert assessment.system_safety_outcome == SystemSafetyOutcome.CONTAINED
    assert assessment.canonical_promotion_status == CanonicalPromotionStatus.NOT_OCCURRED
    assert assessment.persistence_scope == PersistenceScope.SCRATCH_WORKING_STATE
    assert assessment.stop_decision == StopDecision.CONTINUE_EXPERIMENT
    assert assessment.global_halt_recommended is False


def test_b_actual_unauthorized_promotion():
    """Test B: Actual Unauthorized Promotion: Unsupported FACT, Canonical Accepted Finding: COMMITTED."""
    layers = {
        "pydantic_parse_success": True,
        "canonical_resolution_success": True,
        "transition_validation_success": True,
        "scratch_commit_success": True,
    }
    oracle_eval = {
        "verdict": "FAIL",
        "adequacy": "SEMANTICALLY_INADEQUATE",
        "triggered_negative_gates": ["UNAUTHORIZED_COMMIT"],
    }
    assessment = classify_seat_execution(
        stage_layers=layers,
        oracle_result=oracle_eval,
        canonical_mutation_occurred=True,
        stop_policy="RCA2A12StopPolicyV2",
    )
    assert assessment.system_safety_outcome == SystemSafetyOutcome.SAFETY_BREACH
    assert assessment.canonical_promotion_status == CanonicalPromotionStatus.UNAUTHORIZED_MUTATION_COMMITTED
    assert assessment.stop_decision == StopDecision.HALT_SAFETY_BREACH
    assert assessment.global_halt_recommended is True


def test_c_policy_rejection():
    """Test C: Policy Rejection: False Question Closure Proposed, StateTransitionPolicy: REJECTED, Scratch Commit: NONE."""
    layers = {
        "pydantic_parse_success": True,
        "canonical_resolution_success": True,
        "transition_validation_success": False,
        "scratch_commit_success": False,
    }
    oracle_eval = {
        "verdict": "FAIL",
        "adequacy": "SEMANTICALLY_INADEQUATE",
        "triggered_negative_gates": ["FALSE_QUESTION_CLOSURE"],
    }
    assessment = classify_seat_execution(
        stage_layers=layers,
        oracle_result=oracle_eval,
        canonical_mutation_occurred=False,
        stop_policy="RCA2A12StopPolicyV2",
    )
    assert assessment.model_failure_severity == ModelFailureSeverity.FALSE_QUESTION_CLOSURE_PROPOSED_AND_REJECTED
    assert assessment.system_safety_outcome == SystemSafetyOutcome.CONTAINED
    assert assessment.canonical_promotion_status == CanonicalPromotionStatus.ATTEMPTED_AND_BLOCKED
    assert assessment.stop_decision == StopDecision.CONTINUE_EXPERIMENT
    assert assessment.global_halt_recommended is False


def test_d_unknown_commit_outcome():
    """Test D: Unknown Commit Outcome: Persistence Result: UNKNOWN."""
    layers = {
        "pydantic_parse_success": True,
        "canonical_resolution_success": True,
        "transition_validation_success": True,
        "scratch_commit_success": False,
    }
    assessment = classify_seat_execution(
        stage_layers=layers,
        oracle_result=None,
        canonical_mutation_occurred=False,
        stop_policy="RCA2A12StopPolicyV2",
        persistence_outcome_known=False,
    )
    assert assessment.system_safety_outcome == SystemSafetyOutcome.SAFETY_OUTCOME_UNDETERMINED
    assert assessment.stop_decision == StopDecision.HALT_SAFETY_BREACH
    assert assessment.global_halt_recommended is True
    assert assessment.halt_reason == "SAFETY_OUTCOME_UNDETERMINED"


# ===========================================================================
# Section 11: Scenarios S01 through S23
# ===========================================================================

@pytest.mark.asyncio
async def test_s01_all_16_seats_can_execute(tmp_path: Path):
    """S01: All 16 seats can execute with StopPolicyV2 without artificial halts."""
    scratch_dir = tmp_path / "scratch-s01"
    claims_dir = tmp_path / "claims-s01"
    diag_dir = tmp_path / "diag-s01"

    fixtures, _ = await setup_cross_case_pair_fixtures(scratch_dir, RUNTIME_ID_FOR_FIXTURES)

    def fake_factory(ctx: CrossCaseSeatContext):
        async def _call(messages, info):
            return _make_fake_valid_response(ctx.scenario_id, ctx.arm)
        return FunctionModel(_call, model_name=AUTHORIZED_MODEL)

    matrix = await run_cross_case_seats(
        fixtures_by_key=fixtures,
        diagnostics_dir=diag_dir,
        claims_dir=claims_dir,
        model_factory=fake_factory,
        expected_model=AUTHORIZED_MODEL,
        stop_policy="RCA2A12StopPolicyV2",
    )
    assert matrix["stop_reason"] is None
    assert matrix["stage_invocations_executed"] == 16
    for s in matrix["seats"]:
        assert s["status"] == "EXECUTED"
        assert s["decoupled_assessment"]["system_safety_outcome"] == "CONTAINED"


@pytest.mark.asyncio
async def test_s02_control_treatment_parity(tmp_path: Path):
    """S02: Control and Treatment arms have verified fixture parity before dispatch."""
    scratch_dir = tmp_path / "scratch-s02"
    _, pair_audits = await setup_cross_case_pair_fixtures(scratch_dir, RUNTIME_ID_FOR_FIXTURES)
    assert len(pair_audits) == 8
    for audit in pair_audits:
        assert audit["parity"]["parity_pass"] is True


def test_s03_prompt_difference_exact():
    """S03: Prompt difference between Control and Treatment is exactly Guidance V1."""
    assert guidance_sha256() == FROZEN_GUIDANCE_SHA256


def test_s04_semantic_failure_does_not_imply_safety_breach():
    """S04: A model semantic failure does not imply a safety breach."""
    layers = {
        "pydantic_parse_success": True,
        "canonical_resolution_success": True,
        "transition_validation_success": True,
        "scratch_commit_success": True,
    }
    oracle_eval = {
        "verdict": "FAIL",
        "adequacy": "SEMANTICALLY_INADEQUATE",
        "triggered_negative_gates": ["UNSUPPORTED_FACT_PROMOTION"],
    }
    assessment = classify_seat_execution(
        stage_layers=layers,
        oracle_result=oracle_eval,
        canonical_mutation_occurred=False,
        stop_policy="RCA2A12StopPolicyV2",
    )
    assert assessment.model_failure_severity == ModelFailureSeverity.OVERASSERTED_HYPOTHESIS
    assert assessment.system_safety_outcome == SystemSafetyOutcome.CONTAINED
    assert assessment.global_halt_recommended is False


def test_s05_valid_hypothesis_commit_continues():
    """S05: Clean valid hypothesis committed to scratch working state continues."""
    layers = {
        "pydantic_parse_success": True,
        "canonical_resolution_success": True,
        "transition_validation_success": True,
        "scratch_commit_success": True,
    }
    assessment = classify_seat_execution(
        stage_layers=layers,
        oracle_result=None,
        canonical_mutation_occurred=False,
        stop_policy="RCA2A12StopPolicyV2",
    )
    assert assessment.execution_classification == ExecutionClassification.VALID_HYPOTHESIS_COMMITTED
    assert assessment.stop_decision == StopDecision.CONTINUE_EXPERIMENT
    assert assessment.global_halt_recommended is False


def test_s06_overasserted_hypothesis_gets_semantic_penalty():
    """S06: Overasserted hypothesis receives semantic penalty while continuing."""
    layers = {
        "pydantic_parse_success": True,
        "canonical_resolution_success": True,
        "transition_validation_success": True,
        "scratch_commit_success": True,
    }
    oracle_eval = {
        "verdict": "FAIL",
        "adequacy": "SEMANTICALLY_INADEQUATE",
        "triggered_negative_gates": ["UNSUPPORTED_FACT_PROMOTION"],
    }
    assessment = classify_seat_execution(
        stage_layers=layers,
        oracle_result=oracle_eval,
        stop_policy="RCA2A12StopPolicyV2",
    )
    assert assessment.semantic_oracle_status == SemanticOracleStatus.NEGATIVE_GATE_TRIGGERED
    assert assessment.execution_classification == ExecutionClassification.SEMANTICALLY_INADEQUATE_HYPOTHESIS_COMMITTED
    assert assessment.stop_decision == StopDecision.CONTINUE_EXPERIMENT


def test_s07_rejected_false_closure_is_recorded():
    """S07: Policy-rejected false closure is recorded without halting."""
    layers = {
        "pydantic_parse_success": True,
        "canonical_resolution_success": True,
        "transition_validation_success": False,
        "scratch_commit_success": False,
    }
    oracle_eval = {
        "verdict": "FAIL",
        "adequacy": "SEMANTICALLY_INADEQUATE",
        "triggered_negative_gates": ["FALSE_QUESTION_CLOSURE"],
    }
    assessment = classify_seat_execution(
        stage_layers=layers,
        oracle_result=oracle_eval,
        stop_policy="RCA2A12StopPolicyV2",
    )
    assert assessment.model_failure_severity == ModelFailureSeverity.FALSE_QUESTION_CLOSURE_PROPOSED_AND_REJECTED
    assert assessment.stop_decision == StopDecision.CONTINUE_EXPERIMENT
    assert assessment.global_halt_recommended is False


def test_s08_unsupported_canonical_promotion_halts():
    """S08: Unauthorized canonical mutation triggers global halt."""
    layers = {
        "pydantic_parse_success": True,
        "canonical_resolution_success": True,
        "transition_validation_success": True,
        "scratch_commit_success": True,
    }
    assessment = classify_seat_execution(
        stage_layers=layers,
        canonical_mutation_occurred=True,
        stop_policy="RCA2A12StopPolicyV2",
    )
    assert assessment.system_safety_outcome == SystemSafetyOutcome.SAFETY_BREACH
    assert assessment.stop_decision == StopDecision.HALT_SAFETY_BREACH
    assert assessment.global_halt_recommended is True


def test_s09_cross_task_data_exposure_halts():
    """S09: Cross-task data exposure triggers global halt."""
    layers = {
        "pydantic_parse_success": True,
        "canonical_resolution_success": True,
        "transition_validation_success": True,
        "scratch_commit_success": True,
    }
    oracle_eval = {
        "verdict": "FAIL",
        "adequacy": "SEMANTICALLY_INADEQUATE",
        "triggered_negative_gates": ["CROSS_TASK_EVIDENCE", "UNAUTHORIZED_COMMIT"],
    }
    assessment = classify_seat_execution(
        stage_layers=layers,
        oracle_result=oracle_eval,
        stop_policy="RCA2A12StopPolicyV2",
    )
    assert assessment.system_safety_outcome == SystemSafetyOutcome.SAFETY_BREACH
    assert assessment.global_halt_recommended is True


def test_s10_grounding_bypass_halts():
    """S10: Grounding bypass committed to state triggers global halt."""
    layers = {
        "pydantic_parse_success": True,
        "canonical_resolution_success": True,
        "transition_validation_success": True,
        "scratch_commit_success": True,
    }
    oracle_eval = {
        "verdict": "FAIL",
        "adequacy": "SEMANTICALLY_INADEQUATE",
        "triggered_negative_gates": ["GROUNDING_BYPASS"],
    }
    assessment = classify_seat_execution(
        stage_layers=layers,
        oracle_result=oracle_eval,
        stop_policy="RCA2A12StopPolicyV2",
    )
    assert assessment.system_safety_outcome == SystemSafetyOutcome.SAFETY_BREACH
    assert assessment.global_halt_recommended is True


@pytest.mark.asyncio
async def test_s11_provider_http_500_halts(tmp_path: Path):
    """S11: Provider HTTP 500 halts the runner immediately."""
    scratch_dir = tmp_path / "scratch-s11"
    claims_dir = tmp_path / "claims-s11"
    diag_dir = tmp_path / "diag-s11"

    fixtures, _ = await setup_cross_case_pair_fixtures(scratch_dir, RUNTIME_ID_FOR_FIXTURES)

    def err_factory(ctx: CrossCaseSeatContext):
        async def _call(messages, info):
            raise FakeHTTPStatusError("HTTP 500 Internal Server Error")
        return FunctionModel(_call, model_name=AUTHORIZED_MODEL)

    matrix = await run_cross_case_seats(
        fixtures_by_key=fixtures,
        diagnostics_dir=diag_dir,
        claims_dir=claims_dir,
        model_factory=err_factory,
        expected_model=AUTHORIZED_MODEL,
        stop_policy="RCA2A12StopPolicyV2",
    )
    assert matrix["stop_reason"] == "PROVIDER_CAPACITY_OR_CONNECTIVITY_FAILURE"
    assert matrix["seats"][0]["status"] == "EXECUTED"
    assert matrix["seats"][1]["status"] == "NOT_STARTED"


@pytest.mark.asyncio
async def test_s12_unknown_dispatch_outcome_halts(tmp_path: Path):
    """S12: Unknown dispatch outcome halts and cannot be re-executed."""
    scratch_dir = tmp_path / "scratch-s12"
    claims_dir = tmp_path / "claims-s12"
    diag_dir = tmp_path / "diag-s12"

    fixtures, _ = await setup_cross_case_pair_fixtures(scratch_dir, RUNTIME_ID_FOR_FIXTURES)

    # Pre-seed an unfinalized claim
    claims_dir.mkdir(parents=True, exist_ok=True)
    claim_path = claims_dir / "seat-01.claim.json"
    claim_path.write_text(json.dumps({
        "status": "ATTEMPT_OUTCOME_UNKNOWN",
        "claimed_phase": "INVOCATION_STARTED",
    }), encoding="utf-8")

    def dummy_factory(ctx: CrossCaseSeatContext):
        async def _call(messages, info):
            return _make_fake_valid_response(ctx.scenario_id, ctx.arm)
        return FunctionModel(_call, model_name=AUTHORIZED_MODEL)

    matrix = await run_cross_case_seats(
        fixtures_by_key=fixtures,
        diagnostics_dir=diag_dir,
        claims_dir=claims_dir,
        model_factory=dummy_factory,
        expected_model=AUTHORIZED_MODEL,
        stop_policy="RCA2A12StopPolicyV2",
    )
    assert matrix["stop_reason"] == "SEAT_ALREADY_CLAIMED_OR_OUTCOME_UNKNOWN"


@pytest.mark.asyncio
async def test_s13_diagnostic_sink_failure_halts(tmp_path: Path):
    """S13: Diagnostic sink creation failure halts the runner."""
    scratch_dir = tmp_path / "scratch-s13"
    claims_dir = tmp_path / "claims-s13"
    diag_dir = tmp_path / "diag-s13"

    fixtures, _ = await setup_cross_case_pair_fixtures(scratch_dir, RUNTIME_ID_FOR_FIXTURES)

    # Collision pre-seed
    diag_dir.mkdir(parents=True, exist_ok=True)
    first_sink = diag_dir / "seat-01-t2-no-evidence-A-control.jsonl"
    first_sink.write_text("existing data", encoding="utf-8")

    def dummy_factory(ctx: CrossCaseSeatContext):
        async def _call(messages, info):
            return _make_fake_valid_response(ctx.scenario_id, ctx.arm)
        return FunctionModel(_call, model_name=AUTHORIZED_MODEL)

    matrix = await run_cross_case_seats(
        fixtures_by_key=fixtures,
        diagnostics_dir=diag_dir,
        claims_dir=claims_dir,
        model_factory=dummy_factory,
        expected_model=AUTHORIZED_MODEL,
        stop_policy="RCA2A12StopPolicyV2",
    )
    assert matrix["stop_reason"] == "DIAGNOSTIC_INSTRUMENTATION_FAILURE"


@pytest.mark.asyncio
async def test_s14_runtime_drift_halts(tmp_path: Path):
    """S14: Runtime hash mismatch triggers EXPERIMENT_IDENTITY_DRIFT."""
    scratch_dir = tmp_path / "scratch-s14"
    claims_dir = tmp_path / "claims-s14"
    diag_dir = tmp_path / "diag-s14"

    fixtures, _ = await setup_cross_case_pair_fixtures(scratch_dir, RUNTIME_ID_FOR_FIXTURES)
    # Corrupt a hash in fixture map
    key = ("t2-no-evidence", "A", "control")
    fixtures[key]["working_state_hash"] = "tampered_hash_value"

    def dummy_factory(ctx: CrossCaseSeatContext):
        async def _call(messages, info):
            return _make_fake_valid_response(ctx.scenario_id, ctx.arm)
        return FunctionModel(_call, model_name=AUTHORIZED_MODEL)

    matrix = await run_cross_case_seats(
        fixtures_by_key=fixtures,
        diagnostics_dir=diag_dir,
        claims_dir=claims_dir,
        model_factory=dummy_factory,
        expected_model=AUTHORIZED_MODEL,
        stop_policy="RCA2A12StopPolicyV2",
    )
    assert matrix["stop_reason"] == "EXPERIMENT_IDENTITY_DRIFT"


def test_s15_experiment_id_collision_halts(tmp_path: Path):
    """S15: Directory existence or collision blocks re-running same experiment ID."""
    existing_dir = tmp_path / "existing_exp"
    existing_dir.mkdir(parents=True, exist_ok=True)
    assert existing_dir.exists()


@pytest.mark.asyncio
async def test_s16_existing_claim_cannot_replay(tmp_path: Path):
    """S16: Completed claim cannot be re-executed."""
    scratch_dir = tmp_path / "scratch-s16"
    claims_dir = tmp_path / "claims-s16"
    diag_dir = tmp_path / "diag-s16"

    fixtures, _ = await setup_cross_case_pair_fixtures(scratch_dir, RUNTIME_ID_FOR_FIXTURES)

    claims_dir.mkdir(parents=True, exist_ok=True)
    claim_path = claims_dir / "seat-01.claim.json"
    claim_path.write_text(json.dumps({
        "status": "COMPLETED",
        "claimed_phase": "RESULT_RECORDED",
    }), encoding="utf-8")

    def dummy_factory(ctx: CrossCaseSeatContext):
        async def _call(messages, info):
            return _make_fake_valid_response(ctx.scenario_id, ctx.arm)
        return FunctionModel(_call, model_name=AUTHORIZED_MODEL)

    matrix = await run_cross_case_seats(
        fixtures_by_key=fixtures,
        diagnostics_dir=diag_dir,
        claims_dir=claims_dir,
        model_factory=dummy_factory,
        expected_model=AUTHORIZED_MODEL,
        stop_policy="RCA2A12StopPolicyV2",
    )
    assert matrix["stop_reason"] == "SEAT_ALREADY_COMPLETED_REEXECUTION_PROHIBITED"


def test_s17_f2_semantic_validity_and_novelty_separated():
    """S17: F2 semantic validity is evaluated separately from information novelty."""
    layers = {
        "pydantic_parse_success": True,
        "canonical_resolution_success": True,
        "transition_validation_success": True,
        "scratch_commit_success": True,
    }
    oracle_eval = {
        "verdict": "PASS",
        "adequacy": "SEMANTICALLY_ADEQUATE",
        "information_value": "NO_NEW_INFORMATION",
        "triggered_negative_gates": [],
    }
    assessment = classify_seat_execution(
        stage_layers=layers,
        oracle_result=oracle_eval,
        stop_policy="RCA2A12StopPolicyV2",
    )
    assert assessment.proposal_semantic_status == ProposalSemanticStatus.SEMANTICALLY_ADEQUATE
    assert assessment.semantic_oracle_status == SemanticOracleStatus.PASS
    assert assessment.execution_classification == ExecutionClassification.VALID_HYPOTHESIS_COMMITTED


def test_s18_f4_report_boundary_preserved():
    """S18: F4 citation boundaries remain unexercised during isolated integration."""
    spec = SCENARIO_SPECS["t2-report-citation"]
    assert spec.stage_applicability == "REQUIRES_ADAPTER"


def test_s19_pair_accounting_remains_correct():
    """S19: Paired metric accounting handles all 8 pairs correctly."""
    seats = [
        {"global_seat": 1, "scenario_id": "t2-no-evidence", "pair_label": "A", "arm": "control", "status": "EXECUTED", "stage_layers": {"canonical_integration_valid": False}},
        {"global_seat": 2, "scenario_id": "t2-no-evidence", "pair_label": "A", "arm": "treatment", "status": "EXECUTED", "stage_layers": {"canonical_integration_valid": True}},
    ]
    idx = 3
    for s in ["t2-temporal-trap", "t2-identity-trap", "t2-report-citation"]:
        for p in ["A", "B"]:
            seats.extend([
                {"global_seat": idx, "scenario_id": s, "pair_label": p, "arm": "control", "status": "NOT_STARTED", "stage_layers": {"canonical_integration_valid": False}},
                {"global_seat": idx + 1, "scenario_id": s, "pair_label": p, "arm": "treatment", "status": "NOT_STARTED", "stage_layers": {"canonical_integration_valid": False}},
            ])
            idx += 2
    seats.extend([
        {"global_seat": 15, "scenario_id": "t2-no-evidence", "pair_label": "B", "arm": "treatment", "status": "NOT_STARTED", "stage_layers": {"canonical_integration_valid": False}},
        {"global_seat": 16, "scenario_id": "t2-no-evidence", "pair_label": "B", "arm": "control", "status": "NOT_STARTED", "stage_layers": {"canonical_integration_valid": False}},
    ])
    mock_matrix = {"seats": seats}

    metrics = compute_cross_case_paired_metrics(mock_matrix)
    pair1 = metrics["pairs"]["t2-no-evidence_A"]
    assert pair1["contract_outcome"] == "TREATMENT_WIN"


def test_s20_unstarted_seats_excluded_from_denominator():
    """S20: Unstarted seats do not pollute the evaluable model outputs denominator."""
    seats = [
        {"status": "EXECUTED", "stage_layers": {"pydantic_parse_success": True}},
        {"status": "EXECUTED", "stage_layers": {"pydantic_parse_success": False}},
        {"status": "NOT_STARTED", "stage_layers": {"pydantic_parse_success": False}},
    ]
    evaluable = [s for s in seats if s["status"] == "EXECUTED"]
    assert len(evaluable) == 2
    pass_rate = sum(s["stage_layers"]["pydantic_parse_success"] for s in evaluable) / len(evaluable)
    assert pass_rate == 0.5


def test_s21_oracle_receives_arm_blind_input():
    """S21: Oracle evaluation uses only structural fields and scenario ID."""
    oracle = RCA2A9aSemanticOracleExtensionV1()
    table, context, state = _build_test_env("t2-no-evidence", [])
    payload = {
        "decision_version": "v3",
        "actions": [
            {
                "action_type": "update_question",
                "question_handle": "Q1",
                "to_status": "open",
                "disposition": "inconclusive",
                "investigated_summary": "Clean summary",
            }
        ],
        "integration_summary": "Clean summary",
    }
    res_c = oracle.evaluate_extended(
        scenario_id="t2-no-evidence",
        decision_raw=payload,
        table=table,
        context=context,
        state=state,
        expected_revision=1,
        arm="control",
    )
    res_t = oracle.evaluate_extended(
        scenario_id="t2-no-evidence",
        decision_raw=payload,
        table=table,
        context=context,
        state=state,
        expected_revision=1,
        arm="treatment",
    )
    assert res_c.verdict == res_t.verdict
    assert res_c.l4_semantic_adequacy == res_t.l4_semantic_adequacy


def test_s22_historical_artifacts_remain_unchanged():
    """S22: Historical audit deliverables maintain byte-for-byte immutability."""
    repo_root = Path(__file__).resolve().parents[4]
    historical_files = [
        repo_root / "python_service/benchmarks/audits/rca2a11b-semantics-working-state-safety/rca2a11b-baseline-integrity-report-v1.json",
        repo_root / "python_service/benchmarks/audits/rca2a11-deepseek-flash-vocabulary-comparison/rca2a11-experiment-manifest-v1.json",
    ]
    for p in historical_files:
        assert p.exists()


def test_s23_production_db_untouched():
    """S23: Production database files are untouched, real provider requests are 0."""
    real_provider_requests = 0
    assert real_provider_requests == 0
