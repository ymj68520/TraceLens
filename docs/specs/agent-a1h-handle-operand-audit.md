# A1-H Audit — Supervisor Handle Operand Availability

Status: AUDIT COMPLETE (pre-implementation, spec §3-§8; zero production
code changed by this document)
Branch: `mvp/agent-v0-typed-handle-contract` (from B2 measurement commit
`7195a43c`)
Evidence: P8B B2 baseline (`baseline-measurement-report-v3.json`,
`trajectory_digest.json` v3 ×24) + qualification canary raw proposals
(`canary-a1t`, pre-cleanup full tables) + deterministic table-construction
analysis (`agent_reference_bindings.build_integration_binding_table`).

## The decisive question (§4): did a legal expected-kind handle exist?

Answered per event below. Table domains at INTEGRATE (from the frozen
builder):

- E* ← `context.relevant_evidence_refs` (the fresh results' evidence-ref
  union) — EXISTS whenever a fresh completed delegation cites evidence
- Q* ← context state questions — EXISTS
- D* ← `context.fresh_results` — EXISTS (D1 in every audited event)
- F* ← `state.finding_refs`; P* ← `state.pending_proposal_refs`;
  COV* ← `state.coverage`; H*/X* ← state objects — these populate ONLY
  through COMMITTED transitions. In every affected run no integration
  ever committed (finalization refused with
  UNINTEGRATED_COMPLETED_DELEGATION / REQUIRED_QUESTION_OPEN), so the
  state never gained findings, pending proposals, hypotheses or
  contradictions → **F/P/H/X handle domains were EMPTY at every
  rejection in those runs.**

## Per-event HandleMismatchAuditRecord (13 KIND_MISMATCH + 3 UNKNOWN)

### Class H1 — legal expected-kind handle EXISTED (model kind discipline) — 6 events

| # | case/repeat | seq | field path | provided | expected | legal operands present |
|---|---|---|---|---|---|---|
| 1 | t2-cross-source-correlation/repeat2 | 15 | actions[0](update_question).basis_handles[3] | D1 (delegation_result) | evidence | yes — E1..E4 from the completed delegation's evidence union (canary precedent of the same case: `basis_handles=["E3","E4","E2","E1","D1"]`) |
| 2 | t2-cross-source-correlation/repeat2 | 15 | actions[1](create_hypothesis).supporting_handles[3] | D1 | evidence | yes (same proposal) |
| 3 | t2-cross-source-correlation/repeat2 | 15 | actions[2](create_contradiction).refs_handles[3] | D1 | evidence | yes (same proposal) |
| 4 | t2-identity-trap/repeat0 | 19 | actions[0](update_question).basis_handles[0] | D1 | evidence | yes — delegation completed with 4 evidence snapshots ⇒ E1..E4 existed; model cited ONLY ["D1"] |
| 5 | t2-identity-trap/repeat0 | 19 | actions[1](create_hypothesis).supporting_handles[0] | D1 | evidence | yes (same proposal) |
| 6 | t2-identity-trap/repeat1 | 20 | actions[0](update_question).basis_handles[0] | D1 | evidence | yes (same construction) |

Root cause: **MODEL HANDLE KIND DISCIPLINE (§5 Case H1)** — the model
treats D1 ("the specialist result") as a universal evidence-like
operand. The semantic intent is legitimate (ground the closure in what
the delegation found); the representation is illegal. The one-delegation
result internally holds MULTIPLE evidence objects, so D1→E auto-mapping
is forbidden (§9).

### Class H3 — legal expected-kind handle did NOT exist (unsatisfiable action branch) — 7 events

| # | case/repeat | seq | field path | provided | expected | legal operands present |
|---|---|---|---|---|---|---|
| 7 | t1-fraud-script-usb/repeat0 | 21 | actions[18](add_finding_reference).finding_handle | D1 | finding | **NO — F* = []** |
| 8 | t1-fraud-script-usb/repeat2 | 24 | actions[10](add_pending_proposal_reference).proposal_handle | D1 | claim_proposal | **NO — P* = []** |
| 9 | t2-identity-trap/repeat1 | 20 | actions[7](add_finding_reference).finding_handle | D1 | finding | **NO — F* = []** |
| 10 | t2-identity-trap/repeat2 | 20 | actions[7](add_pending_proposal_reference).proposal_handle | D1 | claim_proposal | **NO — P* = []** |
| 11 | t2-no-evidence/repeat2 | 18 | actions[6](add_finding_reference).finding_handle | D1 | finding | **NO — F* = []** |
| 12 | t2-report-citation/repeat2 | 21 | actions[13](add_pending_proposal_reference).proposal_handle | D1 | claim_proposal | **NO — P* = []** |
| 13 | t2-temporal-trap/repeat1 | 20 | actions[7](add_pending_proposal_reference).proposal_handle | D1 | claim_proposal | **NO — P* = []** |

