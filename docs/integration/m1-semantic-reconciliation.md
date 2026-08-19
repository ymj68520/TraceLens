# TraceLens M1 Semantic Reconciliation

## A. Baselines and Scope

| Item | Value |
| --- | --- |
| Local frozen baseline | `051db05 feat: add phase f live acceptance harness` |
| Remote `origin/Dev` | `2b9b8f2 chore: ignore local environment configuration` |
| Merge base | `8c4c7d4` |
| Integration branch | `integration/dev-merge-20260819` |
| Previous merge | `git merge --no-ff origin/Dev` attempted, then safely aborted |
| Merge commit | none |
| History rewrite | none |
| Push | none |
| Worktree before M1 | clean |

M1 is documentation and investigation only. No production, frontend, schema, or test file is changed by this document. The previous merge produced 154 `add/add` conflicts and 5 content conflicts, 159 total. The current tree comparison also contains 388 direct divergent paths. This is a semantic reconciliation problem, not a mechanical ours/theirs merge.

The analysis priority is current tree, current callers, current tests, current schema, current routes, then commit history. Local `051db05` is the safety baseline because its Evidence, Investigation, R2, lifecycle, and Phase F contracts have live acceptance evidence. Remote `2b9b8f2` is the feature baseline for the newer Workbench, Final Report presentation/rendering, Android/MIUI/QQNT, media metadata, and cluster improvements.

## B. Decision Vocabulary

Only these five module strategies are used:

- `KEEP_LOCAL_CORE`: local implementation remains canonical; remote behavior may be ported only through a later compatibility layer.
- `ADOPT_REMOTE`: remote implementation replaces local only after proving every frozen invariant equivalent. No current high-risk module qualifies.
- `ADAPT_REMOTE_ON_LOCAL`: remote UI, workflow, or rendering is retained through an adapter/facade over local canonical state.
- `MERGE_COMPLEMENTARY`: both sides solve independent problems and can coexist with one owner per capability.
- `REJECT_REMOTE_REGRESSION`: remote behavior is based on a retired or weaker contract and must not enter the integrated tree.

No module is left as "decide during merge".

## C. Reconciliation Matrix

| Module | LOCAL | REMOTE | OVERLAP | Remote new value | Local invariant | Integration decision |
| --- | --- | --- | --- | --- | --- | --- |
| Evidence / Resolver | `path_utils`, strict key parser, task-scoped resolver | duplicate normalizer/parser and optional resolver | same file/cluster evidence concepts | cluster expansion and bounded evidence presentation | `(task_id, evidence_key)` and exact normalization | `KEEP_LOCAL_CORE` |
| Files / Initial Analysis | task-owned C++ paths, read-only source DB, Chain B retirement | legacy case-analysis caller and client path extraction | file descriptions and reanalysis | existing case-analysis compatibility surface | task-owned path authority; no overwrite of Initial Analysis | `REJECT_REMOTE_REGRESSION` plus adapter later |
| Timeline / Cluster | stable event cluster identity and overlay links | canonical cluster bucket semantics and richer timeline UI | event clustering and investigation drawer | configurable cluster presentation and digest behavior | identity is timestamp bucket plus event type, never title | `MERGE_COMPLEMENTARY` |
| Investigation persistence | `InvestigationRepository`, split services, v7 store, live-store guard | `investigation_persistence.py` and replacement service | snapshots, analyses, claims, events, refreshes | bootstrap, notes, provenance, report dataset | existing-only writes, TOCTOU liveness, immutable inputs | `KEEP_LOCAL_CORE` |
| Secondary Analysis | versioned executor and structured grounding | replacement direct job writer | same analyst analysis flow | richer workbench views and claim provenance | queued/running/review_pending/accepted/rejected/failed/invalid | `KEEP_LOCAL_CORE` |
| Analyst Review | explicit review route and accepted-first selection | task-scoped accept/reject workflow | same review purpose | newer task-scoped UI workflow | no automatic accept and exact version review | `KEEP_LOCAL_CORE` plus adapter |
| Investigation Event | local event repository and evidence links | replacement service event model | event timeline and evidence links | bootstrap and event presentation | task-scoped immutable event history | `KEEP_LOCAL_CORE` |
| Event Refresh | frozen envelope, atomic completion, stale recovery | direct LLM update in replacement service | event title/summary refresh | richer event analysis presentation | frozen input; restart -> `failed(service_restart)`; no resurrection | `KEEP_LOCAL_CORE` |
| Investigation Graph | accepted-first overlay over base KG | local graph and relation presentation in workbench | graph nodes and evidence | richer filtering/presentation | accepted analysis first; pending explicitly unconfirmed | `ADAPT_REMOTE_ON_LOCAL` |
| Report Evidence | exact accepted analysis binding or original-only NULL | replacement report evidence selection | same selected evidence concept | richer report dataset selection | exact binding, no pending fallback | `KEEP_LOCAL_CORE` |
| Report Generation | local R2 frozen input, hash, manifest and citation traceback | Final Report dataset/assembly/render pipeline | report inputs and publication | section planning, render validation, presentation/export | R2 generation and manifest remain authority | `ADAPT_REMOTE_ON_LOCAL` |
| Final Report / Rendering | immutable R2 report/version reader | final report repository, render candidate and presentation | report output display | richer HTML/Markdown/print and validation | viewer reads exact immutable version, no silent latest | `ADAPT_REMOTE_ON_LOCAL` |
| CaseIntelligence | local forensic default and explicit legacy route | report reader/workspace changes | case report navigation | richer report browsing | default forensic path and task scope | `MERGE_COMPLEMENTARY` |
| Investigation frontend | local graph/workbench shell | Workbench vNext and Final Report Viewer | same `/investigation` product area | richer analyst workflow and report UI | calls canonical backend; polling/task isolation preserved | `ADAPT_REMOTE_ON_LOCAL` |
| AnalysisCenter | existing task-scoped analysis page | small UI/service changes | same analysis entry | feature additions | no change to Initial/Secondary layering | `MERGE_COMPLEMENTARY` |
| ServiceManager | local executor lifecycle and recovery | manager without investigation executors | same service ownership | remote workbench service facade | one lifecycle owner, recovery before serving | `KEEP_LOCAL_CORE` plus adapter |
| Task lifecycle | local task ID and trusted output path chain | real C++ integration task fixtures | task lookup and terminal state | improved ingestion integration | task ID is authority and terminal semantics remain stable | `KEEP_LOCAL_CORE` |
| Markitdown / Office | live socket handoffs and bounded workspace | extractor improvements | same conversion boundary | additional media/document extraction | workspace containment and cleanup | `MERGE_COMPLEMENTARY` |
| Android / MIUI / QQNT | D6 initialization and no-AI protections | MIUI, QQNT, WeChat and Android LLM features | same Android analyzers | artifact parsers, routes and UI | no real LLM dependency in deterministic tests; preserve source integrity | `MERGE_COMPLEMENTARY` |
| Media metadata | existing extractor and scratch cleanup | expanded media metadata extraction | media analysis | richer metadata coverage | temporary frame resources cleaned and bounded | `MERGE_COMPLEMENTARY` |
| C++ build/runtime | Phase F path isolation, Markitdown/DLL handoffs | Android/MIUI/media/text-dump additions | shared build and runtime files | new analyzers and tests | `PROJECT_ROOT`/`DATA_DIR`, ports, cleanup | `MERGE_COMPLEMENTARY` with manual build merge |
| Testing / acceptance | T1 profiles, focused Investigation tests, Phase F live harness | remote feature tests and real C++ ingestion tests | shared fixtures and test runners | new feature coverage | Phase F five acceptance targets remain | `MERGE_COMPLEMENTARY` |

