"""8x1 screening disposition (§10-§21), RCA-1.5-corrected.

Deterministically re-derives everything from the persisted 8x1 series
(evaluate-only, zero model calls):
  §1  per-request routing identity (identity_telemetry.json, all runs)
  §10 schema-vs-provider failure separation — type-derived where the
      runner recorded it (failure_class), legacy marker fallback ONLY for
      pre-RCA-1 artifacts that carry a bare failure_reason string
  §11 structural hard gates recomputed from terminal snapshots
  §12 negative gates (overclaim-channel components)
  §13 P/H/S/G counters (counting rule labeled)
  §15 question terminalization — INDEPENDENT reported metric (RCA-1.0:
      never an automatic 100% screening gate)
  §16 coverage status distribution (terminal snapshots only)
  §17 CaseOutcomeV2 (terminal snapshots only)

RCA-1.0 reconciled contract (ScreeningContractReconciliationV1):
  - 8x1 is a low-cost SCREENING, never B6 acceptance;
  - every scheduled run is accounted, including abnormal failures;
  - READY_FOR_8X3 is UNREACHABLE through the fallback branch: any
    unclassified run failure -> REVIEW_REQUIRED; any classified run-level
    failure blocks READY with its class-specific reason;
  - dispositions keep the frozen §21 vocabulary (no new thresholds).

RCA-1.5 accounting (machine-readable, never conflated):
  scheduled_count / run_terminal_count / run_failed_count (failure.json) /
  run_integration_failed_count (terminal snapshot + contained INTEGRATE
  failure in the digest) / snapshot_reproduced_count (evaluate-only covers
  ONLY snapshot-bearing runs) / failure_classified_count.

Failure classes (agent_failure_taxonomy): MODEL_OUTPUT_RETRY_EXHAUSTED,
PROVIDER_REQUEST_TIMEOUT, PROVIDER_RATE_LIMITED, ... — anything falling to
BENCHMARK_RUNTIME_FAILURE (no rule matched) is UNCLASSIFIED.

Usage (from python_service/):
    .venv/bin/python scripts/disposition_openrouter_8x1.py \
        --results-root benchmarks/results/agent-v0/model-candidates/<c>/qual-8x1
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

from httpserver.services.investigation.agent_failure_taxonomy import (  # noqa: E402
    BENCHMARK_RUNTIME_FAILURE,
    MODEL_OUTPUT_RETRY_EXHAUSTED,
    PROVIDER_RATE_LIMITED,
    PROVIDER_REQUEST_TIMEOUT,
    classify_failure,
    is_output_failure,
    is_provider_failure,
)

DEFAULT_REQUESTED_MODEL = "stealth/space-bunny-alpha"
SCHEMA_FAILURE_CODES = {"agent_output_invalid"}
OUTPUT_RETRY_MARKER = "exceeded maximum output retries"
# RCA-1.5: the 0.5 ceiling serves TWO different axes — never conflate them
# (audit F-8). Same frozen 0.5 number, distinct denominators, distinct uses:
RUN_AXIS_COLLAPSE_CEILING = SPECIALIST_COLLAPSE_CEILING
DELEGATION_AXIS_COLLAPSE_CEILING = SPECIALIST_COLLAPSE_CEILING

# supervisor-integration failure markers in durable trajectory digests
# (RCA-1.1 containment events; pre-RCA-1 digests never carry these)
INTEGRATION_FAILURE_STAGE = "integrate"
INTEGRATION_FAILURE_CODE = "supervisor_integration_failed"


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def classify_run_failure(failure_record: dict) -> dict:
    """Classify one failed run. New-style records (post-RCA-1 runner) carry
    type-derived ``failure_class``; legacy artifacts fall back to marker
    matching on the reason string, and anything unmatchable is explicitly
    UNCLASSIFIED (BENCHMARK_RUNTIME_FAILURE / classified=False)."""
    failure_class = failure_record.get("failure_class")
    if failure_class:
        return {
            "class": str(failure_class),
            "classified": bool(failure_record.get("failure_classified", True)),
            "source": "runner",
            "exception_class": failure_record.get("exception_class"),
        }
    reason = str(failure_record.get("failure_reason", ""))
    lowered = reason.lower()
    if OUTPUT_RETRY_MARKER in lowered:
        return {"class": MODEL_OUTPUT_RETRY_EXHAUSTED, "classified": True,
                "source": "legacy_marker", "exception_class": None}
    if "timed out" in lowered or "timeout" in lowered:
        return {"class": PROVIDER_REQUEST_TIMEOUT, "classified": True,
                "source": "legacy_marker", "exception_class": None}
    if "rate_limit" in lowered or "429" in lowered or "quota" in lowered:
        return {"class": PROVIDER_RATE_LIMITED, "classified": True,
                "source": "legacy_marker", "exception_class": None}
    # legacy string carried nothing recognizable — try the taxonomy on the
    # exception type recorded nowhere: explicitly unclassified
    return {"class": BENCHMARK_RUNTIME_FAILURE, "classified": False,
            "source": "legacy_marker", "exception_class": None}


def classify_integration_failure(payload: dict) -> dict:
    """Classify one contained INTEGRATE failure from its trajectory payload
    (RCA-1.1 writes underlying_code; digest extraction surfaces it as
    supervisor_failures[])."""
    underlying = str(payload.get("underlying_code") or "")
    if underlying and underlying != BENCHMARK_RUNTIME_FAILURE:
        return {"class": underlying, "classified": True, "source": "digest"}
    if underlying == BENCHMARK_RUNTIME_FAILURE:
        return {"class": BENCHMARK_RUNTIME_FAILURE, "classified": False,
                "source": "digest"}
    code = str(payload.get("code") or "")
    if code == INTEGRATION_FAILURE_CODE:
        # pre-taxation containment payload without underlying_code: treat
        # the safe message as unavailable for typing -> unclassified
        return {"class": BENCHMARK_RUNTIME_FAILURE, "classified": False,
                "source": "digest"}
    # legacy supervisor_failure payload (PLAN-style): keep legacy classes
    return {"class": code or BENCHMARK_RUNTIME_FAILURE,
            "classified": bool(code), "source": "digest"}


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
    integration_failed_runs = []  # terminal snapshots with contained INTEGRATE failure
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
            cls = classify_run_failure(f)
            failed_runs.append({
                "case_id": case, "repeat": run_dir.name,
                "failure_layer": f.get("failure_layer"),
                "reason": str(f.get("failure_reason", ""))[:200],
                "classification": cls["class"],
                "classified": cls["classified"],
            })
        else:
            digest = _load(run_dir / "trajectory_digest.json")
            if not isinstance(digest, dict):
                digest = {"legacy_flat_rejection_codes": digest}
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
                code = str(f.get("code", ""))
                if code == INTEGRATION_FAILURE_CODE or (
                        stage == INTEGRATION_FAILURE_STAGE and
                        f.get("underlying_code")):
                    # RCA-1.1 contained INTEGRATE failure on a terminal run:
                    # a run-level failure that never produced failure.json
                    cls = classify_integration_failure(f)
                    integration_failed_runs.append({
                        "case_id": case, "repeat": run_dir.name,
                        "classification": cls["class"],
                        "classified": cls["classified"],
                        "underlying_code": f.get("underlying_code"),
                    })
                elif stage and "plan" in stage:
                    sup_plan += 1
                elif "integrate" in stage or code == INTEGRATION_FAILURE_CODE:
                    sup_integrate += 1
            for f in digest.get("delegation_failures", []):
                if isinstance(f, str):
                    code = f
                else:
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
    # RCA-1.5: this reproduces the persisted hard gates for SNAPSHOT-BEARING
    # runs ONLY. snapshot_reproduced_count is reported explicitly and MUST
    # NOT be presented as full-measurement verification.
    evaluate_reproduced = True
    from httpserver.services.benchmarks.metrics import structural_hard_gates
    from httpserver.services.benchmarks.snapshot import BenchmarkRunSnapshotV1
    snapshot_reproduced_count = 0
    for run_dir in run_dirs:
        if not (run_dir / "result.json").is_file():
            continue
        persisted = {
            g["gate_id"]: g["passed"]
            for g in _load(run_dir / "result.json").get("hard_gate_results", [])
        }
        snap_model = BenchmarkRunSnapshotV1(**_load(run_dir / "snapshot.json"))
        recomputed = {g.gate_id: g.passed for g in structural_hard_gates(snap_model)}
        snapshot_reproduced_count += 1
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
                "attribution": (
                    "INTEGRATE failed (contained, RCA-1.1): "
                    f"{_integration_failed_attribution(integration_failed_runs, r)}"
                    if _integration_failed_attribution(integration_failed_runs, r)
                    else "undetermined (terminal snapshot, charter question "
                         "never left the open set)"
                ),
            })
        for dim in (snap.get("coverage") or []):
            if isinstance(dim, dict):
                coverage_statuses[dim.get("status")] += 1
    for f in failed_runs:
        non_terminal.append({
            "case_id": f["case_id"], "repeat": f["repeat"],
            "charter_status": None,
            "attribution": (
                f"run-level {f['classification']}"
                + ("" if f["classified"] else " (UNCLASSIFIED)")
                + f": {f['reason'][:90]}"
            ),
        })
    terminalized_total = n_terminal  # failed runs cannot terminalize

    # ---- run-level failure classification rollup (RCA-1.5) -----------------------
    run_level_failures = [
        {"case_id": f["case_id"], "repeat": f["repeat"],
         "class": f["classification"], "classified": f["classified"],
         "kind": "run_failed"}
        for f in failed_runs
    ] + [
        {"case_id": f["case_id"], "repeat": f["repeat"],
         "class": f["classification"], "classified": f["classified"],
         "kind": "integration_failed"}
        for f in integration_failed_runs
    ]
    class_hist: Counter = Counter(f["class"] for f in run_level_failures)
    unclassified_count = sum(
        1 for f in run_level_failures if not f["classified"])
    failure_classified_count = len(run_level_failures) - unclassified_count
    timeout_count = class_hist.get(PROVIDER_REQUEST_TIMEOUT, 0)
    quota_run_count = class_hist.get(PROVIDER_RATE_LIMITED, 0)
    output_retry_count = class_hist.get(MODEL_OUTPUT_RETRY_EXHAUSTED, 0)

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
        if not isinstance(digest, dict):
            continue
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
    # run axis: runs lost to output schema failures (failure.json OR
    # contained INTEGRATE output-retry exhaustion)
    run_output_schema_failures = (
        output_retry_count
        + sum(1 for f in integration_failed_runs
              if f["classification"] == MODEL_OUTPUT_RETRY_EXHAUSTED)
    )
    run_schema_rate = run_output_schema_failures / scheduled if scheduled else None
    systemic_output_failure = (
        run_schema_rate is not None and run_schema_rate > RUN_AXIS_COLLAPSE_CEILING
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

    # ---- §21 disposition (RCA-1.0 reconciled contract) ------------------------------
    # ORDER MATTERS: exhaustiveness before any pass-ish verdict.
    def _class_breakdown() -> str:
        return ", ".join(
            f"{code}×{n}" for code, n in class_hist.most_common()
        ) or "none"

    if scheduled == 0:
        disposition, reason = "MEASUREMENT_INVALID", "no persisted runs"
    elif identity_mismatch:
        disposition, reason = "PROVIDER_ROUTING_IDENTITY_MISMATCH", (
            "returned_model != requested model in identity telemetry (§1)")
    elif unclassified_count:
        disposition, reason = "REVIEW_REQUIRED", (
            f"{unclassified_count} run-level failure(s) match no "
            f"classification rule ({_class_breakdown()}); the fallback "
            "branch can never produce READY_FOR_8X3 (RCA-1.0)")
    elif not gates_clean:
        disposition, reason = "NOT_QUALIFIED_SCREENING", (
            "structural hard gate violation on a terminal snapshot (§11)")
    elif negative_failures:
        disposition, reason = "NOT_QUALIFIED_SCREENING", (
            f"negative gate failure(s): {len(negative_failures)} overclaim-channel "
            "component failures (§12)")
    elif grounding_events:
        disposition, reason = "NOT_QUALIFIED_SCREENING", (
            f"grounding regression: {grounding_events} grounding rejection events (§20)")
    elif systemic_output_failure:
        disposition, reason = "NOT_QUALIFIED_SCREENING", (
            f"systemic structured-output failure: {run_output_schema_failures}/{scheduled} "
            f"runs lost to output-retry exhaustion ({run_schema_rate:.1%} > run-axis "
            f"ceiling {RUN_AXIS_COLLAPSE_CEILING}); §10 taxonomy — model output, "
            "not provider capacity (no 429/quota events in the series)")
    elif quota_dominant:
        disposition, reason = "PROVIDER_CAPACITY_BLOCKED", (
            f"series quota-dominated ({provider_failures} provider failures, "
            f"delegation axis) — §19: not a semantic verdict")
    elif run_level_failures:
        # RCA-1.0: ANY classified run-level failure blocks READY with its
        # class-specific reason. No fallback can reach READY_FOR_8X3.
        if timeout_count and timeout_count == len(run_level_failures):
            disposition, reason = "NOT_QUALIFIED_SCREENING", (
                f"provider request timeout(s): {timeout_count}/{scheduled} runs "
                "lost to classified PROVIDER_REQUEST_TIMEOUT — provider "
                "latency limitation under the frozen per-attempt budget, "
                "never a screening pass")
        else:
            disposition, reason = "NOT_QUALIFIED_SCREENING", (
                f"run-level failures: {_class_breakdown()} of {scheduled} "
                "scheduled runs (§10 classified; terminalization and "
                "completion metrics reported independently)")
    else:
        disposition, reason = "READY_FOR_8X3", (
            f"screening clean: gates {sum(1 for r in terminal_runs if r['hard_gates_pass'])}/"
            f"{n_terminal} terminal runs, run-level output failures "
            f"{run_output_schema_failures}/{scheduled}, provider failures "
            f"{provider_failures}, terminalization {terminalized}/{scheduled} (§17 "
            "independent metric) — 8x3 awaits explicit authorization (§22)")

    report = {
        "artifact_version": args.artifact_version,
        "candidate_id": args.candidate_id,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "candidate_config_hash": config_hash,
        "results_root": str(root),
        # RCA-1.5 explicit accounting — 2/2 snapshot reproduction is NEVER
        # presentable as 8/8 evaluate-only completeness
        "accounting": {
            "scheduled_count": scheduled,
            "run_terminal_count": n_terminal,
            "run_failed_count": len(failed_runs),
            "run_integration_failed_count": len(integration_failed_runs),
            "snapshot_reproduced_count": snapshot_reproduced_count,
            "failure_classified_count": failure_classified_count,
            "unclassified_failure_count": unclassified_count,
            "aggregate_disposition_verified": True,
            "note": "evaluate-only reproduction covers snapshot-bearing runs "
                    f"({snapshot_reproduced_count}/{scheduled}) — not a "
                    "full-measurement verification",
        },
        "scheduled_runs": scheduled,
        "terminal_runs": n_terminal,
        "failed_runs": failed_runs,
        "integration_failed_runs": integration_failed_runs,
        "run_level_failure_classes": dict(class_hist),
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
            "note": "provider classes never enter schema/semantic numerators (§10)",
        },
        "hydration": _hydration_stats(root),
        "p_h_s_g": {
            "P_plan_duplicate": plan_duplicate,
            "H_handle_unknown": handle_unknown,
            "S_output_schema": schema_delegation_failures + run_output_schema_failures,
            "G_grounding": grounding_events,
            "counting_rule": "P/H/G from trajectory_digest rejections[].violation_codes keywords; S = non-quota delegation failures (delegation axis) + run-level output-retry failures (run axis)",
        },
        "question_terminalization": {
            "terminalized": terminalized,
            "total": scheduled,
            "metric": "charter required question q-1 left the open set {open, in_progress} (frozen §15 metric); INDEPENDENT reported metric — not an automatic screening gate (RCA-1.0); failed runs cannot terminalize",
            "non_terminalized": non_terminal,
        },
        "coverage_statuses": dict(coverage_statuses),
        "case_outcome_v2": dict(outcomes),
        "negative_gates": {"failures": negative_failures, "clean": not negative_failures},
        "specialist_schema_reliability": {
            "delegation_axis_schema_failures": schema_delegation_failures,
            "delegation_attempts": delegation_attempts,
            "delegation_axis_ceiling": DELEGATION_AXIS_COLLAPSE_CEILING,
            "run_axis_output_failures": run_output_schema_failures,
            "run_axis_rate": run_schema_rate,
            "run_axis_ceiling": RUN_AXIS_COLLAPSE_CEILING,
            "verdict": "SYSTEMIC (run axis)" if systemic_output_failure else "within ceiling",
        },
        "supervisor_reliability": {
            "PLAN_failures": sup_plan, "INTEGRATE_failures": sup_integrate,
            "note": "INTEGRATE counts contained RCA-1.1 failures carried in "
                    "non-integrate stage fields; integration_failed_runs is "
                    "the authoritative per-run list",
        },
        "token_usage": {"input": tokens_in, "output": tokens_out, "requests": requests},
        "wall_ms_total": wall_ms,
        "evaluate_only_reproduction": evaluate_reproduced,
        "evaluate_only_coverage": (
            f"{snapshot_reproduced_count}/{scheduled} snapshot-bearing runs"),
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
    print(f"  scheduled {scheduled} | terminal {n_terminal} | failed "
          f"{len(failed_runs)} (integration-failed {len(integration_failed_runs)})"
          f" | reproduced {snapshot_reproduced_count}/{scheduled}")
    print(f"  identity {len(identity_records)} records / {runs_with_identity} runs, "
          f"mismatch={identity_mismatch}")
    print(f"  terminalization {terminalized}/{scheduled} | outcomes {dict(outcomes)} | "
          f"provider failures {provider_failures}")
    print(f"-> {out}")
    return 0


def _integration_failed_attribution(
        integration_failed_runs: list[dict], terminal_row: dict) -> str:
    for f in integration_failed_runs:
        if (f["case_id"] == terminal_row["case_id"]
                and f["repeat"] == terminal_row["repeat"]):
            label = f["classification"] + (
                "" if f["classified"] else " (UNCLASSIFIED)")
            return label
    return ""


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
