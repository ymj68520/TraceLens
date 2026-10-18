#!/usr/bin/env python3
"""Gen-3 B6 §2-§5: frozen inputs + final zero-model preflight.

Produces:
  gen3-b6-frozen-inputs-v1.json   Gen3B6FrozenInputsV1 (§2: every frozen
                                  identity hash, recorded BEFORE the
                                  first model request)
  holdout-bootstrap-preflight-v3.json  HoldoutBootstrapPreflightV3
                                  (§3: seal verification, substrate
                                  image hashes, REAL provisioning +
                                  parsing ×2, evidence-world digests,
                                  expected keys, unexpected-evidence
                                  check, bootstrap projection,
                                  coverage/question association,
                                  attention preflight, and
                                  enforce_execution_gate_v3)

ZERO model calls (provisioning uses the LLM-disabled task lifecycle).
Any failure exits non-zero => BENCHMARK_PREFLIGHT_BLOCKED with
execution_count 0; the Gen-3 driver refuses to start without this
artifact.
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
PREFLIGHT_FILE = GEN3_ROOT / "holdout-bootstrap-preflight-v3.json"
FROZEN_INPUTS_FILE = GEN3_ROOT / "gen3-b6-frozen-inputs-v1.json"
MODEL_CONFIG = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0"
    / "b2-restart" / "sensenova-6.8-flash-lite.model-config.json"
)

ACCEPTANCE_PROFILE_SHA = (
    "c40f1adcad816e433f7edfc6cbc0b56dc32c031bf1fcb31528523ffa62f0e98d"
)
CALIBRATION_BINDING_SHA = (
    "e2c35c4e0fa744a5aa49a9b4b4ac1ec990999107ea1ac4eafa7e41645f94c038"
)
GENERATION_BINDING_SHA = hashlib.sha256(
    (
        PYTHON_SERVICE_ROOT
        / "benchmarks/profiles/acceptance-profile-generation-binding-v3.json"
    ).read_bytes()
).hexdigest()
MODEL_CONFIG_SHA = (
    "9cdcb1fde1cdf6ca25067c0436bbc83618fcf3708b3fd4cc49207ba4b2d130fb"
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
        enforce_execution_gate_v3,
        parser_config_hash,
        provision_and_digest,
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

    failures: list[str] = []

    seal_dict = json.loads(
        (GEN3_ROOT / "holdout-seal-v3.json").read_text(encoding="utf-8")
    )
    stored = seal_dict.get("seal_hash", "")
    seal = HoldoutSealV3(**seal_dict)
    if seal.seal_hash != stored:
        failures.append("seal record internally inconsistent")

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
        model_config_path=MODEL_CONFIG,
    )
    seal_violations = verify_holdout_seal_v3(seal, **gate_kwargs)
    if seal_violations:
        failures.extend(seal_violations)

    # --- frozen identities (§2)
    frozen_inputs = {
        "artifact_version": "Gen3B6FrozenInputsV1",
        "generation_id": "acceptance-generation-3",
        "recorded_before_first_model_request": True,
        "git_head": _git("rev-parse", "HEAD"),
        # cleanliness scope = the freeze surface (production + config
        # code); benchmark result artifacts are written by this preflight
        # itself and are expected to be untracked at entry
        "worktree_clean": _git(
            "status", "--porcelain",
            "--", "python_service/httpserver", "config", ".env",
        )
        == "",
        "runtime_investigation_subtree_hash": gate_kwargs[
            "runtime_investigation_subtree_hash"
        ],
        "model": {
            "provider": "sensenova-cloud",
            "model_id": "sensenova-6.8-flash-lite",
            "config_sha256": _sha256_file(MODEL_CONFIG),
        },
        "acceptance_profile_sha256": _sha256_file(
            gate_kwargs["acceptance_profile_path"]
        ),
        "calibration_binding_sha256": _sha256_file(
            gate_kwargs["calibration_binding_path"]
        ),
        "generation_binding_sha256": _sha256_file(
            gate_kwargs["generation_binding_path"]
        ),
        "admission_audit_superseding_record_sha256": _sha256_file(
            GEN3_ROOT
            / "generation3-admission-audit-v1-superseding-record.json"
        ),
        "seal_hash": seal.seal_hash,
        "parser_config_hash": parser_config_hash(
            gate_kwargs["profiles_dir"]
        ),
        "bootstrap_transform_sha256": seal.bootstrap_transform[
            "code_sha256"
        ],
        "evaluator_sha256": seal.evaluator["code_sha256"],
        "public_case_hashes": dict(seal.public_case_hashes),
        "truth_hashes": {
            cid: h["truth_manifest_input_hash"]
            for cid, h in seal.truth_hashes.items()
        },
        "substrate_image_hashes": {
            cid: h["image_sha256"]
            for cid, h in seal.evidence_substrate_hashes.items()
        },
        "evidence_manifest_hashes": dict(seal.evidence_manifest_hashes),
        "evidence_world_digests": dict(seal.evidence_world_digests),
        "population": {
            "families": sorted(seal.public_case_hashes),
            "repetitions_per_family": 3,
            "scheduled_runs": 6,
        },
    }
    expected_shas = {
        "acceptance_profile": (
            frozen_inputs["acceptance_profile_sha256"],
            ACCEPTANCE_PROFILE_SHA,
        ),
        "calibration_binding": (
            frozen_inputs["calibration_binding_sha256"],
            CALIBRATION_BINDING_SHA,
        ),
        "generation_binding": (
            frozen_inputs["generation_binding_sha256"],
            GENERATION_BINDING_SHA,
        ),
        "model_config": (
            frozen_inputs["model"]["config_sha256"],
            MODEL_CONFIG_SHA,
        ),
    }
    for name, (actual, expected) in expected_shas.items():
        if actual != expected:
            failures.append(f"frozen identity drift: {name}")
    if not frozen_inputs["worktree_clean"]:
        failures.append("worktree not clean at B6 entry")

    # --- per-case §3 chain
    builder = AttentionBuilder()
    case_results = []
    world_digests = {}
    world_keys = {}
    world_files = {}
    for case_id in sorted(seal.public_case_hashes):
        checks: dict[str, bool] = {}
        case = load_public_holdout_case(
            GEN3_ROOT / "cases" / f"{case_id}.public-case.json"
        )
        checks["sealed_public_case_loads"] = (
            case.input_hash == seal.public_case_hashes[case_id]
        )
        truth = TruthManifestV1(
            **json.loads(
                (GEN3_ROOT / "truth" / f"{case_id}.truth.json").read_text(
                    encoding="utf-8"
                )
            )
        )
        checks["truth_public_isolation"] = not (
            verify_truth_public_isolation(case, truth)
        )

        # bootstrap + association + attention
        states = [
            build_holdout_working_state(
                case, task_id="t", investigation_id="i"
            )
            for _ in range(2)
        ]
        links = {
            link.dimension_id: tuple(link.related_question_ids)
            for link in case.coverage_question_links
        }
        checks["bootstrap_association_verbatim"] = all(
            c.required
            and c.status.value == "not_started"
            and c.related_question_ids == links[c.dimension_id]
            for c in states[0].coverage
        ) and [
            (q.question_id, q.text) for q in states[0].questions
        ] == [(q.question_id, q.text) for q in case.charter]
        attention_runs = [
            builder.build_full_set(s, state_revision=1).items
            for s in states
        ]
        item_ids = [[i.item_id for i in items] for items in attention_runs]
        checks["attention_deterministic_folded"] = (
            item_ids[0] == item_ids[1]
            and not any(i.startswith("coverage:") for i in item_ids[0])
        )

        # §3/§4: REAL provisioning + parsing, twice; digest vs seal
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
        equivalence = None
        try:
            equivalence = provisioning_equivalence_check(
                substrate,
                manifest,
                seal.evidence_world_digests[case_id],
                images_dir=GEN3_ROOT / "images",
            )
            checks["evidence_world_digest_match_x2"] = (
                equivalence["ok"]
                and len(set(equivalence["digests"])) == 1
            )
        except Exception as exc:
            checks["evidence_world_digest_match_x2"] = False
            failures.append(f"{case_id}: provisioning failed: {exc}")
        world_digests[case_id] = seal.evidence_world_digests[case_id]
        # use the sealed expectation as the gate's world identity; the
        # live equivalence above just proved a fresh provision matches it
        world_keys[case_id] = {
            e.expected_evidence_key for e in manifest.entries
        }
        world_files[case_id] = {
            e.normalized_path.lstrip("/") for e in manifest.entries
        }
        ok = all(checks.values())
        if not ok:
            failures.append(f"{case_id}: preflight checks failed")
        case_results.append(
            {
                "case_id": case_id,
                "case_family": case.case_family,
                "substrate_id": substrate.substrate_id,
                "image_sha256": substrate.image_sha256,
                "checks": checks,
                "provisioning": (
                    {
                        "digests": equivalence["digests"],
                        "violations": equivalence["violations"],
                    }
                    if equivalence
                    else {"error": "not executed"}
                ),
                "ok": ok,
            }
        )
        print(f"{case_id:28s} {'PASS' if ok else 'FAIL'}")

    # --- §3/§4/§20: the execution gate itself
    gate_ok = True
    try:
        enforce_execution_gate_v3(
            seal,
            **gate_kwargs,
            evidence_world_digests=world_digests,
            evidence_world_keys=world_keys,
            evidence_world_files=world_files,
        )
    except Exception as exc:
        gate_ok = False
        failures.append(f"execution gate: {exc}")

    all_ok = not failures and gate_ok
    frozen_inputs["input_hash"] = state_hash_of(
        canonical_state_json(
            {
                k: v
                for k, v in frozen_inputs.items()
                if k != "input_hash"
            }
        )
    )
    FROZEN_INPUTS_FILE.write_text(
        json.dumps(frozen_inputs, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    artifact = {
        "artifact_version": "HoldoutBootstrapPreflightV3",
        "generation_id": "acceptance-generation-3",
        "created_at": "2026-10-01T00:00:00+00:00",
        "zero_model_calls": True,
        "seal_hash": seal.seal_hash,
        "frozen_inputs_ref": "gen3-b6-frozen-inputs-v1.json",
        "frozen_inputs_input_hash": frozen_inputs["input_hash"],
        "cases": case_results,
        "execution_gate_passed": gate_ok,
        "failures": failures,
        "all_passed": all_ok,
    }
    artifact["input_hash"] = state_hash_of(
        canonical_state_json(
            {k: v for k, v in artifact.items() if k != "input_hash"}
        )
    )
    PREFLIGHT_FILE.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"frozen inputs -> {FROZEN_INPUTS_FILE}")
    print(f"preflight -> {PREFLIGHT_FILE}")
    print("ALL PASS" if all_ok else "PREFLIGHT FAILED -> "
          "BENCHMARK_PREFLIGHT_BLOCKED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