## D. Evidence and Path Authority

### Evidence identity

Local is authoritative for:

- `normalize_evidence_path`: slash normalization, repeated slash collapse, trailing slash removal, no lowercase, no `normcase`, no basename identity, and no dot-segment identity rewrite.
- `parse_evidence_key` and `resolve_evidence`: strict key grammar and task-scoped fail-closed resolution.
- `file:<normalized_path>` and `cluster:v1:<unix_minute>:<encoded_event_type>`.
- `(task_id, evidence_key)` as the complete identity boundary.

Remote `investigation_evidence.py` duplicates the grammar and uses more permissive decoding and nullable resolution. That is not an equivalent replacement. Remote cluster expansion and bounded presentation may be ported through the local resolver; a second identity grammar is prohibited.

### Files and task paths

The integrated authority map is frozen as:

| Input | Classification | Authority |
| --- | --- | --- |
| `task_id` | client selector and server lookup key | trusted C++ task state |
| `files_db_path`, `raw_db_path`, `events_db_path` | compatibility hint only | server-derived task-owned paths |
| `workspace_root` | bounded request input | server containment check |
| Evidence key | client-selected identity | local strict parser plus task resolver |

Remote active Chain B callers derive `task_id` from a client `files_db_path` and pass that path into analysis. This reintroduces D2b risk and is classified `REJECT_REMOTE_REGRESSION`. No remote path may become database authority without a task lookup and exact trusted-path comparison.

## E. Investigation Backend Decision

The canonical Investigation backend is the local split package:

```text
python_service/httpserver/services/investigation/
  repository.py
  live_store.py
  acquisition.py
  execution.py
  review.py
  event.py
  event_refresh_execution.py
  graph.py
  read.py
  report_evidence.py
```

Its canonical store is the task-owned v7 `investigation.db`. It owns snapshots, versioned Secondary Analysis, claims, review state, events, event evidence, refresh envelopes, and Report Evidence.

The remote `investigation_persistence.py` and `investigation_service.py` are not a drop-in replacement. The current inspection found direct replacement job writes that do not carry the local `open_live_task_store` TOCTOU and existing-store-only terminal write boundary. Remote bootstrap, notes, claim provenance, local graph presentation, evidence analysis views, and report dataset helpers are valuable, but they must be adapted onto the local backend. The integrated product must not have two Investigation writers or two canonical Investigation databases.

### Investigation table ownership target

