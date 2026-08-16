# Phase R2c — Report Generation Execution & Citation Validation

- Date: 2026-08-16
- Baseline: Dev @ `1ed670d` + `131e021` (R2b), on top of R2a `91682eb`,
  R1 `ffdacba`, Security Preflight `d83c1f7`, C10 `eb05322`
- Scope: execute admitted frozen generations end-to-end — LLM consumes only
  the persisted envelope, strict structured output, three-layer citation
  validation, immutable publication with the citation manifest, restart/
  shutdown recovery, and the exact-ID public API. **No frontend** (R2d).

## 1. Added / Modified / Reused

**Added**

- `forensic_report/generation_prompts.py` — prompt registry
  (`final-report:v1` → system/user templates), envelope-compat map
  (`{1: {final-report:v1}}`), prompt → output-contract map
  (`structured_final_report_v1`), and the user-prompt builder (the prompt
  IS the persisted envelope, serialized canonically — nothing else).
- `forensic_report/generation_structured.py` — strict parser
  (`StructuredReportOutputError`) mirroring the C7c-2/C5b primitive:
  duplicate-key/constant rejection, top-level object required,
  frozen `extra="forbid"` models. No repair, no regex, no fallback.
- `forensic_report/generation_writer.py` — `GenerationReportWriter`:
  staging → immutability re-check → atomic `os.replace` publication of ONE
  canonical `manifest.json` (sections + citation manifest together), plus a
  confinement-checked strict manifest reader. Fresh uuid4 `report_id` per
  publication and no retries, so no cross-process claim is needed (unlike
  the A-chain adapter writer).
- `forensic_report/generation_execution.py` —
  `ReportGenerationExecutor` (independent; only mirrors
  Secondary/EventRefresh executor patterns),
  `validate_report_citations` / `build_citation_manifest`, the error
  classifier, and `read_generation_strict` (mode=ro + query_only exact-ID
  generation read for the GET route).
- `routes/report_generation.py` — `POST /api/reports/generate` (202) and
  `GET /api/reports/generations/{generation_id}?task_id=` (exact-ID poll).
- Tests: `tests/unit/forensic_report/test_generation_execution.py` (37),
  `tests/unit/forensic_report/test_report_generation_routes.py` (6).

**Modified**

- `forensic_report/models.py` — `StructuredReportCitation/Section/Response`
  (strict output contract with cross-field citation-reference validation),
  `CitationManifestEntry`, `GenerationReportManifest`, and the
  `ReportGenerationInput` row model extended with the execution columns.
- `forensic_report/repository.py` — additive execution columns (inline for
  fresh stores + `ALTER` migration for R2b-era stores), four state-machine
  triggers, and `claim_generation` / `fail_generation` /
  `complete_generation_publication` / `list_stale_generations`.
- `service_manager.py` — `report_generation_executor` slot: field, ready
  flag, factory (repository + writer + LLM, LLM may be None), eager init
  with restart recovery, shutdown/rollback cleanup entries, `_clear_services`.
- `main.py` — router mounted under `/api/reports`.
- `tests/unit/forensic_report/test_routes.py` — the two new routes join the
  exact route-contract set.

**Reused (zero changes to their semantics)**

- A-chain publication discipline (staging + `os.replace` + immutable final
  dir), `report_versions` version allocation (`BEGIN IMMEDIATE MAX+1`),
  `SnapshotWriter._canonical_json`, `safe_segment`.
- `LLMService.chat_completion` transport (底层) with the C7c-2 error
  classification (timeout/connect/http → llm_* codes).
- C5b/C7c-2 strict-parse primitive pattern; `canonical_json` + SHA-256 +
  `hmac.compare_digest` verification.
- R2b admission stack unchanged.

**Do Not Touch (and untouched)**

- `/api/llm/case-analysis` legacy Chain B: zero changes, zero calls, its
  table/prompts/markdown tokens/dynamic aggregation all unused.
- Investigation executors/state machines, Event refresh, Graphiti/Neo4j,
  KnowledgeGraph, Viewer, C++, R1 binding semantics.

## 2. Generation state machine

R2b's `admitted` is the queued state (naming follows the R2b schema; no
value migration needed — historical rows stay queueable, locked by test):

```
admitted ──> running ──> completed | failed
   └──────────────────> failed          (scheduling / restart)
completed | failed = terminal
```

