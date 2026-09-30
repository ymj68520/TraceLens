#!/usr/bin/env python3
"""Post-B5.5 B2 report — PostB55BaselineMeasurementReportV1 (spec §25).

Consumes benchmarks/results/agent-v0/b2-restart/b2-post-b55 with
evaluator v2 (production-faithful disposition semantics) + digest v5
(coverage bootstrap proof, specialist semantic payloads) and emits the
admission-decision measurement report:

- 24-run matrix, CaseOutcomeV2 distribution, per-case 3-repeat grid
- coverage terminalization per required dimension (§13: terminal ∈
  {covered, partial, unavailable, not_applicable}; not_started/
  in_progress are non-terminal) and question terminalization (§15)
- P/H/S/G, specialist/PLAN/INTEGRATE output failures split
- negative-case correctness signals (from digest semantic payloads)
- FinalizationPass reconciliation, provider/runtime availability,
  cost, failure attribution
- coverage bootstrap join: case.json expected dims vs digest seeded dims

Usage (from python_service/):
    .venv/bin/python scripts/build_post_b55_report.py
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

ROOT = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0" / "b2-restart"
)
import os
RUNS_ROOT = ROOT / os.environ.get("POST_B55_RUNS_ROOT", "b2-post-b55")
CASES_ROOT = PYTHON_SERVICE_ROOT / "benchmarks" / "cases"
BASELINE = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "profiles"
    / "benchmark-measurement-baseline-v5.json"
)
OUT_FILE = RUNS_ROOT / "post-b55-measurement-report-v1.json"

P_CODES = {
    "PLAN_IDENTITY_MISMATCH", "PLAN_ATTENTION_HASH_MISMATCH",
    "PLAN_STATE_REVISION_STALE", "INTEGRATION_IDENTITY_MISMATCH",
    "INTEGRATION_STATE_REVISION_STALE", "INTEGRATION_SOURCE_RESULT_UNKNOWN",
    "INTEGRATION_SOURCE_RESULT_HASH_MISMATCH",
    "INTEGRATION_BASIS_REF_UNKNOWN", "INTEGRATION_EVIDENCE_REF_INVALID",
    "INTEGRATION_PROPOSAL_REF_UNRESOLVED",
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


def main() -> int:
    from httpserver.services.benchmarks.metrics import structural_hard_gates
    from httpserver.services.benchmarks.snapshot import BenchmarkRunSnapshotV1
    from httpserver.services.benchmarks.case_outcome import (
        evaluate_case_outcome_v2,
    )
    from httpserver.services.benchmarks.truth_manifest import TruthManifestV1

    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    runs: list[dict] = []
    bootstrap_join: list[dict] = []

    for case_dir in sorted(p for p in RUNS_ROOT.iterdir() if p.is_dir()):
        case_id = case_dir.name
        case_payload = json.loads(
            (CASES_ROOT / case_id / "case.json").read_text(encoding="utf-8")
        )
        expected_dims = sorted(
            case_payload.get("required_coverage_dimensions", ())
        )
        truth = None
        for run_dir in sorted(p for p in case_dir.iterdir() if p.is_dir()):
            digest_file = run_dir / "trajectory_digest.json"
            digest = (
                json.loads(digest_file.read_text(encoding="utf-8"))
                if digest_file.exists()
                else {}
            )
            row: dict = {
                "case_id": case_id,
                "repeat": run_dir.name,
                "status": "no_artifacts",
                "rejection_codes": digest.get("rejection_codes", []),
                "rejections": digest.get("rejections", []),
                "supervisor_failures": digest.get("supervisor_failures", []),
                "delegation_failures": digest.get("delegation_failures", []),
                "completions": digest.get("completions", []),
                "finalization_event": digest.get("finalization", {}),
            }
            failure = None
            for name in ("failure.json", "driver_failure.json"):
                f = run_dir / name
                if f.exists():
                    failure = json.loads(f.read_text(encoding="utf-8"))
            snap_file = run_dir / "snapshot.json"
            if snap_file.exists():
                snapshot = json.loads(snap_file.read_text(encoding="utf-8"))
                result_file = run_dir / "result.json"
                result = (
                    json.loads(result_file.read_text(encoding="utf-8"))
                    if result_file.exists()
                    else {}
                )
                delegs = snapshot.get("delegations") or []
                integrated = sum(
                    1 for d in delegs if d.get("integrated_revision")
                )
                usage = snapshot.get("usage_entries") or []
                gates = [
                    g
                    for g in result.get("hard_gate_results", [])
                    if not g.get("passed")
                ]
                coverage_rows = snapshot.get("coverage") or []
                coverage_terminalization = {
                    c.get("dimension_id"): (c.get("status") or "")
                    for c in coverage_rows
                }
                questions = [
                    {
                        "question_id": q.get("question_id"),
                        "status": q.get("status"),
                        "disposition": q.get("disposition"),
                    }
                    for q in (snapshot.get("questions") or ())
                ]
                # evaluator v2 outcome
                outcome_v2 = None
                if truth is None:
                    truth = TruthManifestV1(
                        **json.loads(
                            (
                                CASES_ROOT / case_id / "truth_manifest.json"
                            ).read_text(encoding="utf-8")
                        )
                    )
                try:
                    snap_model = BenchmarkRunSnapshotV1(**snapshot)
                    gates_v2 = [
                        {"gate_id": g.gate_id, "passed": g.passed,
                         "violations": list(g.violations)}
                        for g in structural_hard_gates(snap_model)
                    ]
                    payloads = [
                        c.get("result_semantic_payload") or {}
                        for c in digest.get("completions", [])
                    ]
                    oc = evaluate_case_outcome_v2(
                        truth=truth,
                        snapshot=snap_model,
                        hard_gates=gates_v2,
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
                row.update(
                    {
                        "status": "completed",
                        "terminal_status": snapshot.get("terminal_status"),
                        "finalization_pass": bool(
                            snapshot.get("finalization_id")
                        ),
                        "hard_gate_violations": [
                            g.get("gate") or g.get("gate_id")
                            for g in gates
                        ],
                        "delegations_completed": sum(
                            1 for d in delegs
                            if d.get("status") == "completed"
                        ),
                        "delegations_failed": sum(
                            1 for d in delegs if d.get("status") == "failed"
                        ),
                        "integrated": integrated,
                        "coverage_terminalization": coverage_terminalization,
                        "questions": questions,
                        "case_outcome_v2": outcome_v2,
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
                        "failure_reason": None,
                    }
                )
                seeded = (
                    digest.get("coverage_bootstrap", {}).get(
                        "seeded_coverage_dimensions"
                    )
                )
                bootstrap_join.append(
                    {
                        "case_id": case_id,
                        "repeat": run_dir.name,
                        "expected": expected_dims,
                        "seeded": seeded,
                        "match": (
                            sorted(seeded) == expected_dims
                            if isinstance(seeded, list)
                            else None
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
                        )[:200],
                    }
                )
            runs.append(row)

    completed = [r for r in runs if r["status"] == "completed"]
    code_counter = Counter(
        c for r in runs for c in r["rejection_codes"]
    )

    # §13 coverage terminalization across completed runs
    coverage_summary: dict = {}
    for r in completed:
        for dim, status in (
            r.get("coverage_terminalization") or {}
        ).items():
            entry = coverage_summary.setdefault(
                dim, {"terminalizations": Counter(), "runs": 0}
            )
            entry["terminalizations"][status or "absent"] += 1
            entry["runs"] += 1
    coverage_report = {
        dim: {
            "runs": e["runs"],
            "terminalizations": dict(e["terminalizations"]),
            "terminal": any(
                s not in _NON_TERMINAL_COVERAGE
                for s in e["terminalizations"]
            ),
        }
        for dim, e in sorted(coverage_summary.items())
    }

    # question terminalization
    q_summary = {"terminal": 0, "non_terminal": 0, "dispositions": Counter()}
    for r in completed:
        for q in r.get("questions", []):
            if q.get("status") in ("open", "in_progress", None):
                q_summary["non_terminal"] += 1
            else:
                q_summary["terminal"] += 1
                q_summary["dispositions"][q.get("disposition") or "none"] += 1
    q_summary["dispositions"] = dict(q_summary["dispositions"])

    totals = {
        "runs_total": len(runs),
        "runs_completed": len(completed),
        "runs_runner_failed": len(runs) - len(completed),
        "hard_gate_violation_runs": sum(
            1 for r in completed if r.get("hard_gate_violations")
        ),
        "finalization_pass": sum(
            1 for r in completed if r.get("finalization_pass")
        ),
        "runs_with_completed_specialist_result": sum(
            1 for r in completed if r.get("delegations_completed", 0) > 0
        ),
        "total_completed_specialist_results": sum(
            r.get("delegations_completed", 0) for r in completed
        ),
        "runs_with_integrated_delegation": sum(
            1 for r in completed if r.get("integrated", 0) > 0
        ),
        "integrated_delegation_count": sum(
            r.get("integrated", 0) for r in completed
        ),
        "specialist_structured_output_failures": sum(
            1
            for r in runs
            if any(
                f.get("failure_code") == "agent_output_invalid"
                for f in r.get("delegation_failures", [])
            )
        ),
        "supervisor_plan_failures": sum(
            1
            for r in runs
            if any(
                sf.get("delegations_admitted_before", 0) == 0
                and sf.get("delegations_completed_before", 0) == 0
                for sf in r.get("supervisor_failures", [])
            )
        ),
        "supervisor_integrate_failures": sum(
            1
            for r in runs
            if any(
                sf.get("delegations_admitted_before", 0) > 0
                or sf.get("delegations_completed_before", 0) > 0
                for sf in r.get("supervisor_failures", [])
            )
        ),
        "provider_failure_runs": sum(
            1
            for r in runs
            if r["status"] == "runner_failed"
            and any(
                w in str(r.get("failure_reason", "")).lower()
                for w in ("timed out", "timeout", "connection", "429",
                          "rate limit")
            )
        ),
        "P_identity_events": sum(
            1 for r in runs for c in r["rejection_codes"] if c in P_CODES
        ),
        "H_handle_events": sum(
            1 for r in runs for c in r["rejection_codes"] if c in H_CODES
        ),
        "S_semantic_events": sum(
            1 for r in runs for c in r["rejection_codes"] if c in S_CODES
        ),
        "G_grounding_events": sum(
            1 for r in runs for c in r["rejection_codes"] if c in G_CODES
        ),
        "rejection_code_distribution": dict(code_counter),
        "tokens_in_total": sum(r.get("tokens_in", 0) for r in completed),
        "tokens_out_total": sum(r.get("tokens_out", 0) for r in completed),
        "wall_s_median": statistics.median(
            [r["wall_s"] for r in completed if r.get("wall_s")] or [None]
        )
        if any(r.get("wall_s") for r in completed)
        else None,
    }

    case_outcome_v2_distribution = dict(
        Counter(
            (r.get("case_outcome_v2") or {}).get("outcome", "unavailable")
            for r in completed
        )
    )

    report = {
        "artifact_version": "PostB55BaselineMeasurementReportV1",
        "round": "post-b55-b2-acceptance-admission",
        "created_at": time.strftime(
            "%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()
        ),
        "measurement_baseline": baseline,
        "totals": totals,
        "case_outcome_v2_distribution": case_outcome_v2_distribution,
        "coverage_bootstrap_join": bootstrap_join,
        "coverage_terminalization": coverage_report,
        "question_terminalization": q_summary,
        "runs": runs,
    }
    OUT_FILE.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"report -> {OUT_FILE}")
    t = totals
    print(
        f"runs={t['runs_total']} done={t['runs_completed']} "
        f"gate_viol={t['hard_gate_violation_runs']} "
        f"P={t['P_identity_events']} H={t['H_handle_events']} "
        f"S={t['S_semantic_events']} G={t['G_grounding_events']}"
    )
    print("CaseOutcomeV2:", case_outcome_v2_distribution)
    print(
        f"integrated={t['integrated_delegation_count']} "
        f"runs_w_integ={t['runs_with_integrated_delegation']} "
        f"fin={t['finalization_pass']} "
        f"specialist_fail={t['specialist_structured_output_failures']} "
        f"sup={t['supervisor_plan_failures']}/"
        f"{t['supervisor_integrate_failures']} "
        f"provider={t['provider_failure_runs']}"
    )
    print("coverage:", json.dumps(coverage_report, ensure_ascii=False)[:400])
    print("questions:", json.dumps(q_summary)[:200])
    matched = sum(1 for b in bootstrap_join if b["match"])
    print(
        f"bootstrap join: {matched}/{len(bootstrap_join)} expected==seeded"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
