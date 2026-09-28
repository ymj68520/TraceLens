#!/usr/bin/env python3
"""P8B Model Qualification — Q1 promotion decision (§9/§12/§13/§14/§15).

Reads q1-screening-report.v1.json and applies the spec rules MECHANICALLY:

  §9   any structural hard-gate violation  -> QUALIFICATION_DISQUALIFIED
       (correctness incompatibility; not compensable by averages)
  §12  transport-level failures (429/timeout/5xx/reset) are classified
       PROVIDER/INFRA and are NOT capability failures by themselves
  §13  rank surviving candidates: case outcomes -> integration validity
       -> semantic correctness -> reliability -> cost; at most 2 advance
  §14  a single clearly-dominant candidate may advance alone
  §15  if every candidate is ≈ the MiMo reference (0/very low case
       success + high integration invalidity) -> NO_QUALIFIED_MODEL
       and the experiment stops before Q2

Emits model-qualification/q1-promotion-decision.v1.json.

Usage (from python_service/):
    .venv/bin/python scripts/build_q1_promotion_decision.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PYTHON_SERVICE_ROOT = SCRIPT_PATH.parents[1]
QUAL_ROOT = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0"
    / "model-qualification"
)
MIMO_REFERENCE = "mimo-v2.6-flash-reference"
REPORT_FILE = QUAL_ROOT / "q1-screening-report.v1.json"
OUT_FILE = QUAL_ROOT / "q1-promotion-decision.v1.json"


def main() -> int:
    report = json.loads(REPORT_FILE.read_text(encoding="utf-8"))
    candidates = report["candidates"]
    mimo = candidates[MIMO_REFERENCE]["summary"]

    decisions = []
    for cid, entry in candidates.items():
        if cid == MIMO_REFERENCE:
            continue
        s = entry["summary"]
        notes = []
        disqualified = bool(entry["hard_gate_violations"])
        if disqualified:
            notes.append(
                "§9 QUALIFICATION_DISQUALIFIED: structural hard-gate "
                f"violations {entry['hard_gate_violations']}"
            )
        # §12 provider/infra classification
        provider_runs = s["provider_failure_runs"]
        # cross-candidate comparability: rates over completed runs, not
        # counts (candidates ran fewer runs than the 24-run reference)
        completed = max(s["runs_completed"], 1)
        integration_rate = (
            s["integration_invalid_runs"] / completed
        )
        reference_rate = (
            mimo["integration_invalid_runs"] / max(mimo["runs_completed"], 1)
        )
        outcome_better = (
            s["case_outcome_success"] > mimo["case_outcome_success"]
        )
        integration_better = (
            integration_rate < reference_rate
        )
        decisions.append(
            {
                "candidate_id": cid,
                "hard_gates": (
                    "VIOLATION" if disqualified else "PASS"
                ),
                "runs_total": s["runs_total"],
                "runs_completed": s["runs_completed"],
                "not_run_cases": entry["not_run_cases"],
                "case_outcome_success": s["case_outcome_success"],
                "case_outcome_distribution": s[
                    "case_outcome_distribution"
                ],
                "finalization_pass": s["finalization_pass"],
                "integration_invalid_runs": s[
                    "integration_invalid_runs"
                ],
                "provider_failure_runs": provider_runs,
                "outcome_better_than_reference": outcome_better,
                "integration_better_than_reference": integration_better,
                "integration_invalid_rate": integration_rate,
                "disqualified": disqualified,
                "notes": notes,
            }
        )

    eligible = [
        d for d in decisions
        if not d["disqualified"]
        and d["runs_completed"] > 0
        and (d["outcome_better_than_reference"]
             or d["integration_better_than_reference"])
    ]
    # §13 priority order: outcome, integration validity, reliability, cost
    eligible.sort(
        key=lambda d: (
            -d["case_outcome_success"],
            d["integration_invalid_runs"],
            d["provider_failure_runs"],
        )
    )

    if not eligible:
        rule = "§15 NO_QUALIFIED_MODEL_CONFIGURATION"
        advancing = []
        stop_experiment = True
    elif len(eligible) == 1:
        rule = "§14 single clearly-better candidate advances"
        advancing = [eligible[0]["candidate_id"]]
        stop_experiment = False
    else:
        best = eligible[0]
        second = eligible[1]
        dominant = (
            best["case_outcome_success"] > second["case_outcome_success"]
            and best["integration_invalid_runs"]
            < second["integration_invalid_runs"]
        )
        advancing = [d["candidate_id"] for d in eligible[:2]]
        rule = (
            "§14 dominant candidate advances alone"
            if dominant
            else "§13 top-2 advance to Q2"
        )
        if dominant:
            advancing = [best["candidate_id"]]
        stop_experiment = False

    artifact = {
        "artifact_version": "q1-promotion-decision:v1",
        "screening_report": REPORT_FILE.name,
        "reference_summary": {
            "candidate_id": MIMO_REFERENCE,
            "runs_total": mimo["runs_total"],
            "case_outcome_success": mimo["case_outcome_success"],
            "integration_invalid_runs": mimo[
                "integration_invalid_runs"
            ],
        },
        "candidate_decisions": decisions,
        "eligible_for_q2": [d["candidate_id"] for d in eligible],
        "advancing_to_q2": advancing,
        "decision_rule": rule,
        "stop_experiment": stop_experiment,
        "stop_reason": (
            "§15: no candidate materially improves on the MiMo reference; "
            "record NO QUALIFIED MODEL CONFIGURATION and do not enter Q2 "
            "or holdout."
            if stop_experiment
            else ""
        ),
    }
    OUT_FILE.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"decision -> {OUT_FILE}")
    for d in decisions:
        print(
            f"  {d['candidate_id']:24} gates={d['hard_gates']:8} "
            f"succ={d['case_outcome_success']} "
            f"integ_inv={d['integration_invalid_runs']} "
            f"prov_fail={d['provider_failure_runs']}"
        )
    print(f"advancing: {advancing or 'NONE'}  ({rule})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
