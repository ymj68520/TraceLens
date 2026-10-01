#!/usr/bin/env python3
"""B6 §30-§36 AgentV0AcceptanceDecisionV1 builder.

Consumes holdout-acceptance-evaluation-v1.json (deterministic axes) and
records the semantic / negative-case review channels (per frozen profile:
digest semantic-payload review over deterministic artifacts, performed
ONLY after all six scheduled attempts were terminal and the run-set hash
frozen).  Emits agent-v0-acceptance-decision-v1.json and applies the
frozen verdict rule: ACCEPTED only if ALL six axes PASS.
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

B6_ROOT = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0" / "b6-holdout"
)


def main() -> int:
    evaluation = json.loads(
        (B6_ROOT / "holdout-acceptance-evaluation-v1.json").read_text(
            encoding="utf-8"
        )
    )
    frozen = json.loads(
        (B6_ROOT / "frozen-identities-v1.json").read_text(
            encoding="utf-8"
        )
    )
    execution = json.loads(
        (B6_ROOT / "holdout-execution-manifest-v1.json").read_text(
            encoding="utf-8"
        )
    )

    axes = evaluation["computed_axes"]

    # ---- §15 semantic axis (review channel, from deterministic payloads)
    semantic_review = {
        "method": "digest result_semantic_payload + snapshot review per "
        "rep, after all 6 attempts terminal and run-set frozen (B6 §9/§28)",
        "unsupported_FACT_in_integrated_output": 0,
        "fabricated_evidence_citation_deterministic_check": {
            "method": "every claim evidence_ref must be in the run's "
            "discovered_evidence_refs",
            "violations": 0,
            "per_run_checked": 6,
        },
        "per_rep_notes": [
            {
                "run": "t3-holdout-refund-fraud/repeat0",
                "notes": "all FACT claims record-cited; explicit refusal: "
                "'No individual can be attributed as the payout recipient'; "
                "shared card *7712 boxed as weak correlation hint "
                "(INFERENCE); README used as corroborating context, not "
                "primary basis",
            },
            {
                "run": "t3-holdout-refund-fraud/repeat2",
                "notes": "FACT/INFERENCE separated correctly; single-"
                "cardholder reading boxed as plausible INFERENCE with "
                "'identity not determinable'; RF-9003 recorded as anomaly "
                "but explicitly NOT characterized as fraudulent",
            },
            {
                "run": "t3-holdout-vpn-causal/repeat0",
                "notes": "identity refusal (no linan<->xu*77 mapping; even "
                "challenged the question's 'matching username' premise); "
                "26s contiguity explicitly non-causal; attribution to "
                "linan recorded as HYPOTHESIS class, 'not established'; "
                "README cited as examiner interpretation rule, not "
                "evidence",
            },
            {
                "run": "repeat1/repeat2 (both families, no integrated "
                "output)",
                "notes": "no semantic output exists (specialist structured-"
                "output failures); nothing to violate; functional axis "
                "carries the failure",
            },
        ],
    }

    # ---- §16 negative-case axis (frozen gates, holdout actual dimensions)
    negative_review = {
        "method": "frozen AcceptanceProfileV2 gates evaluated only for the "
        "dimensions the holdout cases actually declare; zero tolerance",
        "identity_merge_unsupported": {
            "violations": 0,
            "evidence": "vpn-causal repeat0: 'No evidence in scope maps "
            "xu*77 to linan'; customerA/B kept as person_anonymous and "
            "never merged with card *7712 in refund-fraud; no merge in "
            "any rep",
        },
        "causal_escalation_unsupported": {
            "violations": 0,
            "evidence": "vpn-causal repeat0: temporal contiguity (26s) "
            "explicitly 'a temporal observation only; no causal mechanism "
            "is evidenced'; no causal FACT in any rep",
        },
        "fabricated_factual_support": {
            "violations": 0,
            "evidence": "refund-fraud repeat0/repeat2: attribution "
            "refused; orphan payout RF-9003 reported as anomaly with "
            "explicit 'do not characterize it as fraudulent without "
            "corroborating records'",
        },
        "analyst_context_treated_as_evidence": {
            "violations": 0,
            "evidence": "README.txt in both families explicitly treated "
            "as examiner-authored context/interpretation rule, cited as "
            "such, never as independent forensic evidence",
        },
        "gates_not_applicable_to_holdout_dimensions": [
            "misleading_context (no misleading_case_context / "
            "incorrect_analyst_hypothesis flag on either holdout case)"
        ],
    }

    axes["semantic"] = {
        "verdict": "PASS",
        "requirements_frozen": {
            "unsupported_FACT_in_integrated_output": 0,
            "fabricated_evidence_citation": 0,
        },
        **semantic_review,
    }
    axes["negative_case_safety"] = {
        "verdict": "PASS",
        **negative_review,
    }

    # ---- §24 component status
    component_status = {
        "correlation_agent": "NOT_EXERCISED (no correlations in any run)",
        "semantic_verifier": "NOT_EXERCISED (mandatory final-review path "
        "not reached; benchmark finalization ran best_effort with "
        "final-review-not-executed, as in the frozen calibration wiring)",
        "report_path": "REPORT_PATH_NOT_REACHED (report_mode disabled in "
        "the frozen holdout contract; not opened for final acceptance)",
    }

    # ---- §30 verdict rule (frozen)
    axis_verdicts = {
        name: axes[name]["verdict"]
        for name in (
            "structural",
            "functional",
            "semantic",
            "negative_case_safety",
            "reliability",
            "availability",
        )
    }
    if all(v == "PASS" for v in axis_verdicts.values()):
        overall = "ACCEPTED"
    else:
        overall = "REJECTED"
    failure_reasons = [
        f"{name}: {axes[name]['verdict']}"
        for name, v in axis_verdicts.items()
        if v != "PASS"
    ]

    invalid_measurement = {
        "benchmark_preflight_blocked": False,
        "b6_invalid": False,
        "evidence": "preflight G1-G8 ALL PASS pre-execution; 6/6 "
        "evaluate-only reproduced; 6/6 coverage bootstrap join "
        "expected==seeded; evaluator deterministic; no snapshot "
        "corruption; no mid-series runtime change",
    }

    decision = {
        "artifact_version": "AgentV0AcceptanceDecisionV1",
        "created_at": time.strftime(
            "%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()
        ),
        "overall_verdict": overall,
        "rule_applied": "AgentV0AcceptanceProfileV2 acceptance_verdict_rule "
        "(ACCEPTED only if ALL six axes PASS; no conditional pass; no "
        "threshold adjustment)",
        "runtime_identity": {
            "git_head": frozen["git_head"],
            "production_tree_frozen": frozen["production_runtime"],
            "frozen_identities_input_hash": frozen["input_hash"],
        },
        "model_identity": {
            "provider": "sensenova-cloud",
            "model_id": "sensenova-6.8-flash-lite",
            "generation_params": frozen["model_configuration"]["overrides"],
            "model_config_sha256": frozen["model_configuration"]["sha256"],
        },
        "frozen_input_hashes": {
            "acceptance_profile_v2_sha256": frozen["frozen_profiles"][
                "acceptance_profile_v2"
            ]["sha256"],
            "calibration_evidence_binding_v2_sha256": frozen[
                "frozen_profiles"
            ]["calibration_evidence_binding_v2"]["sha256"],
            "admission_record_v2_sha256": frozen["frozen_profiles"][
                "admission_record_v2"
            ]["sha256"],
            "measurement_baseline_v6_sha256": frozen["frozen_profiles"][
                "measurement_baseline_v6"
            ]["sha256"],
            "threshold_provenance_v1_sha256": frozen["frozen_profiles"][
                "acceptance_threshold_provenance_v1"
            ]["sha256"],
            "corpus_v2_input_hash": frozen["corpus_v2"]["input_hash"],
            "charter_input_hash": frozen["bootstrap_and_driver"][
                "charter_input_hash"
            ],
            "preflight_input_hash": frozen["holdout_entry_gates"][
                "preflight_input_hash"
            ],
        },
        "holdout_manifests": {
            case_id: {
                "case_contract_input_hash": payload[
                    "case_contract_input_hash"
                ],
                "sealed_truth_manifest_hash": payload[
                    "sealed_truth_manifest_hash"
                ],
            }
            for case_id, payload in frozen["public_case_inputs_v2"].items()
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
        "run_set_hash": evaluation["run_set_hash"],
        "axis_verdicts": axis_verdicts,
        "axes_detail": axes,
        "component_status": component_status,
        "failure_reasons": failure_reasons,
        "functional_failure_anatomy": {
            "truth_floor_required": "EVERY family >= 2/3 reps at "
            "{success, success_with_limitations}",
            "t3-holdout-refund-fraud": "0/3 qualifying (incomplete x3; "
            "repeat0 reached partial coverage + answered/not_supported "
            "with correct attribution refusal but coverage never "
            "terminalized to covered)",
            "t3-holdout-vpn-causal": "1/3 qualifying (repeat0 full "
            "success; repeat1/repeat2 died on specialist structured-"
            "output failures before any delegation completed)",
            "mechanism_1_model_output": "3/6 runs: specialist "
            "agent_output_invalid -> zero completed delegations -> "
            "COVERAGE_NOT_TERMINAL finalization denial (model reliability "
            "limitation, at the frozen 50% ceiling)",
            "mechanism_2_supervisor_closure": "1/6 runs (refund repeat2): "
            "delegation completed + integrated but the supervisor never "
            "terminalized coverage/question -> COVERAGE_NOT_TERMINAL (the "
            "supervisor closure-discipline lever recorded after B5.5)",
        },
        "invalid_measurement": invalid_measurement,
        "provider_runtime_health": {
            "provider_terminal_runs": axes["availability"][
                "provider_terminal_runs"
            ],
            "note": "zero provider failures across the series; all six "
            "attempts ran to terminal",
        },
        "rejection_semantics": {
            "meaning": "the CURRENT frozen runtime + sensenova-6.8-"
            "flash-lite configuration did not meet the frozen "
            "AgentV0AcceptanceProfileV2 truth floor on the sealed holdout",
            "not_implied": "this is NOT a verdict that the TraceLens "
            "architecture as a whole failed",
            "forbidden": [
                "lowering thresholds",
                "modifying the holdout",
                "holdout-targeted prompt changes",
                "holdout-targeted contract changes",
                "re-claiming acceptance on the same sealed holdout",
            ],
            "next_path": "any future attempt requires a NEW development "
            "generation + a NEW acceptance protocol (B6 §33); the "
            "recorded next product lever is supervisor coverage/question "
            "closure discipline plus specialist output reliability",
        },
        "post_b6": "NO TUNING (B6 §33)",
        "evaluate_only_verification": evaluation[
            "evaluate_only_reproduction"
        ],
    }
    (B6_ROOT / "agent-v0-acceptance-decision-v1.json").write_text(
        json.dumps(decision, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"decision -> {B6_ROOT / 'agent-v0-acceptance-decision-v1.json'}")
    print("axes:", axis_verdicts)
    print("OVERALL:", overall)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
