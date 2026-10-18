"""RCA-2A.4 — bounded real-model isolated INTEGRATE diagnostic runner.

Stages (each gated, each idempotent-safe, artifacts via exclusive create):

  fixture-parity   build the FROZEN Fixture A store through Path A and
                   re-verify Path A/B input parity (RCA-2A.3 mechanism)
  manifest         freeze RCA2A4StepFunDiagnosticManifestV1 BEFORE any
                   real call (hashes code + config + fixture identity)
  sink-readiness   deterministic FunctionModel invalid-output -> RCA-1
                   sink, verified end to end (zero real model calls)
  provider-check   construct the REAL production StepFun adapter offline
                   and verify identity/config (no network)
  preflight        the ONE-time frozen capacity preflight (3 probes,
                   256 tokens) into the experiment directory
  execute          THE single real INTEGRATE stage invocation
                   (guarded by every prior gate; never re-executed)
  record           raw forensic evidence aggregation from the recording
                   model proxy

Storage boundary: everything lives under this experiment directory; the
fixture store is a controlled synthetic scratch task. No real
investigation.db is touched; no PLAN/Specialist model calls exist on
this path; finalization is NOT exercised.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PYTHON_SERVICE_ROOT = HERE.parents[2]
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

EXPERIMENT_ID = "rca2a4-stepfun-isolated-integration"
PARENT_PHASE = "RCA-2A.3"
BASELINE_COMMIT = "3ad0dcf531975a4133f0e75b9d93f118967e4842"
CASE_ID = "t2-no-evidence"

# historical frozen step-3.7-flash@stepfun candidate configuration
# (source: rca2a2-stepfun-diagnostic run_manifest.json — restored
# verbatim, never re-derived from current model defaults)
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



def _env_key() -> str:
    """Existing environment injection (.env LLM_API_KEY); presence only —
    the key value never enters any report or log."""
    for line in (PYTHON_SERVICE_ROOT.parent / ".env").read_text(
            encoding="utf-8").splitlines():
        if line.startswith("LLM_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _exclusive_json(path: Path, payload: dict) -> Path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT / "scripts"))
    from benchmark_output_guard import OutputPathError, exclusive_output_file

    try:
        with exclusive_output_file(path) as fh:
            fh.write(json.dumps(payload, indent=2, ensure_ascii=False,
                                sort_keys=True) + "\n")
    except OutputPathError as exc:
        raise SystemExit(f"OUTPUT REFUSED (no-clobber): {exc}")
    return path


def _write_overwrite(path: Path, payload: dict) -> Path:
    """For mutable state artifacts (gate progression), never artifacts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return path


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# stages
# ---------------------------------------------------------------------------


