# TraceLens Agent v0 — RCA-2A.11a Audit Report
## Negative Gate Causality & Commit Integrity Audit

### Executive Summary

| Dimension / Metric | Finding / Audit Verdict | Status |
|---|---|---|
| **Audit ID** | `rca2a11a-negative-gate-causality-audit` | Authorized Forensic Audit |
| **Baseline Commit** | `dbdda63fdf` | Verified Ancestor |
| **Runtime Commit** | `afbeb55bf7` | Verified Ancestor |
| **Artifact Commit** | `7707279c35` | Verified Baseline |
| **Final Dispositions** | `SEMANTIC_FAILURE_WITH_EFFECTIVE_CONTAINMENT`<br>`BENCHMARK_ACCOUNTING_DEFECT_CONFIRMED`<br>`SEMANTIC_REVIEW_BOUNDARY_IDENTIFIED` | Multi-Factor Classification |
| **Seat 5 Commit Causality** | `UNSUPPORTED_ASSERTION_COMMITTED_TO_SCRATCH` | Scratch DB Only |
| **Production State Mutation** | **ZERO (0 Mutations)** | Absolute Containment |
| **Canonical Finding Promotion** | **ZERO (0 Finding Mutations)** | Contained in Working State |
| **Pydantic Validity Rate (Executed)** | **5 / 5 (100.0%)** | 3/3 Control, 2/2 Treatment |
| **Planned Schedule Coverage** | Control: 3/8 (37.5%), Treatment: 2/8 (25.0%) | 11 Seats Unstarted |
| **F1 (`t2-no-evidence`) Outcome** | `BOTH_INVALID` (Rejected before commit) | L3 Policy Rejected Both |
| **F2 (`t2-temporal-trap`) Outcome** | **`TREATMENT_WIN`** (Passed L1–L5 cleanly) | Genuine Positive Discovery |
| **F3 (`t2-identity-trap`) Outcome** | `INCOMPLETE_PAIR` (Seat 5 Control halted experiment) | Stop Reason Refined |
| **Production Safety Boundary** | **UNCHANGED (DEFENSE_WORKING_AS_DESIGNED)** | No Gaps Identified |
| **Status** | **HARD STOP** | Append-Only Closure |

---

### 1. Priority P0 — Seat 5 Commit Causality Forensic Breakdown

1. **What did `COMMITTED` in the Stop Reason signify?**
   - In `cross_case_runner.py` line 751, the check `elif record["stage_layers"].get("scratch_commit_success"):` evaluated to `True`.
   - The stage harness executed `commit_agent_integration()` on the **isolated temporary clone SQLite database** located in `python_service/benchmarks/scratch/rca2a11_scratch/`.
   - The runner appended `_COMMITTED` to signal that the stage's local scratch transaction had committed before the post-commit Semantic Oracle flagged the payload.
   - **It did NOT indicate any write to the production database or canonical finding tables.**

2. **What was actually written to SQLite?**
   - Written to Scratch SQLite:
     - `agent_working_state_revisions`: inserted revision 1 with `AgentWorkingStateV1` containing the hypothesis in `hypotheses`.
     - `agent_trajectories`: appended `supervisor_integration_committed` audit event.
     - `agent_delegations`: updated `integrated_at` timestamp.
   - **NOT written to Scratch or Production:**
     - `findings`: Zero records (no finding created or accepted).
     - `questions`: Zero records (question was NOT closed).
     - `coverage`: Zero records.
     - `canonical entity tables`: Zero records (no entity merge occurred).

3. **Assertion Class Distinction:**
   - The model wrapped its unproven claim in `CreateHypothesisActionV2` (`HYPOTHESIS`).
   - In the TraceLens domain model, a hypothesis is an investigative conjecture that remains unadmitted until subsequent verification and analyst acceptance.
   - The model did not and could not promote the hypothesis to an accepted FACT.

---

### 2. Multi-Layer Commit Safety Boundary Assessment

- **Case A (Deterministic Guard Gap):** NOT OBSERVED. All deterministic policy checks (schema, handles, question closure basis, verification prerequisites) executed correctly.
- **Case B (Semantic Sufficiency Gap):** CONFIRMED. The model cited valid handles within the task, but the evidence did not prove that two cross-system accounts belonged to the same person.
- **Containment:** Because hypotheses do not mutate canonical findings or close charter questions, production safety was fully preserved (`DEFENSE_WORKING_AS_DESIGNED`).

