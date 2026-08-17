# D4a — Recovery / Concurrency / Resource Lifecycle Investigation

Status: docs-only investigation. No production code, frontend, API, migration, tests, or
databases were modified. Nothing was executed against real user-case data. Fast/Full not run.

Baseline: Dev `6e15fc0` (D3b soft retirement frozen).

## A. Scope and method

D4a investigates **system-level lifecycle boundaries only**: ServiceManager
init/rollback/shutdown ordering, cross-executor interactions, task deletion during
in-flight work, resource/subprocess/client cleanup, and frontend polling cleanup.

Per the D4a charter, the already-frozen individual executor state machines
(SecondaryAnalysis E1-E11, EventRefresh C7c, ReportGeneration R2c §25-28) are **not
re-audited**; their invariants are taken as proven and only their boundaries with other
components are examined.

Method: direct source reading (`python_service/httpserver/services/`,
`src/network/HTTPServer/`, `web/src/`) plus one delegated resource-cleanup sweep whose
HIGH findings were re-verified by hand. Three other delegated sweeps were lost to a
session interruption without output; their scopes were re-done directly in the main
thread.

## B. ServiceManager lifecycle

### B.1 Initialization (`service_manager.py:118-227`)

Order: cpp_backend → forensic_report_service → graphiti → llm →
SecondaryAnalysisExecutor → EventRefreshExecutor → ReportGenerationExecutor →
IngestionJobManager → MigrationManager.

- Every service failure except `BaseException` is tolerated per-service (warning +
  continue). Only cancellation aborts the whole transition via
  `_rollback_initialization` (`service_manager.py:104-110`).
- Executor creation is gated on `_cpp_backend_ready`; ReportGeneration recovery is
  deliberately off-loop (`asyncio.to_thread`, factory does durable DDL) — the R2c
  lifecycle-flakiness lesson is already encoded here.
- Consequence (by design, not a bug): a running state may exist with individual
  services unavailable; properties then raise `RuntimeError` through
  `_require_service_access` (`service_manager.py:353-359`). This is degraded-but-owned,
  not half-initialized: `_initialized` is set only after the whole transition succeeds.

### B.2 Rollback vs shutdown ordering

`_rollback_initialization` (`service_manager.py:229-261`) and `_drain_shutdown`
(`service_manager.py:287-309`) both iterate a per-service try/excepted plan and end
with `_clear_services()` under the lifecycle lock; state ends `stopped`.

Two observations, both LOW:

- The two plans use **different orderings** (rollback: migration→ingestion→event_refresh
  →report_generation→secondary→llm→graphiti→forensic_report→cpp; drain:
  event_refresh→report_generation→secondary→forensic_report→cpp→graphiti→llm
  →ingestion→migration). Both are defensible (rollback approximates reverse-init; drain
  cancels work producers before infrastructure), but the divergence is undocumented.
- `_drain_shutdown` nulls `_forensic_report_service` in a `finally` mid-loop
  (`service_manager.py:300-302`) while every other service is cleared only afterwards in
  `_clear_services`. Cosmetic asymmetry.

### B.3 Shutdown coordination

`shutdown()` (`service_manager.py:263-275`) funnels all callers into one shielded
`_coordinate_shutdown` task that first awaits an in-flight initialization (its exception
is swallowed because rollback already ran inside `_run_initialization`), then drains.
Concurrent shutdown callers coalesce; concurrent initialize/shutdown serialize through
`_lifecycle_lock`. No gap found.

### B.4 Executor initialize-vs-shutdown race (verified benign)

`ReportGenerationExecutor.initialize` (restart recovery sweep, `generation_execution.py:216-229`)
does not take the admission lock. If ServiceManager shutdown overlaps the sweep, both the
sweep's `fail_generation` and shutdown's durable-fail target the same rows. Verified
benign: `fail_generation` returns `None` for already-terminal rows and its UPDATE is
guarded on non-terminal status (`forensic_report/repository.py:451-463`); concurrent
losers of `claim_generation` get `None` and are forbidden from any write
(`repository.py:430-448`). Claim/loser semantics across all three executors remain the
frozen per-executor contracts; no cross-executor claim regression exists.

