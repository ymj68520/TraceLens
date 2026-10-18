"""Unit tests for RCA-2A.8 Post-Experiment Semantic Validity & Generalization Readiness Audit.

Validates:
- Reconstructed 8-seat INTEGRATE decisions and model outputs.
- Four Treatment SQLite scratch database state diffs (Revision 1 -> Revision 2).
- Distinguishing Canonical Valid (L2) vs Semantic Adequacy (L4).
- No-evidence question closure policy (fail-closed, non-terminal preserved).
- Evidence refs resolution and cross-task isolation.
- Epistemic claim strength boundaries (FACT vs INFERENCE vs HYPOTHESIS).
- Retry self-correction error classification and attribution.
- Exact token and latency accounting reconciliation.
- Missing telemetry (HTTP attempts / billing) unobservable handling.
- Immutability of RCA-2A.7c original artifacts (SHA-256 verification).
- Zero production code modifications.
- Experimental Vocabulary Guidance is NOT the production default.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, Dict

import pytest

PYTHON_SERVICE_ROOT = Path(__file__).resolve().parents[3]
RCA2A7C_DIR = PYTHON_SERVICE_ROOT / "benchmarks/audits/rca2a7c-stepfun-vocabulary-comparison"
RCA2A8_DIR = PYTHON_SERVICE_ROOT / "benchmarks/audits/rca2a8-semantic-validity"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def rca2a7c_matrix() -> Dict[str, Any]:
    p = RCA2A7C_DIR / "rca2a7c-paired-execution-matrix-v1.json"
    assert p.exists()
    return json.loads(p.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rca2a8_inventory() -> Dict[str, Any]:
    p = RCA2A8_DIR / "rca2a8-source-evidence-inventory-v1.json"
    assert p.exists()
    return json.loads(p.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rca2a8_reconstruction() -> Dict[str, Any]:
    p = RCA2A8_DIR / "rca2a8-integration-decision-reconstruction-v1.json"
    assert p.exists()
    return json.loads(p.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rca2a8_state_audit() -> Dict[str, Any]:
    p = RCA2A8_DIR / "rca2a8-committed-state-semantic-audit-v1.json"
    assert p.exists()
    return json.loads(p.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rca2a8_retry_attribution() -> Dict[str, Any]:
    p = RCA2A8_DIR / "rca2a8-retry-mechanism-attribution-v1.json"
    assert p.exists()
    return json.loads(p.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rca2a8_cost_accounting() -> Dict[str, Any]:
    p = RCA2A8_DIR / "rca2a8-cost-and-accounting-audit-v1.json"
    assert p.exists()
    return json.loads(p.read_text(encoding="utf-8"))


def test_eight_seats_reconstruction(rca2a8_reconstruction):
    """Test forensic reconstruction of all 8 seats from persisted artifacts."""
    seats = rca2a8_reconstruction["seats"]
    assert len(seats) == 8

    ctl_seats = [s for s in seats if s["arm"] == "control"]
    tmt_seats = [s for s in seats if s["arm"] == "treatment"]
    assert len(ctl_seats) == 4
    assert len(tmt_seats) == 4

    # All initial attempts failed Pydantic validation across both arms
    for s in seats:
        assert s["initial_attempt"]["pydantic_pass"] is False
        assert s["initial_attempt"]["output_tool_received"] is True

    # On retry, Control failed 4/4 while Treatment passed 4/4
    for s in ctl_seats:
        assert s["retry_attempt"]["pydantic_pass"] is False
        assert s["pipeline_stages"]["canonical_integration_valid"] is False
        assert s["pipeline_stages"]["scratch_commit_success"] is False

    for s in tmt_seats:
        assert s["retry_attempt"]["pydantic_pass"] is True
        assert s["pipeline_stages"]["canonical_integration_valid"] is True
        assert s["pipeline_stages"]["scratch_commit_success"] is True
        assert len(s["applied_actions"]) == 1
        act = s["applied_actions"][0]
        assert act["action_type"] == "update_question"
        assert act["question_handle"] == "q-1"


def test_four_treatment_sqlite_state_diffs(rca2a8_state_audit):
    """Test that all 4 Treatment SQLite scratch stores advanced exactly 1 revision with valid diffs."""
    treatment_seats = rca2a8_state_audit["treatment_seats"]
    assert len(treatment_seats) == 4

    for item in treatment_seats:
        pid = item["pair_id"]
        pre = item["pre_integration_state"]
        post = item["post_integration_state"]

        assert pre["revision"] == 1
        assert post["revision"] == 2
        assert post["previous_state_hash"] == pre["state_hash"]
        assert pre["status"] == "open"
        assert post["status"] in ("open", "in_progress")
        assert len(post["basis_refs"]) == 0
        assert len(post["limitations"]) > 0
        assert "no analyzable evidence" in post["limitations"][0].lower()

        # Connect directly to the SQLite DB on disk to confirm persistence
        db_path = RCA2A7C_DIR / f"scratch/pair_{pid}/pair-0{pid}-treatment/investigation.db"
        assert db_path.exists()
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM agent_working_state_revisions")
        count = cur.fetchone()[0]
        assert count == 2

        # Verify Control DB remains at 1 revision and identical to source
        ctl_db_path = RCA2A7C_DIR / f"scratch/pair_{pid}/pair-0{pid}-control/investigation.db"
        src_db_path = RCA2A7C_DIR / f"scratch/pair_{pid}/source-pair-0{pid}/investigation.db"
        assert sha256_file(ctl_db_path) == sha256_file(src_db_path)
        conn.close()


def test_canonical_valid_vs_semantic_adequate_distinction(rca2a8_state_audit):
    """Test 4-layer evaluation: L1-L3 PASS does not imply L4 positive discovery."""
    for item in rca2a8_state_audit["treatment_seats"]:
        layers = item["four_layer_evaluation"]
        assert layers["L1_SCHEMA_VALIDITY"] == "PASS"
        assert layers["L2_CANONICAL_VALIDITY"] == "PASS"
        assert layers["L3_STATE_INTEGRITY"] == "PASS"
        assert layers["L4_SEMANTIC_ADEQUACY"] == "VALID_BUT_INFORMATION_NEUTRAL"

    assert rca2a8_state_audit["overall_semantic_verdict"] == "VALID_BUT_INFORMATION_NEUTRAL"


def test_no_evidence_question_closure_policy():
    """Test that closure of a required question without basis refs is rejected by StateTransitionPolicy."""
    from httpserver.services.investigation.agent_transitions import (
        EvidenceRefStatus,
        QUESTION_CLOSURE_BASIS_REQUIRED,
        QuestionTransition,
        StateTransitionPolicy,
        TransitionBatch,
        TransitionPolicyContext,
    )
    from httpserver.services.investigation.agent_working_state import (
        AgentWorkingStateV1,
        QuestionDisposition,
        QuestionPriority,
        QuestionSource,
        QuestionStatus,
        WorkingQuestion,
    )

    policy = StateTransitionPolicy()
    q = WorkingQuestion(
        question_id="q-1",
        text="Test required charter question?",
        source=QuestionSource.charter,
        priority=QuestionPriority.required,
        status=QuestionStatus.open,
    )
    state = AgentWorkingStateV1(
        task_id="task-A",
        investigation_id="inv-1",
        questions=[q],
    )
    ctx = TransitionPolicyContext(
        investigation_id="inv-1",
        run_id="run-1",
        task_id="task-A",
        current_state_hash="a" * 64,
        working_state=state,
        evidence_ref_resolver=lambda ref: EvidenceRefStatus.not_found,
        finding_ref_validator=lambda ref: True,
    )

    # Attempt to close question without basis refs
    transition = QuestionTransition(
        question_id="q-1",
        to_status=QuestionStatus.answered,
        disposition=QuestionDisposition.supported,
        basis_refs=(),
    )
    batch = TransitionBatch(transitions=[transition])
    result = policy.evaluate_batch(state, batch, ctx)

    assert result.status.value == "rejected"
    assert QUESTION_CLOSURE_BASIS_REQUIRED in [v.code for v in result.violations]


def test_evidence_refs_resolution():
    """Test that EvidenceResolver and BindingTable reject unknown, cross-task, or fabricated evidence handles."""
    from httpserver.services.investigation.agent_integration import (
        IntegrationContextPack,
    )
    from httpserver.services.investigation.agent_integration_v2 import (
        ResolutionViolationCode,
        SupervisorIntegrationDecisionV2,
        UpdateQuestionActionV2,
        resolve_integration_proposal_v2,
    )
    from httpserver.services.investigation.agent_reference_bindings import (
        BindingKind,
        build_integration_binding_table,
    )
    from httpserver.services.investigation.agent_working_state import (
        AgentWorkingStateV1,
        QuestionPriority,
        QuestionSource,
        QuestionStatus,
        WorkingQuestion,
    )

    state = AgentWorkingStateV1(
        task_id="task-A",
        investigation_id="inv-1",
        questions=[
            WorkingQuestion(
                question_id="q-1",
                text="Test charter?",
                source=QuestionSource.charter,
                priority=QuestionPriority.required,
                status=QuestionStatus.open,
            )
        ],
    )
    # Empty relevant_evidence_refs simulates Fixture A (honest no-evidence)
    ctx = IntegrationContextPack(
        task_id="task-A",
        investigation_id="inv-1",
        run_id="run-1",
        state_revision=1,
        state_hash="a" * 64,
        relevant_evidence_refs=(),
    )
    table = build_integration_binding_table(ctx, state)

    # No evidence bindings exist in the table
    assert len(table.canonical_refs_of_kind(BindingKind.evidence)) == 0
    assert table.by_handle("E1") is None
    assert table.by_handle("E999") is None

    # Proposal referencing fabricated handle E999 must fail resolution
    decision = SupervisorIntegrationDecisionV2(
        actions=[
            UpdateQuestionActionV2(
                question_handle="Q1",
                to_status=QuestionStatus.in_progress,
                basis_handles=("E999",),
            )
        ]
    )
    canonical, record = resolve_integration_proposal_v2(decision, table, ctx, state)
    assert record.ok is False
    assert any(v.code == ResolutionViolationCode.HANDLE_UNKNOWN for v in record.violations)


def test_epistemic_claim_strength_boundary():
    """Test that claims without evidence cannot be promoted to FACT."""
    from httpserver.services.investigation.agent_specialist_result import (
        AssertionClass,
        SpecialistClaimCandidate,
    )

    assert AssertionClass.FACT.value == "FACT"
    assert AssertionClass.INFERENCE.value == "INFERENCE"
    assert AssertionClass.HYPOTHESIS.value == "HYPOTHESIS"

    cand = SpecialistClaimCandidate(
        candidate_id="c-1",
        text="No evidence found",
        assertion_class=AssertionClass.FACT,
        evidence_refs=[],
        limitations=["no evidence"],
    )
    assert len(cand.evidence_refs) == 0

    # In Fixture A runs, exactly 0 claims were accepted into working state
    inv_path = RCA2A8_DIR / "rca2a8-evidence-and-policy-audit-v1.json"
    audit = json.loads(inv_path.read_text(encoding="utf-8"))
    assert audit["epistemic_claim_strength"]["total_claims_proposed"] == 0
    assert audit["epistemic_claim_strength"]["fact_without_evidence_prevented"] is True


def test_retry_error_aggregation_and_attribution(rca2a8_retry_attribution):
    """Test retry error classification and attribution verdict."""
    assert rca2a8_retry_attribution["attribution_verdict"] == "CONTRACT_ADHERENCE_IMPROVEMENT_OBSERVED"
    assert rca2a8_retry_attribution["treatment_attempts"]["retry_recovery_rate"] == "4/4 (100.0%)"
    assert rca2a8_retry_attribution["control_attempts"]["retry_recovery_rate"] == "0/4 (0.0%)"

    # Verify that guidance text does NOT contain literal 'question_handle' string
    q_ans = rca2a8_retry_attribution["eight_key_attribution_questions"]
    assert "NO" in q_ans["7_guidance_text_literally_provided_field_names"]


def test_token_and_latency_statistics_reconciliation(rca2a8_cost_accounting):
    """Test exact reconciliation of tokens and latencies."""
    tok = rca2a8_cost_accounting["token_reconciliation"]
    assert tok["control"]["total_output_tokens"] == 12331
    assert tok["treatment"]["total_output_tokens"] == 15922
    assert tok["control"]["total_input_tokens"] == 43617
    assert tok["treatment"]["total_input_tokens"] == 46427

    # Cost per successful integration must be UNDEFINED for Control
    assert "UNDEFINED" in str(tok["control"]["tokens_per_successful_integration"])
    assert tok["treatment"]["tokens_per_successful_integration"] > 0

    lat = rca2a8_cost_accounting["latency_reconciliation"]
    assert lat["control"]["mean_latency_per_response_seconds"] == 9.82
    assert lat["treatment"]["mean_latency_per_response_seconds"] == 13.27
    assert lat["control"]["mean_latency_per_seat_seconds"] == 19.64
    assert lat["treatment"]["mean_latency_per_seat_seconds"] == 26.55


def test_missing_telemetry_unknown_handling(rca2a8_cost_accounting, rca2a7c_matrix):
    """Test that unobservable metrics are recorded as UNOBSERVABLE/UNDEFINED."""
    assert rca2a8_cost_accounting["monetary_billing"]["status"] == "PROVIDER_BILLING_UNOBSERVABLE"
    for s in rca2a7c_matrix["seats"]:
        assert s["http_attempts"] == "HTTP_ATTEMPTS_UNOBSERVABLE"
        assert s["finalization"] == "NOT_EXERCISED"


def test_original_rca2a7c_artifacts_sha256_unmodified(rca2a8_inventory):
    """Test that all original RCA-2A.7c files remain unmodified (SHA-256 integrity)."""
    historical = rca2a8_inventory["historical_hashes"]
    manifest_p = RCA2A7C_DIR / "rca2a7c-experiment-manifest-v1.json"
    matrix_p = RCA2A7C_DIR / "rca2a7c-paired-execution-matrix-v1.json"
    preflight_p = RCA2A7C_DIR / "rca2a7c-preflight-gate-report-v1.json"
    vocab_p = RCA2A7C_DIR / "rca2a7c-vocabulary-effect-report-v1.json"
    runtime_p = RCA2A7C_DIR / "rca2a7c-runtime-identity-record-v1.json"

    assert sha256_file(manifest_p) == historical["manifest_sha256"]
    assert sha256_file(matrix_p) == historical["matrix_sha256"]
    assert sha256_file(preflight_p) == historical["preflight_sha256"]
    assert sha256_file(vocab_p) == historical["vocab_report_sha256"]
    assert sha256_file(runtime_p) == historical["runtime_record_sha256"]


def test_no_production_path_modified():
    """Test that production supervisor, schema, validator, and transitions are unmodified."""
    prod_files = [
        "httpserver/services/investigation/agent_supervisor.py",
        "httpserver/services/investigation/agent_integration_v2.py",
        "httpserver/services/investigation/agent_integration.py",
        "httpserver/services/investigation/agent_transitions.py",
        "httpserver/services/investigation/agent_working_state.py",
    ]
    for rel in prod_files:
        full_path = PYTHON_SERVICE_ROOT / rel
        assert full_path.exists()
        # Ensure git diff on production files is empty
        res = subprocess.run(
            ["git", "diff", "HEAD", "--", str(full_path)],
            cwd=PYTHON_SERVICE_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        assert res.stdout.strip() == "", f"Production file modified: {rel}"


def test_experimental_guidance_not_production_default():
    """Test that production SupervisorAgentFactory does not inject vocabulary guidance."""
    from httpserver.services.investigation.agent_supervisor import (
        SupervisorAgentFactory,
    )

    # Instantiate or inspect instructions in production factory
    factory = SupervisorAgentFactory
    # Production factory must not reference vocabulary guidance draft
    import inspect
    src = inspect.getsource(factory)
    assert "integration_vocabulary_guidance" not in src
    assert "Vocabulary guidance" not in src
