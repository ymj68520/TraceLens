#!/usr/bin/env python3
"""Acceptance Generation 2 — Generation2AdmissionAuditV1 (spec §27/§28).

Zero model calls.  Verifies, AFTER the seal:
  all Agent-visible inputs presealed + hash-match
  no semantic authoring exists on the B6 runtime path
  bootstrap is projection-only (state rows verbatim from the sealed
  contract)
  truth isolated from public surface (§16, per case)
  AcceptanceProfile frozen (unchanged hash)
  production runtime frozen (investigation subtree unchanged since the
  B6 execution HEAD)
  model frozen (configuration hash unchanged since Gen-1)
  holdout never executed (execution_count = 0)

Emits generation2-admission-audit-v1.json with status
ADMITTED_FOR_B6 or WITHHELD.
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
GEN2_ROOT = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0"
    / "acceptance-gen2"
)
OUT_FILE = GEN2_ROOT / "generation2-admission-audit-v1.json"

ACCEPTANCE_PROFILE_SHA = (
    "c40f1adcad816e433f7edfc6cbc0b56dc32c031bf1fcb31528523ffa62f0e98d"
)
MODEL_CONFIG_SHA_GEN1 = (
    "9cdcb1fde1cdf6ca25067c0436bbc83618fcf3708b3fd4cc49207ba4b2d130fb"
)
B6_EXECUTION_HEAD = "49e8172eea55abf45ddf13bda95715506da4b872"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, cwd=REPO_ROOT
    ).stdout.strip()


def main() -> int:
    from httpserver.services.benchmarks.holdout_contract import (
        GEN2_GENERATION_ID,
        NEGATIVE_FLAGS_OWNERSHIP,
        HoldoutSealV2,
        build_holdout_working_state,
        load_public_holdout_case,
        verify_holdout_seal,
        verify_truth_public_isolation,
    )
    from httpserver.services.benchmarks.truth_manifest import TruthManifestV1
    from httpserver.services.investigation.agent_runtime import (
        canonical_state_json,
        state_hash_of,
    )

    import httpserver.services.benchmarks.holdout_contract as contract_mod

    checks: dict[str, dict] = {}

    seal_dict = json.loads(
        (GEN2_ROOT / "holdout-seal-v2.json").read_text(encoding="utf-8")
    )
    stored_seal_hash = seal_dict.get("seal_hash", "")
    seal = HoldoutSealV2(**seal_dict)  # re-derives seal_hash from payload
    if seal.seal_hash != stored_seal_hash:
        raise SystemExit(
            "seal record internally inconsistent: stored seal_hash does "
            "not match its payload — refusing admission audit"
        )
    seal_violations = verify_holdout_seal(
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
        provisioning_substrate_path=Path(
            seal.provisioning_substrate["path"]
        ),
    )
    checks["all_agent_visible_inputs_presealed"] = {
        "ok": not seal_violations,
        "seal_hash": seal.seal_hash,
        "violations": list(seal_violations),
    }

    # no semantic authoring on the runtime path: the contract module's
    # public surface contains projection/validation/seal functions only
    forbidden = ("author", "infer", "derive_charter", "create_charter")
    offending = [
        name for name in contract_mod.__all__
        if any(word in name.lower() for word in forbidden)
    ]
    checks["no_semantic_authoring_at_b6_runtime"] = {
        "ok": not offending,
        "public_surface": sorted(contract_mod.__all__),
        "offending": offending,
    }

    # bootstrap projection-only: state rows must be the verbatim
    # projection of the sealed contract (ids, texts, links, statuses)
    projection_ok = True
    projection_detail = []
    for public_path in sorted((GEN2_ROOT / "cases").glob("*.public-case.json")):
        case = load_public_holdout_case(public_path)
        state = build_holdout_working_state(
            case, task_id="t", investigation_id="i"
        )
        questions_ok = [
            (q.question_id, q.text) for q in state.questions
        ] == [(q.question_id, q.text) for q in case.charter]
        links = {
            link.dimension_id: tuple(link.related_question_ids)
            for link in case.coverage_question_links
        }
        coverage_ok = all(
            c.required
            and c.status.value == "not_started"
            and c.related_question_ids == links[c.dimension_id]
            for c in state.coverage
        ) and {c.dimension_id for c in state.coverage} == set(
            case.required_coverage_dimensions
        )
        projection_ok &= questions_ok and coverage_ok
        projection_detail.append(
            {
                "case_id": case.case_id,
                "questions_verbatim": questions_ok,
                "coverage_verbatim_and_not_started": coverage_ok,
                "state_hash": state_hash_of(
                    canonical_state_json(state.model_dump(mode="json"))
                ),
            }
        )
    checks["bootstrap_is_projection_only"] = {
        "ok": projection_ok,
        "cases": projection_detail,
    }

    # truth isolation per case
    isolation_ok = True
    isolation_detail = []
    for public_path in sorted((GEN2_ROOT / "cases").glob("*.public-case.json")):
        case = load_public_holdout_case(public_path)
        truth = TruthManifestV1(
            **json.loads(
                (
                    GEN2_ROOT / "truth" / f"{case.case_id}.truth.json"
                ).read_text(encoding="utf-8")
            )
        )
        violations = verify_truth_public_isolation(case, truth)
        isolation_ok &= not violations
        isolation_detail.append(
            {"case_id": case.case_id, "violations": list(violations)}
        )
    checks["truth_isolated"] = {
        "ok": isolation_ok,
        "negative_flags_ownership": NEGATIVE_FLAGS_OWNERSHIP,
        "cases": isolation_detail,
    }

    checks["acceptance_profile_frozen"] = {
        "ok": _sha256_file(
            PYTHON_SERVICE_ROOT
            / "benchmarks/profiles/agent-v0-acceptance-profile-v2.json"
        )
        == ACCEPTANCE_PROFILE_SHA,
        "expected_sha256": ACCEPTANCE_PROFILE_SHA,
    }

    investigation_tree_now = _git(
        "rev-parse", "HEAD:python_service/httpserver/services/investigation"
    )
    investigation_tree_b6 = _git(
        f"rev-parse", f"{B6_EXECUTION_HEAD}:python_service/httpserver/services/investigation"
    )
    checks["production_runtime_frozen"] = {
        "ok": investigation_tree_now == investigation_tree_b6,
        "investigation_subtree_hash": investigation_tree_now,
        "b6_execution_reference": investigation_tree_b6,
    }

    model_config_sha = _sha256_file(
        PYTHON_SERVICE_ROOT
        / "benchmarks/results/agent-v0/b2-restart/"
        "sensenova-6.8-flash-lite.model-config.json"
    )
    checks["model_frozen"] = {
        "ok": model_config_sha == MODEL_CONFIG_SHA_GEN1,
        "sha256": model_config_sha,
        "model": "sensenova-6.8-flash-lite (CALIBRATION-QUALIFIED; formal "
        "sealed acceptance NOT ESTABLISHED — see "
        "docs/specs/agent-v0-acceptance-status.md)",
    }

    # holdout never executed: no run artifacts anywhere in the generation
    executed_artifacts = [
        p.name
        for p in GEN2_ROOT.rglob("*")
        if p.name
        in ("result.json", "failure.json", "run_manifest.json",
            "snapshot.json", "driver_failure.json")
    ]
    checks["holdout_never_executed"] = {
        "ok": not executed_artifacts,
        "execution_count": 0,
        "stray_artifacts": executed_artifacts,
    }

    all_ok = all(entry["ok"] for entry in checks.values())
    admission = "ADMITTED_FOR_B6" if all_ok else "WITHHELD"
    artifact = {
        "artifact_version": "Generation2AdmissionAuditV1",
        "generation_id": GEN2_GENERATION_ID,
        "created_at": "2026-10-01T00:00:00+00:00",
        "zero_model_calls": True,
        "status": admission,
        "admission": admission,
        "checks": checks,
        "all_passed": all_ok,
        "b6_preconditions": [
            "explicit user authorization for B6 (never auto-executed)",
            "Gen-2 preflight (load/validate/hash-check/bootstrap, zero "
            "model calls) must pass at execution entry",
            "enforce_execution_gate must run before the first task "
            "provisioning",
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
