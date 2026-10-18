#!/usr/bin/env python3
"""P8B §21-§25 B3 ablation driver.

Runs the frozen ablation stages over the SAME calibration corpus with the
SAME repeat policy as B2, changing ONLY the ablation wiring (§24):

  A0  supervisor=None, dispatcher=None  (deterministic control plane only)
  A1  supervisor=on,   dispatcher=None  (plan only; delegations stay queued)
  A2  supervisor=on,   dispatcher=on     (full agent execution — B2 baseline
      wiring, no correlation/verifier/graph/report changes available at
      runtime; those stages are policy-frozen in production code)

A3/A4/A5/A6 status is recorded honestly: production code has no runtime
toggle for correlation / semantic-verifier / graph-mode / report on the
benchmark path, so running them as ablation variants would require
runtime changes — prohibited by the §0 freeze. They are marked
NOT_SEPARABLY_RUNNABLE rather than faked (§24/§25).

Usage (from python_service/):
    .venv/bin/python scripts/run_p8b_ablation.py --stage A0 --case t2-no-evidence --repeats 3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PYTHON_SERVICE_ROOT = SCRIPT_PATH.parents[1]
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

sys.path.insert(
    0, str(PYTHON_SERVICE_ROOT / "scripts")
)
import run_p8b_baseline as baseline_driver  # noqa: E402

ABLATION_ROOT = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0" / "ablation"
)

STAGES = ("A0", "A1", "A2")

NOT_SEPARABLY_RUNNABLE = {
    "A3": "correlation stage is policy-frozen inside the production "
    "execution path; no runtime toggle exists on the benchmark seam",
    "A4": "semantic verifier stage is policy-frozen inside the production "
    "execution path (best_effort final review unavailable marker); no "
    "runtime toggle exists on the benchmark seam",
    "A5": "graph stage requires runtime wiring changes (prohibited by the "
    "§0 freeze); Neo4j reachable = environment eligible for a future run",
    "A6": "report stage requires runtime wiring changes (prohibited by "
    "the §0 freeze)",
}


def _run_one_ablation(
    stage: str, case_id: str, repeat: str, fresh_task_id: str
) -> dict:
    """Re-wire the baseline executor with the ablation stage's seams.

    Only supervisor/dispatcher wiring changes; everything else (settings,
    registry, policies, frozen instructions) is identical to B2 (§22).
    """
    import scripts.run_p8b_baseline as bd

    # temporarily patch the baseline driver's wiring knobs
    orig_supervisor = bd.__dict__.get("ABLATION_DISABLE_SUPERVISOR", False)
    orig_dispatcher = bd.__dict__.get("ABLATION_DISABLE_DISPATCHER", False)
    bd.__dict__["ABLATION_DISABLE_SUPERVISOR"] = stage in ("A0",)
    bd.__dict__["ABLATION_DISABLE_DISPATCHER"] = stage in ("A0", "A1")
    try:
        return bd._run_one(case_id, repeat, fresh_task_id)
    finally:
        bd.__dict__["ABLATION_DISABLE_SUPERVISOR"] = orig_supervisor
        bd.__dict__["ABLATION_DISABLE_DISPATCHER"] = orig_dispatcher


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="run_p8b_ablation")
    parser.add_argument("--stage", required=True, choices=list(STAGES) + list(NOT_SEPARABLY_RUNNABLE))
    parser.add_argument("--case", help="single case id (default: all)")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--repeat-start", type=int, default=0)
    args = parser.parse_args(argv)

    if args.stage in NOT_SEPARABLY_RUNNABLE:
        record = {
            "stage": args.stage,
            "status": "NOT_SEPARABLY_RUNNABLE",
            "reason": NOT_SEPARABLY_RUNNABLE[args.stage],
            "recorded_at": "2026-09-28",
        }
        out = ABLATION_ROOT / f"{args.stage}-status.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(record, indent=2), encoding="utf-8"
        )
        print(f"{args.stage}: NOT_SEPARABLY_RUNNABLE -> {out}")
        return 0

    stage = args.stage
    corpus = json.loads(
        (
            PYTHON_SERVICE_ROOT
            / "benchmarks/corpus/corpus-agent-v0-b2.v1.json"
        ).read_text(encoding="utf-8")
    )
    case_ids = [c["case_id"] for c in corpus["calibration_cases"]]
    if args.case:
        case_ids = [args.case]

    failures = 0
    for case_id in case_ids:
        for repeat in range(
            args.repeat_start, args.repeat_start + args.repeats
        ):
            tag = f"repeat{repeat}"
            out_dir = ABLATION_ROOT / stage / case_id / tag
            if (out_dir / "result.json").exists() or (
                out_dir / "failure.json"
            ).exists():
                print(f"[skip] {stage}/{case_id}/{tag}")
                continue
            print(f"[run ] {stage}/{case_id}/{tag}: provisioning...")
            provision = baseline_driver._provision_fresh_task(case_id, tag)
            fresh_task_id = provision["task_id"]
            try:
                outcome = _run_one_ablation(
                    stage, case_id, tag, fresh_task_id
                )
            except Exception as exc:
                import traceback

                failures += 1
                print(f"[FAIL] {stage}/{case_id}/{tag}: {exc}")
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / "driver_failure.json").write_text(
                    json.dumps(
                        {
                            "error": str(exc)[:1000],
                            "traceback": traceback.format_exc()[-4000:],
                            "task_id": fresh_task_id,
                        }
                    ),
                    encoding="utf-8",
                )
                continue
            out_dir.mkdir(parents=True, exist_ok=True)
            manifest = outcome["run_manifest"]
            (out_dir / "run_manifest.json").write_text(
                manifest.model_dump_json(), encoding="utf-8"
            )
            if outcome["status"] == "completed":
                (out_dir / "snapshot.json").write_text(
                    outcome["snapshot"].model_dump_json(), encoding="utf-8"
                )
                (out_dir / "result.json").write_text(
                    outcome["result"].model_dump_json(), encoding="utf-8"
                )
                print(
                    f"[done] {stage}/{case_id}/{tag}: "
                    f"run={outcome['result'].run_manifest_id}"
                )
            else:
                (out_dir / "failure.json").write_text(
                    outcome["failure"].model_dump_json(), encoding="utf-8"
                )
                failures += 1
                print(
                    f"[fail] {stage}/{case_id}/{tag}: "
                    f"{outcome['failure'].failure_reason[:120]}"
                )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