| Data | Canonical owner | Remote treatment |
| --- | --- | --- |
| Evidence snapshot | local `InvestigationRepository` | derived/read adapter only |
| Analysis version/history | local repository and executor | presentation adapter only |
| Analysis claims and claim evidence | local repository | presentation adapter only |
| Analyst review | local review service | adapter route/view model |
| Event and event evidence | local event service | adapter route/view model |
| Event Refresh envelope/version | local refresh executor | remote summary input only |
| Graph overlay selection | local graph reader | remote rendering may consume output |
| Report Evidence | local exact-binding service | remote dataset reads selected rows |
| Remote notes/provenance views | no second writer in M2 | derived projection until ownership review |

No Investigation schema migration is designed in M1.

## F. Report Architecture Decision

The local R2 chain remains the only factual and publication authority:

```text
Local Report Evidence selection
  -> Local frozen generation input
  -> Local LLM generation
  -> Local citation validation
  -> Local immutable report version and manifest
```

The remote Final Report family is classified as downstream capability:

```text
Local immutable report/version/manifest
  -> remote dataset adapter
  -> section planning/rendering/validation
  -> HTML/Markdown/print presentation
```

Remote `final_report_repository.py`, `report_render_repository.py`, and `report_validation_repository.py` may be retained as derived/presentation stores only after their inputs are bound to a local immutable report/version. They may not create a competing factual authority, a second accepted/published state, or a dynamic latest-state report. Any remote implementation that rereads current Files, current Analysis, or current Graph and regenerates a report outside the frozen R2 envelope is rejected as a publication replacement.

### Report schema ownership target

| Store/table family | Owner | Classification |
| --- | --- | --- |
| local `reports.db` report versions | local R2 repository | canonical publication |
| local `report_generation_inputs` | local R2 repository | canonical frozen admission |
| local citation manifest and claim/evidence bindings | local generation executor | canonical provenance |
| remote `final_report_versions` | remote Final Report adapter only | derived presentation projection |
| remote `final_report_publications` | not a second publication authority | prohibited until mapped to local report ID/version |
| remote `section_render_candidates` | remote render repository | derived render cache/history |
| remote `section_render_validations` | remote QA/render validation | presentation-only validation |

Version numbers must not be compared numerically across these families. No migration SQL is part of M1. If M2 proves a remote table necessary, its owner, rebuild source, task scope, and one-way dependency on local canonical data must be documented before implementation.

## G. API Ownership Matrix

| API family | Local owner | Remote surface | Final M2 strategy |
| --- | --- | --- | --- |
| `/api/investigation/snapshots` | local capture route | task-scoped bootstrap/snapshot methods | keep local route; adapter may translate shape |
| `/api/investigation/analyses` | local Secondary admission/status/claims | `/{task_id}/analysis/...` workbench routes | keep local writer; add non-colliding facade |
| `/api/investigation/events/*` | local event and refresh routes | task-scoped event/report routes | keep local writer; adapter reads/writes through it |
| `/api/investigation/graph` | local accepted-first graph | workbench graph view | adapter over local graph output |
| `/api/reports/evidence` | local exact binding | task-scoped report-evidence | local route is canonical; facade only |
| `/api/reports/generate` | local R2 admission/execution | final-report assembly | local generation first; rendering downstream |
| `/api/reports/generations/*` | local exact generation polling | final report detail/publication | local generation ID/version remains source |
| `/api/llm/case-analysis` | local retired writer returns 410 | remote active writer | `REJECT_REMOTE_REGRESSION` |
| `/api/reports/*` legacy readers | local compatibility readers | remote report workspace | preserve local routes and add explicit adapter |

Remote static routes must not be shadowed by a broad `/{task_id}` route. Any adapter must preserve opaque error mappings and task context.

## H. Remote Feature Preservation Matrix

| Remote feature | User value | Backend/frontend | Schema impact | Local overlap | Final strategy | M2 gate |
| --- | --- | --- | --- | --- | --- | --- |
| Investigation Workbench vNext | analyst evidence-to-report workflow | new task-scoped service/routes/UI | uses remote persistence today | high | `ADAPT_REMOTE_ON_LOCAL` | route adapter tests plus Phase F analyst journey |
| Final Report rendering/presentation | HTML/Markdown/print report views | final-report services and viewer | derived render/publication tables | medium | `ADAPT_REMOTE_ON_LOCAL` | exact local report/version/manifest binding |
| Android LLM analysis | Android artifact analysis | C++ service, Python routes, UI | Android analysis tables | low | `MERGE_COMPLEMENTARY` | C++ Android tests and deterministic no-AI checks |
| MIUI backup enhancements | richer offline backup parsing | C++ parsers, routes, UI | Android artifact tables | low | `MERGE_COMPLEMENTARY` | MIUI CTest and CLI smoke |
| QQNT artifact parsing | QQNT inventory and extraction | C++ parser and Android UI | Android artifact tables | low | `MERGE_COMPLEMENTARY` | parser and source-integrity tests |
| WeChat graph improvements | richer graph/timeline behavior | Python/C++/frontend | existing graph data | low | `MERGE_COMPLEMENTARY` | WeChat dataset and graph tests |
| Media metadata expansion | more file metadata | Python extractor, C++ queries, Files UI | existing output records | low | `MERGE_COMPLEMENTARY` | media metadata and C++ query tests |
| Canonical cluster semantics | stable timeline investigation | C++ Timeline, Python cluster, UI drawer | no new DB required | medium | `MERGE_COMPLEMENTARY` | identity and cluster regression tests |
| Real C++ ingestion integration | stronger task parsing test | Python integration test | no schema change | low | `MERGE_COMPLEMENTARY` | isolated real-task test plus Phase F task |
| Text dump/export improvements | bounded extraction | C++ exporter and tests | no schema change | low | `MERGE_COMPLEMENTARY` | TextDump and Markitdown tests |

