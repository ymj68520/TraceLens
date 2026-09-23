# TraceLens Agent v0 — Phase 4A: Agent Execution Foundation

Status: implemented on `mvp/agent-v0-phase4-investigation-loop`.

## 1. Baseline / Branch / Commits

- P3 frozen baseline: `d132ec3a` (post freeze-follow-up, schema v10)
- Branch: `mvp/agent-v0-phase4-investigation-loop` (created from the P3 frozen HEAD)
- Commits:
  - `b3d2ad56` — `feat: add specialist result contract and validation` (P4A-1)
  - `fa5dbf6a` — `feat: add agent delegation execution` (P4A-2)
  - (P4A-3) — `feat: wire specialist runtime execution` (ServiceManager lifecycle, offline e2e, docs, regression gate)

## 2. Repository findings

- P2 Orchestrator EXECUTE is admission-only (confirmed): `admit_run` / `admit_delegations` freeze identity and never execute. P4A adds exactly one capability at that point — real delegation execution — and nothing Supervisor-shaped.
- Delegation lifecycle primitives reused unchanged: `start_delegation` (queued→running), `transition_delegation_terminal` (completed/failed/cancelled/stale; `failed` requires a failure code), `request_delegation_cancel` (cooperative `cancel_requested_at`), `mark_delegation_integrated` stays P4B.
- P3 `build_specialist_agent(pack, registry, *, model)` extended with `output_type` / `retries` (defaults preserve the P3 signature); platform differences still come only from Profile + Skill + ContextPack — one factory, no per-platform agent classes.

## 3. Added

```
httpserver/services/investigation/
    agent_specialist_result.py    SpecialistResultV1 + candidates + validator + violation codes
    agent_specialist_executor.py  DelegationExecutionEnvelope + failure mapping +
                                  SpecialistDelegationExecutor (cancellation, retry, batch)
```

Modified: `agent_context.py` (`OUTPUT_CONTRACT_REF = "specialist-result:v1"` replaces the P4 placeholder; pack carries `question_id`), `agent_tools/pydantic_bridge.py` (typed output factory), `agent_runtime.py` (DelegationResult model + `record_delegation_result` / `complete_delegation_with_result` primitives), `repository.py` (v11), `service_manager.py` (executor lifecycle), `investigation_service.py` (v10 store gate).

## 4. SpecialistResultV1 (P4A-E2/E3)

`specialist-result:v1` — frozen, version-checked, `extra="forbid"`: `delegation_id`, `question_id`, `summary`, `claim_candidates[]` (assertion_class ∈ FACT/INFERENCE/HYPOTHESIS), `evidence_refs[]`, `entity_candidates[]`, `correlation_candidates[]`, `follow_up_questions[]`, `coverage_observations[]`, `limitations[]`, `warnings[]`, `execution_digest` (model name, request/token counts — None when unavailable, never fabricated). Deterministic `result_hash()`. Every candidate is a PROPOSAL: the contract structurally carries no review/decision/finding fields, and the validator rejects any smuggled payload carrying them. Assertion ceiling, grounding, entity merge and correlation stay in P5.

## 5. Evidence visibility enforcement (P4A-E4)

`SpecialistResultValidator` (deterministic, no case semantics) reconstructs `allowed_evidence_ids = ContextPack initial refs ∪ successful ToolObservation refs` from durable records and requires EVERY ref in the result (top level and inside all candidates) to be inside it. Real-but-unexposed → `RESULT_EVIDENCE_NOT_VISIBLE`; guessed-but-well-formed → same; malformed → `RESULT_EVIDENCE_REF_INVALID`; cross-task (injected seam) → `RESULT_EVIDENCE_CROSS_TASK`. No auto-acquisition of Evidence exists anywhere in P4A.

## 6. Violation codes

`RESULT_VERSION_UNSUPPORTED, RESULT_DELEGATION_MISMATCH, RESULT_QUESTION_MISMATCH, RESULT_EVIDENCE_REF_INVALID, RESULT_EVIDENCE_NOT_VISIBLE, RESULT_EVIDENCE_CROSS_TASK, RESULT_DUPLICATE_CANDIDATE_ID, RESULT_CANDIDATE_TEXT_INVALID, RESULT_SCOPE_EXPANSION_NOT_ALLOWED, RESULT_REVIEW_STATE_FORBIDDEN, RESULT_GRAPH_STATE_FORBIDDEN, RESULT_REPORT_STATE_FORBIDDEN`. Messages never contain DB paths, stack traces or internals.

## 7. DelegationExecutionEnvelope (P4A-E7)

