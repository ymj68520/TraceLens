"""RCA-2A.6 — integration vocabulary guidance: offline design & test.

Stages (ALL offline; zero real model calls; artifacts via exclusive
create):

  consistency      RCA2A6PromptContractConsistencyReportV1 — control
                   (production factory) vs treatment (guidance factory)
                   captured on the FROZEN RCA-2A.4 store, read-only:
                   schema byte identity, instructions exact-suffix
                   delta, byte/char/token accounting, frozen input
                   identity
  offline          RCA2A6OfflineValidationReportV1 — deterministic
                   FunctionModel battery through the FULL production
                   stage path on fresh honest-empty fixtures, both
                   factories: legal actions stay legal, completed stays
                   rejected, closures stay fail-closed, fabricated
                   basis stays rejected, guidance contains no invented
                   handles
  protocol         RCA2A6ControlledComparisonProtocolV1 — the
                   pre-registered, NOT-EXECUTED controlled comparison
                   (arms, counts, order, gates, stop conditions,
                   metrics, analysis method)

Isolation: production code never imports anything in this tree; the
guidance module lives in benchmarks/contracts/experimental/ and the
harness extension is opt-in (default remains the production factory).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
AUDITS = HERE.parent
PARENT = AUDITS / "rca2a4-stepfun-isolated-integration"
PYTHON_SERVICE_ROOT = HERE.parents[2]
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

EXPERIMENT_ID = "rca2a6-vocabulary-guidance"
BASELINE_COMMIT = "85ab57523c966576b080846a6721e79ffa990b23"
PARENT_BASELINE_COMMIT = "3ad0dcf531975a4133f0e75b9d93f118967e4842"
COMPARISON_EXPERIMENT_ID = "rca2a6-controlled-comparison"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def _guidance_module():
    from benchmarks.contracts.experimental import (
        integration_vocabulary_guidance_v1 as guidance,
    )

    return guidance


def _harness_on_frozen_store():
    from benchmarks.isolated_integration.harness import (
        IsolatedIntegrationHarness,
    )

    fixture = _load(PARENT / "scratch" / "fixture-identity.json")
    return IsolatedIntegrationHarness(
        db_path=PARENT / "scratch" / "fixture-a" / "investigation.db",
        task_id=fixture["task_id"],
        investigation_id=fixture["investigation_id"],
        run_id=fixture["run_id"],
        runtime_identity={
            "baseline_commit": PARENT_BASELINE_COMMIT,
            "harness": "rca2a6-vocabulary-guidance (read-only derivation)",
            "specialist_result_kind": "SYNTHETIC_SPECIALIST_RESULT",
        },
    )


# ---------------------------------------------------------------------------
# §3 — prompt/contract consistency
# ---------------------------------------------------------------------------


def _token_count_estimate(text: str) -> dict:
    """Approximate token count (cl100k_base).  stepfun's own tokenizer
    is not available offline, so this is marked estimated."""
    try:
        import tiktoken

        encoding = tiktoken.get_encoding("cl100k_base")
        return {"tokens": len(encoding.encode(text)),
                "tokenizer": "cl100k_base (approximation)",
                "estimated": True}
    except Exception:  # pragma: no cover
        return {"tokens": max(1, len(text) // 4),
                "tokenizer": "chars/4 fallback",
                "estimated": True}


def stage_consistency() -> dict:
    from benchmarks.isolated_integration.harness import (
        IsolatedIntegrationHarness,
    )
    from httpserver.services.investigation.agent_failure_diagnostics import (
        schema_hash_of,
    )
    from httpserver.services.investigation.agent_integration_v2 import (
        SupervisorIntegrationDecisionV2,
    )

    guidance = _guidance_module()
    if guidance.guidance_violations():
        raise SystemExit(
            f"GUIDANCE VOCABULARY VIOLATIONS — STOP: "
            f"{guidance.guidance_violations()}")

    fixture = _load(PARENT / "scratch" / "fixture-identity.json")
    manifest = _load(PARENT / "rca2a4-stepfun-diagnostic-manifest-v1.json")
    harness = IsolatedIntegrationHarness(
        db_path=PARENT / "scratch" / "fixture-a" / "investigation.db",
        task_id=fixture["task_id"],
        investigation_id=fixture["investigation_id"],
        run_id=fixture["run_id"],
        runtime_identity={
            "baseline_commit": PARENT_BASELINE_COMMIT,
            "harness": "rca2a6-consistency (read-only derivation)",
            "specialist_result_kind": "SYNTHETIC_SPECIALIST_RESULT",
        },
    )
    control = asyncio.run(harness.capture_model_visible_input())
    treatment = asyncio.run(harness.capture_model_visible_input(
        agent_factory=guidance.GuidanceIntegrationAgentFactory))

    control_instructions = control["instructions"]
    treatment_instructions = treatment["instructions"]
    suffix = "\n\n" + guidance.GUIDANCE_TEXT
    exact_suffix = (
        treatment_instructions == control_instructions + suffix)
    # the shared prefix carries the projection (available actions,
    # evidence context, state revision/source digests) — identical
    shared_prefix_identical = treatment_instructions.startswith(
        control_instructions)

    def _schema_fingerprint(schemas) -> str:
        return _sha256_text(json.dumps(schemas, sort_keys=True))

    schema_identical = (
        control["output_tool_schemas"] == treatment["output_tool_schemas"])
    names_identical = (
        control["output_tool_names"] == treatment["output_tool_names"])
    settings_identical = (
        control["model_settings"] == treatment["model_settings"])
    projection_identical = control["projection"] == treatment["projection"]
    captured_schema_fingerprint = _schema_fingerprint(
        control["output_tool_schemas"])

    input_contract = harness.isolated_input()
    production_schema_hash = schema_hash_of(SupervisorIntegrationDecisionV2)
    input_identity = {
        "integration_context_hash": input_contract[
            "integration_context_hash"],
        "reference_binding_table_hash": input_contract[
            "reference_binding_table_hash"],
        "model_visible_instructions_hash": input_contract[
            "model_visible_instructions_hash"],
        "output_schema_hash": input_contract["output_schema_hash"],
        "equals_frozen_2a4": (
            input_contract["integration_context_hash"]
            == fixture["integration_context_hash"]
            and input_contract["reference_binding_table_hash"]
            == fixture["reference_binding_table_hash"]
            and input_contract["output_schema_hash"]
            == fixture["output_schema_hash"]),
        "schema_definition_matches_frozen_manifest": (
            production_schema_hash == manifest["output_tool_schema_hash"]),
    }

    input_identity["captured_schema_fingerprint"] = (
        captured_schema_fingerprint)
    guidance_text = guidance.GUIDANCE_TEXT
    report = {
        "artifact_version": "RCA2A6PromptContractConsistencyReportV1",
        "experiment_id": EXPERIMENT_ID,
        "baseline_commit": BASELINE_COMMIT,
        "guidance": {
            "artifact": (
                "benchmarks/contracts/experimental/"
                "integration_vocabulary_guidance_v1.py"),
            "version": guidance.GUIDANCE_VERSION,
            "sha256": guidance.guidance_sha256(),
            "self_verification_violations": guidance.guidance_violations(),
            "bytes": len(guidance_text.encode("utf-8")),
            "chars": len(guidance_text),
            "vocabulary_source": (
                "rendered programmatically from the production "
                "QuestionStatus/QuestionDisposition enums — no second "
                "state definition exists"),
        },
        "comparison": {
            "control_arm": (
                "production SupervisorAgentFactory."
                "build_integration_agent_v2 (untouched)"),
            "treatment_arm": (
                "GuidanceIntegrationAgentFactory — same model, same "
                "output_type, production instruction text + frozen "
                "guidance suffix"),
            "capture_store": "frozen RCA-2A.4 fixture store (read-only)",
        },
        "checks": {
            "SCHEMA_UNCHANGED": schema_identical,
            "output_tool_names_unchanged": names_identical,
            "model_settings_unchanged": settings_identical,
            "projection_unchanged": projection_identical,
            "PROMPT_DIFF_PASS__exact_suffix_only": exact_suffix,
            "shared_prefix_identical": shared_prefix_identical,
            "INPUT_IDENTITY_PASS__frozen_store": input_identity[
                "equals_frozen_2a4"],
            "schema_hash_matches_frozen_manifest": (
                production_schema_hash
                == manifest["output_tool_schema_hash"]
                == input_contract["output_schema_hash"]),
            "retry_timeout_unchanged": (
                "structural: neither arm touches the output retry budget "
                "(pydantic-ai default 1), the frozen model config, or "
                "the adapter; the protocol binds the identical frozen "
                "config for both arms"),
        },
        "delta_accounting": {
            "guidance_bytes": len(guidance_text.encode("utf-8")),
            "guidance_chars": len(guidance_text),
            "guidance_tokens": _token_count_estimate(guidance_text),
            "instructions_delta_bytes": len(
                treatment_instructions.encode("utf-8"))
            - len(control_instructions.encode("utf-8")),
            "instructions_delta_chars": len(treatment_instructions)
            - len(control_instructions),
            "schema_delta_bytes": 0,
            "note": (
                "the ONLY model-visible difference is the pre-registered "
                "guidance suffix; everything else is byte-identical"),
        },
        "input_identity": input_identity,
        "verdict": (
            "PROMPT_CONTRACT_CONSISTENT" if (
                schema_identical and names_identical and settings_identical
                and projection_identical and exact_suffix
                and input_identity["equals_frozen_2a4"]
                and input_identity["schema_definition_matches_frozen_manifest"])
            else "PROMPT_CONTRACT_INCONSISTENT"),
    }
    if report["verdict"] != "PROMPT_CONTRACT_CONSISTENT":
        raise SystemExit("PROMPT_CONTRACT_INCONSISTENT — STOP")
    _exclusive_json(
        HERE / "rca2a6-vocabulary-guidance-draft-v1.json",
        {
            "artifact_version": "RCA2A6VocabularyGuidanceDraftV1",
            "experiment_id": EXPERIMENT_ID,
            "baseline_commit": BASELINE_COMMIT,
            "module": (
                "benchmarks/contracts/experimental/"
                "integration_vocabulary_guidance_v1.py"),
            "guidance_version": guidance.GUIDANCE_VERSION,
            "sha256": guidance.guidance_sha256(),
            "text": guidance_text,
            "generation": (
                "rendered programmatically from the production "
                "QuestionStatus/QuestionDisposition enums; "
                "guidance_violations() re-extracts every enumerated "
                "value from the text and requires exact enum membership"),
            "self_verification_violations": guidance.guidance_violations(),
            "confusions_addressed": [
                "delegation status 'completed' means the delegation "
                "finished, not that the question was answered",
                "to_status must come from the frozen QuestionStatus "
                "enum; 'completed' is not a member",
                "to_status and disposition are different semantic "
                "fields",
                "'not_supported' is a disposition value, never a "
                "to_status",
                "absence of evidence does not by itself make a question "
                "closable as answered/unresolved",
                "required-question closure still needs basis, a passed "
                "verification and the existing StateTransitionPolicy",
                "never fabricate evidence, basis handles or implied "
                "verification results",
            ],
            "forbidden_and_respected": {
                "adds_no_status_or_disposition_value": True,
                "no_auto_mapping_completed_to_answered": True,
                "no_auto_mapping_no_evidence_found_to_fact": True,
                "changes_no_pydantic_enum": True,
                "changes_no_server_validation_resolver_policy": True,
                "suggests_no_fabricated_evidence": True,
            },
            "scope": "INTEGRATE-only (GuidanceIntegrationAgentFactory "
                     "builds no PLAN/Specialist agent)",
            "accounting": {
                "bytes": report["delta_accounting"]["guidance_bytes"],
                "chars": report["delta_accounting"]["guidance_chars"],
                "tokens": report["delta_accounting"]["guidance_tokens"],
            },
            "status": "DRAFT candidate bound into "
                      "RCA2A6ControlledComparisonProtocolV1",
        })
    _exclusive_json(
        HERE / "rca2a6-prompt-contract-consistency-report-v1.json", report)
    print(f"[consistency] {report['verdict']} "
          f"(guidance {report['delta_accounting']['guidance_bytes']}B, "
          f"schema byte-identical, exact-suffix diff)")
    return report


# ---------------------------------------------------------------------------
# §4 — offline contract validation battery
# ---------------------------------------------------------------------------


def _fn(payload: dict):
    def model_fn(messages, info):  # noqa: ANN001
        from pydantic_ai.messages import ModelResponse, ToolCallPart

        return ModelResponse(parts=[ToolCallPart(
            info.output_tools[0].name, json.dumps(payload))])

    model_fn.__name__ = "rca2a6_model_fn"
    return model_fn


IN_PROGRESS_PAYLOAD = {
    "actions": [{"action_type": "update_question",
                 "question_handle": "Q1", "to_status": "in_progress",
                 "investigated_summary":
                     "honest stage integration: question advanced"}],
    "integration_summary": "question advanced in the cycle",
    "limitations": [], "warnings": []}
COMPLETED_PAYLOAD = {
    "actions": [{"action_type": "update_question",
                 "question_handle": "Q1", "to_status": "completed",
                 "disposition": "not_supported"}],
    "integration_summary": "closed", "limitations": [], "warnings": []}
ANSWERED_PAYLOAD = {
    "actions": [{"action_type": "update_question",
                 "question_handle": "Q1", "to_status": "answered",
                 "disposition": "not_supported"}],
    "integration_summary": "closed", "limitations": [], "warnings": []}
UNRESOLVED_PAYLOAD = {
    "actions": [{"action_type": "update_question",
                 "question_handle": "Q1", "to_status": "unresolved"}],
    "integration_summary": "unresolved", "limitations": [], "warnings": []}
BLOCKED_PAYLOAD = {
    "actions": [{"action_type": "update_question",
                 "question_handle": "Q1", "to_status": "blocked"}],
    "integration_summary": "blocked", "limitations": [], "warnings": []}
FABRICATED_BASIS_PAYLOAD = {
    "actions": [{"action_type": "update_question",
                 "question_handle": "Q1", "to_status": "answered",
                 "disposition": "not_supported",
                 "basis_handles": ["E1"]}],
    "integration_summary": "closed with (fabricated) basis",
    "limitations": [], "warnings": []}
NOT_SUPPORTED_AS_STATUS_PAYLOAD = {
    "actions": [{"action_type": "update_question",
                 "question_handle": "Q1", "to_status": "not_supported"}],
    "integration_summary": "status/disposition confusion",
    "limitations": [], "warnings": []}


async def _run_scenario(factory, payload, tmp_dir, scenario):
    from benchmarks.isolated_integration.fixtures import (
        prepare_post_delegation_store,
    )
    from benchmarks.isolated_integration.harness import (
        IsolatedIntegrationHarness,
    )

    prepared = await prepare_post_delegation_store(
        tmp_dir / scenario, with_evidence=False)
    harness = IsolatedIntegrationHarness(
        db_path=prepared.db_path,
        task_id=prepared.task_id,
        investigation_id=prepared.investigation_id,
        run_id=prepared.run_id,
        runtime_identity={
            "baseline_commit": BASELINE_COMMIT,
            "harness": f"rca2a6-offline-{scenario}",
            "specialist_result_kind": "SYNTHETIC_SPECIALIST_RESULT",
        },
    )
    result = await harness.run_stage(
        _fn(payload), agent_factory=factory)
    return {
        "steps": {s.name: {"ok": s.ok, "detail": s.detail}
                  for s in result.steps},
        "step_order": [s.name for s in result.steps],
        "committed": result.committed,
        "exception_class": result.exception_class,
        "resolution_violations": list(result.resolution_violations),
        "finalization": result.lifecycle.get("finalization"),
    }


async def _offline_battery(tmp_dir) -> dict:
    from httpserver.services.investigation.agent_supervisor import (
        SupervisorAgentFactory,
    )

    guidance = _guidance_module()
    scenarios = {}
    # a) legal action stays legal under BOTH arms — and behaves
    #    identically
    scenarios["legal_in_progress_control"] = await _run_scenario(
        SupervisorAgentFactory, IN_PROGRESS_PAYLOAD, tmp_dir,
        "legal_control")
    scenarios["legal_in_progress_treatment"] = await _run_scenario(
        guidance.GuidanceIntegrationAgentFactory, IN_PROGRESS_PAYLOAD,
        tmp_dir, "legal_treatment")
    # b) completed still rejected under guidance
    scenarios["completed_treatment"] = await _run_scenario(
        guidance.GuidanceIntegrationAgentFactory, COMPLETED_PAYLOAD,
        tmp_dir, "completed")
    # c-e) closures still fail closed under guidance
    scenarios["answered_treatment"] = await _run_scenario(
        guidance.GuidanceIntegrationAgentFactory, ANSWERED_PAYLOAD,
        tmp_dir, "answered")
    scenarios["unresolved_treatment"] = await _run_scenario(
        guidance.GuidanceIntegrationAgentFactory, UNRESOLVED_PAYLOAD,
        tmp_dir, "unresolved")
    scenarios["blocked_treatment"] = await _run_scenario(
        guidance.GuidanceIntegrationAgentFactory, BLOCKED_PAYLOAD,
        tmp_dir, "blocked")
    # f) fabricated basis still rejected (no evidence exists; the
    #    resolver must not accept an invented E-handle)
    scenarios["fabricated_basis_treatment"] = await _run_scenario(
        guidance.GuidanceIntegrationAgentFactory,
        FABRICATED_BASIS_PAYLOAD, tmp_dir, "fabricated")
    # g) disposition/status confusion still rejected
    scenarios["not_supported_as_status_treatment"] = await _run_scenario(
        guidance.GuidanceIntegrationAgentFactory,
        NOT_SUPPORTED_AS_STATUS_PAYLOAD, tmp_dir, "not_supported_status")
    return scenarios


def stage_offline() -> dict:
    import re
    import tempfile

    guidance = _guidance_module()
    tmp_dir = Path(tempfile.mkdtemp(prefix="rca2a6-offline-"))
    scenarios = asyncio.run(_offline_battery(tmp_dir))

    def steps_of(name):
        return scenarios[name]["steps"]

    def codes_of(name):
        detail = steps_of(name).get("transition_validation", {}).get(
            "detail", {})
        return detail.get("codes")

    def ok_chain(name, *names):
        return all(steps_of(name).get(n, {}).get("ok") for n in names)

    # expected outcomes
    both_legal_commit = (
        scenarios["legal_in_progress_control"]["committed"]
        and scenarios["legal_in_progress_treatment"]["committed"]
        and scenarios["legal_in_progress_control"]["step_order"]
        == scenarios["legal_in_progress_treatment"]["step_order"])
    completed_still_rejected = (
        not scenarios["completed_treatment"]["committed"]
        and scenarios["completed_treatment"]["exception_class"]
        == "UnexpectedModelBehavior")
    answered_still_fail_closed = (
        not scenarios["answered_treatment"]["committed"]
        and ok_chain("answered_treatment", "model_output_received",
                     "pydantic_validation", "canonical_resolution",
                     "decision_validator")
        and not steps_of("answered_treatment")[
            "transition_validation"]["ok"]
        and codes_of("answered_treatment")
        == ["QUESTION_CLOSURE_BASIS_REQUIRED",
            "QUESTION_CLOSURE_VERIFICATION_REQUIRED"])
    unresolved_still_fail_closed = (
        not scenarios["unresolved_treatment"]["committed"]
        and codes_of("unresolved_treatment")
        == ["QUESTION_CLOSURE_BASIS_REQUIRED"])
    blocked_still_fail_closed = (
        not scenarios["blocked_treatment"]["committed"]
        and codes_of("blocked_treatment") == ["QUESTION_BLOCKER_REQUIRED"])
    fabricated_still_rejected = (
        not scenarios["fabricated_basis_treatment"]["committed"]
        and scenarios["fabricated_basis_treatment"]["resolution_violations"]
        == ["HANDLE_UNKNOWN"])
    not_supported_status_still_rejected = (
        not scenarios["not_supported_as_status_treatment"]["committed"]
        and scenarios["not_supported_as_status_treatment"][
            "exception_class"] == "UnexpectedModelBehavior")

    # guidance must not invent concrete handles (no E1/Q1/... anywhere)
    invented_handles = sorted(set(
        re.findall(r"\b(?:COV)?[EQHXFP]\d+\b", guidance.GUIDANCE_TEXT)))

    report = {
        "artifact_version": "RCA2A6OfflineValidationReportV1",
        "experiment_id": EXPERIMENT_ID,
        "baseline_commit": BASELINE_COMMIT,
        "scope_statement": (
            "these tests verify the guidance does not CONFLICT with the "
            "existing contract and that every fail-closed layer still "
            "holds with the guidance present; they CANNOT prove the "
            "model would comply with the guidance — that is exactly "
            "what the pre-registered controlled comparison is for"),
        "scenario_results": scenarios,
        "checks": {
            "legal_actions_still_legal_and_identical": both_legal_commit,
            "completed_still_rejected": completed_still_rejected,
            "answered_closure_still_fail_closed": answered_still_fail_closed,
            "unresolved_still_fail_closed": unresolved_still_fail_closed,
            "blocked_still_fail_closed": blocked_still_fail_closed,
            "fabricated_basis_still_rejected": fabricated_still_rejected,
            "disposition_as_status_still_rejected":
                not_supported_status_still_rejected,
            "guidance_invents_no_handles": invented_handles == [],
            "guidance_enum_self_verification":
                guidance.guidance_violations() == [],
        },
        "finalization_separation": {
            "every_scenario_finalization": "NOT_EXERCISED",
            "note": (
                "integration_commit (when it happens) is a stage-level "
                "state transition only; Pydantic improvement != Policy "
                "success != Investigation finalization — no scenario "
                "exercised finalization and none will in the "
                "comparison arms"),
        },
        "invented_handle_scan": invented_handles,
        "verdict": "NO_CONFLICT_WITH_EXISTING_CONTRACT" if all([
            both_legal_commit, completed_still_rejected,
            answered_still_fail_closed, unresolved_still_fail_closed,
            blocked_still_fail_closed, fabricated_still_rejected,
            not_supported_status_still_rejected,
            invented_handles == [],
            guidance.guidance_violations() == [],
        ]) else "CONFLICT_DETECTED",
        "disposition": None,  # filled below
    }
    report["disposition"] = (
        "VOCABULARY_CANDIDATE_READY_FOR_COMPARISON"
        if report["verdict"] == "NO_CONFLICT_WITH_EXISTING_CONTRACT"
        else "VOCABULARY_CANDIDATE_NEEDS_REVISION")
    _exclusive_json(
        HERE / "rca2a6-offline-validation-report-v1.json", report)
    print(f"[offline] {report['verdict']} -> {report['disposition']}")
    if report["verdict"] != "NO_CONFLICT_WITH_EXISTING_CONTRACT":
        raise SystemExit("CONFLICT_DETECTED — STOP")
    return report


# ---------------------------------------------------------------------------
# §5/§6/§7 — pre-registered controlled comparison protocol (NOT executed)
# ---------------------------------------------------------------------------


def stage_protocol() -> dict:
    guidance = _guidance_module()
    consistency = _load(
        HERE / "rca2a6-prompt-contract-consistency-report-v1.json")
    offline = _load(HERE / "rca2a6-offline-validation-report-v1.json")
    manifest_2a4 = _load(
        PARENT / "rca2a4-stepfun-diagnostic-manifest-v1.json")
    if consistency["verdict"] != "PROMPT_CONTRACT_CONSISTENT":
        raise SystemExit("PROMPT_CONTRACT_INCONSISTENT — STOP")
    if offline["verdict"] != "NO_CONFLICT_WITH_EXISTING_CONTRACT":
        raise SystemExit("CONFLICT_DETECTED — STOP")

    protocol = {
        "artifact_version": "RCA2A6ControlledComparisonProtocolV1",
        "experiment_id": COMPARISON_EXPERIMENT_ID,
        "authored_by_phase": EXPERIMENT_ID,
        "baseline_commit": BASELINE_COMMIT,
        "status": "PREREGISTERED__NOT_EXECUTED",
        "execution_boundary": (
            "this protocol is a frozen DESIGN; executing it requires an "
            "explicit new authorization with real-model budget. Nothing "
            "here is an approval to call any provider"),
        "arms": {
            "control": {
                "schema": "SupervisorIntegrationDecisionV2 (frozen, "
                          "unchanged)",
                "instructions": "production _integration_instructions_v2",
                "factory": "SupervisorAgentFactory (production)",
                "instructions_sha256_bound_at_pair_time": (
                    "captured and pinned per pair by the INPUT_IDENTITY "
                    "gate"),
            },
            "treatment": {
                "schema": "SupervisorIntegrationDecisionV2 (frozen, "
                          "unchanged — byte-identical, see consistency "
                          "report)",
                "instructions": ("production _integration_instructions_v2"
                                 " + frozen guidance suffix"),
                "factory": "GuidanceIntegrationAgentFactory "
                           "(INTEGRATE-only experimental)",
                "guidance_version": guidance.GUIDANCE_VERSION,
                "guidance_sha256": guidance.guidance_sha256(),
                "guidance_bytes": consistency["delta_accounting"][
                    "guidance_bytes"],
            },
        },
        "invariants_both_arms": {
            "model": manifest_2a4["requested_model"],
            "provider": manifest_2a4["provider"],
            "frozen_model_config": manifest_2a4["frozen_model_config"],
            "adapter": "production build_chat_model (unchanged source, "
                       "hash-pinned at manifest time)",
            "output_tool_schema": manifest_2a4["output_tool_schema_hash"],
            "output_retry_budget":
                manifest_2a4["frozen_model_config"]["output_retry_budget"],
            "http_attempt_timeout": manifest_2a4["http_attempt_timeout"],
            "grounding_and_policy": "production IntegrationDecisionValidator"
                                    " + StateTransitionPolicy (unchanged)",
            "only_allowed_model_visible_difference": "the guidance suffix",
        },
        "fixture": {
            "builder": ("benchmarks.isolated_integration.fixtures."
                        "prepare_post_delegation_store(with_evidence="
                        "False) — the verified t2-no-evidence semantics"),
            "per_pair_instances": 2,
            "instance_discipline": (
                "ONE fresh deterministic instance per ARM per pair "
                "(a committed integration mutates the store, so arms "
                "never share an instance); cross-instance identity is "
                "SEMANTIC (the 2A.3 parity fields: output_tool_schema, "
                "projection, model_settings, output_tool_names), not "
                "byte identity of run-scoped hashes"),
            "evidence": "public synthetic/calibration only",
        },
        "pairing_and_order": {
            "design": "paired diagnostics, deterministic order",
            "rule": ("for pair i (i=1..4): prepare control instance, "
                     "run control; prepare treatment instance, run "
                     "treatment; never reorder, never skip, never "
                     "re-run"),
            "randomization": "none (fixed order, declared in advance)",
        },
        "sample_counts": {
            "pairs": 4,
            "per_arm_stage_invocations": 4,
            "total_stage_invocations": 8,
            "max_model_requests": 16,
            "derivation": "retry budget 1 -> at most 2 requests per "
                          "stage invocation",
            "no_dynamic_increase": (
                "the sample count is frozen here; results may NEVER be "
                "used to justify adding pairs"),
        },
        "provider_capacity_gate": {
            "tool": "scripts/capacity_preflight_stepfun.py --out "
                    "(exclusive create, exit-3 no-clobber)",
            "requirement": "CAPACITY_PREFLIGHT_PASS + identity exact on "
                           "every probe, BEFORE pair 1",
            "preflight_probes": 3,
            "classification_mapping": {
                "PROVIDER_QUOTA_BLOCKED": "PROVIDER_CAPACITY_BLOCKED",
                "PROVIDER_AUTH_BLOCKED": "PROVIDER_AUTH_BLOCKED",
            },
        },
        "pre_call_gates": {
            "INPUT_IDENTITY_PASS": (
                "per pair: semantic parity of both instances' captured "
                "model-visible input (2A.3 field discipline)"),
            "PROMPT_DIFF_PASS": (
                "treatment instructions == control instructions + "
                "\\n\\n + guidance(GUIDANCE sha "
                f"{guidance.guidance_sha256()[:12]}…) exactly"),
            "SCHEMA_UNCHANGED": (
                "output-tool schema hash == "
                f"{manifest_2a4['output_tool_schema_hash']} in both arms "
                "and equal to the frozen RCA-2A.4 manifest"),
            "DIAGNOSTICS_READY": (
                "deterministic FunctionModel invalid-output through BOTH "
                "arms -> RCA-1 sink with observable stage/schema_hash/"
                "tool_name/validation_error_details, 0600 permissions, "
                "zero real model calls"),
        },
        "stop_conditions": [
            "any pre-call gate fails",
            "CAPACITY_PREFLIGHT not PASS / PROVIDER_AUTH_BLOCKED / "
            "PROVIDER_CAPACITY_BLOCKED",
            "MODEL_IDENTITY_MISMATCH on any response",
            "EXPERIMENT_IDENTITY_DRIFT (runtime/schema/guidance hash "
            "change mid-experiment)",
            "any stage invocation raises an exception class outside "
            "{UnexpectedModelBehavior, APITimeoutError}",
            "never re-execute a stage invocation",
            "never add pairs after seeing results",
        ],
        "metrics": {
            "primary": {
                "canonical_integration_valid": (
                    "the stage reached integration_commit with status "
                    "committed — the ONLY success metric; nothing below "
                    "it counts as success"),
            },
            "layered_diagnostics": {
                "output_tool_received": "stage step model_output_received",
                "pydantic_parse_success": "stage step pydantic_validation",
                "canonical_resolution_success":
                    "stage step canonical_resolution",
                "transition_validation_success":
                    "stage step transition_validation",
                "integration_commit_eligible": "StageResult.committed",
            },
            "observables": {
                "invalid_question_status": (
                    "enum error on to_status in the terminal validation "
                    "details, or raw args scan of the recording proxy"),
                "invalid_disposition": (
                    "enum error on disposition, or raw args scan"),
                "field_name_mismatch": (
                    "extra_forbidden/missing on the operand/status "
                    "field names in raw args"),
                "output_retry_exhaustion": (
                    "UnexpectedModelBehavior with retry_attempts==1"),
                "provider_timeout": "APITimeoutError classification",
                "input_tokens": "usage per response (recording proxy)",
                "output_tokens": "usage per response (recording proxy)",
                "to_status_completed_recurrence": (
                    "EXPLICIT CHECK: scan every raw response's args for "
                    '"to_status": "completed" and record per arm'),
            },
            "separation_rule": (
                "Pydantic improvement != Policy success != Investigation "
                "finalization; an arm whose payload only parses better "
                "is NOT a policy success; finalization is NOT_EXERCISED "
                "in every arm and no incomplete investigation result may "
                "be recorded as success"),
        },
        "analysis_method": {
            "style": "descriptive paired counts ONLY",
            "statistical_testing": (
                "none — 4 pairs cannot support significance; no p-"
                "values, no rates, no generalization"),
            "per_arm_table": (
                "each arm: canonical_integration_valid count, per-layer "
                "reach counts, observables counts, token totals"),
            "paired_view": (
                "per pair: which layers each arm reached; where they "
                "diverge, the raw args and sink entries decide"),
            "claims_allowed": [
                "descriptive observations on this fixture/model/sample",
                "whether to_status=completed recurred",
            ],
            "claims_forbidden": [
                "model reliability improvement",
                "qualification or readiness verdicts",
                "any statement beyond the tested fixture/model",
            ],
        },
        "data_integrity": {
            "historical_payloads": "RCA-2A.4 artifacts immutable "
                                   "(hash-pinned); the historical single "
                                   "failure is NOT a control arm",
            "holdout": "no holdout access",
            "reproducibility": (
                "experiment manifest binds runtime source hash, adapter "
                "hash, schema hash, guidance sha256, fixture builder "
                "identity and the frozen model config before run 1"),
        },
    }
    _exclusive_json(
        HERE / "rca2a6-controlled-comparison-protocol-v1.json", protocol)
    print("[protocol] PREREGISTERED__NOT_EXECUTED "
          "(4 pairs / 8 stage invocations / max 16 model requests)")
    return protocol


STAGES = {
    "consistency": stage_consistency,
    "offline": stage_offline,
    "protocol": stage_protocol,
}


def main() -> int:
    parser = argparse.ArgumentParser(prog="rca2a6_run_audit")
    parser.add_argument("--stage", required=True, choices=sorted(STAGES))
    args = parser.parse_args()
    STAGES[args.stage]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
