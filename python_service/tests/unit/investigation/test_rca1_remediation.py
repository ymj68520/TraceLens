"""RCA-1.6 deterministic regression — zero model calls.

Covers the thirteen required behaviours:
 1. INTEGRATE valid output accepted        (see test_protocol_feasibility_audit)
 2. INTEGRATE invalid output contained + persisted
 3. schema retry exhaustion retains field-level error category
 4. provider timeout exact classification
 5. SDK request retry vs pydantic output retry not conflated
 6. failed delegations keep their truthful state
 7. unintegrated results cannot finalize
 8. CancelledError is never converted into a model failure
 9. all scheduled runs accounted           (see test_screening_disposition_regression)
10. `deferred` is not a legal terminal state
11. timeout-dominated series never READY   (see test_screening_disposition_regression)
12. diagnostics off -> no sensitive leakage
13. historical benchmark artifacts unmodified
"""

import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from tests.unit.investigation.test_agent_investigation_loop import (
    FakeCppBackend,
    OfflineSpecialistDispatcher,
    OfflineSupervisor,
    _build_env,
)
from httpserver.services.investigation.agent_failure_diagnostics import (
    ListFailureDiagnosticSink,
    build_failure_entry,
    failure_diagnostics_sink,
    schema_hash_of,
)
from httpserver.services.investigation.agent_failure_taxonomy import (
    MODEL_OUTPUT_RETRY_EXHAUSTED,
    PROVIDER_CONNECTION_ERROR,
    PROVIDER_RATE_LIMITED,
    PROVIDER_REQUEST_TIMEOUT,
    PROVIDER_SERVER_ERROR,
    classify_failure,
    is_provider_failure,
)
from httpserver.services.investigation.agent_orchestrator import (
    AgentOrchestrator,
)
from httpserver.services.investigation.agent_retry_timeout_facts import (
    SDK_MAX_RETRIES,
    effective_retry_timeout_facts,
)

pytest.importorskip("pydantic_ai")
pytestmark = pytest.mark.migration_matrix

PYTHON_SERVICE_ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# 4/5 — failure taxonomy unit behaviour
# ---------------------------------------------------------------------------


def _openai_exc(class_name: str, **kwargs):
    import openai

    cls = getattr(openai, class_name)
    return cls(**kwargs) if kwargs else cls()


def test_provider_timeout_classified_by_type():
    exc = _openai_exc("APITimeoutError", request=httpx_request())
    c = classify_failure(exc)
    assert c.code == PROVIDER_REQUEST_TIMEOUT
    assert c.classified
    # original SDK exception identity preserved
    assert c.exception_class == "APITimeoutError"
    assert c.exception_module.startswith("openai")


def test_provider_connection_and_http_classes():
    import httpx

    request = httpx.Request("POST", "https://example.invalid/v1/chat/completions")
    conn = classify_failure(_openai_exc("APIConnectionError", request=request))
    assert conn.code == PROVIDER_CONNECTION_ERROR
    rate = classify_failure(
        _status_error("RateLimitError", httpx.Response(429, request=request)))
    assert rate.code == PROVIDER_RATE_LIMITED
    assert rate.http_status == 429
    server = classify_failure(
        _status_error("InternalServerError", httpx.Response(500, request=request)))
    assert server.code == PROVIDER_SERVER_ERROR


def _status_error(class_name: str, response):
    import openai

    cls = getattr(openai, class_name)
    return cls("synthetic status error", response=response, body=None)


def httpx_request():
    import httpx

    return httpx.Request("POST", "https://example.invalid/v1/chat/completions")


def test_output_retry_exhaustion_keeps_budget_metadata():
    from pydantic_ai.exceptions import UnexpectedModelBehavior

    exc = UnexpectedModelBehavior("Exceeded maximum output retries (1)")
    c = classify_failure(exc)
    assert c.code == MODEL_OUTPUT_RETRY_EXHAUSTED
    assert c.output_retry_budget_exhausted == 1
    assert is_provider_failure(c.code) is False


