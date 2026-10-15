"""RCA-2A.3 isolated INTEGRATE stage harness.

Stage-level diagnostic harness over an EXISTING post-delegation state
in a controlled test store.  It composes ONLY production components —
no second ContextPack/binding/prompt logic, no new proposal schema:

    build_integration_context          (production, agent_integration.py)
    build_integration_binding_table    (production, agent_reference_bindings.py)
    render_integration_context_v2      (production, agent_integration_v2.py)
    SupervisorAgentFactory.build_integration_agent_v2 (production factory,
        real SupervisorIntegrationDecisionV2 output contract + real
        _integration_instructions_v2)
    resolve_integration_proposal_v2    (production canonical resolver)
    IntegrationDecisionValidator       (production)
    StateTransitionPolicy              (production)
    AgentRuntimeRepository.commit_agent_integration (production primitive)

Nothing is bypassed: the binding table, grounding (evidence resolver),
state revision/hash checks, the output-tool validator and the frozen
retry budget (pydantic-ai default, identical to production) all run
exactly as in the normal orchestrator path.  The harness never touches
a real investigation.db: the store is the caller's controlled test
task, and the stage owns NO AgentRun lifecycle of its own — it binds to
the run created by Path A and explicitly declares
``finalization: NOT_EXERCISED`` (a stage success is never an
AgentRun/Investigation success; CF-1 settlement semantics are not
bypassed because the harness creates no run that would need settling).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from httpserver.services.investigation.agent_integration import (
    INTEGRATION_POLICY_VERSION,
    IntegrationDecisionValidator,
    build_integration_context,
)
from httpserver.services.investigation.agent_integration_v2 import (
    INTEGRATION_DECISION_VERSION,
    SupervisorIntegrationDecisionV2,
    render_integration_context_v2,
    resolve_integration_proposal_v2,
)
from httpserver.services.investigation.agent_reference_bindings import (
    build_integration_binding_table,
)
from httpserver.services.investigation.agent_runtime import (
    AgentRunStatus,
    AgentRuntimeRepository,
    canonical_state_json,
    state_hash_of,
)
from httpserver.services.investigation.agent_supervisor import (
    SupervisorAgentFactory,
)
from httpserver.services.investigation.agent_transitions import (
    StateTransitionPolicy,
    TransitionBatch,
    TransitionDecisionStatus,
    TransitionPolicyContext,
)
from httpserver.services.investigation.agent_working_state import (
    working_state_from_json,
)
from httpserver.services.investigation.repository import (
    InvestigationRepository,
)

STAGE_NAME = "SUPERVISOR_INTEGRATE"
OUTPUT_TOOL_NAME = "final_result"


# ---------------------------------------------------------------------------
# IsolatedIntegrationInputV1 — machine-verifiable frozen input contract
# (benchmark-side dict contract; field names follow the repository's own
# structures; no new production Pydantic model)
# ---------------------------------------------------------------------------

_REQUIRED_INPUT_FIELDS = (
    "task_id",
    "investigation_id",
    "run_id",
    "working_state_revision",
    "working_state_hash",
    "integration_context_hash",
    "reference_binding_table_hash",
    "fresh_delegation_result_ids",
    "fresh_delegation_result_hashes",
    "model_visible_instructions_hash",
    "output_schema_hash",
    "runtime_identity",
)


def validate_isolated_input(input_contract: dict) -> list[str]:
    """Validate an IsolatedIntegrationInputV1 dict; returns violations."""
    violations = []
    for key in _REQUIRED_INPUT_FIELDS:
        if key not in input_contract:
            violations.append(f"missing field: {key}")
    fresh_ids = input_contract.get("fresh_delegation_result_ids", ())
    fresh_hashes = input_contract.get("fresh_delegation_result_hashes", ())
    if len(fresh_ids) != len(fresh_hashes):
        violations.append("result ids/hashes length mismatch")
    runtime_identity = input_contract.get("runtime_identity") or {}
    for key in ("baseline_commit", "harness", "specialist_result_kind"):
        if key not in runtime_identity:
            violations.append(f"runtime_identity missing: {key}")
    return violations


# ---------------------------------------------------------------------------
# the stage harness
# ---------------------------------------------------------------------------


@dataclass
class StageStep:
    name: str
    ok: bool
    detail: dict = field(default_factory=dict)


@dataclass
class StageResult:
    steps: list[StageStep] = field(default_factory=list)
    committed: bool = False
    resolution_violations: tuple = ()
    exception_class: Optional[str] = None
    diagnostics_emitted: list[dict] = field(default_factory=list)
    lifecycle: dict = field(default_factory=dict)

    def step(self, name: str, ok: bool, **detail) -> None:
        self.steps.append(StageStep(name=name, ok=ok, detail=detail))

    @property
    def pydantic_ok(self) -> bool:
        return self._step_ok("pydantic_validation")

    def _step_ok(self, name: str) -> bool:
        return any(s.name == name and s.ok for s in self.steps)


class IsolatedIntegrationHarness:
    """One stage execution bound to one frozen post-delegation state."""

    def __init__(
        self,
        *,
        db_path,
        task_id: str,
        investigation_id: str,
        run_id: str,
        runtime_identity: dict,
    ):
        self._db_path = db_path
        self._task_id = task_id
        self._investigation_id = investigation_id
        self._run_id = run_id
        self._runtime_identity = dict(runtime_identity)
        repo = InvestigationRepository.open_existing(db_path, task_id)
        self._runtime = AgentRuntimeRepository(repo)
        self._state_revision: int = 0
        self._state_hash: str = ""
        self._state = None
        self._context = None
        self._table = None
        self._projection: dict = {}
        self._fresh_envelopes: tuple = ()
        self._derive()

    # -- durable derivation (no PLAN memory dependency) ------------------

    def _derive(self) -> None:
        runtime = self._runtime
        investigation_id = self._investigation_id
        latest = runtime.get_latest_working_state(investigation_id)
        self._state_revision = latest.revision
        self._state_hash = latest.state_hash
        self._state = working_state_from_json(
            self._task_id, investigation_id, latest.state
        )
        # fresh selection: completed-unintegrated delegations of THIS run
        # with a durably stored result (the orchestrator's MergeGuard
        # owns staleness; a stage run over this frozen state sees the
        # same fresh set the orchestrator saw at its INTEGRATE point).
        # context_hash comes from the completion transaction row (the
        # execution envelope hash); source_scope_id comes from the
        # durable PLAN decision payload — both byte-identical to what
        # the orchestrator held in memory at its INTEGRATE point.
        plan_scopes = {
            action["question_id"]: action.get("source_scope_id")
            for action in self._durable_plan_delegate_actions()
        }
        fresh = []
        for run in runtime.list_runs(investigation_id):
            for delegation in runtime.list_delegations(run.run_id):
                if delegation.status.value != "completed":
                    continue
                if delegation.integrated_at is not None:
                    continue
                stored = runtime.get_delegation_result(
                    delegation.delegation_id
                )
                if stored is None:
                    continue
                from httpserver.services.investigation.agent_integration import (
                    FreshResultEnvelope,
                )
                from httpserver.services.investigation.agent_specialist_result import (
                    SpecialistResultV1,
                )

                result = SpecialistResultV1.model_validate(stored.result)
                fresh.append(FreshResultEnvelope(
                    delegation_id=delegation.delegation_id,
                    question_id=delegation.question_ref,
                    source_scope_id=plan_scopes.get(delegation.question_ref),
                    result=result,
                    result_hash=stored.result_hash,
                    context_hash=stored.context_hash,
                ))
        self._fresh_envelopes = tuple(fresh)
        # attention refs + directive digests from durable facts only
        attention_refs = tuple(
            action["attention_item_id"]
            for action in self._durable_plan_delegate_actions()
        )
        current_directive_digests = {
            f"directive-{index}": digest
            for index, digest in enumerate(
                sorted(
                    state_hash_of(canonical_state_json(d.model_dump()))
                    for d in self._state.directive_refs
                )
            )
        }
        self._context = build_integration_context(
            task_id=self._task_id,
            investigation_id=investigation_id,
            run_id=self._run_id,
            state=self._state,
            state_revision=self._state_revision,
            state_hash=self._state_hash,
            fresh_results=self._fresh_envelopes,
            stale_result_digests=(),
            failure_digests=(),
            attention_refs=attention_refs,
            current_directive_digests=current_directive_digests,
        )
        self._table = build_integration_binding_table(
            self._context, self._state
        )
        self._projection = render_integration_context_v2(
            self._context, self._state, self._table
        )

    def _durable_plan_delegate_actions(self) -> list[dict]:
        for event in self._runtime.list_trajectory(self._investigation_id):
            if event.event_type.value != "supervisor_plan_decided":
                continue
            decision = (event.payload or {}).get("decision") or {}
            return [
                action
                for action in decision.get("actions", ())
                if action.get("action_kind") == "delegate_investigation"
            ]
        return []

    # -- contract ---------------------------------------------------------

    def isolated_input(self) -> dict:
        """IsolatedIntegrationInputV1: all trusted identity is
        server-constructed; nothing here is LLM-generated."""
        from httpserver.services.investigation.agent_failure_diagnostics import (
            schema_hash_of,
        )

        input_contract = {
            "task_id": self._task_id,
            "investigation_id": self._investigation_id,
            "run_id": self._run_id,
            "working_state_revision": self._state_revision,
            "working_state_hash": self._state_hash,
            "integration_context_hash": self._context.input_hash(),
            "reference_binding_table_hash": self._table.table_hash(),
            "fresh_delegation_result_ids": [
                env.delegation_id for env in self._fresh_envelopes
            ],
            "fresh_delegation_result_hashes": [
                env.result_hash for env in self._fresh_envelopes
            ],
            "evidence_snapshot_refs": sorted({
                ref
                for env in self._fresh_envelopes
                for ref in env.result.iter_evidence_refs()
            }),
            "model_visible_instructions_hash": _sha256(
                self.model_visible_instructions()
            ),
            "output_schema_hash": schema_hash_of(
                SupervisorIntegrationDecisionV2
            ),
            "runtime_identity": dict(self._runtime_identity),
        }
        violations = validate_isolated_input(input_contract)
        if violations:
            raise ValueError(
                f"IsolatedIntegrationInputV1 invalid: {violations}"
            )
        return input_contract

    def model_visible_instructions(self) -> str:
        from httpserver.services.investigation.agent_supervisor import (
            _integration_instructions_v2,
        )

        return _integration_instructions_v2(self._projection)

    # -- stage execution ---------------------------------------------------

    async def capture_model_visible_input(
        self,
        *,
        agent_factory=None,
    ) -> dict:
        """Build the production INTEGRATE agent and capture exactly what
        the model would see (instructions / output tool / settings).
        ``agent_factory`` optionally substitutes the factory class
        (experimental INTEGRATE-only variants, e.g. RCA-2A.6 vocabulary
        guidance); the default remains the untouched production
        factory."""
        captured: dict = {}

        def capture_fn(messages, info):  # noqa: ANN001
            chunks = [str(getattr(p, "content", "")) for m in messages
                      for p in (m.parts or ()) if isinstance(
                          getattr(p, "content", None), str)]
            info_instructions = getattr(info, "instructions", None)
            if isinstance(info_instructions, str):
                chunks.append(info_instructions)
            text = "\n".join(chunks)
            captured["instructions"] = text
            captured["output_tool_schemas"] = [
                tool.parameters_json_schema
                for tool in getattr(info, "output_tools", None) or ()
            ]
            captured["output_tool_names"] = [
                tool.name
                for tool in getattr(info, "output_tools", None) or ()
            ]
            captured["model_settings"] = _jsonable(
                getattr(info, "model_settings", None))
            marker = "typed actions only.\n\n"
            captured["projection"] = (
                json.loads(text.split(marker, 1)[1].split("\n\nRules:", 1)[0])
                if marker in text else None
            )
            raise _StageCaptureReached()

        from pydantic_ai.models.function import FunctionModel

        factory = agent_factory if agent_factory is not None \
            else SupervisorAgentFactory
        agent = factory(
            model=FunctionModel(capture_fn)
        ).build_integration_agent_v2(self._projection)
        try:
            await agent.run("integrate")
        except _StageCaptureReached:
            pass
        return captured

    async def run_stage(
        self,
        model_function: Callable | None = None,
        *,
        diagnostic_sink=None,
        model: Any = None,
        agent_factory=None,
    ) -> StageResult:
        """Run one isolated stage.  ``model_function`` drives an offline
        FunctionModel; pass ``model`` instead to inject a REAL pydantic-ai
        model (production adapter) — exactly one of the two.
        ``agent_factory`` optionally substitutes the factory class for
        the INTEGRATE agent construction (experimental INTEGRATE-only
        variants, e.g. RCA-2A.6 vocabulary guidance); the default is the
        untouched production factory.  Everything downstream (output
        contract, validation, resolver, policy, commit, diagnostics) is
        identical in every mode."""
        """One isolated stage execution: production agent -> production
        validation -> production resolution -> production policy ->
        production commit.  Failures are contained inside the stage and
        emitted through the SAME diagnostic builders the orchestrator
        uses; no AgentRun lifecycle is created or modified."""
        from pydantic_ai.models.function import FunctionModel

        result = StageResult()
        result.lifecycle = {
            "stage_execution": "isolated_stage_diagnostic",
            "agent_run_created": False,
            "bound_run_id": self._run_id,
            "finalization": "NOT_EXERCISED",
            "specialist_reexecuted": False,
        }
        if (model_function is None) == (model is None):
            raise ValueError(
                "run_stage requires exactly one of model_function "
                "(offline FunctionModel) or model (real pydantic-ai model)"
            )
        from pydantic_ai.models.function import FunctionModel as _FM

        factory = agent_factory if agent_factory is not None \
            else SupervisorAgentFactory
        agent = factory(
            model=model if model is not None else _FM(model_function)
        ).build_integration_agent_v2(self._projection)

        try:
            agent_result = await agent.run("integrate")
        except Exception as exc:  # noqa: BLE001 — contained, classified
            from pydantic_ai.exceptions import UnexpectedModelBehavior

            # an UnexpectedModelBehavior means the model DID respond and
            # its output failed validation/retry — not a provider failure
            output_received = isinstance(exc, UnexpectedModelBehavior)
            result.step("model_output_received", output_received)
            result.exception_class = type(exc).__name__
            result.step("pydantic_validation", False,
                        not_reached=not output_received)
            self._emit_diagnostics(result, diagnostic_sink, exc,
                                   retry_attempts=None)
            return result
        result.step("model_output_received", True)
        decision = agent_result.output
        result.step("pydantic_validation", True,
                    decision_version=decision.decision_version)

        resolution, record = resolve_integration_proposal_v2(
            decision, self._table, self._context, self._state
        )
        if resolution is None:
            result.step("canonical_resolution", False,
                        violations=[v.code.value for v in
                                    record.violations])
            result.resolution_violations = tuple(
                v.code.value for v in record.violations)
            return result
        result.step("canonical_resolution", True,
                    actions=record.actions_total)

        validator = IntegrationDecisionValidator(
            evidence_ref_validator=None,
            proposal_ref_resolver=(
                lambda ref, _rid=self._investigation_id,
                _rt=self._runtime:
                _rt.get_claim_proposal(_rid, ref) is not None
            ),
            finding_ref_resolver=(
                lambda ref, _rid=self._investigation_id,
                _rt=self._runtime:
                (
                    lambda finding: finding is not None
                    and finding["status"] in ("review_pending", "accepted")
                )(_rt.get_investigation_finding(_rid, ref))
            ),
        )
        iv = validator.validate(self._context, resolution)
        if not iv.valid:
            result.step("decision_validator", False, codes=list(iv.codes))
            return result
        result.step("decision_validator", True)

        policy = StateTransitionPolicy()
        policy_result = policy.evaluate_batch(
            self._state,
            TransitionBatch(transitions=resolution.transition_proposals),
            self._policy_context(),
        )
        if policy_result.status is TransitionDecisionStatus.rejected:
            result.step(
                "transition_validation", False,
                codes=[v.code for v in policy_result.violations])
            return result
        result.step("transition_validation", True,
                    status=policy_result.status.value)

        operation_key = "integ:" + hashlib.sha256(
            (
                f"{self._investigation_id}:{self._state_revision}:"
                + ",".join(sorted(env.result_hash
                                  for env in self._fresh_envelopes))
                + f":{INTEGRATION_POLICY_VERSION}"
            ).encode("utf-8")
        ).hexdigest()[:32]
        commit = self._runtime.commit_agent_integration(
            self._investigation_id,
            expected_revision=self._state_revision,
            expected_state_hash=self._state_hash,
            operation_key=operation_key,
            integration_policy_version=INTEGRATION_POLICY_VERSION,
            decision_payload=resolution.model_dump(
                mode="json", exclude={"transition_proposals"}),
            decision_hash=resolution.decision_hash(),
            delegation_integrations=[
                {
                    "delegation_id": env.delegation_id,
                    "result_hash": env.result_hash,
                }
                for env in self._fresh_envelopes
            ],
            new_state=(
                json.loads(json.dumps(
                    _state_to_jsonable(policy_result.new_state)))
                if policy_result.status is TransitionDecisionStatus.accepted
                else None
            ),
            run_id=self._run_id,
        )
        result.step("integration_commit", True,
                    status=commit.status,
                    revision=commit.state_revision)
        result.committed = commit.status == "committed"
        return result

    def _policy_context(self) -> TransitionPolicyContext:
        # same resolvers as the orchestrator's INTEGRATE policy call —
        # the production static helpers are reused, not copied
        return TransitionPolicyContext(
            task_id=self._task_id,
            investigation_id=self._investigation_id,
            evidence_ref_resolver=(
                AgentOrchestratorResolvers.evidence_ref_resolver(
                    self._runtime)),
            finding_ref_validator=(
                AgentOrchestratorResolvers.finding_ref_validator(
                    self._runtime, self._investigation_id)),
            verification_checker=lambda question_id: any(
                v.target_ref == question_id
                and v.status.value == "passed"
                for v in self._state.pending_verifications
            ),
        )

    def _emit_diagnostics(
        self,
        result: StageResult,
        diagnostic_sink,
        exc: Exception,
        *,
        retry_attempts: Optional[int],
    ) -> None:
        from httpserver.services.investigation.agent_failure_diagnostics import (
            build_failure_entry,
            schema_hash_of,
        )
        from httpserver.services.investigation.agent_failure_taxonomy import (
            classify_failure,
        )

        entry = build_failure_entry(
            stage=STAGE_NAME,
            exc=exc,
            classification=classify_failure(exc),
            output_schema_hash=schema_hash_of(
                SupervisorIntegrationDecisionV2),
            tool_name=OUTPUT_TOOL_NAME,
            retry_attempts=retry_attempts,
            context={"run_id": self._run_id},
        )
        result.diagnostics_emitted.append(entry)
        if diagnostic_sink is not None:
            diagnostic_sink.record_failure(entry)

    # -- post-conditions ---------------------------------------------------

    def store_lifecycle_snapshot(self) -> dict:
        """Independent lifecycle facts for the stage (CF-1 compat)."""
        runtime = self._runtime
        runs = runtime.list_runs(self._investigation_id)
        return {
            "stage_execution": "isolated_stage_diagnostic",
            "execution_snapshot_status": self._state_revision,
            "settled_agent_run_status": [
                {
                    "run_id": r.run_id,
                    "status": r.status.value,
                    "stop_reason": (
                        r.stop_reason.value if r.stop_reason else None),
                }
                for r in runs
            ],
            "non_terminal_runs": [
                r.run_id for r in runs
                if r.status in (AgentRunStatus.queued, AgentRunStatus.running)
            ],
            "finalization_status": (
                "finalized"
                if runtime.get_finalization(self._investigation_id)
                else "NOT_EXERCISED"
            ),
        }


class _StageCaptureReached(Exception):
    pass


class AgentOrchestratorResolvers:
    """Reuse seam: the orchestrator's production static resolver helpers,
    called (not copied) so the harness policy context is byte-identical
    to the normal path's."""

    @staticmethod
    def evidence_ref_resolver(runtime):
        from httpserver.services.investigation.agent_orchestrator import (
            AgentOrchestrator,
        )

        return AgentOrchestrator._evidence_ref_resolver(runtime)

    @staticmethod
    def finding_ref_validator(runtime, investigation_id):
        from httpserver.services.investigation.agent_orchestrator import (
            AgentOrchestrator,
        )

        return AgentOrchestrator._finding_ref_validator(
            runtime, investigation_id)


def _jsonable(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, default=str))
    except Exception:
        return str(value)


def _state_to_jsonable(state) -> dict:
    from httpserver.services.investigation.agent_working_state import (
        working_state_to_json,
    )

    dumped = working_state_to_json(state)
    return json.loads(dumped) if isinstance(dumped, str) else dumped


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


__all__ = [
    "INTEGRATION_DECISION_VERSION",
    "IsolatedIntegrationHarness",
    "StageResult",
    "validate_isolated_input",
]
