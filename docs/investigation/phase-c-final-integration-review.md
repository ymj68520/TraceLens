# Phase C — Final Integration Review (C10)

Date: 2026-08-14 · Branch: Dev · Reviewer pass: C10 audit + minimal fix set
Scope: the complete Investigation MVP user chain, identity boundaries,
transaction boundaries, Evidence provenance, recovery semantics, and the
E1–E14 exit gate. No new domain semantics were introduced by this review.

## 1. Architecture achieved

```
Task (per-task files.db + investigation.db, schema v7)
→ Evidence Snapshot          evidence_snapshots        (C3, immutable)
→ Secondary Analysis         secondary_analyses         (C4/C6, versioned state machine)
→ Structured Claims          analysis_claims + claim_evidence_refs (C5, append-only)
→ Analyst Review             review_analysis()          (C7b, sole accept writer)
→ Investigation Event        investigation_events + _versions (C7a, append-only narrative)
→ Event↔Evidence link        investigation_event_evidence (C7a, append-only)
→ needs_refresh propagation  same-transaction dirty marks (C7b P2/P5)
→ Explicit Event Refresh     investigation_event_refreshes (C7c, frozen V2 envelope)
→ Investigation Graph        mode=ro overlay reader + Base KG (C8b/C8c)
→ Workbench UI               /investigation three-column shell (C9a–C9c, C10)
```

Per-task SQLite stores (`investigation.db`, schema v7, `user_version=7`)
are the single source of truth for every Investigation conclusion. All
identity is exact persisted ids: `(task_id, evidence_key)`, `analysis_id`,
`claim_id`, `event_id`, `refresh_id`. Every read filters by `task_id`; the
stores themselves are physically separated per task.

## 2. End-to-end workflow (verified chain)

1. **Capture** — analyst picks a file from the task file list (Workbench
   left column, C10); `POST /snapshots` resolves + captures server-side.
2. **Initial Analysis** — read from the immutable snapshot payload only
   (`GET /evidence/{key}/snapshot`); never from `files.db` LLM columns and
   never re-analyzed in place. Modifying the source `files.db` description
   after capture does not change the Workbench view (frozen regression:
   `test_investigation_read.py`).
3. **Secondary Analysis** — explicit submit (`POST /analyses`) captures
   missing snapshots, versions the analysis, executes from the frozen input
   envelope only, lands in `review_pending` with persisted claims + grounding.
4. **Claims/grounding** — claims carry refs from `claim_evidence_refs` only;
   refs outside the declared analysis input are dropped by the grounding
   validator (`test_phase_c_evidence_to_review_flow.py`).
5. **Review** — explicit accept/reject/invalid through `review_analysis()`
   only; terminal rows are immutable (DB trigger).
6. **Event** — explicit creation (v1 narrative) and explicit evidence link
   (append-only, snapshot-backed FK, no unlink).
7. **Dirty propagation** — accept dirties linked events in the same
   transaction; a later link to already-accepted evidence is born dirty;
   the bump is idempotent per clean→dirty transition.
8. **Refresh** — explicit admission freezes a V2 envelope (hash-verified at
   execution and again at completion); execution reads the envelope only;
   completion compares the frozen accepted-signature against the current
   authoritative state, so admission-window staleness is never swallowed.
9. **Version N+1** — completed refresh appends an immutable version;
   `base_version_changed` fails without overwriting history.
10. **Graph** — task-level overlay from persisted state only: accepted >
    review_pending fallback, one analysis per evidence, edge whitelist
    (`event_evidence`, `analysis_evidence`, `analysis_claim`,
    `claim_evidence`, `base_relation`), Base KG failure degrades to
    overlay-only, Investigation store failure fails closed (503).

## 3. Evidence provenance chain

Any displayed conclusion traces, by exact id, to persisted rows:

```
Claim (claim_id) → analysis_id → evidence_refs (claim_evidence_refs)
                                    ↘ snapshot_id → evidence_snapshots
Event version (task_id, event_id, version)
    → refresh_id → input_hash + frozen envelope → requested_by + model
Evidence (task_id, evidence_key) → captured snapshot payload → parsed source
```

Prohibited identity forms were grepped and are absent from the Workbench
surface: basename/`file_path`/title/event-title identity, lowercase or
normcase matching, latest/current fallbacks in place of exact ids. The
frontend never derives `latest_accepted` locally — the C8b server selection
is the only accepted-state projection.

## 4. State machines

- **SecondaryAnalysis**: `queued → running → review_pending →
  accepted|rejected|invalid`; execution failure → `failed`. Terminal rows
  reject all UPDATEs (trigger); input columns are immutable in every state
  (trigger); only `review_analysis()` can enter an accepted status from
  `review_pending`.
- **EventRefresh**: `queued → running → completed|failed`. Terminal rows
  immutable; frozen input columns immutable in every state (trigger);
  completion is a single `BEGIN IMMEDIATE` transaction (version INSERT +
  needs_refresh decision + refresh UPDATE).
