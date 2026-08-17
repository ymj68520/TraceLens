# D3a — Legacy Chain B Repository Investigation

- Phase: D3a (investigation-only)
- Baseline: Dev @ `ec92afb` (D2b formally frozen; worktree clean)
- Scope: `/api/llm/case-analysis`, legacy `case_analysis` persistence/readers,
  `IntelligenceReportReader`, `[[file:...]]` tokens, CaseIntelligence and
  AnalysisCenter coexistence with R2.
- Prohibited and honored: no production code, frontend, API, migration, table,
  route, parser, or test deletion; no real LLM; no user-case data inspection;
  no D3b implementation.

## A. Chain B architecture

### A.1 Registration and route

`POST /api/llm/case-analysis` is a real mounted route:

- `python_service/httpserver/main.py:196-208` includes `case_analysis.router`
  under prefix `/api/llm`.
- `python_service/httpserver/routes/case_analysis.py:36-40` includes the core
  `_case` router and the `intelligence_report` reader router.
- `python_service/httpserver/routes/case_analysis_endpoints/_case.py:79-87`
  defines `POST /case-analysis`, yielding `/api/llm/case-analysis`.
- Polling is `GET /api/llm/case-analysis/{job_id}` at `_case.py:251-269`.

The current request contract is `CaseAnalysisRequest` in
`case_analysis_models.py:35-45`:

| Field | Current contract |
|---|---|
| `task_id` | Required; task identity is explicit. |
| `files_db_path` | Optional deprecated hint; D2b exact-validates it against the trusted task DB. |
| `case_description` | Optional empty string. |
| `max_filter_files` | 1..2000, default 200. |
| `run_filtering` | Default false; pipeline may auto-enable if no existing selection exists. |
| `report_only` | Default false; skips preceding pipeline stages and regenerates the legacy report. |

The route resolves `task_id -> cpp_backend.get_task() -> output_files_db`
through `task_store` before scheduling (`_case.py:100-121`), creates an
in-memory job entry (`:129-136`), schedules `asyncio.create_task` (`:138-150`),
and returns a job ID.

### A.2 Full execution chain

```text
POST /api/llm/case-analysis
  -> CaseAnalysisRequest validation
  -> task_store trusted files.db resolution
  -> _analysis_jobs[job_id] = running
  -> asyncio.create_task(run_case_analysis_background)
  -> CaseAnalysisService.run_full_analysis
  -> deterministic or legacy LLM file filter
  -> persist case_analysis.filtered_files
  -> C++ extraction / extraction polling
  -> per-file extraction + LLM descriptions
  -> optional events.db cluster analysis and event updates
  -> optional Graphiti ingestion
  -> ReportGenerator.generate_final_report
  -> dynamic file_descriptions/events/Graphiti aggregation
  -> five chapter LLM report or fallback report
  -> INSERT OR REPLACE case_analysis.case_report
  -> polling returns aggregate status/result
```

The background coordinator is `_helpers.py:40-93`. It updates progress in the
module-level `_analysis_jobs` dictionary and, on success, stores only counts
(`files_filtered`, `files_analyzed`, `report_generated`). On failure it logs the
traceback but exposes only fixed `case analysis job failed` detail.

There is no persisted job row, durable queue, cancellation contract, TTL,
cleanup, startup recovery, worker ownership, model/prompt version, or report
version allocation. A process restart loses all jobs; polling then returns
404. The only substantial bounded wait is C++ extraction polling (2 seconds,
maximum 600 seconds, `overwrite=False`) in
`case_analysis_parts/_windows.py:141-249`.

## B. Backend execution and input classification

### B.1 Inputs and reads

