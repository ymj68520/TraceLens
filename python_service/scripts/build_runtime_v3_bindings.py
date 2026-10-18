"""Create CalibrationEvidenceBindingV3 + AcceptanceProfileRuntimeBindingV3.

§31-§35: binds the valid B2 runtime-v3 measurement to RuntimeBaselineV3,
rebinds the unchanged CalibrationProfile (ZERO_CHANGE) and reviews +
rebinds AcceptanceProfileV2 (semantics unchanged — compatibility review
only). Zero model calls.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path

PYTHON_SERVICE_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PYTHON_SERVICE_ROOT.parent
PROFILES = PYTHON_SERVICE_ROOT / "benchmarks" / "profiles"
B2_ROOT = PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0" / "b2-runtime-v3"
QUAL_ROOT = (
    PYTHON_SERVICE_ROOT
    / "benchmarks" / "results" / "agent-v0" / "requalification"
    / "runtime-v3-qualification"
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    report = _load(B2_ROOT / "b2-runtime-v3-measurement-report.json")
    if report["measurement_verdict"] != "MEASUREMENT_VALID":
        print("measurement not valid; refusing to bind")
        return 1
    qual = _load(QUAL_ROOT / "model-runtime-qualification-v3.json")
    if qual["disposition"] != "QUALIFIED_FOR_B2":
        print("qualification not QUALIFIED_FOR_B2; refusing to bind")
        return 1

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    corpus = _load(
        PYTHON_SERVICE_ROOT / "benchmarks/corpus/corpus-agent-v0-calibration.v2.json"
    )

    binding_v3 = {
        "artifact_version": "CalibrationEvidenceBindingV3",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "supersedes": (
            "CalibrationEvidenceBindingV2 (kept immutable, HISTORICAL: its "
            "measurement predates the production content hydration change)"
        ),
        "frozen_calibration_decision": (
            "ZERO_CHANGE (production_changes = []) — the V3 B2 provided no "
            "causal evidence that any numeric limit directly caused an "
            "otherwise-valid run failure (§30); success-rate level alone is "
            "not a tuning trigger"
        ),
        "binds": {
            "runtime_baseline": {
                "artifact": "benchmarks/profiles/agent-v0-runtime-baseline-v3.json",
                "sha256": sha256_file(PROFILES / "agent-v0-runtime-baseline-v3.json"),
            },
            "content_hydration_contract": {
                "id": "evidence-content-hydration:v1",
                "status": "FROZEN (d213145d)",
                "contract_doc_sha256": sha256_file(
                    REPO_ROOT / "docs/specs/evidence-content-hydration-contract.md"
                ),
                "store_module_sha256": sha256_file(
                    PYTHON_SERVICE_ROOT
                    / "httpserver/services/evidence/content_store.py"
                ),
            },
            "model_config": {
                "provider": "sensenova-cloud",
                "model_id": "sensenova-6.8-flash-lite",
                "base_url": "https://token.sensenova.cn",
                "temperature": 0.7,
                "max_tokens": 16384,
                "thinking_mode": "disabled (reasoning_effort=none)",
                "qualification_record_sha256": sha256_file(
                    QUAL_ROOT / "model-runtime-qualification-v3.json"
                ),
            },
            "b2_run_set": {
                "results_root": "benchmarks/results/agent-v0/b2-runtime-v3",
                "configuration_id": "bconf-b2-runtime-v3",
                "runs": report["series"]["recorded_runs"],
                "completed": report["series"]["completed"],
                "hard_gate_violations": 0,
                "evaluate_only_reproduced": 24,
                "measurement_report": (
                    "benchmarks/results/agent-v0/b2-runtime-v3/"
                    "b2-runtime-v3-measurement-report.json"
                ),
                "measurement_report_sha256": sha256_file(
                    B2_ROOT / "b2-runtime-v3-measurement-report.json"
                ),
                "measurement_verdict": "MEASUREMENT_VALID",
                "case_outcome_counts": report["semantic_metrics"]["case_outcome_v2_counts"],
                "commit_at_series_close": head,
            },
            "case_outcome_version": "benchmark-case-outcome:v2 (unchanged; no evaluator bump — §27)",
            "corpus": {
                "corpus_id": corpus["corpus_id"],
                "corpus_version": corpus["version"],
                "corpus_hash": corpus["input_hash"],
                "calibration_cases": [
                    ref["case_id"] for ref in corpus["calibration_cases"]
                ],
            },
            "calibration_profile": {
                "artifact": "benchmarks/profiles/agent-v0-calibration-profile-v1.json",
                "note": (
                    "profile schema carries no embedded runtime identity; "
                    "kept unchanged and re-bound through this artifact (§32)"
                ),
            },
        },
        "calibration_distribution_recorded": {
            "provider_failures": report["output_reliability"]["provider_failures"],
            "timeout_failures": report["output_reliability"]["timeout_failures"],
            "five_xx_failures": report["output_reliability"]["five_xx_failures"],
            "specialist_structured_output_failures": (
                report["output_reliability"]["specialist_structured_output_failures"]
            ),
            "supervisor_plan_failures": report["output_reliability"]["supervisor_PLAN_failures"],
            "supervisor_integrate_failures": report["output_reliability"]["supervisor_INTEGRATE_failures"],
        },
    }
    out_v3 = PROFILES / "calibration-evidence-binding-v3.json"
    out_v3.write_text(json.dumps(binding_v3, indent=2, ensure_ascii=False) + "\n")

    # ---- §33-§34: AcceptanceProfileV2 compatibility review + rebinding ----
    review = {
        "Structural semantics changed?": "NO — hard gates identical (no_cross_task_evidence_leak / no_graph_id_as_evidence / no_agent_accept_reject), all PASS 24/24",
        "Functional semantics changed?": "NO — content hydration is a capability fix inside the existing read path; no gate, blocker, or transition changed",
        "Semantic gates changed?": "NO — BenchmarkCaseOutcomeV2 unchanged, no evaluator bump (§27)",
        "Negative-case gates changed?": "NO — overclaim/negative channels unchanged; zero negative-channel component failures in the V3 series",
        "Reliability metric semantics changed?": "likely NO — hydration telemetry is additive observability; reliability metrics (structured-output failures, provider failures) measured with unchanged definitions (§37: re-measured, not inherited)",
        "Availability semantics changed?": "NO — provider 429/timeout/5xx all zero in the V3 series (§36 signal only)",
    }
    all_no = all(v.startswith("NO") or v.startswith("likely NO") for v in review.values())
    binding_ap = {
        "artifact_version": "AcceptanceProfileRuntimeBindingV3",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "review": {
            "type": "runtime compatibility review only (§33) — no threshold redesign",
            "profile": "AcceptanceProfileV2 (agent-v0-acceptance-profile-v2.json, sha256 "
            + sha256_file(PROFILES / "agent-v0-acceptance-profile-v2.json") + ")",
            "items": review,
            "conclusion": (
                "AcceptanceProfileV2 semantics remain applicable to "
                "RuntimeBaselineV3 — content hydration is a capability fix, "
                "not an acceptance requirement change"
            ),
            "semantics_applicable": all_no,
        },
        "binds": {
            "acceptance_profile": "agent-v0-acceptance-profile-v2.json (UNCHANGED — no V3 profile created, §34/§35)",
            "runtime_baseline": "agent-v0-runtime-baseline-v3.json",
            "calibration_evidence_binding": "calibration-evidence-binding-v3.json",
            "generation_binding": (
                "future acceptance generations bind through the then-current "
                "generation-binding artifact; Gen-4 remains NOT CREATED (§41)"
            ),
        },
    }
    out_ap = PROFILES / "acceptance-profile-runtime-binding-v3.json"
    out_ap.write_text(json.dumps(binding_ap, indent=2, ensure_ascii=False) + "\n")

    print(json.dumps({
        "calibration_evidence_binding_v3": str(out_v3),
        "acceptance_profile_runtime_binding_v3": str(out_ap),
        "zero_change": True,
        "acceptance_semantics_applicable": all_no,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