def stage_fixture_parity() -> None:
    import asyncio
    import tempfile

    from benchmarks.isolated_integration.fixtures import (
        prepare_post_delegation_store,
    )
    from benchmarks.isolated_integration.harness import (
        IsolatedIntegrationHarness,
        validate_isolated_input,
    )

    async def build():
        scratch = HERE / "scratch"
        fixture_dir = scratch / "fixture-a"
        if (fixture_dir / "investigation.db").exists():
            print("[fixture] store already frozen; reusing")
            return None
        prepared = await prepare_post_delegation_store(
            fixture_dir, with_evidence=False)
        harness = IsolatedIntegrationHarness(
            db_path=prepared.db_path,
            task_id=prepared.task_id,
            investigation_id=prepared.investigation_id,
            run_id=prepared.run_id,
            runtime_identity={
                "baseline_commit": BASELINE_COMMIT,
                "harness": "rca2a3-isolated-integration (as extended for "
                           "RCA-2A.4 real-model injection)",
                "specialist_result_kind": prepared.specialist_result_kind,
            },
        )
        captured_b = await harness.capture_model_visible_input()
        a, b = prepared.capture, captured_b
        fields = {
            "output_tool_schema": (a["output_tool_schemas"]
                                   == b["output_tool_schemas"]),
            "model_instructions": a["instructions"] == b["instructions"],
            "integration_context_projection": (a["projection"]
                                               == b["projection"]),
            "available_actions": (a["projection"]["available_actions"]
                                  == b["projection"]["available_actions"]),
            "typed_handle_domains": (a["projection"]["handle_kinds"]
                                     == b["projection"]["handle_kinds"]),
            "source_result_references": (
                a["projection"]["fresh_results"]
                == b["projection"]["fresh_results"]),
            "model_settings": a["model_settings"] == b["model_settings"],
            "output_tool_names": (a["output_tool_names"]
                                  == b["output_tool_names"]),
        }
        contract = harness.isolated_input()
        parity = {
            "artifact_version": "RCA2A4InputParityGateReportV1",
            "experiment_id": EXPERIMENT_ID,
            "case_id": CASE_ID,
            "fixture": "A_no_evidence (t2-no-evidence semantics)",
            "fields_compared": fields,
            "identity_note": ("same frozen store on both paths — even "
                              "identity fields equal; NO normalization "
                              "applied"),
            "contract_violations": validate_isolated_input(contract),
            "verdict": ("INTEGRATION_INPUT_PARITY_PASS"
                        if all(fields.values())
                        and not validate_isolated_input(contract)
                        else "INTEGRATION_INPUT_PARITY_FAIL"),
        }
        _exclusive_json(HERE / "rca2a4-input-parity-gate-report-v1.json",
                        parity)
        _write_overwrite(HERE / "scratch" / "fixture-identity.json", {
            "task_id": prepared.task_id,
            "investigation_id": prepared.investigation_id,
            "run_id": prepared.run_id,
            "working_state_revision": contract["working_state_revision"],
            "working_state_hash": contract["working_state_hash"],
            "integration_context_hash": contract["integration_context_hash"],
            "reference_binding_table_hash": contract[
                "reference_binding_table_hash"],
            "fresh_result_ids": contract["fresh_delegation_result_ids"],
            "fresh_result_hashes": contract["fresh_delegation_result_hashes"],
            "evidence_snapshot_refs": contract["evidence_snapshot_refs"],
            "model_visible_instructions_hash": contract[
                "model_visible_instructions_hash"],
            "output_schema_hash": contract["output_schema_hash"],
        })
        print(f"[fixture] parity: {parity['verdict']}")
        if parity["verdict"] != "INTEGRATION_INPUT_PARITY_PASS":
            raise SystemExit("INTEGRATION_INPUT_PARITY_BLOCKED — STOP")

    asyncio.run(build())


