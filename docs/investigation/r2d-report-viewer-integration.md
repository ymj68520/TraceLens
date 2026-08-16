# R2d — Final Report Viewer & Frontend Integration

Baseline: R1 Report Evidence `ffdacba` → R2a investigation `91682eb` → R2b
frozen admission `131e021` → R2c execution/citations `1bfd852` → **R2d (this
phase)**. This closes the R2 main chain:

```
Report Evidence (R1) → Frozen Generation (R2b) → LLM execution (R2c)
→ validated citations (R2c) → immutable version + persisted manifest (R2c)
→ Viewer → exact Evidence / Analysis / Claim traceback (R2d)
```

## 1. Repository investigation conclusions (pre-implementation)

1. A completed generation returns exact `generation_id` + `report_id` +
   `produced_version` (and embeds the persisted manifest on completed polls).
2. R2c publication allocates `MAX(version)+1` inside the task scope and
   inserts a **Chain A `report_versions` ready row** — narrative versions and
   deterministic snapshots share one version sequence and one `reports.db`.
3. The existing Viewer selects versions by exact `report_id` (VersionHistory
   radio); initial load auto-selects `latestReady` (allowed by §30 as the
   "no prior selection" case).
4. The R2c manifest (`report_kind:"llm_generation"`, `sections`, `citations`)
   does **not** fit the deterministic Viewer schema (`categories`/`pages`);
   feeding it to `ReportWorkspace` would crash on `manifest.categories`.
5. → Strategy B: a new Narrative view inside the existing Report page; the
   deterministic snapshot Viewer is untouched.
6. Chain A `GET /api/reports/{report_id}/manifest` layout check rejects the
   R2c `snapshots/` layout → narrative needs its own read path.
7. The global-report-id-no-task-scope issue (R2a P1-5) is untouched in Chain
   A; the new narrative read façade enforces task scope with opaque 404s.
8. Before R2d the R2c manifest was only exposed embedded in the completed
   generation poll — no exact-version persisted-manifest read existed.
9. Citation traceback had no backend surface; the C9a strict snapshot /
   exact analysis / exact claims GETs already provide optional enrichment.

## 2. Backend minimal gaps (§29 — read-only, no executor semantics changes)

- **`report_kind` version marker (§11).** Additive nullable column on
  `report_versions` (`_add_report_kind_column`): `NULL` = deterministic
  snapshot (all pre-existing rows), `'llm_generation'` = R2c publication.
  The publication INSERT writes the marker. A one-time backfill types
  R2c-era rows via the writer-owned `snapshots/` layout convention
  (server-side migration, not a frontend filename heuristic). The marker is
  exposed on `ReportVersion` read models (A-chain list/status responses now
  distinguish the two kinds deterministically).
- **Relative `manifest_path`.** R2c stored an absolute path (inconsistent
  with the A-chain relative convention; disclosed absolute server paths in
  list/status responses). Publication now stores
  `final_dir.relative_to(report_root)`.
- **Strict narrative read façade.**
  `GET /api/reports/narrative/versions/{report_id}?task_id=` —
  `read_narrative_version_strict` (`forensic_report/narrative_reader.py`):
  `mode=ro` + `PRAGMA query_only` (no create/migrate/self-heal — §20),
  identity = `(task_id, report_id)`; foreign-task ids, deterministic ids and
  missing ids are all the same opaque 404 (`report not found`), never a
  scope hint (§19). The manifest is resolved through
  `GenerationReportWriter.read_manifest` (confined by construction),
  re-validated against `GenerationReportManifest`, and identity-matched to
  the row; a missing/tampered manifest fails closed with 503
  (`report narrative record is unavailable`). Response = persisted version
  row + manifest: `task_id, report_id, version, status, generation_id,
  title, created_at, model, prompt_version, input_hash, sections[],
  citations[]` (§21). No envelope bytes, no system prompt, no filesystem
  paths.

Forbidden by §29 and not done: changes to generation input semantics, the
citation validator, Report Evidence binding, or the R2c executor (the two
publication changes above are additive metadata/consistency fixes, not
semantics).

## 3. Frontend architecture

Single generation UI on the Report page (`/case-intelligence?taskId=…&tab=forensic`,
the forensic tab hosts `ForensicReportPage`). The Investigation Workbench
gains only a navigation entry (`生成叙事报告 / 打开报告` →
`/case-intelligence?taskId=<id>&tab=forensic`); the report page has
`返回调查工作台`. No second generation UI, no Workbench viewer, one task
source (global TaskSelector searchParam).

