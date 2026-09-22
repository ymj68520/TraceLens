# Agent v0 Phase 1 — Runtime Persistence Foundation

Implementation record. Architecture source of truth:
`docs/specs/agent-architecture-v0.md` (TraceLens Agent Architecture v0,
frozen baseline). This document records what Phase 1 (P1) implemented on top
of the current repository; it does not restate the architecture.

## Baseline / Branch

```text
baseline branch : mvp/phase1-acceptance
baseline HEAD   : d78524a7656d4bd22336685fffee902e04be175b
dev branch      : mvp/agent-v0-phase1-runtime-foundation
docs baseline   : 6632d93a (docs: add TraceLens Agent Architecture v0 baseline)
```

## Repository facts discovered (pre-implementation)

- The task-owned `data/tasks/<task_id>/investigation.db` is owned by
  `httpserver/services/investigation/repository.py`
  (`InvestigationRepository`), `PRAGMA user_version = 7` before P1, with a
  per-step explicit `BEGIN IMMEDIATE` migration chain
  (`_migrate_vN_to_vN+1`), atomic fresh-store init, strict validation
  (`_validate_*_schema`), self-healing auxiliary objects, and a fail-closed
  `open_existing()` constructor (URI `mode=rw`, no create/heal).
- `httpserver/services/investigation_persistence.py`
  (`InvestigationPersistence`, user_version 3) is the LEGACY workbench
  persistence; it explicitly skips repository-owned stores (`>= 7`). P1 did
  not change its semantics, only widened that skip guard.
- Task liveness / trusted-path boundary: `investigation/paths.py`
  (`investigation_db_path_for_task`) + `investigation/live_store.py`
  (`open_live_task_store`) revalidate task existence and store identity at
  every terminal write. P1 reuses this unchanged.
- Restart-recovery pattern: executors implement `initialize()` with a stale
  sweep (`list_stale_analyses`, `list_stale_event_refreshes`), called by
  `ServiceManager._initialize_services()`; `shutdown()` drains tracked
  asyncio tasks. Existing error code convention: `service_restart`.
- Tests: `python_service/pytest.ini`; focused suites under
  `python_service/tests/unit/investigation/` with a shared
  `investigation_v7_baseline` fixture pinning the current schema version.

## Schema migration

```text
before : user_version = 7
after  : user_version = 8   (SUPPORTED_SCHEMA_VERSION = 8)
```

Additive v8 migration `_migrate_v7_to_v8` (single `BEGIN IMMEDIATE`
transaction: DDL + version bump, no `executescript`). Fresh stores build
everything via `_initialize_v8_atomically`. Reopen of a current store runs
`_validate_v8_schema` + `_ensure_v8_auxiliary_objects` (idempotent self-heal).
A store with `user_version > 8` (or missing objects) fails closed.

New tables (all task-scoped, composite-FKed onto `agent_investigations`):

| table | purpose |
|---|---|
| `agent_investigations` | Investigation runtime identity + lifecycle (`ready/active/paused/completed/cancelled`, `pause_reason`) |
| `agent_runs` | Agent Run lifecycle (`queued/running/completed/failed/cancelled`, `stop_reason`, `error_code/message`, `idempotency_key`) |
| `agent_working_state_revisions` | append-only Working State revisions (PK `(task_id, investigation_id, revision)`, `state_json`, `state_hash`, `previous_state_hash`, `operation_key`) |
| `agent_delegations` | Delegation lifecycle (`queued/running/completed/failed/cancelled/stale`, `question_ref`, `based_on_state_revision`, `context_hash`, `cancel_requested_at`, `failure_code`, `integrated_at/revision`, `idempotency_key`) |
| `agent_trajectory_events` | append-only Action Trace (`event_id`, `event_type` CHECK, `payload_json`, autoincrement `seq`) |
| `agent_tool_observations` | Tool Observation storage boundary (immutable result rows) |

DB-level guards (same style as existing triggers):

- one active run per investigation: partial unique index
  `idx_agent_run_one_active_per_investigation ... WHERE status IN ('queued','running')`;