## I. Local Invariant Preservation Matrix

| Invariant | Remote conflict | Final owner | M2 verification |
| --- | --- | --- | --- |
| Evidence identity | duplicate permissive grammar | local resolver | key and resolver tests; Phase F Evidence snapshot |
| Immutable snapshot | replacement persistence can rewrite inputs | local repository | snapshot equality and hash test |
| Secondary history | remote direct writer | local executor/repository | version/status/grounding tests |
| Analyst review | remote task-scoped accept surface | local review service | explicit review and accepted-first tests |
| Grounding | remote validation differs | local structured/grounding validator | claims and invalid-output tests |
| Event Refresh | direct remote LLM update | local refresh executor | frozen envelope and atomic completion tests |
| Task deletion | remote replacement lacks local live-store guard | local `open_live_task_store` | D4 deletion race suite |
| Restart recovery | remote service has different recovery path | local executor initialization | `failed(service_restart)` and no replay |
| Graph selection | remote may expose broader history | local graph reader | accepted-first overlay test |
| Report Evidence | remote replacement selection | local exact binding | accepted ID and original-only NULL tests |
| Frozen generation | remote Final Report can dynamically reread | local R2 admission | input hash and frozen envelope tests |
| Citation | remote report validation may become authority | local citation manifest | Evidence/Analysis/Claim traceback |
| Chain B retirement | remote reactivates writer | local retired route | HTTP 410 and no active writer caller |
| Task path authority | remote accepts client path | local C++ task lookup and trusted paths | path ownership tests and live task journey |
| Acceptance harness | remote tree omits local scripts/targets | local Phase F harness | five `make acceptance-*` profiles |
| Error sanitization | remote restores raw exception responses | local config/error mapping | D1 sanitization tests |
| Port contract | remote has older config variants | local 8080/8090/8091 contract | Vite proxy and service smoke |
| Temporary resource cleanup | remote media additions touch scratch paths | local cleanup guards | C++ scratch and matrix acceptance |

## J. Schema and Migration Findings

No Investigation or report migration chain is accepted by M1. The local Investigation store is v7 and already carries the tested semantics for snapshots, analyses, claims, events, refreshes, and Report Evidence. The remote persistence source describes a separate schema family with event, snapshot, analysis, claim, and report tables, but its direct writer/recovery behavior is not equivalent to the local D4/C7 contracts.

The remote Final Report tables are not automatically a replacement for local `reports.db` or `report_generation_inputs`. They are classified as derived until a later design proves stable local report/version/manifest binding. No new database, no schema version bump, and no migration SQL is authorized by M1.

Schema ownership is therefore:

```text
investigation.db -> Local InvestigationRepository
reports.db      -> Local R2 ReportRepository
render caches    -> Remote derived renderer, rebuildable from local manifest
```

There must be one writer per canonical capability and no Local Investigation write plus Remote Investigation write, or Local report publication plus Remote Final Report publication, in the integrated product.

## K. Conflict Family Matrix

