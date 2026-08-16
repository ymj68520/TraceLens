# Phase R2a — Repository Investigation Report: Report Generation Integration

- Date: 2026-08-16
- Baseline: Dev @ `ffdacba` (R1), on top of `d83c1f7` (Security Preflight) and `eb05322` (C10)
- Scope: READ-ONLY investigation of the current Report generation / Viewer
  implementation and freeze of the R2 target contract. No production code was
  changed in this phase.
- Test policy: full regression DEFERRED BY POLICY (single full run costs ≥ 90
  min; next required full gate is after the R2 main chain closes). Only
  collect-only plus two focused route suites were run (see §K).

## 0. Executive summary

There is no single Report system in this repository. Three coexisting chains
must not be conflated when designing R2:

| Chain | Entry | What it is | LLM | Persistence |
|---|---|---|---|---|
| **A. Forensic snapshot report** | `POST /api/reports` → `services/forensic_report/` | Deterministic, versioned snapshot of a task's `files` table into JSON page shards + per-report FTS index + manifest | **No** | Global `reports.db` (`report_versions`) + immutable snapshot dir per report |
| **B. LLM narrative case report** | `POST /api/llm/case-analysis` → `services/case_analysis/` | Legacy per-chapter LLM Markdown report | Yes | In-memory job dict + `INSERT OR REPLACE` into task `files.db` `case_analysis` |
| **C. Report Evidence binding (R1)** | `GET/POST/PUT /api/reports/evidence` → `services/investigation/` | Frozen analyst bindings of captured Evidence (± exact accepted Analysis) | No | Per-task `investigation.db` `report_evidence` (optional v7 extension) |

Headline facts for the R2 contract:

1. **The current `/api/reports` engine contains no LLM, no prompt, no citation
   system, and no report_evidence consumption.** It is a deterministic
   file-table exporter with excellent version/immutability/publish machinery.
2. **No `citation_manifest` exists anywhere in the repo** (`grep -ri citation`
   over `python_service/` and `web/src`: zero source matches). The nearest
   structures are the free-text `AnalysisReference{chapter, token}` field
   (never populated) and Chain B's inline Markdown `[[file:...]]` tokens
   resolved by fuzzy path matching in the frontend.
3. **Chain B (the only LLM report today) violates the frozen-input principle
   by design** — it re-reads live DB state and live Graphiti/Neo4j inside the
   background job ("DYNAMIC AGGREGATION", `report_generator.py:78-80`), keeps
   jobs in a module dict (lost on restart), persists with
   `INSERT OR REPLACE` (history overwritten), and leaks `str(e)` / provider
   URLs to HTTP. R2 must NOT extend Chain B; its reusable parts are the LLM
   transport and the structured-response parser pattern already proven by
   C5b/C7c-2 in the investigation subsystem.
4. **Chain A's machinery is directly reusable**: `BEGIN IMMEDIATE` per-scope
   version allocation, staged + atomically published immutable snapshots,
   restart recovery that fails interrupted versions, strict fixed-string route
   errors, a read-only FTS open path, and a frontend Viewer with version
   history. What is missing is everything the R2 contract adds: frozen
   admission input, narrative generation, exact-ID citations, traceback UI.
5. **One real R1 regression was found during R2a focused verification**:
   `tests/unit/forensic_report/test_routes.py::test_application_registration_exposes_report_routes_and_preserves_legacy_routes`
   fails at HEAD because R1 mounted three `/api/reports/evidence` routes that
   the test's exact-route-set assertion (lines 357-361) does not include. The
   file is outside the `investigation` profile's path set, so R1's staged
   verification never collected it. Fix is a 3-entry addition to
   `expected_report_routes` — scheduled as the first commit of R2b (see §J).
6. **No P0 blockers.** All integrity-relevant machinery (R1 bindings,
   immutable analysis/event provenance in `investigation.db`, Chain A
   publish) is sound. The P1s are additive gaps or live in Chain B, which R2
   does not extend. Recommendation: **proceed directly to R2b.**

---

## A. Existing Report Architecture

### A.1 Chain A — forensic snapshot report (`/api/reports`)

- **Root entity**: `ReportVersion` (`services/forensic_report/models.py:196`),
  one row per generated version. Scope is `(scope_type, scope_id)` with
  `ScopeType = task | case`; **only `task` is implemented** — `case` raises
  `NotImplementedError` before version allocation (`service.py:93-94`,
  `125-128`).
