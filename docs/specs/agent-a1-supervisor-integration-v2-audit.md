# A1 Repository Investigation — Supervisor Integration Contract v2

Status: AUDIT COMPLETE (pre-implementation gate, spec §27)
Branch: `mvp/agent-v0-supervisor-integration-v2` (from `c87641db`)
Baseline runtime: `946f325e` (frozen P8B measurement baseline; A1 changes
the supervisor/model interface only — every §1 invariant listed at the end
stays byte-identical).

---

## 1. The 13 questions (spec §27), answered from code

### Q1. Current Supervisor proposal exact schema

Two decision schemas exist:

**PLAN** — `SupervisorPlanDecisionV1`
(`httpserver/services/investigation/agent_supervisor.py:275`):
`decision_version, task_id, investigation_id, run_id, based_on_state_revision,
based_on_state_hash, attention_hash, actions[DelegateInvestization|
RequestFinalization|NoPlanAction], summary, warnings, limitations`.
`DelegateInvestigation` carries `action_id, attention_item_id, question_id,
source_scope_id, time_scope, investigation_intent, execution_group`.

**INTEGRATE** — `SupervisorIntegrationDecisionV1`
(`agent_integration.py:308`):
`decision_version, task_id, investigation_id, run_id, based_on_state_revision,
based_on_state_hash, source_result_ids, source_result_hashes,
transition_proposals[P4BTransitionProposal], integration_summary, limitations,
warnings`. (Note: `source_result_ids` is declared twice at lines 323–324 —
harmless duplicate, cleaned up in v2.)

`P4BTransitionProposal` (`agent_integration.py:45`) = the typed P2 transitions:
`QuestionTransition, CreateQuestion, EvidenceRelevanceTransition,
CreateHypothesis, HypothesisTransition, CreateContradiction,
ContradictionTransition, CoverageTransition, AddPendingProposalReference,
AddFindingReference` (`agent_transitions.py:229–291`).

### Q2/Q3. Which fields are semantic decisions vs trusted identity echo

**Pure trusted-identity echo (model copies, server already knows):**

| field | decided by model | enforced by |
|---|---|---|
| `task_id/investigation_id/run_id` (both decisions) | echo | `PLAN_IDENTITY_MISMATCH` (agent_supervisor.py:388), `INTEGRATION_IDENTITY_MISMATCH` (agent_integration.py:424) |
| `based_on_state_revision/hash` (both) | echo | `*_STATE_REVISION_STALE` |
| `attention_hash` (plan) | echo of 64-hex | `PLAN_ATTENTION_HASH_MISMATCH` (supervisor.py:407) |
| `source_result_ids/hashes` (integrate) | echo of delegation UUID + result hash pairs | `INTEGRATION_SOURCE_RESULT_UNKNOWN/_HASH_MISMATCH` (integration.py:444–463) |

Decisive finding: at commit time the orchestrator builds
`delegation_integrations` **from `fresh_envelopes`, not from the decision**
(`agent_orchestrator.py:1584–1589`). `source_result_ids/hashes` are pure
transcription burden — the commit path never reads them.

**Semantic decisions (real model responsibility):** transition dispositions
and statuses, question text/priority on create, closure basis selection
(which evidence supports closure), limitations/summaries, hypothesis and
contradiction semantics, finding/proposal references (which artifact),
coverage status with basis, integration summary.

**Identity-shaped fields embedded INSIDE semantic transitions** (the model
must transcribe canonical strings to express a semantic choice):
`QuestionTransition.question_id/basis_refs/superseded_by_ref`,
`CoverageTransition.dimension_id/basis_refs/related_question_ids`,
`EvidenceRelevanceTransition.evidence_key/related_question_ids`,
`ContradictionTransition.contradiction_id/resolution_basis_refs`,
`HypothesisTransition.hypothesis_id`,
`AddFindingReference.finding_ref`, `AddPendingProposalReference.proposal_ref`,
`CreateQuestion.question(full WorkingQuestion incl. server-style
`question_id`)`.

### Q4. StateTransitionPolicy input exact shape

`StateTransitionPolicy.evaluate_batch(current_state: AgentWorkingStateV1,
batch: TransitionBatch, ctx: TransitionPolicyContext)`
(`agent_transitions.py:390`). `TransitionPolicyContext` (:326) = `task_id,
investigation_id, origin, policy_version, evidence_ref_resolver,
finding_ref_validator, verification_checker`. It consumes ONLY
`TransitionBatch.transitions` (typed models) + current state + resolver
seams. It never sees task/investigation/run UUIDs from the decision, never
sees result hashes, never sees attention hashes.

