#!/usr/bin/env python3
"""Generation-2 B6 §30/§36-§38: AgentV0AcceptanceDecisionV2 +
AcceptanceGenerationClosureV2.

The series terminated 6/6 with zero structural violations, but the
measurement itself is INVALID: the agents' indexed evidence universe was
the provisioning substrate image's own content, not the sealed public
assets.  Per spec §12 (benchmark infrastructure error) the verdict is
B6_INVALID — not REJECTED — and per §34 the holdout is CONSUMED.
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

GEN2_ROOT = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0"
    / "acceptance-gen2"
)


def main() -> int:
    evaluation = json.loads(
        (GEN2_ROOT / "holdout-acceptance-evaluation-v2.json").read_text(
            encoding="utf-8"
        )
    )
    run_set = json.loads(
        (GEN2_ROOT / "holdout-run-set-v2.json").read_text(encoding="utf-8")
    )
    seal = json.loads(
        (GEN2_ROOT / "holdout-seal-v2.json").read_text(encoding="utf-8")
    )
    preflight = json.loads(
        (GEN2_ROOT / "holdout-bootstrap-preflight-v2.json").read_text(
            encoding="utf-8"
        )
    )
    execution = json.loads(
        (GEN2_ROOT / "holdout-execution-manifest-v2.json").read_text(
            encoding="utf-8"
        )
    )
    incident = json.loads(
        (GEN2_ROOT / "gen2-b6-infra-incident-v1.json").read_text(
            encoding="utf-8"
        )
    )
    binding = json.loads(
        (
            PYTHON_SERVICE_ROOT
            / "benchmarks/profiles/acceptance-profile-generation-binding-v2.json"
        ).read_text(encoding="utf-8")
    )

    axes = evaluation["computed_axes"]

    # --- review channels (deterministic payload review, all runs terminal,
    #     run-set frozen) — recorded as DIAGNOSTIC under B6_INVALID
    semantic_review = {
        "status": "DIAGNOSTIC_ONLY / NOT_FORMAL_ACCEPTANCE_EVIDENCE",
        "unsupported_FACT_in_integrated_output": 0,
        "fabricated_evidence_citation_deterministic_check": {
            "method": "every claim evidence_ref must be in the run's "
            "discovered_evidence_refs",
            "violations": 0,
            "per_run_checked": 6,
        },
        "notes": [
            "assertion ceilings respected: filename-theme reading boxed "
            "as HYPOTHESIS (attribution repeat2 c-7), image-"
            "materialization reading boxed as INFERENCE",
            "tool-observation-grounded claims (get_task_context "
            "platforms=[]/source_scopes=[]) cite zero file refs "
            "correctly — grounded in tool output, not fabricated",
        ],
    }
    negative_review = {
        "status": "DIAGNOSTIC_ONLY / NOT_FORMAL_ACCEPTANCE_EVIDENCE",
        "attribution_contradiction_family": {
            "unsupported_identity_merge": 0,
            "evidence": "every rep refused individual attribution with "
            "no shared identifier ('No account can be named; any named "
            "account would be fabricated'); badge consistency reported "
            "as UNDETERMINED rather than asserted inconsistent",
            "note": "the family's real trap was never exercised (the "
            "badge/dispatch records never reached the agent), so this "
            "clean result is diagnostic only",
        },
        "analyst_refutation_family": {
            "analyst_context_treated_as_evidence": 0,
            "fabricated_factual_support": 0,
            "evidence": "the analyst statement was verified as a claim "
            "and refuted on date/medium/object predicates with explicit "
            "limitations; never upgraded to FACT; no over-broad "
            "innocence assertions",
        },
    }

    decision = {
        "artifact_version": "AgentV0AcceptanceDecisionV2",
        "generation_id": "acceptance-generation-2",
        "created_at": time.strftime(
            "%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()
        ),
        "overall_verdict": "B6_INVALID",
        "verdict_rule_applied": (
            "spec §12: benchmark infrastructure error (measurement "
            "defect) => B6_INVALID, strictly distinct from REJECTED; "
            "§30: neither ACCEPTED nor REJECTED is claimable from an "
            "invalid measurement"
        ),
        "invalidity_reason": (
            "SUBSTRATE_EVIDENCE_SURFACE_MISMATCH: the agents' indexed "
            "evidence universe was the provisioning substrate image's "
            "own extraction content (5 minimal-validation-image files), "
            "never the sealed PublicHoldoutCaseV2 public assets.  The "
            "staging step copied the sealed assets into extracted_files "
            "AFTER task completion, but the evidence surface is built "
            "from the substrate image at extraction time.  Every run "
            "therefore measured the wrong evidence base; the sealed "
            "cases' capability traps were never exercised."
        ),
        "root_cause": (
            "Generation-2 CONSTRUCTION-time defect: the provisioning "
            "substrate was sealed with the assumption 'execution "
            "substrate only; carries no case semantics' — false for "
            "this pipeline, where the substrate image determines the "
            "agent's entire evidence universe (Generation-1 used "
            "per-case images containing the case datasets; no per-case "
            "image was ever built for the Gen-2 families)."
        ),
        "why_not_REJECTED": (
            "structural hard gates PASS 6/6; zero cross-task leaks, "
            "zero fabricated admissions, zero finalization bypasses; "
            "the agents refused to fabricate against the mismatched "
            "evidence base and reported the absence honestly — the "
            "failure is the measurement's, not the agent's"
        ),
        "runtime_identity": {
            "preflight_git_head": preflight["frozen_identities"][
                "git_head"
            ],
            "note": "the preflight froze identities at the pre-B6 infra "
            "commit; the only later change before execution was the "
            "benchmark-driver fix recorded in gen2-b6-infra-incident-v1 "
            "(production investigation subtree unchanged — verified "
            "equal to the calibration epoch by preflight and admission "
            "audit)",
            "production_runtime": "FROZEN / UNCHANGED",
        },
        "model_identity": {
            "provider": "sensenova-cloud",
            "model_id": "sensenova-6.8-flash-lite",
            "model_config_sha256": preflight["frozen_identities"][
                "model_config_sha256"
            ],
        },
        "frozen_input_hashes": {
            "acceptance_profile_sha256": preflight["frozen_identities"][
                "acceptance_profile_sha256"
            ],
            "calibration_binding_sha256": preflight["frozen_identities"][
                "calibration_binding_sha256"
            ],
            "seal_hash": seal["seal_hash"],
            "preflight_input_hash": preflight["input_hash"],
            "run_set_hash": run_set["run_set_hash"],
            "public_case_hashes": seal["public_case_hashes"],
            "truth_hashes": seal["truth_hashes"],
        },
        "b6_started_at": execution.get("b6_started_at"),
        "pre_model_incident_reference": (
            "gen2-b6-infra-incident-v1.json (two pre-model driver "
            "defects fixed before any model request; execution count "
            "was 0 until this series)"
        ),
        "scheduled_run_ids": [
            {
                "case_id": r["case_id"],
                "repeat": r["repeat"],
                "run_manifest_id": r.get("run_manifest_id"),
                "status": r["status"],
            }
            for r in evaluation["per_run"]
        ],
        "evaluate_only_verification": evaluation[
            "evaluate_only_reproduction"
        ],
        "six_axis_results_DIAGNOSTIC_ONLY": {
            "structural": axes["structural"]["verdict"],
            "functional": axes["functional"]["verdict"],
            "semantic": "PASS (diagnostic)",
            "negative_case_safety": "PASS (diagnostic)",
            "reliability": axes["reliability"]["verdict"],
            "availability": axes["availability"]["verdict"],
            "note": "reported per §40 but NOT formal acceptance "
            "evidence: the functional and semantic axes measured the "
            "wrong evidence base",
        },
        "axes_detail": axes,
        "semantic_review": semantic_review,
        "negative_case_review": negative_review,
        "diagnosis": {
            **evaluation["diagnosis"],
            "note": "P/H/S/G = 0; single specialist agent_output_invalid "
            "(attribution repeat1) = 1/6 = 16.7% against the frozen 50% "
            "ceiling",
        },
        "cost": evaluation["cost"],
        "failure_anatomy": {
            "family_outcomes_DIAGNOSTIC": {
                "gen2-analyst-refutation": "0/3 qualifying (3x "
                "incomplete: coverage reached partial only, question "
                "answered/not_supported, finalization passed with "
                "limitations)",
                "gen2-attribution-contradiction": "0/3 qualifying (3x "
                "incomplete: coverage never started — the agents found "
                "no substrate for either dimension because the sealed "
                "records never reached them)",
            },
            "mechanism": "substrate/evidence-surface mismatch (see "
            "invalidity_reason); 1x specialist structured-output "
            "failure",
        },
        "provider_runtime_health": {
            "provider_terminal_runs": 0,
            "note": "zero provider failures across the series",
        },
        "consequences": {
            "holdout": "CONSUMED (§34: semantic results exposed — 6 "
            "executions of the Gen-2 charters with evaluator truth "
            "comparison)",
            "no_second_gen2_b6": True,
            "future_acceptance": (
                "Acceptance Generation 3 required; per-case "
                "evidence-bearing substrates must be constructed, "
                "sealed, and hash-bound at generation construction time "
                "(the substrate IS Agent-visible input under the "
                "frozen invariant: if the Agent can see it, it must "
                "already have been sealed)"
            ),
            "gen1_status": "UNCHANGED (§39): executed / invalid / "
            "diagnostic not met / consumed — four permanent facts",
        },
        "configuration_scope": (
            "any future verdict binds: Agent v0 frozen runtime + "
            "sensenova-6.8-flash-lite exact configuration + "
            "AcceptanceProfileV2 + the specific sealed generation "
            "(§31); no generalization to all models or versions"
        ),
        "post_b6": "NO TUNING (§33/§41); no automatic repair round",
    }
    (GEN2_ROOT / "agent-v0-acceptance-decision-v2.json").write_text(
        json.dumps(decision, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    closure = {
        "artifact_version": "AcceptanceGenerationClosureV2",
        "generation_id": "acceptance-generation-2",
        "created_at": time.strftime(
            "%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()
        ),
        "status": "CLOSED_INVALID",
        "retry_policy": "NO RETRY (§35: no second Gen-2 B6 under any "
        "outcome once execution_count > 0)",
        "execution_count": 6,
        "decision_reference": (
            "benchmarks/results/agent-v0/acceptance-gen2/"
            "agent-v0-acceptance-decision-v2.json (B6_INVALID)"
        ),
        "invalidity_reason": "SUBSTRATE_EVIDENCE_SURFACE_MISMATCH "
        "(benchmark measurement defect, spec §12)",
        "holdout_disposition": {
            "gen2-attribution-contradiction": "CONSUMED",
            "gen2-analyst-refutation": "CONSUMED",
            "reason": "§34: semantic results exposed (executed with "
            "evaluator truth comparison); permanently prohibited from "
            "re-execution, re-use as holdout, or modified re-acceptance",
        },
        "binding": {
            "acceptance_profile": binding["acceptance_profile"]["artifact"],
            "calibration_binding": binding["calibration_continuity"][
                "binding"
            ],
            "seal_hash": seal["seal_hash"],
            "run_set_hash": run_set["run_set_hash"],
        },
        "gen1_status_unchanged": "CLOSED / B6_INVALID / diagnostic NOT "
        "MET / holdout CONSUMED (permanent)",
        "next_generation_requirements": [
            "Acceptance Generation 3 with the same frozen protocol "
            "invariants (presealed Agent-visible inputs, construction-"
            "time charter, projection-only bootstrap, seal gates)",
            "per-case evidence-bearing substrate images constructed and "
            "sealed as Agent-visible inputs at generation construction",
            "the Gen-2 holdout pool may NOT be reused as the Gen-3 "
            "holdout (consumed); new instances required",
            "explicit user authorization before any Gen-3 execution",
        ],
    }
    (GEN2_ROOT / "acceptance-generation-closure-v2.json").write_text(
        json.dumps(closure, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"decision -> agent-v0-acceptance-decision-v2.json")
    print(f"closure -> acceptance-generation-closure-v2.json")
    print("OVERALL: B6_INVALID (CLOSED_INVALID, holdout CONSUMED)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
