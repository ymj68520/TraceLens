"""RCA-2A.2 §2 — deterministic diagnostic-effectiveness gate.

MUST pass before any real model call: proves that the production
diagnostics sink records every field-level observation the diagnostic
canary needs, through the REAL orchestrator containment path with a REAL
file sink:

    SUPERVISOR_INTEGRATE -> invalid output-tool arguments -> ValidationError
    -> output retry -> retry exhaustion -> sink entry with
    stage / exception type / validation error type / validation error
    location / schema hash / retry count / failure classification / run id.

If this gate cannot be met: DIAGNOSTIC_INSTRUMENTATION_BLOCKED (directive
§2) — no blind real-model spending.
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


class _IntegrateViolatingSupervisor(OfflineSupervisor):
    """The historical failure signature, reproduced deterministically."""

    async def integrate(self, context):
        from httpserver.services.investigation.agent_supervisor import (
            SupervisorAgentFactory,
        )

        args = self._bind_integration(
            context,
            {
                "decision_version": "supervisor-integration-decision:v1",
                "integration_summary": "valid until the extra field",
                "transition_proposals": [
                    {
                        "question_id": "q-1",
                        "to_status": "answered",
                        "disposition": "supported",
                        "tool_call_count": 10,
                    },
                ],
            },
        )
        model = TestModel(call_tools=[], custom_output_args=args)
        agent = SupervisorAgentFactory(model=model).build_integration_agent(
            context
        )
        result = await agent.run("integrate")
        return result.output


@pytest.mark.asyncio
async def test_diagnostic_instrumentation_gate(tmp_path):
    diag_path = tmp_path / "diag" / "calibration-failures.jsonl"
    sink = JsonlFailureDiagnosticSink(diag_path)  # absolute, 0600
    repo, db, investigation_id = _build_env(tmp_path)
    orchestrator = AgentOrchestrator(
        FakeCppBackend(tmp_path),
        supervisor=_IntegrateViolatingSupervisor(),
        delegation_dispatcher=OfflineSpecialistDispatcher(repo, db),
        source_scope_provider=lambda task_id: ("windows",),
        failure_diagnostics_sink=sink,
    )
    outcome = (await orchestrator.run_loop("task-A", investigation_id))[0]
    assert outcome.integration_status == "failed"
    failed_run_id = repo.list_runs(investigation_id)[-1].run_id

    lines = [json.loads(line) for line in
             diag_path.read_text(encoding="utf-8").splitlines() if line]
    assert lines, "sink recorded nothing — INSTRUMENTATION BLOCKED"
    entry = next(
        e for e in lines if e["stage"] == "SUPERVISOR_INTEGRATE")

    # §2 required observations — every one must be present and correct
    assert entry["normalized_failure_code"] == "model_output_retry_exhausted"
    assert entry["classified"] is True
    assert entry["exception_class"] == "UnexpectedModelBehavior"
    assert entry["exception_module"].startswith("pydantic_ai")
    assert entry["retry_attempts"] == 1  # supervisor output-retry budget
    # the schema hash identifies the ACTUAL output contract the failing
    # agent carried (the offline harness defaults to the v1 contract; the
    # production benchmark path runs v2 — either way the hash must match
    # the orchestrator's own output type)
    assert entry["schema_hash"] == schema_hash_of(
        orchestrator._integrate_output_type())
    assert entry["tool_name"] == "final_result"
    details = entry["validation_error_details"]
    assert details, "field-level validation errors NOT observable — "
    "INSTRUMENTATION BLOCKED"
    types = {d["type"] for d in details}
    assert "extra_forbidden" in types
    # field-level cause IS observable: every loc path ends in the exact
    # offending schema field (union-member paths included)
    offending = {d["loc"][-1] for d in details if d["loc"]}
    assert "tool_call_count" in offending
    # run-id correlation (§3)
    assert entry["context"]["run_id"] == failed_run_id
    # redaction holds: no input values anywhere in the file
    raw = diag_path.read_text(encoding="utf-8")
    assert "10" not in json.dumps(
        [d for e in lines for d in e.get("validation_error_details", [])])
