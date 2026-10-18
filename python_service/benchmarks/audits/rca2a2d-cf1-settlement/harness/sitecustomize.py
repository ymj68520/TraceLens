"""RCA-2A.2d CF-1 settlement harness — deterministic offline injection for
the REAL run_p8b_baseline CLI (extends the RCA-2A.2c mechanism).

Scenarios (env RCA2A2D_SCENARIO):
  valid            plan valid; honest specialist; integration commits
  invalid_union    plan FunctionModel emits the historical `type`
                   discriminant payload -> PLAN containment
  timeout          plan FunctionModel raises openai.APITimeoutError
  cancelled        plan FunctionModel raises asyncio.CancelledError
  integrate_invalid plan valid; integration FunctionModel emits a
                   KNOWN-ILLEGAL V2 action (extra tool_call_count field)
                   -> INTEGRATE containment (run failed by the orchestrator)
  sqlite_failure   valid run, but AgentRuntimeRepository.fail_run always
                   raises sqlite3.OperationalError -> the settlement write
                   itself fails
  task_deletion    valid run, but the investigation store is deleted right
                   before settlement -> settlement must not recreate it

Zero real model calls by construction (tripwire on the unpatched
model-construction seam). Evidence JSONL carries schemas/handles/calls
only — never case content, prompts, or keys.
"""

import json
import os
import sys

_SCENARIO = os.environ.get("RCA2A2D_SCENARIO", "valid")
_EVIDENCE = os.environ.get("RCA2A2C_EVIDENCE_PATH", "")


