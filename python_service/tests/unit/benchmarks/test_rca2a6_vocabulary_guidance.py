"""RCA-2A.6 — vocabulary guidance: offline contract tests.

All deterministic, zero real model calls.  What these tests prove:

  - the guidance text is GENERATED from the production enums and
    self-verifies (no second state definition);
  - the experimental factory is INTEGRATE-only and the production
    PLAN/Specialist instruction builders are byte-identical with the
    module imported (no leak, no monkeypatching);
  - control vs treatment captures differ by EXACTLY the guidance
    suffix — schema, settings, tool names and projection are
    byte-identical;
  - through the FULL production stage path with the guidance present:
    legal actions stay legal, ``completed`` stays rejected, closures
    stay fail-closed, fabricated basis stays rejected, disposition and
    to_status stay non-interchangeable;
  - the four pre-call gates (INPUT_IDENTITY / PROMPT_DIFF /
    SCHEMA_UNCHANGED / DIAGNOSTICS_READY) hold.

What they CANNOT prove: that a model would comply with the guidance —
that is the pre-registered controlled comparison's purpose only.
"""

from __future__ import annotations

import inspect
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from benchmarks.contracts.experimental import (
    integration_vocabulary_guidance_v1 as guidance,
)
from benchmarks.contracts.experimental.integration_vocabulary_guidance_v1 import (
    GuidanceIntegrationAgentFactory,
)
from benchmarks.isolated_integration.fixtures import (
    prepare_post_delegation_store,
)
from benchmarks.isolated_integration.harness import (
    IsolatedIntegrationHarness,
)
from benchmarks.isolated_integration.harness import (
    validate_isolated_input,
)
from httpserver.services.investigation.agent_failure_diagnostics import (
    JsonlFailureDiagnosticSink,
    schema_hash_of,
)
from httpserver.services.investigation.agent_integration_v2 import (
    SupervisorIntegrationDecisionV2,
)
from httpserver.services.investigation.agent_supervisor import (
    SupervisorAgentFactory,
)

pytest.importorskip("pydantic_ai")
pytestmark = pytest.mark.migration_matrix

PYTHON_SERVICE_ROOT = Path(__file__).resolve().parents[3]
PARENT_DIR = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "audits"
    / "rca2a4-stepfun-isolated-integration"
)
RUNTIME_IDENTITY = {
    "baseline_commit": "85ab57523c966576b080846a6721e79ffa990b23",
    "harness": "rca2a6-deterministic-tests",
    "specialist_result_kind": "SYNTHETIC_SPECIALIST_RESULT",
}


def _fn(payload: dict):
    def model_fn(messages, info):  # noqa: ANN001
        from pydantic_ai.messages import ModelResponse, ToolCallPart

        return ModelResponse(parts=[ToolCallPart(
            info.output_tools[0].name, json.dumps(payload))])

    model_fn.__name__ = "rca2a6_test_model_fn"
    return model_fn


async def _prepared_harness(tmp_path, scenario: str):
    prepared = await prepare_post_delegation_store(
        tmp_path / scenario, with_evidence=False)
    return prepared, IsolatedIntegrationHarness(
        db_path=prepared.db_path,
        task_id=prepared.task_id,
        investigation_id=prepared.investigation_id,
        run_id=prepared.run_id,
        runtime_identity=RUNTIME_IDENTITY,
    )


# ---------------------------------------------------------------------------
# guidance text generation & self-verification
# ---------------------------------------------------------------------------


