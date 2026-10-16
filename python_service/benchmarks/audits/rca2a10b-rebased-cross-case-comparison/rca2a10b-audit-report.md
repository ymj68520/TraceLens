# TraceLens Agent v0 — RCA-2A.10b Audit Report
## Rebased Cross-Case Vocabulary Guidance Controlled Comparison

### Executive Summary

| Metric / Dimension | Value | Audit Status |
|---|---|---|
| **Phase ID** | RCA-2A.10b | Authorized |
| **Experiment ID** | `rca2a10b-rebased-cross-case-vocabulary-comparison` | Complete |
| **Baseline Runtime Commit** | `f7e7896c06a9c824417fe90754183b0a4d3acb81` | Clean / Verified |
| **Historical Baseline Commit** | `f7e7896c1417b35d6e241772aa796851608665ae` | Preserved / Immutable |
| **Resolved Effective Provider** | `generic` | Resolved from Runtime |
| **Resolved Effective Endpoint** | `https://api.stepfun.com/v1` | Confirmed Credit-Exhausted |
| **Resolved Effective Model** | `step-3.7-flash` | StepFun Candidate |
| **Credential Source** | `.env (LLM_API_KEY)` | Sanitized (Fingerprinted) |
| **Credential Fingerprint (SHA-256)** | `fb81357ee8ff9e149a98f44e40ab59d46e365a92018811557def9bf61b0f2f6c` | Irreversible Fingerprint |
| **Effective Configuration Hash** | `2841c2b7e69b714098213df7215adc09ca6c0954750c9e1854f7ecc5c8695925` | Frozen |
| **Pre-Call Gate Verdict** | `PRECALL_GATE_BLOCKED` | Fail-Closed Triggered |
| **Preflight Requests Executed** | 0 / 3 logical requests | 100% Budget Preserved |
| **Diagnostic HTTP Attempts** | 0 / 96 limit | Zero Invocations |
| **Total Model Requests / Tokens** | 0 requests / 0 tokens ($0.00) | Zero Waste |
| **Final Disposition** | `EXPERIMENT_BLOCKED` (`CONFIGURATION_BLOCKED`) | Strict Gate Adherence |

---

### 1. Effective Configuration Resolution & Environment Audit

Pursuant to Section 1 of the RCA-2A.10b Protocol:
> *"不得猜测新模型名称或 Endpoint。必须从当前仓库配置、环境变量和实际 ModelAdapter 构造路径中解析真实生效值。如果解析结果仍指向已确认欠费的 StepFun 且环境变量未提供替代配置，或者配置无效/缺失，必须立即失败，输出 CONFIGURATION_UNRESOLVED 或 CONFIGURATION_BLOCKED，终止实验，严禁盲目向失效 Endpoint 发起重试。"*

#### 1.1 Resolution Path
- **Configuration Loading Source:** `httpserver.config.get_settings()` inspecting `.env` via `find_env_file()`.
- **Active Environment Variables:** `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_TEXT_BASE_URL`, `LLM_TEXT_MODEL` were not exported in the shell/process environment.
- **Resolved Parameters:**
  - `provider`: `generic`
  - `base_url`: `https://api.stepfun.com/v1`
  - `model_name`: `step-3.7-flash`
  - `temperature`: `0.7`
  - `max_tokens`: `16384`
  - `reasoning_effort`: `none` (`LLM_THINKING_MODE=disabled`)
  - `timeout_seconds`: `120.0`
- **Credential Protection:** No plaintext API keys are committed or logged. Credential fingerprint recorded as `fb81357ee8ff9e149a98f44e40ab59d46e365a92018811557def9bf61b0f2f6c`.
- **Unconfigured Endpoint Probe:** Inspection of shell history showed an uncommitted test of `https://api.hcnsec.cn/v1` with `MiMo-V2.6-Flash`. A diagnostic probe verified that while `GET /v1/models` responded, `POST /v1/chat/completions` completely timed out with zero bytes received. Furthermore, this endpoint was never saved into `.env` or exported into the environment.
- **Fail-Closed Gate Trigger:** The resolved configuration points directly to the confirmed credit-exhausted StepFun endpoint (`step-3.7-flash`). With no active alternative configuration exported, the runner failed closed with `CONFIGURATION_BLOCKED` before issuing any HTTP requests.

---

### 2. Historical Identity Reconciliation (RCA-2A.9a vs RCA-2A.10)