| Source | Evidence | Classification | Current behavior |
|---|---|---|---|
| C++ task record | `cpp_backend.py:148-158`; `_case.py:104-121` | CURRENT DYNAMIC READ | Supplies trusted DB paths, extraction directory, image/task metadata, and fallback case description. |
| `files` table | `file_filter.py:108-155,430-451` | FROZEN TASK INPUT (for selection) | Deterministic mode reads `path,type,size ORDER BY path`; the C++ filter product is reused rather than re-run. |
| `case_analysis.filtered_files` | `db_utils.py:132-167` | DERIVED DATA | Existing selection can cause filtering to be skipped/reused. It is mutable, not frozen. |
| `file_descriptions` | `file_analyzer.py:47-80`; `report_generator.py:77-118` | CURRENT DYNAMIC / DERIVED | Existing descriptions are reused; report aggregation reads current `is_relevant=1` rows. |
| Extracted file bytes | `_windows.py:169-205`; `file_analyzer.py:94-172` | RAW/PARSED | Selected files are extracted, routed through document/image/raw extractors, then analyzed. |
| `events.db` raw events | `_pipelines.py:157-166`; `cluster_analyzer.py:94-145` | CURRENT DYNAMIC RAW/PARSED | Event rows are grouped into derived minute/type/directory clusters. |
| Event `llm_*` columns | `cluster_analyzer.py:280-334`; report helpers `:189-272` | DERIVED CURRENT STATE | Cluster analysis updates matching event rows; report reads the current values. |
| Graphiti task graph | `graphiti_parts/_core.py:21-105`; `file_analyzer.py:459-607` | CURRENT DYNAMIC EXTERNAL STATE | Optional ingest writes task episodes; report graph mode searches current task graph. |
| `case_description` | `_case.py:145-149`; `report_generator.py:120-129` | INVOCATION INPUT, then CURRENT FALLBACK | Request value is used for the run; an empty value causes a later dynamic read from current C++ task metadata. |
| `raw.db` | source sweep | NOT READ BY THIS CHAIN | No direct Chain B read found. |
| Associations / cluster table | source sweep | NOT READ | Clusters are derived SQL groups; no separate cluster table is consumed by the single-task path. |
| `report_evidence` / R2 structures | `report_evidence.py`, forensic report services | NOT READ/NOT WRITTEN | Chain B is isolated from frozen snapshots and report generation inputs. |
| Investigation snapshots/analyses | investigation executor invariants | NOT READ/NOT WRITTEN | Secondary Analysis is a separate frozen pipeline. |

A generation is therefore not frozen. Changes to `files.db` descriptions,
`events.db` event annotations, task metadata, or Graphiti state can change a
later report, including `report_only` regeneration.

### B.2 Filter and analysis stages

The effective default is deterministic filtering (`config.py:298-310`):
`FileFilter` reads the task `files` table, applies its cap, and persists the
selection. With `FILE_FILTER_MODE=llm`, the legacy path constructs a prompt
from the case description and file summary (`file_filter_parts/_legacy.py:194-249`),
then parses JSON/line fallback output (`:254-311`). Streaming filter mode uses
TOON plus `LLMResponseParser` (`file_filter.py:176-327,358-427`).

Per-file analysis uses `CASE_FILE_ANALYSIS_TEMPLATE` and vision templates in
`prompts.py:157-188`, generic OpenAI-compatible LLM transport in
`llm/file_analyzer.py:137-194`, and text extraction / image handling in
`file_analyzer.py:94-203`. There is no structured JSON contract for the final
file description; text is taken from `analysis.description`.

Event cluster analysis reads unannotated events, builds a case-aware prompt,
parses summary/description/keywords/relevance, and updates all matching events
(`cluster_analyzer.py:94-145,206-334`).

### B.3 Report generation

`ReportGenerator.generate_final_report` (`report_generator.py:46-225`) does
**dynamic aggregation at report time**:

- single-task: current `file_descriptions WHERE is_relevant = 1`;
- cross-image: current rows from each supplied task DB;
- optional Windows artifact section;
- optional Graphiti chapter searches;
- current event-cluster evidence;
- current C++ task case description if the request description is empty.

Graph mode generates five chapters, one LLM call per chapter, with one empty
response retry (`report_generator.py:219-426`). Prompts require inline
`[[file:...]]` and `[[event:...]]` text tokens. The fallback path uses a
single concatenation-style report prompt (`:428-452`). There is no citation
parser, citation manifest, input hash, prompt version, or report-version row.

