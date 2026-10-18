"""RCA-2A.2 §2 — V2 production-contract diagnostic readiness gate.

MUST pass before the StepFun real-model canary: the SAME containment +
sink path as the readiness test, but driven through the PRODUCTION
supervisor contract version (v2), so the failing output contract is the
actual production ``SupervisorIntegrationDecisionV2`` and every §2
observation is verified against it:

    V2 output-tool -> pydantic validation -> output retry exhaustion
    -> INTEGRATE containment -> diagnostic JSONL sink

Eight confirmations (directive §2): V2 schema hash; full validation
error paths; retry_attempts; tool_name; run_id == AgentRun;
supervisor_integration_failed persisted; no illegal integration commit;
redaction (input values / evidence bodies / keys absent).
"""

import json
from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

from tests.unit.investigation.test_agent_investigation_loop import (
    FakeCppBackend,
    OfflineSpecialistDispatcher,
    OfflineSupervisor,
    _build_env,
)
from httpserver.services.investigation.agent_failure_diagnostics import (
    JsonlFailureDiagnosticSink,
    schema_hash_of,
)
from httpserver.services.investigation.agent_integration_v2 import (
    SupervisorIntegrationDecisionV2,
)
from httpserver.services.investigation.agent_orchestrator import (
    AgentOrchestrator,
)

pytest.importorskip("pydantic_ai")
pytestmark = pytest.mark.migration_matrix


class _V2ViolatingSupervisor(OfflineSupervisor):
    """Production v2 integrate path with schema-violating output-tool args
    (extra field + invalid enum value — the two dominant historical error
    classes). The real SupervisorAgentFactory v2 agent performs the
    validation; the real orchestrator containment records the failure."""

    async def plan_v2(self, planning_context, plan_table):
        """v2 PLAN: delegate q-1 through the REAL v2 plan agent (handles
        taken from the frozen plan binding table)."""
        from httpserver.services.investigation.agent_integration_v2 import (
            PLAN_DECISION_VERSION_V2,
        )
        from httpserver.services.investigation.agent_supervisor import (
            SupervisorAgentFactory,
        )

        attention = next(
            b.handle for b in plan_table.bindings
            if b.handle.startswith("A"))
        question = next(
            b.handle for b in plan_table.bindings
            if b.handle.startswith("Q"))
        args = {
            "decision_version": PLAN_DECISION_VERSION_V2,
            "actions": [{
                "action_type": "delegate_investigation",
                "attention_handle": attention,
                "question_handle": question,
                "source_scope_id": "windows",
            }],
            "summary": "delegate the open charter question",
        }
        agent = SupervisorAgentFactory(
            model=TestModel(call_tools=[], custom_output_args=args)
        ).build_plan_agent_v2(planning_context, plan_table)
        result = await agent.run("plan")
        return result.output

    async def integrate_v2(self, context, table, state):
        from httpserver.services.investigation.agent_integration_v2 import (
            render_integration_context_v2,
        )
        from httpserver.services.investigation.agent_supervisor import (
            SupervisorAgentFactory,
        )

        projection = render_integration_context_v2(context, state, table)
        args = {
            "decision_version": "supervisor-integration-decision:v2",
            "integration_summary": "valid until the violations",
            "actions": [
                {
                    "action_type": "update_question",
                    "question_handle": "Q1",
                    "to_status": "answered",
                    "disposition": "supported",
                    # an invented field: EXTRA_FORBIDDEN_FIELD class
                    "tool_call_count": 10,
                },
                {
                    "action_type": "update_coverage",
                    "coverage_handle": "COV1",
                    # not a member of CoverageStatus: INVALID_ENUM class
                    "to_status": "answered",
                },
            ],
        }
        agent = SupervisorAgentFactory(
            model=TestModel(call_tools=[], custom_output_args=args)
        ).build_integration_agent_v2(projection)
        result = await agent.run("integrate")
        return result.output


@pytest.mark.asyncio
async def test_v2_production_contract_diagnostic_gate(tmp_path):
    diag_path = tmp_path / "diag" / "v2-failures.jsonl"
    sink = JsonlFailureDiagnosticSink(diag_path)
    repo, db, investigation_id = _build_env(tmp_path)
    orchestrator = AgentOrchestrator(
        FakeCppBackend(tmp_path),
        supervisor=_V2ViolatingSupervisor(),
        delegation_dispatcher=OfflineSpecialistDispatcher(repo, db),
        source_scope_provider=lambda task_id: ("windows",),
        failure_diagnostics_sink=sink,
        supervisor_contract_version="v2",
    )
    outcome = (await orchestrator.run_loop("task-A", investigation_id))[0]

    # containment held; no integration committed
    assert outcome.integration_status == "failed"
    revision_after = repo.get_latest_working_state(investigation_id).revision
    failed_run_id = repo.list_runs(investigation_id)[-1].run_id

    # §2.6: supervisor_integration_failed persisted
    events = [
        e for e in repo.list_trajectory(investigation_id)
        if e.event_type.value == "transition_decision_rejected"
        and "supervisor_failure" in (e.payload or {})
    ]
    assert events
    assert events[0].payload["supervisor_failure"] == (
        "supervisor_integration_failed")
    assert events[0].payload["underlying_code"] == (
        "model_output_retry_exhausted")

    # §2.1-5: sink entry fields, all against the PRODUCTION V2 contract
    lines = [json.loads(line) for line in
             diag_path.read_text(encoding="utf-8").splitlines() if line]
    entry = next(e for e in lines if e["stage"] == "SUPERVISOR_INTEGRATE")
    assert entry["schema_hash"] == schema_hash_of(
        SupervisorIntegrationDecisionV2)
    assert entry["exception_class"] == "UnexpectedModelBehavior"
    assert entry["normalized_failure_code"] == "model_output_retry_exhausted"
    assert entry["retry_attempts"] == 1
    assert entry["tool_name"] == "final_result"
    assert entry["context"]["run_id"] == failed_run_id
    details = entry["validation_error_details"]
    assert details, "field-level validation errors not observable"
    # field paths reach the exact offending fields (full union-member path)
    field_tails = {d["loc"][-1] for d in details if d["loc"]}
    assert "tool_call_count" in field_tails
    types = {d["type"] for d in details}
    assert "extra_forbidden" in types
    # pydantic v2 reports a wrong Literal status value as literal_error —
    # the observable form of the INVALID_ENUM class
    assert "literal_error" in types, sorted(types)

    # §2.7: no illegal integration commit — working state revision did not
    # advance beyond the delegation-admission baseline
    assert repo.get_latest_working_state(investigation_id).revision == (
        revision_after)

    # §2.8: redaction — no raw input values (10 / answered-on-coverage
    # payload) and no key material anywhere in the sink file
    raw = diag_path.read_text(encoding="utf-8")
    payload_blob = json.dumps(
        [d for e in lines for d in e.get("validation_error_details", [])])
    for forbidden in ('"input_value=10"', '"input": 10', "sk-", "Bearer "):
        assert forbidden not in payload_blob
    # the diagnosis carries TYPES and LOCATIONS, not model output text
    assert all(set(d.keys()) <= {"type", "loc"} for d in details)
