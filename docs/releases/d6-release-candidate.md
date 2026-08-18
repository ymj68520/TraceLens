# TraceLens D6 Release Candidate

Date: 2026-08-18

## Baseline

- Branch: `Dev`
- D5 baseline: `adef938`
- D6 measured/implementation commits: `49e2dd9`, `b110bf5`, `7661382`
- Release candidate baseline: this document's final commit

## Test gates

| Area | Result |
|---|---|
| Python Investigation | 425 passed, 19 deselected, 1 warning, 30:17 |
| Python Fast | 1086 passed, 49 deselected, 1 warning, 41:28 |
| Python Full | 1135 passed, 1 warning, 52:00 |
| Frontend ESLint | 0 errors, 0 warnings |
| Frontend Vitest | 39 files, 207 tests passed |
| Frontend production build | PASS |
| C++ aggregate CTest | 62/62 passed, 339.73s |
| C++ MiuiBackupHeaderTests | 65/65 passed |
| Large synthetic stability | 10 sequential LARGE runs passed; temporary roots 0 before / 0 after |
| Static checks | Python compile, shell syntax, diff check passed |

The aggregate CTest run uses the current rebuilt test artifacts. A prior aggregate attempt timed out because stale C++ test binaries still contained the pre-D6 Android schema initializer; after rebuilding the affected targets, the terminal result was 62/62 PASS. A separate top-level `cmake --build build` attempt was blocked by the environment's missing `node` executable while building the web frontend target; the frontend lint/test/build gate itself passed from `web/`.

## CTest hang closure

The D5 `MiuiBackupHeaderTests` apparent hang was classified as an environment/durability-bound initialization problem exposed by artifact persistence tests, not a parser loop, mutex, condition variable, subprocess, network call, or malformed-input infinite loop. Syscall tracing showed near-zero CPU and repeated SQLite journal `fdatasync` calls caused by separate Android schema and `llm_*` column DDL statements. Wrapping the existing initialization DDL in one transaction reduced representative cases from about 140–145 seconds to about 1.3 seconds. The full standalone Miui suite and aggregate CTest now terminate and pass.

## Implemented changes

1. `49e2dd9` batches Android analysis schema creation and idempotent LLM-column additions in one transaction. No table, column, index, trigger, evidence identity, or schema version changed.
2. `b110bf5` adds the standalone deterministic SQLite benchmark harness plus D6 methodology/results documentation.
3. `7661382` propagates the explicit CLI `--no-ai` flag into Android logical analysis and makes MIUI CLI contract tests explicit no-AI tests, preventing external LLM configuration from turning a local CTest into a network/retry test.

## Performance findings

The synthetic SMALL/MEDIUM/LARGE results and query plans are recorded in `docs/performance/d6-results.md`. Representative task-scoped queries use existing indexes and produced no measured `SCAN` or `TEMP B-TREE`, so no index or schema change was admitted. The only measurement-backed optimization implemented in D6 is Android schema DDL batching.

Large synthetic stability was repeated 10 times with deterministic seed `20260818`; each run cleaned its temporary root and returned the temporary-directory count to baseline. This is a repository/reader stability result, not a claim about browser rendering, external services, or real LLM throughput.

## Frozen contract audit

The following remained unchanged and passed their focused/full coverage:

- exact evidence identity and normalization;
- immutable Evidence Snapshots;
- historical Initial Analysis and versioned Secondary Analysis;
- claim grounding and exact evidence references;
- review transitions and event dirty propagation;
- Event Refresh frozen input and `needs_refresh` behavior;
- accepted-first graph overlay selection with explicit pending fallback;
- Report Evidence exact binding;
- Report Generation `input_hash`, frozen envelope, manifest authority, and citation traceback;
- D3 legacy read compatibility and retired Chain B publication behavior;
- D4 existing-store-only terminal writes and no-resurrection deletion behavior.

No persistent schema version, Investigation state machine, Event Refresh frozen-input contract, R2 provenance/citation contract, or report publication transaction was changed.

## D6-E1 to D6-E24

| Gate | Status | Evidence |
|---|---|---|
| E1 Miui hang classified/closed | PASS | SQLite DDL sync root cause and transaction fix |
| E2 aggregate CTest terminal result | PASS | 62/62, 339.73s |
| E3 reproducible synthetic harness | PASS | `scripts/benchmark.py`, fixed seed and tiers |
| E4 backend key-path profiling | PASS | graph/report repository paths and plans measured |
| E5 Investigation/report scale profiling | PASS | SMALL/MEDIUM/LARGE results recorded |
| E6 Graph/LLM lifecycle/concurrency profiling | PARTIAL | graph read measured; fake LLM concurrency not run |
| E7 frontend bundle/runtime profiling | PARTIAL | build/bundle baseline measured; browser runtime not run |
| E8 large synthetic stability | PASS | 10 sequential LARGE runs, no temp growth |
| E9 implemented optimizations have before/after | PASS | Android DDL timing before/after |
| E10 no measurement-free optimization | PASS | rejected candidates documented |
| E11 evidence identity unchanged | PASS | focused/full Investigation coverage |
| E12 Investigation frozen contracts unchanged | PASS | Investigation 425-pass gate |
| E13 R2 provenance/citation unchanged | PASS | Full and report tests pass |
| E14 D3 legacy read compatibility | PASS | Full compatibility coverage |
| E15 D4 no-resurrection | PASS | D4 boundary tests pass |
| E16 Python Investigation | PASS | 425 passed |
| E17 Python Fast | PASS | 1086 passed |
| E18 Python Full | PASS | 1135 passed |
| E19 frontend ESLint 0/0 | PASS | lint gate |
| E20 frontend Vitest/build | PASS | 207 tests and production build |
| E21 C++ build/CTest | PASS | rebuilt test targets, 62/62 CTest |
| E22 large-run resource stability | PASS | 10-run temporary-root check |
| E23 performance documentation | PASS | methodology, results, RC documents |
| E24 worktree clean | PASS | verified after final commit |

E6 and E7 are intentionally marked PARTIAL rather than overstated. Their remaining measurement candidates are recorded for a future review; no cache, concurrency, virtualization, pagination, dependency, or frontend chunk rewrite was made without evidence.

## Accepted limitations and future backlog

- The Python Full/ Fast/Investigation timings are development-machine comparisons, not SLAs. This host showed substantial SQLite journal sync variance.
- Frontend build retains known Browserslist, dynamic/static import overlap, and large-chunk warnings. They are accepted or D6-future because the current bundle baseline did not prove a user-facing runtime bottleneck.
- Real browser render/payload profiling, association query profiling, Event Refresh envelope profiling, report frozen-input admission profiling, and fake worker concurrency correctness/lock-wait profiling remain measured backlog.
- Credential rotation for PostgreSQL/Neo4j/Redis remains a user operation and was not changed.

## Final disposition

D6 measurement, the evidence-backed low-risk optimizations, C++ aggregate gate, Python gates, frontend gates, and large synthetic stability loop are complete. No automatic D7/Phase E/architecture work follows this document.