def test_delegation_map_no_longer_misclasses_timeout():
    """Audit F-4 fix: openai transport timeout maps to AGENT_TIMEOUT
    (retryable), never AGENT_INTERNAL_FAILURE."""
    from httpserver.services.investigation.agent_specialist_executor import (
        DelegationFailureCode,
        map_provider_exception,
    )

    assert map_provider_exception(
        _openai_exc("APITimeoutError", request=httpx_request())
    ) is DelegationFailureCode.AGENT_TIMEOUT
    assert map_provider_exception(
        _openai_exc("APIConnectionError", request=httpx_request())
    ) is DelegationFailureCode.AGENT_PROVIDER_UNAVAILABLE
    # output retry exhaustion is NOT a provider class
    from pydantic_ai.exceptions import UnexpectedModelBehavior

    assert map_provider_exception(
        UnexpectedModelBehavior("Exceeded maximum output retries (2)")
    ) is DelegationFailureCode.AGENT_OUTPUT_INVALID


def test_retry_timeout_facts_pin_effective_values():
    import openai

    assert SDK_MAX_RETRIES == openai.DEFAULT_MAX_RETRIES == 2
    facts = effective_retry_timeout_facts()
    assert facts["http_attempts_per_logical_request_max"] == 3
    assert facts["agent_output_retries"]["supervisor_integrate"] == 1
    assert facts["agent_output_retries"]["specialist"] == 2
    assert facts["run_timeout"].startswith("disabled")
    assert facts["dead_configuration"]["llm_max_retries"]


# ---------------------------------------------------------------------------
# 2/3/6/8 — INTEGRATE containment end-to-end on the offline loop
# ---------------------------------------------------------------------------


class _IntegrateViolatingSupervisor(OfflineSupervisor):
    """Reproduces the exact candidate failure signature through the real
    pydantic-ai retry machinery: args violate extra=forbid, the retry
    prompt fires once (default budget 1), then UnexpectedModelBehavior."""

    async def integrate(self, context):
        from pydantic_ai.models.test import TestModel

        from httpserver.services.investigation.agent_supervisor import (
            SupervisorAgentFactory,
        )

        self.integration_calls += 1
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


class _RaisingIntegrateSupervisor(OfflineSupervisor):
    def __init__(self, exc):
        super().__init__()
        self._exc = exc

    async def integrate(self, context):
        self.integration_calls += 1
        raise self._exc


@pytest.mark.asyncio
async def test_integrate_invalid_output_contained_and_persisted(tmp_path):
    """Requirement 2: the historical run-killer is now a first-class
    contained outcome — no exception escape, trajectory event persisted,
    run failed closed."""
    repo, db, investigation_id = _build_env(tmp_path)
    sink = ListFailureDiagnosticSink()
    orchestrator = AgentOrchestrator(
        FakeCppBackend(tmp_path),
        supervisor=_IntegrateViolatingSupervisor(),
        delegation_dispatcher=OfflineSpecialistDispatcher(repo, db),
        source_scope_provider=lambda task_id: ("windows",),
        failure_diagnostics_sink=sink,
    )
    outcome = (await orchestrator.run_loop("task-A", investigation_id))[0]

    assert outcome.integration_status == "failed"
    assert outcome.run_stop_reason == "internal_failure"
    # requirement 6: the delegation keeps its truthful completed state —
    # never marked integrated, never rewritten
    delegation_id = outcome.delegation_ids[0]
    delegation = repo.get_delegation(delegation_id)
    assert delegation.status.value == "completed"
    assert delegation.integrated_at is None
    # persistence: the containment event is in the durable trajectory
    events = [
        e for e in repo.list_trajectory(investigation_id)
        if e.event_type.value == "transition_decision_rejected"
        and "supervisor_failure" in (e.payload or {})
    ]
    assert events, "containment event missing from trajectory"
    payload = events[0].payload
    assert payload["supervisor_failure"] == "supervisor_integration_failed"
    assert payload["underlying_code"] == MODEL_OUTPUT_RETRY_EXHAUSTED
    assert payload["stage"] == "integrate"
    # the AgentRun is terminally failed, consistent with the record
    runs = repo.list_runs(investigation_id)
    assert runs[-1].status.value == "failed"
    # requirement 3: diagnostics retained the field-level error category
    assert sink.entries, "diagnostics sink received nothing"
    entry = sink.entries[0]
    assert entry["stage"] == "SUPERVISOR_INTEGRATE"
    assert entry["normalized_failure_code"] == MODEL_OUTPUT_RETRY_EXHAUSTED
    assert entry["exception_class"] == "UnexpectedModelBehavior"
    assert entry["validation_error_details"], entry
    assert all("input" not in d for d in entry["validation_error_details"])
    assert entry["schema_hash"]


