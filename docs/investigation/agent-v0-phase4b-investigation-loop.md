# TraceLens Agent v0 — Phase 4B: Supervisor Integration & Investigation Loop Closure

Status: implemented on `mvp/agent-v0-phase4-investigation-loop`.

## 1. Baseline / Branch / Commits

- P4A frozen checkpoint: `0e78cb75` (F1 follow-up included)
- Branch: `mvp/agent-v0-phase4-investigation-loop`
- Commits:
  - `1b78df5a` — `feat: add investigation supervisor planning` (P4B-1)
  - `11c37333` — `feat: add agent result merge and integration contracts` (P4B-2)
  - `4923aa36` — `feat: add atomic agent semantic integration` (P4B-3)
  - (P4B-4) — `feat: close agent investigation loop` (execute_cycle/run_loop, E2E, docs, freeze gate)

## 2. Schema

**Minimal v11 → v12** (P4B §35): exactly two trajectory CHECK values added —
`supervisor_plan_decided` and `supervisor_integration_committed` — so PLAN and
Integration decisions have their own immutable Action Trace events. The same
migration also re-installs the delegation guard triggers with ONE sanctioned
new edge: `completed → stale` (unintegrated rows only; every other column
pinned to OLD by trigger WHEN clauses; the guarded repo primitive
`mark_completed_delegation_stale` additionally requires an exact result-hash
match — the triggers are pure SQL backstops of that). `SUPPORTED_SCHEMA_VERSION = 12`.

## 3. Supervisor PLAN (P4B-E2/E3/E5/E6)

`InvestigationSupervisor` — the single logical investigation-level supervisor;
no per-platform supervisor classes. PLAN mode: **Tools = none** (structurally:
the agent is constructed with no toolsets), reading only the frozen
`SupervisorPlanningContextPack` (`supervisor-planning-context:v1`): identity,
state revision/hash, objective + directive digests, attention window +
attention/policy hashes, question/coverage/contradiction digests + question
index, source scopes, active/recent delegation digests, progress/budget
digests, last-finalization-denial digest, phase capabilities, deterministic
`input_hash()`. Raw evidence bodies / full observations / chat history are
structurally absent. The supervisor never touches the registry, resolver,
SQLite, filesystem or Graphiti.

`SupervisorPlanDecisionV1` (`supervisor-plan-decision:v1`): only
`delegate_investigation` / `request_finalization` / `no_action` (P5/P6 action
kinds are rejected by the phase-capability validator even if named). Delegate
actions bind attention item + question + source scope only — tools, skill
versions, profiles and budgets stay with deterministic resolution.
`SupervisorPlanDecisionValidator` (deterministic, §36): version, identity,
state revision/hash, attention hash, item exists+eligible+admits delegation,
question known+active, scope granted, duplicate fingerprints (in-plan,
in-flight), budget cap — all stable violation codes.

## 4. Admission transaction (P4B-E7/E8, §37)

`commit_supervisor_plan`: ONE `BEGIN IMMEDIATE` — revalidate run → append
`supervisor_plan_decided` (full structured decision audit: decision payload,
hash, model name/config hash, prompt version, usage) → admit queued
delegations through the shared conn-level admission body (P2 semantics,
deterministic idempotency keys) → COMMIT. Replay: a decision hash already on
the trace is not duplicated; per-spec keys keep delegation admission
replay-identical. The executor dispatches only after this commits.

## 5. EXECUTE (P4B-E9/E10)

Direct reuse of the P4A executor (exact profile/skill version binding,
ContextPack, frozen tool registry, evidence visibility, provider failure
mapping, cancellation, bounded parallelism). Group waits **all_terminal**:
failed/cancelled workers become `FailureDigest`s (delegation, question, scope,
terminal status, failure code/summary, hashes) entering the integration
context — a runtime failure is never dressed up as evidence absence.

## 6. MergeGuard (P4B-E11/E12, §38)

Deterministic freshness over frozen dependencies (question, scopes, evidence
refs, bound directive digests, bound hypothesis refs). Stale ONLY on:
question inactive/unknown, bound scope revoked, referenced evidence
invalidated (injected seam), bound directive digest changed, bound hypothesis
rejected. **`current revision != based_on revision` is never stale by
itself** — tested with N vs N+3. Version provenance (profile/skill/registry
hashes) is never a staleness input. Unrelated new directives / added scopes
keep results fresh (§24). Stale results: `mark_completed_delegation_stale`
(full audit preserved, never integrable).