- **`reportGenerationService.js`** — `generateReport(taskId, {requestedBy})`
  (request body is exactly `{task_id, requested_by}`),
  `getReportGeneration(taskId, generationId)` (exact-id poll),
  `getNarrativeReport(taskId, reportId)` (strict façade read).
- **`useReportGenerationPolling`** — identity-bound `{taskId, generationId}`;
  polls only `GET /generations/{generation_id}`; `admitted`/`running`
  continue, `completed`/`failed` stop; transient HTTP errors don't stop
  polling; late responses from an old identity are dropped.
- **`GenerateReportPanel`** — source summary from R1
  `GET /api/reports/evidence` (Main/Appendix/Original-only/Bound counts;
  `newer_accepted_available` hint "存在更新的 accepted Analysis，但当前
  Report Evidence 仍绑定历史版本" — no auto rebind); correct semantics line
  ("基于当前显式 Report Evidence 集合"); actor input; synchronous-ref
  double-click guard (one admission per user action); HTTP admission error
  and durable `status=failed` are displayed separately (error_code +
  sanitized message + neutral hints for the common codes); after a terminal
  state an explicit new admission (new `generation_id`) is allowed — never
  an automatic retry.
- **`ForensicReportPage`** — renders `NarrativeReportView` when the selected
  version's `report_kind === 'llm_generation'` (task scope only);
  `useReportVersion.loadManifest` skips narrative versions (they never touch
  the A-chain manifest route). On generation completion the page refreshes
  and then selects **only the exact** `(report_id, produced_version)` via
  the new `useReportVersion.selectByReportId` (reads the hook's
  synchronously-fresh `versionsRef`) — and only if the user's selection has
  not changed since admission; otherwise it just refreshes the list (a late
  completion never hijacks an explicit historical selection, §7/§30).
- **`VersionHistory`** — remains the single version selector; rows carry a
  快照/叙事 badge derived from the server-persisted `report_kind` (never a
  filename/manifest-shape guess).
- **`NarrativeReportView`** — renders persisted sections + audit metadata
  (generation_id, prompt_version, model, truncated input_hash); citation
  chips are exact `citation_id`s; clicking opens the traceback panel; an
  unknown citation id in a corrupted payload fails safely with no guessing.
- **`CitationTracebackPanel`** — manifest entry is the authoritative frozen
  identity; three visually/semantically distinct layers: Evidence
  (Evidence Source) → optional Accepted Analysis (analyst-accepted derived
  finding) → optional Claim (derived claim). Original-only citations show
  "Original Evidence only" and never auto-attach an analysis (§17). Optional
  enrichment via exact strict reads (`getInvestigationSnapshot`,
  `getInvestigationAnalysis`, `listInvestigationAnalysisClaims` + exact
  `claim_id` filter); if current Investigation detail is unavailable the
  frozen identity stays visible with a "详细记录暂时不可读取" hint — the
  citation is never reported as nonexistent (§15). No Graph Entity / Event /
  Timeline Cluster ever appears as provenance (§24). The panel's identity is
  `{taskId, reportId, citationId}`; late responses from another
  citation/task are dropped (§23).
- **Task switch** — `CaseIntelligence` remounts `ForensicReportPage` with a
  scope key, which resets the generation panel, polling, narrative view and
  citation panel; pending responses are identity-guarded inside each
  component/hook.

## 4. Historical version semantics (§12/§16/§30)

The narrative view reads only the persisted version + manifest; the
traceback panel shows the manifest's frozen `analysis_id`/`claim_id` and
enriches through exact-id reads. Later accepted analyses, rebinding, claim
changes or event refreshes cannot alter an opened version: the §28
integration test proves V1 keeps showing A1/C1 after A2 is accepted and
rebound, and only G2/V2 shows A2. Selection changes only on initial load,
explicit user click, or a just-completed generation while the user is still
in the generation workflow.

## 5. Added / Modified / Reused

**Added (backend)**: `forensic_report/narrative_reader.py`,
`routes/report_narrative.py`,
`tests/unit/forensic_report/test_report_narrative_routes.py`.
**Added (frontend)**: `services/reportGenerationService.js`,
`hooks/useReportGenerationPolling.js` (+test),
`components/reports/GenerateReportPanel.jsx` (+test),
`components/reports/NarrativeReportView.jsx` (+test),
`components/reports/CitationTracebackPanel.jsx` (+test),
`pages/ForensicReportPage.generation.test.jsx`.
**Modified**: `forensic_report/repository.py` (report_kind column/backfill/
insert/read), `forensic_report/models.py` (ReportVersion.report_kind),
`forensic_report/generation_execution.py` (relative manifest_path),
`httpserver/main.py` (router), `routes` contract test; frontend
`useReportVersion.js` (narrative skip + `selectByReportId`),
`ForensicReportPage.jsx`, `VersionHistory.jsx`, `CaseIntelligence.jsx`
(tab param + back link), `Investigation.jsx` (navigation entry), locales.
**Reused**: R2c generate/poll routes, R1 evidence list API, C9a/C9b/C5a
exact investigation reads, A-chain list surface, GenerationReportWriter
confined manifest read, existing Viewer components for deterministic
snapshots.
**Do-not-touch (verified untouched)**: Chain B `/api/llm/case-analysis` and
`IntelligenceReportReader` (legacy isolated), deterministic snapshot
generation/Viewer internals, R2c executor semantics, citation validator,
Report Evidence binding, C++ services.

## 6. Tests

- Backend (`test_report_narrative_routes.py`, real store + published
  manifest): persisted contract + version numbering; opaque 404 for
  cross-task / deterministic-id / unknown-id (identical detail); missing
  store / missing table → 404; corrupt store → 503; missing/tampered
  manifest → 503; `report_kind` marker + relative path on the list surface;
  R2c-era store backfill migration.
- §26 Generate UI: source summary counts (main=2/appendix=1/original-only=1/
  bound=2), newer-accepted hint, request body exactly `{task_id,
  requested_by}`, rapid triple-click → one POST, HTTP admission failure vs
  durable failure separated, empty source guidance, queued/running continue
  + completed/failed stop (hook), completed → exact report_id/version, task
  switch stale drop (hook), late completion never hijacks an explicit
  historical selection (page).
- §27 Viewer: sections render, exact manifest lookup for citation chips,
  original-only citation → no Analysis layer, exact A1/C1 ids passed to the
  detail readers, same-text C1/C2 → C1 exact, enrichment unavailable →
  frozen identity still visible, unknown citation id → safe error,
  cross-task report id → opaque 404 (backend). Item 8 (unselected evidence
  can never appear in a valid manifest) is locked by the R2c citation
  validator regression (`test_generation_execution.py`).
- §28 integration (`ForensicReportPage.generation.test.jsx`): Evidence A
  (main, bound A1/C1) + B (appendix, original-only) → Generate →
  admitted → running → completed → exact V1 → citation CITA → exact A1/C1
  → A2 accepted + rebind → V1 unchanged → G2/V2 shows A2; plus the
  no-hijack historical-selection scenario.

## 7. R2 Exit Gate (§33)

| Gate | Result |
| --- | --- |
| R2-E1 generation consumes only frozen R1 bindings | PASS — R2b/R2c suites; request body `{task_id, requested_by}` only |
| R2-E2 Original-only evidence never gains an analysis | PASS — §17 test; R2c validator rejects it server-side |
| R2-E3 Historical report version immutable | PASS — manifest-frozen Viewer + §28 V1-after-rebind proof |
| R2-E4 citations only selected Report Evidence | PASS — R2c validator regression |
| R2-E5 analysis citations = frozen bound analysis | PASS — R2c validator + traceback exact-id test |
| R2-E6 claim citations = exact frozen claim | PASS — C1/C2 same-text test |
| R2-E7 Viewer consumes persisted manifest only | PASS — NarrativeReportView + traceback read model |
| R2-E8 same claim text never merges identity | PASS — exact claim_id filter test |
| R2-E9 later accepted/rebind never rewrites old reports | PASS — §28 + §16 semantics |
| R2-E10 cross-task report isolation | PASS — opaque 404 backend test |
| R2-E11 report read path has no DB mutation/self-heal | PASS — mode=ro + query_only reader |
| R2-E12 legacy case-analysis chain outside new flow | PASS — untouched; new UI never references it |
| R2-E13 Workbench → Report → Citation traceback chain | PASS — §28 integration test |

## 8. Verification record

- Focused: backend narrative/routes/lifecycle batch green; new frontend
  tests 23 passed; existing frontend regression batch 111 passed; R2c
  execution + generation routes regression green.
- Full Gate (this phase, required — first full R2 main-chain milestone):
  frontend full vitest, production build, scoped ESLint; Python
  investigation / fast / full; `git diff --check`. Results recorded in the
  final report.

## 9. Known P2/Debt (unchanged)

Reports.db read routes of Chain A still lack task-scope validation (R2a
P1-5; the new façade covers the R2 surface only). ReportVersion.error raw
leak (R2a P1-4). Credential rotation still pending (user action). PDF/DOCX
export, WYSIWYG, automatic evidence selection, collaboration, Phase D —
explicitly out of scope (§36).