- **Storage**: one **global** `reports.db` (NOT per-task) at
  `<report_output_dir>/reports.db` (default `build/data/reports`, env
  `FORENSIC_REPORT_DIR`; `service_manager.py:345-368`), plus a per-report
  snapshot directory
  `snapshots/<scope_type>/<safe_segment(scope_id)>/<report_id>/` containing
  `manifest.json`, `data/<evidence_id>/<platform>/<category>/<page>.json`
  shards, and `search.sqlite3` (`snapshot_writer.py:178-296`).
- **DDL (complete)** — `repository.py:25-50`:
  ```sql
  CREATE TABLE IF NOT EXISTS report_versions (
      report_id TEXT PRIMARY KEY,
      version INTEGER NOT NULL,
      scope_type TEXT NOT NULL,
      scope_id TEXT NOT NULL,
      status TEXT NOT NULL,
      title TEXT NOT NULL,
      task_ids_json TEXT NOT NULL,
      stage TEXT NOT NULL,
      progress INTEGER NOT NULL DEFAULT 0,
      generated_at TEXT,
      manifest_path TEXT,
      offline_bundle_path TEXT,
      warnings_json TEXT NOT NULL DEFAULT '[]',
      error TEXT,
      created_at TEXT NOT NULL,
      UNIQUE(scope_type, scope_id, version)
  );
  ```
  There is **no `task_id` column** — task association is `scope_type='task'` +
  `scope_id=<task_id>` plus the `task_ids_json` list. There are **no triggers**
  and **no DELETE path** on this table.
- **Async model**: HTTP 202 + in-process `asyncio` worker
  (`service.py:112-115`). States persisted exactly: `queued | generating |
  ready | failed` (`models.py:15-19`). Admission row is inserted **before**
  any worker starts, and version allocation is inside the same
  `BEGIN IMMEDIATE` as the INSERT (`repository.py:52-95`). Concurrency: the
  per-scope unique version serializes numbering; a cross-process
  `_ReportClaim` (flock + PID-sentinel, `snapshot_writer.py:78-154`) guards
  snapshot staging; there is no per-scope generation mutex (two concurrent
  POSTs produce v_n and v_n+1 generating in parallel). Restart recovery:
  `initialize() → resume_unfinished()` marks every queued/generating row
  `failed(stage="service_restart")` (`service.py:84-90`); shutdown drains and
  fails rows with `stage="shutdown"`. Failure between disk publish
  (`os.replace`) and `mark_ready` leaves an orphaned snapshot dir + a row that
  restart marks failed — no partial version ever becomes `ready`.
- **Published artifact**: `ReportManifest` (`models.py:175-193`) — strict
  canonical JSON with per-shard `sha256`, `evidence: list[EvidenceSource]`
  (by-value: `evidence_id, task_id, name, image_path, db_paths,
  source_fingerprints`), `source_fingerprints` (SHA-256/size/mtime of each
  source DB frozen at resolve time), `categories`, `directory`, `warnings`,
  `integrity`.
- **API surface** (router `routes/forensic_reports.py`, mounted at `/api/reports`
  in `main.py:205-209`; R1's `report_evidence.router` under the same prefix at
  `main.py:210-214`):

  | Method | Path | Notes / errors |
  |---|---|---|
  | POST | `/api/reports` | 202 `ReportVersion`; 503 unavailable; 404 scope; 501 case scope |
  | GET | `/api/reports` | list versions for scope, `ORDER BY version DESC` |
  | GET | `/api/reports/{id}/status` | 404; returns raw `error` column (see §J P1-4) |
  | GET | `/api/reports/{id}/manifest` | 404/409/500 fixed-string integrity error |
  | GET | `/api/reports/{id}/categories/{cid}/pages/{page}` | 404/409/500; path confinement checks |
  | GET | `/api/reports/{id}/search?q&offset&limit` | 404/409/500; opens FTS `mode=ro` |

- **ServiceManager**: eager creation at startup when the C++ backend is ready,
  then `initialize()` runs restart recovery (`service_manager.py:127-136`);
  lazy re-creation only while lifecycle state is `"new"` (see §G read-side
  mutation). Dependencies: `ReportRepository`, `SourceResolver`,
  `SnapshotWriter`, `build_default_adapters()` → `[SqliteTaskReportAdapter()]`.

### A.2 Chain B — LLM narrative case report (`/api/llm/case-analysis`)

- Route family `routes/case_analysis_endpoints/_case.py` +
  `routes/multi_analysis.py` → `case_analysis/report_generator.py`.
