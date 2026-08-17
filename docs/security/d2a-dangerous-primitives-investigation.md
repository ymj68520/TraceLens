# D2a — Dangerous File / SQL Primitive Repository Investigation

- Phase: D2a (investigation only — **no production code changed**)
- Baseline: Dev @ `5820082` (D1 closed; worktree clean)
- Date: 2026-08-17
- Scope per plan §0-§5: client-controllable server filesystem paths, DB paths,
  output directories, `/api/db/query` capability boundary, trusted task-path
  resolution. Auth remains out of scope (project decision, D1 §0).
- Method: direct code reads of all entry routes, 4 read-only sweeps (web
  callers, C++ routes + path resolution, python_service path-field inventory,
  test pin points), plus §43-sanctioned PoC scripts using **tmp dirs / test
  DBs only** (nothing read outside the repo; no host sensitive files touched).

## A. Primitive inventory (client-reachable path / DB inputs)

Legend — Path class: **A** = trusted task store (`cpp_backend.get_task(task_id)`
→ `output_raw_db` / `output_events_db` / `output_files_db`), **B** =
evidence-derived identity string (files-table `path`, never a host path),
**C** = client-supplied arbitrary path. "Mounted" = reachable on :8090 today.

### A.1 Live, mounted, Class C (the D2 audit targets)

