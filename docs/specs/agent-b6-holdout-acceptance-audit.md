# B6 — Sealed Holdout Final Acceptance Audit

Status: **EXECUTED → AgentV0AcceptanceDecisionV1 = REJECTED (functional axis)**
Round completed 2026-10-01. Post-B6: **NO TUNING** (spec §33/§38 STOP).

Authorization: explicit user directive (B6 AUTHORIZED; AcceptanceProfileV2
FROZEN / ADMITTED_FOR_B6; Calibration ZERO_CHANGE; production runtime
frozen; holdout SEALED until entry).

## Entry chain (before the first model call)

| step | artifact | hash |
|---|---|---|
| B6-entry public charter (Case B association declared) | `benchmarks/profiles/b6-holdout-charter-v1.json` | `34c888e4349bbdef…` (input_hash) |
| deterministic holdout preflight G1–G8, ZERO model calls | `b6-holdout/holdout-bootstrap-preflight-v1.json` | ALL PASS (2/2 cases) |
| frozen identities (§1) | `b6-holdout/frozen-identities-v1.json` | `bec05939768d0504…` @ HEAD `49e8172e` |
| preflight commit / driver commit | `211f081e` / `49e8172e` | — |

Charter derivation was PUBLIC-SURFACE ONLY (agent-visible dataset README +
case contract v2 `required_coverage_dimensions` + `negative_flags`);
truth manifests were never read during chartering or preflight (G8b checks
the sealed canonical hash against the corpus binding, hash-only).  The
association contract: one charter question per family, every required
dimension → `q-1` (declared in the charter, not driver-guessed, not
truth-derived).  `t1-usb-collector` (third corpus acceptance entry) is NOT
in the B6 population and remains SEALED / NEVER RUN.

## Execution (§7/§8)

2 families × 3 repetitions = 6 scheduled attempts, case-major, every
attempt fresh task/investigation/run/state.  No best-of, no replacement,
no discard; the frozen provider-internal retry only.  `B6_STARTED` at the
first holdout model request (recorded in
`holdout-execution-manifest-v1.json`); runtime frozen from that moment.

Artifacts persisted per attempt BEFORE lifecycle cleanup; evaluate-only
reproduction verified per completed run (6/6 hash-identical).

## Results

| run | terminal | CaseOutcomeV2 | finalization | integrated |
|---|---|---|---|---|
| refund-fraud repeat0 | completed | incomplete (coverage=partial) | yes | 1 |
| refund-fraud repeat1 | completed | incomplete (no output) | denied COVERAGE_NOT_TERMINAL | 0 |
| refund-fraud repeat2 | completed | incomplete (coverage not updated) | denied COVERAGE_NOT_TERMINAL | 1 |
| vpn-causal repeat0 | completed | **success** | yes | 1 |
| vpn-causal repeat1 | completed | incomplete (no output) | denied COVERAGE_NOT_TERMINAL | 0 |
| vpn-causal repeat2 | completed | incomplete (no output) | denied COVERAGE_NOT_TERMINAL | 0 |

P = H = S = G = 0.  Structural hard gates PASS 6/6.  PLAN_DUPLICATE 0.
Provider failures 0.  Run-set hash `58f418ec1308680b…`.

## Six axes (frozen AcceptanceProfileV2)

| axis | verdict | evidence |
|---|---|---|
| structural | PASS | 0 violations of any zero-tolerance gate (independent snapshot recompute) |
| **functional** | **FAIL** | truth floor requires EVERY family ≥2/3 at {success, success_with_limitations}: refund-fraud **0/3**, vpn-causal **1/3** |
| semantic | PASS | 0 unsupported FACT, 0 fabricated citation (deterministic ref check 6/6); HYPOTHESIS/INFERENCE assertion boxing correct |
| negative-case | PASS | 0 identity merges (vpn r0 explicitly refuses and challenges the "matching username" premise), 0 causal escalations (26 s contiguity explicitly non-causal), 0 fabricated support (attribution refused; RF-9003 recorded as anomaly, not fraud), README always treated as examiner context, never evidence |
| reliability | PASS (at ceiling) | specialist structured-output failures 3/6 = 50.0% ≤ 50% ceiling; supervisor plan/integrate 0/6 ≤ 20% |
| availability | PASS | provider-terminal 0/6 = 0% ≤ 20% |

**Overall: REJECTED** — frozen rule: any floor miss ⇒ REJECTED; no
conditional pass.

## Failure anatomy (diagnosis, not a tuning mandate)

1. **Model output (3/6 runs):** specialist `agent_output_invalid` → zero
   completed delegations → coverage never terminal → finalization denied.
   Same class as the calibration specialist wall; episodic there (2/24),
   dense here (3/6).  The specialist proposal contract removed the
   systematic cause; the residual is model schema discipline.
2. **Supervisor closure discipline (1/6 runs):** refund repeat2 completed
   and integrated a delegation but never terminalized coverage/question →
   `COVERAGE_NOT_TERMINAL`.  This is the supervisor question/coverage
   closure lever already recorded after B5.5 — a product work item for a
   FUTURE generation, not a B6 remediation.
3. When the model performs (vpn repeat0), the full chain reaches a
   truth-semantically correct terminal: coverage covered, question
   answered/not_supported, identity and causality both refused with
   correct assertion boxing.

## Component status (§24)

CorrelationAgent NOT_EXERCISED; SemanticVerifier NOT_EXERCISED (mandatory
final-review path not reached; frozen benchmark wiring best_effort);
report path REPORT_PATH_NOT_REACHED (disabled in the frozen contract —
not opened for acceptance).

## Rejection semantics (§32/§33)

This verdict means: the CURRENT frozen runtime + sensenova-6.8-flash-lite
did not meet the frozen AgentV0AcceptanceProfileV2 truth floor on the
sealed holdout.  It does NOT mean the TraceLens architecture failed, and
it does NOT authorize lowering thresholds, modifying the holdout, or
holdout-targeted prompt/contract changes.  Any future attempt requires a
NEW development generation + NEW acceptance protocol; this sealed holdout
can no longer serve as a calibration set.

## Preservation (§34)

Original sealed manifests untouched (G8b verified pre/post); pre-execution
hashes, all six run artifact sets, run-set hash, profile hashes, binding
hashes, and the verdict artifact are committed under
`benchmarks/results/agent-v0/b6-holdout/`.