def test_guidance_generated_from_enums_and_self_verified():
    assert guidance.guidance_violations() == []
    # deterministic regeneration, never hand-maintained lists
    assert guidance.build_vocabulary_guidance_text() == guidance.GUIDANCE_TEXT
    statuses = list(guidance.question_status_vocabulary())
    dispositions = list(guidance.question_disposition_vocabulary())
    from httpserver.services.investigation.agent_working_state import (
        QuestionDisposition,
        QuestionStatus,
    )

    assert statuses == [m.value for m in QuestionStatus]
    assert dispositions == [m.value for m in QuestionDisposition]
    # the two clarifying claims the guidance exists for
    assert "completed" not in statuses
    assert "not_supported" in dispositions
    assert "not_supported" not in statuses
    # it never invents concrete handles
    import re

    assert not re.findall(r"\b(?:COV)?[EQHXFP]\d+\b", guidance.GUIDANCE_TEXT)


def test_guidance_factory_is_integrate_only():
    factory = GuidanceIntegrationAgentFactory(
        model=object())  # never built; construction only
    with pytest.raises(AttributeError, match="INTEGRATE-only"):
        factory.build_plan_agent_v2(None, None)  # type: ignore[attr-defined]
    with pytest.raises(AttributeError, match="INTEGRATE-only"):
        factory.build_plan_agent(None)  # type: ignore[attr-defined]


def test_production_instruction_builders_untouched_by_import():
    """Byte-identical function sources in a fresh interpreter (no
    experimental import) prove the guidance module monkeypatches
    nothing; plus the PLAN instructions contain no guidance text."""
    from httpserver.services.investigation import agent_supervisor as sup

    probe = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, '.'); "
         "import inspect; "
         "from httpserver.services.investigation import agent_supervisor "
         "as s; "
         "assert not any('integration_vocabulary_guidance' in k "
         "for k in sys.modules); "
         "print('===BEGIN==='); "
         "print(inspect.getsource(s._integration_instructions_v2) + "
         "'@#@' + inspect.getsource(s._planning_instructions_v2))"],
        cwd=str(PYTHON_SERVICE_ROOT), capture_output=True, text=True)
    assert probe.returncode == 0
    fresh_sources = probe.stdout.split("===BEGIN===", 1)[1].strip()
    fresh_sources = [part.strip() for part in fresh_sources.split("@#@")]
    assert inspect.getsource(
        sup._integration_instructions_v2).strip() == fresh_sources[0]
    assert inspect.getsource(
        sup._planning_instructions_v2).strip() == fresh_sources[1]
    # guidance text can never appear in any production instruction
    # builder's source
    assert "GUIDANCE" not in fresh_sources[0]


# ---------------------------------------------------------------------------
# control vs treatment capture parity
# ---------------------------------------------------------------------------


async def test_capture_differs_exactly_by_guidance_suffix(tmp_path):
    prepared, harness = await _prepared_harness(tmp_path, "capture")
    control = await harness.capture_model_visible_input()
    treatment = await harness.capture_model_visible_input(
        agent_factory=GuidanceIntegrationAgentFactory)

    # schema/settings/names/projection byte-identical
    assert control["output_tool_schemas"] == treatment["output_tool_schemas"]
    assert control["output_tool_names"] == treatment["output_tool_names"]
    assert control["model_settings"] == treatment["model_settings"]
    assert control["projection"] == treatment["projection"]
    # instructions differ by EXACTLY the frozen suffix
    assert treatment["instructions"] == (
        control["instructions"] + "\n\n" + guidance.GUIDANCE_TEXT)
    # the guidance names no concrete handles and adds no schema
    assert guidance.GUIDANCE_TEXT not in control["instructions"]


