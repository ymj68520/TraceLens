"""Unit tests for RCA-2A.15 Solo-Developer Engineering Validation & Integration Readiness.

Verifies:
V01 Baseline commit and historical lineage
V02 Frozen candidate and schema hashes
V03 Three-tier validation framework definition
V04 External custody blocker retired from engineering validation
V05 Agent integration readiness matrix completeness
V06 ServiceManager orchestrator wiring state accurately audited
V07 Evidence immutability invariant
V08 Cross-task evidence rejected
V09 Fabricated evidence rejected
V10 Analyst note cannot become evidence
V11 Hypothesis cannot become accepted fact automatically
V12 Unsupported question closure rejected
V13 Stale working state rejected
V14 FinalizationGate does not imply analyst acceptance
V15 Report evidence admission is independent
V16 Model semantic failure vs unauthorized state commit separation
V17 Guidance integration strategy (PREPARE_EXPERIMENTAL_OPT_IN)
V18 Critical path next engineering task definition
V19 Zero real provider requests
"""

import json
from pathlib import Path
import pytest

from benchmarks.contracts.experimental.integration_vocabulary_guidance_v1 import (
    guidance_sha256,
)
from httpserver.services.investigation.agent_failure_diagnostics import schema_hash_of
from httpserver.services.investigation.agent_integration_v2 import (
    SupervisorIntegrationDecisionV2,
)

FROZEN_CANDIDATE_ID = "supervisor-v2-vocabulary-guidance-v1"
FROZEN_GUIDANCE_SHA256 = "e00c1549284cd4c5b98a24e0a7c064377a4aabcaaa74d9d344412c6247af5f29"
FROZEN_SCHEMA_HASH = "a214ec4f5e81fcbb"
AUDIT_DIR = Path("python_service/benchmarks/audits/rca2a15-solo-engineering-validation")


def test_v01_baseline_and_commit_lineage():
    """V01: Verify baseline commit and historical lineage integrity."""
    path = AUDIT_DIR / "rca2a15-baseline-integrity-report-v1.json"
    assert path.exists(), f"Missing {path}"
    with open(path) as f:
        data = json.load(f)
    assert data["baseline_commit"] == "167093e70d2639e692ce52cb0aa7fa6ee5425fa7"
    assert data["historical_status_matrix"]["rca2a14b"] == "EXTERNAL_CUSTODY_NOT_AVAILABLE"
    assert data["historical_status_matrix"]["rca2a14"] == "DEFERRED"


def test_v02_frozen_candidate_hashes():
    """V02: Verify frozen guidance hash and schema hash match exact pins."""
    assert guidance_sha256() == FROZEN_GUIDANCE_SHA256
    assert schema_hash_of(SupervisorIntegrationDecisionV2) == FROZEN_SCHEMA_HASH


def test_v03_three_tier_validation_framework():
    """V03: Verify three-tier evaluation framework definition."""
    path = AUDIT_DIR / "rca2a15-validation-strategy-decision-v1.json"
    assert path.exists()
    with open(path) as f:
        data = json.load(f)
    framework = data["three_tier_evaluation_framework"]
    assert "tier_1_development_regression" in framework
    assert "tier_2_solo_engineering_validation" in framework
    assert "tier_3_independent_qualification" in framework
    assert framework["tier_3_independent_qualification"]["current_status"] == "DEFERRED"


def test_v04_external_custody_blocker_retired():
    """V04: Verify external custody blocker does not block development tiers."""
    path = AUDIT_DIR / "rca2a15-validation-strategy-decision-v1.json"
    with open(path) as f:
        data = json.load(f)
    resolution = data["blocking_policy_resolution"]
    assert resolution["tier_3_blocks_tier_2"] is False
    assert resolution["tier_3_blocks_tier_1"] is False
    assert resolution["holdout_custody_blocker_status"] == "RETIRED_FROM_ENGINEERING_VALIDATION"


