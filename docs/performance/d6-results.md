# D6 Measurement Results

Date: 2026-08-18

This document records the current-machine D6 benchmark results. It does not define an SLA. All measurements use the deterministic synthetic seed `20260818`, local SQLite production configuration, and sequential runs of `python3 python_service/scripts/benchmark.py`.

## Environment

- OS: Linux 7.0.0-28-generic x86_64
- Python: 3.12.3
- SQLite: 3.45.1
- Machine: x86_64
- Harness: `python_service/scripts/benchmark.py`
- Samples: 3 for SMALL, 5 for MEDIUM/LARGE, one warmup for steady-state operations
- Dataset: synthetic only; no real case data, Neo4j, PostgreSQL, or external LLM

## Baseline measurements

Times are median milliseconds. RSS is a rough process `ru_maxrss` observation and is not a heap profile.

| Operation | SMALL | MEDIUM | LARGE |
|---|---:|---:|---:|
| Dataset evidence / events / reports | 100 / 25 / 100 | 1,000 / 250 / 1,000 | 5,000 / 1,250 / 5,000 |
| Fresh Investigation initialization | 51.066 | 60.823 | 725.809 |
| Graph overlay read | 2.105 | 14.669 | 73.641 |
| Graph evidence list | 1.101 | 7.215 | 38.668 |
| Graph event list | 0.535 | 1.503 | 6.076 |
| Report search | 0.277 | 0.347 | 0.766 |
| Report version list | 0.974 | 9.002 | 47.979 |
| Overlay rough RSS delta | 192 KB | 2,496 KB | 9,984 KB |

Observed result counts were consistent with the generated stores: overlay returned the sum of its event/link/selection/claim/evidence projections, evidence/event/version listings returned their corresponding row counts, and report search matched all generated documents.

## Query-plan inventory

Representative task-scoped query plans were the same across all tiers:

- `evidence_snapshots` task lookup: `SEARCH ... USING INDEX sqlite_autoindex_evidence_snapshots_1`;
- `secondary_analyses` task/status lookup: `SEARCH ... USING INDEX idx_secondary_scope_version`;
- `investigation_events` task lookup: `SEARCH ... USING INDEX sqlite_autoindex_investigation_events_2`.

No measured representative query produced a `SCAN` or `TEMP B-TREE` in this run. No index, schema version, or query rewrite was admitted from this measurement alone.

## Classification

### MEASURED

- Android analysis database fresh initialization had a reproducible durability-bound long tail in the C++ Miui artifact tests. Before batching, the first artifact persistence case took `144,812 ms` and the QQNT XML case took `140,307 ms`. Syscall tracing showed near-zero CPU and repeated SQLite journal `fdatasync` calls for separate schema/column DDL statements.
- After wrapping the existing Android schema creation and idempotent `llm_*` column additions in one transaction, the same cases took `1,367 ms` and `1,274 ms`. The complete 65-case `MiuiBackupHeaderTests` executable passed in `51.657 s`.
- Investigation overlay and report list paths scale with generated row counts, with overlay and version-list materialization the largest measured steady-state reads at LARGE. Their current query plans use existing indexes.

### SUSPECTED

- Large-case graph payload/object construction may become a frontend runtime bottleneck when the backend payload is transported and rendered. This harness measures only Python read/materialization, not browser parse/layout.
- Report version list JSON/Pydantic materialization grows with version count. The current LARGE result is measurable but does not establish a production bottleneck or justify pagination/schema changes.
- Fresh Investigation initialization has high variance at LARGE, likely filesystem/journal related. It requires repeated same-host runs before any further change is considered.

### NOT REPRODUCIBLE

- The historical D5 aggregate CTest hang was not reproduced after the measured Android initialization fix. The prior blocker was narrowed to SQLite synchronous initialization cost rather than a parser loop, thread deadlock, subprocess, or network call.
- A one-off `cannot start a transaction within a transaction` stderr line appeared during one full Miui run but did not reproduce in the focused rerun; it is retained as an observation, not treated as a confirmed defect.

## Optimization admission

Implemented optimization: batch Android analysis schema initialization DDL in one transaction. Semantic impact is limited to transaction grouping; table definitions, columns, triggers, indexes, evidence identity, and Android database API behavior are unchanged. Commit: `49e2dd9`.

Rejected/deferred changes:

- no new SQLite indexes, because measured plans already use indexes;
- no PRAGMA durability changes;
- no graph cache, LRU, or TTL, because cache hit/eviction behavior was not measured;
- no report pagination, JSON library, or frontend virtualization, because browser/HTTP scale evidence is not yet available;
- no database engine migration or new infrastructure.

## Measured backlog

The next evidence-gathering candidates are frontend bundle/runtime payload and render measurements, association route query shape under synthetic paired databases, event refresh frozen-envelope costs, report frozen-input admission/read costs, and worker concurrency correctness/lock-wait measurements. These are candidates only; they are not automatic D6-G changes.