- Job registry is a module-level dict `_analysis_jobs` (`_helpers.py:16`);
  states `running | completed | failed` are **never persisted** — jobs vanish
  on restart. No admission row before LLM work; no concurrency guard
  (repeated POSTs run parallel pipelines over the same `files.db`).
- Output is persisted via `INSERT OR REPLACE INTO case_analysis`
  (`db_utils.py:81-98`) inside the task `files.db` — the previous report is
  overwritten (latest-wins; readers use `ORDER BY updated_at DESC LIMIT 1`,
  `routes/intelligence_report.py:824-826`).
- Frontend consumer: Analysis Center / Intelligence Report Reader
  (`/api/llm/intelligence-report/*`), NOT the `/api/reports` Viewer.

### A.3 Chain C — R1 Report Evidence (`/api/reports/evidence`)

Frozen bindings in per-task `investigation.db` (`report_evidence` optional
v7 extension): identity `(task_id, evidence_key)`, status
`excluded | main | appendix`, optional `analysis_id` triple-checked at write
time (same task / same evidence / status accepted), identity + no-delete
triggers, read side via strict `mode=ro` reader returning exact
`bound_analysis` plus the `newer_accepted_available` hint. Semantics frozen in
`docs/investigation/r1-report-evidence-foundation.md`; unchanged by this phase.

### A.4 Frontend

- `/case-intelligence` (`CaseIntelligence.jsx`) hosts two tabs: the
  Intelligence Report Reader (default, Chain B output) and
  `ForensicReportPage` (Chain A Viewer). Legacy report routes are redirects
  into `/case-intelligence` (`routes.jsx:113-123`).
- Chain A Viewer (`components/reports/`): `ReportToolbar` (version info,
  "生成新版本" gated to task scope; export/history buttons disabled),
  `VersionHistory` (radio over all versions), `ReportWorkspace` (directory
  tree + in-report search + paginated category sections with
  table/key-value renderers), `useReportVersion`/`useReportCategory`/
  `useReportSearch` hooks with stale-response guards and 2 s generating poll.
- Investigation Workbench (`/investigation`) owns the R1
  `ReportEvidenceForm`; **no cross-navigation exists in either direction**
  between the Workbench and the report Viewer (§E.7).

---

## B. Generation Input Today

### B.1 Chain A inputs (per generation)

| Input | Where read | Classification |
|---|---|---|
| Task metadata (`image_path`, `output_files_db`) | `source_resolver.py:55-67` via `cpp_backend.get_task` | Context |
| Task database list | `source_resolver.py:60-61` via `get_task_databases` | Evidence Source pointer |
| Source DB fingerprints (SHA-256/size/mtime) | `source_resolver.py:23-48` at resolve time | Input freeze (files only — see §G.6) |
| `files` table rows (whitelist `name, path, size, extension, category, type, mtime, ctime, is_deleted, md5, scene_type, scene_priority, scene_relevant`) | `adapters/sqlite_task.py:17-21, 76-80`, read-only URI, fallback cap 500 rows | Evidence Source |

NOT read by Chain A: `llm_description`/`llm_summary` columns,
`file_descriptions`, `case_analysis`, and the entire `investigation.db`
(snapshots, secondary analyses, claims, events, graph, `report_evidence`).
`AnalysisChaptersAdapter` (`forensic_report/analysis_adapter.py`, reads
`case_analysis.case_report` read-only) exists but is **not registered** in
`build_default_adapters()` (`sqlite_task.py:190-191`).

### B.2 Chain B inputs (per generation, inside the background job)

| Input | Where read | Classification |
|---|---|---|
| `file_descriptions` rows `WHERE is_relevant = 1` | `report_generator.py:95-117` (single) / `_helpers.py:63-65` (multi) — **re-queried at execution time** ("DYNAMIC AGGREGATION … Always pull the latest", `report_generator.py:78-80`); the caller's list is overridden | Derived LLM finding + **unsafe dynamic dependency** |
| `case_description` from task | `report_generator.py:122-130` | Context |
| Windows artifact descriptions (`windows_artifact_descriptions`) | `_helpers.py:103-141` | Derived LLM finding |
| `events.db` clusters `WHERE llm_summary IS NOT NULL` LIMIT 50 | `_helpers.py:237-254`; **and mutates the DB during generation** via a self-healing `ALTER TABLE` loop (`_helpers.py:226-235`) | Derived LLM finding + unsafe write |
| Graphiti/Neo4j search per chapter | `report_generator.py:296-336` | **Unsafe dynamic dependency** (Base KG) |

