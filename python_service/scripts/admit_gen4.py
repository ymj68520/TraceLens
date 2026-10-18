"""Generation4AdmissionAuditV1 (§34-§36): static admission.

Verifies every §34 item deterministically (zero model calls). Any
failure -> WITHHELD; all pass -> Generation 4 SEALED / ADMITTED_FOR_B6
/ execution_count = 0.
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


def _load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def main() -> int:
    seal = _load(GEN4_ROOT / "holdout-seal-v3.json")
    binding = _load(GEN4_ROOT / "generation-4-binding-v1.json")
    closure = _load(GEN4_ROOT / "runtime-identity-closure.json")
    independence = _load(GEN4_ROOT / "holdout-independence-audit-v1.json")
    model_config = _load(GEN4_ROOT / "gen4-model-config.json")
    head = git("rev-parse", "HEAD")

    checks = {}

    # 1. runtime identity exact (§34 runtime identity / §2 closure)
    checks["runtime_identity_closed"] = closure["disposition"].startswith(
        "CASE_C_SUPERSEDING_RECORD"
    ) or closure["disposition"] == "RUNTIME_IDENTITY_CONFIRMED"
    checks["runtime_superseding_record_present"] = (
        GEN4_ROOT / "runtime-baseline-v3-superseding-record.json"
    ).is_file()
    checks["investigation_subtree_matches_seal"] = (
        git("rev-parse",
            f"{head}:python_service/httpserver/services/investigation")
        == seal["runtime_investigation_subtree_hash"]
    )
    from httpserver.services.benchmarks.holdout_contract_v3 import (
        SealedEvidenceManifestV1,
        SealedEvidenceSubstrateV1,
        enforce_execution_gate_v3,
        provisioning_equivalence_check,
        verify_holdout_seal_v3,
    )

    seal_obj = None
    from httpserver.services.benchmarks.holdout_contract_v3 import (
        HoldoutSealV3,
    )

    seal_obj = HoldoutSealV3(**seal)
    # frozen seal integrity: re-verify against CURRENT artifacts
    try:
        violations = verify_holdout_seal_v3(
            seal_obj,
            gen3_root=GEN4_ROOT,
            profiles_dir=REPO_ROOT / "config" / "filter_profiles",
            acceptance_profile_path=PROFILES
            / "agent-v0-acceptance-profile-v2.json",
            calibration_binding_path=PROFILES
            / "calibration-evidence-binding-v3.json",
            generation_binding_path=GEN4_ROOT / "generation-4-binding-v1.json",
            runtime_investigation_subtree_hash=seal[
                "runtime_investigation_subtree_hash"
            ],
            model_config_path=GEN4_ROOT / "gen4-model-config.json",
        )
        checks["frozen_seal_integrity_replay"] = not violations
        gate_error = ("; ".join(violations)[:300] if violations else None)
    except Exception as exc:  # noqa: BLE001 — audit must record failures
        checks["frozen_seal_integrity_replay"] = False
        gate_error = f"{type(exc).__name__}: {exc}"[:300]

    # live equivalence: provision each sealed image x2 (zero model calls)
    equivalence_all_ok = True
    for case_id in seal["public_case_hashes"]:
        substrate = SealedEvidenceSubstrateV1(
            **_load(GEN4_ROOT / "substrates" / f"{case_id}.substrate.json")
        )
        manifest = SealedEvidenceManifestV1(
            **_load(
                GEN4_ROOT / "substrates" / f"{case_id}.evidence-manifest.json"
            )
        )
        try:
            equivalence = provisioning_equivalence_check(
                substrate,
                manifest,
                seal["evidence_world_digests"][case_id],
                images_dir=GEN4_ROOT / "images",
            )
            ok = bool(equivalence.get("ok"))
        except Exception as exc:  # noqa: BLE001
            ok = False
            gate_error = f"{case_id} provisioning: {exc}"[:300]
        checks[f"{case_id}_provisioning_equivalence_x2"] = ok
        equivalence_all_ok &= ok

    # the frozen execution-gate chain over the sealed world identity
    try:
        enforce_execution_gate_v3(
            seal_obj,
            gen3_root=GEN4_ROOT,
            profiles_dir=REPO_ROOT / "config" / "filter_profiles",
            acceptance_profile_path=PROFILES
            / "agent-v0-acceptance-profile-v2.json",
            calibration_binding_path=PROFILES
            / "calibration-evidence-binding-v3.json",
            generation_binding_path=GEN4_ROOT / "generation-4-binding-v1.json",
            runtime_investigation_subtree_hash=seal[
                "runtime_investigation_subtree_hash"
            ],
            model_config_path=GEN4_ROOT / "gen4-model-config.json",
            evidence_world_digests=dict(seal["evidence_world_digests"]),
            evidence_world_keys={
                cid: {
                    e["expected_evidence_key"]
                    for e in _load(
                        GEN4_ROOT
                        / "substrates"
                        / f"{cid}.evidence-manifest.json"
                    )["entries"]
                }
                for cid in seal["public_case_hashes"]
            },
            evidence_world_files={
                cid: {
                    e["normalized_path"].lstrip("/")
                    for e in _load(
                        GEN4_ROOT
                        / "substrates"
                        / f"{cid}.evidence-manifest.json"
                    )["entries"]
                }
                for cid in seal["public_case_hashes"]
            },
        )
        checks["frozen_execution_gate_replay_pass"] = True
    except Exception as exc:  # noqa: BLE001
        checks["frozen_execution_gate_replay_pass"] = False
        gate_error = (
            (gate_error + " | " if gate_error else "")
            + f"{type(exc).__name__}: {exc}"[:300]
        )

    # 2. model identity exact (§31)
    checks["model_identity_exact"] = (
        model_config["model_id"] == "sensenova-6.8-flash-lite"
        and model_config["generation_params"]["temperature"] == 0.7
        and model_config["generation_params"]["max_tokens"] == 16384
        and model_config["generation_params"]["thinking_mode"] == "disabled"
        and seal["model_config_hash"] == sha256_file(
            GEN4_ROOT / "gen4-model-config.json"
        )
    )

    # 3. calibration binding V3 exact (§29)
    checks["calibration_binding_v3_exact"] = (
        seal["calibration_binding_sha256"]
        == sha256_file(PROFILES / "calibration-evidence-binding-v3.json")
        and _load(PROFILES / "calibration-evidence-binding-v3.json")[
            "binds"
        ]["b2_run_set"]["measurement_verdict"] == "MEASUREMENT_VALID"
    )

    # 4. acceptance profile V2 + runtime binding V3 exact (§28/§30)
    checks["acceptance_profile_v2_unchanged"] = (
        seal["acceptance_profile_sha256"]
        == sha256_file(PROFILES / "agent-v0-acceptance-profile-v2.json")
    )
    checks["acceptance_runtime_binding_v3_exact"] = (
        binding["acceptance"]["runtime_binding_sha256"]
        == sha256_file(PROFILES / "acceptance-profile-runtime-binding-v3.json")
        and _load(PROFILES / "acceptance-profile-runtime-binding-v3.json")[
            "review"
        ]["semantics_applicable"]
    )

    # 5. hydration contract bound via the generation binding (§33)
    checks["hydration_contract_bound"] = (
        binding["content_hydration"]["contract_doc_sha256"]
        == sha256_file(REPO_ROOT / "docs/specs/evidence-content-hydration-contract.md")
        and binding["content_hydration"]["content_store_sha256"]
        == sha256_file(
            PYTHON_SERVICE_ROOT / "httpserver/services/evidence/content_store.py"
        )
        and seal["acceptance_profile_generation_binding_sha256"] == sha256_file(
            GEN4_ROOT / "generation-4-binding-v1.json"
        )
    )

    # 6. hydration proofs exact per case (§14-§17)
    for case_id in seal["public_case_hashes"]:
        pre = _load(GEN4_ROOT / f"hydration-preseal-{case_id}-pre.json")
        post = _load(GEN4_ROOT / f"hydration-preseal-{case_id}-post.json")
        checks[f"{case_id}_hydration_pre_pass"] = pre["pre_status"] == "PASS"
        checks[f"{case_id}_restart_proof_pass"] = post["post_status"] == "PASS"
        checks[f"{case_id}_world_matches_seal"] = (
            pre["world_digest"] == seal["evidence_world_digests"][case_id]
        )

    # 7. bootstrap / attention preflight recorded from construction (§23/§24)
    validation = _load(GEN4_ROOT / "evidence-world-validation-v1.json")
    checks["bootstrap_and_attention_clean"] = validation["all_passed"] and all(
        row["checks"].get("attention_no_standalone_coverage")
        and row["checks"].get("attention_no_duplicate_topology")
        for row in validation["cases"]
    )

    # 8. truth isolation (§21/§22): public surfaces carry no truth values
    from httpserver.services.benchmarks.holdout_contract import (
        PublicHoldoutCaseV2,
        verify_truth_public_isolation,
    )
    from httpserver.services.benchmarks.truth_manifest import (
        TruthManifestV1,
    )
    isolation_clean = True
    for case_id in seal["public_case_hashes"]:
        pub = PublicHoldoutCaseV2(
            **_load(GEN4_ROOT / "cases" / f"{case_id}.public-case.json")
        )
        truth = TruthManifestV1(
            **_load(GEN4_ROOT / "truth" / f"{case_id}.truth.json")
        )
        if verify_truth_public_isolation(pub, truth):
            isolation_clean = False
        # content store reads only (task_id, evidence_key): structural
        # check — the store module must not reference truth artifacts
        store_src = (
            PYTHON_SERVICE_ROOT
            / "httpserver/services/evidence/content_store.py"
        ).read_text(encoding="utf-8")
        if "truth_manifest" in store_src or "TruthManifest" in store_src:
            isolation_clean = False
    checks["truth_isolation_clean"] = isolation_clean

    # 9. holdout independence (§27)
    checks["holdout_independence_confirmed"] = independence[
        "independence_confirmed"
    ]

    # 10. execution count (§25/§36)
    checks["execution_count_zero"] = (
        binding["execution"]["gen4_execution_count"] == 0
        and binding["execution"]["model_calls_in_preparation"] == 0
    )

    # 11. no protocol extension (§6/§32)
    checks["protocol_unchanged"] = (
        binding["protocol"]["seal"] == "holdout-seal-v3 (UNCHANGED — no protocol v4, §6/§32)"
        and binding["protocol"]["evaluator"] == "benchmark-case-outcome:v2 (unchanged, §27)"
    )

    all_pass = all(bool(v) for v in checks.values())
    audit = {
        "artifact_version": "Generation4AdmissionAuditV1",
        "generation_id": "acceptance-generation-4",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "head_at_admission": head,
        "seal_hash": seal["seal_hash"],
        "checks": checks,
        "gate_replay_error": gate_error,
        "admission": (
            "ADMITTED_FOR_B6" if all_pass else "WITHHELD"
        ),
        "execution_count": 0,
    }
    out = GEN4_ROOT / "generation4-admission-audit-v1.json"
    out.write_text(json.dumps(audit, indent=2, ensure_ascii=False))
    failed = [k for k, v in checks.items() if not v]
    print(json.dumps({
        "admission": audit["admission"],
        "checks_passed": sum(1 for v in checks.values() if v),
        "checks_total": len(checks),
        "failed": failed,
        "gate_replay_error": gate_error,
    }, indent=1))
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
