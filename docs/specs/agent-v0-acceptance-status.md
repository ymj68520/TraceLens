# Agent v0 Project Status — Acceptance Track

Updated: 2026-10-01 (Runtime V3 requalification + recalibration
complete: model QUALIFIED on RuntimeBaselineV3, B2 MEASUREMENT_VALID,
CalibrationEvidenceBindingV3 ZERO_CHANGE, AcceptanceProfileV2
reviewed unchanged and bound to Runtime V3; formal acceptance still
NOT ESTABLISHED; Gen-4 NOT CREATED).

```text
Agent v0 Architecture:
FROZEN

Runtime:
AgentV0RuntimeBaselineV3 CURRENT / QUALIFIED
(v2-era baselines HISTORICAL)

Model (SenseNova sensenova-6.8-flash-lite):
QUALIFIED on RuntimeBaselineV3
(ModelRuntimeQualificationRecordV3)

Calibration:
MEASUREMENT_VALID (b2-runtime-v3, 8×3=24 runs,
all gates PASS, 24/24 evaluate-only reproduced)
ZERO_CHANGE
CalibrationEvidenceBindingV3 FROZEN
(V2 HISTORICAL / immutable)

AcceptanceProfileV2:
SEMANTICS / THRESHOLDS UNCHANGED
BOUND_TO_RUNTIME_V3 (compatibility review: all six axes NO change;
AcceptanceProfileRuntimeBindingV3)

Content hydration:
evidence-content-hydration:v1 FROZEN
(B2 hydration: 22/24 runs exercised, 75 items, 0 unavailable,
0 integrity failures, 0 legacy fallbacks)

Acceptance Generation 1:
CLOSED_INVALID / B6_INVALID / CONSUMED

Acceptance Generation 2:
CLOSED_INVALID (SUBSTRATE_EVIDENCE_SURFACE_MISMATCH) / CONSUMED

Acceptance Generation 3:
CLOSED_INVALID (EVIDENCE_CONTENT_SURFACE_TRANSIENT — remediated) /
CONSUMED

Formal Agent v0 acceptance:
NOT ESTABLISHED

Generation 4:
NOT CREATED
Prerequisites now satisfied:
CONTENT_HYDRATION_FROZEN ✓ RuntimeBaselineV3 ✓ model QUALIFIED ✓
valid new B2 ✓ CalibrationEvidenceBindingV3 ✓
AcceptanceProfileRuntimeBindingV3 ✓
Any Gen-4 preparation still requires explicit user authorization.
```

## Model status (exact wording, superseding earlier summaries)

```text
SenseNova (sensenova-6.8-flash-lite):
CALIBRATION-QUALIFIED

Generation-1 B6 diagnostic:
functional requirement not met

Formal sealed acceptance:
NOT ESTABLISHED
```

It is incorrect to say "SenseNova was formally rejected by a valid B6":
the Generation-1 B6 execution is formally B6_INVALID
(HOLDOUT_AGENT_INPUT_NOT_PRESEALED — the Agent-visible charter was authored
at execution entry instead of being presealed before admission), so no
formal sealed acceptance measurement exists for any model.  The 6-run
diagnostic remains preserved as DIAGNOSTIC_ONLY evidence
(functional floor not met: refund-fraud 0/3, vpn-causal 1/3 qualifying;
five other axes clean).

## Frozen vs open

- `formal acceptance not established` does NOT unfreeze the architecture:
  there is no Evidence Integrity / StateTransition / Grounding / Handle
  correctness regression.  Architecture stays FROZEN.
- Agent runtime semantics (A1-S, Supervisor v2, A1-T, A1-H,
  StateTransitionPolicy, FinalizationGate) stay UNCHANGED.  The one
  sanctioned production change is the durable evidence content backing
  (`evidence-content-hydration:v1`, FROZEN — see
  `docs/specs/evidence-content-hydration-contract.md`); the runtime
  epoch is now `AgentV0RuntimeBaselineV3`
  (`benchmarks/profiles/agent-v0-runtime-baseline-v3.json`), QUALIFIED
  with a valid recalibration (see
  `benchmarks/profiles/calibration-evidence-binding-v3.json` and
  `benchmarks/profiles/acceptance-profile-runtime-binding-v3.json`).
  Any next acceptance generation (Gen-4) is gated on explicit user
  authorization — all six §42 prerequisites are now satisfied — and
  must use brand-new holdout instances, never consumed holdout answers.

## Generation-1 permanent history (never to be overwritten)

1. B6 execution occurred (6 scheduled attempts; artifacts immutable).
2. Formal measurement invalid (B6_INVALID).
3. Holdout consumed (entire Generation-1 pool retired).
4. Diagnostic functional requirement not met (DIAGNOSTIC_ONLY).