There is **no** `get_latest_analysis` / `get_latest_accepted_analysis` / any
analysis-selection code in either report package: Chain B's dynamic inputs are
`file_descriptions`/clusters/graph, not Investigation analyses. The
latest-accepted freeze pattern exists only in the investigation subsystem
(event refresh admission, `investigation/repository.py:2444-2494`).

### B.3 Chain C inputs

`report_evidence` rows joined to the exact bound `analysis_id`
(`graph_reader.py:290-305`). **No generator consumes these rows today.**

---

## C. FinalReportVersion Contract (as implemented today)

- **Identity**: `report_id` (uuid4, PK); per-scope integer `version` with
  `UNIQUE(scope_type, scope_id, version)`. No entity named
  "FinalReportVersion" exists; `ReportVersion` + `ReportManifest` are the
  equivalents.
- **Version allocation**: `SELECT COALESCE(MAX(version),0)+1 …` + INSERT in
  one `BEGIN IMMEDIATE` (`repository.py:52-95`) — collision-free across
  concurrent workers and processes.
- **Immutability**: application-level only. Lifecycle UPDATEs
  (`mark_generating` / `update_progress` / `mark_ready` / `mark_failed`) are
  guarded by `_assert_mutable` + `status NOT IN ('ready','failed')` WHERE +
  rowcount checks (`repository.py:97-177`); terminal rows reject further
  mutation and there is no DELETE. **No DB triggers** back this — contrast
  with `investigation.db` where R1/C7 use `RAISE(ABORT)` triggers. Disk side
  is stronger: `SnapshotWriter` refuses any existing final dir three times and
  publishes via atomic `os.replace` under a flock claim
  (`snapshot_writer.py:185-275`).
- **State machine**: `queued → generating → ready | failed`; `stage` and
  `progress` (1-99) tracked; `error` free text on failure.
- **Task scoping**: via `(scope_type='task', scope_id=task_id)`; read routes
  (`/status`, `/manifest`, pages, search) fetch by global `report_id` with
  **no task-scope re-validation** (see §J P1-5).
- **Admission freeze**: source DB *fingerprints* are frozen at resolve time
  into the manifest, but the admission row records **no input set, no
  canonical serialization, no input_hash, no prompt version**; the adapter
  re-reads `files.db` content later at write time with no post-write
  fingerprint re-verification (see §G.6 TOCTOU).
- **History behavior**: generating V2 leaves V1's snapshot dir and manifest
  untouched (separate `report_id` dirs; overwrite refused). The DB row for V1
  is terminal-immutable. So V1 content is effectively frozen — *given* it
  reached `ready` (the row content itself has no hash chain; the manifest
  carries shard hashes only).

**Verdict: PARTIALLY IMMUTABLE** — bytes on disk are immutable and
version-numbered; the metadata row is terminal-immutable only by application
discipline; admission inputs are not persisted at all.

---

## D. Citation Manifest

**Does not exist.** No table, model, builder, or test mentions citations
(`grep -ri citation` over `python_service/` and `web/src`: zero source
matches). The two nearest structures, field by field:

### D.1 `AnalysisReference` (`forensic_report/models.py:67-69`)

```python
class AnalysisReference(BaseModel):
    chapter: str   # free-text chapter name
    token: str     # free-text token
```

Attached to every `ReportRecord.analysis_references: list[AnalysisReference]`.
It carries **no `evidence_key`, no `analysis_id`, no `claim_id`, no exact
refs**. The only registered adapter never populates it; the writer merely
counts it (`snapshot_writer.py:349`); the frontend renders it as a static
"被 {chapter} 引用" badge with no interaction (`RecordBadges.jsx:34-41`).
→ Dead contract field; a natural extension point but semantically empty today.

### D.2 Chain B inline Markdown tokens (`prompts.py:306-307`)

`[[file:路径]]` and `[[event:TYPE@window/dir]]` embedded in chapter Markdown.
No separate manifest; no IDs; enforcement is a prompt instruction only
("严禁虚构不存在的文件路径或事件", `report_generator.py:386`); **no
post-generation validation** that emitted tokens exist in the generation
input. Frontend resolution is regex + fuzzy path matching (exact →
normalized → tail-suffix tiers, `AnalysisCenter.jsx:443-457`); a miss is only
a toast. In the newer reader the click handler is a literal no-op
(`ReportReaderContent.jsx:102 scrollToFile: () => {}`).

### D.3 Chain A `manifest.json`

