#!/usr/bin/env python3
"""P8B Model Qualification — ModelQualificationExperimentV1 assembly
(§23/§24/§26/§15).

Consumes the Q1 screening report, the Q1 promotion decision and the four
ModelQualificationConfigV1 artifacts, and emits the frozen experiment
record:

  - candidate configs + every run id with hard gates, case outcomes,
    integration validity, reliability, tokens, wall time
  - per-candidate selection disposition (§24 enum)
  - MiMo final qualification (§26, data retained)
  - CC-1 reclassification review (§28/§29)
  - overall selection decision (§15 NO_QUALIFIED_MODEL_CONFIGURATION)
  - profile freeze precondition status (§31/§32)

Usage (from python_service/):
    .venv/bin/python scripts/build_model_qualification_experiment.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PYTHON_SERVICE_ROOT = SCRIPT_PATH.parents[1]
QUAL_ROOT = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0"
    / "model-qualification"
)
OUT_FILE = QUAL_ROOT / "model-qualification-experiment.v1.json"
CREATED_AT = "2026-09-28T00:00:00+00:00"
RUNTIME_COMMIT = "946f325eeb6add1072466aed96e5e2e7e38748ed"

MIMO_REFERENCE = "mimo-v2.6-flash-reference"

CANDIDATE_DISPOSITIONS = {
    "deepseek-v4-flash": {
        "disposition": "rejected",
        "rationale": (
            "0/8 case success; 8/8 completed runs integration-invalid "
            "count-level; rejection signature INTEGRATION_BASIS_REF_UNKNOWN "
            "(5) + PLAN_IDENTITY_MISMATCH (3).  Investigates genuinely "
            "(up to 57 tool calls, full critical recall where it runs) "
            "but cannot produce a valid Supervisor INTEGRATE proposal — "
            "the same wall as the reference.  §14/§15: no material "
            "improvement; also 4-8x reference wall time (median 534s vs "
            "118s), so it is dominated on the §13 priority axes."
        ),
    },
    "kimi-k3": {
        "disposition": "rejected",
        "rationale": (
            "0/7 completed-run case success; 7/7 integration-invalid; "
            "dominant rejection EVIDENCE_REF_CROSS_TASK x33 — a "
            "systematic invalid integration identity (§12 qualification "
            "issue, not compensable).  1 endpoint 500 (available channel "
            "missing) classified PROVIDER/INFRA per §12.  Fastest "
            "candidate (median 96s) and clean recall, but functionally "
            "unable to close a single delegation into the working state."
        ),
    },
    "glm-5.3": {
        "disposition": "inconclusive",
        "rationale": (
            "Endpoint deployment non-responsive during compatibility "
            "probing (6/6 probe requests, incl. streaming, produced zero "
            "bytes within 60-302s), so Q1 screened 1/8 cases (§14: no "
            "calls wasted on formal symmetry).  The single available run "
            "finalized with an empty investigation (0 delegations, 0 "
            "tool calls, incomplete outcome) — the same failure family "
            "as the reference — but the sample is too small for a "
            "capability verdict.  Recorded honestly as inconclusive, "
            "not screened-out on quality."
        ),
    },
}


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    screening = json.loads(
        (QUAL_ROOT / "q1-screening-report.v1.json").read_text(
            encoding="utf-8"
        )
    )
    decision = json.loads(
        (QUAL_ROOT / "q1-promotion-decision.v1.json").read_text(
            encoding="utf-8"
        )
    )
    configs = {}
    for cfg_file in sorted((QUAL_ROOT / "configs").glob("*.config.json")):
        cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
        configs[cfg["candidate_id"]] = {
            "config_file": cfg_file.name,
            "config_hash": _sha256_file(cfg_file),
            "requested_model_id": cfg["requested_model_id"],
            "api_reported_model_id": cfg["api_reported_model_id"],
            "adapter_config_hash": cfg["adapter_config_hash"],
            "effective_adapter_config": cfg["effective_adapter_config"],
            "compatibility_encoding": cfg["compatibility_encoding"],
            "overrides": cfg["overrides"],
        }

    candidates_out = {}
    for cid, entry in screening["candidates"].items():
        s = entry["summary"]
        runs_out = []
        for run in entry["runs"]:
            runs_out.append(
                {
                    "run_dir": run["run_dir"],
                    "run_id": run.get("run_id"),
                    "status": run.get("status"),
                    "result_hash": run.get("result_hash"),
                    "case_outcome": run.get("outcome"),
                    "finalization_pass": run.get("finalization_pass"),
                    "integration_invalid_count_level": run.get(
                        "integration_invalid_count_level"
                    ),
                    "rejection_reasons": run.get("rejection_reasons"),
                    "critical_recall": run.get("critical_recall"),
                    "tool_calls_total": run.get("tool_calls_total"),
                    "wall_ms_total": run.get("wall_ms_total"),
                    "usage_tokens": run.get("usage_tokens"),
                    "failure_reason": (
                        (run.get("failure_reason") or "")[:200] or None
                    ),
                    "provider_failure": run.get("provider_failure"),
                }
            )
        cand = {
            "summary": s,
            "not_run_cases": entry["not_run_cases"],
            "hard_gate_violations": entry["hard_gate_violations"],
            "runs": runs_out,
        }
        if cid == MIMO_REFERENCE:
            cand["role"] = "reference"
            cand["disposition"] = {
                "disposition": "unsupported_provisional_supervisor_role",
                "rationale": (
                    "§26 final qualification: MiMo-V2.6-Flash remains "
                    "unsupported/provisional for the Supervisor role.  "
                    "Its 24-run measured baseline is retained unchanged.  "
                    "The qualification experiment generalizes the "
                    "finding: the INTEGRATE wall is not MiMo-specific."
                ),
            }
        else:
            cand["role"] = "q1_candidate"
            cand["disposition"] = CANDIDATE_DISPOSITIONS[cid]
            cand["config"] = configs.get(cid)
        candidates_out[cid] = cand

    artifact = {
        "artifact_version": "ModelQualificationExperimentV1",
        "experiment_id": "mqexp-agent-v0-2026-09-28",
        "production_runtime_commit": RUNTIME_COMMIT,
        "pre_calibration_profile_hash": (
            "6dd38a0e0f68704fb881e7e1f78031d58dc54368b6188826a3262660d86b218c"
        ),
        "corpus_id": screening["corpus_id"],
        "corpus_hash": screening["corpus_hash"],
        "experiment_axis": "provider/model identity + provider-required "
        "compatibility encoding ONLY (§3/§4); all prompts, policies, "
        "tool registry, temperatures (except kimi provider-forced "
        "temperature=1), max tokens, timeouts, corpus and repeat "
        "semantics frozen",
        "phases_executed": {
            "q1_screening": "executed (3 candidates x up to 8 cases x 1 "
            "repeat + 24-run reference reuse)",
            "q2_qualification": "NOT EXECUTED — §15 stop (no eligible "
            "candidate)",
        },
        "inputs": {
            "q1_screening_report": {
                "file": "q1-screening-report.v1.json",
                "sha256": _sha256_file(
                    QUAL_ROOT / "q1-screening-report.v1.json"
                ),
            },
            "q1_promotion_decision": {
                "file": "q1-promotion-decision.v1.json",
                "sha256": _sha256_file(
                    QUAL_ROOT / "q1-promotion-decision.v1.json"
                ),
            },
        },
        "candidates": candidates_out,
        "structural_hard_gates": {
            "all_candidates_all_runs": "PASS",
            "violations": [],
            "note": "no candidate committed a correctness violation "
            "(cross-task leak, fabricated evidence acceptance, authority "
            "bypass, assertion ceiling breach); the failure mode is "
            "functional (Supervisor INTEGRATE contract), not safety",
        },
        "cc1_reclassification_review": {
            "finding": "CC-1 SupervisorIntegrationProposalInvalidRate",
            "classification": "MODEL_CAPABILITY_LIMIT — now GENERALIZED "
            "across the tested model population",
            "evidence": (
                "4 models from 4 families (MiMo-V2.6-Flash, "
                "DeepSeek-V4-Flash, kimi-k3, glm-5.3 single-run) all "
                "fail at the same Supervisor INTEGRATE wall with 0 "
                "aggregate case success and ~100% integration-invalid "
                "rate, each with a DISTINCT rejection signature (MiMo: "
                "question-disposition/closure-basis semantics; DeepSeek: "
                "INTEGRATION_BASIS_REF_UNKNOWN; kimi: "
                "EVIDENCE_REF_CROSS_TASK x33; glm: empty-investigation "
                "path).  §28's confirm-by-selected-model path is not "
                "applicable (no model selected); §29 applies: no "
                "CALIBRATABLE_NUMERIC causal evidence, therefore "
                "production_changes = [] and no cycle/budget increase."
            ),
            "production_changes": [],
            "never_justify_relaxation": "these results NEVER justify "
            "relaxing StateTransitionPolicy or FinalizationGate (§46 of "
            "the B3.5/B4 spec, unchanged §45)",
        },
        "selection_decision": {
            "decision": "none",
            "status": "NO_QUALIFIED_MODEL_CONFIGURATION",
            "rule": "§15",
            "rationale": (
                "Every screened candidate is approximately the reference: "
                "0 aggregate case success (0/7, 0/8, 0/1 vs reference "
                "0/24) and integration-invalid rate 1.0 on completed "
                "runs.  No candidate materially improves functional "
                "behavior, so none may be validated and Q2 is not "
                "entered."
            ),
            "required_next_step_outside_p8b": (
                "Re-evaluate model capability requirements (reasoning-"
                "class models, larger context discipline) OR the "
                "Supervisor output interaction design (§15).  Per the "
                "spec this is no longer numeric P8 calibration work."
            ),
        },
        "profile_freeze_preconditions": {
            "calibration_profile": {
                "status": "CANDIDATE / PROVISIONAL — freeze blocked",
                "reason": "§31 precondition (selected model) unmet: "
                "NO_QUALIFIED_MODEL_CONFIGURATION.  A deployment "
                "calibration profile cannot bind a model that does not "
                "exist.",
            },
            "acceptance_profile": {
                "status": "CANDIDATE — freeze blocked",
                "reason": "§32 requires product correctness requirements "
                "+ full v5 calibration distributions + selected model "
                "reliability.  The third input does not exist.  §33 "
                "analysis recorded: the 0.8 aggregate proposal has NO "
                "empirical anchor in any measured distribution (all "
                "four models measure 0.0); freezing it now would freeze "
                "a number no configuration can be measured against, and "
                "§33's case-level requirements (negative/high-risk "
                "cases must pass individually, never be masked by the "
                "aggregate) are recorded in the candidate for the "
                "future freeze.  §34 dual-axis (functional floor + "
                "semantic correctness ceiling) remains in the candidate.",
            },
        },
        "holdout": {
            "status": "SEALED / NEVER RUN",
            "note": "§2: the acceptance holdout remained sealed through "
            "the entire qualification experiment; no holdout-based "
            "selection, inspection or tuning occurred.",
        },
        "created_at": CREATED_AT,
    }
    OUT_FILE.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"experiment -> {OUT_FILE}")
    print("selection: none — NO_QUALIFIED_MODEL_CONFIGURATION (§15)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
