"""RCA-2A.2c CF-1 harness — deterministic offline model injection for the
REAL run_p8b_baseline CLI.

Loaded via PYTHONPATH sitecustomize. Every model-facing seam is replaced
with a pydantic-ai FunctionModel; NO real provider client is ever
constructed and NO network call is possible:

- SupervisorAgentFactory.build_plan_agent / build_plan_agent_v2 ->
    production Agent (same instructions function, same output_type) whose
    model is a scenario-driven FunctionModel.  The REAL model-visible
    output tool schema is captured from AgentInfo.output_tools on the
    first PLAN call (audit section 3 evidence).
- SupervisorAgentFactory.build_integration_agent / _v2 -> same pattern
    (valid minimal update_question action) so the control scenario
    exercises the full PLAN->EXECUTE->INTEGRATE->EVALUATE cycle.
- SpecialistDelegationExecutor._get_model -> FunctionModel running an
    honest search_evidence round-trip then an empty-evidence proposal.
- agent_model_adapter.build_chat_model -> tripwire FunctionModel: any
    UNPATCHED consumer that actually runs a model fails loudly offline.

Scenario selection: env RCA2A2C_PLAN_SCENARIO in
  valid | invalid_union | timeout | cancelled
Evidence JSONL: env RCA2A2C_EVIDENCE_PATH (handles/schema/calls only —
never case content, never prompts, never keys).

Baseline 4b006c28; zero real model calls by construction.
"""

import json
import os
import sys

_HARNESS_SCENARIO = os.environ.get("RCA2A2C_PLAN_SCENARIO", "valid")
_HARNESS_EVIDENCE = os.environ.get("RCA2A2C_EVIDENCE_PATH", "")