| # | Route (file:line) | Field(s) | Op | Normalization / containment | Symlink handling | DB mutation | Real caller today | Finding |
|---|---|---|---|---|---|---|---|---|
| 1 | `POST /api/markitdown/convert` — routes/markitdown.py:61 | `file_path` | read; **full content returned** | exists/is_file only; none | none | no | C++ only (MarkitdownProxy.cpp:93, FileAnalyzer.cpp:153); **no web caller** | arbitrary server file read (content echoed) — **F-1 (P1)** |
| 2 | `POST /api/markitdown/convert-one` — markitdown.py:311 | `input_root`/`input_file`/`output_root` | read + write `.md` | per-root symlink rejection + input containment under `input_root` (markitdown.py:224-266); **roots themselves arbitrary**; atomic temp+`os.replace` write | roots/components/file rejected | no | C++ only (TextDumpAdapters.cpp:100) | arbitrary-directory write incl. other task store dirs & repo source dir; overwrite of any existing `*.md` possible (suffix forced, so raw Evidence originals not directly clobberable) — **F-2 (P0)** |
| 3 | `POST /api/markitdown/batch-convert` — markitdown.py:370 | `input_dir`/`output_dir` | recursive read + recursive write, `mkdir(parents=True)` | root symlink checks only; per-file via #2 primitive; **roots arbitrary** | roots rejected | no | C++ only (TextDumpAdapters.cpp:138) | same as F-2 at tree scale — **F-2 (P0)**; plan §12 "绝对禁止 output_dir=其他task目录/python_service/系统目录" — all three reachable today (PoC P3) |
| 4 | `POST /api/office/parse` — routes/office.py:37 | `file_path` | read (xlsx/xls/pptx/ppt content as Markdown) | exists check only; extension whitelist | none | no | web OfficePreviewTab.jsx:30 via officeService.js:8; path = server-listed `file.path` (Files listing) | arbitrary server file read, office formats — **F-3 (P1)** |
| 5 | `POST /api/llm/analyze` — routes/llm_endpoints/_analysis.py:145 | `file_path` (read), `files_db_path` (persist target), `db_file_path` (row key, not a host path) | read (image bytes / document extractor / text, llm_models.py:22-29); write via `persist_to_files_db` | none (Path().exists only) | none | **yes**: `UPDATE files SET llm_*` gated on exact `files.path` match + `file_descriptions` upsert; fail-closed if DB file missing (llm_service.py:143-148, 166-215) | web Files.jsx:376-381 — sends `filePath` (listing + `extraction_directory`) and `filesDbPath = task.output_files_db` (server-derived) | read = **F-4 (P1)**; persist to client-chosen DB = **F-5 (P0)** cross-task store write (PoC P2) |
| 6 | `POST /api/llm/batch` — _analysis.py:390 | `file_paths: List[str]` | read verbatim (absolute paths used as-is, file_analyzer.py:434-469) | none | none | no — persist target is **server-derived** `task_info.output_files_db` ✓ | web batch UI | arbitrary read — **F-6 (P1)** |
| 7 | `POST /api/llm/analyze/dll` — routes/dll.py:83 | `file_path` (forwarded verbatim to C++ `/api/forensics/dlls/analyze`, DLLAnalysisRoutes.cpp:413 — parses any local binary: hashes/imports/exports/sections), `files_db_path` (persist) | read (C++ parse), write (persist_to_files_db) | none | none | same as #5 | web Files.jsx:252-257/301-304 (server-derived both) | read = **F-7 (P1)**; persist = shares **F-5** |
| 8 | `POST /api/llm/reanalyze-files` — case_analysis_endpoints/_case.py:172 | `file_paths[]` (verbatim read, file_analyzer.py:231-366), `files_db_path` (persist) | read + write | none | none | yes (case-analysis pipeline writes descriptions + report tables) | web LLMDescriptions.jsx:167, AnalysisCenter.jsx:344 (server-derived) | arbitrary read **F-8 (P1)** + shares **F-5** |
| 9 | `POST /api/llm/case-analysis` — _case.py:80 (Chain B) | `files_db_path` — **authoritative**; `task_id` extracted from it by regex `/tasks/<uuid>/files.db` (_case.py:110) | full read+write pipeline (db_utils.py 11× `sqlite3.connect`), report_generator writes into that `_files.db` | none | none | yes | web AnalysisCenter.jsx:248, useTaskAutoTrigger.js:69 (server-derived) | **F-9 (P0)** by capability; Chain B frozen-isolation policy applies (see G.5) |
| 10 | `POST /api/llm/multi-image-analysis` — multi_analysis.py:220 | `files_db_paths: List[str]` | full pipeline per DB (read+write) | none | none | yes | web Cases.jsx:90-104 (task-derived list) | shares **F-5/F-9** |
| 11 | `POST /api/forensics/oss/ai/filter` — oss_analysis.py:54 | `oss_db_path` | sqlite read (`oss_objects` table, oss_filter_service.py:236-243, plain connect) | exists check only | none | no | **zero callers** (web never sends it; C++ AI routes unregistered) | arbitrary SQLite read (schema-limited) — **F-10 (P1 capability / dead feature)** |
| 12 | `POST /api/forensics/oss/ai/analyze` — oss_analysis.py:91 | `oss_db_path`, `download_dir` | accepted but **discarded** — `OSSAnalysisService.start_analysis` is a stub (oss_analysis_service.py:60-83) | n/a | n/a | no | zero callers | dead — **Debt** (wire-up or retire later; see D.4) |
| 13 | `POST /api/db/query` — routes/database.py:340 | `sql` (full user input), `task_id`+`database_type`+`table`+`parameters`+`limit` | intended SQL execution | weak route-side guard (see D.1) | n/a | none possible | **zero callers** (web has no SQL console) | **dead route** — forwarding target does not exist (D.2) — **Debt** |

### A.2 Live, mounted, already-safe (server-derived Class A / B) — no action

| Route | Field | Why safe |
|---|---|---|
| `POST /api/llm/analyze-event-cluster` (_analysis.py:28) | `parent_directory` | bound SQL parameter only; `events_db` from `task_info` (A) |
| `POST /api/llm/toggle-relevance` (_management.py:70) | `file_path` | parameter; db = `task_info.output_files_db` (A) |
| `POST /api/associations/file-clusters`, `/cluster-files` (associations.py:313/150) | `file_path`/`parent_directory` | `normalize_evidence_path` + SQL params; dbs from `task_info` (A; raw db derived by string replace) |
| `/api/llm/windows-analysis|report|export` (_windows.py) | — | `windows_db_path` always from `task_info["output_windows_db"]` (A). ⚠ P2: `/windows-export` interpolates client `severity` into a WHERE clause (_windows.py:211) |
| wechat graph routes | `task_id` only | android db resolved server-side (wechat_graph_models.py:137) |
| graphiti routes | `task_id` only | server-side resolution |
| investigation / reports routes (R2/R3 frozen) | `task_id`/`evidence_key` | server-root confined, symlink-checked (forensic_report/service.py:257-313); evidence resolver opens files_db read-only URI (evidence/resolver.py:30-53) |
| `GET /api/system/logs*` (system.py) | `service` | fixed `build/logs` paths, dict-keyed |
| `POST /api/llm/analyze/file` (_analysis.py:296) | multipart only | in-memory; `tempfile.mkstemp` + unlink — the sole upload endpoint |

