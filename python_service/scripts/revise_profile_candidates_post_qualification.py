#!/usr/bin/env python3
"""P8B post-qualification profile candidate revision (§32/§33/§34/§15).

Revises the two AgentV0 profile CANDIDATES after the model qualification
experiment returned NO_QUALIFIED_MODEL_CONFIGURATION:

  1. calibration profile candidate: records the qualification outcome and
     the §31 freeze block (no selected model to bind).
  2. acceptance profile candidate:
       - §33 review: fixes the stale "4 of 5" holdout arithmetic (the
         sealed corpus holds 3 cases, so aggregate >= 0.8 is equivalent
         to 3/3) and encodes §33's case-level requirements for the
         high-risk trap cases explicitly instead of leaving them masked
         inside the aggregate;
       - §34 answer: documents that the silence false-pass
         ("no output -> 0 unsupported FACT -> fake PASS") is already
         structurally excluded by BenchmarkCaseOutcomeV1 (no semantic
         output => incomplete, never success), so the success-rate
         floor IS the functional floor;
       - records the §32 freeze block (selected-model reliability input
         does not exist).
  3. re-computes the calibration candidate hash into the acceptance
     candidate reference (written last).

Both remain status=candidate: NEITHER profile is frozen this round.

Usage (from python_service/):
    .venv/bin/python scripts/revise_profile_candidates_post_qualification.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PYTHON_SERVICE_ROOT = SCRIPT_PATH.parents[1]
B4_ROOT = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0" / "b4"
)
QUAL_ROOT = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0"
    / "model-qualification"
)

EXPERIMENT_REF = {
    "experiment_artifact": "model-qualification-experiment.v1.json",
    "selection_decision": "none / NO_QUALIFIED_MODEL_CONFIGURATION (§15)",
}


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    calib_path = B4_ROOT / "calibration-profile-candidate.v1.json"
    acc_path = B4_ROOT / "acceptance-profile-candidate.v1.json"
    calib = json.loads(calib_path.read_text(encoding="utf-8"))
    acc = json.loads(acc_path.read_text(encoding="utf-8"))

    # -- 1. calibration profile candidate ---------------------------------
    calib["qualification_outcome"] = {
        **EXPERIMENT_REF,
        "model_qualification_experiment_id": "mqexp-agent-v0-2026-09-28",
        "candidates_dispositions": {
            "mimo-v2.6-flash-reference": (
                "unsupported_provisional_supervisor_role"
            ),
            "deepseek-v4-flash": "rejected",
            "kimi-k3": "rejected",
            "glm-5.3": "inconclusive",
        },
        "freeze_status": "BLOCKED (§31): a calibration profile binds a "
        "SELECTED model; NO_QUALIFIED_MODEL_CONFIGURATION means there is "
        "nothing to bind.  The zero-change candidate content "
        "(tuned_parameters={}) is retained unchanged for the future "
        "round in which a qualified model exists.",
        "production_changes": [],
        "cc1_status": "MODEL_CAPABILITY_LIMIT — generalized across 4 "
        "tested model families; §29: no calibratable-numeric causal "
        "evidence, no cycle or budget increase",
    }

    # -- 2. acceptance profile candidate -----------------------------------
    for threshold in acc["thresholds"]:
        if threshold["metric_id"] == "case_outcome_success_rate":
            threshold["rationale"] = (
                "§33 review (2026-09-28): the sealed holdout contains 3 "
                "cases, so an aggregate floor of 0.8 is arithmetically "
                "3/3 — the B4-era 'at least 4 of 5' wording was stale. "
                "Why 0.8 and not 0.7/0.9: on a 3-case sealed set the "
                "only distinct integer cuts are 2/3 (0.67) and 3/3 "
                "(1.0); the product-correctness position is that NO "
                "sealed trap case may fail, which this floor expresses. "
                "If a future corpus revision changes the sealed case "
                "count, this floor must be re-derived from product "
                "correctness (never from a model baseline, §38) with "
                "the per-case requirements below kept explicit.  "
                "Empirical honesty: all four qualification models "
                "measure 0.0 today; this floor is a product requirement, "
                "and the current population is an unsupported-model "
                "qualification, not a bar to lower."
            )
    acc["case_level_requirements"] = {
        "principle": "§33: high-risk negative/trap cases are governed by "
        "case-level success requirements, never masked by the aggregate",
        "required_case_outcomes": [
            {
                "applies_to": "every sealed holdout case",
                "requirement": (
                    "outcome in {success, success_with_limitations}; "
                    "an incorrect or incomplete outcome fails that case "
                    "outright regardless of the aggregate"
                ),
            },
            {
                "applies_to": "trap-shaped sealed cases (identity/causal "
                "traps, negative-evidence cases such as the VPN-egress "
                "and refund-fraud holdouts)",
                "requirement": (
                    "the trap must be HANDLED, not avoided: identity "
                    "traps must not merge (false_entity_merge=0), "
                    "causal traps must not assert causation, "
                    "negative-evidence cases must close unresolved "
                    "questions as limitations rather than inventing "
                    "affirmative findings"
                ),
            },
        ],
    }
    acc["silence_guard"] = {
        "principle": "§34: a silent model must never fake-PASS via "
        "'0 unsupported FACT'",
        "mechanism": (
            "structural, not a separate threshold: "
            "BenchmarkCaseOutcomeV1 marks any run without semantic "
            "output (integrated delegations or findings) incomplete, "
            "and incomplete never satisfies the success-rate floor. "
            "The aggregate success floor therefore doubles as the "
            "functional floor; the zero-tolerance ceilings (unsupported "
            "FACT, premature closure, incorrect) apply only to runs "
            "that produced semantic output."
        ),
    }
    acc["freeze_status"] = {
        "status": "BLOCKED (§32)",
        "reason": (
            "freezing requires product correctness requirements (held) "
            "+ full v5 calibration distributions (held) + selected "
            "model reliability (ABSENT — no model qualified).  The "
            "candidate is fully specified so that the freeze is "
            "mechanical once a qualified model exists."
        ),
        "must_never_be_revised_from": "future holdout results (§32)",
    }

    calib_path.write_text(
        json.dumps(calib, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    acc["calibration_profile_hash"] = _sha256_file(calib_path)
    acc_path.write_text(
        json.dumps(acc, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"revised {calib_path.name} (status stays candidate)")
    print(f"revised {acc_path.name} (status stays candidate, "
          f"calibration hash refreshed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