---

### 3. F1 and F2 Detailed Verification

- **F1 (`t2-no-evidence`):**
  - Control attempted question closure without basis refs, rejected by `StateTransitionPolicy` (`QUESTION_CLOSURE_BASIS_REQUIRED`, `QUESTION_CLOSURE_VERIFICATION_REQUIRED`).
  - Treatment attempted question update without basis, rejected by `StateTransitionPolicy` (`QUESTION_CLOSURE_BASIS_REQUIRED`).
  - Both rejected before commit (`INVALID_PROPOSAL_REJECTED_BEFORE_COMMIT`). Pair outcome: `BOTH_INVALID`.
- **F2 (`t2-temporal-trap`):**
  - Control attempted unverified causal question closure, rejected by `StateTransitionPolicy`.
  - Treatment formulated a disciplined hypothesis acknowledging temporal sequence while explicitly stating that temporal proximity does not establish causality. Passed L1–L5 cleanly (`POSITIVE_DISCOVERY`).
  - Outcome: **`TREATMENT_WIN`** under blind oracle rules.

---

### 4. Statistical Accounting Correction

- **Initial Pydantic Parse Validity Rate:** 5 / 5 (100.0%) across all executed seats.
- **Schedule Execution Coverage:** Control 3/8 (37.5%), Treatment 2/8 (25.0%).
- **Pair Outcomes:** Completed: 2/8 (1 Both Invalid, 1 Treatment Win); Incomplete: 6/8.
- **Guidance Token Delta:** Exactly **+312 input tokens** on both static prompt inspection and wire provider telemetry.
- **Cross-Case Verdict:** `INSUFFICIENT_EVIDENCE` for production qualification due to early halt.

---

### 5. Exit Gate Answers Summary

| Gate Question | Audit Answer | Key Evidence |
|---|---|---|
| **Q1: Meaning of `COMMITTED`** | Isolated Scratch DB commit only | `scratch_commit_success == True` in harness |
| **Q2: SQLite COMMIT Occurred** | YES in scratch DB; ZERO in production | `commit_agent_integration` on clone DB |
| **Q3: Tables & Fields Written** | `agent_working_state_revisions` (rev=1) | No findings, questions, or merges written |
| **Q4: Assertion Class** | `HYPOTHESIS` | `CreateHypothesisActionV2` |
| **Q5: Unsupported Promotion** | YES in NL text; NO in database authority | NL "same person" in hypothesis text |
| **Q6: Defect Classification** | R1 (Model) + R2 (Runner) + R5 (Boundary) | Multi-factor classification |
| **Q7: F1 False Closure Blocked** | YES | Rejected by `StateTransitionPolicy` |
| **Q8: F1 Treatment Invalid Reason** | Rejected by `StateTransitionPolicy` | `QUESTION_CLOSURE_BASIS_REQUIRED` |
| **Q9: F2 Positive Discovery** | YES, confirmed | Passed L1–L5, no causal overclaim |
| **Q10: F2 Control Causal Overclaim** | YES, confirmed | Rejected by `StateTransitionPolicy` |
| **Q11: Denominator Correctness** | Executed: 5/5 (100%); Planned: 5/16 (31.25%) | Disambiguated in accounting amendment |
| **Q12: Production Safety Gap** | NO gap | Defenses worked as designed |
| **Q13: Unadmitted Fact Containment** | YES, guaranteed | FinalizationGate & Report Admission |
| **Q14: Future Comparison Feasibility**| YES | With refined runner stop taxonomy |

---

### 6. Architectural Freeze & Mandatory STOP

- **Production Supervisor Prompt:** UNCHANGED
- **Production Supervisor Schema:** UNCHANGED
- **Production StateTransitionPolicy:** UNCHANGED
- **EvidenceResolver & GroundingValidator:** UNCHANGED
- **FinalizationGate & Report Admission:** UNCHANGED
- **RCA-2B:** NOT AUTHORIZED
- **Gen-5:** NOT CREATED
- **Status:** HARD STOP