def _log(obj) -> None:
    if not _EVIDENCE:
        return
    try:
        with open(_EVIDENCE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def _install() -> None:
    python_service_root = os.environ.get("RCA2A2C_PY_SERVICE_ROOT", "")
    if python_service_root and python_service_root not in sys.path:
        sys.path.insert(0, python_service_root)

    import asyncio
    import httpx

    from pydantic_ai import Agent
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    from httpserver.services.investigation import agent_supervisor as sup
    from httpserver.services.investigation import (
        agent_specialist_executor as spec_exec,
    )
    from httpserver.services.investigation import agent_model_adapter as adapter

    _call_counters: dict = {}

    def _next_call(stage: str) -> int:
        _call_counters[stage] = _call_counters.get(stage, 0) + 1
        return _call_counters[stage]

    def _instruction_text(messages, info=None) -> str:
        chunks = []
        for message in messages:
            for part in getattr(message, "parts", ()) or ():
                content = getattr(part, "content", None)
                if isinstance(content, str):
                    chunks.append(content)
        info_instructions = getattr(info, "instructions", None)
        if isinstance(info_instructions, str):
            chunks.append(info_instructions)
        elif isinstance(info_instructions, (list, tuple)):
            chunks.extend(str(c) for c in info_instructions)
        return "\n".join(chunks)

    def _extract_json_blob(text: str, start_marker: str) -> dict:
        if start_marker not in text:
            raise RuntimeError(f"harness: marker missing: {start_marker!r}")
        blob = text.split(start_marker, 1)[1].split("\n\nRules:", 1)[0]
        return json.loads(blob)

    def _first_tool(info) -> str:
        tools = getattr(info, "output_tools", None) or ()
        if not tools:
            raise RuntimeError("harness: no output tool offered")
        return tools[0].name

    def _capture_output_schema(stage: str, info) -> None:
        for tool in getattr(info, "output_tools", None) or ():
            _log({
                "kind": "output_tool_schema", "stage": stage,
                "tool_name": tool.name,
                "parameters_json_schema": tool.parameters_json_schema,
            })

    def plan_function(messages, info):  # noqa: ANN001
        stage = "plan"
        _capture_output_schema(stage, info)
        n = _next_call(stage)
        if _SCENARIO == "timeout":
            from openai import APITimeoutError

            _log({"kind": "raised", "stage": stage, "call": n,
                  "exception": "openai.APITimeoutError"})
            raise APITimeoutError(request=httpx.Request(
                "POST", "http://127.0.0.1:9/v1/chat/completions"))
        if _SCENARIO == "cancelled":
            _log({"kind": "raised", "stage": stage, "call": n,
                  "exception": "asyncio.CancelledError"})
            raise asyncio.CancelledError()
        text = _instruction_text(messages, info)
        projection = _extract_json_blob(
            text, "supervisor plan decision (v2).\n\n")
        items = [i for i in projection.get("attention_items", [])
                 if i.get("eligibility") == "eligible"] or \
            projection.get("attention_items", [])
        attention = items[0]["handle"] if items else "A1"
        questions = projection.get("questions", [])
        question = questions[0]["handle"] if questions else "Q1"
        scope = (projection.get("source_scopes") or ["windows"])[0]
        if _SCENARIO == "invalid_union":
            action = {"type": "delegate_investigation",
                      "attention_handle": attention,
                      "question_handle": question,
                      "source_scope_id": scope}
        else:
            action = {"action_type": "delegate_investigation",
                      "attention_handle": attention,
                      "question_handle": question,
                      "source_scope_id": scope}
        args = {"decision_version": "supervisor-plan-decision:v2",
                "actions": [action],
                "summary": "delegate the charter question"}
        _log({"kind": "plan_action", "call": n,
              "discriminant_field": sorted(action)[0]})
        return ModelResponse(parts=[ToolCallPart(
            _first_tool(info), json.dumps(args))])

    def integrate_function(messages, info):  # noqa: ANN001
        stage = "integrate"
        _capture_output_schema(stage, info)
        n = _next_call(stage)
        text = _instruction_text(messages, info)
        projection = _extract_json_blob(text, "typed actions only.\n\n")
        questions = [q for q in projection.get("questions", [])
                     if q.get("status") in ("open", "in_progress")]
        question = questions[0]["handle"] if questions else "Q1"
        action = {"action_type": "update_question",
                  "question_handle": question,
                  "to_status": "in_progress",
                  "investigated_summary": (
                      "honest no-evidence investigation completed; nothing "
                      "fraud-related found")}
        if _SCENARIO == "integrate_invalid":
            # RCA-2A.2b gate's known-illegal shape: a runtime-owned field
            # the v2 schema structurally forbids -> extra_forbidden
            action["tool_call_count"] = 9
        args = {"actions": [action]}
        _log({"kind": "integrate_action", "call": n,
              "illegal_field": "tool_call_count" in action})
        return ModelResponse(parts=[ToolCallPart(
            _first_tool(info), json.dumps(args))])

    def plan_function_v1(messages, info):  # noqa: ANN001
        raise RuntimeError("harness: v1 plan unexpectedly invoked")

    def integrate_function_v1(messages, info):  # noqa: ANN001
        raise RuntimeError("harness: v1 integration unexpectedly invoked")

    def specialist_function(messages, info):  # noqa: ANN001
        stage = "specialist"
        n = _next_call(stage)
        if n == 1:
            tools = getattr(info, "function_tools", None) or ()
            search = next(
                (t for t in tools if "search" in (t.name or "")), None)
            if search is not None:
                schema = search.parameters_json_schema or {}
                args = {k: "fraud financial activity"
                        for k in schema.get("required", []) or []
                        if "query" in k or "text" in k or "term" in k}
                if not args:
                    args = {k: "" for k in schema.get("properties", {})}
                _log({"kind": "specialist_tool_call", "call": n,
                      "tool": search.name})
                return ModelResponse(parts=[ToolCallPart(
                    search.name, json.dumps(args))])
        text = _instruction_text(messages, info)
        delegation_id = ""
        if '"delegation_id"' in text:
            blob = text.split('"delegation_id"', 1)[1]
            for candidate in blob.replace("'", '"').split('"')[1::2]:
                if candidate and candidate != "-":
                    delegation_id = candidate
                    break
        if not delegation_id:
            raise RuntimeError("harness: delegation_id not found in pack")
        args = {
            "proposal_version": "specialist-result-proposal:v1",
            "delegation_id": delegation_id,
            "summary": (
                "Investigation completed honestly: the analyzed content "
                "contains no fraud-related financial activity."),
            "claim_candidates": [],
            "evidence_refs": [],
            "limitations": ["no analyzable evidence of the queried activity"],
        }
        _log({"kind": "specialist_final", "call": n,
              "delegation_id": delegation_id[:40]})
        return ModelResponse(parts=[ToolCallPart(
            _first_tool(info), json.dumps(args))])

    def tripwire_function(messages, info):  # noqa: ANN001
        _log({"kind": "TRIPWIRE"})
        raise RuntimeError(
            "rca2a2d harness tripwire: an unpatched model consumer tried "
            "to run; offline audit forbids any real provider call")

    def _agent_with(function_model, builder):
        agent = builder()
        agent._model = function_model
        return agent

    def build_plan_agent_v2(self, planning_context, table):
        from httpserver.services.investigation.agent_integration_v2 import (
            SupervisorPlanDecisionV2, render_plan_context_v2)

        projection = render_plan_context_v2(planning_context, table)
        return _agent_with(
            FunctionModel(plan_function),
            lambda: Agent(
                self._model,
                output_type=SupervisorPlanDecisionV2,
                instructions=[sup._planning_instructions_v2(projection)],
            ),
        )

    def build_plan_agent(self, planning_context):
        return _agent_with(
            FunctionModel(plan_function_v1),
            lambda: Agent(
                self._model,
                output_type=sup.SupervisorPlanDecisionV1,
                instructions=[sup._planning_instructions(planning_context)],
            ),
        )

    def build_integration_agent_v2(self, projection):
        from httpserver.services.investigation.agent_integration_v2 import (
            SupervisorIntegrationDecisionV2)

        return _agent_with(
            FunctionModel(integrate_function),
            lambda: Agent(
                self._model,
                output_type=SupervisorIntegrationDecisionV2,
                instructions=[sup._integration_instructions_v2(projection)],
            ),
        )

    def build_integration_agent(self, integration_context):
        from httpserver.services.investigation.agent_integration import (
            SupervisorIntegrationDecisionV1)

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
        build_integration_agent_v2)
    sup.SupervisorAgentFactory.build_integration_agent = build_integration_agent

    spec_exec.SpecialistDelegationExecutor._get_model = (
        lambda self: FunctionModel(specialist_function))
    adapter.build_chat_model = (
        lambda settings, *, model_name=None: FunctionModel(tripwire_function))

    if _SCENARIO == "sqlite_failure":
        import sqlite3

        from httpserver.services.investigation import agent_runtime as ar

        def failing_fail_run(self, *args, **kwargs):
            _log({"kind": "injected_fault", "operation": "fail_run"})
            raise sqlite3.OperationalError("injected settlement fault")

        ar.AgentRuntimeRepository.fail_run = failing_fail_run
        _log({"kind": "fault_installed", "target": "fail_run"})

    if _SCENARIO == "task_deletion":
        from httpserver.services.benchmarks import one_shot_settlement as oss

        original = oss.settle_one_shot_execution

        def deleting_settle(*, db_path, **kwargs):
            import contextlib

            db = str(db_path)
            for suffix in ("", "-wal", "-shm", "-journal"):
                with contextlib.suppress(FileNotFoundError):
                    os.remove(db + suffix)
            _log({"kind": "injected_fault", "operation": "store_deleted",
                  "db_existed_before": True})
            return original(db_path=db_path, **kwargs)

        oss.settle_one_shot_execution = deleting_settle
        _log({"kind": "fault_installed", "target": "settle_one_shot_execution"})

    _log({
        "kind": "harness_installed",
        "scenario": _SCENARIO,
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
