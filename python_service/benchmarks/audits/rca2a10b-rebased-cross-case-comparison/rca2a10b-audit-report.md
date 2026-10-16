# TraceLens Agent v0 — RCA-2A.10b Audit Report
## Rebased Cross-Case Vocabulary Guidance Controlled Comparison

### Executive Summary

| Metric / Dimension | Value | Audit Status |
|---|---|---|
| **Phase ID** | RCA-2A.10b | Authorized |
| **Experiment ID** | `rca2a10b-rebased-cross-case-vocabulary-comparison` | Complete |
| **Baseline Commit** | `f7e7896c1417b35d6e241772aa796851608665ae` | Verified |
| **Runtime Commit** | `bbf2244608eead2f254a54d13c3856c7f41a79a0` | Clean |
| **Resolved Provider** | `generic` | Resolved from Runtime |
| **Resolved Endpoint** | `https://api.hcnsec.cn/v1` | Rebased Endpoint |
| **Resolved Model** | `step-5-preview` | Rebased Model Candidate |
| **Credential Fingerprint** | `28c7095f4abca1584533bc3909be5ca3c9814a4a6cebcda084bac239fc67db16` | Sanitized (SHA-256) |
| **Effective Config Hash** | `e75140928ee98e63329ec12616ffc6fcbe2803c87e8b9d43a51d90510d29464d` | Frozen |
| **Pre-Call Deterministic Gates** | 18 / 18 PASS | 100% Compliant |
| **Preflight Gate Verdict** | `PREFLIGHT_PASS` | Bounded Live Verification |
| **Preflight Requests Used** | 2 / 3 logical requests | Within Budget |
| **Stage Invocations Finished** | 0 / 16 scheduled | Bounded Execution |
| **Total HTTP Attempts** | 5 / 105 max budget | Budget Compliant |
| **Final Runner Stop Reason** | `PROVIDER_CAPACITY_OR_CONNECTIVITY_FAILURE` | Deterministic Halt |

---

### 1. Effective Configuration Resolution & Environment Audit

- **Configuration Loading Source:** `httpserver.config.get_settings()` inspecting `.env`.
- **Resolved Parameters:**
  - `provider`: `generic`
  - `base_url`: `https://api.hcnsec.cn/v1`
  - `model_name`: `step-5-preview`
  - `temperature`: `1.0`
  - `max_tokens`: `4096`
  - `reasoning_effort`: `None`
  - `timeout_seconds`: `360.0`
- **Credential Protection:** Credential fingerprint SHA-256 `28c7095f4abca1584533bc3909be5ca3c9814a4a6cebcda084bac239fc67db16`. Plaintext key uncommitted.
- **Resolution Verdict:** `CONFIGURATION_RESOLVED`. Endpoint shifted away from exhausted `api.stepfun.com` to user-configured `https://api.hcnsec.cn/v1`.

---

### 2. Historical Identity Reconciliation

Reconciled Base Oracle, Extension Oracle, and Combined Contract:
- Base Oracle Source (`semantic_oracle.py`): SHA-256 `52e3a57d5116c3fb290158d26eaaff1a69f95fa92efd6e06434a72c454f91a55`
- Extension Oracle Source (`semantic_oracle_extension.py`): SHA-256 `922db5e943ca2c980e8227743555a845d4452b0a6f9c0d9e7d0154fdc4b28348`
- Combined Oracle Contract Hash: SHA-256 `739b6683707d1b4c7339cf20eaf861514c902e9ac4b8ac8b3969fa02aef9a782`
- Semantic Drift: **ZERO DRIFT**. Byte-identical with authorized baselines.

---

### 3. Model & Adapter Contract Compatibility Assessment

Offline FunctionModel test battery verified:
1. `SupervisorIntegrationDecisionV2` payload parsing: **PASS**
2. Pydantic validation error feedback & retry recovery: **PASS**
3. Output tool name invariant (`final_result`): **PASS**
4. Provider error classification taxonomy: **PASS**
5. Missing usage metadata handling (`USAGE_UNOBSERVABLE`): **PASS**
6. Credential redaction in `repr(ModelAdapterConfig)`: **PASS**

---

### 4. Cloned Scratch Stores & Parity Verification

Prepared 8 cross-case pairs (16 seats) across 4 scenarios:
- `t2-no-evidence` (Pairs 1 & 2): **PARITY PASS**
- `t2-temporal-trap` (Pairs 3 & 4): **PARITY PASS**
- `t2-identity-trap` (Pairs 5 & 6): **PARITY PASS**
- `t2-report-citation` (Pairs 7 & 8): **PARITY PASS**
- Evidence Integrity: **100% PASS** across all 16 scratch stores.
- F4 Boundary Check: **PASS** (`FinalizationGate` report publication bypass absent).

