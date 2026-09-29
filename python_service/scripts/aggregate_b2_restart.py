#!/usr/bin/env python3
"""B2-restart §7-§13 canary / §16-§26 B2 baseline aggregation.

Reads every run under benchmarks/results/agent-v0/b2-restart/<stage>/
(case_id/repeat<k>/), classifies every trajectory rejection event into
the P/H/S/G taxonomy (§11):

  P — canonical identity plumbing (v2 expected 0)
  H — handle protocol failures (§11: should be ≈0)
  S — semantic proposal failures (legal; §11)
  G — evidence grounding / lifecycle failures (EVIDENCE_SNAPSHOT_MISSING,
      EVIDENCE_REF_CROSS_TASK; §9/§10 expect 0 — any hit = STOP gate)

plus supervisor structured-output failures (§12 primary metric) and
specialist delegation failures. Emits one aggregate artifact.

Handles trajectory_digest v1 (flat code list, pre-b2-restart runs) and
v2 (structured dict) formats.

Usage (from python_service/):
    .venv/bin/python scripts/aggregate_b2_restart.py --stage canary
    .venv/bin/python scripts/aggregate_b2_restart.py --stage b2
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PYTHON_SERVICE_ROOT = SCRIPT_PATH.parents[1]
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

RESULTS_BASE = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0" / "b2-restart"
)
CASES_ROOT = PYTHON_SERVICE_ROOT / "benchmarks" / "cases"
MODEL_CONFIG = (
    RESULTS_BASE / "sensenova-6.8-flash-lite.model-config.json"
)

# §11 taxonomy. EVIDENCE_REF_CROSS_TASK is deliberately G-class here (not
# P as in the A1-R layout): post-S4 it is an evidence-grounding outcome.
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
SUPERVISOR_OUTPUT_FAILURE_CODES = {
    "output_invalid", "output_retry_exhausted", "max_output_retries",
    "unexpected_output", "model_request_failed", "verification_failed",
}


def _digest_codes(run_dir: Path) -> tuple[list[str], list[dict], list[dict]]:
    tj = run_dir / "trajectory_digest.json"
    if not tj.exists():
        return [], [], []
    data = json.loads(tj.read_text(encoding="utf-8"))
    if isinstance(data, list):  # digest v1
        return data, [], []
    return (
        data.get("rejection_codes", []),
        data.get("supervisor_failures", []),
        data.get("delegation_failures", []),
    )


def _supervisor_output_failure(run_dir: Path, failure: dict | None) -> bool:
    """§12: supervisor structured-output failure at run level."""
    codes, sup_failures, _ = _digest_codes(run_dir)
    for f in sup_failures:
        if f.get("code") in SUPERVISOR_OUTPUT_FAILURE_CODES:
            return True
    if failure:
        reason = str(failure.get("failure_reason", ""))
        if "maximum output retries" in reason or "output retries" in reason:
            return True
    return False


def _provider_failure(failure: dict | None) -> bool:
    if not failure:
        return False
    reason = str(failure.get("failure_reason", "")).lower()
    return (
        "timed out" in reason
        or "timeout" in reason
        or "connection" in reason
        or "http" in reason
        or "provider" in reason
    )


def _case_outcomes(case_id: str, snapshot: dict) -> dict:
    """Negative-case behavior (§20-§21) and question dispositions."""
    questions = [
        {
            "question_id": q.get("question_id"),
            "status": q.get("status"),
            "disposition": q.get("disposition"),
        }
        for q in (snapshot.get("questions") or ())
    ]
    limitations = [
        str(l.get("limitation_type") or l.get("code") or l)
        for l in (snapshot.get("limitations") or ())
    ]
    findings = len(snapshot.get("findings") or ())
    return {"questions": questions, "limitations": limitations[:10],
            "findings": findings}


def _critical_recall(case_id: str, snapshot: dict) -> str:
    truth_file = CASES_ROOT / case_id / "truth_manifest.json"
    if not truth_file.exists():
        return "n/a"
    truth = json.loads(truth_file.read_text(encoding="utf-8"))
    expected = [
        e["expected_evidence_key"]
        for e in truth.get("critical_evidence", [])
        if e.get("expected_evidence_key")
    ]
    if not expected:
        return "n/a (zero critical)"
    discovered = set(snapshot.get("discovered_evidence_refs") or ())
    hits = [k for k in expected if k in discovered]
    return f"{len(hits)}/{len(expected)}"


def aggregate_stage(stage: str, results_root: Path) -> dict:
    runs: list[dict] = []
    code_counter: dict[str, int] = {}
    for case_dir in sorted(
        p for p in results_root.iterdir() if p.is_dir()
    ):
        case_id = case_dir.name
        for run_dir in sorted(case_dir.iterdir()):
            if not run_dir.is_dir():
                continue
            codes, sup_failures, deleg_failures = _digest_codes(run_dir)
            for c in codes:
                code_counter[c] = code_counter.get(c, 0) + 1
            row: dict = {
                "case_id": case_id,
                "repeat": run_dir.name,
                "rejection_codes": codes,
                "supervisor_failures": sup_failures,
                "delegation_failures": deleg_failures,
            }
            failure = None
            failure_file = run_dir / "failure.json"
            driver_failure = run_dir / "driver_failure.json"
            if failure_file.exists():
                failure = json.loads(
                    failure_file.read_text(encoding="utf-8")
                )
            if driver_failure.exists():
                failure = json.loads(
                    driver_failure.read_text(encoding="utf-8")
                )
                row["status"] = "driver_failed"
                row["failure_reason"] = str(
                    failure.get("error", "")
                )[:200]
                runs.append(row)
                continue
            result_file = run_dir / "result.json"
            if result_file.exists():
                snapshot = json.loads(
                    (run_dir / "snapshot.json").read_text(
                        encoding="utf-8"
                    )
                )
                result = json.loads(
                    result_file.read_text(encoding="utf-8")
                )
                gates = result.get("hard_gate_results", [])
                violations = [g for g in gates if not g.get("passed")]
                delegs = snapshot.get("delegations") or []
                integrated = sum(
                    1 for d in delegs if d.get("integrated_revision")
                )
                usage = snapshot.get("usage_entries") or []
                row.update(
                    {
                        "status": "completed",
                        "terminal_status": snapshot.get("terminal_status"),
                        "finalization_pass": bool(
                            snapshot.get("finalization_id")
                        ),
                        "hard_gate_violations": [
                            g.get("gate") or g.get("gate_id")
                            for g in violations
                        ],
                        "delegations": len(delegs),
                        "delegations_failed": sum(
                            1 for d in delegs
                            if d.get("status") == "failed"
                        ),
                        "delegations_integrated": integrated,
                        "runs_with_integrated_delegation": 1
                        if integrated
                        else 0,
                        "semantic_output_available": bool(
                            integrated or snapshot.get("findings")
                        ),
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
                        "critical_recall": _critical_recall(
                            case_id, snapshot
                        ),
                        "case_behavior": _case_outcomes(case_id, snapshot),
                        "supervisor_output_failure": (
                            _supervisor_output_failure(run_dir, None)
                        ),
                        "provider_failure": _provider_failure(None),
                        "run_id": result.get("run_manifest_id"),
                    }
                )
            elif failure is not None:
                row.update(
                    {
                        "status": "runner_failed",
                        "failure_reason": str(
                            failure.get("failure_reason", "")
                        )[:200],
                        "failure_layer": failure.get("failure_layer"),
                        "supervisor_output_failure": (
                            _supervisor_output_failure(run_dir, failure)
                        ),
                        "provider_failure": _provider_failure(failure),
                    }
                )
            else:
                row["status"] = "no_artifacts"
            runs.append(row)

    completed = [r for r in runs if r.get("status") == "completed"]
    failed_runs = [r for r in runs if r.get("status") == "runner_failed"]
    p_total = sum(v for k, v in code_counter.items() if k in P_CODES)
    h_total = sum(v for k, v in code_counter.items() if k in H_CODES)
    s_total = sum(v for k, v in code_counter.items() if k in S_CODES)
    g_total = sum(v for k, v in code_counter.items() if k in G_CODES)
    classified = len(P_CODES | H_CODES | S_CODES | G_CODES)

    integrated_cases = {
        r["case_id"]
        for r in completed
        if r.get("delegations_integrated", 0) > 0
    }
    sup_output_failures = sum(
        1 for r in runs if r.get("supervisor_output_failure")
    )
    runs_with_data = len(
        [r for r in runs if r.get("status") != "no_artifacts"]
    )
    walls = [r["wall_s"] for r in completed if r.get("wall_s")]

    # §13 qualification gate
    hard_gate_ok = all(
        not r.get("hard_gate_violations") for r in completed
    ) and not any(
        r.get("status") == "driver_failed" for r in runs
    )
    gate = {
        "structural_hard_gates_all_pass": hard_gate_ok,
        "P_identity_plumbing_zero": p_total == 0,
        "G_grounding_zero": g_total == 0,
        "EVIDENCE_SNAPSHOT_MISSING_zero": (
            code_counter.get("EVIDENCE_SNAPSHOT_MISSING", 0) == 0
        ),
        "EVIDENCE_REF_CROSS_TASK_zero": (
            code_counter.get("EVIDENCE_REF_CROSS_TASK", 0) == 0
        ),
        "supervisor_output_failure_rate": (
            round(sup_output_failures / runs_with_data, 3)
            if runs_with_data
            else None
        ),
        "supervisor_output_not_systematically_failing": (
            runs_with_data > 0
            and sup_output_failures / runs_with_data < 0.5
        ),
        "independent_cases_with_integration": sorted(integrated_cases),
        "at_least_2_independent_integrating_cases": (
            len(integrated_cases) >= 2
        ),
    }
    gate["qualified_for_b2"] = all(
        (
            gate["structural_hard_gates_all_pass"],
            gate["P_identity_plumbing_zero"],
            gate["G_grounding_zero"],
            gate["EVIDENCE_SNAPSHOT_MISSING_zero"],
            gate["EVIDENCE_REF_CROSS_TASK_zero"],
            gate["supervisor_output_not_systematically_failing"],
            gate["at_least_2_independent_integrating_cases"],
        )
    )

    return {
        "stage": stage,
        "runs": runs,
        "totals": {
            "runs_total": len(runs),
            "runs_completed": len(completed),
            "runs_runner_failed": len(failed_runs),
            "finalization_pass": sum(
                1 for r in completed if r.get("finalization_pass")
            ),
            "runs_with_integrated_delegation": sum(
                1 for r in completed
                if r.get("delegations_integrated", 0) > 0
            ),
            "total_integrated_delegations": sum(
                r.get("delegations_integrated", 0) for r in completed
            ),
            "total_delegations": sum(
                r.get("delegations", 0) for r in completed
            ),
            "delegations_failed": sum(
                r.get("delegations_failed", 0) for r in completed
            ),
            "semantic_output_available_runs": sum(
                1 for r in completed if r.get("semantic_output_available")
            ),
            "supervisor_output_failures": sup_output_failures,
            "provider_failure_runs": sum(
                1 for r in runs if r.get("provider_failure")
            ),
            "P_identity_plumbing_events": p_total,
            "H_handle_events": h_total,
            "S_semantic_events": s_total,
            "G_grounding_events": g_total,
            "rejection_code_distribution": code_counter,
            "wall_s_median": statistics.median(walls) if walls else None,
            "tokens_in_total": sum(
                r.get("tokens_in", 0) for r in completed
            ),
            "tokens_out_total": sum(
                r.get("tokens_out", 0) for r in completed
            ),
        },
        "qualification_gate": gate,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="aggregate_b2_restart")
    parser.add_argument(
        "--stage", choices=("smoke-deep", "canary", "b2"), required=True
    )
    parser.add_argument(
        "--results-root", default=None,
        help="override results root (default b2-restart/<stage>)",
    )
    args = parser.parse_args(argv)

    results_root = (
        Path(args.results_root)
        if args.results_root
        else RESULTS_BASE / args.stage
    )
    if not results_root.is_dir():
        print(f"no results root: {results_root}")
        return 1

    aggregate = aggregate_stage(args.stage, results_root)
    config = json.loads(MODEL_CONFIG.read_text(encoding="utf-8"))
    artifact = {
        "artifact_version": "B2RestartStageAggregateV1",
        "model": {
            "provider": config["provider"],
            "requested_model_id": config["requested_model_id"],
            "api_reported_model_id": config["api_reported_model_id"],
            "compatibility_encoding": config["compatibility_encoding"],
        },
        "runtime_commit": config["runtime_commit"],
        "corpus_id": config["corpus_id"],
        "corpus_hash": config["corpus_hash"],
        "supervisor_contract": "v2",
        "evidence_admission": "S4",
        **aggregate,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
    }
    out = RESULTS_BASE / f"{args.stage}-aggregate.v1.json"
    out.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    t, g = artifact["totals"], artifact["qualification_gate"]
    print(f"aggregate -> {out}")
    print(
        f"runs={t['runs_total']} done={t['runs_completed']} "
        f"runner_failed={t['runs_runner_failed']} "
        f"fin={t['finalization_pass']} "
        f"runs_w_integ={t['runs_with_integrated_delegation']} "
        f"integ_total={t['total_integrated_delegations']}"
    )
    print(
        f"P={t['P_identity_plumbing_events']} "
        f"H={t['H_handle_events']} S={t['S_semantic_events']} "
        f"G={t['G_grounding_events']} "
        f"sup_out_fail={t['supervisor_output_failures']}/{t['runs_total']} "
        f"provider_fail={t['provider_failure_runs']}"
    )
    print("codes:", json.dumps(t["rejection_code_distribution"]))
    print("gate.qualified_for_b2:", g["qualified_for_b2"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