def stage_manifest() -> None:
    fixture = _load(HERE / "scratch" / "fixture-identity.json")
    parity = _load(HERE / "rca2a4-input-parity-gate-report-v1.json")
    if parity["verdict"] != "INTEGRATION_INPUT_PARITY_PASS":
        raise SystemExit("INTEGRATION_INPUT_PARITY_BLOCKED — STOP")
    manifest = {
        "artifact_version": "RCA2A4StepFunDiagnosticManifestV1",
        "experiment_id": EXPERIMENT_ID,
        "parent_phase": PARENT_PHASE,
        "baseline_commit": BASELINE_COMMIT,
        "frozen_before_any_real_call": True,
        "runtime_commit": BASELINE_COMMIT,
        "runtime_source_hash": _sha256_file(
            PYTHON_SERVICE_ROOT / "httpserver/services/investigation/"
            "agent_runtime.py"),
        "stage_harness_hash": _sha256_file(
            PYTHON_SERVICE_ROOT / "benchmarks/isolated_integration/"
            "harness.py"),
        "model_adapter_hash": _sha256_file(
            PYTHON_SERVICE_ROOT / "httpserver/services/investigation/"
            "agent_model_adapter.py"),
        "diagnostic_sink_hash": _sha256_file(
            PYTHON_SERVICE_ROOT / "httpserver/services/investigation/"
            "agent_failure_diagnostics.py"),
        "provider": FROZEN_CONFIG["provider"],
        "requested_model": FROZEN_CONFIG["requested_model"],
        "provider_model_id": FROZEN_CONFIG["requested_model"],
        "candidate_config_hash": _sha256_text(json.dumps(
            FROZEN_CONFIG, sort_keys=True)),
        "frozen_model_config": FROZEN_CONFIG,
        "corpus_case_id": CASE_ID,
        "fixture_hash": _sha256_file(HERE / "scratch" / "fixture-identity.json"),
        "working_state_hash": fixture["working_state_hash"],
        "working_state_revision": fixture["working_state_revision"],
        "integration_context_hash": fixture["integration_context_hash"],
        "reference_binding_table_hash": fixture[
            "reference_binding_table_hash"],
        "fresh_result_ids": fixture["fresh_result_ids"],
        "fresh_result_hashes": fixture["fresh_result_hashes"],
        "model_visible_instructions_hash": fixture[
            "model_visible_instructions_hash"],
        "output_tool_schema_hash": fixture["output_schema_hash"],
        "output_retry_budget": FROZEN_CONFIG["output_retry_budget"],
        "sdk_retry_policy": FROZEN_CONFIG["sdk_retry_policy"],
        "http_attempt_timeout": FROZEN_CONFIG["llm_timeout_seconds"],
        "scheduled_invocations": 1,
        "stop_conditions": [
            "INTEGRATION_INPUT_PARITY_FAIL",
            "DIAGNOSTIC_INSTRUMENTATION_BLOCKED",
            "CONNECTIVITY_BLOCKED", "PROVIDER_CAPACITY_BLOCKED",
            "PROVIDER_AUTH_BLOCKED", "MODEL_IDENTITY_MISMATCH",
            "EXPERIMENT_IDENTITY_DRIFT",
            "exactly one INTEGRATE stage invocation — never re-executed",
        ],
    }
    _exclusive_json(HERE / "rca2a4-stepfun-diagnostic-manifest-v1.json",
                    manifest)
    print("[manifest] frozen (before any real call)")


def _check_identity_drift() -> dict:
    manifest = _load(HERE / "rca2a4-stepfun-diagnostic-manifest-v1.json")
    fixture = _load(HERE / "scratch" / "fixture-identity.json")
    checks = {
        "runtime_source_hash": (
            manifest["runtime_source_hash"] == _sha256_file(
                PYTHON_SERVICE_ROOT / "httpserver/services/investigation/"
                "agent_runtime.py")),
        "stage_harness_hash": (
            manifest["stage_harness_hash"] == _sha256_file(
                PYTHON_SERVICE_ROOT / "benchmarks/isolated_integration/"
                "harness.py")),
        "model_adapter_hash": (
            manifest["model_adapter_hash"] == _sha256_file(
                PYTHON_SERVICE_ROOT / "httpserver/services/investigation/"
                "agent_model_adapter.py")),
        "diagnostic_sink_hash": (
            manifest["diagnostic_sink_hash"] == _sha256_file(
                PYTHON_SERVICE_ROOT / "httpserver/services/investigation/"
                "agent_failure_diagnostics.py")),
        "working_state_hash": (
            manifest["working_state_hash"] == fixture["working_state_hash"]),
        "integration_context_hash": (
            manifest["integration_context_hash"]
            == fixture["integration_context_hash"]),
        "binding_table_hash": (
            manifest["reference_binding_table_hash"]
            == fixture["reference_binding_table_hash"]),
    }
    if not all(checks.values()):
        raise SystemExit(f"EXPERIMENT_IDENTITY_DRIFT — STOP: {checks}")
    return manifest


