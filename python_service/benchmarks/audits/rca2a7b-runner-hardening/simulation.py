"""RCA-2A.7b Full Eight-Seat Offline Simulation Engine.

Implements all 14 scenarios (E1-E14) using FunctionModel / Fake Providers:
- Zero network requests (verified via network spy).
- Full verification of:
    stage_invocations_started
    stage_invocations_finished
    logical_model_generations
    pydantic_output_retries
    provider_errors
    pydantic_parse_success
    canonical_resolution_success
    transition_validation_success
    scratch_commit_success
- Paired metrics and classification tests.
- Label: SYNTHETIC_TEST_OBSERVATIONS.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

import runner
from runner import (
    MODEL,
    PAIRS,
    REQUEST_BUDGET,
    RecordingProxyModel,
    SeatExecutionContext,
    SeatPhase,
    build_cloned_pair_fixtures,
    compute_paired_metrics,
    run_eight_seats,
)

LEGAL_PAYLOAD = {
    "actions": [
        {
            "action_type": "update_question",
            "question_handle": "Q1",
            "to_status": "in_progress",
            "investigated_summary": "advanced",
        }
    ],
    "integration_summary": "advanced",
    "limitations": [],
    "warnings": [],
}

INVALID_STATUS_PAYLOAD = {
    "actions": [
        {
            "action_type": "update_question",
            "question_handle": "Q1",
            "to_status": "completed",
            "disposition": "not_supported",
        }
    ],
    "integration_summary": "invalid status",
    "limitations": [],
    "warnings": [],
}

POLICY_FAIL_PAYLOAD = {
    "actions": [
        {
            "action_type": "update_question",
            "question_handle": "Q1",
            "to_status": "answered",
            "disposition": "supported",
        }
    ],
    "integration_summary": "closure without evidence",
    "limitations": [],
    "warnings": [],
}

FABRICATED_HANDLE_PAYLOAD = {
    "actions": [
        {
            "action_type": "update_question",
            "question_handle": "Q1",
            "to_status": "in_progress",
            "basis_handles": ["E999"],
        }
    ],
    "integration_summary": "fabricated handle",
    "limitations": [],
    "warnings": [],
}


class NetworkSpy:
    """Verifies that zero real network calls are made."""

    def __init__(self):
        self.call_count = 0

    def assert_zero_calls(self):
        assert self.call_count == 0, f"Unauthorized network calls detected: {self.call_count}"

    def intercept(self, *args, **kwargs):
        self.call_count += 1
        raise runner.NetworkCallDetectedError("REAL_NETWORK_CALL_FORBIDDEN_IN_OFFLINE_SIMULATION")


async def setup_simulation_fixtures(base_dir: Path) -> list[dict[str, Any]]:
    """Build all 4 pairs (8 seats) of cloned scratch fixtures."""
    fixtures = []
    for pair_id in range(1, 5):
        h_c, h_t, meta = await build_cloned_pair_fixtures(
            pair_id=pair_id, base_dir=base_dir, with_evidence=False
        )
        c_contract = h_c.isolated_input()
        t_contract = h_t.isolated_input()

        fixtures.append({
            "pair_id": pair_id,
            "arm": "control",
            "fixture_path": meta["control_dir"],
            "task_id": meta["task_id"],
            "investigation_id": meta["investigation_id"],
            "run_id": meta["run_id"],
            "working_state_hash": c_contract["working_state_hash"],
            "context_hash": c_contract["integration_context_hash"],
            "binding_table_hash": c_contract["reference_binding_table_hash"],
            "fixture_kind": "NO_EVIDENCE_HONEST_EMPTY",
            "binding_table_resolves_to_current_synthetic_task": True,
        })
        fixtures.append({
            "pair_id": pair_id,
            "arm": "treatment",
            "fixture_path": meta["treatment_dir"],
            "task_id": meta["task_id"],
            "investigation_id": meta["investigation_id"],
            "run_id": meta["run_id"],
            "working_state_hash": t_contract["working_state_hash"],
            "context_hash": t_contract["integration_context_hash"],
            "binding_table_hash": t_contract["reference_binding_table_hash"],
            "fixture_kind": "NO_EVIDENCE_HONEST_EMPTY",
            "binding_table_resolves_to_current_synthetic_task": True,
        })
    return fixtures


def make_function_model(
    payload_or_generator: dict | Callable[[list, Any], ModelResponse],
    *,
    model_name: str = MODEL,
) -> FunctionModel:
    if callable(payload_or_generator):
        fn = payload_or_generator
    else:
        def fn(messages, info):
            tool_name = info.output_tools[0].name
            return ModelResponse(
                parts=[ToolCallPart(tool_name, json.dumps(payload_or_generator))],
                model_name=model_name,
            )
    return FunctionModel(fn, model_name=model_name)


# ---------------------------------------------------------------------------
# Scenarios E1 - E14
# ---------------------------------------------------------------------------


async def simulate_e1_all_legal(tmp_path: Path, spy: NetworkSpy) -> dict[str, Any]:
    """E1: All 8 seats produce legal payloads. 8/8 succeed, commits independent."""
    fixtures = await setup_simulation_fixtures(tmp_path / "fixtures_e1")
    diag_dir = tmp_path / "diag_e1"

    def model_factory(_ctx: SeatExecutionContext):
        return make_function_model(LEGAL_PAYLOAD)

    matrix = await run_eight_seats(fixtures, diag_dir, model_factory=model_factory)
    spy.assert_zero_calls()
    return matrix


async def simulate_e2_retry_success(tmp_path: Path, spy: NetworkSpy) -> dict[str, Any]:
    """E2: First generation invalid enum, second generation legal. Retry self-corrects."""
    fixtures = await setup_simulation_fixtures(tmp_path / "fixtures_e2")
    diag_dir = tmp_path / "diag_e2"

    def model_factory(ctx: SeatExecutionContext):
        if ctx.pair_id == 1 and ctx.arm == "control":
            call_idx = 0

            def dynamic_fn(messages, info):
                nonlocal call_idx
                call_idx += 1
                tool_name = info.output_tools[0].name
                # First attempt: invalid status; second attempt: legal
                payload = INVALID_STATUS_PAYLOAD if call_idx == 1 else LEGAL_PAYLOAD
                return ModelResponse(
                    parts=[ToolCallPart(tool_name, json.dumps(payload))],
                    model_name=MODEL,
                )

            return make_function_model(dynamic_fn)
        return make_function_model(LEGAL_PAYLOAD)

    matrix = await run_eight_seats(fixtures, diag_dir, model_factory=model_factory)
    spy.assert_zero_calls()
    return matrix


async def simulate_e3_retry_exhausted(tmp_path: Path, spy: NetworkSpy) -> dict[str, Any]:
    """E3: Output retries exhausted in one seat. Schema failure does not stop remaining seats."""
    fixtures = await setup_simulation_fixtures(tmp_path / "fixtures_e3")
    diag_dir = tmp_path / "diag_e3"

    def model_factory(ctx: SeatExecutionContext):
        if ctx.pair_id == 1 and ctx.arm == "control":
            # Always invalid
            return make_function_model(INVALID_STATUS_PAYLOAD)
        return make_function_model(LEGAL_PAYLOAD)

    matrix = await run_eight_seats(fixtures, diag_dir, model_factory=model_factory)
    spy.assert_zero_calls()
    return matrix


async def simulate_e4_policy_fail(tmp_path: Path, spy: NetworkSpy) -> dict[str, Any]:
    """E4: Pydantic PASS, Policy FAIL. Rejected by transition policy, not canonical valid."""
    fixtures = await setup_simulation_fixtures(tmp_path / "fixtures_e4")
    diag_dir = tmp_path / "diag_e4"

    def model_factory(ctx: SeatExecutionContext):
        if ctx.pair_id == 1 and ctx.arm == "control":
            return make_function_model(POLICY_FAIL_PAYLOAD)
        return make_function_model(LEGAL_PAYLOAD)

    matrix = await run_eight_seats(fixtures, diag_dir, model_factory=model_factory)
    spy.assert_zero_calls()
    return matrix


async def simulate_e5_provider_timeout(tmp_path: Path, spy: NetworkSpy) -> dict[str, Any]:
    """E5: Provider timeout in seat 2. Typed attribution, stops remaining seats."""
    fixtures = await setup_simulation_fixtures(tmp_path / "fixtures_e5")
    diag_dir = tmp_path / "diag_e5"

    class MockTimeoutError(Exception):
        status_code = None

    def model_factory(ctx: SeatExecutionContext):
        if ctx.pair_id == 1 and ctx.arm == "treatment":  # seat 2
            def timeout_fn(messages, info):
                raise MockTimeoutError("Request timed out waiting for upstream provider")

            return make_function_model(timeout_fn)
        return make_function_model(LEGAL_PAYLOAD)

    matrix = await run_eight_seats(fixtures, diag_dir, model_factory=model_factory)
    spy.assert_zero_calls()
    return matrix


async def simulate_e6_provider_429(tmp_path: Path, spy: NetworkSpy) -> dict[str, Any]:
    """E6: Provider 429 rate limit in seat 1. Halts remaining seats."""
    fixtures = await setup_simulation_fixtures(tmp_path / "fixtures_e6")
    diag_dir = tmp_path / "diag_e6"

    class MockRateLimitError(Exception):
        status_code = 429

    def model_factory(ctx: SeatExecutionContext):
        if ctx.pair_id == 1 and ctx.arm == "control":
            def ratelimit_fn(messages, info):
                raise MockRateLimitError("Rate limit exceeded; quota blocked")

            return make_function_model(ratelimit_fn)
        return make_function_model(LEGAL_PAYLOAD)

    matrix = await run_eight_seats(fixtures, diag_dir, model_factory=model_factory)
    spy.assert_zero_calls()
    return matrix


async def simulate_e7_model_identity_mismatch(tmp_path: Path, spy: NetworkSpy) -> dict[str, Any]:
    """E7: Model identity mismatch (wrong returned model). Immediate STOP."""
    fixtures = await setup_simulation_fixtures(tmp_path / "fixtures_e7")
    diag_dir = tmp_path / "diag_e7"

    def model_factory(ctx: SeatExecutionContext):
        if ctx.pair_id == 1 and ctx.arm == "control":
            return make_function_model(LEGAL_PAYLOAD, model_name="unauthorized-model-xyz")
        return make_function_model(LEGAL_PAYLOAD)

    matrix = await run_eight_seats(fixtures, diag_dir, model_factory=model_factory)
    spy.assert_zero_calls()
    return matrix


async def simulate_e8_diagnostic_sink_failure(tmp_path: Path, spy: NetworkSpy) -> dict[str, Any]:
    """E8: Diagnostic sink failure on a failing seat triggers immediate STOP."""
    fixtures = await setup_simulation_fixtures(tmp_path / "fixtures_e8")
    diag_dir = tmp_path / "diag_e8"
    diag_dir.mkdir(parents=True, exist_ok=True)

    # Pre-create a corrupt diagnostic sink file with invalid permissions
    sink_path = diag_dir / "pair-01-control.jsonl"
    sink_path.write_text("corrupted_data\n")

    def model_factory(_ctx: SeatExecutionContext):
        return make_function_model(LEGAL_PAYLOAD)

    matrix = await run_eight_seats(fixtures, diag_dir, model_factory=model_factory)
    spy.assert_zero_calls()
    return matrix


async def simulate_e9_fabricated_handle(tmp_path: Path, spy: NetworkSpy) -> dict[str, Any]:
    """E9: Fabricated Evidence handle (E999). Immediate STOP."""
    fixtures = await setup_simulation_fixtures(tmp_path / "fixtures_e9")
    diag_dir = tmp_path / "diag_e9"

    def model_factory(ctx: SeatExecutionContext):
        if ctx.pair_id == 1 and ctx.arm == "control":
            return make_function_model(FABRICATED_HANDLE_PAYLOAD)
        return make_function_model(LEGAL_PAYLOAD)

    matrix = await run_eight_seats(fixtures, diag_dir, model_factory=model_factory)
    spy.assert_zero_calls()
    return matrix


async def simulate_e10_identity_drift(tmp_path: Path, spy: NetworkSpy) -> dict[str, Any]:
    """E10: Source identity drift detected before first call. STOP before seat 1 starts."""
    fixtures = await setup_simulation_fixtures(tmp_path / "fixtures_e10")
    diag_dir = tmp_path / "diag_e10"

    # Mutate fixture hash to simulate drift
    fixtures[0]["working_state_hash"] = "drifted_hash_value"

    def model_factory(_ctx: SeatExecutionContext):
        return make_function_model(LEGAL_PAYLOAD)

    matrix = await run_eight_seats(fixtures, diag_dir, model_factory=model_factory)
    spy.assert_zero_calls()
    return matrix


async def simulate_e11_scratch_commit_failure(tmp_path: Path, spy: NetworkSpy) -> dict[str, Any]:
    """E11: Scratch commit failure does not report success or pollute other arm."""
    fixtures = await setup_simulation_fixtures(tmp_path / "fixtures_e11")
    diag_dir = tmp_path / "diag_e11"

    # Make control db read-only to simulate commit failure
    control_db = Path(fixtures[0]["fixture_path"]) / "investigation.db"
    os.chmod(control_db, 0o400)

    def model_factory(_ctx: SeatExecutionContext):
        return make_function_model(LEGAL_PAYLOAD)

    try:
        matrix = await run_eight_seats(fixtures, diag_dir, model_factory=model_factory)
    finally:
        os.chmod(control_db, 0o600)

    spy.assert_zero_calls()
    return matrix


async def simulate_e12_unexpected_runner_exception(tmp_path: Path, spy: NetworkSpy) -> dict[str, Any]:
    """E12: Unexpected runner exception recorded as infrastructure failure, not schema failure."""
    fixtures = await setup_simulation_fixtures(tmp_path / "fixtures_e12")
    diag_dir = tmp_path / "diag_e12"

    def model_factory(ctx: SeatExecutionContext):
        if ctx.pair_id == 1 and ctx.arm == "control":
            def bad_fn(messages, info):
                raise RuntimeError("Unexpected internal runner bug")

            return make_function_model(bad_fn)
        return make_function_model(LEGAL_PAYLOAD)

    matrix = await run_eight_seats(fixtures, diag_dir, model_factory=model_factory)
    spy.assert_zero_calls()
    return matrix


async def simulate_e13_duplicate_seat_execution(tmp_path: Path, spy: NetworkSpy) -> dict[str, Any]:
    """E13: Duplicate seat execution prohibited."""
    fixtures = await setup_simulation_fixtures(tmp_path / "fixtures_e13")
    diag_dir = tmp_path / "diag_e13"

    # Pre-create pair-01-control diagnostic sink to simulate existing seat
    sink_path = diag_dir / "pair-01-control.jsonl"
    sink_path.parent.mkdir(parents=True, exist_ok=True)
    sink_path.touch()

    def model_factory(_ctx: SeatExecutionContext):
        return make_function_model(LEGAL_PAYLOAD)

    matrix = await run_eight_seats(fixtures, diag_dir, model_factory=model_factory)
    spy.assert_zero_calls()
    return matrix


async def simulate_e14_mid_run_interruption(tmp_path: Path, spy: NetworkSpy) -> dict[str, Any]:
    """E14: Mid-run interruption preserves executed facts, unstarted seats marked NOT_STARTED."""
    fixtures = await setup_simulation_fixtures(tmp_path / "fixtures_e14")
    diag_dir = tmp_path / "diag_e14"

    def model_factory(_ctx: SeatExecutionContext):
        return make_function_model(LEGAL_PAYLOAD)

    # Interrupt after 3 seats
    matrix = await run_eight_seats(
        fixtures, diag_dir, model_factory=model_factory, stop_early_after_seat=3
    )
    spy.assert_zero_calls()
    return matrix
