# D1 — Error / Secret / Configuration Hardening

Baseline Dev `3b6371e` (R3 closeout) + D0a investigation `fa5fd29`. D1 was
executed against current HEAD with a fresh sweep (D0a's families were only
the starting points); every fix point below was verified reachable and
client-visible before editing.

## A. Scope

Client-visible internal error disclosure, tracked/config secret hygiene,
unsafe credential/config defaults, sensitive path/URI/internal-detail
leakage, configuration fail-closed behavior. Explicitly out of scope (D2+):
file-access capability, `/api/db/query` semantics, Chain B architecture,
state machines, Graph, LLM grounding, report semantics.

## B. Explicit auth exclusion

Per the D1 plan §0, TraceLens needs **no authentication/authorization**.
Nothing in D1 adds auth, tokens, principals, RBAC, or binds audit actor
fields to identities. D0a's auth findings remain historical records only.
The self-asserted fields (`reviewer`, `created_by`, `linked_by`,
`requested_by`, `added_by`, `updated_by`) keep their frozen semantics as
self-asserted audit metadata.

## C. Confirmed findings (all fixed)

Fresh sweep: ~120 `str(e)`-family sites across routes+services were
individually classified. Confirmed **client-visible internal-detail
disclosure** and fixed:

| Family | Sites | What leaked |
| --- | --- | --- |
| `main.py` global exception handler | 1 | raw `str(exc)` to clients under `log_level=DEBUG` |
| `health.py` + `service_manager.py` + `_manager.py` | 9 | full `redis_url` **including inline password** in `/health/ready`, `/api/system/redis/status` (×3 sites); raw transport/driver exceptions embedding `http://10.x`/bolt URIs (×6) |
| `database.py`, `associations.py` | 12 | sqlite errors with absolute task-DB paths |
| wechat `_graph`/`_data` routes + `_queries`/`_timeline` services | 13 | sqlite errors with absolute DB paths |
| graphiti `_query`/`_jobs`/`_migrate`/`_ingest`/`_admin` routes + `_jobs`/`_ingest`/`_status` services | 18 | driver exceptions (Bolt URI), task-data errors |
| llm `_analysis`/`_management` routes + `model_manager` | 17 | provider base URLs, resolved server paths in validation/404 errors |
| case-analysis Chain B routes (`_case`, `_windows`, `_helpers`) + services (`_pipelines`, `file_analyzer`, `cluster_analyzer`, `case_aggregation_manager`, `report_generator`) | ~30 | step errors with server paths, provider details, one report-content embed (`报告生成失败：{exc}`) |
| `multi_analysis.py` | 5 | 500 details + persisted job `error` strings |
| `office.py` | 3 | FileNotFoundError path echo (resolved path), parse errors |
| `markitdown.py` | 2 | `_exception_text` passthrough (outcome/batch errors), conversion-failed detail |
| `system.py` logs | 2 | **absolute log-file path** in 404-style body; read-failure `str(e)` |
| ingestion `_worker.py` | 3 | persisted job `error` (returned via job GET) |
| `dll.py`, `oss_analysis.py`, `windows_analyzer`, `windows_integration`, `windows_toon_exporter`, `cpp_backend.py` | 8 | analysis errors; cpp transport errors with internal URL |
| `_manager.py` log line | 1 | full redis URL (with password) written to server log |

Fix pattern everywhere: `logger.error(...)` (unchanged/added — full detail
stays server-side) + fixed sanitized client string; transport/health errors
report `type(e).__name__` only; URLs rendered through the new
`mask_url_credentials()` helper (`httpserver/config.py`), which is also the
§17 sanitizer reused for the redis log line.

## D. False positives / non-reachable / kept

- `routes/report_generation.py:47,56` — `str(exc)` of our **own fixed-string**
  `RuntimeError` from the service-manager lifecycle guards; safe by
  construction (verified messages are constants).
- `markitdown.py:319` — 400 detail from `ValueError`/`FileNotFoundError` of
  the path-confinement checks: domain semantics and client-input echo
  (§6: domain errors stay precise).
