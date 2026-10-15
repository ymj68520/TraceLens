"""Tests for RCA-2A.9 Cross-Case Readiness & Semantic Oracle Freeze."""

import asyncio
import json
from pathlib import Path

import pytest

from benchmarks.contracts.experimental.integration_vocabulary_guidance_v1 import (
    guidance_sha256,
)
from benchmarks.isolated_integration.cross_case_fixtures import (
    SCENARIO_SPECS,
    build_cloned_cross_case_pair,
    prepare_cross_case_store,
    verify_cross_case_arm_parity,
    verify_cross_case_production_stage_parity,
    verify_evidence_integrity,
)
from benchmarks.isolated_integration.semantic_oracle import (
    InformationValue,
    NegativeGateCode,
    RCA2A9SemanticOracleV1,
    SemanticAdequacy,
    run_oracle_calibration,
)
from httpserver.services.investigation.agent_failure_diagnostics import schema_hash_of
from httpserver.services.investigation.agent_integration_v2 import (
    SupervisorIntegrationDecisionV2,
)


def test_frozen_hashes():
    """Verify that guidance and schema hashes remain strictly frozen."""
    assert guidance_sha256() == "e00c1549284cd4c5b98a24e0a7c064377a4aabcaaa74d9d344412c6247af5f29"
    assert schema_hash_of(SupervisorIntegrationDecisionV2) == "a214ec4f5e81fcbb"


def test_four_scenarios_defined():
    """Verify all four scenario specs are properly configured with expected properties."""
    assert len(SCENARIO_SPECS) == 4
    for sid in ("t2-no-evidence", "t2-temporal-trap", "t2-identity-trap", "t2-report-citation"):
        assert sid in SCENARIO_SPECS
        spec = SCENARIO_SPECS[sid]
        assert spec.tier == "T2"
        assert spec.charter_question
        assert spec.objective

    assert SCENARIO_SPECS["t2-no-evidence"].stage_applicability == "INTEGRATE_REPRESENTABLE"
    assert SCENARIO_SPECS["t2-temporal-trap"].stage_applicability == "INTEGRATE_REPRESENTABLE"
    assert SCENARIO_SPECS["t2-identity-trap"].stage_applicability == "INTEGRATE_REPRESENTABLE"
    assert SCENARIO_SPECS["t2-report-citation"].stage_applicability == "REQUIRES_ADAPTER"


@pytest.mark.asyncio
async def test_fixture_construction_and_parity(tmp_path):
    """Verify synthetic post-delegation fixture construction, production stage parity,

    evidence integrity, and cross-arm parity for all 4 scenarios.
    """
    for sid in SCENARIO_SPECS:
        s_dir = tmp_path / f"fixture-{sid}"
        s_dir.mkdir(parents=True)
        prep = await prepare_cross_case_store(s_dir, sid)

        # 1. Path A vs Path B parity
        parity = await verify_cross_case_production_stage_parity(prep)
        assert parity["parity_pass"], f"Production stage parity failed for {sid}"
        assert parity["verdict"] == "PRODUCTION_STAGE_PARITY_PASS"
        assert parity["instructions_equal"]
        assert parity["projection_equal"]
        assert parity["tools_equal"]
        assert parity["settings_equal"]

        # 2. Evidence integrity
        from benchmarks.isolated_integration.harness import IsolatedIntegrationHarness
        harness = IsolatedIntegrationHarness(
            db_path=prep.db_path,
            task_id=prep.task_id,
            investigation_id=prep.investigation_id,
            run_id=prep.run_id,
            runtime_identity={
                "baseline_commit": "test-commit",
                "harness": f"test-{sid}",
                "specialist_result_kind": "SYNTHETIC_SPECIALIST_RESULT",
            },
        )
        integrity = verify_evidence_integrity(prep, harness)
        assert integrity["integrity_pass"], f"Evidence integrity failed for {sid}"
        assert integrity["verdict"] == "EVIDENCE_INTEGRITY_PASS"
        assert integrity["fabricated_evidence_count"] == 0
        assert integrity["cross_task_leak_count"] == 0
        assert integrity["graph_id_as_evidence_count"] == 0
        assert integrity["analyst_note_as_evidence_count"] == 0

        # 3. Cross-arm parity on cloned physical SQLite
        pair_dir = tmp_path / f"cloned-{sid}"
        hc, ht, meta = await build_cloned_cross_case_pair(sid, 1, pair_dir)
        arm_parity = await verify_cross_case_arm_parity(sid, hc, ht)
        assert arm_parity["parity_pass"], f"Cross-arm parity failed for {sid}"
        assert arm_parity["verdict"] == "CROSS_ARM_PARITY_PASS"
        assert arm_parity["canonical_control_hash"] == arm_parity["canonical_treatment_hash"]
        assert arm_parity["instructions_exact_suffix"]


def test_oracle_calibration_suite():
    """Verify that all 14 calibration cases O1-O14 pass deterministically."""
    res = run_oracle_calibration()
    assert res["all_passed"]
    assert res["passed_cases"] == 14
    assert res["total_cases"] == 14