- legal-transition triggers for Investigation/Run/Delegation (terminal states
  have no outgoing transitions; `completed` investigations cannot reopen);
- state-field consistency triggers (insert + update) per state machine;
- identity-immutability triggers; no-DELETE triggers on every agent table;
- Working State revisions: strict sequentiality (`revision = MAX+1`) and hash
  chaining (`previous_state_hash` must equal revision N-1's `state_hash`) via
  BEFORE INSERT triggers, plus no-UPDATE/no-DELETE;
- Delegations: terminal rows immutable except exactly one
  `integrated_at/integrated_revision` bookkeeping write on `completed` rows,
  which is composite-FKed onto `agent_working_state_revisions`.

## Added

- `httpserver/services/investigation/agent_runtime.py`:
  `AgentRuntimeRepository` + frozen Pydantic models + enums
  (`AgentInvestigationStatus`, `AgentRunStatus`, `RunStopReason`,
  `DelegationStatus`, `InvestigationPauseReason`,
  `AgentTrajectoryEventType`) + transition tables +
  `AgentRuntimeConflictError` / `WorkingStateRevisionConflictError`.
- P1 domain API (all explicit `BEGIN IMMEDIATE` transactions):
  `create_investigation`, `get_investigation`, `list_investigations`,
  `pause_investigation`, `complete_investigation`, `cancel_investigation`,
  `start_run`, `mark_run_running`, `finish_run`, `fail_run`, `cancel_run`,
  `get_run`, `list_runs`, `admit_delegations`, `start_delegation`,
  `transition_delegation_terminal`, `request_delegation_cancel`,
  `mark_delegation_integrated`, `get_delegation`, `list_delegations`,
  `append_trajectory`, `list_trajectory`, `get_latest_working_state`,
  `get_working_state_revision`, `commit_working_state`,
  `append_tool_observation`, `list_tool_observations`,
  `recover_interrupted_agent_runtime`.
- `tests/unit/investigation/test_agent_runtime_persistence.py` (32 tests).
- `docs/specs/agent-architecture-v0.md` (architecture baseline, separate
  docs commit).

## Modified (minimal, forced by the schema bump)

- `repository.py`: `SUPPORTED_SCHEMA_VERSION 7 -> 8`, v8 DDL + builders +
  `_migrate_v7_to_v8` + `_validate_agent_runtime_tables` (schema owner only).
- `investigation_service.py` `_ensure_v7_store`: migrate v7 stores to v8 via
  the repository, accept version 8 (previously pinned to 7).
- `investigation_persistence.py` `_ensure_schema`: legacy skip guard widened
  from `== 7` to `>= 7` (repository-owned stores must never receive legacy
  DDL).
- `tests/unit/investigation/conftest.py`: baseline pin `7 -> 8`.
- Existing migration tests that pinned the then-current version (`== 7`)
  now pin `== 8` (`test_investigation_completion`, `test_investigation_event`,
  `test_investigation_grounding`, `test_investigation_refresh`,
  `test_investigation_report_evidence`, `test_investigation_secondary`).
  No assertion was weakened; the new-table list in
  `test_new_db_is_current_version_with_report_extension` was extended.

## Reused (unchanged)

`InvestigationRepository` connection policy (`PRAGMA foreign_keys=ON`,
`BEGIN IMMEDIATE`, `mode=rw` existing-only), `canonical_json` serialization
rules (same dump parameters for `canonical_state_json`), `_now_iso` UTC
timestamps, `sa_/ie_/er_`-style id prefixes (`inv_/run_/del_/trj_/obs_`),
composite-FK task scoping (EV1/EV2 pattern), partial-unique one-active pattern
(F10), trigger-guarded state machines (refresh pattern), `EvidenceStoreError`
fail-closed semantics, `live_store.open_live_task_store` boundary for future
executors.

## Runtime invariants (P1)

- `P1-E2/E3`: investigation.db remains the only runtime store; agent tables
  reference canonical objects by opaque id only, never duplicate them.
- `P1-E4`: Investigation / Run / Delegation lifecycles persisted exactly as
  frozen (§15.2 of the architecture), including all eight `RunStopReason`
  values.
- `P1-E5`: one queued/running run per investigation is a partial unique
  index, verified by raw-INSERT rejection in tests.
- `P1-E6`: revisions start at 1 (repo convention: analysis/event versions
  start at 1), are strictly sequential, immutable and hash chained;
  `state_hash = sha256(canonical_state_json(state))` (sorted keys, compact
  separators — deterministic).
- `P1-E7`: trajectory is INSERT-only Action Trace; event types are a CHECK
  enum; ordering is the autoincrement `seq` (deterministic); payloads are
  structured dicts, never model Chain-of-Thought.
- `P1-E8/E9`: admission/commit primitives run in explicit transactions; the
  optimistic guard (`expected_revision`) and idempotency-key content checks
  fail closed (`WorkingStateRevisionConflictError` /
  `AgentRuntimeConflictError`).
- `P1-E11`: every statement is `task_id`-scoped; a wrong-task repository gets
  opaque not-found behavior; terminal writes cannot resurrect a vanished
  store (`open_existing` mode=rw fail closed).
- Run completed != Investigation completed: finishing a run never mutates the
  investigation row; completing the investigation requires active status and
  no active run.

## Recovery semantics

`recover_interrupted_agent_runtime()` (one transaction, deterministic order
runs -> delegations -> investigations):

```text
queued/running Agent Run      -> failed(stop_reason=runtime_restart, error_code=runtime_restart)
queued/running Delegation     -> failed(failure_code=runtime_restart)
active Investigation          -> paused(pause_reason=runtime_restart)
Working State                 -> untouched (last committed revision survives)
```

One `runtime_recovered` trace event per affected investigation; idempotent
(second call returns zeros). Not wired into `ServiceManager` yet: P1 has no
Agent executor service to own background tasks, so startup wiring is deferred
(see below); the primitive is fully tested and callable.

## Focused test commands / results

```text
cd python_service

# P1 focused (new)
.venv/bin/python -m pytest tests/unit/investigation/test_agent_runtime_persistence.py -q
  -> 32 passed

# Investigation persistence / lifecycle regression + adjacent consumers
.venv/bin/python -m pytest tests/unit/investigation/ \
  tests/unit/test_investigation_persistence.py \
  tests/unit/test_investigation_seed_bootstrap.py \
  tests/unit/test_investigation_review_routes.py \
  tests/unit/test_investigation_workbench_routes.py \
  tests/unit/test_investigation_read_routes.py \
  tests/unit/test_investigation_refresh_routes.py \
  tests/unit/test_claim_provenance_reader.py \
  tests/unit/forensic_report/ \
  tests/unit/test_startup_reliability.py \
  tests/unit/test_database_events_route.py -q
  -> 653 passed, 0 failed (no pre-existing failures observed)

# static sanity
.venv/bin/python -m py_compile <all touched modules>  -> OK
```

## Known limitations

- No orchestrator: transitions are repository primitives driven manually (in
  tests) — by design for P1.
- `pause_investigation` cancels the active run (cooperative
  `cancel_requested_at` on its delegations); delegation executors do not exist
  yet, so the terminal observation of a cancel request is test-driven.
- Idempotency-key replay for delegations validates `question_ref` content;
  richer request-fingerprint binding is deferred until the Delegation contract
  (profile/skill/toolset versions) exists.
- `complete_investigation` is a deterministic transition only — the
  FinalizationGate semantic preflight is Phase-later work and does not exist
  in P1.
- Working State `state_json` is an opaque canonical-JSON dict in P1; the
  versioned Pydantic Working State schema arrives with the control plane.

## Deferred to Phase 2 (control plane)

- `ServiceManager` wiring of agent runtime recovery into an
  `AgentOrchestrator` executor (`initialize()`/`shutdown()` pattern), and the
  `mvp/agent-v0-phase2-control-plane` branch.
- Orchestrator main loop (PLAN/EXECUTE/INTEGRATE/EVALUATE), real Delegation
  executors, continuation provenance (`continues_from`) columns if/when
  frozen.
- Any HTTP surface (P1 added none) and any frontend change (none).
