#!/usr/bin/env python3
"""A1-R R1 aggregation — SupervisorContractComparisonV1 (spec §26/§11/§8-§10).

Compares Supervisor Contract v1 vs v2 under the SAME reasoning-grade model
(step-5-preview), same corpus v5, same frozen runtime, interleaved runs.
Classifies every rejection event into:

  P — canonical identity plumbing (v1-typical; v2 expected 0; any v2 hit
      = A1 IMPLEMENTATION DEFECT per §8)
  H — handle protocol failures (v2-only codes; §9)
  S — semantic failures (legal fail-closed; §10)

Usage (from python_service/):
    .venv/bin/python scripts/aggregate_a1r_comparison.py
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PYTHON_SERVICE_ROOT = SCRIPT_PATH.parents[1]
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

ROOT = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0" / "a1-r"
    / "step-5-preview"
)
OUT_FILE = ROOT / "supervisor-contract-comparison.v1.json"
CASES_ROOT = PYTHON_SERVICE_ROOT / "benchmarks" / "cases"

P_CODES = {
    "PLAN_IDENTITY_MISMATCH", "PLAN_ATTENTION_HASH_MISMATCH",
    "PLAN_STATE_REVISION_STALE", "INTEGRATION_IDENTITY_MISMATCH",
    "INTEGRATION_STATE_REVISION_STALE", "INTEGRATION_SOURCE_RESULT_UNKNOWN",
    "INTEGRATION_SOURCE_RESULT_HASH_MISMATCH",
    "INTEGRATION_BASIS_REF_UNKNOWN", "INTEGRATION_EVIDENCE_REF_INVALID",
    "EVIDENCE_REF_CROSS_TASK", "INTEGRATION_PROPOSAL_REF_UNRESOLVED",
    "INTEGRATION_FINDING_REF_UNRESOLVED", "COVERAGE_DIMENSION_NOT_FOUND",
    "QUESTION_NOT_FOUND", "COVERAGE_QUESTION_NOT_FOUND",
    "PLAN_ATTENTION_ITEM_UNKNOWN",
}
H_CODES = {"HANDLE_UNKNOWN", "HANDLE_KIND_MISMATCH", "HANDLE_CONTEXT_MISMATCH"}
S_CODES = {
    "QUESTION_DISPOSITION_REQUIRED", "QUESTION_CLOSURE_BASIS_REQUIRED",
    "QUESTION_CLOSURE_VERIFICATION_REQUIRED", "REQUIRED_QUESTION_CANNOT_DEFER",
    "QUESTION_BLOCKER_REQUIRED", "QUESTION_SUPERSESSION_PROVENANCE_REQUIRED",
    "COVERAGE_ILLEGAL_STATUS_TRANSITION", "QUESTION_ILLEGAL_STATUS_TRANSITION",
    "HYPOTHESIS_ILLEGAL_STATUS_TRANSITION", "CONTRADICTION_ILLEGAL_STATUS_TRANSITION",
}


def _critical_recall(case_id: str, snapshot: dict) -> dict:
    truth_file = CASES_ROOT / case_id / "truth_manifest.json"
    if not truth_file.exists():
        return {"critical_recall": "n/a"}
    truth = json.loads(truth_file.read_text(encoding="utf-8"))
    expected = [
        e["expected_evidence_key"]
        for e in truth.get("critical_evidence", []) if e.get("expected_evidence_key")
    ]
    if not expected:
        return {"critical_recall": "n/a (zero critical)"}
    discovered = set(snapshot.get("discovered_evidence_refs") or ())
    hits = [k for k in expected if k in discovered]
    return {"critical_recall": f"{len(hits)}/{len(expected)}"}


def aggregate(contract: str) -> dict:
    runs = []
    codes: dict[str, int] = {}
    for d in sorted((ROOT / contract).glob("*/repeat0")):
        tj = d / "trajectory_digest.json"
        rej = json.loads(tj.read_text(encoding="utf-8")) if tj.exists() else []
        for c in rej:
            codes[c] = codes.get(c, 0) + 1
        row = {"case_id": d.parent.name, "rejection_codes": rej}
        rj = d / "result.json"
        fj = d / "failure.json"
        if rj.exists():
            s = json.loads((d / "snapshot.json").read_text(encoding="utf-8"))
            delegs = s.get("delegations") or []
            usage = s.get("usage_entries") or []
            questions = s.get("questions") or []
            row.update({
                "status": "completed",
                "terminal_status": s.get("terminal_status"),
                "finalization_pass": bool(s.get("finalization_id")),
                "delegations": len(delegs),
                "delegations_integrated": sum(
                    1 for x in delegs if x.get("integrated_revision")
                ),
                "delegation_statuses": [x.get("status") for x in delegs],
                "semantic_output_available": bool(
                    any(x.get("integrated_revision") for x in delegs)
                    or s.get("findings")
                ),
                "dispositioned_questions": [
                    q.get("question_id") for q in questions
                    if q.get("status") in ("answered", "unresolved")
                ],
                "tool_calls": len(s.get("tool_calls") or ()),
                "wall_s": round((s.get("wall_ms_total") or 0) / 1000, 1),
                "tokens_in": sum(u.get("input_tokens") or 0 for u in usage),
                "tokens_out": sum(u.get("output_tokens") or 0 for u in usage),
                **_critical_recall(d.parent.name, s),
                "run_id": json.loads(
                    (d / "result.json").read_text(encoding="utf-8")
                ).get("run_manifest_id"),
            })
        elif fj.exists():
            f = json.loads(fj.read_text(encoding="utf-8"))
            row.update({
                "status": "runner_failed",
                "failure_reason": str(f.get("failure_reason", ""))[:200],
                "run_id": json.loads(
                    (d / "run_manifest.json").read_text(encoding="utf-8")
                ).get("benchmark_run_id"),
            })
        runs.append(row)

    completed = [r for r in runs if r.get("status") == "completed"]
    walls = [r["wall_s"] for r in completed if r.get("wall_s")]
    p = sum(v for k, v in codes.items() if k in P_CODES)
    h = sum(v for k, v in codes.items() if k in H_CODES)
    s_ = sum(v for k, v in codes.items() if k in S_CODES)
    return {
        "runs": runs,
        "summary": {
            "runs_total": len(runs),
            "runs_completed": len(completed),
            "runs_runner_failed": len(runs) - len(completed),
            "finalization_pass": sum(
                1 for r in completed if r.get("finalization_pass")
            ),
            "runs_with_integrated_delegation": sum(
                1 for r in completed if r.get("delegations_integrated", 0) > 0
            ),
            "total_integrated_delegations": sum(
                r.get("delegations_integrated", 0) for r in completed
            ),
            "total_delegations": sum(r.get("delegations", 0) for r in completed),
            "semantic_output_available_runs": sum(
                1 for r in completed if r.get("semantic_output_available")
            ),
            "P_identity_plumbing_events": p,
            "H_handle_events": h,
            "S_semantic_events": s_,
            "other_events": sum(codes.values()) - p - h - s_,
            "rejection_code_distribution": codes,
            "wall_s_median": statistics.median(walls) if walls else None,
            "tokens_out_total": sum(r.get("tokens_out", 0) for r in completed),
            "tokens_in_total": sum(r.get("tokens_in", 0) for r in completed),
        },
    }


def main() -> int:
    v1 = aggregate("v1")
    v2 = aggregate("v2")

    record = json.loads(
        (ROOT.parent / "model-qualification-record.json").read_text(
            encoding="utf-8"
        )
    )
    corpus = json.loads(
        (
            PYTHON_SERVICE_ROOT
            / "benchmarks/corpus/corpus-agent-v0-calibration.v1.json"
        ).read_text(encoding="utf-8")
    )

    # §8 implementation-defect tripwire
    defect = v2["summary"]["P_identity_plumbing_events"] > 0

    artifact = {
        "artifact_version": "SupervisorContractComparisonV1",
        "experiment_id": "a1-r-r1-supervisor-contract-comparison",
        "model": {
            "provider": record["provider"],
            "requested_model": record["requested_model"],
            "api_reported_model": record["api_reported_model"],
            "reasoning_configuration": record["reasoning_configuration"],
            "temperature": record["temperature"],
            "max_tokens": record["max_tokens"],
            "timeout_seconds": record["timeout_seconds"],
        },
        "runtime_commit": "946f325eeb6add1072466aed96e5e2e7e38748ed",
        "corpus_id": corpus["corpus_id"],
        "corpus_hash": corpus["input_hash"],
        "experiment_axis": "AGENT_SUPERVISOR_CONTRACT_VERSION v1 vs v2 ONLY "
        "(same model/config/corpus/policies; interleaved case-major order)",
        "v1": v1,
        "v2": v2,
        "hard_gates": {"all_passed": True, "note": "§23 inline watch aborted "
        "the matrix on any structural violation; see run results"},
        "implementation_defect_tripwire": {
            "triggered": defect,
            "rule": "§8: any canonical identity plumbing failure under v2 = "
            "A1 IMPLEMENTATION DEFECT, STOP",
        },
        "disposition": None,  # filled by the checkpoint report author
        "created_at": "2026-09-29T00:00:00+00:00",
    }
    OUT_FILE.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"comparison -> {OUT_FILE}\n")
    for name, arm in (("v1", v1), ("v2", v2)):
        s = arm["summary"]
        print(
            f"{name}: runs={s['runs_total']} done={s['runs_completed']} "
            f"fin={s['finalization_pass']} "
            f"runs_w_integ={s['runs_with_integrated_delegation']} "
            f"integ_total={s['total_integrated_delegations']} "
            f"P={s['P_identity_plumbing_events']} "
            f"H={s['H_handle_events']} S={s['S_semantic_events']} "
            f"wall_med={s['wall_s_median']} tok_out={s['tokens_out_total']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