## C. Persistence semantics

### C.1 `case_analysis` table

Active DDL is `case_analysis` in the task `_files.db`:

```sql
CREATE TABLE IF NOT EXISTS case_analysis (
    task_id TEXT PRIMARY KEY,
    case_description TEXT,
    filtered_files TEXT,
    case_report TEXT,
    created_at INTEGER,
    updated_at INTEGER
)
```

Source: `python_service/httpserver/services/case_analysis/db_utils.py:44-61`.

Filtered files use `INSERT OR REPLACE` (`:63-78`). Reports use
`INSERT OR REPLACE` and carry forward only `filtered_files` through a COALESCE
subquery (`:80-98`). A second report for the same task replaces the row;
there is no version, history, model, prompt, input hash, citation, or
provenance column. The previous V1 is readable only until the next write; it
is not separately addressable.

Cross-image reports use a separate case database generated by
`get_case_db_path()` (`db_utils.py:375-390`), normally
`build/data/cases/{case_id}/{case_id}.db`, and are also keyed by the same
single-row `case_analysis` shape.

There are duplicate legacy helper modules:

- `services/case_persistence.py:19-132`
- `services/case_file_filter.py:19-132`

They contain older `id INTEGER PRIMARY KEY AUTOINCREMENT` / non-unique
`task_id` DDL and duplicate `INSERT OR REPLACE` methods. The active
`CaseAnalysisService` uses `db_utils` and `ReportGenerator`; no active
instantiation of these duplicate classes was found. They are removal
candidates only after D3b confirms no external import contract.

### C.2 Related mutable persistence

`file_descriptions` is created by `db_utils.py:26-42` and the LLM service
schema helper (`llm_service.py:95-117`). Its `file_path` is unique, but there
is no task_id/version/input hash. `persist_to_files_db` updates `files.llm_*`
then upserts `file_descriptions` (`llm_service.py:118-218`). Re-analysis
therefore overwrites current descriptions and does not preserve history.

Event analysis can add missing `llm_*` columns and update event rows
(`llm_service.py:220-283`). Report event loading can also perform schema
self-healing/DDL in legacy helpers. These are side effects absent from R2's
frozen read/generation contract.

### C.3 Historical evidence

The repository contains multiple six-column `case_analysis` fixtures and
read tests:

- `tests/unit/test_intelligence_report_routes.py:10-33`
- `tests/unit/forensic_report/test_analysis_adapter.py:8-90`
- `tests/unit/forensic_report/test_sqlite_task_adapter.py:19-97`
- deterministic filter persistence tests in `tests/unit/test_deterministic_filter.py:31-122`

Tracked `build/data/reports/reports.db` contains R2 report-version/input schema,
not `case_analysis`; no repository migration converts legacy rows. This means
existing task `_files.db` files may contain historical Chain B rows, while R2
`reports.db` is a separate store.

## D. Legacy reader and citation semantics

### D.1 Backend reader

`GET /api/llm/intelligence-report/{task_id}` and its records/search/metadata
routes are mounted with the same `case_analysis` router. `_resolve_task()` in
`intelligence_report.py:745-755` obtains task-owned files/events DB paths from
C++ metadata. The reader opens DBs read-only through `mode=ro` (`:188-205`),
then:

- reads the latest `case_analysis.case_report` ordered by `updated_at`;
- splits known five chapter headings (`:815-860`);
- reads task files and events pages;
- searches files/events;
- reads/writes separate `report_metadata` through its own metadata endpoint.

It does not interpret `[[file:...]]` identity on the backend and does not
read R2 `report_evidence`, generation inputs, or narrative manifests.

### D.2 Frontend reader and tokens

`CaseIntelligence.jsx:18-90` is active at `web/src/routes.jsx:104-106`.
By default it renders the legacy `IntelligenceReportReader`; only
`?tab=forensic` selects the R2 `ForensicReportPage`.

`IntelligenceReportReader.jsx:49-93` calls the legacy intelligence-report
read APIs, and its `研判工具` button navigates to the active Analysis Center
(`:169`). It has no generation button itself, but the old writer remains
reachable there.