Frozen at dispatch (§14): delegation/run/investigation/task identity, question id + snapshot text, `based_on_state_revision/hash`, source/time scopes, profile id/version, skill bindings, `tool_registry_hash`, the embedded ContextPack + `context_hash`, allowed tool ids, budget policy, `model_config_digest` (normalized adapter config — never the API key), `output_contract_ref` (validator-enforced to `specialist-result:v1`), `created_at`. `execution_input_hash()` covers all of it (§42). The running PydanticAI call reads only the envelope; no hot context updates (§15). Pre-execution `verify_envelope_bindings` re-checks pack hash / profile / skills / registry hash / three-way source-scope agreement (§34) and fails closed with `input_contract_changed`.

## 8. Executor (P4A-E8..E13)

`SpecialistDelegationExecutor.dispatch_delegation(envelope)`: trusted task lookup → `open_existing` (vanished task ⇒ SKIPPED, no terminal write anywhere) → terminal/cancelled pre-checks (cancel before start ⇒ `cancelled`, zero agent calls) → binding verification → `start_delegation` → real PydanticAI run (`output_type=SpecialistResultV1`, instructions from `pack.layered_view()`, registry toolset) → validate → persist. Cancellation is cooperative with three checkpoints (before start / before run / before terminal persistence); a late result after cancel is discarded from the semantic channel — cancel wins (§28). Restart never resumes an agent conversation: P2 recovery terminalizes running delegations as `failed(runtime_restart)` and executor `initialize()` only does lifecycle setup (§29-30).

Failure mapping (§13): 402→`agent_billing_unavailable` (never recorded as an evidence conclusion), 401/403→`agent_auth_failed`, 429→`agent_rate_limited`, 5xx→`agent_provider_unavailable`, timeouts→`agent_timeout`, contract/validator violations→`agent_output_invalid` (invalid results are still persisted with `validation_status="invalid"` for audit), registry errors→`agent_tool_failure`, everything else→`agent_internal_failure`; plus `input_contract_changed` for binding mismatches. Retryable (timeout/429/5xx) get bounded provider retries; auth/billing/model errors never retry (§40). All retry counts are `AgentRunPolicy` config, provisional, P8-calibrated.

## 9. Result persistence (P4A-E10, schema v11)

`agent_delegation_results` (minimal additive v10→v11): composite FKs into the agent runtime tables, `UNIQUE(task_id, delegation_id)` (one terminal result per delegation), INSERT-only (no-UPDATE / no-DELETE triggers), stores `result_version/result_json/result_hash/context_hash/tool_registry_hash/model_name/model_config_hash/usage_json/validation_status`. `complete_delegation_with_result` makes the row and the delegation's `completed` transition ONE transaction — a completed delegation always has exactly one valid result row. Nothing is written to SecondaryAnalysis/Claim/Event/Report/Graph (P4A-E16). A `SpecialistResult` is not Evidence: only its cited refs matter, and only via the visibility rule (§23).

## 10. Parallel execution (P4A-E14/E15)

`execute_batch(envelopes, mode="parallel_all"|"sequential", max_parallel=...)` — asyncio.Semaphore, N from `AgentRunPolicy.max_parallel_delegations` (config, not frozen); one worker's failure never cancels another; all workers are read-only so no semantic write coordination exists in P4A.

## 11. ServiceManager wiring (§57)

`specialist_delegation_executor` service: factory + `initialize()`/`shutdown()` + cleanup-plan/rollback entries. `initialize()` is lifecycle setup only — queued delegations are consumed exclusively by explicit `dispatch_delegation`/`execute_batch` calls (P4B will attach the orchestrator loop; the P2 PLAN/EXECUTE shell is unchanged).

## 12. Tests

`test_agent_specialist_result.py` (18), `test_agent_specialist_executor.py` (23, incl. §49 offline e2e through a REAL pydantic_ai TestModel agent and the F1 binding matrix), `test_agent_schema_v11_migration.py` (5). All offline (TestModel / duck-typed offline agents over the real registry); no default-gate test touches a real provider (§48/§56).

## 13. Known limitations / P4B deferred

- Cancellation cannot interrupt a provider call mid-flight (§27's "if feasible" clause); the run finishes and the late output is discarded. No mid-run cancel polling between tool calls.
- (resolved by the P4A freeze follow-up) Skill bindings are exact id+version pairs everywhere — see §7b.
- Executor does not yet attach to the AgentOrchestrator loop — dispatch is explicit (P4B boundary).
- Live provider smoke stays opt-in and is not a freeze gate; the DeepSeek account billing state is unchanged.
- P4B owns: AttentionSet→Supervisor→SupervisorDecision→DecisionValidator→admission loop, MergeGuard, IntegrationContextPack, integration mode, Typed TransitionProposal → StateTransitionPolicy → Working State revisions, progress evaluation, re-plan/finalization.
