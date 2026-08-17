# D4b — Lifecycle Boundary & Resource Cleanup Fixes

Status: implementation complete. Baseline D4a: `f9e3f4e`. No new persistent schema, executor state-machine redesign, R2 publication change, D3b change, performance work, or repo-wide SQLite sweep.

## A. Added / Modified / Reused

Added:

- `InvestigationRepository.open_existing()` — strict SQLite `mode=rw` opener; no mkdir, create, migration, or self-heal.
- `investigation/live_store.py` — trusted task liveness/path identity helper for terminal writes.
- deterministic deletion/TOCTOU/shutdown/path-mismatch race tests.
- task-scoped C++ `LLMScratch` helper and GoogleTest target.
- video, Graphiti, PEM, and batch-polling focused tests.

Modified:

- `SecondaryAnalysisExecutor` and `EventRefreshExecutor` terminal write boundaries.
- video frame sample cleanup.
- C++ LLM image extraction scratch ownership and cleanup.
- Graphiti owned client close and failed deletion cleanup.
- certificate temporary PEM handling.
- Files batch polling identity, cancellation, and unmount/task-switch cleanup.

Reused unchanged:

- frozen secondary/event refresh state machines and claims;
- E11 frozen input envelope and admission-time DB identity;
- R2 generation/publication/citation transactions;
- D3b Chain B retirement contract;
- normal `InvestigationRepository` constructor for admission/live-task schema-owner paths.

## B. Deletion Boundary

Before D4b, executor workers retained the submit-time path and could construct a normal `InvestigationRepository` after task deletion. That constructor self-heals directories and schemas, allowing an orphan store to be resurrected.

D4b now applies the following rule to every terminal write boundary:

1. query the trusted C++ task registry;
2. if the task is absent or lookup cannot confirm liveness, discard the result and do not write;
3. derive the current trusted investigation path;
4. require exact equality with the submit-time `db_path`;
5. open the existing store with SQLite URI `mode=rw`;
6. validate supported schema without migration/self-healing;
7. perform the terminal write.

The worker still consumes only its admission-time frozen input envelope and submitted DB identity. It does not re-resolve Evidence, Snapshot, source DB, or LLM input.

A task deleted after the liveness check but before the store open fails at the existing-only open. It cannot recreate the directory. Backend transport errors also fail closed; they are not misclassified as deletion and never trigger blind repository construction.

Task deletion therefore means: LLM may finish, result is discarded, no failed row or tombstone is created for a task that no longer exists.

## C. Secondary and Event Refresh Coverage

Both executors now use existing-only repositories from the first worker access, before claim/read. Completion, structured-output failure, LLM failure, cancellation, shutdown sweep, schedule-failure, and restart recovery paths are covered by the boundary policy.

Normal live-task semantics remain unchanged:

- Secondary: queued → running → review_pending;
- Event Refresh: queued → running → completed;
- claim loser performs no competing write;
- `base_version_changed` and `needs_refresh` rules remain unchanged.

## D. Video Scratch Cleanup

`VideoExtractor` now treats frame samples as transient processing aids. The sample directory is always removed in `finally` on success, ffmpeg failure, missing ffmpeg, timeout, and unexpected errors. Returned Markdown contains only stable frame names and counts; it never exposes a deleted scratch path.

Focused tests cover success, non-zero ffmpeg, subprocess exception, and missing duration.

## E. C++ Scratch Cleanup

LLM image extraction now uses:

`<tempdir>/forensics_llm_extract/<task_id>/`

instead of one flat shared namespace. `LLMScratch` provides idempotent per-task path and cleanup helpers. `LLMAnalysisService` owns the task ID and cleans its scratch subtree through RAII. `TaskManager::delete_task` and the deleted-task worker cleanup path also remove only that task subtree.

C++ tests prove task A/B isolation, A-only cleanup, and idempotence. The production `forensic_analyzer` target builds successfully.