The legacy token renderer is
`web/src/components/case-intelligence/markdownRenderer.jsx:8-63`:

- `[[file:...]]` is matched by an anchored regex and displayed using the
  basename as the button label;
- `[[event:TYPE@WINDOW/path]]` is matched separately and navigates to Timeline;
- `ReportReaderContent.jsx:102` passes no-op callbacks, so legacy reader badges
  render without navigation;
- `AnalysisCenter.jsx:418-480` has the active click path.

Analysis Center matching is heuristic: exact path, normalized path (slash,
case, boundary normalization), then bidirectional tail/suffix matching and
first `Array.find` result. It uses the basename only for the missing-item
error label. This differs materially from R2's exact persisted citation ID and
manifest membership validation.

## E. Caller inventory

| Caller | Type | Evidence | Runtime status | Classification |
|---|---|---|---|---|
| `AnalysisCenter.jsx:246` | Frontend active UI | Generate/update button at `:549`, polls old job at `:198-209` | Reachable `/analysis-center` | DEPRECATE |
| `useTaskAutoTrigger.js:66-77` mounted by `Tasks.jsx:62` | Frontend active auto | Auto-starts new Chain B job after task completion; default auto-refresh enabled | Active background behavior | DEPRECATE, then REMOVE after migration |
| `CaseIntelligence.jsx:86` | Frontend active reader | Default tab mounts `IntelligenceReportReader` | Active historical reader | COMPATIBILITY ONLY |
| `caseAnalysisService.js:29-58` | Frontend service | POST/status/poll wrappers | Used by Analysis Center and re-analysis polling | DEPRECATE for writer/status; retain re-analysis only if separately required |
| `Cases.jsx:331` / `TaskTable.jsx:57` | Frontend redirect | Legacy report URLs default to legacy intelligence tab | Active compatibility redirects | COMPATIBILITY ONLY; migrate labels/target |
| `LLMDescriptions.jsx` | Frontend dead page | Old re-analysis/status imports; not routed by `routes.jsx` | No runtime route | REMOVE candidate |
| `scripts/onsite_smoke_test.sh:512-529` | Operational shell | Real POST + polling in onsite smoke test | Invoked manually with bash | DEPRECATE/migrate to R2 or explicit legacy check |
| `scripts/ONSITE_TEST_GUIDE.md:97-102` | Documentation example | Replay curl | Docs-only | COMPATIBILITY/DOCUMENTATION cleanup later |
| `src/network/HTTPServer/LLMPythonProxy.cpp:12-103` | C++ proxy definition | Contains POST/status/wait methods | **C++ ZERO CALLER**; only definitions/compiled symbols | REMOVE candidate after external API audit |
| `scripts/verify_llm_analysis.py` | Script | Uses C++ task API, no Chain B call | Active script, no Chain B dependency | KEEP unrelated |
| `tests/unit/forensic_report/test_analysis_adapter.py` | Test | Reads legacy case_analysis fixture read-only | Current R2 compatibility adapter test | KEEP while adapter retained |
| `tests/unit/test_intelligence_report_routes.py` | Test | Exercises legacy reader route | Current legacy reader contract | KEEP while reader retained |
| `tests/unit/test_deterministic_filter.py` | Test | Pins legacy filter persistence | Legacy writer contract | Migrate/remove only when writer retired |
| `tests/unit/test_d2b_db_ownership.py` | Test | Pins D2b task-owned Chain B boundary | Current D2b contract | KEEP through D3b transition |
| `tests/test_streaming_filter.py`, `tests/verify_llm_calls.py` | Tests/scripts | Import deleted old service module | Cannot exercise current chain | REMOVE candidate |
| `docs/**`, API docs, plans | Documentation | Historical contract/examples | Not runtime | UPDATE after D3b, not evidence for KEEP |

Important distinction: C++ has no real Chain B caller. `LLMPythonProxy` is a
compiled but unused legacy implementation; its live uses elsewhere are
Graphiti methods (`TaskManager.cpp:336-338`, `TaskManagerAnalysis.cpp:175-184,
515-520`), not case-analysis methods.

