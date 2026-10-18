#!/usr/bin/env python3
"""Acceptance Generation 3 — Generation3AdmissionAuditV1 (spec §29/§40).

Zero model calls (provisioning uses the LLM-disabled task lifecycle
only).  Verifies AFTER the seal:
  all public semantics presealed (sealed loader + hash match)
  all evidence substrates presealed (image hashes, manifests, world
    digests, parser config — via verify_holdout_seal_v3)
  truth/public/substrate isolation valid (three-way separation)
  provisioning reproducible (LIVE re-provisioning x2 per case against
    the sealed digests — the §19 equivalence check)
  attention preflight clean (frozen projection + real builder)
  AcceptanceProfile frozen / runtime frozen / model frozen
  execution count = 0
Status: ADMITTED_FOR_B6 or WITHHELD.
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

REPO_ROOT = PYTHON_SERVICE_ROOT.parent
GEN3_ROOT = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0"
    / "acceptance-gen3"
)
OUT_FILE = GEN3_ROOT / "generation3-admission-audit-v1.json"

ACCEPTANCE_PROFILE_SHA = (
    "c40f1adcad816e433f7edfc6cbc0b56dc32c031bf1fcb31528523ffa62f0e98d"
)
MODEL_CONFIG_SHA = (
    "9cdcb1fde1cdf6ca25067c0436bbc83618fcf3708b3fd4cc49207ba4b2d130fb"
)
CALIBRATION_EPOCH_RUNTIME_HEAD = (
    "49e8172eea55abf45ddf13bda95715506da4b872"
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, cwd=REPO_ROOT
    ).stdout.strip()


def main() -> int:
    from httpserver.services.benchmarks.holdout_contract import (
        build_holdout_working_state,
        load_public_holdout_case,
        verify_truth_public_isolation,
    )
    from httpserver.services.benchmarks.holdout_contract_v3 import (
        HoldoutSealV3,
        SealedEvidenceManifestV1,
        SealedEvidenceSubstrateV1,
        provisioning_equivalence_check,
        verify_holdout_seal_v3,
    )
    from httpserver.services.benchmarks.truth_manifest import TruthManifestV1
    from httpserver.services.investigation.agent_attention import (
        AttentionBuilder,
    )
    from httpserver.services.investigation.agent_runtime import (
        canonical_state_json,
        state_hash_of,
    )

    checks: dict[str, dict] = {}

    seal_dict = json.loads(
        (GEN3_ROOT / "holdout-seal-v3.json").read_text(encoding="utf-8")
    )
    stored = seal_dict.get("seal_hash", "")
    seal = HoldoutSealV3(**seal_dict)
    if seal.seal_hash != stored:
        raise SystemExit("seal record internally inconsistent")

    gate_kwargs = dict(
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
            "rev-parse",
            "HEAD:python_service/httpserver/services/investigation",
        ),
        model_config_path=(
            PYTHON_SERVICE_ROOT
            / "benchmarks/results/agent-v0/b2-restart/"
            "sensenova-6.8-flash-lite.model-config.json"
        ),
    )
    seal_violations = verify_holdout_seal_v3(seal, **gate_kwargs)
    checks["all_public_and_substrate_inputs_presealed"] = {
        "ok": not seal_violations,
        "seal_hash": seal.seal_hash,
        "violations": list(seal_violations),
    }

    # three-way isolation: truth never in public surface; substrate
    # carries exactly the public asset set (verified by the manifest
    # == asset-set equivalence and the seal bindings)
    isolation_ok = True
    isolation_detail = []
    case_ids = sorted(seal.public_case_hashes)
    for case_id in case_ids:
        case = load_public_holdout_case(
            GEN3_ROOT / "cases" / f"{case_id}.public-case.json"
        )
        truth = TruthManifestV1(
            **json.loads(
                (GEN3_ROOT / "truth" / f"{case_id}.truth.json").read_text(
                    encoding="utf-8"
                )
            )
        )
        manifest = SealedEvidenceManifestV1(
            **json.loads(
                (
                    GEN3_ROOT / "substrates"
                    / f"{case_id}.evidence-manifest.json"
                ).read_text(encoding="utf-8")
            )
        )
        violations = list(verify_truth_public_isolation(case, truth))
        asset_paths = {
            f"/{a.relative_path}" for a in case.public_assets
        }
        manifest_paths = {e.normalized_path for e in manifest.entries}
        if manifest_paths != asset_paths:
            violations.append(
                f"substrate manifest != public asset set: "
                f"{sorted(manifest_paths ^ asset_paths)}"
            )
        isolation_ok &= not violations
        isolation_detail.append(
            {"case_id": case_id, "violations": violations}
        )
    checks["truth_public_substrate_isolation"] = {
        "ok": isolation_ok,
        "relation": "public contract = what the Agent is asked; "
        "substrate = what the Agent can observe; truth = how the "
        "result is evaluated — mutually consistent at construction, "
        "strictly separated at execution",
        "cases": isolation_detail,
    }

    # LIVE provisioning equivalence (×2 per case, zero model calls)
    equivalence_ok = True
    equivalence_detail = []
    for case_id in case_ids:
        substrate = SealedEvidenceSubstrateV1(
            **json.loads(
                (
                    GEN3_ROOT / "substrates" / f"{case_id}.substrate.json"
                ).read_text(encoding="utf-8")
            )
        )
        manifest = SealedEvidenceManifestV1(
            **json.loads(
                (
                    GEN3_ROOT / "substrates"
                    / f"{case_id}.evidence-manifest.json"
                ).read_text(encoding="utf-8")
            )
        )
        result = provisioning_equivalence_check(
            substrate,
            manifest,
            seal.evidence_world_digests[case_id],
            images_dir=GEN3_ROOT / "images",
        )
        equivalence_ok &= result["ok"]
        equivalence_detail.append(result)
        print(
            f"provisioning {case_id}: "
            f"{'PASS' if result['ok'] else 'FAIL'} "
            f"digests={[d[:12] for d in result['digests']]}"
        )
    checks["provisioning_reproducible_and_equivalent"] = {
        "ok": equivalence_ok,
        "repetitions_per_case": 2,
        "cases": equivalence_detail,
    }

    # attention preflight
    builder = AttentionBuilder()
    attention_ok = True
    attention_detail = []
    for case_id in case_ids:
        case = load_public_holdout_case(
            GEN3_ROOT / "cases" / f"{case_id}.public-case.json"
        )
        states = [
            build_holdout_working_state(
                case, task_id="t", investigation_id="i"
            )
            for _ in range(2)
        ]
        runs = [
            [i.item_id for i in builder.build_full_set(s, state_revision=1).items]
            for s in states
        ]
        ok = runs[0] == runs[1] and not any(
            i.startswith("coverage:") for i in runs[0]
        )
        attention_ok &= ok
        attention_detail.append(
            {"case_id": case_id, "deterministic_and_folded": ok,
             "attention_item_ids": runs[0]}
        )
    checks["attention_preflight_clean"] = {
        "ok": attention_ok,
        "cases": attention_detail,
    }

    checks["acceptance_profile_frozen"] = {
        "ok": _sha256_file(gate_kwargs["acceptance_profile_path"])
        == ACCEPTANCE_PROFILE_SHA,
        "expected_sha256": ACCEPTANCE_PROFILE_SHA,
    }
    inv_now = _git(
        "rev-parse", "HEAD:python_service/httpserver/services/investigation"
    )
    inv_ref = _git(
        f"rev-parse",
        f"{CALIBRATION_EPOCH_RUNTIME_HEAD}:python_service/httpserver/services/investigation",
    )
    checks["runtime_frozen"] = {
        "ok": inv_now == inv_ref,
        "investigation_subtree_hash": inv_now,
        "calibration_epoch_reference": inv_ref,
    }
    checks["model_frozen"] = {
        "ok": _sha256_file(gate_kwargs["model_config_path"])
        == MODEL_CONFIG_SHA,
        "expected_sha256": MODEL_CONFIG_SHA,
        "model": "sensenova-6.8-flash-lite (CALIBRATION-QUALIFIED; "
        "formal sealed acceptance NOT ESTABLISHED)",
    }

    executed = [
        p.name
        for p in GEN3_ROOT.rglob("*")
        if p.name in (
            "result.json", "failure.json", "run_manifest.json",
            "snapshot.json", "driver_failure.json",
        )
    ]
    checks["execution_count_zero"] = {
        "ok": not executed,
        "execution_count": 0,
        "stray_artifacts": executed,
    }

    all_ok = all(entry["ok"] for entry in checks.values())
    admission = "ADMITTED_FOR_B6" if all_ok else "WITHHELD"
    artifact = {
        "artifact_version": "Generation3AdmissionAuditV1",
        "generation_id": "acceptance-generation-3",
        "created_at": "2026-10-01T00:00:00+00:00",
        "zero_model_calls": True,
        "status": admission,
        "admission": admission,
        "checks": checks,
        "all_passed": all_ok,
        "b6_preconditions": [
            "explicit user authorization for B6 (never auto-executed)",
            "Gen-3 execution preflight at entry: load/validate/"
            "hash-check/bootstrap + FRESH provisioning equivalence "
            "(zero model calls) feeding enforce_execution_gate_v3",
            "population at execution: 2 families x 3 repetitions = 6 "
            "scheduled runs under the frozen AcceptanceProfileV2",
        ],
    }
    OUT_FILE.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    for name, entry in checks.items():
        print(f"{'PASS' if entry['ok'] else 'FAIL'}  {name}")
    print(f"admission -> {OUT_FILE}")
    print(f"STATUS: {admission}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
