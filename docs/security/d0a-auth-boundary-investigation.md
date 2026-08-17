# D0a — Authentication & Network Boundary Investigation

Investigation-only phase (no production code changed). Baseline Dev `3b6371e`
(R3 closeout; R3-E1~E12 PASS). Evidence below is file:line-verified against
the current tree via code reading + exhaustive greps (three parallel code
sweeps: auth mechanisms, Python route inventory, C++ inventory + client
matrix) plus config/deployment inspection.

## A. Current deployment / trust model

Three services, all started by `run.sh` (the only orchestrator; **no Docker,
no nginx, no external proxy exist anywhere in the repo**):

| Service | Default bind | Port (deployed) | Auth |
| --- | --- | --- | --- |
| C++ forensic server (Crow) | `0.0.0.0` (Crow default; no `.bindaddr()` call; `HTTP_SERVER_HOST=0.0.0.0` in `.env`) | 8666 (code default 8080) | **NONE** |
| Python `httpserver` (FastAPI) | `0.0.0.0` (`config.py:134` `python_http_host`) | 8090 | **NONE** |
| Python C/S control plane | `0.0.0.0` (`server/config.py:38`) | 8091 | JWT (real) |

The intended usage model is **not** localhost-only: the C++ server serves the
built web UI (`web/dist`, `HTTPserver.cpp:109-159`) and the frontend
deliberately supports **cross-machine LAN access** — `web/src/services/api.js:8-24`
derives `http://${window.location.hostname}:8090` for `pythonApi` with an
explicit comment about accessing from another machine (e.g. 192.168.31.50).

**Threat-model verdict: category B — trusted LAN multi-client by explicit
design.** Not A (localhost single-user): the 0.0.0.0 defaults, UI-serving
C++ server, and hostname-derived API base URLs all actively support remote
browsers. Not D: no principal reaches the forensic surfaces.

"当前没有 auth" is therefore **both**: an intentional local/LAN trust
*design* (docs explicitly defer auth — `src/network/HTTPServer/README.md:545-585`
"需自行实现"; `docs/architecture/Security.md` JWT design is aspirational,
`ENABLE_AUTH` matches zero code) **and** an accidental missing control
relative to the supported access pattern (permissive LAN exposure with
destructive mutations and no caller identity anywhere).

## B. Current authentication status

- **httpserver (8090): zero authentication.** Complete middleware list
  (`main.py`): `CORSMiddleware` (default `["*"]`, credentials only when
  origins explicit — `main.py:114-125`), `log_requests` HTTP middleware
  (`main.py:128`), global exception handlers. No `HTTPBearer`/`OAuth2`/
  `Security()`/auth dependency exists in any route or service. The only
  `Authorization` headers are OUTBOUND to LLM providers
  (`services/llm/llm_service.py:410`, `file_analyzer.py:178,277`,
  `event_analyzer.py:132`). Interactive docs exposed at `/docs`, `/redoc`,
  `/openapi.json` (`main.py:108-110`).
- **C++ server (8666): zero authentication.** "Authorization" appears only
  inside `Access-Control-Allow-Headers` (`HTTPserver.cpp:94,117,149`;
  `routes/RouteHelpers.cpp:19`); never read/validated. CORS `*` (env-tunable
  on API routes, hardcoded `*` on static).
- **C/S control plane (8091): real JWT auth** (`server/middleware/auth.py` —
  HTTPBearer, HS256 verify, user vs client token types; bcrypt; login/
  refresh/me; roles super_admin/org_admin/analyst/auditor; 30-day client
  JWTs gated by one-time registration tokens). BUT it runs with the default
  secret `"change-this-in-production"` (`server/config.py:48`) —
  `JWT_SECRET_KEY` is not set in `.env` — and binds 0.0.0.0.
- **Web main-mode login is a mock**: `web/src/pages/Login.jsx:14-17` accepts
  any non-empty credentials, stores `mock_jwt_token_<ts>` in localStorage;
  `api.js:45-59` attaches it as Bearer (ignored by the C++ server); no route
  guards exist anywhere (`routes.jsx`). Only the Distributed page uses the
  real 8091 login (`csAuthService.js`, `csApi` interceptor `api.js:141-154`).

## C. Current authorization status

