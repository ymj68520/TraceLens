# R1 Report Evidence Foundation

## Scope

R1 closes the first report integration boundary:

```text
Accepted Investigation Finding
  -> explicit Report Evidence binding
  -> frozen optional accepted Analysis version
```

R1 does not generate report narrative, regenerate reports, invoke an LLM, or create PDF/DOCX output. Those behaviors remain R2 scope.

## Repository Investigation

The existing `/api/reports` implementation is an immutable forensic snapshot generator. It stores report-version metadata in `reports.db`, then publishes a manifest and page shards. Its manifest contains by-value `EvidenceSource` data, but the repository had no `report_evidence` table, no `ReportEvidence` model, and no citation manifest or citation-binding API.

R1 therefore adds a separate task-scoped binding in the Investigation store. Existing forensic report version rows and their immutable snapshot output are not modified.

## Frozen Identity And Semantics

The authoritative Report Evidence identity is:

```text
(task_id, evidence_key)
```

`evidence_key` must be canonical and must already exist as a captured `evidence_snapshots` row in the same task. The evidence snapshot is always the report source. A bound `analysis_id` is only an attached interpretation of that source.

The persisted state is one of:

```text
excluded | main | appendix
```

`excluded` is an explicit state, not deletion. The row is retained so the audit trail records that an analyst considered and excluded the evidence. Database triggers reject DELETE and identity/audit-field mutation.

## Frozen Analysis Binding

`analysis_id` is nullable:

- `NULL` means `Original Evidence only`; this is valid even when no accepted analysis exists.
- A non-null value must pass all three checks inside the write transaction:
  1. the analysis belongs to the current task;
  2. it belongs to the exact requested `evidence_key`;
  3. its status is exactly `accepted`.

`review_pending`, `rejected`, `invalid`, `failed`, and another evidence's analysis cannot be bound. A foreign-task analysis returns an opaque not-found result rather than leaking existence.

Report reads always join the exact persisted `analysis_id`. They never call `get_latest_analysis()` or `get_latest_accepted_analysis()`. The read projection may expose `newer_accepted_available`, but this is only an analyst hint. A newer accepted version never changes the binding automatically.

Explicit rebind is the only way to change the frozen analysis binding. Status changes (`excluded`, `main`, `appendix`) are also explicit analyst actions. There is no implicit unbind action.

## Persistence And Integrity

`report_evidence` is added to the per-task Investigation SQLite store with:

- composite FK `(task_id, evidence_key)` -> `evidence_snapshots`;
- composite FK `(task_id, analysis_id)` -> `secondary_analyses`;
- a unique parent index on `(task_id, analysis_id)` for SQLite FK enforcement;
- immutable identity/audit columns (`task_id`, `evidence_key`, `added_by`, `created_at`);
- no-delete trigger.

The table is an OPTIONAL extension of the frozen v7 schema, not a v8 bump:

- fresh stores create it at initialization while staying `user_version = 7`;
- an existing C10-era v7 store without the table keeps reading as "no report
  evidence" — the strict reader returns an empty projection and the store
  bytes are untouched (the C10 §14/E13 no-write-on-GET guarantee is preserved
  for the new projection);
- the first explicit Report write constructs the extension objects through
  the write-capable repository path;
- if a legacy table-rewrite migration renamed the `secondary_analyses` parent,
  the repository rebuilds the child table so the composite FK points at the
  authoritative current parent while preserving existing Report Evidence rows.

GET paths use `InvestigationGraphReader` only (`mode=ro`, `query_only`, fail-closed on unsupported/corrupt stores). A missing Investigation DB returns an empty Report Evidence list without creating a file. POST/PUT paths use the write-capable repository after task/path trust validation.

## API Contract

```http
GET  /api/reports/evidence?task_id=...
POST /api/reports/evidence
PUT  /api/reports/evidence
```

Request bodies are strict (`extra=forbid`) and never accept `db_path`, source file paths, or other server-authority fields.

POST adds `main` or `appendix` and may include `analysis_id` for explicit binding. PUT explicitly changes status and/or binds another accepted analysis. Error semantics follow the Investigation boundary: invalid key/request shape is 400/422, missing task/evidence/analysis is 404, duplicate/conflicting binding is 409, and store/service failure is 503.

## Workbench Integration

Evidence detail now contains a Report Evidence panel:

- Add to Report requires an explicit analyst identity, report status, and either Original Evidence only or one accepted analysis version.
- `review_pending` and other non-accepted versions are not offered as binding choices.
- Existing rows show report status, exact bound analysis ID/version, accepting analyst, and the newer-accepted hint.
- Rebinding and status changes require an explicit Save action.
- The page reloads the server projection after mutations; it does not patch report state locally.

## Tests

The R1 matrix covers:

- uncited Evidence with `analysis_id = NULL`;
- main and appendix inclusion;
- explicit accepted binding;
- review_pending/rejected/invalid rejection;
- same-task wrong-evidence rejection;
- foreign-task opaque failure;
- A1 binding remaining frozen through A2 pending and A2 accepted;
- explicit rebind to A2;
- `excluded <-> main <-> appendix` transitions;
- identity/no-delete triggers and composite FKs;
- optional-extension compatibility: C10-era v7 stores read empty without
  mutation, and the first Report write builds the extension in place;
- HTTP request validation, canonicalization, 404/409/503 mapping;
- Workbench Original-only, accepted binding, pending exclusion, frozen display, newer hint, and explicit rebind UI flows.

R1 deliberately does not add claim-level Report bindings, Event-as-Evidence bindings, Graph-to-Report actions, automatic recommendations, or report generation.