A **data** manifest (schema_version, evidence sources, category indexes, page
paths, shard hashes, fingerprints, warnings) — not a citation manifest. It
does provide the exact-ID pagination contract (`category_id` + page +
`record_id`) that the Viewer's search-hit navigation already uses.

**All ten §E questions**: no citation identity; no evidence_key/analysis_id/
claim_id; no exact refs; no exact-ID viewer lookup for citations; no
Markdown→manifest parsing; no latest/current fallback (nothing to fall back
from); nothing prevents citing evidence outside the generation input
(prompt-only in Chain B). **Every item is GAP.**

---

## E. Viewer Contract (Chain A Viewer, current)

- **Version selection**: list-then-select; default = highest `ready` version
  (`latestReady`, `useReportVersion.js:15-19, 240`), fall back to first row;
  user can select any historical version via `VersionHistory` radio
  (state-only; no URL param/bookmark). Selection preserved across polls;
  `queued`/`generating` polled at 2 s. Duplicate create guarded client-side.
- **Data contract**: `ReportVersion` fields, `manifest` (guard
  `schema_version === '1.0'` and `manifest.report_id === selected.report_id`),
  `categories[{category_id, renderer, page_size, pages, …}]`, page shards
  `{records[], sha256}`, search `{total, hits[]}` with exact
  `(category_id, page, record_id)` navigation and `scrollIntoView`.
- **Citation interaction**: none (§D). Exact-ID traceback (claim → analysis →
  evidence) exists **only** in the Investigation Workbench `DetailPanel`
  (`onSelectClaim(claim_id, analysis_id)`, `onSelectAnalysis`, …) with no
  entry point from the Viewer, and vice versa.
- **Missing-data behavior**: per-state banners (尚未生成 / 不兼容 / stage·progress /
  失败+error), category load error alerts, silent no-op scroll for absent
  records, search failure clears hits. Toolbar "导出离线 HTML"/"版本历史"
  disabled; `reportDataSource.getPreviewUrl`/`getOfflineBundleUrl` build URLs
  for backend routes that **do not exist** (dead code).
- **Reuse verdict**: version-selection skeleton, status lifecycle, category
  rendering, and stale-guard hooks are **Direct reuse** for R2d; citation
  traceback UI and any Workbench cross-link are **Must add**.

---

## F. R1 Integration Gaps (target contract vs today)

Target contract (plan §4) item-by-item:

| Contract item | Status | Evidence |
|---|---|---|
| `task_id` at admission | CURRENT (as `scope_id`) | `report_versions.scope_id` |
| main Report Evidence[] / appendix Report Evidence[] as generation input | **GAP** | Chain A never reads `report_evidence`; R1 rows have no consumer |
| per-evidence `{evidence_key, report_status, bound analysis_id \| NULL}` frozen at admission | **GAP** | No admission persistence of any input set |
| exact Evidence Snapshot projection in input | **GAP** | Chain A reads `files` table only; snapshots live in `investigation.db`, unread |
| exact accepted Analysis + exact Claims + `claim_evidence_refs` when bound | **GAP** | Present in `investigation.db` (`graph_reader` projections), never read by any generator |
| report prompt version recorded | **GAP** | Only `generator_version` ("1.0.0") in manifest; nothing at admission |
| generation parameters recorded | **GAP** | none |
| canonical input serialization | **GAP** | none (investigation event refresh has the pattern: `canonical_json` + envelope) |
| `input_hash` | **GAP** | none (pattern exists at `investigation/repository.py:2481-2494`) |
| worker consumes frozen input only | **GAP** | No LLM worker in Chain A; Chain B is explicitly dynamic (§B.2) — must not be extended |
| T1 (bind A1 → admit V1 → A2 accepted/rebound → V1 still A1) | **GAP** (no mechanism, no test) | — |
| T2 (set A+B → admit V1 → B excluded, C main → V1 still A+B) | **GAP** (no mechanism, no test) | — |

**Original Evidence only (plan §5)**: today no generator either supports or
violates it — `analysis_id = NULL` rows simply have no consumer. Nothing in
either report chain auto-discovers latest accepted analyses (confirmed by
grep), so no *existing* anti-pattern needs removing; R2 must implement the
distinction (Evidence Snapshot = source; accepted Analysis = derived finding).

**Citation boundary (plan §6)**: `allowed_report_evidence_ids` does not exist;
Chain B's prompt-only "no fabrication" rule is the entire boundary. The
Claim-refs-[A,B]-but-B-not-in-report scenario is unhandled anywhere. **GAP.**

