# TraceLens Phase E Release Readiness

Date: 2026-08-18

## Disposition

**PHASE E RELEASE READINESS = PASS WITH EXTERNAL BROWSER-RUNTIME VALIDATION PENDING**

The repository's existing product contracts, backend lifecycle coverage, C++ aggregate gate, MIUI CLI E2E, Python profiles, frontend static/unit/build gates, and deterministic D6 stability evidence remain green at the D6 baseline. Phase E adds a reproducible browser harness and closes confirmed operator/setup inconsistencies. The browser runtime remains environment-blocked in this workspace because headless Chrome could not navigate to the local harness server after CDP attachment; no browser PASS is claimed.

No automatic next product phase follows this document.

## Baseline and changes

- Phase E focused backend contracts: 146 passed, 1 warning, 31:05 (Investigation, deletion boundaries, report generation/recovery, ServiceManager lifecycle, Markitdown, Office, and legacy routes).
- Phase E changes are limited to browser-test infrastructure, setup/launcher contract fixes, and release documentation.
- No persistent schema, auth model, Investigation state machine, R2 publication design, evidence identity, frozen envelope, citation traceback, or legacy writer behavior was changed.

Confirmed operational fixes:

1. CMake now tracks and installs both `python_service/httpserver/requirements.txt` and `python_service/requirements.txt`. The distributed server cannot be accidentally omitted because a legacy-only `.deps_installed` marker exists.
2. `scripts/start_all_services.sh` verifies distributed imports (`sqlalchemy`, `psycopg2`, `jwt`, `passlib`) before trusting the dependency marker.
3. Vite's `/api` and `/tasks` development proxies follow `HTTP_SERVER_PORT`, defaulting to the current C++ port `8080`; `VITE_CPP_PROXY_TARGET` can override it.
4. The top-level Makefile exposes the declared `web` alias, marks all declared targets phony, uses both Python requirements files in `setup-venv`, and follows `HTTP_SERVER_PORT` for `make cpp`.
5. `run.sh` now documents and uses the current C++ default `8080` instead of the stale `8666` fallback.

## Phase E matrix

| Gate | Result | Evidence / qualification |
|---|---|---|
| E-E1 browser harness exists | PASS | `scripts/browser_e2e.py`, standard-library only |
| E-E2 browser runtime measurement | ENVIRONMENT BLOCKED | `docs/testing/browser-e2e.md`; system Chrome/CDP were available, but headless Chrome did not complete navigation to the local harness server |
| E-E3 Basic Task Journey | PARTIAL | task lifecycle and command contracts pass in Python/C++ suites; no live cross-language task execution |
| E-E4 Investigation to Report Journey | PARTIAL | Phase C/R1/R2 Python and frontend contract suites pass; no live backend-plus-browser Journey B |
| E-E5 Historical reopen | PASS (contract level) | repository reopen, historical report, legacy reader, and version tests pass; no process-level restart |
| E-E6 exact identity | PASS (contract level) | snapshot, analysis, claim, event, refresh, report, generation, and citation tests |
| E-E7 evidence hash integrity | PASS (contract level) | frozen snapshot/report and source immutability coverage |
| E-E8 active proxy destinations | PASS | route inventory plus current C++/Python proxy configuration; live socket sweep remains future integration work |
| E-E9 frontend routes | PASS | Vitest route/service contract coverage and corrected Vite C++ proxy target |
| E-E10 Markitdown | PASS (component contract) | Python route and C++ proxy tests; no live socket handoff |
| E-E11 Office | PASS (component contract) | task containment and C++ parser tests; no live xlsx/pptx handoff |
| E-E12 DLL | PASS (component contract) | C++ parser/integration and Python route/client tests; no live cross-service handoff |
| E-E13 Android/MIUI no-AI | PASS | 65 MIUI tests plus real `MiuiCliEndToEndTests` with explicit `--no-ai` |
| E-E14 deletion under work | PASS | D4b terminal-write, TOCTOU, and no-resurrection tests |
| E-E15 restart recovery | PASS (service-contract level) | stale Investigation/Report recovery and ServiceManager lifecycle tests; no process kill/relaunch |
| E-E16 graph degradation | PASS | overlay-only/unavailable graph tests and browser synthetic fallback path |
| E-E17 report manifest-only degradation | PASS | persisted manifest/citation identity tests |
| E-E18 legacy historical reader/read-only | PASS | legacy route/adapter/UI tab tests; retired writer remains 410 |
| E-E19 operator commands | PASS | canonical commands and health URLs documented below |
| E-E20 active config inventory | PASS (operational set) | required/optional/legacy distinctions recorded below; no secret values |
| E-E21 UI loading/empty/error states | PASS (component contract) | Files, Investigation, graph, report, legacy, polling, and route tests |
| E-E22 Investigation | PASS | 425 passed, 19 deselected, 1 warning |
| E-E23 Fast | PASS | 1086 passed, 49 deselected, 1 warning |
| E-E24 Full | PASS | 1135 passed, 1 warning |
| E-E25 ESLint | PASS | 0 errors, 0 warnings |
| E-E26 Vitest/build | PASS | 39 files, 207 tests, production build |
| E-E27 C++ aggregate | PASS | 62/62 CTest; 392.19s; MIUI 65/65 |
| E-E28 E2E cleanup | PASS (synthetic harness design) | temporary browser profile/server are cleaned in `finally`; no repository data writes |
| E-E29 frozen contract audit | PASS | D6 frozen contract audit retained and focused suites remain applicable |
| E-E30 worktree | PASS | final static checks pass; this document is included in the Phase E freeze commit |

