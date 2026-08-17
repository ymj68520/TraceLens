# R3 — Report End-to-End Review & R2 Closeout

Baseline: R1 `ffdacba` → R2a `91682eb` → R2b `131e021` → R2c `1bfd852` →
R2d `9fb8c22` (R2-E1~E13 all PASS; milestone Full Gate green: frontend 198,
python investigation 415 / fast 1015 / full 1064). R3 is audit + acceptance +
minimal repair only: no new product features, no re-design, no automatic Full
re-run.

Audit method: every claim below was verified against the current tree by
code reading plus targeted grep (identity heuristics, Chain B references,
Evidence-Source wording, write sites of `ReportVersion.error`) and backed by
the existing focused test suites; one confirmed P1 received a minimal fix
with a new regression test (§9).

## 1. Final architecture

Three report chains, deliberately still separate:

- **Chain A — deterministic forensic snapshot** (`/api/reports`, no LLM):
  global `reports.db` (`report_versions` keyed by scope_type/scope_id, no
  task_id column), category/page artifacts, search index. Untouched by R3
  except one sanitized failure message (§9).
- **Chain B — legacy LLM case analysis** (`/api/llm/case-analysis`):
  isolated legacy surface, zero references from the R2 chain (§8).
- **Chain R2 — frozen narrative generation** (R1+R2b+R2c+R2d):
  Report Evidence in the per-task `investigation.db` → frozen envelope
  admission in `reports.db` → LLM execution → validated citations →
  atomic manifest publication → immutable `report_versions` ready row
  (`report_kind='llm_generation'`) → task-scoped strict narrative read →
  Viewer with exact citation traceback.

Narrative versions and deterministic snapshots share one version sequence
per task scope and one `reports.db`; the additive `report_kind` column
(NULL = deterministic, `'llm_generation'` = R2c) distinguishes them
server-side — no filename heuristics anywhere.

## 2. Evidence → Report provenance chain

The §3 acceptance chain (A: snapshot + accepted A1 + C1 as **main**; B:
**appendix**, original-only; G1→V1; then A2 accepted + rebind; G2→V2) is
enforced end-to-end:

- **Admission** (`generation.py`): one read transaction over the v7
  investigation store (mode=ro + query_only) assembles the envelope from
  `report_evidence` rows; `excluded` rows are skipped (audit state, never
  input); `allowed_report_evidence_ids` = main+appendix keys only.
- **Original-only** (§3/R3-E2): `analysis_id IS NULL` → `bound=None`; the
  item never gains an analysis, and `validate_report_citations` rejects any
  citation that attaches `analysis_id`/`claim_id` to it
  (`test_citation_analysis_on_original_only_is_invalid`,
  `test_original_only_envelope_has_null_binding`).
- **Exact analysis/claim identity** (R3-E3/E4): citations must equal the
  frozen `bound_analysis.analysis_id`; `claim_id` must be a member of that
  frozen analysis's claims — never text matching
  (`test_citation_claim_matched_by_exact_id_not_text`,
  `test_citation_of_newer_accepted_analysis_is_invalid`).
- **V1 immutability across rebind** (R3-E6): the envelope is frozen bytes
  (input_hash verified with `hmac.compare_digest` before the LLM runs);
  `test_old_versions_unchanged_and_versions_unique` plus the R2d page-level
  integration test prove V1 keeps A1/C1 after A2 is accepted/rebound and
  V2 alone carries A2.
- **Claim external refs** (R3-E5): a claim's `evidence_refs=[A, X]` is
  preserved verbatim as historical claim provenance inside the envelope,
  but citation candidates are only `allowed_report_evidence_ids`; X never
  becomes a citation candidate and the Viewer never renders X as Report
  Evidence (`test_claim_external_ref_does_not_widen_citation_boundary`).

## 3. Report state/version model

- Deterministic: queued → generating → ready/failed (immutable once
  terminal; `_assert_mutable`).
- Narrative: generation row admitted → running → completed/failed
  (`fail_generation` guards `status IN ('admitted','running')`);
  the version row is created **only** inside the successful publication
  transaction, directly as `ready` + `report_kind='llm_generation'`.
  Failed generations never leave a Viewer-visible version (R2C6).
