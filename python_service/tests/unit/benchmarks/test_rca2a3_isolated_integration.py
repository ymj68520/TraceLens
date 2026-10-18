"""RCA-2A.3 — isolated Supervisor INTEGRATE stage: deterministic tests.

Every test is offline (FunctionModel/TestModel only, zero provider
calls).  The post-delegation state is built through the REAL
orchestrator path (Path A, fixtures.py); the isolated stage harness
(Path B) recomposes the production INTEGRATE chain from durable facts
only.  Specialist results are SYNTHETIC_SPECIALIST_RESULTs driven
through the REAL executor/registry/completion transaction.

The parity test (§6 hard gate) proves Path B's model-visible input is
byte-identical to Path A's captured production input on the same frozen
store — same run_id, same binding table, same context hash — so no
identity normalization is needed at all.
"""

from __future__ import annotations

import json
import stat

import pytest

from benchmarks.isolated_integration.fixtures import (
    VISIBLE_EVIDENCE_KEY,
    prepare_post_delegation_store,
)
from benchmarks.isolated_integration.harness import (
    IsolatedIntegrationHarness,
    validate_isolated_input,
)

pytest.importorskip("pydantic_ai")
pytestmark = pytest.mark.migration_matrix

RUNTIME_IDENTITY = {
    "baseline_commit": "7d94dfe96568010d61e5006ab8a1d51580031796",
    "harness": "rca2a3-isolated-integration",
    "specialist_result_kind": "SYNTHETIC_SPECIALIST_RESULT",
}


def _harness(prepared) -> IsolatedIntegrationHarness:
    return IsolatedIntegrationHarness(
        db_path=prepared.db_path,
        task_id=prepared.task_id,
        investigation_id=prepared.investigation_id,
        run_id=prepared.run_id,
        runtime_identity=RUNTIME_IDENTITY,
    )


def _valid_decision_fn(messages, info):  # noqa: ANN001
    import json

    from pydantic_ai.messages import ModelResponse, ToolCallPart

    text = str(getattr(info, "instructions", "") or "")
    marker = "typed actions only.\n\n"
    projection = json.loads(text.split(marker, 1)[1].split("\n\nRules:", 1)[0])
    question = next(
        q["handle"] for q in projection["questions"]
        if q["status"] in ("open", "in_progress")
    )
    args = {"actions": [{
        "action_type": "update_question",
        "question_handle": question,
        "to_status": "in_progress",
        "investigated_summary": (
            "honest stage integration: question advanced to in_progress"),
    }]}
    return ModelResponse(parts=[ToolCallPart(
        info.output_tools[0].name, json.dumps(args))])


def _head(repo, investigation_id):
    return repo.get_latest_working_state(investigation_id)


# ---------------------------------------------------------------------------
# §6 — production input parity gate (the hard gate)
# ---------------------------------------------------------------------------


async def test_integration_input_parity_path_a_vs_path_b(tmp_path):
    prepared = await prepare_post_delegation_store(
        tmp_path, with_evidence=True)
    harness = _harness(prepared)
    captured_b = await harness.capture_model_visible_input()
    a, b = prepared.capture, captured_b
    # strict identity on every stable field — same frozen store means
    # even the identity fields match, so NO normalization is applied
    assert a["instructions"] == b["instructions"]
    assert a["output_tool_schemas"] == b["output_tool_schemas"]
    assert a["output_tool_names"] == b["output_tool_names"]
    assert a["model_settings"] == b["model_settings"]
    assert a["projection"] == b["projection"]
    projection = b["projection"]
    # availability + handle domains + source results are inside the
    # projection the instructions embed
    assert projection["available_actions"]
    assert projection["handle_kinds"]
    assert any(h.startswith("D") for h in projection["handle_kinds"]), (
        "fresh specialist results must be bound as D-handles")
    assert any(h.startswith("E") for h in projection["handle_kinds"]), (
        "fixture B evidence must be bound as E-handles")
    # contract validates
    contract = harness.isolated_input()
    assert validate_isolated_input(contract) == []
    assert contract["fresh_delegation_result_ids"]
    assert contract["fresh_delegation_result_hashes"]
    assert contract["evidence_snapshot_refs"] == [VISIBLE_EVIDENCE_KEY]


