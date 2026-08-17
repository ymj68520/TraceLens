# TraceLens D2b — Task Data Boundary & Path Contract Correction

- Phase: D2b
- Baseline: D2a `bb86388`
- Scope: task data ownership, DB-path authority, internal conversion workspace, Office file contract, dead database-query proxy, Windows severity correctness.
- Out of scope: auth/network security, Evidence identity redesign, Investigation/Report state machines, Chain B retirement, OSS implementation, C++ events-export read-only follow-up, performance.
- Full/Fast: deferred by plan. Focused Python/C++/frontend checks were run.

## 1. Changed Contracts

### Task-owned persistence

HTTP task mode now resolves the only authoritative `_files.db` target as:

```text
task_id -> cpp_backend.get_task(task_id) -> output_files_db
```

`files_db_path` remains only as a deprecated compatibility hint on the legacy
request models. When present, it is resolved and compared exactly with the
trusted path. Basename, suffix, parent, case-insensitive, or fuzzy matching is
not accepted. When absent, the trusted path is still used.

Applied to:

- `/api/llm/analyze`
- `/api/llm/analyze/dll`
- `/api/llm/reanalyze-files`
- `/api/llm/case-analysis` (Chain B)
- `/api/llm/multi-image-analysis` (one exact pair per `task_id`)

The Chain B task identity is now explicit and is never regex-extracted from a
client path. Multi-image analysis preserves its `task_ids[]` mapping and sends
the server-resolved trusted paths to the background service.

The underlying `persist_to_files_db()` exact UPDATE/UPSERT behavior is reused
unchanged. D2b corrects only the Facade boundary before that service is called.

### Internal Markitdown conversion

The three conversion endpoints now use a task/workspace contract:

- `/convert`: `task_id + file_path`, or the explicit standalone compatibility
  pair `workspace_root + file_path` for the CLI converter.
- `/convert-one`: `task_id + input_root + input_file + output_root`, or the
  equivalent `workspace_root` standalone form.
- `/batch-convert`: `task_id + input_dir + output_dir`, or the equivalent
  `workspace_root` standalone form.

With `task_id`, the workspace is derived from trusted task database parents;
C++'s internal extraction scratch directory is accepted only for the read-side
single-file conversion. With `workspace_root`, the caller explicitly declares
the standalone workspace; this is a compatibility adapter for the CLI, not a
return to arbitrary server filesystem semantics.

All path checks use `Path.resolve(strict=False)` and component-aware
`relative_to()` containment. Existing lexical symlink components are rejected
before resolution. Conversion roots must remain inside the workspace, input
must be beneath input root, and input/output trees may not overlap. Batch output
mirrors are checked so a generated `.md` target cannot overwrite an input file.
The resolved path is passed to the actual operation (no validate-raw/open-raw
split).

### Office parse

`/api/office/parse` accepts `task_id + file_path` for the Files workflow, plus
the explicit `workspace_root + file_path` standalone adapter used by the C++
OfficeAnalyzer fallback. In task mode, the file must be an exact `files.path`
record or lie under the server-derived task extraction directory. A random file
merely located in the task DB parent is not considered known. Unknown/foreign
files are rejected before the Office service is called.

Evidence path normalization is not used for OS authorization. `files.path`
remains an Evidence-derived identity string and is queried exactly.

### Dead database query proxy

Removed:

- Python `/api/db/query` request/response models and route
- `CppBackendService.execute_query()` forwarding method

The C++ target `/api/database/query` never existed in repository source or
history, and there were no frontend callers. No new SQL engine was introduced.

### Windows severity

Windows TOON export now accepts a `severity` value and binds it with a SQLite
parameter. The previous `f"severity = '{severity}'"` SQL fragment was removed.

## 2. Compatibility Strategy

- Existing frontend task callers already had task identity and continue sending
  their task-derived `output_files_db` values.
- `analyzeContent` and `analyzeDLL` now send `task_id`; OfficePreviewTab passes
  the current task id to `parseFile`.
- Existing Chain B and multi-image frontend services already sent `task_id` or
  `task_ids[]`; no UI redesign was needed.
- C++ MarkitdownProxy and OfficeAnalyzer payloads now include `task_id` and an
  explicit standalone `workspace_root`. FileAnalyzer, LLMAnalysisService,
  TextDumpAdapters, and AnalysisOrchestrator thread these values without
  redesigning the existing analysis pipeline.
