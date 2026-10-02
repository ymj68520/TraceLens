"""Gen-4 B6 post-freeze evaluation (§25-§33).

Runs ONLY after HoldoutRunSetV4 is frozen: deterministic evaluate-only
per completed run (frozen truth/evaluator), six-axis verdicts per the
frozen AcceptanceProfileV2, then AgentV0AcceptanceDecisionV4 +
AcceptanceGenerationClosureV4. Zero LLM.
"""

from __future__ import annotations

import hashlib
import json
import re
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PYTHON_SERVICE_ROOT = SCRIPT_PATH.parents[1]
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

REPO_ROOT = PYTHON_SERVICE_ROOT.parent
GEN4_ROOT = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0"
    / "acceptance-gen4"
)
RUNS_ROOT = GEN4_ROOT / "run-set-v1"
TRUTH_DIR = GEN4_ROOT / "truth"
CASES_DIR = GEN4_ROOT / "cases"
PROFILES = PYTHON_SERVICE_ROOT / "benchmarks" / "profiles"

P_CODES = {
    "PLAN_IDENTITY_MISMATCH", "PLAN_ATTENTION_HASH_MISMATCH",
    "PLAN_STATE_REVISION_STALE", "INTEGRATION_IDENTITY_MISMATCH",
    "INTEGRATION_STATE_REVISION_STALE", "INTEGRATION_SOURCE_RESULT_UNKNOWN",
    "INTEGRATION_SOURCE_RESULT_HASH_MISMATCH",
    "INTEGRATION_BASIS_REF_UNKNOWN", "INTEGRATION_EVIDENCE_REF_INVALID",
    "EVIDENCE_REF_CROSS_TASK", "INTEGRATION_PROPOSAL_REF_UNRESOLVED",
    "INTEGRATION_FINDING_REF_UNRESOLVED", "COVERAGE_DIMENSION_NOT_FOUND",
    "QUESTION_NOT_FOUND", "COVERAGE_QUESTION_NOT_FOUND",
    "PLAN_ATTENTION_ITEM_UNKNOWN",
}
H_CODES = {
    "HANDLE_UNKNOWN", "HANDLE_KIND_MISMATCH", "HANDLE_CONTEXT_MISMATCH",
}
S_CODES = {
    "QUESTION_DISPOSITION_REQUIRED", "QUESTION_CLOSURE_BASIS_REQUIRED",
    "QUESTION_CLOSURE_VERIFICATION_REQUIRED",
    "REQUIRED_QUESTION_CANNOT_DEFER", "QUESTION_BLOCKER_REQUIRED",
    "QUESTION_SUPERSESSION_PROVENANCE_REQUIRED",
    "COVERAGE_ILLEGAL_STATUS_TRANSITION",
    "QUESTION_ILLEGAL_STATUS_TRANSITION",
    "HYPOTHESIS_ILLEGAL_STATUS_TRANSITION",
    "CONTRADICTION_ILLEGAL_STATUS_TRANSITION",
}
G_CODES = {"EVIDENCE_SNAPSHOT_MISSING", "EVIDENCE_REF_CROSS_TASK"}
_PROVIDER_WORDS = (
    "timed out", "timeout", "connection", "429", "rate limit", "5xx",
)
_QUALIFYING = {"success", "success_with_limitations"}
_NEGATIVE_COMPONENT_MARKERS = ("overclaim",)


def _load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _load_json_tolerant(path: Path) -> dict:
    raw = Path(path).read_text(encoding="utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        unwrapped = re.sub(
            r":\s*\((\s*\"(?:[^\"\\]|\\.)*\"(?:\s*\"(?:[^\"\\]|\\.)*\")*\s*)\)",
            r": \1",
            raw,
        )
        pattern = re.compile(r"(\"(?:[^\"\\]|\\.)*\")\s*(\"(?:[^\"\\]|\\.)*\")")
        _join = lambda m: m.group(1)[:-1] + m.group(2)[1:]
        while True:
            joined = pattern.sub(_join, unwrapped)
            if joined == unwrapped:
                break
            unwrapped = joined
        return json.loads(unwrapped)


