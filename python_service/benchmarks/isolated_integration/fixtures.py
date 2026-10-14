"""RCA-2A.3 fixtures: synthetic post-delegation stores for the isolated
INTEGRATE stage harness.

Two public fixtures, both built through the REAL production
orchestrator path (Path A) with offline deterministic models:

- Fixture A (``no_evidence``, t2-no-evidence semantics): the honest
  specialist result carries ZERO evidence refs — never a fabricated
  evidence key.
- Fixture B (``evidence_backed``, t2-temporal-trap semantics): the
  specialist result references the REAL visible evidence of the test
  task's files store (``file:C/logon_4624.doc``); the completion
  transaction resolves every ref through the production
  EvidenceResolver and establishes the immutable snapshots, so the
  typed E-handles of the binding table point at legally acquired
  evidence.

Every specialist result below is a SYNTHETIC_SPECIALIST_RESULT: it is
produced by a deterministic TestModel driving the REAL
SpecialistDelegationExecutor, the REAL read-only tool registry and the
REAL completion transaction (production structure validation and
binding constraints apply unchanged).  It is NEVER a
REAL_MODEL_SPECIALIST_RESULT — this stage performs zero model calls
against any provider.

All writes land in the caller's controlled test store (tmp_path); no
real investigation.db is touched.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional

import pytest

from tests.unit.investigation.test_agent_investigation_loop import (
    FakeCppBackend,
    _build_env,
    _registry_builder,
)

pytest.importorskip("pydantic_ai")

from httpserver.services.investigation.agent_orchestrator import (  # noqa: E402
    AgentOrchestrator,
    DelegationExecutionSummary,
)
from httpserver.services.investigation.agent_specialist_executor import (  # noqa: E402
    AgentRunPolicy,
    SpecialistDelegationExecutor,
    build_execution_envelope,
)
from httpserver.services.investigation.agent_specialist_result import (  # noqa: E402
    SpecialistResultProposalV1,
    SpecialistResultV1,
)
from httpserver.services.investigation.agent_supervisor import (  # noqa: E402
    InvestigationSupervisor,
)

SYNTHETIC_SPECIALIST_RESULT = "SYNTHETIC_SPECIALIST_RESULT"
REAL_MODEL_SPECIALIST_RESULT = "REAL_MODEL_SPECIALIST_RESULT"

CHARTER_QUESTION = (
    "Does this device contain evidence of fraud-related financial "
    "activity, and what exactly can and cannot be concluded from the "
    "analyzed content?"
)
VISIBLE_EVIDENCE_KEY = "file:C/logon_4624.doc"


class _ProjectionPlanFunction:
    """PLAN FunctionModel body: resolves A/Q handles from the REAL
    instruction projection and emits one valid delegate action."""

    __name__ = "rca2a3_plan_function"

    def __call__(self, messages, info):
        import json

        from pydantic_ai.messages import ModelResponse, ToolCallPart

        chunks = [str(getattr(p, "content", "")) for m in messages
                  for p in (m.parts or ()) if isinstance(
                      getattr(p, "content", None), str)]
        info_instructions = getattr(info, "instructions", None)
        if isinstance(info_instructions, str):
            chunks.append(info_instructions)
        text = "\n".join(chunks)
        marker = "supervisor plan decision (v2).\n\n"
        projection = json.loads(
            text.split(marker, 1)[1].split("\n\nRules:", 1)[0])
        items = [i for i in projection["attention_items"]
                 if i.get("eligibility") == "eligible"]
        action = {
            "action_type": "delegate_investigation",
            "attention_handle": items[0]["handle"],
            "question_handle": projection["questions"][0]["handle"],
            "source_scope_id": projection["source_scopes"][0],
        }
        args = {"decision_version": "supervisor-plan-decision:v2",
                "actions": [action],
                "summary": "delegate the charter question"}
        return ModelResponse(parts=[ToolCallPart(
            info.output_tools[0].name, json.dumps(args))])


def _synthetic_specialist_result_args(
    delegation_id: str, question_id: str, *, with_evidence: bool
) -> dict:
    """SYNTHETIC_SPECIALIST_RESULT payload for the TestModel-driven
    real specialist executor."""
    evidence = [VISIBLE_EVIDENCE_KEY] if with_evidence else []
    return {
        "proposal_version": "specialist-result-proposal:v1",
        "delegation_id": delegation_id,
        "question_id": question_id,
        "summary": (
            "honest no-evidence investigation; nothing fraud-related "
            "found"
            if not with_evidence
            else "logon cluster observed on the analyzed evidence"
        ),
        "evidence_refs": evidence,
        "claim_candidates": (
            []
            if not with_evidence
            else [{
                "candidate_id": "c-1",
                "text": "logon cluster observed",
                "assertion_class": "INFERENCE",
                "evidence_refs": list(evidence),
                "limitations": [],
            }]
        ),
        "limitations": (
            [] if with_evidence
            else ["no analyzable evidence of the queried activity"]
        ),
    }


class SyntheticSpecialistDispatcher:
    """Runs the REAL SpecialistDelegationExecutor with a deterministic
    TestModel — the result is a SYNTHETIC_SPECIALIST_RESULT that passes
    production structure validation and the real completion transaction
    (A1-S evidence snapshot acquisition for Fixture B)."""

    def __init__(self, repo, db_path, *, with_evidence: bool):
        self._repo = repo
        self._db_path = db_path
        self._with_evidence = with_evidence

    async def __call__(self, planning_context, decision, admitted):
        from types import SimpleNamespace

        from pydantic_ai.models.test import TestModel

        from httpserver.services.investigation.agent_context import (
            ContextAssembler,
        )
        from httpserver.services.investigation.agent_capabilities import (
            ArtifactFamilyRegistry,
        )
        from httpserver.services.investigation.agent_profiles import (
            default_profiles,
        )
        from httpserver.services.investigation.agent_skills import (
            SkillRegistry,
        )
        from httpserver.services.investigation.agent_tools.pydantic_bridge import (
            build_specialist_agent,
        )

        registry = _registry_builder(self._repo)
        assembler = ContextAssembler(
            skill_registry=SkillRegistry.with_defaults(),
            family_registry=ArtifactFamilyRegistry.with_defaults(),
            profiles=default_profiles(),
            tool_schema_hash=registry.schema_hash(),
        )
        summaries: list[DelegationExecutionSummary] = []
        for delegation, action in zip(admitted, decision.delegate_actions()):
            pack = assembler.build(
                task={"id": "task-A", "scenarios": ["windows"],
                      "scenario_databases": {}},
                run_identity={
                    "task_id": "task-A",
                    "investigation_id": delegation.investigation_id,
                    "run_id": delegation.run_id,
                },
                question=CHARTER_QUESTION,
                question_id=action.question_id,
                source_scope_id=action.source_scope_id,
                table_lister=lambda _p: frozenset(),
            )
            pack = pack.model_copy(update={
                "task_id": "task-A",
                "investigation_id": delegation.investigation_id,
                "run_id": delegation.run_id,
                "delegation_id": delegation.delegation_id,
            })
            envelope = build_execution_envelope(
                pack, registry, question_text=CHARTER_QUESTION,
                model_config_digest="cfg-rca2a3",
            )
            result_args = _synthetic_specialist_result_args(
                delegation.delegation_id, action.question_id,
                with_evidence=self._with_evidence,
            )
            model = TestModel(
                call_tools=["search_evidence"],
                custom_output_args=result_args,
            )

            def build_agent(pack_arg, registry_arg, _model=model):
                return build_specialist_agent(
                    pack_arg, registry_arg, model=_model,
                    output_type=SpecialistResultProposalV1, retries=1,
                )

            executor = SpecialistDelegationExecutor(
                cpp_backend=FakeCppBackend(self._db_path.parent),
                settings=SimpleNamespace(
                    llm_text_base_url="http://localhost:9",
                    llm_endpoint="/v1/chat/completions",
                    llm_api_key="k",
                    llm_text_model="offline",
                    llm_thinking_mode="",
                    llm_timeout_seconds=5.0,
                    llm_text_temperature=None,
                    llm_text_max_tokens=None,
                ),
                tool_services=None,
                registry_builder=lambda runtime, observation_sink=None: (
                    registry),
                investigation_db_path_for_task=lambda task: self._db_path,
            )
            executor._build_agent = build_agent
            executor._policy = AgentRunPolicy(max_provider_retries=0)
            outcome = await executor.dispatch_delegation(envelope)
            stored = self._repo.get_delegation_result(
                delegation.delegation_id)
            summaries.append(DelegationExecutionSummary(
                delegation_id=delegation.delegation_id,
                question_id=action.question_id,
                source_scope_id=action.source_scope_id,
                status=outcome.status.value,
                result=(
                    SpecialistResultV1.model_validate(stored.result)
                    if stored is not None else None
                ),
                result_hash=outcome.result_hash,
                context_hash=envelope.context_hash,
                failure_code=outcome.failure_code,
                failure_summary=outcome.failure_message,
            ))
        return summaries


class _IntegrateCaptureFunction:
    """INTEGRATE FunctionModel for Path A: captures the production
    model-visible input, then raises so the orchestrator's containment
    stops the cycle BEFORE any integration commit."""

    __name__ = "rca2a3_integrate_capture"

    def __init__(self) -> None:
        self.captured: Optional[dict] = None

    def __call__(self, messages, info):
        import json

        chunks = [str(getattr(p, "content", "")) for m in messages
                  for p in (m.parts or ()) if isinstance(
                      getattr(p, "content", None), str)]
        info_instructions = getattr(info, "instructions", None)
        if isinstance(info_instructions, str):
            chunks.append(info_instructions)
        elif isinstance(info_instructions, (list, tuple)):
            chunks.extend(str(c) for c in info_instructions)
        text = "\n".join(chunks)
        schema = None
        for tool in getattr(info, "output_tools", None) or ():
            schema = tool.parameters_json_schema
        projection = None
        marker = "typed actions only.\n\n"
        if marker in text:
            projection = json.loads(
                text.split(marker, 1)[1].split("\n\nRules:", 1)[0])
        self.captured = {
            "instructions": text,
            "output_tool_schemas": [
                tool.parameters_json_schema
                for tool in getattr(info, "output_tools", None) or ()
            ],
            "output_tool_names": [
                tool.name
                for tool in getattr(info, "output_tools", None) or ()
            ],
            "model_settings": _jsonable(getattr(info, "model_settings",
                                                None)),
            "projection": projection,
        }
        raise _CaptureReached()


class _CaptureReached(Exception):
    """Raised by the capture model after recording the production
    input; the orchestrator's INTEGRATE containment treats it as a
    first-class contained failure (no commit — exactly the boundary
    the parity gate needs)."""


def _jsonable(value: Any) -> Any:
    try:
        import json

        return json.loads(json.dumps(value, default=str))
    except Exception:
        return str(value)


async def prepare_post_delegation_store(
    tmp_path, *, with_evidence: bool
) -> SimpleNamespace:
    """Build a post-delegation store through the REAL orchestrator
    (Path A) and capture the production INTEGRATE model-visible input.

    Returns a namespace with: db_path, repo (AgentRuntimeRepository),
    task_id, investigation_id, run_id, capture (Path A captured input),
    evidence_kind.  The test AgentRun is terminal (the capture raise is
    contained by the orchestrator's RCA-1.1 INTEGRATE containment)."""
    repo, db_path, investigation_id = _build_env(tmp_path)
    capture = _IntegrateCaptureFunction()
    from pydantic_ai.models.function import FunctionModel

    class _MultiModelSupervisor(InvestigationSupervisor):
        """PLAN via the projection-driven FunctionModel; INTEGRATE via
        the capture FunctionModel. Both offline and deterministic."""

        def __init__(self):
            super().__init__(model=FunctionModel(_ProjectionPlanFunction()))
            self._integrate_model = FunctionModel(capture)

        async def integrate_v2(self, context, table, state):
            from httpserver.services.investigation.agent_integration_v2 import (
                render_integration_context_v2,
            )
            from httpserver.services.investigation.agent_supervisor import (
                SupervisorAgentFactory,
            )

            projection = render_integration_context_v2(context, state, table)
            agent = SupervisorAgentFactory(
                model=self._integrate_model
            ).build_integration_agent_v2(projection)
            await agent.run("integrate")
            raise AssertionError("capture model must raise")

    orchestrator = AgentOrchestrator(
        FakeCppBackend(db_path.parent),
        supervisor=_MultiModelSupervisor(),
        delegation_dispatcher=SyntheticSpecialistDispatcher(
            repo, db_path, with_evidence=with_evidence),
        supervisor_contract_version="v2",
    )
    outcome = await orchestrator.execute_cycle(
        "task-A", investigation_id, source_scope_ids=("windows",)
    )
    assert outcome.integration_status == "failed", (
        "Path A must stop at the INTEGRATE boundary via containment"
    )
    runs = repo.list_runs(investigation_id)
    assert runs and runs[-1].status.value == "failed", (
        "the capture containment must leave a terminal AgentRun (CF-1)"
    )
    assert capture.captured is not None, (
        "Path A must have captured the production model-visible input"
    )
    return SimpleNamespace(
        db_path=db_path,
        repo=repo,
        task_id="task-A",
        investigation_id=investigation_id,
        run_id=runs[-1].run_id,
        capture=capture.captured,
        evidence_kind=(
            "REAL_BOUND_TASK_EVIDENCE" if with_evidence
            else "NO_EVIDENCE_HONEST_EMPTY"
        ),
        specialist_result_kind=SYNTHETIC_SPECIALIST_RESULT,
    )