- CLI `--dump-text` remains valid without an HTTP task record because it uses
  the explicit standalone workspace adapter. `--task-id` is available when a
  CLI invocation is associated with a registered task.
- `files_db_path` is not removed from legacy request shapes; it is deprecated,
  exact-validated, and never authoritative.

## 3. Added / Modified / Reused

### Added

- `httpserver/services/task_store.py`: small task-store facade, exact legacy
  path validator, resolved component-aware containment, symlink-component check,
  task file membership check, and C++ extraction-root constant.
- `tests/unit/test_d2b_task_store.py`
- `tests/unit/test_d2b_db_ownership.py`
- `tests/unit/test_d2b_office_routes.py`

### Modified

- LLM, DLL, Chain B, multi-image, Markitdown, Office, database, and Windows
  route/service modules.
- C++ task anchor payload path through Markitdown, OfficeAnalyzer,
  FileAnalyzer, LLMAnalysisService, TextDump adapters, CLI parser, and
  AnalysisOrchestrator.
- Minimal frontend services/components and their LLM service test.
- Existing Markitdown and D1 Office tests for the new request contract.

### Reused

- `cpp_backend.get_task()` task metadata
- `persist_to_files_db()` exact Phase A persistence primitive
- Existing `Path.resolve`/symlink behavior in Markitdown's conversion helper
- Existing task extraction directory emitted by C++ task serialization
- Existing frontend task context and `output_files_db` fields
- Existing Office and Markitdown conversion implementations

## 4. Engineering Findings

### BLOCKER

- Before D2b, a client-supplied `files_db_path` could redirect legacy LLM
  persistence into another task's store.
- Before D2b, Markitdown output roots were arbitrary client directories.
- Chain B derived task identity from the client path.

### CORRECTNESS

- `/api/db/query` was a broken proxy to a never-existent C++ endpoint.
- Windows export severity was interpolated into a SQL fragment.
- Office's old absolute-path contract did not establish current-task file
  membership.

### COMPATIBILITY

- Legacy path fields remain present but non-authoritative.
- C++ standalone document/textdump callers use explicit workspace roots.
- Frontend layout and product workflow were not redesigned.

### DEBT

- OSS remains an incomplete/dead chain; it was intentionally not given a new
  path policy in D2b.
- C++ events export still uses the existing read-write connection; the plan
  explicitly leaves that independent follow-up outside the D2b blocker.
- Resource limits and SQL query-engine design remain deferred with the removed
  dead query interface.

## 5. Validation

Focused checks:

| Check | Result |
|---|---:|
| Task-store helper + containment + symlink matrix | 20 passed |
| Task DB ownership / legacy exact-match / Chain B / multi-image / dead proxy | 12 passed |
| Markitdown route and primitive regression | 27 passed |
| Office task membership matrix | 4 passed |
| D1 error/config regression | 12 passed |
| Phase A `persist_to_files_db` regression | 4 passed |
| Frontend full Vitest suite | 200 passed / 35 files |
| Frontend production build | PASS |
| C++ incremental build | PASS |
| Python syntax + `git diff --check` | PASS |

The final focused Python set totals 79 passing tests. Fast and Full profiles
remain deferred according to the D2b plan; the last major Full baseline is
1064 passed at `9fb8c22`.

## 6. Exit Gate

- D2b-E1: HTTP task-mode files DB only resolves from `task_id` — PASS
- D2b-E2: legacy `files_db_path` cannot change task ownership — PASS
- D2b-E3: Chain B no longer derives task id from path — PASS
- D2b-E4: normal Markitdown task workflow remains supported — PASS
- D2b-E5: Markitdown output cannot leave declared task/standalone workspace — PASS
- D2b-E6: Office accepts only current-task known files or explicit standalone workspace — PASS
- D2b-E7: dead `/api/db/query` broken proxy removed — PASS
- D2b-E8: Windows severity is parameterized — PASS
- D2b-E9: frontend/C++ callers need no manual workaround — PASS
- D2b-E10: Evidence/Investigation/Report identity and state machines unchanged — PASS

**D2b decision: PASS.**

Per the phase stop condition, do not enter D3, D4, D5, or D6 automatically.
