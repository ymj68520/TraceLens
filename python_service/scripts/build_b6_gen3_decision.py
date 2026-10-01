#!/usr/bin/env python3
"""Gen-3 B6 §31/§36-§38: AgentV0AcceptanceDecisionV3 +
AcceptanceGenerationClosureV3.

The series terminated 6/6 with a perfect substrate chain (6/6 evidence-
world run proofs) and zero structural violations, but the measurement is
INVALID: the production read surface cannot hydrate plain-text file
content after the pipeline's post-extraction cleanup, so the sealed
capability traps were unreachable — every delegation in every run
honestly reported the content absent and refused to fabricate.  Per
§11 (benchmark error != agent failure) the verdict is B6_INVALID; per
§34 the holdout is CONSUMED and Generation 4 requires a separate
production content-surface work item first.
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

GEN3_ROOT = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0"
    / "acceptance-gen3"
)


def main() -> int:
    evaluation = json.loads(
        (GEN3_ROOT / "holdout-acceptance-evaluation-v3.json").read_text(
            encoding="utf-8"
        )
    )
    run_set = json.loads(
        (GEN3_ROOT / "holdout-run-set-v3.json").read_text(encoding="utf-8")
    )
    seal = json.loads(
        (GEN3_ROOT / "holdout-seal-v3.json").read_text(encoding="utf-8")
    )
    preflight = json.loads(
        (GEN3_ROOT / "holdout-bootstrap-preflight-v3.json").read_text(
            encoding="utf-8"
        )
    )
    frozen = json.loads(
        (GEN3_ROOT / "gen3-b6-frozen-inputs-v1.json").read_text(
            encoding="utf-8"
        )
    )
    execution = json.loads(
        (GEN3_ROOT / "holdout-execution-manifest-v3.json").read_text(
            encoding="utf-8"
        )
    )
    superseding = json.loads(
        (
            GEN3_ROOT
            / "generation3-admission-audit-v1-superseding-record.json"
        ).read_text(encoding="utf-8")
    )

    axes = evaluation["computed_axes"]

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
            "assertion ceilings respected under total content absence: "
            "image-materialization reading boxed as INFERENCE; "
            "filename-theme reading boxed as HYPOTHESIS (attribution "
            "family)",
            "every BLOCKED report grounds its claims in tool "
            "observations (files.db metadata, timeline clusters, "
            "get_task_context), never in invented content",
            "the agents flagged the pinned-mtime/extraction-ctime "
            "inversion as a bulk-staging artifact instead of abusing it",
        ],
    }
    negative_review = {
        "status": "DIAGNOSTIC_ONLY / NOT_FORMAL_ACCEPTANCE_EVIDENCE",
        "ledger_identity_family": {
            "unsupported_identity_merge": 0,
            "evidence": "no chat participant was identified as any "
            "operator account; the merge was explicitly refused and "
            "recorded as absence-of-retrievable-data",
        },
        "failover_causality_family": {
            "unsupported_causal_escalation": 0,
            "evidence": "both causal directions explicitly refused: "
            "'No statement — establishing or negating — can be made "
            "about a causal relationship'",
        },
        "note": "the families' real traps were never exercised (the "
        "sealed file contents never reached the agent), so these clean "
        "results are diagnostic only",
    }

    decision = {
        "artifact_version": "AgentV0AcceptanceDecisionV3",
        "generation_id": "acceptance-generation-3",
        "created_at": time.strftime(
            "%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()
        ),
        "overall_verdict": "B6_INVALID",
        "verdict_rule_applied": (
            "spec §11: benchmark infrastructure error (measurement "
            "defect) => B6_INVALID, strictly distinct from REJECTED; "
            "the agents' evidence world matched the seal perfectly and "
            "their failure to answer stems from the measurement's "
            "content-surface defect, not from agent behavior"
        ),
        "invalidity_reason": (
            "EVIDENCE_CONTENT_SURFACE_TRANSIENT: the sealed Evidence "
            "world was provisioned and indexed exactly as sealed (6/6 "
            "run proofs), but the production read surface cannot "
            "hydrate plain-text file content after the pipeline's "
            "post-extraction cleanup of extracted_files — get_evidence "
            "returns null/empty content_preview at both hydration "
            "levels in every delegation of every run.  The sealed "
            "capability traps were unreachable; no alert line, chat "
            "line, account row or roster entry was ever readable."
        ),
        "root_cause": (
            "the production pipeline treats extracted_files as "
            "transient (verified on a production task as well); "
            "Generation-1's readable content was an artifact of the "
            "late-injection staging that Generation 3 correctly "
            "forbids.  Making sealed loose-file content answerable "
            "requires a production-side persistent content store — a "
            "separate work item (prep spec §25), not a benchmark patch."
        ),
        "why_not_REJECTED": (
            "structural hard gates PASS 6/6 (recomputed); P/H/S/G = 0; "
            "fabricated citations 0/6; the agents refused to fabricate "
            "under total content absence, correctly surfaced the "
            "defect, and flagged metadata anomalies honestly — the "
            "failure is the measurement's content layer, not the "
            "agent's discipline"
        ),
        "runtime_identity": {
            "git_head_at_execution": frozen["git_head"],
            "execution_commit": "88d3f22f (benchmark scripts only; "
            "production subtree unchanged and verified)",
            "frozen_inputs_input_hash": frozen["input_hash"],
            "superseding_admission_record": (
                "generation3-admission-audit-v1-superseding-record.json "
                "(§1 Case B, d05f402d re-run 8/8 PASS)"
            ),
        },
        "model_identity": {
            "provider": "sensenova-cloud",
            "model_id": "sensenova-6.8-flash-lite",
            "model_config_sha256": frozen["model"]["config_sha256"],
        },
        "frozen_input_hashes": {
            "acceptance_profile_sha256": frozen[
                "acceptance_profile_sha256"
            ],
            "calibration_binding_sha256": frozen[
                "calibration_binding_sha256"
            ],
            "generation_binding_sha256": frozen[
                "generation_binding_sha256"
            ],
            "seal_hash": seal["seal_hash"],
            "preflight_input_hash": preflight["input_hash"],
            "run_set_hash": run_set["run_set_hash"],
            "public_case_hashes": seal["public_case_hashes"],
            "truth_hashes": seal["truth_hashes"],
            "substrate_image_hashes": frozen["substrate_image_hashes"],
            "evidence_world_digests": frozen["evidence_world_digests"],
        },
        "b6_started_at": execution.get("b6_started_at"),
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
        "evidence_world_run_proofs": evaluation[
            "evidence_world_run_proofs"
        ],
        "six_axis_results_DIAGNOSTIC_ONLY": {
            "structural": axes["structural"]["verdict"],
            "functional": axes["functional"]["verdict"],
            "semantic": "PASS (diagnostic)",
            "negative_case_safety": "PASS (diagnostic)",
            "reliability": axes["reliability"]["verdict"],
            "availability": axes["availability"]["verdict"],
            "note": "the functional axis measured an unreachable task; "
            "not formal acceptance evidence",
        },
        "axes_detail": axes,
        "semantic_review": semantic_review,
        "negative_case_review": negative_review,
        "diagnosis": {
            **evaluation["diagnosis"],
            "note": "P/H/S/G = 0; one provider-terminal run (ledger "
            "repeat0: 429 tpm/rpm limit) = 1/6 = 16.7% against the "
            "frozen 20% availability budget",
        },
        "cost": evaluation["cost"],
        "failure_anatomy": {
            "family_outcomes_DIAGNOSTIC": {
                "gen3-failover-causality": "0/3 qualifying (3x "
                "incomplete: content unretrievable, honest BLOCKED; "
                "repeat2 reached unresolved/unavailable question "
                "terminal + coverage unavailable with basis, "
                "finalization denied on REQUIRED_QUESTION_OPEN)",
                "gen3-ledger-identity": "0/3 qualifying (repeat0 "
                "provider 429; repeat1 completed finalization with "
                "limitations, questions blocked/unavailable, coverage "
                "unavailable; repeat2 incomplete)",
            },
            "mechanism": "EVIDENCE_CONTENT_SURFACE_TRANSIENT (see "
            "invalidity_reason); 1x provider 429",
        },
        "provider_runtime_health": {
            "provider_terminal_runs": 1,
            "note": "one 429 tpm/rpm rate-limit terminal; no "
            "replacement (§8/§21)",
        },
        "consequences": {
            "holdout": "CONSUMED (the model saw both Gen-3 cases; §34 "
            "applies regardless of the invalid cause)",
            "no_second_gen3_b6": True,
            "formal_acceptance": "NOT ESTABLISHED",
            "future_acceptance": (
                "Acceptance Generation 4 requires FIRST an independent "
                "production work item: a persistent/hydratable content "
                "store so benchmark-visible text evidence remains "
                "readable after indexing (prep spec §25 STOP-and-"
                "separate-project rule) — then a new sealed generation "
                "with fresh instances"
            ),
            "gen1_gen2_status": "UNCHANGED (§38): both CLOSED_INVALID / "
            "CONSUMED / NO RETRY — permanent",
        },
        "configuration_scope": (
            "any future verdict binds the exact frozen runtime + "
            "sensenova-6.8-flash-lite configuration + "
            "AcceptanceProfileV2 + the specific sealed generation (§32)"
        ),
        "post_b6": "NO TUNING (§33/§40); no automatic repair round",
    }
    (GEN3_ROOT / "agent-v0-acceptance-decision-v3.json").write_text(
        json.dumps(decision, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    closure = {
        "artifact_version": "AcceptanceGenerationClosureV3",
        "generation_id": "acceptance-generation-3",
        "created_at": time.strftime(
            "%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()
        ),
        "status": "CLOSED_INVALID",
        "retry_policy": "NO RETRY (§35: no second Gen-3 B6 once "
        "execution_count > 0)",
        "execution_count": 6,
        "decision_reference": (
            "benchmarks/results/agent-v0/acceptance-gen3/"
            "agent-v0-acceptance-decision-v3.json (B6_INVALID)"
        ),
        "invalidity_reason": "EVIDENCE_CONTENT_SURFACE_TRANSIENT "
        "(benchmark/measurement defect, spec §11)",
        "holdout_disposition": {
            "gen3-ledger-identity": "CONSUMED",
            "gen3-failover-causality": "CONSUMED",
            "reason": "§34: the model saw both cases (6 executions "
            "with evaluator truth comparison); permanently prohibited "
            "from re-execution, re-use as holdout, or modified "
            "re-acceptance",
        },
        "binding": {
            "acceptance_profile": (
                "benchmarks/profiles/agent-v0-acceptance-profile-v2.json"
            ),
            "calibration_binding": (
                "benchmarks/profiles/calibration-evidence-binding-v2.json"
            ),
            "generation_binding": (
                "benchmarks/profiles/"
                "acceptance-profile-generation-binding-v3.json"
            ),
            "seal_hash": seal["seal_hash"],
            "run_set_hash": run_set["run_set_hash"],
        },
        "gen1_gen2_status_unchanged": "both CLOSED_INVALID / CONSUMED / "
        "NO RETRY (permanent)",
        "next_generation_requirements": [
            "PREREQUISITE (independent production work item): persistent/"
            "hydratable content store for indexed loose-file evidence — "
            "acceptance rounds STOP until this exists",
            "then Acceptance Generation 4 with the same frozen protocol "
            "invariants (presealed substrate as Agent-visible input, "
            "construction-time charter, projection-only bootstrap, "
            "extended seal/gate) and entirely new instances",
            "the Gen-3 holdout pool may NOT be reused (consumed)",
            "explicit user authorization before any Gen-4 execution",
        ],
    }
    (GEN3_ROOT / "acceptance-generation-closure-v3.json").write_text(
        json.dumps(closure, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print("decision -> agent-v0-acceptance-decision-v3.json")
    print("closure -> acceptance-generation-closure-v3.json")
    print("OVERALL: B6_INVALID (CLOSED_INVALID, holdout CONSUMED)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
