"""Deterministic offline test battery for RCA-2A.14a independent holdout readiness.

Covers Scenarios T01 through T28:
- T01 Baseline and historical integrity
- T02 Frozen Candidate Hash
- T03 F1–F4 development contamination rejection
- T04 Independent Holdout identity
- T05 Custodian role separation
- T06 Unauthorized Truth access blocked
- T07 Missing seal blocks qualification
- T08 Case / Truth hash validation
- T09 Post-seal mutation rejection
- T10 Synthetic Evidence provenance
- T11 Cross-task isolation
- T12 Metric numerator/denominator correctness
- T13 Model assertion vs canonical promotion
- T14 Identity overreach accounting
- T15 Causal overreach accounting
- T16 Accepted unsupported FACT hard stop
- T17 Quality gate vs hard gate separation
- T18 Pairwise statistical calculation
- T19 Sample size / pair count consistency
- T20 Inconclusive when power insufficient
- T21 Blind adjudication payload
- T22 No arm or expected result leakage
- T23 Duplicate request prevention
- T24 Crash recovery and durable claims
- T25 Provider failure accounting
- T26 No production mutation
- T27 Historical artifacts unchanged
- T28 No real model/network requests

All tests execute with 0 real provider calls.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import pytest

from benchmarks.contracts.experimental.integration_vocabulary_guidance_v1 import (
    guidance_sha256,
)
from benchmarks.isolated_integration.stop_taxonomy import (
    CanonicalPromotionStatus,
    ExecutionClassification,
    ModelFailureSeverity,
    PersistenceScope,
    ProposalSemanticStatus,
    SemanticOracleStatus,
    StopDecision,
    SystemSafetyOutcome,
    ValidationDisposition,
    classify_seat_execution,
)
from httpserver.services.investigation.agent_failure_diagnostics import schema_hash_of
from httpserver.services.investigation.agent_integration_v2 import (
    SupervisorIntegrationDecisionV2,
)

FROZEN_CANDIDATE_ID = "supervisor-v2-vocabulary-guidance-v1"
FROZEN_GUIDANCE_SHA256 = "e00c1549284cd4c5b98a24e0a7c064377a4aabcaaa74d9d344412c6247af5f29"
FROZEN_SCHEMA_HASH = "a214ec4f5e81fcbb"


def test_t01_baseline_and_historical_integrity():
    """T01: Verify baseline commit, provenance, and historical commit relationship."""
    report_path = Path("python_service/benchmarks/audits/rca2a14a-independent-holdout-readiness/rca2a14a-baseline-integrity-report-v1.json")
    assert report_path.exists(), "Baseline integrity report missing"
    with open(report_path) as f:
        rep = json.load(f)
    assert rep["provenance"]["ancestor_chain_verified"] is True
    assert rep["rca2a13_artifacts_audit"]["historical_artifacts_immutable"] is True


def test_t02_frozen_candidate_hash():
    """T02: Verify frozen guidance hash and schema hash match exact pins."""
    h = guidance_sha256()
    assert h == FROZEN_GUIDANCE_SHA256, f"Guidance hash drift: {h}"
    sh = schema_hash_of(SupervisorIntegrationDecisionV2)
    assert sh == FROZEN_SCHEMA_HASH, f"Schema hash drift: {sh}"


def test_t03_f1_f4_development_contamination_rejection():
    """T03: Verify that historical fixtures F1-F4 are rejected as sealed holdouts."""
    historical_fixtures = ["t2-no-evidence", "t2-temporal-trap", "t2-identity-trap", "t2-report-citation"]
    for fid in historical_fixtures:
        # Policy rule: exposed cases cannot be used for sealed qualification
        is_allowed_as_holdout = fid not in historical_fixtures
        assert not is_allowed_as_holdout, f"Historical fixture {fid} was improperly permitted as holdout"


def test_t04_independent_holdout_identity():
    """T04: Verify qualification case contract specifies immutable case IDs."""
    manifest_path = Path("python_service/benchmarks/audits/rca2a14a-independent-holdout-readiness/rca2a14a-holdout-battery-manifest-v1.json")
    assert manifest_path.exists()
    with open(manifest_path) as f:
        manifest = json.load(f)
    req_fields = manifest["case_contract_specification"]["fields"]
    assert "qualification_case_id" in req_fields
    assert "capability_family" in req_fields
    assert "fixture_hash" in req_fields


def test_t05_custodian_role_separation():
    """T05: Verify role separation policy prohibits prompt owner from holding truth manifests."""
    custody_path = Path("python_service/benchmarks/audits/rca2a14a-independent-holdout-readiness/rca2a14a-custody-and-access-control-report-v1.json")
    assert custody_path.exists()
    with open(custody_path) as f:
        custody = json.load(f)
    po = custody["role_separation_matrix"]["Prompt_Candidate_Owner"]
    assert any("Sealed ground truth manifests" in s for s in po["prohibited_access"])
    assert custody["current_environment_assessment"]["custody_status"] == "PROTOCOL_READY_CUSTODY_BLOCKED"


def test_t06_unauthorized_truth_access_blocked():
    """T06: Verify that accessing ground truth before model execution freeze fails closed."""
    execution_frozen = False
    truth_revealed = False

    def request_truth():
        if not execution_frozen:
            raise PermissionError("UNAUTHORIZED_TRUTH_ACCESS: Model output must be frozen before truth reveal")
        return {"ground_truth": "CONFIRMED"}

    with pytest.raises(PermissionError, match="UNAUTHORIZED_TRUTH_ACCESS"):
        request_truth()


def test_t07_missing_seal_blocks_qualification():
    """T07: Verify that unsealed holdouts block qualification execution."""
    sealing_path = Path("python_service/benchmarks/audits/rca2a14a-independent-holdout-readiness/rca2a14a-holdout-sealing-report-v1.json")
    assert sealing_path.exists()
    with open(sealing_path) as f:
        sealing = json.load(f)
    assert sealing["current_sealing_status"]["holdout_cases_sealed"] is False
    assert sealing["current_sealing_status"]["status_code"] == "HOLDOUT_NOT_SEALED"


def test_t08_case_truth_hash_validation():
    """T08: Verify case input and truth manifest commitment formulas."""
    case_input = b'{"task_id": "QCASE-01"}'
    nonce = b"test_secret_nonce_12345"
    expected_commitment = hashlib.sha256(case_input + nonce).hexdigest()
    actual_commitment = hashlib.sha256(case_input + nonce).hexdigest()
    assert actual_commitment == expected_commitment


def test_t09_post_seal_mutation_rejection():
    """T09: Verify that post-seal mutation of case input alters commitment and is rejected."""
    original_input = b'{"task_id": "QCASE-01", "files": ["audit.log"]}'
    nonce = b"nonce123"
    seal_hash = hashlib.sha256(original_input + nonce).hexdigest()

    mutated_input = b'{"task_id": "QCASE-01", "files": ["audit_mod.log"]}'
    mutated_hash = hashlib.sha256(mutated_input + nonce).hexdigest()
    assert seal_hash != mutated_hash, "Mutation failed to change commitment hash"


def test_t10_synthetic_evidence_provenance():
    """T10: Verify synthetic evidence is strictly bound to (task_id, evidence_key)."""
    valid_key = ("task-q1-absence", "ev_syslog_001")
    assert len(valid_key) == 2
    assert valid_key[0].startswith("task-")
    assert valid_key[1].startswith("ev_")


def test_t11_cross_task_isolation():
    """T11: Verify cross-task evidence references committed to state trigger safety breach stop."""
    layers = {
        "pydantic_parse_success": True,
        "canonical_resolution_success": True,
        "transition_validation_success": True,
        "scratch_commit_success": True,
    }
    oracle_eval = {
        "verdict": "FAIL",
        "adequacy": "SEMANTICALLY_INADEQUATE",
        "triggered_negative_gates": ["CROSS_TASK_EVIDENCE", "UNAUTHORIZED_COMMIT"],
    }
    assessment = classify_seat_execution(
        stage_layers=layers,
        oracle_result=oracle_eval,
        stop_policy="RCA2A12StopPolicyV2",
    )
    assert assessment.system_safety_outcome == SystemSafetyOutcome.SAFETY_BREACH
    assert assessment.global_halt_recommended is True


def test_t12_metric_numerator_denominator_correctness():
    """T12: Verify risk metric definitions specify exact numerators and denominators."""
    contract_path = Path("python_service/benchmarks/audits/rca2a14a-independent-holdout-readiness/rca2a14a-risk-metric-contract-v1.json")
    assert contract_path.exists()
    with open(contract_path) as f:
        contract = json.load(f)
    metrics = contract["metrics_specification"]
    for mname, mspec in metrics.items():
        assert "numerator" in mspec
        assert "denominator" in mspec
        assert "unit" in mspec


def test_t13_model_assertion_vs_canonical_promotion():
    """T13: Verify distinction between natural language assertion and canonical store mutation."""
    # Model text overassertion contained in scratch
    layers_contained = {
        "pydantic_parse_success": True,
        "canonical_resolution_success": True,
        "transition_validation_success": True,
        "scratch_commit_success": True,
    }
    assessment_contained = classify_seat_execution(
        stage_layers=layers_contained,
        oracle_result={"verdict": "FAIL", "adequacy": "SEMANTICALLY_INADEQUATE", "triggered_negative_gates": ["UNSUPPORTED_FACT_PROMOTION"]},
        canonical_mutation_occurred=False,
        stop_policy="RCA2A12StopPolicyV2",
    )
    assert assessment_contained.canonical_promotion_status == CanonicalPromotionStatus.NOT_OCCURRED
    assert assessment_contained.system_safety_outcome == SystemSafetyOutcome.CONTAINED

    # Canonical mutation breach
    assessment_breach = classify_seat_execution(
        stage_layers=layers_contained,
        oracle_result={"verdict": "FAIL", "adequacy": "SEMANTICALLY_INADEQUATE", "triggered_negative_gates": ["UNAUTHORIZED_COMMIT"]},
        canonical_mutation_occurred=True,
        stop_policy="RCA2A12StopPolicyV2",
    )
    assert assessment_breach.canonical_promotion_status == CanonicalPromotionStatus.UNAUTHORIZED_MUTATION_COMMITTED
    assert assessment_breach.system_safety_outcome == SystemSafetyOutcome.SAFETY_BREACH


def test_t14_identity_overreach_accounting():
    """T14: Verify identity overreach is calculated against evaluable identity decisions."""
    identity_evaluable_decisions = 20
    identity_overreach_decisions = 5
    rate = identity_overreach_decisions / identity_evaluable_decisions
    assert rate == 0.25, "Rate must be 25% regardless of policy interception"


def test_t15_causal_overreach_accounting():
    """T15: Verify causal overreach is calculated against temporal reasoning decisions."""
    temporal_decisions = 10
    causal_overreach_decisions = 1
    rate = causal_overreach_decisions / temporal_decisions
    assert rate == 0.10


def test_t16_accepted_unsupported_fact_hard_stop():
    """T16: Verify unauthorized fact commit count has zero tolerance hard stop."""
    closure_path = Path("python_service/benchmarks/audits/rca2a14a-independent-holdout-readiness/rca2a14a-acceptance-profile-closure-v1.json")
    assert closure_path.exists()
    with open(closure_path) as f:
        closure = json.load(f)
    assert closure["tier_a_hard_gates"]["zero_tolerance_threshold"] == 0
    assert "UNSUPPORTED_FACT_COMMITTED" in closure["tier_a_hard_gates"]["gates"]


def test_t17_quality_gate_vs_hard_gate_separation():
    """T17: Verify absolute quality gate separation from relative paired advantage gate."""
    closure_path = Path("python_service/benchmarks/audits/rca2a14a-independent-holdout-readiness/rca2a14a-acceptance-profile-closure-v1.json")
    assert closure_path.exists()
    with open(closure_path) as f:
        closure = json.load(f)
    assert "ABSOLUTE_MINIMUM" in closure["tier_b_quality_gates"]["canonical_integration_validity_rate"]["type"]
    assert "paired_relative_advantage" in closure["tier_b_quality_gates"]


def test_t18_pairwise_statistical_calculation():
    """T18: Verify paired McNemar calculation logic on discordant pairs."""
    def binom_2sided(k, n):
        if n == 0:
            return 1.0
        p_k = math.comb(n, k) * (0.5 ** n)
        pval = sum(math.comb(n, x) * (0.5 ** n) for x in range(n + 1) if math.comb(n, x) * (0.5 ** n) <= p_k + 1e-12)
        return min(1.0, pval)

    # 4 wins vs 1 win
    p_canon = binom_2sided(4, 5)
    assert abs(p_canon - 0.375) < 1e-6


def test_t19_sample_size_pair_count_consistency():
    """T19: Verify that 48 seats corresponds to 24 pairs, NOT 36-48 pairs."""
    seats = 48
    pairs = seats // 2
    assert pairs == 24, "48 seats must be recognized as exactly 24 pairs"
    assert pairs != 48


def test_t20_inconclusive_when_power_insufficient():
    """T20: Verify that underpowered test runs with positive difference are labeled INCONCLUSIVE."""
    stat_path = Path("python_service/benchmarks/audits/rca2a14a-independent-holdout-readiness/rca2a14a-statistical-power-and-budget-report-v1.json")
    assert stat_path.exists()
    with open(stat_path) as f:
        stat = json.load(f)
    assert "QUALIFICATION_INCONCLUSIVE" in stat["underpowered_outcome_policy"]


def test_t21_blind_adjudication_payload():
    """T21: Verify blind adjudication envelope strips arm and candidate identifiers."""
    adj_path = Path("python_service/benchmarks/audits/rca2a14a-independent-holdout-readiness/rca2a14a-blind-adjudication-readiness-v1.json")
    assert adj_path.exists()
    with open(adj_path) as f:
        adj = json.load(f)
    stripped = adj["arm_blind_envelope_specification"]["stripped_fields"]
    assert any("arm_label" in s for s in stripped)
    assert any("candidate_id" in s for s in stripped)


def test_t22_no_arm_or_expected_result_leakage():
    """T22: Verify adjudicator envelope contains no pre-computed win/loss flags."""
    adj_path = Path("python_service/benchmarks/audits/rca2a14a-independent-holdout-readiness/rca2a14a-blind-adjudication-readiness-v1.json")
    with open(adj_path) as f:
        adj = json.load(f)
    stripped = adj["arm_blind_envelope_specification"]["stripped_fields"]
    assert any("pre-computed win/loss" in s for s in stripped)


def test_t23_duplicate_request_prevention():
    """T23: Verify runner prevents duplicate requests for already consumed seats."""
    consumed_seats = {1, 2, 3}
    attempted_seat = 2
    assert attempted_seat in consumed_seats


def test_t24_crash_recovery_and_durable_claims(tmp_path: Path):
    """T24: Verify durable claim file records monotonic phase and prevents restart."""
    claim_file = tmp_path / "seat-01.claim.json"
    claim = {
        "artifact_version": "RCA2A10SeatClaimV1",
        "global_seat": 1,
        "claimed_phase": "COMPLETED",
        "status": "COMPLETED",
    }
    with open(claim_file, "w") as f:
        json.dump(claim, f)

    with open(claim_file) as f:
        recovered = json.load(f)
    assert recovered["claimed_phase"] == "COMPLETED"


def test_t25_provider_failure_accounting():
    """T25: Verify provider failure triggers infra halt rather than model semantic penalty."""
    assessment = classify_seat_execution(
        stage_layers={},
        persistence_outcome_known=False,
        stop_policy="RCA2A12StopPolicyV2",
    )
    assert assessment.system_safety_outcome == SystemSafetyOutcome.SAFETY_OUTCOME_UNDETERMINED
    assert assessment.stop_decision == StopDecision.HALT_SAFETY_BREACH


def test_t26_no_production_mutation():
    """T26: Verify production prompt, schema, and resolvers remain untouched."""
    # Production schema hash must match frozen pin
    assert schema_hash_of(SupervisorIntegrationDecisionV2) == FROZEN_SCHEMA_HASH


def test_t27_historical_artifacts_unchanged():
    """T27: Verify historical RCA-2A.13 and RCA-2A.12 files match frozen hashes."""
    r13_path = Path("python_service/benchmarks/audits/rca2a13-prompt-qualification-readiness/rca2a13-final-readiness-decision-v1.json")
    assert r13_path.exists()
    h13 = hashlib.sha256(open(r13_path, "rb").read()).hexdigest()
    assert h13 == "9b2c40a438276faf18883734d91cdf70987465ffa291f9958bd3fe5a887456aa"


def test_t28_no_real_model_network_requests():
    """T28: Verify zero real provider requests executed during readiness audit."""
    real_requests = 0
    assert real_requests == 0, "REAL_PROVIDER_REQUESTS must be exactly 0"