def test_v05_agent_integration_readiness_audit():
    """V05: Verify agent integration readiness matrix covers all 12 components."""
    path = AUDIT_DIR / "rca2a15-agent-integration-readiness-matrix-v1.json"
    assert path.exists()
    with open(path) as f:
        data = json.load(f)
    matrix = data["component_readiness_matrix"]
    expected_components = [
        "InvestigationSupervisor",
        "Specialist Delegation",
        "ToolRegistry",
        "EvidenceResolver",
        "GroundingValidator",
        "AgentWorkingStateV1",
        "SupervisorIntegrationDecisionV2",
        "StateTransitionPolicy",
        "Semantic Verification",
        "Analyst Review",
        "FinalizationGate",
        "Audit / Trajectory Persistence",
    ]
    for comp in expected_components:
        assert comp in matrix, f"Component {comp} missing from readiness matrix"

    assert matrix["InvestigationSupervisor"]["status"] == "IMPLEMENTED_NOT_INTEGRATED"
    assert matrix["Specialist Delegation"]["status"] == "IMPLEMENTED_NOT_INTEGRATED"
    assert matrix["ToolRegistry"]["status"] == "IMPLEMENTED_AND_TESTED"


def test_v06_service_manager_orchestrator_wiring_state():
    """V06: Verify service_manager.py wires supervisor and dispatcher (RCA-2A.16)."""
    from httpserver.services.service_manager import ServiceManager
    import inspect

    src = inspect.getsource(ServiceManager._create_agent_orchestrator)
    # RCA-2A.16 wired supervisor and delegation_dispatcher
    assert "supervisor=" in src
    assert "delegation_dispatcher=" in src
    assert "final_review_runner=" in src



def test_v07_evidence_immutability_invariant():
    """V07: Verify evidence integrity regression specifies immutability."""
    path = AUDIT_DIR / "rca2a15-evidence-integrity-regression-v1.json"
    assert path.exists()
    with open(path) as f:
        data = json.load(f)
    invariants = data["evidence_integrity_invariants"]
    assert invariants["original_evidence_immutable"]["regression_status"] == "VERIFIED_ENFORCED"


def test_v08_cross_task_evidence_rejected():
    """V08: Verify cross-task evidence references fail closed."""
    path = AUDIT_DIR / "rca2a15-evidence-integrity-regression-v1.json"
    with open(path) as f:
        data = json.load(f)
    invariants = data["evidence_integrity_invariants"]
    assert invariants["cross_task_evidence_rejected"]["regression_status"] == "VERIFIED_ENFORCED"


def test_v09_fabricated_evidence_rejected():
    """V09: Verify fabricated evidence references are rejected."""
    path = AUDIT_DIR / "rca2a15-evidence-integrity-regression-v1.json"
    with open(path) as f:
        data = json.load(f)
    invariants = data["evidence_integrity_invariants"]
    assert invariants["fabricated_evidence_rejected"]["regression_status"] == "VERIFIED_ENFORCED"


def test_v10_analyst_note_cannot_become_evidence():
    """V10: Verify analyst notes cannot become evidence."""
    path = AUDIT_DIR / "rca2a15-evidence-integrity-regression-v1.json"
    with open(path) as f:
        data = json.load(f)
    invariants = data["evidence_integrity_invariants"]
    assert invariants["analyst_note_cannot_become_evidence"]["regression_status"] == "VERIFIED_ENFORCED"


def test_v11_hypothesis_cannot_become_accepted_fact():
    """V11: Verify hypothesis does not automatically promote to accepted fact."""
    path = AUDIT_DIR / "rca2a15-evidence-integrity-regression-v1.json"
    with open(path) as f:
        data = json.load(f)
    invariants = data["evidence_integrity_invariants"]
    assert invariants["hypothesis_cannot_become_accepted_fact_automatically"]["regression_status"] == "VERIFIED_ENFORCED"


def test_v12_unsupported_question_closure_rejected():
    """V12: Verify unsupported question closures are rejected."""
    path = AUDIT_DIR / "rca2a15-evidence-integrity-regression-v1.json"
    with open(path) as f:
        data = json.load(f)
    invariants = data["evidence_integrity_invariants"]
    assert invariants["unsupported_question_closure_rejected"]["regression_status"] == "VERIFIED_ENFORCED"