**Event / Graph as generation source (plan §7)**: R1-side answer is clean —
Chain A reads neither. Chain B *does* depend on `events.db` cluster
`llm_summary` (Timeline Cluster, derived LLM finding) and per-chapter
Graphiti/Base-KG search. R2's new generation path must not adopt these
dependencies; Chain B is left untouched (do not silently delete, do not
extend). Base KG entities remain NOT SAFE TO MERGE with Investigation
Evidence (C8a finding, unchanged).

**Structured output (plan §8)**: Chain B = free Markdown chapters (no parser;
retry-once on empty chapter); Chain A = strict JSON shards. No structured LLM
report contract exists. **Auditability gap** — record and design in R2c; do
not build a parser in R2a.

---

## G. Provenance Risks (required judgments)

1. **Latest-accepted dependency**: ABSENT in report packages (good). Chain
   B's dynamic re-read of `file_descriptions`/clusters/graph at execution
   time is the same class of risk under a different name — BLOCKER-by-design
   for reuse, recorded, not fixed here.
2. **Dynamic report evidence**: no report_evidence consumer exists yet, so no
   dynamic re-selection occurs. GAP, not violation.
3. **Markdown citation parsing**: present in Chain B + Intelligence Reader
   (regex token split, fuzzy path match, no-op `scrollToFile` in the new
   reader). Auditability gap — P1-6; R2 replaces this pattern with exact-ID
   citations on the new chain; Chain B left as-is.
4. **Cross-task identity**: `reports.db` is global; read routes fetch by
   global `report_id` without task-scope re-validation (P1-5). Chain C and
   investigation stores are per-task isolated (C10 §18) — no mixing occurs in
   persistence; the exposure is read-route authorization only.
5. **Evidence Source confusion**: Chain A's `EvidenceSource` manifest entry is
   metadata about a task DB (by-value, fingerprinted) — cannot be confused
   with LLM output. Chain B embeds LLM-derived descriptions as if they were
   evidence narrative — acceptable only because it is a legacy display chain;
   R2 must keep Evidence Snapshot vs accepted Analysis vs generated narrative
   as distinct contract layers (plan §5).
6. **Read-side mutation**: Chain A GETs are effectively clean — manifest/page
   are pure file reads with confinement checks; search opens `mode=ro` and
   provably does not mutate (`test_search_index.py:45`). Residual risks:
   (a) `ReportRepository.__init__` (mkdir + DDL) is reachable from GETs via
   the lazy `"new"`-state window of `forensic_report_service`
   (`service_manager.py:370-381`) — practically closed in the serving app
   because lifespan awaits `initialize()` before serving, but structurally
   present; (b) status/list reads use read-write connections (no writes
   issued). **TOCTOU note**: source fingerprints are frozen at resolve time,
   but the adapter re-reads DB *content* later during write with no
   re-verification — a source DB mutated between resolve and write yields a
   report whose manifest fingerprints do not match its content (P1-7). Chain
   B additionally *writes* to the evidence DB during generation
   (`ensure_file_descriptions_schema`, ALTER TABLE loop) — P1-2, do not
   import this pattern into R2.

---

## H. Reuse Matrix

| Verdict | Items |
|---|---|
| **Direct reuse** | `ReportRepository` version allocation (`BEGIN IMMEDIATE`) + state machine + restart recovery; `SnapshotWriter` claim/atomic-publish/immutability; `manifest.json` canonical-JSON + shard sha256 contract; strict fixed-string route error style; `SnapshotSearchIndex.open_readonly`; R1 `report_evidence` + `graph_reader` projections (exact bound analysis, claims); C7c-1 frozen-envelope + `input_hash` + `canonical_json` pattern; C5b structured-LLM parser discipline; LLM transport (`llm_service`/`file_analyzer` timeout mapping); frontend `useReportVersion`/`VersionHistory`/`ForensicReportPage` skeleton + stale-guard hooks |
| **Adapter (small modification)** | `SourceResolver` (admission must additionally assemble R1 report-evidence inputs); `ReportRecord.analysis_references` (upgrade `AnalysisReference` to exact IDs or supersede with a citation manifest); `ForensicReportService.start` admission (build + persist frozen input before worker) |
| **Must add** | Frozen generation admission record (input set + canonical serialization + `input_hash` + prompt version); narrative LLM executor consuming the frozen envelope only; citation manifest with exact IDs + admission-boundary validation (`allowed_report_evidence_ids`); Viewer narrative tab + citation traceback (exact-ID links into Workbench data); T1/T2 frozen-input tests |
| **Do not touch** | Chain B `case_analysis` legacy pipeline (recorded, not extended, not deleted); Investigation write state machines; Base KG / Graphiti; C++ (no report API callers found); existing KnowledgeGraph page; R1 frozen binding semantics |