**NO CURRENT TASK AUTHORIZATION MODEL.** The task system behind all forensic
surfaces (C++ TaskManager, `HTTPServerDataTypes.h:98-161`) carries no
owner/creator/user_id/ACL/role/case-membership; `GET /api/tasks` returns
every task to every caller. Task enumeration is trivially unauthenticated
(`/api/db/tasks` `database.py:108`, `/api/graphiti/tasks` `_admin.py:59`,
C++ `/api/tasks`). Per R3 §6 reconfirmed: because any client can enumerate
all task_ids, a `task_id` guard on Chain A `{report_id}` reads would be a
pseudo-fix, not authorization. A genuine org+user+role model exists only in
the disconnected 8091 control plane (`AnalysisTask.org_id/user_id`,
`server/api/tasks.py` org-scoped with cross-org 403) — nothing in 8090 or
the C++ server consults it. `require_permission` on 8091 is itself a partial
stub (super_admin short-circuit only).

## D. API exposure matrix (condensed)

Python 8090 (~119 endpoints, all unauthenticated; full per-file table in the
investigation sweep) and C++ 8666 (~100 endpoints, all unauthenticated).
Highest-exposure classes:

| Class | Examples | Risk |
| --- | --- | --- |
| Unauthenticated destructive mutations | C++ `DELETE /api/tasks/{id}` (deletes task+data), `POST /api/tasks/cleanup`; `DELETE /api/graphiti/tasks/{task_id}` (whole task KG), `POST /api/graphiti/migrate/deduplicate` (global, all tasks), `.../cleanup/{task_id}` (irreversible, `?confirm=true` only); `DELETE /api/llm/cases/{case_id}` | Evidence/history corruption (P0-class on LAN) |
| Server-filesystem primitives via client paths | `POST /api/markitdown/convert` (arbitrary file read → markdown), `convert-one`/`batch-convert` (**write** .md trees to client-chosen dirs), `POST /api/office/parse` (absolute `file_path`), `POST /api/llm/analyze` + `/api/llm/analyze/dll` (persist into client-supplied `files_db_path`), `POST /api/forensics/oss/ai/*` (raw `oss_db_path`/`download_dir`) | Arbitrary read/write on the server host |
| Opaque-ID reads without scope | `/api/reports/{report_id}/status|manifest|pages|search` (R3-known), `/api/llm/batch/{job_id}`, `/api/llm/case-analysis/{job_id}`, `/api/llm/cases/{case_id}`, `/api/graphiti/jobs/{job_id}` (+DELETE) | Cross-task disclosure (secondary to no-auth) |
| Config/log exposure | `/api/system/info` (host/ports/neo4j_uri/model names), `/api/system/redis/status` (redis URL), `/health/ready` (dependency URLs), `/api/system/logs[...]` (full server logs; 404 body leaks absolute log path `system.py:83`), C++ `/api/system/health/dependencies`, Swagger UIs | Internal topology/path disclosure |
| SQL execution | `POST /api/db/query` — client SQL against task DBs, SELECT-prefix + substring blacklist only; C++ export routes similar | Read primitive over all task data |

Investigation/report chain (R1–R2d) sits on 8090 with task-scoped exact-ID
reads and fixed-string errors — the hardened core — but shares the same
zero-auth perimeter and self-asserted actor fields.

## E. Task ownership model

See C: none on the forensic path. The 8091 `AnalysisTask` (org_id, user_id
creator, org-scoped list, cross-org 403) is the only ownership model in the
repo and is not wired to the forensic task system. **Do not add
`task.owner_id` as a route-level patch** — ownership only means something
after a principal exists (D0b+ decision).

## F. Self-asserted audit fields

**AUDIT IDENTITY IS SELF-ASSERTED.** All actor fields are free client-supplied
strings, validated only by `min_length=1, max_length=256`, stored verbatim,
and echoed back in read models:

| Field | Entry | Storage |
| --- | --- | --- |
| `reviewer` | `routes/investigation.py:149` | `secondary_analyses.decided_by` |
| `created_by` | `routes/investigation.py:244` | event narrative versions |
| `linked_by` | `routes/investigation.py:254` | event evidence links |
| `requested_by` (refresh) | `routes/investigation.py:263` | event refreshes |
| `requested_by` (generation) | `routes/report_generation.py:63` | report_generation_inputs |
| `added_by`/`updated_by` | `routes/report_evidence.py:85,135` | report_evidence |
| `decided_by` | server-set **from client `reviewer`** | — |

No server-derived identity exists (none exists to derive). The older chains
(LLM analyze/batch/toggles, case-analysis, metadata PUT, graphiti, wechat
cache) record **no actor at all**. `models.py:446` deliberately keeps
reviewer identity out of input_hash — correct, but the identity itself is
spoofable: anyone with network reach can attribute an accept review or a
report generation to any name.

