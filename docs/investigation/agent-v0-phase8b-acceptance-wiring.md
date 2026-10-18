# TraceLens Agent v0 — Phase 8B

# Measured Acceptance Wiring / Calibration Policy / Final Closure Contracts

Status: **IMPLEMENTATION COMPLETE / ACCEPTANCE PENDING** (§104: code
complete ≠ phase PASS — the acceptance holdout has NOT run because no
funded model provider was available; see §4. The honest disposition is
recorded, not claimed).

P8A baseline: `f13ffd89` (P8A frozen HEAD). Branch:
`mvp/agent-v0-phase8-benchmark-acceptance-calibration` (same branch, per
plan §0).

## 1. Commits (P8B)

```text
P8B-1  d6a53872  feat: wire live agent benchmark execution and corpus freeze
P8B-5  5179acac  feat: add agent v0 acceptance report contracts
docs   this commit
```

P8B-3 (baseline measurement) and P8B-4 (calibration) were NOT created:
§83/§104 forbid fabricating measured results, and §95 forbids declaring
acceptance without real production-path runs.

## 2. B0 — Production execution wiring (§7-§12, E2/E3/E4)

`ProductionBenchmarkExecutor` (`benchmarks/production_executor.py`)
drives the REAL production pipeline through public APIs only:

```text
fresh task_id (bench-<run_id>) + fresh investigation id
→ orchestrator.create_investigation (typed v1 Working State seeded from
  the PUBLIC case input: goal/seed questions/coverage — no truth)
→ orchestrator.admit_run (production run admission)
→ orchestrator.run_loop (PLAN→EXECUTE→INTEGRATE→EVALUATE, production
  Supervisor/Specialist/verifier paths untouched)
→ orchestrator.finalize (the REAL FinalizationGate decides; a refusal
  leaves terminal_status failed — never overridden)
→ BenchmarkRunSnapshot built from durable stores only
```

- Truth isolation (§9/E3): the executor's public interface takes
  `PublicCaseInputV1` + the run manifest; no truth-typed parameter
  exists anywhere in the call graph (signature + source tests).
- Fresh-run isolation (§10/E4): every repetition gets a fresh
  task/investigation; warm caches would only reuse declared
  infrastructure caches, never case semantic results.
- Timeout (§11): covers the whole run; expiry returns the PARTIAL
  snapshot with `terminal_status=failed` and a recorded limitation —
  timeout runs are never deleted.
- No direct Finding inserts, no Working State mutation, no gate bypass
  (§8): the adapter implements no semantic path of its own.

## 3. Calibration inventory (§3-§5, E13/E14)

`ProductionCalibrationInventoryV1` (`benchmarks/calibration.py`)
records every tunable traced from the actual repository:
`SupervisorCyclePolicy` (1/20), `AttentionPolicyConfig`
(window/exploration), specialist `max_output_retries`, correlation
bounds (200 candidates / 3600 s window — explicitly provisional per
P5), graph admission budget (32/cycle) and materializer parallelism
(2), the four `RetrievalBudgetV1` report budgets, provider timeout.
All §4 semantic invariants (evidence identity/task isolation, grounding,
assertion semantics, analyst-only accept/reject, mandatory verification,
graph provenance, citation allowlist, writer tools=0, finalization
blockers) are enumerated as NON-calibratable — the model validator
refuses to mark any semantic parameter calibratable.

## 4. B2 baseline measurement — BLOCKED, recorded honestly (§95, E8/E33)

Feasibility probe at B2: the configured provider
(`api.deepseek.com`, model `deepseek-flash`) authenticates but returns
**402 Insufficient Balance** on any completion; no local provider
(localhost:1234, host:1234, ollama 11434) is reachable. Real
production-path benchmark executions (§95) are therefore IMPOSSIBLE in
this environment right now. Per §104 the phase status is:

```text
P8B IMPLEMENTATION COMPLETE
ACCEPTANCE PENDING
```

The blocked execution chain: corpus cases can be authored and frozen
(`benchmarks/cases/...` file format from P8A), the runner freezes run
manifests, and the executor seam is live — the only missing input is a
funded/available model endpoint. Nothing about the harness was relaxed
to hide this.

## 5. B1 — Corpus freeze contracts (§13-§19, E5/E6/E7)

`BenchmarkCorpusManifestV1` (`benchmarks/corpus.py`): content-addressed
freeze over four splits (development / calibration / acceptance_holdout
/ stress); a case may appear in at most ONE split (validator-enforced);
calibration and holdout must be non-empty; the holdout is SEALED —
`assert_holdout_released()` refuses until
`release_holdout(calibration_profile_hash=...)` records the frozen
calibration profile (§32/§51); refs carry hashes only (no case payload
in the manifest); `verify_corpus_hashes` catches any hash drift;
`check_minimum_independence` enforces §18 (>1 instance per critical
negative dimension) and honestly reports evidence-strength limits.

