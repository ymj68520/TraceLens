# D3b Legacy Chain B Soft Retirement

## A. Before / After

Before D3b, the task lifecycle and Analysis Center could POST `/api/llm/case-analysis`, schedule an in-memory Chain B job, and write mutable `case_analysis` rows. Case Intelligence defaulted to that legacy reader, while R2 was available only through an explicit forensic tab.

After D3b, new report generation is explicit R2 generation. The normal task lifecycle and frontend report workflow do not invoke Chain B. `case_analysis` data, the legacy intelligence reader, and legacy token rendering remain available only for historical compatibility.

## B. Current Report Workflow

The current UI defaults Case Intelligence to the forensic view. Task-scoped R2 generation remains available through the existing Report Evidence and `/api/reports/generate` workflow, with exact generation and report identities. Case scope remains a read/view context; this phase does not invent case-scope R2 generation.

Analysis Center remains an evidence and explicit file re-analysis workspace. Its former full-report button and mutable Markdown preview were removed. The page links to the forensic report view instead of silently replacing Chain B with another writer.

## C. Legacy Read Compatibility

The following remain unchanged and read-compatible:

- `case_analysis` schema and historical rows;
- `/api/llm/intelligence-report/{task_id}` directory, records, search, and metadata routes;
- `IntelligenceReportReader` and its historical chapters;
- `AnalysisChaptersAdapter` and the SQLite legacy adapter;
- `[[file:...]]` and `[[event:...]]` legacy token rendering.

The legacy tab is reached explicitly with `?tab=intelligence` and is labeled `历史研判报告`. It does not fall back to R2 data and does not trigger generation when historical data is absent.

## D. Writer Retirement Contract

`POST /api/llm/case-analysis` now returns HTTP 410 with:

`legacy case analysis generation has been retired; use report generation`

The response is produced before task-store resolution, service construction, job insertion, or `asyncio.create_task`. No new full Chain B job or `case_analysis` row can be created through this route.

The status route remains mounted for the independent explicit file re-analysis workflow. Jobs created by that workflow are tagged `kind=\`reanalyze\``; untagged historical/full-generation job IDs return the same retired 410 contract.

## E. UI Migration

- Case Intelligence defaults to `forensic`; explicit `?tab=intelligence` remains historical compatibility.
- Legacy report redirects now include `tab=forensic` when a task or case identity is present.
- Analysis Center's full Chain B generation button, report polling, and mutable legacy preview were removed.
- Analysis Center's explicit file re-analysis controls remain available.

## F. Auto-Trigger Changes

`useTaskAutoTrigger` remains mounted by Tasks for silent task-list refresh. It no longer checks for legacy reports or calls `startCaseAnalysis`, and it does not auto-submit R2 generation. Final report generation remains analyst-triggered.

## G. Onsite Smoke Migration

The onsite smoke script no longer POSTs or polls `/api/llm/case-analysis`. Its AI-degradation stage now performs a read-only mounted-surface check against `/api/reports?scope_type=task&scope_id=...`. It does not require Report Evidence or an LLM. Replay guidance directs operators to the explicit R2 Evidence + Generate workflow.

## H. C++ Compatibility

`LLMPythonProxy` Chain B method definitions remain compiled and source-compatible. Repository inspection found zero production C++ callers for those methods, but external binary/source consumers cannot be ruled out. Their removal is deferred to a later dead-code cleanup after consumer audit. Active Graphiti proxy methods remain untouched.

## I. Classification

KEEP:

- R2 report evidence, generation, exact polling, narrative viewer, and citation traceback;
- current evidence workflows;
- explicit file re-analysis;
- historical reader and its compatibility adapters.

COMPATIBILITY ONLY:

- `case_analysis` schema/data;
- legacy intelligence routes and reader;
- legacy token renderer;
- historical report redirects;
- C++ Chain B proxy signatures.

RETIRED / DEPRECATED:

- full Chain B POST writer;
- full-generation status jobs;
- Analysis Center full-report action;
- task-completion Chain B auto-trigger;
- onsite Chain B smoke generation.

REMOVED:

- active frontend full-report writer call;
- auto-trigger writer call;
- onsite Chain B POST/poll call.

## J. Tests and Verification

D3b focused verification:

- Python retirement and D2b ownership tests: 14 passed.
- Legacy intelligence reader, legacy adapters, and R2 route registration: 45 passed.
- Frontend Case Intelligence, redirects, and route tests: 12 passed.
- Existing R2 generation panel and narrative integration: 8 passed.
- Frontend production build: passed.
- Python compile and onsite shell syntax: passed.
- `git diff --check`: passed.

The full frontend lint command remains blocked by pre-existing repository-wide errors and warnings outside this change; the changed files have no new lint errors. The Fast Refresh warning on `LegacyReportRedirect.jsx` predates D3b.

## K. Known Remaining Legacy Code

- Chain B service/pipeline/parser/report-generator internals remain for historical compatibility and later dead-code review.
- `caseAnalysisService.js` retains legacy read and explicit re-analysis helpers; the full generation helper now fails closed locally.
- C++ Chain B proxy methods remain for compatibility.
- Unrouted legacy `LLMDescriptions` code and duplicate persistence helpers remain deferred debt.
- Case-scope R2 generation is intentionally not added in this phase.

## L. Exit Gate

| Gate | Result |
|---|---|
| E1 R2 forensic view is the default | PASS |
| E2 Analysis Center no longer invokes Chain B writer | PASS |
| E3 task auto-trigger no longer invokes Chain B writer | PASS |
| E4 onsite smoke no longer depends on Chain B writer | PASS |
| E5 POST case-analysis cannot create a new legacy report | PASS |
| E6 historical case_analysis remains readable | PASS |
| E7 legacy token renderer remains historical-only | PASS |
| E8 R2 generation/viewer/citation behavior unchanged | PASS |
| E9 schema/data not deleted or migrated | PASS |
| E10 C++ production flow unchanged | PASS |
| E11 normal lifecycle creates no new full Chain B rows | PASS |
| E12 current and historical report UI semantics are separated | PASS |

**D3b SOFT RETIREMENT PASS**

Fast and Full profiles remain deferred by phase policy. D4 lifecycle, D5 debt cleanup, D6 performance work, Chain B full deletion, schema deletion, migration, and C++ proxy removal are outside this phase.
