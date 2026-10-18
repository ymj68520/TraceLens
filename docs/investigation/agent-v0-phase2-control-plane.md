# Agent v0 Phase 2 — Deterministic Control Plane

Implementation record. Architecture source of truth:
`docs/specs/agent-architecture-v0.md` (§29: frozen eight-phase plan; this is
P2 — Deterministic Control Plane). P1 record:
`docs/investigation/agent-v0-phase1-runtime-foundation.md`.

## Baseline / Branch

```text
baseline (P1 frozen HEAD) : 04d9408892551bd8e480e3ce9698f7c3e2ffb497
branch                    : mvp/agent-v0-phase2-control-plane
commits                   : P2-1 deterministic working state policies
                            P2-2 deterministic finalization gate
                            P2-3 control plane orchestrator shell
```

First hard constraint held throughout: **only the deterministic control
plane — no PydanticAI installed or imported, no LLM call, no
Supervisor/Specialist/Correlation/Verifier agent, no Tool Registry, no
agent-backed delegation execution.** Admitted actions only mean "legal —
executable by a future P4 executor".

## Repository facts (re-checked at P1 frozen HEAD)

- P1 `AgentRuntimeRepository` primitives (lifecycle, revisions, trajectory,
  recovery) on `investigation.db` v8; `InvestigationPauseReason` was
  `{user_paused, runtime_restart}`; trajectory CHECK enum had 17 types.
- Trusted task enumeration for the recovery sweep follows the
  `SecondaryAnalysisExecutor` pattern (`cpp_backend.list_tasks` paging ->
  `get_task` -> `investigation_db_path_for_task` -> `open_existing`).
  No filesystem task scanning anywhere.
- ServiceManager executor pattern: `_create_*` factory + `initialize()`
  (recovery) with `optional_service_init_timeout`, ready flag,
  `_service_cleanup_plan()` / `_rollback_initialization()` entries,
  `_clear_services()` reset, read property with
  `_require_service_access()`.

## Schema migration

```text
before : user_version = 8
after  : user_version = 9    (SUPPORTED_SCHEMA_VERSION = 9)
```

- Additive: `agent_finalizations` — immutable FinalizationRecord table.
  `UNIQUE(task_id, investigation_id)` (one successful finalization per
  investigation), composite FKs onto `agent_investigations`, `agent_runs`
  and `agent_working_state_revisions(task_id, investigation_id, revision)`,
  no-UPDATE / no-DELETE triggers.
- CHECK extensions via single-transaction table rebuilds (rows preserved,
  `PRAGMA foreign_keys=OFF` for the rebuild, triggers recreated, AUTOINCREMENT
  sequence preserved): `agent_investigations.pause_reason` +=
  `finalization_review_unavailable` (P2 §34); `agent_trajectory_events.event_type`
  += 9 control-plane events (`attention_compiled`,
  `transition_decision_validated`, `transition_decision_rejected`,
  `working_state_integrated`, `no_progress_detected`,
  `finalization_requested`, `finalization_denied`, `finalization_stale`,
  `finalization_completed`).
- Version pins updated where the migration chain endpoint moved (conftest,
  existing migration tests pin the then-current version; assertions
  strengthened, none weakened; future-version fail-closed test now pins 10).

## Added

- `agent_working_state.py` — `AgentWorkingStateV1`
  (`schema_version="agent-working-state:v1"`): questions (priority
  required/high/normal/exploratory; status open/in_progress/answered/
  unresolved/blocked/deferred/superseded; disposition
  supported/not_supported/inconclusive/unavailable/not_applicable;
  blocks/supports/explores relations; closure fields), coverage
  (not_started/in_progress/covered/partial/unavailable/not_applicable),
  refs-only evidence working set (candidate/relevant/high_value/irrelevant),
  hypotheses, contradictions (low/material/critical;
  open/resolved/explained/unresolved), directive ref/digests, pending
  verification placeholders (pending/passed/failed/unavailable), refs-only
  finding/entity/proposal lists, progress/budget bookkeeping. Refs and
  investigation semantics only — no Evidence content, canonical copies,
  Graph payloads, conversations, or CoT.
- `agent_transitions.py` — frozen typed transition family
  (QuestionTransition, CreateQuestion, EvidenceRelevanceTransition,
  AddEntityReference, CreateHypothesis, HypothesisTransition,
  CreateContradiction, ContradictionTransition, CoverageTransition,
  AddFindingReference, AddPendingProposalReference, and the contract-only
  ModifyScope placeholder) + `StateTransitionPolicy`
  (`state-transition:v1`): pure deterministic, all-or-nothing batch
  evaluation, stable violation codes (P2 §17), idempotent-duplicate noop.