Primary records:
`benchmarks/profiles/b6-interpretation-amendment-v1.json`,
`benchmarks/profiles/acceptance-generation-closure-v1.json`,
`benchmarks/results/agent-v0/b6-holdout/` (immutable),
`docs/specs/agent-b6-holdout-acceptance-audit.md` (execution-era record).

## Acceptance Generation 2 (executed → B6_INVALID, CLOSED_INVALID)

B6 was executed 2026-10-01 under explicit authorization: preflight ALL
PASS, execution gate passed, 6/6 scheduled attempts terminal, hard gates
PASS 6/6, evaluate-only 6/6 reproduced, zero provider failures,
P/H/S/G = 0, run-set `7b63834b…`.

**Verdict: B6_INVALID** (`SUBSTRATE_EVIDENCE_SURFACE_MISMATCH`).  The
agents' indexed evidence universe derives from the provisioning
substrate image's extraction; the generic minimal-validation substrate
delivered its own five fraud-demo files instead of the sealed public
assets (staging copies land after the completion-time evidence index).
The sealed capability traps were never exercised — the measurement is a
benchmark defect (§12), NOT an agent failure (the agents refused to
fabricate against the mismatched evidence and reported absence
honestly).  Consequences per §34/§35: both Gen-2 holdout families are
**CONSUMED**; **no second Gen-2 B6**; any future acceptance requires an
**Acceptance Generation 3** whose per-case evidence-bearing substrates
are constructed and sealed as Agent-visible inputs at generation
construction time (the substrate IS Agent-visible input under the
frozen invariant).

Diagnostic (NOT formal evidence): functional 0/3 + 0/3 qualifying;
structural/semantic/negative-case/reliability/availability clean;
fabricated citations 0/6 (deterministic); assertion ceilings and
analyst-note discipline correct throughout.

Records: `benchmarks/results/agent-v0/acceptance-gen2/` —
`agent-v0-acceptance-decision-v2.json`,
`acceptance-generation-closure-v2.json` (CLOSED_INVALID / NO RETRY),
`holdout-run-set-v2.json`, `holdout-acceptance-evaluation-v2.json`,
`holdout-execution-manifest-v2.json`,
`holdout-bootstrap-preflight-v2.json`, `gen2-b6-infra-incident-v1.json`
(two pre-model driver defects, fixed before any model request;
execution count was 0 until the real series).

## Generation-2 protocol (frozen, carried into Generation 3)

Protocol (`acceptance-generation-2-protocol:v1`, contract module
`httpserver/services/benchmarks/holdout_contract.py`):

- **Core invariants** — "If the Agent can see it, it must already have
  been sealed before acceptance admission" and "B6 executes frozen
  semantics; B6 never authors semantics."
- `PublicHoldoutCaseV2` (`public-holdout-case:v2`): goal, context,
  charter questions, required coverage dimensions, coverage→question
  links, public assets, `negative_risk_context` (the ONLY Agent-visible
  framing slot), source scopes — all hash-bound at construction.
- `negative_flags` ownership RESOLVED: **evaluator-only truth metadata**
  (structurally absent from the public contract and bootstrap).
- Charter authored ONLY at construction time (Holdout Author role);
  B6 preflight loads / validates / hash-checks / bootstraps — never
  authors.
- Bootstrap = pure deterministic projection (frozen, seal-bound);
  TruthManifestV2 bundle = TruthManifestV1 schema (evaluator-bound) with
  truth/public separation enforced by deterministic tests.
- `HoldoutSealV2` seal `a7b9d1ea92166d0a…`; seal mismatch or post-seal
  mutation BLOCKS execution (`enforce_execution_gate`).
- AcceptanceProfileV2 continues unchanged, bound to Gen 2 via
  `acceptance-profile-generation-binding-v2.json` (per-family ≥2/3 floor
  inherited from the product contract — NOT adjusted for the Gen-1
  diagnostic). Calibration NOT rerun (runtime/model/corpus unchanged).

Holdout set `holdout-set-gen2-v1` (2 families — now CONSUMED):

| case | family | public hash |
|---|---|---|
| gen2-attribution-contradiction | cross_source_attribution_contradiction | `416ed6ccf90e3cfa…` |
| gen2-analyst-refutation | misleading_analyst_context | `e7d31f6aef7c7939…` |

Construction-time static validation ALL PASS; admission audit 8/8 PASS →
ADMITTED_FOR_B6 (superseded by execution → B6_INVALID, see above).
Regression at preparation: 2676 passed (22 new Gen-2 contract tests; 2
pre-existing environment-dependent failures unrelated: local Postgres
auth, CORS origin — both fail on a clean tree).

## Acceptance Generation 1 (closed — unchanged)

Generation-1 permanent history, protocol era, closure record and the
 SenseNova wording block above remain the authoritative Gen-1 record:
`benchmarks/profiles/b6-interpretation-amendment-v1.json`,
`benchmarks/profiles/acceptance-generation-closure-v1.json`,
`benchmarks/results/agent-v0/b6-holdout/` (immutable),
`docs/specs/agent-b6-holdout-acceptance-audit.md` (execution-era record).