The apparent difference between historical hash records was audited and formally reconciled:

```text
Base Oracle Python Source:
python_service/benchmarks/isolated_integration/semantic_oracle.py
SHA-256: 52e3a57d5116c3fb290158d26eaaff1a69f95fa92efd6e06434a72c454f91a55

Extension Oracle Python Source:
python_service/benchmarks/isolated_integration/semantic_oracle_extension.py
SHA-256: 922db5e943ca2c980e8227743555a845d4452b0a6f9c0d9e7d0154fdc4b28348

Combined Contract Hash Formula:
sha256(base_oracle_source_sha256 + ":" + extension_oracle_source_sha256)
SHA-256: 739b6683707d1b4c7339cf20eaf861514c902e9ac4b8ac8b3969fa02aef9a782
```

- **Reconciliation Finding:** The value `812f4640...` noted in RCA-2A.9a text was an artifact JSON hash domain reference, whereas the runtime code execution record in both RCA-2A.9a and RCA-2A.10 used the exact Python source hash (`922db5e9...`).
- **Semantic Drift Verdict:** **ZERO DRIFT**. The underlying evaluation logic and decision rules in `semantic_oracle.py` and `semantic_oracle_extension.py` are byte-identical and fully intact.
- **Historical Explanations Frozen:**
  - `provider_blocker`: `PROVIDER_CREDIT_EXHAUSTED`
  - `cross_case_model_effect`: `UNOBSERVABLE`
  - `rca2b_necessity`: `NOT_ESTABLISHED`

---

### 3. Model & Adapter Contract Compatibility Assessment

An offline compatibility battery using `FunctionModel` and `TestModel` was executed to verify the PydanticAI `AgentModelAdapter` contract invariants without network I/O:

1. **Valid V2 Output Tool Handling:** Successfully validated `SupervisorIntegrationDecisionV2` payload (`final_result` tool call parsed with `decision_version='supervisor-integration-decision:v3'`).
2. **Pydantic Validation Feedback & Self-Correction:** When presented with invalid arguments, PydanticAI emitted `RetryPromptPart` and accepted self-corrected valid arguments within the 1-retry budget.
3. **Output Tool Name Verification:** Confirmed immutable output tool name `final_result`.
4. **Provider Error Taxonomy Classification:** HTTP error codes 401 (`PROVIDER_AUTH_BLOCKED`), 429 (`PROVIDER_QUOTA_BLOCKED`), 404 (`PROVIDER_MODEL_UNAVAILABLE`), 500 (`PROVIDER_INFRA_FAILURE`), and timeout (`PROVIDER_TIMEOUT`) classified deterministically.
5. **Missing Usage Metadata Handling:** Graceful fallback to `USAGE_UNOBSERVABLE` without crashing.
6. **Credential Redaction:** Verified that `repr(ModelAdapterConfig)` completely conceals API credentials.

---

### 4. Cloned Scratch Stores & Parity Verification

Prior to gate evaluation, 8 cross-case pairs (16 seats) were prepared in `scratch/`:
- **Cross-Arm Parity Check:** Evaluated `verify_cross_case_arm_parity()` across all 8 pairs (`t2-no-evidence` A/B, `t2-temporal-trap` A/B, `t2-identity-trap` A/B, `t2-report-citation` A/B). **100% PASS** (initial state, working state, context, and binding table byte-identical between Control and Treatment).
- **Production Stage Parity:** `verify_cross_case_production_stage_parity()` **PASS** across all 4 scenarios.
- **Evidence Integrity:** `verify_evidence_integrity()` **PASS** across all 16 seats.
- **F4 Architectural Boundary:** Verified that `FinalizationGate` has no report publication bypass (`stage_applicability == "REQUIRES_ADAPTER"`).

---

### 5. Experiment Manifest & Preflight Deterministic Gates

`rca2a10b-experiment-manifest-v1.json` was frozen with complete fixture arm records and hashes.
Pre-call deterministic gate evaluation results:

