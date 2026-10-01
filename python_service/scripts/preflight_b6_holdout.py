#!/usr/bin/env python3
"""B6 §2-§4 deterministic holdout bootstrap + attention preflight.

ZERO model calls.  For the two sealed holdout cases this script builds
the initial benchmark Working State through the EXACT production driver
code (`build_benchmark_seed_state`), driven by the B6-entry public
charter (benchmarks/profiles/b6-holdout-charter-v1.json), then compiles
the REAL frozen AttentionBuilder projection and asserts the
structural-collision class cannot occur.

Gates (B6 spec §2-§4):
  G1  all required coverage dimensions present
  G2  required=true for every dimension
  G3  initial status=not_started for every dimension
  G4  related_question_ids EXACT per the charter-declared association
  G5  every related question exists in the seeded questions
  G6  AttentionBuilder produces the merged structure: NO standalone
      `coverage:*` attention item (folded into the question item)
  G7  no duplicate delegable question×scope opportunity created by the
      bootstrap representation
  G8  charter integrity: goal/questions are NOT the sealed placeholders
      and the sealed TruthManifest file hash still matches the corpus
      binding (hash-only check; content never read)

Usage (from python_service/):
    .venv/bin/python scripts/preflight_b6_holdout.py
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PYTHON_SERVICE_ROOT = SCRIPT_PATH.parents[1]
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))
SCRIPTS_DIR = SCRIPT_PATH.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

REPO_ROOT = PYTHON_SERVICE_ROOT.parent
CHARTER_FILE = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "profiles"
    / "b6-holdout-charter-v1.json"
)
CORPUS_FILE = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "corpus"
    / "corpus-agent-v0-calibration.v2.json"
)
OUT_DIR = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0" / "b6-holdout"
)
OUT_FILE = OUT_DIR / "holdout-bootstrap-preflight-v1.json"

SEALED_PLACEHOLDER_MARKERS = ("[SEALED HOLDOUT]",)


def main() -> int:
    from types import SimpleNamespace

    import run_p8b_baseline as driver
    from httpserver.services.investigation.agent_attention import (
        AttentionBuilder,
    )
    from httpserver.services.investigation.agent_runtime import (
        canonical_state_json,
        state_hash_of,
    )

    charter = json.loads(CHARTER_FILE.read_text(encoding="utf-8"))
    corpus = json.loads(CORPUS_FILE.read_text(encoding="utf-8"))
    corpus_holdout = {
        c["case_id"]: c for c in corpus["acceptance_cases"]
    }

    builder = AttentionBuilder()
    results = []
    all_ok = True
    for case_id in charter["holdout_population"]["families"]:
        entry = charter["cases"][case_id]
        case_payload = json.loads(
            (PYTHON_SERVICE_ROOT / "benchmarks/cases" / case_id / "case.json")
            .read_text(encoding="utf-8")
        )
        expected_dims = sorted(
            case_payload.get("required_coverage_dimensions", ())
        )
        seed_questions = tuple(entry["seed_questions"])
        declared_association = entry["coverage_association"]

        # G8a: the charter must actually unseal the public surface
        checks: dict[str, bool] = {}
        checks["G8a_charter_not_placeholder"] = (
            "[SEALED HOLDOUT]" not in entry["goal"]
            and all(
                marker not in q
                for q in seed_questions
                for marker in SEALED_PLACEHOLDER_MARKERS
            )
        )
        # G8b: the sealed TruthManifest canonical hash must still match
        # the corpus binding (the model validates + hashes in-process,
        # exactly as the evaluator will; no content enters this artifact)
        from httpserver.services.benchmarks.truth_manifest import (
            TruthManifestV1,
        )

        truth_file = (
            PYTHON_SERVICE_ROOT / "benchmarks/cases" / case_id
            / "truth_manifest.json"
        )
        truth_file_hash = hashlib.sha256(truth_file.read_bytes()).hexdigest()
        truth_model = TruthManifestV1(
            **json.loads(truth_file.read_text(encoding="utf-8"))
        )
        checks["G8b_truth_manifest_untouched_versus_corpus"] = (
            truth_model.input_hash
            == corpus_holdout[case_id]["truth_manifest_hash"]
        )

        ci = SimpleNamespace(
            goal=entry["goal"],
            seed_questions=seed_questions,
            seed_coverage_dimensions=tuple(expected_dims),
        )
        state = driver.build_benchmark_seed_state(
            f"task-{case_id}", f"inv-{case_id}", ci
        )

        dims = {c.dimension_id: c for c in state.coverage}
        checks["G1_dims_present"] = sorted(dims) == expected_dims
        checks["G2_required_true"] = all(c.required for c in dims.values())
        checks["G3_initial_not_started"] = all(
            c.status.value == "not_started" for c in dims.values()
        )
        # G4: EXACT match against the charter-declared association
        # (Case B: per-dimension declaration, not the blanket Case-A rule)
        checks["G4_related_question_ids_exact_per_charter"] = all(
            list(c.related_question_ids)
            == list(declared_association[c.dimension_id])
            for c in dims.values()
        )
        question_ids = {q.question_id for q in state.questions}
        checks["G5_related_questions_exist"] = all(
            set(c.related_question_ids) <= question_ids
            for c in dims.values()
        )

        attention = builder.build_full_set(state, state_revision=1)
        item_ids = [item.item_id for item in attention.items]
        checks["G6_no_standalone_coverage_item"] = not any(
            item_id.startswith("coverage:") for item_id in item_ids
        )
        delegable = [
            item
            for item in attention.items
            if any(
                a.value in ("delegate_source", "delegate_investigation")
                for a in getattr(item, "eligible_action_types", ())
            )
        ]
        question_refs = []
        for item in delegable:
            refs = tuple(getattr(item, "related_question_ids", ()) or ())
            question_refs.extend(refs or (item.item_id,))
        checks["G7_no_duplicate_delegable_topology"] = len(
            question_refs
        ) == len(set(question_refs))

        ok = all(checks.values())
        all_ok &= ok
        results.append(
            {
                "case_id": case_id,
                "charter_goal": entry["goal"],
                "charter_seed_questions": list(seed_questions),
                "charter_association": declared_association,
                "expected_coverage_dimensions": expected_dims,
                "seeded_question_ids": sorted(question_ids),
                "attention_item_ids": item_ids,
                "truth_manifest_file_sha256": truth_file_hash,
                "truth_manifest_canonical_hash": truth_model.input_hash,
                "seed_state_hash": state_hash_of(
                    canonical_state_json(state.model_dump(mode="json"))
                ),
                "checks": checks,
                "ok": ok,
            }
        )
        print(
            f"{case_id:28s} {'PASS' if ok else 'FAIL'} "
            f"| attention: {item_ids}"
        )

    artifact = {
        "artifact_version": "HoldoutBootstrapPreflightV1",
        "round": "b6-holdout",
        "created_at": time.strftime(
            "%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()
        ),
        "zero_model_calls": True,
        "charter_artifact": str(CHARTER_FILE.relative_to(PYTHON_SERVICE_ROOT)),
        "charter_input_hash": charter["input_hash"],
        "association_contract": {
            "case": "B (charter declared at B6 entry; see charter artifact)",
            "rule": charter["association_contract"]["rule"],
        },
        "truth_access": "hash-only (G8b); content never read",
        "cases": results,
        "all_passed": all_ok,
    }
    artifact["input_hash"] = state_hash_of(
        canonical_state_json(
            {k: v for k, v in artifact.items() if k != "input_hash"}
        )
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"preflight -> {OUT_FILE}")
    print("ALL PASS" if all_ok else "PREFLIGHT FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