async def test_parity_also_holds_on_no_evidence_fixture(tmp_path):
    prepared = await prepare_post_delegation_store(
        tmp_path, with_evidence=False)
    harness = _harness(prepared)
    captured_b = await harness.capture_model_visible_input()
    assert prepared.capture["instructions"] == captured_b["instructions"]
    assert prepared.capture["projection"] == captured_b["projection"]
    contract = harness.isolated_input()
    assert contract["evidence_snapshot_refs"] == []


# ---------------------------------------------------------------------------
# §7 — deterministic stage tests
# ---------------------------------------------------------------------------


async def test_t1_valid_integration_decision_commits(tmp_path):
    prepared = await prepare_post_delegation_store(tmp_path, with_evidence=True)
    harness = _harness(prepared)
    revision_before = _head(prepared.repo, prepared.investigation_id).revision

    result = await harness.run_stage(_valid_decision_fn)

    names = [s.name for s in result.steps]
    assert names == ["model_output_received", "pydantic_validation",
                     "canonical_resolution", "decision_validator",
                     "transition_validation", "integration_commit"]
    assert all(s.ok for s in result.steps)
    assert result.committed
    head = _head(prepared.repo, prepared.investigation_id)
    assert head.revision == revision_before + 1
    # delegation consumed (integrated) exactly as the normal path does
    delegations = prepared.repo.list_delegations(prepared.run_id)
    assert delegations[0].integrated_at is not None
    # lifecycle: the bound run was already terminal (Path A containment);
    # the stage created no run and exercised no finalization
    snapshot = harness.store_lifecycle_snapshot()
    assert snapshot["non_terminal_runs"] == []
    assert snapshot["finalization_status"] == "NOT_EXERCISED"


async def test_t2_invalid_union_fails_closed_observable(tmp_path):
    prepared = await prepare_post_delegation_store(tmp_path, with_evidence=True)
    harness = _harness(prepared)
    revision_before = _head(prepared.repo, prepared.investigation_id).revision

    def model_fn(messages, info):  # noqa: ANN001
        import json

        from pydantic_ai.messages import ModelResponse, ToolCallPart

        args = {"actions": [{
            "action_type": "frobnicate", "question_handle": "Q1"}]}
        return ModelResponse(parts=[ToolCallPart(
            info.output_tools[0].name, json.dumps(args))])

    result = await harness.run_stage(model_fn)
    assert result.exception_class == "UnexpectedModelBehavior"
    assert not result.committed
    assert not any(s.ok and s.name == "pydantic_validation"
                   for s in result.steps)
    # ONE diagnostics entry for the ONE failed payload (retries are not
    # independent model failures)
    assert len(result.diagnostics_emitted) == 1
    entry = result.diagnostics_emitted[0]
    assert entry["normalized_failure_code"] == "model_output_retry_exhausted"
    assert entry["retry_attempts"] == 1
    # state unchanged
    assert _head(prepared.repo, prepared.investigation_id).revision == (
        revision_before)


async def test_t3_extra_forbidden_field_rejected_and_sanitized(tmp_path):
    prepared = await prepare_post_delegation_store(tmp_path, with_evidence=True)
    harness = _harness(prepared)

    def model_fn(messages, info):  # noqa: ANN001
        import json

        from pydantic_ai.messages import ModelResponse, ToolCallPart

        text = str(getattr(info, "instructions", "") or "")
        projection = json.loads(
            text.split("typed actions only.\n\n", 1)[1].split(
                "\n\nRules:", 1)[0])
        question = projection["questions"][0]["handle"]
        args = {"actions": [{
            "action_type": "update_question",
            "question_handle": question,
            "to_status": "in_progress",
            "tool_call_count": 9,  # server-owned field: extra_forbidden
        }]}
        return ModelResponse(parts=[ToolCallPart(
            info.output_tools[0].name, json.dumps(args))])

    result = await harness.run_stage(model_fn)
    assert result.exception_class == "UnexpectedModelBehavior"
    assert not result.committed
    entry = result.diagnostics_emitted[0]
    details = entry["validation_error_details"]
    assert any(
        d["type"] == "extra_forbidden" and d["loc"][-1] == "tool_call_count"
        for d in details
    )
    # sanitized: the offending INPUT VALUE never appears
    assert "9" not in json.dumps(details)
    assert all(set(d.keys()) <= {"type", "loc"} for d in details)