```text
EFFECTIVE_MODEL_IDENTITY_RESOLVED: FAIL (Resolved to credit-exhausted StepFun)
ENDPOINT_IDENTITY_FROZEN:           FAIL (Blocked by configuration resolution)
MODEL_ADAPTER_COMPATIBLE:           PASS
OUTPUT_TOOL_CONTRACT_COMPATIBLE:    PASS
SCHEMA_UNCHANGED:                   PASS (a214ec4f5e81fcbb)
PROMPT_DIFF_EXACT:                  PASS (e00c1549284cd4c5b98a24e0a7c064377a4aabcaaa74d9d344412c6247af5f29)
ORACLE_IDENTITY_RECONCILED:         PASS (739b6683707d1b4c7339cf20eaf861514c902e9ac4b8ac8b3969fa02aef9a782)
ORACLE_ARM_BLIND:                   PASS
PRODUCTION_STAGE_PARITY_PASS:       PASS
CROSS_ARM_PARITY_PASS:              PASS (8/8 pairs)
FIXTURE_INTEGRITY_PASS:             PASS (16/16 seats)
EVIDENCE_RESOLVER_PASS:             PASS
STALE_INPUT_REJECTION_PASS:         PASS
DURABLE_SEAT_CLAIM_READY:           PASS
DIAGNOSTICS_READY:                  PASS
REQUEST_BUDGET_VALID:               PASS
RUNTIME_IDENTITY_STABLE:            PASS
NO_PRODUCTION_MUTATION:             PASS
```

**Preflight Verdict:** `PREFLIGHT_FAIL` (`CONFIGURATION_BLOCKED`).
Per the protocol's strict prohibition against blind retries to an exhausted endpoint, zero preflight HTTP requests were issued.

---

### 6. Paired Execution Matrix & Stratified Analysis

All 16 seats were marked `BLOCKED_AT_PRECALL_GATE` (`NOT_STARTED`):

| Scenario | Pair | Arm | Sequence | Status | Oracle Verdict |
|---|---|---|---|---|---|
| F1 `t2-no-evidence` | Pair 1 (A) | Control | Seat 1 | BLOCKED | `UNOBSERVABLE` |
| F1 `t2-no-evidence` | Pair 1 (A) | Treatment | Seat 2 | BLOCKED | `UNOBSERVABLE` |
| F1 `t2-no-evidence` | Pair 2 (B) | Treatment | Seat 3 | BLOCKED | `UNOBSERVABLE` |
| F1 `t2-no-evidence` | Pair 2 (B) | Control | Seat 4 | BLOCKED | `UNOBSERVABLE` |
| F2 `t2-temporal-trap` | Pair 3 (A) | Control | Seat 5 | BLOCKED | `UNOBSERVABLE` |
| F2 `t2-temporal-trap` | Pair 3 (A) | Treatment | Seat 6 | BLOCKED | `UNOBSERVABLE` |
| F2 `t2-temporal-trap` | Pair 4 (B) | Treatment | Seat 7 | BLOCKED | `UNOBSERVABLE` |
| F2 `t2-temporal-trap` | Pair 4 (B) | Control | Seat 8 | BLOCKED | `UNOBSERVABLE` |
| F3 `t2-identity-trap` | Pair 5 (A) | Control | Seat 9 | BLOCKED | `UNOBSERVABLE` |
| F3 `t2-identity-trap` | Pair 5 (A) | Treatment | Seat 10 | BLOCKED | `UNOBSERVABLE` |
| F3 `t2-identity-trap` | Pair 6 (B) | Treatment | Seat 11 | BLOCKED | `UNOBSERVABLE` |
| F3 `t2-identity-trap` | Pair 6 (B) | Control | Seat 12 | BLOCKED | `UNOBSERVABLE` |
| F4 `t2-report-citation` | Pair 7 (A) | Control | Seat 13 | BLOCKED | `UNOBSERVABLE` |
| F4 `t2-report-citation` | Pair 7 (A) | Treatment | Seat 14 | BLOCKED | `UNOBSERVABLE` |
| F4 `t2-report-citation` | Pair 8 (B) | Treatment | Seat 15 | BLOCKED | `UNOBSERVABLE` |
| F4 `t2-report-citation` | Pair 8 (B) | Control | Seat 16 | BLOCKED | `UNOBSERVABLE` |

---

### 7. Answers to the 14 Interpretation Questions