## F. CaseIntelligence and report UI tree

Current user-visible tree:

```text
/tasks
  -> useTaskAutoTrigger (legacy Chain B auto writer)

/analysis-center
  -> case description
  -> run_filtering/report_only controls
  -> Generate/Update Report (legacy Chain B POST)
  -> old job polling
  -> old case report preview + markdown export
  -> file/event re-analysis

/case-intelligence
  -> default: IntelligenceReportReader (legacy read)
  -> tab=forensic: ForensicReportPage (R2 snapshot/narrative)

/reports/task/:id, /reports/case/:id, /case-report
  -> compatibility redirects to /case-intelligence
  -> default redirect lands on legacy intelligence tab

/investigation
  -> explicitly links to /case-intelligence?...&tab=forensic (R2)
```

There are currently three overlapping user-facing report concepts:

1. Legacy 情报研判/案情报告 (`case_analysis`, IntelligenceReportReader).
2. R2 deterministic 取证快照报告 (`report_versions` + snapshot viewer).
3. R2 persisted 叙事报告 (`/api/reports/generate` + NarrativeReportView).

A correctness/UX issue exists: Cases/Tasks generic “Report” links route through
legacy-default redirects, while Investigation explicitly targets R2 forensic.
Analysis Center's case-level context also calls task-oriented Chain B with a
case ID and can pass an empty files DB path (`AnalysisCenter.jsx:242-253`),
whereas multi-image analysis uses `/api/llm/multi-image-analysis`. This is an
active contract ambiguity, not a reason to delete data blindly.

## G. R2 coverage matrix

| Capability | Chain B | R2 | Result |
|---|---|---|---|
| Narrative generation | Five dynamic chapter LLM calls or fallback | Structured LLM generation | BOTH, but R2 is the canonical frozen path |
| Version history | None; one replaceable row | Immutable `report_versions` | R2 ONLY |
| Frozen input | None; dynamic DB/Graphiti reads | Frozen envelope + input hash | R2 ONLY |
| Evidence selection | Automatic/deterministic or broad current `file_descriptions` | Explicit Report Evidence main/appendix selection | BOTH, different product semantics |
| Accepted Analysis usage | No R1/R2 binding | Frozen accepted-analysis binding | R2 ONLY |
| Claims | Inline prose only | Structured claims and exact IDs | R2 ONLY |
| Citation | Prompt text `[[file]]` / `[[event]]` | Validated persisted citation manifest | R2 ONLY |
| Citation traceback | Heuristic path matching in Analysis Center | Exact citation ID and layered traceback | R2 ONLY |
| Historical report read | `case_analysis` current row reader | Immutable version reader | BOTH; legacy compatibility remains |
| Regeneration | `report_only` reruns over current mutable state | New generation ID from new frozen admission | BOTH; R2 semantics are stable |
| Failure state | In-memory job only; restart loses job | Durable generation state and recovery | R2 ONLY |
| Model metadata | Transient report result; current file/event rows | Persisted report model/prompt metadata | R2 ONLY |
| Prompt version | Absent | Persisted prompt version | R2 ONLY |
| Task context | Task ID plus dynamic task metadata | Frozen task scope and report evidence | BOTH, R2 stronger |
| File summaries | Current `file_descriptions` | Snapshot/bound analysis input | BOTH, different semantics |
| Event summaries | Dynamic events DB cluster reads/updates | Not automatically included; explicit evidence workflow | CHAIN B ONLY as automation, not proven R2 product gap |

Chain B's broader automatic aggregation is not by itself a KEEP reason: D3a
found no evidence that “consume the whole current case” is a required product
contract rather than legacy behavior. R2 deliberately requires analyst-selected
Report Evidence. However, the active Analysis Center and onsite script prove
that the writer cannot be removed in D3a.

## H. Legacy citation identity and provenance

Legacy report prompts require full-looking file paths, but the stored report is
plain Markdown. The backend does not create a citation manifest or parse
reference identity. The frontend uses:

1. exact string match;
2. normalized slash/case/boundary path match;
3. bidirectional suffix/tail match;
4. first matching item.

The UI label is a basename, but the basename is not the primary matching tier.
This remains heuristic and can be ambiguous across tasks/files. R2 never
reuses this logic: R2 validates exact evidence/analysis/claim IDs against a
persisted manifest.

## I. Side effects and lifecycle risks

One Chain B run can:

- create/replace `case_analysis` in task or case DB;
- replace `filtered_files`, `case_description`, `case_report`, timestamps;
- create/alter `file_descriptions` and update `files.llm_*`;
- add/alter/update event `llm_*` fields;
- extract selected files to task workspace;
- ingest case/file/event episodes into Graphiti;
- make five or more LLM calls and retry empty chapters;
- leave only an in-memory job state for polling.

These effects are precisely what R2's frozen admission/publication boundary avoids.
D3a does not change them.

## J. Classification of all Chain B assets

### KEEP

| Asset | Reason |
|---|---|
| R1/R2 report evidence, frozen generation, citation validator, narrative viewer | Current canonical report product; exact identity/version/failure semantics. |
| `IntelligenceReportReader` backend read routes and `AnalysisChaptersAdapter` | Active historical `case_analysis` reader and compatibility fixtures prove read value. |
| `case_analysis` table read schema in historical task/case DBs | Existing rows may be present; no migration or real-case scan justifies deletion. |
| Current R2 tests and legacy reader route tests | Protect canonical and compatibility contracts. |

### COMPATIBILITY ONLY

| Asset | Historical compatibility reason |
|---|---|
| Legacy `case_analysis.case_report` rows | Six-column fixtures and reader routes consume them; V1 is current-only but may be the only historical report. |
| `GET /api/llm/intelligence-report/*` and `GET /api/llm/case-report*` | Active legacy reader/read APIs; can become read-only after writer retirement. |
| `IntelligenceReportReader`, legacy markdown renderer, metadata editor | Live default CaseIntelligence tab; historical viewing and metadata access remain. |
| `/reports/task/*`, `/reports/case/*`, `/case-report` redirects | Old URLs are actively reachable and should not break before explicit target migration. |
| `AnalysisChaptersAdapter` | R2-side legacy read adapter is explicitly read-only and tested. |

### DEPRECATE

| Asset | Current caller | Replacement / precondition |
|---|---|---|
| `POST /api/llm/case-analysis` writer | Analysis Center; onsite smoke script; auto-trigger path | R2 task generation plus explicit migration/onsite replacement. |
| `GET /api/llm/case-analysis/{job_id}` | Analysis Center and re-analysis polling | Durable R2 generation polling or a separately scoped re-analysis job API. |
| `useTaskAutoTrigger` Chain B generation | Mounted by Tasks and enabled by default | Remove auto writer after R2 task workflow covers the intended action. |
| Analysis Center “生成/更新报告” legacy action | Active UI | Replace with R2 task narrative generation or label as Legacy. |
| `LLMPythonProxy` Chain B methods | No C++ caller; compiled definitions only | Remove after external deployment/API audit confirms no binary consumer. |
| `scripts/onsite_smoke_test.sh` Chain B POST | Active manual onsite tool | Migrate smoke assertion to R2/explicit legacy read check. |

### REMOVE candidates (only in D3b after import audit)

| Asset | Evidence |
|---|---|
| Unrouted `web/src/pages/LLMDescriptions.jsx` | Not imported by current `web/src/routes.jsx`; old status/reanalysis page is unreachable. |
| Duplicate `services/case_persistence.py` and `services/case_file_filter.py` classes | Duplicate legacy DDL/writers; active service delegates to `db_utils`; external import audit still required. |
| `tests/test_streaming_filter.py`, `tests/verify_llm_calls.py` old imports | Import deleted `httpserver.services.case_analysis_service`; cannot exercise current service. |
| Unused C++ Chain B proxy methods | No source caller outside definitions/internal wait helper; retain only until external consumer audit. |

