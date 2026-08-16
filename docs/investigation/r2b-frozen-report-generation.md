# Phase R2b — Frozen Report Generation Admission & Persistence

- Date: 2026-08-16
- Baseline: Dev @ `1ed670d` (route-contract fix) on top of R2a `91682eb`,
  R1 `ffdacba`, Security Preflight `d83c1f7`, C10 `eb05322`
- Scope: freeze the R2 LLM-generation input. Admission assembles a
  consistent read snapshot from R1 Report Evidence, builds an immutable
  typed envelope, serializes it once to canonical JSON, hashes it
  (SHA-256), and persists an insert-only admission row. **No LLM call, no
  narrative generation, no executor, no public route** — those are R2c/R2d.

## 1. Added / Modified / Reused

**Added**

- `python_service/httpserver/services/forensic_report/generation.py` —
  `REPORT_GENERATION_PROMPT_VERSION = "final-report:v1"` (version identity
  only), `ReportGenerationInputError(code, message)` (stable machine codes
  `no_report_evidence` / `invalid_report_evidence_binding`), the strictly
  read-only `ReportGenerationInputBuilder`, and
  `ReportGenerationAdmissionService` (task lookup via the C++ backend,
  envelope assembly, canonical JSON + SHA-256, durable insert).
- `report_generation_inputs` table + two triggers in
  `reports.db` (see §2).
- Envelope V1 models + `ReportGenerationInput` row model in
  `forensic_report/models.py` (§3).
- `tests/unit/forensic_report/test_generation_admission.py` (§11).

**Modified**

- `forensic_report/repository.py` — additive `_ensure_schema` objects and
  two insert-only methods (`create_generation_input`,
  `get_generation_input`); nothing about `report_versions` changed.
- `forensic_report/__init__.py` — exports the new models.
- `services/service_manager.py` — lazy `report_generation_service` slot
  (created only when the C++ backend is ready; **no route is wired to it**).

**Reused (unchanged semantics)**

- R1 Report Evidence persistence + the optional-v7-extension read guards.
- Immutable Evidence Snapshot payloads (`FileSnapshotPayload` /
  `ClusterSnapshotPayload`) as the only Evidence Source projection.
- Exact `secondary_analyses` / `analysis_claims` / `claim_evidence_refs`
  provenance (read-only).
- C7c/C4b `canonical_json` primitive (`investigation/acquisition.py`) and
  the `sha256(canonical_json)` input-hash pattern — no third serializer.
- A-chain `ReportRepository` store ownership and connection style.

**Do Not Touch (and untouched)**

- `/api/llm/case-analysis` legacy Chain B (not extended, not fixed, not
  consumed), Investigation write state machines, Event refresh,
  Graphiti/Neo4j, KnowledgeGraph, Viewer, C++, R1 binding semantics.

## 2. Persistence layout — additive companion in `reports.db`

`reports.db` has **no schema-version/migration mechanism** (its schema owner
is `ReportRepository._ensure_schema`, pure `CREATE TABLE IF NOT EXISTS`), so
the minimal additive migration is exactly that: new objects created
idempotently next to `report_versions`.

```sql
CREATE TABLE IF NOT EXISTS report_generation_inputs (
    generation_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    scope_type TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'admitted',
    requested_by TEXT NOT NULL,
    input_schema_version INTEGER NOT NULL,
    prompt_version TEXT NOT NULL,
    input_envelope_json TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    report_id TEXT,
    created_at TEXT NOT NULL,
    CHECK (scope_type = 'task' AND scope_id = task_id)
);
CREATE INDEX IF NOT EXISTS idx_report_generation_task
    ON report_generation_inputs(task_id, created_at);
CREATE TRIGGER IF NOT EXISTS trg_report_generation_input_frozen
BEFORE UPDATE ON report_generation_inputs
FOR EACH ROW
WHEN NEW.generation_id IS NOT OLD.generation_id
  OR NEW.task_id IS NOT OLD.task_id
  OR NEW.scope_type IS NOT OLD.scope_type
  OR NEW.scope_id IS NOT OLD.scope_id
  OR NEW.requested_by IS NOT OLD.requested_by
  OR NEW.input_schema_version IS NOT OLD.input_schema_version
  OR NEW.prompt_version IS NOT OLD.prompt_version
  OR NEW.input_envelope_json IS NOT OLD.input_envelope_json
  OR NEW.input_hash IS NOT OLD.input_hash
  OR NEW.created_at IS NOT OLD.created_at
BEGIN
    SELECT RAISE(ABORT, 'report generation input is immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_report_generation_input_no_delete
BEFORE DELETE ON report_generation_inputs
BEGIN
    SELECT RAISE(ABORT, 'report generation input is never deleted');
END;
```

