# B5.5 Acceptance Semantics Closure — Audit & Freeze Record

Status: COMPLETE — disposition **B2_RERUN_REQUIRED** (spec §24)
Branch: `mvp/agent-v0-typed-handle-contract`
Scope: deterministic audit only; ZERO model calls; ZERO production
runtime changes (all fixes are benchmark/truth/evaluator/harness layer).

## §1 Research question

Why were all 23 evaluable post-A1-H B2 runs `BenchmarkCaseOutcome ==
incomplete`, and which root cause class (A truth/evaluator mismatch,
B harness/bootstrap gap, C production correctness gap, D genuine model
failure) does each failed requirement belong to?

Evidence: `BaselineMeasurementReportV4`, `BenchmarkRunSnapshot`s, digest
v4 semantic payloads, `TruthManifestV1`s, `evaluate_case_outcome` v1
source, frozen production modules. Per-run table:
`b2-post-h/case-outcome-incomplete-audit-v1.json`.

## §3-§4 Coverage root cause (Q1-Q4)

- **Q1** Yes — the truth manifests' `expected_coverage` dimensions are
  charter-level Required Coverage in the frozen architecture's own
  vocabulary (`CoverageDimension.required`; the coverage axis is a first-
  class product concept).
- **Q2** They are created at **investigation initialization** (the
  seeded initial Working State). Proof: the frozen production policy is
  UPDATE-only — `CoverageTransition` on an unknown dimension raises
  `COVERAGE_DIMENSION_NOT_FOUND` and **no reachable `CreateCoverage`
  transition exists** (Q3 = confirmed).
- **Q4** YES — **the benchmark harness failed to initialize required
  state**: `PublicCaseInputV1.seed_coverage_dimensions` exists on the
  public executor surface precisely for this bootstrap, but the driver
  never populated it and `case.json` never declared the dimensions.
  Production is not incapable → **root cause B (BENCHMARK_HARNESS_DEFECT)**
  for every coverage requirement. `PRODUCTION_CORRECTNESS_GAP` (C) is
  explicitly excluded.

Fix (benchmark initialization only, Supervisor untouched): case contract
v2 declares `required_coverage_dimensions` (names ONLY — no expected
statuses, no evidence bindings, so truth isolation is preserved); the
driver now seeds them into the initial working state.

## §5 Question-disposition root cause

- Truth `expected_disposition: "answered"` — **root cause A
  (BENCHMARK_SEMANTICS_DEFECT)**: v1 counted terminal rows whose
  DISPOSITION literal is "answered"; that token does not exist in the
  frozen production contract (`QuestionStatus.answered` is the terminal;
  `QuestionDisposition ∈ {supported, not_supported, inconclusive,
  unavailable, not_applicable}`). Structurally unsatisfiable by any
  conforming run.
- Truth `expected_disposition: "unresolved"` — **satisfiable** under
  production semantics (status ∈ {unresolved, blocked, deferred}, or
  answered with refusal disposition {not_supported, inconclusive}). Runs
  that did not produce it are **root cause D (genuine model behaviour)**:
  the model answered the compound seed question without splitting the
  unresolved sub-question. Kept as a real quality result (§13).
- The acceptable-set is derived from the frozen product enums — the
  merge/causal assertion prohibitions stay policed by the overclaim and
  case-level negative gates (no set inflation, §5).

## §7 FinalizationGate vs CaseOutcome reconciliation

`FinalizationPass 21/24` vs `CaseOutcome incomplete ×23` evaluates
**different concepts** and may legitimately coexist:
- FinalizationGate: internal consistency of the Working State (no
  unintegrated completed delegation, no required question left open) —
  it never consults the TruthManifest.
- CaseOutcome: correspondence of terminal semantics to the case truth
  (critical evidence, dispositions, coverage, overclaims).
No contract inconsistency found; no obligation is claimed satisfied by
one and unsatisfied by the other under the same vocabulary. Per §8,
CaseOutcome remains truth-based; `CaseOutcome := FinalizationPass` is
forbidden and not done.

## §9-§14 Root-cause totals and path

Requirement-level classification (per `case-outcome-incomplete-audit-v1.json`):
A ×30 (answered-vocabulary ×~13, overclaim channel ×23), B ×29 (coverage),
D ×21 (semantic output never produced ×8, unresolved expectation ×6,
terminal-disposition absence on failed runs, provider 429 ×1 — the last
recorded PROVIDER_INFRA per §21). C: ZERO occurrences.

Path determination (§14):
- Coverage seeding changed the harness initial state → **Case B:
  full B2 rerun required**. A reevaluate-only pass cannot conjure
  coverage the runs never addressed.
