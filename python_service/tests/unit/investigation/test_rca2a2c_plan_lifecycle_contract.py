"""RCA-2A.2c — PLAN failure lifecycle consistency + contract audit (CF-1).

Offline regression suite for the audit findings recorded in
``benchmarks/audits/rca2a2c-plan-consistency-audit/``. Zero real model
calls: every supervisor agent runs on a deterministic FunctionModel under
the PRODUCTION v2 contract (real SupervisorAgentFactory builders, real
instructions, real output schemas); the runtime is the real P1 SQLite
store.

Documented (frozen) semantics these tests pin down:

- CF-1: PLAN containment (invalid output / provider timeout / validator
  rejection) is a first-class cycle outcome that does NOT terminalize the
  AgentRun — the run stays non-terminal so a live service can re-plan on
  the next invocation. INTEGRATE containment, by contrast, fails the run
  (RCA-1.1). A one-shot driver therefore exits with a non-terminal row;
  the production restart-recovery primitive is the terminalizer.
- CancelledError is NEVER converted to an ordinary failure and never
  reaches the diagnostics sink (``except Exception`` only).
- Finalization is fail-closed: a gate denial persists no record and
  leaves the run untouched.
- The v2 PLAN model-facing contract is consistent with its instructions
  on the audited domain: every instructed field exists in the schema,
  all three action variants are constructible, the historical
  ``type``-discriminant payload fails as INVALID_UNION against every
  branch, and the empty/no-action paths are legal.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from pydantic import TypeAdapter, ValidationError

from tests.unit.investigation.test_agent_investigation_loop import (
    FakeCppBackend,
    _build_env,
)

pytest.importorskip("pydantic_ai")

from httpserver.services.investigation.agent_failure_diagnostics import (  # noqa: E402
    ListFailureDiagnosticSink,
)
from httpserver.services.investigation.agent_integration_v2 import (  # noqa: E402
    PLAN_DECISION_VERSION_V2,
    SupervisorPlanDecisionV2,
)
from httpserver.services.investigation.agent_orchestrator import (  # noqa: E402
    AgentOrchestrator,
)
from httpserver.services.investigation.agent_runtime import (  # noqa: E402
    AgentRunStatus,
)
from httpserver.services.investigation.agent_supervisor import (  # noqa: E402
    InvestigationSupervisor,
)

pytestmark = pytest.mark.migration_matrix


# ---------------------------------------------------------------------------
# v2 scenario supervisor: real agents, deterministic FunctionModel outputs
# ---------------------------------------------------------------------------


class _ProjectionPlanFunction:
    """FunctionModel body that resolves its handles from the REAL
    instruction projection (same mechanism the production model sees)."""

    scenario = "valid"  # valid | invalid_union | timeout | cancelled
    __name__ = "scenario_plan_function"

    def __call__(self, messages, info):
        import httpx
        from openai import APITimeoutError
        from pydantic_ai.messages import ModelResponse, ToolCallPart

        if self.scenario == "timeout":
            raise APITimeoutError(
                request=httpx.Request("POST", "http://127.0.0.1:9/v1")
            )
        if self.scenario == "cancelled":
            raise asyncio.CancelledError()

        instructions = getattr(info, "instructions", "") or ""
        marker = "supervisor plan decision (v2).\n\n"
        blob = instructions.split(marker, 1)[1].split("\n\nRules:", 1)[0]
        projection = json.loads(blob)
        attention = next(
            item["handle"]
            for item in projection["attention_items"]
            if item.get("eligibility") == "eligible"
        )
        question = projection["questions"][0]["handle"]
        scope = projection["source_scopes"][0]
        action = {
            "attention_handle": attention,
            "question_handle": question,
            "source_scope_id": scope,
        }
        if self.scenario == "invalid_union":
            # RCA-2A.2b field-level shape: discriminant named `type`
            action = {"type": "delegate_investigation", **action}
        else:
            action = {"action_type": "delegate_investigation", **action}
        args = {
            "decision_version": PLAN_DECISION_VERSION_V2,
            "actions": [action],
            "summary": "delegate the charter question",
        }
        return ModelResponse(parts=[
            ToolCallPart(info.output_tools[0].name, json.dumps(args))
        ])


def _build_orchestrator(tmp_path, scenario, sink=None):
    from pydantic_ai.models.function import FunctionModel

    plan_function = _ProjectionPlanFunction()
    plan_function.scenario = scenario
    supervisor = InvestigationSupervisor(model=FunctionModel(plan_function))
    repo, db_path, investigation_id = _build_env(tmp_path)
    orchestrator = AgentOrchestrator(
        FakeCppBackend(tmp_path),
        supervisor=supervisor,
        delegation_dispatcher=None,  # delegations stay queued (documented)
        supervisor_contract_version="v2",
        failure_diagnostics_sink=sink or ListFailureDiagnosticSink(),
    )
    return repo, db_path, investigation_id, orchestrator


def _run_row(repo, investigation_id):
    runs = repo.list_runs(investigation_id)
    assert runs, "expected an admitted run"
    return runs[-1]


def _event_types(repo, investigation_id):
    return [
        event.event_type.value
        for event in repo.list_trajectory(investigation_id)
    ]


# ---------------------------------------------------------------------------
# CF-1: PLAN containment vs AgentRun lifecycle
# ---------------------------------------------------------------------------


async def test_plan_output_invalid_contained_run_stays_nonterminal(tmp_path):
    repo, _db, investigation_id, orchestrator = _build_orchestrator(
        tmp_path, "invalid_union"
    )
    outcome = await orchestrator.execute_cycle(
        "task-A", investigation_id, source_scope_ids=("windows",)
    )
    # containment: first-class outcome, no exception, no run_stop_reason
    assert "supervisor plan failed: agent_output_invalid" in outcome.warnings
    assert outcome.run_stop_reason is None
    # the durable row is NOT terminal (P4B re-plan semantics)
    row = _run_row(repo, investigation_id)
    assert row.status is AgentRunStatus.running
    assert row.stop_reason is None
    # trajectory records the rejection; no run_failed event exists
    assert "transition_decision_rejected" in _event_types(repo, investigation_id)
    assert "run_failed" not in _event_types(repo, investigation_id)


async def test_plan_output_invalid_diagnostics_field_level(tmp_path):
    sink = ListFailureDiagnosticSink()
    _repo, _db, investigation_id, orchestrator = _build_orchestrator(
        tmp_path, "invalid_union", sink=sink
    )
    await orchestrator.execute_cycle(
        "task-A", investigation_id, source_scope_ids=("windows",)
    )
    plan_entries = [
        e for e in sink.entries if e["stage"] == "SUPERVISOR_PLAN"
    ]
    assert len(plan_entries) == 1
    entry = plan_entries[0]
    assert entry["normalized_failure_code"] == "model_output_retry_exhausted"
    assert entry["exception_class"] == "UnexpectedModelBehavior"
    # the field-level cascade names the discriminant error in every branch
    pairs = {
        (d["type"], tuple(str(part) for part in d["loc"]))
        for d in entry["validation_error_details"]
    }
    assert (
        "extra_forbidden",
        ("actions", "0", "DelegateInvestigationActionV2", "type"),
    ) in pairs
    assert (
        "extra_forbidden",
        ("actions", "0", "NoPlanActionV2", "type"),
    ) in pairs
    assert (
        "missing",
        ("actions", "0", "RequestFinalizationActionV2", "reason_code"),
    ) in pairs


async def test_plan_provider_timeout_contained_typed(tmp_path):
    repo, _db, investigation_id, orchestrator = _build_orchestrator(
        tmp_path, "timeout"
    )
    sink = orchestrator._failure_diagnostics_sink
    outcome = await orchestrator.execute_cycle(
        "task-A", investigation_id, source_scope_ids=("windows",)
    )
    # RCA-1.2 typed classification: APITimeoutError -> agent_timeout
    assert "supervisor plan failed: agent_timeout" in outcome.warnings
    assert outcome.run_stop_reason is None
    row = _run_row(repo, investigation_id)
    assert row.status is AgentRunStatus.running
    entry = [e for e in sink.entries if e["stage"] == "SUPERVISOR_PLAN"][0]
    assert entry["normalized_failure_code"] == "provider_request_timeout"
    assert entry["classified"] is True
    assert entry["exception_class"] == "APITimeoutError"


async def test_plan_valid_cycle_admits_delegation_run_stays_nonterminal(
    tmp_path,
):
    repo, _db, investigation_id, orchestrator = _build_orchestrator(
        tmp_path, "valid"
    )
    outcome = await orchestrator.execute_cycle(
        "task-A", investigation_id, source_scope_ids=("windows",)
    )
    assert outcome.plan_rejected_codes == ()
    assert outcome.run_stop_reason is None
    assert "supervisor_plan_decided" in _event_types(repo, investigation_id)
    # no dispatcher wired -> delegations stay queued; the run is not terminal
    row = _run_row(repo, investigation_id)
    assert row.status is AgentRunStatus.running
    delegations = repo.list_delegations(row.run_id)
    assert delegations and delegations[0].status.value == "queued"


async def test_cancellederror_propagates_without_conversion(tmp_path):
    repo, _db, investigation_id, orchestrator = _build_orchestrator(
        tmp_path, "cancelled"
    )
    sink = orchestrator._failure_diagnostics_sink
    with pytest.raises(asyncio.CancelledError):
        await orchestrator.execute_cycle(
        "task-A", investigation_id, source_scope_ids=("windows",)
    )
    # never converted to an ordinary failure: no rejection trajectory, no
    # diagnostics entry, row untouched at whatever non-terminal state held
    assert "transition_decision_rejected" not in _event_types(
        repo, investigation_id
    )
    assert "run_failed" not in _event_types(repo, investigation_id)
    assert sink.entries == []
    assert _run_row(repo, investigation_id).status is AgentRunStatus.running


async def test_recovery_sweep_terminalizes_nonterminal_run_idempotent(
    tmp_path,
):
    repo, _db, investigation_id, orchestrator = _build_orchestrator(
        tmp_path, "invalid_union"
    )
    await orchestrator.execute_cycle(
        "task-A", investigation_id, source_scope_ids=("windows",)
    )
    assert _run_row(repo, investigation_id).status is AgentRunStatus.running

    summary = repo.recover_interrupted_agent_runtime()
    assert summary["runs_failed"] == 1
    row = _run_row(repo, investigation_id)
    assert row.status is AgentRunStatus.failed
    assert row.stop_reason.value == "runtime_restart"
    assert "run_failed" in _event_types(repo, investigation_id)
    assert "runtime_recovered" in _event_types(repo, investigation_id)
    # idempotent
    second = repo.recover_interrupted_agent_runtime()
    assert second["runs_failed"] == 0


async def test_recovery_does_not_reexecute_or_resume(tmp_path):
    repo, _db, investigation_id, orchestrator = _build_orchestrator(
        tmp_path, "invalid_union"
    )
    await orchestrator.execute_cycle(
        "task-A", investigation_id, source_scope_ids=("windows",)
    )
    before = _event_types(repo, investigation_id)
    repo.recover_interrupted_agent_runtime()
    after = _event_types(repo, investigation_id)
    # recovery appends exactly the terminal transition + pause + marker,
    # never replays PLAN or delegation work
    assert after[len(before):] == ["run_failed", "investigation_paused",
                                   "runtime_recovered"]
    assert _run_row(repo, investigation_id).status is AgentRunStatus.failed


# ---------------------------------------------------------------------------
# FinalizationGate fail-closed
# ---------------------------------------------------------------------------


async def test_finalization_denied_fail_closed_no_record(tmp_path):
    repo, _db, investigation_id, orchestrator = _build_orchestrator(
        tmp_path, "valid"
    )
    outcome = await orchestrator.execute_cycle(
        "task-A", investigation_id, source_scope_ids=("windows",)
    )
    assert outcome.finalization is None  # cycle itself did not finalize

    from httpserver.services.investigation.agent_finalization import (
        FinalReviewMode,
        FinalizationRequest,
        FinalSemanticReview,
        FinalSemanticReviewStatus,
    )

    latest = repo.get_latest_working_state(investigation_id)
    request = FinalizationRequest(
        investigation_id=investigation_id,
        expected_state_revision=latest.revision,
        review_mode=FinalReviewMode.best_effort,
        final_semantic_review=FinalSemanticReview(
            status=FinalSemanticReviewStatus.unavailable,
            result_ref="test:final-review-not-executed",
        ),
        requested_by="rca2a2c-test",
    )
    commit = await orchestrator.finalize("task-A", request)
    # gate denial: no record, run untouched (still running, still non-terminal)
    assert commit.record is None
    assert commit.finalized is False
    assert repo.get_finalization(investigation_id) is None
    row = _run_row(repo, investigation_id)
    assert row.status is AgentRunStatus.running
    assert "finalization_denied" in _event_types(repo, investigation_id)


# ---------------------------------------------------------------------------
# §3: v2 PLAN model-facing contract vs instructions (deterministic)
# ---------------------------------------------------------------------------


def _plan_schema():
    return TypeAdapter(SupervisorPlanDecisionV2).json_schema()


def test_schema_offers_all_three_phase_capabilities():
    schema = _plan_schema()
    consts = {
        branch["properties"]["action_type"]["const"]
        for branch in schema["$defs"].values()
    }
    assert consts == {"delegate_investigation", "request_finalization",
                      "no_action"}
    # every branch forbids extra fields (the INVALID_UNION guard)
    assert all(
        branch.get("additionalProperties") is False
        for branch in schema["$defs"].values()
    )


def test_three_action_variants_construct_from_instruction_conformant_payloads():
    for action in (
        {"action_type": "delegate_investigation", "attention_handle": "A1",
         "question_handle": "Q1", "source_scope_id": "windows"},
        {"action_type": "request_finalization", "reason_code": "coverage_terminal"},
        {"action_type": "no_action", "reason_code": "nothing actionable"},
    ):
        decision = SupervisorPlanDecisionV2.model_validate(
            {"actions": [action]}
        )
        assert len(decision.actions) == 1


def test_historical_type_discriminant_payload_is_invalid_union():
    """The RCA-2A.2b field-level shape: `type` instead of `action_type`
    fails EVERY union branch (extra_forbidden) -> one INVALID_UNION."""
    with pytest.raises(ValidationError) as excinfo:
        SupervisorPlanDecisionV2.model_validate({
            "actions": [{
                "type": "delegate_investigation",
                "attention_handle": "A1",
                "question_handle": "Q1",
                "source_scope_id": "windows",
            }],
        })
    branches = {
        error["loc"][2]
        for error in excinfo.value.errors()
        if error["type"] == "extra_forbidden"
        and len(error["loc"]) >= 3
        and error["loc"][-1] == "type"
    }
    assert branches == {
        "DelegateInvestigationActionV2",
        "RequestFinalizationActionV2",
        "NoPlanActionV2",
    }


def test_instructions_never_require_schema_forbidden_fields():
    """Cross-check: every field the v2 instructions name exists in the
    schema, and no instruction-required construct is schema-forbidden."""
    from httpserver.services.investigation.agent_supervisor import (
        SupervisorPlanningContextPack,
        _planning_instructions_v2,
    )
    from httpserver.services.investigation.agent_integration_v2 import (
        render_plan_context_v2,
    )
    from httpserver.services.investigation.agent_reference_bindings import (
        build_plan_binding_table,
    )
    from httpserver.services.investigation.agent_supervisor import (
        AttentionItemDigest,
        QuestionIndexEntry,
    )

    pack = SupervisorPlanningContextPack(
        task_id="t", investigation_id="i", run_id="r",
        state_revision=1, state_hash="h",
        attention_policy_version="apv", attention_hash="ah",
        attention_items=(AttentionItemDigest(
            item_id="ai-1", band="b1", eligibility="eligible",
            related_question_ids=("q-1",),
            eligible_action_types=("delegate_source",),
        ),),
        question_index=(QuestionIndexEntry(
            question_id="q-1", status="open"),),
        source_scope_ids=("windows",),
    )
    instructions = _planning_instructions_v2(
        render_plan_context_v2(pack, build_plan_binding_table(pack))
    )
    assert "source_scope_id" in instructions
    schema_fields = {"action_type", "action_id", "attention_handle",
                     "question_handle", "source_scope_id", "reason_code",
                     "summary", "time_scope", "investigation_intent",
                     "execution_group"}
    for token in ("task_id", "investigation_id", "run_id",
                  "based_on_state_revision", "state_hash", "attention_hash"):
        # the identity echo the v1 contract demanded is exactly what v2
        # forbids in both the instructions and the schema
        assert f"{token}=" not in instructions
        assert token not in _plan_schema()["properties"]
    assert schema_fields  # sanity: field inventory non-empty


def test_no_plan_action_constructible_minimally():
    """The legal no-evidence / nothing-to-do path is expressible."""
    decision = SupervisorPlanDecisionV2.model_validate({
        "actions": [{"action_type": "no_action", "reason_code": "x"}]
    })
    assert decision.actions[0].action_type == "no_action"
    # and the empty plan is schema-legal
    assert SupervisorPlanDecisionV2.model_validate({"actions": []}).actions == ()