| Conflict family | Scope | Strategy | Complexity | M2 notes |
| --- | --- | --- | --- | --- |
| Root config/build/docs | `.env.example`, `.gitignore`, `CMakeLists.txt`, `Makefile`, README and route docs | `MANUAL_COMBINE` | medium | keep 8080/8090/8091, add acceptance targets, preserve remote build entries |
| Python generic routes/services | existing routes, extractor, graphiti, LLM and config modules | `REBUILD_FROM_LOCAL_WITH_REMOTE_FEATURE` | medium | preserve local sanitization/path contracts; port additive behavior |
| Chain B case-analysis | case-analysis endpoint/helper files | `TAKE_LOCAL` | high | remote active writer and client path are rejected |
| Investigation route | `REBUILD_FROM_LOCAL_WITH_REMOTE_FEATURE` | very high | keep flat frozen routes; add workbench facade without duplicate writer |
| Investigation persistence/executors | local investigation package versus remote replacement modules | `TAKE_LOCAL` for writer; `ADAPT_REMOTE_ON_LOCAL` for reads | very high | no second store or direct replacement job writes |
| Forensic report generation | local R2 generation modules versus remote stripped forensic report modules | `REBUILD_FROM_LOCAL_WITH_REMOTE_FEATURE` | very high | local generation schema and citation authority remain |
| Final Report modules | remote-only dataset/render/assembly/presentation family | `ADAPT_REMOTE_ON_LOCAL` | high | consume exact local immutable version/manifest |
| ServiceManager | local recovery lifecycle versus remote reduced manager | `TAKE_LOCAL` plus facade | high | executor recovery and shutdown ordering are mandatory |
| Python tests and profiles | local T1/Phase F suites versus remote feature tests | `MANUAL_COMBINE` | high | retain all local contract suites; add remote feature tests |
| C++ core/HTTP/TaskManager | shared runtime and new remote analyzer behavior | `MANUAL_COMBINE` | high | preserve DATA_DIR/PROJECT_ROOT and task lifecycle |
| Android/MIUI/QQNT | overlapping Android database/parser files | `MERGE_COMPLEMENTARY` | medium | preserve D6 no-AI and source integrity |
| Media/Markitdown/TextDump | shared extractor/client files | `MERGE_COMPLEMENTARY` | medium | preserve bounded workspace and cleanup |
| Frontend shared pages/services | many add/add files | `MANUAL_COMBINE` | high | preserve task context, proxy, stale polling and local routes |
| Frontend Investigation | local shell versus remote Workbench vNext | `REBUILD_FROM_REMOTE_WITH_LOCAL_INVARIANT` | very high | remote UI may be retained only over local backend |
| Frontend Reports | local report views versus remote Final Report viewer | `REBUILD_FROM_REMOTE_WITH_LOCAL_INVARIANT` | high | exact immutable report/version is the only data source |
| CMake/test registration | shared test lists | `MANUAL_COMBINE` | medium | union registrations; no test deletion |

## L. File-Level Merge Manifest

The following is the complete manifest for the 159 paths reported by the safe hypothetical merge. The strategy applies to every path explicitly listed below; this is the M2 conflict-resolution input, not an instruction to run a bulk ours/theirs checkout.

### L1. Manual combine: root, docs, shared Python infrastructure