## G. Network / CORS / bind risks

- All three services default to `0.0.0.0`; `.env` explicitly sets
  `HTTP_SERVER_HOST=0.0.0.0`. No firewall/packaging confines them.
- CORS: Python default `["*"]` (credentials correctly disabled for the
  wildcard); C++ `*` hardcoded on static, env-tunable on API routes. CORS is
  not being used as auth (no cookies/sessions exist) — its permissiveness is
  a symptom, not the boundary problem.
- The combination **no authentication + 0.0.0.0 + LAN-supported browser
  access** is the high-priority finding of this phase (plan §13): every
  mutation and read in section D is reachable by any host on the LAN.

## H. Credential status

Local `.env` (untracked, kept out of HEAD by Security Preflight `d83c1f7`):

- PostgreSQL: **not rotated** (old leaked value still in use)
- Neo4j: **not rotated** (current value is the one already leaked in git
  history)
- Redis: **not rotated** (old leaked value still in use)
- C/S control plane: `JWT_SECRET_KEY` **unset → default secret in use**;
  default DB URL uses a weak well-known password (`server/config.py:44`)

Tracked HEAD is clean of real credentials (`.env` untracked; `.env.example`
placeholders; remaining hits are vendor SDK samples/identifiers). No history
rewrite performed (separate governance decision, unchanged).

**External blocking actions for the D0 exit gate: rotate the three service
credentials; set a real `JWT_SECRET_KEY` (or the D0b guard will refuse to
start non-loopback).**

## I. Web / C++ compatibility constraints

- **Web**: `api.js` has the unified interceptor layer D0b needs — `api`
  client already injects a (mock) Bearer header; `csApi` injects the real
  8091 token; `pythonApi` currently injects nothing (baseURL is
  hostname-derived, so a bundled constant secret is impossible anyway).
  Correct pattern for D0b: runtime-entered token (sessionStorage/memory)
  injected via one interceptor per client, never in the bundle.
- **C++ → 8090**: exactly three client files, 14 endpoint calls, no auth
  headers today — `LLMPythonProxy.cpp` (9 calls: case-analysis, graphiti
  ingest/jobs/delete), `MarkitdownProxy.cpp` (4), `OfficeAnalyzer.cpp`
  (1, libcurl). Base URL already env-driven (`PYTHON_SERVICE_URL`) — a
  sibling env token is a minimal change.
- **C++ http_agent → 8091**: already sends `Authorization: Bearer` with
  redirect-following disabled (`http_client.cpp:32-42`) — no changes needed.
- **Tests**: pytest hits TestClient (in-process, middleware still applies) —
  a default-off token mode in loopback mode leaves the entire suite green.

## J. Recommended minimal auth model

Ranked for the real deployment (LAN multi-client supported by design):

1. **Option A+ (default-on): loopback-by-default binds.** Flip code/env
   defaults of `python_http_host`, C++ bind (add explicit `.bindaddr(...)`),
   and C/S `HOST` to `127.0.0.1`. Single-machine use keeps today's UX and
   eliminates the entire LAN/remote exposure class.
2. **Option B (opt-in for LAN): server-held static token.** Non-loopback
   bind refuses to start unless a token env var is set (fail-closed guard).
   One token per deployment (no user ACL): FastAPI middleware on 8090
   (exempt `/health*`), Crow pre-route check on 8666 (exempt health + static
   UI so the token-entry page can load), 8091 keeps its JWT auth but also
   refuses default secret off-loopback. Web: runtime token entry injected at
   the `api.js` interceptor layer; C++: three proxy files read the token
   from env.
3. Reverse proxy (§16) remains an option later; do not trust forgeable
   headers without a network boundary guaranteeing proxy-only ingress.
4. **Not chosen**: Option C (session/login/CSRF) and Option D (RBAC) — no
   multi-user requirement; MVP freeze explicitly defers them. The existing
   8091 JWT stack satisfies its own control-plane needs already.

Authorization stays OUTSIDE evidence identity (plan §9): principal → may
access task → then existing `resolve_evidence(task_id, evidence_key)`; no
persisted identity (`analysis_id`/`event_id`/`report_id`/`claim_id`) changes.

## K. Findings (P0/P1/P2/Debt)

- **P0-1: Unauthenticated network-reachable forensic writes.** All three
  services bind 0.0.0.0 with zero auth while the product supports LAN
  browsers; destructive mutations exist (task delete/cleanup, task-KG
  delete, global graph dedup/migrate, case delete) plus client-path write
  primitives (markitdown output dirs, client-supplied `files_db_path`
  persistence). On a LAN-attached host this is "unauthenticated remote write
  allowing Evidence/history corruption". → D0b-1 loopback defaults + guard.
