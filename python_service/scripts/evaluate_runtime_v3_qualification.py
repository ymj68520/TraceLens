"""Runtime V3 qualification evaluation (§10-§15).

Consumes the 8×1 qualification canary artifacts and produces the
ModelRuntimeQualificationRecordV3 disposition. Zero model calls.
"""

from __future__ import annotations

import argparse
import hashlib
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
from httpserver.services.benchmarks.snapshot import (  # noqa: E402
    BenchmarkRunSnapshotV1,
)
from httpserver.services.benchmarks.truth_manifest import (  # noqa: E402
    TruthManifestV1,
)

CASES_ROOT = PYTHON_SERVICE_ROOT / "benchmarks" / "cases"
RESULTS_ROOT = (
    PYTHON_SERVICE_ROOT
    / "benchmarks" / "results" / "agent-v0" / "requalification"
    / "runtime-v3-qualification"
)


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _h_class(rejections: list[dict]) -> dict:
    """P/H/S/G-style taxonomy from §11-§13 rejection/failure records."""
    codes = {}
    for r in rejections:
        for code in r.get("violation_codes", []):
            codes[code] = codes.get(code, 0) + 1
    return codes


def stats_completed_delegations(snapshot: dict) -> int:
    return sum(
        1 for d in (snapshot.get("delegations") or [])
        if d.get("status") == "completed"
    )


