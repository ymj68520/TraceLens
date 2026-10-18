#!/usr/bin/env python3
"""Generation-2 B6 §2 deterministic execution preflight.

ZERO model calls.  Runs the full frozen gate chain BEFORE the first
model request:

  seal verification (public cases + assets + truth + bootstrap transform
    + evaluator + AcceptanceProfileV2 + calibration binding + substrate)
  frozen identity checks (runtime subtree, model config, profile hashes)
  per case: sealed load -> hash-check -> frozen bootstrap projection ->
  AttentionBuilder preflight (valid + deterministic, declared links
  verbatim, no duplicate question×scope topology)

Writes HoldoutBootstrapPreflightV2 (hash-linked to the seal).  Any
failure exits non-zero => BENCHMARK_PREFLIGHT_BLOCKED with execution
count 0; the Gen-2 driver refuses to start without this artifact.
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
OUT_FILE = GEN2_ROOT / "holdout-bootstrap-preflight-v2.json"

ACCEPTANCE_PROFILE_SHA = (
    "c40f1adcad816e433f7edfc6cbc0b56dc32c031bf1fcb31528523ffa62f0e98d"
)
CALIBRATION_BINDING_SHA = (
    "e2c35c4e0fa744a5aa49a9b4b4ac1ec990999107ea1ac4eafa7e41645f94c038"
)
MODEL_CONFIG_SHA = (
    "9cdcb1fde1cdf6ca25067c0436bbc83618fcf3708b3fd4cc49207ba4b2d130fb"
)
GEN1_B6_RUNTIME_HEAD = "49e8172eea55abf45ddf13bda95715506da4b872"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, cwd=REPO_ROOT
    ).stdout.strip()


def main() -> int:
    from httpserver.services.benchmarks.holdout_contract import (
        HoldoutSealV2,
        build_holdout_working_state,
        enforce_execution_gate,
        load_public_holdout_case,
        verify_holdout_seal,
    )
    from httpserver.services.investigation.agent_attention import (
        AttentionBuilder,
    )
    from httpserver.services.investigation.agent_runtime import (
        canonical_state_json,
        state_hash_of,
    )

    failures: list[str] = []

    seal_dict = json.loads(
        (GEN2_ROOT / "holdout-seal-v2.json").read_text(encoding="utf-8")
    )
    stored_hash = seal_dict.get("seal_hash", "")
    seal = HoldoutSealV2(**seal_dict)
    if seal.seal_hash != stored_hash:
        failures.append("seal record internally inconsistent")

    seal_kwargs = dict(
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
    seal_violations = verify_holdout_seal(seal, **seal_kwargs)
    if seal_violations:
        failures.extend(seal_violations)

    # §2 frozen identity checks
    profile_sha = _sha256_file(
        PYTHON_SERVICE_ROOT
        / "benchmarks/profiles/agent-v0-acceptance-profile-v2.json"
    )
    if profile_sha != ACCEPTANCE_PROFILE_SHA:
        failures.append("AcceptanceProfileV2 hash drifted")
    binding_sha = _sha256_file(
        PYTHON_SERVICE_ROOT
        / "benchmarks/profiles/calibration-evidence-binding-v2.json"
    )
    if binding_sha != CALIBRATION_BINDING_SHA:
        failures.append("CalibrationEvidenceBindingV2 hash drifted")
    model_sha = _sha256_file(
        PYTHON_SERVICE_ROOT
        / "benchmarks/results/agent-v0/b2-restart/"
        "sensenova-6.8-flash-lite.model-config.json"
    )
    if model_sha != MODEL_CONFIG_SHA:
        failures.append("model configuration hash drifted")
    inv_tree_now = _git(
        "rev-parse", "HEAD:python_service/httpserver/services/investigation"
    )
    inv_tree_ref = _git(
        "rev-parse",
        f"{GEN1_B6_RUNTIME_HEAD}:python_service/httpserver/services/investigation",
    )
    if inv_tree_now != inv_tree_ref:
        failures.append("production runtime (investigation subtree) drifted")

    # §2 per-case: sealed load -> frozen bootstrap -> attention preflight
    builder = AttentionBuilder()
    case_results = []
    for public_path in sorted((GEN2_ROOT / "cases").glob("*.public-case.json")):
        case_id = public_path.stem.replace(".public-case", "")
        checks: dict[str, bool] = {}
        try:
            case = load_public_holdout_case(public_path)
            checks["sealed_public_case_loads"] = (
                case.input_hash == seal.public_case_hashes[case_id]
            )
        except Exception as exc:
            failures.append(f"{case_id}: sealed load failed: {exc}")
            case_results.append({"case_id": case_id, "ok": False})
            continue

        states = [
            build_holdout_working_state(
                case, task_id="t", investigation_id="i"
            )
            for _ in range(2)
        ]
        state_hashes = {
            state_hash_of(canonical_state_json(s.model_dump(mode="json")))
            for s in states
        }
        checks["bootstrap_deterministic"] = len(state_hashes) == 1
        links = {
            link.dimension_id: tuple(link.related_question_ids)
            for link in case.coverage_question_links
        }
        checks["links_verbatim_required_not_started"] = all(
            c.required
            and c.status.value == "not_started"
            and c.related_question_ids == links[c.dimension_id]
            for c in states[0].coverage
        )
        checks["questions_verbatim_from_charter"] = [
            (q.question_id, q.text) for q in states[0].questions
        ] == [(q.question_id, q.text) for q in case.charter]

        attention_runs = [
            builder.build_full_set(state, state_revision=1)
            for state in states
        ]
        item_id_lists = [
            [item.item_id for item in attention.items]
            for attention in attention_runs
        ]
        checks["attention_deterministic"] = (
            item_id_lists[0] == item_id_lists[1]
        )
        checks["no_standalone_coverage_item"] = not any(
            i.startswith("coverage:") for i in item_id_lists[0]
        )
        delegable_refs = []
        for item in attention_runs[0].items:
            if any(
                a.value in ("delegate_source", "delegate_investigation")
                for a in getattr(item, "eligible_action_types", ())
            ):
                refs = tuple(
                    getattr(item, "related_question_ids", ()) or ()
                )
                delegable_refs.extend(refs or (item.item_id,))
        checks["no_duplicate_question_scope_topology"] = (
            len(delegable_refs) == len(set(delegable_refs))
        )

        ok = all(checks.values())
        if not ok:
            failures.append(f"{case_id}: preflight checks failed")
        case_results.append(
            {
                "case_id": case_id,
                "case_family": case.case_family,
                "public_input_hash": case.input_hash,
                "seed_state_hash": sorted(state_hashes)[0],
                "attention_item_ids": item_id_lists[0],
                "checks": checks,
                "ok": ok,
            }
        )
        print(f"{case_id:34s} {'PASS' if ok else 'FAIL'} "
              f"| attention: {item_id_lists[0]}")

    # §2: the execution gate itself (refuses on ANY violation)
    try:
        enforce_execution_gate(seal, **seal_kwargs)
        gate_ok = True
    except Exception as exc:
        gate_ok = False
        failures.append(f"execution gate: {exc}")

    all_ok = not failures and gate_ok
    artifact = {
        "artifact_version": "HoldoutBootstrapPreflightV2",
        "generation_id": "acceptance-generation-2",
        "created_at": "2026-10-01T00:00:00+00:00",
        "zero_model_calls": True,
        "seal_hash": seal.seal_hash,
        "frozen_identities": {
            "git_head": _git("rev-parse", "HEAD"),
            "investigation_subtree_hash": inv_tree_now,
            "acceptance_profile_sha256": profile_sha,
            "calibration_binding_sha256": binding_sha,
            "model_config_sha256": model_sha,
            "bootstrap_transform_sha256": seal.bootstrap_transform[
                "code_sha256"
            ],
            "evaluator_sha256": seal.evaluator["code_sha256"],
        },
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
    GEN2_ROOT.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"preflight -> {OUT_FILE}")
    print("ALL PASS" if all_ok else "PREFLIGHT FAILED -> "
          "BENCHMARK_PREFLIGHT_BLOCKED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