async def test_pre_call_gates_hold_on_frozen_2a4_store(tmp_path):
    fixture = json.loads(
        (PARENT_DIR / "scratch" / "fixture-identity.json")
        .read_text(encoding="utf-8"))
    harness = IsolatedIntegrationHarness(
        db_path=PARENT_DIR / "scratch" / "fixture-a" / "investigation.db",
        task_id=fixture["task_id"],
        investigation_id=fixture["investigation_id"],
        run_id=fixture["run_id"],
        runtime_identity=RUNTIME_IDENTITY,
    )
    # INPUT_IDENTITY_PASS: frozen store re-derivation
    contract = harness.isolated_input()
    assert validate_isolated_input(contract) == []
    assert contract["integration_context_hash"] == (
        fixture["integration_context_hash"])
    assert contract["output_schema_hash"] == fixture["output_schema_hash"]
    assert contract["output_schema_hash"] == schema_hash_of(
        SupervisorIntegrationDecisionV2)
    # PROMPT_DIFF_PASS + SCHEMA_UNCHANGED on the frozen context
    control = await harness.capture_model_visible_input()
    treatment = await harness.capture_model_visible_input(
        agent_factory=GuidanceIntegrationAgentFactory)
    assert treatment["instructions"] == (
        control["instructions"] + "\n\n" + guidance.GUIDANCE_TEXT)
    assert control["output_tool_schemas"] == treatment["output_tool_schemas"]


async def test_diagnostics_ready_through_both_arms(tmp_path):
    from pydantic_ai.exceptions import UnexpectedModelBehavior

    bad_payload = {"actions": [{"action_type": "update_question",
                                "question_handle": "Q1",
                                "to_status": "completed"}]}
    for arm_factory in (SupervisorAgentFactory,
                        GuidanceIntegrationAgentFactory):
        prepared, harness = await _prepared_harness(
            tmp_path, f"diag-{arm_factory.__name__}")
        sink_path = (tmp_path / f"{arm_factory.__name__}.jsonl").resolve()
        sink = JsonlFailureDiagnosticSink(sink_path)
        result = await harness.run_stage(
            _fn(bad_payload), diagnostic_sink=sink,
            agent_factory=arm_factory)
        assert not result.committed
        assert result.exception_class == "UnexpectedModelBehavior"
        lines = [json.loads(line)
                 for line in sink_path.read_text().splitlines()
                 if line.strip()]
        entry = lines[-1]
        assert entry["stage"] == "SUPERVISOR_INTEGRATE"
        assert entry["schema_hash"] == schema_hash_of(
            SupervisorIntegrationDecisionV2)
        assert entry["tool_name"] == "final_result"
        assert entry["validation_error_details"]
        assert (sink_path.stat().st_mode & 0o777) == 0o600


# ---------------------------------------------------------------------------
# full-path behavior with guidance present
# ---------------------------------------------------------------------------


LEGAL_PAYLOAD = {
    "actions": [{"action_type": "update_question",
                 "question_handle": "Q1", "to_status": "in_progress",
                 "investigated_summary": "advanced"}],
    "integration_summary": "advanced", "limitations": [], "warnings": []}


async def test_legal_action_still_commits_and_matches_control(tmp_path):
    control_prepared, control_harness = await _prepared_harness(
        tmp_path, "legal-control")
    treatment_prepared, treatment_harness = await _prepared_harness(
        tmp_path, "legal-treatment")
    control = await control_harness.run_stage(
        _fn(LEGAL_PAYLOAD), agent_factory=SupervisorAgentFactory)
    treatment = await treatment_harness.run_stage(
        _fn(LEGAL_PAYLOAD), agent_factory=GuidanceIntegrationAgentFactory)
    for result in (control, treatment):
        assert [s.name for s in result.steps] == [
            "model_output_received", "pydantic_validation",
            "canonical_resolution", "decision_validator",
            "transition_validation", "integration_commit"]
        assert result.committed


async def test_completed_still_rejected_with_guidance(tmp_path):
    payload = {"actions": [{"action_type": "update_question",
                            "question_handle": "Q1",
                            "to_status": "completed",
                            "disposition": "not_supported"}]}
    _, harness = await _prepared_harness(tmp_path, "completed")
    result = await harness.run_stage(
        _fn(payload), agent_factory=GuidanceIntegrationAgentFactory)
    assert not result.committed
    assert result.exception_class == "UnexpectedModelBehavior"
    assert not any(s.ok and s.name == "pydantic_validation"
                   for s in result.steps)


