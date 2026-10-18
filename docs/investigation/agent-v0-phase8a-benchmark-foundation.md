# TraceLens Agent v0 — Phase 8A

# Benchmark Foundation / Truth Manifest / Measurement Harness

Status: **PASS** (P8A contract/harness freeze; measurement-only — no
calibration, no acceptance thresholds).

P7 baseline:

```text
P7 code freeze checkpoint = 550aa1ee
P7 frozen branch tip      = 936d3fbd
P8A branch                = mvp/agent-v0-phase8-benchmark-acceptance-calibration
                            (created exactly at 936d3fbd)
```

## 1. Repository telemetry investigation (§4)

Findings at `936d3fbd` that drove the design:

1. Run-level model usage lives on `agent_delegation_results.usage` — the
   P4A specialist executor persists pydantic-ai usage
   (`requests/input_tokens/output_tokens`) plus `model_name`,
   `tool_registry_hash`, `model_config_hash` per delegation
   (`agent_specialist_executor.py:668-725`). `LLMService.chat_completion`
   returns `tokens_used` (total only) for the R2/P7 chain.
2. Tool observations carry `created_at`, `tool_id`, `result_count`,
   `evidence_refs` (`ToolObservation`); delegations/runs carry full
   lifecycle timestamps, so wall time and tool productivity are
   computable. Per-call durations are NOT recorded (see §10 limitations).
3. Token usage is readable for specialist delegations from durable rows;
   supervisor/verifier/reviewer calls currently expose only the
   chat-level `tokens_used`.
4. Graph materializations are durable with a state machine
   (`graph-materialization-manifest:v1`) but do not record per-call
   duration/backend-call counts.
5. P7 report runtime persists packs/generations/ledgers/reviews; the pack
   carries the deterministic allowlist and budget accounting
   (`apply_budget` accounting), i.e. context compression is measurable
   from durable rows.
6. A canonical dataset hash exists for the REPORT dataset
   (`report_dataset.compute_hash`), not for raw benchmark datasets —
   P8A adds per-file dataset manifests.
7. No truth-like fixtures existed before P8A; expected questions/claims
   are expressible via the new TruthManifest only.
8. `scripts/benchmark.py` (SQLite store performance harness) is
   reusable as a style reference for CLI + JSON output; it measures
   storage, not Agent behavior.
9. Minimal telemetry gaps for P8A: per-observation durations, verifier/
   reviewer usage rows. These are NOT added in P8A (additive telemetry
   belongs to the owning phase); the metrics mark them `unavailable`
   where absent (§64).
10. No semantic behavior changes: P8A only ADDS the benchmarks service
    package, tests, one CLI script, and docs.

## 2. Modules added (§101, Added/Modified/Reused)

```text
httpserver/services/benchmarks/__init__.py
httpserver/services/benchmarks/truth_manifest.py   added
httpserver/services/benchmarks/availability.py     added
httpserver/services/benchmarks/benchmark_case.py   added
httpserver/services/benchmarks/run_manifest.py     added
httpserver/services/benchmarks/snapshot.py         added (reuses P1–P7 readers)
httpserver/services/benchmarks/metrics.py          added
httpserver/services/benchmarks/runner.py           added
scripts/benchmark_agent_v0.py                      added (CLI, §83)
tests/unit/test_benchmark_truth_manifest.py        19 tests
tests/unit/test_benchmark_run_manifest.py          10 tests
tests/unit/test_benchmark_metrics.py               21 tests
tests/unit/test_benchmark_runner.py                10 tests
```

No production Agent module was moved or modified. No production SQLite
schema changed (§82: file-based, versionable contracts).

## 3. TruthManifest contract (§6-§17, E2/E6/E7/E8)

`TruthManifestV1` (content-addressed `tman:<hash>`) with structured
groups: `critical/supporting/irrelevant_evidence`, `expected_questions`,
`confirmed_claims`, `acceptable_inferences`,
`unsupported_or_prohibited_overclaims`, `expected_relations`,
`expected_coverage`, `known_ambiguities`, `unavailable_truth`.

- Three-valued truth (§7): `confirmed / unsupported / indeterminate`;
  contract validation forbids forcing evidence support onto unsupported
  claims and requires `maximum_assertion_class` on every confirmed claim
  (§13 acceptable-inference ceiling) while forbidding ceilings on
  non-confirmed claims.
- `TruthEvidenceItemV1` carries prose identity + optional
  `expected_evidence_key` — the truth author never needs to know
  TraceLens's final evidence keys (§9).