async def test_t4_invalid_enum_rejected_within_frozen_retry_budget(tmp_path):
    prepared = await prepare_post_delegation_store(tmp_path, with_evidence=True)
    harness = _harness(prepared)
    attempts = {"n": 0}

    def model_fn(messages, info):  # noqa: ANN001
        import json

        from pydantic_ai.messages import ModelResponse, ToolCallPart

        attempts["n"] += 1
        text = str(getattr(info, "instructions", "") or "")
        projection = json.loads(
            text.split("typed actions only.\n\n", 1)[1].split(
                "\n\nRules:", 1)[0])
        question = projection["questions"][0]["handle"]
        args = {"actions": [{
            "action_type": "update_question",
            "question_handle": question,
            "to_status": "vacuously_closed",  # invalid enum value
        }]}
        return ModelResponse(parts=[ToolCallPart(
            info.output_tools[0].name, json.dumps(args))])

    result = await harness.run_stage(model_fn)
    assert result.exception_class == "UnexpectedModelBehavior"
    assert not result.committed
    # frozen retry budget: exactly one in-band retry, no auto-correction
    assert attempts["n"] == 2
    assert result.diagnostics_emitted[0]["retry_attempts"] == 1


async def test_t5_handle_layers_each_own_their_validation(tmp_path):
    prepared = await prepare_post_delegation_store(tmp_path, with_evidence=True)
    harness = _harness(prepared)
    table_hash_before = harness.isolated_input()[
        "reference_binding_table_hash"]

    # (a) pattern-valid but UNKNOWN handle -> the RESOLVER fails closed
    def unknown_handle_fn(messages, info):  # noqa: ANN001
        import json

        from pydantic_ai.messages import ModelResponse, ToolCallPart

        args = {"actions": [{
            "action_type": "update_question",
            "question_handle": "Q99",
            "to_status": "in_progress",
        }]}
        return ModelResponse(parts=[ToolCallPart(
            info.output_tools[0].name, json.dumps(args))])

    result = await harness.run_stage(unknown_handle_fn)
    assert not result.committed
    assert "HANDLE_UNKNOWN" in result.resolution_violations

    # (b) WRONG-KIND handle -> the SCHEMA (pattern) rejects first: no
    # evidence handle can occupy a question slot
    def wrong_kind_fn(messages, info):  # noqa: ANN001
        import json

        from pydantic_ai.messages import ModelResponse, ToolCallPart

        args = {"actions": [{
            "action_type": "update_question",
            "question_handle": "E1",
            "to_status": "in_progress",
        }]}
        return ModelResponse(parts=[ToolCallPart(
            info.output_tools[0].name, json.dumps(args))])

    result_b = await harness.run_stage(wrong_kind_fn)
    assert result_b.exception_class == "UnexpectedModelBehavior"
    assert not result_b.committed
    # no evidence identity drift: the binding table is immutable
    assert harness.isolated_input()["reference_binding_table_hash"] == (
        table_hash_before)


def _moved_state_json(prepared):
    from httpserver.services.investigation.agent_working_state import (
        working_state_from_json,
        working_state_to_json,
    )

    latest = prepared.repo.get_latest_working_state(prepared.investigation_id)
    state = working_state_from_json(
        prepared.task_id, prepared.investigation_id, latest.state)
    moved = state.model_copy(update={"objective": state.objective + " !"})
    dumped = working_state_to_json(moved)
    return json.loads(dumped) if isinstance(dumped, str) else dumped


