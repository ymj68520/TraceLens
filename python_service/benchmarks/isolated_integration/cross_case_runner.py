"""RCA-2A.10 Cross-Case Comparison Runner.

Provides:
- 16-seat lifecycle management across 4 scenarios (F1-F4) with 2 repetitions (Pair A, Pair B).
- Balanced execution sequence: Pair A (Control -> Treatment), Pair B (Treatment -> Control).
- Strict multi-layer request budget enforcement:
    16 stage invocations, max 32 logical generations, max 3 preflight requests,
    SDK max retries = 2, theoretical HTTP ceiling = 105.
- Durable Seat Claims (seat-01.claim.json .. seat-16.claim.json) with ATTEMPT_OUTCOME_UNKNOWN
  persisted exclusively to disk with fsync before any model invocation.
- Idempotent sanitized diagnostic sinks (0600 permissions, zero credentials).
- Integrated evaluation via RCA2A9aSemanticOracleExtensionV1 across 5 layers:
    L1 Schema Validity, L2 Canonical Resolution, L3 Transition Integrity,
    L4 Semantic Adequacy, L5 Information Value.
- Mandatory Negative Gates enforcement:
    FABRICATED_EVIDENCE, CROSS_TASK_EVIDENCE, GRAPH_ID_AS_EVIDENCE,
    ANALYST_NOTE_AS_FACT, UNSUPPORTED_FACT_PROMOTION, FALSE_QUESTION_CLOSURE,
    UNAUTHORIZED_COMMIT, GROUNDING_BYPASS.
- Pair independence and cross-arm state isolation across cloned SQLite databases.
"""

from __future__ import annotations

import asyncio
import copy
import enum
import hashlib
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

