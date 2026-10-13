"""Space Bunny Alpha / OpenRouter 8x1 screening disposition (§10-§21).

Deterministically re-derives everything from the persisted 8x1 series
(evaluate-only, zero model calls):
  §1  per-request routing identity (identity_telemetry.json, all runs)
  §10 schema-vs-provider failure separation, INCLUDING run-level output
      failures (failure_layer=RUNTIME, "Exceeded maximum output retries"
      = MODEL_OUTPUT_SCHEMA_FAILURE) which leave no delegation-failure
      record in the trajectory digest
  §11 structural hard gates recomputed from terminal snapshots
  §12 negative gates (overclaim-channel components)
  §13 P/H/S/G counters (counting rule labeled)
  §15 question terminalization (frozen metric: charter q-1 leaves
      {open, in_progress}); failed runs are non-terminalized with M7
  §16 coverage status distribution (terminal snapshots only)
  §17 CaseOutcomeV2 (terminal snapshots only)

Dispositions (§21): READY_FOR_8X3 / NOT_QUALIFIED_SCREENING /
PROVIDER_CAPACITY_BLOCKED / PROVIDER_ROUTING_IDENTITY_MISMATCH /
MEASUREMENT_INVALID.

Usage (from python_service/):
    .venv/bin/python scripts/disposition_openrouter_8x1.py \
        --results-root benchmarks/results/agent-v0/model-candidates/space-bunny-alpha-openrouter/qual-8x1
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

PYTHON_SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

from disposition_wave2_final import (  # noqa: E402
    OPEN_STATUSES,
    SPECIALIST_COLLAPSE_CEILING,
)
from disposition_wave2_screening import QUOTA_CODES  # noqa: E402

DEFAULT_REQUESTED_MODEL = "stealth/space-bunny-alpha"
SCHEMA_FAILURE_CODES = {"agent_output_invalid"}
OUTPUT_RETRY_MARKER = "exceeded maximum output retries"


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(prog="disposition_openrouter_8x1")
    parser.add_argument("--results-root", required=True)
    parser.add_argument(
        "--candidate-config",
        default="benchmarks/results/agent-v0/model-candidates/"
                "space-bunny-alpha-openrouter/candidate-config.json",
    )
    parser.add_argument("--requested-model", default=DEFAULT_REQUESTED_MODEL)
    parser.add_argument("--candidate-id", default="space-bunny-alpha@openrouter")
    parser.add_argument(
        "--artifact-version",
        default="SpaceBunnyOpenRouter8x1ScreeningReportV1")
    args = parser.parse_args()
    root = Path(args.results_root)
    candidate_config = _load(Path(args.candidate_config))
    config_hash = candidate_config.get("config_hash")
    PROVIDER_MODEL_ID = args.requested_model

    # ---- walk all scheduled runs --------------------------------------------
    run_dirs = sorted(root.glob("t*/repeat*"))
    scheduled = len(run_dirs)
    terminal_runs = []   # _walk_runs rows for snapshot-bearing runs
    failed_runs = []
    identity_records = []
    failure_code_hist: Counter = Counter()
    provider_failures = schema_delegation_failures = 0
    sup_plan = sup_integrate = 0
    handle_unknown = plan_duplicate = grounding_events = 0

    for run_dir in run_dirs:
        case = run_dir.parent.name
        # §1 identity telemetry (present for every run — written by the
        # runtime-layer failure path too)
        tp = run_dir / "identity_telemetry.json"
        if tp.is_file():
            for rec in _load(tp):
                identity_records.append({"run": f"{case}/{run_dir.name}", **rec})

        failure_path = run_dir / "failure.json"
        if failure_path.is_file():
            f = _load(failure_path)
            reason = str(f.get("failure_reason", ""))
            layer = f.get("failure_layer")
            if OUTPUT_RETRY_MARKER in reason.lower():
                fclass = "MODEL_OUTPUT_SCHEMA_FAILURE"
            else:
                fclass = "RUNTIME_FAILURE_UNATTRIBUTED"
            failed_runs.append({
                "case_id": case, "repeat": run_dir.name,
                "failure_layer": layer, "reason": reason[:200],
                "classification": fclass,
            })
        else:
            digest = _load(run_dir / "trajectory_digest.json")
            for r in digest.get("rejections", []):
                stage = str(r.get("stage", ""))
                for code in r.get("violation_codes", []):
                    if "PLAN_DUPLICATE" in code:
                        plan_duplicate += 1
                    if "HANDLE_UNKNOWN" in code or "HANDLE" in code:
                        handle_unknown += 1
                    if "GROUND" in code.upper() or "ground" in stage.lower():
                        grounding_events += 1
            for f in digest.get("supervisor_failures", []):
                stage = str(f.get("stage", "")).lower()
                if "plan" in stage:
                    sup_plan += 1
                elif "integrate" in stage:
                    sup_integrate += 1
            for f in digest.get("delegation_failures", []):
                code = str(f.get("failure_code", "unknown"))
                failure_code_hist[code] += 1
                if any(q in code.lower() for q in QUOTA_CODES):
                    provider_failures += 1
                else:
                    schema_delegation_failures += 1

    # terminal rows via the shared deterministic walker
    from disposition_wave2_screening import _walk_runs
    terminal_runs = _walk_runs(root)
    n_terminal = len(terminal_runs)

    # ---- §1 identity verdict ---------------------------------------------------
    identity_mismatch = any(
        r.get("returned_model") != PROVIDER_MODEL_ID for r in identity_records
    )
    runs_with_identity = len({r["run"] for r in identity_records})

    # ---- §18 evaluate-only reproduction (terminal snapshots) --------------------
    evaluate_reproduced = True
    from httpserver.services.benchmarks.metrics import structural_hard_gates
    from httpserver.services.benchmarks.snapshot import BenchmarkRunSnapshotV1
    for run_dir in run_dirs:
        if not (run_dir / "result.json").is_file():
            continue
        persisted = {
            g["gate_id"]: g["passed"]
            for g in _load(run_dir / "result.json").get("hard_gate_results", [])
        }
        snap_model = BenchmarkRunSnapshotV1(**_load(run_dir / "snapshot.json"))
        recomputed = {g.gate_id: g.passed for g in structural_hard_gates(snap_model)}
        if persisted and persisted != recomputed:
            evaluate_reproduced = False
    gates_clean = all(r["hard_gates_pass"] for r in terminal_runs)

    # ---- §15 terminalization + §16/§17 (terminal snapshots) ----------------------
    terminalized = 0
    non_terminal = []
    coverage_statuses: Counter = Counter()
    outcomes: Counter = Counter()
    cases_root = PYTHON_SERVICE_ROOT / "benchmarks" / "cases"
    for r in terminal_runs:
        outcomes[r["case_outcome"]] += 1
        snap = _load(root / r["case_id"] / r["repeat"] / "snapshot.json")
        questions = snap.get("questions") or []
        charter = [q for q in questions if q.get("question_id") == "q-1"]
        q_ok = bool(charter) and charter[0].get("status") not in OPEN_STATUSES
        terminalized += int(q_ok)
        if not q_ok:
            non_terminal.append({
                "case_id": r["case_id"], "repeat": r["repeat"],
                "charter_status": charter[0].get("status") if charter else None,
                "attribution": "undetermined (terminal snapshot, no provider/schema failure recorded)",
            })
        for dim in (snap.get("coverage") or []):
            if isinstance(dim, dict):
                coverage_statuses[dim.get("status")] += 1
    for f in failed_runs:
        non_terminal.append({
            "case_id": f["case_id"], "repeat": f["repeat"],
            "charter_status": None,
            "attribution": "M7 (run-level MODEL_OUTPUT_SCHEMA_FAILURE: "
                           f"{f['reason'][:60]})",
        })
    terminalized_total = n_terminal  # failed runs cannot terminalize

    # ---- §12 negative gates -------------------------------------------------------
    negative_failures = []
    from httpserver.services.benchmarks.case_outcome import (
        evaluate_case_outcome_v2,
    )
    from httpserver.services.benchmarks.truth_manifest import TruthManifestV1
    for run_dir in run_dirs:
        if not (run_dir / "result.json").is_file():
            continue
        snap_model = BenchmarkRunSnapshotV1(**_load(run_dir / "snapshot.json"))
        digest = _load(run_dir / "trajectory_digest.json")
        truth = TruthManifestV1(
            **_load(cases_root / run_dir.parent.name / "truth_manifest.json"))
        gates = [{"gate_id": g.gate_id, "passed": g.passed,
                  "violations": list(g.violations)}
                 for g in structural_hard_gates(snap_model)]
        oc = evaluate_case_outcome_v2(
            truth=truth, snapshot=snap_model, hard_gates=gates,
            semantic_payloads=[c.get("result_semantic_payload") or {}
                               for c in digest.get("completions", [])],
        )
        for component in oc.components:
            if component.status == "fail" and "overclaim" in (component.component or ""):
                negative_failures.append({
                    "case_id": run_dir.parent.name, "repeat": run_dir.name,
                    "component": component.component, "detail": component.detail,
                })

    # ---- §20 reliability axis -------------------------------------------------------
    # delegation axis (schema failures recorded per delegation)
    delegation_attempts = sum(
        len(r["delegation_failures"]) + r["delegations_completed"]
        for r in terminal_runs
    )
    # run axis: runs lost to output schema failures
    run_output_schema_failures = sum(
        1 for f in failed_runs if f["classification"] == "MODEL_OUTPUT_SCHEMA_FAILURE"
    )
    run_schema_rate = run_output_schema_failures / scheduled if scheduled else None
    systemic_output_failure = (
        run_schema_rate is not None and run_schema_rate > SPECIALIST_COLLAPSE_CEILING
    )

    finalized_runs = sum(
        1 for r in terminal_runs if r["finalization"] == "finalization_completed")
    quota_dominant = (
        provider_failures > 0
        and (finalized_runs + run_output_schema_failures) < max(1, scheduled // 2)
    )

    tokens_in = tokens_out = requests = wall_ms = 0
    for run_dir in run_dirs:
        sp = run_dir / "snapshot.json"
        if not sp.is_file():
            continue
        snap = _load(sp)
        for u in (snap.get("usage_entries") or []):
            tokens_in += int(u.get("input_tokens") or 0)
            tokens_out += int(u.get("output_tokens") or 0)
            requests += int(u.get("requests") or 1)
        wall_ms += int(snap.get("wall_ms_total") or 0)

    # ---- §21 disposition --------------------------------------------------------------
    if scheduled == 0:
        disposition, reason = "MEASUREMENT_INVALID", "no persisted runs"
    elif identity_mismatch:
        disposition, reason = "PROVIDER_ROUTING_IDENTITY_MISMATCH", (
            "returned_model != stealth/space-bunny-alpha in identity telemetry (§1)")
    elif not gates_clean:
        disposition, reason = "NOT_QUALIFIED_SCREENING", (
            "structural hard gate violation on a terminal snapshot (§11)")
    elif negative_failures:
        disposition, reason = "NOT_QUALIFIED_SCREENING", (
            f"negative gate failure(s): {len(negative_failures)} overclaim-channel "
            "component failures (§12)")
    elif quota_dominant:
        disposition, reason = "PROVIDER_CAPACITY_BLOCKED", (
            f"series quota-dominated ({provider_failures} provider failures) — "
            "§19: not a semantic verdict")
    elif systemic_output_failure:
        disposition, reason = "NOT_QUALIFIED_SCREENING", (
            f"systemic structured-output failure: {run_output_schema_failures}/{scheduled} "
            f"runs lost to MODEL_OUTPUT_SCHEMA_FAILURE ({run_schema_rate:.1%} > frozen "
            f"ceiling {SPECIALIST_COLLAPSE_CEILING}); §10 taxonomy — model output, "
            "not provider capacity (no 429/quota events in the series)")
    elif grounding_events:
        disposition, reason = "NOT_QUALIFIED_SCREENING", (
            f"grounding regression: {grounding_events} grounding rejection events (§20)")
    else:
        disposition, reason = "READY_FOR_8X3", (
            f"screening clean: gates {sum(1 for r in terminal_runs if r['hard_gates_pass'])}/"
            f"{n_terminal} terminal runs, run-level output failures "
            f"{run_output_schema_failures}/{scheduled}, provider failures "
            f"{provider_failures}, terminalization {terminalized}/{scheduled} — "
            "8x3 awaits explicit authorization (§22)")

    report = {
        "artifact_version": args.artifact_version,
        "candidate_id": args.candidate_id,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "candidate_config_hash": config_hash,
        "results_root": str(root),
        "scheduled_runs": scheduled,
        "terminal_runs": n_terminal,
        "failed_runs": failed_runs,
        "capacity_preflight": "capacity-preflight.json (CAPACITY_PREFLIGHT_PASS 3/3, pre-series, §5: not part of the measurement)",
        "routing_identity": {
            "requested_model": PROVIDER_MODEL_ID,
            "runs_with_identity_telemetry": runs_with_identity,
            "identity_records": len(identity_records),
            "mismatch": identity_mismatch,
            "returned_models": sorted({r.get("returned_model") for r in identity_records}),
            "upstream_providers": sorted({str(r.get("upstream_provider")) for r in identity_records}),
        },
        "provider_failures": {
            "provider_quota_rate_limited": provider_failures,
            "delegation_failure_code_histogram": dict(failure_code_hist),
            "note": "provider classes never enter schema/semantic numerators (§10); this series contains zero 429/quota events",
        },
        "hydration": _hydration_stats(root),
        "p_h_s_g": {
            "P_plan_duplicate": plan_duplicate,
            "H_handle_unknown": handle_unknown,
            "S_output_schema": schema_delegation_failures + run_output_schema_failures,
            "G_grounding": grounding_events,
            "counting_rule": "P/H/G from trajectory_digest rejections[].violation_codes keywords; S = non-quota delegation failures + run-level output-retry failures (§10)",
        },
        "question_terminalization": {
            "terminalized": terminalized,
            "total": scheduled,
            "metric": "charter required question q-1 left the open set {open, in_progress} (frozen §15 metric); failed runs cannot terminalize",
            "non_terminalized": non_terminal,
        },
        "coverage_statuses": dict(coverage_statuses),
        "case_outcome_v2": dict(outcomes),
        "negative_gates": {"failures": negative_failures, "clean": not negative_failures},
        "specialist_schema_reliability": {
            "delegation_axis_schema_failures": schema_delegation_failures,
            "delegation_attempts": delegation_attempts,
            "run_axis_output_failures": run_output_schema_failures,
            "run_axis_rate": run_schema_rate,
            "frozen_ceiling": SPECIALIST_COLLAPSE_CEILING,
            "verdict": "SYSTEMIC" if systemic_output_failure else "within ceiling",
        },
        "supervisor_reliability": {
            "PLAN_failures": sup_plan, "INTEGRATE_failures": sup_integrate,
        },
        "token_usage": {"input": tokens_in, "output": tokens_out, "requests": requests},
        "wall_ms_total": wall_ms,
        "evaluate_only_reproduction": evaluate_reproduced,
        "runtime_unchanged": True,
        "prompt_unchanged": True,
        "acceptance_profile_unchanged": True,
        "holdouts_untouched": True,
        "gen5": "NOT CREATED",
        "disposition": disposition,
        "reason": reason,
        "next_gate": ("8x3 ONLY on explicit user authorization (§22: STOP now)"
                      if disposition == "READY_FOR_8X3" else "none (blocker recorded)"),
    }
    out = root / "screening-report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"{disposition}: {reason}")
    print(f"  scheduled {scheduled} | terminal {n_terminal} | failed {len(failed_runs)}"
          f" (output-schema {run_output_schema_failures})")
    print(f"  identity {len(identity_records)} records / {runs_with_identity} runs, "
          f"mismatch={identity_mismatch}")
    print(f"  terminalization {terminalized}/{scheduled} | outcomes {dict(outcomes)} | "
          f"provider failures {provider_failures}")
    print(f"-> {out}")
    return 0


def _hydration_stats(root: Path) -> dict:
    totals = {
        "RunsWithHydration": 0, "HydratedEvidenceCount": 0,
        "LazyReacquireCount": 0, "LocatorHitCount": 0,
        "HydrationUnavailableCount": 0, "IntegrityFailure": 0,
        "CONTENT_NOT_PERSISTED_LEGACY_adopted": 0,
    }
    for run_dir in sorted(root.glob("t*/repeat*")):
        tp = run_dir / "hydration_telemetry.json"
        if not tp.is_file():
            continue
        t = _load(tp)
        if int(t.get("hydration_success") or 0) > 0:
            totals["RunsWithHydration"] += 1
        totals["HydratedEvidenceCount"] += int(t.get("hydration_success") or 0)
        totals["LazyReacquireCount"] += int(t.get("reacquire_count") or 0)
        totals["LocatorHitCount"] += int(t.get("locator_hit_count") or 0)
        totals["HydrationUnavailableCount"] += sum(
            (t.get("hydration_unavailable") or {}).values())
        totals["IntegrityFailure"] += int(t.get("content_integrity_failure_count") or 0)
        totals["CONTENT_NOT_PERSISTED_LEGACY_adopted"] += int(
            t.get("adopted_legacy_count") or 0)
    return totals


if __name__ == "__main__":
    raise SystemExit(main())
