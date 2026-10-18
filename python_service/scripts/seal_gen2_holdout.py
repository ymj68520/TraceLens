#!/usr/bin/env python3
"""Acceptance Generation 2 — HoldoutSealV2 (spec §25).

Freezes the constructed generation: public case hashes, public asset
hashes, truth hashes, bootstrap transform hash, evaluator hash,
AcceptanceProfile hash, CalibrationEvidenceBinding hash, provisioning
substrate, timestamp, seal reason.  After this record exists the
generation is immutable; any mutation is detectable and BLOCKS execution
(tested contract).  Refuses to seal if static validation did not pass.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PYTHON_SERVICE_ROOT = SCRIPT_PATH.parents[1]
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

GEN2_ROOT = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0"
    / "acceptance-gen2"
)
SEAL_FILE = GEN2_ROOT / "holdout-seal-v2.json"
SUBSTRATE = Path("/home/ymj68520/projects/testimgs/最小验证镜像.img")


def main() -> int:
    from httpserver.services.benchmarks.holdout_contract import (
        build_gen2_seal,
        verify_holdout_seal,
    )

    validation = json.loads(
        (GEN2_ROOT / "gen2-static-validation-v1.json").read_text(
            encoding="utf-8"
        )
    )
    if not validation.get("all_passed"):
        raise SystemExit("refusing to seal: static validation did not pass")
    if SEAL_FILE.exists():
        raise SystemExit(
            "seal already exists (immutable); post-seal mutation requires "
            "GENERATION_INVALIDATED_PRE_EXECUTION and a new generation"
        )
    if not SUBSTRATE.is_file():
        raise SystemExit(f"provisioning substrate missing: {SUBSTRATE}")

    seal = build_gen2_seal(
        cases_dir=GEN2_ROOT / "cases",
        truth_dir=GEN2_ROOT / "truth",
        acceptance_profile_path=(
            PYTHON_SERVICE_ROOT
            / "benchmarks/profiles/agent-v0-acceptance-profile-v2.json"
        ),
        calibration_binding_path=(
            PYTHON_SERVICE_ROOT
            / "benchmarks/profiles/calibration-evidence-binding-v2.json"
        ),
        provisioning_substrate_path=SUBSTRATE,
        seal_reason=(
            "Acceptance Generation 2 sealed at construction time: every "
            "Agent-visible input presealed and hash-bound before "
            "admission (spec §10/§25); B6 will execute frozen semantics, "
            "never author them"
        ),
    )
    # self-check immediately: the freshly built seal must verify clean
    violations = verify_holdout_seal(
        seal,
        cases_dir=GEN2_ROOT / "cases",
        truth_dir=GEN2_ROOT / "truth",
        acceptance_profile_path=(
            PYTHON_SERVICE_ROOT
            / "benchmarks/profiles/agent-v0-acceptance-profile-v2.json"
        ),
        calibration_binding_path=(
            PYTHON_SERVICE_ROOT
            / "benchmarks/profiles/calibration-evidence-binding-v2.json"
        ),
        provisioning_substrate_path=SUBSTRATE,
    )
    if violations:
        raise SystemExit(f"seal self-check FAILED: {violations}")
    SEAL_FILE.write_text(
        seal.model_dump_json(indent=1), encoding="utf-8"
    )
    print(f"seal -> {SEAL_FILE}")
    print(f"seal_hash: {seal.seal_hash}")
    for case_id, h in seal.public_case_hashes.items():
        print(f"  {case_id}: public={h[:16]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