---

## I. Recommended R2 Implementation Split

The planned split fits the repository with one refinement — keep each slice
independently verifiable and keep the first LLM call out of R2b:

- **R2b — Frozen Generation Admission & Persistence.** Extend Chain A
  admission: resolve R1 `report_evidence` (main/appendix + exact bound
  `analysis_id`), assemble the frozen input (exact Evidence Snapshot
  projections; exact accepted Analysis + Claims + `claim_evidence_refs` when
  bound), serialize canonically, persist admission input + `input_hash` +
  prompt version in `reports.db`, all before any worker starts; worker
  contract = envelope-only. Also fixes the R1 route-cardinality test (§J
  P1-1) as its first commit. No LLM.
- **R2c — Generation Execution & Citation Validation.** LLM narrative
  generation from the frozen envelope only; structured output contract
  (reuse C5b-style parser); citation manifest built and **validated against
  `allowed_report_evidence_ids`** (claims may retain historical refs to
  non-report evidence, but citations may not); immutable publish through the
  existing SnapshotWriter/ReportRepository path; restart/shutdown recovery
  reuse; fixed-string errors.
- **R2d — Viewer / Frontend Integration.** Narrative tab + exact-ID citation
  traceback in the Chain A Viewer (version-selected, historical), "newer
  accepted available" surfaces, entry points between Workbench and Viewer.

Open design decisions for the R2b plan (not decided here): admission record
shape (new `reports.db` columns vs side table vs envelope file in the
snapshot staging area); whether `excluded` rows are recorded in the envelope
for audit; narrative storage (new category/shard kind vs separate document).

**G-option answer (plan §3G)**: closest to **B** — the version/immutability
system and the Viewer are reusable as-is — **plus the citation system of C**:
a citation manifest and its persistence do not exist and must be added. The
generation engine itself (Chain A) needs an input adapter + admission freeze,
not a rebuild. **D is rejected**: nothing blocks safe expression of frozen
provenance.

**Enter R2b now? YES.** No P0; P1s are either additive (input freeze,
citations, test) or live entirely in Chain B which R2 does not extend.

---

## J. Findings Severity

**P0 — none.** (No evidence-integrity, cross-task persistence, or history
corruption issue found in the chains R2 will build on.)

**P1**

1. **R1 regression at HEAD**: `tests/unit/forensic_report/test_routes.py:357-361`
   asserts the exact `/api/reports` route set; R1's three `/api/reports/evidence`
   routes fail it. Missed because the file is outside the `investigation`
   profile's path set (`scripts/test.py INVESTIGATION_PATHS`). Fix = add the
   three routes to `expected_report_routes` — first commit of R2b. (Found and
   confirmed in this phase: 1 failed, 23 passed in that file at HEAD.)
2. **Chain B mutates evidence DBs during generation** — `ensure_file_descriptions_schema`
   + `ALTER TABLE events` self-healing loop (`_helpers.py:226-235`,
   `report_generator.py:98-99`). Do not import into R2; leave Chain B as-is.
3. **Chain B error leaks** — `detail=str(e)` / `detail=r.text` on 500s
   (provider URLs, internal exceptions) and failure text embedded into report
   bodies; jobs in-memory only; result `INSERT OR REPLACE` overwrites history.
   Classification only; fixing Chain B is out of R2 scope.
4. **`ReportVersion.error` returned raw to HTTP** via `GET /{id}/status` —
   can contain filesystem paths (`FileExistsError(f"immutable report already
   exists: {final_dir}")`, source-changed fingerprints). C10 §15-style leak on
   the new chain's surface — fold sanitization into R2b when the admission
   row's error semantics are defined.
5. **Report read routes lack task-scope validation** — global `report_id`
   lookups; a known/guessed `report_id` from another task renders its content.
   Add scope checks when R2b/R2d touch these routes; deployment exposure
   itself remains a Phase D item.
6. **Citation auditability gap** — no manifest; free-text `AnalysisReference`
   never populated; Markdown tokens resolved fuzzily; prompt-only fabrication
   guard (§D). Core R2c work item.
7. **Admission-input TOCTOU** — fingerprints frozen at resolve, content read
   later without re-verification (§G.6); plus no admission record at all
   (no input_hash/prompt version). Core R2b work item.

**P2**