- Version allocation is `MAX(version)+1` under `BEGIN IMMEDIATE` in both
  chains; restart recovery fail-closes stale admitted/running generations
  (`service_restart`) without auto-replay.

## 4. Citation authority model

The **persisted citation manifest is the only provenance authority**:
`CitationManifestEntry` carries `citation_id`, `evidence_key`,
`analysis_id`, `claim_id`, `evidence_captured_at`, `analysis_version`,
`claim_type` — identity and audit metadata only. The Viewer resolves a
click by `citation_id` → exact manifest lookup (no regex/Markdown/path
derivation). Layer labels state the epistemic rank explicitly: only the
canonical evidence layer is labeled **Evidence Source**; Accepted Analysis
is "analyst-accepted derived finding"; Claim is "derived claim" (§5 audit —
no Graph Entity / Investigation Event / Timeline Cluster wording appears
anywhere in the provenance UI). Nothing re-validates a citation as current
validity; the optional "newer accepted exists" hint on the Generate panel
is informational only, with no auto-rebind.

## 5. Historical independence

Persisted manifest = historical authority; current investigation reads =
optional detail enrichment (C9a/C9b exact APIs). On enrichment failure the
panel keeps every frozen identity (citation_id, evidence_key, frozen
analysis id/version, frozen claim id/type) and shows "详细记录当前不可读取"
— a citation is never reported missing (`CitationTracebackPanel` +
`traceback-enrichment-error` test). Unknown `citation_id` renders a neutral
"未知引用" notice with no guessing. Late responses are dropped by
identity-bound refs (`{taskId}|{reportId}|{citationId}`), and a late G1
completion never hijacks an explicit historical selection
(`selectionWhenAdmittedRef` + `selectByReportId` on the fresh internal
`versionsRef`).

## 6. Cross-task isolation

- `GET /api/reports/generations/{id}?task_id=`: strict read; `row.task_id
  != task_id` is indistinguishable from missing (opaque 404).
- `GET /api/reports/narrative/versions/{id}?task_id=`: scope/kind mismatch
  → opaque `None` → 404; cross-task and deterministic-snapshot ids look
  identical to "not found".
- Citation enrichment calls the per-task investigation routes with the
  current task id; the store is derived from that task, so a foreign
  evidence_key/analysis_id is a plain miss.
- Task switch drops all in-flight responses everywhere (identity refs in
  the polling hook, Narrative view, traceback panel, page).

## 7. Read-only guarantees

All new R2 GET paths use `mode=ro` + `PRAGMA query_only`, never construct a
repository (no create/migrate/self-heal), never write `updated_at` or any
other column: `read_generation_strict`, `read_narrative_version_strict`,
`GenerationReportWriter.read_manifest` (confined-layout file read). Missing
store/table → 404/empty per contract; corruption → fail-closed 503.
Narrative publication remains: staging write → immutability re-check →
atomic `os.replace` → single transaction (version row + generation
completion), with `test_failure_after_publish_before_completion_is_invisible`
pinning the crash window. R2d additionally made `manifest_path` relative
(no absolute server paths in the DB).

## 8. Chain B isolation

Greps for `case-analysis`, `case_analysis`, `IntelligenceReportReader`, and
the legacy `[[file:...]]` token over the entire R2 surface (backend
`forensic_report/` + `report_generation.py` + `report_narrative.py`,
frontend report components/services) return **zero** hits. All remaining
references are the pre-existing legacy modules themselves (`main.py` router
registration, `dependencies.py`, `intelligence_report.py`,
`case_analysis_endpoints/`). No fallback, no aggregation, no reuse.

## 9. Findings (P0/P1/P2/Debt)

- **P0:** none.
- **P1 (confirmed, fixed minimally in R3):** deterministic Chain A stored
  `str(exc)` into `ReportVersion.error` (`service.py` `_generate` failure
  path). Snapshot-writer `OSError` messages embed absolute filesystem
  paths, and `GET /api/reports/{id}/status` / list routes serve the field
  verbatim → sensitive error disclosure (§14 P1 class). The other two
  failure writers already used fixed sanitized strings and
  `logger.exception` preserves the full traceback server-side. **Minimal
  fix:** persist the fixed string `"report generation failed"`; new
  regression `test_writer_failure_persists_sanitized_error_without_paths`.
  Risk: negligible — message-only change on the deterministic failure path.
