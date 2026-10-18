"""RCA-2A.5 — offline failure explanation & counterfactual validation.

Every test is deterministic and offline (FunctionModel only, zero
provider calls).  Four evidence kinds are exercised:

(a) the TWO frozen RCA-2A.4 raw output-tool payloads replayed against
    the byte-identical production SupervisorIntegrationDecisionV2;
(b) attempt-2 single-field status counterfactuals through the FULL
    production stage path (pydantic -> canonical -> validator ->
    StateTransitionPolicy -> commit boundary) on COPIES of a freshly
    prepared honest-empty post-delegation fixture;
(c) rejection-LAYER positions across the three integration schemes
    (original V2 / uniform proposal draft / strict+compact-typed);
(d) isolation guards: historical payload immutability, frozen store
    integrity, and no production import of the experimental contract.

A payload that merely parses is never treated as a legal investigation
outcome: pydantic validity and integration eligibility are asserted as
DISTINCT layers throughout.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from benchmarks.contracts.experimental.integration_proposal_v1 import (
    CompactTypedUpdateAction,
    P_DISPOSITION_NOT_IN_ENUM,
    P_STATUS_NOT_IN_KIND_ENUM,
    ProposalViolation,
    SupervisorIntegrationProposalV1,
    UpdateAction,
    resolve_proposal_to_canonical,
)
from benchmarks.isolated_integration.fixtures import (
    prepare_post_delegation_store,
)
from benchmarks.isolated_integration.harness import (
    IsolatedIntegrationHarness,
)
from httpserver.services.investigation.agent_integration_v2 import (
    SupervisorIntegrationDecisionV2,
    UpdateQuestionActionV2,
    resolve_integration_proposal_v2,
)
from httpserver.services.investigation.agent_working_state import (
    QuestionStatus,
)

pytest.importorskip("pydantic_ai")
pytestmark = pytest.mark.migration_matrix

PYTHON_SERVICE_ROOT = Path(__file__).resolve().parents[3]
PARENT_DIR = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "audits"
    / "rca2a4-stepfun-isolated-integration"
)
AUDIT_DIR = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "audits"
    / "rca2a5-failure-explanation"
)
RUNTIME_IDENTITY = {
    "baseline_commit": "69e5bdc78e4280464b8a087d9e797f9ab66078e0",
    "harness": "rca2a5-deterministic-tests",
    "specialist_result_kind": "SYNTHETIC_SPECIALIST_RESULT",
}


def _raw_args(attempt_index: int) -> str:
    evidence = json.loads(
        (PARENT_DIR / "rca2a4-stage-execution-evidence-v1.json")
        .read_text(encoding="utf-8"))
    responses = [e for e in evidence["model_response_events"]
                 if e["kind"] == "response"]
    tool_parts = [p for p in responses[attempt_index]["parts"]
                  if p["part_kind"] == "tool-call"]
    assert len(tool_parts) == 1
    return tool_parts[0]["args"]


def _replay(payload: dict) -> dict:
    """Deterministic replay against the frozen production schema."""
    try:
        SupervisorIntegrationDecisionV2.model_validate(payload)
    except ValidationError as exc:
        errors = exc.errors(include_url=True)
        branches: dict[str, list] = {}
        for err in errors:
            branch = (err["loc"][2] if len(err["loc"]) >= 3 else "<top>")
            branches.setdefault(branch, []).append(
                {"type": err["type"], "field": err["loc"][-1],
                 "loc": list(err["loc"])})
        return {"valid": False, "raw_error_count": len(errors),
                "by_branch": branches}
    return {"valid": True, "raw_error_count": 0, "by_branch": {}}


def _counterfactual_fn(payload: dict):
    def counterfactual_fn(messages, info):  # noqa: ANN001
        from pydantic_ai.messages import ModelResponse, ToolCallPart

        return ModelResponse(parts=[ToolCallPart(
            info.output_tools[0].name, json.dumps(payload))])

    counterfactual_fn.__name__ = "counterfactual_fn"
    return counterfactual_fn


# ---------------------------------------------------------------------------
# (a) frozen payload replay
# ---------------------------------------------------------------------------


def test_attempt_payloads_immutable_and_replay_reproduces():
    raw_1, raw_2 = _raw_args(0), _raw_args(1)
    parsed_1, parsed_2 = json.loads(raw_1), json.loads(raw_2)

    # historical immutability: the recorded SHA256 values in the 2A.5
    # evidence artifact must still match the raw strings byte-for-byte
    evidence_2a5 = json.loads(
        (AUDIT_DIR / "rca2a5-observed-payload-evidence-v1.json")
        .read_text(encoding="utf-8"))
    assert evidence_2a5["attempts"]["attempt_1"]["raw_args_sha256"] == (
        hashlib.sha256(raw_1.encode("utf-8")).hexdigest())
    assert evidence_2a5["attempts"]["attempt_2"]["raw_args_sha256"] == (
        hashlib.sha256(raw_2.encode("utf-8")).hexdigest())
    assert not evidence_2a5["payload_immutability"][
        "corrected_or_reserialized"]

    # the 2A.4 field-level report must embed exactly the parsed raw args
    field_report = json.loads(
        (PARENT_DIR / "rca2a4-field-level-failure-report-v1.json")
        .read_text(encoding="utf-8"))
    assert parsed_1["actions"][0] == (
        field_report["attempt_1_raw_output_tool_payload"]["action"])
    assert parsed_2["actions"][0] == (
        field_report["attempt_2_raw_output_tool_payload"]["action"])

    replay_1 = _replay(parsed_1)
    assert not replay_1["valid"]
    assert replay_1["raw_error_count"] == 72
    blocking_1 = replay_1["by_branch"]["UpdateQuestionActionV2"]
    assert sorted((e["type"], e["field"]) for e in blocking_1) == sorted([
        ("extra_forbidden", "handle"),
        ("extra_forbidden", "status"),
        ("missing", "question_handle"),
        ("missing", "to_status"),
        ("enum", "disposition"),
    ])
    # every other reporting branch is union cascade, not intent
    assert set(replay_1["by_branch"]) - {"UpdateQuestionActionV2"}

    replay_2 = _replay(parsed_2)
    assert not replay_2["valid"]
    assert replay_2["raw_error_count"] == 46
    blocking_2 = replay_2["by_branch"]["UpdateQuestionActionV2"]
    assert [(e["type"], e["field"]) for e in blocking_2] == [
        ("enum", "to_status")]


def test_attempt2_is_one_enum_value_from_parse_valid():
    parsed_2 = json.loads(_raw_args(1))
    repaired = json.loads(json.dumps(parsed_2))
    repaired["actions"][0]["to_status"] = "unresolved"
    assert SupervisorIntegrationDecisionV2.model_validate(repaired)
    # and the legal-vocabulary proof in the other direction: 'completed'
    # is not a QuestionStatus member
    assert "completed" not in [m.value for m in QuestionStatus]


def test_sink_terminal_pairs_are_a_replay_subset():
    sink = json.loads(
        (PARENT_DIR / "diagnostics" / "stepfun-integrate-failures.jsonl")
        .read_text(encoding="utf-8").splitlines()[-1])
    persisted = [
        (d["type"], tuple(str(part) for part in d["loc"]))
        for d in sink["validation_error_details"]]
    replay_2 = _replay(json.loads(_raw_args(1)))
    replay_pairs = [
        (e["type"], tuple(str(part) for part in e["loc"]))
        for errors in replay_2["by_branch"].values() for e in errors]
    assert persisted and set(persisted) <= set(replay_pairs)


# ---------------------------------------------------------------------------
# (b) counterfactuals through the full production path
# ---------------------------------------------------------------------------


def _attempt2_with(to_status: str) -> dict:
    payload = json.loads(json.dumps(json.loads(_raw_args(1))))
    payload["actions"][0]["to_status"] = to_status
    return payload


@pytest.mark.parametrize(
    "to_status,expected_codes",
    [
        ("answered", ["QUESTION_CLOSURE_BASIS_REQUIRED",
                      "QUESTION_CLOSURE_VERIFICATION_REQUIRED"]),
        ("unresolved", ["QUESTION_CLOSURE_BASIS_REQUIRED"]),
        ("blocked", ["QUESTION_BLOCKER_REQUIRED"]),
    ],
)
async def test_counterfactuals_fail_closed_at_policy_layer(
        tmp_path, to_status, expected_codes):
    prepared = await prepare_post_delegation_store(
        tmp_path, with_evidence=False)
    harness = IsolatedIntegrationHarness(
        db_path=prepared.db_path,
        task_id=prepared.task_id,
        investigation_id=prepared.investigation_id,
        run_id=prepared.run_id,
        runtime_identity=RUNTIME_IDENTITY,
    )
    result = await harness.run_stage(
        _counterfactual_fn(_attempt2_with(to_status)))

    steps = {s.name: s for s in result.steps}
    assert steps["model_output_received"].ok
    assert steps["pydantic_validation"].ok          # PYDANTIC_VALID
    assert steps["canonical_resolution"].ok         # CANONICAL_VALID
    assert steps["decision_validator"].ok
    assert not steps["transition_validation"].ok    # NOT TRANSITION_VALID
    assert steps["transition_validation"].detail["codes"] == expected_codes
    assert not result.committed                     # NOT eligible
    snapshot = harness.store_lifecycle_snapshot()
    assert snapshot["finalization_status"] == "NOT_EXERCISED"
    assert snapshot["non_terminal_runs"] == []


async def test_pydantic_valid_is_not_integration_eligible(tmp_path):
    """The directive's layer-distinction requirement, pinned as a test:
    a payload that parses (the 2A.4 'minimal-repair witness') is still
    rejected by the production policy layer on the honest-empty
    fixture."""
    prepared = await prepare_post_delegation_store(
        tmp_path, with_evidence=False)
    harness = IsolatedIntegrationHarness(
        db_path=prepared.db_path,
        task_id=prepared.task_id,
        investigation_id=prepared.investigation_id,
        run_id=prepared.run_id,
        runtime_identity=RUNTIME_IDENTITY,
    )
    result = await harness.run_stage(
        _counterfactual_fn(_attempt2_with("unresolved")))
    names = [s.name for s in result.steps if s.ok]
    assert names == ["model_output_received", "pydantic_validation",
                     "canonical_resolution", "decision_validator"]
    assert not result.committed


async def test_counterfactuals_leave_source_store_untouched(tmp_path):
    prepared = await prepare_post_delegation_store(
        tmp_path, with_evidence=False)
    store: Path = prepared.db_path
    before = hashlib.sha256(store.read_bytes()).hexdigest()
    for to_status in ("answered", "unresolved", "blocked"):
        variant_dir = tmp_path / f"variant-{to_status}"
        variant_dir.mkdir()
        variant_store = variant_dir / "investigation.db"
        shutil.copy2(store, variant_store)
        harness = IsolatedIntegrationHarness(
            db_path=variant_store,
            task_id=prepared.task_id,
            investigation_id=prepared.investigation_id,
            run_id=prepared.run_id,
            runtime_identity=RUNTIME_IDENTITY,
        )
        result = await harness.run_stage(
            _counterfactual_fn(_attempt2_with(to_status)))
        assert not result.committed
    after = hashlib.sha256(store.read_bytes()).hexdigest()
    assert before == after


async def test_no_fact_promotion_and_no_fabricated_evidence(tmp_path):
    prepared = await prepare_post_delegation_store(
        tmp_path, with_evidence=False)
    harness = IsolatedIntegrationHarness(
        db_path=prepared.db_path,
        task_id=prepared.task_id,
        investigation_id=prepared.investigation_id,
        run_id=prepared.run_id,
        runtime_identity=RUNTIME_IDENTITY,
    )
    # the frozen 2A.4 store contract: the honest-empty fixture binds no
    # evidence at all
    assert harness.isolated_input()["evidence_snapshot_refs"] == []

    payload = _attempt2_with("unresolved")
    action = payload["actions"][0]
    assert len(payload["actions"]) == 1
    assert action["action_type"] == "update_question"
    assert not any(
        action.get(key) for key in (
            "basis_handles", "supporting_handles", "refs_handles",
            "resolution_basis_handles"))

    # canonical resolution of the (parse-valid) repaired payload: one
    # question transition, zero evidence-bearing operands, zero violations
    decision = SupervisorIntegrationDecisionV2.model_validate(payload)
    resolution, record = resolve_integration_proposal_v2(
        decision, harness._table, harness._context, harness._state)
    assert resolution is not None and not record.violations
    assert record.actions_total == 1
    transitions = resolution.model_dump()["transition_proposals"]
    assert len(transitions) == 1
    transition = transitions[0]
    assert transition["to_status"] == "unresolved"
    assert not transition.get("basis_refs")
    assert not transition.get("blocker")
    # the canonical question id is server-owned identity — the payload
    # never carried it
    assert transition["question_id"] not in json.dumps(payload)


async def test_typed_handle_identity_of_the_frozen_payloads(tmp_path):
    import re

    prepared = await prepare_post_delegation_store(
        tmp_path, with_evidence=False)
    harness = IsolatedIntegrationHarness(
        db_path=prepared.db_path,
        task_id=prepared.task_id,
        investigation_id=prepared.investigation_id,
        run_id=prepared.run_id,
        runtime_identity=RUNTIME_IDENTITY,
    )
    for raw in (_raw_args(0), _raw_args(1)):
        action = json.loads(raw)["actions"][0]
        handle = action.get("question_handle") or action.get("handle")
        assert re.fullmatch(r"Q\d+", handle)
    binding = harness._table.by_handle("Q1")
    assert binding is not None
    assert binding.kind.value == "question"


# ---------------------------------------------------------------------------
# (c) rejection-layer positions across the three schemes
# ---------------------------------------------------------------------------


def test_completed_is_illegal_in_all_three_schemes():
    # original V2: per-branch enum at parse
    with pytest.raises(ValidationError) as exc:
        UpdateQuestionActionV2(question_handle="Q1", to_status="completed")
    assert any(e["type"] == "enum" and e["loc"][-1] == "to_status"
               for e in exc.value.errors(include_url=True))
    # uniform proposal draft: parse accepts the string, the resolver
    # rejects fail-closed (no retry feedback at that layer)
    with pytest.raises(ProposalViolation) as pv:
        resolve_proposal_to_canonical(SupervisorIntegrationProposalV1(
            actions=[UpdateAction(target_handle="Q1",
                                  to_status="completed")]))
    assert pv.value.code == P_STATUS_NOT_IN_KIND_ENUM
    # strict+compact-typed: merged enum rejects at parse (retry-eligible)
    with pytest.raises(ValidationError):
        CompactTypedUpdateAction(target_handle="Q1", to_status="completed")


def test_rejection_layers_differ_between_schemes():
    bad_status = {
        "action_type": "update_question", "question_handle": "Q1",
        "to_status": "completed", "disposition": "not_supported",
    }
    # V2: PARSE-layer rejection
    with pytest.raises(ValidationError):
        SupervisorIntegrationDecisionV2.model_validate(
            {"actions": [bad_status]})
    # draft: parse ACCEPTS, resolver rejects (behind the retry boundary)
    proposal = SupervisorIntegrationProposalV1.model_validate({
        "actions": [{"action": "update", "target_handle": "Q1",
                     "to_status": "completed",
                     "disposition": "not_supported"}]})
    with pytest.raises(ProposalViolation) as pv:
        resolve_proposal_to_canonical(proposal)
    assert pv.value.code == P_STATUS_NOT_IN_KIND_ENUM
    # compact: PARSE-layer rejection again (retry feedback restored for
    # the status dimension) — validated against the frozen §8 compact
    # action, whose to_status carries the real merged enum
    with pytest.raises(ValidationError):
        CompactTypedUpdateAction.model_validate({
            "action": "update", "target_handle": "Q1",
            "to_status": "completed", "disposition": "not_supported"})


def test_envelope_does_not_accept_attempt1_abbreviated_names():
    """Correction guard for the RCA-2A.4 field-level report q7: the
    uniform envelope's operand field is target_handle (NOT 'handle'),
    so the attempt-1 abbreviated names are extra_forbidden under the
    envelope exactly as under V2."""
    attempt_1_action = json.loads(_raw_args(0))["actions"][0]
    assert "handle" in attempt_1_action and "status" in attempt_1_action
    with pytest.raises(ValidationError) as exc:
        SupervisorIntegrationProposalV1.model_validate(
            {"actions": [attempt_1_action]})
    fields = {e["loc"][-1]: e["type"]
              for e in exc.value.errors(include_url=True)
              if len(e.get("loc", ())) >= 2}
    assert fields.get("handle") == "extra_forbidden"
    assert fields.get("status") == "extra_forbidden"
    assert UpdateAction.model_fields["target_handle"].is_required()


def test_attempt1_disposition_violation_position():
    """The illegal disposition value moves BELOW the retry boundary in
    both proposal variants: V2 rejects it at parse (typed enum); the
    compact envelope parses it (untyped string) and the resolver rejects
    it only after to_status is legal."""
    legal_named = {
        "action_type": "update_question", "question_handle": "Q1",
        "to_status": "answered",
        "disposition": "no_evidence_found",
    }
    with pytest.raises(ValidationError) as exc:
        SupervisorIntegrationDecisionV2.model_validate(
            {"actions": [legal_named]})
    assert any(e["type"] == "enum" and e["loc"][-1] == "disposition"
               for e in exc.value.errors(include_url=True))

    proposal = SupervisorIntegrationProposalV1.model_validate({
        "actions": [{"action": "update", "target_handle": "Q1",
                     "to_status": "answered",
                     "disposition": "no_evidence_found"}]})
    with pytest.raises(ProposalViolation) as pv:
        resolve_proposal_to_canonical(proposal)
    assert pv.value.code == P_DISPOSITION_NOT_IN_ENUM


# ---------------------------------------------------------------------------
# (d) isolation guards
# ---------------------------------------------------------------------------


def test_production_never_imports_the_experimental_contract():
    services = PYTHON_SERVICE_ROOT / "httpserver" / "services"
    hits = [
        str(path)
        for path in services.rglob("*.py")
        if "integration_proposal_v1" in path.read_text(encoding="utf-8")
        or "SupervisorIntegrationProposalV1" in path.read_text(
            encoding="utf-8")
    ]
    assert hits == []
    probe = subprocess.run(
        [sys.executable, "-c",
         "import sys; import httpserver.services.investigation."
         "agent_supervisor as m; "
         "assert not any(k.startswith('benchmarks.contracts') "
         "for k in sys.modules); print('clean')"],
        cwd=str(PYTHON_SERVICE_ROOT), capture_output=True, text=True)
    assert probe.returncode == 0 and "clean" in probe.stdout


def test_frozen_2a4_store_replay_identity_unchanged():
    fixture = json.loads(
        (PARENT_DIR / "scratch" / "fixture-identity.json")
        .read_text(encoding="utf-8"))
    store = PARENT_DIR / "scratch" / "fixture-a" / "investigation.db"
    sha_before = hashlib.sha256(store.read_bytes()).hexdigest()
    harness = IsolatedIntegrationHarness(
        db_path=store,
        task_id=fixture["task_id"],
        investigation_id=fixture["investigation_id"],
        run_id=fixture["run_id"],
        runtime_identity={
            "baseline_commit": "3ad0dcf531975a4133f0e75b9d93f118967e4842",
            "harness": "rca2a5-deterministic-tests (read-only)",
            "specialist_result_kind": "SYNTHETIC_SPECIALIST_RESULT",
        },
    )
    contract = harness.isolated_input()
    assert contract["integration_context_hash"] == (
        fixture["integration_context_hash"])
    assert contract["reference_binding_table_hash"] == (
        fixture["reference_binding_table_hash"])
    assert contract["working_state_hash"] == fixture["working_state_hash"]
    assert hashlib.sha256(store.read_bytes()).hexdigest() == sha_before