async def test_t6_stale_inputs_refused(tmp_path):
    from httpserver.services.investigation.agent_runtime import (
        AgentRuntimeConflictError,
    )

    # (a) state revision moved after the context was frozen
    prepared = await prepare_post_delegation_store(tmp_path, with_evidence=True)
    harness = _harness(prepared)
    inv = prepared.investigation_id
    latest = _head(prepared.repo, inv)
    prepared.repo.commit_working_state(
        inv,
        _moved_state_json(prepared),
        expected_revision=latest.revision,
        operation_key="rca2a3-stale-mover",
    )
    raised = None
    try:
        await harness.run_stage(_valid_decision_fn)
    except AgentRuntimeConflictError as exc:
        raised = exc
    assert raised is not None, "stale revision must be refused"
    assert _head(prepared.repo, inv).revision == latest.revision + 1, (
        "no partial commit may land on top of the moved head")

    # (b) tampered source result hash -> the commit revalidation refuses
    prepared_b = await prepare_post_delegation_store(
        tmp_path / "b", with_evidence=True)
    harness_b = _harness(prepared_b)
    tampered = harness_b._fresh_envelopes[0].model_copy(
        update={"result_hash": "deadbeef"})
    harness_b._fresh_envelopes = (tampered,)
    raised_b = None
    try:
        await harness_b.run_stage(_valid_decision_fn)
    except AgentRuntimeConflictError as exc:
        raised_b = exc
    assert raised_b is not None, "hash mismatch must be refused"
    assert not prepared_b.repo.list_delegations(
        prepared_b.run_id)[0].integrated_at


async def test_t7_mixed_actions_all_or_nothing(tmp_path):
    prepared = await prepare_post_delegation_store(tmp_path, with_evidence=True)
    harness = _harness(prepared)
    refs_before = harness.isolated_input()["evidence_snapshot_refs"]
    snapshot_before = prepared.repo._repo.get_snapshot(VISIBLE_EVIDENCE_KEY)

    def model_fn(messages, info):  # noqa: ANN001
        import json

        from pydantic_ai.messages import ModelResponse, ToolCallPart

        text = str(getattr(info, "instructions", "") or "")
        projection = json.loads(
            text.split("typed actions only.\n\n", 1)[1].split(
                "\n\nRules:", 1)[0])
        question = projection["questions"][0]["handle"]
        args = {"actions": [
            {  # legal
                "action_type": "update_question",
                "question_handle": question,
                "to_status": "in_progress",
            },
            {  # illegal: unknown handle
                "action_type": "update_evidence_relevance",
                "evidence_handle": "E99",
                "to_status": "irrelevant",
            },
        ]}
        return ModelResponse(parts=[ToolCallPart(
            info.output_tools[0].name, json.dumps(args))])

    result = await harness.run_stage(model_fn)
    assert not result.committed
    assert "HANDLE_UNKNOWN" in result.resolution_violations
    # nothing partially landed: integration, evidence integrity intact
    delegations = prepared.repo.list_delegations(prepared.run_id)
    assert delegations[0].integrated_at is None
    snapshot_after = prepared.repo._repo.get_snapshot(VISIBLE_EVIDENCE_KEY)
    assert snapshot_after.payload == snapshot_before.payload
    assert snapshot_after.captured_at == snapshot_before.captured_at
    assert harness.isolated_input()["evidence_snapshot_refs"] == refs_before


