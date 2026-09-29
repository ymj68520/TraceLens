# A1-T Repository Audit — Specialist Result Trusted-field Separation

Status: AUDIT COMPLETE (pre-implementation, spec §1)
Branch: `mvp/agent-v0-specialist-result-contract` (from `48bc1a4d`;
production tree byte-identical to frozen ancestor `ed382cbb`)
Scope: answer Q1–Q12 from code; freeze the §2 responsibility split and the
§3/§5 design. No production behaviour changed by this document.

Trigger evidence: B2-restart round `48bc1a4d` — sensenova-6.8-flash-lite
failed the SpecialistResultV1 output contract 7/8 with
`UnexpectedModelBehavior("Exceeded maximum output retries (2)")`;
captured RetryPrompt errors show the model attempting to FILL
server-computed fields (`execution_digest` as a JSON string,
top-level `tool_call_count`/`observation_count` → `extra_forbidden`).

## Q1 — SpecialistResultV1 exact fields?

`agent_specialist_result.py:102` — frozen, `extra="forbid"`:

- identity bindings: `result_version` (validator pins
  `"specialist-result:v1"`), `delegation_id`, `question_id`
- semantic proposal payload: `summary`, `claim_candidates`,
  `evidence_refs`, `entity_candidates`, `correlation_candidates`,
  `follow_up_questions`, `coverage_observations`, `limitations`,
  `warnings`
- runtime facts: `execution_digest: ExecutionDigest` (default
  `ExecutionDigest()`; fields `model_name`, `request_count`,
  `input_tokens`, `output_tokens`, `tool_call_count`, `observation_count`)

## Q2 — which fields does the model output today?

ALL of them. `SpecialistDelegationExecutor._build_agent`
(`agent_specialist_executor.py:832-841`) is the single production
construction point and passes `output_type=SpecialistResultV1` to
PydanticAI: the model receives and fills the full canonical schema,
including the runtime-owned `execution_digest` object.

## Q3 — which fields are recomputed/overwritten server-side today?

- `execution_digest`: built by the executor
  (`agent_specialist_executor.py:672-687`) AFTER validation and injected
  with `result.model_copy(update={"execution_digest": ...})` — the
  model-written value (if any) is always discarded.
- `result_version`: never recomputed, but validator-pinned to the frozen
  constant.
- `delegation_id` / `question_id`: never overwritten; validator rejects
  mismatches against the frozen pack.
- everything else about the PERSISTED record (hash, timestamps, usage
  column, scope bindings) is server-side by construction (Q5/Q9).

## Q4 — who computes execution_digest, and where exactly?

The executor, after `agent.run()` and after result validation:

- `model_name` ← `agent_result._model_name` / response model_name
- `request_count` / `input_tokens` / `output_tokens` ← pydantic-ai
  usage object (`getattr(usage, "requests"|"input_tokens"|"output_tokens")`)
- `tool_call_count` = `observation_count` = number of durable
  `ToolObservation` rows in the run scope whose `delegation_id` equals
  this delegation (`runtime.list_tool_observations(investigation_id,
  run_id=run_id)`, filtered)

## Q5 — canonical truth for tool_call_count / observation_count?

Durable runtime records: `agent_tool_observations` rows written by the
P3-F2.3 atomic observation+trajectory pair. NEVER model claims. The
executor's filter (delegation-scoped) is the only counting rule.

## Q6 — other model-facing fields with server-owned character?

Inside the output schema: `execution_digest` is the ONLY runtime-owned
field. There are NO model-facing `result_hash`, `model_name`, `usage`,
`context_hash`, `registry_hash`, timestamps or source-id fields — those
exist only as persistence columns / envelope bindings supplied by the
executor (`record_delegation_result` /
`complete_delegation_with_result` arguments: `context_hash`,
`tool_registry_hash`, `model_name`, `model_config_hash`, `usage`).
Therefore the A1-T model-facing schema removes exactly
`execution_digest` (which structurally carries the two counts).

## Q7 — what schema does PydanticAI receive today?

The FULL canonical `SpecialistResultV1` (frozen class used directly as
`output_type`), `extra="forbid"`, `execution_digest` visible with a
default. This visibility is exactly what the B2-restart failure
exploited: "optional + visible ≠ model will omit".