DB triggers enforce: legal transitions only, terminal immutability (any
execution-column change on a terminal row aborts), completed requires
report_id + produced_version + model + completed_at, failed requires
failed_at and must NOT reference a published version, plus the R2b
frozen-input trigger (identity/envelope/hash immutable) and no-delete.

Execution columns (all nullable, added additively): `produced_version`,
`model`, `started_at`, `completed_at`, `failed_at`, `error_code`,
`error_message` (`report_id` existed since R2b).

## 3. Exact public API

- `POST /api/reports/generate` — body `{task_id, requested_by}` only
  (`extra="forbid"`; evidence lists / analysis IDs / citations / prompt
  version / model / envelope submissions are 422). Admits via the R2b
  service (server builds everything from R1 bindings), schedules the
  executor, returns 202 with the row. Errors: 404 task not found; 409
  `task has no report evidence` / `report evidence binding is invalid`;
  503 store/service unavailable.
- `GET /api/reports/generations/{generation_id}?task_id=` — exact-ID poll
  (no latest fallback), strict read (`read_generation_strict`: mode=ro +
  query_only, missing store/table → 404, corruption → 503; never creates or
  migrates the DB — the C10 lesson applied to the new endpoint). Wrong
  task scope → opaque 404. Completed rows embed the published `report`
  manifest (confinement-checked file read); a missing manifest for a
  completed row is a fixed-string 503.

## 4. Prompt / output contract

`final-report:v1` (the R2b-frozen identity, unchanged — existing admitted
rows keep executing): the system prompt states the provenance semantics
(Evidence Snapshot = authoritative source; accepted Analysis = derived
finding; claim refs = historical provenance that never widens the citation
boundary; report evidence set = the selected universe; inventing IDs,
citing unselected evidence, treating analyses/events/graph as evidence,
and emitting review decisions are all forbidden) and the strict JSON
contract. The user prompt is the persisted envelope verbatim (canonically
serialized) — locked by a test asserting the LLM received exactly the
envelope bytes even after a post-admission rebind + evidence addition.

Output contract `structured_final_report_v1`:
`{title, sections[{heading, content, citation_ids}], citations[
{citation_id, evidence_key, analysis_id|null, claim_id|null}]}` — frozen,
`extra="forbid"`, at least one section, no duplicate citation IDs, sections
may only reference known citation IDs. Parser rejections (all →
`structured_output_invalid`): fences, embedded JSON, duplicate keys,
NaN/Infinity, top-level non-object, extra fields, empty required fields,
unknown citation references.

## 5. Citation manifest schema

Published inside `GenerationReportManifest` (one canonical JSON artifact
with the narrative — a body can never exist without its manifest):

```
{schema_version:"1.0", report_kind:"llm_generation", report_id,
 scope_type:"task", scope_id, task_id, generation_id, title,
 prompt_version, input_hash, model, generated_at,
 sections:[{heading, content, citation_ids}],
 citations:[{citation_id, evidence_key, analysis_id|null, claim_id|null,
             evidence_captured_at, analysis_version|null, claim_type|null}]}
```

The report `version` is deliberately absent — version identity is owned by
the `report_versions` row allocated in the publication transaction (R2b
Option B). Entries carry exact persisted identity plus copied frozen
provenance metadata only; no narrative payload duplication. The Viewer
(R2d) reads this and never re-derives provenance.

## 6. Citation validation rules (envelope-only, no live lookups)

For every emitted citation, against the persisted envelope:

1. `evidence_key ∈ allowed_report_evidence_ids` — the report boundary,
   narrower than the task; "exists in the task" is NOT sufficient.
2. `analysis_id`: null, or exactly the item's frozen
   `bound_analysis.analysis_id` — never a newer accepted, review_pending,
   rejected, foreign-evidence, or any other task analysis; original-only
   evidence must be cited with null.
3. `claim_id`: null, or requires (2) non-null AND the claim_id persisted
   inside that frozen analysis — exact identity, never matched by
   `claim_text` (same-text different-ID stays distinct, locked by test).

Claim external refs stay visible as provenance but never widen the
boundary: citing B when the claim refs [A,B] but only A is report evidence
→ `citation_invalid` (whole generation fails closed).

## 7. Publication atomicity & version allocation

Flow: LLM → strict parse → citation validation → build manifest →
staging write → atomic `os.replace` publish → ONE `BEGIN IMMEDIATE`
transaction allocating the next per-scope version (A-chain `MAX+1` reuse),
inserting the ready `report_versions` row, and completing the generation
with report_id/produced_version/model. Consequences:

- A version becomes visible only together with its published manifest;
- a crash between publish and commit leaves at most an invisible orphan
  directory (no `report_versions` row) that recovery fails closed;
- allocation/snapshot/metadata can never be half-visible ("completed but
  Viewer can't open"), locked by failure-injection tests (writer failure,
  completion-transaction failure).

`model` is execution audit metadata: persisted on completed (required
non-null) and retained on parser/citation failures when the transport
already reported it; it never enters `input_hash`.

## 8. Worker claim, recovery, shutdown

- Claim: `BEGIN IMMEDIATE`, exact `generation_id`, `admitted → running` +
  `started_at`; the loser gets `None`, calls no LLM, writes no failure
  (dual-worker LLM-exactly-once locked by test).
- Restart recovery (`initialize`): all admitted/running →
  `failed(service_restart)`, no auto replay (unpredictable duplicate LLM
  output); queued-but-never-scheduled rows fail the same way.
- Shutdown: accepting flag, cancel + drain tracked workers (CancelledError
  handler durably fails `service_shutdown`), sweep for stragglers;
  publication runs as an un-cancellable thread step, so a cancellation
  there leaves at worst the same invisible-orphan window as a crash.
- Scheduling: admission persists first, then the task is created; any
  scheduling failure (including shutdown races) terminalizes the row
  `execution_schedule_failed` — no orphan queued rows.

## 9. Error codes (fixed-string messages; traceback only in server logs)

`execution_schedule_failed`, `service_restart`, `service_shutdown`,
`input_integrity_error`, `unsupported_input_contract`, `llm_unavailable`,
`llm_timeout`, `llm_connection_error`, `llm_http_error`,
`llm_empty_response`, `structured_output_invalid`, `citation_invalid`,
`publication_error`, `execution_error`. No DB paths, provider URLs,
tokens, or staging paths reach the row or HTTP responses.

## 10. Tests

`test_generation_execution.py` (37) — §25: happy path (completed, version
ready, manifest with exact IDs + provenance enrichment), LLM timeout (no
version, no snapshot), dual claim (LLM once), hash mismatch
(`input_integrity_error`, no version), unknown prompt contract, empty LLM
response (model audit kept), LLM unavailable, frozen-input prompt equality
across post-admission rebind + evidence addition, original-only
(`"bound_analysis":null` in the LLM input), strict-parser rejection matrix
(9 malformed shapes) + executor mapping; §26: all ten citation cases
(boundary/unselected/original-only+analysis/newer-A2/claim-without-
analysis/exact-ID-not-text/external-ref-no-widen/unknown-claim/pass/
manifest-identity); §27: old versions unchanged + concurrent completions
unique versions, post-publish completion failure invisible, writer failure
`publication_error` with zero versions; §28: restart recovery (stale
failed, terminal untouched), shutdown fails running, scheduling failure no
orphans; plus state-machine trigger guards and R2b-legacy-row additive
migration.

`test_report_generation_routes.py` (6) — 202 admit+submit exact ID,
client-controlled field rejection (422 × 5), error mapping
(409/404/503 fixed strings), exact-ID + task-scope GET, completed embeds
manifest, missing manifest → 503.

Lifecycle-test hermeticity note: the manager lifecycle tests fake the
forensic-report factory; R2c adds the report-generation executor factory to
the same `_patched_services` patch (a silent fake — the manager drain/
deadlock assertions must not depend on real durable DDL, which under disk
latency spikes pushed the gated 1s drain budget over — the file went from
intermittently 125-220s/failing to a stable ~4s). Production-side, the
executor factory also moved off the event loop (`asyncio.to_thread`) since
it performs durable DDL. The executor's own lifecycle is covered by its
dedicated tests above.

Freeze regression: forensic_report suite (incl. R2b admission + updated
route contract) + R1 evidence + strict reads + ServiceManager lifecycle =
**233 passed**. Fast/Full: DEFERRED BY POLICY (next required full gate
after R2d closes the Viewer loop).

## 11. R2d remaining scope

- Frontend: Generate Report action (POST + exact-generation polling hook),
  generation status/progress surface, published report view (title/
  sections from the manifest), citation click → exact traceback
  (manifest entry → evidence snapshot / frozen analysis / exact claim)，
  Workbench ↔ report cross-entry points, "newer accepted available" hints.
- Any Markdown rendering happens client-side from the structured sections
  (server-side deterministic rendering only if a document export is added).
- Optional: generation list view; PDF/DOCX export (explicitly NOT in R2c).