- `.env.example`
- `.gitignore`
- `CMakeLists.txt`
- `Makefile`
- `README.md`
- `docs/README.md`
- `docs/modules/python/httpserver/HTTPRoutes.md`
- `python_service/graphiti_integration/graphiti_ingestor.py`
- `python_service/httpserver/config.py`
- `python_service/httpserver/main.py`
- `python_service/httpserver/prompts.py`
- `python_service/httpserver/routes/associations.py`
- `python_service/httpserver/routes/case_analysis_models.py`
- `python_service/httpserver/routes/database.py`
- `python_service/httpserver/routes/dll.py`
- `python_service/httpserver/routes/graphiti_endpoints/_admin.py`
- `python_service/httpserver/routes/graphiti_endpoints/_ingest.py`
- `python_service/httpserver/routes/graphiti_endpoints/_jobs.py`
- `python_service/httpserver/routes/graphiti_endpoints/_migrate.py`
- `python_service/httpserver/routes/graphiti_endpoints/_query.py`
- `python_service/httpserver/routes/health.py`
- `python_service/httpserver/routes/llm_endpoints/_analysis.py`
- `python_service/httpserver/routes/llm_endpoints/_management.py`
- `python_service/httpserver/routes/llm_models.py`
- `python_service/httpserver/routes/markitdown.py`
- `python_service/httpserver/routes/multi_analysis.py`
- `python_service/httpserver/routes/office.py`
- `python_service/httpserver/routes/oss_analysis.py`
- `python_service/httpserver/routes/system.py`
- `python_service/httpserver/routes/wechat_graph_endpoints/_data.py`
- `python_service/httpserver/routes/wechat_graph_endpoints/_graph.py`
- `python_service/httpserver/services/case_analysis/case_aggregation_manager.py`
- `python_service/httpserver/services/case_analysis/case_analysis_parts/_pipelines.py`
- `python_service/httpserver/services/case_analysis/case_analysis_parts/_windows.py`
- `python_service/httpserver/services/case_analysis/cluster_analyzer.py`
- `python_service/httpserver/services/case_analysis/file_analyzer.py`
- `python_service/httpserver/services/case_analysis/report_generator.py`
- `python_service/httpserver/services/cpp_backend.py`
- `python_service/httpserver/services/extractors/media_metadata.py`
- `python_service/httpserver/services/extractors/security_formats.py`
- `python_service/httpserver/services/forensic_report/__init__.py`
- `python_service/httpserver/services/forensic_report/search_index.py`
- `python_service/httpserver/services/forensic_report/service.py`
- `python_service/httpserver/services/llm/file_analyzer.py`
- `python_service/httpserver/services/llm/llm_service.py`
- `python_service/httpserver/services/llm/model_manager.py`
- `python_service/httpserver/services/graphiti_parts/_ingest.py`
- `python_service/httpserver/services/graphiti_parts/_jobs.py`
- `python_service/httpserver/services/graphiti_parts/_status.py`
- `python_service/httpserver/services/ingestion_job_parts/_manager.py`
- `python_service/httpserver/services/ingestion_job_parts/_worker.py`
- `python_service/httpserver/services/wechat_graph_parts/_queries.py`
- `python_service/httpserver/services/wechat_graph_parts/_timeline.py`
- `python_service/httpserver/services/windows_artifacts/windows_analyzer.py`
- `python_service/httpserver/services/windows_artifacts/windows_integration.py`
- `python_service/httpserver/services/windows_artifacts/windows_toon_exporter.py`
- `python_service/pytest.ini`
- `python_service/tests/conftest.py`
- `python_service/tests/integration/test_analyzed_only_ingestion_e2e.py`
- `run.sh`
- `scripts/ONSITE_TEST_GUIDE.md`
- `scripts/onsite_smoke_test.sh`
- `scripts/start_all_services.sh`
- `web/.eslintrc.cjs`
- `web/src/components/Layout/Layout.jsx`
- `web/src/components/case-intelligence/report-reader/ReportMetadataEditor.jsx`
- `web/src/components/case-intelligence/report-reader/ReportMetadataEditor.test.jsx`
- `web/src/components/case-intelligence/report-reader/sections/CaseInfoSection.jsx`
- `web/src/components/case-intelligence/report-reader/sections/DeviceInfoSection.jsx`
- `web/src/components/case-intelligence/report-reader/sections/EvidenceInfoSection.jsx`
- `web/src/components/case-intelligence/report-reader/sections/GenericArtifactTable.jsx`
- `web/src/components/case-intelligence/report-reader/sections/SmsThreads.jsx`
- `web/src/components/case-intelligence/report-reader/sections/artifactColumns.jsx`
- `web/src/components/case-intelligence/report-reader/sections/shared.jsx`
- `web/src/components/case-intelligence/report-reader/sections/shared.test.jsx`
- `web/src/components/common/TaskSelector.jsx`
- `web/src/components/common/TaskSelector.test.jsx`
- `web/src/components/common/TerminalOutput.jsx`
- `web/src/components/common/ToastContext.jsx`
- `web/src/components/files/OfficePreviewTab.jsx`
- `web/src/components/filters/FilterProfileEditor.jsx`
- `web/src/components/filters/FilterProfileSelector.jsx`
- `web/src/components/reports/VersionHistory.jsx`
- `web/src/components/tasks/AddTasksToCaseModal.jsx`
- `web/src/components/tasks/ComposeCaseModal.jsx`
- `web/src/components/tasks/CreateTaskModal.jsx`
- `web/src/components/tasks/TaskTable.jsx`
- `web/src/components/timeline/ClusterInvestigationDrawer.jsx`
- `web/src/hooks/useFileLLMAnalysis.js`
- `web/src/hooks/useFilesData.js`
- `web/src/hooks/useReportVersion.js`
- `web/src/hooks/useReportVersion.test.jsx`
- `web/src/hooks/useTaskAutoTrigger.js`
- `web/src/locales/en.js`
- `web/src/locales/zh.js`
- `web/src/pages/AnalysisCenter.jsx`
- `web/src/pages/CaseIntelligence.jsx`
- `web/src/pages/Cases.jsx`
- `web/src/pages/Dashboard.jsx`
- `web/src/pages/Files.jsx`
- `web/src/pages/ForensicReportPage.jsx`
- `web/src/pages/KnowledgeGraph.jsx`
- `web/src/pages/LLMDescriptions.jsx`
- `web/src/pages/LegacyReportRedirect.jsx`
- `web/src/pages/LegacyReportRedirect.test.jsx`
- `web/src/pages/Logs.jsx`
- `web/src/pages/OSS.jsx`
- `web/src/pages/Tasks.jsx`
- `web/src/pages/Terminal.jsx`
- `web/src/pages/Timeline.jsx`
- `web/src/pages/WeChatGraph/components/SearchBar.jsx`
- `web/src/routes.jsx`
- `web/src/routes.test.jsx`
- `web/src/services/api.js`
- `web/src/services/caseAnalysisService.js`
- `web/src/services/forensicsService.js`
- `web/src/services/investigationService.js`
- `web/src/services/llmService.js`
- `web/src/services/llmService.test.js`
- `web/src/services/officeService.js`
- `web/src/services/ossService.js`
- `web/vite.config.js`

### L2. Take local: retired Chain B and canonical Investigation lifecycle

- `python_service/httpserver/routes/case_analysis_endpoints/_case.py`
- `python_service/httpserver/routes/case_analysis_endpoints/_helpers.py`
- `python_service/httpserver/routes/case_analysis_endpoints/_windows.py`
- `python_service/httpserver/services/service_manager.py`

The listed route helper files are local-first manual work in M2, with the explicit rule that the local 410 writer retirement, task-owned path resolution, and sanitized errors remain. `service_manager.py` is local lifecycle core; remote workbench services are added only as manager-owned adapters.

The following local package is not an unresolved add/add path because remote deletes it, but it must be retained when resolving deletes:

- `python_service/httpserver/services/investigation/`

All files under that package are `KEEP_LOCAL_CORE`, especially `repository.py`, `live_store.py`, `execution.py`, `event_refresh_execution.py`, `event.py`, `review.py`, `graph.py`, `read.py`, and `report_evidence.py`.

### L3. Rebuild from local with remote feature: Investigation and R2 conflicts

