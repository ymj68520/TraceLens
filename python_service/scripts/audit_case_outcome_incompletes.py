#!/usr/bin/env python3
"""P8B B5.5 §3 — CaseOutcomeIncompleteAuditV1 generator.

Deterministic, zero-LLM audit of every incomplete BenchmarkCaseOutcome in
the post-A1-H B2 series.  For each run, decomposes the evaluator
components into exact failed requirements and classifies each against the
root-cause taxonomy (spec §1/§9-§13):

  A BENCHMARK_SEMANTICS_DEFECT   — truth/evaluator vocabulary or shape not
                                   derivable from the frozen production
                                   contract (disposition "answered";
                                   overclaim measured on a findings channel
                                   production does not populate)
  B BENCHMARK_HARNESS_DEFECT     — required coverage dimensions never
                                   seeded although the public case surface
                                   and executor hook exist (driver omitted
                                   seed_coverage_dimensions)
  C PRODUCTION_CORRECTNESS_GAP   — frozen contract requires an object the
                                   runtime has no path to create
  D MODEL_SEMANTIC_FAILURE       — contract satisfiable, model did not do
                                   it (semantic output never produced;
                                   compound question not split/closed)

Usage (from python_service/):
    .venv/bin/python scripts/audit_case_outcome_incompletes.py
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

ROOT = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0" / "b2-restart"
)
RUNS_ROOT = ROOT / "b2-post-h"
CASES_ROOT = PYTHON_SERVICE_ROOT / "benchmarks" / "cases"
COMPONENTS_FILE = ROOT / "b2-post-h" / "case-outcome-components.json"
OUT_FILE = ROOT / "b2-post-h" / "case-outcome-incomplete-audit-v1.json"

# field evidence for classifications (from the frozen-code audit,
# docs/specs/agent-b55-acceptance-semantics-audit.md)
COVERAGE_CLASS = "B_BENCHMARK_HARNESS_DEFECT"
COVERAGE_BASIS = (
    "Q1-Q4: coverage dimensions are charter-level Required Coverage; the "
    "production contract is update-only (CoverageTransition -> "
    "COVERAGE_DIMENSION_NOT_FOUND; no reachable CreateCoverage), creation "
    "belongs to investigation bootstrap. The benchmark public surface "
    "PublicCaseInputV1.seed_coverage_dimensions exists exactly for this, "
    "but the driver never populated it and case.json never declared the "
    "dimensions. Production is not incapable; the harness failed to "
    "initialize required state."
)
ANSWERED_CLASS = "A_BENCHMARK_SEMANTICS_DEFECT"
ANSWERED_BASIS = (
    "evaluator counts terminal rows with disposition=='answered', but the "
    "frozen production contract expresses answered as "
    "QuestionStatus=answered with QuestionDisposition in "
    "{supported, not_supported, inconclusive, unavailable, "
    "not_applicable} — the literal disposition 'answered' does not exist "
    "in the production enum, so the requirement is unsatisfiable by any "
    "conforming run. Truth/evaluator vocabulary defect, not a model or "
    "runtime defect."
)
UNRESOLVED_CLASS = "D_MODEL_SEMANTIC_FAILURE"
UNRESOLVED_BASIS = (
    "truth expects an unresolved-type terminal for a distinct sub-question; "
    "the production contract can express it (QuestionStatus=unresolved or "
    "answered with disposition not_supported/inconclusive, and "
    "create_question is available), but the model answered the compound "
    "seed question without splitting the unresolved sub-question. "
    "Satisfiable, not done — retained as a genuine quality result."
)
OVERCLAIM_CLASS = "A_BENCHMARK_SEMANTICS_DEFECT"
OVERCLAIM_BASIS = (
    "overclaim is measured over snapshot.findings, a channel the frozen "
    "production flow never populates in benchmark runs (P5 findings "
    "require the unexercised verifier path; integrated semantics live in "
    "claim candidates). Component structurally unobservable — evaluator/"
    "snapshot shape mismatch, not model behaviour. Digest v4 carries the "
    "integrated claim texts for a v2 evaluator."
)
NO_SEMANTIC_CLASS = "D_MODEL_SEMANTIC_FAILURE"
NO_SEMANTIC_BASIS = (
    "specialist delegation failed output validation before any semantic "
    "output existed (7 runs) or the run never completed (provider 429) — "
    "genuine model/infra result, correctly incomplete; not fixable by "
    "benchmark revision."
)
PROVIDER_CLASS = "PROVIDER_INFRA"


def main() -> int:
    rows = json.loads(COMPONENTS_FILE.read_text(encoding="utf-8"))
    runs = []
    for r in rows:
        if r["outcome"] == "unavailable":
            runs.append(
                {
                    "case_id": r["case"],
                    "repeat": r["repeat"],
                    "outcome": "unavailable",
                    "failed_requirements": [
                        {
                            "requirement": "run completion",
                            "expected": "terminal benchmark run",
                            "observed": "runner failure: provider HTTP 429 "
                            "(inference exceeds tpm/rpm limit)",
                            "requirement_source": "benchmark harness",
                            "root_cause": PROVIDER_CLASS,
                        }
                    ],
                }
            )
            continue
        reqs = []
        for c in r["components"]:
            status = c["status"]
            if status == "satisfied":
                continue
            name = c["component"]
            if name == "semantic_output_available":
                reqs.append(
                    {
                        "requirement": "integrated semantic output",
                        "expected": ">=1 integrated delegation or findings",
                        "observed": c["detail"],
                        "requirement_source": "evaluator §14/§40",
                        "root_cause": NO_SEMANTIC_CLASS,
                        "basis": NO_SEMANTIC_BASIS,
                    }
                )
            elif name == "question_dispositions":
                detail = c["detail"]
                truth_part = detail.split("truth expects")[-1]
                if "answered=1" in truth_part:
                    reqs.append(
                        {
                            "requirement": "answered-type terminal question",
                            "expected": (
                                "truth expected_disposition=answered; "
                                "production terminal = QuestionStatus="
                                "answered with a recorded "
                                "QuestionDisposition"
                            ),
                            "observed": detail,
                            "requirement_source": "TruthManifest "
                            "expected_questions + evaluator §4.3",
                            "root_cause": ANSWERED_CLASS,
                            "basis": ANSWERED_BASIS,
                        }
                    )
                if "unresolved=1" in truth_part:
                    reqs.append(
                        {
                            "requirement": (
                                "unresolved-type terminal disposition for "
                                "the truth's distinct sub-question"
                            ),
                            "expected": (
                                "a terminal row in "
                                "{unresolved, blocked, deferred} or an "
                                "answered row with disposition "
                                "{not_supported, inconclusive}"
                            ),
                            "observed": detail,
                            "requirement_source": "TruthManifest "
                            "expected_questions (notes mark unresolved as "
                            "the correct terminal)",
                            "root_cause": UNRESOLVED_CLASS,
                            "basis": UNRESOLVED_BASIS,
                        }
                    )
                if "terminal=0" in detail:
                    reqs.append(
                        {
                            "requirement": (
                                "any terminal question disposition"
                            ),
                            "observed": detail,
                            "requirement_source": "evaluator §4.3",
                            "root_cause": NO_SEMANTIC_CLASS,
                            "basis": NO_SEMANTIC_BASIS,
                        }
                    )
            elif name.startswith("coverage:"):
                reqs.append(
                    {
                        "requirement": (
                            f"required coverage dimension "
                            f"{name.split(':', 1)[1]} terminal in "
                            f"{{covered, partial}}"
                        ),
                        "expected": (
                            "dimension seeded at investigation bootstrap "
                            "and closed with basis by integration"
                        ),
                        "observed": c["detail"],
                        "requirement_source": "TruthManifest "
                        "expected_coverage + evaluator §4.4",
                        "root_cause": COVERAGE_CLASS,
                        "basis": COVERAGE_BASIS,
                    }
                )
            elif name == "overclaim_constraints":
                reqs.append(
                    {
                        "requirement": (
                            "prohibited overclaim observability"
                        ),
                        "expected": (
                            "integrated claim/finding texts exposed on the "
                            "snapshot findings channel"
                        ),
                        "observed": c["detail"],
                        "requirement_source": "evaluator §4.5",
                        "root_cause": OVERCLAIM_CLASS,
                        "basis": OVERCLAIM_BASIS,
                    }
                )
        runs.append(
            {
                "case_id": r["case"],
                "repeat": r["repeat"],
                "outcome": r["outcome"],
                "rationale": r["rationale"],
                "failed_requirements": reqs,
            }
        )

    from collections import Counter

    causes = Counter(
        req["root_cause"]
        for run in runs
        for req in run["failed_requirements"]
    )
    artifact = {
        "artifact_version": "CaseOutcomeIncompleteAuditV1",
        "round": "p8b-b55-acceptance-semantics-closure",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "scope": "23 incomplete + 1 unavailable runs of b2-post-h",
        "root_cause_totals": dict(causes),
        "runs": runs,
    }
    OUT_FILE.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"audit -> {OUT_FILE}")
    print("root causes:", dict(causes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