- **needs_refresh**: 0→1 only via the two same-transaction dirty writers
  (`_mark_related_events_dirty`, `_mark_event_dirty_if_evidence_accepted`),
  both guarded `WHERE needs_refresh = 0`; 1→0 only inside refresh
  completion when (still dirty) ∧ (dirty at submission) ∧ (frozen accepted
  signature == current accepted signature).

## 5. SQLite ownership (schema v7)

| Table | Owner / writer | Mutable fields | Immutable | FK | Terminal guard | Version semantics |
|---|---|---|---|---|---|---|
| `evidence_snapshots` | capture (`capture_if_absent`) | — | everything (no UPDATE trigger) | — | `trg_evsnap_no_update` | UNIQUE(task_id, evidence_key); one snapshot per evidence |
| `secondary_analyses` | executor admission/execution, `review_analysis` | status, output cols, lifecycle timestamps, decision/error fields, grounding | task_id, evidence_key, snapshot_id, version, input_hash, input_envelope_json, prompt_version | snapshot_id → evidence_snapshots(id) | `trg_secondary_no_terminal_update` + legal-transition trigger | UNIQUE(task_id, evidence_key, version); latest ≠ latest_accepted |
| `analysis_claims` | structured completion path | — | everything | analysis_id → secondary_analyses ON DELETE RESTRICT | `trg_claims_no_update/no_delete` | per analysis version, claim_index ordered |
| `claim_evidence_refs` | grounding validator | — | everything | claim_id → analysis_claims | `trg_claim_refs_no_update/no_delete` | refs ⊆ declared analysis input |
| `investigation_events` | event create / dirty writers / refresh completion | needs_refresh, updated_at | identity (trigger), created_at | — | `trg_inv_events_no_identity_update` | current_version = MAX(version) derived |
| `investigation_event_versions` | event create (v1), refresh completion (vN+1) | — | everything | (task_id, event_id) → investigation_events | `trg_inv_event_versions_no_update/no_delete` | append-only narrative history |
| `investigation_event_evidence` | explicit link | — | everything | (task_id, event_id), snapshot-backed evidence existence check | `trg_inv_event_evidence_no_update/no_delete` | append-only; no unlink |
| `investigation_event_refreshes` | refresh admission/claim/completion/fail | status, lifecycle timestamps, produced_version, error fields, model | refresh_id, task_id, event_id, base_version, input_hash, input_envelope_json, requested_by, created_at | (task_id,event_id)→events; base/produced version → versions | `trg_inv_refresh_no_terminal_update` + legal-transition + input-immutability triggers | one in-flight refresh per event (admission 409) |

## 6. Frontend / backend coverage

| Backend capability | UI consumer |
|---|---|
| POST /snapshots (capture) | Workbench Capture Evidence form (C10 fix P1-b) |
| GET /evidence, /evidence/{key}/snapshot | Evidence workspace + Analysis workspace |
| POST /analyses + polling | Run Secondary Analysis form + exact-id polling |
| GET /analyses (history) | version list, exact selected version |
| POST /analyses/{id}/review | Review Decision form (review_pending only) |
| GET claims | claims section, per-analysis provenance |
| POST /events | Create Event form |
| POST /events/{id}/evidence | Link Evidence picker (captured candidates, no free text) |
| POST /events/{id}/refresh + history polling | Refresh Narrative form + exact refresh_id polling |
| GET /events, versions, refreshes | Event list, immutable version history, refresh history |
| GET /graph | Graph tab (accepted>review_pending projection, server-side) |

## 7. Failure / recovery semantics

- **Restart**: both executors sweep stale `queued`/`running` rows at
  initialize → `failed(service_restart)`; admission refuses while shutting
  down.
- **Shutdown**: tracked tasks cancelled, then durable
  `failed(service_shutdown)`; analysis sweep tolerates already-terminal rows
  (loser never fails winner).
- **Read failures**: all GET projections go through the strict `mode=ro` +
  `query_only` reader (C10 fix P1-a); unsupported schema version or
  corruption → fail-closed `EvidenceStoreError` → HTTP 503; missing store →
  `[]`/404 with the file never created.
- **Error surface**: 400 invalid key/status, 404 exact identity missing,
  409 duplicate link / refresh-in-progress / review conflict, 422 request
  validation, 503 store/service unavailable; details are fixed strings — no
  DB paths, URIs, stack traces, provider secrets, or internal exception text.
- **Frontend stale protection**: `useStaleResource`, both polling hooks and
  all mutation handlers are identity-keyed; late responses never overwrite
  a newer task/evidence/event, never yank selection back, and completed
  refreshes never clear `needs_refresh` locally (server reload decides).

## 8. Findings and fix set

### P0 — none found.