- **Identity**: `generation_id = rg_<uuid4hex>` — opaque, persisted, never
  derived from title/timestamp/index. Generation identity and report
  version identity stay separate concepts.
- **Frozen after admission** (DB-enforced, NULL-safe `IS NOT`): identity,
  scope, requester, schema version, prompt version, envelope bytes, hash,
  created_at. `status` (starts `admitted`) and `report_id` (NULL until an
  R2c publication links it) are deliberately **outside** the frozen set so
  the R2c lifecycle can transition them without touching frozen input.
- Terminal/history semantics (running/completed/failed transitions,
  restart recovery) are R2c; the frozen-input trigger exists already per
  the plan.

## 3. Envelope V1 — exact schema

`ReportGenerationEnvelopeV1` (frozen, `extra="forbid"`,
`schema_version: Literal[1] = 1`, `prompt_version` required):

```
{
  schema_version: 1,
  prompt_version: "final-report:v1",
  task_id: "...",
  main_evidence: [EnvelopeEvidenceItemV1],
  appendix_evidence: [EnvelopeEvidenceItemV1],
  allowed_report_evidence_ids: ["file:/case/a.txt", ...]
}
```

`EnvelopeEvidenceItemV1`:

```
{ evidence_key, report_status: main|appendix, snapshot, bound_analysis|null }
```

`EnvelopeSnapshotV1` (exact canonical persisted snapshot fields only):

```
{ task_id, evidence_key, evidence_type: file|cluster, captured_at, payload }
```

`payload` is the frozen C4 capture-time projection
(`FileSnapshotPayload`/`ClusterSnapshotPayload`). Never a re-read of
`files.db.llm_description`, reanalyze output, or current raw metadata.

`EnvelopeBoundAnalysisV1` (only when R1 `analysis_id != NULL`):

```
{
  analysis_id, version,
  description, summary, model,
  grounding_status,
  review: { decided_by, decided_at, decision_reason },
  claims: [EnvelopeClaimV1]
}
```

`EnvelopeClaimV1`:

```
{ claim_id, claim_index, claim_type, claim_text, grounding_status,
  warnings, evidence_refs: [...], created_at }
```

Explicitly **not** in the envelope: DB paths, SQLite rowids, source store
paths, current filesystem paths as authority, raw prompt runtime metadata,
`requested_by` (audit column on the row), `newer_accepted_available` (UI
hint), and anything derived at execution time.

Model validators freeze the determinism contract itself: main/appendix
sorted by `evidence_key` with no duplicates; `allowed_report_evidence_ids`
sorted-unique and exactly the main+appendix keys (server-derived — clients
can never supply it); claims sorted by `claim_id`; claim refs sorted;
snapshot `task_id` must equal the envelope `task_id`; item `report_status`
only `main|appendix`; snapshot identity must match the item key.

## 4. Canonicalization & input_hash

- `canonical_json(envelope)` — the existing C7c primitive:
  `model_dump(mode="json")` → `json.dumps(ensure_ascii=False,
  sort_keys=True, separators=(",", ":"))`. Serialized **exactly once** per
  admission; UTF-8; pydantic `mode="json"` guarantees no NaN/Infinity (and
  the persisted payloads never contain them).
- `input_hash = sha256(canonical_json.encode("utf-8")).hexdigest()` —
  identical rule to `secondary_analyses`/event refresh.
- Both the exact serialized bytes and the hash are frozen on the row; R2c's
  executor must recompute and verify before consuming.

## 5. Report version allocation — decision: **Option B (allocate at R2c publication)**

The A chain's `BEGIN IMMEDIATE` `MAX(version)+1` allocation and publication
machinery stay untouched. R2b does **not** allocate a `report_versions` row
because (a) there is no executor yet, so an allocated row would sit
`queued` forever — exactly the stranded-public-API smell the plan forbids
(§14); (b) faking a not-yet-generated narrative row into the deterministic
snapshot chain's semantics would be wrong. R2c will allocate the version
inside its publication transaction and link it via the (mutable)
`report_id` column on the generation row.

## 6. Read consistency boundary

One admission = one `mode=ro` + `PRAGMA query_only` connection to the
task's `investigation.db` + one explicit `BEGIN … ROLLBACK` read
transaction wrapping the whole assembly (report_evidence list → snapshots →
analyses → claims/refs). SQLite keeps that snapshot internally
self-consistent, so an analyst rebind committed mid-assembly can never
produce a mixed-epoch envelope. Cross-file atomicity with `reports.db` is
explicitly not required: the envelope is a value once built; later R1
changes cannot alter it. The builder also fails closed on any store whose
`user_version != 7` (EvidenceStoreError) and treats a missing
`report_evidence` table (C10-era v7 store) as "no report evidence" without
ever writing.

