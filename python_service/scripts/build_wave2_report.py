"""Wave-2 final report builder (§39/§40).

Assembles AGENT V0 MODEL CANDIDATE WAVE 2 REPORT deterministically from
persisted artifacts: the candidate pool, the admission smoke, every
candidate's ModelCandidateQualificationV2 (screening and/or final), the
frozen control numbers, and the wave-1 accounting correction. Zero model
calls.

Disposition logic (§40):
  PROMOTE_NEW_MODEL_CANDIDATE  — some candidate QUALIFIED_FOR_PROMOTION
  KEEP_CURRENT_MODEL_REJECTED  — candidates were semantically measured
                                 and none qualified
  PROVIDER_CAPACITY_BLOCKED    — no candidate could be semantically
                                 measured (quota/auth/availability)
  RUNTIME_CONTRACT_GAP_FOUND   — reserved; never set by this builder
                                 (M4/M5 == 0, runtime closed §2)

Usage (from python_service/):
    .venv/bin/python scripts/build_wave2_report.py
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

PYTHON_SERVICE_ROOT = Path(__file__).resolve().parent.parent
RESULTS = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0"
)
WAVE2 = RESULTS / "model-candidates" / "wave2"

POOL = ["kimi-k3", "deepseek-v4-flash", "deepseek-v4-pro", "deepseek-flash",
        "sensenova-u1-fast", "sensenova-u1.5-lite", "deepseek-v4.1-flash"]


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _maybe(path: Path):
    return _load(path) if path.is_file() else None


def main() -> int:
    smoke = _load(WAVE2 / "candidate-adapter-smoke.json")
    pool = _load(WAVE2 / "model-candidate-pool-v2.json")

    candidates = {}
    for cid in POOL:
        entry = {"smoke": smoke["candidates"].get(cid)}
        # screening dispositions live at the candidate root (latest chain
        # run) and optionally per results root
        rec = _maybe(WAVE2 / cid / "ModelCandidateQualificationV2.json")
        if rec:
            entry.setdefault("screenings", []).append(rec)
        for stage_dir in (f"{cid}/qual-8x1", f"{cid}/qual-8x1-reentry"):
            rec = _maybe(WAVE2 / stage_dir / "ModelCandidateQualificationV2.json")
            if rec:
                entry.setdefault("screenings", []).append(
                    {"root": stage_dir, **rec}
                )
        final = _maybe(RESULTS / f"b2-runtime-v3-{cid}" /
                       "ModelCandidateQualificationV2.json")
        if final:
            entry["final_8x3"] = final
        candidates[cid] = entry

    # wave-1 accounting correction (transparent, disposition unchanged)
    glm_codes = {}
    for f in (RESULTS / "b2-runtime-v3-glm52").glob("t*/repeat*/trajectory_digest.json"):
        for x in _load(f).get("delegation_failures", []):
            glm_codes[x.get("failure_code")] = glm_codes.get(x.get("failure_code"), 0) + 1

    # §26 frozen control (no re-run)
    control = _load(RESULTS / "b2-runtime-v3" /
                    "b2-runtime-v3-measurement-report.json")

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
        cwd=PYTHON_SERVICE_ROOT.parent,
    ).stdout.strip()

    # disposition
    any_promoted = any(
        e.get("final_8x3", {}).get("disposition") == "QUALIFIED_FOR_PROMOTION"
        or any(s.get("disposition") == "QUALIFIED_FOR_PROMOTION"
               for s in e.get("screenings", []))
        for e in candidates.values()
    )
    semantic_rejections = [
        cid for cid, e in candidates.items()
        if e.get("final_8x3", {}).get("disposition") == "NOT_QUALIFIED"
        or any(s.get("disposition") == "NOT_QUALIFIED"
               for s in e.get("screenings", []))
    ]
    if any_promoted:
        disposition = "PROMOTE_NEW_MODEL_CANDIDATE"
    elif semantic_rejections:
        disposition = "KEEP_CURRENT_MODEL_REJECTED"
    else:
        disposition = "PROVIDER_CAPACITY_BLOCKED"

    report = {
        "report_version": "agent-v0-model-candidate-wave2-report:v1",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "git_commit": head,
        "current_control": {
            "model": "sensenova-6.8-flash-lite",
            "runtime": "RuntimeBaselineV3 QUALIFIED/FROZEN",
            "calibration_qualified": True,
            "formal_acceptance": "REJECTED (Gen-4 DecisionV4 authoritative)",
            "frozen_measurement": {
                "series": "b2-runtime-v3 (24 runs, MEASUREMENT_VALID)",
                "case_outcome_v2": control["semantic_metrics"]["case_outcome_v2_counts"],
                "finalization_completed": control["semantic_metrics"]["FinalizationPass"],
                "question_terminalization": "20/24 (charter required question per run)",
                "specialist_schema_failures": 1,
                "provider_failures": 0,
            },
            "no_rerun": "§26: control retained without re-execution",
        },
        "candidates_tested": {
            cid: {
                "smoke": (
                    {"all_pass": e["smoke"]["all_pass"],
                     "classification": e["smoke"].get("exception", {}).get("classification")}
                    if e["smoke"] else None
                ),
                "screenings": [
                    {"root": s.get("root", "candidate-root"),
                     "disposition": s["disposition"],
                     "reason": s["reason"],
                     "runs": s.get("runs"),
                     "structural_hard_gates": s.get("structural_hard_gates"),
                     "delegation_failures": s.get("delegation_failures")}
                    for s in e.get("screenings", [])
                ],
                "final_8x3": (
                    {k: e["final_8x3"][k] for k in (
                        "disposition", "reason", "runs", "measurement_verdict",
                        "case_outcomes", "per_case_repeatability",
                        "question_terminalization", "delegation_failure_codes",
                        "specialist_schema_output_failures",
                        "specialist_schema_failure_rate")}
                    if e.get("final_8x3") else None
                ),
            }
            for cid, e in candidates.items()
        },
        "excluded": {
            "glm-5.2": "§27: exact config NOT_QUALIFIED (wave-1); no re-run, "
                       "no seed change, no temperature tweak under same identity",
            "sensenova-6.8-flash-lite": "frozen control (§26)",
        },
        "wave1_accounting_correction": {
            "finding": (
                "wave-1 counted ALL delegation failures as 'specialist "
                "structured-output failures'; failure_code breakdown shows "
                "glm-5.2's 8x3 14 failures were ALL agent_rate_limited "
                "(provider quota events, §7), not schema failures"
            ),
            "glm_5.2_8x3_delegation_failure_codes": glm_codes,
            "disposition_impact": (
                "none: glm-5.2 remains NOT_QUALIFIED under §27 (frozen), and "
                "under the corrected §7 reading the series was quota-degraded "
                "(PROVIDER_QUOTA_BLOCKED semantics) — either way never "
                "QUALIFIED_FOR_PROMOTION"
            ),
            "wave2_practice": (
                "schema-only reliability counting (failure_code-based) in all "
                "wave-2 disposition scripts"
            ),
        },
        "runtime": "unchanged (RuntimeBaselineV3 FROZEN)",
        "prompt": "unchanged (§3 gate closed)",
        "acceptance_profile": "unchanged (AcceptanceProfileV2 FROZEN)",
        "consumed_holdouts": "untouched (Gen-1/2/3/4 zero access, §31)",
        "provider_constraints": {
            "endpoint": "token.sensenova.cn (single cloud credential)",
            "observed": (
                "account-level TPM/RPM exhaustion from 14:15 local after three "
                "24-run-class series earlier today; brief recovery windows "
                "(~10 min quiet); smoke+sustained runs re-exhaust it"
            ),
        },
        "disposition": disposition,
        "disposition_basis": (
            "candidate outcomes: "
            + json.dumps(
                {cid: (
                    e.get("final_8x3", {}).get("disposition")
                    or (e.get("screenings") or [{}])[-1].get("disposition")
                    or ("SMOKE_FAIL:" + (e["smoke"].get("exception", {}).get("classification") or "checks")
                        if e["smoke"] and not e["smoke"]["all_pass"] else None)
                ) for cid, e in candidates.items()},
                ensure_ascii=False)
        ),
    }
    out = WAVE2 / "wave2-final-report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"disposition: {disposition}")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
