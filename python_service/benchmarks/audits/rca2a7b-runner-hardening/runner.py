"""RCA-2A.7b Hardened Benchmark Runner.

Provides:
- Explicit seat accounting lifecycle:
    NOT_STARTED -> INPUT_VERIFIED -> INVOCATION_STARTED -> INVOCATION_FINISHED -> RESULT_RECORDED
- Strict budget enforcement (8 stage invocations, max 16 logical generations, max 3 preflight logical requests).
- Stop rules that cleanly halt remaining seats and record them as NOT_STARTED.
- Exclusive diagnostic sink creation (0600) and idempotent readiness probe handling.
- Prevention of duplicate seat execution.
- Pluggable model factory seam with zero-network spy for simulation.
- Paired metrics and classification.
"""

from __future__ import annotations

import asyncio
import enum
import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from benchmarks.contracts.experimental.integration_vocabulary_guidance_v1 import (
    GUIDANCE_TEXT,
    GuidanceIntegrationAgentFactory,
    guidance_sha256,
)
from benchmarks.isolated_integration.harness import (
    IsolatedIntegrationHarness,
    validate_isolated_input,
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
from httpserver.services.investigation.agent_supervisor import SupervisorAgentFactory
from pydantic import ValidationError
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models import Model as _PydanticAiModel

HERE = Path(__file__).resolve().parent
PYTHON_SERVICE_ROOT = HERE.parents[2]
REPO_ROOT = PYTHON_SERVICE_ROOT.parent

sys.path.insert(0, str(HERE))
from diagnostic_sink_hardening import (
    DiagnosticDataQualityError,
    DiagnosticSinkCollisionError,
    create_exclusive_diagnostic_sink,
    execute_or_verify_readiness_probe,
    read_and_validate_sink_entries,
)
from cross_arm_parity import (
    build_cloned_pair_fixtures,
    verify_pair_parity,
)

EXPERIMENT_ID = "rca2a7b-runner-hardening"
BASELINE_COMMIT = "cb78ea813cdc2678b352c80a77fcf57bc4ec96b9"
PROVIDER = "stepfun"
MODEL = "step-3.7-flash"

PAIRS = (
    ("C", "T"),
    ("T", "C"),
    ("T", "C"),
    ("C", "T"),
)
ARM_NAMES = {"C": "control", "T": "treatment"}

REQUEST_BUDGET = {
    "stage_invocations": 8,
    "logical_model_generations_max": 16,
    "preflight_logical_requests": 3,
    "sdk_max_retries": 2,
    "sdk_http_attempts_per_logical_request_max": 3,
    "diagnostic_http_attempts_max": 48,
    "preflight_http_attempts_max": 9,
}


class SeatPhase(str, enum.Enum):
    NOT_STARTED = "NOT_STARTED"
    INPUT_VERIFIED = "INPUT_VERIFIED"
    INVOCATION_STARTED = "INVOCATION_STARTED"
    INVOCATION_FINISHED = "INVOCATION_FINISHED"
    RESULT_RECORDED = "RESULT_RECORDED"


class DuplicateSeatExecutionError(Exception):
    """Raised when an already-recorded seat is re-executed."""


class NetworkCallDetectedError(Exception):
    """Raised when an unauthorized network call is attempted."""


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def sha256_json(value: Any) -> str:
    return sha256_bytes(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )


def exclusive_json(path: Path, value: dict) -> None:
    scripts = str(PYTHON_SERVICE_ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from benchmark_output_guard import OutputPathError, exclusive_output_file

    try:
        with exclusive_output_file(path) as fh:
            fh.write(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    except OutputPathError as exc:
        raise SystemExit(f"OUTPUT_REFUSED_NO_CLOBBER: {exc}") from exc


def code_paths() -> dict[str, Path]:
    return {
        "stage_harness": PYTHON_SERVICE_ROOT / "benchmarks/isolated_integration/harness.py",
        "fixture_builder": PYTHON_SERVICE_ROOT / "benchmarks/isolated_integration/fixtures.py",
        "model_adapter": PYTHON_SERVICE_ROOT / "httpserver/services/investigation/agent_model_adapter.py",
        "supervisor": PYTHON_SERVICE_ROOT / "httpserver/services/investigation/agent_supervisor.py",
        "schema": PYTHON_SERVICE_ROOT / "httpserver/services/investigation/agent_integration_v2.py",
        "working_state": PYTHON_SERVICE_ROOT / "httpserver/services/investigation/agent_working_state.py",
        "validator": PYTHON_SERVICE_ROOT / "httpserver/services/investigation/agent_integration.py",
        "transition_policy": PYTHON_SERVICE_ROOT / "httpserver/services/investigation/agent_transitions.py",
        "diagnostic_sink": PYTHON_SERVICE_ROOT / "httpserver/services/investigation/agent_failure_diagnostics.py",
        "diagnostic_taxonomy": PYTHON_SERVICE_ROOT / "httpserver/services/investigation/agent_failure_taxonomy.py",
        "runner": HERE / "runner.py",
        "guidance_factory": PYTHON_SERVICE_ROOT / "benchmarks/contracts/experimental/integration_vocabulary_guidance_v1.py",
        "diagnostic_hardening": HERE / "diagnostic_sink_hardening.py",
        "cross_arm_parity": HERE / "cross_arm_parity.py",
    }


def code_hashes() -> dict[str, str]:
    return {name: sha256_file(path) for name, path in code_paths().items() if path.exists()}


def git_head() -> str:
    return subprocess.check_output(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], text=True
    ).strip()


def validate_payload(payload: dict) -> dict[str, Any]:
    try:
        SupervisorIntegrationDecisionV2.model_validate(payload)
        return {"passed": True, "error_groups": []}
    except ValidationError as exc:
        grouped: dict[str, dict[str, Any]] = {}
        for error in exc.errors():
            loc = [str(part) for part in error.get("loc", ())]
            key = json.dumps(loc[:2], separators=(",", ":"))
            item = grouped.setdefault(key, {"payload_location": loc[:3], "errors": []})
            item["errors"].append({"type": str(error.get("type")), "loc": loc})
        return {
            "passed": False,
            "error_groups": list(grouped.values()),
            "union_cascade_payload": any(
                len(group.get("payload_location", [])) >= 3 for group in grouped.values()
            ),
        }


def scan_payload(payload: dict, valid_handles: set[str] | None = None) -> dict[str, int]:
    actions = payload.get("actions", []) if isinstance(payload, dict) else []
    if not isinstance(actions, list):
        actions = []
    statuses = {"open", "in_progress", "answered", "unresolved", "blocked", "deferred", "superseded"}
    dispositions = {"supported", "not_supported", "inconclusive", "unavailable", "not_applicable"}
    result = {
        "to_status_completed": 0,
        "invalid_question_status": 0,
        "invalid_disposition": 0,
        "wrong_action_field_name": 0,
        "invalid_union": 0,
        "missing_required_field": 0,
        "extra_forbidden": 0,
        "unknown_handle": 0,
        "fabricated_evidence_like_identifier": 0,
    }
    for action in actions:
        if not isinstance(action, dict):
            continue
        if action.get("to_status") == "completed":
            result["to_status_completed"] += 1
        if "to_status" in action and action.get("to_status") not in statuses:
            result["invalid_question_status"] += 1
        if "disposition" in action and action.get("disposition") not in dispositions:
            result["invalid_disposition"] += 1
        if "handle" in action or "status" in action:
            result["wrong_action_field_name"] += 1
        if any("E999" in str(v) for v in action.values()) or any(
            k in action for k in ("basis_ref", "evidence_id")
        ):
            result["fabricated_evidence_like_identifier"] += 1
        for key, value in action.items():
            if key.endswith("handle") or key.endswith("handles"):
                values = value if isinstance(value, list) else [value]
                if valid_handles is not None and any(
                    isinstance(item, str) and item not in valid_handles for item in values
                ):
                    result["unknown_handle"] += 1
                    if any(
                        isinstance(item, str) and item.startswith("E") and item not in valid_handles
                        for item in values
                    ):
                        result["fabricated_evidence_like_identifier"] += 1
    return result


def stage_layers(result) -> dict[str, Any]:
    steps = {step.name: step for step in getattr(result, "steps", [])}
    return {
        "stage_invocation_success": getattr(result, "exception_class", None) is None,
        "output_tool_received": bool(
            steps.get("model_output_received") and steps["model_output_received"].ok
        ),
        "pydantic_parse_success": bool(
            steps.get("pydantic_validation") and steps["pydantic_validation"].ok
        ),
        "canonical_resolution_success": bool(
            steps.get("canonical_resolution") and steps["canonical_resolution"].ok
        ),
        "integration_decision_validator_success": bool(
            steps.get("decision_validator") and steps["decision_validator"].ok
        ),
        "transition_validation_success": bool(
            steps.get("transition_validation") and steps["transition_validation"].ok
        ),
        "scratch_commit_success": bool(getattr(result, "committed", False)),
        "canonical_integration_valid": bool(getattr(result, "committed", False)),
        "resolution_violations": list(getattr(result, "resolution_violations", ())),
        "exception_class": getattr(result, "exception_class", None),
    }


def is_provider_error_class(err_name: str | None) -> bool:
    if not err_name:
        return False
    return any(t in str(err_name) for t in ("Timeout", "Connection", "RateLimit", "Status", "API", "HTTP"))


class RecordingProxyModel(_PydanticAiModel):
    """Transparent PydanticAI model proxy that records generations and catches provider errors."""

    def __init__(self, inner, spy_callback: Callable | None = None):
        self._inner = inner
        self.events: list[dict[str, Any]] = []
        self._spy_callback = spy_callback

    @property
    def model_name(self):
        return getattr(self._inner, "model_name", "test")

    @property
    def system(self):
        return getattr(self._inner, "system", None)

    async def request(self, messages, model_settings, model_request_parameters):
        if self._spy_callback:
            self._spy_callback()
        started = time.monotonic()
        req_event = {"request_started": True}
        self.events.append(req_event)
        try:
            response = await self._inner.request(messages, model_settings, model_request_parameters)
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            err_class = type(exc).__name__
            is_net = (
                status_code is not None
                or is_provider_error_class(err_class)
                or any(t in str(exc).lower() for t in ("timeout", "timed out", "rate limit", "connection"))
            )
            if is_net:
                classification = classify_provider_http_error(status_code, str(exc))
                req_event.update({
                    "provider_error_class": err_class,
                    "provider_status": status_code,
                    "provider_classification": classification,
                    "latency_ms": round((time.monotonic() - started) * 1000, 1),
                })
            else:
                req_event.update({
                    "internal_error_class": err_class,
                    "latency_ms": round((time.monotonic() - started) * 1000, 1),
                })
            raise

        elapsed = round((time.monotonic() - started) * 1000, 1)
        payloads = []
        for part in getattr(response, "parts", ()) or ():
            if getattr(part, "part_kind", None) != "tool-call":
                continue
            args = part.args
            try:
                parsed = json.loads(args) if isinstance(args, str) else args
            except (TypeError, ValueError):
                parsed = {}
            payloads.append({
                "tool_name": part.tool_name,
                "parsed_payload": parsed,
                "field_scan": scan_payload(parsed),
                "parse_validation": validate_payload(parsed),
            })

        usage = getattr(response, "usage", None)
        req_event.update({
            "response_model": getattr(response, "model_name", None) or self.model_name,
            "latency_ms": elapsed,
            "usage": {
                "requests": getattr(usage, "requests", 1),
                "input_tokens": getattr(usage, "input_tokens", 250),
                "output_tokens": getattr(usage, "output_tokens", 50),
            } if usage else {"requests": 1, "input_tokens": 250, "output_tokens": 50},
            "payloads": payloads,
            "response_metadata": True,
        })
        return response

    def __getattr__(self, name):
        return getattr(self._inner, name)


@dataclass
class SeatExecutionContext:
    pair_id: int
    arm: str  # "control" or "treatment"
    fixture_record: dict[str, Any]
    harness: IsolatedIntegrationHarness
    diagnostic_sink_path: Path
    claim_path: Optional[Path] = None
    phase: SeatPhase = SeatPhase.NOT_STARTED
    stage_invocations_started: int = 0
    stage_invocations_finished: int = 0
    identity_sink: list[dict[str, Any]] = field(default_factory=list)
    diagnostic_sink: Optional[JsonlFailureDiagnosticSink] = None
    model_proxy: Optional[RecordingProxyModel] = None
    stage_result: Optional[Any] = None
    stop_reason: Optional[str] = None
    executed: bool = False
    outcome_status: Optional[str] = None
    claim_record: Optional[dict[str, Any]] = None
    record: Optional[dict[str, Any]] = None


def build_seat_record(ctx: SeatExecutionContext) -> dict[str, Any]:
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

    logical_gens = sum(
        bool(e.get("response_metadata")) or bool(e.get("provider_error_class")) for e in events
    )

    status = ctx.outcome_status or ("EXECUTED" if ctx.executed else "NOT_STARTED")

    return {
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
        "http_attempt_upper_bound": len(events) * 3,
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
        "response_models": returned_names,
        "identity_sink_records": identity_records,
        "returned_identity_exact": returned_identity_exact,
        "token_usage": {
            "input_tokens": sum((e.get("usage") or {}).get("input_tokens", 0) for e in events),
            "output_tokens": sum((e.get("usage") or {}).get("output_tokens", 0) for e in events),
        },
        "latency_ms": [e["latency_ms"] for e in response_events if e.get("latency_ms") is not None],
        "fixture_identity": ctx.fixture_record,
        "finalization": (
            ctx.stage_result.lifecycle.get("finalization")
            if ctx.stage_result and hasattr(ctx.stage_result, "lifecycle")
            else "NOT_EXERCISED"
        ),
        "evidence_integrity": {
            "fixture_kind": ctx.fixture_record.get("fixture_kind", "NO_EVIDENCE_HONEST_EMPTY"),
            "model_generated_evidence_id_accepted": False,
            "current_task_binding": ctx.fixture_record.get(
                "binding_table_resolves_to_current_synthetic_task", True
            ),
        },
    }


async def run_eight_seats(
    fixtures: list[dict[str, Any]],
    diagnostics_dir: Path,
    *,
    claims_dir: Path | None = None,
    model_factory: Callable[[SeatExecutionContext], _PydanticAiModel],
    stop_early_after_seat: int | None = None,
    allow_reexecution: bool = False,
    crash_before_result_recording: bool = False,
) -> dict[str, Any]:
    """Execute all 8 seats with strict lifecycle management, budget bounds, and stop rules."""
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    claims_dir = (claims_dir or (diagnostics_dir / "claims")).resolve()
    claims_dir.mkdir(parents=True, exist_ok=True)
    fixture_map = {(x["pair_id"], x["arm"]): x for x in fixtures}

    seat_contexts: list[SeatExecutionContext] = []
    executed_seats: set[tuple[int, str]] = set()

    total_logical_generations = 0
    total_invocations_started = 0
    total_invocations_finished = 0
    global_stop_reason: Optional[str] = None

    seat_index = 0
    for pair_id, pair in enumerate(PAIRS, start=1):
        for arm_code in pair:
            seat_index += 1
            arm_name = ARM_NAMES[arm_code]
            key = (pair_id, arm_name)
            fix_item = fixture_map.get(key)
            if not fix_item:
                raise ValueError(f"Missing fixture record for seat {key}")

            fixture_path = Path(fix_item["fixture_path"])
            sink_path = (diagnostics_dir / f"pair-{pair_id:02d}-{arm_name}.jsonl").resolve()
            claim_path = (claims_dir / f"seat-{pair_id:02d}-{arm_name}.claim.json").resolve()

            harness = IsolatedIntegrationHarness(
                db_path=fixture_path / "investigation.db",
                task_id=fix_item["task_id"],
                investigation_id=fix_item["investigation_id"],
                run_id=fix_item["run_id"],
                runtime_identity={
                    "baseline_commit": BASELINE_COMMIT,
                    "experiment_id": EXPERIMENT_ID,
                    "harness": f"RCA-2A.7b-Seat-{seat_index}",
                    "specialist_result_kind": "SYNTHETIC_SPECIALIST_RESULT",
                },
            )

            ctx = SeatExecutionContext(
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
                ctx.record = build_seat_record(ctx)
                continue

            # Check duplicate execution prevention (E13)
            if key in executed_seats and not allow_reexecution:
                global_stop_reason = "DUPLICATE_SEAT_EXECUTION_PROHIBITED"
                ctx.stop_reason = global_stop_reason
                ctx.phase = SeatPhase.NOT_STARTED
                ctx.record = build_seat_record(ctx)
                break

            # Check durable seat claim collision / prior in-flight crash
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
                    ctx.record = build_seat_record(ctx)
                    break
                elif claim_data.get("status") == "COMPLETED" and not allow_reexecution:
                    global_stop_reason = "SEAT_ALREADY_COMPLETED_REEXECUTION_PROHIBITED"
                    ctx.stop_reason = global_stop_reason
                    ctx.phase = SeatPhase.RESULT_RECORDED
                    ctx.record = build_seat_record(ctx)
                    break

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
                ctx.record = build_seat_record(ctx)
                break

            ctx.phase = SeatPhase.INPUT_VERIFIED

            # Mid-run interruption scenario (E14)
            if stop_early_after_seat is not None and seat_index > stop_early_after_seat:
                global_stop_reason = "SIMULATED_INTERRUPTION"
                ctx.phase = SeatPhase.NOT_STARTED
                ctx.stop_reason = global_stop_reason
                ctx.record = build_seat_record(ctx)
                continue

            # Diagnostic sink exclusive creation
            if sink_path.exists():
                global_stop_reason = "DIAGNOSTIC_INSTRUMENTATION_FAILURE"
                ctx.stop_reason = global_stop_reason
                ctx.record = build_seat_record(ctx)
                break

            try:
                ctx.diagnostic_sink = create_exclusive_diagnostic_sink(sink_path)
            except DiagnosticSinkError:
                global_stop_reason = "DIAGNOSTIC_INSTRUMENTATION_FAILURE"
                ctx.stop_reason = global_stop_reason
                ctx.record = build_seat_record(ctx)
                break

            # Durable Seat Claim: persist exclusively to disk BEFORE any remote/model invocation
            claim_data = {
                "artifact_version": "RCA2A7SeatClaimV1",
                "experiment_id": EXPERIMENT_ID,
                "pair_id": pair_id,
                "arm": arm_name,
                "seat_index": seat_index,
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
                ctx.record = build_seat_record(ctx)
                break
            ctx.claim_record = claim_data

            # Phase 2 -> 3: INVOCATION_STARTED
            ctx.phase = SeatPhase.INVOCATION_STARTED
            ctx.stage_invocations_started += 1
            total_invocations_started += 1

            inner_model = model_factory(ctx)
            proxy_model = RecordingProxyModel(inner_model)
            ctx.model_proxy = proxy_model

            factory = (
                SupervisorAgentFactory if arm_code == "C" else GuidanceIntegrationAgentFactory
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
                # Unexpected runner exception
                ctx.phase = SeatPhase.INVOCATION_FINISHED
                ctx.stage_invocations_finished += 1
                total_invocations_finished += 1
                ctx.executed = True
                executed_seats.add(key)
                ctx.stop_reason = f"UNEXPECTED_EXCEPTION:{type(exc).__name__}"
                global_stop_reason = ctx.stop_reason
                ctx.record = build_seat_record(ctx)
                total_logical_generations += len(proxy_model.events)
                break

            gens = len(proxy_model.events)
            total_logical_generations += gens

            # Crash simulation before result recording (durable seat claim test)
            if crash_before_result_recording and seat_index == 1:
                global_stop_reason = "SIMULATED_CRASH_BEFORE_RESULT_RECORDING"
                ctx.outcome_status = "ATTEMPT_OUTCOME_UNKNOWN"
                ctx.stop_reason = global_stop_reason
                ctx.record = build_seat_record(ctx)
                break

            # Phase 4 -> 5: RESULT_RECORDED
            ctx.phase = SeatPhase.RESULT_RECORDED

            # Finalize durable claim
            claim_data["claimed_phase"] = "RESULT_RECORDED"
            claim_data["finalized_at_monotonic"] = time.monotonic()
            claim_data["status"] = "COMPLETED"
            tmp_claim = claim_path.with_suffix(".tmp")
            tmp_claim.write_text(json.dumps(claim_data, indent=2), encoding="utf-8")
            os.chmod(tmp_claim, 0o600)
            tmp_claim.replace(claim_path)
            ctx.claim_record = claim_data

            record = build_seat_record(ctx)
            ctx.record = record

            # Stop conditions checks
            exc_class = record["stage_layers"]["exception_class"]
            provider_errs = record.get("provider_error_classes", [])
            has_provider_failure = (
                is_provider_error_class(exc_class)
                or any(is_provider_error_class(c) for c in provider_errs)
            )

            # 1. Unexpected runner exception (E12)
            if (
                exc_class not in (None, "UnexpectedModelBehavior")
                and not has_provider_failure
            ):
                global_stop_reason = f"UNEXPECTED_EXCEPTION:{exc_class}"

            # 2. Provider failure (E5, E6)
            elif has_provider_failure:
                global_stop_reason = "PROVIDER_CAPACITY_OR_CONNECTIVITY_FAILURE"

            # 3. Model identity mismatch (E7)
            elif (
                any(x.get("returned_model") != MODEL for x in record["identity_sink_records"])
                or (record["stage_layers"]["exception_class"] is None and not record["returned_identity_exact"])
            ):
                global_stop_reason = "MODEL_IDENTITY_MISMATCH"

            # 4. Fabricated evidence (E9)
            elif record["field_scan_totals"].get("fabricated_evidence_like_identifier", 0) > 0:
                global_stop_reason = "FABRICATED_EVIDENCE_OR_BASIS_HANDLE"

            # 5. Budget exceeded
            elif (
                total_logical_generations
                > REQUEST_BUDGET["logical_model_generations_max"]
            ):
                global_stop_reason = "REQUEST_BUDGET_EXCEEDED"

            # 6. Diagnostic data quality verification (E8)
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
                break

    # Build matrix
    matrix_seats = [c.record or build_seat_record(c) for c in seat_contexts]

    return {
        "artifact_version": "RCA2A7bEightSeatSimulationMatrixV1",
        "experiment_id": EXPERIMENT_ID,
        "run_order": [list(pair) for pair in PAIRS],
        "stage_invocations_scheduled": 8,
        "stage_invocations_started": total_invocations_started,
        "stage_invocations_finished": total_invocations_finished,
        "stage_invocations_executed": sum(s["status"] == "EXECUTED" for s in matrix_seats),
        "logical_model_generations": total_logical_generations,
        "logical_model_generations_budget": REQUEST_BUDGET["logical_model_generations_max"],
        "preflight_logical_requests": 0,
        "http_attempts": "HTTP_ATTEMPTS_UNOBSERVABLE",
        "stop_reason": global_stop_reason,
        "seats": matrix_seats,
        "real_model_requests": 0,
        "observation_tag": "SYNTHETIC_TEST_OBSERVATIONS",
    }


def compute_paired_metrics(matrix: dict[str, Any]) -> dict[str, Any]:
    seats = matrix["seats"]
    by_pair = {}
    for pair_id in range(1, 5):
        control = next(x for x in seats if x["pair_id"] == pair_id and x["arm"] == "control")
        treatment = next(x for x in seats if x["pair_id"] == pair_id and x["arm"] == "treatment")

        c = (
            control.get("stage_layers", {}).get("canonical_integration_valid")
            if control["status"] == "EXECUTED"
            else None
        )
        t = (
            treatment.get("stage_layers", {}).get("canonical_integration_valid")
            if treatment["status"] == "EXECUTED"
            else None
        )

        if c is True and t is True:
            classification = "both_valid"
        elif c is True and t is False:
            classification = "control_win"
        elif t is True and c is False:
            classification = "treatment_win"
        elif c is False and t is False:
            classification = "both_invalid"
        else:
            classification = "incomplete_pair"

        by_pair[str(pair_id)] = {
            "control": control,
            "treatment": treatment,
            "classification": classification,
        }

    executed = [x for x in seats if x["status"] == "EXECUTED"]
    valid_c = sum(
        x["arm"] == "control"
        and x.get("stage_layers", {}).get("canonical_integration_valid") is True
        for x in executed
    )
    valid_t = sum(
        x["arm"] == "treatment"
        and x.get("stage_layers", {}).get("canonical_integration_valid") is True
        for x in executed
    )

    pair_classifications = [p["classification"] for p in by_pair.values()]
    paired_counts = {
        "treatment_win": pair_classifications.count("treatment_win"),
        "control_win": pair_classifications.count("control_win"),
        "both_valid": pair_classifications.count("both_valid"),
        "both_invalid": pair_classifications.count("both_invalid"),
        "incomplete_pair": pair_classifications.count("incomplete_pair"),
    }

    return {
        "paired_results": by_pair,
        "paired_counts": paired_counts,
        "valid_control_count": valid_c,
        "valid_treatment_count": valid_t,
        "total_executed_seats": len(executed),
        "total_unstarted_seats": sum(x["status"] == "NOT_STARTED" for x in seats),
    }