### Q5. Where the proposal integrator calls the policy

`agent_orchestrator.py` cycle: `supervisor.plan()` (validator at :642 area)
→ dispatcher executes delegations → `build_integration_context()` →
`supervisor.integrate(context)` (:1473) → `IntegrationDecisionValidator`
(:1476–1496) → `StateTransitionPolicy.evaluate_batch` via
`asyncio.to_thread` (:1519–1536) → `runtime.commit_agent_integration`
(:1573). IntegrationDecisionValidator checks decision identity echo,
result-id/hash echo, transition type allow-list, evidence-key syntax +
task-scoping, proposal/finding resolver seams, question-in-context.

### Q6. Attention hash origin

Server-side only: `AttentionSet.attention_hash = _attention_hash(items)`
(`agent_attention.py:254,500`), recompiled per plan cycle
(`attention_compiled` trajectory event). The plan decision is required to
echo it (`supervisor.py:628`); the integration decision has no
attention-hash field (observed `ATTENTION_HASH_MISMATCH` failures are all
PLAN-stage).

### Q7. Plan identity origin

`task_id/investigation_id` from the task record and `run_id` from the
admitted run — both injected into `SupervisorPlanningContextPack` by
`build_supervisor_planning_context` (`supervisor.py:182–186`). The model
never has a legitimate reason to restate them; the only plan-identity
choice the model could make is among active plans — today exactly one
plan is active per cycle (the previous cycle's plan actions were already
admitted or rejected), so no plan selection handle is needed.

### Q8. Question/Coverage ID generation

Questions: seeded as `q-1..q-n` (`AgentWorkingStateV1` seed,
benchmark driver `_seed_state`; production seeds the same scheme);
new questions arrive via `CreateQuestion` where the **model** invents the
`question_id` inside a full `WorkingQuestion` — a server-shaped identity
the model generates. Coverage: `AgentWorkingStateV1.coverage` defaults to
`()` (`agent_working_state.py:271`); skills only *declare*
`applicable_coverage_dimensions` names (`agent_skills.py:76`) and no
production path instantiates `CoverageDimension` rows — in every measured
benchmark run the coverage set was EMPTY, so any model-proposed
`CoverageTransition` could only fail `COVERAGE_DIMENSION_NOT_FOUND`
(`agent_transitions.py:952–957`). This is a structural dead-end, not a
model error.

### Q9. How SpecialistResult evidence refs enter the Supervisor context

`FreshResultEnvelope.result.iter_evidence_refs()` aggregates every
evidence ref from all result sections (`agent_specialist_result.py:141`);
`build_integration_context` unions them into
`IntegrationContextPack.relevant_evidence_refs` (`agent_integration.py:657–
659,697`). The WHOLE pack JSON is rendered into the integration prompt
(`supervisor.py:600`) — the model sees canonical `file:...` keys and is
told to copy them verbatim (:607–609).

### Q10. How ToolObservation evidence refs enter SpecialistResult

Read-only tools return observations carrying evidence keys (tool I/O
addresses); the specialist model cites them into result sections
(`evidence_refs` fields, `agent_specialist_result.py:47–114`). This level
is server-mediated tool interaction; P8B evidence shows specialist-level
refs are overwhelmingly correct (the failures concentrate at the
supervisor boundary). A1 keeps this layer unchanged (§17/§18 investigation
conclusion — tool interaction itself needs the keys as data addresses).

### Q11. Does context refresh invalidate a handle registry?

The supervisor is invoked stateless, one turn per invocation
(`agent.run(objective_digest)`; no cross-cycle conversation). Both context
packs are rebuilt per cycle (`build_supervisor_planning_context`,
`build_integration_context`), attention is recompiled per cycle, and the
state revision advances after every accepted integration. The model never
sees two cycles' contexts at once, so cross-cycle handle stability has
zero value.

### Q12. Which policy failures disappear by deleting model-owned identity fields

Structurally eliminated by v2 (server injects the values):
`PLAN_IDENTITY_MISMATCH`, `PLAN_STATE_REVISION_STALE`,
`PLAN_ATTENTION_HASH_MISMATCH`, `INTEGRATION_IDENTITY_MISMATCH`,
`INTEGRATION_STATE_REVISION_STALE`,
`INTEGRATION_SOURCE_RESULT_UNKNOWN`,
`INTEGRATION_SOURCE_RESULT_HASH_MISMATCH`,
`INTEGRATION_BASIS_REF_UNKNOWN` (question-ref transcription),
`INTEGRATION_EVIDENCE_REF_INVALID`/`EVIDENCE_REF_CROSS_TASK` from copied
keys, `COVERAGE_DIMENSION_NOT_FOUND` from free-form dimension ids,
`QUESTION_NOT_FOUND`/`COVERAGE_QUESTION_NOT_FOUND` from copied question
ids, and `PLAN_ATTENTION_ITEM_UNKNOWN` from copied item ids (handled at
the resolver as `HANDLE_UNKNOWN`, still fail-closed).