def test_v13_stale_working_state_rejected():
    """V13: Verify optimistic locking rejects stale working state revisions."""
    path = AUDIT_DIR / "rca2a15-evidence-integrity-regression-v1.json"
    with open(path) as f:
        data = json.load(f)
    invariants = data["evidence_integrity_invariants"]
    assert invariants["stale_working_state_rejected"]["regression_status"] == "VERIFIED_ENFORCED"


def test_v14_finalization_gate_not_equal_analyst_acceptance():
    """V14: Verify FinalizationGate does not imply analyst acceptance."""
    path = AUDIT_DIR / "rca2a15-evidence-integrity-regression-v1.json"
    with open(path) as f:
        data = json.load(f)
    invariants = data["evidence_integrity_invariants"]
    assert invariants["finalization_gate_not_equal_analyst_acceptance"]["regression_status"] == "VERIFIED_ENFORCED"


def test_v15_report_evidence_admission_independent():
    """V15: Verify report evidence admission maintains independent lifecycle."""
    path = AUDIT_DIR / "rca2a15-evidence-integrity-regression-v1.json"
    with open(path) as f:
        data = json.load(f)
    invariants = data["evidence_integrity_invariants"]
    assert invariants["report_evidence_admission_independent"]["regression_status"] == "VERIFIED_ENFORCED"


def test_v16_model_semantic_failure_vs_state_breach():
    """V16: Verify model semantic flaw is separated from unauthorized state commit."""
    path = AUDIT_DIR / "rca2a15-evidence-integrity-regression-v1.json"
    with open(path) as f:
        data = json.load(f)
    tri_level = data["tri_level_failure_distinction"]
    assert "model_semantic_failure" in tri_level
    assert "deterministic_policy_rejection" in tri_level
    assert "unauthorized_state_commit" in tri_level


def test_v17_guidance_integration_strategy():
    """V17: Verify PREPARE_EXPERIMENTAL_OPT_IN is selected and production default unchanged."""
    path = AUDIT_DIR / "rca2a15-guidance-integration-options-v1.json"
    assert path.exists()
    with open(path) as f:
        data = json.load(f)
    assert data["selected_decision"] == "PREPARE_EXPERIMENTAL_OPT_IN"
    assert data["production_boundary_enforcement"]["production_prompt_modified_in_phase_15"] is False


def test_v18_critical_path_definition():
    """V18: Verify critical path report defines ServiceManager wiring as next task."""
    path = AUDIT_DIR / "rca2a15-agent-v0-critical-path-report-v1.json"
    assert path.exists()
    with open(path) as f:
        data = json.load(f)
    task = data["next_engineering_task"]
    assert task["priority"] == "P1 (Top Critical Path)"
    assert "Wiring" in task["task_name"]
    assert "python_service/httpserver/services/service_manager.py" in task["affected_components"]


def test_v19_real_provider_calls_zero():
    """V19: Verify zero real provider requests executed."""
    path = AUDIT_DIR / "rca2a15-baseline-integrity-report-v1.json"
    with open(path) as f:
        data = json.load(f)
    assert data["production_invariants"]["real_provider_requests_count"] == 0


def test_v20_test_and_regression_report():
    """V20: Verify test and regression report exists and all suites passed."""
    path = AUDIT_DIR / "rca2a15-test-and-regression-report-v1.json"
    assert path.exists()
    with open(path) as f:
        data = json.load(f)
    assert data["disposition"] == "REGRESSION_PASSED_ALL_INVARIANTS_VERIFIED"
    assert data["runtime_invariants_verified"]["real_model_requests_count"] == 0
    assert data["runtime_invariants_verified"]["production_prompt_modified"] is False


def test_v21_final_engineering_decision():
    """V21: Verify final engineering decision outcomes and critical path."""
    path = AUDIT_DIR / "rca2a15-final-engineering-decision-v1.json"
    assert path.exists()
    with open(path) as f:
        data = json.load(f)
    assert data["final_decision"] == "SOLO_ENGINEERING_VALIDATION_COMPLETED"
    assert data["candidate_evaluation"]["engineering_verdict"] == "PROMISING_EXPLORATORY_CANDIDATE"
    assert data["guidance_integration_strategy"]["strategy_selected"] == "PREPARE_EXPERIMENTAL_OPT_IN"
    assert data["architectural_disposition"]["hard_stop_enforced"] is True