def test_negative_gates_trigger_fail_closed():
    """Verify that negative gates strictly trigger FAIL CLOSED."""
    oracle = RCA2A9SemanticOracleV1()
    from httpserver.services.investigation.agent_reference_bindings import (
        BindingKind,
        ReferenceBinding,
        ReferenceBindingTableV1,
    )
    from httpserver.services.investigation.agent_working_state import (
        AgentWorkingStateV1,
        QuestionPriority,
        QuestionSource,
        WorkingQuestion,
    )
    from httpserver.services.investigation.agent_integration import IntegrationContextPack

    table = ReferenceBindingTableV1(
        table_version="reference-binding-table:v1",
        task_id="t2-identity-trap",
        investigation_id="inv-t2-identity-trap",
        working_state_revision=1,
        context_hash="ctx-hash",
        bindings=(
            ReferenceBinding(handle="Q1", kind=BindingKind.question, canonical_ref="q-1"),
            ReferenceBinding(handle="E1", kind=BindingKind.evidence, canonical_ref="file:C/logs/app1.log"),
        ),
    )
    state = AgentWorkingStateV1(
        task_id="t2-identity-trap",
        investigation_id="inv-t2-identity-trap",
        objective="test",
        questions=(
            WorkingQuestion(question_id="q-1", text="charter?", source=QuestionSource.charter, priority=QuestionPriority.required),
        ),
    )
    context = IntegrationContextPack(
        task_id="t2-identity-trap",
        investigation_id="inv-t2-identity-trap",
        run_id="run-test",
        state_revision=1,
        state_hash="hash-1",
        fresh_results=(),
        stale_result_digests=(),
        failure_digests=(),
        attention_refs=(),
        current_directive_digests={},
    )

    # 1. Graph ID as evidence gate
    d_graph = {
        "decision_version": "supervisor-integration-decision:v3",
        "actions": [{
            "action_type": "update_question",
            "question_handle": "Q1",
            "to_status": "in_progress",
            "basis_handles": ["node_bad_id"],
        }],
        "integration_summary": "bad graph id",
    }
    r_graph = oracle.evaluate(scenario_id="t2-identity-trap", decision_raw=d_graph, table=table, context=context, state=state, expected_revision=1)
    assert r_graph.verdict == "FAIL"
    assert NegativeGateCode.GRAPH_ID_AS_EVIDENCE in r_graph.triggered_negative_gates

    # 2. Fabricated handle gate
    d_fab = {
        "decision_version": "supervisor-integration-decision:v3",
        "actions": [{
            "action_type": "update_evidence_relevance",
            "evidence_handle": "E999",
            "to_status": "relevant",
        }],
        "integration_summary": "fabricated handle",
    }
    r_fab = oracle.evaluate(scenario_id="t2-identity-trap", decision_raw=d_fab, table=table, context=context, state=state, expected_revision=1)
    assert r_fab.verdict == "FAIL"
    assert NegativeGateCode.FABRICATED_EVIDENCE in r_fab.triggered_negative_gates

    # 3. Cross task leak gate
    d_cross = {
        "decision_version": "supervisor-integration-decision:v3",
        "actions": [{
            "action_type": "update_question",
            "question_handle": "Q1",
            "to_status": "in_progress",
            "investigated_summary": "task-B:file:C/other.doc referenced",
        }],
        "integration_summary": "cross task leak",
    }
    r_cross = oracle.evaluate(scenario_id="t2-identity-trap", decision_raw=d_cross, table=table, context=context, state=state, expected_revision=1)
    assert r_cross.verdict == "FAIL"
    assert NegativeGateCode.CROSS_TASK_EVIDENCE in r_cross.triggered_negative_gates

    # 4. False question closure gate
    d_close = {
        "decision_version": "supervisor-integration-decision:v3",
        "actions": [{
            "action_type": "update_question",
            "question_handle": "Q1",
            "to_status": "answered",
        }],
        "integration_summary": "unbacked closure",
    }
    r_close = oracle.evaluate(scenario_id="t2-no-evidence", decision_raw=d_close, table=table, context=context, state=state, expected_revision=1)
    assert r_close.verdict == "FAIL"
    assert NegativeGateCode.FALSE_QUESTION_CLOSURE in r_close.triggered_negative_gates


def test_rca2a9_deliverables_exist():
    """Verify that all 10 RCA-2A.9 deliverables exist on disk and are valid JSON."""
    audit_dir = Path(__file__).resolve().parents[3] / "benchmarks" / "audits" / "rca2a9-cross-case-readiness"
    expected_files = [
        "rca2a9-scenario-capability-matrix-v1.json",
        "rca2a9-fixture-integrity-report-v1.json",
        "rca2a9-production-stage-parity-report-v1.json",
        "rca2a9-cross-arm-parity-report-v1.json",
        "rca2a9-semantic-oracle-v1.json",
        "rca2a9-oracle-calibration-report-v1.json",
        "rca2a9-cross-case-comparison-protocol-v1.json",
        "rca2a9-runtime-identity-record-v1.json",
        "rca2a9-readiness-decision-report-v1.json",
        "rca2a8-interpretation-amendment-v1.json",
    ]
    for filename in expected_files:
        p = audit_dir / filename
        assert p.exists(), f"Missing deliverable: {filename}"
        data = json.loads(p.read_text(encoding="utf-8"))
        assert "artifact_version" in data