@pytest.mark.asyncio
async def test_cancelled_error_propagates_unconverted(tmp_path):
    """Requirement 8: CancelledError (BaseException) passes through the
    containment untouched — no trajectory event, no fail_run, no outcome."""
    repo, db, investigation_id = _build_env(tmp_path)
    orchestrator = AgentOrchestrator(
        FakeCppBackend(tmp_path),
        supervisor=_RaisingIntegrateSupervisor(asyncio.CancelledError()),
        delegation_dispatcher=OfflineSpecialistDispatcher(repo, db),
        source_scope_provider=lambda task_id: ("windows",),
    )
    with pytest.raises(asyncio.CancelledError):
        await orchestrator.run_loop("task-A", investigation_id)
    kinds = [e.event_type.value for e in repo.list_trajectory(investigation_id)]
    assert "transition_decision_rejected" not in kinds


def test_diagnostics_default_off_and_sanitized(tmp_path):
    """Requirement 12: no sink configured -> resolution returns None; the
    sanitized builder drops validation input values by construction."""
    assert failure_diagnostics_sink(None) is None

    class _FakeSettings:
        llm_failure_diagnostics = False
        llm_failure_diagnostics_path = ""

    assert failure_diagnostics_sink(_FakeSettings()) is None

    # sanitization: input values can never survive build_failure_entry
    from pydantic import ValidationError

    class Secret(BaseModel):
        model_config = ConfigDict(extra="forbid")
        ok: bool

    try:
        Secret.model_validate({"ok": True, "leak": "MODEL-OUTPUT-TEXT"})
    except ValidationError as ve:
        holder = type("H", (Exception,), {})("wrapped")
        holder.__cause__ = ve

        entry = build_failure_entry(
            stage="SUPERVISOR_INTEGRATE",
            exc=holder,
            classification=classify_failure(holder),
        )
    dumped = json.dumps(entry)
    assert "MODEL-OUTPUT-TEXT" not in dumped
    assert all("input" not in d for d in entry["validation_error_details"])
    assert any(d["type"] == "extra_forbidden" for d in entry["validation_error_details"])
    assert schema_hash_of(Secret)


# ---------------------------------------------------------------------------
# 7/10 — finalization gate interplay
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unintegrated_completed_delegation_cannot_finalize(tmp_path):
    """Requirement 7: after a contained INTEGRATE failure the completed
    delegation is unintegrated; a fresh finalization request is DENIED by
    the real gate with the named violation."""
    repo, db, investigation_id = _build_env(tmp_path)
    orchestrator = AgentOrchestrator(
        FakeCppBackend(tmp_path),
        supervisor=_IntegrateViolatingSupervisor(),
        delegation_dispatcher=OfflineSpecialistDispatcher(repo, db),
        source_scope_provider=lambda task_id: ("windows",),
    )
    (await orchestrator.run_loop("task-A", investigation_id))[0]

    from pydantic_ai.models.test import TestModel

    from httpserver.services.investigation.agent_orchestrator import (
        SupervisorCyclePolicy,
    )

    class _FinalizeSupervisor(OfflineSupervisor):
        async def plan(self, pack):
            from httpserver.services.investigation.agent_supervisor import (
                SupervisorAgentFactory,
            )

            args = self._bind_plan(
                pack,
                {
                    "decision_version": "supervisor-plan-decision:v1",
                    "actions": [{
                        "action_kind": "request_finalization",
                        "action_id": "a-fin",
                        "reason_code": "all_required_answered",
                    }],
                },
            )
            agent = SupervisorAgentFactory(
                model=TestModel(call_tools=[], custom_output_args=args)
            ).build_plan_agent(pack)
            result = await agent.run("plan")
            return result.output

    finalizer = AgentOrchestrator(
        FakeCppBackend(tmp_path),
        supervisor=_FinalizeSupervisor(),
        source_scope_provider=lambda task_id: ("windows",),
        cycle_policy=SupervisorCyclePolicy(final_review_mode="best_effort"),
    )
    outcome = (await finalizer.run_loop("task-A", investigation_id))[0]
    assert outcome.finalization is not None
    assert outcome.finalization.decision.outcome.value == "deny"
    assert "UNINTEGRATED_COMPLETED_DELEGATION" in (
        outcome.finalization.decision.violation_codes)