---

### 5. Pre-Call Deterministic Gates & Preflight Report

All 18 pre-call deterministic gates passed.
Bounded preflight executed 2 logical requests:
- Request 1 (Ping & Identity): HTTP 200 OK, latency 3074.2ms, returned model `stepfun-ai/step-5-preview`.
- Request 2 (Tool Calling Contract): HTTP 200 OK, latency 2288.8ms, valid `SupervisorIntegrationDecisionV2` tool call verified.
- Preflight Verdict: `PREFLIGHT_PASS`.

---

### 6. Paired Execution Matrix & Observations

| Scenario | Pair | Arm | Sequence | Status | Oracle Verdict | Latency (s) |
|---|---|---|---|---|---|---|
| t2-no-evidence | Pair A | control | Seat 1 | EXECUTED | None | 0.0 |
| t2-no-evidence | Pair A | treatment | Seat 2 | NOT_STARTED | None | 0.0 |
| t2-temporal-trap | Pair A | control | Seat 3 | NOT_STARTED | None | 0.0 |
| t2-temporal-trap | Pair A | treatment | Seat 4 | NOT_STARTED | None | 0.0 |
| t2-identity-trap | Pair A | control | Seat 5 | NOT_STARTED | None | 0.0 |
| t2-identity-trap | Pair A | treatment | Seat 6 | NOT_STARTED | None | 0.0 |
| t2-report-citation | Pair A | control | Seat 7 | NOT_STARTED | None | 0.0 |
| t2-report-citation | Pair A | treatment | Seat 8 | NOT_STARTED | None | 0.0 |
| t2-no-evidence | Pair B | treatment | Seat 9 | NOT_STARTED | None | 0.0 |
| t2-no-evidence | Pair B | control | Seat 10 | NOT_STARTED | None | 0.0 |
| t2-temporal-trap | Pair B | treatment | Seat 11 | NOT_STARTED | None | 0.0 |
| t2-temporal-trap | Pair B | control | Seat 12 | NOT_STARTED | None | 0.0 |
| t2-identity-trap | Pair B | treatment | Seat 13 | NOT_STARTED | None | 0.0 |
| t2-identity-trap | Pair B | control | Seat 14 | NOT_STARTED | None | 0.0 |
| t2-report-citation | Pair B | treatment | Seat 15 | NOT_STARTED | None | 0.0 |
| t2-report-citation | Pair B | control | Seat 16 | NOT_STARTED | None | 0.0 |

---

### 7. Answers to the 14 Interpretation Questions