## 7. Admission re-validation (fail closed)

Even though the R1 write path triple-checks bindings, admission re-verifies
the persisted state inside its read transaction: the bound analysis must
exist **in this task's store**, belong to **this evidence_key**, and be
`accepted`. Any failure (or a missing snapshot) raises
`ReportGenerationInputError("invalid_report_evidence_binding")` **before**
any generation row is created — no repair, no rebind, no auto-latest.

## 8. Original-only, excluded, hints, cross-task

- `analysis_id = NULL` means "analyst chose Original Evidence only": the
  item enters the envelope with `bound_analysis: null` even when newer
  accepted analyses exist. There is no `get_latest_accepted_analysis` call
  anywhere on this path (locked by test).
- `excluded` rows never enter main/appendix/allowed/LLM input (locked by
  test, absent from the serialized JSON entirely).
- `newer_accepted_available` is a Workbench UI hint and never enters the
  envelope (locked by test).
- Cross-task: all reads are scoped by the `task_id` whose store path was
  derived from trusted C++ backend paths; a foreign `analysis_id` cannot
  resolve and fails closed; identical evidence_keys in two tasks produce
  strictly isolated envelopes (locked by tests).

## 9. Claim external refs (citation boundary)

A bound analysis's claims keep their **full persisted** `evidence_refs`
(e.g. `[A, B]` with B outside the report set) — that is claim provenance
and stays frozen. But `allowed_report_evidence_ids` is exactly the
main+appendix keys: B does not become report evidence, a citation
candidate, or LLM-visible input by itself. R2c's citation validation
enforces this boundary against the persisted allowed set.

## 10. Schema compatibility

Purely additive: legacy `reports.db` files gain the companion table/triggers
on the next `ReportRepository` construction (idempotent `IF NOT EXISTS`);
`report_versions` rows, the Viewer, FTS snapshots, and every existing
`/api/reports` read contract are byte-compatible (locked by test). No
global schema-version bump happened anywhere (investigation.db stays at
the optional-v7-extension design from R1).

## 11. Tests (`tests/unit/forensic_report/test_generation_admission.py`)

§26 matrix, all deterministic (no LLM/network/sleeps):

1. Original-only main + NULL binding, with an unbound accepted analysis
   present — no latest fallback.
2. Bound A1 → exact A1 (version/description/model/review) + exact claims/refs.
3. Newer accepted A2 admitted later — envelope still only A1; identical
   hash; no `newer_accepted_available` in the JSON.
4. main/appendix/excluded matrix; allowed = sorted(main+appendix); excluded
   key absent from the serialized envelope.
5. Claim refs `[A, B]` with B not report evidence — refs retained,
   allowed only `[A]`.
6. Tampered persisted bindings (wrong evidence / non-accepted) — fail
   closed typed error, zero generation rows.
7. Cross-task: same evidence_key in two tasks → isolated envelopes; a
   corrupted binding pointing at the other task's analysis fails closed.
8. Determinism: same state → identical canonical JSON + hash across
   assemblies and admissions.
9. Hash changes: binding change, report-status change, prompt-version
   change, snapshot-payload change → different hashes.
10. Frozen-input triggers: hash/envelope/prompt_version/task_id/
    requested_by UPDATE → `IntegrityError`; DELETE → `IntegrityError`;
    `status` UPDATE succeeds (R2c lifecycle).
11. `no_report_evidence`: all excluded / store without the extension table
    / missing investigation.db / task without trusted DB paths; unknown
    task stays opaque `EvidenceNotFoundError`; unsupported store version
    fails closed (`EvidenceStoreError`).
12. Read consistency: exactly one `sqlite3.connect` per assembly; epoch
    test — admit(A1) → rebind A2 → admit(A2): the first row still holds A1
    and the hashes differ.

Plus envelope-model contract guards (unsorted lists, allowed-set mismatch,
task mismatch all rejected) and the legacy-`reports.db` additive-migration
test.

## 12. Known R2c gaps (deliberately not in R2b)

- Executor/worker, `queued→running→completed|failed` transitions,
  restart/shutdown recovery for generation rows.
- LLM prompt (the version string is frozen; the prompt text is not).
- Structured output parser; citation manifest build + validation against
  `allowed_report_evidence_ids`.
- Publication: version allocation (Option B), snapshot write via the
  existing A-chain machinery, `report_id` linking.
- Public routes: admission + status/polling, with the typed machine codes
  mapped to fixed-string HTTP errors (`ReportVersion.error` sanitization
  noted as R2a P1-4 should be folded in there).