## C. Task deletion vs in-flight work (the main D4a finding)

### C.1 No deletion notification channel to Python

C++ `TaskManager::delete_task` (`src/network/HTTPServer/TaskManager.cpp:310-353`) does:
mark `cancellation_requested`, erase from `tasks_`, persist tasks.json, call
`deleteGraphitiData` (blocking HTTP, 5s/10s timeouts, `LLMPythonProxy.cpp:121-139`),
and remove the task directory (immediately if not running; otherwise deferred to the
worker's RAII `TaskCleanup`, `TaskManagerAnalysis.cpp:31-51` — that C++ half is healthy).

`python_service/httpserver/services/cpp_backend.py` has **no delete-task passthrough**.
No route, signal, or hook tells the Python executors a task vanished. The only Python
side-effect of deletion is the Graphiti DELETE.

### C.2 Orphan resurrection via store self-heal (CORRECTNESS)

- `SecondaryAnalysisExecutor._execute` uses the `db_path` resolved at submit time and
  explicitly does not re-check task existence ("E11 — does NOT call get_task again",
  `investigation/execution.py:236-244`). `EventRefreshExecutor._execute` follows the
  same pattern (`investigation/event_refresh_execution.py:108-109`).
- `InvestigationRepository.__init__` performs `db_path.parent.mkdir(parents=True,
  exist_ok=True)` + `_ensure_schema()` (`investigation/repository.py:701-705`).

Combined: delete a task while its secondary-analysis/refresh LLM call is in flight and
the completion write either lands on an already-unlinked inode (silent loss) or — once
any post-deletion connection opens — **recreates the deleted task directory with a fresh
`investigation.db`** and persists the stale terminal row into an orphan store. The same
construction happens in the shutdown sweep (`investigation/execution.py:118-126`) and the
refresh submit failure paths (`event_refresh_execution.py:72,97`), so a deletion racing
service shutdown can also resurrect a directory.

### C.3 Report chain: no resurrection, but dangling data (DEBT)

ReportGenerationExecutor uses the global `report_output_dir/reports.db`
(`service_manager.py:560-570`), which task deletion never touches. Writer directory
recreation (`forensic_report/generation_writer.py:55-59`) therefore only ever operates
inside the global report root. Remaining issue: report rows/manifests for deleted tasks
persist forever with no retention/cleanup path — a data-retention question, not a
correctness race.

### C.4 C++ restart and shutdown (verified healthy, minor debt)

- Restart: `TaskPersistence.cpp:54-58` resets persisted RUNNING/PENDING tasks to FAILED
  "Interrupted by server restart" at load.
- Shutdown: `~TaskManager` sets `shutdown_requested_` and **detaches** the watchdog
  (`TaskManager.cpp:40-49`); no signal handlers exist in the server main, so exit is
  abrupt but is covered by the restart reset above. Detached-thread exit is benign debt.
- `delete_task` performs the Graphiti HTTP call on the route thread outside the mutex —
  bounded (~15s worst case) latency coupling to Python availability (LOW).

## D. Resource cleanup

All items below are from the delegated sweep; the two HIGH items were re-verified by
hand (grep for the creating call and for any removal call in the same file/tree).

| # | Finding | Location | Severity |
|---|---------|----------|----------|
| 1 | `mkdtemp("tracelens_video_samples_")` frame-sample dirs never removed anywhere in the file; path even written into report Markdown | `services/extractors/media_metadata.py:175` | HIGH |
| 2 | C++ `forensics_llm_extract/` scratch tree never cleaned on any path (completion/failure/cancel); flattened names can collide across tasks | `src/network/HTTPServer/LLMAnalysisService.cpp:77-79` (Python anchor `services/task_store.py:158-160`) | HIGH |
| 3 | `GraphitiIngestor.close()` closes only the Neo4j driver; injected LLM client + embedder httpx pools never `aclose()`d (2+ pools leaked per task graph) | `graphiti_integration/graphiti_ingestor.py:282-287` | MEDIUM |
| 4 | `_task_graphs` per-task GraphitiIngestor cache unbounded (no LRU/TTL; only admin eviction removes) | `services/graphiti_service.py:65`, `graphiti_parts/_core.py:82-132` | MEDIUM |
| 5 | `.tmp.pem` written **into the evidence directory** and leaked on openssl-missing / failure paths | `services/extractors/security_formats.py:257-283` | MEDIUM |
| 6 | `case_persistence.py` / `case_file_filter.py`: `conn.close()` skipped on swallowed exceptions; write paths unguarded | `services/case_persistence.py:22-176`, `case_file_filter.py:22-184` | MEDIUM — but both are zero-caller dead code (roadmap Deferred); route to D5 deletion, not D4b repair |
| 7 | `SQLiteExtractor`: `sqlite3.Error` handler returns without close | `services/extractors/relational_db.py:29-106` | MEDIUM-LOW |
| 8 | Neo4j driver not closed when `delete_task_graph` session raises (contrast: `list_task_graphs` uses try/finally) | `services/graphiti_parts/_status.py:182-195` | MEDIUM-LOW |
| 9 | openpyxl read-only workbook left open on parse error (success-only `wb.close()`) | `services/office_service.py:67-103` | LOW-MEDIUM |
| 10 | `NamedTemporaryFile(delete=False)` DB copies orphaned if `copy2`/`connect` raises before the guarded region | `extractors/windows_extended.py:143-150, 378-385`, `mobile_forensics.py:36-43`, `browser_history.py:44-49, 133-138` | LOW |
| 11 | ~90 sites of `with sqlite3.connect(...)` commit/rollback but never close (refcount-GC dependent); largest clusters: `investigation/repository.py` (42), `forensic_report/repository.py` (~20), `routes/intelligence_report.py` (19) | repo-wide | LOW (determinism debt) |
| 12 | redis `close()` deprecated alias instead of `aclose()` | `services/ingestion_job_parts/_manager.py:177-178` | INFO |

Clean surfaces (verified, no action): LLM service `aclose()` (`llm_service.py:79-89`),
cpp_backend symmetric close (`cpp_backend.py:48-66`), IngestionJobManager worker-cancel +
Redis/Neo4j close (`ingestion_job_parts/_manager.py:160-179`), graphiti service-level
per-graph close loop (`graphiti_parts/_core.py:137-148`), DLL client `async with`
(`routes/dll.py:109`), ad-hoc httpx clients all `async with`, all Python subprocess calls
timeout-bounded and reaped, Volatility pipe fds closed on every return path
(`Volatility3Runner.cpp:71-171`), upload spool and atomic-write temp files both
`finally`-unlinked (`routes/llm_endpoints/_analysis.py:369-384`, `routes/markitdown.py:358-368`).

## E. Frontend polling cleanup

- **R2 precedent is correct**: `useReportGenerationPolling.js` clears its timer
  (`:69-76`), gates on exact identity, stops on terminal states, drops late responses.
- **Files batch polling predates that discipline** (`pages/Files.jsx:66-109`):
  `startBatchAnalysisPolling` awaits `pollBatchStatus` with no jobId stale-guard, no
  cancellation on unmount or task switch. The auto-resume effect re-fires per `taskId`
  change, so an old task's loop keeps running after navigation until terminal status;
  in-memory backend job registries vanish on backend restart (poll then 404s out).
  Redux writes stay correctly keyed, so impact is bounded to orphaned timers/late
  dispatches (LOW-MEDIUM). Same family: `KnowledgeGraph.jsx:278,339` reingest polling.
- `useFileLLMAnalysis.js:68,72` one-shot 10s `clearBatchJob` timeouts are benign.
- D3b already reduced the task-list auto-trigger to silent refresh only.

## F. Findings register (engineering severity)

- **CORRECTNESS-1** (C.2): task deletion mid-flight → silent loss or orphan directory
  resurrection via `InvestigationRepository` self-heal construction from executor
  worker/shutdown paths. The only finding that changes persisted-state semantics.
- **DEBT-1** (D#1, D#2): unbounded temp-dir growth (video samples; C++ LLM scratch).
- **DEBT-2** (D#3-5, 7-10): pool/handle/driver leaks and guarded-region gaps.
- **DEBT-3** (E): Files batch polling lacks the R2 stale-guard/cancellation discipline.
- **DEBT-4** (D#11-12): SQLite close-pattern standardization; redis alias.
- **INFO**: rollback-vs-drain ordering divergence; detached watchdog; ~15s deletion
  latency coupling; report rows for deleted tasks (retention question); D#6 dead-code
  pair → D5.

No BLOCKER found: no data corruption, no lost-update on live tasks, no uncancellable
process leak was identified.

## G. Recommended D4b minimal fix set

1. **Deletion boundary (CORRECTNESS-1)** — smallest safe semantics: before an executor
   completion/shutdown-sweep write, re-validate task existence via `cpp_backend.get_task`
   (resubmitting nothing, invoking no LLM); if the task is gone, drop the result without
   writing and log. Keep `InvestigationRepository` construction for live tasks unchanged
   (its self-heal is load-bearing for readers); the guard lives in the executor paths,
   not the repository. Do not change E11's no-`get_task`-inside-`_execute` LLM-input
   semantics — validate at the write boundary only.
2. **Temp-dir leaks (DEBT-1)** — `finally: shutil.rmtree` for video sample dirs;
   task-completion (and RAII TaskCleanup) removal of `forensics_llm_extract/<task>`
   scoped subdirs on the C++ side.
3. **Pool leaks (DEBT-2)** — `GraphitiIngestor.close()` also `aclose()` LLM client and
   embedder; bound/LRU `_task_graphs`; `delete_task_graph` driver close in `finally`;
   `.tmp.pem` moved to a real temp path with `finally` unlink.
4. **Frontend (DEBT-3)** — port the `useReportGenerationPolling` stale-guard/cancel
   pattern to Files batch polling (jobId identity + unmount cleanup).
5. **Leave for later phases**: D#6 dead-code pair (D5), D#11 repo-wide close
   standardization (start opportunistically with the two repositories only if D4b diff
   stays small), report-row retention policy, rollback/drain plan unification.

## H. D4b constraints (proposed)

- Do not alter frozen executor state machines, E11 frozen-input semantics, R2
  admission/publication transactions, or any D3b retirement contract.
- Do not introduce a new Python↔C++ deletion RPC surface beyond reading existing task
  state; no new persistent schema.
- C++ changes limited to cleanup calls (no behavior changes to analysis paths).
- Full gate: not required by default; re-evaluate only if the deletion-boundary fix
  touches more than the executor write-boundary guards.

## I. D4a exit gate

| Gate | Result |
|---|---|
| D4a-E1 ServiceManager init/rollback/shutdown ordering mapped with verdicts | PASS |
| D4a-E2 cross-executor claim/loser/recovery boundaries examined without re-auditing frozen state machines | PASS |
| D4a-E3 task-deletion vs in-flight workers boundary traced end-to-end (C++ and Python) | PASS |
| D4a-E4 resource/subprocess/client cleanup inventory with severities | PASS |
| D4a-E5 frontend polling cleanup inventory | PASS |
| D4a-E6 HIGH findings independently re-verified | PASS |
| D4a-E7 exact D4b minimal scope + constraints documented | PASS |
| D4a-E8 docs-only; no code/schema/test/data changes; Fast/Full not run | PASS |

**D4a PASS — stop here and wait for D4b review.**
