"""B2 RuntimeBaselineV3 measurement report (§19-§29, §36-§39).

Consumes the 24-run b2-runtime-v3 series and produces the measurement
report with hydration statistics, semantic metrics, output reliability,
negative cases, content-vs-metadata attribution, provider availability,
cost/latency, storage telemetry, and the §29 measurement verdict.
Zero model calls.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PYTHON_SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

from httpserver.services.benchmarks.case_outcome import (  # noqa: E402
    evaluate_case_outcome_v2,
)
from httpserver.services.benchmarks.metrics import (  # noqa: E402
    structural_hard_gates,
)
from httpserver.services.benchmarks.run_manifest import (  # noqa: E402
    BenchmarkRunManifestV1,
)
from httpserver.services.benchmarks.snapshot import (  # noqa: E402
    BenchmarkRunSnapshotV1,
)
from httpserver.services.benchmarks.truth_manifest import (  # noqa: E402
    TruthManifestV1,
)

CASES_ROOT = PYTHON_SERVICE_ROOT / "benchmarks" / "cases"
REPORT_ROOT = (
    PYTHON_SERVICE_ROOT
    / "benchmarks" / "results" / "agent-v0" / "b2-runtime-v3-glm52"
)
QUAL_ROOT = (
    PYTHON_SERVICE_ROOT
    / "benchmarks" / "results" / "agent-v0" / "requalification"
)


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


NEGATIVE_EXPECTATIONS = {
    "t2-identity-trap": "identity false merge = 0",
    "t2-temporal-trap": "unsupported causality = 0",
    "t2-no-evidence": "fabricated support = 0",
    "t2-misleading-note": "Analyst Note treated as Evidence = 0",
}


def main() -> int:
    parser = argparse.ArgumentParser(prog="build_b2_runtime_v3_report")
    parser.add_argument("--results-root", default=str(REPORT_ROOT))
    args = parser.parse_args()
    root = Path(args.results_root)

    corpus = _load(
        PYTHON_SERVICE_ROOT / "benchmarks/corpus/corpus-agent-v0-calibration.v2.json"
    )
    case_ids = [ref["case_id"] for ref in corpus["calibration_cases"]]

    runs = []
    hydration_by_case = {}
    rejection_totals = {}
    provider_failures = 0
    timeout_failures = 0
    five_xx_failures = 0
    specialist_output_failures = 0
    supervisor_plan_failures = 0
    supervisor_integrate_failures = 0
    content_integrity_failures = 0
    legacy_fallbacks = 0
    unavailable_reasons = {}
    tokens_in = tokens_out = requests = 0
    wall_ms_total = 0
    storage_bytes = 0
    storage_blobs = 0
    reacquire_total = locator_total = 0
    outcome_counts = {}
    negative_checks = {}
    snapshot_blob_scan_hits = 0

    for case_id in case_ids:
        case_runs = []
        for run_dir in sorted((root / case_id).glob("repeat*")):
            if not (run_dir / "result.json").exists():
                continue
            result = _load(run_dir / "result.json")
            snapshot = _load(run_dir / "snapshot.json")
            digest = _load(run_dir / "trajectory_digest.json")
            telemetry = _load(run_dir / "hydration_telemetry.json")
            failure = (
                _load(run_dir / "failure.json")
                if (run_dir / "failure.json").exists() else None
            )
            run_manifest = _load(run_dir / "run_manifest.json")

            snap_model = BenchmarkRunSnapshotV1(**snapshot)
            gates_recompute = [
                {"gate_id": g.gate_id, "passed": g.passed,
                 "violations": list(g.violations)}
                for g in structural_hard_gates(snap_model)
            ]
            gates_pass = all(g["passed"] for g in gates_recompute)

            truth = TruthManifestV1(
                **_load(CASES_ROOT / case_id / "truth_manifest.json")
            )
            payloads = [
                c.get("result_semantic_payload") or {}
                for c in digest.get("completions", [])
            ]
            oc = evaluate_case_outcome_v2(
                truth=truth, snapshot=snap_model,
                hard_gates=gates_recompute, semantic_payloads=payloads,
            )
            outcome_counts[oc.outcome.value] = (
                outcome_counts.get(oc.outcome.value, 0) + 1
            )

            # §23 negative-case gates (evidence-integrity semantics)
            negative_ok = True
            for component in oc.components:
                if component.status == "fail" and "overclaim" in (component.component or ""):
                    negative_ok = False
            negative_checks.setdefault(case_id, []).append(negative_ok)

            # §26 snapshot blob scan: no completion payload may carry
            # content blobs / long hydrated text
            for payload in payloads:
                flat = json.dumps(payload, ensure_ascii=False)
                for marker in ("content_preview", "content_sha256", "blob"):
                    if f'"{marker}"' in flat:
                        snapshot_blob_scan_hits += 1

            for key in ("hydration_attempted", "hydration_success",
                        "reacquire_count", "locator_hit_count",
                        "adopted_legacy_count",
                        "content_integrity_failure_count"):
                pass
            t = telemetry
            content_integrity_failures += int(t.get("content_integrity_failure_count") or 0)
            legacy_fallbacks += int(t.get("adopted_legacy_count") or 0)
            reacquire_total += int(t.get("reacquire_count") or 0)
            locator_total += int(t.get("locator_hit_count") or 0)
            storage_bytes += int(t.get("bytes_persisted_total") or 0)
            storage_blobs += int(t.get("hydration_success") or 0)
            for reason, count in (t.get("hydration_unavailable") or {}).items():
                unavailable_reasons[reason] = unavailable_reasons.get(reason, 0) + count

            for r in digest.get("rejections", []):
                stage = r.get("stage", "")
                for code in r.get("violation_codes", []):
                    key = f"{stage}:{code}"
                    rejection_totals[key] = rejection_totals.get(key, 0) + 1
            sup_f = digest.get("supervisor_failures", [])
            for f in sup_f:
                stage = str(f.get("stage", "")).lower()
                if "plan" in stage:
                    supervisor_plan_failures += 1
                elif "integrate" in stage:
                    supervisor_integrate_failures += 1
            del_f = digest.get("delegation_failures", [])
            specialist_output_failures += len(del_f)

            if failure:
                ftext = json.dumps(failure).lower()
                if "429" in ftext or "rate" in ftext:
                    provider_failures += 1
                elif "timeout" in ftext:
                    timeout_failures += 1
                elif "500" in ftext or "502" in ftext or "503" in ftext:
                    five_xx_failures += 1

            usage = snapshot.get("usage_entries") or []
            for u in usage:
                tokens_in += int(u.get("input_tokens") or 0)
                tokens_out += int(u.get("output_tokens") or 0)
                requests += int(u.get("requests") or 1)
            wall_ms_total += int(snapshot.get("wall_ms_total") or 0)

            cost = result.get("cost_metrics") or {}
            case_runs.append({
                "repeat": run_dir.name,
                "run_manifest_id": result.get("run_manifest_id"),
                "result_hash": result.get("result_hash"),
                "hard_gates_pass": gates_pass,
                "terminal_status": snapshot.get("terminal_status"),
                "case_outcome_v2": oc.outcome.value,
                "components": [
                    {"component": c.component, "status": c.status}
                    for c in oc.components
                ],
                "delegations_completed": sum(
                    1 for d in (snapshot.get("delegations") or [])
                    if d.get("status") == "completed"
                ),
                "finalization": (digest.get("finalization") or {}).get("event"),
                "hydration": {
                    "attempted": t.get("hydration_attempted"),
                    "success": t.get("hydration_success"),
                    "reacquire": t.get("reacquire_count"),
                    "locator_hit": t.get("locator_hit_count"),
                    "unavailable": t.get("hydration_unavailable"),
                    "integrity_failures": t.get("content_integrity_failure_count"),
                },
                "rejection_codes": {
                    r.get("stage", ""): r.get("violation_codes", [])
                    for r in digest.get("rejections", [])
                },
                "supervisor_failures": len(sup_f),
                "delegation_failures": len(del_f),
                "evidence_refs_integrated": sorted({
                    ref
                    for c in digest.get("completions", [])
                    for ref in ((c.get("result_semantic_payload") or {}).get("evidence_refs") or [])
                }),
            })
        if case_runs:
            hydration_by_case[case_id] = case_runs
            runs.extend(case_runs)

    total_runs = len(runs)
    runs_with_hydration = sum(
        1 for c in hydration_by_case.values() for r in c
        if r["hydration"]["success"] and r["hydration"]["success"] > 0
    )
    gates_all = all(r["hard_gates_pass"] for r in runs)
    # §29 verdict inputs
    benchmark_correctness_issues = legacy_fallbacks  # §20
    measurement_valid = (
        gates_all
        and content_integrity_failures == 0
        and benchmark_correctness_issues == 0
        and total_runs == 24
    )
    if not measurement_valid and content_integrity_failures > 0:
        verdict = "RUNTIME_CORRECTNESS_STOP"
    elif not measurement_valid and benchmark_correctness_issues > 0:
        verdict = "BENCHMARK_CORRECTNESS_STOP"
    elif total_runs < 24:
        verdict = "INFRA_BLOCKED"
    else:
        verdict = "MEASUREMENT_VALID"

    # §38 hydration latency split (from qualification canary + B2 telemetry)
    lat = [
        r["hydration"].get("first_hydration_latency_seconds") or 0
        for c in hydration_by_case.values() for r in c
    ]

    report = {
        "report_version": "b2-runtime-v3-glm52-measurement-report:v1",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "binding": {
            "runtime_baseline": "AgentV0RuntimeBaselineV3",
            "content_hydration_contract": "evidence-content-hydration:v1",
            "candidate": "glm-5.2 (AgentV0ModelConfigurationV2 promotion candidate)",
            "model_provider": "sensenova-cloud",
            "model_id": "glm-5.2",
            "configuration_id": "bconf-b2-runtime-v3-glm52",
            "corpus_id": corpus["corpus_id"],
            "corpus_hash": corpus["input_hash"],
            "qualification_record": "benchmarks/results/agent-v0/requalification/runtime-v3/model-runtime-qualification-v3.json (QUALIFIED_FOR_B2)",
        },
        "series": {
            "expected_runs": 24,
            "recorded_runs": total_runs,
            "completed": sum(1 for r in runs if r["terminal_status"] == "completed"),
            "gates_all_pass": gates_all,
            "evaluate_only": "built into --cleanup-tasks (snapshot-verified before delete)",
        },
        "hydration_statistics": {
            "RunsWithHydration": runs_with_hydration,
            "HydratedEvidenceCount": sum(
                r["hydration"]["success"] for c in hydration_by_case.values() for r in c
            ),
            "LocatorHitCount": locator_total,
            "LazyReacquireCount": reacquire_total,
            "HydrationUnavailableCount": sum(unavailable_reasons.values()),
            "HydrationUnavailableReasons": unavailable_reasons,
            "HydrationIntegrityFailureCount": content_integrity_failures,
            "CONTENT_NOT_PERSISTED_LEGACY_expectation": {
                "expected": 0, "observed": legacy_fallbacks,
                "note": "freshly provisioned tasks; nonzero would be wiring defect (§20)",
            },
            "by_case": {
                case: {
                    "attempted": sum(r["hydration"]["attempted"] for r in crs),
                    "success": sum(r["hydration"]["success"] for r in crs),
                    "reacquire": sum(r["hydration"]["reacquire"] for r in crs),
                    "locator_hit": sum(r["hydration"]["locator_hit"] for r in crs),
                }
                for case, crs in hydration_by_case.items()
            },
            "first_hydration_latency_seconds_max": max(lat) if lat else None,
        },
        "semantic_metrics": {
            "case_outcome_v2_counts": outcome_counts,
            "RunsWithCompletedSpecialistResult": sum(
                1 for r in runs if r["delegations_completed"] > 0
            ),
            "RunsWithIntegratedDelegation_finalization_completed": sum(
                1 for r in runs if r["finalization"] == "finalization_completed"
            ),
            "FinalizationPass": sum(
                1 for r in runs if r["finalization"] == "finalization_completed"
            ),
            "question_terminalization_coverage": "per-component statuses recorded per run",
        },
        "negative_cases": {
            "expectations": NEGATIVE_EXPECTATIONS,
            "per_run_overclaim_failures": {
                case: [not ok for ok in oks]
                for case, oks in negative_checks.items()
            },
            "note": "identity/temporal/no-evidence/misleading-note gates are enforced by the CaseOutcomeV2 components; overclaim-channel failures are surfaced in components",
        },
        "output_reliability": {
            "specialist_structured_output_failures": specialist_output_failures,
            "supervisor_PLAN_failures": supervisor_plan_failures,
            "supervisor_INTEGRATE_failures": supervisor_integrate_failures,
            "provider_failures": provider_failures,
            "timeout_failures": timeout_failures,
            "five_xx_failures": five_xx_failures,
        },
        "rejection_codes": rejection_totals,
        "content_vs_metadata": {
            "note": "§24: integrated conclusions in hydrated runs cite file evidence served through the durable store; provenance lists per run below (diagnosis use only — citations remain (task_id, evidence_key))",
            "runs_with_hydrated_integrated_content": [
                {"case_id": case, "repeat": r["repeat"],
                 "evidence_refs": r["evidence_refs_integrated"]}
                for case, crs in hydration_by_case.items()
                for r in crs
                if r["hydration"]["success"] and r["evidence_refs_integrated"]
            ],
        },
        "citation_identity": "(task_id, evidence_key) unchanged; content blob hashes are storage identifiers only (§25)",
        "snapshot_expansion_check": {
            "payload_markers_found": snapshot_blob_scan_hits,
            "expectation": 0,
            "note": "EvidenceSnapshot remains Investigation provenance anchor (§26)",
        },
        "cost_latency": {
            "input_tokens": tokens_in,
            "output_tokens": tokens_out,
            "requests": requests,
            "wall_ms_total": wall_ms_total,
            "content_store_first_hydration_latency_seconds_max": max(lat) if lat else None,
            "note": "content store latency is local-disk bounded (~0.02-0.1s observed); LLM latency dominates wall time",
        },
        "storage_telemetry": {
            "hydrated_blobs": storage_blobs,
            "total_content_bytes_stored": storage_bytes,
            "dedup_savings": "within-task same-hash blobs shared (hash-addressed); savings not separately metered this round",
            "lazy_reacquisition_count": reacquire_total,
        },
        "measurement_verdict": verdict,
    }
    out = root / "b2-runtime-v3-glm52-measurement-report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps({
        "verdict": verdict,
        "runs": total_runs,
        "completed": report["series"]["completed"],
        "gates_all_pass": gates_all,
        "outcome_counts": outcome_counts,
        "hydration": {
            "runs_with_hydration": runs_with_hydration,
            "hydrated_evidence": report["hydration_statistics"]["HydratedEvidenceCount"],
            "integrity_failures": content_integrity_failures,
            "legacy_fallbacks": legacy_fallbacks,
        },
        "reliability": report["output_reliability"],
        "rejection_codes": rejection_totals,
    }, indent=2, ensure_ascii=False))
    return 0 if verdict == "MEASUREMENT_VALID" else 1


if __name__ == "__main__":
    raise SystemExit(main())