- **P2/Debt (reclassified per §10A, evidence-based):** Chain A
  `{report_id}` read routes (status/manifest/categories/pages/search) have
  no task-scope guard. Answers to the §10A questions: yes the normal
  frontend still works (it derives report_ids from the scope-scoped list);
  report_ids are fresh global uuid4 capability tokens; a client knowing a
  foreign report_id can read its snapshot/manifest; **but** the whole HTTP
  surface is an unauthenticated single-user workstation API — the
  scope-scoped list route already serves any task's version list to any
  local client, so a task guard on `{report_id}` routes would create no
  real isolation, and case-scope reports span multiple tasks (no coherent
  single-task guard semantics). There is no task-bound authorization
  promise in the product contract; the R2 façades are task-scoped for
  provenance correctness, not as an authz retrofit. → stays **P2/Debt**,
  owned by Phase D (authn/authz boundary).
- **Debt (unchanged, not expanded):** `ReportVersion.error` legacy rows
  written before R3 may still contain old unsanitized text (no backfill —
  they are historical failure records); pre-existing
  `test_dll_route.py` failures; pre-existing ESLint unused-var in
  `Layout.jsx`/`TaskSelector.jsx`; broken `.venv` direct invocation.

## 10. Known limitations

- No PDF/DOCX export, no WYSIWYG editing, no automatic Report Evidence
  selection, no report collaboration (all deliberately out of scope).
- The "newer accepted analysis" hint compares Report Evidence bindings to
  current accepted analyses at Generate time only; it never re-validates a
  published citation.
- Case-scope narrative generation is not implemented (deterministic chain
  supports task scope only for generation; case reports remain Chain A).
- Single-user unauthenticated HTTP surface (Phase D scope).

## 11. R2 final exit decision

R3 Exit Gate:

| Gate | Check | Result |
| --- | --- | --- |
| R3-E1 | citation → canonical Evidence | PASS (§2/§4) |
| R3-E2 | original-only keeps Analysis=NULL | PASS |
| R3-E3 | bound analysis = exact historical id | PASS |
| R3-E4 | claim identity = exact claim_id | PASS |
| R3-E5 | boundary not widened by claim external refs | PASS |
| R3-E6 | historical V1 never drifts | PASS |
| R3-E7 | persisted manifest = provenance authority | PASS |
| R3-E8 | current reads are enrichment only | PASS |
| R3-E9 | new R2 read paths task-scoped | PASS |
| R3-E10 | new R2 GETs have no mutation/self-heal | PASS |
| R3-E11 | Chain B fully isolated | PASS |
| R3-E12 | core user chain needs no curl workaround | PASS |

With the single P1 fixed (§9), there are **0 open P0 / 0 open P1**.
**Decision: R2/R3 Report Integration is frozen.**

## 12. Recommended Phase D priorities

1. Authn/authz boundary for the HTTP surface (subsumes the Chain A
   task-scope P2 and the credential rotation already pending user action).
2. Legacy Chain B retirement plan (`case_analysis` +
   `intelligence_report` surface) once R2 narrative covers its users.
3. Error/telemetry hygiene pass over remaining pre-existing surfaces
   (`ReportVersion.error` legacy rows, `test_dll_route.py` failures).
4. Deferred product work by explicit user decision only: PDF/DOCX export,
   WYSIWYG, automatic Report Evidence selection, collaboration.

## Verification record (R3)

- Focused backend: `tests/unit/forensic_report/` **138 passed** (0:16:21,
  includes the new sanitized-error regression);
  `tests/unit/test_service_manager_report_lifecycle.py` **18 passed**.
- Focused frontend: reports components + generation integration + polling
  + useReportVersion **54 passed** (one pre-existing load-dependent flake
  in `useReportGenerationPolling.test.js` hardened to wait for the
  terminal state first — test-only change, no production code).
- Full Gate **not** re-run per §16: the P1 fix is a single sanitized
  message in the deterministic failure path — not cross-task identity,
  schema, publication transaction, citation validator, or frozen
  provenance contract.
- `git diff --check`: clean.

Commit: `fix: sanitize report version failure detail and close out R3 review`.
