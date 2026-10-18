"""Wave-2 8x1 screening disposition (model candidate wave 2, §8/§9/§21).

Consumes the deterministic screening report produced by
build_b2_runtime_v3_report.py over an 8x1 qualification root plus the
per-run trajectory digests, applies the §9 immediate-stop rules and the
§7 quota classification, and emits ModelCandidateQualificationV2.

Zero model calls — everything is re-derived from persisted artifacts.

Usage (from python_service/):
    .venv/bin/python scripts/disposition_wave2_screening.py \
        --candidate kimi-k3 \
        --qual-root benchmarks/results/agent-v0/model-candidates/wave2/kimi-k3/qual-8x1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PYTHON_SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

# §15 frozen reliability collapse ceiling (AcceptanceProfile era freeze)
SPECIALIST_COLLAPSE_CEILING = 0.5

QUOTA_CODES = ("agent_rate_limited", "rate_limit", "429")

GROUNDING_STAGE_MARKERS = ("grounding", "reader", "evidence")


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _walk_runs(qual_root: Path) -> list[dict]:
    """Deterministically re-derive per-run facts from persisted artifacts
    (evaluate-only; zero model calls) — same conventions as
    build_b2_runtime_v3_report.py."""
    from httpserver.services.benchmarks.case_outcome import (
        evaluate_case_outcome_v2,
    )
    from httpserver.services.benchmarks.metrics import structural_hard_gates
    from httpserver.services.benchmarks.snapshot import BenchmarkRunSnapshotV1
    from httpserver.services.benchmarks.truth_manifest import TruthManifestV1

    cases_root = PYTHON_SERVICE_ROOT / "benchmarks" / "cases"
    runs: list[dict] = []
    for case_dir in sorted(p for p in qual_root.iterdir() if p.is_dir()):
        for run_dir in sorted(case_dir.glob("repeat*")):
            if not (run_dir / "result.json").is_file():
                continue
            result = _load(run_dir / "result.json")
            snapshot = BenchmarkRunSnapshotV1(**_load(run_dir / "snapshot.json"))
            digest = _load(run_dir / "trajectory_digest.json")
            gates = [
                {"gate_id": g.gate_id, "passed": g.passed,
                 "violations": list(g.violations)}
                for g in structural_hard_gates(snapshot)
            ]
            truth = TruthManifestV1(
                **_load(cases_root / case_dir.name / "truth_manifest.json")
            )
            payloads = [
                c.get("result_semantic_payload") or {}
                for c in digest.get("completions", [])
            ]
            oc = evaluate_case_outcome_v2(
                truth=truth, snapshot=snapshot,
                hard_gates=gates, semantic_payloads=payloads,
            )
            del_f = digest.get("delegation_failures", [])
            runs.append({
                "case_id": case_dir.name,
                "repeat": run_dir.name,
                "hard_gates_pass": all(g["passed"] for g in gates),
                "terminal_status": snapshot.terminal_status,
                "case_outcome": oc.outcome.value,
                "delegations_completed": sum(
                    1 for d in (snapshot.delegations or [])
                    if d.get("status") == "completed"
                ),
                "delegation_failures": del_f,
                "finalization": (digest.get("finalization") or {}).get("event"),
            })
    return runs


def evaluate(candidate_id: str, qual_root: Path) -> dict:
    reports = sorted(qual_root.glob("*measurement-report.json"))
    if not reports:
        raise SystemExit(f"no measurement report under {qual_root} — "
                         "run build_b2_runtime_v3_report.py first")
    report = _load(reports[0])
    runs = _walk_runs(qual_root)
    n_runs = len(runs)

    digest_dir_stats = {
        "delegation_failures_by_code": {},
        "quota_delegation_failures": 0,
        "total_delegation_failures": 0,
    }
    for case_dir in sorted(p for p in qual_root.iterdir() if p.is_dir()):
        for run_dir in sorted(case_dir.glob("repeat*")):
            td = run_dir / "trajectory_digest.json"
            if not td.is_file():
                continue
            digest = _load(td)
            for f in digest.get("delegation_failures", []):
                code = str(f.get("failure_code", "unknown"))
                digest_dir_stats["delegation_failures_by_code"][code] = (
                    digest_dir_stats["delegation_failures_by_code"].get(code, 0) + 1
                )
                digest_dir_stats["total_delegation_failures"] += 1
                if any(q in code.lower() for q in QUOTA_CODES):
                    digest_dir_stats["quota_delegation_failures"] += 1

    reliability = report.get("output_reliability", {})
    # §9 counts SCHEMA failures, not provider events: the aggregate report
    # counter len(delegation_failures) includes agent_rate_limited quota
    # events (wave-1 accounting artifact — see wave-2 report §40), so the
    # schema-only count is re-derived here from failure codes.
    schema_fail = sum(
        1 for r in runs for f in r["delegation_failures"]
        if not any(q in str(f.get("failure_code", "")).lower() for q in QUOTA_CODES)
    )
    sup_plan = int(reliability.get("supervisor_PLAN_failures") or 0)
    sup_int = int(reliability.get("supervisor_INTEGRATE_failures") or 0)
    provider_fail_runs = int(reliability.get("provider_failures") or 0)

    gates_clean = all(r["hard_gates_pass"] for r in runs)

    # grounding regression: any rejection code on grounding/reader/evidence
    grounding_codes = {
        key: codes
        for key, codes in (report.get("rejection_codes") or {}).items()
        if any(m in key.lower() for m in GROUNDING_STAGE_MARKERS) and codes
    }

    stop_reasons: list[str] = []
    if not gates_clean:
        stop_reasons.append("structural_hard_gate_violation")
    if grounding_codes:
        stop_reasons.append("grounding_regression")
    if n_runs and (sup_plan + sup_int) >= max(1, n_runs // 2):
        stop_reasons.append("systemic_supervisor_schema_failure")
    # delegation attempts: completed + failed delegations from snapshots
    delegation_attempts = sum(
        len(r.get("delegation_failures") or [])
        + int(r.get("delegations_completed") or 0)
        for r in runs
    )
    specialist_rate = (schema_fail / delegation_attempts) if delegation_attempts else None
    if specialist_rate is not None and specialist_rate > SPECIALIST_COLLAPSE_CEILING:
        stop_reasons.append("systemic_specialist_schema_failure")

    finalized_runs = sum(
        1 for r in runs if r["finalization"] == "finalization_completed"
    )
    # §7/§28: quota only blocks the MEASUREMENT when it actually degraded
    # the series (finalization majority lost, or run-level provider
    # failures on half the runs). Isolated transient 429s in an otherwise
    # finalized series are recorded as notes, not dispositions.
    quota_starved = (
        digest_dir_stats["quota_delegation_failures"] > 0
        and finalized_runs < n_runs / 2
    ) or (provider_fail_runs >= max(1, n_runs // 2))

    outcomes: dict[str, int] = {}
    for r in runs:
        outcomes[r["case_outcome"]] = outcomes.get(r["case_outcome"], 0) + 1

    if stop_reasons:
        disposition, reason = "NOT_QUALIFIED", ";".join(stop_reasons)
    elif quota_starved:
        disposition, reason = "PROVIDER_QUOTA_BLOCKED", (
            "8x1 quota-starved (majority delegation failures "
            f"{digest_dir_stats['delegation_failures_by_code']}); semantic "
            "qualification NOT ESTABLISHED — re-enter in a clear window (§7/§28)")
    else:
        disposition, reason = "ADVANCE_TO_8X3", (
            "8x1 screening clean: structural gates "
            f"{sum(1 for r in runs if r['hard_gates_pass'])}/{n_runs}, "
            f"specialist failure rate "
            f"{specialist_rate if specialist_rate is not None else 'n/a'} "
            f"(ceiling {SPECIALIST_COLLAPSE_CEILING}), supervisor failures "
            f"{sup_plan + sup_int}, no grounding regression")

    return {
        "artifact_version": "ModelCandidateQualificationV2",
        "wave": 2,
        "candidate_id": candidate_id,
        "stage": "8x1_screening",
        "results_root": str(qual_root),
        "runs": n_runs,
        "structural_hard_gates": (
            f"{sum(1 for r in runs if r['hard_gates_pass'])}/{n_runs} clean"
        ),
        "case_outcomes": outcomes,
        "delegation_failures": digest_dir_stats,
        "specialist_schema_output_failures": schema_fail,
        "specialist_structured_output_failures_incl_quota": int(reliability.get("specialist_structured_output_failures") or 0),
        "specialist_failure_rate": specialist_rate,
        "supervisor_PLAN_failures": sup_plan,
        "supervisor_INTEGRATE_failures": sup_int,
        "grounding_rejection_codes": grounding_codes,
        "provider_failures": provider_fail_runs,
        "disposition": disposition,
        "reason": reason,
        "frozen_axes_untouched": (
            "runtime/prompt/policy/ToolRegistry/AcceptanceProfile unchanged; "
            "holdouts untouched (§1/§31)"
        ),
        "created_at": __import__("time").strftime(
            "%Y-%m-%dT%H:%M:%S+00:00", __import__("time").gmtime()
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="disposition_wave2_screening")
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--qual-root", required=True)
    args = parser.parse_args()
    record = evaluate(args.candidate, Path(args.qual_root))
    out = Path(args.qual_root).parent / "ModelCandidateQualificationV2.json"
    out.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"{args.candidate}: {record['disposition']}")
    print(f"  {record['reason']}")
    print(f"  -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