### Q13. Which failures are true semantic errors and must remain possible

`QUESTION_DISPOSITION_REQUIRED`, `QUESTION_CLOSURE_BASIS_REQUIRED`
(basis_handles empty where basis is required), 
`QUESTION_CLOSURE_VERIFICATION_REQUIRED` (required-question closure
without passed verification), `REQUIRED_QUESTION_CANNOT_DEFER`,
illegal status transitions (question/hypothesis/contradiction/coverage
machines), `QUESTION_BLOCKER_REQUIRED`,
`QUESTION_SUPERSESSION_PROVENANCE_REQUIRED`,
`COVERAGE_ILLEGAL_STATUS_TRANSITION`, assertion-class ceilings and
mandatory-verification rules (P5B), finalization hard blockers.
v2 success = identity plumbing → ~0 while these stay visible.

---

## 2. §28 failure-ownership matrix (P8B observed codes)

| observed code (P8B measurements) | stage | ownership | v2 disposition |
|---|---|---|---|
| `PLAN_IDENTITY_MISMATCH` (DeepSeek ×3) | PLAN | identity plumbing | eliminated (injected) |
| `PLAN_ATTENTION_HASH_MISMATCH` (MiMo ×1) | PLAN | identity plumbing | eliminated (injected) |
| `INTEGRATION_IDENTITY_MISMATCH` (MiMo ×2) | INTEGRATE | identity plumbing | eliminated (injected) |
| `INTEGRATION_BASIS_REF_UNKNOWN` (DeepSeek ×5) | INTEGRATE | identity plumbing (question-ref copy) | eliminated (handles) |
| `EVIDENCE_REF_CROSS_TASK` (kimi ×33) | INTEGRATE | identity plumbing (copied/mutated keys) | eliminated (handles; exact handle lookup, no normalization) |
| `INTEGRATION_EVIDENCE_REF_INVALID` (MiMo ×1, kimi ×3) | INTEGRATE | identity plumbing | eliminated (handles) |
| `INTEGRATION_FINDING_REF_UNRESOLVED` (kimi ×5) | INTEGRATE | identity plumbing (finding id copy) | resolver `HANDLE_UNKNOWN`, fail-closed; correct handles resolve |
| `INTEGRATION_PROPOSAL_REF_UNRESOLVED` (MiMo ×1) | INTEGRATE | identity plumbing | same as above |
| `COVERAGE_DIMENSION_NOT_FOUND` (MiMo ×1, kimi ×2) | INTEGRATE | structural dead-end (empty coverage + free-form ids) | server-issued COV handles; empty coverage ⇒ no handles ⇒ `HANDLE_UNKNOWN` |
| `QUESTION_DISPOSITION_REQUIRED` (MiMo ×5, kimi ×2) | POLICY | semantic | PRESERVED |
| `QUESTION_CLOSURE_BASIS_REQUIRED` (MiMo ×5, kimi ×2) | POLICY | semantic | PRESERVED (basis_handles=[] still fails) |

## 3. §19 handle scope decision

**Option A — per-invocation frozen binding table.** Evidence (Q11): the
supervisor is stateless across cycles; every cycle rebuilds context packs
and recompiles attention; state revision advances per accepted batch. A
run-scoped append-only registry (Option B) would bind identical handles to
referents whose status changed between cycles while the model can never
carry a reference across invocations anyway — added complexity, zero
benefit, audit ambiguity. The binding table is derived deterministically
from the exact frozen context pack of ONE supervisor invocation and is
valid only within it (`binding_table_id` = hash of table content; resolves
against `run_id` + table id).

## 4. V2 design (freezes the A1-1..A1-4 implementation)