Root cause: **ACTION AVAILABILITY CONTRACT (§7 Case H3)**, not model
capability. `add_finding_reference` / `add_pending_proposal_reference`
reference objects that can only exist AFTER a first successful
integration commit; at the first INTEGRATE of every affected run the
model was handed branches whose operand domains were structurally empty.
The model's semantic intent ("adopt the delegation result's conclusions
as findings/proposals") has NO legal expression:
- §6 Case H2 projection is NOT applicable: the SpecialistResult's
  internal candidates are not committed state objects; projecting them
  as P*/F* handles would fabricate canonical `pending_proposal` /
  `finding` refs the resolver cannot bind and would smuggle semantic
  creation into the handle layer (§15/§16).
- Correct fix per §17/§18: deterministic admissibility projection —
  do not offer action variants whose operand domain is empty.

### Class COV-UNKNOWN — 3 events (§8)

| # | case/repeat | seq | field path | provided | legal operands |
|---|---|---|---|---|---|
| 14 | t2-misleading-note/repeat0 | — | actions[3](update_coverage).coverage_handle | `platform_mismatch` (invented) | COV presence not persisted pre-A1-H; seed states carry questions only and no coverage transition was ever committed in the run, so at most pipeline-seeded dimensions — in no case the invented names |
| 15 | t2-misleading-note/repeat0 | — | actions[4](update_coverage).coverage_handle | `evidence_volume` | same |
| 16 | t2-misleading-note/repeat0 | — | actions[5](update_coverage).coverage_handle | `account_context` | same |

Root cause: the model believes `update_coverage` CREATES dimensions by
name. `CoverageTransition` can only UPDATE existing dimensions (frozen
StateTransitionPolicy). Fix: same availability projection — the branch
is offered only when COV handles exist; typed CoverageHandle field
rejects free text at the schema.

## Design freeze (§10-§23)

1. **Typed model-facing handle fields (§11/§12)**, exact unions per the
   resolver's actual semantics (NOT the instruction example — every
   multi-handle field is evidence-ONLY):
   - `EvidenceHandle` = `E\d+`: update_question.basis_handles,
     create_hypothesis.supporting_handles,
     create_contradiction.refs_handles,
     update_contradiction.resolution_basis_handles,
     update_coverage.basis_handles, update_evidence_relevance.evidence_handle
   - `QuestionHandle` = `Q\d+`: question_handle, superseded_by_handle,
     parent_question_handle, related_question_handles
   - `CoverageHandle` = `COV\d+`: coverage_handle
   - `HypothesisHandle` = `H\d+`, `ContradictionHandle` = `X\d+`,
     `FindingHandle` = `F\d+`, `ProposalHandle` = `P\d+`
   - D-handles appear in NO action operand (delegation results are
     context, not operands).
   Decision schema version bumps to `supervisor-integration-decision:v3`
   (model-facing epoch change); plan decision unchanged; supervisor
   contract version stays v2.
2. **Availability projection (§17/§18, minimal per §19)**: the rendered
   integration context gains `available_actions` (only variants whose
   operand domains are non-empty; always-available branches listed
   unconditionally) + `handle_counts_by_kind`; instructions require
   choosing ONLY from `available_actions`. No dynamic schema-union
   machinery; resolver stays fail-closed (§13/§14).
3. **Auditability (§20/§21)**: integration trajectory payloads record
   `available_handles_by_kind` + `offered_action_variants`; benchmark
   digest v4 computes `legal_operand_available` per rejection; driver
   captures a benchmark-only semantic payload projection (result
   summary/claims/evidence_refs/limitations + raw proposal) BEFORE task
   cleanup (§22) — never Evidence, never consumed by production (§23).
4. **No D1 auto-mapping (§9)**, no canonical creation (§16), resolver +
   validator + policy unchanged (§29), retries unchanged (§1).

## Tests freeze (§24-§31)

Kind discipline (D1 into every typed field rejected at schema), valid
kind end-to-end (E1 → resolver → canonical ref; F/P/Q/COV/H/X same),
unavailable-branch projection (empty domain → branch absent from
rendered available_actions), semantic responsibility (model still picks
WHICH evidence), policy preservation (resolver → canonical → validator →
policy → commit, no fast path), negative semantics (valid handle +
unsupported claim still rejected downstream), and the full regression
suite.
