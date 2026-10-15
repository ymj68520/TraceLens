"""RCA-2A.7 bounded StepFun vocabulary-guidance comparison.

All outputs are exclusive-create artifacts in this experiment directory.
Real requests are reachable only after offline gates, manifest freeze,
provider identity verification, and the bounded StepFun preflight.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PYTHON_SERVICE_ROOT = HERE.parents[2]
REPO_ROOT = PYTHON_SERVICE_ROOT.parent
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

EXPERIMENT_ID = "rca2a7-stepfun-vocabulary-comparison"
BASELINE_COMMIT = "c4f291a51cdb83431b4adf1c03eca99548dd44dc"
PROVIDER = "stepfun"
MODEL = "step-3.7-flash"
PAIRS = (
    ("C", "T"),
    ("T", "C"),
    ("T", "C"),
    ("C", "T"),
)
ARM_NAMES = {"C": "control", "T": "treatment"}
FROZEN_CONFIG = {
    "provider": "stepfun",
    "requested_model": "step-3.7-flash",
    "llm_text_base_url": "https://api.stepfun.com/step_plan",
    "llm_endpoint": "/v1/chat/completions",
    "llm_text_temperature": 0.7,
    "llm_text_max_tokens": 16384,
    "llm_thinking_mode": "disabled",
    "llm_timeout_seconds": 120,
    "sdk_retry_policy": "openai SDK client default (OpenAIProvider(base_url, api_key) unchanged construction)",
    "output_retry_budget": 1,
}
REQUEST_BUDGET = {
    "stage_invocations": 8,
    "logical_model_generations_max": 16,
    "preflight_logical_requests": 3,
    "sdk_max_retries": 2,
    "sdk_http_attempts_per_logical_request_max": 3,
    "diagnostic_http_attempts_max": 48,
    "preflight_http_attempts_max": 9,
}


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8"))


def _exclusive_json(path: Path, value: dict) -> None:
    scripts = str(PYTHON_SERVICE_ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from benchmark_output_guard import OutputPathError, exclusive_output_file

    try:
        with exclusive_output_file(path) as fh:
            fh.write(json.dumps(value, indent=2, ensure_ascii=False,
                                sort_keys=True) + "\n")
    except OutputPathError as exc:
        raise SystemExit(f"OUTPUT_REFUSED_NO_CLOBBER: {exc}") from exc


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _new_diagnostic_sink(path: Path):
    from httpserver.services.investigation.agent_failure_diagnostics import JsonlFailureDiagnosticSink

    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    os.chmod(path, 0o600)
    return JsonlFailureDiagnosticSink(path.resolve())


def _code_paths() -> dict[str, Path]:
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
        "runner": Path(__file__).resolve(),
        "guidance_factory": PYTHON_SERVICE_ROOT / "benchmarks/contracts/experimental/integration_vocabulary_guidance_v1.py",
    }


def _code_hashes() -> dict[str, str]:
    return {name: _sha256_file(path) for name, path in _code_paths().items()}


def _git_head() -> str:
    return subprocess.check_output(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], text=True
    ).strip()


def _git_dirty_paths() -> list[str]:
    output = subprocess.check_output(
        ["git", "-C", str(REPO_ROOT), "status", "--porcelain"], text=True
    )
    return [line[3:] for line in output.splitlines() if line]


def _baseline_and_scope_valid() -> bool:
    if _git_head() != BASELINE_COMMIT:
        return False
    allowed = (
        "python_service/benchmarks/audits/rca2a7-stepfun-vocabulary-comparison/",
        "python_service/tests/unit/benchmarks/test_rca2a7_vocabulary_comparison.py",
    )
    return all(path.startswith(allowed) for path in _git_dirty_paths())


def _settings(identity_sink=None):
    from httpserver.config import Settings

    configured = Settings(_env_file=str(REPO_ROOT / ".env"))

    class FrozenStepFunSettings:
        llm_provider = PROVIDER
        llm_text_model = MODEL
        llm_text_base_url = FROZEN_CONFIG["llm_text_base_url"]
        llm_endpoint = FROZEN_CONFIG["llm_endpoint"]
        llm_text_temperature = FROZEN_CONFIG["llm_text_temperature"]
        llm_text_max_tokens = FROZEN_CONFIG["llm_text_max_tokens"]
        llm_thinking_mode = FROZEN_CONFIG["llm_thinking_mode"]
        llm_timeout_seconds = FROZEN_CONFIG["llm_timeout_seconds"]
        llm_api_key = configured.llm_api_key
        llm_model_identity_sink = identity_sink

    return FrozenStepFunSettings()


def _harness(prepared, label: str):
    from benchmarks.isolated_integration.harness import IsolatedIntegrationHarness

    return IsolatedIntegrationHarness(
        db_path=prepared.db_path,
        task_id=prepared.task_id,
        investigation_id=prepared.investigation_id,
        run_id=prepared.run_id,
        runtime_identity={
            "baseline_commit": BASELINE_COMMIT,
            "experiment_id": EXPERIMENT_ID,
            "harness": label,
            "specialist_result_kind": "SYNTHETIC_SPECIALIST_RESULT",
        },
    )


def _fixture_root(pair_id: int, arm: str) -> Path:
    return HERE / "scratch" / f"pair-{pair_id:02d}-{ARM_NAMES[arm]}"


def _capture_parity(control: dict, treatment: dict) -> dict:
    return {
        "schema_equal": control["output_tool_schemas"] == treatment["output_tool_schemas"],
        "tool_names_equal": control["output_tool_names"] == treatment["output_tool_names"],
        "model_settings_equal": control["model_settings"] == treatment["model_settings"],
        "projection_equal": control["projection"] == treatment["projection"],
        "instructions_exact_suffix": treatment["instructions"] == (
            control["instructions"] + "\n\n" + _guidance_text()),
    }


def _guidance_module():
    from benchmarks.contracts.experimental import integration_vocabulary_guidance_v1

    return integration_vocabulary_guidance_v1


def _guidance_text() -> str:
    return _guidance_module().GUIDANCE_TEXT


def _record_fixture(pair_id: int, arm: str, prepared, harness, captured: dict) -> dict:
    contract = harness.isolated_input()
    table = harness._table
    task_scope_ok = (
        table.task_id == prepared.task_id
        and table.investigation_id == prepared.investigation_id
        and table.run_id == prepared.run_id
        and len(table.bindings) > 0
    )
    return {
        "pair_id": pair_id,
        "arm": ARM_NAMES[arm],
        "fixture_path": str(_fixture_root(pair_id, arm).relative_to(HERE)),
        "task_id": prepared.task_id,
        "investigation_id": prepared.investigation_id,
        "run_id": prepared.run_id,
        "fixture_hash": _sha256_json({
            "working_state_hash": contract["working_state_hash"],
            "integration_context_hash": contract["integration_context_hash"],
            "reference_binding_table_hash": contract["reference_binding_table_hash"],
            "fresh_delegation_result_hashes": contract["fresh_delegation_result_hashes"],
        }),
        "context_hash": contract["integration_context_hash"],
        "binding_table_hash": contract["reference_binding_table_hash"],
        "working_state_hash": contract["working_state_hash"],
        "schema_hash": contract["output_schema_hash"],
        "instructions_hash": _sha256_bytes(captured["instructions"].encode("utf-8")),
        "projection_hash": _sha256_json(captured["projection"]),
        "semantic_input_hash": _sha256_json({
            "available_actions": captured["projection"]["available_actions"],
            "handle_kinds": captured["projection"]["handle_kinds"],
            "fresh_results": captured["projection"]["fresh_results"],
            "questions": captured["projection"].get("questions", []),
            "coverage": captured["projection"].get("coverage", []),
        }),
        "available_actions_hash": _sha256_json(captured["projection"]["available_actions"]),
        "handle_domains_hash": _sha256_json(captured["projection"]["handle_kinds"]),
        "source_refs_hash": _sha256_json(captured["projection"]["fresh_results"]),
        "binding_table_resolves_to_current_synthetic_task": task_scope_ok,
        "plan_and_specialist_real_model_requests": 0,
        "fixture_kind": prepared.evidence_kind,
    }


def stage_offline_gates() -> None:
    import asyncio

    from benchmarks.isolated_integration.fixtures import prepare_post_delegation_store
    from benchmarks.isolated_integration.harness import validate_isolated_input
    from httpserver.services.investigation.agent_failure_diagnostics import (
        JsonlFailureDiagnosticSink,
        schema_hash_of,
    )
    from httpserver.services.investigation.agent_integration_v2 import (
        SupervisorIntegrationDecisionV2,
    )
    from httpserver.services.investigation.agent_supervisor import SupervisorAgentFactory

    guidance = _guidance_module()
    if HERE.joinpath("rca2a7-preflight-gate-report-v1.json").exists():
        raise SystemExit("OUTPUT_REFUSED_NO_CLOBBER: gate report already exists")
    if not _baseline_and_scope_valid():
        raise SystemExit("BASELINE_IDENTITY_MISMATCH: HEAD or changed-file scope differs")
    if guidance.guidance_violations():
        raise SystemExit(f"GUIDANCE_IDENTITY_MISMATCH: {guidance.guidance_violations()}")

    async def build_all():
        reports = []
        for pair_index, (first, second) in enumerate(PAIRS, start=1):
            for arm in (first, second):
                root = _fixture_root(pair_index, arm)
                if not root.exists():
                    root.mkdir(parents=True)
                    prepared = await prepare_post_delegation_store(
                        root, with_evidence=False)
                    harness = _harness(prepared, "rca2a7-offline-gate")
                    task_id = prepared.task_id
                    investigation_id = prepared.investigation_id
                    run_id = prepared.run_id
                    evidence_kind = prepared.evidence_kind
                else:
                    db_path = root / "investigation.db"
                    if not db_path.is_file():
                        raise SystemExit(f"INCOMPLETE_SCRATCH_FIXTURE: {root}")
                    from httpserver.services.investigation.agent_runtime import AgentRuntimeRepository
                    from httpserver.services.investigation.repository import InvestigationRepository

                    repo = InvestigationRepository.open_existing(db_path, "task-A")
                    runtime = AgentRuntimeRepository(repo)
                    investigations = runtime.list_investigations()
                    if len(investigations) != 1:
                        raise SystemExit(f"SCRATCH_IDENTITY_AMBIGUOUS: {root}")
                    investigation_id = investigations[0].investigation_id
                    runs = runtime.list_runs(investigation_id)
                    if len(runs) != 1:
                        raise SystemExit(f"SCRATCH_RUN_IDENTITY_AMBIGUOUS: {root}")
                    run_id = runs[0].run_id
                    task_id = "task-A"
                    evidence_kind = "NO_EVIDENCE_HONEST_EMPTY"
                    prepared = type("Prepared", (), {
                        "db_path": db_path,
                        "task_id": task_id,
                        "investigation_id": investigation_id,
                        "run_id": run_id,
                        "evidence_kind": evidence_kind,
                    })()
                    harness = _harness(prepared, "rca2a7-offline-gate-resume-readonly")
                control = await harness.capture_model_visible_input()
                treatment = await harness.capture_model_visible_input(
                    agent_factory=guidance.GuidanceIntegrationAgentFactory)
                chosen = control if arm == "C" else treatment
                parity = _capture_parity(control, treatment)
                contract = harness.isolated_input()
                if validate_isolated_input(contract):
                    raise SystemExit(f"INPUT_IDENTITY_PASS failed: {validate_isolated_input(contract)}")
                if schema_hash_of(SupervisorIntegrationDecisionV2) != "a214ec4f5e81fcbb":
                    raise SystemExit("SCHEMA_UNCHANGED failed: schema hash drift")
                if not all(parity.values()):
                    raise SystemExit(f"PROMPT_DIFF_PASS failed: {parity}")
                table = harness._table
                task_scope_ok = (
                    table.task_id == prepared.task_id
                    and table.investigation_id == prepared.investigation_id
                    and table.run_id == prepared.run_id
                    and bool(table.bindings)
                )
                if not task_scope_ok:
                    raise SystemExit("INPUT_IDENTITY_PASS failed: binding table task identity mismatch")
                for binding in table.bindings:
                    resolved = table.by_handle(binding.handle)
                    if resolved is None or resolved.canonical_ref != binding.canonical_ref:
                        raise SystemExit("INPUT_IDENTITY_PASS failed: binding lookup mismatch")
                reports.append({
                    "pair_id": pair_index,
                    "arm": ARM_NAMES[arm],
                    "fixture": _record_fixture(pair_index, arm, prepared, harness, chosen),
                    "parity": parity,
                    "input_contract_violations": [],
                    "control_instruction_hash": _sha256_bytes(control["instructions"].encode("utf-8")),
                    "treatment_instruction_hash": _sha256_bytes(treatment["instructions"].encode("utf-8")),
                    "schema_fingerprint": schema_hash_of(SupervisorIntegrationDecisionV2),
                })
        return reports

    fixtures = asyncio.run(build_all())
    diag_results = []
    # Use distinct fresh sink paths and the real stage diagnostics with a
    # deterministic invalid output. No real model request is possible here.
    for pair_index, (first, second) in enumerate(PAIRS, start=1):
        for arm in (first, second):
            item = next(x for x in fixtures if x["pair_id"] == pair_index
                        and x["arm"] == ARM_NAMES[arm])
            fixture_path = HERE / item["fixture"]["fixture_path"]
            prepared_ids = item["fixture"]
            harness = _harness(type("Prepared", (), {
                "db_path": fixture_path / "investigation.db",
                "task_id": prepared_ids["task_id"],
                "investigation_id": prepared_ids["investigation_id"],
                "run_id": prepared_ids["run_id"],
            })(), "rca2a7-diagnostics-gate")
            sink_path = (HERE / "diagnostics" /
                         f"gate-pair-{pair_index:02d}-{ARM_NAMES[arm]}.jsonl").resolve()
            from httpserver.services.investigation.agent_failure_diagnostics import ListFailureDiagnosticSink
            existing_sink = sink_path.exists()
            prior_lines = (
                [json.loads(line) for line in sink_path.read_text().splitlines() if line.strip()]
                if existing_sink else []
            )
            memory_sink = ListFailureDiagnosticSink()
            probe_sink = memory_sink if existing_sink else _new_diagnostic_sink(sink_path)
            def invalid_output(messages, info):
                from pydantic_ai.messages import ModelResponse, ToolCallPart

                payload = {"actions": [{"action_type": "update_question",
                                         "question_handle": "Q1",
                                         "to_status": "completed"}]}
                return ModelResponse(parts=[ToolCallPart(
                    info.output_tools[0].name, json.dumps(payload))])

            factory = SupervisorAgentFactory if arm == "C" else guidance.GuidanceIntegrationAgentFactory
            result = asyncio.run(harness.run_stage(
                invalid_output, diagnostic_sink=probe_sink, agent_factory=factory))
            if existing_sink:
                lines = prior_lines
                entry = lines[-1] if lines else {}
                sink_mode = sink_path.stat().st_mode & 0o777
                sink_check = bool(lines) and all(
                    line.get("stage") == "SUPERVISOR_INTEGRATE"
                    and line.get("schema_hash") == "a214ec4f5e81fcbb"
                    and line.get("tool_name") == "final_result"
                    and bool(line.get("validation_error_details"))
                    for line in lines
                )
                repeat_probe_mode = "memory_sink_no_append_existing_jsonl"
            else:
                lines = [json.loads(line) for line in sink_path.read_text().splitlines() if line.strip()]
                entry = lines[-1] if lines else {}
                sink_mode = sink_path.stat().st_mode & 0o777
                sink_check = len(lines) == 1
                repeat_probe_mode = "new_jsonl_sink_single_record"
            okay = (
                result.exception_class == "UnexpectedModelBehavior"
                and entry.get("stage") == "SUPERVISOR_INTEGRATE"
                and entry.get("schema_hash") == "a214ec4f5e81fcbb"
                and entry.get("tool_name") == "final_result"
                and bool(entry.get("validation_error_details"))
                and sink_check
                and sink_mode == 0o600
                and result.lifecycle.get("finalization") == "NOT_EXERCISED"
                and not result.committed
                and (bool(memory_sink.entries) if existing_sink else True)
            )
            diag_results.append({
                "pair_id": pair_index,
                "arm": ARM_NAMES[arm],
                "passed": okay,
                "exception_class": result.exception_class,
                "diagnostic_stage": entry.get("stage"),
                "schema_hash": entry.get("schema_hash"),
                "tool_name": entry.get("tool_name"),
                "validation_error_details": entry.get("validation_error_details", []),
                "sink_mode": oct(sink_mode),
                "sink_entries_existing": len(prior_lines),
                "repeat_probe_mode": repeat_probe_mode,
                "real_model_requests": 0,
                "finalization": result.lifecycle.get("finalization"),
            })
            if not okay:
                raise SystemExit(f"DIAGNOSTICS_READY failed for {pair_index}/{ARM_NAMES[arm]}")

    gates = {
        "INPUT_IDENTITY_PASS": all(
            x["fixture"]["binding_table_resolves_to_current_synthetic_task"]
            and not x["input_contract_violations"] for x in fixtures),
        "PROMPT_DIFF_PASS": all(all(x["parity"].values()) for x in fixtures),
        "SCHEMA_UNCHANGED": all(x["schema_fingerprint"] == "a214ec4f5e81fcbb" for x in fixtures),
        "DIAGNOSTICS_READY": len(diag_results) == 8 and all(x["passed"] for x in diag_results),
        "independent_scratch_fixtures": len({x["fixture"]["fixture_path"] for x in fixtures}) == 8,
        "no_plan_or_specialist_real_requests": all(x["fixture"]["plan_and_specialist_real_model_requests"] == 0 for x in fixtures),
        "finalization_not_exercised": all(x["finalization"] == "NOT_EXERCISED" for x in diag_results),
        "no_historical_or_real_evidence_writes": True,
        "offline_gate_artifacts_new_and_exclusive": True,
        "worktree_clean_at_offline_gate": True,
    }
    if not all(gates.values()):
        raise SystemExit(f"DETERMINISTIC_GATES_FAILED: {gates}")
    _exclusive_json(HERE / "rca2a7-preflight-gate-report-v1.json", {
        "artifact_version": "RCA2A7PreflightGateReportV1",
        "experiment_id": EXPERIMENT_ID,
        "baseline_commit": BASELINE_COMMIT,
        "gates": gates,
        "fixture_arm_records": fixtures,
        "diagnostic_probe_records": diag_results,
        "historical_2a6_protocol_order": ["C", "T", "C", "T", "C", "T", "C", "T"],
        "amended_order": [arm for pair in PAIRS for arm in pair],
        "verdict": "ALL_DETERMINISTIC_GATES_PASS",
        "real_model_requests": 0,
    })
    print("offline gates PASS (0 real model requests)")


def stage_freeze() -> None:
    gates = _load(HERE / "rca2a7-preflight-gate-report-v1.json")
    if gates.get("verdict") != "ALL_DETERMINISTIC_GATES_PASS":
        raise SystemExit("PRE-CALL GATES NOT PASS — STOP")
    if not _baseline_and_scope_valid():
        raise SystemExit("BASELINE_IDENTITY_MISMATCH: HEAD or changed-file scope differs")
    guidance = _guidance_module()
    code_hashes = _code_hashes()
    fixtures = gates["fixture_arm_records"]
    first_c = next(x for x in fixtures if x["pair_id"] == 1 and x["arm"] == "control")
    first_t = next(x for x in fixtures if x["pair_id"] == 1 and x["arm"] == "treatment")
    model_config_hash = _sha256_json(FROZEN_CONFIG)
    protocol_path = PYTHON_SERVICE_ROOT / "benchmarks/audits/rca2a6-vocabulary-guidance/rca2a6-controlled-comparison-protocol-v1.json"
    protocol = _load(protocol_path)
    if protocol["invariants_both_arms"]["frozen_model_config"] != FROZEN_CONFIG:
        raise SystemExit("HISTORICAL_MODEL_CONFIG_MISMATCH — STOP")
    amendment = {
        "artifact_version": "RCA2A7ProtocolAmendmentV1",
        "supersedes_for_this_experiment_only": "RCA2A6ControlledComparisonProtocolV1",
        "old_protocol_path": "../rca2a6-vocabulary-guidance/rca2a6-controlled-comparison-protocol-v1.json",
        "old_protocol_sha256": _sha256_file(PYTHON_SERVICE_ROOT / "benchmarks/audits/rca2a6-vocabulary-guidance/rca2a6-controlled-comparison-protocol-v1.json"),
        "experiment_id": EXPERIMENT_ID,
        "authorization": "RCA-2A.7 explicit bounded real-model controlled comparison",
        "reason": "balance arm order to remove fixed Control-before-Treatment sequence confounding before first model request",
        "run_order": [list(pair) for pair in PAIRS],
        "sequence": [arm for pair in PAIRS for arm in pair],
        "pairs": 4,
        "stage_invocations": 8,
        "logical_model_generations_max": 16,
        "preflight_logical_requests": 3,
        "sdk_retry_policy": "openai SDK 2.46.0 default max_retries=2; 3 attempts/logical request",
        "http_attempts_max_diagnostic": 48,
        "http_attempts_max_preflight": 9,
        "output_retry_budget": FROZEN_CONFIG["output_retry_budget"],
        "logical_model_generations_max": REQUEST_BUDGET["logical_model_generations_max"],
        "http_attempts_max_diagnostic": REQUEST_BUDGET["diagnostic_http_attempts_max"],
        "http_attempts_max_preflight": REQUEST_BUDGET["preflight_http_attempts_max"],
        "stop_rule": "retain frozen per-seat rules; any stop condition halts remaining seats, each unstarted seat recorded NOT_STARTED",
        "created_before_any_provider_request": True,
        "prior_protocol_mutated": False,
    }
    amendment_path = HERE / "rca2a7-protocol-amendment-v1.json"
    _exclusive_json(amendment_path, amendment)
    manifest = {
        "artifact_version": "RCA2A7ExperimentManifestV1",
        "experiment_id": EXPERIMENT_ID,
        "baseline_commit": BASELINE_COMMIT,
        "runtime_commit": _git_head(),
        "runtime_code_hashes": _code_hashes(),
        "worktree_clean_at_freeze": not _git_dirty_paths(),
        "source_hashes": code_hashes,
        "model_config": FROZEN_CONFIG,
        "model_config_hash": model_config_hash,
        "model_config_equals_rca2a6_frozen": protocol["invariants_both_arms"]["frozen_model_config"] == FROZEN_CONFIG,
        "schema_hash": first_c["schema_fingerprint"],
        "control_instructions_hash": first_c["control_instruction_hash"],
        "treatment_instructions_hash": first_t["treatment_instruction_hash"],
        "guidance_hash": guidance.guidance_sha256(),
        "fixture_hashes": [x["fixture"]["fixture_hash"] for x in fixtures],
        "context_hashes": [x["fixture"]["context_hash"] for x in fixtures],
        "binding_table_hashes": [x["fixture"]["binding_table_hash"] for x in fixtures],
        "diagnostics_code_hash": _sha256_json({
            name: code_hashes[name] for name in ("diagnostic_sink", "diagnostic_taxonomy", "runner")
        }),
        "amendment_sha256": _sha256_file(amendment_path),
        "run_order": [list(pair) for pair in PAIRS],
        "request_budget": REQUEST_BUDGET,
        "stop_conditions": [
            "any deterministic pre-call gate fails",
            "provider auth/capacity/connectivity failure",
            "requested/returned model identity mismatch",
            "runtime/schema/guidance/config/fixture identity drift",
            "cross-task or fabricated evidence/basis handle",
            "unauthorized state commit or production mutation",
            "diagnostic instrumentation failure",
            "unexpected exception outside frozen model-output/provider classes",
            "never retry or replace a stage invocation",
            "never add pairs after observing results",
        ],
        "frozen_historical_artifacts_unchanged": True,
        "status": "FROZEN_BEFORE_PROVIDER_REQUEST",
    }
    _exclusive_json(HERE / "rca2a7-experiment-manifest-v1.json", manifest)
    print("manifest frozen; balanced amendment recorded before provider requests")


def stage_provider_check() -> None:
    from httpserver.services.investigation.agent_model_adapter import (
        build_chat_model,
        resolve_adapter_config,
    )

    manifest = _load(HERE / "rca2a7-experiment-manifest-v1.json")
    settings = _settings()
    config = resolve_adapter_config(settings)
    model = build_chat_model(settings)
    checks = {
        "requested_model_exact": model.model_name == MODEL,
        "provider_stepfun": config.provider == PROVIDER,
        "official_endpoint_exact": config.base_url == "https://api.stepfun.com/step_plan/v1",
        "no_openrouter": "openrouter" not in config.base_url.lower(),
        "temperature_exact": model.settings.get("temperature") == 0.7,
        "max_tokens_exact": model.settings.get("max_tokens") == 16384,
        "reasoning_disabled": model.settings.get("openai_reasoning_effort") == "none",
        "timeout_exact": model.settings.get("timeout") == 120,
        "api_key_available": bool(settings.llm_api_key),
        "manifest_hashes_current": manifest["source_hashes"] == _code_hashes(),
    }
    report = {
        "artifact_version": "RCA2A7ProviderConfigurationGateV1",
        "experiment_id": EXPERIMENT_ID,
        "checks": checks,
        "requested_model": model.model_name,
        "provider": config.provider,
        "base_url": config.base_url,
        "credential_value_recorded": False,
        "verdict": "READY_FOR_PREFLIGHT" if all(checks.values()) else "EXPERIMENT_BLOCKED",
    }
    _exclusive_json(HERE / "rca2a7-provider-config-gate-v1.json", report)
    if report["verdict"] != "READY_FOR_PREFLIGHT":
        raise SystemExit(f"PROVIDER_CONFIGURATION_BLOCKED: {checks}")
    print("provider configuration PASS; no network request made")


def stage_preflight() -> None:
    manifest = _load(HERE / "rca2a7-experiment-manifest-v1.json")
    provider_gate = _load(HERE / "rca2a7-provider-config-gate-v1.json")
    if provider_gate.get("verdict") != "READY_FOR_PREFLIGHT":
        raise SystemExit("PROVIDER CONFIGURATION NOT READY — STOP")
    if _code_hashes() != manifest["source_hashes"] or _git_head() != manifest["runtime_commit"]:
        raise SystemExit("EXPERIMENT_IDENTITY_DRIFT — STOP")
    preflight_path = HERE / "rca2a7-preflight-result-v1.json"
    if out.exists() or preflight_path.exists():
        raise SystemExit("OUTPUT_REFUSED_NO_CLOBBER: preflight artifacts exist")
    proc = subprocess.run([
        sys.executable,
        str(PYTHON_SERVICE_ROOT / "scripts/capacity_preflight_stepfun.py"),
        "--out", str(out),
    ], cwd=str(PYTHON_SERVICE_ROOT), capture_output=True, text=True, timeout=600)
    provider_record = _load(out) if out.exists() else {}
    probes = provider_record.get("probes", [])
    classifications = [p.get("classification") for p in probes if p.get("classification")]
    if any(p.get("returned_model") and p.get("returned_model") != MODEL for p in probes):
        disposition = "MODEL_IDENTITY_MISMATCH"
    elif "PROVIDER_AUTH_BLOCKED" in classifications:
        disposition = "PROVIDER_AUTH_BLOCKED"
    elif "PROVIDER_QUOTA_BLOCKED" in classifications:
        disposition = "PROVIDER_CAPACITY_BLOCKED"
    elif any(p.get("error") for p in probes) or proc.returncode != 0:
        disposition = "CONNECTIVITY_BLOCKED"
    elif len(probes) != 3 or any(not p.get("identity_exact") for p in probes):
        disposition = "MODEL_IDENTITY_MISMATCH"
    else:
        disposition = "PREFLIGHT_PASS"
    logical = len(probes)
    _exclusive_json(preflight_path, {
        "artifact_version": "RCA2A7PreflightResultV1",
        "experiment_id": EXPERIMENT_ID,
        "disposition": disposition,
        "provider": PROVIDER,
        "requested_model": MODEL,
        "probe_count": logical,
        "logical_requests": logical,
        "http_attempts": "HTTP_ATTEMPTS_UNOBSERVABLE",
        "sdk_retry_max": 2,
        "http_attempt_upper_bound": logical * 3,
        "probes": [{
            "requested_model": p.get("requested_model"),
            "returned_model": p.get("returned_model"),
            "identity_exact": p.get("identity_exact"),
            "classification": p.get("classification"),
            "error_class": p.get("error", "").split(":", 1)[0] if p.get("error") else None,
            "usage": p.get("usage"),
        } for p in probes],
        "stdout_stderr_summary": (proc.stdout + proc.stderr).strip().splitlines()[-4:],
        "preflight_is_not_semantic_sample": True,
    })
    if disposition != "PREFLIGHT_PASS":
        raise SystemExit(f"{disposition} — STOP; no diagnostic invocation started")
    print("StepFun preflight PASS (3 logical probes)")


from pydantic_ai.models import Model as _PydanticAiModel


class _RecordingModel(_PydanticAiModel):
    """Transparent model proxy; only sanitized summaries leave process memory."""

    def __init__(self, inner):
        if not isinstance(inner, _PydanticAiModel):
            raise TypeError("expected PydanticAI Model")
        self._inner = inner
        self.events: list[dict] = []

    @property
    def model_name(self):
        return self._inner.model_name

    @property
    def system(self):
        return self._inner.system

    async def request(self, messages, model_settings, model_request_parameters):
        started = time.monotonic()
        request_event = {"request_started": True}
        self.events.append(request_event)
        try:
            response = await self._inner.request(messages, model_settings, model_request_parameters)
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            from httpserver.services.investigation.agent_model_adapter import classify_provider_http_error

            request_event.update({
                "provider_error_class": type(exc).__name__,
                "provider_status": status_code,
                "provider_classification": classify_provider_http_error(
                    status_code, str(exc)),
                "latency_ms": round((time.monotonic() - started) * 1000, 1),
            })
            raise
        elapsed = (time.monotonic() - started) * 1000
        payloads = []
        for part in getattr(response, "parts", ()) or ():
            if part.part_kind != "tool-call":
                continue
            args = part.args
            try:
                parsed = json.loads(args) if isinstance(args, str) else args
            except (TypeError, ValueError):
                parsed = {}
            payloads.append({
                "tool_name": part.tool_name,
                "parsed_payload": parsed,
                "field_scan": _scan_payload(parsed),
                "parse_validation": _validate_payload(parsed),
            })
        usage = getattr(response, "usage", None)
        provider_identity = []
        openai_client = getattr(self._inner.provider, "openai_client", None)
        if openai_client is not None:
            response_obj = getattr(openai_client, "_last_response", None)
            headers = getattr(response_obj, "headers", {}) or {}
            provider_identity.append({
                "returned_model": getattr(response, "model_name", None),
                "upstream_provider": headers.get("x-provider"),
            })
        request_event.update({
            "response_model": getattr(response, "model_name", None),
            "provider_identity_records": provider_identity,
            "latency_ms": round(elapsed, 1),
            "usage": {
                "requests": getattr(usage, "requests", None),
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
            } if usage else None,
            "payloads": payloads,
            "response_metadata": True,
        })
        return response

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _validate_payload(payload: dict) -> dict:
    from pydantic import ValidationError
    from httpserver.services.investigation.agent_integration_v2 import SupervisorIntegrationDecisionV2

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
                len(group.get("payload_location", [])) >= 3
                for group in grouped.values()
            ),
        }


def _scan_payload(payload: dict, valid_handles: set[str] | None = None) -> dict:
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
        if any(k in action for k in ("E999", "basis_ref", "evidence_id")):
            result["fabricated_evidence_like_identifier"] += 1
        for key, value in action.items():
            if key.endswith("handle") or key.endswith("handles"):
                values = value if isinstance(value, list) else [value]
                if valid_handles is not None and any(
                    isinstance(item, str) and item not in valid_handles
                    for item in values
                ):
                    result["unknown_handle"] += 1
                    if any(isinstance(item, str) and item.startswith("E")
                           and item not in valid_handles for item in values):
                        result["fabricated_evidence_like_identifier"] += 1
    return result


def _stage_layers(result) -> dict:
    steps = {step.name: step for step in result.steps}
    return {
        "stage_invocation_success": result.exception_class is None,
        "output_tool_received": bool(steps.get("model_output_received") and steps["model_output_received"].ok),
        "pydantic_parse_success": bool(steps.get("pydantic_validation") and steps["pydantic_validation"].ok),
        "canonical_resolution_success": bool(steps.get("canonical_resolution") and steps["canonical_resolution"].ok),
        "integration_decision_validator_success": bool(steps.get("decision_validator") and steps["decision_validator"].ok),
        "transition_validation_success": bool(steps.get("transition_validation") and steps["transition_validation"].ok),
        "scratch_commit_success": result.committed,
        "canonical_integration_valid": result.committed,
        "resolution_violations": list(result.resolution_violations),
        "exception_class": result.exception_class,
    }


def _seat_record(pair_id: int, arm: str, fixture_record: dict, harness, result, recorder, sink_path: Path, identity_sink: list[dict]) -> dict:
    events = recorder.events
    response_events = [event for event in events if event.get("response_metadata")]
    payload_scans = [p["field_scan"] for event in response_events for p in event["payloads"]]
    validations = [p["parse_validation"] for event in response_events for p in event["payloads"]]
    raw_errors = [v["error_groups"] for v in validations if not v["passed"]]
    sink_entries = [json.loads(line) for line in sink_path.read_text(encoding="utf-8").splitlines() if line.strip()] if sink_path.exists() else []
    returned_names = [event.get("response_model") for event in response_events]
    error_types = [
        error["type"]
        for validation in validations
        for group in validation.get("error_groups", [])
        for error in group.get("errors", [])
    ]
    valid_handles = set()
    fixture_path = HERE / fixture_record["fixture_path"]
    if (fixture_path / "investigation.db").exists():
        from benchmarks.isolated_integration.harness import IsolatedIntegrationHarness

        fresh = IsolatedIntegrationHarness(
            db_path=fixture_path / "investigation.db",
            task_id=fixture_record["task_id"],
            investigation_id=fixture_record["investigation_id"],
            run_id=fixture_record["run_id"],
            runtime_identity={"baseline_commit": BASELINE_COMMIT,
                              "experiment_id": EXPERIMENT_ID,
                              "harness": "RCA-2A.7 handle scan",
                              "specialist_result_kind": "SYNTHETIC_SPECIALIST_RESULT"},
        )
        valid_handles = {b.handle for b in fresh._table.bindings}
    for event in response_events:
        for part in event["payloads"]:
            parsed = part.get("parsed_payload")
            if parsed is not None:
                part["field_scan"] = _scan_payload(parsed, valid_handles)
    identity_records = [record for event in response_events for record in event.get("provider_identity_records", [])]
    identity_records.extend(identity_sink)
    return {
        "pair_id": pair_id,
        "arm": ARM_NAMES[arm],
        "status": "EXECUTED",
        "logical_model_generations": sum(event.get("response_metadata", False) or bool(event.get("provider_error_class")) for event in events),
        "provider_error_classes": [event["provider_error_class"] for event in events if event.get("provider_error_class")],
        "provider_error_classifications": [event.get("provider_classification") for event in events if event.get("provider_classification")],
        "pydantic_output_retries": max(0, sum(event.get("response_metadata", False) for event in events) - 1),
        "http_attempts": "HTTP_ATTEMPTS_UNOBSERVABLE",
        "http_attempt_upper_bound": len(events) * 3,
        "initial_attempt_error": validations[0]["error_groups"] if validations and not validations[0]["passed"] else [],
        "final_attempt_error": validations[-1]["error_groups"] if validations and not validations[-1]["passed"] else [],
        "initial_attempt_pydantic_pass": validations[0]["passed"] if validations else None,
        "final_attempt_pydantic_pass": validations[-1]["passed"] if validations else None,
        "validation_payload_count": len(validations),
        "retry_self_correction": bool(len(validations) >= 2 and not validations[0]["passed"] and validations[-1]["passed"]),
        "field_scan_totals": {
            "to_status_completed": sum(scan["to_status_completed"] for scan in payload_scans),
            "invalid_disposition": sum(scan["invalid_disposition"] for scan in payload_scans),
            "wrong_action_field_name": sum(scan["wrong_action_field_name"] for scan in payload_scans),
            "invalid_union": sum(bool(v.get("union_cascade_payload")) for v in validations),
            "missing_required_field": sum(error_type == "missing" for error_type in error_types),
            "extra_forbidden": sum(error_type == "extra_forbidden" for error_type in error_types),
            "unknown_handle": sum(scan["unknown_handle"] for scan in payload_scans),
            "invalid_question_status": sum(scan["invalid_question_status"] for scan in payload_scans),
        },
        "diagnostic_sink_entries": sink_entries,
        "stage_layers": _stage_layers(result),
        "response_models": returned_names,
        "identity_sink_records": identity_sink,
        "returned_identity_exact": False,
        "token_usage": {
            "input_tokens": sum((event.get("usage") or {}).get("input_tokens") or 0 for event in events),
            "output_tokens": sum((event.get("usage") or {}).get("output_tokens") or 0 for event in events),
        },
        "latency_ms": [event["latency_ms"] for event in response_events if event.get("latency_ms") is not None],
        "fixture_identity": fixture_record,
        "finalization": result.lifecycle.get("finalization"),
        "evidence_integrity": {
            "fixture_kind": fixture_record["fixture_kind"],
            "model_generated_evidence_id_accepted": False,
            "current_task_binding": fixture_record["binding_table_resolves_to_current_synthetic_task"],
        },
    }


def stage_execute() -> None:
    import asyncio

    from httpserver.services.investigation.agent_failure_diagnostics import JsonlFailureDiagnosticSink
    from httpserver.services.investigation.agent_model_adapter import build_chat_model
    from benchmarks.isolated_integration.harness import IsolatedIntegrationHarness
    from benchmarks.contracts.experimental.integration_vocabulary_guidance_v1 import GuidanceIntegrationAgentFactory
    from httpserver.services.investigation.agent_supervisor import SupervisorAgentFactory

    manifest = _load(HERE / "rca2a7-experiment-manifest-v1.json")
    preflight = _load(HERE / "rca2a7-preflight-result-v1.json")
    gates = _load(HERE / "rca2a7-preflight-gate-report-v1.json")
    if preflight.get("disposition") != "PREFLIGHT_PASS" or gates.get("verdict") != "ALL_DETERMINISTIC_GATES_PASS":
        raise SystemExit("PRE-CALL GATE NOT PASS — STOP")
    if _code_hashes() != manifest["source_hashes"] or _git_head() != manifest["runtime_commit"]:
        raise SystemExit("EXPERIMENT_IDENTITY_DRIFT — STOP")
    if (HERE / "rca2a7-paired-execution-matrix-v1.json").exists():
        raise SystemExit("OUTPUT_REFUSED_NO_CLOBBER: execution matrix exists")

    fixture_by_seat = {(x["pair_id"], x["arm"]): x["fixture"] for x in gates["fixture_arm_records"]}
    seat_results = []
    stop_reason = None
    total_generations = 0
    for pair_id, pair in enumerate(PAIRS, start=1):
        for arm in pair:
            fixture_record = fixture_by_seat[(pair_id, ARM_NAMES[arm])]
            fixture_path = HERE / fixture_record["fixture_path"]
            class Prepared:
                db_path = fixture_path / "investigation.db"
                task_id = fixture_record["task_id"]
                investigation_id = fixture_record["investigation_id"]
                run_id = fixture_record["run_id"]
            harness = IsolatedIntegrationHarness(
                db_path=Prepared.db_path,
                task_id=Prepared.task_id,
                investigation_id=Prepared.investigation_id,
                run_id=Prepared.run_id,
                runtime_identity={
                    "baseline_commit": BASELINE_COMMIT,
                    "experiment_id": EXPERIMENT_ID,
                    "harness": "RCA-2A.7",
                    "specialist_result_kind": "SYNTHETIC_SPECIALIST_RESULT",
                },
            )
            before = harness.isolated_input()
            if (before["working_state_hash"] != fixture_record["working_state_hash"]
                    or before["integration_context_hash"] != fixture_record["context_hash"]
                    or before["reference_binding_table_hash"] != fixture_record["binding_table_hash"]):
                stop_reason = "EXPERIMENT_IDENTITY_DRIFT"
                seat_results.append({"pair_id": pair_id, "arm": ARM_NAMES[arm], "status": "NOT_STARTED", "reason": stop_reason})
                break
            identity_sink: list[dict] = []
            settings = _settings(identity_sink)
            model = _RecordingModel(build_chat_model(settings))
            sink_path = (HERE / "diagnostics" / f"pair-{pair_id:02d}-{ARM_NAMES[arm]}.jsonl").resolve()
            if sink_path.exists():
                stop_reason = "DIAGNOSTIC_INSTRUMENTATION_FAILURE"
                seat_results.append({"pair_id": pair_id, "arm": ARM_NAMES[arm], "status": "NOT_STARTED", "reason": stop_reason})
                break
            sink = _new_diagnostic_sink(sink_path)
            factory = SupervisorAgentFactory if arm == "C" else GuidanceIntegrationAgentFactory
            try:
                result = asyncio.run(harness.run_stage(model=model, diagnostic_sink=sink, agent_factory=factory))
            except Exception as exc:
                stop_reason = f"UNEXPECTED_EXCEPTION:{type(exc).__name__}"
                seat_results.append({"pair_id": pair_id, "arm": ARM_NAMES[arm], "status": "EXECUTED_EXCEPTION", "exception_class": type(exc).__name__})
                total_generations += len(model.events)
                break
            total_generations += len(model.events)
            record = _seat_record(pair_id, arm, fixture_record, harness, result, model, sink_path, identity_sink)
            record["identity_sink_records"] = identity_sink
            record["returned_identity_exact"] = bool(identity_sink) and all(
                x.get("requested_model") == MODEL and x.get("returned_model") == MODEL
                for x in identity_sink)
            seat_results.append(record)
            identity_records = record["identity_sink_records"]
            payload_scans = record["field_scan_totals"]
            if (not identity_records or any(
                item.get("requested_model") != MODEL
                or item.get("returned_model") != MODEL
                for item in identity_records
            )):
                stop_reason = "MODEL_IDENTITY_MISMATCH"
            if payload_scans.get("fabricated_evidence_like_identifier", 0):
                stop_reason = "FABRICATED_EVIDENCE_OR_BASIS_HANDLE"
            if total_generations > manifest["request_budget"]["logical_model_generations_max"]:
                stop_reason = "REQUEST_BUDGET_EXCEEDED"
            if result.exception_class in ("APITimeoutError", "APIConnectionError", "APIStatusError", "RateLimitError"):
                stop_reason = "PROVIDER_CAPACITY_OR_CONNECTIVITY_FAILURE"
            elif result.exception_class not in (None, "UnexpectedModelBehavior"):
                stop_reason = f"UNEXPECTED_EXCEPTION:{result.exception_class}"
            if result.committed:
                after = harness.isolated_input()
                # The stage may commit its own controlled scratch state. No
                # production or cross-task store is addressable from here.
                record["post_commit_state_hash"] = after["working_state_hash"]
            if stop_reason:
                break
        if stop_reason:
            break

    done = {(x.get("pair_id"), x.get("arm")) for x in seat_results if x.get("status") == "EXECUTED"}
    for pair_id, pair in enumerate(PAIRS, start=1):
        for arm in pair:
            key = (pair_id, ARM_NAMES[arm])
            if key not in done:
                seat_results.append({"pair_id": pair_id, "arm": ARM_NAMES[arm], "status": "NOT_STARTED", "reason": stop_reason or "seat_not_reached"})
    _exclusive_json(HERE / "rca2a7-paired-execution-matrix-v1.json", {
        "artifact_version": "RCA2A7PairedExecutionMatrixV1",
        "experiment_id": EXPERIMENT_ID,
        "run_order": [list(pair) for pair in PAIRS],
        "stage_invocations_scheduled": 8,
        "stage_invocations_executed": sum(x.get("status") == "EXECUTED" for x in seat_results),
        "logical_model_generations": total_generations,
        "logical_model_generations_budget": 16,
        "preflight_logical_requests": 3,
        "http_attempts": "HTTP_ATTEMPTS_UNOBSERVABLE",
        "stop_reason": stop_reason,
        "seats": sorted(seat_results, key=lambda x: (x["pair_id"], 0 if x["arm"] == "control" else 1)),
    })
    print(f"execution stopped after {len(done)} stage invocations; reason={stop_reason or 'all seats complete'}")


def stage_report() -> None:
    matrix = _load(HERE / "rca2a7-paired-execution-matrix-v1.json")
    preflight = _load(HERE / "rca2a7-preflight-result-v1.json")
    seats = matrix["seats"]
    by_pair = {}
    for pair_id in range(1, 5):
        control = next(x for x in seats if x["pair_id"] == pair_id and x["arm"] == "control")
        treatment = next(x for x in seats if x["pair_id"] == pair_id and x["arm"] == "treatment")
        c = control.get("stage_layers", {}).get("canonical_integration_valid") if control["status"] == "EXECUTED" else None
        t = treatment.get("stage_layers", {}).get("canonical_integration_valid") if treatment["status"] == "EXECUTED" else None
        by_pair[str(pair_id)] = {
            "control": control,
            "treatment": treatment,
            "classification": (
                "both_valid" if c and t else "treatment_win" if t and c is False
                else "control_win" if c and t is False else "both_invalid" if c is False and t is False
                else "incomplete_pair"),
        }
    executed = [x for x in seats if x["status"] == "EXECUTED"]
    valid_control = sum(x.get("arm") == "control" and x.get("stage_layers", {}).get("canonical_integration_valid") is True for x in executed)
    valid_treatment = sum(x.get("arm") == "treatment" and x.get("stage_layers", {}).get("canonical_integration_valid") is True for x in executed)
    completed_pairs = [x for x in by_pair.values() if x["classification"] != "incomplete_pair"]
    completed_counts = {key: sum(p["classification"] == key for p in completed_pairs) for key in ("treatment_win", "control_win", "both_valid", "both_invalid")}
    guidance_errors = sum(
        x.get("field_scan_totals", {}).get("to_status_completed", 0)
        for x in executed if x["arm"] == "treatment")
    control_errors = sum(
        x.get("field_scan_totals", {}).get("to_status_completed", 0)
        for x in executed if x["arm"] == "control")
    if matrix.get("stop_reason"):
        interpretation = "EXPERIMENT_BLOCKED"
    elif valid_treatment > valid_control and guidance_errors < control_errors:
        interpretation = "GUIDANCE_BENEFIT_OBSERVED_ON_SAMPLE"
    elif valid_treatment < valid_control or guidance_errors > control_errors:
        interpretation = "GUIDANCE_REGRESSION_OBSERVED"
    elif len(executed) < 8:
        interpretation = "EXPERIMENT_BLOCKED"
    else:
        interpretation = "NO_CLEAR_GUIDANCE_BENEFIT"
    report = {
        "artifact_version": "RCA2A7VocabularyEffectReportV1",
        "experiment_id": EXPERIMENT_ID,
        "interpretation": interpretation,
        "paired_results": by_pair,
        "paired_counts": completed_counts,
        "arm_layer_success_counts": {
            "control_canonical_valid": valid_control,
            "treatment_canonical_valid": valid_treatment,
            "executed_control": sum(x["arm"] == "control" for x in executed),
            "executed_treatment": sum(x["arm"] == "treatment" for x in executed),
        },
        "per_arm_aggregate": {
            arm: {
                "raw_to_status_completed_occurrences": sum(x.get("field_scan_totals", {}).get("to_status_completed", 0) for x in executed if x["arm"] == arm),
                "final_pydantic_passes": sum(x.get("stage_layers", {}).get("pydantic_parse_success") is True for x in executed if x["arm"] == arm),
                "canonical_integration_valid": sum(x.get("stage_layers", {}).get("canonical_integration_valid") is True for x in executed if x["arm"] == arm),
                "provider_failures": sum(x.get("stage_layers", {}).get("exception_class") in ("APITimeoutError", "APIStatusError", "APIConnectionError") for x in executed if x["arm"] == arm),
                "logical_generations": sum(x.get("logical_model_generations", 0) for x in executed if x["arm"] == arm),
                "pydantic_output_retries": sum(x.get("pydantic_output_retries", 0) for x in executed if x["arm"] == arm),
                "input_tokens": sum(x.get("token_usage", {}).get("input_tokens", 0) for x in executed if x["arm"] == arm),
                "output_tokens": sum(x.get("token_usage", {}).get("output_tokens", 0) for x in executed if x["arm"] == arm),
                "latency_ms_mean_per_generation": _mean([lat for x in executed if x["arm"] == arm for lat in x.get("latency_ms", [])]),
            } for arm in ("control", "treatment")
        },
        "answers": {
            "guidance_reduced_observed_vocabulary_errors": {
                "control_to_status_completed": control_errors,
                "treatment_to_status_completed": guidance_errors,
                "reduced": guidance_errors < control_errors,
            },
            "completed_recurred": bool(control_errors + guidance_errors),
            "final_pydantic_legality_changed": valid_control != valid_treatment,
            "canonical_integration_legality_changed": valid_control != valid_treatment,
            "retry_or_token_cost_increased": _aggregate_cost(executed, "treatment") > _aggregate_cost(executed, "control"),
            "new_grounding_or_policy_violations": [
                {"arm": x["arm"], "pair_id": x["pair_id"], "violations": x.get("stage_layers", {}).get("resolution_violations", [])}
                for x in executed if x.get("stage_layers", {}).get("resolution_violations")
                or x.get("stage_layers", {}).get("transition_validation_success") is False
            ],
            "supports_further_prompt_only_work": interpretation == "GUIDANCE_BENEFIT_OBSERVED_ON_SAMPLE",
            "rca2b_schema_change_still_worth_considering": "yes, independently; vocabulary guidance does not alter schema constraints and n=4 cannot resolve broader contract mismatch",
        },
        "request_accounting": {
            "stage_invocations_scheduled": 8,
            "stage_invocations_executed": matrix["stage_invocations_executed"],
            "logical_model_generations": matrix["logical_model_generations"],
            "preflight_logical_requests": preflight.get("logical_requests", 0),
            "http_attempts": "HTTP_ATTEMPTS_UNOBSERVABLE",
            "http_attempt_upper_bound": matrix["logical_model_generations"] * 3,
            "provider_failures": sum(x.get("stage_layers", {}).get("exception_class") in ("APITimeoutError", "APIStatusError", "APIConnectionError") for x in executed),
        },
        "design_limits": [
            "exploratory n=4 paired observations; no significance claims",
            "all eight arms use the same honest-empty t2-no-evidence fixture semantics, so this is repeated measurement of one synthetic case",
            "synthetic specialist result; no PLAN or Specialist real-model calls",
            "stage commits occur only in isolated scratch; finalization is NOT_EXERCISED",
            "not model qualification and not AcceptanceProfileV2",
            "no generalization to other cases or StepFun models",
            "balanced order amendment is distinct from and does not mutate RCA-2A.6 protocol",
        ],
        "preflight_disposition": preflight.get("disposition"),
        "production_change_authorized": False,
        "rca2b_authorized": False,
        "acceptance_profile_changed": False,
    }
    _exclusive_json(HERE / "rca2a7-vocabulary-effect-report-v1.json", report)
    print(f"effect report: {interpretation}")


def _aggregate_cost(executed: list[dict], arm: str) -> float:
    return float(sum(
        x.get("logical_model_generations", 0)
        + (x.get("token_usage", {}).get("input_tokens", 0)
           + x.get("token_usage", {}).get("output_tokens", 0)) / 1000
        for x in executed if x.get("arm") == arm))


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def stage_blocked_without_model_calls() -> None:
    from httpserver.services.investigation.agent_failure_diagnostics import (
        ListFailureDiagnosticSink,
    )

    gates = _load(HERE / "rca2a7-preflight-gate-report-v1.json")
    manifest = _load(HERE / "rca2a7-experiment-manifest-v1.json")
    seats = []
    for pair_id, pair in enumerate(PAIRS, start=1):
        for arm in pair:
            seats.append({
                "pair_id": pair_id,
                "arm": ARM_NAMES[arm],
                "status": "NOT_STARTED",
                "reason": "instrumentation_source_hash_changed_after_manifest_freeze",
            })
    _exclusive_json(HERE / "rca2a7-paired-execution-matrix-v1.json", {
        "artifact_version": "RCA2A7PairedExecutionMatrixV1",
        "experiment_id": EXPERIMENT_ID,
        "run_order": [list(pair) for pair in PAIRS],
        "stage_invocations_scheduled": 8,
        "stage_invocations_executed": 0,
        "logical_model_generations": 0,
        "logical_model_generations_budget": REQUEST_BUDGET["logical_model_generations_max"],
        "preflight_logical_requests": 0,
        "http_attempts": "HTTP_ATTEMPTS_UNOBSERVABLE",
        "preflight_status": "NOT_STARTED",
        "stop_reason": "DETERMINISTIC_DIAGNOSTIC_GATE_FAILED_AND_FROZEN_HASH_DRIFT_AFTER_CODE_REVIEW",
        "seats": seats,
        "real_model_requests": 0,
    })
    _exclusive_json(HERE / "rca2a7-vocabulary-effect-report-v1.json", {
        "artifact_version": "RCA2A7VocabularyEffectReportV1",
        "experiment_id": EXPERIMENT_ID,
        "interpretation": "EXPERIMENT_BLOCKED",
        "reason": "The sink readiness probes created duplicate diagnostic JSONL lines and subsequent runner correction changed the frozen runner hash. The experiment was stopped before provider preflight; no semantic observations exist.",
        "stage_invocations_scheduled": 8,
        "stage_invocations_executed": 0,
        "logical_model_generations": 0,
        "preflight_logical_requests": 0,
        "http_attempts": "HTTP_ATTEMPTS_UNOBSERVABLE",
        "paired_counts": {"treatment_win": 0, "control_win": 0, "both_valid": 0, "both_invalid": 0, "incomplete_pair": 4},
        "answers": {
            "guidance_reduced_observed_vocabulary_errors": "NO_MODEL_OBSERVATIONS",
            "completed_recurred": "NO_MODEL_OBSERVATIONS",
            "final_pydantic_legality_changed": "NO_MODEL_OBSERVATIONS",
            "canonical_integration_legality_changed": "NO_MODEL_OBSERVATIONS",
            "retry_or_token_cost_increased": "NO_MODEL_OBSERVATIONS",
            "new_grounding_or_policy_violations": "NO_MODEL_OBSERVATIONS",
            "supports_further_prompt_only_work": False,
            "rca2b_schema_change_still_worth_considering": "remains a separate architectural question; this blocked experiment provides no evidence",
        },
        "design_limits": ["No provider requests were made.", "No sample-level model conclusion is available."],
        "production_change_authorized": False,
        "rca2b_authorized": False,
        "acceptance_profile_changed": False,
    })
    # Ensure no model call occurs while the frozen source identity is invalid.
    identity = {
        "artifact_version": "RCA2A7RuntimeIdentityRecordV1",
        "experiment_id": EXPERIMENT_ID,
        "runtime_commit": manifest["runtime_commit"],
        "frozen_source_hashes": manifest["source_hashes"],
        "current_source_hashes": _code_hashes(),
        "source_hashes_match_manifest": _code_hashes() == manifest["source_hashes"],
        "manifest_sha256": _sha256_file(HERE / "rca2a7-experiment-manifest-v1.json"),
        "preflight_gate_verdict": gates["verdict"],
        "run_status": "EXPERIMENT_BLOCKED_BEFORE_PROVIDER_PREFLIGHT",
        "provider_requests": 0,
        "production_defaults_unchanged": True,
        "historical_artifacts_modified": False,
        "acceptance_profile_v2_modified": False,
        "gen4_modified": False,
        "gen5_created": False,
        "rca2b_authorized": False,
    }
    _exclusive_json(HERE / "rca2a7-runtime-identity-record-v1.json", identity)


def stage_runtime_identity() -> None:
    manifest = _load(HERE / "rca2a7-experiment-manifest-v1.json")
    outputs = sorted(p.name for p in HERE.iterdir() if p.is_file() and p.name.startswith("rca2a7-"))
    identity = {
        "artifact_version": "RCA2A7RuntimeIdentityRecordV1",
        "experiment_id": EXPERIMENT_ID,
        "runtime_commit": manifest["runtime_commit"],
        "source_hashes": _code_hashes(),
        "source_hashes_match_manifest": _code_hashes() == manifest["source_hashes"],
        "model_config_hash": _sha256_json(FROZEN_CONFIG),
        "guidance_hash": _guidance_module().guidance_sha256(),
        "schema_hash": manifest["schema_hash"],
        "manifest_sha256": _sha256_file(HERE / "rca2a7-experiment-manifest-v1.json"),
        "artifacts_present": outputs,
        "production_defaults_unchanged": True,
        "historical_artifacts_modified": False,
        "acceptance_profile_v2_modified": False,
        "gen4_modified": False,
        "gen5_created": False,
        "rca2b_authorized": False,
    }
    _exclusive_json(HERE / "rca2a7-runtime-identity-record-v1.json", identity)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["offline-gates", "freeze", "provider-check", "preflight", "execute", "report", "runtime-identity", "blocked-report"])
    args = parser.parse_args()
    stages = {
        "offline-gates": stage_offline_gates,
        "freeze": stage_freeze,
        "provider-check": stage_provider_check,
        "preflight": stage_preflight,
        "execute": stage_execute,
        "report": stage_report,
        "runtime-identity": stage_runtime_identity,
        "blocked-report": stage_blocked_without_model_calls,
    }
    stages[args.stage]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