- `agent_attention.py` — `AttentionBuilder` (`attention-policy:v1`): P0
  CONTROL … P5 EXPLORATORY bands, blocks-only transitive priority
  propagation (intrinsic priority kept separate), explicit-id deterministic
  coalescing (question+coverage, verification→question item with P1 raise),
  evidence-gated P5 (ref-less leads never enter), eligibility
  eligible/blocked/suppressed with blocked_by/reason codes,
  investigation-level `eligible_action_types` only,
  deterministic content hash; `build_full_set` + separate
  `build_window(full_set, config)`; `AttentionPolicyConfig` carries all
  calibration knobs (window size, exploration allowance, budget-exhausted
  suppression). Never persisted as canonical state.
- `agent_progress.py` — `NoProgressDetector` (`no-progress-policy:v1`):
  semantic state-diff progress (new relevant evidence, question/coverage
  advancement, contradiction change, finding refs, hypothesis change);
  progress/budget bookkeeping excluded from the diff; threshold from
  `NoProgressPolicyConfig` (calibration, no canonical N).
- `agent_finalization.py` — `FinalizationGate` (`finalization-policy:v1`)
  + atomic commit support: hard blockers (P2 §29), required question /
  coverage / contradiction closure rules (§30-§32), capability failure
  policy integrity_critical/semantic_required/optional_enhancement (§33),
  best_effort/required final semantic review policy (§34) with external
  `FinalSemanticReview` input (P2 never runs a verifier), STALE on revision
  mismatch, PASS -> complete / complete_with_limitations.
- `agent_orchestrator.py` — `AgentOrchestrator` deterministic shell:
  `initialize()`/`shutdown()`, `create_investigation` (typed v1 state),
  `admit_run`, `prepare_cycle` (PLAN: typed state load + AttentionSet +
  `attention_compiled` audit with policy version/revision/hash),
  `validate_action_batch` (EXECUTE admission validation only: active
  investigation/run, current revision, allowed action family, question
  exists, duplicate delegation fingerprint incl. in-batch), 
  `integrate_transitions` (INTEGRATE: policy -> optimistic
  `commit_working_state` -> `transition_decision_validated` +
  `working_state_integrated`; fail-closed rejection trajectory),
  `evaluate_progress` (deterministic snapshot + `no_progress_detected`
  trajectory audit + run stop `no_progress` at threshold; never touches the
  Working State revision), `evaluate_finalization`/`finalize`
  (gate + atomic commit; `pause_on_required_review_unavailable`),
  `pause`/`cancel`. Trusted task lookup only; `open_existing` for every
  control write; investigation creation may establish the store (E1
  pattern) from the trusted path.
- `AgentRuntimeRepository.record_finalization` / `get_finalization` —
  atomic Finalization Commit (P2 §37): one BEGIN IMMEDIATE revalidates
  active investigation + revision/hash + run status, inserts the immutable
  record, completes the RUNNING run (`stop_reason=finalized`), completes
  the investigation, appends `finalization_completed`; any failure rolls
  everything back. A queued run is never implicitly promoted to running
  during finalization (freeze follow-up F2). P1's
  `complete_investigation()` remains a low-level primitive and is never a
  finalization pathway (§38 option A).
- Tests: `test_agent_control_plane.py` (39), `test_agent_finalization.py`
  (20), `test_agent_orchestrator.py` (15).

## Modified (minimal)

- `repository.py`: v9 schema owner changes only (DDL/migration/validation,
  `SUPPORTED_SCHEMA_VERSION = 9`).
- `agent_runtime.py`: trajectory enum + pause reason extended (matching the
  v9 CHECKs), `FinalizationRecord` model + `record_finalization`, revision
  lookup by operation key.
- `investigation_service.py` `_ensure_v7_store`: accepts 7/8 -> migrate to
  current (9) — same seam as the P1 bump.
- `service_manager.py`: `_agent_orchestrator` + ready flag, factory,
  property, init block after EventRefreshExecutor (inside
  `_cpp_backend_ready`), shutdown/rollback/cleanup plans, `_clear_services`.

## Reused

P1 repository/transaction/idempotency machinery (`commit_working_state`
optimistic guard, operation keys, trajectory append, recovery primitive),
`parse_evidence_key` + the existing evidence snapshot/event/analysis reads
for policy seams (no second resolver), `investigation_db_path_for_task`,
`open_existing` boundary, executor lifecycle pattern, existing test
conventions.

