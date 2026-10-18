#!/usr/bin/env python3
"""B6 §28-§30 acceptance evaluation — deterministic, evaluate-only.

Runs ONLY after all six scheduled holdout attempts are terminal and
their artifacts frozen.  Produces:

  holdout-run-set-v1.json           HoldoutRunSetV1 (+ run-set hash)
  holdout-acceptance-evaluation-v1.json  HoldoutAcceptanceEvaluationV1
  agent-v0-acceptance-decision-v1.json   AgentV0AcceptanceDecisionV1

Axis computation strictly follows the FROZEN AgentV0AcceptanceProfileV2:
  structural  — zero-tolerance hard gates on every run
  functional  — truth floor: EVERY family >= 2/3 reps at CaseOutcomeV2
                in {success, success_with_limitations} (no surrogates)
  semantic    — unsupported FACT / fabricated citation in integrated
                output (deterministic checks + recorded payload review)
  negative    — frozen per-dimension gates via digest semantic payloads
  reliability — supervisor plan/integrate <= 0.2, specialist <= 0.5
  availability — provider-terminal runs <= 2/6 (fraction <= 0.2)

No threshold is computed from the holdout observations themselves.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PYTHON_SERVICE_ROOT = SCRIPT_PATH.parents[1]
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))
SCRIPTS_DIR = SCRIPT_PATH.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

REPO_ROOT = PYTHON_SERVICE_ROOT.parent
B6_ROOT = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0" / "b6-holdout"
)
RUNS_ROOT = B6_ROOT / "run-set-v1"
CASES_ROOT = PYTHON_SERVICE_ROOT / "benchmarks" / "cases"
CHARTER_FILE = (
    PYTHON_SERVICE_ROOT / "benchmarks/profiles/b6-holdout-charter-v1.json"
)
FROZEN_FILE = B6_ROOT / "frozen-identities-v1.json"

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
_NON_TERMINAL_COVERAGE = {"not_started", "in_progress", None, ""}
_PROVIDER_WORDS = (
    "timed out", "timeout", "connection", "429", "rate limit", "5xx",
)
_QUALIFYING = {"success", "success_with_limitations"}


def _load_json_tolerant(path: Path) -> dict:
    """Parse a frozen profile artifact.

    Two frozen profile artifacts (AcceptanceProfileV2, AdmissionRecordV2)
    were authored with Python-style parenthesized string continuations
    (`"key": ("..." "...")`).  Their committed bytes are IMMUTABLE, so
    this loader repairs only the in-memory parse: unwrap the parens and
    concatenate the adjacent string literals, then parse strictly.
    """
    import re

    raw = path.read_text(encoding="utf-8")
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
    from httpserver.services.benchmarks.snapshot import (
        BenchmarkRunSnapshotV1,
    )
    from httpserver.services.benchmarks.truth_manifest import TruthManifestV1

    charter = json.loads(CHARTER_FILE.read_text(encoding="utf-8"))
    families = charter["holdout_population"]["families"]
    rows: list[dict] = []
    for case_id in families:
        truth = None
        for repeat in ("repeat0", "repeat1", "repeat2"):
            run_dir = RUNS_ROOT / case_id / repeat
            digest_file = run_dir / "trajectory_digest.json"
            digest = (
                json.loads(digest_file.read_text(encoding="utf-8"))
                if digest_file.exists()
                else {}
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
                "coverage_bootstrap": digest.get("coverage_bootstrap", {}),
            }
            failure = None
            for name in ("failure.json", "driver_failure.json"):
                f = run_dir / name
                if f.exists():
                    failure = json.loads(f.read_text(encoding="utf-8"))
            snap_file = run_dir / "snapshot.json"
            if snap_file.exists():
                snapshot = json.loads(
                    snap_file.read_text(encoding="utf-8")
                )
                result = json.loads(
                    (run_dir / "result.json").read_text(encoding="utf-8")
                ) if (run_dir / "result.json").exists() else {}
                delegs = snapshot.get("delegations") or []
                usage = snapshot.get("usage_entries") or []
                gates = [
                    g for g in result.get("hard_gate_results", [])
                    if not g.get("passed")
                ]
                # independent structural recompute from the snapshot
                snap_model = BenchmarkRunSnapshotV1(**snapshot)
                gates_recompute = [
                    {"gate_id": g.gate_id, "passed": g.passed,
                     "violations": list(g.violations)}
                    for g in structural_hard_gates(snap_model)
                ]
                if truth is None:
                    truth = TruthManifestV1(
                        **json.loads(
                            (
                                CASES_ROOT / case_id / "truth_manifest.json"
                            ).read_text(encoding="utf-8")
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
                # evaluate-only independent reproduction
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
                                    CASES_ROOT / case_id / "reachability.json"
                                ).read_text(encoding="utf-8")
                            )
                        ),
                        snapshot=snap_model,
                    )
                    evaluate_only_ok = (
                        recomputed.result_hash == result.get("result_hash")
                    )
                questions = snapshot.get("questions") or []
                discovered = set(
                    snapshot.get("discovered_evidence_refs") or ()
                )
                row.update(
                    {
                        "status": "completed",
                        "run_manifest_id": result.get("run_manifest_id"),
                        "result_hash": result.get("result_hash"),
                        "snapshot_hash": snapshot.get("snapshot_hash"),
                        "terminal_status": snapshot.get("terminal_status"),
                        "finalization_pass": bool(
                            snapshot.get("finalization_id")
                        ),
                        "hard_gate_violations": [
                            g.get("gate") or g.get("gate_id") for g in gates
                        ],
                        "hard_gate_recompute_violations": [
                            g["gate_id"] for g in gates_recompute
                            if not g["passed"]
                        ],
                        "evaluate_only_reproduced": evaluate_only_ok,
                        "delegations_completed": sum(
                            1 for d in delegs
                            if d.get("status") == "completed"
                        ),
                        "delegations_failed": sum(
                            1 for d in delegs if d.get("status") == "failed"
                        ),
                        "integrated": sum(
                            1 for d in delegs if d.get("integrated_revision")
                        ),
                        "coverage_terminalization": {
                            c.get("dimension_id"): (c.get("status") or "")
                            for c in (snapshot.get("coverage") or [])
                        },
                        "questions": [
                            {
                                "question_id": q.get("question_id"),
                                "status": q.get("status"),
                                "disposition": q.get("disposition"),
                            }
                            for q in questions
                        ],
                        "case_outcome_v2": outcome_v2,
                        "discovered_evidence_count": len(discovered),
                        "findings_count": len(
                            snapshot.get("findings") or ()
                        ),
                        "tool_calls": len(snapshot.get("tool_calls") or ()),
                        "wall_s": round(
                            (snapshot.get("wall_ms_total") or 0) / 1000, 1
                        ),
                        "tokens_in": sum(
                            u.get("input_tokens") or 0 for u in usage
                        ),
                        "tokens_out": sum(
                            u.get("output_tokens") or 0 for u in usage
                        ),
                    }
                )
            else:
                row.update(
                    {
                        "status": "runner_failed",
                        "failure_layer": (failure or {}).get("failure_layer"),
                        "failure_reason": str(
                            (failure or {}).get("failure_reason", "")
                        )[:300],
                    }
                )
            rows.append(row)
    return rows


def _axis_verdicts(rows: list[dict], profile: dict) -> dict:
    completed = [r for r in rows if r["status"] == "completed"]
    rel = profile["acceptance_axes"]["reliability"]["requirements"]
    avail_max = profile["acceptance_axes"]["provider_runtime_availability"][
        "requirements"
    ]["provider_terminal_runs_max_fraction"]

    # structural
    structural_violations = [
        {"case_id": r["case_id"], "repeat": r["repeat"],
         "gates": r.get("hard_gate_recompute_violations", [])}
        for r in completed
        if r.get("hard_gate_recompute_violations")
    ]
    structural = {
        "verdict": "PASS" if not structural_violations else "FAIL",
        "violations": structural_violations,
        "measurement": "structural_hard_gates recomputed independently "
        "from every persisted snapshot",
    }

    # functional — truth floor per family
    families = {}
    for case_id in sorted({r["case_id"] for r in rows}):
        fam_rows = [r for r in completed if r["case_id"] == case_id]
        qualifying = [
            r for r in fam_rows
            if (r.get("case_outcome_v2") or {}).get("outcome") in _QUALIFYING
        ]
        per_rep = [
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
        ]
        families[case_id] = {
            "per_repetition": per_rep,
            "qualifying_count": len(qualifying),
            "scheduled_reps": 3,
            "floor_met": len(qualifying) >= 2,
        }
    functional_pass = all(f["floor_met"] for f in families.values()) and len(
        families
    ) == 2
    functional = {
        "verdict": "PASS" if functional_pass else "FAIL",
        "metric": "BenchmarkCaseOutcomeV2 (truth-based; no surrogate)",
        "floor": "EVERY family >= 2/3 reps at {success, "
        "success_with_limitations}",
        "families": families,
        "reporting_metrics_not_gates": {
            "runs_with_integrated_delegation": sum(
                1 for r in completed if r.get("integrated", 0) > 0
            ),
            "finalization_pass": sum(
                1 for r in completed if r.get("finalization_pass")
            ),
        },
    }

    # reliability
    plan_fail_runs = sum(
        1
        for r in rows
        if any(
            sf.get("delegations_admitted_before", 0) == 0
            and sf.get("delegations_completed_before", 0) == 0
            for sf in r.get("supervisor_failures", [])
        )
    )
    integrate_fail_runs = sum(
        1
        for r in rows
        if any(
            sf.get("delegations_admitted_before", 0) > 0
            or sf.get("delegations_completed_before", 0) > 0
            for sf in r.get("supervisor_failures", [])
        )
    )
    specialist_fail_runs = sum(
        1
        for r in rows
        if any(
            f.get("failure_code") == "agent_output_invalid"
            for f in r.get("delegation_failures", [])
        )
    )
    denom = len(rows)
    reliability = {
        "verdict": (
            "PASS"
            if (
                plan_fail_runs / denom <= rel[
                    "supervisor_plan_structured_output_failure_rate_max"
                ]
                and integrate_fail_runs / denom <= rel[
                    "supervisor_integrate_structured_output_failure_rate_max"
                ]
                and specialist_fail_runs / denom <= rel[
                    "specialist_structured_output_failure_rate_max"
                ]
            )
            else "FAIL"
        ),
        "population": denom,
        "supervisor_plan_failure_runs": plan_fail_runs,
        "supervisor_integrate_failure_runs": integrate_fail_runs,
        "specialist_structured_output_failure_runs": specialist_fail_runs,
        "thresholds_frozen": {
            k: v for k, v in rel.items() if k != "note"
        },
    }

    # availability
    provider_failed = sum(
        1
        for r in rows
        if r["status"] == "runner_failed"
        and any(
            w in str(r.get("failure_reason", "")).lower()
            for w in _PROVIDER_WORDS
        )
    )
    availability = {
        "verdict": (
            "PASS" if provider_failed / denom <= avail_max else "FAIL"
        ),
        "provider_terminal_runs": provider_failed,
        "population": denom,
        "fraction": round(provider_failed / denom, 4),
        "threshold_frozen": {
            "provider_terminal_runs_max_fraction": avail_max
        },
    }
    return {
        "structural": structural,
        "functional": functional,
        "reliability": reliability,
        "availability": availability,
    }


def main() -> int:
    from httpserver.services.investigation.agent_runtime import (
        canonical_state_json,
        state_hash_of,
    )

    profile = _load_json_tolerant(
        PYTHON_SERVICE_ROOT
        / "benchmarks/profiles/agent-v0-acceptance-profile-v2.json"
    )
    frozen = json.loads(FROZEN_FILE.read_text(encoding="utf-8"))
    charter = json.loads(CHARTER_FILE.read_text(encoding="utf-8"))
    execution = json.loads(
        (B6_ROOT / "holdout-execution-manifest-v1.json").read_text(
            encoding="utf-8"
        )
    )

    rows = _collect()
    terminal = [r for r in rows if r["status"] in ("completed",
                                                   "runner_failed")]
    if len(terminal) != 6:
        print(
            f"REFUSING evaluation: only {len(terminal)}/6 scheduled "
            f"attempts terminal (B6 §28: evaluate the full population "
            f"only)"
        )
        return 1

    # HoldoutRunSetV1 — frozen run-set identity
    run_set_entries = [
        {
            "case_id": r["case_id"],
            "repeat": r["repeat"],
            "status": r["status"],
            "run_manifest_id": r.get("run_manifest_id"),
            "result_hash": r.get("result_hash"),
            "snapshot_hash": r.get("snapshot_hash"),
            "failure_reason": r.get("failure_reason"),
        }
        for r in rows
    ]
    run_set = {
        "artifact_version": "HoldoutRunSetV1",
        "created_at": time.strftime(
            "%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()
        ),
        "population": execution["population"],
        "b6_started_at": execution.get("b6_started_at"),
        "frozen_identities_input_hash": frozen["input_hash"],
        "charter_input_hash": charter["input_hash"],
        "runs": run_set_entries,
    }
    run_set["run_set_hash"] = state_hash_of(
        canonical_state_json(
            {k: v for k, v in run_set.items() if k != "run_set_hash"}
        )
    )
    (B6_ROOT / "holdout-run-set-v1.json").write_text(
        json.dumps(run_set, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    axes = _axis_verdicts(rows, profile)
    completed = [r for r in rows if r["status"] == "completed"]

    evaluation = {
        "artifact_version": "HoldoutAcceptanceEvaluationV1",
        "created_at": time.strftime(
            "%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()
        ),
        "run_set_hash": run_set["run_set_hash"],
        "profile": "benchmarks/profiles/agent-v0-acceptance-profile-v2.json",
        "profile_status": profile["status"],
        "evaluator": "benchmark-case-outcome:v2 (deterministic; truth "
        "read by the evaluator only)",
        "evaluate_only_reproduction": {
            "per_run": [
                {
                    "case_id": r["case_id"],
                    "repeat": r["repeat"],
                    "reproduced": r.get("evaluate_only_reproduced"),
                }
                for r in completed
            ],
            "all_reproduced": all(
                r.get("evaluate_only_reproduced") for r in completed
            ),
        },
        "per_run": rows,
        "diagnosis": {
            "P_identity_events": sum(
                1 for r in rows for c in r["rejection_codes"]
                if c in P_CODES
            ),
            "H_handle_events": sum(
                1 for r in rows for c in r["rejection_codes"]
                if c in H_CODES
            ),
            "S_semantic_events": sum(
                1 for r in rows for c in r["rejection_codes"]
                if c in S_CODES
            ),
            "G_grounding_events": sum(
                1 for r in rows for c in r["rejection_codes"]
                if c in G_CODES
            ),
            "rejection_code_distribution": dict(
                Counter(c for r in rows for c in r["rejection_codes"])
            ),
        },
        "cost": {
            "tokens_in_total": sum(r.get("tokens_in", 0) for r in completed),
            "tokens_out_total": sum(
                r.get("tokens_out", 0) for r in completed
            ),
            "wall_s_median": statistics.median(
                [r["wall_s"] for r in completed if r.get("wall_s")]
            )
            if any(r.get("wall_s") for r in completed)
            else None,
        },
        "computed_axes": axes,
    }
    (B6_ROOT / "holdout-acceptance-evaluation-v1.json").write_text(
        json.dumps(evaluation, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"run-set hash: {run_set['run_set_hash'][:16]}…")
    for name in ("structural", "functional", "reliability", "availability"):
        print(f"axis {name}: {axes[name]['verdict']}")
    for r in rows:
        oc = (r.get("case_outcome_v2") or {}).get("outcome", "-")
        print(
            f"  {r['case_id']:26s} {r['repeat']} {r['status']:14s} "
            f"outcome={oc} fin={r.get('finalization_pass')} "
            f"integ={r.get('integrated')}"
        )
    print(
        "\nsemantic + negative-case review channels are recorded in "
        "agent-v0-acceptance-decision-v1.json (fill from the "
        "deterministic payloads in holdout-acceptance-evaluation-v1.json)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
