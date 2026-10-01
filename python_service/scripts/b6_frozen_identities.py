#!/usr/bin/env python3
"""B6 §1 frozen identities manifest — recorded BEFORE the first holdout
model call.  Nothing in this manifest may change for the whole of B6.

Run AFTER the pre-B6 infra commit and the passing preflight, BEFORE
scripts/run_b6_holdout.py issues the first model request.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PYTHON_SERVICE_ROOT = SCRIPT_PATH.parents[1]
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))
SCRIPTS_DIR = SCRIPT_PATH.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

REPO_ROOT = PYTHON_SERVICE_ROOT.parent
OUT_DIR = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0" / "b6-holdout"
)
OUT_FILE = OUT_DIR / "frozen-identities-v1.json"
CHARTER_FILE = PYTHON_SERVICE_ROOT / "benchmarks/profiles/b6-holdout-charter-v1.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, cwd=REPO_ROOT
    ).stdout.strip()


def main() -> int:
    from httpserver.services.investigation.agent_runtime import (
        canonical_state_json,
        state_hash_of,
    )

    charter = json.loads(CHARTER_FILE.read_text(encoding="utf-8"))
    corpus = json.loads(
        (
            PYTHON_SERVICE_ROOT
            / "benchmarks/corpus/corpus-agent-v0-calibration.v2.json"
        ).read_text(encoding="utf-8")
    )
    preflight = json.loads(
        (OUT_DIR / "holdout-bootstrap-preflight-v1.json").read_text(
            encoding="utf-8"
        )
    )
    corpus_acceptance = {
        c["case_id"]: c for c in corpus["acceptance_cases"]
    }

    cases = {}
    for case_id in charter["holdout_population"]["families"]:
        case_payload = json.loads(
            (PYTHON_SERVICE_ROOT / "benchmarks/cases" / case_id / "case.json")
            .read_text(encoding="utf-8")
        )
        entry = charter["cases"][case_id]
        public_case_input = {
            "case_id": case_payload["case_id"],
            "goal": entry["goal"],
            "case_context": entry["case_context"],
            "seed_questions": list(entry["seed_questions"]),
            "seed_coverage_dimensions": list(
                case_payload.get("required_coverage_dimensions", ())
            ),
            "source_scope_ids": ["windows"],
        }
        cases[case_id] = {
            "case_contract_file_sha256": sha256_file(
                PYTHON_SERVICE_ROOT / "benchmarks/cases" / case_id
                / "case.json"
            ),
            "case_contract_input_hash": case_payload["input_hash"],
            "corpus_case_hash_binding": corpus_acceptance[case_id][
                "case_hash"
            ],
            "sealed_truth_manifest_hash": corpus_acceptance[case_id][
                "truth_manifest_hash"
            ],
            "sealed_truth_manifest_file_sha256": sha256_file(
                PYTHON_SERVICE_ROOT / "benchmarks/cases" / case_id
                / "truth_manifest.json"
            ),
            "preflight_truth_untouched": next(
                c["checks"]["G8b_truth_manifest_untouched_versus_corpus"]
                for c in preflight["cases"]
                if c["case_id"] == case_id
            ),
            "public_case_input_v2": public_case_input,
            "public_case_input_v2_canonical_hash": state_hash_of(
                canonical_state_json(public_case_input)
            ),
        }

    artifact = {
        "artifact_version": "B6FrozenIdentitiesV1",
        "created_at": "2026-10-01T00:00:00+00:00",
        "binding": (
            "recorded BEFORE the first holdout model call; immutable for "
            "the entire B6 series (spec §1/§6)"
        ),
        "git_head": git("rev-parse", "HEAD"),
        "git_branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "git_clean": git("status", "--porcelain") == "",
        "production_runtime": {
            "code_commit": git("rev-parse", "HEAD"),
            "httpserver_tree_hash": git(
                "rev-parse", "HEAD:python_service/httpserver"
            ),
            "note": "no production runtime changes in B6 (frozen since "
            "the calibration series; any change invalidates the series)",
        },
        "frozen_profiles": {
            "acceptance_profile_v2": {
                "path": "benchmarks/profiles/agent-v0-acceptance-profile-v2.json",
                "sha256": sha256_file(
                    PYTHON_SERVICE_ROOT
                    / "benchmarks/profiles/agent-v0-acceptance-profile-v2.json"
                ),
            },
            "calibration_evidence_binding_v2": {
                "path": "benchmarks/profiles/calibration-evidence-binding-v2.json",
                "sha256": sha256_file(
                    PYTHON_SERVICE_ROOT
                    / "benchmarks/profiles/calibration-evidence-binding-v2.json"
                ),
            },
            "admission_record_v2": {
                "path": "benchmarks/profiles/agent-v0-acceptance-profile-admission-record.v2.json",
                "sha256": sha256_file(
                    PYTHON_SERVICE_ROOT
                    / "benchmarks/profiles/agent-v0-acceptance-profile-admission-record.v2.json"
                ),
            },
            "measurement_baseline_v6": {
                "path": "benchmarks/profiles/benchmark-measurement-baseline-v6.json",
                "sha256": sha256_file(
                    PYTHON_SERVICE_ROOT
                    / "benchmarks/profiles/benchmark-measurement-baseline-v6.json"
                ),
            },
            "acceptance_threshold_provenance_v1": {
                "path": "benchmarks/profiles/acceptance-threshold-provenance-v1.json",
                "sha256": sha256_file(
                    PYTHON_SERVICE_ROOT
                    / "benchmarks/profiles/acceptance-threshold-provenance-v1.json"
                ),
            },
        },
        "model_configuration": {
            "path": "benchmarks/results/agent-v0/b2-restart/sensenova-6.8-flash-lite.model-config.json",
            "sha256": sha256_file(
                PYTHON_SERVICE_ROOT
                / "benchmarks/results/agent-v0/b2-restart/sensenova-6.8-flash-lite.model-config.json"
            ),
            "candidate_id": "sensenova-6.8-flash-lite",
            "overrides": {
                "llm_text_model": "sensenova-6.8-flash-lite",
                "llm_text_temperature": 0.7,
                "llm_thinking_mode": "disabled",
            },
            "api_key_material": "none in artifact; key supplied via env at runtime only",
        },
        "corpus_v2": {
            "path": "benchmarks/corpus/corpus-agent-v0-calibration.v2.json",
            "sha256": sha256_file(
                PYTHON_SERVICE_ROOT
                / "benchmarks/corpus/corpus-agent-v0-calibration.v2.json"
            ),
            "input_hash": corpus["input_hash"],
        },
        "public_case_inputs_v2": cases,
        "evaluator": {
            "path": "httpserver/services/benchmarks/case_outcome.py",
            "sha256": sha256_file(
                PYTHON_SERVICE_ROOT
                / "httpserver/services/benchmarks/case_outcome.py"
            ),
            "case_outcome_version": "benchmark-case-outcome:v2",
            "truth_access": "deterministic evaluator only (spec §27)",
        },
        "bootstrap_and_driver": {
            "run_p8b_baseline.py": sha256_file(
                PYTHON_SERVICE_ROOT / "scripts/run_p8b_baseline.py"
            ),
            "run_b6_holdout.py": sha256_file(
                PYTHON_SERVICE_ROOT / "scripts/run_b6_holdout.py"
            ),
            "preflight_b6_holdout.py": sha256_file(
                PYTHON_SERVICE_ROOT / "scripts/preflight_b6_holdout.py"
            ),
            "b6_frozen_identities.py": sha256_file(
                PYTHON_SERVICE_ROOT / "scripts/b6_frozen_identities.py"
            ),
            "charter_artifact_sha256": sha256_file(CHARTER_FILE),
            "charter_input_hash": charter["input_hash"],
        },
        "holdout_entry_gates": {
            "preflight_artifact": (
                "benchmarks/results/agent-v0/b6-holdout/"
                "holdout-bootstrap-preflight-v1.json"
            ),
            "preflight_input_hash": preflight["input_hash"],
            "preflight_all_passed": preflight["all_passed"],
            "holdout_static_validation_ref": (
                "benchmarks/results/agent-v0/b2-restart/b2-post-b55-final/"
                "holdout-static-validation-v1.json"
            ),
        },
        "population": {
            "families": charter["holdout_population"]["families"],
            "repetitions_per_family": 3,
            "scheduled_runs": 6,
            "acceptance_rule": "AgentV0AcceptanceProfileV2 (all six axes; "
            "truth floor = ALL families x >=2/3 reps at "
            "{success, success_with_limitations})",
        },
    }
    artifact["input_hash"] = state_hash_of(
        canonical_state_json(
            {k: v for k, v in artifact.items() if k != "input_hash"}
        )
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"frozen identities -> {OUT_FILE}")
    print(f"git_head={artifact['git_head'][:12]} "
          f"input_hash={artifact['input_hash'][:16]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
