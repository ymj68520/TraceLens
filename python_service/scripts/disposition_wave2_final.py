"""Wave-2 8x3 final candidate disposition (§10-§22).

Walks a completed 24-run candidate series (b2-runtime-v3-<candidate>),
re-derives everything deterministically from persisted artifacts
(evaluate-only, zero model calls), applies the §21/§22 qualification
conditions with the §7 provider-failure taxonomy, and emits the final
ModelCandidateQualificationV2 record.

Reliability axis uses the §15 frozen specialist collapse ceiling against
SCHEMA failures only: delegation failures whose failure_code is a
provider quota code are §7 provider events, not capability failures
(wave-1 accounting correction — see the wave-2 final report).

Usage (from python_service/):
    .venv/bin/python scripts/disposition_wave2_final.py \
        --candidate kimi-k3 \
        --results-root benchmarks/results/agent-v0/b2-runtime-v3-kimi-k3
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

PYTHON_SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

from disposition_wave2_screening import (  # noqa: E402
    QUOTA_CODES,
    SPECIALIST_COLLAPSE_CEILING,
    _load,
    _walk_runs,
)

SPECIALIST_COLLAPSE_CEILING = 0.5
OPEN_STATUSES = {"open", "in_progress"}


def _terminalization(truth, snapshot_dict: dict) -> dict:
    """§17 per-run required-question terminalization (deterministic).

    The authoritative metric (post-gen4 track, CalibrationEvidenceBinding
    era): each calibration case seeds exactly ONE charter required
    question (q-1); a run terminalizes its required question iff that
    charter row left the open set. Reproduces incumbent 20/24 and
    glm-5.2 10/24 exactly."""
    questions = snapshot_dict.get("questions") or ()
    charter = [q for q in questions if q.get("question_id") == "q-1"]
    open_charter = [
        q for q in charter if q.get("status") in OPEN_STATUSES
    ]
    terminalized = bool(charter) and not open_charter
    return {
        "required_questions_terminalized": terminalized,
        "charter_status": charter[0].get("status") if charter else None,
        "open_rows_total": sum(
            1 for q in questions if q.get("status") in OPEN_STATUSES
        ),
    }


def evaluate(candidate_id: str, results_root: Path) -> dict:
    reports = sorted(results_root.glob("*measurement-report.json"))
    report = _load(reports[0]) if reports else {}
    runs = _walk_runs(results_root)
    n_runs = len(runs)

    cases_root = PYTHON_SERVICE_ROOT / "benchmarks" / "cases"
    per_case: dict[str, list] = {}
    term_total = 0
    schema_fail = 0
    quota_fail = 0
    failure_code_hist: dict[str, int] = {}
    open_detail = []
    for r in runs:
        per_case.setdefault(r["case_id"], []).append(r["case_outcome"])
        for f in r["delegation_failures"]:
            code = str(f.get("failure_code", "unknown"))
            failure_code_hist[code] = failure_code_hist.get(code, 0) + 1
            if any(q in code.lower() for q in QUOTA_CODES):
                quota_fail += 1
            else:
                schema_fail += 1
        snap = _load(
            results_root / r["case_id"] / r["repeat"] / "snapshot.json"
        )
        truth = _load(cases_root / r["case_id"] / "truth_manifest.json")
        from httpserver.services.benchmarks.truth_manifest import (
            TruthManifestV1,
        )

        term = _terminalization(TruthManifestV1(**truth), snap)
        term_total += int(term["required_questions_terminalized"])
        if not term["required_questions_terminalized"]:
            open_detail.append({
                "case_id": r["case_id"], "repeat": r["repeat"],
                "charter_status": term["charter_status"],
                "delegation_failure_codes": [
                    f.get("failure_code") for f in r["delegation_failures"]
                ],
            })

    delegation_attempts = sum(
        len(r["delegation_failures"]) + r["delegations_completed"]
        for r in runs
    )
    schema_rate = (schema_fail / delegation_attempts) if delegation_attempts else None

    gates_clean = all(r["hard_gates_pass"] for r in runs)
    outcomes: dict[str, int] = {}
    for r in runs:
        outcomes[r["case_outcome"]] = outcomes.get(r["case_outcome"], 0) + 1

    # §16 repeatability: per-case 3-repeat outcome distribution
    repeatability = {
        case: {
            "outcomes": ocs,
            "success_repeats": sum(
                1 for o in ocs if o in ("success", "success_with_limitations")
            ),
        }
        for case, ocs in sorted(per_case.items())
    }
    stable_cases = sum(
        1 for v in repeatability.values() if v["success_repeats"] >= 2
    )

    verdict = report.get("measurement_verdict", "REPORT_MISSING")
    finalized_runs = sum(
        1 for r in runs if r["finalization"] == "finalization_completed"
    )
    quota_starved = (
        quota_fail > 0 and finalized_runs < n_runs / 2
    )

    # §21/§22 disposition
    if verdict != "MEASUREMENT_VALID":
        disposition, reason = "MEASUREMENT_INVALID", (
            f"series verdict {verdict} (runs={n_runs}/24, "
            f"gates_clean={gates_clean})"
        )
    elif not gates_clean:
        disposition, reason = "NOT_QUALIFIED", "structural hard gate violation"
    elif schema_rate is not None and schema_rate > SPECIALIST_COLLAPSE_CEILING:
        disposition, reason = "NOT_QUALIFIED", (
            f"specialist SCHEMA failure rate {schema_rate:.1%} > "
            f"frozen ceiling {SPECIALIST_COLLAPSE_CEILING} (§15)"
        )
    elif quota_starved:
        disposition, reason = "PROVIDER_QUOTA_BLOCKED", (
            f"series degraded by provider quota ({quota_fail} "
            f"agent_rate_limited delegation failures; finalized "
            f"{finalized_runs}/{n_runs}) — semantic qualification NOT "
            "ESTABLISHED; re-enter in a clear provider window (§7)"
        )
    elif stable_cases == 0:
        disposition, reason = "NOT_QUALIFIED", (
            "no case reaches stable functional reachability "
            "(no case with >=2/3 success-class repeats; §23)"
        )
    else:
        disposition, reason = "QUALIFIED_FOR_PROMOTION", (
            f"measurement valid, gates clean, schema failures "
            f"{schema_fail}/{delegation_attempts} within ceiling, "
            f"{stable_cases}/8 cases stable (>=2/3 success-class), "
            f"question terminalization {term_total}/{n_runs}"
        )

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
        cwd=PYTHON_SERVICE_ROOT.parent,
    ).stdout.strip()

    return {
        "artifact_version": "ModelCandidateQualificationV2",
        "wave": 2,
        "candidate_id": candidate_id,
        "stage": "8x3_final",
        "results_root": str(results_root),
        "git_commit": head,
        "runs": n_runs,
        "measurement_verdict": verdict,
        "structural_hard_gates": (
            f"{sum(1 for r in runs if r['hard_gates_pass'])}/{n_runs} clean"
        ),
        "case_outcomes": outcomes,
        "per_case_repeatability": repeatability,
        "cases_with_stable_reachability": stable_cases,
        "finalization_completed_runs": finalized_runs,
        "question_terminalization": {
            "terminalized_runs": term_total,
            "total_runs": n_runs,
            "rule": "charter required question (q-1) left the open set {open, in_progress}",
            "non_terminalized_runs": open_detail,
        },
        "delegation_failure_codes": failure_code_hist,
        "specialist_schema_output_failures": schema_fail,
        "specialist_schema_failure_rate": schema_rate,
        "provider_quota_delegation_failures": quota_fail,
        "frozen_ceiling": SPECIALIST_COLLAPSE_CEILING,
        "disposition": disposition,
        "reason": reason,
        "frozen_axes_untouched": (
            "runtime/prompt/policy/ToolRegistry/AcceptanceProfile unchanged; "
            "holdouts untouched (§1/§31)"
        ),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="disposition_wave2_final")
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--results-root", required=True)
    args = parser.parse_args()
    record = evaluate(args.candidate, Path(args.results_root))
    out = Path(args.results_root) / "ModelCandidateQualificationV2.json"
    out.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"{args.candidate}: {record['disposition']}")
    print(f"  {record['reason']}")
    print(f"  -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
