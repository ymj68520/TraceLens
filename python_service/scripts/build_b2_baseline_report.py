#!/usr/bin/env python3
"""P8B B2 restart — BaselineMeasurementReportV3 builder (spec §12-§29).

Reads every run under benchmarks/results/agent-v0/b2-restart/b2/
(snapshot.json / result.json / failure.json / trajectory_digest.json v3),
evaluates deterministically (evaluate-only was already hash-verified by
the driver on --cleanup-tasks) and emits ONE artifact with:

- §12 pipeline metrics (kept separate: completed specialist results vs
  integrated delegations vs semantic availability vs finalization)
- §13 output reliability SPLIT by layer (specialist / supervisor PLAN /
  supervisor INTEGRATE)
- §10/§26 HANDLE_KIND_MISMATCH deep analysis (kind pairs, field
  positions, case concentration, self-correction across cycles)
- §17 A1-T proposal-contract audit and §18 S4 audit
- §23 per-case 3-repeat reliability distribution (no best-of)
- §25 failure attribution over the existing enum vocabulary
- quality / reliability / cost dashboards (§28)

Usage (from python_service/):
    .venv/bin/python scripts/build_b2_baseline_report.py
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

REPO_ROOT = PYTHON_SERVICE_ROOT.parent
ROOT = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0" / "b2-restart"
)
CASES_ROOT = PYTHON_SERVICE_ROOT / "benchmarks" / "cases"

import argparse as _argparse


def _paths() -> tuple[Path, Path, Path]:
    parser = _argparse.ArgumentParser(prog="build_b2_baseline_report")
    parser.add_argument(
        "--runs-root",
        default=str(ROOT / "b2"),
        help="directory containing case_id/repeat<k>/ run artifacts",
    )
    parser.add_argument(
        "--baseline",
        default=(
            "benchmarks/profiles/precalibration-runtime-baseline-v3.json"
        ),
    )
    parser.add_argument("--out", default=None)
    args, _unknown = parser.parse_known_args()
    runs_root = Path(args.runs_root)
    if not runs_root.is_absolute():
        runs_root = PYTHON_SERVICE_ROOT / runs_root
    baseline = Path(args.baseline)
    if not baseline.is_absolute():
        baseline = PYTHON_SERVICE_ROOT / baseline
    out = (
        Path(args.out)
        if args.out
        else runs_root.parent
        / f"{runs_root.name}-measurement-report.json"
    )
    return runs_root, baseline, out


B2_ROOT, BASELINE_V3, OUT_FILE = _paths()

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


def _digest(run_dir: Path) -> dict:
    tj = run_dir / "trajectory_digest.json"
    if not tj.exists():
        return {}
    data = json.loads(tj.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return {"digest_version": 1, "rejection_codes": data}
    return data


def _failure(run_dir: Path) -> dict | None:
    for name in ("failure.json", "driver_failure.json"):
        f = run_dir / name
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))
    return None


def _classify_rep(run: dict) -> str:
    """§23 structural outcome class for one repetition."""
    if run["status"] == "runner_failed":
        return "runtime/provider_failure"
    if run["status"] != "completed":
        return "incomplete"
    if run["delegations_completed"] == 0:
        return "incomplete"
    if run["integrated"] > 0 and run["finalization_pass"]:
        return "success"
    if run["integrated"] > 0:
        return "partial:integrated_not_finalized"
    return "incomplete:no_integration"


def _attribute_failure(run: dict) -> str | None:
    """§25 failure attribution for a NON-success repetition."""
    if run["status"] == "runner_failed":
        reason = str(run.get("failure_reason", "")).lower()
        if "timed out" in reason or "timeout" in reason or "connection" in reason:
            return "PROVIDER_INFRA"
        return "RUNTIME_INFRA"
    if run["status"] != "completed":
        return "RUNTIME_INFRA"
    codes = run.get("rejection_codes", [])
    if any(c in G_CODES for c in codes):
        return "EVIDENCE_LIFECYCLE"
    specialist_out = [
        f.get("failure_code")
        for f in run.get("delegation_failures", [])
        if f.get("failure_code") == "agent_output_invalid"
    ]
    if specialist_out:
        return "MODEL_OUTPUT_SPECIALIST"
    if any(c in H_CODES for c in codes):
        if run["integrated"] > 0:
            return None  # recovered in a later cycle
        if run.get("supervisor_failures"):
            return "MODEL_OUTPUT_SUPERVISOR"
        return "HANDLE_PROTOCOL"
    if any(c in S_CODES for c in codes):
        return "SEMANTIC_TRANSITION"
    if any(c in P_CODES for c in codes):
        return "MODEL_OUTPUT_SUPERVISOR"
    if run["integrated"] > 0 and not run["finalization_pass"]:
        # integrated but the gate refused: disposition/policy discipline
        return "SEMANTIC_TRANSITION"
    if run["integrated"] == 0 and run["delegations_completed"] > 0:
        return "SEMANTIC_TRANSITION"
    return None


def _parse_h_violation(message: str) -> dict | None:
    """'handle D1 is a delegation, expected evidence' -> structured pair."""
    try:
        head, expected = message.split(", expected ")
        handle = head.split("is a")[0].replace("handle", "").strip().strip("'\"")
        actual = head.split("is a")[1].strip()
        return {
            "handle": handle,
            "actual_kind": actual,
            "expected_kind": expected.strip().rstrip("."),
        }
    except Exception:
        return None


def main() -> int:
    baseline = json.loads(BASELINE_V3.read_text(encoding="utf-8"))
    corpus = json.loads(
        (
            PYTHON_SERVICE_ROOT / "benchmarks/corpus/corpus-agent-v0-calibration.v1.json"
        ).read_text(encoding="utf-8")
    )
    case_ids = [c["case_id"] for c in corpus["calibration_cases"]]

    runs: list[dict] = []
    for case_id in case_ids:
        case_root = B2_ROOT / case_id
        if not case_root.is_dir():
            continue
        for run_dir in sorted(p for p in case_root.iterdir() if p.is_dir()):
            digest = _digest(run_dir)
            failure = _failure(run_dir)
            run: dict = {
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
            result_file = run_dir / "result.json"
            if result_file.exists():
                snapshot = json.loads(
                    (run_dir / "snapshot.json").read_text(encoding="utf-8")
                )
                result = json.loads(
                    result_file.read_text(encoding="utf-8")
                )
                delegs = snapshot.get("delegations") or []
                integrated = sum(
                    1 for d in delegs if d.get("integrated_revision")
                )
                usage = snapshot.get("usage_entries") or []
                gates = [
                    g for g in result.get("hard_gate_results", [])
                    if not g.get("passed")
                ]
                questions = [
                    {
                        "question_id": q.get("question_id"),
                        "status": q.get("status"),
                        "disposition": q.get("disposition"),
                    }
                    for q in (snapshot.get("questions") or ())
                ]
                run.update(
                    {
                        "status": "completed",
                        "terminal_status": snapshot.get("terminal_status"),
                        "finalization_pass": bool(
                            snapshot.get("finalization_id")
                        ),
                        "hard_gate_violations": [
                            g.get("gate") or g.get("gate_id") for g in gates
                        ],
                        "delegations_total": len(delegs),
                        "delegations_failed": sum(
                            1 for d in delegs if d.get("status") == "failed"
                        ),
                        "delegations_completed": sum(
                            1 for d in delegs if d.get("status") == "completed"
                        ),
                        "integrated": integrated,
                        "semantic_output_available": bool(
                            integrated or snapshot.get("findings")
                        ),
                        "findings": len(snapshot.get("findings") or ()),
                        "questions": questions,
                        "limitations": [
                            str(
                                (l or {}).get("limitation_type")
                                if isinstance(l, dict)
                                else l
                            )
                            for l in (snapshot.get("limitations") or ())
                        ][:12],
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
                        "run_id": result.get("run_manifest_id"),
                        "result_hash": result.get("result_hash"),
                        "failure_reason": None,
                    }
                )
            else:
                run.update(
                    {
                        "status": "runner_failed",
                        "failure_layer": (failure or {}).get("failure_layer"),
                        "failure_reason": str(
                            (failure or {}).get("failure_reason", "")
                        )[:200],
                    }
                )
            run["outcome_class"] = _classify_rep(run)
            run["failure_attribution"] = _attribute_failure(run)
            runs.append(run)

    totals = {
        "runs_total": len(runs),
        "runs_completed": sum(
            1 for r in runs if r["status"] == "completed"
        ),
        "runs_runner_failed": sum(
            1 for r in runs if r["status"] == "runner_failed"
        ),
        "hard_gate_violation_runs": sum(
            1 for r in runs if r.get("hard_gate_violations")
        ),
        # §12 pipeline (kept separate)
        "finalization_pass": sum(
            1 for r in runs if r.get("finalization_pass")
        ),
        "runs_with_completed_specialist_result": sum(
            1 for r in runs if r.get("delegations_completed", 0) > 0
        ),
        "total_completed_specialist_results": sum(
            r.get("delegations_completed", 0) for r in runs
        ),
        "runs_with_integrated_delegation": sum(
            1 for r in runs if r.get("integrated", 0) > 0
        ),
        "integrated_delegation_count": sum(
            r.get("integrated", 0) for r in runs
        ),
        "semantic_output_available_runs": sum(
            1 for r in runs if r.get("semantic_output_available")
        ),
        # §13 output reliability SPLIT
        "specialist_structured_output_failures": sum(
            1
            for r in runs
            if any(
                f.get("failure_code") == "agent_output_invalid"
                for f in r.get("delegation_failures", [])
            )
        ),
        "supervisor_plan_structured_output_failures": sum(
            1
            for r in runs
            if any(
                sf.get("delegations_admitted_before", 0) == 0
                and sf.get("delegations_completed_before", 0) == 0
                for sf in r.get("supervisor_failures", [])
            )
        ),
        "supervisor_integrate_structured_output_failures": sum(
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
                for w in ("timed out", "timeout", "connection")
            )
        ),
        # P/H/S/G
        "P_identity_events": sum(
            1
            for r in runs
            for c in r["rejection_codes"]
            if c in P_CODES
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
        "rejection_code_distribution": dict(
            Counter(
                c for r in runs for c in r["rejection_codes"]
            )
        ),
        "tokens_in_total": sum(r.get("tokens_in", 0) for r in runs),
        "tokens_out_total": sum(r.get("tokens_out", 0) for r in runs),
        "wall_s_median": statistics.median(
            [r["wall_s"] for r in runs if r.get("wall_s")] or [None]
        )
        if any(r.get("wall_s") for r in runs)
        else None,
    }

    # §17 A1-T proposal-contract audit
    completions_all = [
        c for r in runs for c in r.get("completions", [])
    ]
    proposal_audit = {
        "completed_delegations": len(completions_all),
        "with_proposal_contract": sum(
            1
            for c in completions_all
            if (c.get("specialist_proposal_contract") or {}).get(
                "proposal_version"
            )
            == "specialist-result-proposal:v1"
        ),
        "with_proposal_hash": sum(
            1
            for c in completions_all
            if (c.get("specialist_proposal_contract") or {}).get(
                "proposal_hash"
            )
        ),
        "with_trusted_enrichment_digest": sum(
            1
            for c in completions_all
            if (c.get("specialist_proposal_contract") or {}).get(
                "trusted_enrichment_digest"
            )
        ),
    }
    proposal_audit["contract_consistent"] = (
        proposal_audit["with_proposal_contract"]
        == proposal_audit["completed_delegations"]
        and proposal_audit["with_proposal_hash"]
        == proposal_audit["completed_delegations"]
        and proposal_audit["with_trusted_enrichment_digest"]
        == proposal_audit["completed_delegations"]
    )

    # §18 S4 audit
    s4_audit = {
        "completed_delegations": len(completions_all),
        "with_snapshots_admitted": sum(
            1
            for c in completions_all
            if (c.get("evidence_snapshots_admitted") or 0) > 0
        ),
        "zero_snapshot_completed_results": sum(
            1
            for c in completions_all
            if not (c.get("evidence_snapshots_admitted") or 0)
        ),
        "EVIDENCE_SNAPSHOT_MISSING_events": totals["rejection_code_distribution"].get(
            "EVIDENCE_SNAPSHOT_MISSING", 0
        ),
    }

    # §10/§26 HANDLE_KIND_MISMATCH analysis
    h_details: list[dict] = []
    for r in runs:
        run_integrated_after = r.get("integrated", 0) > 0
        for rej in r.get("rejections", []):
            for v in rej.get("resolution_violations", []):
                if v.get("code") == "HANDLE_KIND_MISMATCH":
                    parsed = _parse_h_violation(str(v.get("message", "")))
                    h_details.append(
                        {
                            "case_id": r["case_id"],
                            "repeat": r["repeat"],
                            "seq": rej.get("seq"),
                            "stage": rej.get("stage"),
                            "location": v.get("location"),
                            "handle": (parsed or {}).get("handle"),
                            "actual_kind": (parsed or {}).get("actual_kind"),
                            "expected_kind": (parsed or {}).get(
                                "expected_kind"
                            ),
                            "run_recovered_integration": run_integrated_after,
                            "action_types_in_proposal": [
                                a.get("action_type")
                                for a in rej.get("raw_action_signatures", [])
                            ],
                        }
                    )
    h_analysis = {
        "total_events": len(h_details),
        "runs_affected": sorted(
            {f"{h['case_id']}/{h['repeat']}" for h in h_details}
        ),
        "cases_affected": sorted({h["case_id"] for h in h_details}),
        "kind_pairs": dict(
            Counter(
                f"{h['actual_kind']} -> {h['expected_kind']}"
                for h in h_details
            )
        ),
        "field_positions": dict(
            Counter(
                (h["location"] or "").split("[")[0] for h in h_details
            )
        ),
        "handles_involved": dict(
            Counter(h.get("handle") for h in h_details)
        ),
        "runs_recovered_integration_despite_rejection": sorted(
            {
                f"{h['case_id']}/{h['repeat']}"
                for h in h_details
                if h["run_recovered_integration"]
            }
        ),
        "events": h_details,
    }

    # §23 per-case reliability distribution (no best-of)
    per_case: dict = {}
    for case_id in case_ids:
        reps = [r for r in runs if r["case_id"] == case_id]
        if not reps:
            continue
        per_case[case_id] = {
            "outcome_grid": [
                {"repeat": r["repeat"], "class": r["outcome_class"]}
                for r in sorted(reps, key=lambda x: x["repeat"])
            ],
            "success": sum(
                1 for r in reps if r["outcome_class"] == "success"
            ),
            "incomplete": sum(
                1
                for r in reps
                if r["outcome_class"].startswith(("incomplete", "partial"))
            ),
            "runtime_provider_failure": sum(
                1 for r in reps if r["outcome_class"] == "runtime/provider_failure"
            ),
            "finalization_pass": sum(
                1 for r in reps if r.get("finalization_pass")
            ),
            "critical_recall": [
                _critical_recall(
                    case_id, B2_ROOT / case_id / r["repeat"]
                )["critical_recall"]
                for r in sorted(reps, key=lambda x: x["repeat"])
            ],
        }

    # §25 failure attribution
    attribution = dict(
        Counter(
            r["failure_attribution"]
            for r in runs
            if r["failure_attribution"]
        )
    )
    successes = sum(1 for r in runs if r["outcome_class"] == "success")

    # §14 evidence recall (from result.json where computed)
    recall_rows = []
    for r in runs:
        if r["status"] != "completed":
            continue
        result_file = B2_ROOT / r["case_id"] / r["repeat"] / "result.json"
        recall_rows.append(
            {
                "case_id": r["case_id"],
                "repeat": r["repeat"],
                **_critical_recall(r["case_id"], result_file.parent),
            }
        )

    report = {
        "artifact_version": "BaselineMeasurementReportV4",
        "round": "p8b-b2-restart",
        "runtime_baseline": {
            "profile_version": baseline["profile_version"],
            "runtime_git_commit": baseline["runtime_git_commit"],
            "production_runtime_commit": baseline["production_runtime_commit"],
            "file": str(BASELINE_V3.relative_to(PYTHON_SERVICE_ROOT)),
        },
        "model": baseline["model_identity"],
        "corpus": baseline["corpus"],
        "historical_comparison_note": (
            "step-5 (R2): supervisor structured-output failure 16/24 = 67%; "
            "SenseNova pre-A1-T: specialist structured-output failure 7/8; "
            "this report: new B2 distribution on the A1-T runtime. Different "
            "runtime/model contract epochs — descriptive only, NOT pooled "
            "statistics (spec §29)."
        ),
        "totals": totals,
        "proposal_contract_audit": proposal_audit,
        "s4_audit": s4_audit,
        "handle_kind_mismatch_analysis": h_analysis,
        "per_case_reliability": per_case,
        "failure_attribution": {
            "successes": successes,
            "attributed_failures": attribution,
            "unattributed_non_success": sum(
                1
                for r in runs
                if r["outcome_class"] != "success"
                and r["failure_attribution"] is None
            ),
        },
        "evidence_recall": recall_rows,
        "runs": runs,
        "created_at": time.strftime(
            "%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()
        ),
    }
    OUT_FILE.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"report -> {OUT_FILE}")
    t = totals
    print(
        f"runs={t['runs_total']} done={t['runs_completed']} "
        f"failed={t['runs_runner_failed']} gate_viol={t['hard_gate_violation_runs']}"
    )
    print(
        f"completed_results={t['total_completed_specialist_results']} "
        f"runs_w_completed={t['runs_with_completed_specialist_result']} | "
        f"integrated={t['integrated_delegation_count']} "
        f"runs_w_integ={t['runs_with_integrated_delegation']} | "
        f"fin={t['finalization_pass']} | semantic={t['semantic_output_available_runs']}"
    )
    print(
        f"out_failures: specialist={t['specialist_structured_output_failures']} "
        f"plan={t['supervisor_plan_structured_output_failures']} "
        f"integrate={t['supervisor_integrate_structured_output_failures']} "
        f"provider={t['provider_failure_runs']}"
    )
    print(
        f"P={t['P_identity_events']} H={t['H_handle_events']} "
        f"S={t['S_semantic_events']} G={t['G_grounding_events']}"
    )
    print("codes:", json.dumps(t["rejection_code_distribution"]))
    print(
        "proposal_audit:", json.dumps(proposal_audit),
        "| s4_audit:", json.dumps(s4_audit),
    )
    print("attribution:", json.dumps(attribution))
    return 0


def _critical_recall(case_id: str, run_dir: Path) -> dict:
    truth_file = CASES_ROOT / case_id / "truth_manifest.json"
    snapshot_file = run_dir / "snapshot.json"
    if not truth_file.exists() or not snapshot_file.exists():
        return {"critical_recall": "n/a"}
    truth = json.loads(truth_file.read_text(encoding="utf-8"))
    snapshot = json.loads(snapshot_file.read_text(encoding="utf-8"))
    expected = [
        e["expected_evidence_key"]
        for e in truth.get("critical_evidence", [])
        if e.get("expected_evidence_key")
    ]
    if not expected:
        return {"critical_recall": "n/a (zero critical)"}
    discovered = set(snapshot.get("discovered_evidence_refs") or ())
    hits = [k for k in expected if k in discovered]
    return {"critical_recall": f"{len(hits)}/{len(expected)}"}


if __name__ == "__main__":
    raise SystemExit(main())