## Existing end-to-end evidence

The repository has strong component and persistence evidence, but it does not yet claim a live full user journey:

- Task API/orchestrator tests cover create/list/get/cancel, progress, terminal guards, command linkage, ownership, FK cascade, and TTL behavior.
- C++ agent tests cover command execution, artifact discovery, process execution, loopback transport, result upload, and local SQLite recovery with fakes or loopback fixtures.
- Investigation tests cover immutable snapshots, versioned secondary analysis, exact claims/grounding, review, event dirty propagation, frozen refresh envelopes, graph projection, restart recovery, deletion boundaries, and cross-task isolation.
- Report tests cover frozen admission, exact report evidence, input hashes, publication, versions, citations, narrative reads, service restart recovery, and legacy additive compatibility.
- Markitdown, Office, DLL, Android logical, and MIUI paths have focused Python/C++ contracts; MIUI also has a real binary CLI E2E.

The remaining cross-boundary gap is explicit: no test currently starts the real C++ and Python services together and carries a task from analyzer output through Investigation, Report Evidence, report generation, and historical browser reopen. That is a future integration test requirement, not a reason to weaken or rewrite the existing contracts.

## Canonical local operation

Use the current dual-stack launcher:

```bash
cp .env.example .env
# Edit local paths and credentials; never commit .env.
make setup
make build
make start
```

Services:

| Service | Default | Health / UI |
|---|---:|---|
| C++ HTTP and built frontend | 8080 | `/api/system/health`, `/` |
| Legacy Python FastAPI | 8090 | `/health`, `/health/ready`, `/docs` |
| Distributed C/S FastAPI | 8091 | `/health`, `/docs` |
| Vite development server | 3000 | `make web-dev`; proxies C++ from `HTTP_SERVER_PORT` |

`run.sh --no-build` is an alternate all-in-one launcher. `scripts/start_services.sh` is a legacy two-service launcher and does not start the distributed C/S service. Do not use the old README examples that refer to C++ `8666` or Vite `5173`.

Health smoke:

```bash
curl -fsS http://localhost:8080/api/system/health
curl -fsS http://localhost:8080/api/health/ready
curl -fsS http://localhost:8090/health
curl -fsS http://localhost:8090/health/ready
curl -fsS http://localhost:8091/health
```

Neo4j, LLM, Redis, and PostgreSQL are optional or separately provisioned depending on the route. Legacy Python readiness requires the C++ backend; Neo4j/LLM/Redis are reported as optional availability checks. Distributed C/S startup requires PostgreSQL and its configured migrations.

## Configuration inventory

Do not record real values in documentation.

Required for a distributed deployment:

- `DATABASE_URL` pointing to PostgreSQL;
- a unique `JWT_SECRET_KEY` and `JWT_ALGORITHM`;
- `PORT`/`CS_PORT` (default 8091);
- `PYTHON_HTTP_PORT` and `HTTP_SERVER_PORT` if non-default ports are used;
- `CPP_BACKEND_URL` matching the C++ listener;
- agent `TRACELENS_SERVER_URL`, `TRACELENS_TOKEN_PATH`, and `TRACELENS_ANALYZER_PATH` when an analysis agent is deployed.

Optional integrations:

- `LLM_BASE_URL`, `LLM_ENDPOINT`, `LLM_API_KEY`, text/vision model settings;
- `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, Graphiti settings;
- `REDIS_URL` for optional job/session acceleration;
- OSS and MCP settings;
- `TRACELENS_WORK_DIR`, `TRACELENS_STATE_DB`, `TRACELENS_HOSTNAME`, `TRACELENS_POLL_INTERVAL`, `TRACELENS_REINDEX_INTERVAL`, and `TRACELENS_IMAGE_DIRS`.

Legacy or compatibility-only values should remain in `.env.example` only when an active consumer still reads them. Never modify the real local `.env` as part of release work. Credential rotation for PostgreSQL/Neo4j/Redis remains a user action.

## Known limitations

- Browser runtime remains externally pending in this environment.
- No live C++↔Python task/report acceptance test exists yet.
- Process-kill/relaunch recovery is covered at service/repository contract level, not as a coordinated live deployment test.
- Real external LLM throughput and provider behavior are not release gates.
- Graphiti/Neo4j, PostgreSQL, Redis, agent deployment, and office/extractor optional dependencies require their own environment prerequisites.
- Legacy Chain B publication is retired; historical reading remains supported and read-only.
- No auth/RBAC redesign, new database engine, message queue, microservice split, report editor, or graph architecture work is part of Phase E.

## Frozen constraints

The following remain active:

- 项目定案不做 auth
- 不做 auth
- 不做新 persistent schema
- 不做 executor state machine redesign
- 不做 R2 publication redesign
- 不做 D3 legacy cleanup
- 不做全仓 SQLite close sweep
- 不做 performance optimization
- Credential rotation for PostgreSQL/Neo4j/Redis remains user action pending
- Do not modify real local .env
- Do not rewrite git history
- 不要自动进入D6 performance optimization
- D6只能处理D5 profiling真正证明的热点。
- 先提交measurement-driven D6 candidate list，等待下一阶段审查。

## Exit condition

After the final focused/static gates and a clean worktree, this document forms the Phase E release-readiness baseline. Stop after Phase E. Do not automatically enter a new feature phase, multi-user collaboration, permissions, a new agent, a report editor, or a new graph architecture.