- `TruthQuestionV1` allows `unresolved` as the correct terminal state
  (§15); `TruthCoverageV1` supports covered/partial/unavailable/
  not_applicable plus `requires_closure_basis` for unjustified-closure
  detection (§16); `TruthRelationV1` covers correlation/identity/causal
  expectations with `identity_merge_allowed` (§17).
- Canonical ordering (every group id-sorted) and idempotent hashing were
  verified by tests — this reused the P7B lesson: ALL defaulted fields
  (including nested groups) are normalized before hashing so a JSON
  reload reproduces `input_hash`/`manifest_id` exactly.

## 4. Evidence availability model (§8-§11, E4/E5)

`ReachabilityManifestV1` rows carry `parser_reachable` and
`agent_discoverable` as separate booleans with status
`resolved / parser_unavailable / tool_not_exposed / unresolved`, plus an
explicit unavailable reason. `compute_availability_summary` counts all
three layers per criticality; `parser_reachable_critical_ids` IS the
agent-recall denominator (§30) and
`critical_ground_truth_reachability` is reported separately so parser
gaps stay visible. A parser-produced record no tool exposes is
`parser_reachable=True, agent_discoverable=False` → TOOL_EXPOSURE gap,
never reasoning-recall blame (§11).

## 5. BenchmarkCase / dataset identity (§18-§20, §56)

`BenchmarkCaseV1` binds `DatasetManifestV1` (per-file logical id +
relative path + size + sha256, order-stable, hashed — never a directory
hash), TruthManifest ref/hash, Goal/Case Context, platform composition,
frozen tier T0–T4, `NegativeCaseFlagsV1` (all ten §20 negative
dimensions), parser profile, and tags. `verify_dataset_files` checks
existence/size/hash and flags undeclared files (dry-run gate, §85).

## 6. RunManifest / Configuration / reproducibility (§21-§25, §57-§59)

- `BenchmarkConfigurationV1`: hashable ablation axes (supervisor,
  playbook, specialist, correlation, verifier, graph_mode
  none/selective/full, report), budgets map, repeat count, seed,
  timeout, cache state (§67 cold/warm/mixed). A configuration change is
  a NEW run (§57 enforced by immutable manifests).
- `BenchmarkRunManifestV1`: frozen BEFORE execution with dataset hash,
  Truth hash, git commit/branch, `ModelIdentityV1` (§58: cloud models
  record provider/model id/API-reported version/request date — no fake
  `weights_hash`; local models record the real file hash +
  quantization), environment digest (§22: OS/arch/python/cpu — no
  secrets, tested), prompt/policy version maps, tool registry hash,
  graph policy versions, report policy versions, cache state, and the
  pending→running→completed|failed status machine (terminal states
  require `completed_at`).
- `AblationContractV1` expresses the seven frozen stages A0–A6; the
  Graph no-graph/full comparison is explicitly declared
  `unsupported_historical_comparison` rather than faked (§24/§25).
  `ablation_configuration(stage)` derives cumulative configurations;
  the A0 baseline is the REAL non-Agent path (production deterministic
  renderer/report chain), not a weakened strawman.

## 7. Run snapshot (§28, §61)

`BenchmarkRunSnapshotV1` (content-addressed) is assembled ONLY from
durable stores via `build_snapshot_from_runtime` — trajectory,
tool observations, delegation results/usage, working-state
questions/coverage, findings, correlation candidates, graph
materializations, finalization, evidence first-seen sequence. No live
Agent reasoning at evaluation time; no CoT collection (§61 — the
snapshot carries the structured Action Trace only).

## 8. Metric engine (§29-§47, §62-§64)

`BenchmarkMetricRegistry` = 16 frozen `MetricSpec` entries
(`benchmark-metric-registry:v1`) each with metric_id, version,
description, EXACT denominator definition, direction, hard-gate
eligibility, limitations. `MetricValue` is either a number with
numerator/denominator or `unavailable` with a reason (§64 — never 0).
The engine is deterministic over truth+snapshot (§62/§97 verified by
hash-reproduction tests); no LLM anywhere in scoring (§29/§32 — claim
matching is exact truth-claim id then normalized proposition text).

Key denominators:

- `critical_evidence_recall` = discovered reachable critical /
  parser-reachable critical (ground-truth-only excluded);
- `relevant_evidence_precision` excludes irrelevant-criticality keys;
- `assertion_overstatement_rate` compares finding class strength to the
  matched claim's `maximum_assertion_class` (§31);
- `causal_overreach_rate` covers causal/actor/intent semantic types;
- `premature_closure_rate` = truth-unresolved questions answered;
- `unjustified_coverage_closure` = not_applicable without capability
  basis where truth requires one;
