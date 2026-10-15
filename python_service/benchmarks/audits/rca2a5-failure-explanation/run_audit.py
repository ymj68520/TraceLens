"""RCA-2A.5 — offline failure explanation & counterfactual validation.

Everything here is OFFLINE and deterministic: zero real model calls, no
production modifications, no new production schema.  The only model
outputs used are the TWO raw output-tool payloads already captured by
the RCA-2A.4 recording proxy (historical artifacts, hash-pinned).

Stages (each writes its artifact through exclusive create; never
overwrites an existing artifact):

  identity        historical artifact fingerprint + runtime identity
                  continuity (schema hash, production source hashes vs
                  the frozen RCA-2A.4 manifest)
  evidence        RCA2A5ObservedPayloadEvidenceV1 — raw args SHA256,
                  observed-vs-replayed ValidationError scope, payload
                  immutability cross-checks
  replay          deterministic replay of BOTH raw payloads against the
                  frozen SupervisorIntegrationDecisionV2 — raw error
                  count vs payload count vs blocking vs union-cascade
  vocabulary      RCA2A5StateVocabularyMatrixV1 — production state
                  vocabulary matrix + token scan of the ACTUAL
                  model-visible input (re-derived READ-ONLY from the
                  frozen RCA-2A.4 store) + verdict
  counterfactual  RCA2A5CounterfactualValidationReportV1 — attempt-2
                  single-field status replacements through the FULL
                  production path (pydantic -> canonical -> validator ->
                  policy -> commit-boundary) on per-variant COPIES of
                  the frozen store
  proposal        Original V2 vs Uniform Proposal V1 draft vs
                  Strict+CompactTyped on both attempts, with explicit
                  deterministic transforms (never passed off as
                  model-generated)
  intervention    RCA2A5InterventionComparisonV1 — design-level A/B/C
                  assessment; nothing is implemented

Isolation: this module lives in the benchmarks tree; production code
never imports it.  Reports contain raw payload digests and validation
metadata only — no full prompts, no API keys, no evidence bodies.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
AUDITS = HERE.parent
PARENT = AUDITS / "rca2a4-stepfun-isolated-integration"
PYTHON_SERVICE_ROOT = HERE.parents[2]
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

EXPERIMENT_ID = "rca2a5-failure-explanation"
PARENT_EXPERIMENT_ID = "rca2a4-stepfun-isolated-integration"
BASELINE_COMMIT = "69e5bdc78e4280464b8a087d9e797f9ab66078e0"
PARENT_BASELINE_COMMIT = "3ad0dcf531975a4133f0e75b9d93f118967e4842"

PARENT_EVIDENCE = PARENT / "rca2a4-stage-execution-evidence-v1.json"
PARENT_MANIFEST = PARENT / "rca2a4-stepfun-diagnostic-manifest-v1.json"
PARENT_FIELD_REPORT = PARENT / "rca2a4-field-level-failure-report-v1.json"
PARENT_SINK = PARENT / "diagnostics" / "stepfun-integrate-failures.jsonl"
PARENT_FIXTURE_IDENTITY = PARENT / "scratch" / "fixture-identity.json"
PARENT_STORE = PARENT / "scratch" / "fixture-a" / "investigation.db"
PARENT_FILES_DB = PARENT / "scratch" / "fixture-a" / "files.db"

HISTORICAL_ARTIFACTS = (
    "capacity-preflight.json",
    "rca2a4-field-level-failure-report-v1.json",
    "rca2a4-input-parity-gate-report-v1.json",
    "rca2a4-provider-verification-v1.attempt1-blocked-system-sitecustomize.json",
    "rca2a4-provider-verification-v1.json",
    "rca2a4-runtime-identity-record-v1.json",
    "rca2a4-sink-readiness-gate-v1.json",
    "rca2a4-stage-execution-evidence-v1.json",
    "rca2a4-stage-execution-report-v1.json",
    "rca2a4-stepfun-diagnostic-manifest-v1.json",
    "diagnostics/sink-readiness.jsonl",
    "diagnostics/stepfun-integrate-failures.jsonl",
    "scratch/fixture-identity.json",
)

TOKENS = (
    "completed", "complete", "answered", "unresolved", "not_supported",
    "in_progress", "blocked", "superseded", "covered", "resolved",
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


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


def _raw_args(evidence: dict, attempt_index: int) -> str:
    """The RAW output-tool args string of one attempt (attempt 1 = the
    initial response, attempt 2 = the one frozen-budget retry)."""
    responses = [e for e in evidence["model_response_events"]
                 if e["kind"] == "response"]
    response = responses[attempt_index]
    tool_parts = [p for p in response["parts"]
                  if p["part_kind"] == "tool-call"]
    assert len(tool_parts) == 1, "exactly one tool-call part per response"
    return tool_parts[0]["args"]


def _harness_on_frozen_store():
    from benchmarks.isolated_integration.harness import (
        IsolatedIntegrationHarness,
    )

    fixture = _load(PARENT_FIXTURE_IDENTITY)
    return IsolatedIntegrationHarness(
        db_path=PARENT_STORE,
        task_id=fixture["task_id"],
        investigation_id=fixture["investigation_id"],
        run_id=fixture["run_id"],
        runtime_identity={
            "baseline_commit": PARENT_BASELINE_COMMIT,
            "harness": "rca2a5-failure-explanation (read-only derivation)",
            "specialist_result_kind": "SYNTHETIC_SPECIALIST_RESULT",
        },
    )


# ---------------------------------------------------------------------------
# stage: identity
# ---------------------------------------------------------------------------


def stage_identity() -> dict:
    from httpserver.services.investigation.agent_failure_diagnostics import (
        schema_hash_of,
    )
    from httpserver.services.investigation.agent_integration_v2 import (
        SupervisorIntegrationDecisionV2,
    )

    manifest = _load(PARENT_MANIFEST)
    fixture = _load(PARENT_FIXTURE_IDENTITY)
    record = {
        "artifact_version": "RCA2A5IdentityContinuityV1",
        "experiment_id": EXPERIMENT_ID,
        "baseline_commit": BASELINE_COMMIT,
        "parent_experiment_id": PARENT_EXPERIMENT_ID,
        "parent_baseline_commit": PARENT_BASELINE_COMMIT,
        "historical_artifact_sha256": {
            name: _sha256_file(PARENT / name)
            for name in HISTORICAL_ARTIFACTS
        },
        "production_continuity": {
            "schema_hash_current": schema_hash_of(
                SupervisorIntegrationDecisionV2),
            "schema_hash_frozen_manifest":
                manifest["output_tool_schema_hash"],
            "schema_hash_frozen_fixture": fixture["output_schema_hash"],
            "agent_runtime_sha256_current": _sha256_file(
                PYTHON_SERVICE_ROOT / "httpserver/services/investigation/"
                "agent_runtime.py"),
            "agent_runtime_sha256_frozen_manifest":
                manifest["runtime_source_hash"],
            "integration_context_hash_current":
                _harness_on_frozen_store().isolated_input()[
                    "integration_context_hash"],
            "integration_context_hash_frozen":
                fixture["integration_context_hash"],
            "binding_table_hash_current":
                _harness_on_frozen_store().isolated_input()[
                    "reference_binding_table_hash"],
            "binding_table_hash_frozen":
                fixture["reference_binding_table_hash"],
        },
        "model": {
            "provider": manifest["provider"],
            "requested_model": manifest["requested_model"],
            "identity_exact": _load(PARENT_EVIDENCE)["identity_exact"],
        },
    }
    checks = {
        "schema_hash_unchanged": (
            record["production_continuity"]["schema_hash_current"]
            == record["production_continuity"]["schema_hash_frozen_manifest"]
            == record["production_continuity"][
                "schema_hash_frozen_fixture"]),
        "agent_runtime_unchanged": (
            record["production_continuity"]["agent_runtime_sha256_current"]
            == record["production_continuity"][
                "agent_runtime_sha256_frozen_manifest"]),
        "frozen_input_context_unchanged": (
            record["production_continuity"][
                "integration_context_hash_current"]
            == record["production_continuity"][
                "integration_context_hash_frozen"]
            and record["production_continuity"]["binding_table_hash_current"]
            == record["production_continuity"]["binding_table_hash_frozen"]),
        "parent_identity_exact": bool(record["model"]["identity_exact"]),
    }
    record["checks"] = checks
    record["verdict"] = (
        "IDENTITY_CONTINUOUS" if all(checks.values())
        else "IDENTITY_DRIFT_BLOCKED")
    _exclusive_json(HERE / "rca2a5-identity-continuity-v1.json", record)
    print(f"[identity] {record['verdict']}")
    if record["verdict"] != "IDENTITY_CONTINUOUS":
        raise SystemExit("IDENTITY_DRIFT_BLOCKED — STOP")
    return record


# ---------------------------------------------------------------------------
# stage: evidence
# ---------------------------------------------------------------------------


def stage_evidence() -> dict:
    from httpserver.services.investigation.agent_failure_diagnostics import (
        schema_hash_of,
    )
    from httpserver.services.investigation.agent_integration_v2 import (
        SupervisorIntegrationDecisionV2,
    )

    evidence = _load(PARENT_EVIDENCE)
    manifest = _load(PARENT_MANIFEST)
    field_report = _load(PARENT_FIELD_REPORT)
    fixture = _load(PARENT_FIXTURE_IDENTITY)
    sink_lines = [json.loads(line) for line
                  in PARENT_SINK.read_text().splitlines() if line.strip()]

    raw_1 = _raw_args(evidence, 0)
    raw_2 = _raw_args(evidence, 1)
    parsed_1 = json.loads(raw_1)
    parsed_2 = json.loads(raw_2)

    # immutability cross-check: the parsed RAW args must equal the
    # payloads embedded in the parent field-level report (proves the
    # historical narrative was built from the raw strings, and that
    # nothing was corrected or re-serialized in between)
    embedded_1 = field_report["attempt_1_raw_output_tool_payload"]["action"]
    embedded_2 = field_report["attempt_2_raw_output_tool_payload"]["action"]
    unmodified = (
        parsed_1["actions"][0] == embedded_1
        and parsed_2["actions"][0] == embedded_2
        and parsed_1["integration_summary"]
        == field_report.get("attempt_1_raw_output_tool_payload", {}).get(
            "integration_summary", parsed_1["integration_summary"]))

    # the production sink captured ONLY the terminal (attempt 2)
    # validation errors; attempt 1's ValidationError was never persisted
    sink_entries = [e for e in sink_lines
                    if e.get("stage") == "SUPERVISOR_INTEGRATE"]
    observed = {
        "attempt_1": None,
        "attempt_2": [
            {"type": d["type"], "loc": d["loc"]}
            for d in sink_entries[-1]["validation_error_details"]
        ] if sink_entries else None,
    }
    record = {
        "artifact_version": "RCA2A5ObservedPayloadEvidenceV1",
        "experiment_id": EXPERIMENT_ID,
        "parent_experiment_id": PARENT_EXPERIMENT_ID,
        "created_from": {
            "stage_execution_evidence": str(
                PARENT_EVIDENCE.relative_to(PYTHON_SERVICE_ROOT)),
            "parent_baseline_commit": PARENT_BASELINE_COMMIT,
        },
        "identity": {
            "provider": manifest["provider"],
            "requested_model": manifest["requested_model"],
            "returned_model_per_response": [
                r.get("model_name") for r in evidence["model_response_events"]
                if r["kind"] == "response"],
            "runtime_commit": manifest["runtime_commit"],
            "output_tool_schema_hash": schema_hash_of(
                SupervisorIntegrationDecisionV2),
            "integration_context_hash":
                fixture["integration_context_hash"],
            "reference_binding_table_hash":
                fixture["reference_binding_table_hash"],
            "model_visible_instructions_hash":
                fixture["model_visible_instructions_hash"],
            "working_state_hash": fixture["working_state_hash"],
            "working_state_revision": fixture["working_state_revision"],
        },
        "attempts": {
            "attempt_1": {
                "role": "initial output-tool response",
                "raw_args_sha256": _sha256_text(raw_1),
                "tool_name": "final_result",
                "genuine_action_type_declared":
                    parsed_1["actions"][0].get("action_type"),
                "observable_validation_error": observed["attempt_1"],
                "observable_scope": (
                    "NOT_PERSISTED — the production sink records only the "
                    "terminal (retry-exhausted) validation error; attempt "
                    "1's ValidationError is reconstructed by deterministic "
                    "replay against the identical frozen schema"),
            },
            "attempt_2": {
                "role": "single frozen-budget output retry response",
                "raw_args_sha256": _sha256_text(raw_2),
                "tool_name": "final_result",
                "genuine_action_type_declared":
                    parsed_2["actions"][0].get("action_type"),
                "observable_validation_error": observed["attempt_2"],
                "observable_scope": (
                    "PERSISTED — terminal sink entry "
                    "(model_output_retry_exhausted, retry_attempts=1); "
                    "type+loc pairs only (RCA-1 redaction: no input "
                    "values)"),
            },
        },
        "payload_immutability": {
            "raw_args_equal_parent_field_report_embedding": unmodified,
            "corrected_or_reserialized": False,
        },
        "retry_feedback_observable_range": {
            "model_request_count": 2,
            "output_retry_budget": manifest["output_retry_budget"],
            "note": (
                "the retry prompt delivered to the model between attempt 1 "
                "and attempt 2 is not persisted verbatim; its effective "
                "content class is INFERRED from the observed field-name "
                "self-correction (handle->question_handle, "
                "status->to_status) — marked HYPOTHESIS where used"),
        },
        "redaction": {
            "api_keys": "absent (never read into reports)",
            "full_prompts": "absent (hashes only)",
            "evidence_bodies": "absent (fixture is honest-empty; no "
                               "evidence content exists)",
        },
    }
    if not unmodified:
        raise SystemExit("PAYLOAD IMMUTABILITY VIOLATION — STOP")
    _exclusive_json(HERE / "rca2a5-observed-payload-evidence-v1.json", record)
    print("[evidence] RCA2A5ObservedPayloadEvidenceV1 written "
          f"(raw_1={record['attempts']['attempt_1']['raw_args_sha256'][:12]}"
          f", raw_2={record['attempts']['attempt_2']['raw_args_sha256'][:12]})")
    return record


# ---------------------------------------------------------------------------
# stage: replay
# ---------------------------------------------------------------------------


def _replay_payload(payload: dict) -> dict:
    from pydantic import ValidationError

    from httpserver.services.investigation.agent_integration_v2 import (
        SupervisorIntegrationDecisionV2,
    )

    try:
        SupervisorIntegrationDecisionV2.model_validate(payload)
    except ValidationError as exc:
        errors = exc.errors(include_url=True)
        branches: dict[str, list] = {}
        for err in errors:
            loc = list(err["loc"])
            branch = loc[2] if len(loc) >= 3 else "<top>"
            branches.setdefault(branch, []).append(
                {"type": err["type"], "loc": loc})
        return {
            "pydantic_valid": False,
            "raw_error_count": len(errors),
            "union_branches_reporting": sorted(branches),
            "errors_by_branch": branches,
        }
    return {"pydantic_valid": True, "raw_error_count": 0,
            "union_branches_reporting": [], "errors_by_branch": {}}


def _genuine_defects(parsed_action: dict, replay: dict) -> list:
    """Blocking errors = errors inside the branch the model actually
    attempted (proven by the raw action_type it emitted).  All errors in
    other branches are non-discriminated-union cascade, NOT intent."""
    declared = parsed_action.get("action_type")
    intended_branch = {
        "update_question": "UpdateQuestionActionV2",
        "create_question": "CreateQuestionActionV2",
        "update_evidence_relevance": "UpdateEvidenceRelevanceActionV2",
        "create_hypothesis": "CreateHypothesisActionV2",
        "update_hypothesis": "UpdateHypothesisActionV2",
        "create_contradiction": "CreateContradictionActionV2",
        "update_contradiction": "UpdateContradictionActionV2",
        "update_coverage": "UpdateCoverageActionV2",
        "add_finding_reference": "AddFindingReferenceActionV2",
        "add_pending_proposal_reference":
            "AddPendingProposalReferenceActionV2",
    }.get(declared)
    if intended_branch is None:
        return []
    blocking = replay["errors_by_branch"].get(intended_branch, [])
    defect_keys = {
        ("extra_forbidden", "actions", 0, intended_branch): [],
    }
    return [
        {"type": e["type"],
         "field": e["loc"][-1] if e["loc"] else "<branch>"}
        for e in blocking
    ]


def stage_replay() -> dict:
    evidence = _load(PARENT_EVIDENCE)
    identity = _load(HERE / "rca2a5-identity-continuity-v1.json")
    if identity["verdict"] != "IDENTITY_CONTINUOUS":
        raise SystemExit("IDENTITY_DRIFT_BLOCKED — STOP")

    raw_1, raw_2 = _raw_args(evidence, 0), _raw_args(evidence, 1)
    parsed_1, parsed_2 = json.loads(raw_1), json.loads(raw_2)
    replay_1 = _replay_payload(parsed_1)
    replay_2 = _replay_payload(parsed_2)

    # sink cross-check: every persisted terminal (type, loc) pair must
    # appear in the replayed attempt-2 error set (loc indexes are
    # stringified on the sink side; normalize both sides)
    sink_pairs = [
        (d["type"], tuple(str(part) for part in d["loc"]))
        for d in _load(HERE / "rca2a5-observed-payload-evidence-v1.json")
        ["attempts"]["attempt_2"]["observable_validation_error"]
    ]
    replay_pairs = [
        (e["type"], tuple(str(part) for part in e["loc"]))
        for e in replay_2["errors_by_branch"].get(
            "UpdateQuestionActionV2", [])
        + replay_2["errors_by_branch"].get("CreateQuestionActionV2", [])
        + replay_2["errors_by_branch"].get(
            "UpdateEvidenceRelevanceActionV2", [])
    ]
    missing = [pair for pair in sink_pairs if pair not in replay_pairs]
    sink_reproduced = not missing
    # the sink records a SUBSET (details truncated to distinct type+loc
    # entries across the three question-related branches)
    attempt_2_blocking = _genuine_defects(parsed_2["actions"][0], replay_2)
    attempt_1_blocking = _genuine_defects(parsed_1["actions"][0], replay_1)

    report = {
        "artifact_version": "RCA2A5FailureExplanationReportV1",
        "experiment_id": EXPERIMENT_ID,
        "baseline_commit": BASELINE_COMMIT,
        "evidence_class_markers": {
            "observed_real_model_behavior": [
                "raw args of both attempts (2A.4 recording proxy)",
                "terminal sink entry (attempt 2, type+loc)",
            ],
            "deterministic_replay": [
                "both payloads re-validated against the byte-identical "
                "frozen schema (schema hash continuity proven)",
            ],
            "counterfactual_simulation": [
                "single-field status replacements (separate report)",
            ],
            "hypothesis": [
                "retry-prompt effective content class (not persisted "
                "verbatim)",
            ],
            "unverified_model_reliability": [
                "no failure-rate or compatibility claim is made from one "
                "sample",
            ],
        },
        "replay": {
            "attempt_1": {
                "pydantic_valid": replay_1["pydantic_valid"],
                "raw_error_count": replay_1["raw_error_count"],
                "union_branches_reporting":
                    replay_1["union_branches_reporting"],
                "intended_branch": "UpdateQuestionActionV2",
                "blocking_errors_in_intended_branch": attempt_1_blocking,
                "explanation": (
                    "three genuine defects, all in the intended branch: "
                    "abbreviated operand name 'handle' (extra_forbidden + "
                    "missing question_handle), abbreviated status name "
                    "'status' (extra_forbidden + missing to_status), and "
                    "illegal disposition 'no_evidence_found' (enum). The "
                    f"remaining {replay_1['raw_error_count'] - len(attempt_1_blocking)} "
                    "raw errors are cascade from the OTHER union branches "
                    "(non-discriminated union tries every branch; branch "
                    "errors do not imply the model attempted those "
                    "actions)"),
            },
            "attempt_2": {
                "pydantic_valid": replay_2["pydantic_valid"],
                "raw_error_count": replay_2["raw_error_count"],
                "union_branches_reporting":
                    replay_2["union_branches_reporting"],
                "intended_branch": "UpdateQuestionActionV2",
                "blocking_errors_in_intended_branch": attempt_2_blocking,
                "explanation": (
                    "exactly ONE genuine defect remains: to_status="
                    "'completed' is not a member of the frozen "
                    "QuestionStatus enum. Every field name is legal, the "
                    "handle is format-correct, disposition 'not_supported'"
                    " is legal. The remaining "
                    f"{replay_2['raw_error_count'] - len(attempt_2_blocking)} "
                    "raw errors are union cascade"),
            },
        },
        "payload_count_vs_error_count": {
            "independent_output_payloads": 2,
            "model_output_failure_count": 1,
            "note": (
                "one logical stage invocation failed once; its two raw "
                "payloads produced 72+46 raw validation errors across "
                "the union — error multiplication is a union-cascade "
                "property, not evidence of many model attempts"),
        },
        "sink_cross_check": {
            "persisted_terminal_pairs_reproduced_by_replay":
                sink_reproduced,
            "persisted_pair_count": len(sink_pairs),
            "normalization": (
                "the RCA-1 sink stringifies loc indexes (redaction-safe "
                "JSON); replay pairs are normalized to strings before "
                "comparison"),
        },
        "retry_feedback_effectiveness": {
            "class": "HYPOTHESIS (feedback text not persisted verbatim)",
            "observed_self_correction": [
                "handle -> question_handle",
                "status -> to_status",
                "dropped non-schema fields (investigated_summary inside "
                "the action was legal; dropped anyway)",
                "disposition no_evidence_found -> not_supported (legal "
                "member chosen)",
            ],
            "not_corrected": ["to_status value 'completed'"],
            "mechanism_note": (
                "attempt 1's wrong field NAME meant no enum-value "
                "feedback for the status VALUE could fire (extra_"
                "forbidden/missing, not enum); the first enum-value "
                "feedback would have been attempt 2's validation error, "
                "but the frozen budget (1) was exhausted — the model "
                "never received the legal QuestionStatus value list"),
        },
        "headline": (
            "DETERMINISTIC REPLAY CONFIRMS the 2A.4 field-level "
            "narrative: attempt 2's payload is one QuestionStatus enum "
            "violation away from parse-valid; the failure layer is a "
            "status-vocabulary error, not identity, not grounding, not "
            "provider"),
        "disposition": "DETERMINISTIC_REPLAY_CONFIRMED",
    }
    if not sink_reproduced:
        raise SystemExit("SINK CROSS-CHECK FAILED — replay does not "
                         "reproduce the persisted terminal errors")
    _exclusive_json(HERE / "rca2a5-failure-explanation-report-v1.json",
                    report)
    print(f"[replay] attempt1 raw={replay_1['raw_error_count']} "
          f"blocking={len(attempt_1_blocking)} | "
          f"attempt2 raw={replay_2['raw_error_count']} "
          f"blocking={len(attempt_2_blocking)} | sink reproduced")
    return report


# ---------------------------------------------------------------------------
# stage: vocabulary
# ---------------------------------------------------------------------------


def _state_vocabulary_matrix() -> list:
    from httpserver.services.investigation.agent_finalization import (
        CompletionMode,
        FinalReviewMode,
        FinalSemanticReviewStatus,
    )
    from httpserver.services.investigation.agent_runtime import (
        AgentRunStatus,
        DelegationStatus,
        InvestigationPauseReason,
        RunStopReason,
    )
    from httpserver.services.investigation.agent_working_state import (
        ContradictionSeverity,
        ContradictionStatus,
        CoverageStatus,
        EvidenceRelevanceStatus,
        HypothesisStatus,
        QuestionDisposition,
        QuestionPriority,
        QuestionSource,
        QuestionStatus,
    )

    rows = [
        ("AgentRunStatus", "agent_runtime", AgentRunStatus,
         "run lifecycle (server-owned)"),
        ("RunStopReason", "agent_runtime", RunStopReason,
         "run terminal reason (server-owned)"),
        ("DelegationStatus", "agent_runtime", DelegationStatus,
         "delegation lifecycle (server-owned)"),
        ("InvestigationPauseReason", "agent_runtime",
         InvestigationPauseReason, "investigation pause (server-owned)"),
        ("QuestionStatus", "agent_working_state", QuestionStatus,
         "question state machine (model updates via to_status)"),
        ("QuestionDisposition", "agent_working_state",
         QuestionDisposition, "question disposition (model chooses)"),
        ("CoverageStatus", "agent_working_state", CoverageStatus,
         "coverage dimension state machine"),
        ("EvidenceRelevanceStatus", "agent_working_state",
         EvidenceRelevanceStatus, "evidence relevance state machine"),
        ("HypothesisStatus", "agent_working_state", HypothesisStatus,
         "hypothesis state machine"),
        ("ContradictionStatus", "agent_working_state",
         ContradictionStatus, "contradiction state machine"),
        ("ContradictionSeverity", "agent_working_state",
         ContradictionSeverity, "contradiction severity (model chooses)"),
        ("QuestionSource", "agent_working_state", QuestionSource,
         "question provenance (model chooses on create)"),
        ("QuestionPriority", "agent_working_state", QuestionPriority,
         "question priority (model chooses on create)"),
        ("CompletionMode", "agent_finalization", CompletionMode,
         "finalization completion mode (server/review-side input)"),
        ("FinalReviewMode", "agent_finalization", FinalReviewMode,
         "final review mode (server-side)"),
        ("FinalSemanticReviewStatus", "agent_finalization",
         FinalSemanticReviewStatus, "external review status (server-side)"),
    ]
    return [
        {
            "enum": name,
            "module": module,
            "members": [m.value for m in enum_cls],
            "completed_is_member": "completed" in [
                m.value for m in enum_cls],
            "owner": owner,
        }
        for name, module, enum_cls, owner in rows
    ]


def _walk_json(node, path: str, hits: dict) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            _walk_json(value, f"{path}.{key}" if path else key, hits)
    elif isinstance(node, (list, tuple)):
        for index, value in enumerate(node):
            _walk_json(value, f"{path}[{index}]", hits)
    elif isinstance(node, str):
        for token in TOKENS:
            if token == node:
                hits.setdefault(token, []).append(
                    {"path": path, "value": node, "match": "exact"})
            elif token in node:
                hits.setdefault(token, []).append(
                    {"path": path, "value": node, "match": "contains"})


def _schema_enum_inventory(schemas: list) -> list:
    """Extract (branch, field, members) for every enum inside the output
    tool JSON schema — proves which legal vocabularies were model-visible
    in the schema itself."""
    inventory = []

    def walk(node, branch: str, trail: str):
        if isinstance(node, dict):
            if "enum" in node and isinstance(node["enum"], list):
                inventory.append({
                    "branch": branch,
                    "trail": trail,
                    "members": list(node["enum"]),
                })
                return
            for key, value in node.items():
                if key == "anyOf" and isinstance(value, list):
                    for index, sub in enumerate(value):
                        walk(sub, f"{branch}#anyOf[{index}]", trail)
                elif key == "properties" and isinstance(value, dict):
                    for prop, spec in value.items():
                        walk(spec, branch, f"{trail}.{prop}" if trail
                             else prop)
                elif key in ("items", "additionalProperties"):
                    walk(value, branch, trail)
                elif key in ("$defs", "definitions") and isinstance(
                        value, dict):
                    for def_name, spec in value.items():
                        walk(spec, f"{branch}#{def_name}", trail)

    for index, schema in enumerate(schemas or ()):
        walk(schema, f"output_tool[{index}]", "")
    return inventory


async def _vocabulary_scan():
    harness = _harness_on_frozen_store()
    captured = await harness.capture_model_visible_input()
    instructions = captured["instructions"]
    projection = captured["projection"]
    schemas = captured["output_tool_schemas"]
    proj_hits: dict = {}
    _walk_json(projection, "", proj_hits)
    instruction_hits = {}
    for token in TOKENS:
        hits = []
        for line in instructions.splitlines():
            if token in line:
                # bounded excerpt only — the full prompt / projection is
                # never reproduced into the report
                idx = line.find(token)
                start = max(0, idx - 40)
                excerpt = line[start:idx + len(token) + 40]
                hits.append({
                    "excerpt": excerpt,
                    "line_class": (
                        "embedded_projection_json"
                        if line.lstrip().startswith("{") else "rules_prose"),
                })
        if hits:
            instruction_hits[token] = hits
    state = harness._state
    question_rows = [
        {
            "handle": harness._table.handle_of(
                __import__(
                    "httpserver.services.investigation.agent_reference_bindings",
                    fromlist=["BindingKind"]).BindingKind.question,
                q.question_id),
            "status": q.status.value,
            "priority": q.priority.value,
            "disposition": (q.disposition.value if q.disposition else None),
            "basis_refs_count": len(q.basis_refs or ()),
            "limitations_count": len(q.limitations or ()),
            "has_investigated_summary": bool(q.investigated_summary),
            "has_blocker": bool(q.blocker),
        }
        for q in state.questions
    ]
    contract = harness.isolated_input()
    return {
        "instructions": instructions,
        "projection": projection,
        "schemas": schemas,
        "projection_hits": proj_hits,
        "instruction_hits": instruction_hits,
        "question_rows": question_rows,
        "input_contract": contract,
    }


def stage_vocabulary() -> dict:
    identity = _load(HERE / "rca2a5-identity-continuity-v1.json")
    if identity["verdict"] != "IDENTITY_CONTINUOUS":
        raise SystemExit("IDENTITY_DRIFT_BLOCKED — STOP")
    scan = asyncio.run(_vocabulary_scan())
    fixture = _load(PARENT_FIXTURE_IDENTITY)
    matrix = _state_vocabulary_matrix()
    schema_enums = _schema_enum_inventory(scan["schemas"])

    # schema hash continuity for the captured input
    schema_enums_question = next(
        (e for e in schema_enums
         if "open" in e["members"] and "superseded" in e["members"]
         and "answered" in e["members"]), None)
    schema_enums_disposition = next(
        (e for e in schema_enums
         if "not_supported" in e["members"]
         and "not_applicable" in e["members"]), None)

    completed_projection_hits = [
        h for h in scan["projection_hits"].get("completed", [])
        if h["match"] == "exact"]
    analysis = {
        "q1_where_is_completed_legal": {
            "legal_state_machines": [
                r["enum"] for r in matrix if r["completed_is_member"]],
            "not_member_of": [
                r["enum"] for r in matrix
                if not r["completed_is_member"]
                and r["enum"] in ("QuestionStatus", "CoverageStatus",
                                  "ContradictionStatus", "HypothesisStatus",
                                  "EvidenceRelevanceStatus",
                                  "CompletionMode")],
            "near_miss": (
                "CompletionMode uses 'complete' (no 'd') — a third, "
                "distinct spelling in the same runtime"),
        },
        "q2_did_the_model_see_completed": {
            "answer": "YES — verbatim, in the model-visible projection",
            "evidence": {
                "projection_exact_hits": [
                    {"path": h["path"],
                     "state_machine": "DelegationStatus (render "
                                      "hardcodes fresh D* envelope status "
                                      "as 'completed')"}
                    for h in completed_projection_hits
                ],
                "field_name_collision": (
                    "the D* envelope field carrying 'completed' is named "
                    "'status' — the SAME field name attempt 1 used for "
                    "the question update, whose legal value vocabulary "
                    "(QuestionStatus) excludes 'completed'"),
            },
        },
        "q3_question_legal_status_presented": {
            "answer": (
                "YES — in the output-tool schema enum"
                + (f" ({schema_enums_question['members']})"
                   if schema_enums_question else " (NOT FOUND — INVESTIGATE)")
                + "; the frozen instructions never enumerate them; the "
                "projection shows only each question's CURRENT status "
                "value"),
            "schema_enum_branch": schema_enums_question,
        },
        "q4_status_disposition_mapping_presented": {
            "answer": (
                "NO explicit mapping is presented anywhere in the "
                "model-visible input; instructions only say "
                "'Dispositions, statuses and closure semantics remain "
                "your responsibility and are validated strictly'; the "
                "policy-layer rules (answered requires basis refs, "
                "unresolved requires basis+limitations+summary, blocked "
                "requires blocker) are NOT in the model-visible input"),
            "basis_rule_visibility": (
                "only the explicit-empty-list rule ('basis_handles: [] "
                "means no basis and will be rejected wherever basis is "
                "required') hints that some closures need basis"),
        },
        "q5_confusion_prone_phrasing": {
            "instruction_hits": {
                k: v for k, v in scan["instruction_hits"].items()
            },
            "assessment": (
                "the D* fresh-result envelope ('status': 'completed') is "
                "the single strongest confusion surface: the model is "
                "closing a question ABOUT a completed delegation and the "
                "input names both with the same field name 'status'. "
                "'completed' reaches the model ONLY through that "
                "embedded envelope (never in the rules prose; the prose "
                "'complete' hit is 'Never emit a complete working "
                "state', an unrelated prohibition). This is an "
                "input-level COLLISION FACT; whether it caused the "
                "model's choice is NOT provable from one sample"),
        },
        "q6_schema_sufficiency": {
            "answer": (
                "the schema DOES express the distinction (per-kind enums "
                "in each action branch; to_status is enum-typed per "
                "branch), but the non-discriminated union means a wrong "
                "branch guess cascades; the schema presents the legal "
                "VALUES yet nothing in the input contrasts the run/"
                "delegation lifecycle vocabulary with the question "
                "vocabulary"),
            "disposition_schema": schema_enums_disposition,
        },
    }
    report = {
        "artifact_version": "RCA2A5StateVocabularyMatrixV1",
        "experiment_id": EXPERIMENT_ID,
        "baseline_commit": BASELINE_COMMIT,
        "evidence_class_markers": {
            "observed_real_model_behavior": [
                "attempt 1 emitted status='completed' (wrong field name "
                "side) and attempt 2 emitted to_status='completed'",
            ],
            "deterministic_replay": [
                "model-visible input re-derived READ-ONLY from the frozen "
                "store; input hashes equal the frozen manifest",
            ],
            "counterfactual_simulation": [],
            "hypothesis": [
                "that the input collision CONTRIBUTED to the model's "
                "value choice (causality unprovable from one sample)",
            ],
            "unverified_model_reliability": [
                "no claim about how often any model makes this choice",
            ],
        },
        "input_identity": {
            "integration_context_hash":
                scan["input_contract"]["integration_context_hash"],
            "reference_binding_table_hash":
                scan["input_contract"]["reference_binding_table_hash"],
            "model_visible_instructions_hash":
                scan["input_contract"]["model_visible_instructions_hash"],
            "output_schema_hash":
                scan["input_contract"]["output_schema_hash"],
            "equals_frozen_manifest": (
                scan["input_contract"]["integration_context_hash"]
                == fixture["integration_context_hash"]
                and scan["input_contract"]["output_schema_hash"]
                == fixture["output_schema_hash"]),
        },
        "state_vocabulary_matrix": matrix,
        "schema_enum_inventory_branch_count": len(schema_enums),
        "question_status_schema_enum": schema_enums_question,
        "question_disposition_schema_enum": schema_enums_disposition,
        "token_scan": {
            "projection_hits": scan["projection_hits"],
            "instruction_hits": {
                k: v for k, v in scan["instruction_hits"].items()
            },
            "note": (
                "instruction hits quote matched production rule lines "
                "only; the full prompt is never reproduced"),
        },
        "fixture_question_facts": scan["question_rows"],
        "analysis": analysis,
        "verdicts": {
            "VOCABULARY_COLLISION_CONFIRMED": (
                "CONFIRMED as an INPUT-LEVEL FACT: 'completed' (legal "
                "only in AgentRunStatus/DelegationStatus) appears "
                "verbatim in the model-visible projection as the D* "
                "envelope's 'status' value, adjacent to the question "
                "the model must update; the field NAME 'status' is also "
                "shared with attempt 1's illegal field choice"),
            "MODEL_INVALID_STATUS_CHOICE_OBSERVED": (
                "OBSERVED: the legal QuestionStatus vocabulary WAS "
                "model-visible in the output-tool schema enum, yet both "
                "attempts emitted 'completed' for to_status/status — "
                "the model-side value choice was invalid and is not "
                "explained away by schema absence"),
            "PROMPT_SCHEMA_MISMATCH_CONFIRMED": (
                "NOT CONFIRMED: no instruction text states or implies "
                "'completed' is legal for questions; instructions and "
                "schema are mutually consistent on the tested domain"),
            "INSUFFICIENT_EVIDENCE": (
                "NOT the case for the collision fact itself; "
                "INSUFFICIENT for causal attribution (one sample) and "
                "for any general model-reliability claim"),
        },
        "causality_statement": (
            "HYPOTHESIS ONLY: the input collision plausibly primed the "
            "value choice, but one sample cannot establish causation; "
            "the schema presented the legal values and the model still "
            "chose an illegal one"),
        "disposition": (
            "VOCABULARY_COLLISION_CONFIRMED__AND__"
            "MODEL_INVALID_STATUS_CHOICE_OBSERVED"),
    }
    if not report["input_identity"]["equals_frozen_manifest"]:
        raise SystemExit("FROZEN INPUT RE-DERIVATION MISMATCH — STOP")
    _exclusive_json(HERE / "rca2a5-state-vocabulary-matrix-v1.json", report)
    hits = {t: len(v) for t, v in scan["projection_hits"].items()}
    print(f"[vocabulary] matrix rows={len(matrix)} "
          f"projection_hits={hits} "
          f"completed_exact={len(completed_projection_hits)}")
    return report


# ---------------------------------------------------------------------------
# stage: counterfactual
# ---------------------------------------------------------------------------


def _copy_store(target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PARENT_STORE, target_dir / "investigation.db")
    shutil.copy2(PARENT_FILES_DB, target_dir / "files.db")
    return target_dir / "investigation.db"


def _counterfactual_fn(payload: dict):
    def counterfactual_fn(messages, info):  # noqa: ANN001
        from pydantic_ai.messages import ModelResponse, ToolCallPart

        return ModelResponse(parts=[ToolCallPart(
            info.output_tools[0].name, json.dumps(payload))])

    counterfactual_fn.__name__ = "counterfactual_fn"
    return counterfactual_fn


def _question_fact_sheet(harness):
    from httpserver.services.investigation.agent_reference_bindings import (
        BindingKind,
    )

    rows = []
    for q in harness._state.questions:
        rows.append({
            "handle": harness._table.handle_of(BindingKind.question,
                                               q.question_id),
            "status": q.status.value,
            "priority": q.priority.value,
            "disposition": q.disposition.value if q.disposition else None,
            "basis_refs_count": len(q.basis_refs or ()),
            "limitations_count": len(q.limitations or ()),
            "has_investigated_summary": bool(q.investigated_summary),
            "has_blocker": bool(q.blocker),
        })
    return rows


def stage_counterfactual() -> dict:
    from benchmarks.isolated_integration.harness import (
        IsolatedIntegrationHarness,
    )
    from httpserver.services.investigation.agent_failure_diagnostics import (
        JsonlFailureDiagnosticSink,
    )

    identity = _load(HERE / "rca2a5-identity-continuity-v1.json")
    if identity["verdict"] != "IDENTITY_CONTINUOUS":
        raise SystemExit("IDENTITY_DRIFT_BLOCKED — STOP")
    evidence = _load(PARENT_EVIDENCE)
    fixture = _load(PARENT_FIXTURE_IDENTITY)
    frozen_store_sha = _sha256_file(PARENT_STORE)

    parsed_2 = json.loads(_raw_args(evidence, 1))
    base_payload = json.loads(json.dumps(parsed_2))  # immutable copy
    original_status = base_payload["actions"][0]["to_status"]
    assert original_status == "completed", "attempt 2 premise"

    variants = {}
    for replacement in ("answered", "unresolved", "blocked"):
        payload = json.loads(json.dumps(parsed_2))
        payload["actions"][0]["to_status"] = replacement
        diff_keys = [
            key for key in payload["actions"][0]
            if payload["actions"][0][key]
            != base_payload["actions"][0].get(key)]
        assert diff_keys == ["to_status"], "single-field replacement only"

        variant_dir = HERE / "scratch" / "counterfactual" / replacement
        db_path = _copy_store(variant_dir)
        sink_path = (variant_dir / "counterfactual-failures.jsonl").resolve()
        sink = JsonlFailureDiagnosticSink(sink_path)
        harness = IsolatedIntegrationHarness(
            db_path=db_path,
            task_id=fixture["task_id"],
            investigation_id=fixture["investigation_id"],
            run_id=fixture["run_id"],
            runtime_identity={
                "baseline_commit": BASELINE_COMMIT,
                "harness": f"rca2a5-counterfactual-to_status={replacement}",
                "specialist_result_kind": "SYNTHETIC_SPECIALIST_RESULT",
            },
        )
        question_before = _question_fact_sheet(harness)
        result = asyncio.run(harness.run_stage(
            _counterfactual_fn(payload), diagnostic_sink=sink))
        steps = {s.name: {"ok": s.ok, "detail": s.detail}
                 for s in result.steps}
        policy_detail = steps.get("transition_validation", {}).get(
            "detail", {})
        question_after = _question_fact_sheet(harness)
        variants[replacement] = {
            "replacement": {"to_status": replacement},
            "single_field_difference_verified": True,
            "layer_labels": {
                "PYDANTIC_VALID": steps.get("pydantic_validation", {})
                .get("ok", False),
                "CANONICAL_VALID": steps.get("canonical_resolution", {})
                .get("ok", False),
                "DECISION_VALIDATOR_PASSED": steps.get(
                    "decision_validator", {}).get("ok", False),
                "TRANSITION_VALID": steps.get("transition_validation", {})
                .get("ok", False),
                "INTEGRATION_ELIGIBLE": result.committed,
            },
            "steps": steps,
            "policy_violation_codes": policy_detail.get("codes"),
            "exception_class": result.exception_class,
            "scratch_commit_success": result.committed,
            "question_before": question_before,
            "question_after": question_after,
            "finalization": "NOT_EXERCISED",
            "diagnostics_emitted": result.diagnostics_emitted,
            "scratch_store": str(db_path.relative_to(PYTHON_SERVICE_ROOT)),
        }
        print(f"[counterfactual] to_status={replacement}: "
              f"pydantic={variants[replacement]['layer_labels']['PYDANTIC_VALID']}"
              f" transition="
              f"{variants[replacement]['layer_labels']['TRANSITION_VALID']}"
              f" codes={policy_detail.get('codes')}")

    # t2-no-evidence fail-closed analysis
    action = base_payload["actions"][0]
    fact_promotion = {
        "action_count": len(base_payload["actions"]),
        "create_hypothesis_actions": sum(
            1 for a in base_payload["actions"]
            if a.get("action_type") == "create_hypothesis"),
        "add_finding_reference_actions": sum(
            1 for a in base_payload["actions"]
            if a.get("action_type") == "add_finding_reference"),
        "evidence_refs_in_payload": sorted({
            ref for a in base_payload["actions"]
            for key in ("basis_handles", "supporting_handles",
                        "refs_handles", "resolution_basis_handles")
            for ref in (a.get(key) or ())}),
        "evidence_snapshot_refs_in_fixture": [],
        "fact_promotion_attempted": False,
    }
    report = {
        "artifact_version": "RCA2A5CounterfactualValidationReportV1",
        "experiment_id": EXPERIMENT_ID,
        "baseline_commit": BASELINE_COMMIT,
        "method": (
            "attempt 2's raw payload (immutable copy) with ONE field "
            "replaced per variant, executed through the FULL production "
            "stage path on per-variant COPIES of the frozen RCA-2A.4 "
            "store (pydantic-ai FunctionModel injection; zero real model "
            "calls); the frozen original store is never opened for "
            "write"),
        "evidence_class_markers": {
            "observed_real_model_behavior": [
                "the base payload and every field of it except to_status",
            ],
            "deterministic_replay": [],
            "counterfactual_simulation": [
                "all three to_status replacements — these are "
                "SIMULATIONS of repaired payloads, NOT model behavior",
            ],
            "hypothesis": [],
            "unverified_model_reliability": [
                "no claim that the model WOULD produce any of these "
                "repairs",
            ],
        },
        "variants": variants,
        "t2_no_evidence_analysis": {
            "fixture": "A_no_evidence (t2-no-evidence semantics; zero "
                       "E* handles bound)",
            "answered_plus_not_supported": {
                "passes_pydantic": True,
                "passes_policy": variants.get("answered", {}).get(
                    "layer_labels", {}).get("TRANSITION_VALID"),
                "policy_codes": variants.get("answered", {}).get(
                    "policy_violation_codes"),
                "explanation": (
                    "QUESTION_CLOSURE_BASIS_REQUIRED: answered closure "
                    "demands non-empty basis refs; the honest-empty "
                    "fixture has no evidence, so an evidence-less "
                    "'answered' closure is correctly rejected "
                    "fail-closed. Q1 is additionally priority=required, "
                    "so a passed closure verification would also be "
                    "required (none exists). An illegal "
                    "auto-terminalization did NOT occur"),
            },
            "unresolved": {
                "passes_pydantic": True,
                "passes_policy": variants.get("unresolved", {}).get(
                    "layer_labels", {}).get("TRANSITION_VALID"),
                "policy_codes": variants.get("unresolved", {}).get(
                    "policy_violation_codes"),
                "explanation": (
                    "unresolved closure requires basis refs AND "
                    "limitations AND investigated_summary; attempt 2 "
                    "dropped all three on retry, and none may be "
                    "auto-filled (not auto-filled here)"),
            },
            "blocked": {
                "passes_pydantic": True,
                "passes_policy": variants.get("blocked", {}).get(
                    "layer_labels", {}).get("TRANSITION_VALID"),
                "policy_codes": variants.get("blocked", {}).get(
                    "policy_violation_codes"),
                "explanation": (
                    "blocked closure requires a verifiable blocker "
                    "string; attempt 2 carries none (single-field "
                    "replacement cannot add one)"),
            },
            "fact_promotion": fact_promotion,
            "auto_finalization": {
                "occurred": False,
                "finalization": "NOT_EXERCISED in every variant; the "
                                "stage owns no finalization path",
            },
            "single_field_repair_conclusion": (
                "COUNTERFACTUAL RESULT: NO single-field to_status "
                "replacement of attempt 2 is integration-eligible on "
                "this honest-empty fixture — pydantic validity is "
                "necessary but nowhere near sufficient; the 2A.4 "
                "'minimal-repair witness' was a SCHEMA-level witness "
                "and must not be read as a legal investigation "
                "outcome"),
        },
        "frozen_store_protection": {
            "store_sha256_before": frozen_store_sha,
            "store_sha256_after": _sha256_file(PARENT_STORE),
            "unchanged": _sha256_file(PARENT_STORE) == frozen_store_sha,
        },
        "disposition": (
            "COUNTERFACTUALS_REJECTED_AT_POLICY_LAYER__"
            "FAIL_CLOSED_HOLDING" if all(
                not v["layer_labels"]["INTEGRATION_ELIGIBLE"]
                for v in variants.values())
            else "UNEXPECTED_COMMIT_REVIEW_REQUIRED"),
    }
    if not report["frozen_store_protection"]["unchanged"]:
        raise SystemExit("FROZEN STORE MUTATED — STOP")
    _exclusive_json(HERE / "rca2a5-counterfactual-validation-report-v1.json",
                    report)
    print("[counterfactual] report written; frozen store untouched")
    return report


# ---------------------------------------------------------------------------
# stage: proposal
# ---------------------------------------------------------------------------


def _transform_v2_action_to_proposal(action: dict) -> dict:
    """EXPLICIT deterministic transform V2 action dict -> proposal
    UpdateAction dict.  Recorded per field.  This models a HYPOTHETICAL
    model that already uses envelope naming — it is never presented as
    something the real model generated."""
    mapping = {
        "action_type": ("action",
                        {"update_question": "update",
                         "update_evidence_relevance": "update",
                         "update_hypothesis": "update",
                         "update_contradiction": "update",
                         "update_coverage": "update"}),
        "handle": ("target_handle", None),
        "question_handle": ("target_handle", None),
        "status": ("to_status", None),
        "to_status": ("to_status", None),
    }
    out = {}
    transform_log = []
    for key, value in action.items():
        if key in mapping:
            new_key, value_map = mapping[key]
            new_value = value_map.get(value, value) if value_map else value
            out[new_key] = new_value
            transform_log.append({"from": key, "to": new_key,
                                  "value": value, "transformed_value":
                                      new_value})
        else:
            out[key] = value
            transform_log.append({"from": key, "to": key,
                                  "value": value, "transformed_value":
                                      value})
    return out, transform_log


def stage_proposal() -> dict:
    from benchmarks.contracts.experimental.integration_proposal_v1 import (
        CompactTypedUpdateAction,
        MergedStatusEnum,
        ProposalViolation,
        SupervisorIntegrationProposalV1,
        UpdateAction,
        resolve_proposal_to_canonical,
    )

    identity = _load(HERE / "rca2a5-identity-continuity-v1.json")
    if identity["verdict"] != "IDENTITY_CONTINUOUS":
        raise SystemExit("IDENTITY_DRIFT_BLOCKED — STOP")
    evidence = _load(PARENT_EVIDENCE)

    parsed_1 = json.loads(_raw_args(evidence, 0))
    parsed_2 = json.loads(_raw_args(evidence, 1))

    def proposal_parse(payload_actions: list, top: dict, scheme: str):
        if scheme == "draft":
            envelope = {
                "integration_summary": top.get("integration_summary", ""),
                "actions": payload_actions,
                "limitations": top.get("limitations", []),
                "warnings": top.get("warnings", []),
            }
            try:
                proposal = SupervisorIntegrationProposalV1.model_validate(
                    envelope)
            except Exception as exc:  # noqa: BLE001
                from pydantic import ValidationError

                if isinstance(exc, ValidationError):
                    return {"parse": "rejected",
                            "parse_errors": exc.errors(include_url=True)}
                raise
            try:
                canonical = resolve_proposal_to_canonical(proposal)
            except ProposalViolation as pv:
                return {"parse": "accepted", "resolver": "rejected",
                        "resolver_violation_code": pv.code,
                        "resolver_violation_message": pv.message}
            return {"parse": "accepted", "resolver": "accepted",
                    "canonical_action_types": [
                        a.action_type for a in canonical.actions]}
        if scheme == "compact":
            envelope = {
                "integration_summary": top.get("integration_summary", ""),
                "actions": payload_actions,
                "limitations": top.get("limitations", []),
                "warnings": top.get("warnings", []),
            }

            from pydantic import BaseModel, ConfigDict, ValidationError
            from typing import Tuple as _Tuple, Union as _Union

            from benchmarks.contracts.experimental.integration_proposal_v1 import (  # noqa: E501
                CreateContradictionAction,
                CreateHypothesisAction,
                CreateQuestionAction,
                AddFindingReferenceAction,
                AddPendingProposalReferenceAction,
                PROPOSAL_VERSION,
            )

            class CompactTypedProposalStrict(BaseModel):
                """COMPARISON-ONLY composition of the FROZEN RCA-2A.1
                building blocks: the §8 compact-typed update action (real
                merged status enum in the model-facing schema) inside the
                §6 option-B strict proposal shape.  Lives in the
                benchmarks tree; no production import path reaches it."""

                model_config = ConfigDict(frozen=True, extra="forbid")

                proposal_version: str = PROPOSAL_VERSION
                integration_summary: str = ""
                actions: _Tuple[
                    CompactTypedUpdateAction,
                    CreateQuestionAction,
                    CreateHypothesisAction,
                    CreateContradictionAction,
                    AddFindingReferenceAction,
                    AddPendingProposalReferenceAction,
                ] = ()
                limitations: _Tuple[str, ...] = ()
                warnings: _Tuple[str, ...] = ()

            try:
                proposal = CompactTypedProposalStrict.model_validate(envelope)
            except ValidationError as exc:
                return {"parse": "rejected",
                        "parse_errors": exc.errors(include_url=True)}
            try:
                canonical = resolve_proposal_to_canonical(
                    SupervisorIntegrationProposalV1(
                        proposal_version=proposal.proposal_version,
                        integration_summary=proposal.integration_summary,
                        actions=tuple(
                            UpdateAction(**{
                                k: v for k, v in a.model_dump().items()
                                if k != "action"})
                            if isinstance(a, CompactTypedUpdateAction)
                            else a
                            for a in proposal.actions),
                        limitations=proposal.limitations,
                        warnings=proposal.warnings,
                    ))
            except ProposalViolation as pv:
                return {"parse": "accepted", "resolver": "rejected",
                        "resolver_violation_code": pv.code,
                        "resolver_violation_message": pv.message}
            return {"parse": "accepted", "resolver": "accepted",
                    "canonical_action_types": [
                        a.action_type for a in canonical.actions]}
        raise ValueError(scheme)

    results = {}
    for attempt_label, parsed in (("attempt_1", parsed_1),
                                  ("attempt_2", parsed_2)):
        action = parsed["actions"][0]
        transformed, transform_log = _transform_v2_action_to_proposal(action)
        entry = {
            "raw_v2_replay": _replay_payload(parsed),
            "transform": {
                "documented_mapping": {
                    "action_type update_question -> action update":
                        "envelope literal",
                    "handle -> target_handle": "operand field rename",
                    "status -> to_status": "status field rename",
                    "same-name pass-through": [
                        "disposition", "limitations",
                        "investigated_summary"],
                },
                "applied": transform_log,
                "honesty_note": (
                    "the transform models a HYPOTHETICAL envelope-literate "
                    "model; the REAL model emitted V2 field names — the "
                    "transformed payloads are NOT model-generated "
                    "proposal outputs"),
            },
        }
        for scheme in ("draft", "compact"):
            entry[f"envelope_{scheme}"] = proposal_parse(
                [transformed], parsed, scheme)
        # envelope faced with the RAW (untransformed) V2 field names
        try:
            SupervisorIntegrationProposalV1.model_validate({
                "actions": [action]})
            raw_names = {"parse": "accepted"}
        except Exception as exc:  # noqa: BLE001
            from pydantic import ValidationError

            raw_names = {
                "parse": "rejected",
                "error_fields": sorted({
                    e["loc"][-1] for e in exc.errors(include_url=True)
                    if e.get("loc")})} if isinstance(
                        exc, ValidationError) else {"parse": "error"}
        entry["envelope_faced_with_raw_v2_names"] = raw_names
        results[attempt_label] = entry

    merged_members = [m.value for m in MergedStatusEnum]
    from httpserver.services.investigation.agent_working_state import (
        QuestionStatus,
    )

    completed_nowhere = {
        "question_status": "completed" not in [
            m.value for m in QuestionStatus],
        "merged_status_enum": "completed" not in merged_members,
        "draft_resolver": (
            results["attempt_2"]["envelope_draft"].get(
                "resolver_violation_code")
            == "proposal_status_not_in_kind_enum"),
    }

    report = {
        "artifact_version": "RCA2A5InterventionComparisonInputV1",
        "experiment_id": EXPERIMENT_ID,
        "baseline_commit": BASELINE_COMMIT,
        "evidence_class_markers": {
            "observed_real_model_behavior": [
                "the RAW payloads and their V2-scheme replay",
            ],
            "deterministic_replay": [
                "scheme comparisons on transformed payloads (explicit "
                "deterministic transforms, documented per field)",
            ],
            "counterfactual_simulation": [
                "transformed-payload scheme outcomes",
            ],
            "hypothesis": [
                "any statement about which names a model would guess",
            ],
            "unverified_model_reliability": [
                "no reliability-improvement rate is computed from one "
                "sample",
            ],
        },
        "schemes_compared": {
            "original_v2": "frozen SupervisorIntegrationDecisionV2 "
                           "(10-branch non-discriminated union, per-branch "
                           "typed enums)",
            "uniform_proposal_v1_draft": "frozen RCA-2A.1 draft envelope "
                                         "(UpdateAction; statuses validated "
                                         "at the RESOLVER)",
            "strict_compact_typed": "frozen RCA-2A.1 building blocks "
                                    "composed (CompactTypedUpdateAction: "
                                    "merged status enum at PARSE + "
                                    "per-kind post-init validation)",
        },
        "attempts": results,
        "questions": {
            "q1_errors_avoidable_by_envelope_naming": {
                "answer": (
                    "NONE mechanically: the envelope's operand field is "
                    "'target_handle' and its status field is 'to_status' "
                    "— the attempt-1 abbreviated names 'handle' and "
                    "'status' are extra_forbidden under the envelope "
                    "exactly as under V2.  CORRECTION to the RCA-2A.4 "
                    "field-level report q7: that report rated the "
                    "'handle' defect LIKELY_ADDRESSED_BY_PROPOSAL on the "
                    "basis that 'the unified update envelope names its "
                    "operand field handle' — the frozen contract names "
                    "it target_handle; the defect is NOT addressed by "
                    "envelope naming"),
                "evidence": {
                    "attempt_1":
                        results["attempt_1"][
                            "envelope_faced_with_raw_v2_names"],
                    "attempt_2":
                        results["attempt_2"][
                            "envelope_faced_with_raw_v2_names"],
                },
            },
            "q2_errors_entering_strict_retry": {
                "answer": (
                    "attempt 2's to_status='completed' DOES enter strict "
                    "parse (merged enum) -> retry feedback; attempt 1's "
                    "disposition='no_evidence_found' does NOT enter "
                    "strict parse (disposition stays an untyped string in "
                    "the envelope; it is caught only at the resolver, "
                    "AFTER the retry boundary) — under original V2 BOTH "
                    "were parse-layer enum errors"),
                "attempt_1_compact_parse":
                    results["attempt_1"]["envelope_compact"]["parse"],
                "attempt_2_compact_parse":
                    results["attempt_2"]["envelope_compact"]["parse"],
            },
            "q3_completed_illegal_everywhere": {
                "answer": (
                    "YES — 'completed' is illegal in ALL THREE schemes "
                    "(V2 per-branch enum; draft resolver "
                    "P_STATUS_NOT_IN_KIND_ENUM; compact merged enum at "
                    "parse); no scheme relaxes the vocabulary"),
                "evidence": completed_nowhere,
            },
            "q4_resolver_new_rejections": {
                "answer": (
                    "YES for the draft: enum-class rejections MOVE from "
                    "parse (with retry feedback) to the resolver "
                    "(fail-closed, no retry feedback): observed "
                    "P_STATUS_NOT_IN_KIND_ENUM.  The compact variant "
                    "restores parse-layer rejection for to_status but "
                    "NOT for disposition (untyped) — the resolver "
                    "disposition rejection is new relative to V2's "
                    "parse-layer behavior"),
                "attempt_1_draft":
                    results["attempt_1"]["envelope_draft"],
                "attempt_2_draft":
                    results["attempt_2"]["envelope_draft"],
            },
            "q5_actionable_feedback_preserved": {
                "answer": (
                    "on THIS sample original V2 surfaces the most "
                    "defect classes at the retry-enabled layer (wrong "
                    "names AND both enums), at the cost of union "
                    "cascade noise (72/46 raw errors for 3 and 1 "
                    "genuine defects); compact trades cascade for a "
                    "smaller schema but lets disposition defects pass "
                    "the retry boundary silently; the draft moves the "
                    "most checks behind the retry boundary.  One "
                    "sample — no general ranking is claimed"),
            },
        },
        "rca2a4_q7_correction": {
            "corrected_rating": {
                "abbreviated_operand_name_handle":
                    "NOT_ADDRESSED_BY_PROPOSAL (envelope operand field "
                    "is target_handle; 'handle' remains extra_forbidden)",
                "abbreviated_status_name_status":
                    "UNKNOWN (unchanged — 'status' is illegal under the "
                    "envelope too; only to_status is legal and attempt 2 "
                    "already used it)",
                "to_status_invalid_enum_completed":
                    "NOT_ADDRESSED_BY_PROPOSAL (unchanged)",
                "disposition_invalid_enum_no_evidence_found":
                    "NOT_ADDRESSED_BY_PROPOSAL (unchanged value "
                    "vocabulary; additionally DEMOTED below the retry "
                    "boundary in both proposal variants)",
            },
            "nature": "append-only factual correction to the 2A.4 "
                      "field-level report q7 rating; the historical "
                      "artifact itself remains immutable",
        },
        "disposition": "PROPOSAL_COMPARISON_COMPLETED_ONE_SAMPLE",
    }
    _exclusive_json(HERE / "rca2a5-proposal-counterfactual-comparison-v1.json",
                    report)
    print("[proposal] draft/compact comparison written "
          f"(attempt2 draft resolver code="
          f"{results['attempt_2']['envelope_draft'].get('resolver_violation_code')})")
    return report


# ---------------------------------------------------------------------------
# stage: intervention
# ---------------------------------------------------------------------------


def stage_intervention() -> dict:
    replay = _load(HERE / "rca2a5-failure-explanation-report-v1.json")
    vocabulary = _load(HERE / "rca2a5-state-vocabulary-matrix-v1.json")
    counterfactual = _load(
        HERE / "rca2a5-counterfactual-validation-report-v1.json")
    proposal = _load(HERE / "rca2a5-proposal-counterfactual-comparison-v1.json")

    directions = {
        "A_keep_original_v2": {
            "description": "keep the full typed schema and frozen "
                           "instructions unchanged",
            "handles_observed_errors": [],
            "does_not_handle": [
                "to_status='completed' enum violation (reproduced as "
                "the sole attempt-2 blocker)",
                "attempt-1 abbreviated field names",
                "attempt-1 illegal disposition value",
            ],
            "prompt_token_delta": 0,
            "output_tool_schema_change": "none",
            "retry_feedback_change": "none",
            "resolver_rejection_change": "none",
            "grounding_policy_risk": "none (unchanged)",
            "runtime_identity_and_requalification_cost": "none",
            "residual_risk": (
                "the input-level vocabulary collision (D* envelope "
                "'status': 'completed') remains model-visible"),
        },
        "B_vocabulary_guidance_candidate": {
            "description": "instructions-only: state that to_status for "
                           "questions must come from the frozen "
                           "QuestionStatus vocabulary, that run/delegation "
                           "'completed' is a DIFFERENT state machine, map "
                           "closure statuses to their policy requirements "
                           "(answered->basis+disposition, "
                           "unresolved->basis+limitations+summary, "
                           "blocked->blocker) AND spell out the frozen "
                           "QuestionDisposition vocabulary with the "
                           "status/disposition mapping; schema unchanged",
            "handles_observed_errors": [
                "attempt-2 to_status='completed' — the exact legal value "
                "list becomes instruction text BEFORE the first attempt",
                "the status-vs-disposition mapping gap (q4) closes",
                "attempt-1's illegal disposition VALUE class "
                "(no_evidence_found) — the frozen QuestionDisposition "
                "members become prose (note: on THIS sample the "
                "disposition error co-occurred with naming errors, so "
                "class-level coverage only)",
            ],
            "does_not_handle": [
                "attempt-1 abbreviated field NAMES (a vocabulary "
                "statement cannot force field-name choice)",
                "any future wrong-branch union cascade",
                "evidence-less closures — irrelevant to B: the "
                "counterfactuals prove the policy layer rejects them "
                "regardless of what the model is told",
            ],
            "prompt_token_delta": "small positive (a few hundred tokens "
                                  "of static rule text; measured before "
                                  "any authorization to implement",
            "output_tool_schema_change": "none",
            "retry_feedback_change": "none (schema unchanged)",
            "resolver_rejection_change": "none",
            "grounding_policy_risk": "none (policy unchanged; guidance "
                                     "only mirrors EXISTING frozen policy "
                                     "rules)",
            "runtime_identity_and_requalification_cost": (
                "production prompt change -> new INTEGRATE runtime "
                "identity -> requalification required (V3 discipline); "
                "zero schema migration"),
            "residual_risk": (
                "guidance increases instruction length; value lists in "
                "text can drift from the schema if enums ever change "
                "(mitigatable by deriving text from the enum at build "
                "time — implementation detail, not decided here)"),
        },
        "C_strict_compact_typed_candidate": {
            "description": "RCA-2A.1 experimental contract (uniform "
                           "update envelope, compact typed merged status "
                           "enum, strict per-kind parse validation) while "
                           "keeping per-kind member checks and server-side "
                           "identity binding",
            "handles_observed_errors": [
                "attempt-2 to_status='completed' — merged enum rejects "
                "at parse with retry feedback (value list in the parse "
                "error)",
                "union cascade noise — 6 variants instead of 10 "
                "branches; -38% model-face size (2A.1 measurement)",
            ],
            "does_not_handle": [
                "the VALUE vocabulary itself — 'completed' is illegal "
                "there too; if the model's priming persists it fails "
                "the same way (one retry instead of zero)",
                "attempt-1 abbreviated field names (target_handle/"
                "to_status are still the required names)",
                "disposition enum violations pass the retry boundary "
                "(untyped string; resolver fail-closed AFTER retry)",
                "evidence-less closures (counterfactuals show the "
                "policy layer rejects them regardless of schema — "
                "unchanged by C)",
            ],
            "prompt_token_delta": "negative on the model face (2A.1: "
                                  "approximately -38% schema tokens), "
                                  "instructions unchanged",
            "output_tool_schema_change": "YES — new model-facing schema "
                                         "(proposal envelope + merged "
                                         "enum)",
            "retry_feedback_change": (
                "parse-layer for merged status; RESOLVER-side (no "
                "retry) for disposition/foreign-field classes"),
            "resolver_rejection_change": (
                "new proposal-layer violation codes fire before the "
                "canonical resolver (P_STATUS_NOT_IN_KIND_ENUM observed "
                "on this sample)"),
            "grounding_policy_risk": (
                "none observed on this sample (canonical actions "
                "identical post-resolver); the None-vs-[] basis "
                "distinction is preserved by the 2A.1 resolver"),
            "runtime_identity_and_requalification_cost": (
                "HIGHEST: new output contract -> new runtime identity -> "
                "full requalification; schema migration risk; "
                "equivalence proven offline (2A.1: 16/16) but model "
                "compatibility UNVERIFIED"),
            "residual_risk": (
                "one sample cannot establish model compatibility with "
                "the envelope; a controlled comparison is the only "
                "honest way to measure"),
        },
    }
    report = {
        "artifact_version": "RCA2A5InterventionComparisonV1",
        "experiment_id": EXPERIMENT_ID,
        "baseline_commit": BASELINE_COMMIT,
        "evidence_class_markers": {
            "observed_real_model_behavior": [
                "the two raw payloads anchor every 'handles observed "
                "errors' row",
            ],
            "deterministic_replay": [
                "scheme behavior on this sample",
            ],
            "counterfactual_simulation": [
                "policy-layer outcomes of repaired payloads",
            ],
            "hypothesis": [
                "priming/causality claims; model behavior under changed "
                "contracts",
            ],
            "unverified_model_reliability": [
                "ALL improvement/compatibility expectations — nothing "
                "here is a reliability measurement",
            ],
        },
        "inputs": {
            "failure_explanation": replay["disposition"],
            "vocabulary": vocabulary["disposition"],
            "counterfactual": counterfactual["disposition"],
            "proposal_comparison": proposal["disposition"],
        },
        "directions": directions,
        "decision_rule": (
            "this is a DESIGN assessment only; it does not select an "
            "implementation and does not authorize any production "
            "change; the shortest-schema option is NOT automatically "
            "preferred — direction C carries the highest "
            "requalification cost and unverified model compatibility"),
        "final_disposition_rca2a5": {
            "value": "VOCABULARY_GUIDANCE_WORTH_TESTING",
            "basis": (
                "the confirmed failure layer is a status-vocabulary "
                "error (VOCABULARY_COLLISION_CONFIRMED as an input "
                "fact + MODEL_INVALID_STATUS_CHOICE_OBSERVED with the "
                "legal values schema-visible but never prose-visible, "
                "and the enum-value feedback cut off by the frozen "
                "retry budget); direction B targets exactly this class "
                "with zero schema change and the smallest "
                "requalification surface; direction C adds NO coverage "
                "for the observed value-vocabulary defect on this "
                "sample (identical accepted values) at the highest "
                "identity/requalification cost, and both proposal "
                "variants demonstrably DEMOTE disposition validation "
                "below the retry boundary"),
            "not_claimed": (
                "B's effectiveness is UNVERIFIED (one sample; needs a "
                "controlled real-model comparison under explicit new "
                "authorization); this is a design-evaluation "
                "conclusion, not a model qualification judgment and "
                "not an implementation approval"),
        },
        "disposition": "ASSESSMENT_ONLY__NOT_IMPLEMENTED__"
                       "VOCABULARY_GUIDANCE_WORTH_TESTING",
    }
    _exclusive_json(HERE / "rca2a5-intervention-comparison-v1.json", report)
    print("[intervention] A/B/C assessment written (nothing implemented)")
    return report


STAGES = {
    "identity": stage_identity,
    "evidence": stage_evidence,
    "replay": stage_replay,
    "vocabulary": stage_vocabulary,
    "counterfactual": stage_counterfactual,
    "proposal": stage_proposal,
    "intervention": stage_intervention,
}


def main() -> int:
    parser = argparse.ArgumentParser(prog="rca2a5_run_audit")
    parser.add_argument("--stage", required=True, choices=sorted(STAGES))
    args = parser.parse_args()
    STAGES[args.stage]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