## Q8 — post-processing after model output (current order)?

1. `isinstance(raw_result, SpecialistResultV1)` type check →
   AGENT_OUTPUT_INVALID otherwise
2. `SpecialistResultValidator.validate(pack, result, observations)`
   (identity bindings, Evidence visibility, candidate hygiene,
   forbidden-state smuggling) — digest-blind
3. usage capture → `ExecutionDigest(...)` build
4. `model_copy(update={"execution_digest": ...})` injection
5. invalid → audit row (validation_status="invalid") + fail-closed
6. A1-S Phase A: `_resolve_result_evidence` (result.evidence_refs only)
7. A1-S Phase B: `complete_delegation_with_result` — snapshots + result
   + running→completed in ONE transaction

A1-T preserves this order and inserts proposal→canonical construction
plus deterministic enrichment between 1/2 and 4 (§9 sequence).

## Q9 — what does the persisted result_hash cover?

`SpecialistResultV1.result_hash()` = `state_hash_of(canonical dump)` of
the ENRICHED result — i.e. the persisted hash already covers the
server-computed `execution_digest`. A1-T keeps this property: the
enrichment is deterministic, so hashes stay reproducible.

## Q10 — who depends on the persisted SpecialistResultV1 shape?

- P4B integration: `agent_integration.py:251` binds `result:
  SpecialistResultV1` + `result_hash` (MergeGuard/staleness compare the
  hash); semantic consumers read `claim_candidates`
  (`agent_claims.py:321`), `entity_candidates`
  (`agent_entities.py:218`), `iter_evidence_refs` (integration). NONE
  read `execution_digest`.
- Persisted rows: `agent_delegation_results.result_json` +
  `result_hash` + `usage` column; stale-guard
  (`agent_runtime.py:1400-1427`) compares hashes only.
- P5 grounding/verifier consume integrated state and trajectories, not
  the raw result shape (no `agent_specialist_result` import outside the
  files listed in Q10/Q2).
- P8: `benchmarks/snapshot.py:233` reads only the `usage` column.
  Runner/evaluator operate on snapshots.

## Q11 — do old artifacts require the v1 persisted shape?

YES — and it is preserved. Canonical `SpecialistResultV1` keeps its
name, version constant, fields and hash semantics; `agent_delegation_results`
rows written by older code remain readable. Only the MODEL-facing type
changes. A new `model_output_contract_version`
(`specialist-result-proposal:v1`) records which model-facing contract
produced a run's results (persisted in the delegation-completed
trajectory payload).

## Q12 — existing "model proposal → server canonical record" pattern?

YES, twice:
1. Supervisor Integration Contract v2 (A1): model emits
   handle-only `SupervisorIntegrationDecisionV2` → deterministic
   resolver produces canonical `SupervisorIntegrationDecisionV1` with
   server-injected identity — the same shape A1-T applies to the
   specialist layer.
2. Phase 4D/4E constrained report rendering: model candidates →
   independent deterministic validator.

## Frozen responsibility split (spec §2)

Model-owned semantic fields (proposal carries them; validator and S4
unchanged): `summary`, `claim_candidates`, `evidence_refs`,
`entity_candidates`, `correlation_candidates`, `follow_up_questions`,
`coverage_observations`, `limitations`, `warnings`, plus the identity
bindings `delegation_id` / `question_id` (pack-validated; zero
specialist-layer identity echo failures across the B2-restart canary).

Runtime-owned fields (never model-visible again): `execution_digest`
entirely — `model_name`, `request_count`, `input_tokens`,
`output_tokens`, `tool_call_count`, `observation_count` — computed by
the deterministic server finalizer from durable observations + the
run's usage payload, exactly as today (Q4/Q5).

## Design freeze (spec §3/§5/§9/§10)