- **P1-1: 8091 control plane runs on the default JWT secret with 0.0.0.0** —
  tokens forgeable by any LAN host; the one authenticated surface is
  bypassable. → guard + secret rotation (user action).
- **P1-2: Server-filesystem read primitives** (`/api/markitdown/convert`,
  `/api/office/parse`, client `files_db_path`/`oss_db_path` bodies) and
  `/api/db/query` SELECT surface — unauthenticated arbitrary-read of task
  data and server files once network-reachable. → boundary fix (P0-1)
  addresses; path-allowlisting is a separate backlog item.
- **P1-3: Raw exception disclosure family** — `detail=str(e)` across legacy
  routes (`database.py` ×8, `associations.py` ×4, `multi_analysis.py` ×5,
  `graphiti_endpoints/_query.py` ×3, `markitdown.py`, `wechat _data.py`,
  plus `/api/system/logs` absolute-path leak `system.py:83`) can leak
  filesystem/DB paths. Continuation of R3 §17; **not fixed in D0a** per plan
  — only the boundary P0/P1s drive D0b; the rest becomes the Phase D
  backlog (fixed-string mapping like Chain A/R2).
- **P2**: mock main-mode login (false security impression — remove or label
  in D0b-2); self-asserted audit actor fields (future `audit_actor` from
  server principal once one exists; keep current fields as display notes —
  frozen API); Chain A `{report_id}` unscoped reads (subsumed by the no-
  authorization-model reality — meaningful only after P0-1/J); `/docs`+
  `/api/system/*` information endpoints; C++ `/api/health/dependencies` URL
  leak; CORS `*` (moot without cookies; tighten with the token mode).
- **Debt**: multi-user/RBAC (Option D), task ownership model, Chain B
  cleanup, `str(e)` full sweep, dead code (`OSSRoutes` compiled-but-
  unregistered, `routes/system_logs.py` unmounted), C++ audit-log `user_id`
  column never populated.

No secrets are printed in this document; credential values are reported as
rotated/not-rotated only.

## L. D0b implementation proposal (for approval)

Split into two independently shippable stages:

**D0b-1 — Loopback default + fail-closed guards (small, test-cheap):**
1. Python `config.py`: `python_http_host` default → `127.0.0.1`;
   `server/config.py` `HOST` default → `127.0.0.1`.
2. C++: explicit `.bindaddr()` honoring `HTTP_SERVER_HOST` (default
   `127.0.0.1`).
3. Startup guards: non-loopback bind refuses to start without (a) the
   service token set — 8090/8666, D0b-2 — and (b) non-default
   `JWT_SECRET_KEY` — 8091. In D0b-1 the 8090/8666 guard message points to
   D0b-2; 8091 guard is complete now.
4. `.env.example`/docs updated (loopback default; how to opt into LAN).
5. Tests: focused config/guard unit tests; `pytest --collect-only`
   (1293 collected today); no Full required (config defaults + startup
   path).

**D0b-2 — Opt-in static-token LAN mode:**
1. Env tokens (`PYTHON_SERVICE_TOKEN`, `HTTP_API_TOKEN`); FastAPI middleware
   on 8090 (exempt `/health*`); Crow pre-route guard on 8666 for `/api/*`
   only (static UI + health open so the token page loads); constant-time
   compare; fixed-string 401s.
2. Web: token entry on 401 (sessionStorage, never bundled), injected via
   the existing `api.js`/`pythonApi` interceptor layer (one place per
   client).
3. C++ proxies: `LLMPythonProxy.cpp`, `MarkitdownProxy.cpp`,
   `OfficeAnalyzer.cpp` attach the token from env (3 files, 14 calls).
4. Tests: middleware unit/route tests with token on/off; frontend client
   interceptor tests; C++ build + a manual smoke (no C++ test harness
   exists).

Explicitly out of D0b (unchanged): RBAC, users table, task ACL, audit_actor
rewrite, CORS redesign, reverse-proxy setup, Chain B cleanup, `str(e)` sweep.

## Verification record (D0a)

Investigation only: zero production/test/doc-tree changes beyond this
document; worktree clean; `pytest --collect-only -q` → 1293 collected.
Full gate: DEFERRED (per plan §21; last major Full 1064 passed @ `9fb8c22`,
R3 `3b6371e` was a message-level fix).