### P1-1 — GET read-side could mutate/create the store (E13) — FIXED
`InvestigationRepository.__init__` mkdir/migrates/self-heals (v1–v6 → v7,
missing triggers/indexes/columns), and initializes a fresh v7 store when
the file is absent. The events/versions/links/refreshes GET services
constructed it on existing stores (migrate/self-heal on read, masking
tamper evidence); the analyses GET additionally **created** the store for
tasks that had none. Fix: extended the strict `InvestigationGraphReader`
with the eight Workbench read projections (task-scoped `get_analysis`
included) and repointed the six event GET service methods plus
`SecondaryAnalysisExecutor.get_analysis/list_analyses`. Regression:
`test_phase_c_read_side_no_mutation.py` (no-create, byte-identical reads,
unsupported-version fail-closed, tamper not self-healed).

### P1-2 — Evidence capture had no UI consumer (E14) — FIXED
`POST /snapshots` was unreachable from the Workbench: the evidence list
shows only captured evidence, and both capture-on-submit and
capture-on-link are circular for the first evidence. A fresh task therefore
could not start the Phase C chain from the UI. Fix: minimal
`CaptureEvidenceForm` (left column) with candidates from the task file list
(Files-page API, no free-text keys), capture → reload evidence list +
graph, no selection changes; backend unchanged (resolver remains the trust
boundary). Tests: 3 new page tests (candidates exclude captured, exact POST
body + reloads + no selection hijack, inline HTTP error).

### P2 — recorded, not blocking MVP (no C10 code change)
- `InvestigationRepository.get_analysis` (repository, write-path helper)
  filters only by `analysis_id`, not `task_id`. Isolation actually holds —
  every repository instance opens its own task's store, and the strict
  reader's `get_analysis` is task-scoped — but the helper should adopt the
  task filter as defense-in-depth on its next touch.
- Capture candidates come from the Files-page "largest files" API (top 100)
  rather than a full task file listing; acceptable for MVP, revisit when a
  full listing API exists.

### Debt (tracked, outside C10)
- Pre-existing failing `httpserver/tests/unit/test_dll_route.py` (3 cases,
  unrelated to Phase C) and pre-existing ESLint unused-var errors in
  `Layout.jsx` / `TaskSelector.jsx`.
- `.env` was committed historically — full history scrub plus credential
  rotation still pending (Phase D entry item).
- Legacy V1 refresh envelopes remain readable but non-executable
  (`historical_envelope`) by design.
- Broken `.venv` interpreter wrapper; tests run via
  `scripts/test.py` (site-packages path injection).

## 9. Phase C exit gate

| Gate | Status | Evidence |
|---|---|---|
| E1 Raw/Initial/Secondary layers unconfused | ✅ | read service + §4 tests |
| E2 Initial Analysis reads immutable Snapshot | ✅ | `get_snapshot` → `latest_snapshot`; no files.db path |
| E3 LLM is not an Evidence Source | ✅ | envelopes/claims only; resolver is the sole evidence authority |
| E4 Claims trace to real Evidence refs | ✅ | `claim_evidence_refs`; out-of-input refs dropped (new test) |
| E5 accepted = explicit Analyst Review | ✅ | `review_analysis()` sole writer; no bypass callers |
| E6 Event↔Evidence authoritative explicit relation | ✅ | link table + snapshot-backed check; no unlink/heuristics |
| E7 accepted→needs_refresh both temporal orders | ✅ | link-then-accept + accept-then-link + idempotency tests |
| E8 Refresh never overwrites narrative history | ✅ | trigger-proven immutability + base_version_changed test |
| E9 Admission-window staleness never swallowed | ✅ | S1–S3 (+clean) completion-signature tests |
| E10 Graph overlays persisted state only | ✅ | mode=ro reader; no graph writes; deterministic namespaces |
| E11 Base KG failure never blocks Investigation | ✅ | degrade-to-overlay warning; investigation failure = 503 |
| E12 Cross-task isolation full chain | ✅ | per-task stores; isolation test file |
| E13 GET read-side never mutates | ✅ (after P1-1) | strict reader everywhere; no-create/no-migrate/no-heal tests |
| E14 Workbench completes the core user chain | ✅ (after P1-2) | capture → … → graph all consumable from UI |

**Decision: Phase C Investigation MVP — PASS.** All P0/P1 findings were
fixed within C10 (strict read projections; capture entry). Next decision:
Report Evidence / Report integration, or Phase D.

## 10. Test inventory added by C10

Backend (`tests/unit/investigation/`, 24 tests):
`test_phase_c_evidence_to_review_flow.py`,
`test_phase_c_accept_to_event_dirty_flow.py`,
`test_phase_c_event_refresh_clean_flow.py`,
`test_phase_c_refresh_new_accept_keeps_dirty.py`,
`test_phase_c_cross_task_isolation.py`,
`test_phase_c_read_side_no_mutation.py`.

Frontend: 3 capture-entry tests in `Investigation.test.jsx` (36 total in
the file), plus the two §26-style chain tests carried from C9c
(clean convergence and concurrent-dirty retention).
