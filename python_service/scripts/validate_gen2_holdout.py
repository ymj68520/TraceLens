#!/usr/bin/env python3
"""Acceptance Generation 2 — pre-seal static validation (spec §24).

ZERO model calls.  For every constructed Gen-2 holdout case:
  public schema valid (sealed loader, hash re-derived)
  charter complete (construction-time, no placeholders)
  Coverage→Question links valid + exact
  all referenced public assets exist + hash match on disk
  bootstrap deterministic (frozen projection, identical state hashes)
  AttentionBuilder preflight valid + deterministic
  no duplicate question×scope delegable topology
  truth schema valid (TruthManifestV1 + ReachabilityManifestV1)
  truth/public separation valid (§16 isolation check)

Writes gen2-static-validation-v1.json under the generation root.
"""

from __future__ import annotations

import hashlib
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
CASES_DIR = GEN2_ROOT / "cases"
TRUTH_DIR = GEN2_ROOT / "truth"
OUT_FILE = GEN2_ROOT / "gen2-static-validation-v1.json"


def main() -> int:
    from httpserver.services.benchmarks.holdout_contract import (
        load_public_holdout_case,
        build_holdout_working_state,
        verify_truth_public_isolation,
    )
    from httpserver.services.benchmarks.truth_manifest import (
        ReachabilityManifestV1,
        TruthManifestV1,
    )
    from httpserver.services.investigation.agent_attention import (
        AttentionBuilder,
    )
    from httpserver.services.investigation.agent_runtime import (
        canonical_state_json,
        state_hash_of,
    )

    case_ids = sorted(
        p.stem.replace(".public-case", "")
        for p in CASES_DIR.glob("*.public-case.json")
    )
    builder = AttentionBuilder()
    results = []
    all_ok = True
    for case_id in case_ids:
        checks: dict[str, bool] = {}
        public_case = load_public_holdout_case(
            CASES_DIR / f"{case_id}.public-case.json"
        )
        checks["public_schema_valid"] = True
        checks["charter_complete"] = len(public_case.charter) > 0 and all(
            q.text.strip() for q in public_case.charter
        )
        checks["coverage_question_links_valid"] = (
            {link.dimension_id for link in public_case.coverage_question_links}
            == set(public_case.required_coverage_dimensions)
            and all(
                set(link.related_question_ids)
                <= {q.question_id for q in public_case.charter}
                for link in public_case.coverage_question_links
            )
        )
        def _asset_ok(asset) -> bool:
            path = (
                CASES_DIR / case_id / "dataset" / asset.relative_path
            )
            if not path.is_file():
                return False
            return (
                hashlib.sha256(path.read_bytes()).hexdigest()
                == asset.sha256
            )

        checks["public_assets_exist_and_match"] = all(
            _asset_ok(asset) for asset in public_case.public_assets
        )

        # bootstrap deterministic
        states = [
            build_holdout_working_state(
                public_case, task_id="t", investigation_id="i"
            )
            for _ in range(2)
        ]
        state_hashes = {
            state_hash_of(canonical_state_json(s.model_dump(mode="json")))
            for s in states
        }
        checks["bootstrap_deterministic"] = len(state_hashes) == 1

        # attention preflight valid + deterministic
        attention_runs = [
            builder.build_full_set(state, state_revision=1)
            for state in states
        ]
        item_id_lists = [
            [item.item_id for item in attention.items]
            for attention in attention_runs
        ]
        checks["attention_preflight_deterministic"] = (
            item_id_lists[0] == item_id_lists[1]
        )
        checks["no_standalone_coverage_item"] = not any(
            item_id.startswith("coverage:")
            for item_id in item_id_lists[0]
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
        checks["no_duplicate_question_scope_topology"] = len(
            delegable_refs
        ) == len(set(delegable_refs))

        # truth schema valid
        truth = TruthManifestV1(
            **json.loads(
                (TRUTH_DIR / f"{case_id}.truth.json").read_text(
                    encoding="utf-8"
                )
            )
        )
        reach = ReachabilityManifestV1(
            **json.loads(
                (TRUTH_DIR / f"{case_id}.reachability.json").read_text(
                    encoding="utf-8"
                )
            )
        )
        checks["truth_schema_valid"] = (
            truth.case_id == case_id and reach.case_id == case_id
        )
        checks["truth_public_separation_valid"] = not (
            verify_truth_public_isolation(public_case, truth)
        )

        ok = all(checks.values())
        all_ok &= ok
        results.append(
            {
                "case_id": case_id,
                "case_family": public_case.case_family,
                "public_input_hash": public_case.input_hash,
                "truth_manifest_input_hash": truth.input_hash,
                "charter_question_ids": [
                    q.question_id for q in public_case.charter
                ],
                "coverage_links": [
                    {
                        "dimension_id": link.dimension_id,
                        "related_question_ids": list(
                            link.related_question_ids
                        ),
                    }
                    for link in public_case.coverage_question_links
                ],
                "attention_item_ids": item_id_lists[0],
                "seed_state_hash": sorted(state_hashes)[0],
                "checks": checks,
                "ok": ok,
            }
        )
        print(f"{case_id:34s} {'PASS' if ok else 'FAIL'}")

    artifact = {
        "artifact_version": "Gen2StaticValidationV1",
        "generation_id": "acceptance-generation-2",
        "created_at": "2026-10-01T00:00:00+00:00",
        "zero_model_calls": True,
        "cases": results,
        "all_passed": all_ok,
        "input_hash": "",
    }
    artifact["input_hash"] = state_hash_of(
        canonical_state_json(
            {k: v for k, v in artifact.items() if k != "input_hash"}
        )
    )
    OUT_FILE.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"validation -> {OUT_FILE}")
    print("ALL PASS" if all_ok else "VALIDATION FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