def stage_sink_readiness() -> None:
    import asyncio

    from benchmarks.isolated_integration.harness import (
        IsolatedIntegrationHarness,
    )
    from httpserver.services.investigation.agent_failure_diagnostics import (
        JsonlFailureDiagnosticSink,
        schema_hash_of,
    )
    from httpserver.services.investigation.agent_integration_v2 import (
        SupervisorIntegrationDecisionV2,
    )

    _check_identity_drift()
    fixture = _load(HERE / "scratch" / "fixture-identity.json")
    sink_path = (HERE / "diagnostics" / "sink-readiness.jsonl").resolve()
    sink = JsonlFailureDiagnosticSink(sink_path)
    harness = IsolatedIntegrationHarness(
        db_path=HERE / "scratch" / "fixture-a" / "investigation.db",
        task_id=fixture["task_id"],
        investigation_id=fixture["investigation_id"],
        run_id=fixture["run_id"],
        runtime_identity={"baseline_commit": BASELINE_COMMIT,
                          "harness": EXPERIMENT_ID,
                          "specialist_result_kind":
                          "SYNTHETIC_SPECIALIST_RESULT"},
    )

    async def run():
        def invalid_fn(messages, info):  # noqa: ANN001
            import json as _json

            from pydantic_ai.messages import ModelResponse, ToolCallPart

            args = {"actions": [{
                "action_type": "update_question",
                "question_handle": "Q1",
                "to_status": "in_progress",
                "tool_call_count": 9,  # known-illegal server-owned field
            }]}
            return ModelResponse(parts=[ToolCallPart(
                info.output_tools[0].name, _json.dumps(args))])

        return await harness.run_stage(invalid_fn, diagnostic_sink=sink)

    result = asyncio.run(run())
    lines = [json.loads(line) for line in
             sink_path.read_text().splitlines() if line.strip()]
    entry = lines[-1] if lines else {}
    checks = {
        "pydantic_parse_failed": not result.committed
        and result.exception_class == "UnexpectedModelBehavior",
        "stage_is_supervisor_integrate": entry.get("stage")
        == "SUPERVISOR_INTEGRATE",
        "schema_hash_matches_frozen_v2": entry.get("schema_hash")
        == schema_hash_of(SupervisorIntegrationDecisionV2)
        == fixture["output_schema_hash"],
        "validation_error_details_observable": bool(
            entry.get("validation_error_details")),
        "tool_name_observable": entry.get("tool_name") == "final_result",
        "retry_attempts_observable": entry.get("retry_attempts") == 1,
        "run_id_correlated": entry.get("context", {}).get("run_id")
        == fixture["run_id"],
        "permissions_0600": ((sink_path.stat().st_mode & 0o777) == 0o600),
        "no_validation_input_leak": "9" not in json.dumps(
            entry.get("validation_error_details", [])),
        "no_evidence_content_leak": CHARTER_SAFE(entry),
        "no_api_key_leak": "sk-" not in json.dumps(entry)
        and "api_key" not in json.dumps(entry).replace("api_key_present", ""),
        "no_sqlite_commit": not result.committed,
        "frozen_state_untouched": (
            harness.isolated_input()["working_state_hash"]
            == fixture["working_state_hash"]),
    }
    gate = {
        "artifact_version": "RCA2A4SinkReadinessGateV1",
        "experiment_id": EXPERIMENT_ID,
        "sink_path": str(sink_path),
        "checks": checks,
        "verdict": ("READY" if all(checks.values())
                    else "DIAGNOSTIC_INSTRUMENTATION_BLOCKED"),
    }
    _exclusive_json(HERE / "rca2a4-sink-readiness-gate-v1.json", gate)
    print(f"[sink-readiness] {gate['verdict']}")
    if gate["verdict"] != "READY":
        raise SystemExit("DIAGNOSTIC_INSTRUMENTATION_BLOCKED — STOP")


def CHARTER_SAFE(entry) -> bool:
    text = json.dumps(entry, ensure_ascii=False)
    # no evidence bodies: the fixture is honest-empty, so any evidence
    # document content is impossible; keys must only be codes/locs
    forbidden = ("logon", "话术", "USDT", "fraud script")
    return not any(token in text for token in forbidden)


