# Phase F live integration

## Purpose

`make acceptance-smoke` starts the actual C++ HTTP server and legacy Python HTTP service in a disposable workspace, waits on each service's health endpoint, checks the frontend route, and then shuts the processes down. It is the F1 process boundary for later Task, Investigation, Report, browser, and restart journeys.

The harness does not patch executors, use an in-process FastAPI client, or replace the production launcher. It starts the built C++ executable and the same `httpserver.main` module used by the operator scripts. A local OpenAI-compatible fake provider supplies deterministic responses for later live journeys without network access or API usage.

## Invocation

```bash
make acceptance-smoke
make acceptance-task
python3 scripts/acceptance/live_services.py --keep-on-failure
python3 scripts/acceptance/live_services.py --with-distributed --distributed-database-url "$TRACELENS_ACCEPTANCE_DATABASE_URL"
python3 scripts/acceptance/live_services.py --llm-delay 2
python3 scripts/acceptance/live_services.py --llm-failure
python3 scripts/acceptance/live_services.py --llm-invalid
```

The default smoke profile starts:

| Service | Runtime endpoint |
| --- | --- |
| C++ HTTP server and built frontend | dynamic loopback port |
| Legacy Python HTTP service | dynamic loopback port |
| Fake LLM | dynamic loopback port |

`--with-distributed` additionally starts the control service only when an isolated PostgreSQL URL is supplied with `--distributed-database-url`. The distributed schema uses PostgreSQL `JSONB`, so SQLite is intentionally rejected by the harness rather than silently testing a different schema. Production defaults remain unchanged: C++ 8080, legacy Python 8090, distributed service 8091.

## Isolation contract

Every run creates a unique temporary workspace containing:

- `data/tasks`, `data/audit`, and `data/logs`;
- a two-file deterministic forensic fixture;
- a temporary report root and database output root;
- a temporary `.env` assembled by the harness;
- failure logs and metadata when `--keep-on-failure` is supplied.

The harness never sources the repository `.env`, never uses the repository `data/` tree, and never writes a fixture copy into the repository. The C++ process applies `PROJECT_ROOT` and `DATA_DIR` before initializing `PathManager`; this is required for the isolation contract. If the built binary or frontend distribution is absent, the run fails before any service starts.

Successful runs remove the temporary workspace. Failed runs remove it by default; use `--keep-on-failure` to preserve diagnostics. Service shutdown sends `SIGTERM` to the process group first and uses `SIGKILL` only after the graceful wait expires.

## Readiness and diagnostics

Readiness uses repeated HTTP requests with a deadline, not a fixed startup sleep. Each failure identifies:

- service name and PID;
- exit code, if present;
- the exact health URL;
- the last observed health error;
- the service log path;
- the last 40 log lines.

The C++ root route, C++ task listing route, legacy Python health route, and optional distributed health route are smoke-checked after readiness. A terminal task journey must still allow a short database-handle stabilization period before reading SQLite artifacts; later acceptance profiles should retain the existing onsite harness's three-second post-terminal rule.

## Fake provider modes

The fake provider implements `GET /health`, `GET /v1/models`, and `POST /v1/chat/completions`. It returns a fixed OpenAI-compatible completion containing `FACT`, `INFERENCE`, and `HYPOTHESIS` claims referencing `file:fixture/notes.txt`. The command-line modes exercise real service behavior:

- `--llm-delay N` delays the HTTP response;
- `--llm-failure` returns HTTP 503;
- `--llm-invalid` returns a non-structured completion.

These modes are provider-level controls. Later acceptance journeys must still call the real HTTP route, executor, persistence, polling, and review APIs.

## Journey A

`make acceptance-task` runs the real Task -> Parsed -> Investigation capture boundary on the same process harness:

1. Copy the existing small `test_image.img` into the temporary workspace.
2. Create a real C++ task with `POST /api/tasks` and poll its exact task ID.
3. Require terminal `completed`, then wait for the existing SQLite handle-release window.
4. Require task-owned `raw.db`, `events.db`, and `files.db` inside the temporary workspace, each with `PRAGMA integrity_check = ok`.
5. Read Files and Timeline through their live C++ routes.
6. Derive `file:<normalized_path>` from the parsed `files` table and call the real Python snapshot route twice.
7. Require identical snapshots and an unchanged `files.db` SHA-256.

## Current scope

F1 through F6 now cover process startup, readiness, cross-service health, frontend reachability, fake-provider availability, cleanup, real task parsing, task-owned SQLite integrity, Files/Timeline reads, Evidence resolver identity, immutable snapshot capture, evidence-hash preservation, Secondary Analysis, explicit review, Event linking, Event Refresh, accepted-first Graph overlay, Report Evidence binding, R2 generation, exact citation traceback, process-kill recovery for Secondary/Refresh/Report, and live Markitdown/Office/DLL socket handoffs. Browser GUI interaction remains environment-blocked because no controllable browser backend was available; distributed/control remains an external PostgreSQL prerequisite. Cross-task UI isolation and final browser screenshots remain pending external browser runtime support.
## Journey B

`make acceptance-analyst` runs the real Investigation -> Review -> Event -> Graph -> Report boundary after Journey A:

1. Submit Secondary Analysis through `POST /api/investigation/analyses`.
2. Poll the exact `analysis_id` until `review_pending`, then accept through the explicit review route.
3. Read exact persisted claims, create an Investigation Event, and link the same Evidence.
4. Admit Event Refresh and poll the exact `refresh_id` from the event refresh history route until a new version is produced.
5. Read the live graph and require deterministic Evidence and accepted Analysis overlay nodes.
6. Add Report Evidence with the exact accepted `analysis_id` binding.
7. Generate through `POST /api/reports/generate`, poll the exact `generation_id`, and require a completed manifest whose citation points to the exact Evidence, Analysis, and Claim IDs.

The fake provider returns the frozen structured contracts required by each real executor. No analysis, event, report-evidence, or report row is inserted directly by the harness.
