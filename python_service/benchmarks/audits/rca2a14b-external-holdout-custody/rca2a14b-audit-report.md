# TraceLens Agent v0 — RCA-2A.14b Audit Report
## External Holdout Custody Activation & Sealed Dataset Intake

**Status: EXTERNAL_CUSTODY_NOT_AVAILABLE**  
**Execution Mode: STRICT OFFLINE PREPARATION (0 Real Provider Requests)**  
**Target Next Phase: RCA-2A.14 (NOT_AUTHORIZED)**  
**Parent Baseline Commit (RCA-2A.14a):** `ce5649e37f5791d250dc87e23910aec2c75464e6`

---

### Executive Summary

Phase **RCA-2A.14b** audited external custody activation conditions, prepared the complete operational handoff package for external collaborators, verified the dataset intake schema contracts and cryptographic sealing interfaces, and conducted comprehensive offline deterministic regression.

1. **Custody Infrastructure & Independence Assessment:**  
   - Evaluated actual custody conditions against the 5-role custody matrix.
   - Verified that while roles and protocols are formally defined, no independent external custodian is actually assigned or provisioned in reality (`custodian_identity: NOT_ASSIGNED`, `independent_storage_boundary: NOT_ESTABLISHED`).
   - The coding agent strictly adheres to the P0 non-negotiable rule: an agent with workspace-wide read access cannot act as an independent custodian or self-certify custody.
   - Status honestly ruled as **`EXTERNAL_CUSTODY_NOT_AVAILABLE`**. Formal sealed holdout case count remains **`0`**.

2. **External Custodian Handoff Package Prepared:**  
   - Generated an actionable external collaborator operational package (`RCA2A14bExternalCustodianHandoffV1`) containing:
     - `HoldoutAuthorInstructionsV1` (novel scenario rules across Q1–Q6 families, strict prohibition on recycling F1–F4).
     - `CustodianOperationsGuideV1` (verification of author independence, evidence/truth consistency, cryptographic commitments, external storage boundary).
     - `CasePackageSchemaV1` (JSON schema for `ModelVisibleCaseInput`).
     - `TruthManifestSchemaV1` (JSON schema for `SealedGroundTruth`).
     - `CustodyAttestationTemplateV1` (formal non-repudiation template).
     - `SealingVerificationGuideV1` (canonical JSON serialization and salt nonce verification).
     - `QualificationDataReleaseProtocolV1` (two-phase release separating execution from post-freeze adjudication).
   - Maintained strict output separation: `PUBLIC_PROTOCOL`, `MODEL_VISIBLE_CASE_INPUT`, `SEALED_GROUND_TRUTH`, and `CUSTODY_ATTESTATION`. Zero ground truth or private keys were admitted into the repository workspace.

3. **Dataset Contract & Sealing Verification:**  
   - Formalized intake verification gates: `CASE_ID_UNIQUE`, `CASE_VERSION_FROZEN`, `EVIDENCE_SCOPE_VALID`, `EVIDENCE_KEY_RESOLVABLE`, `SOURCE_CAPABILITY_CONSISTENT`, `INPUT_TRUTH_SEPARATED`, `HOLDOUT_NOVELTY_ATTESTED`, and `CANDIDATE_IDENTITY_FROZEN`.
   - Clarified the cryptographic distinction: `Hash Commitment != Encryption != Access Control`. Hash commitments verify integrity; confidentiality requires external key management; access control requires independent storage.
   - Current truth sealing status is declared as **`HOLDOUT_NOT_SEALED`**. Test mock fixtures are strictly excluded from official qualification case accounting.

4. **Statistical Hierarchy & Sample Size Binding:**  
   - Bound statistical plan to the actual holdout inventory.
   - Reaffirmed required sample sizes for 80% confirmatory power at $\alpha=0.05$: **38 pairs (76 seats)** for a +30pp target; **52 pairs (104 seats)** for a +25pp target.
   - With 0 actual pairs available, status is ruled **`QUALIFICATION_SAMPLE_SIZE_INSUFFICIENT`**. Established the binding rule: underpowered screening runs ($N < 38$ pairs) yielding $p \ge 0.05$ with positive effect must be declared `QUALIFICATION_INCONCLUSIVE`, never `PASS`.

5. **Controlled Intake & Adjudication Readiness:**  
   - Designed the controlled intake pipeline ensuring executor access is strictly limited to `ModelVisibleCaseInput`.
   - Formalized and verified 10 negative gate policies:
     `UNAUTHORIZED_TRUTH_READ_DENIED`, `MISSING_CUSTODIAN_BLOCKED`, `INVALID_SEAL_BLOCKED`, `CASE_HASH_DRIFT_BLOCKED`, `TRUTH_HASH_DRIFT_BLOCKED`, `DUPLICATE_CASE_ID_BLOCKED`, `EXPOSED_DEVELOPMENT_FIXTURE_BLOCKED`, `CANDIDATE_HASH_DRIFT_BLOCKED`, `UNSEALED_ANSWER_LEAKAGE_BLOCKED`, `MISSING_ATTESTATION_BLOCKED`.
   - Identified high-risk semantic domains requiring mandatory double-blind human review (Identity Attribution, Causal Sufficiency, Unsupported FACT, Question Closure). Adjudicator status is recorded as **`ADJUDICATOR_NOT_ASSIGNED`**.