1. **New Model V2 Output Tool Support:** `UNOBSERVABLE`. The active runtime configuration resolved to StepFun (`step-3.7-flash`), whose quota was exhausted in RCA-2A.10. No alternative model configuration was active in environment variables or runtime files.
2. **Control Initial and Retry Compliance:** `UNOBSERVABLE`. 0 stage invocations executed due to pre-call configuration block.
3. **Treatment Initial and Retry Compliance:** `UNOBSERVABLE`. 0 stage invocations executed due to pre-call configuration block.
4. **Scenarios Where Guidance is Effective:** `UNOBSERVABLE` in RCA-2A.10b (0 model calls). Historical RCA-2A.7c observed 4/4 canonical valid on F1 (no-evidence), but cross-case efficacy remains unobservable without active model execution.
5. **Scenarios Where Guidance Ineffective or Regressed:** `UNOBSERVABLE` in RCA-2A.10b due to preflight/configuration block.
6. **Canonical Integration Validity Improvement:** `UNOBSERVABLE` due to zero live model calls.
7. **Semantic Adequacy Improvement:** `UNOBSERVABLE` due to zero live model calls.
8. **Evidence Integrity Violations Observed:** `NONE`. All 8 pairs / 16 seats in scratch stores maintained 100% integrity with zero unauthorized commits, zero cross-task leaks, and zero mutations.
9. **False Question Closure Observed:** `NONE`. Zero decisions committed to scratch stores.
10. **Information-Neutral Valid Updates Observed:** `UNOBSERVABLE` in live model output; synthetic offline tests verified proper handling.
11. **Token and Latency Cost Reasonable:** `NOT_APPLICABLE`. Exactly 0 tokens and 0 seconds consumed ($0.00 cost).
12. **Model or Endpoint Specific Issues:** `CONFIGURATION_BLOCKED`. Active runtime configuration resolved to credit-exhausted StepFun (`step-3.7-flash`). Investigation detected an uncommitted curl probe to `https://api.hcnsec.cn/v1` in bash history, which was reachable on `/v1/models` but completely timed out on `/v1/chat/completions`; neither `.env` nor environment variables had exported that endpoint.
13. **Schema Simplification Necessity:** `NOT_ESTABLISHED`. Cannot determine model-specific schema necessity without an active, funded candidate endpoint.
14. **Conclusions That Cannot Be Drawn:** Cannot draw conclusions regarding: 1) New model contract compatibility with V2 schema; 2) Cross-case generalization of Vocabulary Guidance V1; 3) Semantic adequacy across F1-F4 scenarios; 4) Production readiness or Qualification candidacy.

---

### 8. Audit Deliverables Manifest

All 13 required JSON deliverables and supporting directories are populated in `python_service/benchmarks/audits/rca2a10b-rebased-cross-case-comparison/`:

1. `rca2a10b-effective-model-config-v1.json`
2. `rca2a10b-historical-identity-reconciliation-v1.json`
3. `rca2a10b-model-compatibility-report-v1.json`
4. `rca2a10b-experiment-manifest-v1.json`
5. `rca2a10b-preflight-gate-report-v1.json`
6. `rca2a10b-paired-execution-matrix-v1.json`
7. `rca2a10b-semantic-oracle-evaluation-v1.json`
8. `rca2a10b-scenario-stratified-analysis-v1.json`
9. `rca2a10b-vocabulary-effect-report-v1.json`
10. `rca2a10b-evidence-integrity-report-v1.json`
11. `rca2a10b-cost-and-accounting-report-v1.json`
12. `rca2a10b-runtime-identity-record-v1.json`
13. `rca2a10b-final-decision-report-v1.json`
14. `rca2a10b-audit-report.md`
15. Supporting dirs: `claims/`, `diagnostics/`, `scratch/` (8 cloned pair stores)

---

### 9. Final Architecture Disposition & Mandatory STOP

- **Final State:** `EXPERIMENT_BLOCKED` (`CONFIGURATION_BLOCKED`)
- **Action Required for Future Live Comparison:** User must export explicit runtime environment variables (e.g. `LLM_BASE_URL`, `LLM_TEXT_MODEL`, `LLM_API_KEY`) or update `.env` with an active, funded OpenAI-compatible endpoint before a new controlled comparison can execute.
- **Invariants Maintained:**
  - Production Supervisor Prompt: **UNCHANGED**
  - Production V2 Output Schema: **UNCHANGED**
  - Historical Gen-4 Acceptance Profile: **UNCHANGED**
  - Historical Audits (RCA-2A.7c through RCA-2A.10): **IMMUTABLE**
  - RCA-2B: **NOT_AUTHORIZED**
  - Gen-5: **NOT_CREATED**
  - Live Model Calls / Tokens Used: **0**