**New module `agent_reference_bindings.py`** (pure, deterministic):
`ReferenceBindingTableV1` per spec §5 (`binding_table_id, task_id,
investigation_id, run_id, working_state_revision, context_hash, bindings[],
created_at, input_hash`; binding = `handle, kind, canonical_ref,
display_digest`). Builders: `build_plan_binding_table(pack)` (A*=attention
items, Q*=questions, S*=source scopes) and
`build_integration_binding_table(context, state)` (D*=fresh results,
E*=evidence refs (`iter_evidence_refs` union, dedup, one stable handle per
canonical ref), Q*=questions, COV*=coverage dimensions, F*=finding_refs,
P*=pending proposal refs, H*=hypotheses, X*=contradictions). Handles are
ordinal over canonically sorted refs — same context ⇒ same table hash
(§4: not array indices of any model-visible list; server-owned ordinal
identity). Renderer produces the v2 prompt projection (handles + display
digests + semantic content; canonical 64-hex hashes and UUIDs omitted).

**New module `agent_integration_v2.py`**:
`SupervisorIntegrationDecisionV2` = `decision_version
("supervisor-integration-decision:v2"), actions, integration_summary,
limitations, warnings` — NO identity fields (§7/§30). Typed v2 actions
(one per allowed v1 transition type): `update_question{question_handle,
to_status, disposition?, basis_handles?, limitations?,
investigated_summary?, blocker?, superseded_by_handle?}`,
`create_question{text, priority, source, parent_question_handle?}`
(server assigns `question_id`), `update_evidence_relevance{
evidence_handle, to_status, related_question_handles?}`,
`create_hypothesis{...}` / `update_hypothesis{hypothesis_handle,
to_status}`, `create_contradiction{...}` / `update_contradiction{
contradiction_handle, to_status, resolution_basis_handles?, ...}`,
`update_coverage{coverage_handle, to_status, basis_handles?, limitation?,
capability_basis?, related_question_handles?}`,
`add_finding_reference{finding_handle}`,
`add_pending_proposal_reference{proposal_handle}`.
`SupervisorPlanDecisionV2` = `decision_version, actions[
delegate_investigation{attention_handle, question_handle, source_scope_id,
...}, request_finalization, no_action], summary, warnings, limitations` —
no identity/revision/hash echo (§20/§21); `source_scope_id` stays raw
(small closed semantic set; `PLAN_SOURCE_SCOPE_NOT_ALLOWED` preserved).

**`IntegrationReferenceResolver`** (§10): exact table lookup → kind check
→ (integration) canonical ref still valid in context → build canonical
v1-shaped objects. No fuzzy repair of any kind (§25); unknown handle ⇒
`HANDLE_UNKNOWN`, wrong kind ⇒ `HANDLE_KIND_MISMATCH`, foreign table ⇒
`HANDLE_CONTEXT_MISMATCH` — all fail-closed (§6/§11/§26: resolver never
chooses dispositions, never fills basis_handles).

**V2→canonical adapter (§12)**: resolver emits a genuine
`SupervisorIntegrationDecisionV1` / `SupervisorPlanDecisionV1` with
identity/revision/hash/source fields injected from the context — then the
EXISTING `IntegrationDecisionValidator` → `StateTransitionPolicy` →
`commit_agent_integration` path runs unchanged. No v2 fast path (§35).

**Orchestrator wiring**: constructor flag
`integration_contract_version: Literal["v1","v2"]` (default `"v1"` until
the A1 freeze commit flips it; benchmark driver overrides to `"v2"` for
the canary). v2 branch at plan (:~642) and integrate (:1473): build table →
`supervisor.plan_v2/integrate_v2` → resolve → on resolution failure emit
trajectory `transition_decision_rejected` with v2 codes → else feed the
canonical decision into the unchanged gates.

**Audit (§22) & trajectory (§23)**: persist `raw_model_proposal_v2`,
`binding_table_id`, resolution record (per-action ok/violation) and the
policy verdict inside the existing trajectory event payloads and the
integration `decision_payload` (JSON columns — no schema bump, no new
event types; `integration_binding_created` is realized as payload fields
on `transition_decision_validated`).

**Compatibility (§24)**: all v1 models/prompts/validators stay; trajectories
carry `integration_contract_version`; P8B v1 measurement history remains
the historical v1 benchmark.

## 5. §1 invariants re-checked (unchanged by A1)

Evidence identity `(task_id, evidence_key)`, `resolve_evidence()`, task
isolation, `allowed_evidence_ids`, GroundingValidator, FACT/INFERENCE/
HYPOTHESIS ceilings, SemanticVerifier mandatory rules, analyst-only
accepted/rejected, StateTransitionPolicy authority (v2 feeds it, never
bypasses), FinalizationGate hard blockers, Graph provenance, Report
citation boundary, fail-closed everywhere. The LLM still cannot invent
Evidence, choose task identity, bypass scope, lower verification, accept/
reject findings, or bypass finalization — it stops having to transcribe
machine identity strings (§45).
