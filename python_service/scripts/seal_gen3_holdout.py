#!/usr/bin/env python3
"""Acceptance Generation 3 — HoldoutSealV3 (spec §38/§39).

Seals the constructed generation INCLUDING the evidence substrates:
public case hashes, public asset hashes, truth hashes, evidence image
hashes, EvidenceManifest hashes, logical Evidence-world digests, parser
config hash, bootstrap transform, evaluator, AcceptanceProfile,
CalibrationBinding, GenerationBinding, runtime subtree hash, model
config hash.  Refuses to seal unless the construction validation passed.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PYTHON_SERVICE_ROOT = SCRIPT_PATH.parents[1]
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

REPO_ROOT = PYTHON_SERVICE_ROOT.parent
GEN3_ROOT = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0"
    / "acceptance-gen3"
)
SEAL_FILE = GEN3_ROOT / "holdout-seal-v3.json"
MODEL_CONFIG = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0"
    / "b2-restart" / "sensenova-6.8-flash-lite.model-config.json"
)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, cwd=REPO_ROOT
    ).stdout.strip()


def main() -> int:
    from httpserver.services.benchmarks.holdout_contract_v3 import (
        build_gen3_seal,
        verify_holdout_seal_v3,
    )

    validation = json.loads(
        (GEN3_ROOT / "evidence-world-validation-v1.json").read_text(
            encoding="utf-8"
        )
    )
    if not validation.get("all_passed"):
        raise SystemExit("refusing to seal: construction validation failed")
    if SEAL_FILE.exists():
        raise SystemExit(
            "seal already exists (immutable); post-seal mutation requires "
            "GENERATION_INVALIDATED_PRE_EXECUTION and a new generation"
        )

    kwargs = dict(
        gen3_root=GEN3_ROOT,
        profiles_dir=REPO_ROOT / "config" / "filter_profiles",
        acceptance_profile_path=(
            PYTHON_SERVICE_ROOT
            / "benchmarks/profiles/agent-v0-acceptance-profile-v2.json"
        ),
        calibration_binding_path=(
            PYTHON_SERVICE_ROOT
            / "benchmarks/profiles/calibration-evidence-binding-v2.json"
        ),
        generation_binding_path=(
            PYTHON_SERVICE_ROOT
            / "benchmarks/profiles/acceptance-profile-generation-binding-v3.json"
        ),
        runtime_investigation_subtree_hash=_git(
            "rev-parse", "HEAD:python_service/httpserver/services/investigation"
        ),
        model_config_path=MODEL_CONFIG,
    )
    seal = build_gen3_seal(
        seal_reason=(
            "Acceptance Generation 3 sealed at construction time: every "
            "Agent-observable input — public semantics, evidence-bearing "
            "substrate images, expected Evidence world, parser "
            "configuration — frozen and hash-bound before admission "
            "(spec §4/§14/§38)"
        ),
        **kwargs,
    )
    violations = verify_holdout_seal_v3(seal, **kwargs)
    if violations:
        raise SystemExit(f"seal self-check FAILED: {violations}")
    SEAL_FILE.write_text(seal.model_dump_json(indent=1), encoding="utf-8")
    print(f"seal -> {SEAL_FILE}")
    print(f"seal_hash: {seal.seal_hash}")
    for case_id, h in seal.public_case_hashes.items():
        print(
            f"  {case_id}: public={h[:12]}… image="
            f"{seal.evidence_substrate_hashes[case_id]['image_sha256'][:12]}… "
            f"world={seal.evidence_world_digests[case_id][:12]}…"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
