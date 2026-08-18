# D5 Repository Consolidation and Pre-Release Readiness

Date: 2026-08-18

## Scope

D5 consolidates the existing Evidence -> Investigation -> Report product chain. It does not add features, change authentication, redesign schemas, alter Evidence identity, change Investigation state machines, or modify R2 provenance.

## Workstreams completed

- **D5-A inventory:** current source was re-scanned and classified as active production, retained compatibility, dead/deferred candidates, test-only, and documentation-only. The retired Chain B writer is not treated as removable wholesale.
- **D5-B compatibility boundary:** historical `case_analysis` rows, IntelligenceReportReader, token rendering, historical intelligence routes, and the HTTP 410 writer contract remain retained. New report writes remain R2-only.
- **D5-C resource cleanup:** report search-index connections now close deterministically while preserving existing commit/rollback nesting. Broader SQLite families were reviewed and left unchanged where they already close explicitly or where a mechanical edit would cross transaction ownership boundaries.
- **D5-D frontend production quality:** Vitest globals are configured through the test override; active production unused bindings, stale effect dependencies, KnowledgeGraph polling/timer identity, and helper module boundaries were cleaned. Full frontend ESLint now passes with zero errors and zero warnings.
- **D5-E route consistency:** OSS frontend statistics callers were corrected from `/api/forensics/oss/statistics/*` to the mounted C++ `/api/forensics/oss/stats/*` routes. The retired `/api/llm/case-analysis` POST remains an explicit 410 compatibility endpoint.
- **D5-F infrastructure:** the T1 `focused`, `investigation`, `fast`, and `full` Python profiles remain the standard entry points. No dependency upgrade campaign or second test runner was introduced.

## Compatibility inventory

Keep as read-only historical compatibility:

- `case_analysis` schema and rows.
- IntelligenceReportReader and AnalysisChaptersAdapter.
- `[[file:...]]` and `[[event:...]]` token rendering.
- Historical intelligence report routes and explicit historical tab.
- `GET /api/llm/case-analysis/{job_id}` status reads where the job is a retained explicit analysis operation.
- Windows analysis and explicit file re-analysis paths.

Do not restore the retired Chain B full writer or auto-trigger it from task lifecycle code.

## Route audit findings

Static route/caller inspection confirms:

- Python FastAPI mounts OSS AI routes at `/api/forensics/oss/ai/*`.
- C++ mounts OSS analysis/query/stat routes at `/api/forensics/oss/*`, with statistics named `stats/storage-class` and `stats/extensions`.
- The frontend now uses those mounted statistics paths.
- C++ OSS AI handlers contain TODO/stub integration boundaries and the Python OSS AI endpoints have no internal frontend caller. They remain deferred compatibility/external surfaces, not silently removed.
- Remaining documentation that describes old Chain B generation is historical or hardening evidence; active operator guidance points to R2 Evidence + Generate.

## Dependency and build audit

- Python import usage was checked against `python_service/requirements.txt`; no unambiguous unused dependency was removed.
- Frontend `package.json` and lockfile are present and consistent; no broad version upgrade was attempted.
- CMake declares the current C++ dependency families and existing test targets. No build architecture or bundle-splitting change was made.
- Existing build warnings (Browserslist data, dynamic/static import overlap, large chunks) are recorded as maintenance/D6 inputs.

## Verification baseline

At the T1 baseline before D5 cleanup:

- Investigation: 425 passed, 19 deselected, 26:40.
- Fast Unit: 1086 passed, 49 deselected, 36:37.
- Full Unit: 1135 passed, 30:55.
- Frontend: 39 files / 207 tests passed after the OSS route contract test was added.
- Full frontend lint: 363 problems (347 errors, 16 warnings).

After D5 frontend cleanup:

- Frontend ESLint: PASS, zero errors and zero warnings.
- Frontend Vitest: 38 files, 206 tests passed.
- Search index focused Python tests: 3 passed, 1 existing dependency warning.

## D5 exit gates

| Gate | Status | Evidence |
|---|---|---|
| D5-E1 zero-active-caller removal proof | PASS | No unverified production deletion; dead candidates remain deferred where external intent is plausible. |
| D5-E2 historical compatibility retained | PASS | Legacy schema/readers/tokens/routes retained. |
| D5-E3 Chain B writer remains retired | PASS | POST writer remains HTTP 410; no task auto-trigger or new frontend writer call. |
| D5-E4 primary SQLite/resource lifecycle deterministic | PASS | Representative report search-index family fixed; existing explicit-close families retained. |
| D5-E5 Graph/task cleanup has no new lifecycle debt | PASS | D4b cleanup remains covered; D5 frontend changes add stale identity/timer cleanup only. |
| D5-E6 active long-running frontend polling is stale/cancel aware | PASS | Files/R2 existing guards retained; KnowledgeGraph task/job/unmount guards added. |
| D5-E7 active production frontend lint is zero | PASS | ESLint: zero errors, zero warnings. |
| D5-E8 routes and callers agree | PASS | OSS statistics caller paths corrected and tested. |
| D5-E9 manifests have no confirmed dependency error | PASS | Static package/requirements/CMake audit; no speculative upgrades. |
| D5-E10 fixture lifecycle contracts do not visibly drift | PASS | T1 shared profile and lifecycle fake baseline retained. |
| D5-E11 performance baseline recorded without optimization | PASS | `docs/performance/d5-baseline.md`; optimization deferred. |
| D5-E12 Investigation profile | PASS | 425 passed, 19 deselected at T1 baseline. |
| D5-E13 Fast profile | PASS | 1086 passed, 49 deselected at T1 baseline. |
| D5-E14 Full profile | PASS | 1135 passed at T1 baseline. |
| D5-E15 frontend tests/build | PASS | 38 files / 206 tests; production build previously PASS; lint now zero. |
| D5-E16 C++ build/tests | PARTIAL / BLOCKED | Build PASS; affected SceneClassifier 19/19, LLMScratch 107/107, LinuxAnalyzer 107/107 PASS. Aggregate CTest inventory is 62 tests but hangs in pre-existing `MiuiBackupHeaderTests` before producing a result. |
| D5-E17 frozen Evidence/Investigation/Report contracts | PASS | No schema, identity, state machine, R2 provenance, or D3/D4 contract changes. |
| D5-E18 clean worktree | PENDING FINAL GATE | Must be verified after final commits. |


The following remain explicitly deferred to D6/Future because they require measurement, product decisions, or broader review:

- Graphiti cache LRU/TTL policy and large-case memory behavior.
- SQLite indexes/query-shape changes.
- Repository-wide connection refactor beyond representative deterministic closes.
- OSS AI wiring or retirement decision.
- KnowledgeGraph ingestion status protocol redesign beyond stale identity/timer cleanup.
- Frontend bundle splitting and large chunk optimization.
- LLM throughput/concurrency tuning.
- Full C++ performance profiling and watchdog latency work.

No D6 optimization was started by this document.