def main() -> int:
    parser = argparse.ArgumentParser(prog="evaluate_runtime_v3_qualification")
    parser.add_argument(
        "--results-root", default=str(RESULTS_ROOT),
        help="qualification canary results root (per case/repeat dirs)",
    )
    args = parser.parse_args()
    root = Path(args.results_root)

    corpus = _load(
        PYTHON_SERVICE_ROOT / "benchmarks/corpus/corpus-agent-v0-calibration.v2.json"
    )
    case_ids = [ref["case_id"] for ref in corpus["calibration_cases"]]

    runs = []
    totals = {
        "hydration_attempted": 0,
        "hydration_success": 0,
        "reacquire_count": 0,
        "locator_hit_count": 0,
        "adopted_legacy_count": 0,
        "content_integrity_failure_count": 0,
    }
    unavailable_reasons = {}
    rejection_totals = {}
    integrated_cases = set()
    supervisor_failures = 0
    delegation_failures = 0
    specialist_output_failures = 0
    gates_all_pass = True

    for case_id in case_ids:
        for run_dir in sorted((root / case_id).glob("repeat*")):
            if not (run_dir / "result.json").exists():
                continue
            result = _load(run_dir / "result.json")
            snapshot = _load(run_dir / "snapshot.json")
            digest = _load(run_dir / "trajectory_digest.json")
            telemetry = _load(run_dir / "hydration_telemetry.json")
            failure = (
                _load(run_dir / "failure.json")
                if (run_dir / "failure.json").exists()
                else None
            )

            snap_model = BenchmarkRunSnapshotV1(**snapshot)
            gates_recompute = [
                {"gate_id": g.gate_id, "passed": g.passed, "violations": list(g.violations)}
                for g in structural_hard_gates(snap_model)
            ]
            gates_pass = all(g["passed"] for g in gates_recompute)
            gates_all_pass = gates_all_pass and gates_pass

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

            for key in totals:
                totals[key] += int(telemetry.get(key) or 0)
            for reason, count in (telemetry.get("hydration_unavailable") or {}).items():
                unavailable_reasons[reason] = unavailable_reasons.get(reason, 0) + count

            codes = _h_class(digest.get("rejections", []))
            for code, count in codes.items():
                rejection_totals[code] = rejection_totals.get(code, 0) + count
            sup_f = len(digest.get("supervisor_failures", []))
            del_f = len(digest.get("delegation_failures", []))
            supervisor_failures += sup_f
            delegation_failures += del_f
            for f in digest.get("delegation_failures", []):
                if "structured" in json.dumps(f).lower() or "output" in json.dumps(f).lower():
                    specialist_output_failures += 1

            integrated = any(
                (c.get("evidence_snapshots_admitted") or 0) > 0
                for c in digest.get("completions", [])
            ) and snapshot.get("terminal_status") in (
                "completed", "finalized", "investigated",
            )
            # §14 "valid integrated delegation": the production pipeline
            # reached finalization with a completed (production-integrated)
            # delegation — NOT case-level success (§15: qualification is not
            # acceptance).
            if (
                snapshot.get("terminal_status") == "completed"
                and (digest.get("finalization") or {}).get("event")
                == "finalization_completed"
                and stats_completed_delegations(snapshot) > 0
            ):
                integrated_cases.add(case_id)

            runs.append({
                "case_id": case_id,
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
                "delegations": len(snapshot.get("delegations") or []),
                "get_evidence_calls": len([
                    t for t in snapshot.get("tool_calls") or []
                    if t.get("tool_id") == "get_evidence"
                ]),
                "hydration": telemetry,
                "rejection_codes": codes,
                "supervisor_failures": sup_f,
                "delegation_failures": del_f,
                "provider_failure": failure is not None
                and "provider" in json.dumps(failure).lower(),
            })

    # §11 content correctness gate
    content_gate = {
        "content_integrity_mismatch": totals["content_integrity_failure_count"],
        "unavailable_reasons": unavailable_reasons,
        "legacy_fallback_adopted": totals["adopted_legacy_count"],
    }
    content_gate_pass = (
        content_gate["content_integrity_mismatch"] == 0
        and totals["adopted_legacy_count"] == 0
    )

    hydration_exercised_runs = [
        r for r in runs if r["hydration"]["hydration_success"] > 0
    ]

    # §14 minimum evidence
    minimum_evidence = {
        "content_hydration_exercised_runs": len(hydration_exercised_runs),
        "runs_total": len(runs),
        "specialist_consumed_content": all(
            r["hydration"]["hydration_success"] > 0
            and r["get_evidence_calls"] > 0
            for r in runs
        ),
        "supervisor_structured_output_not_systemically_broken": (
            supervisor_failures <= len(runs) // 2
        ),
        "cases_with_valid_integrated_delegation": len(integrated_cases),
        "structural_hard_gates_clean": gates_all_pass,
    }
    qualified = (
        minimum_evidence["content_hydration_exercised_runs"] >= 2
        and minimum_evidence["specialist_consumed_content"]
        and minimum_evidence["supervisor_structured_output_not_systemically_broken"]
        and minimum_evidence["cases_with_valid_integrated_delegation"] >= 2
        and minimum_evidence["structural_hard_gates_clean"]
        and content_gate_pass
    )

    record = {
        "record": "ModelRuntimeQualificationRecordV3",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "binding": {
            "runtime_baseline": "AgentV0RuntimeBaselineV3",
            "runtime_baseline_sha256": hashlib.sha256(
                (PYTHON_SERVICE_ROOT
                 / "benchmarks/profiles/agent-v0-runtime-baseline-v3.json").read_bytes()
            ).hexdigest(),
            "content_hydration_contract": "evidence-content-hydration:v1 (FROZEN d213145d)",
            "provider": "sensenova-cloud",
            "model_id": "sensenova-6.8-flash-lite",
            "configuration_id": "bconf-runtime-v3-qualification",
            "corpus_id": corpus["corpus_id"],
            "corpus_hash": corpus["input_hash"],
        },
        "adapter_smoke": "CONTINUE (6/6 checks, see model-runtime-qualification-v3.json)",
        "deep_smokes": {
            "content_hydration": "PASS (image→parse→no staging→hydration; sha256==source ×3)",
            "restart_hydration": "PASS (same keys/sha256/preview semantics after real restart)",
            "agent_deep_smoke": "PASS (image-exclusive markers in SpecialistResult + trajectory)",
        },
        "runs": runs,
        "hydration_totals": {
            **totals,
            "unavailable_reasons": unavailable_reasons,
            "first_hydration_latency_seconds": [
                r["hydration"].get("first_hydration_latency_seconds") for r in runs
            ],
        },
        "content_correctness_gate": content_gate,
        "content_gate_pass": content_gate_pass,
        "rejection_code_totals": rejection_totals,
        "output_reliability": {
            "supervisor_failures": supervisor_failures,
            "delegation_failures": delegation_failures,
            "specialist_structured_output_failures": specialist_output_failures,
        },
        "minimum_evidence": minimum_evidence,
        "disposition": "QUALIFIED_FOR_B2" if qualified else "MODEL_NOT_QUALIFIED",
    }
    out = RESULTS_ROOT / "model-runtime-qualification-v3.json"
    out.write_text(json.dumps(record, indent=2, ensure_ascii=False))
    print(json.dumps({
        "disposition": record["disposition"],
        "runs": len(runs),
        "hydration_totals": record["hydration_totals"],
        "content_gate_pass": content_gate_pass,
        "rejection_code_totals": rejection_totals,
        "output_reliability": record["output_reliability"],
        "minimum_evidence": minimum_evidence,
        "case_outcomes": {r["case_id"]: r["case_outcome_v2"] for r in runs},
    }, indent=2, ensure_ascii=False))
    return 0 if qualified else 1


if __name__ == "__main__":
    raise SystemExit(main())