@pytest.mark.asyncio
async def test_deferred_is_not_a_legal_terminal_state(tmp_path):
    """Requirement 10: a required question cannot even REACH deferred —
    the StateTransitionPolicy rejects the transition outright, so the
    terminalization metric can never be inflated by deferral."""
    repo, db, investigation_id = _build_env(tmp_path)

    class _DeferSupervisor(OfflineSupervisor):
        async def integrate(self, context):
            from pydantic_ai.models.test import TestModel

            from httpserver.services.investigation.agent_supervisor import (
                SupervisorAgentFactory,
            )

            args = self._bind_integration(
                context,
                {
                    "decision_version": "supervisor-integration-decision:v1",
                    "integration_summary": "defer the charter question",
                    "transition_proposals": [
                        {"question_id": "q-1", "to_status": "deferred"},
                    ],
                },
            )
            model = TestModel(call_tools=[], custom_output_args=args)
            agent = SupervisorAgentFactory(model=model).build_integration_agent(
                context
            )
            result = await agent.run("integrate")
            return result.output

    orchestrator = AgentOrchestrator(
        FakeCppBackend(tmp_path),
        supervisor=_DeferSupervisor(),
        delegation_dispatcher=OfflineSpecialistDispatcher(repo, db),
        source_scope_provider=lambda task_id: ("windows",),
    )
    outcome = (await orchestrator.run_loop("task-A", investigation_id))[0]
    assert outcome.integration_status == "rejected"
    assert "REQUIRED_QUESTION_CANNOT_DEFER" in outcome.integration_violation_codes
    latest = repo.get_latest_working_state(investigation_id)
    q1 = next(q for q in latest.state.get("questions")
              if q.get("question_id") == "q-1")
    assert q1["status"] == "open"


# ---------------------------------------------------------------------------
# 13 — historical artifact immutability (read-only)
# ---------------------------------------------------------------------------


def test_historical_artifacts_match_amendment_chain():
    """Requirement 13: every artifact referenced by the audit's
    interpretation amendment still hashes to its recorded sha256 (the
    audit dir also carries the RCA-1 contract reconciliation). Read-only
    verification — replays of the disposition script MUST use a temp copy
    of a series root, never the historical directory."""
    audit_dir = (
        PYTHON_SERVICE_ROOT / "benchmarks" / "audits"
        / "cross-model-root-cause-audit-v1"
    )
    amendment = json.loads(
        (audit_dir / "interpretation-amendment-v1.json").read_text())
    for entry in amendment["amendments"]:
        for artifact in entry["original_artifacts"]:
            path = PYTHON_SERVICE_ROOT / artifact["path"]
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            assert digest == artifact["sha256"], (
                f"HISTORICAL ARTIFACT MODIFIED: {artifact['path']}")


def test_sink_operational_boundary(tmp_path):
    """RCA-1.8 §4: path safety, owner-only permissions, serialized appends,
    and write-failure isolation are pinned before first operational use."""
    import os
    import threading

    from httpserver.services.investigation.agent_failure_diagnostics import (
        DiagnosticsPathError,
        JsonlFailureDiagnosticSink,
    )

    # relative paths are rejected at construction (fail loud, never mid-run)
    with pytest.raises(DiagnosticsPathError):
        JsonlFailureDiagnosticSink("relative/diagnostics.jsonl")

    sink = JsonlFailureDiagnosticSink(tmp_path / "diag" / "failures.jsonl")
    sink.record_failure({"normalized_failure_code": "probe", "stage": "X"})
    mode = os.stat(sink.path).st_mode & 0o777
    assert mode == 0o600, f"diagnostics file must be owner-only, got {oct(mode)}"
    content = sink.path.read_text()
    assert "probe" in content

    # serialized appends: a class-level lock exists and is held during writes
    assert isinstance(
        JsonlFailureDiagnosticSink._write_lock, type(threading.Lock()))

    # write failures never propagate (telemetry is never fatal): turn the
    # target into a DIRECTORY so the append raises IsADirectoryError inside
    # record_failure -- the sink must swallow it
    hostile = tmp_path / "diag3" / "f.jsonl"
    hostile_sink = JsonlFailureDiagnosticSink(hostile)
    hostile.unlink()
    hostile.mkdir()
    hostile_sink.record_failure({"normalized_failure_code": "probe2"})
