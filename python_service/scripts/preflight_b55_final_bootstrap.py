#!/usr/bin/env python3
"""B5.5-final §4/§5 deterministic bootstrap + attention preflight.

ZERO model calls.  For all 8 calibration cases this script builds the
initial benchmark Working State through the EXACT production driver code
(`build_benchmark_seed_state`), asserts the coverage/question association
contract, then compiles the REAL frozen AttentionBuilder projection and
asserts the structural-collision class cannot occur.

Gates (spec §4/§5/§12):
  G1  all required coverage dimensions present
  G2  required=true for every dimension
  G3  initial status=not_started for every dimension
  G4  related_question_ids exact (association contract Case A: the
      single charter question)
  G5  every related question exists in the seeded questions
  G6  AttentionBuilder produces the merged structure: NO standalone
      `coverage:*` attention item (folded into the question item)
  G7  no duplicate delegable question×scope opportunity created by the
      bootstrap representation (single delegable attention item per
      charter question; the delegable-item×scope matrix has no repeats)

Usage (from python_service/):
    .venv/bin/python scripts/preflight_b55_final_bootstrap.py
"""

from __future__ import annotations

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
OUT_FILE = (
    PYTHON_SERVICE_ROOT
    / "benchmarks"
    / "results"
    / "agent-v0"
    / "b2-restart"
    / "b2-post-b55-final"
    / "bootstrap-preflight-v1.json"
)


def main() -> int:
    from types import SimpleNamespace

    import run_p8b_baseline as driver
    from httpserver.services.investigation.agent_attention import (
        AttentionBuilder,
    )

    corpus = json.loads(
        (
            PYTHON_SERVICE_ROOT
            / "benchmarks/corpus/corpus-agent-v0-calibration.v2.json"
        ).read_text(encoding="utf-8")
    )
    case_ids = [c["case_id"] for c in corpus["calibration_cases"]]

    builder = AttentionBuilder()
    results = []
    all_ok = True
    for case_id in case_ids:
        case_payload = json.loads(
            (PYTHON_SERVICE_ROOT / "benchmarks/cases" / case_id / "case.json")
            .read_text(encoding="utf-8")
        )
        expected_dims = sorted(
            case_payload.get("required_coverage_dimensions", ())
        )
        seed_questions = driver.SEED_QUESTIONS[case_id]
        if isinstance(seed_questions, str):
            seed_questions = (seed_questions,)
        ci = SimpleNamespace(
            goal=case_payload.get("goal", ""),
            seed_questions=tuple(seed_questions),
            seed_coverage_dimensions=tuple(expected_dims),
        )
        state = driver.build_benchmark_seed_state(
            f"task-{case_id}", f"inv-{case_id}", ci
        )

        checks: dict[str, bool] = {}
        dims = {
            c.dimension_id: c
            for c in state.coverage
        }
        checks["G1_dims_present"] = sorted(dims) == expected_dims
        checks["G2_required_true"] = all(c.required for c in dims.values())
        checks["G3_initial_not_started"] = all(
            c.status.value == "not_started" for c in dims.values()
        )
        expected_related = tuple(
            f"q-{index}"
            for index, _ in enumerate(ci.seed_questions, start=1)
        )
        checks["G4_related_question_ids_exact"] = all(
            c.related_question_ids == expected_related
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
        # G7: delegable attention items (delegate-eligible) mapped onto
        # charter questions must be unique per question — the bootstrap
        # must not create two items demanding the same question × scope.
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
                "expected_coverage_dimensions": expected_dims,
                "charter_questions": sorted(question_ids),
                "attention_item_ids": item_ids,
                "checks": checks,
                "ok": ok,
            }
        )
        print(
            f"{case_id:32s} {'PASS' if ok else 'FAIL'} "
            f"| attention: {item_ids}"
        )

    artifact = {
        "artifact_version": "BootstrapPreflightV1",
        "round": "b2-post-b55-final",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "association_contract": {
            "case": "A (single charter question per case)",
            "rule": (
                "all required coverage dimensions -> related_question_ids = "
                "the seeded charter questions (q-1, ...); deterministic, "
                "public-surface derived, no truth content"
            ),
            "implemented_in": "run_p8b_baseline.build_benchmark_seed_state",
        },
        "cases": results,
        "all_passed": all_ok,
    }
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"preflight -> {OUT_FILE}")
    print("ALL PASS" if all_ok else "PREFLIGHT FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