## Acceptance Generation 3 (sealed, admitted, NOT executed)

Preparation commit chain: `0144636d` (Gen-2 addendum) → `3312e9b9`
(substrate contract + tests) → `224c3c97` (construct + seal) → admission.

**Supreme invariant (frozen)**: "If the Agent can observe it, directly
or through parsing/indexing, it must be frozen and hash-bound before
admission." The evidence-bearing substrate image is now a formal sealed
protocol object (`SealedEvidenceSubstrateV1` + `SealedEvidenceManifestV1`,
contract module `holdout_contract_v3.py`); post-extraction file
injection is not legal provisioning; the execution gate gained
SUBSTRATE_IMAGE_HASH_MATCH / EVIDENCE_WORLD_DIGEST_MATCH /
EXPECTED_EVIDENCE_KEYS_PRESENT / UNEXPECTED_SEMANTIC_EVIDENCE_ABSENT /
PARSER_CONFIG_HASH_MATCH.

Holdout set `holdout-set-gen3-v1` (2 new families, entirely new
instances):

| case | family | public hash | image hash | evidence-world digest |
|---|---|---|---|---|
| gen3-ledger-identity | identity_ambiguity | `f5d5c09abdcd…` | `5202a1513e3b…` | `6faa0265df5d…` |
| gen3-failover-causality | causal_ambiguity | `f3c254fdb13e…` | `0aa0e4c4d064…` | `d68811a6fec8…` |

Seal `HoldoutSealV3` = `d11a17e1a7f45e11…`; construction validation
(EvidenceWorldValidationV1) ALL PASS with real provisioning ×2 per case
(zero model calls); admission audit `Generation3AdmissionAuditV1` 8/8
PASS → **ADMITTED_FOR_B6**, **execution_count = 0**. AcceptanceProfileV2
unchanged, bound via `acceptance-profile-generation-binding-v3.json`;
calibration NOT rerun.

Regression: 2680 passed (34 Gen-2/Gen-3 contract tests; the 2 known
pre-existing environment failures excluded — local Postgres auth, CORS
origin).

**B6 execution entry (next round, explicit authorization required)**:
Gen-3 execution preflight (load/validate/hash-check/bootstrap + FRESH
provisioning equivalence, zero model calls) → `enforce_execution_gate_v3`
→ 2 families × 3 repetitions = 6 scheduled runs → six-axis verdict under
the frozen profile.


## Acceptance Generation 3 (executed → B6_INVALID, CLOSED_INVALID)

B6 was executed 2026-10-01 under explicit authorization after the §1
Case-B superseding record (`d05f402d` re-run, 8/8 PASS): preflight ALL
PASS, execution gate passed, 6/6 scheduled attempts terminal, hard gates
PASS 6/6, evaluate-only 6/6 reproduced, run-set `3d3ee2e1…`, and **6/6
evidence-world run proofs** — every run's parsed evidence world matched
the sealed world exactly (the Gen-2 substrate defect was fixed).

**Verdict: B6_INVALID** (`EVIDENCE_CONTENT_SURFACE_TRANSIENT`).  The
production read surface cannot hydrate plain-text file content after the
pipeline's post-extraction cleanup of `extracted_files` (verified on a
production task as well): every delegation in every run found the files
indexed but content_preview null at both hydration levels, and honestly
reported BLOCKED — refusing to fabricate (0/6 fabricated citations,
P/H/S/G = 0, hard gates clean).  The sealed capability traps were
unreachable; the failure is the measurement's content layer, not agent
discipline (§11).  Generation-1's readable content had been an artifact
of the now-forbidden late injection.

Consequences per §34/§35: both Gen-3 families **CONSUMED**; **no second
Gen-3 B6**; formal acceptance **NOT ESTABLISHED**.  Generation 4 has a
PREREQUISITE: an independent production work item — a persistent/
hydratable content store for indexed loose-file evidence (the §25
STOP-and-separate-project rule) — then a new sealed generation with
fresh instances and explicit authorization.

Diagnostic (NOT formal evidence): functional 0/3 + 0/3; availability 1/6
(429) within budget; reliability clean; semantic/negative-case clean
(merges refused, causality refused in both directions, metadata
anomalies flagged not abused).

Records: `benchmarks/results/agent-v0/acceptance-gen3/` —
`agent-v0-acceptance-decision-v3.json`,
`acceptance-generation-closure-v3.json` (CLOSED_INVALID / NO RETRY),
`holdout-run-set-v3.json`, `holdout-acceptance-evaluation-v3.json`,
`holdout-execution-manifest-v3.json`, `holdout-bootstrap-preflight-v3.json`,
`gen3-b6-frozen-inputs-v1.json`,
`generation3-admission-audit-v1-superseding-record.json`.