## 6. B3/B4 — Calibration policy (§31-§33, §44-§50, E15-E18)

`benchmarks/acceptance.py` implements the deterministic selection rule
(§89-tested with synthetic fixtures):

1. a variant with ANY failed structural hard gate is never selected;
2. a variant regressing any baseline-known quality metric is rejected;
3. survivors must not regress cost; adoption requires quality
   improvement or cost improvement without regression (Pareto);
4. otherwise `inconclusive` — the baseline stands; ZERO parameter
   change is an explicitly valid outcome (§50).

`CalibrationExperimentV1` records changed-parameters-only experiments
with run ids, metric summaries, hard gates, tradeoffs, decision,
rationale. `CalibrationComparisonReportV1` classifies improvements,
regressions, neutral, unavailable (§49: regressions never hidden).
`AgentV0CalibrationProfileV1` is the candidate profile; it becomes
final only via the holdout gate. Because no measured runs exist, NO
calibration experiment was executed and NO production default was
changed (E16: changes require measured rationale; there is none).

## 7. B6 — Acceptance policy (§53-§64, §90-§91)

`AgentV0AcceptanceProfileV1` (content-addressed) with typed thresholds
(case_level_ceiling / case_level_floor / aggregate /
observational_only), each requiring a recorded rationale and
supporting experiment ids — no invented thresholds (§56). 
`evaluate_acceptance` enforces:

- any structural gate violation → FAIL (never averaged, §53);
- required metric unavailable → FAIL (§91);
- case-level ceilings apply per case — the 9×0% + 1×100% aggregate
  masking pattern is structurally impossible (§57, tested);
- optional non-safety gaps (T4, GPU telemetry) → PASS_WITH_LIMITATIONS
  only (§76), never for correctness failures;
- exact §74 dispositions (`PASS / PASS_WITH_LIMITATIONS / FAIL /
  EXTERNAL_VALIDATION_PENDING`) — "looks good" is not expressible.

## 8. B7/B8 — Final artifacts (§65-§80, §100-§102)

`benchmarks/final_report.py`: `BenchmarkAcceptanceReportV1`
(content-addressed; NO aggregate score field anywhere; a blocking
external validation structurally forbids PASS; human summary generated
FROM the machine data), `ModelSupportTier` entries
(validated/provisional/unsupported per provider+model — no
"any OpenAI-compatible model" claims), `SupportedResourceEnvelopeV1`
(dev-machine specs recorded as measured context, never promoted to
requirements), `KnownLimitationsV1` with external-validation items.

## 9. Known limitations (§80)

- Provider budget exhausted → no measured baseline/ablation/holdout
  numbers exist; all dashboards remain contract-level.
- Per-observation durations and verifier/reviewer token rows still not
  durable (P8A limitation carried forward).
- T0–T3 real-path acceptance: PENDING (blocked by §4).
- T4 large-case: EXTERNAL_VALIDATION_PENDING (no dataset/hardware run).
- Statistical restraint (§97): no distribution claims are made at all
  this phase, since no runs occurred.

## 10. Regression gate (§99) + exit gates

```text
P8 focused (6 files)              98 passed
P7 focused + audit + planning     64 passed  (combined P8+P7: 162)
P1–P6 investigation regression    930 passed, 1 skipped
R2 forensic_report suite          147 passed, 1 pre-existing failure
startup / ServiceManager          48 passed
py_compile / git diff --check     PASS
pip check                         baseline environment conflicts only
worktree                          clean
```

The single forensic_report failure is the PRE-EXISTING deep-recursion
route test (reproduced on clean baselines in both earlier gates).

P8B E1–E38: E1 PASS (baseline f13ffd89); E2/E3/E4 PASS (wiring + tests);
E5/E6/E7 PASS (corpus contracts); E8–E18 BLOCKED-PENDING (need measured
runs; harness ready, execution impossible); E19–E36 BLOCKED-PENDING
(threshold/profile freezes require B2–B6 data); E37 PASS (no new
regressions); E38 PASS (worktree clean).

## 11. Final status (§102)

```text
PHASE 8B: IMPLEMENTATION COMPLETE / ACCEPTANCE PENDING
AGENT V0: IMPLEMENTATION COMPLETE
BENCHMARK ACCEPTANCE: PENDING (provider budget required)
ARCHITECTURE: FROZEN (P1–P8A semantic design unchanged)
```

Not claimed: PHASE 8B PASS, AGENT V0 ACCEPTED. Unblocking requires a
funded model endpoint (or a reachable local model), then: freeze the
corpus → measure the baseline (E8) → ablations (E10-E12) → calibration
if warranted (E15-E18) → holdout acceptance (E20-E30) → final profile
(E35) → P8B PASS per §104.
