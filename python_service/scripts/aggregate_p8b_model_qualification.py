#!/usr/bin/env python3
"""P8B Model Qualification — Q1/Q2 aggregation (§10/§11/§19).

Walks each candidate's run dirs under
benchmarks/results/agent-v0/model-qualification/<candidate_id>/<case>/repeat<k>/,
re-evaluates every persisted run deterministically (evaluate-only), computes
BenchmarkCaseOutcomeV1 per run (case_outcome.py), and emits a per-candidate
screening report comparable against the frozen MiMo 24-run reference
baseline under benchmarks/results/agent-v0/baseline/.

No single aggregate score is produced (§10): the report carries the case
outcome distribution first, then integration validity, semantic
correctness components, reliability and cost columns.

Usage (from python_service/):
    .venv/bin/python scripts/aggregate_p8b_model_qualification.py \
        [--phase q1]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PYTHON_SERVICE_ROOT = SCRIPT_PATH.parents[1]
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

RESULTS_ROOT = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0"
)
QUAL_ROOT = RESULTS_ROOT / "model-qualification"
BASELINE_ROOT = RESULTS_ROOT / "baseline"
CASES_ROOT = PYTHON_SERVICE_ROOT / "benchmarks" / "cases"
CORPUS_FILE = (
    PYTHON_SERVICE_ROOT
    / "benchmarks/corpus/corpus-agent-v0-calibration.v1.json"
)

MIMO_REFERENCE = "mimo-v2.6-flash-reference"


def _evaluate_run(case_id: str, run_dir: Path) -> dict:
    from httpserver.services.benchmarks.snapshot import (
        BenchmarkRunSnapshotV1,
    )
    from httpserver.services.benchmarks.run_manifest import (
        BenchmarkRunManifestV1,
    )
    from httpserver.services.benchmarks.truth_manifest import (
        ReachabilityManifestV1,
        TruthManifestV1,
    )
    from httpserver.services.benchmarks.runner import evaluate_only
    from httpserver.services.benchmarks.case_outcome import (
        evaluate_case_outcome,
    )

    case_dir = CASES_ROOT / case_id
    manifest = BenchmarkRunManifestV1(
        **json.loads(
            (run_dir / "run_manifest.json").read_text(encoding="utf-8")
        )
    )
    snapshot = BenchmarkRunSnapshotV1(
        **json.loads(
            (run_dir / "snapshot.json").read_text(encoding="utf-8")
        )
    )
    truth = TruthManifestV1(
        **json.loads(
            (case_dir / "truth_manifest.json").read_text(encoding="utf-8")
        )
    )
    reach = ReachabilityManifestV1(
        **json.loads(
            (case_dir / "reachability.json").read_text(encoding="utf-8")
        )
    )
    result = evaluate_only(
        run_manifest=manifest,
        truth_manifest=truth,
        reachability=reach,
        snapshot=snapshot,
    )
    result_dict = json.loads(result.model_dump_json())
    outcome = evaluate_case_outcome(
        truth=truth,
        snapshot=snapshot,
        hard_gates=result_dict["hard_gate_results"],
    )
    return {
        "result": result_dict,
        "outcome": json.loads(outcome.model_dump_json()),
        "snapshot": json.loads(snapshot.model_dump_json()),
    }


def _recall_against_truth(case_id: str, snapshot: dict) -> dict:
    truth = json.loads(
        (CASES_ROOT / case_id / "truth_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    expected_critical = [
        e["expected_evidence_key"]
        for e in truth.get("critical_evidence", [])
    ]
    discovered = set(snapshot.get("discovered_evidence_refs") or ())
    hits = [k for k in expected_critical if k and k in discovered]
    expected_n = len([k for k in expected_critical if k])
    return {
        "critical_recall_hits": len(hits),
        "critical_recall_expected": expected_n,
        "critical_recall": (
            f"{len(hits)}/{expected_n}" if expected_n else "n/a"
        ),
    }


def _tool_stats(snapshot: dict) -> dict:
    calls = snapshot.get("tool_calls") or []
    return {
        "tool_calls_total": len(calls),
        "tool_calls_ok": sum(
            1 for c in calls if c.get("status") == "ok"
        ),
    }


def _rejection_reasons(run_dir: Path) -> list[str]:
    tj = run_dir / "trajectory_digest.json"
    if tj.exists():
        return json.loads(tj.read_text(encoding="utf-8"))
    return []


def _aggregate_candidate(candidate_id: str, root: Path, corpus_cases) -> dict:
    entry: dict = {
        "candidate_id": candidate_id,
        "results_root": str(root.relative_to(PYTHON_SERVICE_ROOT)),
        "runs": [],
        "not_run_cases": [],
        "outcome_distribution": Counter(),
        "hard_gate_violations": [],
        "rejection_reasons": Counter(),
    }
    for case_id in corpus_cases:
        case_root = root / case_id
        if not case_root.is_dir():
            entry["not_run_cases"].append(case_id)
            continue
        for run_dir in sorted(p for p in case_root.iterdir() if p.is_dir()):
            has_failure = (run_dir / "failure.json").exists()
            has_driver_failure = (
                run_dir / "driver_failure.json"
            ).exists()
            has_result = (run_dir / "result.json").exists()
            if not (has_failure or has_driver_failure or has_result):
                entry["not_run_cases"].append(f"{case_id}/{run_dir.name}")
                continue
            row: dict = {
                "run_dir": f"{case_id}/{run_dir.name}",
            }
            if has_failure and not has_result:
                failure = json.loads(
                    (run_dir / "failure.json").read_text(
                        encoding="utf-8"
                    )
                )
                reason = str(failure.get("failure_reason", ""))
                row.update(
                    {
                        "status": "runner_failed",
                        "failure_layer": failure.get("failure_layer"),
                        "failure_reason": reason[:300],
                        "provider_failure": any(
                            token in reason.lower()
                            for token in (
                                "timeout",
                                "connection",
                                "429",
                                "5xx",
                                "status_code: 5",
                                "rate",
                                "provider",
                                "渠道",
                                "channel",
                            )
                        ),
                        "outcome": "unavailable",
                    }
                )
                entry["runs"].append(row)
                continue
            if has_driver_failure and not has_result:
                failure = json.loads(
                    (run_dir / "driver_failure.json").read_text(
                        encoding="utf-8"
                    )
                )
                row.update(
                    {
                        "status": "driver_failed",
                        "failure_reason": failure.get("error", "")[:300],
                        "provider_failure": False,
                        "outcome": "unavailable",
                    }
                )
                entry["runs"].append(row)
                continue

            evaluated = _evaluate_run(case_id, run_dir)
            result = evaluated["result"]
            snapshot = evaluated["snapshot"]
            gates = result.get("hard_gate_results", [])
            violations = [g for g in gates if not g.get("passed")]
            if violations:
                entry["hard_gate_violations"].append(
                    {"run": row["run_dir"], "gates": [
                        g.get("gate_id") for g in violations
                    ]}
                )
            delegs = snapshot.get("delegations") or []
            integrated = any(
                d.get("integrated_revision") for d in delegs
            )
            usage = snapshot.get("usage_entries") or []
            outcome = evaluated["outcome"]
            entry["outcome_distribution"][outcome["outcome"]] += 1
            reasons = _rejection_reasons(run_dir)
            entry["rejection_reasons"].update(reasons)
            row.update(
                {
                    "status": "completed",
                    "run_id": result.get("run_manifest_id"),
                    "result_hash": result.get("result_hash"),
                    "outcome": outcome["outcome"],
                    "outcome_rationale": outcome.get("rationale", "")[:200],
                    "finalization_pass": bool(
                        snapshot.get("finalization_id")
                    ),
                    "integration_invalid_count_level": bool(
                        not integrated
                    ),
                    "semantic_output_available": integrated
                    or bool(snapshot.get("findings")),
                    "delegations": len(delegs),
                    "delegations_integrated": sum(
                        1 for d in delegs if d.get("integrated_revision")
                    ),
                    "wall_ms_total": snapshot.get("wall_ms_total"),
                    "usage_tokens": {
                        "input": sum(
                            u.get("input_tokens") or 0 for u in usage
                        ),
                        "output": sum(
                            u.get("output_tokens") or 0 for u in usage
                        ),
                    },
                    "rejection_reasons": reasons,
                    **_recall_against_truth(case_id, snapshot),
                    **_tool_stats(snapshot),
                }
            )
            entry["runs"].append(row)

    runs = entry["runs"]
    completed = [r for r in runs if r.get("status") == "completed"]
    walls = [
        r["wall_ms_total"]
        for r in completed
        if r.get("wall_ms_total")
    ]
    entry["summary"] = {
        "runs_total": len(runs),
        "runs_completed": len(completed),
        "runs_runner_failed": sum(
            1 for r in runs if r.get("status") == "runner_failed"
        ),
        "provider_failure_runs": sum(
            1 for r in runs if r.get("provider_failure")
        ),
        "finalization_pass": sum(
            1 for r in completed if r.get("finalization_pass")
        ),
        "case_outcome_success": entry["outcome_distribution"].get(
            "success", 0
        )
        + entry["outcome_distribution"].get(
            "success_with_limitations", 0
        ),
        "case_outcome_distribution": dict(entry["outcome_distribution"]),
        "integration_invalid_runs": sum(
            1 for r in completed
            if r.get("integration_invalid_count_level")
        ),
        "hard_gates_all_passed": not entry["hard_gate_violations"],
        "wall_ms_median": statistics.median(walls) if walls else None,
        "tokens_input_total": sum(
            r["usage_tokens"]["input"] for r in completed
        ),
        "tokens_output_total": sum(
            r["usage_tokens"]["output"] for r in completed
        ),
        "rejection_reason_distribution": dict(
            entry["rejection_reasons"]
        ),
    }
    entry["outcome_distribution"] = dict(entry["outcome_distribution"])
    entry["rejection_reasons"] = dict(entry["rejection_reasons"])
    return entry


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", default="q1",
                        choices=["q1", "q2"])
    args = parser.parse_args()

    corpus = json.loads(CORPUS_FILE.read_text(encoding="utf-8"))
    corpus_cases = [c["case_id"] for c in corpus["calibration_cases"]]

    candidates = [MIMO_REFERENCE]  # frozen 24-run reference baseline
    candidates += [
        p.name
        for p in sorted(QUAL_ROOT.iterdir())
        if p.is_dir()
        and p.name != MIMO_REFERENCE
        and p.name != "configs"
    ]

    report = {
        "report_version": "model-qualification-screening-report:v1",
        "phase": args.phase,
        "corpus_id": corpus["corpus_id"],
        "corpus_hash": corpus["input_hash"],
        "production_runtime_commit": (
            "946f325eeb6add1072466aed96e5e2e7e38748ed"
        ),
        "candidates": {},
        "candidate_order": candidates,
    }
    for candidate_id in candidates:
        root = (
            BASELINE_ROOT
            if candidate_id == MIMO_REFERENCE
            else QUAL_ROOT / candidate_id
        )
        report["candidates"][candidate_id] = _aggregate_candidate(
            candidate_id, root, corpus_cases
        )

    out_file = QUAL_ROOT / f"{args.phase}-screening-report.v1.json"
    out_file.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"report -> {out_file}\n")
    header = (
        f"{'candidate':32} {'runs':>4} {'fin':>4} {'succ':>4} "
        f"{'integ-inv':>9} {'gates':>6} {'prov-fail':>9} "
        f"{'wall_med_s':>10}"
    )
    print(header)
    for cid, entry in report["candidates"].items():
        s = entry["summary"]
        wall = s["wall_ms_median"]
        print(
            f"{cid:32} {s['runs_total']:>4} {s['finalization_pass']:>4} "
            f"{s['case_outcome_success']:>4} "
            f"{s['integration_invalid_runs']:>9} "
            f"{'PASS' if s['hard_gates_all_passed'] else 'VIOL':>6} "
            f"{s['provider_failure_runs']:>9} "
            f"{(round(wall/1000, 1) if wall else '-'):>10}"
        )
        print(
            f"{'  outcomes':32} {s['case_outcome_distribution']} "
            f"not_run={len(entry['not_run_cases'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