def _no_harness_injection() -> bool:
    """The real invocation must not run through any benchmark harness
    injection: our sitecustomize must not be loaded, the supervisor
    factory must be the original production functions, and PYTHONPATH
    must not point at any harness directory."""
    import os

    mod = sys.modules.get("sitecustomize")
    if mod is not None:
        origin = getattr(mod, "__file__", "") or ""
        if "benchmarks" in origin or "audits" in origin:
            return False
    from httpserver.services.investigation import agent_model_adapter as _ama
    from httpserver.services.investigation import agent_supervisor as _sup

    if getattr(_ama, "build_chat_model").__module__ != _ama.__name__:
        return False
    if getattr(_sup.SupervisorAgentFactory, "build_integration_agent_v2").__qualname__ != (
        "SupervisorAgentFactory.build_integration_agent_v2"):
        return False
    for segment in os.environ.get("PYTHONPATH", "").split(os.pathsep):
        if segment and ("audits" in segment or "cf1-harness" in segment):
            return False
    return True


def stage_provider_check() -> None:
    from httpserver.services.investigation.agent_model_adapter import (
        build_chat_model,
        derive_openai_base_url,
    )

    _check_identity_drift()

    class _FrozenStepFunSettings:
        """The historical frozen step-3.7-flash@stepfun configuration,
        restored verbatim from the RCA-2A.2 run_manifest (never
        re-derived from current model defaults)."""

        llm_provider = ""
        llm_text_model = FROZEN_CONFIG["requested_model"]
        llm_text_base_url = FROZEN_CONFIG["llm_text_base_url"]
        llm_endpoint = FROZEN_CONFIG["llm_endpoint"]
        llm_text_temperature = FROZEN_CONFIG["llm_text_temperature"]
        llm_text_max_tokens = FROZEN_CONFIG["llm_text_max_tokens"]
        llm_thinking_mode = FROZEN_CONFIG["llm_thinking_mode"]
        llm_timeout_seconds = FROZEN_CONFIG["llm_timeout_seconds"]
        llm_api_key = _env_key()
        llm_model_identity_sink = []

    settings = _FrozenStepFunSettings()
    identity_sink: list = []
    settings.llm_model_identity_sink = identity_sink
    model = build_chat_model(settings)  # no network I/O by contract
    expected_base_url = derive_openai_base_url(
        FROZEN_CONFIG["llm_text_base_url"], FROZEN_CONFIG["llm_endpoint"])
    checks = {
        "actual_model_is_step_3_7_flash": model.model_name
        == "step-3.7-flash",
        "base_url_is_frozen_stepfun": expected_base_url
        == "https://api.stepfun.com/step_plan/v1",
        "no_openrouter": "openrouter" not in expected_base_url.lower(),
        "no_harness_sitecustomize_active": _no_harness_injection(),
        "api_key_present": bool(settings.llm_api_key),
        "temperature_frozen": model.settings.get("temperature") == 0.7,
        "max_tokens_frozen": model.settings.get("max_tokens") == 16384,
        "reasoning_effort_frozen": model.settings.get(
            "openai_reasoning_effort") == "none",
        "timeout_frozen": model.settings.get("timeout") == 120,
    }
    gate = {
        "artifact_version": "RCA2A4ProviderVerificationV1",
        "experiment_id": EXPERIMENT_ID,
        "checks": checks,
        "resolved_base_url": expected_base_url,
        "identity_sink_wired": True,
        "verdict": ("VERIFIED" if all(checks.values()) else "BLOCKED"),
    }
    _exclusive_json(HERE / "rca2a4-provider-verification-v1.json", gate)
    print(f"[provider-check] {gate['verdict']}")
    if gate["verdict"] != "VERIFIED":
        raise SystemExit("PROVIDER VERIFICATION BLOCKED — STOP")


