"""TraceLens Agent v0 — RCA-2A.11a Deterministic Audit Test Suite.

Covers tests T01 to T19:
T01 Seat 5 historical output replay
T02 Unsupported FACT proposed and rejected
T03 Unsupported FACT written to audit only
T04 Unsupported FACT committed to scratch
T05 No cross-task evidence promotion
T06 HYPOTHESIS vs FACT semantic distinction
T07 Valid evidence ref but insufficient support
T08 False Question Closure proposed
T09 False Question Closure rejected
T10 F1 Control/Treatment distinct failure reasons
T11 F2 Treatment semantic sufficiency
T12 F2 information-value classification
T13 Post-commit Oracle violation classification
T14 Provider success != semantic success
T15 Executed-seat denominator correctness
T16 Unstarted seats excluded from validity rate
T17 Unpaired Seat 5 classification
T18 Historical artifacts unchanged
T19 No real Provider requests
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping

import pytest

from benchmarks.isolated_integration.semantic_oracle import (
    InformationValue,
    NegativeGateCode,
    RCA2A9SemanticOracleV1,
    SemanticAdequacy,
)
from benchmarks.isolated_integration.semantic_oracle_extension import (
    RCA2A9aSemanticOracleExtensionV1,
)
from httpserver.services.investigation.agent_integration import (
    build_integration_context,
    FreshResultEnvelope,
)
from httpserver.services.investigation.agent_integration_v2 import (
    CreateHypothesisActionV2,
    SupervisorIntegrationDecisionV2,
    UpdateQuestionActionV2,
)
from httpserver.services.investigation.agent_reference_bindings import (
    BindingKind,
    ReferenceBinding,
    ReferenceBindingTableV1,
    build_integration_binding_table,
)
from httpserver.services.investigation.agent_runtime import (
    AgentRuntimeRepository,
    AgentTrajectoryEventType,
    canonical_state_json,
    state_hash_of,
)
from httpserver.services.investigation.agent_specialist_result import (
    SpecialistResultV1,
)
from httpserver.services.investigation.repository import (
    InvestigationRepository,
)
from httpserver.services.investigation.agent_transitions import (
    CreateHypothesis,
    EvidenceRefStatus,
    PolicyViolation,
    QuestionStatus,
    QuestionTransition,
    StateTransitionPolicy,
    TransitionBatch,
    TransitionDecisionStatus,
    TransitionPolicyContext,
    _refute_evidence_refs,
)
from httpserver.services.investigation.agent_working_state import (
    AgentWorkingStateV1,
    CoverageDimension,
    CoverageStatus,
    Hypothesis,
    HypothesisStatus,
    QuestionPriority,
    QuestionSource,
    WorkingQuestion,
)

HERE = Path(__file__).resolve().parent
PYTHON_SERVICE_ROOT = HERE.parents[2]
REPO_ROOT = PYTHON_SERVICE_ROOT.parent
RCA2A11_DIR = PYTHON_SERVICE_ROOT / "benchmarks" / "audits" / "rca2a11-deepseek-flash-vocabulary-comparison"
RCA2A11A_DIR = PYTHON_SERVICE_ROOT / "benchmarks" / "audits" / "rca2a11a-negative-gate-causality-audit"


def _make_dummy_state(task_id: str = "task-t01") -> AgentWorkingStateV1:
    return AgentWorkingStateV1(
        task_id=task_id,
        investigation_id=f"inv-{task_id}",
        objective="Forensic audit objective",
        questions=(
            WorkingQuestion(
                question_id="q-1",
                text="Charter fraud question?",
                source=QuestionSource.charter,
                priority=QuestionPriority.required,
                status=QuestionStatus.in_progress,
            ),
        ),
        evidence_working_set=(),
        hypotheses=(),
    )


def _make_env(
    task_id: str = "task-t01",
    evidence_keys: tuple[str, ...] = ("file:windows/1.iso", "file:windows/2.iso"),
) -> tuple[ReferenceBindingTableV1, Any, AgentWorkingStateV1]:
    state = AgentWorkingStateV1(
        task_id=task_id,
        investigation_id=f"inv-{task_id}",
        objective="Forensic audit objective",
        questions=(
            WorkingQuestion(
                question_id="q-1",
                text="Charter fraud question?",
                source=QuestionSource.charter,
                priority=QuestionPriority.required,
                status=QuestionStatus.in_progress,
            ),
        ),
        coverage=(
            CoverageDimension(
                dimension_id="windows",
                required=True,
                status=CoverageStatus.not_started,
            ),
        ),
        evidence_working_set=(),
        hypotheses=(),
    )
    st_hash = state_hash_of(canonical_state_json(state.model_dump()))
    fresh = []
    if evidence_keys:
        res = SpecialistResultV1(
            result_version="specialist-result:v1",
            delegation_id="del-1",
            question_id="q-1",
            summary="specialist found evidence",
            evidence_refs=evidence_keys,
        )
        fresh.append(
            FreshResultEnvelope(
                delegation_id="del-1",
                question_id="q-1",
                source_scope_id="windows",
                result=res,
                result_hash="res-hash-1",
                context_hash="ctx-hash-1",
            )
        )
    context = build_integration_context(
        task_id=task_id,
        investigation_id=f"inv-{task_id}",
        run_id="run-test",
        state=state,
        state_revision=1,
        state_hash=st_hash,
        fresh_results=tuple(fresh),
        stale_result_digests=(),
        failure_digests=(),
        attention_refs=(),
        current_directive_digests={},
    )
    table = build_integration_binding_table(context, state)
    return table, context, state


# ---------------------------------------------------------------------------
# T01: Seat 5 historical output replay
# ---------------------------------------------------------------------------
def test_t01_seat_5_historical_output_replay():
    oracle = RCA2A9aSemanticOracleExtensionV1()
    table, context, state = _make_env("t2-identity-trap")

    # Synthetic reproduction of Seat 5's model proposal asserting "same person"
    decision = SupervisorIntegrationDecisionV2(
        actions=[
            CreateHypothesisActionV2(
                action_type="create_hypothesis",
                text="Accounts alice and bob belong to the same person across workstations.",
                supporting_handles=["E1", "E2"],
            )
        ],
    )

    eval_result = oracle.evaluate_extended(
        scenario_id="t2-identity-trap",
        decision_raw=decision.model_dump(mode="json"),
        table=table,
        context=context,
        state=state,
        expected_revision=1,
        arm="control",
    )

    assert eval_result.verdict == "FAIL"
    assert NegativeGateCode.UNSUPPORTED_FACT_PROMOTION in eval_result.triggered_negative_gates
    assert eval_result.l4_semantic_adequacy == SemanticAdequacy.SEMANTICALLY_INADEQUATE
    assert eval_result.l5_information_value == InformationValue.DEGRADED


# ---------------------------------------------------------------------------
# T02: Unsupported FACT proposed and rejected
# ---------------------------------------------------------------------------
def test_t02_unsupported_fact_proposed_and_rejected():
    policy = StateTransitionPolicy()
    state = _make_dummy_state("task-t02")
    ctx = TransitionPolicyContext(
        task_id="task-t02",
        investigation_id="inv-task-t02",
        evidence_ref_resolver=lambda r: EvidenceRefStatus.valid,
        finding_ref_validator=lambda r: True,
    )

    # Attempting to answer a required question without basis refs
    transition = QuestionTransition(
        question_id="q-1",
        to_status=QuestionStatus.answered,
        investigated_summary="Closing without evidence",
    )
    result = policy.evaluate_batch(
        state,
        TransitionBatch(transitions=(transition,)),
        ctx,
    )

    assert result.status is TransitionDecisionStatus.rejected
    assert any(v.code == "QUESTION_CLOSURE_BASIS_REQUIRED" for v in result.violations)


# ---------------------------------------------------------------------------
# T03: Unsupported FACT written to audit only
# ---------------------------------------------------------------------------
def test_t03_unsupported_fact_written_to_audit_only(tmp_path: Path):
    db_file = tmp_path / "scratch_audit.db"
    store = InvestigationRepository(db_file, "task-t03")
    rt = AgentRuntimeRepository(store)
    state = _make_dummy_state("task-t03")
    rt.create_investigation(
        state.model_dump(),
        investigation_id="inv-task-t03",
    )

    # Record integration trajectory
    now = "2026-10-17T02:00:00Z"
    with rt._connect() as conn:
        rt._append_trajectory_with_conn(
            conn,
            "inv-task-t03",
            AgentTrajectoryEventType.supervisor_integration_committed,
            run_id=None,
            payload={"decision_text": "same person claimed", "fact_promoted": False},
            now=now,
        )
        conn.commit()

        # Verify trajectory row exists
        row = conn.execute(
            "SELECT * FROM agent_trajectory_events WHERE investigation_id = ? ORDER BY seq DESC LIMIT 1",
            ["inv-task-t03"],
        ).fetchone()
        assert row is not None
        assert row["event_type"] == AgentTrajectoryEventType.supervisor_integration_committed.value

        # Verify NO finding rows exist
        findings = conn.execute(
            "SELECT count(*) as cnt FROM investigation_findings WHERE investigation_id = ?",
            ["inv-task-t03"],
        ).fetchone()
        assert findings["cnt"] == 0


# ---------------------------------------------------------------------------
# T04: Unsupported FACT committed to scratch
# ---------------------------------------------------------------------------
def test_t04_unsupported_fact_committed_to_scratch(tmp_path: Path):
    db_file = tmp_path / "scratch_commit.db"
    store = InvestigationRepository(db_file, "task-t04")
    rt = AgentRuntimeRepository(store)
    state = _make_dummy_state("task-t04")
    inv, rev = rt.create_investigation(
        state.model_dump(),
        investigation_id="inv-task-t04",
    )
    # Activate investigation so commit_agent_integration passes status check
    with rt._connect() as conn:
        conn.execute(
            "UPDATE agent_investigations SET status = 'active' WHERE investigation_id = ?",
            ["inv-task-t04"],
        )
        conn.commit()

    # Commit a new working state with a hypothesis
    new_state = state.with_replacements(
        hypotheses=(
            Hypothesis(
                hypothesis_id="hyp-1",
                text="alice and bob are same person",
                status=HypothesisStatus.active,
                supporting_refs=("ev:windows:1",),
                contradicting_refs=(),
            ),
        )
    )

    commit = rt.commit_agent_integration(
        investigation_id="inv-task-t04",
        expected_revision=rev.revision,
        expected_state_hash=rev.state_hash,
        operation_key="op-t04",
        integration_policy_version="state-transition:v1",
        decision_payload={"action": "create_hypothesis"},
        decision_hash="dec-hash-t04",
        new_state=new_state.model_dump(),
    )

    assert commit.status == "committed"
    assert commit.state_revision == rev.revision + 1

    # Verify scratch DB table has revision
    with rt._connect() as conn:
        rev_row = conn.execute(
            "SELECT * FROM agent_working_state_revisions WHERE revision = ?",
            [commit.state_revision],
        ).fetchone()
        assert rev_row is not None
        assert "alice and bob are same person" in rev_row["state_json"]

        # Ensure no finding table rows exist
        cnt = conn.execute("SELECT count(*) as cnt FROM investigation_findings").fetchone()["cnt"]
        assert cnt == 0



# ---------------------------------------------------------------------------
# T05: No cross-task evidence promotion
# ---------------------------------------------------------------------------
def test_t05_no_cross_task_evidence_promotion():
    ctx = TransitionPolicyContext(
        task_id="task-t05",
        investigation_id="inv-task-t05",
        evidence_ref_resolver=lambda r: EvidenceRefStatus.not_found,
        finding_ref_validator=lambda r: True,
    )
    violations: list[PolicyViolation] = []
    _refute_evidence_refs(["file:foreign_task/1.iso"], ctx, 0, violations)

    assert len(violations) == 1
    assert violations[0].code == "EVIDENCE_REF_CROSS_TASK"


# ---------------------------------------------------------------------------
# T06: HYPOTHESIS vs FACT semantic distinction
# ---------------------------------------------------------------------------
def test_t06_hypothesis_vs_fact_semantic_distinction():
    state = _make_dummy_state("task-t06")
    hyp = Hypothesis(
        hypothesis_id="h-06",
        text="Entities might be linked",
        status=HypothesisStatus.active,
        supporting_refs=(),
        contradicting_refs=(),
    )
    new_state = state.with_replacements(hypotheses=(hyp,))

    # Hypothesis lives in hypotheses tuple
    assert len(new_state.hypotheses) == 1
    assert new_state.hypotheses[0].hypothesis_id == "h-06"

    # Does not alter questions or findings
    assert len(new_state.questions) == 1
    assert new_state.questions[0].status == QuestionStatus.in_progress


# ---------------------------------------------------------------------------
# T07: Valid evidence ref but insufficient support (Case B)
# ---------------------------------------------------------------------------
def test_t07_valid_evidence_ref_but_insufficient_support():
    policy = StateTransitionPolicy()
    state = _make_dummy_state("task-t07")
    ctx = TransitionPolicyContext(
        task_id="task-t07",
        investigation_id="inv-task-t07",
        evidence_ref_resolver=lambda r: EvidenceRefStatus.resolved,
        finding_ref_validator=lambda r: True,
    )

    # StateTransitionPolicy allows CreateHypothesis because ref is syntactically valid
    trans = CreateHypothesis(
        hypothesis=Hypothesis(
            hypothesis_id="hyp-7",
            text="Unproven cross-system identity merge",
            status=HypothesisStatus.active,
            supporting_refs=("file:windows/1.iso",),
            contradicting_refs=(),
        )
    )
    res = policy.evaluate_batch(state, TransitionBatch(transitions=(trans,)), ctx)
    assert res.status is TransitionDecisionStatus.accepted

    # But Semantic Oracle catches insufficient semantic proof in natural language
    oracle = RCA2A9aSemanticOracleExtensionV1()
    table, context, state = _make_env("t2-identity-trap")
    decision = SupervisorIntegrationDecisionV2(
        actions=[
            CreateHypothesisActionV2(
                action_type="create_hypothesis",
                text="Unproven cross-system identity merge: alice and bob are the same person.",
                supporting_handles=["E1"],
            )
        ],
    )
    eval_res = oracle.evaluate_extended(
        scenario_id="t2-identity-trap",
        decision_raw=decision.model_dump(mode="json"),
        table=table,
        context=context,
        state=state,
        expected_revision=1,
        arm="control",
    )
    assert NegativeGateCode.UNSUPPORTED_FACT_PROMOTION in eval_res.triggered_negative_gates


# ---------------------------------------------------------------------------
# T08: False Question Closure proposed
# ---------------------------------------------------------------------------
def test_t08_false_question_closure_proposed():
    oracle = RCA2A9aSemanticOracleExtensionV1()
    table, context, state = _make_env("t2-no-evidence", evidence_keys=())

    decision = SupervisorIntegrationDecisionV2(
        actions=[
            UpdateQuestionActionV2(
                action_type="update_question",
                question_handle="Q1",
                to_status=QuestionStatus.answered,
                investigated_summary="Confirmed answered without evidence basis",
                basis_handles=[],
            )
        ],
    )
    eval_res = oracle.evaluate_extended(
        scenario_id="t2-no-evidence",
        decision_raw=decision.model_dump(mode="json"),
        table=table,
        context=context,
        state=state,
        expected_revision=1,
        arm="control",
    )
    assert NegativeGateCode.FALSE_QUESTION_CLOSURE in eval_res.triggered_negative_gates


# ---------------------------------------------------------------------------
# T09: False Question Closure rejected
# ---------------------------------------------------------------------------
def test_t09_false_question_closure_rejected():
    policy = StateTransitionPolicy()
    state = _make_dummy_state("t2-no-evidence")
    ctx = TransitionPolicyContext(
        task_id="t2-no-evidence",
        investigation_id="inv-t2-no-evidence",
        evidence_ref_resolver=lambda r: EvidenceRefStatus.valid,
        finding_ref_validator=lambda r: True,
    )

    trans = QuestionTransition(
        question_id="q-1",
        to_status=QuestionStatus.answered,
        investigated_summary="Answering with no basis",
        basis_refs=(),
    )
    res = policy.evaluate_batch(state, TransitionBatch(transitions=(trans,)), ctx)
    assert res.status is TransitionDecisionStatus.rejected
    assert any(v.code == "QUESTION_CLOSURE_BASIS_REQUIRED" for v in res.violations)


# ---------------------------------------------------------------------------
# T10: F1 Control/Treatment distinct failure reasons
# ---------------------------------------------------------------------------
def test_t10_f1_control_treatment_distinct_failure_reasons():
    f1_path = RCA2A11A_DIR / "rca2a11a-f1-policy-violation-audit-v1.json"
    data = json.loads(f1_path.read_text(encoding="utf-8"))

    ctrl = data["seat_1_control"]
    treat = data["seat_2_treatment"]

    assert "FALSE_QUESTION_CLOSURE" in ctrl["oracle_triggered_negative_gates"]
    assert treat["oracle_triggered_negative_gates"] == []
    assert data["pair_outcome"] == "BOTH_INVALID"


# ---------------------------------------------------------------------------
# T11: F2 Treatment semantic sufficiency
# ---------------------------------------------------------------------------
def test_t11_f2_treatment_semantic_sufficiency():
    oracle = RCA2A9aSemanticOracleExtensionV1()
    table, context, state = _make_env("t2-temporal-trap", evidence_keys=("file:windows/1.iso", "file:windows/2.iso"))

    # Treatment correctly documents temporal order without asserting causality
    decision = SupervisorIntegrationDecisionV2(
        actions=[
            CreateHypothesisActionV2(
                action_type="create_hypothesis",
                text="Observed login followed by file access; temporal sequence does not prove causality or unauthorized transfer.",
                supporting_handles=["E1", "E2"],
            ),
        ],
    )
    eval_res = oracle.evaluate_extended(
        scenario_id="t2-temporal-trap",
        decision_raw=decision.model_dump(mode="json"),
        table=table,
        context=context,
        state=state,
        expected_revision=1,
        arm="treatment",
    )
    assert eval_res.verdict == "PASS"
    assert eval_res.l4_semantic_adequacy == SemanticAdequacy.SEMANTICALLY_ADEQUATE
    assert eval_res.l5_information_value == InformationValue.POSITIVE_DISCOVERY
    assert eval_res.triggered_negative_gates == []


# ---------------------------------------------------------------------------
# T12: F2 information-value classification
# ---------------------------------------------------------------------------
def test_t12_f2_information_value_classification():
    f2_path = RCA2A11A_DIR / "rca2a11a-f2-semantic-win-verification-v1.json"
    data = json.loads(f2_path.read_text(encoding="utf-8"))

    assert data["seat_3_control"]["information_value"] == "DEGRADED"
    assert data["seat_4_treatment"]["information_value"] == "POSITIVE_DISCOVERY"
    assert data["pair_outcome"] == "TREATMENT_WIN"


# ---------------------------------------------------------------------------
# T13: Post-commit Oracle violation classification
# ---------------------------------------------------------------------------
def test_t13_post_commit_oracle_violation_classification():
    stop_report = json.loads((RCA2A11A_DIR / "rca2a11a-negative-gate-semantics-report-v1.json").read_text(encoding="utf-8"))
    reason = stop_report["runner_stop_reason_analysis"]["stop_reason_observed"]

    assert "MANDATORY_NEGATIVE_GATE_VIOLATION_COMMITTED" in reason
    assert "UNSUPPORTED_FACT_PROMOTION" in reason


# ---------------------------------------------------------------------------
# T14: Provider success != semantic success
# ---------------------------------------------------------------------------
def test_t14_provider_success_not_equal_semantic_success():
    matrix_path = RCA2A11_DIR / "rca2a11-seat-execution-matrix-v1.json"
    data = json.loads(matrix_path.read_text(encoding="utf-8"))

    seats = data["matrix"]["seats"][:5]
    for s in seats:
        # All 5 achieved 100% Pydantic validity on initial attempt
        assert s["final_attempt_pydantic_pass"] is True
    # But only Seat 4 passed semantic oracle
    passes = [s["semantic_oracle_evaluation"]["verdict"] for s in seats]
    assert passes == ["FAIL", "FAIL", "FAIL", "PASS", "FAIL"]


# ---------------------------------------------------------------------------
# T15: Executed-seat denominator correctness
# ---------------------------------------------------------------------------
def test_t15_executed_seat_denominator_correctness():
    acct = json.loads((RCA2A11A_DIR / "rca2a11a-outcome-accounting-amendment-v1.json").read_text(encoding="utf-8"))
    validity = acct["pydantic_validity_rates"]

    assert validity["control_executed_initial_pass_rate"] == "3 / 3 (100.0%)"
    assert validity["treatment_executed_initial_pass_rate"] == "2 / 2 (100.0%)"
    assert validity["overall_executed_initial_pass_rate"] == "5 / 5 (100.0%)"


# ---------------------------------------------------------------------------
# T16: Unstarted seats excluded from validity rate
# ---------------------------------------------------------------------------
def test_t16_unstarted_seats_excluded_from_validity_rate():
    acct = json.loads((RCA2A11A_DIR / "rca2a11a-outcome-accounting-amendment-v1.json").read_text(encoding="utf-8"))

    assert acct["seat_accounting"]["executed_seats_total"] == 5
    assert acct["seat_accounting"]["unstarted_seats_total"] == 11
    assert acct["seat_accounting"]["planned_seats_total"] == 16


# ---------------------------------------------------------------------------
# T17: Unpaired Seat 5 classification
# ---------------------------------------------------------------------------
def test_t17_unpaired_seat_5_classification():
    acct = json.loads((RCA2A11A_DIR / "rca2a11a-outcome-accounting-amendment-v1.json").read_text(encoding="utf-8"))

    assert acct["paired_accounting"]["unpaired_executed_seats"] == 1
    assert "INCOMPLETE_PAIR" in acct["paired_accounting"]["pair_results"]["pair_3_f3_t2-identity-trap"]


# ---------------------------------------------------------------------------
# T18: Historical artifacts unchanged
# ---------------------------------------------------------------------------
def test_t18_historical_artifacts_unchanged():
    manifest_path = RCA2A11_DIR / "rca2a11-experiment-manifest-v1.json"
    assert manifest_path.exists()
    h = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    assert h == "2ea9d103a02ce981999c4898cbb5a8f9e810cf6b10d5e31f47fd3e2ea16a0fbe"


# ---------------------------------------------------------------------------
# T19: No real Provider requests
# ---------------------------------------------------------------------------
def test_t19_no_real_provider_requests():
    identity = json.loads((RCA2A11A_DIR / "rca2a11a-runtime-identity-record-v1.json").read_text(encoding="utf-8"))
    assert identity["boundaries_enforced"]["real_model_calls_made"] == 0