## 7. IntegrationContextPack + Integration decision (P4B-E13/E14/E15/E16)

`integration-context:v1` — current state revision/hash, state slice
(`question:<id>` entries), fresh validated results + hashes, stale digests,
failure digests, evidence refs, attention refs, directive digests, policy
version, `input_hash()`. `SupervisorIntegrationDecisionV1` carries **typed P2
transition proposals** through a frozen union (`QuestionTransition,
CreateQuestion, EvidenceRelevanceTransition, CreateHypothesis,
HypothesisTransition, CreateContradiction, ContradictionTransition,
CoverageTransition, AddPendingProposalReference`). AddEntityReference /
AddFindingReference / ModifyScope are outside the union — structurally
impossible to construct — and the validator names them forbidden (P5+).
JSON-patch dicts fail construction; unknown-question refs fail
`INTEGRATION_BASIS_REF_UNKNOWN`; source result hashes must match persisted
records exactly.

## 8. Atomic semantic integration (P4B-E17..E22, §41/§42/§43)

`commit_agent_integration`: ONE transaction — revalidate investigation/run →
revalidate head revision+hash → revalidate every source delegation
(completed, unintegrated, exact result hash) → append
`supervisor_integration_committed` (decision audit) → accepted batches insert
the new Working State revision (exactly +1, operation_key-bound) → mark
consumed delegations integrated. Any failure rolls back everything (failure
injection on the revision insert proves no partial audit/revision/
integrated_at). `StateTransitionPolicy.evaluate_batch` remains the semantic
authority — the validator cannot repair intent, and a policy rejection leaves
results unintegrated and records an unresolved transition conflict (which
blocks finalization). Noop integrations consume results without a revision
(§20). Idempotency (§22): operation_key = hash(investigation, head revision,
sorted result hashes, policy version); replay returns the original outcome;
noop replays are proven by already-integrated delegations.

## 9. execute_cycle / run_loop (P4B-E23/E24/E25/E26/E27)

`AgentOrchestrator.execute_cycle` implements the frozen 21-step cycle;
`run_loop` is bounded by `SupervisorCyclePolicy.max_cycles_per_invocation` /
`max_cycles_per_run` (provisional config; P8 calibrates) — never `while True`.
PLAN/EXECUTE/EVALUATE bookkeeping consumes no revision. Directive re-plan
seam (§23): a digest change mid-run stops admissions, cooperatively cancels
active delegations and stops the run with `directive_replan` (the frozen
stop-reason enum already carried it); the next run re-PLANs from the latest
committed revision. Budget stop = `budget_exhausted` (never "investigation
completed"). Finalization requests go ONLY through the P2
evaluate/finalize path; with no P5 semantic verifier the review is honestly
`unavailable` ("semantic verifier not available in P4B") and the frozen gate
decides — required mode can never be bypassed; DENY records blockers and the
investigation stays active. Provider failures map through the P4A normalizer
into explicit trajectory + outcome states; supervisor output retry counts are
config. Restart never resumes any conversation (P1/P2 recovery owns the
terminal states).

## 10. Tests

`test_agent_supervisor_plan.py` (17), `test_agent_merge_integration.py` (15),
`test_agent_atomic_integration.py` (9, incl. failure injection),
`test_agent_schema_v12_migration.py` (2),
`test_agent_investigation_loop.py` (6, incl. the §44 full offline cycle with
REAL PydanticAI TestModel agents on both supervisor modes and the specialist,
a real read-only tool call through the frozen registry, and the exactly-one-
revision assertion; §45 all_terminal with one failure; §46 stale exclusion;
§47 directive re-plan; §48 finalization gate; §49 restart).

## 11. Known limitations / P5 deferred

- Directive seam is a provider callable (no canonical Directive store exists; none invented — Architecture TBD respected).
- Cycle budget is per-run cycle count (simplest deterministic budget; P8 refines).
- PLAN admission idempotency keys bind attention+question+scope; re-plans on a moved state naturally produce new keys.
- No mid-flight provider-call cancellation (inherited from P4A's documented limit).
- P5 owns: EntityOccurrence/identity policy, DeterministicCorrelationEngine + CorrelationAgent, ProposedClaim pipeline, Grounding Validator, SemanticVerifierAgent, AssertionPolicy, canonical review_pending findings. Until then every specialist FACT/INFERENCE/entity/correlation output remains proposal/hypothesis/pending-proposal only.