def stage_preflight() -> None:
    _check_identity_drift()
    out = HERE / "capacity-preflight.json"
    proc = subprocess.run(
        [sys.executable,
         str(PYTHON_SERVICE_ROOT / "scripts" / "capacity_preflight_stepfun.py"),
         "--out", str(out)],
        capture_output=True, text=True, timeout=600,
    )
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-3:]
    print("[preflight] exit", proc.returncode, "|", " / ".join(tail))
    if proc.returncode == 3:
        raise SystemExit("OUTPUT REFUSED — STOP")
    if proc.returncode != 0:
        record = _load(out) if out.exists() else {}
        disposition = record.get("disposition", "UNKNOWN")
        classification = next(
            (p.get("classification") for p in record.get("probes", [])
             if p.get("classification")), "UNKNOWN")
        mapping = {
            "PROVIDER_QUOTA_BLOCKED": "PROVIDER_CAPACITY_BLOCKED",
            "PROVIDER_AUTH_BLOCKED": "PROVIDER_AUTH_BLOCKED",
        }
        raise SystemExit(
            f"{mapping.get(classification, 'CONNECTIVITY_BLOCKED')} — STOP "
            f"(disposition={disposition}, classification={classification})")
    record = _load(out)
    identity_ok = all(
        p.get("identity_exact") for p in record.get("probes", []))
    if not identity_ok:
        raise SystemExit("MODEL_IDENTITY_MISMATCH — STOP")
    print("[preflight] CAPACITY_PREFLIGHT_PASS (not counted as diagnostic)")


