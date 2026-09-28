#!/usr/bin/env python3
"""P8B §25 AblationReportV1 aggregation — numeric deltas only.

Aggregates A0/A1/A2 (and baseline=B2) per-case/per-stage metrics from the
persisted snapshot+result artifacts.  Stages A3–A6 are referenced from
their NOT_SEPARABLY_RUNNABLE status records (never faked).

Usage (from python_service/):
    .venv/bin/python scripts/aggregate_p8b_ablation.py
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
ABLATION_ROOT = RESULTS / "ablation"
BASELINE_ROOT = RESULTS / "baseline"
CASES_ROOT = PYTHON_SERVICE_ROOT / "benchmarks" / "cases"
CORPUS_FILE = PYTHON_SERVICE_ROOT / "benchmarks" / "corpus" / "corpus-agent-v0-b2.v1.json"
REPORT_FILE = ABLATION_ROOT / "ablation-report.v1.json"


def _load_runs(root: Path) -> list[dict]:
    rows = []
    if not root.is_dir():
        return rows
    for case_dir in sorted(root.iterdir()):
        if not case_dir.is_dir():
            continue
        for run_dir in sorted(case_dir.iterdir()):
            snap_file = run_dir / "snapshot.json"
            if not snap_file.is_file():
                continue
            snap = json.loads(snap_file.read_text(encoding="utf-8"))
            usage = snap.get("usage_entries") or []
            delegs = snap.get("delegations") or []
            integrated = any(d.get("integrated_revision") for d in delegs)
            failed = any(d.get("status") == "failed" for d in delegs)
            fin = bool(snap.get("finalization_id"))
            if fin and integrated and not failed:
                completion = "completed"
            elif fin:
                completion = "complete_with_limitations"
            else:
                completion = "finalization_denied"
            rows.append(
                {
                    "case_id": case_dir.name,
                    "run": run_dir.name,
                    "terminal": snap.get("terminal_status"),
                    "functional_completion": completion,
                    "discovered": len(snap.get("discovered_evidence_refs") or ()),
                    "tool_calls": len(snap.get("tool_calls") or ()),
                    "zero_result": sum(
                        1
                        for c in snap.get("tool_calls") or ()
                        if c.get("status") == "zero_result"
                    ),
                    "delegations": len(delegs),
                    "delegation_failed": failed,
                    "integrated": integrated,
                    "input_tokens": sum(u.get("input_tokens") or 0 for u in usage),
                    "output_tokens": sum(u.get("output_tokens") or 0 for u in usage),
                    "wall_ms": snap.get("wall_ms_total"),
                }
            )
    return rows


def _stage_summary(rows: list[dict]) -> dict:
    n = len(rows)
    comp = Counter(r["functional_completion"] for r in rows)
    walls = [r["wall_ms"] for r in rows if r["wall_ms"]]
    tools = [r["tool_calls"] for r in rows]
    zero = [r["zero_result"] for r in rows]
    return {
        "runs": n,
        "functional_completion": dict(comp),
        "completion_rate": round(
            (comp.get("completed", 0) + comp.get("complete_with_limitations", 0)) / n,
            3,
        )
        if n
        else None,
        "mean_tool_calls": round(statistics.mean(tools), 1) if tools else None,
        "mean_zero_result": round(statistics.mean(zero), 1) if zero else None,
        "input_tokens_total": sum(r["input_tokens"] for r in rows),
        "output_tokens_total": sum(r["output_tokens"] for r in rows),
        "wall_ms_median": statistics.median(walls) if walls else None,
    }


def main() -> int:
    corpus = json.loads(CORPUS_FILE.read_text(encoding="utf-8"))
    case_ids = [c["case_id"] for c in corpus["calibration_cases"]]

    baseline = _load_runs(BASELINE_ROOT)
    a0 = _load_runs(ABLATION_ROOT / "A0")
    a1 = _load_runs(ABLATION_ROOT / "A1")
    a2 = _load_runs(ABLATION_ROOT / "A2")

    def per_case(rows):
        out = {}
        for cid in case_ids:
            sub = [r for r in rows if r["case_id"] == cid]
            if sub:
                out[cid] = _stage_summary(sub)
        return out

    statuses = {}
    for stage in ("A3", "A4", "A5", "A6"):
        p = ABLATION_ROOT / f"{stage}-status.json"
        if p.exists():
            statuses[stage] = json.loads(p.read_text(encoding="utf-8"))

    report = {
        "report_version": "ablation-report:v1",
        "experiment_id": "bexp-agent-v0-b2-baseline",
        "repeat_policy": "3 fresh repeats per case per stage",
        "stages": {
            "B2_baseline_full": {"summary": _stage_summary(baseline), "per_case": per_case(baseline)},
            "A0_non_agent_baseline": {"summary": _stage_summary(a0), "per_case": per_case(a0)},
            "A1_supervisor_only": {"summary": _stage_summary(a1), "per_case": per_case(a1)},
            "A2_supervisor_plus_specialist": {"summary": _stage_summary(a2), "per_case": per_case(a2)},
        },
        "deltas": {},
        "not_separately_runnable": statuses,
        "notes": [
            "A2 wiring equals the B2 baseline executor seams (supervisor+dispatcher); "
            "B2_baseline_full numbers come from the B2 measurement phase for cross-checking.",
            "A3 (correlation) / A4 (semantic verifier) / A5 (graph) / A6 (report) have no "
            "runtime toggle on the production benchmark seam; running them would require "
            "runtime changes prohibited by the §0 freeze. Recorded NOT_SEPARABLY_RUNNABLE.",
        ],
    }

    def delta(name, a_rows, b_rows):
        a, b = _stage_summary(a_rows), _stage_summary(b_rows)
        report["deltas"][name] = {
            "completion_rate_delta": (
                round(a["completion_rate"] - b["completion_rate"], 3)
                if a["completion_rate"] is not None and b["completion_rate"] is not None
                else None
            ),
            "input_tokens_delta": a["input_tokens_total"] - b["input_tokens_total"],
            "output_tokens_delta": a["output_tokens_total"] - b["output_tokens_total"],
            "wall_ms_median_delta": (
                round(a["wall_ms_median"] - b["wall_ms_median"])
                if a["wall_ms_median"] and b["wall_ms_median"]
                else None
            ),
        }

    delta("A2_minus_A1", a2, a1)
    delta("A2_minus_A0", a2, a0)
    delta("A1_minus_A0", a1, a0)

    REPORT_FILE.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"report -> {REPORT_FILE}")
    for stage, data in report["stages"].items():
        s = data["summary"]
        print(
            f"{stage}: runs={s['runs']} completion_rate={s['completion_rate']} "
            f"tools={s['mean_tool_calls']} tokens_in={s['input_tokens_total']}"
        )
    for name, d in report["deltas"].items():
        print(name, d)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
