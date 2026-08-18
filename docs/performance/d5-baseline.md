# D5 Performance Baseline

Date: 2026-08-18

This document records measurements only. It does not define performance targets and does not authorize optimization.

## Existing regression timings

Measured by the established Python profile runner on synthetic/unit fixtures:

| Operation | Dataset/profile | Result |
|---|---:|---:|
| Investigation regression | unit Investigation paths | 425 passed, about 26 minutes |
| Fast Unit regression | `tests/unit` excluding `slow`, `concurrency`, `migration_matrix` | 1086 passed, about 36:37 |
| Full Unit regression | `tests/unit -q` | 1135 passed, about 30:55 |
| Frontend unit suite | 39 Vitest files after OSS route contract coverage | 207 passed, about 4.9 seconds |

These are regression baselines, not SLAs. Runtime is affected by filesystem, SQLite journal, and environment scheduling.

## Frontend bundle baseline

The existing production build passes. Current warnings are:

- stale Browserslist/caniuse data;
- a module imported both statically and dynamically;
- chunks above the default 500 kB warning threshold.

Chunk splitting and import-graph redesign are deferred to D6 profiling.

## Measured D5 changes

- Frontend lint before D5-D: 363 problems, including 347 errors and 16 warnings.
- Frontend lint after D5-D: zero errors and zero warnings.
- Frontend tests before/after: 38 files and 206 tests passed.
- Report search-index lifecycle representative tests: 3 passed after deterministic-close change.

## Query and storage profiling status

No real user-case data was used. A broad synthetic 1k/10k/100k SQLite benchmark and query-plan inventory were not run in this consolidation pass because no stable benchmark harness exists in the repository and creating one would change the scope from cleanup to performance tooling. Candidate measurements for D6 are:

- InvestigationRepository common read/write latency across small/medium/large synthetic stores.
- Event Refresh read/write latency and journal churn.
- Report generation admission/read latency.
- Graph overlay load size and memory.
- Files listing and association query shapes.
- SQLite `EXPLAIN QUERY PLAN` for measured hotspots.

No index, pagination, cache, or concurrency optimization was made without those measurements.