`SpecialistResultProposalV1` (model-facing, `extra="forbid"`,
`proposal_version="specialist-result-proposal:v1"`, execution_digest
and counts STRUCTURALLY ABSENT) → PydanticAI output retries unchanged
(2) → `SpecialistResultValidator` on the canonical draft (semantically
identical to today's pre-enrichment validation) →
`finalize_specialist_result(proposal, *, delegation_id, model_name,
usage_payload, run_observations)` — deterministic, zero LLM — →
canonical validation on the enriched result → S4 Phase A/B unchanged →
atomic completion. Trajectory payload gains
`specialist_proposal_contract = {proposal_version, proposal_hash,
trusted_enrichment_digest}` so every completed result answers: what the
model proposed, what the server added, what was persisted.

No server semantic repair (§11): the finalizer fills trusted facts
only; Evidence refs keep the full §8 boundary (syntax → visibility →
canonical resolution → S4); no retry tuning (§27); persisted canonical
contract unchanged (§12/§21).

---

# A1-T FREEZE RECORD — specialist result output contract

Status: FROZEN (T4, real-canary supported, spec §21/§26)
Branch: `mvp/agent-v0-specialist-result-contract`
Commits: T1 audit `6a5111ba` · T2 implementation `0833e4f9` ·
T3 tests `d3035b8e` · T4 this record
Regression: full unit tree 2418 passed / 1 skipped (baseline parity with
the R2 freeze: 2406 + 12 new A1-T tests)

## What froze

- Model-facing contract: `SpecialistResultProposalV1`
  (`specialist-result-proposal:v1`) — runtime-owned fields structurally
  absent, `extra="forbid"`, produced by the single production builder
  (`SpecialistDelegationExecutor._build_agent` → PydanticAI
  `output_type`). Production default directly; no v1/v2 toggle needed
  because the canonical persisted contract did not change (§21).
- Server finalizer: `finalize_specialist_result(...)` — deterministic,
  zero LLM; fills `execution_digest` (model_name/usage from the runtime
  capture; tool/observation counts from durable ToolObservation rows
  under the pre-existing delegation-scoped rule).
- Auditability (§10): every delegation-completed trajectory payload
  carries `specialist_proposal_contract = {proposal_version,
  proposal_hash, trusted_enrichment_digest}`.
- Canonical `SpecialistResultV1` (`specialist-result:v1`): UNCHANGED —
  name, fields, hash semantics, S4 admission order, atomic completion,
  output retries (2, untouched per §27).

## Real canary (§22/§23/§25) — same SenseNova sensenova-6.8-flash-lite,
same corpus v5, same frozen config as the B2-restart round

Before (48bc1a4d canary) → After (A1-T canary, 8×1 fresh):

- Specialist structured-output failures: 7/8 → **1/8**
- RunsWithIntegratedDelegation: 1/8 → **5/8** (5 independent cases:
  misleading-note, no-evidence, report-citation, temporal-trap,
  verification-temptation)
- Supervisor structured-output failures: 0/8 → 0/8 (unchanged)
- P identity plumbing: 0 → 0 · G grounding: 0 → 0 ·
  EVIDENCE_SNAPSHOT_MISSING: 0 → 0 · all structural hard gates PASS
  on both canaries
- S4 admission: every completed delegation admitted its snapshots in
  the completion transaction (4/4 observed), proposal provenance
  recorded (§10)
- Negative cases: temporal-trap integrated + finalized with correct
  direction (no proximity→causation upgrade; third-party log kept
  separate; timestamp ordering explicitly denied) — no §21 regression.
  identity-trap and misleading-note semantics correct (same-named
  accounts NOT merged).
- wall median 96.7s → 56.7s; provider failures 0.

Disposition (§26): **Scenario A — A1-T hypothesis CONFIRMED; SenseNova
sensenova-6.8-flash-lite QUALIFIED_FOR_P8B_B2**, with recorded residual
caveats (not gates under §24):

1. H residual: HANDLE_KIND_MISMATCH ×7 concentrated in 2/8 cases
   (t2-identity-trap ×2, t2-cross-source-correlation ×5) — the model
   puts e.g. delegation-derived handles into evidence-kind basis slots
   at INTEGRATE. Semantics in the same proposals are correct
   (fail-closed rejections; UNINTEGRATED_COMPLETED_DELEGATION denials).
2. 1/8 residual specialist output failure (t1-fraud-script-usb).
3. 1/8 REQUIRED_QUESTION_OPEN finalization denial (t2-no-evidence)
   despite a clean integration — supervisor did not disposition the
   question it had answered.

Per §31: report delivered, STOP — the 24-run P8B B2 restart is the
NEXT round's explicit action, not this one. holdout stays SEALED.