def _collect() -> list[dict]:
    from httpserver.services.benchmarks.case_outcome import (
        evaluate_case_outcome_v2,
    )
    from httpserver.services.benchmarks.metrics import structural_hard_gates
    from httpserver.services.benchmarks.snapshot import BenchmarkRunSnapshotV1
    from httpserver.services.benchmarks.truth_manifest import TruthManifestV1

    families = sorted(
        p.stem.replace(".public-case", "")
        for p in CASES_DIR.glob("*.public-case.json")
    )
    rows = []
    for case_id in families:
        truth = None
        for repeat in ("repeat0", "repeat1", "repeat2"):
            run_dir = RUNS_ROOT / case_id / repeat
            digest_file = run_dir / "trajectory_digest.json"
            digest = (
                json.loads(digest_file.read_text(encoding="utf-8"))
                if digest_file.exists() else {}
            )
            row = {
                "case_id": case_id,
                "repeat": repeat,
                "status": "no_artifacts",
                "rejection_codes": digest.get("rejection_codes", []),
                "supervisor_failures": digest.get("supervisor_failures", []),
                "delegation_failures": digest.get("delegation_failures", []),
                "completions": digest.get("completions", []),
                "finalization_event": digest.get("finalization", {}),
            }
            proof_file = run_dir / "evidence-world-proof.json"
            if proof_file.exists():
                row["evidence_world_proof"] = json.loads(
                    proof_file.read_text(encoding="utf-8")
                )
            failure = None
            for name in ("failure.json", "driver_failure.json"):
                f = run_dir / name
                if f.exists():
                    failure = json.loads(f.read_text(encoding="utf-8"))
            snap_file = run_dir / "snapshot.json"
            if snap_file.exists():
                snapshot = json.loads(snap_file.read_text(encoding="utf-8"))
                result = (
                    json.loads(
                        (run_dir / "result.json").read_text(encoding="utf-8")
                    )
                    if (run_dir / "result.json").exists() else {}
                )
                delegs = snapshot.get("delegations") or []
                gates = [
                    g for g in result.get("hard_gate_results", [])
                    if not g.get("passed")
                ]
                snap_model = BenchmarkRunSnapshotV1(**snapshot)
                gates_recompute = [
                    {"gate_id": g.gate_id, "passed": g.passed,
                     "violations": list(g.violations)}
                    for g in structural_hard_gates(snap_model)
                ]
                if truth is None:
                    truth = TruthManifestV1(
                        **json.loads(
                            (TRUTH_DIR / f"{case_id}.truth.json").read_text(
                                encoding="utf-8"
                            )
                        )
                    )
                payloads = [
                    c.get("result_semantic_payload") or {}
                    for c in digest.get("completions", [])
                ]
                try:
                    oc = evaluate_case_outcome_v2(
                        truth=truth,
                        snapshot=snap_model,
                        hard_gates=gates_recompute,
                        semantic_payloads=payloads,
                    )
                    outcome_v2 = {
                        "outcome": oc.outcome.value,
                        "rationale": oc.rationale,
                        "components": [
                            {"component": c.component, "status": c.status,
                             "detail": c.detail}
                            for c in oc.components
                        ],
                    }
                except Exception as exc:
                    outcome_v2 = {
                        "outcome": "unavailable",
                        "error": f"{type(exc).__name__}: {exc}"[:200],
                    }
                evaluate_only_ok = None
                if result:
                    from httpserver.services.benchmarks.runner import (
                        evaluate_only,
                    )
                    from httpserver.services.benchmarks.run_manifest import (
                        BenchmarkRunManifestV1,
                    )
                    from httpserver.services.benchmarks.truth_manifest import (
                        ReachabilityManifestV1 as _RM,
                    )

                    recomputed = evaluate_only(
                        run_manifest=BenchmarkRunManifestV1(
                            **json.loads(
                                (run_dir / "run_manifest.json").read_text(
                                    encoding="utf-8"
                                )
                            )
                        ),
                        truth_manifest=truth,
                        reachability=_RM(
                            **json.loads(
                                (
                                    TRUTH_DIR
                                    / f"{case_id}.reachability.json"
                                ).read_text(encoding="utf-8")
                            )
                        ),
                        snapshot=snap_model,
                    )
                    evaluate_only_ok = (
                        recomputed.result_hash == result.get("result_hash")
                    )
                usage = snapshot.get("usage_entries") or []
                questions = snapshot.get("questions") or []
                coverage = snapshot.get("coverage") or []
                row.update({
                    "status": "completed",
                    "run_manifest_id": result.get("run_manifest_id"),
                    "result_hash": result.get("result_hash"),
                    "snapshot_hash": snapshot.get("snapshot_hash"),
                    "terminal_status": snapshot.get("terminal_status"),
                    "finalization_pass": bool(snapshot.get("finalization_id")),
                    "hard_gate_violations": [
                        g.get("gate") or g.get("gate_id") for g in gates
                    ],
                    "hard_gate_recompute_violations": [
                        g["gate_id"] for g in gates_recompute
                        if not g["passed"]
                    ],
                    "evaluate_only_reproduced": evaluate_only_ok,
                    "case_outcome_v2": outcome_v2,
                    "delegations_completed": sum(
                        1 for d in delegs if d.get("status") == "completed"
                    ),
                    "delegations_failed": sum(
                        1 for d in delegs if d.get("status") == "failed"
                    ),
                    "integrated": sum(
                        1 for d in delegs if d.get("integrated_revision")
                    ),
                    "coverage_terminalization": {
                        c.get("dimension_id"): (c.get("status") or "")
                        for c in coverage
                    },
                    "question_terminalization": {
                        q.get("question_id"): (q.get("status") or "")
                        for q in questions
                    },
                    "tokens_in": sum(
                        int(u.get("input_tokens") or 0) for u in usage
                    ),
                    "tokens_out": sum(
                        int(u.get("output_tokens") or 0) for u in usage
                    ),
                    "wall_s": snapshot.get("wall_ms_total", 0) / 1000.0,
                })
            elif failure is not None:
                row.update({
                    "status": "runner_failed",
                    "failure_reason": str(failure.get("failure_reason", ""))[:300],
                })
            rows.append(row)
    return rows