def _log(obj) -> None:
    if not _HARNESS_EVIDENCE:
        return
    try:
        with open(_HARNESS_EVIDENCE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def _install() -> None:
    python_service_root = os.environ.get("RCA2A2C_PY_SERVICE_ROOT", "")
    if python_service_root and python_service_root not in sys.path:
        sys.path.insert(0, python_service_root)

    import httpx

    from pydantic_ai import Agent
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    from httpserver.services.investigation import agent_supervisor as sup
    from httpserver.services.investigation import (
        agent_specialist_executor as spec_exec,
    )
    from httpserver.services.investigation import agent_model_adapter as adapter

    # ------------------------------------------------------------------
    # shared helpers
    # ------------------------------------------------------------------

    def _instruction_text(messages, info=None) -> str:
        chunks = []
        for message in messages:
            for part in getattr(message, "parts", ()) or ():
                content = getattr(part, "content", None)
                if isinstance(content, str):
                    chunks.append(content)
        # this pydantic-ai build delivers Agent(instructions=[...]) through
        # AgentInfo.instructions, not as a message part
        info_instructions = getattr(info, "instructions", None)
        if isinstance(info_instructions, str):
            chunks.append(info_instructions)
        elif isinstance(info_instructions, (list, tuple)):
            chunks.extend(str(c) for c in info_instructions)
        return "\n".join(chunks)

    def _extract_json_blob(text: str, start_marker: str) -> dict:
        if start_marker not in text:
            raise RuntimeError(f"harness: projection marker missing: {start_marker!r}")
        blob = text.split(start_marker, 1)[1]
        blob = blob.split("\n\nRules:", 1)[0]
        return json.loads(blob)

    def _first_tool(info) -> str:
        tools = getattr(info, "output_tools", None) or ()
        if not tools:
            raise RuntimeError("harness: no output tool offered")
        return tools[0].name

    def _capture_output_schema(stage: str, info) -> None:
        for tool in getattr(info, "output_tools", None) or ():
            _log({
                "kind": "output_tool_schema",
                "stage": stage,
                "tool_name": tool.name,
                "parameters_json_schema": tool.parameters_json_schema,
            })

    _call_counters: dict = {}

    def _next_call(stage: str) -> int:
        _call_counters[stage] = _call_counters.get(stage, 0) + 1
        return _call_counters[stage]

    # ------------------------------------------------------------------
    # PLAN FunctionModel
    # ------------------------------------------------------------------

    def _plan_handles_from(text: str) -> tuple[str, str, str]:
        projection = _extract_json_blob(
            text, "supervisor plan decision (v2).\n\n"
        )
        items = [
            item for item in projection.get("attention_items", [])
            if item.get("eligibility") == "eligible"
        ] or projection.get("attention_items", [])
        attention_handle = items[0]["handle"] if items else "A1"
        questions = projection.get("questions", [])
        question_handle = questions[0]["handle"] if questions else "Q1"
        scopes = projection.get("source_scopes", []) or ["windows"]
        _log({
            "kind": "plan_projection_facts",
            "attention_items": len(projection.get("attention_items", ())),
            "eligible_items": len(items),
            "questions": len(questions),
            "handles_chosen": [attention_handle, question_handle],
            "source_scopes": list(scopes),
            "phase_capabilities": list(projection.get("phase_capabilities", ())),
        })
        return attention_handle, question_handle, scopes[0]

    def plan_function(messages, info):  # noqa: ANN001 - FunctionModel shape
        stage = "plan"
        _capture_output_schema(stage, info)
        n = _next_call(stage)
        try:
            attention, question, scope = _plan_handles_from(
                _instruction_text(messages, info)
            )
        except Exception as exc:  # noqa: BLE001 — harness visibility only
            _log({"kind": "plan_exception", "call": n,
                  "error": repr(exc)[:200],
                  "instructions_len": len(getattr(info, "instructions", "") or ""),
                  "marker_present": "supervisor plan decision (v2)." in (
                      getattr(info, "instructions", "") or "")})
            raise
        if _HARNESS_SCENARIO == "timeout":
            from openai import APITimeoutError

            _log({"kind": "raised", "stage": stage, "call": n,
                  "exception": "openai.APITimeoutError"})
            raise APITimeoutError(request=httpx.Request(
                "POST", "http://127.0.0.1:9/v1/chat/completions"))
        if _HARNESS_SCENARIO == "cancelled":
            import asyncio

            _log({"kind": "raised", "stage": stage, "call": n,
                  "exception": "asyncio.CancelledError"})
            raise asyncio.CancelledError()
        if _HARNESS_SCENARIO == "invalid_union":
            # RCA-2A.2b historical field-level shape: discriminant field
            # named `type` instead of `action_type` (extra_forbidden in
            # every union branch -> INVALID_UNION).
            args = {
                "decision_version": "supervisor-plan-decision:v2",
                "actions": [{
                    "type": "delegate_investigation",
                    "attention_handle": attention,
                    "question_handle": question,
                    "source_scope_id": scope,
                }],
                "summary": "delegate the charter question",
            }
        else:  # valid (default)
            args = {
                "decision_version": "supervisor-plan-decision:v2",
                "actions": [{
                    "action_type": "delegate_investigation",
                    "attention_handle": attention,
                    "question_handle": question,
                    "source_scope_id": scope,
                }],
                "summary": "delegate the charter question",
            }
        _log({"kind": "plan_action", "call": n,
              "discriminant_field": sorted(args["actions"][0])[0]})
        return ModelResponse(parts=[ToolCallPart(
            _first_tool(info), json.dumps(args))])

    def plan_function_v1(messages, info):  # noqa: ANN001
        # v1 contract is not exercised by the production default (v2);
        # tripwire only.
        raise RuntimeError("harness: v1 plan contract unexpectedly invoked")

    # ------------------------------------------------------------------
    # INTEGRATE FunctionModel (control scenario only reaches this)
    # ------------------------------------------------------------------

    def integrate_function(messages, info):  # noqa: ANN001
        stage = "integrate"
        _capture_output_schema(stage, info)
        n = _next_call(stage)
        text = _instruction_text(messages, info)
        projection = _extract_json_blob(
            text, "typed actions only.\n\n"
        )
        questions = [
            q for q in projection.get("questions", [])
            if q.get("status") in ("open", "in_progress")
        ]
        question_handle = questions[0]["handle"] if questions else "Q1"
        args = {
            "actions": [{
                "action_type": "update_question",
                "question_handle": question_handle,
                "to_status": "in_progress",
                "investigated_summary": (
                    "honest no-evidence investigation completed; nothing "
                    "fraud-related found"
                ),
            }],
        }
        _log({"kind": "integrate_action", "call": n,
              "question_handle": question_handle})
        return ModelResponse(parts=[ToolCallPart(
            _first_tool(info), json.dumps(args))])

    def integrate_function_v1(messages, info):  # noqa: ANN001
        raise RuntimeError("harness: v1 integration unexpectedly invoked")

    # ------------------------------------------------------------------
    # specialist FunctionModel: honest search round-trip then empty result
    # ------------------------------------------------------------------

    def specialist_function(messages, info):  # noqa: ANN001
        stage = "specialist"
        n = _next_call(stage)
        if n == 1:
            tools = getattr(info, "function_tools", None) or ()
            search = next(
                (t for t in tools if "search" in (t.name or "")), None
            )
            if search is not None:
                schema = search.parameters_json_schema or {}
                required = schema.get("required", []) or []
                args = {}
                for key in required:
                    if "query" in key or "text" in key or "term" in key:
                        args[key] = "fraud financial activity"
                if not args:
                    args = {k: "" for k in schema.get("properties", {})}
                _log({"kind": "specialist_tool_call", "call": n,
                      "tool": search.name})
                return ModelResponse(parts=[ToolCallPart(
                    search.name, json.dumps(args))])
        text = _instruction_text(messages, info)
        marker = '"delegation_id"'
        delegation_id = ""
        if marker in text:
            blob = text.split(marker, 1)[1]
            for candidate in blob.replace("'", '"').split('"')[1::2]:
                if candidate and candidate not in ("-",):
                    delegation_id = candidate
                    break
        _log({"kind": "specialist_parse", "call": n,
              "delegation_id_found": bool(delegation_id),
              "instructions_len": len(text),
              "part_kinds": [
                  (p.part_kind, len(str(getattr(p, "content", "") or "")))
                  for m in messages for p in (m.parts or ())
              ],
              "info_instructions_head": str(
                  getattr(info, "instructions", "") or "")[:300],
              "text_head": text[:300]})
        if not delegation_id:
            raise RuntimeError("harness: delegation_id not found in pack")
        args = {
            "proposal_version": "specialist-result-proposal:v1",
            "delegation_id": delegation_id,
            "summary": (
                "Investigation completed honestly: the analyzed content "
                "contains no fraud-related financial activity."
            ),
            "claim_candidates": [],
            "evidence_refs": [],
            "limitations": ["no analyzable evidence of the queried activity"],
        }
        _log({"kind": "specialist_final", "call": n,
              "delegation_id": delegation_id[:40]})
        return ModelResponse(parts=[ToolCallPart(
            _first_tool(info), json.dumps(args))])

    def tripwire_function(messages, info):  # noqa: ANN001
        _log({"kind": "TRIPWIRE", "output_tools": len(
            getattr(info, "output_tools", None) or ())})
        raise RuntimeError(
            "rca2a2c harness tripwire: an unpatched model consumer tried "
            "to run; offline audit forbids any real provider call"
        )

    # ------------------------------------------------------------------
    # patch points (production instructions + output schemas preserved)
    # ------------------------------------------------------------------

    def _agent_with(function_model, builder):
        """Build the PRODUCTION agent, then swap only the model object.

        (Agent.model is a read-only property over _model; setting the
        private attribute is the exact seam pydantic-ai itself uses.)"""
        agent = builder()
        agent._model = function_model
        return agent

    _orig_plan_v2 = sup.SupervisorAgentFactory.build_plan_agent_v2

    def build_plan_agent_v2(self, planning_context, table):
        from httpserver.services.investigation.agent_integration_v2 import (
            SupervisorPlanDecisionV2,
            render_plan_context_v2,
        )

        projection = render_plan_context_v2(planning_context, table)
        return _agent_with(
            FunctionModel(plan_function),
            lambda: Agent(
                self._model,
                output_type=SupervisorPlanDecisionV2,
                instructions=[sup._planning_instructions_v2(projection)],
            ),
        )

    _orig_plan = sup.SupervisorAgentFactory.build_plan_agent

    def build_plan_agent(self, planning_context):
        return _agent_with(
            FunctionModel(plan_function_v1),
            lambda: Agent(
                self._model,
                output_type=sup.SupervisorPlanDecisionV1,
                instructions=[sup._planning_instructions(planning_context)],
            ),
        )

    _orig_int_v2 = sup.SupervisorAgentFactory.build_integration_agent_v2

    def build_integration_agent_v2(self, projection):
        from httpserver.services.investigation.agent_integration_v2 import (
            SupervisorIntegrationDecisionV2,
        )

        return _agent_with(
            FunctionModel(integrate_function),
            lambda: Agent(
                self._model,
                output_type=SupervisorIntegrationDecisionV2,
                instructions=[sup._integration_instructions_v2(projection)],
            ),
        )

    _orig_int = sup.SupervisorAgentFactory.build_integration_agent

    def build_integration_agent(self, integration_context):
        from httpserver.services.investigation.agent_integration import (
            SupervisorIntegrationDecisionV1,
        )

        return _agent_with(
            FunctionModel(integrate_function_v1),
            lambda: Agent(
                self._model,
                output_type=SupervisorIntegrationDecisionV1,
                instructions=[sup._integration_instructions(integration_context)],
            ),
        )

    sup.SupervisorAgentFactory.build_plan_agent_v2 = build_plan_agent_v2
    sup.SupervisorAgentFactory.build_plan_agent = build_plan_agent
    sup.SupervisorAgentFactory.build_integration_agent_v2 = (
        build_integration_agent_v2
    )
    sup.SupervisorAgentFactory.build_integration_agent = build_integration_agent

    spec_exec.SpecialistDelegationExecutor._get_model = (
        lambda self: FunctionModel(specialist_function)
    )
    adapter.build_chat_model = (
        lambda settings, *, model_name=None: FunctionModel(tripwire_function)
    )

    _log({
        "kind": "harness_installed",
        "scenario": _HARNESS_SCENARIO,
        "patched": [
            "SupervisorAgentFactory.build_plan_agent_v2",
            "SupervisorAgentFactory.build_plan_agent",
            "SupervisorAgentFactory.build_integration_agent_v2",
            "SupervisorAgentFactory.build_integration_agent",
            "SpecialistDelegationExecutor._get_model",
            "agent_model_adapter.build_chat_model (tripwire)",
        ],
    })


try:
    _install()
except Exception as _exc:  # noqa: BLE001 — never break the interpreter
    _log({"kind": "HARNESS_INSTALL_FAILED", "error": repr(_exc)})