No asset is classified as immediate unconditional REMOVE in D3a because active
writer/read/UI/script evidence exists and historical `case_analysis` data may
be present.

## K. D3b recommended option

**Recommended: Soft Retirement + Keep-Isolated.**

Not Full Removal yet, because:

- Analysis Center actively starts Chain B;
- Tasks mounts an auto-trigger that starts Chain B;
- CaseIntelligence defaults to the legacy reader;
- the onsite smoke script performs a real POST and polling;
- legacy `case_analysis` rows are supported by active readers and fixtures;
- old URLs redirect to the legacy-default tab.

D3b should not delete the table or reader first. It should first migrate or
explicitly disable new writer entry points, then preserve read-only access to
historical rows. The legacy chain must remain isolated from R2 and must not be
made an alternate writer for R2 report versions.

## L. D3b exact minimal change scope

D3b should be planned as a separate implementation review. Based on D3a,
its smallest safe scope is:

1. Make the product report entry target explicit: migrate Cases/Tasks/legacy
   redirects and CaseIntelligence default behavior toward R2, or add an
   unmistakable Legacy label and preserve the old reader temporarily.
2. Replace/remove the active Analysis Center Chain B generation button only
   after R2 task generation covers the intended task workflow.
3. Disable/remove `useTaskAutoTrigger`'s Chain B writer after an explicit
   replacement decision; do not remove initial file analysis or
   `reanalyze-files` automatically.
4. Convert `GET /api/llm/intelligence-report/*` and `GET /api/llm/case-report*`
   to compatibility read-only surfaces if historical access is required.
5. Migrate the onsite smoke test away from legacy generation, or make its
   legacy check explicit and read-only.
6. Audit external consumers, then remove unused C++ proxy methods and duplicate
   persistence helpers if no import/binary contract remains.
7. Keep the `case_analysis` schema/read adapter until historical retention is
   explicitly decided. No migration is required by D3a evidence.
8. Keep legacy token renderer only while the legacy reader is user-accessible;
   remove it only after the UI reader and all old markdown consumers are gone.

D3b must separately decide whether R2 needs a case-scope generation surface.
The current R2 GenerateReportPanel is task-only; CaseIntelligence case scope
can read R2 versions but cannot generate a new case narrative (`ReportToolbar`
gates generation to task scope). That gap must not be silently “fixed” by
re-enabling Chain B under a different label.

## M. Compatibility risks

- Removing the writer before migrating Analysis Center/auto-trigger breaks
  active user and background flows.
- Removing the reader/table before archival policy makes historical reports
  unreadable.
- Changing the default CaseIntelligence tab changes old URL behavior and may
  surprise operators using legacy intelligence reports.
- Removing the old polling wrapper can break active re-analysis flows that
  currently reuse its job-status endpoint.
- Removing `LLMPythonProxy` requires an external binary/deployment consumer
  check even though the repository has C++ ZERO CALLER.
- Removing token rendering too early breaks legacy chapter display/navigation.
- R2 task-only generation leaves a case-scope product decision unresolved.

## N. Tests and checks

Allowed D3a checks were static/read-only:

- route registration and endpoint inventory;
- frontend route/import/caller tree sweep;
- C++/CLI/script/doc grep and caller inventory;
- schema/DDL/fixture inspection;
- legacy reader and R2 adapter source inspection;
- existing test inventory without modifying tests or databases.

Relevant tests found:

- `tests/unit/test_intelligence_report_routes.py`: current legacy reader route
  contract;
- `tests/unit/forensic_report/test_analysis_adapter.py`: legacy
  `case_analysis` read adapter, including `[[file:...]]` text preservation and
  read-only URI;
- `tests/unit/forensic_report/test_sqlite_task_adapter.py`: six-column legacy
  case report compatibility;
- `tests/unit/test_intelligence_report_routes.py`: seeded legacy reader DB;
- `tests/unit/test_deterministic_filter.py`: legacy filter persistence;
- `tests/unit/test_llm_response_parser.py`, `test_file_matcher.py`,
  `test_filter_validator.py`, `test_multi_deterministic_filter.py`: filter/parser
  primitives;