HERE = Path(__file__).resolve().parent
PYTHON_SERVICE_ROOT = HERE.parents[1]
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
    GuidanceIntegrationAgentFactory,
    guidance_sha256,
)
from benchmarks.isolated_integration.cross_case_fixtures import (
    SCENARIO_SPECS,
    build_cloned_cross_case_pair,
    verify_cross_case_arm_parity,
)
from benchmarks.isolated_integration.harness import (
    IsolatedIntegrationHarness,
    validate_isolated_input,
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
from diagnostic_sink_hardening import (
    DiagnosticDataQualityError,
    DiagnosticSinkCollisionError,
    create_exclusive_diagnostic_sink,
    read_and_validate_sink_entries,
)
from runner import (
    RecordingProxyModel,
    SeatPhase,
    is_provider_error_class,
    scan_payload,
    stage_layers,
    validate_payload,
)
from httpserver.services.investigation.agent_failure_diagnostics import (
    JsonlFailureDiagnosticSink,
    schema_hash_of,
)
from httpserver.services.investigation.agent_integration_v2 import (
    SupervisorIntegrationDecisionV2,
)
from httpserver.services.investigation.agent_model_adapter import (
    classify_provider_http_error,
)
from httpserver.services.investigation.agent_retry_timeout_facts import (
    SDK_MAX_RETRIES,
)
from httpserver.services.investigation.agent_supervisor import (
    SupervisorAgentFactory,
)
from pydantic_ai.models import Model as _PydanticAiModel

EXPERIMENT_ID = "rca2a10-cross-case-vocabulary-comparison"
PROVIDER = "stepfun"
MODEL = "step-3.7-flash"

# 16-seat execution order matching Protocol V2 and RCA-2A.10 Section 2.1
SEAT_SCHEDULE: list[dict[str, Any]] = [
    {"global_seat": 1, "scenario_id": "t2-no-evidence", "pair_label": "A", "arm": "control", "pair_id": 1},
    {"global_seat": 2, "scenario_id": "t2-no-evidence", "pair_label": "A", "arm": "treatment", "pair_id": 1},
    {"global_seat": 3, "scenario_id": "t2-temporal-trap", "pair_label": "A", "arm": "control", "pair_id": 1},
    {"global_seat": 4, "scenario_id": "t2-temporal-trap", "pair_label": "A", "arm": "treatment", "pair_id": 1},
    {"global_seat": 5, "scenario_id": "t2-identity-trap", "pair_label": "A", "arm": "control", "pair_id": 1},
    {"global_seat": 6, "scenario_id": "t2-identity-trap", "pair_label": "A", "arm": "treatment", "pair_id": 1},
    {"global_seat": 7, "scenario_id": "t2-report-citation", "pair_label": "A", "arm": "control", "pair_id": 1},
    {"global_seat": 8, "scenario_id": "t2-report-citation", "pair_label": "A", "arm": "treatment", "pair_id": 1},
    {"global_seat": 9, "scenario_id": "t2-no-evidence", "pair_label": "B", "arm": "treatment", "pair_id": 2},
    {"global_seat": 10, "scenario_id": "t2-no-evidence", "pair_label": "B", "arm": "control", "pair_id": 2},
    {"global_seat": 11, "scenario_id": "t2-temporal-trap", "pair_label": "B", "arm": "treatment", "pair_id": 2},
    {"global_seat": 12, "scenario_id": "t2-temporal-trap", "pair_label": "B", "arm": "control", "pair_id": 2},
    {"global_seat": 13, "scenario_id": "t2-identity-trap", "pair_label": "B", "arm": "treatment", "pair_id": 2},
    {"global_seat": 14, "scenario_id": "t2-identity-trap", "pair_label": "B", "arm": "control", "pair_id": 2},
    {"global_seat": 15, "scenario_id": "t2-report-citation", "pair_label": "B", "arm": "treatment", "pair_id": 2},
    {"global_seat": 16, "scenario_id": "t2-report-citation", "pair_label": "B", "arm": "control", "pair_id": 2},
]

REQUEST_BUDGET = {
    "stage_invocations": 16,
    "output_retry_budget_per_invocation": 1,
    "max_logical_model_generations": 32,
    "preflight_logical_requests": 3,
    "sdk_max_retries": SDK_MAX_RETRIES,  # 2
    "diagnostic_http_attempts_max": 32 * (1 + SDK_MAX_RETRIES),  # 96
    "preflight_http_attempts_max": 3 * (1 + SDK_MAX_RETRIES),  # 9
    "total_max_http_attempts": 35 * (1 + SDK_MAX_RETRIES),  # 105
}

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


@dataclass
class CrossCaseSeatContext:
    global_seat: int
    scenario_id: str
    pair_label: str  # "A" or "B"
    pair_id: int  # 1 or 2
    arm: str  # "control" or "treatment"
    fixture_record: dict[str, Any]
    harness: IsolatedIntegrationHarness
    diagnostic_sink_path: Path
    claim_path: Path
    phase: SeatPhase = SeatPhase.NOT_STARTED
    stage_invocations_started: int = 0
    stage_invocations_finished: int = 0
    identity_sink: list[dict[str, Any]] = field(default_factory=list)
    diagnostic_sink: Optional[JsonlFailureDiagnosticSink] = None
    model_proxy: Optional[RecordingProxyModel] = None
    stage_result: Optional[Any] = None
    oracle_result: Optional[OracleEvaluationResult] = None
    stop_reason: Optional[str] = None
    executed: bool = False
    outcome_status: Optional[str] = None
    claim_record: Optional[dict[str, Any]] = None
    record: Optional[dict[str, Any]] = None


async def setup_cross_case_pair_fixtures(
    scratch_root: Path,
    runtime_identity: dict[str, Any],
) -> tuple[dict[tuple[str, str, str], dict[str, Any]], list[dict[str, Any]]]:
    """Build cloned, physically isolated scratch stores for all 4 scenarios × 2 pairs = 8 pairs."""
    scratch_root.mkdir(parents=True, exist_ok=True)
    fixtures_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    pair_audits: list[dict[str, Any]] = []

    scenarios = ["t2-no-evidence", "t2-temporal-trap", "t2-identity-trap", "t2-report-citation"]

    for scenario_id in scenarios:
        for pair_label, pair_id in [("A", 1), ("B", 2)]:
            pair_dir = scratch_root / f"{scenario_id}_pair_{pair_label.lower()}"
            pair_identity = dict(runtime_identity)
            pair_identity["harness"] = f"RCA-2A.10-{scenario_id}-Pair-{pair_id:02d}"
            h_c, h_t, meta = await build_cloned_cross_case_pair(
                scenario_id=scenario_id,
                pair_id=pair_id,
                base_dir=pair_dir,
                runtime_identity=pair_identity,
            )

            # Cross-arm parity audit
            parity = await verify_cross_case_arm_parity(
                scenario_id=scenario_id,
                harness_control=h_c,
                harness_treatment=h_t,
            )
            if not parity["parity_pass"]:
                raise RuntimeError(
                    f"CROSS_ARM_PARITY_BLOCKED: {scenario_id} Pair {pair_label} failed parity check"
                )

            pair_audits.append({
                "scenario_id": scenario_id,
                "pair_label": pair_label,
                "pair_id": pair_id,
                "parity": parity,
            })

            c_input = h_c.isolated_input()
            t_input = h_t.isolated_input()

            fixtures_by_key[(scenario_id, pair_label, "control")] = {
                "scenario_id": scenario_id,
                "pair_label": pair_label,
                "pair_id": pair_id,
                "arm": "control",
                "fixture_path": meta["control_dir"],
                "task_id": meta["task_id"],
                "investigation_id": meta["investigation_id"],
                "run_id": meta["run_id"],
                "working_state_hash": c_input["working_state_hash"],
                "context_hash": c_input["integration_context_hash"],
                "binding_table_hash": c_input["reference_binding_table_hash"],
                "harness": h_c,
            }

            fixtures_by_key[(scenario_id, pair_label, "treatment")] = {
                "scenario_id": scenario_id,
                "pair_label": pair_label,
                "pair_id": pair_id,
                "arm": "treatment",
                "fixture_path": meta["treatment_dir"],
                "task_id": meta["task_id"],
                "investigation_id": meta["investigation_id"],
                "run_id": meta["run_id"],
                "working_state_hash": t_input["working_state_hash"],
                "context_hash": t_input["integration_context_hash"],
                "binding_table_hash": t_input["reference_binding_table_hash"],
                "harness": h_t,
            }

    return fixtures_by_key, pair_audits


def build_cross_case_seat_record(
    ctx: CrossCaseSeatContext,
    oracle: Optional[RCA2A9aSemanticOracleExtensionV1] = None,
) -> dict[str, Any]:
    """Build a detailed accounting and observation record for a single seat."""
    events = ctx.model_proxy.events if ctx.model_proxy else []
    response_events = [e for e in events if e.get("response_metadata")]
    validations = [p["parse_validation"] for e in response_events for p in e.get("payloads", [])]

    valid_handles = {b.handle for b in ctx.harness._table.bindings}
    for e in response_events:
        for p in e.get("payloads", []):
            parsed = p.get("parsed_payload")
            if parsed is not None:
                p["field_scan"] = scan_payload(parsed, valid_handles)

    payload_scans = [p["field_scan"] for e in response_events for p in e.get("payloads", [])]

    sink_entries = []
    if ctx.diagnostic_sink_path.exists():
        try:
            sink_entries = [
                json.loads(line)
                for line in ctx.diagnostic_sink_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except Exception:
            pass

    returned_names = [e.get("response_model") for e in response_events]
    identity_records = list(ctx.identity_sink)
    for e in response_events:
        identity_records.append({
            "requested_model": MODEL,
            "returned_model": e.get("response_model"),
        })

    error_types = [
        err["type"]
        for v in validations
        for g in v.get("error_groups", [])
        for err in g.get("errors", [])
    ]

    returned_identity_exact = bool(identity_records) and all(
        x.get("returned_model") == MODEL for x in identity_records
    )

    layers = (
        stage_layers(ctx.stage_result)
        if ctx.stage_result
        else {
            "stage_invocation_success": False,
            "output_tool_received": False,
            "pydantic_parse_success": False,
            "canonical_resolution_success": False,
            "integration_decision_validator_success": False,
            "transition_validation_success": False,
            "scratch_commit_success": False,
            "canonical_integration_valid": False,
            "resolution_violations": [],
            "exception_class": ctx.stop_reason,
        }
    )

    # Evaluate with Semantic Oracle if available
    oracle_eval: Optional[OracleEvaluationResult] = ctx.oracle_result
    if oracle_eval is None and oracle is not None and ctx.executed:
        # Extract last parsed payload if any
        decision_raw = None
        for e in reversed(response_events):
            for p in reversed(e.get("payloads", [])):
                if p.get("parsed_payload"):
                    decision_raw = p["parsed_payload"]
                    break
            if decision_raw:
                break

        state_before = ctx.harness._state
        table = ctx.harness._table
        context = ctx.harness._context
        expected_rev = ctx.harness._state_revision

        oracle_eval = oracle.evaluate_extended(
            scenario_id=ctx.scenario_id,
            decision_raw=decision_raw,
            table=table,
            context=context,
            state=state_before,
            expected_revision=expected_rev,
            arm=ctx.arm,
        )
        ctx.oracle_result = oracle_eval

    oracle_record = {
        "verdict": oracle_eval.verdict if oracle_eval else "UNOBSERVABLE",
        "adequacy": oracle_eval.l4_semantic_adequacy.value if oracle_eval else "UNOBSERVABLE",
        "information_value": oracle_eval.l5_information_value.value if oracle_eval else "UNOBSERVABLE",
        "triggered_negative_gates": (
            [g.value for g in oracle_eval.triggered_negative_gates] if oracle_eval else []
        ),
        "evaluation_notes": oracle_eval.violations if oracle_eval else [],
        "layers": {
            "L1_SCHEMA_VALIDITY": layers["pydantic_parse_success"],
            "L2_CANONICAL_RESOLUTION": layers["canonical_resolution_success"],
            "L3_TRANSITION_INTEGRITY": (
                layers["transition_validation_success"] and layers["scratch_commit_success"]
            ),
            "L4_SEMANTIC_ADEQUACY": (
                oracle_eval.l4_semantic_adequacy.value
                if oracle_eval
                else ("UNOBSERVABLE" if not layers["pydantic_parse_success"] else "UNKNOWN")
            ),
            "L5_INFORMATION_VALUE": (
                oracle_eval.l5_information_value.value
                if oracle_eval
                else ("UNOBSERVABLE" if not layers["pydantic_parse_success"] else "NEUTRAL")
            ),
        },
    }

    logical_gens = sum(
        bool(e.get("response_metadata")) or bool(e.get("provider_error_class")) for e in events
    )

    status = ctx.outcome_status or ("EXECUTED" if ctx.executed else "NOT_STARTED")

    return {
        "global_seat": ctx.global_seat,
        "scenario_id": ctx.scenario_id,
        "pair_label": ctx.pair_label,
        "pair_id": ctx.pair_id,
        "arm": ctx.arm,
        "status": status,
        "phase": ctx.phase.value,
        "durable_claim": ctx.claim_record,
        "logical_model_generations": logical_gens,
        "provider_error_classes": [
            e["provider_error_class"] for e in events if e.get("provider_error_class")
        ],
        "provider_error_classifications": [
            e["provider_classification"] for e in events if e.get("provider_classification")
        ],
        "pydantic_output_retries": max(
            0, sum(bool(e.get("response_metadata")) for e in events) - 1
        ),
        "http_attempts": "HTTP_ATTEMPTS_UNOBSERVABLE",
        "http_attempt_upper_bound": len(events) * (1 + SDK_MAX_RETRIES),
        "initial_attempt_error": (
            validations[0]["error_groups"] if validations and not validations[0]["passed"] else []
        ),
        "final_attempt_error": (
            validations[-1]["error_groups"] if validations and not validations[-1]["passed"] else []
        ),
        "initial_attempt_pydantic_pass": validations[0]["passed"] if validations else None,
        "final_attempt_pydantic_pass": validations[-1]["passed"] if validations else None,
        "validation_payload_count": len(validations),
        "retry_self_correction": bool(
            len(validations) >= 2 and not validations[0]["passed"] and validations[-1]["passed"]
        ),
        "field_scan_totals": {
            "to_status_completed": sum(s["to_status_completed"] for s in payload_scans),
            "invalid_disposition": sum(s["invalid_disposition"] for s in payload_scans),
            "wrong_action_field_name": sum(s["wrong_action_field_name"] for s in payload_scans),
            "invalid_union": sum(bool(v.get("union_cascade_payload")) for v in validations),
            "missing_required_field": sum(t == "missing" for t in error_types),
            "extra_forbidden": sum(t == "extra_forbidden" for t in error_types),
            "unknown_handle": sum(s["unknown_handle"] for s in payload_scans),
            "invalid_question_status": sum(s["invalid_question_status"] for s in payload_scans),
            "fabricated_evidence_like_identifier": sum(
                s["fabricated_evidence_like_identifier"] for s in payload_scans
            ),
        },
        "diagnostic_sink_entries": sink_entries,
        "stage_layers": layers,
        "semantic_oracle_evaluation": oracle_record,
        "response_models": returned_names,
        "identity_sink_records": identity_records,
        "returned_identity_exact": returned_identity_exact,
        "token_usage": {
            "input_tokens": sum((e.get("usage") or {}).get("input_tokens", 0) for e in events),
            "output_tokens": sum((e.get("usage") or {}).get("output_tokens", 0) for e in events),
        },
        "latency_ms": [e["latency_ms"] for e in response_events if e.get("latency_ms") is not None],
        "fixture_identity": {
            "scenario_id": ctx.scenario_id,
            "pair_label": ctx.pair_label,
            "pair_id": ctx.pair_id,
            "arm": ctx.arm,
            "task_id": ctx.fixture_record.get("task_id"),
            "investigation_id": ctx.fixture_record.get("investigation_id"),
            "run_id": ctx.fixture_record.get("run_id"),
        },
        "citation_boundary_discipline": {
            "scenario_id": ctx.scenario_id,
            "stage_applicability": SCENARIO_SPECS[ctx.scenario_id].stage_applicability,
            "calls_report_admission": False,
            "report_admission_status": "NOT_EXERCISED",
            "report_publication_status": "NOT_EXERCISED",
            "analyst_acceptance_status": "NOT_EXERCISED",
        },
    }


async def run_cross_case_seats(
    fixtures_by_key: dict[tuple[str, str, str], dict[str, Any]],
    diagnostics_dir: Path,
    claims_dir: Path,
    *,
    model_factory: Callable[[CrossCaseSeatContext], _PydanticAiModel],
    oracle: Optional[RCA2A9aSemanticOracleExtensionV1] = None,
    stop_early_after_seat: Optional[int] = None,
    allow_reexecution: bool = False,
    crash_before_result_recording: bool = False,
    experiment_id: str = EXPERIMENT_ID,
    seat_schedule: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Execute all seats in the schedule with durable claims, bounds, and stop rules."""
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    claims_dir.mkdir(parents=True, exist_ok=True)
    schedule = seat_schedule or SEAT_SCHEDULE
    oracle = oracle or RCA2A9aSemanticOracleExtensionV1()

    seat_contexts: list[CrossCaseSeatContext] = []
    executed_seats: set[tuple[str, str, str]] = set()

    total_logical_generations = 0
    total_invocations_started = 0
    total_invocations_finished = 0
    global_stop_reason: Optional[str] = None

    for entry in schedule:
        g_seat = entry["global_seat"]
        scenario_id = entry["scenario_id"]
        pair_label = entry["pair_label"]
        arm_name = entry["arm"]
        pair_id = entry["pair_id"]
        key = (scenario_id, pair_label, arm_name)

        fix_item = fixtures_by_key.get(key)
        if not fix_item:
            raise ValueError(f"Missing fixture record for seat {key}")

        harness: IsolatedIntegrationHarness = fix_item["harness"]
        sink_path = (diagnostics_dir / f"seat-{g_seat:02d}-{scenario_id}-{pair_label}-{arm_name}.jsonl").resolve()
        claim_path = (claims_dir / f"seat-{g_seat:02d}.claim.json").resolve()

        ctx = CrossCaseSeatContext(
            global_seat=g_seat,
            scenario_id=scenario_id,
            pair_label=pair_label,
            pair_id=pair_id,
            arm=arm_name,
            fixture_record=fix_item,
            harness=harness,
            diagnostic_sink_path=sink_path,
            claim_path=claim_path,
        )
        seat_contexts.append(ctx)

        # Check if global stop condition was already hit
        if global_stop_reason is not None:
            ctx.phase = SeatPhase.NOT_STARTED
            ctx.stop_reason = global_stop_reason
            ctx.record = build_cross_case_seat_record(ctx, oracle)
            continue

        # Duplicate seat execution check
        if key in executed_seats and not allow_reexecution:
            global_stop_reason = "DUPLICATE_SEAT_EXECUTION_PROHIBITED"
            ctx.stop_reason = global_stop_reason
            ctx.phase = SeatPhase.NOT_STARTED
            ctx.record = build_cross_case_seat_record(ctx, oracle)
            break

        # Check durable seat claim collision / prior crash
        if claim_path.exists():
            try:
                claim_data = json.loads(claim_path.read_text(encoding="utf-8"))
            except Exception:
                claim_data = {"status": "ATTEMPT_OUTCOME_UNKNOWN"}
            ctx.claim_record = claim_data
            if (
                claim_data.get("status") in ("ATTEMPT_OUTCOME_UNKNOWN", "CLAIMED_BEFORE_INVOCATION")
                or claim_data.get("claimed_phase") == "INVOCATION_STARTED"
            ):
                global_stop_reason = "SEAT_ALREADY_CLAIMED_OR_OUTCOME_UNKNOWN"
                ctx.outcome_status = "ATTEMPT_OUTCOME_UNKNOWN"
                ctx.stop_reason = global_stop_reason
                ctx.phase = SeatPhase.INVOCATION_STARTED
                ctx.record = build_cross_case_seat_record(ctx, oracle)
                continue
            elif claim_data.get("status") == "COMPLETED" and not allow_reexecution:
                global_stop_reason = "SEAT_ALREADY_COMPLETED_REEXECUTION_PROHIBITED"
                ctx.stop_reason = global_stop_reason
                ctx.phase = SeatPhase.RESULT_RECORDED
                ctx.record = build_cross_case_seat_record(ctx, oracle)
                continue

        # Phase 1 -> 2: INPUT_VERIFIED
        before = harness.isolated_input()
        if (
            before["working_state_hash"] != fix_item["working_state_hash"]
            or before["integration_context_hash"] != fix_item["context_hash"]
            or before["reference_binding_table_hash"] != fix_item["binding_table_hash"]
        ):
            global_stop_reason = "EXPERIMENT_IDENTITY_DRIFT"
            ctx.phase = SeatPhase.NOT_STARTED
            ctx.stop_reason = global_stop_reason
            ctx.record = build_cross_case_seat_record(ctx, oracle)
            continue

        ctx.phase = SeatPhase.INPUT_VERIFIED

        # Mid-run interruption simulation
        if stop_early_after_seat is not None and g_seat > stop_early_after_seat:
            global_stop_reason = "SIMULATED_INTERRUPTION"
            ctx.phase = SeatPhase.NOT_STARTED
            ctx.stop_reason = global_stop_reason
            ctx.record = build_cross_case_seat_record(ctx, oracle)
            continue

        # Diagnostic sink exclusive creation (0600)
        if sink_path.exists():
            global_stop_reason = "DIAGNOSTIC_INSTRUMENTATION_FAILURE"
            ctx.stop_reason = global_stop_reason
            ctx.record = build_cross_case_seat_record(ctx, oracle)
            continue

        try:
            ctx.diagnostic_sink = create_exclusive_diagnostic_sink(sink_path)
        except Exception:
            global_stop_reason = "DIAGNOSTIC_INSTRUMENTATION_FAILURE"
            ctx.stop_reason = global_stop_reason
            ctx.record = build_cross_case_seat_record(ctx, oracle)
            continue

        # Durable Seat Claim: persist exclusively to disk BEFORE any remote invocation
        claim_data = {
            "artifact_version": "RCA2A10SeatClaimV1",
            "experiment_id": experiment_id,
            "global_seat": g_seat,
            "scenario_id": scenario_id,
            "pair_label": pair_label,
            "pair_id": pair_id,
            "arm": arm_name,
            "claimed_phase": "INVOCATION_STARTED",
            "claimed_at_monotonic": time.monotonic(),
            "status": "ATTEMPT_OUTCOME_UNKNOWN",
        }
        try:
            with open(claim_path, "x", encoding="utf-8") as f:
                os.chmod(claim_path, 0o600)
                json.dump(claim_data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
        except FileExistsError:
            global_stop_reason = "SEAT_ALREADY_CLAIMED_OR_OUTCOME_UNKNOWN"
            ctx.outcome_status = "ATTEMPT_OUTCOME_UNKNOWN"
            ctx.stop_reason = global_stop_reason
            ctx.phase = SeatPhase.INVOCATION_STARTED
            ctx.record = build_cross_case_seat_record(ctx, oracle)
            continue
        ctx.claim_record = claim_data

        # Phase 2 -> 3: INVOCATION_STARTED
        ctx.phase = SeatPhase.INVOCATION_STARTED
        ctx.stage_invocations_started += 1
        total_invocations_started += 1

        inner_model = model_factory(ctx)
        proxy_model = RecordingProxyModel(inner_model)
        ctx.model_proxy = proxy_model

        factory = (
            SupervisorAgentFactory if arm_name == "control" else GuidanceIntegrationAgentFactory
        )

        # Phase 3 -> 4: INVOCATION_FINISHED
        try:
            stage_res = await harness.run_stage(
                model=proxy_model,
                diagnostic_sink=ctx.diagnostic_sink,
                agent_factory=factory,
            )
            ctx.stage_result = stage_res
            ctx.phase = SeatPhase.INVOCATION_FINISHED
            ctx.stage_invocations_finished += 1
            total_invocations_finished += 1
            ctx.executed = True
            executed_seats.add(key)
        except Exception as exc:
            ctx.phase = SeatPhase.INVOCATION_FINISHED
            ctx.stage_invocations_finished += 1
            total_invocations_finished += 1
            ctx.executed = True
            executed_seats.add(key)
            ctx.stop_reason = f"UNEXPECTED_EXCEPTION:{type(exc).__name__}"
            global_stop_reason = ctx.stop_reason
            ctx.record = build_cross_case_seat_record(ctx, oracle)
            total_logical_generations += len(proxy_model.events)
            continue

        gens = len(proxy_model.events)
        total_logical_generations += gens

        # Crash simulation before result recording
        if crash_before_result_recording and g_seat == 1:
            global_stop_reason = "SIMULATED_CRASH_BEFORE_RESULT_RECORDING"
            ctx.outcome_status = "ATTEMPT_OUTCOME_UNKNOWN"
            ctx.stop_reason = global_stop_reason
            ctx.record = build_cross_case_seat_record(ctx, oracle)
            continue

        # Phase 4 -> 5: RESULT_RECORDED
        ctx.phase = SeatPhase.RESULT_RECORDED

        # Finalize durable claim atomically
        claim_data["claimed_phase"] = "RESULT_RECORDED"
        claim_data["finalized_at_monotonic"] = time.monotonic()
        claim_data["status"] = "COMPLETED"
        tmp_claim = claim_path.with_suffix(".tmp")
        tmp_claim.write_text(json.dumps(claim_data, indent=2), encoding="utf-8")
        os.chmod(tmp_claim, 0o600)
        tmp_claim.replace(claim_path)
        ctx.claim_record = claim_data

        record = build_cross_case_seat_record(ctx, oracle)
        ctx.record = record

        # Stop conditions evaluation
        exc_class = record["stage_layers"]["exception_class"]
        provider_errs = record.get("provider_error_classes", [])
        has_provider_failure = (
            is_provider_error_class(exc_class)
            or any(is_provider_error_class(c) for c in provider_errs)
        )

        # 1. Unexpected runner exception
        if (
            exc_class not in (None, "UnexpectedModelBehavior")
            and not has_provider_failure
        ):
            global_stop_reason = f"UNEXPECTED_EXCEPTION:{exc_class}"

        # 2. Provider failure
        elif has_provider_failure:
            global_stop_reason = "PROVIDER_CAPACITY_OR_CONNECTIVITY_FAILURE"

        # 3. Model identity mismatch
        elif (
            any(x.get("returned_model") != MODEL for x in record["identity_sink_records"])
            or (record["stage_layers"]["exception_class"] is None and not record["returned_identity_exact"])
        ):
            global_stop_reason = "MODEL_IDENTITY_MISMATCH"

        # 4. Fabricated evidence or basis handle
        elif record["field_scan_totals"].get("fabricated_evidence_like_identifier", 0) > 0:
            global_stop_reason = "FABRICATED_EVIDENCE_OR_BASIS_HANDLE"

        # 5. Mandatory Negative Gate violations
        elif ctx.oracle_result and ctx.oracle_result.triggered_negative_gates:
            gates = [g.value for g in ctx.oracle_result.triggered_negative_gates]
            # If an unauthorized commit occurred into state
            if NegativeGateCode.UNAUTHORIZED_COMMIT in ctx.oracle_result.triggered_negative_gates:
                global_stop_reason = f"MANDATORY_NEGATIVE_GATE_VIOLATION:{','.join(gates)}"
            elif record["stage_layers"].get("scratch_commit_success"):
                global_stop_reason = f"MANDATORY_NEGATIVE_GATE_VIOLATION_COMMITTED:{','.join(gates)}"

        # 6. Budget exceeded
        elif total_logical_generations > REQUEST_BUDGET["max_logical_model_generations"]:
            global_stop_reason = "REQUEST_BUDGET_EXCEEDED"

        # 7. Diagnostic data quality verification
        if not global_stop_reason and sink_path.exists():
            try:
                read_and_validate_sink_entries(
                    sink_path,
                    expected_stage="SUPERVISOR_INTEGRATE",
                    require_validation_details=False,
                    allow_empty=True,
                )
            except DiagnosticDataQualityError:
                global_stop_reason = "DIAGNOSTIC_INSTRUMENTATION_FAILURE"

        if global_stop_reason:
            ctx.stop_reason = global_stop_reason
            continue

    matrix_seats = [c.record or build_cross_case_seat_record(c, oracle) for c in seat_contexts]

    return {
        "artifact_version": "RCA2A10PairedExecutionMatrixV1",
        "experiment_id": experiment_id,
        "run_order": [dict(s) for s in schedule],
        "stage_invocations_scheduled": len(schedule),
        "stage_invocations_started": total_invocations_started,
        "stage_invocations_finished": total_invocations_finished,
        "stage_invocations_executed": sum(s["status"] == "EXECUTED" for s in matrix_seats),
        "logical_model_generations": total_logical_generations,
        "logical_model_generations_budget": REQUEST_BUDGET["max_logical_model_generations"],
        "preflight_logical_requests": 0,
        "http_attempts": "HTTP_ATTEMPTS_UNOBSERVABLE",
        "stop_reason": global_stop_reason,
        "seats": matrix_seats,
        "real_model_requests": 0,
        "observation_tag": "CROSS_CASE_OBSERVATIONS",
    }


def compute_cross_case_paired_metrics(matrix: dict[str, Any]) -> dict[str, Any]:
    """Compute paired metrics for all 8 pairs and scenario-stratified breakdown."""
    seats = matrix["seats"]
    scenarios = ["t2-no-evidence", "t2-temporal-trap", "t2-identity-trap", "t2-report-citation"]
    by_pair = {}

    for scenario_id in scenarios:
        for pair_label in ["A", "B"]:
            pair_key = f"{scenario_id}_{pair_label}"
            control_seats = [
                s for s in seats
                if s["scenario_id"] == scenario_id and s["pair_label"] == pair_label and s["arm"] == "control"
            ]
            treatment_seats = [
                s for s in seats
                if s["scenario_id"] == scenario_id and s["pair_label"] == pair_label and s["arm"] == "treatment"
            ]

            if not control_seats or not treatment_seats:
                continue

            control = control_seats[0]
            treatment = treatment_seats[0]

            # Contract layer outcome
            c_valid = (
                control.get("stage_layers", {}).get("canonical_integration_valid")
                if control["status"] == "EXECUTED"
                else None
            )
            t_valid = (
                treatment.get("stage_layers", {}).get("canonical_integration_valid")
                if treatment["status"] == "EXECUTED"
                else None
            )

            if c_valid is True and t_valid is True:
                contract_outcome = "BOTH_VALID"
            elif c_valid is True and t_valid is False:
                contract_outcome = "CONTROL_WIN"
            elif t_valid is True and c_valid is False:
                contract_outcome = "TREATMENT_WIN"
            elif c_valid is False and t_valid is False:
                contract_outcome = "BOTH_INVALID"
            else:
                contract_outcome = "INCOMPLETE_PAIR"

            # Semantic layer outcome
            c_sem = control.get("semantic_oracle_evaluation", {}).get("adequacy")
            t_sem = treatment.get("semantic_oracle_evaluation", {}).get("adequacy")

            c_adeq = c_sem in (
                SemanticAdequacy.SEMANTICALLY_ADEQUATE.value,
                SemanticAdequacy.VALID_BUT_INFORMATION_NEUTRAL.value,
            )
            t_adeq = t_sem in (
                SemanticAdequacy.SEMANTICALLY_ADEQUATE.value,
                SemanticAdequacy.VALID_BUT_INFORMATION_NEUTRAL.value,
            )

            if c_adeq and t_adeq:
                semantic_outcome = "BOTH_SEMANTICALLY_ADEQUATE"
            elif not c_adeq and not t_adeq:
                if c_sem in ("UNOBSERVABLE", None) or t_sem in ("UNOBSERVABLE", None):
                    semantic_outcome = "SEMANTIC_COMPARISON_UNAVAILABLE"
                else:
                    semantic_outcome = "BOTH_SEMANTICALLY_INADEQUATE"
            elif t_adeq and not c_adeq:
                semantic_outcome = "TREATMENT_SEMANTIC_WIN"
            elif c_adeq and not t_adeq:
                semantic_outcome = "CONTROL_SEMANTIC_WIN"
            else:
                semantic_outcome = "SEMANTIC_COMPARISON_UNAVAILABLE"

            by_pair[pair_key] = {
                "scenario_id": scenario_id,
                "pair_label": pair_label,
                "contract_outcome": contract_outcome,
                "semantic_outcome": semantic_outcome,
                "control_seat": control["global_seat"],
                "treatment_seat": treatment["global_seat"],
                "control_canonical_valid": c_valid,
                "treatment_canonical_valid": t_valid,
                "control_semantic_adequacy": c_sem,
                "treatment_semantic_adequacy": t_sem,
                "control_information_value": control.get("semantic_oracle_evaluation", {}).get("information_value"),
                "treatment_information_value": treatment.get("semantic_oracle_evaluation", {}).get("information_value"),
            }

    # Stratified by scenario
    scenario_stratified = {}
    for sc in scenarios:
        sc_pairs = [v for k, v in by_pair.items() if v["scenario_id"] == sc]
        scenario_stratified[sc] = {
            "pairs_count": len(sc_pairs),
            "contract_outcomes": [p["contract_outcome"] for p in sc_pairs],
            "semantic_outcomes": [p["semantic_outcome"] for p in sc_pairs],
            "treatment_contract_wins": sum(p["contract_outcome"] == "TREATMENT_WIN" for p in sc_pairs),
            "control_contract_wins": sum(p["contract_outcome"] == "CONTROL_WIN" for p in sc_pairs),
            "both_valid": sum(p["contract_outcome"] == "BOTH_VALID" for p in sc_pairs),
            "both_invalid": sum(p["contract_outcome"] == "BOTH_INVALID" for p in sc_pairs),
            "treatment_semantic_wins": sum(p["semantic_outcome"] == "TREATMENT_SEMANTIC_WIN" for p in sc_pairs),
            "control_semantic_wins": sum(p["semantic_outcome"] == "CONTROL_SEMANTIC_WIN" for p in sc_pairs),
            "both_semantically_adequate": sum(p["semantic_outcome"] == "BOTH_SEMANTICALLY_ADEQUATE" for p in sc_pairs),
        }

    all_contract = [p["contract_outcome"] for p in by_pair.values()]
    all_semantic = [p["semantic_outcome"] for p in by_pair.values()]

    return {
        "pairs": by_pair,
        "scenario_stratified": scenario_stratified,
        "total_pairs": len(by_pair),
        "contract_summary": {
            "treatment_win": all_contract.count("TREATMENT_WIN"),
            "control_win": all_contract.count("CONTROL_WIN"),
            "both_valid": all_contract.count("BOTH_VALID"),
            "both_invalid": all_contract.count("BOTH_INVALID"),
            "incomplete_pair": all_contract.count("INCOMPLETE_PAIR"),
        },
        "semantic_summary": {
            "treatment_semantic_win": all_semantic.count("TREATMENT_SEMANTIC_WIN"),
            "control_semantic_win": all_semantic.count("CONTROL_SEMANTIC_WIN"),
            "both_semantically_adequate": all_semantic.count("BOTH_SEMANTICALLY_ADEQUATE"),
            "both_semantically_inadequate": all_semantic.count("BOTH_SEMANTICALLY_INADEQUATE"),
            "semantic_comparison_unavailable": all_semantic.count("SEMANTIC_COMPARISON_UNAVAILABLE"),
        },
    }