- Lazy `"new"`-state GET-reachable construction of `ReportRepository`
  (mkdir+DDL) and read-write connections on status/list reads (§G.6) —
  practically closed in serving; tighten opportunistically.
- `offline_bundle_path` column never written; `getPreviewUrl` /
  `getOfflineBundleUrl` target nonexistent routes; toolbar export/history
  disabled — dead surface, keep frozen until R2d decides.
- Search endpoint 404/409 branches untested; two snapshot-writer tests spawn
  real `multiprocessing` children with 10-15 s joins and carry **no marker**
  (run in every `fast`).
- No URL/bookmark for a selected report version.

**Debt**

- `AnalysisChaptersAdapter` registered nowhere; `case_analysis`-latest reader
  (`ORDER BY updated_at DESC`) on the legacy chain; legacy redirect routes.

---

## K. Test Inventory (report system) & what R2a ran

**R2a executed** (policy-compliant, no full):

- `pytest tests/unit/forensic_report tests/unit/investigation/test_report_evidence_routes.py tests/unit/test_service_manager_report_lifecycle.py --collect-only -q`
  → **96 tests collected**.
- `pytest tests/unit/forensic_report/test_routes.py tests/unit/investigation/test_report_evidence_routes.py -q`
  → **1 failed (P1-1 above), 23 passed, 0.96 s**.

Coverage snapshot (details in the four investigation streams):

- **Solid**: repository version allocation/immutability
  (`test_repository.py`), snapshot writer claim/publish/rollback including
  cross-process cases (`test_snapshot_writer.py`), service lifecycle +
  restart/shutdown recovery (`test_service.py`), resolver fingerprint
  freezing (`test_source_resolver.py`), route error mapping incl. no-leak
  asserts (`test_routes.py`), R1 binding matrix
  (`test_investigation_report_evidence.py`, 26), frontend viewer hooks/page
  (`useReportVersion` 18 tests, workspace, renderers).
- **Missing for R2** (must-add, mirrors §F): no frozen-input test
  (admission snapshot vs later mutation — neither Chain A content-freeze nor
  T1/T2 scenarios); no citation tests (nothing exists to test); no
  mutate-then-generate-V2-assert-V1-byte-identical test; page `sha256` never
  verified on a read path; search 404/409 branches.
- **Reusable fixtures/fakes**: `FakeAdapter`/`PartialFailureAdapter` family +
  `write_snapshot` helper; `FakeReportService` + `make_client`
  (dependency_overrides); `_resolved_task()`/`_service()` service helpers;
  R1's `_repo_with_evidence`/`_analysis_at`; frontend `deferred` promise
  patterns.
- **Cost**: report suites are cheap (no LLM/network/sleeps); heaviest are the
  two unmarked real-`multiprocessing` writer tests (P2) and
  `test_intelligence_report_routes.py` (4 full-app fixtures, legacy chain).

**Full regression: DEFERRED — not required for R2a** (per plan §10; next
required full gate after the R2 main chain closes).

---

## L. Added / Modified / Reused / Do Not Touch (recommendations for R2)

- **Added (candidates)**: frozen generation admission record (input set +
  canonical serialization + `input_hash` + prompt version) in `reports.db`;
  narrative generation module (envelope-only input) in `services/forensic_report/`;
  citation manifest (exact IDs) + `allowed_report_evidence_ids` validation;
  Viewer narrative/traceback components; T1/T2 + citation + V1-immutability
  tests.
- **Modified (minimal)**: `ForensicReportService.start`/`_resolve` (admission
  assembly); `SourceResolver` (report-evidence input resolution); route set
  for generation + admission reads; `AnalysisReference` or its successor;
  `tests/unit/forensic_report/test_routes.py` route-set assertion (P1-1 fix);
  error sanitization on the new surfaces (P1-4/5).
- **Reused**: report engine version/immutability/publish machinery
  (`ReportRepository`, `SnapshotWriter`), FinalReportVersion-equivalent
  (`ReportVersion`/`ReportManifest`), Viewer skeleton (`ForensicReportPage`,
  `useReportVersion`, `VersionHistory`), LLM transport, strict parser
  discipline (C5b pattern), frozen-envelope pattern (C7c-1), provenance
  readers (`graph_reader` exact-ID projections).
- **Do Not Touch**: Investigation write state machines; Base KG / Graphiti;
  C++ (zero report callers verified); existing KnowledgeGraph; R1 frozen
  binding semantics; Chain B `case_analysis` legacy pipeline (recorded,
  neither extended nor deleted).
