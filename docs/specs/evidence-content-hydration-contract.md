# Durable Evidence Content Contract — FROZEN

Status: **CONTENT_HYDRATION_CONTRACT = FROZEN** (2026-10-01,
branch `mvp/agent-v0-content-hydration`, frozen_at_commit 09c74e96).
Audit basis: `docs/specs/evidence-content-hydration-audit.md` (incl.
addendum).

## 1. Frozen production invariant (§48)

```text
For any content-readable File Evidence E belonging to a live task T:

resolve_evidence(T, E) succeeds
AND
content backing remains deterministically readable
after parser temporary cleanup and service restart.

If the type is not readable, the unavailability is explicit:
content_available = false with a reason code — never an ambiguous null,
never fabricated content.
```

## 2. Contract version and surface

| element | value |
|---|---|
| contract id | `evidence-content-hydration:v1` |
| store module | `httpserver/services/evidence/content_store.py` |
| storage layout | `data/tasks/<task_id>/content/blobs/<sha256>` (hash-addressed, task-owned) |
| locator manifest | additive `files.db` columns `content_sha256 TEXT`, `content_size INTEGER`, `content_stored_at INTEGER` (idempotent `ALTER TABLE`, first-write wins) |
| reacquisition primitive | C++ `POST /api/forensics/files/materialize` (raw-DB membership gate, fail-closed); `POST /api/forensics/extract` for jobs — unchanged |
| reason codes | `CONTENT_NOT_PERSISTED_LEGACY`, `CONTENT_UNSUPPORTED_TYPE`, `CONTENT_SOURCE_MISSING`, `CONTENT_INTEGRITY_MISMATCH`, `CONTENT_READ_FAILED`, + documented extension `CONTENT_EXCEEDS_PERSISTENCE_LIMIT` |
| persistence cap | 64 MiB per file (`EVIDENCE_CONTENT_PERSISTENCE_LIMIT_BYTES`); above the cap content is served bounded but not retained |
| decode chain | UTF-8 strict → GB18030 strict → UTF-8 replacement; binary (NUL sniff, first 8 KiB) refused as `CONTENT_UNSUPPORTED_TYPE` |
| preview bound | `MAX_CONTENT_CHARS = 8000` (unchanged) |

## 3. Integrity policy

- When the parser recorded a content hash (`files.db.md5`), stored bytes
  are verified against it at write; any mismatch fails closed. The image
  walk currently leaves `md5` NULL (audit addendum), so absence is the
  norm, not an error.
- When no parser hash exists, raw-DB-gated reacquisition from the image
  is preferred; an unverifiable extraction artifact is served only when
  reacquisition is impossible, with explicit `adopted-legacy`
  provenance.
- Every persisted blob is re-verified (sha256 locator) on every read;
  mismatch raises `CONTENT_INTEGRITY_MISMATCH` and nothing is served.
- Reads are task-scoped via `resolve_evidence(task_id, evidence_key)`;
  there is no cross-task blob lookup. Lazy materialization only ever
  creates the verified derived content cache — agent reads stay
  read-only with respect to Evidence identity.

## 4. Boundaries preserved (all frozen)

- Evidence identity stays `(task_id, evidence_key)` — no content-based
  identity.
- Original Evidence (image bytes, source rows' forensic metadata,
  timestamps) is never modified.
- A1-S EvidenceSnapshot remains metadata-only; Initial AI Analysis is
  never a content source; ToolObservation remains non-durable.
- Investigation lifecycle, A1-T/A1-H contracts, benchmark machinery:
  unchanged (full unit regression green).
- Task deletion removes identity, DBs, and content backing atomically
  (content dir lives inside the task dir; deletion-race guard never
  recreates a store for a deleted task).

## 5. Freeze-gate evidence (§58)

| gate | evidence |
|---|---|
| audit + root cause | C1 bffd93df + addendum 8f3b52d8 |
| no benchmark-only workaround | store lives in the production read path; canaries used zero benchmark special paths |
| survives cleanup + restart, bytes/hash exact | canary `content-pre` (reacquired, sha256 = source ×3) → real dual-service restart → `content-post` (locator provenance, identical sha256 ×3, ~20 ms) |
| cross-task / tamper / normalization / binary / oversized / legacy / deletion-race | `tests/unit/evidence/test_content_store.py` (18 tests) + resolver/adapter wiring tests |
| Files path regression | `test_auto_extract_analyze.py` + full suite green; office/auto-extract flows untouched |
| Agent Tool path | `test_agent_tool_adapters.py` availability semantics; agent canary: calibration fixture `t2-no-evidence` provisioned with NO staging, full agent loop, image-exclusive content markers in delegation results + trajectory |
| S4/A1-T/A1-H + full unit regression | 2461 passed + 36 benchmark contract tests, 1 skipped, 0 failures |
| task deletion | canary `content-post`: task dir (incl. content store) removed |

## 6. Runtime epoch and downstream obligations (§49–§53)

- New baseline: `benchmarks/profiles/agent-v0-runtime-baseline-v3.json`
  (supersedes v2-era runtime as historical). The prior
  `CalibrationEvidenceBindingV2` remains historical and cannot serve as
  Gen-4 admission evidence (§50).
- Required BEFORE any Acceptance Generation 4 (none auto-started):
  model/runtime requalification, a new valid B2 calibration measurement,
  CalibrationEvidence rebinding, and AcceptanceProfile review/binding to
  the new runtime. These are separately directed; this phase executed
  only a hydration canary (not a calibration measurement).
- Gen-4 must use brand-new holdout instances; Gen-1/2/3 stay CONSUMED.
  Gen-3 cases must never be used to validate this fix (canaries used a
  fresh synthetic fixture and the public calibration fixture only).