## Test commands / results

```text
cd python_service

# P2 focused
.venv/bin/python -m pytest tests/unit/investigation/test_agent_control_plane.py \
  tests/unit/investigation/test_agent_finalization.py \
  tests/unit/investigation/test_agent_orchestrator.py -q
  -> 74 passed

# P1 focused regression
.venv/bin/python -m pytest tests/unit/investigation/test_agent_runtime_persistence.py -q
  -> 32 passed

# Investigation suite (incl. v9 migration matrix)
.venv/bin/python -m pytest tests/unit/investigation/ -q
  -> 484 passed

# ServiceManager lifecycle / startup reliability
.venv/bin/python -m pytest tests/unit/test_startup_reliability.py \
  tests/unit/test_service_manager_report_lifecycle.py -q
  -> 21 passed

# static sanity: py_compile over all touched modules -> OK
```

## Runtime invariants

- One semantic commit -> exactly one revision increment (W12), committed
  only through the P1 optimistic-guard API.
- Illegal transitions reject the whole batch; the policy never performs
  semantic auto-correction (a rejected `answered` is never silently turned
  into `unresolved`).
- AttentionSet is a projection: nothing persisted except the
  `attention_compiled` audit trail event (policy version, state revision,
  attention hash, item count) — enough to answer "why did the Supervisor
  see these items" later.
- Calibration (P1 internal ordering, window size, exploration allowance,
  no-progress threshold, batch size) lives in injected config objects; no
  architecture constants hardcoded; P1-vs-P1 band order stays
  deterministic-by-item-id with no semantic winner.
- Finalization atomicity: no path can leave `Investigation completed`
  without its immutable FinalizationRecord (unique constraint + single
  transaction + trigger immutability).
- `completed` remains a no-outgoing terminal; `continues_from` untouched.
- Policy versioning (`state-transition:v1`, `attention-policy:v1`,
  `finalization-policy:v1`, `no-progress-policy:v1`,
  `agent-working-state:v1`) recorded in trajectory payloads, the
  FinalizationRecord, and state validation.

## Known limitations

- EXECUTE is admission-only; no worker consumes admitted actions in P2
  (fake/manual outcomes drive tests).
- Final semantic review is an external input; the real verifier arrives in
  P5. Until then `required` + `unavailable` denies (with the documented
  pause path) and `best_effort` + `unavailable` completes with limitations.
- `request_graph_admission` actions validate but have no P2 consumer;
  Graph admission semantics are P6.
- Working State v1 still carries no Charter/Question provenance objects
  beyond refs; Charter/Directive canonical persistence remains Architecture
  TBD.
- The no-progress streak is run-level runtime bookkeeping audited through
  trajectory events; it is intentionally not recovered across restarts
  (a restarted run terminalises as `failed(runtime_restart)`).

## Freeze follow-up: state semantics tightening

Working State revisions are semantic, not cycle bookkeeping:

- A revision grows only through semantic state mutation (Question, Coverage,
  Evidence Working Set, Hypothesis, Finding ref, Contradiction,
  directive/scope semantic state). Progress counters, no-progress streaks,
  cycle numbers, attention compilation, tool/operation noise, runtime
  bookkeeping and budget observations never consume a revision.
- Progress/no-progress bookkeeping does not consume revisions:
  `evaluate_progress` compares committed revisions deterministically, emits
  `ProgressSnapshot` facts into the trajectory
  (`no_progress_detected` payloads carry the streak, threshold and state
  revision) and keeps the streak in run-level runtime bookkeeping.
  `AgentWorkingStateV1.progress_state` remains for schema compatibility but
  is never updated without another semantic mutation.
- Finalization requires a running Agent Run: `running ->
  completed(stop_reason=finalized)` is the only finalization path. A queued
  run (admission only, no started investigation loop) is DENYed by the gate
  (`FINALIZATION_RUN_NOT_RUNNING`) and refused by the atomic commit;
  failed/cancelled/completed runs cannot finalize. No schema change was
  required for either tightening (no v10).

## Deferred to P3/P4

- P3 (PydanticAI + read-only Tool/Skill substrate): PydanticAI thin adapter,
  ToolDefinition/ToolRegistry, canonical read-only tools,
  SourceCapabilityManifest, SourceSpecialist profiles, SkillResolver,
  ContextAssembler. Still no canonical mutation from agents.
- P4 (Agent Investigation Loop): Supervisor, Specialist, real agent-backed
  delegation execution consuming admitted P2 action envelopes, bounded
  parallelism, NoProgress-driven re-plan wiring into real runs.
