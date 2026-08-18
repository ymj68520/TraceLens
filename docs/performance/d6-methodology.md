# D6 Benchmark Methodology

## Purpose

`python_service/scripts/benchmark.py` is a standalone, standard-library benchmark runner for local SQLite repository paths. It is intentionally outside pytest Fast/Full profiles and does not alter production pragmas, schema versions, or durability settings.

The harness creates temporary synthetic stores from the current Investigation v7 and report schemas. It does not read real evidence, real task directories, Neo4j, PostgreSQL, or external LLM providers. Temporary stores are removed in a `finally` block and no benchmark database is written to the repository.

## Invocation

From the repository root:

```bash
python3 python_service/scripts/benchmark.py --tier small --samples 7
python3 python_service/scripts/benchmark.py --tier medium --samples 7 --output /tmp/tracelens-d6-medium.json
python3 python_service/scripts/benchmark.py --tier large --samples 7 --output /tmp/tracelens-d6-large.json
```

From `python_service/`, the equivalent command is:

```bash
python3 scripts/benchmark.py --tier small --samples 7
```

The runner injects the existing local virtualenv site-packages using the same path discovery convention as `scripts/test.py`. It does not install dependencies.

## Synthetic tiers

| Tier | Evidence snapshots | Investigation events | Report/search rows |
|---|---:|---:|---:|
| SMALL | 100 | 25 | 100 |
| MEDIUM | 1,000 | 250 | 1,000 |
| LARGE | 5,000 | 1,250 | 5,000 |

Seed: `20260818`.

Investigation rows use task `bench`, deterministic file evidence keys, one immutable snapshot per key, one accepted or review-pending analysis per snapshot, claims on alternating rows, and one version/link per synthetic event. Report rows and search documents are deterministic and inserted in setup transactions. The setup data is synthetic and does not represent a real case.

## Measurements

Each operation runs one warmup followed by the requested number of samples. Timing uses `time.perf_counter_ns()` and reports milliseconds:

- median;
- p95 using the nearest measured sample at the 95th percentile position;
- minimum and maximum;
- sample count;
- result count;
- process `ru_maxrss` delta as a rough observation, not a heap profile.

Measured operations:

- fresh Investigation v7 initialization;
- complete read-only Investigation graph overlay;
- graph evidence listing;
- graph event listing;
- report search through the existing snapshot search index;
- report version listing.

The report search and version listing measurements exclude setup and report generation/LLM latency. Fresh initialization is measured separately from steady-state reads.

## Query plans

The harness records `EXPLAIN QUERY PLAN` for representative task-scoped snapshot, analysis, and event queries. The output is diagnostic only. An index change is admissible only when a measured hotspot, a stable production query shape, and an `EXPLAIN` result showing a missing index all agree. No index or schema migration is implied by this harness.

## Caveats

Timing is a same-machine engineering comparison, not an SLA or cross-machine promise. Filesystem cache state, SQLite journal sync, CPU scheduling, Python object construction, and process RSS accounting affect results. Run tiers sequentially on the same host when comparing before/after changes. Do not run the harness concurrently with SQLite-heavy regression suites.

The harness currently measures repository/reader paths only. It does not claim coverage for C++ image analysis, browser rendering, real LLM throughput, Neo4j connection pooling, or full end-to-end report publication. Those remain separate D6 measurement tracks.
