"""Gen-4 seal integrity tests (§39): post-seal mutation, content-hash
drift, hydration-contract binding, and gate rejection semantics — all on the
REAL sealed artifacts (zero model calls, no provisioning).
"""

import json
from pathlib import Path

import pytest

PYTHON_SERVICE_ROOT = Path(__file__).resolve().parents[3]
GEN4_ROOT = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0"
    / "acceptance-gen4"
)
REPO_ROOT = PYTHON_SERVICE_ROOT.parent
PROFILES = PYTHON_SERVICE_ROOT / "benchmarks" / "profiles"

pytestmark = pytest.mark.skipif(
    not (GEN4_ROOT / "holdout-seal-v3.json").is_file(),
    reason="Gen-4 not sealed on this checkout",
)


def _load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _seal():
    from httpserver.services.benchmarks.holdout_contract_v3 import (
        HoldoutSealV3,
    )

    return HoldoutSealV3(**_load(GEN4_ROOT / "holdout-seal-v3.json"))


def _verify(seal):
    from httpserver.services.benchmarks.holdout_contract_v3 import (
        verify_holdout_seal_v3,
    )

    return verify_holdout_seal_v3(
        seal,
        gen3_root=GEN4_ROOT,
        profiles_dir=REPO_ROOT / "config" / "filter_profiles",
        acceptance_profile_path=PROFILES
        / "agent-v0-acceptance-profile-v2.json",
        calibration_binding_path=PROFILES
        / "calibration-evidence-binding-v3.json",
        generation_binding_path=GEN4_ROOT / "generation-4-binding-v1.json",
        runtime_investigation_subtree_hash=seal.runtime_investigation_subtree_hash,
        model_config_path=GEN4_ROOT / "gen4-model-config.json",
    )


def test_seal_verifies_against_current_artifacts():
    assert not _verify(_seal())


def test_post_seal_public_mutation_blocks(monkeypatch):
    """§39: post-seal public mutation must fail the seal verification."""
    seal = _seal()
    case_id = sorted(seal.public_case_hashes)[0]
    tampered = dict(seal.public_case_hashes)
    tampered[case_id] = "0" * 64
    forged = seal.model_copy(
        update={"public_case_hashes": tampered}, deep=True
    )
    violations = _verify(forged)
    assert any("public" in v.lower() or "case" in v.lower() for v in violations)


def test_content_hash_drift_blocks():
    """§39: a sealed manifest whose per-file content sha256 drifted no
    longer matches the seal's manifest hash (content hashes are sealed
    inputs, §12)."""
    seal = _seal()
    case_id = sorted(seal.evidence_manifest_hashes)[0]
    manifest = _load(
        GEN4_ROOT / "substrates" / f"{case_id}.evidence-manifest.json"
    )
    drifted = json.loads(json.dumps(manifest))
    drifted["entries"][0]["sha256"] = "f" * 64
    from httpserver.services.benchmarks.holdout_contract_v3 import (
        SealedEvidenceManifestV1,
    )

    drifted_model = SealedEvidenceManifestV1(**drifted)
    assert drifted_model.input_hash != seal.evidence_manifest_hashes[case_id]


def test_sealed_content_hashes_cover_every_entry():
    """§12: content is a sealed input — every manifest entry carries a
    content sha256 and the hydration proofs matched each of them."""
    for manifest_path in sorted(GEN4_ROOT.glob("substrates/*.evidence-manifest.json")):
        manifest = _load(manifest_path)
        assert manifest["entries"]
        for entry in manifest["entries"]:
            assert len(entry["sha256"]) == 64
        case_id = manifest["case_id"]
        pre = _load(GEN4_ROOT / f"hydration-preseal-{case_id}-pre.json")
        sealed = {
            entry["expected_evidence_key"]: entry["sha256"]
            for entry in manifest["entries"]
        }
        hydrated = {
            i["evidence_key"]: i["sha256"] for i in pre["first_read"]["items"]
        }
        assert hydrated == sealed


def test_generation_binding_binds_hydration_contract():
    """§33: the seal binds the hydration contract + store implementation
    transitively via the generation binding."""
    import hashlib

    binding = _load(GEN4_ROOT / "generation-4-binding-v1.json")
    seal = _seal()
    assert seal.acceptance_profile_generation_binding_sha256 == hashlib.sha256(
        (GEN4_ROOT / "generation-4-binding-v1.json").read_bytes()
    ).hexdigest()
    assert binding["content_hydration"]["contract"] == (
        "evidence-content-hydration:v1 (FROZEN d213145d)"
    )
    current_store = hashlib.sha256(
        (
            PYTHON_SERVICE_ROOT
            / "httpserver/services/evidence/content_store.py"
        ).read_bytes()
    ).hexdigest()
    assert binding["content_hydration"]["content_store_sha256"] == current_store


def test_admission_audit_admitted_and_execution_count_zero():
    audit = _load(GEN4_ROOT / "generation4-admission-audit-v1.json")
    assert audit["admission"] == "ADMITTED_FOR_B6"
    assert audit["execution_count"] == 0
    assert all(audit["checks"].values())