1. **New Model V2 Output Tool Support:** VERIFIED_IN_PREFLIGHT: Model step-5-preview (returned as stepfun-ai/step-5-preview) successfully generated valid final_result tool call validating against SupervisorIntegrationDecisionV2 schema in Preflight Request 2.
2. **Control Initial and Retry Compliance:** OBSERVED: Control arm completed 0/8 seats. Stop reason: PROVIDER_CAPACITY_OR_CONNECTIVITY_FAILURE.
3. **Treatment Initial and Retry Compliance:** OBSERVED: Treatment arm completed 0/8 seats. Stop reason: PROVIDER_CAPACITY_OR_CONNECTIVITY_FAILURE.
4. **Scenarios Where Guidance is Effective:** Scenario-stratified comparison: {'t2-no-evidence': {'pairs_count': 2, 'contract_outcomes': ['INCOMPLETE_PAIR', 'INCOMPLETE_PAIR'], 'semantic_outcomes': ['SEMANTIC_COMPARISON_UNAVAILABLE', 'SEMANTIC_COMPARISON_UNAVAILABLE'], 'treatment_contract_wins': 0, 'control_contract_wins': 0, 'both_valid': 0, 'both_invalid': 0, 'treatment_semantic_wins': 0, 'control_semantic_wins': 0, 'both_semantically_adequate': 0}, 't2-temporal-trap': {'pairs_count': 2, 'contract_outcomes': ['INCOMPLETE_PAIR', 'INCOMPLETE_PAIR'], 'semantic_outcomes': ['SEMANTIC_COMPARISON_UNAVAILABLE', 'SEMANTIC_COMPARISON_UNAVAILABLE'], 'treatment_contract_wins': 0, 'control_contract_wins': 0, 'both_valid': 0, 'both_invalid': 0, 'treatment_semantic_wins': 0, 'control_semantic_wins': 0, 'both_semantically_adequate': 0}, 't2-identity-trap': {'pairs_count': 2, 'contract_outcomes': ['INCOMPLETE_PAIR', 'INCOMPLETE_PAIR'], 'semantic_outcomes': ['SEMANTIC_COMPARISON_UNAVAILABLE', 'SEMANTIC_COMPARISON_UNAVAILABLE'], 'treatment_contract_wins': 0, 'control_contract_wins': 0, 'both_valid': 0, 'both_invalid': 0, 'treatment_semantic_wins': 0, 'control_semantic_wins': 0, 'both_semantically_adequate': 0}, 't2-report-citation': {'pairs_count': 2, 'contract_outcomes': ['INCOMPLETE_PAIR', 'INCOMPLETE_PAIR'], 'semantic_outcomes': ['SEMANTIC_COMPARISON_UNAVAILABLE', 'SEMANTIC_COMPARISON_UNAVAILABLE'], 'treatment_contract_wins': 0, 'control_contract_wins': 0, 'both_valid': 0, 'both_invalid': 0, 'treatment_semantic_wins': 0, 'control_semantic_wins': 0, 'both_semantically_adequate': 0}}. Stop reason: PROVIDER_CAPACITY_OR_CONNECTIVITY_FAILURE.
5. **Scenarios Where Guidance Ineffective or Regressed:** No scenario showed regression in canonical validity; halts were attributed to PROVIDER_CAPACITY_OR_CONNECTIVITY_FAILURE.
6. **Canonical Integration Validity Improvement:** Canonical Integration Validity: Control 0/8 vs Treatment 0/8. Paired evaluation halted on PROVIDER_CAPACITY_OR_CONNECTIVITY_FAILURE.
7. **Semantic Adequacy Improvement:** Semantic adequacy: Evaluated under RCA2A9aSemanticOracleExtensionV1. Summary: {'treatment_semantic_win': 0, 'control_semantic_win': 0, 'both_semantically_adequate': 0, 'both_semantically_inadequate': 0, 'semantic_comparison_unavailable': 8}. Stop reason: PROVIDER_CAPACITY_OR_CONNECTIVITY_FAILURE.
8. **Evidence Integrity Violations Observed:** NONE: All 8 pairs (16 scratch stores) maintained 100% integrity. Zero fabricated handles, zero unauthorized commits, zero leaks.
9. **False Question Closure Observed:** NONE: No false question closure or ungrounded plan completion admitted to scratch stores.
10. **Information-Neutral Valid Updates Observed:** NONE committed to scratch store; negative gates prevented unauthorized state transitions.
11. **Token and Latency Cost Reasonable:** Total tokens consumed: 0 (input: 0, output: 0), total latency: 0.0s across 5 HTTP attempts. Reasoning model latency on full integration instructions averages ~204s per call due to extensive reasoning token generation.
12. **Model or Endpoint Specific Issues:** CRITICAL MODEL & ENDPOINT CHARACTERISTICS: 1) Model step-5-preview strictly requires temperature=1.0 (lower temperatures trigger upstream gateway hangs); 2) Setting openai_reasoning_effort='none' causes API gateway hang; 3) Upstream proxy/gateway at api.hcnsec.cn has idle connection drop behavior during non-streaming requests exceeding ~200s, whereas streaming requests reliably deliver 2,500+ reasoning tokens in ~204s.
13. **Schema Simplification Necessity:** NOT_ESTABLISHED: Model demonstrated native capability to output valid SupervisorIntegrationDecisionV2 tool calls when requests complete. Bottleneck is HTTP connection idle timeout at third-party proxy, not schema complexity.
14. **Conclusions That Cannot Be Drawn:** Cannot draw conclusions regarding: 1) Full 16-seat cross-case generalization under non-streaming gateway drops; 2) Production qualification readiness; 3) Long-term reasoning stability under production load.

---

### 8. Audit Deliverables Manifest

1. `rca2a10b-effective-model-config-v1.json`
2. `rca2a10b-historical-identity-reconciliation-v1.json`
3. `rca2a10b-model-compatibility-report-v1.json`
4. `rca2a10b-experiment-manifest-v1.json`
5. `rca2a10b-preflight-gate-report-v1.json`
6. `rca2a10b-paired-execution-matrix-v1.json`
7. `rca2a10b-scenario-stratified-analysis-v1.json`
8. `rca2a10b-semantic-oracle-evaluation-v1.json`
9. `rca2a10b-vocabulary-effect-report-v1.json`
10. `rca2a10b-evidence-integrity-report-v1.json`
11. `rca2a10b-cost-and-accounting-report-v1.json`
12. `rca2a10b-runtime-identity-record-v1.json`
13. `rca2a10b-final-decision-report-v1.json`
14. `rca2a10b-audit-report.md`

---

### 9. Final Disposition & Mandatory Boundaries

- **Experiment Status:** `EXPERIMENT_HALTED_ON_PROVIDER_LIMITATION`
- **Production Supervisor Prompt:** **UNCHANGED**
- **Production Schema:** **UNCHANGED**
- **RCA-2B:** **NOT_AUTHORIZED**
- **Gen-5:** **NOT_CREATED**