- The disposition-vocabulary fix is evaluator-only (Case A semantics)
  and is FOLDED INTO the same rerun (evaluator v2 applies to the new
  series; v1 artifacts remain immutable).

### Evaluator v2 (implemented, `benchmark-case-outcome:v2`)

- disposition semantics per §5 above (production `(status, disposition)`
  mapping);
- overclaim component KEPT on the findings channel after the
  zero-model-call reevaluation **falsified** the proposed extension:
  substring matching over raw claim texts flags correct negations
  ("CANNOT be treated as the same person") — 16/23 false positives.
  Claim-level overclaim adjudication belongs to the case-level negative
  gates (product semantics), not string equality (§5);
- v1 stays importable and unchanged; v1 artifacts immutable.

Reevaluation evidence (existing 23 runs, evaluator v2, zero calls):
coverage reasons correctly persist on all 23 → confirms the rerun
requirement; the 10 runs whose only failures were the vocabulary/
coverage artifacts now show their true residual (model-failure or
coverage-only).

## §15/§16 Holdout static audit (no execution)

Holdout cases `t3-holdout-refund-fraud` / `t3-holdout-vpn-causal`
STATICALLY audited (files read, never executed): both truths carry
`expected_coverage` (payout-attribution / shared-egress-assessment) and
both case files lacked public coverage declarations — **the same defect**.
Holdout case contract **v2 revisions created WITHOUT any execution**:
`6e7268a90ef8 → 5d139609d06e` and `2145aa2367ca → d09eb7139eb9`
(old hashes preserved in `benchmarks/cases/b55-case-revision.json`,
supersession reason = this document, derivation solely from the frozen
product contract). New sealed hashes recorded; no holdout result exists.

## §17 AcceptanceProfile admission

`AgentV0AcceptanceProfileV1` artifact remains immutable; B6 admission is
WITHHELD pending semantic closure completion:
`benchmarks/profiles/agent-v0-acceptance-profile-admission-record.v1.json`
(status `FROZEN_PENDING_SEMANTIC_CLOSURE` → becomes `ADMITTED` only
after the post-fix B2 rerun is measured).

## §18 Numeric-threshold provenance (independent rationale, pre-holdout)

| threshold | value | provenance |
|---|---|---|
| runs_with_integrated_delegation ≥ 60% | product requirement: an investigation deliverable must produce a defensible integrated answer in a solid majority of runs; 60% is the minimum defensible operational bar, chosen BEFORE seeing holdout data |
| ≥5 of 8 cases with ≥2/3 reps integrated | engineering SLO: breadth requirement — capability must not concentrate in easy cases; 5/8 = a solid majority of case families |
| finalization pass ≥ 60% | engineering SLO: the gate is the production completion path; below 60% the runtime cannot be operated as an investigation product |
| specialist structured-output failure ≤ 50% | risk tolerance ceiling, NOT derived from the observed 29%: 50% marks COLLAPSE (systematic failure dominating outcomes); the recorded 29% model limit stays visible and is judged at B6 against this independent ceiling |
| provider-terminal runs ≤ 20% | availability SLO: resumable infra failures above one in five make acceptance non-evaluable (INFRA_BLOCKED) |

## §19 Truth-based functional floor (pending amendment, effective at rerun)

The functional axis MUST include a truth-based `BenchmarkCaseOutcome`
floor. Amendment recorded in the admission record: after the post-fix
B2 rerun, the functional gate gains
`cases with CaseOutcome ∈ {success, success_with_limitations} ≥ 3 of 8`
(product requirement: at least the solid minority of case families must
reach a truth-semantically correct terminal, not merely integrate
something). The exact number is set from the corrected evaluator's
calibration distribution at rerun completion — before any holdout
execution.

## §23 Completion gate status

| requirement | status |
|---|---|
| all 23 incomplete outcomes explained | ✅ audit artifact |
| every missing expectation classified A/B/C/D | ✅ |
| TruthManifest/evaluator aligned with frozen product semantics | ✅ evaluator v2 (+ case v2 declarations); truth files unchanged (vocabulary mapping lives in the evaluator) |
| CaseOutcome meaningful for current runtime | ⏳ requires the seeded rerun (coverage is a real expectation) |
| AcceptanceProfile includes truth-based functional floor | ✅ recorded (effective at rerun) |
| numeric threshold rationale recorded | ✅ §18 |
| holdout manifest statically audited | ✅ §15/§16 |
| holdout still NEVER RUN | ✅ |

→ **B2_RERUN_REQUIRED**: rerun B2 8×3 on corpus v2 with the seeding
driver and evaluator v2; then re-derive the B4-adjacent distributions,
admit the AcceptanceProfile, and only then B6.