- `python_service/httpserver/routes/investigation.py`
- `python_service/httpserver/services/forensic_report/models.py`
- `python_service/httpserver/services/forensic_report/repository.py`
- `python_service/tests/unit/forensic_report/test_repository.py`
- `python_service/tests/unit/forensic_report/test_routes.py`
- `python_service/tests/unit/forensic_report/test_service.py`
- `python_service/tests/unit/forensic_report/test_source_resolver.py`
- `python_service/tests/unit/test_investigation_routes.py`
- `python_service/tests/unit/test_markitdown_routes.py`
- `python_service/tests/unit/test_service_manager_report_lifecycle.py`
- `python_service/tests/unit/test_wechat_dataset.py`

Remote-only modules that must be evaluated as adapters rather than dropped are:

- `python_service/httpserver/services/investigation_errors.py`
- `python_service/httpserver/services/investigation_evidence.py`
- `python_service/httpserver/services/investigation_persistence.py`
- `python_service/httpserver/services/investigation_service.py`
- `python_service/httpserver/services/citation_validation.py`
- `python_service/httpserver/services/claim_provenance_reader.py`
- `python_service/httpserver/services/report_dataset.py`
- `python_service/httpserver/services/report_final_validation.py`
- `python_service/httpserver/services/report_render_repository.py`
- `python_service/httpserver/services/report_rendering.py`
- `python_service/httpserver/services/report_validation_repository.py`
- `python_service/httpserver/services/section_planning.py`
- `python_service/httpserver/services/final_report_assembly.py`
- `python_service/httpserver/services/final_report_presentation.py`
- `python_service/httpserver/services/final_report_repository.py`

These are remote additions, not permission to create a second canonical writer or schema.

### L4. Manual combine: C++ and shared runtime

- `src/AnalysisOrchestrator.cpp`
- `src/CommandLineParser.cpp`
- `src/CommandLineParser.h`
- `src/analyzers/AndroidAnalyzer/AndroidAnalysisDatabase.cpp`
- `src/analyzers/OfficeAnalyzer/OfficeAnalyzer.cpp`
- `src/analyzers/OfficeAnalyzer/OfficeAnalyzer.h`
- `src/export/TextDumpAdapters.cpp`
- `src/export/TextDumpAdapters.h`
- `src/export/TextDumpExporter.h`
- `src/integration/LLMIntegration/FileAnalyzer.cpp`
- `src/integration/LLMIntegration/FileAnalyzer.h`
- `src/integration/LLMIntegration/MarkitdownProxy.cpp`
- `src/integration/LLMIntegration/MarkitdownProxy.h`
- `src/main.cpp`
- `src/network/HTTPServer/LLMAnalysisService.cpp`
- `src/network/HTTPServer/LLMAnalysisService.h`
- `src/network/HTTPServer/Queries/TimelineQueries.cpp`
- `src/network/HTTPServer/TaskManager.cpp`
- `src/network/HTTPServer/TaskManagerAnalysis.cpp`
- `src/network/HTTPServer/routes/TimelineRoutes.cpp`
- `tests/CMakeLists.txt`
- `tests/integration/test_miui_cli_e2e.py`

The local `src/main.cpp` `PROJECT_ROOT`/`DATA_DIR` startup wiring is mandatory. The remote Android, media, text-dump, Markitdown, Timeline and C++ task additions are preserved only after symbol-level review. `tests/CMakeLists.txt` is a union, never a deletion of either side's tests.

### L5. Manual combine: frontend Investigation and Report surfaces

- `web/src/pages/Investigation.jsx` (local path conflicts with remote directory replacement and must be resolved as a route migration, not a deletion)
- `web/src/pages/Investigation/Investigation.jsx`
- `web/src/pages/Investigation/FinalReportViewer.jsx`
- `web/src/components/investigation/InvestigationGraphCanvas.jsx`
- `web/src/components/investigation/investigationGraphConstants.js`
- `web/src/components/investigation/workbench/CaptureEvidenceForm.jsx`
- `web/src/components/investigation/workbench/CreateEventForm.jsx`
- `web/src/components/investigation/workbench/DetailPanel.jsx`
- `web/src/components/investigation/workbench/EventTimelinePanel.jsx`
- `web/src/components/investigation/workbench/EvidenceListPanel.jsx`
- `web/src/components/investigation/workbench/GraphTabPanel.jsx`
- `web/src/components/investigation/workbench/LinkEvidenceForm.jsx`
- `web/src/components/investigation/workbench/RefreshNarrativeForm.jsx`
- `web/src/components/investigation/workbench/ReportEvidenceForm.jsx`
- `web/src/components/investigation/workbench/ReviewDecisionForm.jsx`
- `web/src/components/investigation/workbench/SubmitAnalysisForm.jsx`
- `web/src/components/reports/CitationTracebackPanel.jsx`
- `web/src/components/reports/GenerateReportPanel.jsx`
- `web/src/components/reports/NarrativeReportView.jsx`

Remote Workbench components and Final Report Viewer are retained as `ADAPT_REMOTE_ON_LOCAL`; local graph/polling/task isolation behavior is preserved. The final route map is not changed in M1.

