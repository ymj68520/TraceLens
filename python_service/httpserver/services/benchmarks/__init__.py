"""Agent v0 benchmark foundation (Phase 8A §101).

Benchmark harness lives OUTSIDE the production planes:

- `truth_manifest` — structured TruthManifestV1 oracle (NOT Evidence, NOT
  readable by the production Agent);
- `availability` — ground-truth / parser-reachable / agent-discoverable
  three-layer evidence availability model;
- `run_manifest` — BenchmarkRunManifestV1 / BenchmarkConfigurationV1 /
  environment digest (reproducibility identity);
- `snapshot` — immutable completed-run snapshot adapter over the P1–P7
  durable stores (evaluation input; no live Agent reasoning);
- `metrics` — BenchmarkMetricRegistry + deterministic metric engine (no
  LLM for core scoring);
- `attribution` — failure-layer attribution;
- `runner` — BenchmarkRunner orchestration + ablation configurations.

P8A measures; it never tunes production budgets/policies (P8B owns
calibration).  No single aggregate "TraceLens Score" exists.
"""