- `false_entity_merge_rate` = same_person relations against unsupported
  truth (hard-risk, §35);
- `productive_tool_call_ratio` (§39 frozen definition: successful call
  exposing ≥1 evidence ref not seen in an earlier call),
  `duplicate_call_rate` (§40: same tool + normalized args), zero-result
  ≠ failure (§41);
- `time_to_first_critical_evidence_ms` from the durable first-seen
  sequence (per-call timestamps marked as a limitation).

## 9. Failure attribution (§48-§49, E20)

18-layer `FailureLayer` enum (DATASET…RUNTIME/UNKNOWN).
`attribute_missed_critical_evidence` implements the §49 decision tree:
parser-unreachable → PARSER; parser-reachable but not exposed →
TOOL_EXPOSURE; exposed but undiscovered → RETRIEVAL. Tests verify the
three layers diverge on one fixture.

## 10. Hard gates (§51, E13/E14)

Structural zero-tolerance gates (not thresholds):
`no_cross_task_evidence_leak`, `no_graph_id_as_evidence`,
`no_agent_accept_reject`. Gate results carry violations for §81-style
attribution reporting. NO final numeric thresholds exist in P8A (§52/E31).

## 11. Runner / CLI (§26-§28, §65-§69, §83-§86)

`BenchmarkRunner.run`: freeze manifest → execute through the injected
production executor seam → snapshot → hard gates → availability →
`BenchmarkResultV1`. Failed runs keep the frozen manifest, failure
layer, reason, and partial telemetry (`FailedRunRecordV1`, §65) — never
deleted. The runner never touches production semantic rules (§27; the
executor seam is the ONLY integration point). Repeat runs get
independent run ids (§66). `evaluate_only` recomputes from a persisted
snapshot with identical result hash (§84, tested). CLI
`scripts/benchmark_agent_v0.py` supports `--case --config --repeat
--output --dry-run --evaluate-only --expect-result-hash --snapshot
--run-manifest`.

## 12. Truth leakage protections (§54-§55, E3)

- The TruthManifest lives only in `services/benchmarks` and benchmark
  case files; nothing in `investigation.db`/`reports.db` references it.
- Test: production `ToolRegistry` module source contains no
  TruthManifest/benchmarks reference.
- Test: `build_writer_prompts` output (Writer's entire universe)
  contains no oracle field names (`truth_evidence_id`,
  `expected_questions`, `acceptable_evidence_sets`, …).
- The evaluator is the only reader of truth (§55).

## 13. Minimal E2E (§99)

`test_minimal_e2e_case_to_result`: dataset+truth → runner → (fixture
executor seam over the production snapshot contract) → snapshot → hard
gates → availability → cost metrics → `BenchmarkResultV1`, with
evaluate-only hash reproduction. P8A measures CORRECTLY; it makes no
claim about Agent scores (no production corpus run in P8A, per §76/§77).

## 14. Tests / regression gate (§105)

```text
P8A focused (4 files)                60 passed
P7B focused + audit + P7A planning   64 passed
R2 forensic_report suite             147 passed, 1 pre-existing failure
P1–P6 investigation regression       930 passed, 1 skipped
startup / ServiceManager             48 passed
py_compile / git diff --check        PASS
pip check                            baseline environment conflicts only
```

The single forensic_report failure is the PRE-EXISTING deep-recursion
route test (reproduced on clean 936d3fbd in the P7B gate; unchanged).

## 15. Known limitations (§106 item 29)

- No per-observation duration telemetry: wall-clock process metrics use
  the snapshot total + first-seen sequence projection; marked
  `unavailable` when absent.
- Supervisor/verifier/reviewer token usage is not yet durable per call
  (only specialist delegation usage is); cost dashboards report what
  exists.
- Graph metrics are contract-level (§43/§44 defined in the registry);
  measured values require a production run (P8B).
- The CLI executes only from persisted snapshots in P8A; live Agent
  execution wiring is P8B (§76/§86).

## 16. P8B deferred (§107)

Corpus freeze, measured benchmark matrix, ablation/negative-case runs,
T1–T4 acceptance, reliability variance, hard-gate thresholds, quality/
cost targets, budget calibration (Attention/cycle/tool/Specialist/
Verifier/Graph/Report), final acceptance profile. P8A froze NO
thresholds and tuned NO production budgets (E31/E32).

```text
PHASE 8A: PASS
P8A HEAD = <final P8A commit>
P8B NOT STARTED
```