def stage_execute() -> None:
    import asyncio

    from httpserver.services.investigation.agent_failure_diagnostics import (
        JsonlFailureDiagnosticSink,
    )
    from httpserver.services.investigation.agent_model_adapter import (
        build_chat_model,
    )
    from pydantic_ai.models import Model as PydanticAiModel

    manifest = _check_identity_drift()
    fixture = _load(HERE / "scratch" / "fixture-identity.json")
    readiness = _load(HERE / "rca2a4-sink-readiness-gate-v1.json")
    provider = _load(HERE / "rca2a4-provider-verification-v1.json")
    preflight = _load(HERE / "capacity-preflight.json")
    if readiness.get("verdict") != "READY":
        raise SystemExit("DIAGNOSTIC_INSTRUMENTATION_BLOCKED — STOP")
    if provider.get("verdict") != "VERIFIED":
        raise SystemExit("PROVIDER VERIFICATION BLOCKED — STOP")
    if preflight.get("disposition") != "CAPACITY_PREFLIGHT_PASS":
        raise SystemExit("PREFLIGHT NOT PASS — STOP")

    class RecordingModel(PydanticAiModel):
        """Transparent delegate: records every request/response of the
        REAL model without altering behavior (forensic observability)."""

        def __init__(self, inner):
            self._inner = inner
            self.events: list[dict] = []

        @property
        def model_name(self):
            return self._inner.model_name

        @property
        def system(self):
            return self._inner.system

        async def request(self, messages, model_settings,
                          model_request_parameters):
            request_record = {
                "kind": "request",
                "message_count": len(messages),
                "request_tool_schemas": [
                    t.name for t in
                    (getattr(model_request_parameters, "output_tools", None)
                     or ())] or None,
            }
            self.events.append(request_record)
            response = await self._inner.request(
                messages, model_settings, model_request_parameters)
            parts = []
            for part in getattr(response, "parts", ()) or ():
                entry = {"part_kind": part.part_kind}
                if part.part_kind == "tool-call":
                    entry["tool_name"] = part.tool_name
                    entry["args"] = part.args  # RAW output-tool payload
                parts.append(entry)
            usage = getattr(response, "usage", None)
            self.events.append({
                "kind": "response",
                "parts": parts,
                "model_name": getattr(response, "model_name", None),
                "usage": {
                    "requests": getattr(usage, "requests", None),
                    "input_tokens": getattr(usage, "input_tokens", None),
                    "output_tokens": getattr(usage, "output_tokens", None),
                } if usage else None,
            })
            return response

        def __getattr__(self, name):
            return getattr(self._inner, name)

    class _FrozenStepFunSettings:
        llm_provider = ""
        llm_text_model = FROZEN_CONFIG["requested_model"]
        llm_text_base_url = FROZEN_CONFIG["llm_text_base_url"]
        llm_endpoint = FROZEN_CONFIG["llm_endpoint"]
        llm_text_temperature = FROZEN_CONFIG["llm_text_temperature"]
        llm_text_max_tokens = FROZEN_CONFIG["llm_text_max_tokens"]
        llm_thinking_mode = FROZEN_CONFIG["llm_thinking_mode"]
        llm_timeout_seconds = FROZEN_CONFIG["llm_timeout_seconds"]
        llm_api_key = _env_key()
        llm_model_identity_sink = []

    settings = _FrozenStepFunSettings()
    identity_sink: list = []
    settings.llm_model_identity_sink = identity_sink
    real_model = build_chat_model(settings)
    recorder = RecordingModel(real_model)

    from benchmarks.isolated_integration.harness import (
        IsolatedIntegrationHarness,
    )

    sink_path = (HERE / "diagnostics"
                 / "stepfun-integrate-failures.jsonl").resolve()
    sink = JsonlFailureDiagnosticSink(sink_path)
    harness = IsolatedIntegrationHarness(
        db_path=HERE / "scratch" / "fixture-a" / "investigation.db",
        task_id=fixture["task_id"],
        investigation_id=fixture["investigation_id"],
        run_id=fixture["run_id"],
        runtime_identity={"baseline_commit": BASELINE_COMMIT,
                          "harness": EXPERIMENT_ID,
                          "specialist_result_kind":
                          "SYNTHETIC_SPECIALIST_RESULT"},
    )

    result = asyncio.run(harness.run_stage(model=recorder,
                                           diagnostic_sink=sink))

    from httpserver.services.investigation.agent_failure_diagnostics import (
        schema_hash_of,
    )
    from httpserver.services.investigation.agent_integration_v2 import (
        SupervisorIntegrationDecisionV2,
    )

    evidence = {
        "artifact_version": "RCA2A4StageExecutionEvidenceV1",
        "experiment_id": EXPERIMENT_ID,
        "case_id": CASE_ID,
        "model_calls": {"plan": 0, "specialist": 0, "integrate_stage": 1},
        "stage_steps": [
            {"name": s.name, "ok": s.ok, "detail": s.detail}
            for s in result.steps
        ],
        "stage_exception_class": result.exception_class,
        "resolution_violations": list(result.resolution_violations),
        "scratch_commit_success": result.committed,
        "finalization": "NOT_EXERCISED",
        "model_response_events": recorder.events,
        "identity_records": identity_sink,
        "identity_exact": all(
            r.get("requested_model") == r.get("returned_model")
            == "step-3.7-flash" for r in identity_sink) if identity_sink
        else None,
        "sink_entries": [
            json.loads(line) for line in sink_path.read_text().splitlines()
            if line.strip()
        ] if sink_path.exists() else [],
        "sink_schema_hash_expected": schema_hash_of(
            SupervisorIntegrationDecisionV2),
        "lifecycle": result.lifecycle,
        "store_lifecycle_after": harness.store_lifecycle_snapshot(),
        "frozen_state_hash_after": harness.isolated_input()[
            "working_state_hash"],
        "frozen_state_hash_expected": fixture["working_state_hash"],
    }
    _exclusive_json(HERE / "rca2a4-stage-execution-evidence-v1.json", evidence)
    print(f"[execute] steps={[(s.name, s.ok) for s in result.steps]} "
          f"committed={result.committed} "
          f"identity_exact={evidence['identity_exact']} "
          f"model_responses={len(recorder.events) // 2}")


def main() -> int:
    parser = argparse.ArgumentParser(prog="rca2a4_run_diagnostic")
    parser.add_argument("--stage", required=True, choices=[
        "fixture-parity", "manifest", "sink-readiness", "provider-check",
        "preflight", "execute"])
    args = parser.parse_args()
    {
        "fixture-parity": stage_fixture_parity,
        "manifest": stage_manifest,
        "sink-readiness": stage_sink_readiness,
        "provider-check": stage_provider_check,
        "preflight": stage_preflight,
        "execute": stage_execute,
    }[args.stage]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
