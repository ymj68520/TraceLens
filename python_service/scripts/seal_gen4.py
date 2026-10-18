"""Seal Acceptance Generation 4 (G4-4).

Creates the Generation-4 binding artifact (§29-§31, §33: runtime V3 +
superseding record + calibration binding V3 + acceptance profile V2 +
acceptance runtime binding V3 + hydration contract + content store
implementation + model config), then seals via the FROZEN HoldoutSealV3
schema — the generation_binding slot carries the binding above, so the
seal transitively binds the hydration contract without any protocol
extension (§32: new generation, not new protocol). Zero model calls.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PYTHON_SERVICE_ROOT = SCRIPT_PATH.parents[1]
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

REPO_ROOT = PYTHON_SERVICE_ROOT.parent
GEN4_ROOT = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0"
    / "acceptance-gen4"
)
PROFILES = PYTHON_SERVICE_ROOT / "benchmarks" / "profiles"


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def main() -> int:
    head = git("rev-parse", "HEAD")

    case_ids = [
        "gen4-layered-dispersion",
        "gen4-departure-staging",
    ]
    binding = {
        "artifact_version": "Generation4BindingV1",
        "generation_id": "acceptance-generation-4",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "case_ids": case_ids,
        "protocol": {
            "public_case": "public-holdout-case:v2",
            "substrate": "sealed-evidence-substrate:v1",
            "manifest": "sealed-evidence-manifest:v1",
            "seal": "holdout-seal-v3 (UNCHANGED — no protocol v4, §6/§32)",
            "evaluator": "benchmark-case-outcome:v2 (unchanged, §27)",
            "execution_gate": "enforce_execution_gate_v3 (unchanged)",
        },
        "runtime": {
            "baseline": "AgentV0RuntimeBaselineV3",
            "baseline_sha256": sha256_file(
                PROFILES / "agent-v0-runtime-baseline-v3.json"
            ),
            "identity_closure": (
                "acceptance-gen4/runtime-identity-closure.json "
                "(§2 Case C → superseding record)"
            ),
            "superseding_record_sha256": sha256_file(
                GEN4_ROOT / "runtime-baseline-v3-superseding-record.json"
            ),
            "measured_runtime_commit": "1b6c0a88 (production files unchanged through seal-time HEAD)",
            "head_at_seal": head,
            "investigation_subtree_at_seal": git(
                "rev-parse", f"{head}:python_service/httpserver/services/investigation"
            ),
        },
        "content_hydration": {
            "contract": "evidence-content-hydration:v1 (FROZEN d213145d)",
            "contract_doc_sha256": sha256_file(
                REPO_ROOT / "docs/specs/evidence-content-hydration-contract.md"
            ),
            "content_store_sha256": sha256_file(
                PYTHON_SERVICE_ROOT
                / "httpserver/services/evidence/content_store.py"
            ),
            "note": "§33: seal binds the hydration contract and store "
            "implementation transitively via this generation binding "
            "(the seal's generation_binding slot), without extending the "
            "frozen HoldoutSealV3 schema",
        },
        "calibration": {
            "binding": "CalibrationEvidenceBindingV3",
            "sha256": sha256_file(
                PROFILES / "calibration-evidence-binding-v3.json"
            ),
            "verdict": "MEASUREMENT_VALID / ZERO_CHANGE",
        },
        "acceptance": {
            "profile": "AgentV0AcceptanceProfileV2 (UNCHANGED, §28)",
            "profile_sha256": sha256_file(
                PROFILES / "agent-v0-acceptance-profile-v2.json"
            ),
            "runtime_binding": "AcceptanceProfileRuntimeBindingV3",
            "runtime_binding_sha256": sha256_file(
                PROFILES / "acceptance-profile-runtime-binding-v3.json"
            ),
        },
        "model_config": {
            "artifact": "acceptance-gen4/gen4-model-config.json",
            "sha256": sha256_file(GEN4_ROOT / "gen4-model-config.json"),
            "model_id": "sensenova-6.8-flash-lite",
            "temperature": 0.7,
            "max_tokens": 16384,
            "reasoning": "disabled",
        },
        "capability_selection": {
            "record": "acceptance-gen4/capability-selection-record-v1.json",
            "families": ["fund_flow_layering", "bulk_staging_discrimination"],
        },
        "independence_audit": (
            "acceptance-gen4/holdout-independence-audit-v1.json (confirmed)"
        ),
        "hydration_preseal": {
            "validator": "scripts/validate_gen4_hydration.py (production "
            "content path only, §41)",
            "per_case_proofs": [
                f"acceptance-gen4/hydration-preseal-{case}-pre.json"
                for case in case_ids
            ] + [
                f"acceptance-gen4/hydration-preseal-{case}-post.json"
                for case in case_ids
            ],
        },
        "execution": {
            "model_calls_in_preparation": 0,
            "gen4_execution_count": 0,
            "b6_requires_explicit_authorization": True,
        },
    }
    binding_path = GEN4_ROOT / "generation-4-binding-v1.json"
    binding_path.write_text(json.dumps(binding, indent=2, ensure_ascii=False) + "\n")

    from httpserver.services.benchmarks.holdout_contract_v3 import (
        build_gen3_seal,
    )

    seal = build_gen3_seal(
        gen3_root=GEN4_ROOT,
        profiles_dir=REPO_ROOT / "config" / "filter_profiles",
        acceptance_profile_path=PROFILES / "agent-v0-acceptance-profile-v2.json",
        calibration_binding_path=PROFILES
        / "calibration-evidence-binding-v3.json",
        generation_binding_path=binding_path,
        runtime_investigation_subtree_hash=git(
            "rev-parse",
            f"{head}:python_service/httpserver/services/investigation",
        ),
        model_config_path=GEN4_ROOT / "gen4-model-config.json",
        seal_reason=(
            "acceptance-generation-4 sealed: runtime-v3-bound final sealed "
            "holdout; ADMITTED_FOR_B6 pending admission audit; "
            "execution_count = 0"
        ),
        sealed_at=time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
    )
    seal_path = GEN4_ROOT / "holdout-seal-v3.json"
    seal_path.write_text(seal.model_dump_json(indent=1), encoding="utf-8")

    print(json.dumps({
        "generation_binding": str(binding_path),
        "seal_hash": seal.seal_hash,
        "seal_file": str(seal_path),
        "cases": sorted(seal.public_case_hashes.keys()),
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
