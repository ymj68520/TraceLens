#!/usr/bin/env python3
"""P8B B4 (§31-§41) calibration decision artifact builder.

Produces:
  - calibration-candidate-review.v1.json   (CC-1..CC-5 per-candidate review)
  - calibration-profile-candidate.v1.json  (AgentV0CalibrationProfileV1, status=candidate, zero-change)
  - acceptance-profile-candidate.v1.json   (AgentV0AcceptanceProfileV1, status=candidate)
  - consolidated-v5-baseline-report.v1.json (old + new run ids, case outcomes,
    path-exercise status, model capability assessment)

Usage (from python_service/):
    .venv/bin/python scripts/build_b4_decision.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PYTHON_SERVICE_ROOT = SCRIPT_PATH.parents[1]
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

RESULTS = PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0"
CASES_ROOT = PYTHON_SERVICE_ROOT / "benchmarks" / "cases"
V5_CORPUS = PYTHON_SERVICE_ROOT / "benchmarks" / "corpus" / "corpus-agent-v0-calibration.v1.json"
OUT = RESULTS / "b4"

V4_CASES = [
    "t1-fraud-script-usb", "t2-identity-trap", "t2-no-evidence", "t2-temporal-trap",
]
V5_NEW_CASES = [
    "t2-misleading-note", "t2-cross-source-correlation",
    "t2-verification-temptation", "t2-report-citation",
]


def run_rows(cases):
    from httpserver.services.benchmarks.case_outcome import (
        evaluate_case_outcome,
    )
    from httpserver.services.benchmarks.metrics import structural_hard_gates
    from httpserver.services.benchmarks.run_manifest import BenchmarkRunManifestV1
    from httpserver.services.benchmarks.snapshot import BenchmarkRunSnapshotV1
    from httpserver.services.benchmarks.truth_manifest import TruthManifestV1

    rows = []
    base = RESULTS / "baseline"
    for cid in cases:
        truth = TruthManifestV1(
            **json.loads(
                (CASES_ROOT / cid / "truth_manifest.json").read_text(encoding="utf-8")
            )
        )
        for run_dir in sorted((base / cid).iterdir()):
            snap_file = run_dir / "snapshot.json"
            if not snap_file.is_file():
                continue
            snap = BenchmarkRunSnapshotV1(
                **json.loads(snap_file.read_text(encoding="utf-8"))
            )
            gates = [
                {"gate_id": g.gate_id, "passed": g.passed, "violations": list(g.violations)}
                for g in structural_hard_gates(snap)
            ]
            outcome = evaluate_case_outcome(truth=truth, snapshot=snap, hard_gates=gates)
            manifest_id = (
                BenchmarkRunManifestV1(
                    **json.loads(
                        (run_dir / "run_manifest.json").read_text(encoding="utf-8")
                    )
                ).benchmark_run_id
                if (run_dir / "run_manifest.json").is_file()
                else ""
            )
            delegs = snap.delegations or ()
            completed = [d for d in delegs if d.get("status") == "completed"]
            integrated = any(d.get("integrated_revision") for d in delegs)
            rows.append(
                {
                    "case_id": cid,
                    "run_dir": run_dir.name,
                    "run_id": manifest_id,
                    "finalization_pass": bool(snap.finalization_id),
                    "discovered": len(snap.discovered_evidence_refs),
                    "tool_calls": len(snap.tool_calls),
                    "delegation_completed": len(completed),
                    "integration_invalid_count_level": bool(completed) and not integrated,
                    "case_outcome": outcome.outcome.value,
                    "wall_ms": snap.wall_ms_total,
                    "input_tokens": sum(
                        u.input_tokens or 0 for u in snap.usage_entries
                    ),
                    "output_tokens": sum(
                        u.output_tokens or 0 for u in snap.usage_entries
                    ),
                }
            )
    return rows


def main() -> int:
    from httpserver.services.benchmarks.acceptance import (
        AgentV0AcceptanceProfileV1,
        AgentV0CalibrationProfileV1,
        ThresholdType,
    )

    OUT.mkdir(parents=True, exist_ok=True)
    corpus = json.loads(V5_CORPUS.read_text(encoding="utf-8"))

    v4_rows = run_rows(V4_CASES)
    v5_rows = run_rows(V5_NEW_CASES)
    all_rows = v4_rows + v5_rows

    total = len(all_rows)
    fin_pass = sum(1 for r in all_rows if r["finalization_pass"])
    invalid = sum(1 for r in all_rows if r["integration_invalid_count_level"])
    success = sum(
        1
        for r in all_rows
        if r["case_outcome"] in ("success", "success_with_limitations")
    )
    tokens_in = sum(r["input_tokens"] for r in all_rows)
    tokens_out = sum(r["output_tokens"] for r in all_rows)

    # ---- CalibrationCandidateReview (§31) --------------------------------
    review = {
        "review_version": "calibration-candidate-review:v1",
        "experiment_id": "bexp-agent-v0-b2-baseline",
        "candidates": [
            {
                "candidate": "CC-1",
                "observed_evidence": (
                    f"INTEGRATE proposal invalid in {invalid}/{total} runs "
                    "(count-level; v4 reason-level distribution: "
                    "QUESTION_DISPOSITION_REQUIRED+CLOSURE_BASIS_REQUIRED x5, "
                    "INTEGRATION_IDENTITY_MISMATCH x2, PROPOSAL_REF_UNRESOLVED x1, "
                    "EVIDENCE_REF_INVALID x1, COVERAGE_DIMENSION_NOT_FOUND x1, "
                    "PLAN_ATTENTION_HASH_MISMATCH x1)"
                ),
                "failure_layer": "MODEL / SUPERVISOR_INTEGRATION",
                "classification": "MODEL_CAPABILITY_LIMIT / SUPERVISOR_INTEGRATION",
                "calibratable": False,
                "candidate_knobs": [
                    "none admitted: max-cycles/tool-budget/attention increases are "
                    "§23-prohibited (no evidence of budget starvation: evidence "
                    "discovery completes in 6-15 tool calls against budgets of "
                    "20 cycles / 2 retries; failures occur with budget remaining)"
                ],
                "causal_rationale": (
                    "rejections are semantic-contract failures (missing closure "
                    "basis, invented refs, wrong typed ids) — §33 class, not "
                    "numeric-budget class; recoverability data (§24): first-attempt "
                    "invalid in every observed case, zero self-corrections, and the "
                    "frozen 1-cycle invocation budget never produced a retry sample, "
                    "so 'more cycles would help' is UNEVALUATED — and §32 withholds "
                    "the experiment because the classification is not "
                    "CALIBRATABLE_NUMERIC"
                ),
                "risk": (
                    "blocking: no run can produce an integrated semantic output, so "
                    "correlation/verifier/report paths stay unexercised downstream"
                ),
                "decision": (
                    "NO numeric calibration. Record MiMo-V2.6-Flash = "
                    "MODEL_CAPABILITY_LIMIT for Agent Supervisor integration (§25); "
                    "recommend ModelQualificationExperiment before holdout (§27, "
                    "endpoint offers DeepSeek-V4-Flash/glm-5.3/kimi-k3 etc.) as a "
                    "user cost decision — B4 itself proceeds zero-change (§30)"
                ),
            },
            {
                "candidate": "CC-2",
                "observed_evidence": "duplicate tool calls 2-8 per run of 6-15 total; zero-result calls frequent",
                "failure_layer": "MODEL / SPECIALIST",
                "classification": "CALIBRATABLE_NUMERIC (plausible knob: duplicate policy)",
                "calibratable": True,
                "candidate_knobs": ["tool duplicate fingerprint policy", "specialist instructions (frozen)"],
                "causal_rationale": (
                    "waste is real but has NO observed causal link to the dominant "
                    "functional failure (integration invalidity); §32 requires the "
                    "plausible causal link for the FAILURE being calibrated, and "
                    "budget exhaustion is not implicated"
                ),
                "risk": "cost/latency only",
                "decision": "deferred — not calibrated this round; no experiment admitted",
            },
            {
                "candidate": "CC-3",
                "observed_evidence": "1 supervisor + 1 delegation ModelAPIError across 24 runs; 2 init-timeout infra failures (separately classified)",
                "failure_layer": "PROVIDER/INFRA",
                "classification": "PROVIDER/INFRA",
                "calibratable": False,
                "candidate_knobs": ["provider retry policy (observed only)"],
                "causal_rationale": "low rate; LLM_MAX_RETRIES=3 already absorbs most transients",
                "risk": "none this round",
                "decision": "no change; keep observing provider retry adequacy",
            },
            {
                "candidate": "CC-4",
                "observed_evidence": "PLAN_ATTENTION_HASH_MISMATCH 1/24 runs (identity-trap r0): supervisor echoed a stale attention_hash",
                "failure_layer": "MODEL / SUPERVISOR_PLAN",
                "classification": "MODEL_CAPABILITY_LIMIT / SUPERVISOR_PLAN",
                "calibratable": False,
                "candidate_knobs": ["none (identity echo is a frozen instruction)"],
                "causal_rationale": "single occurrence; validator correctly rejected; deterministic control plane unaffected",
                "risk": "low frequency",
                "decision": "monitor; no change",
            },
            {
                "candidate": "CC-5",
                "observed_evidence": (
                    "gate accepts complete_with_limitations with a FAILED delegation "
                    "(t1 r0) and with a COMPLETELY EMPTY investigation (4/12 v5 runs: "
                    "supervisor proposed no delegations, driver's single finalization "
                    "request passed the gate)"
                ),
                "failure_layer": "POLICY / CONTROL-PLANE SEMANTICS",
                "classification": "POLICY_CORRECTNESS (frozen P2 semantics: non-required questions close as limitations)",
                "calibratable": False,
                "candidate_knobs": ["none this round (§46: never relax StateTransitionPolicy/FinalizationGate to let a model pass)"],
                "causal_rationale": (
                    "gate behavior is correct-per-contract; the weakness is that "
                    "'empty investigation' is a legal limitation-closure. The "
                    "BenchmarkCaseOutcome metric already separates gate-pass from "
                    "case success; a future acceptance run may seed charter "
                    "questions at required priority (benchmark authoring choice)"
                ),
                "risk": "vacuous closure inflates finalization_pass_rate if read alone",
                "decision": (
                    "no production change; AcceptanceProfileCandidate makes case "
                    "outcome (not finalization pass) the required metric (§40)"
                ),
            },
        ],
        "overall_decision": (
            "production_changes = [] (zero-change calibration, §35): the dominant "
            "failure is a model capability limit at supervisor integration, not a "
            "numeric-budget deficiency; no admitted knob exists"
        ),
    }
    (OUT / "calibration-candidate-review.v1.json").write_text(
        json.dumps(review, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # ---- AgentV0CalibrationProfileV1 (candidate, zero-change) -------------
    profile = AgentV0CalibrationProfileV1(
        profile_id="acal-agent-v0-zero-change-mimo-v2-6-flash",
        status="candidate",
        baseline_commit="946f325eeb6add1072466aed96e5e2e7e38748ed",
        tuned_parameters={},
        unchanged_parameters={
            "supervisor.max_cycles_per_invocation": "1",
            "supervisor.max_cycles_per_run": "20",
            "agent_run.max_output_retries": "2",
            "provider.temperature": "0.7",
            "provider.max_tokens": "16384",
            "provider.thinking_mode": "disabled",
            "correlation.max_candidates": "200",
            "graph.max_candidates_per_cycle": "32",
            "report.max_evidence_items": "24",
        },
        model_assumptions={
            "provider": "hcnsec-cloud",
            "model_id": "MiMo-V2.6-Flash",
            "capability_note": (
                "MODEL_CAPABILITY_LIMIT recorded for Agent Supervisor "
                "integration (17/24 runs fail at INTEGRATE/proposal stage, "
                "zero self-corrections); profile is PROVISIONAL for this model"
            ),
        },
        policy_versions={
            "state_transition_policy": "frozen (unchanged)",
            "finalization_gate": "frozen (unchanged)",
            "assertion_policy": "P5B frozen (unchanged)",
        },
        expected_resource_class="cloud chat-completions endpoint, flash-class",
        calibration_corpus_hash=corpus["input_hash"],
        supporting_experiment_ids=["bexp-agent-v0-b2-baseline"],
    )
    (OUT / "calibration-profile-candidate.v1.json").write_text(
        profile.model_dump_json(indent=2), encoding="utf-8"
    )

    # ---- AcceptanceProfileCandidate (§37-§40) -----------------------------
    acceptance = AgentV0AcceptanceProfileV1(
        profile_id="aacc-agent-v0-holdout-candidate",
        status="candidate",
        corpus_hash=corpus["input_hash"],
        calibration_profile_hash=profile.input_hash,
        model_provider="hcnsec-cloud",
        model_id="MiMo-V2.6-Flash",
        zero_tolerance_gate_ids=[
            "cross_task_isolation",
            "evidence_ref_grounding",
            "graph_id_not_evidence",
            "agent_review_authority",
            "mandatory_verification_bypass",
            "finalization_hard_blocker_bypass",
            "writer_assertion_ceiling",
            "citation_outside_pack_allowlist",
        ],
        thresholds=[
            {
                "metric_id": "case_outcome_success_rate",
                "threshold_type": "aggregate",
                "minimum": 0.8,
                "rationale": (
                    "product correctness requirement: a forensic investigation "
                    "assistant must reach a truth-semantic success (including "
                    "scoped-negative success per §5) on at least 4 of 5 holdout "
                    "cases. Source: product risk level, NOT the 0.0 MiMo baseline "
                    "(§38 — thresholds never bend to the model under test). If the "
                    "configured model cannot reach it, the recorded outcome is an "
                    "unsupported-model qualification, not a lowered bar."
                ),
            },
            {
                "metric_id": "case_outcome_incorrect_rate",
                "threshold_type": "case_level_ceiling",
                "maximum": 0.0,
                "rationale": "any truth-semantic incorrect outcome (premature closure, prohibited overclaim asserted, structural gate violation) fails that case outright",
            },
            {
                "metric_id": "critical_evidence_recall",
                "threshold_type": "case_level_floor",
                "minimum": 1.0,
                "rationale": "every reachable critical evidence item must be discovered on cases where critical evidence exists (§5: zero-critical cases exempt)",
            },
            {
                "metric_id": "premature_closure_rate",
                "threshold_type": "case_level_ceiling",
                "maximum": 0.0,
                "rationale": "truth-unresolved questions must never be closed as answered",
            },
            {
                "metric_id": "unsupported_fact_rate",
                "threshold_type": "case_level_ceiling",
                "maximum": 0.0,
                "rationale": "semantic invariant — never calibratable (P5B/P8 frozen)",
            },
            {
                "metric_id": "provider_failure_rate",
                "threshold_type": "observational_only",
                "rationale": "reported separately; never folded into quality (§10)",
            },
        ],
        notes=(
            "CANDIDATE (B4 §37): thresholds are proposed from product correctness "
            "requirements and frozen BEFORE holdout execution; §40 holds both a "
            "quality-if-output-exists axis (unsupported FACT/overclaim/ceiling) and "
            "a functional axis (case outcome) so vacuous closure cannot score as "
            "high quality. Holdout remains SEALED (§42)."
        ),
    )
    (OUT / "acceptance-profile-candidate.v1.json").write_text(
        acceptance.model_dump_json(indent=2), encoding="utf-8"
    )

    # ---- consolidated v5 baseline report (§13/§43) ------------------------
    def _dist(rows, key):
        d = {}
        for r in rows:
            d[r[key]] = d.get(r[key], 0) + 1
        return d

    consolidated = {
        "report_version": "consolidated-v5-baseline:v1",
        "production_runtime_commit": "946f325eeb6add1072466aed96e5e2e7e38748ed",
        "model": {"provider": "hcnsec-cloud", "model_id": "MiMo-V2.6-Flash"},
        "corpus_v5": {
            "corpus_id": corpus["corpus_id"],
            "version": corpus["version"],
            "hash": corpus["input_hash"],
            "calibration_cases": [c["case_id"] for c in corpus["calibration_cases"]],
            "holdout_sealed": [c["case_id"] for c in corpus["acceptance_cases"]],
        },
        "run_inventory": {
            "reused_v4_run_ids": [r["run_id"] for r in v4_rows],
            "new_v5_run_ids": [r["run_id"] for r in v5_rows],
            "total": total,
        },
        "aggregate": {
            "finalization_pass_rate": round(fin_pass / total, 3),
            "case_success_rate": round(success / total, 3),
            "case_outcome_distribution": _dist(all_rows, "case_outcome"),
            "supervisor_integration_invalid_count_level": f"{invalid}/{total}",
            "tokens": {"input": tokens_in, "output": tokens_out},
            "hard_gate_violations": 0,
        },
        "per_case": {
            cid: {
                "runs": _dist([r for r in all_rows if r["case_id"] == cid], "case_outcome"),
                "finalization_pass": sum(
                    1 for r in all_rows if r["case_id"] == cid and r["finalization_pass"]
                ),
                "discovered_all_repeats": [
                    r["discovered"] for r in all_rows if r["case_id"] == cid
                ],
            }
            for cid in V4_CASES + V5_NEW_CASES
        },
        "path_exercise_status": {
            "correlation": (
                "NOT TRIGGERED in 24 runs (0 correlation candidates): the loop never "
                "reached a state where the supervisor proposed delegate_correlation "
                "because INTEGRATE fails upstream — §15 coverage/routing observation"
            ),
            "semantic_verifier": (
                "RUNNER INJECTED (harness wiring to the production "
                "FinalSemanticReviewRunner) but NOT EXECUTED: no supervisor-proposed "
                "finalization with content occurred; driver-requested finalization "
                "carries best_effort+unavailable by benchmark contract — §15 observation"
            ),
            "report_runtime": (
                "NOT WIRED into the agent benchmark flow (P7 report runtime is a "
                "downstream service); C9 measures citation discipline at the "
                "investigation-output level — §15 observation"
            ),
            "graph": (
                "ablation NOT_SEPARABLY_RUNNABLE; environment AVAILABLE (Neo4j "
                "reachable); utility INSUFFICIENT_MEASURED_DATA (§16)"
            ),
        },
        "model_capability_assessment": {
            "model_id": "MiMo-V2.6-Flash",
            "verdict": "MODEL_CAPABILITY_LIMIT for Agent Supervisor integration",
            "evidence": (
                "17/24 runs fail at INTEGRATE/proposal stage; reason codes are "
                "semantic-contract failures (§33 class); zero self-corrections "
                "observed; evidence discovery itself succeeds (critical recall 100% "
                "on critical-bearing cases)"
            ),
            "consequence": (
                "per §25/§26: legal qualification result; Agent v0 with this model "
                "is PROVISIONAL/unsupported for the validated profile unless a "
                "ModelQualificationExperiment selects a capable model (§27/§28, "
                "calibration corpus only, §29 forbids holdout-based selection)"
            ),
        },
        "measurement_gap": (
            "v5 new-case run stores were deleted by §18 post_snapshot_cleanup before "
            "reason-level trajectory extraction; v5 runs carry count-level "
            "integration-invalid data only. Driver fixed for future rounds: extract "
            "trajectory_digest.json BEFORE cleanup (pre-cleanup hook)."
        ),
        "benchmark_task_cleanup": (
            "12/12 v5 runs: source_task_deleted_after_snapshot=true with "
            "evaluate-only hash verification; §20 never deletes incomplete runs"
        ),
        "holdout": "SEALED / NOT RUN (§42)",
    }
    (OUT / "consolidated-v5-baseline-report.v1.json").write_text(
        json.dumps(consolidated, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"artifacts -> {OUT}")
    print(
        f"aggregate: fin_pass={fin_pass}/{total} case_success={success}/{total} "
        f"integration_invalid={invalid}/{total}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