async def test_t8_provider_failures_classified_not_schema(tmp_path):
    import httpx
    from openai import APIConnectionError, APITimeoutError

    prepared = await prepare_post_delegation_store(tmp_path, with_evidence=True)
    harness = _harness(prepared)

    def timeout_fn(messages, info):  # noqa: ANN001
        raise APITimeoutError(request=httpx.Request(
            "POST", "http://127.0.0.1:9/v1/chat/completions"))

    result = await harness.run_stage(timeout_fn)
    assert result.exception_class == "APITimeoutError"
    assert not result.committed
    code = result.diagnostics_emitted[0]["normalized_failure_code"]
    assert code == "provider_request_timeout"
    assert not code.startswith("model_output_")

    def connection_fn(messages, info):  # noqa: ANN001
        raise APIConnectionError(request=httpx.Request(
            "POST", "http://127.0.0.1:9/v1/chat/completions"))

    result_b = await harness.run_stage(connection_fn)
    code_b = result_b.diagnostics_emitted[0]["normalized_failure_code"]
    assert code_b == "provider_connection_error"
    assert not code_b.startswith("model_output_")


async def test_t9_diagnostic_sink_on_harness_path(tmp_path):
    from httpserver.services.investigation.agent_failure_diagnostics import (
        JsonlFailureDiagnosticSink,
        schema_hash_of,
    )
    from httpserver.services.investigation.agent_integration_v2 import (
        SupervisorIntegrationDecisionV2,
    )

    prepared = await prepare_post_delegation_store(tmp_path, with_evidence=True)
    sink_path = tmp_path / "sink" / "integrate-failures.jsonl"
    sink = JsonlFailureDiagnosticSink(sink_path)
    harness = _harness(prepared)

    def model_fn(messages, info):  # noqa: ANN001
        import json

        from pydantic_ai.messages import ModelResponse, ToolCallPart

        args = {"actions": [{"action_type": "frobnicate"}]}
        return ModelResponse(parts=[ToolCallPart(
            info.output_tools[0].name, json.dumps(args))])

    result = await harness.run_stage(model_fn, diagnostic_sink=sink)
    assert result.diagnostics_emitted
    lines = [json.loads(line) for line in
             sink_path.read_text().splitlines() if line.strip()]
    assert lines, "sink must have persisted the entry"
    entry = lines[-1]
    assert entry["stage"] == "SUPERVISOR_INTEGRATE"
    assert entry["context"] == {"run_id": prepared.run_id}
    assert entry["schema_hash"] == schema_hash_of(
        SupervisorIntegrationDecisionV2)
    assert entry["tool_name"] == "final_result"
    assert entry["retry_attempts"] == 1
    assert entry["validation_error_details"]
    assert stat.S_IMODE(sink_path.stat().st_mode) == 0o600


async def test_t10_stage_lifecycle_ownership(tmp_path):
    prepared = await prepare_post_delegation_store(tmp_path, with_evidence=True)
    harness = _harness(prepared)
    delegation_before = prepared.repo.list_delegations(prepared.run_id)[0]
    result_hash_before = prepared.repo.get_delegation_result(
        delegation_before.delegation_id).result_hash

    result = await harness.run_stage(_valid_decision_fn)
    assert result.committed

    snapshot = harness.store_lifecycle_snapshot()
    # no orphaned/owned running AgentRun: the bound run was terminal
    # before the stage (Path A containment) and stays terminal
    assert snapshot["non_terminal_runs"] == []
    assert all(r["status"] in ("failed", "completed", "cancelled")
               for r in snapshot["settled_agent_run_status"])
    # the stage explicitly owns no finalization
    assert snapshot["finalization_status"] == "NOT_EXERCISED"
    assert result.lifecycle["agent_run_created"] is False
    assert result.lifecycle["finalization"] == "NOT_EXERCISED"
    # no specialist re-execution: the stored result is byte-identical
    delegation_after = prepared.repo.list_delegations(prepared.run_id)[0]
    result_hash_after = prepared.repo.get_delegation_result(
        delegation_after.delegation_id).result_hash
    assert result_hash_after == result_hash_before


async def test_stage_input_contract_rejects_incomplete(tmp_path):
    prepared = await prepare_post_delegation_store(tmp_path, with_evidence=True)
    harness = _harness(prepared)
    incomplete = {k: v for k, v in harness.isolated_input().items()
                  if k != "run_id"}
    violations = validate_isolated_input(incomplete)
    assert "missing field: run_id" in violations