6. **Offline Deterministic Verification & Full Regression:**  
   - Implemented 19 deterministic offline simulation tests (T01–T19) in `test_rca2a14b_custody_intake.py`: **19/19 PASSED (100%)** in 3.00s.
   - Focused multi-phase regression (14b, 14a, 13, 12, 11b, 9a): **137/137 PASSED (100%)** in 40.55s.
   - Benchmark regression (`tests/unit/benchmarks/`): **455/455 PASSED (100%)** in 227.73s.
   - Investigation safety regression (`tests/unit/investigation/`): **1067 PASSED (1 skipped, 0 failed)** in 68.00s.
   - Real provider requests: **0** (strictly offline).

---

### Component Accounting: Added / Modified / Reused

| Component | Status | Location / Details |
|---|---|---|
| `test_rca2a14b_custody_intake.py` | **ADDED** | 19 deterministic simulation tests (T01–T19) validating intake gates, sealing, and fail-closed paths. |
| 9 Versioned Audit Reports (JSON) | **ADDED** | `benchmarks/audits/rca2a14b-external-holdout-custody/` |
| `rca2a14b-audit-report.md` | **ADDED** | In-tree formal audit report. |
| `rca2a14b_audit_report.md` | **ADDED** | User-facing brain artifact. |
| `SupervisorIntegrationDecisionV2` | **REUSED (UNCHANGED)** | Output schema hash `a214ec4f5e81fcbb` untouched. |
| `GUIDANCE_TEXT` / `guidance_sha256()` | **REUSED (UNCHANGED)** | Guidance V1 hash `e00c1549...` confirmed identical. |
| Production Supervisor Prompt | **REUSED (UNCHANGED)** | Production instructions untouched. |
| `STOP_POLICY_CONTRACT_V2` | **REUSED (UNCHANGED)** | Reused StopPolicyV2 decoupled containment logic. |
| Semantic Oracle L1–L5 | **REUSED (UNCHANGED)** | Tiered oracle reused for evaluation logic. |
| `cross_case_runner.py` | **REUSED (UNCHANGED)** | Runner scheduling, claims, and telemetry reused. |
| Production Resolver, Policy, Gates | **REUSED (UNCHANGED)** | Zero production code touched. |

---

### Mandatory Metrics Accounting

```text
actual_holdout_case_count:     0 (PENDING_EXTERNAL_DELIVERY)
actual_sealed_case_count:      0 (HOLDOUT_NOT_SEALED)
actual_custodian_status:       NOT_ASSIGNED
actual_adjudicator_status:     NOT_ASSIGNED
actual_access_isolation:       UNVERIFIED (SINGLE_WORKSPACE)
actual_model_request_count:    0 (STRICTLY_OFFLINE)
```

---

### Outstanding Blockers

1. **Independent Custodian Provisioning:** External collaborator organization/personnel must accept custodian role and establish isolated storage outside the repository.
2. **Novel Holdout Case Authoring:** External author must compose clean Q1–Q6 case bundles with verified synthetic evidence tuples `(task_id, evidence_key)`.
3. **Cryptographic Sealing & Attestation:** Custodian must compute SHA-256 commitments over canonical JSON, hold salt nonces securely, and submit a signed `CustodyAttestation`.
4. **Independent Adjudication Panel:** Human subject-matter experts must be recruited and assigned for double-blind review of high-risk semantic decisions.

---

### Required Human Actions

1. Designate and provision an external, independent Holdout Custodian and Author outside the TraceLens repository workspace.
2. Handoff `RCA2A14bExternalCustodianHandoffV1` specifications to the designated external team.
3. Establish external secure storage (e.g. KMS-backed S3 bucket) with strict IAM policies excluding candidate developers and automated agents.
4. Deliver formal attested dataset meeting minimum confirmatory sample size ($\ge 38$ pairs for +30pp target).

---

### Recommended Next Authorization

**Authorization: OFFLINE EXTERNAL CUSTODIAN PROVISIONING ONLY**  
Do NOT authorize RCA-2A.14 or any real model execution until the independent custodian has officially submitted a signed `CustodyAttestation` and sealed case bundles have passed automated verification.

---

### Final Architectural Disposition

```text
RCA-2A.11:   EXPERIMENT_HALTED (FROZEN)
RCA-2A.11a:  AUDIT_COMPLETED (FROZEN)
RCA-2A.11b:  BENCHMARK_HARDENED (FROZEN)
RCA-2A.12:   CROSS_CASE_COMPARISON_COMPLETED (FROZEN)
RCA-2A.13:   QUALIFICATION_PROTOCOL_READY_WITH_LIMITATIONS (FROZEN)
RCA-2A.14a:  PROTOCOL_READY_CUSTODY_BLOCKED (FROZEN)
RCA-2A.14b:  EXTERNAL_CUSTODY_NOT_AVAILABLE
RCA-2A.14:   NOT_AUTHORIZED

Production Prompt: UNCHANGED (supervisor-v2)
Production Schema: UNCHANGED (SupervisorIntegrationDecisionV2)
Gen-5:             NOT_CREATED
RCA-2B:            NOT_AUTHORIZED
```

**MANDATORY HARD STOP ENFORCED.**