def _six_axes(rows: list[dict], profile: dict) -> dict:
    completed = [r for r in rows if r["status"] == "completed"]
    denom = len(rows)

    # ---- structural (§10): hard gates + content/world integrity ----
    structural_violations = [
        {"case_id": r["case_id"], "repeat": r["repeat"],
         "gates": r.get("hard_gate_recompute_violations", [])}
        for r in completed
        if r.get("hard_gate_recompute_violations")
    ]
    proof_problems = []
    for r in rows:
        p = r.get("evidence_world_proof") or {}
        if not p:
            proof_problems.append(
                {"case_id": r["case_id"], "repeat": r["repeat"],
                 "problem": "missing world proof"}
            )
            continue
        if not p.get("match"):
            proof_problems.append(
                {"case_id": r["case_id"], "repeat": r["repeat"],
                 "problem": "world/hydration proof failed"}
            )
        hyd = p.get("hydration") or {}
        if hyd.get("content_integrity_failures"):
            proof_problems.append(
                {"case_id": r["case_id"], "repeat": r["repeat"],
                 "problem": "content integrity failure"}
            )
    structural = {
        "verdict": "PASS" if not structural_violations and not proof_problems
        else "FAIL",
        "hard_gate_violations": structural_violations,
        "evidence_world_and_content_integrity": proof_problems,
        "note": "zero tolerance: cross-task leak, fabricated evidence, "
        "graph-id-as-evidence, review-authority bypass, verification "
        "bypass, finalization-blocker bypass, evidence/content integrity",
    }

    # ---- functional (§11): per-family floor, no compensation ----
    families = {}
    for case_id in sorted({r["case_id"] for r in rows}):
        fam_rows = [r for r in completed if r["case_id"] == case_id]
        qualifying = [
            r for r in fam_rows
            if (r.get("case_outcome_v2") or {}).get("outcome") in _QUALIFYING
        ]
        families[case_id] = {
            "per_repetition": [
                {
                    "repeat": r["repeat"],
                    "outcome": (r.get("case_outcome_v2") or {}).get(
                        "outcome", "unavailable"
                    ),
                    "qualifies": (r.get("case_outcome_v2") or {}).get(
                        "outcome"
                    ) in _QUALIFYING,
                }
                for r in sorted(fam_rows, key=lambda x: x["repeat"])
            ],
            "qualifying_count": len(qualifying),
            "scheduled_reps": 3,
            "floor_met": len(qualifying) >= 2,
        }
    functional_pass = (
        all(f["floor_met"] for f in families.values()) and len(families) == 2
    )
    functional = {
        "verdict": "PASS" if functional_pass else "FAIL",
        "metric": "BenchmarkCaseOutcomeV2 (sole truth authority, §11)",
        "floor": "EVERY family >= 2/3 at {success, "
        "success_with_limitations}; no cross-family compensation",
        "families": families,
        "reporting_metrics_not_gates": {
            "runs_with_integrated_delegation": sum(
                1 for r in completed if (r.get("integrated") or 0) > 0
            ),
            "finalization_pass": sum(
                1 for r in completed if r.get("finalization_pass")
            ),
        },
    }

    # ---- semantic (§12): frozen evaluator semantics ----
    semantic_component_fails = [
        {"case_id": r["case_id"], "repeat": r["repeat"],
         "components": [
             c["component"] for c in (r.get("case_outcome_v2") or {}).get(
                 "components", []
             )
             if c["status"] == "fail" and not any(
                 m in c["component"] for m in _NEGATIVE_COMPONENT_MARKERS
             )
         ]}
        for r in completed
    ]
    semantic_component_fails = [f for f in semantic_component_fails if f["components"]]
    evaluate_only_all = all(
        r.get("evaluate_only_reproduced") for r in completed
    ) if completed else False
    semantic = {
        "verdict": "PASS" if not semantic_component_fails else "FAIL",
        "semantic_component_failures": semantic_component_fails,
        "evaluate_only_all_reproduced": evaluate_only_all,
        "note": "grounding/assertion-strength/question/coverage/limitation "
        "semantics computed by the frozen evaluator only; rubric "
        "untouched after seal",
    }

    # ---- negative-case (§13): zero tolerance per frozen gate classes ----
    negative_fails = [
        {"case_id": r["case_id"], "repeat": r["repeat"],
         "components": [
             c["component"] for c in (r.get("case_outcome_v2") or {}).get(
                 "components", []
             )
             if c["status"] == "fail" and any(
                 m in c["component"] for m in _NEGATIVE_COMPONENT_MARKERS
             )
         ]}
        for r in rows
    ]
    negative_fails = [f for f in negative_fails if f["components"]]
    negative = {
        "verdict": "PASS" if not negative_fails else "FAIL",
        "negative_gate_failures": negative_fails,
        "gate_classes": [
            "unsupported entity attribution", "unsupported causality",
            "fabricated factual support",
            "Analyst Context treated as Evidence",
        ],
    }

    # ---- reliability (§16): frozen thresholds, disaggregated ----
    rel = profile["acceptance_axes"]["reliability"]["requirements"]
    plan_fail_runs = sum(
        1 for r in rows
        if any(
            sf.get("delegations_admitted_before", 0) == 0
            and sf.get("delegations_completed_before", 0) == 0
            for sf in r.get("supervisor_failures", [])
        )
    )
    integrate_fail_runs = sum(
        1 for r in rows
        if any(
            sf.get("delegations_admitted_before", 0) > 0
            or sf.get("delegations_completed_before", 0) > 0
            for sf in r.get("supervisor_failures", [])
        )
    )
    specialist_fail_runs = sum(
        1 for r in rows
        if any(
            f.get("failure_code") == "agent_output_invalid"
            for f in r.get("delegation_failures", [])
        )
    )
    reliability = {
        "verdict": "PASS" if (
            plan_fail_runs / denom <= rel[
                "supervisor_plan_structured_output_failure_rate_max"
            ]
            and integrate_fail_runs / denom <= rel[
                "supervisor_integrate_structured_output_failure_rate_max"
            ]
            and specialist_fail_runs / denom <= rel[
                "specialist_structured_output_failure_rate_max"
            ]
        ) else "FAIL",
        "population": denom,
        "supervisor_plan_failure_runs": plan_fail_runs,
        "supervisor_integrate_failure_runs": integrate_fail_runs,
        "specialist_structured_output_failure_runs": specialist_fail_runs,
        "thresholds_frozen": {k: v for k, v in rel.items() if k != "note"},
    }

    # ---- availability (§17): frozen threshold ----
    avail_max = profile["acceptance_axes"]["provider_runtime_availability"][
        "requirements"
    ]["provider_terminal_runs_max_fraction"]
    provider_failed = sum(
        1 for r in rows
        if r["status"] == "runner_failed"
        and any(
            w in str(r.get("failure_reason", "")).lower()
            for w in _PROVIDER_WORDS
        )
    )
    availability = {
        "verdict": "PASS" if provider_failed / denom <= avail_max else "FAIL",
        "provider_terminal_runs": provider_failed,
        "population": denom,
        "fraction": round(provider_failed / denom, 4),
        "threshold_frozen": avail_max,
    }

    return {
        "structural": structural,
        "functional": functional,
        "semantic": semantic,
        "negative_case": negative,
        "reliability": reliability,
        "availability": availability,
    }