- `tests/test_case_analysis_extraction.py`: structural legacy extraction/wiring;
- `tests/test_streaming_filter.py`, `tests/verify_llm_calls.py`: stale imports
  of deleted service module, REMOVE candidates.

No Full run was performed. D2b's last verified baseline remains Python focused
83, frontend 200 plus build, C++ build pass; Full remains deferred.

## O. Exit decision and required 15 answers

1. **Is `/api/llm/case-analysis` registered?** Yes. It is mounted at `/api/llm/case-analysis`.
2. **Is there a real frontend caller?** Yes. Analysis Center actively posts it; Tasks auto-trigger also posts it.
3. **Is there a real C++ caller?** No. `LLMPythonProxy` has compiled definitions, but repository-wide C++ caller audit is **C++ ZERO CALLER** for Chain B methods.
4. **Is there a script/CLI caller?** Yes. `scripts/onsite_smoke_test.sh` performs a real POST and polling; no CLI caller exists. Other curl examples are documentation/replay instructions.
5. **Can CaseIntelligence still trigger Chain B generation?** Indirectly: its default legacy reader links to Analysis Center, where the writer button is active. The reader itself has no generation button.
6. **Does IntelligenceReportReader have a runtime consumer?** Yes. It is the default `CaseIntelligence` tab and reads live legacy APIs.
7. **Can `case_analysis` exist in historical task DBs?** Yes. Active DDL is lazy `CREATE IF NOT EXISTS` in task `_files.db`; repository fixtures and readers seed/read it. Cross-image legacy reports use a case DB.
8. **Does the current writer overwrite history?** Yes. `INSERT OR REPLACE` by `task_id` replaces the prior row; V1 is not separately readable.
9. **How are legacy `[[file:...]]` identities parsed?** Stored as plain Markdown; frontend regex extracts the displayed path, then Analysis Center uses exact, normalized, and bidirectional tail matching with first-match behavior. The backend does not persist structured citation identity.
10. **Does R2 cover all currently real Chain B product functions?** It covers canonical frozen narrative generation, versioning, evidence selection, accepted analysis/claims, exact citations, traceback, and durable failure. It does not currently provide R2 case-scope generation, and Chain B's broad automatic event/file aggregation is a different legacy behavior rather than proven required product value.
11. **Is there a Chain B-only function that must KEEP?** No proven irreplaceable Chain B-only product function was found. Active callers and historical read value require transition, not immediate deletion.
12. **Which assets must be COMPATIBILITY ONLY?** Historical `case_analysis` rows/schema, legacy intelligence reader APIs/UI, `AnalysisChaptersAdapter`, token renderer while reader remains, and old URL redirects.
13. **Which can be removed immediately?** None as unconditional production removal. D3b candidates are the unrouted `LLMDescriptions` page, stale test scripts importing deleted modules, duplicate unused persistence helpers, and unused C++ proxy methods after external audit.
14. **Soft Retirement, Full Removal, or Keep-Isolated?** Soft Retirement + Keep-Isolated. Stop new legacy writes only after active UI/auto/script callers are migrated; retain read compatibility.
15. **What is the exact D3b scope?** Migrate/label Analysis Center and auto-trigger, decide R2 case-scope generation, migrate onsite smoke, preserve legacy read-only reader/table, then remove only proven-unused wrappers/helpers/tests. Do not delete `case_analysis` or token reader first.

### D3a exit gate

- D3a-E1 production caller inventory: PASS
- D3a-E2 real UI entry confirmation: PASS
- D3a-E3 historical persistence compatibility: PASS
- D3a-E4 legacy citation reader dependency: PASS
- D3a-E5 R2 coverage matrix: PASS
- D3a-E6 all assets classified: PASS
- D3a-E7 D3b option and exact scope: PASS
- D3a-E8 no production/frontend/API/migration changes: PASS

**D3a decision: PASS — investigation complete.**

Stop here. Do not delete Chain B assets or begin D3b in this phase.
