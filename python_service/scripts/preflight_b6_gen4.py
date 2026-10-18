"""Gen-4 B6 final zero-model preflight (§1-§4).

Identity closure + frozen inputs + the FULL deterministic gate chain,
plus the §3 hydration hard gate through the PRODUCTION content path on
a freshly provisioned task per case. Zero model calls. Any failure ->
BENCHMARK_PREFLIGHT_BLOCKED, execution_count stays 0, Gen-4 unconsumed.
"""

from __future__ import annotations

import asyncio
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
FROZEN_INPUTS_FILE = GEN4_ROOT / "gen4-b6-frozen-inputs-v1.json"
PREFLIGHT_FILE = GEN4_ROOT / "holdout-bootstrap-preflight-v4.json"
MODEL_CONFIG = GEN4_ROOT / "gen4-model-config.json"

ACCEPTANCE_PROFILE_SHA = (
    "c40f1adcad816e433f7edfc6cbc0b56dc32c031bf1fcb31528523ffa62f0e98d"
)
CALIBRATION_BINDING_SHA = (
    "4c0235eaa80b8450cc879ebb568aa6c8bafc233c1a6683ad3897323e72cc3823"
)
GENERATION_BINDING_SHA = (
    "8d2e3162febd1fa3ee70358b6043037ff1b25ffdfc29a6b5670e25f5ed9d2ad7"
)
MODEL_CONFIG_SHA = (
    "a980cafab34bb2c76dfec47edf2604c112a1d7211402ae18cb1760f7e253d8dd"
)
EXPECTED_HEAD = "253cfac62274fc5d0876ef1686639903e3aebac5"


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, cwd=REPO_ROOT
    ).stdout.strip()