def main() -> int:
    from httpserver.services.investigation.agent_runtime import (
        canonical_state_json,
        state_hash_of,
    )

    seal = _load(GEN4_ROOT / "holdout-seal-v3.json")
    frozen = _load(GEN4_ROOT / "gen4-b6-frozen-inputs-v1.json")
    preflight = _load(GEN4_ROOT / "holdout-bootstrap-preflight-v4.json")
    execution = _load(GEN4_ROOT / "holdout-execution-manifest-v4.json")
    run_set = _load(GEN4_ROOT / "holdout-run-set-v4.json")
    profile = _load_json_tolerant(
        PROFILES / "agent-v0-acceptance-profile-v2.json"
    )

    rows = _collect()
    axes = _six_axes(rows, profile)
    completed = [r for r in rows if r["status"] == "completed"]

    # §27 verdict rules
    measurement_defect = (
        any(
            not (r.get("evidence_world_proof") or {}).get("match")
            and (r.get("evidence_world_proof") or {}).get(
                "parsed_world_match"
            ) != "indirect"
            for r in rows
        )
        or (completed and not all(
            r.get("evaluate_only_reproduced") for r in completed
        ))
    )
    all_pass = all(a["verdict"] == "PASS" for a in axes.values())
    if measurement_defect:
        overall = "B6_INVALID"
    elif all_pass:
        overall = "ACCEPTED"
    else:
        overall = "REJECTED"

    all_codes = [
        c for r in rows for c in r["rejection_codes"]
    ]
    evaluation = {
        "artifact_version": "HoldoutAcceptanceEvaluationV4",
        "generation_id": "acceptance-generation-4",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "run_set_hash": run_set["run_set_hash"],
        "seal_hash": seal["seal_hash"],
        "frozen_inputs_input_hash": frozen["input_hash"],
        "preflight_input_hash": preflight["input_hash"],
        "profile": "benchmarks/profiles/agent-v0-acceptance-profile-v2.json",
        "evaluator": "benchmark-case-outcome:v2 (deterministic; zero LLM)",
        "per_run": rows,
        "evaluate_only_reproduction": {
            "per_run": [
                {"case_id": r["case_id"], "repeat": r["repeat"],
                 "reproduced": r.get("evaluate_only_reproduced")}
                for r in completed
            ],
            "all_reproduced": bool(completed) and all(
                r.get("evaluate_only_reproduced") for r in completed
            ),
        },
        "six_axes": axes,
        "diagnosis": {
            "P_identity_events": sum(1 for c in all_codes if c in P_CODES),
            "H_handle_events": sum(1 for c in all_codes if c in H_CODES),
            "S_semantic_events": sum(1 for c in all_codes if c in S_CODES),
            "G_grounding_events": sum(1 for c in all_codes if c in G_CODES),
            "rejection_code_distribution": dict(Counter(all_codes)),
        },
        "cost": {
            "tokens_in_total": sum(r.get("tokens_in", 0) for r in completed),
            "tokens_out_total": sum(
                r.get("tokens_out", 0) for r in completed
            ),
            "wall_s_median": (
                statistics.median(
                    [r["wall_s"] for r in completed if r.get("wall_s")]
                )
                if any(r.get("wall_s") for r in completed) else None
            ),
        },
    }
    evaluation["input_hash"] = state_hash_of(
        canonical_state_json(
            {k: v for k, v in evaluation.items() if k != "input_hash"}
        )
    )
    (GEN4_ROOT / "holdout-acceptance-evaluation-v4.json").write_text(
        json.dumps(evaluation, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    closure_state = {
        "ACCEPTED": "CLOSED_ACCEPTED",
        "REJECTED": "CLOSED_REJECTED",
        "B6_INVALID": "CLOSED_INVALID",
    }[overall]

    decision = {
        "artifact_version": "AgentV0AcceptanceDecisionV4",
        "generation_id": "acceptance-generation-4",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "overall_verdict": overall,
        "verdict_rule": "spec §27: ACCEPTED only if ALL SIX axes PASS; "
        "any acceptance-axis FAIL -> REJECTED; measurement defect -> "
        "B6_INVALID",
        "six_axes": {k: v["verdict"] for k, v in axes.items()},
        "scope_limitation": (
            "ACCEPTED (if so) is strictly limited to: RuntimeBaselineV3 "
            "exact production runtime (incl. superseding record), "
            "evidence-content-hydration:v1, sensenova-6.8-flash-lite "
            "exact frozen config, AcceptanceProfileV2, Acceptance "
            "Generation 4"
        ),
        "runtime_identity": {
            "git_head_at_preflight": frozen["git_head"],
            "frozen_inputs_input_hash": frozen["input_hash"],
            "superseding_record": (
                "runtime-baseline-v3-superseding-record.json"
            ),
        },
        "model_identity": {
            "provider": "sensenova-cloud",
            "model_id": "sensenova-6.8-flash-lite",
            "model_config_sha256": frozen["model"]["config_sha256"],
        },
        "frozen_input_hashes": {
            "acceptance_profile_sha256": frozen["acceptance_profile_sha256"],
            "calibration_binding_sha256": frozen[
                "calibration_binding_sha256"
            ],
            "generation_binding_sha256": frozen[
                "generation_binding_sha256"
            ],
            "seal_hash": seal["seal_hash"],
            "run_set_hash": run_set["run_set_hash"],
            "preflight_input_hash": preflight["input_hash"],
        },
        "population": run_set["population"],
        "no_retry": True,
    }
    (GEN4_ROOT / "agent-v0-acceptance-decision-v4.json").write_text(
        json.dumps(decision, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    closure = {
        "artifact_version": "AcceptanceGenerationClosureV4",
        "generation_id": "acceptance-generation-4",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "closure_state": closure_state,
        "no_retry": "spec §31: no second Gen-4 B6 under any verdict; "
        "B6_INVALID would force Generation 5",
        "consumption": "Gen-4 holdout pool CONSUMED (all 6 scheduled "
        "attempts executed against the sealed cases)",
        "historical": {
            "Gen-1": "CLOSED_INVALID / CONSUMED",
            "Gen-2": "CLOSED_INVALID / CONSUMED",
            "Gen-3": "CLOSED_INVALID / CONSUMED",
            "Gen-4": f"{closure_state} / CONSUMED (verdict: {overall})",
        },
        "decision_ref": "agent-v0-acceptance-decision-v4.json",
        "evaluation_ref": "holdout-acceptance-evaluation-v4.json",
        "run_set_ref": "holdout-run-set-v4.json",
    }
    (GEN4_ROOT / "acceptance-generation-closure-v4.json").write_text(
        json.dumps(closure, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"run_set: {run_set['run_set_hash'][:16]}…")
    for name, axis in axes.items():
        print(f"axis {name}: {axis['verdict']}")
    for r in rows:
        oc = (r.get("case_outcome_v2") or {}).get("outcome", "-")
        print(
            f"  {r['case_id']:26s} {r['repeat']} {r['status']:14s} "
            f"outcome={oc}"
        )
    print(f"OVERALL: {overall} -> {closure_state}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