@pytest.mark.parametrize(
    "to_status,expected_codes",
    [
        ("answered", ["QUESTION_CLOSURE_BASIS_REQUIRED",
                      "QUESTION_CLOSURE_VERIFICATION_REQUIRED"]),
        ("unresolved", ["QUESTION_CLOSURE_BASIS_REQUIRED"]),
        ("blocked", ["QUESTION_BLOCKER_REQUIRED"]),
    ],
)
async def test_closures_still_fail_closed_with_guidance(
        tmp_path, to_status, expected_codes):
    payload = {"actions": [{"action_type": "update_question",
                            "question_handle": "Q1",
                            "to_status": to_status,
                            "disposition": "not_supported"
                            if to_status == "answered" else None}]}
    payload["actions"][0] = {
        k: v for k, v in payload["actions"][0].items() if v is not None}
    _, harness = await _prepared_harness(tmp_path, f"closure-{to_status}")
    result = await harness.run_stage(
        _fn(payload), agent_factory=GuidanceIntegrationAgentFactory)
    steps = {s.name: s for s in result.steps}
    assert steps["pydantic_validation"].ok
    assert steps["canonical_resolution"].ok
    assert not steps["transition_validation"].ok
    assert steps["transition_validation"].detail["codes"] == expected_codes
    assert not result.committed


async def test_fabricated_basis_still_rejected_with_guidance(tmp_path):
    payload = {"actions": [{"action_type": "update_question",
                            "question_handle": "Q1",
                            "to_status": "answered",
                            "disposition": "not_supported",
                            "basis_handles": ["E1"]}]}
    _, harness = await _prepared_harness(tmp_path, "fabricated")
    result = await harness.run_stage(
        _fn(payload), agent_factory=GuidanceIntegrationAgentFactory)
    assert not result.committed
    assert list(result.resolution_violations) == ["HANDLE_UNKNOWN"]


async def test_not_supported_as_status_still_rejected_with_guidance(
        tmp_path):
    payload = {"actions": [{"action_type": "update_question",
                            "question_handle": "Q1",
                            "to_status": "not_supported"}]}
    # schema-level proof that disposition and status vocabularies stay
    # disjoint
    with pytest.raises(ValidationError):
        SupervisorIntegrationDecisionV2.model_validate(payload)
    _, harness = await _prepared_harness(tmp_path, "confusion")
    result = await harness.run_stage(
        _fn(payload), agent_factory=GuidanceIntegrationAgentFactory)
    assert not result.committed
    assert result.exception_class == "UnexpectedModelBehavior"


def test_deliverable_artifacts_coherent():
    audit = (PYTHON_SERVICE_ROOT / "benchmarks" / "audits"
             / "rca2a6-vocabulary-guidance")
    consistency = json.loads(
        (audit / "rca2a6-prompt-contract-consistency-report-v1.json")
        .read_text(encoding="utf-8"))
    offline = json.loads(
        (audit / "rca2a6-offline-validation-report-v1.json").read_text(
            encoding="utf-8"))
    protocol = json.loads(
        (audit / "rca2a6-controlled-comparison-protocol-v1.json")
        .read_text(encoding="utf-8"))
    assert consistency["verdict"] == "PROMPT_CONTRACT_CONSISTENT"
    assert consistency["guidance"]["sha256"] == guidance.guidance_sha256()
    assert offline["verdict"] == "NO_CONFLICT_WITH_EXISTING_CONTRACT"
    assert offline["disposition"] == (
        "VOCABULARY_CANDIDATE_READY_FOR_COMPARISON")
    assert protocol["status"] == "PREREGISTERED__NOT_EXECUTED"
    assert protocol["arms"]["treatment"]["guidance_sha256"] == (
        guidance.guidance_sha256())
    assert protocol["sample_counts"]["total_stage_invocations"] == 8
    assert list(protocol["metrics"]["primary"]) == [
        "canonical_integration_valid"]
    assert protocol["analysis_method"]["statistical_testing"].startswith(
        "none")