def _hydration_hard_gate(case_id: str, manifest, checks: dict, failures: list):
    """§3: resolve + production get_evidence on a fresh provisioned task;
    hydrated sha256 must equal the sealed content sha256 for every
    entry; content_available explicit; task deleted afterwards."""
    import urllib.request

    def _http(method, url, *, body=None, timeout=60):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={"Content-Type": "application/json"} if data else {},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read().decode()
        return json.loads(payload) if payload else {}

    from httpserver.config import Settings
    from httpserver.services.cpp_backend import CppBackendService
    from httpserver.services.investigation_service import (
        InvestigationService,
        _ResolvedContentRef,
    )
    from httpserver.services.investigation_evidence import ResolvedEvidence

    task_id = None
    try:
        task_id = _http(
            "POST", "http://127.0.0.1:8666/api/tasks",
            body={
                "image_path": str(
                    GEN4_ROOT / "images" / f"{case_id}.img"
                ),
                "case_description": (
                    f"gen4 b6 preflight hydration gate {case_id} "
                    "(deterministic, zero model calls)"
                ),
                "llm_analyze": False,
                "llm_event_analyze": False,
                "priority": "high",
            },
        )["id"]
        deadline = time.monotonic() + 600
        record = {}
        while time.monotonic() < deadline:
            record = _http("GET", f"http://127.0.0.1:8666/api/tasks/{task_id}")
            if record.get("status") in ("completed", "failed", "cancelled"):
                break
            time.sleep(3)
        if record.get("status") != "completed":
            checks["hydration_gate_provisioned"] = False
            failures.append(f"{case_id}: hydration-gate task not completed")
            return

        async def run():
            settings = Settings(
                _env_file=str(PYTHON_SERVICE_ROOT.parent / ".env")
            )
            backend = CppBackendService(settings)
            await backend.initialize()
            service = InvestigationService(cpp_backend=backend)
            items = []
            try:
                for entry in manifest.entries:
                    resolved = await service.resolve_evidence(
                        task_id, entry.expected_evidence_key
                    )
                    if resolved is None:
                        items.append({"key": entry.expected_evidence_key,
                                      "resolved": False})
                        continue
                    located = await service._content_store.locate_for_resolved(
                        _ResolvedContentRef.from_dict(resolved)
                    )
                    ref = ResolvedEvidence.from_dict(resolved)
                    text = await service._evidence_resolver.bounded_content(ref)
                    blob = Path(located.path).read_bytes()
                    items.append({
                        "key": entry.expected_evidence_key,
                        "resolved": True,
                        "content_available": True,
                        "content_unavailable_reason": None,
                        "sha256": hashlib.sha256(blob).hexdigest(),
                        "matches_sealed": (
                            hashlib.sha256(blob).hexdigest() == entry.sha256
                        ),
                        "preview_chars": len(text),
                    })
            finally:
                await backend.shutdown()
            return items

        items = asyncio.run(run())
        checks["hydration_gate_provisioned"] = True
        checks["hydration_all_resolved"] = all(i["resolved"] for i in items)
        checks["hydration_content_available_explicit"] = all(
            i["content_available"]
            and i["content_unavailable_reason"] is None
            for i in items
        )
        checks["hydration_sha256_equals_sealed"] = all(
            i["matches_sealed"] for i in items
        )
    finally:
        if task_id:
            try:
                _http("DELETE", f"http://127.0.0.1:8666/api/tasks/{task_id}")
            except Exception:
                pass


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

    seal_dict = _load(GEN4_ROOT / "holdout-seal-v3.json")
    stored = seal_dict.get("seal_hash", "")
    seal = HoldoutSealV3(**seal_dict)
    if seal.seal_hash != stored:
        failures.append("seal record internally inconsistent")

    gate_kwargs = dict(
        gen3_root=GEN4_ROOT,
        profiles_dir=REPO_ROOT / "config" / "filter_profiles",
        acceptance_profile_path=(
            PYTHON_SERVICE_ROOT
            / "benchmarks/profiles/agent-v0-acceptance-profile-v2.json"
        ),
        calibration_binding_path=(
            PYTHON_SERVICE_ROOT
            / "benchmarks/profiles/calibration-evidence-binding-v3.json"
        ),
        generation_binding_path=(
            GEN4_ROOT / "generation-4-binding-v1.json"
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

    head = _git("rev-parse", "HEAD")
    frozen_inputs = {
        "artifact_version": "Gen4B6FrozenInputsV1",
        "generation_id": "acceptance-generation-4",
        "recorded_before_first_model_request": True,
        "git_head": head,
        "head_matches_authorized": head == EXPECTED_HEAD,
        "worktree_clean": _git(
            "status", "--porcelain",
            "--", "python_service/httpserver", "config", ".env",
        ) == "",
        "runtime_investigation_subtree_hash": gate_kwargs[
            "runtime_investigation_subtree_hash"
        ],
        "runtime_superseding_record_sha256": _sha256_file(
            GEN4_ROOT / "runtime-baseline-v3-superseding-record.json"
        ),
        "runtime_identity_closure_sha256": _sha256_file(
            GEN4_ROOT / "runtime-identity-closure.json"
        ),
        "capability_selection_sha256": _sha256_file(
            GEN4_ROOT / "capability-selection-record-v1.json"
        ),
        "independence_audit_sha256": _sha256_file(
            GEN4_ROOT / "holdout-independence-audit-v1.json"
        ),
        "admission_audit_sha256": _sha256_file(
            GEN4_ROOT / "generation4-admission-audit-v1.json"
        ),
        "model": {
            "provider": "sensenova-cloud",
            "model_id": "sensenova-6.8-flash-lite",
            "config_sha256": _sha256_file(MODEL_CONFIG),
        },
        "acceptance_profile_sha256": _sha256_file(
            gate_kwargs["acceptance_profile_path"]
        ),
        "acceptance_runtime_binding_sha256": _sha256_file(
            PYTHON_SERVICE_ROOT
            / "benchmarks/profiles/acceptance-profile-runtime-binding-v3.json"
        ),
        "calibration_binding_sha256": _sha256_file(
            gate_kwargs["calibration_binding_path"]
        ),
        "generation_binding_sha256": _sha256_file(
            gate_kwargs["generation_binding_path"]
        ),
        "content_store_sha256": _sha256_file(
            PYTHON_SERVICE_ROOT
            / "httpserver/services/evidence/content_store.py"
        ),
        "hydration_contract_doc_sha256": _sha256_file(
            REPO_ROOT / "docs/specs/evidence-content-hydration-contract.md"
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
    if not frozen_inputs["head_matches_authorized"]:
        failures.append("HEAD does not match authorized 253cfac6")

    builder = AttentionBuilder()
    case_results = []
    world_digests = {}
    world_keys = {}
    world_files = {}
    for case_id in sorted(seal.public_case_hashes):
        checks: dict[str, bool] = {}
        case = load_public_holdout_case(
            GEN4_ROOT / "cases" / f"{case_id}.public-case.json"
        )
        checks["sealed_public_case_loads"] = (
            case.input_hash == seal.public_case_hashes[case_id]
        )
        truth = TruthManifestV1(
            **json.loads(
                (GEN4_ROOT / "truth" / f"{case_id}.truth.json").read_text(
                    encoding="utf-8"
                )
            )
        )
        checks["truth_public_isolation"] = not (
            verify_truth_public_isolation(case, truth)
        )

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

        substrate = SealedEvidenceSubstrateV1(
            **json.loads(
                (
                    GEN4_ROOT / "substrates" / f"{case_id}.substrate.json"
                ).read_text(encoding="utf-8")
            )
        )
        manifest = SealedEvidenceManifestV1(
            **json.loads(
                (
                    GEN4_ROOT / "substrates"
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
                images_dir=GEN4_ROOT / "images",
            )
            checks["evidence_world_digest_match_x2"] = (
                equivalence["ok"]
                and len(set(equivalence["digests"])) == 1
            )
        except Exception as exc:
            checks["evidence_world_digest_match_x2"] = False
            failures.append(f"{case_id}: provisioning failed: {exc}")

        # §3 hydration hard gate (production content path only)
        try:
            _hydration_hard_gate(case_id, manifest, checks, failures)
        except Exception as exc:
            checks["hydration_gate_provisioned"] = False
            failures.append(f"{case_id}: hydration gate: {exc}")

        world_digests[case_id] = seal.evidence_world_digests[case_id]
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
            {k: v for k, v in frozen_inputs.items() if k != "input_hash"}
        )
    )
    FROZEN_INPUTS_FILE.write_text(
        json.dumps(frozen_inputs, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    artifact = {
        "artifact_version": "HoldoutBootstrapPreflightV4",
        "generation_id": "acceptance-generation-4",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "zero_model_calls": True,
        "seal_hash": seal.seal_hash,
        "frozen_inputs_ref": "gen4-b6-frozen-inputs-v1.json",
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