### A.3 C++ side (:8666, directly LAN-reachable, serves web/dist)

| Route | Path field | Handling | Note |
|---|---|---|---|
| `POST /api/forensics/dlls/analyze` (DLLAnalysisRoutes.cpp:413) | `file_path` | existence check only, parses any local binary | called by Python #7 with verbatim client path — pairs with F-7 |
| `POST /api/forensics/extract` (FileExtractionRoutes.cpp:43) | `output_dir` | **rejects absolute + `..`, `weakly_canonical` containment under task extract dir** (:86-108) | good containment precedent for D2b |
| `POST /api/search/index` (SearchRoutes.cpp) | `source_path`/`index_path` | contained via `fts_path_within_allowed_root` | second precedent |
| `POST /api/tasks` (TaskCRUDRoutes.cpp:132-193) | `image_path`, `db_output_dir`, `key_file_dir`, free-form `metadata` | by-design task definition; seeds `output_*_db` (TaskSerialization.cpp:71-73) | Class A origin — the task-create authority itself (single-user workstation model) |
| `GET /api/forensics/export/events/json\|csv` (ExportRoutes.cpp:18/30) | `query` (SQL, not path) | `is_readonly_select` guard; db = `get_database_path(task_id,"events")` (A); **opened read-write** via `SQLiteHelper::open_database` (sqlite3_open); writes `<task_id>_events.json` to CWD | see D.3 — the *real* client-SQL surface |
| OSS routes (`OSS*Routes.cpp`) | — | **unregistered** (class never instantiated; `OSSRoutes_new.cpp` not even compiled) + stubs (501/503) | web OSS page calls `/api/forensics/oss/analyze` (ossService.js:9) → dead at runtime |

## B. Caller inventory (who sends paths today)

