# Phase F Product Acceptance

## Baseline

Phase E frozen baseline: `92fb7e8 feat: close out phase E release readiness`.

Phase F validates the live local product chain with an isolated temporary workspace, real C++ and Python processes, a deterministic local fake LLM, and exact public HTTP contracts. No repository `data/`, user case, report store, or real `.env` is used by the acceptance harness.

## Live topology

- C++ HTTP server and built frontend: dynamic loopback port for acceptance; production default remains 8080.
- Legacy Python HTTP service: dynamic loopback port for acceptance; production default remains 8090.
- Distributed/control service: optional only with an explicitly supplied isolated PostgreSQL URL; production default remains 8091. The harness rejects SQLite because the current control schema uses PostgreSQL `JSONB`.
- Fake LLM: dynamic loopback port implementing `/health`, `/v1/models`, and `/v1/chat/completions`.

## Acceptance matrix

| Gate | Result | Evidence |
| --- | --- | --- |
| F-E1 live service harness | PASS | `make acceptance-smoke`; dynamic ports, readiness polling, diagnostics, process-group cleanup |
| F-E2 fake LLM real HTTP contract | PASS | live `/v1/models` and `/v1/chat/completions`; delay/failure/invalid modes available |
| F-E3 real task parsing | PASS | `make acceptance-task`; exact C++ task ID reaches `completed` |
| F-E4 Files/Timeline live reads | PASS | C++ Files and Timeline routes return HTTP 200 after real parsing |
| F-E5 Evidence resolver | PASS | exact `file:/file10.sh` identity resolves through Python snapshot route |
| F-E6 immutable snapshot | PASS | repeated snapshot capture returns identical payload |
| F-E7 evidence integrity | PASS | `files.db` SHA-256 unchanged; raw/events/files `PRAGMA integrity_check=ok` |
| F-E8 Secondary Analysis live API | PASS | exact analysis ID reaches `review_pending` |
| F-E9 analyst review | PASS | explicit review route reaches `accepted`; no auto-accept |
| F-E10 Event and Evidence link | PASS | event created and linked through public routes |
| F-E11 Event Refresh | PASS | exact refresh history ID completes and produces a new version |
| F-E12 Graph overlay | PASS | Evidence and accepted Analysis overlay nodes present |
| F-E13 Report Evidence | PASS | exact accepted analysis binding is persisted through public route |
| F-E14 R2 report generation | PASS | exact generation ID reaches `completed` |
| F-E15 citation traceback | PASS | completed manifest cites exact Evidence, Analysis, and Claim IDs |
| F-E16 Secondary restart recovery | PASS | SIGKILL/restart yields `failed(service_restart)`; no replay |
| F-E17 Refresh restart recovery | PASS | SIGKILL/restart yields `failed(service_restart)`; event history preserved |
| F-E18 Report restart recovery | PASS | SIGKILL/restart yields `failed(service_restart)`; no report ID/manifest published |
| F-E19 Markitdown live handoff | PASS | real Python `/api/markitdown/convert` socket conversion |
| F-E20 Office live handoff | PASS | real Python `/api/office/parse` socket parse of generated XLSX |
| F-E21 DLL live handoff | PASS | C++ DLL route and Python `/api/llm/analyze/dll` Python→C++ socket path |
| F-E22 browser analyst workflow | ENVIRONMENT BLOCKED | browser registry returned no controllable backend; no GUI PASS claimed |
| F-E23 distributed/control live service | EXTERNAL PREREQUISITE | requires isolated PostgreSQL because current schema uses JSONB |

## Commands

```bash
make acceptance-smoke
make acceptance-task
make acceptance-analyst
make acceptance-restart
make acceptance-matrix
```

Each command creates an isolated temporary workspace and removes it on success. `--keep-on-failure` preserves service logs and task metadata for diagnosis. `--serve` holds a completed analyst workspace for browser validation and emits `runtime.json`; it must be stopped explicitly after use.

## Browser disposition

The live analyst workspace was prepared successfully, including a real completed Task → Report chain and a verified dynamic frontend URL. Browser discovery then returned an empty registry, so no IAB, extension, or managed CDP backend was available for GUI clicks or screenshots. This is an external browser-runtime blocker, not a product PASS. The disposition remains:

`PASS WITH EXTERNAL BROWSER-ACCEPTANCE VALIDATION PENDING`

## Scope boundary

Phase F does not add auth, RBAC, permissions, multi-user collaboration, a new Agent architecture, Event Merge/Split, relation-level review, report editor, graph redesign, a new database, Redis redesign, a message queue, microservice refactoring, or a performance campaign. The distributed/control service remains pending an explicitly isolated PostgreSQL environment. No automatic Phase G work starts from this baseline.