- `extractors/relational_db.py:104` — `str(e)` used in an equality
  comparison, never output.
- `llm_response_parser.py:98` — 50-char bounded JSON-parse diagnostics;
  no path/credential content observed (P2, left as-is).
- `forensic_report/snapshot_writer.py` / `adapters/sqlite_task.py` — probe
  warnings carry `sqlite3.Error` text which does not embed absolute paths;
  part of the frozen Chain A manifest warning semantics (P2, untouched).
- C++ `e.what()` family (~100 catch sites): sampled (`AndroidForensicsRoutes`,
  `CaseCRUDRoutes`, `FilterRoutes`) — they echo their own `runtime_error`
  domain strings and `sqlite3_errmsg` (no absolute paths). P2 wording, no C++
  test harness exists; recorded as **Debt**, no C++ changes in D1.
- Dead code (`routes/system_logs.py` unmounted, C++ `OSSRoutes` never
  registered): left untouched (§23).

## E. Error sanitization contract

Internal implementation exceptions never reach a client response as raw
text: routes return fixed strings ("database query failed", "case report is
unavailable", ...); health/readiness surfaces report the exception **class
name** only (`ConnectError`, `RuntimeError`); the global handler returns a
constant body even under DEBUG. Full messages and tracebacks remain in
server logs (`logger.error(..., exc_info=True)` preserved or added at every
fix point). Domain errors (404 not-found, 400 validation, 409 conflicts,
R2/R3 stable codes like `llm_timeout`/`citation_invalid`/`service_restart`)
are untouched — D1 does not generalize them.

## F. Secret / config contract

- Tracked HEAD contains no real credentials (re-verified; vendor SDK samples
  and identifier strings only).
- `.env` / `.env.bak` untracked; `.gitignore` covers `.env`, `.env.*`,
  `!.env.example`.
- `.env.example`: sensitive keys are placeholders only; `JWT_SECRET_KEY`
  no longer echoes the code default (now `change-me-generate-a-unique-secret`).
- httpserver `Settings` defaults carry no credentials (`neo4j_password=""`,
  OSS secrets `""`, redis URL without password) — regression-tested, plus
  env-override behavior.
- 8091 control plane (legacy, unused by the main product per D0a/§15):
  default `JWT_SECRET_KEY="change-this-in-production"` and default
  `DATABASE_URL` with `postgres:postgres` remain **Debt** (fail-closed guard
  belongs to any future auth decision; D1 does not expand that subsystem).
- Config fail-closed: unchanged — optional Graph/LLM/Redis features keep
  graceful degradation (E9); nothing new fails startup.

## G. External credential rotation state

Repository secret hygiene = **PASS** (this phase). External rotation =
**USER ACTION PENDING**: PostgreSQL / Neo4j / Redis credentials are still
not confirmed rotated (D0a §H status unchanged; D1 did not touch the local
`.env`, print any historical value, or rotate anything server-side).

## H. Added / Modified / Reused

- **Added**: `mask_url_credentials()` in `httpserver/config.py`;
  `tests/unit/test_d1_error_sanitization.py` (12 tests); this document.
- **Modified**: `main.py` (global handler), `config.py` (helper only — the
  mid-edit string corruption found and fixed during the phase is fully
  covered by compile + helper tests), `routes/` (health, system, office,
  markitdown, database, associations, multi_analysis, dll, oss_analysis,
  llm_endpoints/_analysis, llm_endpoints/_management,
  case_analysis_endpoints/_case, _windows, _helpers, wechat_graph_endpoints/
  _graph, _data, graphiti_endpoints/_query, _jobs, _migrate, _ingest,
  _admin), `services/` (service_manager, ingestion_job_parts/_manager,
  _worker, wechat_graph_parts/_queries, _timeline, graphiti_parts/_jobs,
  _ingest, _status, llm/model_manager, llm/file_analyzer, cpp_backend,
  case_analysis/{file_analyzer, cluster_analyzer,
  case_aggregation_manager, report_generator, case_analysis_parts/_pipelines,
  case_analysis_parts/_windows}, windows_artifacts/{windows_analyzer,
  windows_integration, windows_toon_exporter}); `.env.example` (JWT
  placeholder); `test_markitdown_routes.py` (5 assertions moved to the
  sanitized contract).
- **Reused**: existing logger-with-exc_info pattern at every site; the R3
  fixed-string discipline; no new error framework (§8).
- **Do Not Touch**: auth (none added), Evidence identity, Investigation /
  Report state machines and frozen provenance, Graph architecture, Chain B
  architecture (message-level sanitization only), file/SQL primitive
  semantics.

## I. Tests

- New `tests/unit/test_d1_error_sanitization.py` — 12 tests: helper masking
  (with/without password, port), system-log read failure, readiness
  classification + URL masking + no-credential/no-host leakage, redis status
  masking, ServiceManager health classification, office parse failure,
  wechat OperationalError, global exception handler (probe route), settings
  defaults hygiene, env override, `.env.example` placeholder contract,
  `.env`/`.env.bak` untracked.
- `test_markitdown_routes.py` updated to the sanitized contract (5 tests).
- Regression batches (§31): markitdown+associations+cors+dll+d1 = 70 passed;
  forensic_report frozen surface = separate batch (see §L record);
  git diff --check clean.

## J. Deferred D2 items

Path/capability hardening for `markitdown` (`convert`/`batch-convert`
client-controlled read+write dirs), `office/parse` absolute `file_path`,
`/api/llm/analyze`+`dll` client-supplied `files_db_path` persistence, OSS
raw `oss_db_path`/`download_dir`, `/api/db/query` SELECT-guard semantics,
Chain B retirement (D3), C++ `e.what()` wording debt.

## K. P0/P1/P2/Debt

- **P0**: none (no tracked live credential; no evidence corruption from
  error handling).
- **P1 (all fixed this phase)**: redis-URL credential disclosure (health
  endpoints + one log line); raw internal exceptions with absolute
  server paths / provider URLs / Bolt URIs across ~35 route/service fix
  points; DEBUG-mode global handler echo; log-path disclosure in
  `/api/system/logs`.
- **P2 (left, documented)**: exception-class-only naming is a wording
  change for some surfaces; `llm_response_parser` bounded diagnostics;
  snapshot-writer probe warning text; `/api/system/info` topology fields.
- **Debt**: 8091 default JWT secret + default DB URL (legacy plane);
  C++ `e.what()` wording; dead code (`system_logs.py`, C++ OSSRoutes);
  duplicate sanitizer usage may consolidate later.

## L. Exit decision

| Gate | Result |
| --- | --- |
| D1-E1 tracked HEAD no real secret | PASS |
| D1-E2 `.env`/`.env.bak` untracked | PASS |
| D1-E3 `.env.example` placeholders only | PASS |
| D1-E4 confirmed client-visible `str(exc)` P1s eliminated | PASS |
| D1-E5 no server implementation path via fixed points | PASS |
| D1-E6 no DB/provider credential/URI via fixed points | PASS |
| D1-E7 domain 400/404/409 contracts unchanged | PASS (forensic_report batch green) |
| D1-E8 server logs keep full diagnostics | PASS (exc_info preserved/added) |
| D1-E9 optional Graph/LLM degrade gracefully | PASS (untouched) |
| D1-E10 Investigation/Report frozen provenance unchanged | PASS (forensic_report batch green) |
| D1-E11 no new auth functionality | PASS |
| D1-E12 rotation state recorded | PASS (USER ACTION PENDING) |

**D1 CODE PASS.** External credential rotation remains pending (user
action; does not gate the code verdict). Full gate: DEFERRED BY POLICY —
D1 touched route error strings, one helper, and log hygiene; it did not
change global middleware behavior (beyond removing a DEBUG echo), the
config loader, SQLite store semantics, or any state machine. Last major
Full baseline: 1064 passed @ `9fb8c22`.