1. **C++ backend → markitdown family** (sole caller of #1-#3):
   `FileAnalyzer.cpp:153` (single convert during LLM file analysis) and
   `AnalysisOrchestrator.cpp:397-437 → TextDumpExporter.run(original_root,
   markdown_root) → MarkitdownTextDumpConverter` (TextDumpAdapters.cpp:100/138)
   — both pass **server-derived task paths** (task extraction / textdump dirs).
   No web code references markitdown endpoints at all.
2. **Web Files page** → `/api/office/parse`, `/api/llm/analyze`,
   `/api/llm/analyze/dll`: all path values server-derived (files listing
   `file.path`, `currentTask.extraction_directory` join helper Files.jsx:649-663,
   `filesDbPath = currentTask.output_files_db`). The UI never offers a
   free-text server-path input on these flows.
3. **Web AnalysisCenter / LLMDescriptions / Cases / useTaskAutoTrigger** →
   case-analysis, reanalyze-files, multi-image-analysis: all send
   `task.output_files_db`-derived values (server-derived, equals the trusted
   path byte-for-byte).
4. **Nobody** → `/api/db/query`, `/api/forensics/oss/ai/*` (zero references).
5. **Web OSS page** → `/api/forensics/oss/analyze` with user-typed
   `source_path` (OSS.jsx:161-168) — targets the **unregistered** C++ route;
   the OSS web feature is currently non-functional end-to-end.
6. Free-text absolute path inputs in the UI exist only at **task create**
   (`image_path`, by design) and the dead OSS page.

Key compatibility fact for D2b: every live caller of the DB-path fields
already sends the exact trusted value (`task.output_files_db`), so
server-side exact-match validation against resolved task stores breaks **no
real caller**.

## C. Trusted / untrusted path classes

- **Class A — trusted task store**: `get_task(task_id)` →
  `output_raw_db`/`output_events_db`/`output_files_db` (+ `investigation.db`
  sibling). Already the resolution mechanism for investigation, reports,
  associations, wechat, windows, toggle-relevance, event-cluster, and the
  `/api/llm/batch` *persist* target. The gap is only that several routes
  *also* accept a client path field with equal-or-greater authority (A.1 #5,
  #7-#10).
- **Class B — evidence-derived identity**: `files.path` /
  `file_descriptions.file_path` strings inside stores. Used correctly as SQL
  parameters (associations, toggle-relevance) and normalized via
  `normalize_evidence_path()` in `persist_to_files_db`. Not a host path; D2b
  must not conflate it with OS-path authorization (plan §10).
- **Class C — client-supplied**: every field in A.1. None of them currently
  distinguishes itself from Class A — the same `str` is trusted verbatim.

## D. `/api/db/query` and the real SQL boundary

### D.1 Route-side guard (routes/database.py:359-374)
`sql.strip().upper().startswith("SELECT")` + substring blacklist
{DROP, DELETE, UPDATE, INSERT, ALTER, CREATE, TRUNCATE}. PoC-verified:
- **Passes and forwards**: `SELECT 1; ATTACH DATABASE '/tmp/poc.db' AS p`,
  `SELECT 1; PRAGMA writable_schema=ON` (semicolon + non-blacklisted verb).
- **Wrongly rejects**: `WITH x AS (SELECT 1) SELECT * FROM x` (legal forensic
  CTE — guard is SELECT-prefix-only), and literal substrings
  (`WHERE note='DELETED...'` → "forbidden keyword DELETE").
- `parameters` dict and full `sql` forwarded verbatim to
  `cpp_backend.execute_query` (cpp_backend.py:284-310).

### D.2 The forwarding target does not exist → route is dead
`execute_query` POSTs to `/api/database/query` on the C++ backend. Grep of
`src/` for `database/query`: **0 hits**; `git log -S '"/api/database/query"'
--all -- src/`: **empty** (never existed). Crow has no matching route (the
SPA catch-all is GET-only), so every call errors at the proxy layer and the
route returns 500 — **no SQL of any kind can currently execute through
`/api/db/query`**. Runtime PoC confirmed the request leaves the Python side
(“C++ API Error (502)” with the backend down). Classification: dead route —
Debt, not a live SQL primitive. If it is ever revived, the D.1 guard alone
would be the only barrier (see G.4).

### D.3 The *live* client-SQL surface is C++ `GET /api/forensics/export/events/json|csv?query=`
- Guard `SQLiteHelper::is_readonly_select` (SQLiteHelperCore.cpp:130-153):
  rejects comments (`--`, `/*`), multi-statement (any `;` not final), requires
  `SELECT`/`WITH` prefix, whole-word token blocklist {ATTACH, DETACH, PRAGMA,
  INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, REPLACE, VACUUM, REINDEX}.
  Substantially stronger than the Python guard; CTEs allowed.
- DB identity is **task-scoped and trusted** (`get_database_path(task_id,
  "events")` — RouteHelpers.cpp:35-90 maps raw/events/files/android/dll/memory
  from the stored task record; no client path input).
- Connection is opened **read-write** (`sqlite3_open` via open_database,
  EventExportQueries.cpp:18) — no `SQLITE_OPEN_READONLY`, no
  `PRAGMA query_only`. Today the guard + single `sqlite3_prepare_v2` statement
  + default-off `load_extension` (never enabled anywhere in src/) make writes
  unreachable, but the connection mode is not a barrier — defense rests on the
  string guard. Hygiene gap → G.6 (open read-only like TOON export does,
  ExportRoutes.cpp:85).
- Python proxy `GET /api/db/tasks/{id}/export/json` (routes/database.py:441)
  does **not** forward `query`, so the web path cannot inject SQL; only direct
  :8666 clients reach the `query` parameter.
- Resource limits: none (unbounded recursive CTE / huge results) → D6 per
  plan §26; result-side caps also absent → P2/D6.

### D.4 OSS subsystem state
Python `/api/forensics/oss/ai/filter` is mounted and functional (arbitrary
SQLite read, #11) with **zero callers**; `/analyze` is a stub discarding its
paths; the C++ OSS route classes are unregistered stubs; the web OSS page
calls the unregistered C++ endpoint. The entire OSS feature is dead
end-to-end. No `download_dir` write primitive exists anywhere today.

## E. Exploitability classification (PoC-verified where marked)

- **F-1 (P1) markitdown /convert — arbitrary file read, content returned**:
  PoC P3: tmp “secret” file converted, contents echoed in response. Any file
  readable by the service process (bind 0.0.0.0:8090, trusted-LAN model).
- **F-2 (P0) convert-one / batch-convert — arbitrary-directory write**:
  PoC P3: wrote mirrored `.md` tree into an unrelated directory. Can target
  `data/tasks/<other_task>` textdump trees (modifies another task's store),
  `python_service/` source tree (overwrite any existing `*.md`, e.g.
  `README.md` ← input named `README`), or any system dir writable by the
  process; `mkdir(parents=True)` anywhere. Mitigators (honest): forced `.md`
  suffix means raw Evidence originals with other names cannot be directly
  overwritten; input≠output filename; symlink components rejected; atomic
  replace.
- **F-3 (P1) office/parse — arbitrary read** (office formats only, content
  returned).
- **F-4/F-6/F-7/F-8 (P1) LLM read primitives** — `file_path` / `file_paths[]`
  used verbatim (analyze, batch, dll-via-C++-parse, reanalyze). Disclosure is
  mediated (LLM analysis of file contents; dll route returns binary metadata),
  except analyze which extracts full document content.
- **F-5 (P0) `files_db_path` persistence — cross-task store write**: PoC P2:
  `persist_to_files_db(db_path=<task B files.db>, file_path=<path present in
  B>)` updated B's `files.llm_*` and upserted `file_descriptions` — client
  chooses the store, violating the task trust boundary (plan §5-§6). Reachable
  via /api/llm/analyze, /analyze/dll, /reanalyze-files (and the Chain B
  full-pipeline routes F-9). Mitigators: target DB must exist, must have a
  `files` table, and the UPDATE must match an existing `files.path` row
  (fail-closed otherwise, llm_service.py:143-185) — arbitrary non-tracelens
  SQLite files are *not* writable, but **any task's files.db is**.
- **F-9 (P0-capability) Chain B case-analysis / multi-image authoritative
  `files_db_path`**: full read+write pipeline + report write into the
  client-chosen DB; task identity is *derived from the client path*, inverting
  the trust direction (plan §5).
- **F-10 (P1-capability, dead) OSS ai/filter**: arbitrary existing-SQLite
  read limited to a table named `oss_objects`.
- **F-11 (Debt) /api/db/query**: dead (D.2).
- **F-12 (P2) windows-export `severity` SQL interpolation** (_windows.py:211).
- **F-13 (P2) C++ events-export read-write connection** (D.3).

## F. Severity roll-up

| ID | Finding | Severity |
|---|---|---|
| F-2 | markitdown convert-one/batch-convert arbitrary-directory write (incl. other task store dir, repo dir) | **P0** |
| F-5 | `files_db_path` client-authoritative persistence → cross-task store write | **P0** |
| F-9 | Chain B `files_db_path` authoritative (task_id derived from path) | **P0** (policy-constrained, see G.5) |
| F-1 | markitdown /convert arbitrary read w/ content echo | P1 |
| F-3 | office/parse arbitrary read | P1 |
| F-4/6/7/8 | LLM-family verbatim `file_path(s)` reads (incl. C++ dll parse) | P1 |
| F-10 | OSS ai/filter arbitrary SQLite read (zero callers) | P1 capability / dead feature |
| F-12 | windows-export severity SQL interpolation | P2 |
| F-13 | C++ events export: read-write open, string-guard-only barrier; no resource limits | P2 |
| F-11 | /api/db/query dead route (missing C++ endpoint; weak guard would matter if revived) | Debt |
| — | C++ OSS routes unregistered + web OSS page dead; OSSAnalysisService stub; routes/system_logs.py unmounted (D1); useFileLLMAnalysis.js dead hook | Debt |

P0/P1 阻塞 D2 exit per plan §33.

## G. Proposed D2b minimal fix set (for review — not implemented)

1. **Trusted task-store resolver (§5-§7, §32)**: small helper
   `resolve_task_store(task_id, store)` / or set-validation
   `is_trusted_files_db(path)` built on `cpp_backend.get_task` /
   `list_tasks`. Apply to:
   - `/api/llm/analyze`, `/api/llm/analyze/dll`, `/api/llm/reanalyze-files`:
     keep `files_db_path` as **deprecated, non-authoritative**; server accepts
     it only on **exact match** with the resolved trusted path (or ignore and
     resolve). Both routes lack `task_id` today — exact-match against the
     trusted set needs no schema change and breaks no caller (B.2/B.3 send the
     trusted value already).
   - read-side `file_path`/`file_paths`: confine to workspace roots (see 2)
     or to the task extraction dir when a task is resolvable.
2. **Workspace-root containment for the markitdown family + office (§9-§13)**:
   minimal config (e.g. `allowed_file_roots`, default = task data/output roots
   already used by PathManager) + one containment helper
   (`resolve → relative_to`, component-aware, symlink-checked — reuse the
   existing `_output_path_for` checks, add the root check). The only real
   callers (C++ pipeline, Files page) already operate inside task trees →
   zero caller breakage expected; C++ needs no change if defaults cover task
   output locations. Reject-traversal, never rewrite (§29); validate and use
   the *resolved* path for the operation (§30).
3. **`/api/db/query` disposition**: either (a) remove the dead route +
   `cpp_backend.execute_query` (zero callers; breaking but honest), or
   (b) implement per plan §19-§25: `task_id + store enum` → trusted path →
   `sqlite3.connect("file:...?mode=ro", uri=True)` + `PRAGMA query_only=ON`,
   single-statement SELECT/WITH validation (mirror `is_readonly_select`),
   bound parameters, server-enforced row cap. Recommend (a) now, (b) only if
   the SQL console becomes a real feature.
4. **OSS**: no subsystem work (§17). Record Debt; optionally cheap-guard
   `oss_db_path` to task data roots if the route stays mounted.
5. **Chain B (case-analysis / multi-image)**: architecture frozen by standing
   policy; D2b should apply the *same exact-match validation* of
   `files_db_path`/`files_db_paths` against trusted task stores at the route
   boundary (message-level guard, no architecture change) — decision point
   for the D2b review since R2/R3 kept Chain B legacy-isolated.
6. **P2 hygiene**: parameterize windows-export `severity`; (C++-side, optional)
   open events-export DBs read-only.

## H. Compatibility impact

- **Frontend**: no change required — all live callers already send
  server-derived trusted values (B). If `/api/db/query` is removed: no UI
  caller exists. OSS page already broken (no new impact).
- **C++**: no change required if workspace roots default to the task data
  tree; MarkitdownProxy/TextDumpExporter paths already live there. The dll
  route's C++ parse is confined on the Python side before forwarding.
- **Tests that pin current loose semantics** (would need updating in D2b):
  `test_markitdown_routes.py` (arbitrary tmp roots for convert-one/batch, 22
  tests), `test_d1_error_sanitization.py::test_office_parse_failure_error_is_fixed`
  (arbitrary path), `test_dll_route.py`/`test_dll_analyzer.py` (payload
  passthrough), `test_persist_to_files_db.py` (direct service calls —
  unaffected by route-level validation). No tests exist for `/api/db/query`,
  OSS services, or `/convert` (no breakage there).

## Validation performed (§43)

- Static: route reads + main.py mount map; `grep -rln database/query src/` → 0;
  `git log -S` → never existed; load_extension never enabled; read-only open
  inventory.
- PoC (tmp-only, `/tmp/d2a_poc.py`, not committed): guard bypass strings
  forwarded (P1); cross-task `persist_to_files_db` write proven (P2);
  `/convert` content echo + `/batch-convert` out-of-tree write proven (P3).
- No production code, tests, frontend, or C++ changed. Full suite: DEFERRED
  (last major full baseline 1064 passed @ `9fb8c22`).

## D2a stop

Investigation only — per plan §45, stopped here. Awaiting D2b review.