## M. M2 Implementation Order

1. Reconcile root config, CMake, Makefile, ports and independent C++ additions.
2. Reconcile Android/MIUI/QQNT, media metadata, TextDump, Markitdown and Timeline/cluster while preserving cleanup and identity.
3. Re-establish Evidence and task-path authority in the merged Python boundary.
4. Keep local Investigation persistence, lifecycle, executors and recovery as the backend owner.
5. Add remote evidence/provenance/workbench read behavior through adapters without a second writer.
6. Keep local R2 Report Evidence, frozen generation, citation validation and publication authority.
7. Add remote dataset/render/validation/presentation as derived downstream capabilities.
8. Integrate the remote Workbench and Final Report UI over canonical local API data.
9. Merge tests by contract ownership; retain all local regression and Phase F profiles, then add remote feature tests.
10. Run focused tests, cheap gates, full language-specific gates, then all five Phase F acceptance profiles.

Do not merge frontend first and infer backend semantics afterward.

## N. Tests and Acceptance Ownership

Local contract tests are mandatory and cannot be deleted as duplicates:

- Evidence key and resolver tests.
- D4 task deletion boundary tests.
- Secondary analysis, grounding, review and event tests.
- Event Refresh execution/recovery tests.
- Graph accepted-first tests.
- Report Evidence and R2 admission/execution tests.
- D1 error sanitization and D3 Chain B retirement tests.
- T1 Investigation/Fast/Full runners.
- Phase F `acceptance-smoke`, `acceptance-task`, `acceptance-analyst`, `acceptance-restart`, and `acceptance-matrix`.

Remote feature tests are also preserved:

- citation/provenance reader tests;
- dataset, section planning, render and final-report repository tests;
- Investigation evidence/persistence/workbench route tests;
- Android/MIUI/QQNT and media metadata tests;
- real C++ ingestion integration tests;
- frontend Workbench and Final Report tests.

Any test with a conflicting expectation must be classified by contract. A test cannot be removed merely because it exercises the local implementation. M1 runs no test suite and makes no claim that a merged tree is buildable.

## O. Risks and Exit Questions

### Known risks

- Investigation route shapes are incompatible: local flat routes use body/query `task_id`; remote routes use `/{task_id}/...` and can shadow static paths.
- Remote replacement persistence lacks demonstrated local D4 liveness and existing-store-only terminal writes.
- Remote Final Report publication can become a second authority unless bound to local immutable report/version/manifest.
- Remote Chain B callers actively use a retired writer and client path input.
- `service_manager.py`, `main.py`, `src/main.cpp`, CMake, Makefile, Vite proxy, and shared frontend services are high-blast-radius files.
- The browser backend remains external-validation pending and is not a reason to invent a browser PASS.
- Distributed/control remains an isolated PostgreSQL JSONB prerequisite.

### M1 exit questions

| Question | M1 answer |
| --- | --- |
| Which Investigation persistence is canonical? | Local `InvestigationRepository` and split services |
| How does Workbench connect? | Remote UI through an adapter/facade over local backend |
| Is a new Investigation schema needed? | No decision or migration authorized; remote schema is not a replacement |
| Which Report publication is canonical? | Local R2 report repository and manifest |
| Is Remote Final Report competing or presentation? | Presentation/derived capability, not competing authority |
| Which remote report tables remain? | Render/validation tables only as rebuildable derived data, pending M2 owner mapping |
| Is a schema migration needed? | Not established; M1 explicitly does not design one |
| How are Chain B callers handled? | Reject active writer callers; retain 410/read-only compatibility |
| How are `files_db_path` regressions handled? | Reject client authority; use task-owned trusted paths |
| How are Android/MIUI/QQNT features preserved? | Merge complementary with D6 safeguards |
| How are remote frontend routes preserved? | Adapt Workbench and Final Report UI over local APIs |
| How is Phase F preserved? | Keep all five acceptance targets and harness files |
| Which remote code is explicitly rejected? | Chain B writer, client path authority, raw debug error exposure, replacement Investigation/R2 writers |
| Which local code can remote replace? | No current canonical high-risk backend; remote may replace presentation components via adapter |
| Can M2 proceed without redesigning frozen architecture? | Yes only with the adapter/derived-data plan and no dual writers; implementation risk is very high |

## P. M1 GO / NO-GO

`M1 NO-GO FOR M2 IMPLEMENTATION` at this point.

The architecture decisions are now explicit, but the following implementation proofs are still required before M2 can begin:

- adapter route shape that cannot shadow local routes;
- proof that remote Workbench reads and writes only through local canonical services;
- proof that remote Final Report consumes exact local immutable report/version/manifest;
- explicit ownership for any derived render/validation store;
- complete file-level implementation review for all 159 conflict paths;
- no reactivation of Chain B or client-authoritative database paths.

M1 is therefore complete as a reconciliation document, but not a merge authorization. A later review may change the decision to `GO FOR M2` only after these proofs are accepted. No final merge, production change, schema change, test change, or Phase G work is started by M1.
