#!/usr/bin/env python3
"""P8B §13-§19 B2 baseline aggregation.

Reads every persisted baseline run under
benchmarks/results/agent-v0/baseline/<case_id>/repeat<k>/, evaluates
deterministically from the persisted snapshots (§17 evaluate-only), and
emits BaselineMeasurementReportV1 with per-case/per-run distributions,
SupervisorIntegrationProposalInvalidRate by reason (§11), functional
completion classification (§15), semantic_output_available flag (§14),
structural hard gates (§16), and failure attribution.

Usage (from python_service/):
    .venv/bin/python scripts/aggregate_p8b_baseline.py
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PYTHON_SERVICE_ROOT = SCRIPT_PATH.parents[1]
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

BASELINE_ROOT = PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0" / "baseline"
CASES_ROOT = PYTHON_SERVICE_ROOT / "benchmarks" / "cases"
CORPUS_FILE = PYTHON_SERVICE_ROOT / "benchmarks" / "corpus" / "corpus-agent-v0-b2.v1.json"
REPORT_FILE = BASELINE_ROOT / "baseline-measurement-report.v1.json"


def _evaluate_run(case_id: str, run_dir: Path) -> dict:
    from httpserver.services.benchmarks.snapshot import BenchmarkRunSnapshotV1
    from httpserver.services.benchmarks.run_manifest import BenchmarkRunManifestV1
    from httpserver.services.benchmarks.truth_manifest import (
        ReachabilityManifestV1,
        TruthManifestV1,
    )
    from httpserver.services.benchmarks.runner import evaluate_only

    case_dir = CASES_ROOT / case_id
    manifest = BenchmarkRunManifestV1(
        **json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    )
    snapshot = BenchmarkRunSnapshotV1(
        **json.loads((run_dir / "snapshot.json").read_text(encoding="utf-8"))
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
    (run_dir / "result.json").write_text(
        result.model_dump_json(), encoding="utf-8"
    )
    return json.loads(result.model_dump_json())


def _critical_recall(result: dict, snapshot: dict) -> str:
    avail = result.get("availability_summary", {})
    discoverable = avail.get("critical_agent_discoverable", 0)
    if not discoverable:
        return "unavailable"
    keys = set(snapshot.get("discovered_evidence_refs") or ())
    truth = json.loads(
        (CASES_ROOT / snapshot["task_id"] and "{}").read_text()
    ) if False else None
    return f"computed-elsewhere:{discoverable}"


def _recall_against_truth(case_id: str, snapshot: dict) -> dict:
    """Deterministic recall/precision over truth-expected evidence keys."""
    truth = json.loads(
        (CASES_ROOT / case_id / "truth_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    expected_critical = [
        e["expected_evidence_key"] for e in truth["critical_evidence"]
    ]
    expected_supporting = [
        e["expected_evidence_key"] for e in truth["supporting_evidence"]
    ]
    discovered = set(snapshot.get("discovered_evidence_refs") or ())
    crit_hit = [k for k in expected_critical if k and k in discovered]
    supp_hit = [k for k in expected_supporting if k and k in discovered]
    return {
        "critical_recall": f"{len(crit_hit)}/{len([k for k in expected_critical if k])}",
        "supporting_recall": f"{len(supp_hit)}/{len([k for k in expected_supporting if k])}",
    }


def _tool_call_stats(snapshot: dict) -> dict:
    calls = snapshot.get("tool_calls") or []
    total = len(calls)
    ok = sum(1 for c in calls if c.get("status") == "ok")
    zero = sum(1 for c in calls if c.get("status") == "zero_result")
    failed = sum(1 for c in calls if c.get("status") == "failed")
    seen = Counter(
        (c.get("delegation_id"), c.get("tool_id"), json.dumps(c.get("args_normalized"), sort_keys=True))
        for c in calls
    )
    duplicates = sum(v - 1 for v in seen.values() if v > 1)
    return {
        "tool_calls_total": total,
        "ok": ok,
        "zero_result": zero,
        "failed": failed,
        "duplicate_calls": duplicates,
    }


def _integration_rejection_reasons(case_id: str, run_dir: Path) -> list[str]:
    """Pull INTEGRATE-stage rejection reasons from the run's trajectory
    (read from the durable task store via the recorded payload in the
    snapshot's state/limitation rows is not enough — read the driver-
    persisted failure/result payloads plus the trajectory dump file if a
    repeat was persisted by the driver)."""
    traj_file = run_dir / "trajectory_digest.json"
    if traj_file.exists():
        return json.loads(traj_file.read_text(encoding="utf-8"))
    return []


def main() -> int:
    from httpserver.services.benchmarks.metrics import structural_hard_gates

    corpus = json.loads(CORPUS_FILE.read_text(encoding="utf-8"))
    calibration_ids = [c["case_id"] for c in corpus["calibration_cases"]]

    report: dict = {
        "report_version": "baseline-measurement-report:v1",
        "experiment_id": "bexp-agent-v0-b2-baseline",
        "corpus_id": corpus["corpus_id"],
        "corpus_hash": corpus["input_hash"],
        "production_runtime_commit": "946f325eeb6add1072466aed96e5e2e7e38748ed",
        "corpus_freeze_commit": corpus["freeze_commit"],
        "cases": {},
        "totals": {},
        "hard_gates": {"all_passed": True, "violations": []},
        "provider_failure_runs": [],
        "notes": [],
    }

    all_wall = []
    total_usage_in = total_usage_out = 0
    reason_counter: Counter = Counter()

    for case_id in calibration_ids:
        case_root = BASELINE_ROOT / case_id
        if not case_root.is_dir():
            report["notes"].append(f"missing baseline dir: {case_id}")
            continue
        case_entry = {"runs": [], "terminal_status": Counter(), "functional_completion": Counter()}
        for run_dir in sorted(case_root.iterdir()):
            if not run_dir.is_dir():
                continue
            has_failure = (run_dir / "failure.json").exists()
            has_result = (run_dir / "result.json").exists()
            if not (has_failure or has_result):
                report["notes"].append(
                    f"run without artifacts: {run_dir.name}"
                )
                continue
            if has_failure and not has_result:
                failure = json.loads(
                    (run_dir / "failure.json").read_text(encoding="utf-8")
                )
                case_entry["runs"].append(
                    {
                        "run_dir": run_dir.name,
                        "status": "runner_failed",
                        "failure_layer": failure.get("failure_layer"),
                        "failure_reason": failure.get("failure_reason"),
                    }
                )
                case_entry["functional_completion"]["provider_failed" if "provider" in str(failure.get("failure_reason", "")) else "runtime_failed"] += 1
                continue
            result = _evaluate_run(case_id, run_dir)
            snapshot = json.loads(
                (run_dir / "snapshot.json").read_text(encoding="utf-8")
            )
            gates = result.get("hard_gate_results", [])
            gate_violations = [
                g for g in gates if not g.get("passed")
            ]
            if gate_violations:
                report["hard_gates"]["all_passed"] = False
                report["hard_gates"]["violations"].extend(
                    {
                        "run": f"{case_id}/{run_dir.name}",
                        "gates": gate_violations,
                    }
                )
            recall = _recall_against_truth(case_id, snapshot)
            tools = _tool_call_stats(snapshot)
            usage = snapshot.get("usage_entries") or []
            usage_in = sum(u.get("input_tokens") or 0 for u in usage)
            usage_out = sum(u.get("output_tokens") or 0 for u in usage)
            total_usage_in += usage_in
            total_usage_out += usage_out
            wall = snapshot.get("wall_ms_total")
            if wall:
                all_wall.append(wall)
            # functional completion classification (§15)
            fin = bool(snapshot.get("finalization_id"))
            delegs = snapshot.get("delegations") or []
            deleg_failed = any(
                d.get("status") == "failed" for d in delegs
            )
            integrated = any(d.get("integrated_revision") for d in delegs)
            if fin and not deleg_failed and integrated:
                completion = "completed"
            elif fin and (deleg_failed or not integrated):
                completion = "complete_with_limitations"
            else:
                completion = "finalization_denied"
            # semantic_output_available (§14): any integrated finding/claim
            semantic_available = fin and integrated
            run_row = {
                "run_dir": run_dir.name,
                "run_id": result["run_manifest_id"],
                "result_hash": result["result_hash"],
                "terminal_status": snapshot.get("terminal_status"),
                "finalization_id": bool(snapshot.get("finalization_id")),
                "functional_completion": completion,
                "semantic_output_available": semantic_available,
                "discovered_count": len(
                    snapshot.get("discovered_evidence_refs") or ()
                ),
                "delegations": len(delegs),
                "delegation_failed": deleg_failed,
                "usage": {"input_tokens": usage_in, "output_tokens": usage_out},
                "wall_ms_total": wall,
                "hard_gates": "PASS" if not gate_violations else "VIOLATION",
                **recall,
                **tools,
            }
            case_entry["runs"].append(run_row)
            case_entry["terminal_status"][snapshot.get("terminal_status", "?")] += 1
            case_entry["functional_completion"][completion] += 1
            reasons = _integration_rejection_reasons(case_id, run_dir)
            reason_counter.update(reasons)
            if completion == "finalization_denied":
                run_row["finalization_denied"] = True
        report["cases"][case_id] = case_entry

    # §11 SupervisorIntegrationProposalInvalidRate — reasons collected from
    # trajectory digests the driver wrote per run (if present).
    report["totals"] = {
        "runs_total": sum(
            len(c["runs"]) for c in report["cases"].values()
        ),
        "wall_ms": {
            "min": min(all_wall) if all_wall else None,
            "median": statistics.median(all_wall) if all_wall else None,
            "max": max(all_wall) if all_wall else None,
            "n": len(all_wall),
        },
        "usage_tokens": {
            "input_total": total_usage_in,
            "output_total": total_usage_out,
        },
        "supervisor_integration_invalid_reasons": dict(reason_counter),
    }
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"report -> {REPORT_FILE}")
    print("hard gates:", "ALL PASS" if report["hard_gates"]["all_passed"] else "VIOLATIONS PRESENT")
    for case_id, entry in report["cases"].items():
        print(f"{case_id}: {dict(entry['functional_completion'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