## F. Graphiti and PEM Cleanup

`GraphitiIngestor` records clients created by its own initialization and closes owned LLM/embedder pools plus the Neo4j driver independently. Injected Graphiti clients are not treated as owned HTTP clients. Close is idempotent and attempts all owned resources even if one close fails.

`delete_task_graph` now closes its temporary Neo4j driver in `finally`, including session failure paths.

Certificate parsing now uses a real system temporary PEM file and unlinks it in `finally`; the Evidence directory is never polluted, including OpenSSL missing and subprocess failure paths.

The unbounded Graphiti cache, report retention, and repo-wide SQLite close style remain deferred policy/debt items.

## G. Frontend Polling Cleanup

`pollBatchStatus` now accepts an optional `AbortSignal`, clears its recursive timer, stops after terminal state, and rejects cancellation with `AbortError`.

Files polling tracks the identity pair `(taskId, jobId)`. It aborts the previous controller on task/job switch, aborts on unmount, ignores late progress/completion/failure responses from old identities, and only clears the matching Redux job.

The existing R2 generation polling identity/cleanup discipline remains unchanged and serves as the reference implementation.

## H. Tests and Validation

Focused Python:

- executor + refresh frozen suites, deletion boundary, resource cleanup, media, Graphiti: **58 passed**;
- earlier complete D4b Python focus including all resource suites: **76 passed**.

Focused frontend:

- polling service, auto-refresh, CaseIntelligence, redirects/routes, R2 generation panel, narrative integration: **23 passed**;
- production build: **passed**;
- changed Files/LLM service lint: **passed**.

C++:

- `forensic_analyzer`: **built successfully**;
- `test_llm_scratch_gtest`: **3 passed**.

Static:

- Python compile: passed;
- shell syntax: passed;
- `git diff --check`: passed.

Full frontend lint remains a repository-wide pre-existing debt outside D4b; D4b changed-file lint is clean. Full/Fast were not run by phase policy.

## I. Deferred Debt

Outside D4b:

- Graphiti `_task_graphs` LRU/TTL/cache policy;
- global report rows/manifests retention for deleted tasks;
- repo-wide `sqlite3.connect` close standardization;
- dead `case_persistence.py` / `case_file_filter.py` cleanup;
- KnowledgeGraph polling unless a trivial shared helper is justified;
- ServiceManager rollback/drain ordering unification;
- C++ detached watchdog and bounded Graphiti deletion latency;
- D5 test/dependency/build debt;
- D6 performance profiling.

## J. Exit Gates

| Gate | Result |
|---|---|
| D4b-E1 Secondary deletion race cannot resurrect task directory | PASS |
| D4b-E2 Event Refresh deletion race cannot resurrect task directory | PASS |
| D4b-E3 delete-after-live-check TOCTOU fails closed | PASS |
| D4b-E4 live executor state semantics unchanged | PASS |
| D4b-E5 E11 frozen input/DB identity preserved | PASS |
| D4b-E6 shutdown/recovery cannot write deleted stores | PASS |
| D4b-E7 video scratch cleanup on success/failure | PASS |
| D4b-E8 C++ scratch task-scoped and RAII-cleaned | PASS |
| D4b-E9 no Evidence-directory `.tmp.pem` residue | PASS |
| D4b-E10 Graphiti local resources close deterministically | PASS |
| D4b-E11 Files stale polling is cancelled and late responses ignored | PASS |
| D4b-E12 Investigation/Report/D3b frozen contracts unchanged | PASS |

**D4b PASS**

## K. Commits and Worktree

- `77a1fdf` — `fix: prevent investigation writes after task deletion`
- `159cc21` — `fix: clean temporary analysis resources`
- `71f3074` — `fix: cancel stale files batch polling`
- `3a0299e` — `fix: enforce existing investigation stores`

The worktree is clean after the final commit. D5 and D6 are not started.
