#!/usr/bin/env python3
"""P8B B3.5 §7 measurement-closure recompute.

Recomputes ALL persisted B2 + A0/A1/A2 snapshots evaluate-only under the
new BenchmarkCaseOutcomeV1 metric (benchmark-case-outcome:v1) and emits
measurement-report.v2.json with:
  - finalization_pass_rate  (the §2/§3 rename of the old "completion")
  - case outcome per run (truth-semantic, deterministic)
  - per-stage/per-case distributions

Old run artifacts (run_manifest/snapshot/result JSON) are NOT modified
(§1): this script reads them and writes only the v2 report.

Usage (from python_service/):
    .venv/bin/python scripts/recompute_p8b_case_outcomes.py
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

RESULTS = PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0"
CASES_ROOT = PYTHON_SERVICE_ROOT / "benchmarks" / "cases"
CORPUS_FILE = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "corpus" / "corpus-agent-v0-b2.v1.json"
)
REPORT_FILE = RESULTS / "measurement-report.v2.json"


def _load_truth(case_id: str):
    from httpserver.services.benchmarks.truth_manifest import TruthManifestV1

    return TruthManifestV1(
        **json.loads(
            (CASES_ROOT / case_id / "truth_manifest.json").read_text(
                encoding="utf-8"
            )
        )
    )


def _collect(root: Path) -> list[dict]:
    from httpserver.services.benchmarks.metrics import structural_hard_gates
    from httpserver.services.benchmarks.snapshot import BenchmarkRunSnapshotV1
    from httpserver.services.benchmarks.case_outcome import (
        evaluate_case_outcome,
    )

    rows = []
    if not root.is_dir():
        return rows
    for case_dir in sorted(root.iterdir()):
        if not case_dir.is_dir():
            continue
        truth = None
        for run_dir in sorted(case_dir.iterdir()):
            snap_file = run_dir / "snapshot.json"
            if not snap_file.is_file():
                continue
            if truth is None:
                truth = _load_truth(case_dir.name)
            snap = BenchmarkRunSnapshotV1(
                **json.loads(snap_file.read_text(encoding="utf-8"))
            )
            gates = [
                {"gate_id": g.gate_id, "passed": g.passed, "violations": list(g.violations)}
                for g in structural_hard_gates(snap)
            ]
            outcome = evaluate_case_outcome(
                truth=truth, snapshot=snap, hard_gates=gates
            )
            rows.append(
                {
                    "stage_root": root.name,
                    "case_id": case_dir.name,
                    "run_dir": run_dir.name,
                    "run_id": snap.run_id,
                    "snapshot_hash": snap.snapshot_hash,
                    "finalization_pass": outcome.finalization_pass,
                    "case_outcome": outcome.outcome.value,
                    "rationale": outcome.rationale,
                    "wall_ms": snap.wall_ms_total,
                }
            )
    return rows


def _summarize(rows: list[dict]) -> dict:
    n = len(rows)
    if not n:
        return {"runs": 0}
    fin = sum(1 for r in rows if r["finalization_pass"])
    outcomes = Counter(r["case_outcome"] for r in rows)
    walls = [r["wall_ms"] for r in rows if r["wall_ms"]]
    return {
        "runs": n,
        "finalization_pass_rate": round(fin / n, 3),
        "case_outcome_distribution": dict(outcomes),
        "case_success_rate": round(
            (outcomes.get("success", 0) + outcomes.get("success_with_limitations", 0)) / n,
            3,
        ),
        "wall_ms_median": statistics.median(walls) if walls else None,
    }


def main() -> int:
    corpus = json.loads(CORPUS_FILE.read_text(encoding="utf-8"))
    case_ids = [c["case_id"] for c in corpus["calibration_cases"]]

    baseline_rows = _collect(BASELINE_ROOT := RESULTS / "baseline")
    ablation_rows = []
    for stage in ("A0", "A1", "A2"):
        ablation_rows.extend(_collect(RESULTS / "ablation" / stage))

    report = {
        "report_version": "measurement-report:v2",
        "metric_additions": {
            "benchmark_case_outcome": "benchmark-case-outcome:v1",
            "finalization_pass_rate": (
                "renamed display of the old functional-completion metric "
                "(B3.5 §2/§3): it measures FinalizationGate closure, not "
                "investigative success"
            ),
        },
        "corpus_id": corpus["corpus_id"],
        "corpus_version": corpus["version"],
        "production_runtime_commit": "946f325eeb6add1072466aed96e5e2e7e38748ed",
        "stages": {
            "B2_baseline_full": {
                "summary": _summarize(baseline_rows),
                "per_case": {
                    cid: _summarize(
                        [r for r in baseline_rows if r["case_id"] == cid]
                    )
                    for cid in case_ids
                    if any(r["case_id"] == cid for r in baseline_rows)
                },
                "runs": baseline_rows,
            },
            "A0_non_agent_baseline": {
                "summary": _summarize(
                    [r for r in ablation_rows if r["stage_root"] == "A0"]
                ),
                "runs": [
                    r for r in ablation_rows if r["stage_root"] == "A0"
                ],
            },
            "A1_supervisor_only": {
                "summary": _summarize(
                    [r for r in ablation_rows if r["stage_root"] == "A1"]
                ),
                "runs": [
                    r for r in ablation_rows if r["stage_root"] == "A1"
                ],
            },
            "A2_supervisor_plus_specialist": {
                "summary": _summarize(
                    [r for r in ablation_rows if r["stage_root"] == "A2"]
                ),
                "runs": [
                    r for r in ablation_rows if r["stage_root"] == "A2"
                ],
            },
        },
        "notes": [
            "§1: v1 artifacts under benchmarks/results/agent-v0/ are "
            "preserved untouched; this v2 report is an additive "
            "evaluate-only recompute (no model calls).",
            "§6: A0 finalization_pass_rate=1.0 stands; its case outcomes "
            "are computed by the deterministic evaluator, not asserted.",
        ],
    }
    REPORT_FILE.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"report -> {REPORT_FILE}")
    for stage, data in report["stages"].items():
        s = data["summary"]
        print(
            f"{stage}: finalization_pass_rate={s.get('finalization_pass_rate')} "
            f"outcomes={s.get('case_outcome_distribution')}"
        )
    print("per-case (B2):")
    for cid, s in report["stages"]["B2_baseline_full"]["per_case"].items():
        print(
            f"  {cid}: fin={s.get('finalization_pass_rate')} "
            f"outcomes={s.get('case_outcome_distribution')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
