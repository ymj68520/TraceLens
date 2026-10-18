# TraceLens Agent v0 — RCA-2A.13 Audit Report
## Prompt Qualification Readiness & Sealed Holdout Protocol Freeze

**Status: QUALIFICATION_PROTOCOL_READY_WITH_LIMITATIONS**  
**Execution Mode: STRICT OFFLINE QUALIFICATION PREPARATION (0 Network Calls)**  
**Target Next Phase: RCA-2A.14 (PROPOSED_NOT_AUTHORIZED)**

---

### Executive Summary

Phase **RCA-2A.13** has successfully transformed the exploratory paired findings of RCA-2A.12 into a formal, auditable Prompt Qualification protocol. In strict adherence to authorization constraints, **zero real LLM/network calls** were executed, and **zero production code mutations** were made. 

1. **RCA-2A.12 Empirical Result Reconstruction:**  
   Independently reconstructed from raw seat execution claims across all 16 seats and 8 pairs:
   - **Canonical Integration Validity:** Control 4/8 (50.0%) vs Treatment 7/8 (87.5%) -> **+37.5 percentage points** (Treatment Win 4, Control Win 1, Both Valid 3). Exact two-sided McNemar $p = 0.375$.
   - **Semantic Adequacy:** Control 3/8 (37.5%) vs Treatment 5/8 (62.5%) -> **+25.0 percentage points** (Treatment Win 4, Control Win 2, Both Adequate 1, Both Inadequate 1). Exact two-sided McNemar $p = 0.6875$.
   - **Sample Size Limitation:** The observed +37.5pp and +25.0pp deltas reflect strong exploratory directional signals, but lack statistical power at $N=8$ pairs to reject the null hypothesis at $\alpha=0.05$. They do **not** constitute production qualification pass.

2. **Semantic & Information Value Deep-Dive:**
   - **F1 (`t2-no-evidence`):** Treatment won 2/2 by keeping questions open and recording explicit limitations (`INFORMATION_NEUTRAL`), avoiding false closures without falsely claiming new evidence.
   - **F2 (`t2-temporal-trap`):** Treatment won 1/2 and tied 1/2 by distinguishing sequence from causation (`VALID_LIMITATION_CLARIFICATION`).
   - **F3 (`t2-identity-trap`):** Contract validity was 4/4, but Control won Pair A semantically while both arms failed Pair B. Treatment committed `UNSUPPORTED_FACT_PROMOTION` (cross-system identity merges across SSH and audit logs without proof). This proves that Vocabulary Guidance V1 does not solve entity disambiguation.
   - **F4 (`t2-report-citation`):** Split 1–1 due to stochastic LLM boundary adherence. Report admission, analyst acceptance, and report publication were strictly unexercised (`NOT_EXERCISED`).

3. **Qualification Candidate Frozen:**
   - `candidate_id`: `supervisor-v2-vocabulary-guidance-v1`
   - `guidance_sha256`: `e00c1549284cd4c5b98a24e0a7c064377a4aabcaaa74d9d344412c6247af5f29` (verified verbatim).
   - Candidate status: `QUALIFICATION_PENDING`.
   - Explicit policy decision: **Guidance V1 is frozen without ad-hoc edits for F3/F4 development cases** to prevent prompt overfitting.

4. **Holdout Contamination Assessment:**
   - Existing fixtures F1–F4 have undergone 4 iterative exploratory audits and are classified as `EXPOSED_FOR_DEVELOPMENT`.
   - **Clean qualification holdouts in repository: 0.**
   - True qualification requires a newly authored, sealed holdout battery with novel scenarios, unobserved entities, and independent custody.

5. **Independent Qualification Battery Design (Q1–Q6):**
   - Designed 6 capability families: Q1 Evidence Absence, Q2 Temporal Reasoning, Q3 Entity Identity, Q4 Evidence Citation, Q5 Negative Grounding, Q6 Investigation State.
   - Formalized case contracts with three-valued truth manifests (`CONFIRMED`, `UNSUPPORTED`, `INDETERMINATE`).
   - Sizing: Compact battery (24 seats) and Full battery (48 seats).

6. **Pre-Registered Acceptance Criteria (`PROPOSED_NOT_AUTHORIZED`):**
   - **Tier A (Hard Gates):** 0 tolerance for fabricated evidence, grounding bypass, unauthorized canonical mutations, unsupported fact acceptance, or unauthorized question closures.
   - **Tier B (Quality Gates):** Canonical validity $\ge 80\%$, Semantic adequacy $\ge 60\%$, Unsupported FACT rate $= 0\%$, Identity overreach $\le 10\%$, Causal overreach $\le 10\%$, Citation validity $100\%$.
   - **Tier C (Operational Gates):** Provider reliability $\ge 95\%$, Model identity match $100\%$, Retry rate $\le 5\%$, Token overhead $\le 400$ tokens.

7. **Adjudication & Statistical Plan:**
   - Arm-blind review protocol stripping candidate names, arm labels, and outcomes.
   - McNemar exact tests, Newcombe-Wilson score intervals, Bonferroni-Holm multiplicity adjustments, and power analysis.

8. **Deterministic Offline Simulation & Regression:**
   - Implemented 22 deterministic offline simulation tests (Q01–Q22) in `test_rca2a13_qualification_readiness.py`: **22/22 PASSED (100%)**.
   - Focused regression: **90/90 PASSED (100%)**.
   - Benchmark regression: **408/408 PASSED (100%)**.
   - Investigation safety regression: **1067 PASSED (1 skipped, 0 failed)**.
   - Real provider requests: **0**.

---

### Component Accounting: Added / Modified / Reused

| Component | Status | Location / Details |
|---|---|---|
| `test_rca2a13_qualification_readiness.py` | **ADDED** | 22 deterministic simulation tests (Q01–Q22) validating qualification readiness. |
| 13 Versioned Audit Reports (JSON) | **ADDED** | `benchmarks/audits/rca2a13-prompt-qualification-readiness/` |
| `rca2a13-audit-report.md` | **ADDED** | In-tree formal audit report. |
| `rca2a13_audit_report.md` | **ADDED** | User-facing brain artifact. |
| `SupervisorIntegrationDecisionV2` | **REUSED (UNCHANGED)** | Output schema hash `a214ec4f5e81fcbb` untouched. |
| `GUIDANCE_TEXT` / `guidance_sha256()` | **REUSED (UNCHANGED)** | Guidance V1 hash `e00c1549...` confirmed identical. |
| Production Supervisor Prompt | **REUSED (UNCHANGED)** | Production instructions untouched. |
| `STOP_POLICY_CONTRACT_V2` | **REUSED (UNCHANGED)** | Reused StopPolicyV2 decoupled containment logic. |
| Semantic Oracle L1–L5 | **REUSED (UNCHANGED)** | Tiered oracle reused for arm-blind evaluation. |
| `cross_case_runner.py` | **REUSED (UNCHANGED)** | Runner scheduling, claims, and telemetry reused. |
| Production Resolver, Policy, Gates | **REUSED (UNCHANGED)** | Zero production code touched. |

---

### Detailed Reconciliation of RCA-2A.12 Results

#### Canonical Integration Comparison
| Scenario | Pair | Control Seat (Valid) | Treatment Seat (Valid) | Canonical Outcome |
|---|---|---|---|---|
| `t2-no-evidence` | A | Seat 01 (`False`) | Seat 02 (`True`) | `TREATMENT_WIN` |
| `t2-no-evidence` | B | Seat 10 (`False`) | Seat 09 (`True`) | `TREATMENT_WIN` |
| `t2-temporal-trap` | A | Seat 03 (`False`) | Seat 04 (`True`) | `TREATMENT_WIN` |
| `t2-temporal-trap` | B | Seat 12 (`True`) | Seat 11 (`True`) | `BOTH_VALID` |
| `t2-identity-trap` | A | Seat 05 (`True`) | Seat 06 (`True`) | `BOTH_VALID` |
| `t2-identity-trap` | B | Seat 14 (`True`) | Seat 13 (`True`) | `BOTH_VALID` |
| `t2-report-citation` | A | Seat 07 (`False`) | Seat 08 (`True`) | `TREATMENT_WIN` |
| `t2-report-citation` | B | Seat 16 (`True`) | Seat 15 (`False`) | `CONTROL_WIN` |

- **Control Valid:** 4 / 8 (50.0%)
- **Treatment Valid:** 7 / 8 (87.5%)
- **Absolute Advantage:** +37.5 percentage points
- **Pairwise Breakdown:** Treatment Win 4, Control Win 1, Both Valid 3, Both Invalid 0.
- **Exact McNemar p-value:** $p = 0.375$ (Discordant pairs: 4 vs 1).

#### Semantic Adequacy Comparison
| Scenario | Pair | Control Seat (Adequacy) | Treatment Seat (Adequacy) | Semantic Outcome |
|---|---|---|---|---|
| `t2-no-evidence` | A | Seat 01 (`INADEQUATE`) | Seat 02 (`ADEQUATE`) | `TREATMENT_SEMANTIC_WIN` |
| `t2-no-evidence` | B | Seat 10 (`INADEQUATE`) | Seat 09 (`ADEQUATE`) | `TREATMENT_SEMANTIC_WIN` |
| `t2-temporal-trap` | A | Seat 03 (`INADEQUATE`) | Seat 04 (`ADEQUATE`) | `TREATMENT_SEMANTIC_WIN` |
| `t2-temporal-trap` | B | Seat 12 (`ADEQUATE`) | Seat 11 (`ADEQUATE`) | `BOTH_SEMANTICALLY_ADEQUATE` |
| `t2-identity-trap` | A | Seat 05 (`ADEQUATE`) | Seat 06 (`INADEQUATE`) | `CONTROL_SEMANTIC_WIN` |
| `t2-identity-trap` | B | Seat 14 (`INADEQUATE`) | Seat 13 (`INADEQUATE`) | `BOTH_SEMANTICALLY_INADEQUATE` |
| `t2-report-citation` | A | Seat 07 (`INADEQUATE`) | Seat 08 (`ADEQUATE`) | `TREATMENT_SEMANTIC_WIN` |
| `t2-report-citation` | B | Seat 16 (`ADEQUATE`) | Seat 15 (`INADEQUATE`) | `CONTROL_SEMANTIC_WIN` |

- **Control Adequate:** 3 / 8 (37.5%)
- **Treatment Adequate:** 5 / 8 (62.5%)
- **Absolute Advantage:** +25.0 percentage points
- **Pairwise Breakdown:** Treatment Win 4, Control Win 2, Both Adequate 1, Both Inadequate 1.
- **Exact McNemar p-value:** $p = 0.6875$ (Discordant pairs: 4 vs 2).

---

### Answers to All 20 Exit Gate Questions

1. **RCA-2A.12 的八对结果能否从原始记录独立重建？**  
   **能。** 从 16 个 Seat 的原始记录和 Durable Claims 独立计算，Canonical Valid 为 Control 4/8 (50.0%) vs Treatment 7/8 (87.5%)，Semantic Adequate 为 Control 3/8 (37.5%) vs Treatment 5/8 (62.5%)，完全精确吻合。

2. **+37.5pp 和 +25pp 的统计解释是否准确？**  
   **准确。** 它们是 8 对样本下的观察值，具有明显的探索性方向信号，但因样本量受限（N=8），精确 McNemar 检验 p 值为 0.375 和 0.6875，不具备在 $\alpha=0.05$ 下拒绝原假设的统计功效。不能解释为统计确证的通用改善，也不能替代正式 Qualification。

3. **F1 的无证据处理收益是否成立？**  
   **成立。** Treatment 2/2 获胜。Guidance 彻底消除了无证据支持时强行 Answered 的错误闭环（`FALSE_QUESTION_CLOSURE`），合法保留了 Question 的 Open 状态，记录了明确局限。该收益被合理记为 `INFORMATION_NEUTRAL`，未误算为发现新事实。

4. **F2 的认识论澄清是否与新事实发现区分？**  
   **严格区分。** Treatment 正确区分了时间先后、相关性与因果推论，将推论隔离在 HYPOTHESIS 中，未将其提升为未经验证的 FACT。该认识论澄清记为 `VALID_LIMITATION_CLARIFICATION`，与物理证据发现清晰解耦。

5. **F3 的 Treatment Identity Overreach 是否需要专项风险门？**  
   **必须设置专项风险门。** F3 中 Treatment 在两对中均触发了 `UNSUPPORTED_FACT_PROMOTION`（因相同 IP 或用户名而断言跨系统同一攻击主体）。Guidance V1 缺乏跨系统身份消歧指导，总体胜率掩盖了身份过度断言的严重风险，必须在 Tier B Quality Gates 中独立考核 `identity_overreach_rate \le 10%`。

6. **F4 是否存在局部 Prompt Regression？**  
   **不存在系统性 Regression，但存在随机边界波动。** Pair A Treatment 获胜，Pair B Control 获胜，1-1 平手。所有 Citation Handle 均合法接地，且下游 Report Admission/Publication 均被严格隔离（`NOT_EXERCISED`）。平手反映了模型在边界条件下的固有随机性。

7. **是否有足够证据修改生产 Prompt？**  
   **绝对不足。** 现有数据仅为 8 对探索性样本，缺乏统计功效；F1–F4 案例均已在开发中暴露；F3 存在明确的身份过度断言风险。修改生产 Prompt 将带来未经资格认定的回归风险。

8. **RCA-2A.12 的哪些 Fixture 已经受到实验开发污染？**  
   **全部 4 个 Fixture (F1–F4) 均已受污染。** 它们均被多次执行、人工审查，并参与了 Prompt 与 Oracle 的开发调试，分类为 `EXPOSED_FOR_DEVELOPMENT`，不能再充当盲测 Holdout。

9. **当前仓库是否存在真正独立的 Qualification Holdout？**  
   **不存在。** 仓库中现有且仅有 F1–F4 四组测试用例，Clean Candidate 数量为 0。

10. **如果没有，如何构建和保管？**  
    应遵循“出题者与解题者分离”（Fixture Author $\ne$ Prompt Developer）原则，由独立人员编写全新的 Q1–Q6 案例（不同实体、不同日志、不同时间戳），并将 Ground Truth Manifest 实行加密/哈希封存，模型执行前仅见初始输入。

11. **Qualification 应覆盖哪些新增取证风险？**  
    覆盖 6 大核心维度：Q1 无证据处理、Q2 时序与因果混淆、Q3 跨系统身份归因（Same IP/User $\ne$ Same Actor）、Q4 证据引用与阶段边界、Q5 植入伪造与跨任务数据防御、Q6 调查状态（Question/Coverage/Finalization）治理。

12. **统计设计需要多少样本与请求预算？**  
    在 $\alpha=0.05$、$1-\beta=0.80$ 下检测 +30pp 效应，需至少 36–48 对配对样本（72–96 席位）。紧凑版至少需 12 对（24 席位）。若使用 48 席位，逻辑请求预算为 48，预计输入 Token 约 18 万，输出约 2.4 万。

13. **Semantic Oracle 与人工裁决如何分工？**  
    L1–L3 完全由确定性代码自动化校验；L4–L5 由 Arm-blind Semantic Oracle 初筛；对存在分歧或高危场景（如身份归因、因果充分性），由人工评审在去标签（脱敏 Arm、Seat、Candidate）条件下进行双盲裁决。

14. **Qualification 的 Hard Gates 和 Quality Gates 是什么？**  
    - **Hard Gates (零容忍):** 伪造证据接受、跨任务泄漏、接地绕过、未授权修改规范库、未证实事实提升、未授权问题闭环、报告准入绕过、历史工件篡改。
    - **Quality Gates:** 规范集成率 $\ge 80\%$、语义充分率 $\ge 60\%$、未证实事实率 $= 0\%$、身份过度断言率 $\le 10\%$、因果过度断言率 $\le 10\%$、引用有效率 $100\%$、配对改善显著性或正向优势。

15. **如何防止因 F3/F4 已知结果而过拟合？**  
    严格冻结 Guidance V1 哈希，禁止针对已公开的 F3/F4 样例修改 Prompt；强制 Qualification 必须使用全新的独立 Holdout 集。

16. **是否需要新版本 Vocabulary Guidance？**  
    **当前阶段不需要。** 当前必须保持 Candidate V1 冻结并完成其基准测试。若后续针对身份断言开发专用指导，必须版本化为 Candidate V2，并在独立开发集上训练，重新冻结哈希。

17. **是否需要 RCA-2B？**  
    **不需要。** 当前处于 RCA-2A（单 Agent 调查员架构安全与资格认定）阶段，多 Agent 或 RCA-2B 均未授权。

18. **是否需要任何生产代码修改？**  
    **不需要。** 本阶段所有工作均在 Benchmark 和 Audit 目录下进行，生产 Prompt、Schema、Policy、Resolver 保持 100% 原始不变。

19. **Qualification Harness 是否可重复、可审计？**  
    **是。** 经 Q01–Q22 共 22 项离线模拟测试全面验证，Harness 具备幂等性 Claim、崩溃恢复、确定性 Oracle、严格预算控制及网络隔离能力。

20. **是否已经具备独立授权下一阶段的条件？**  
    **具备进入 RCA-2A.14 准备的条件，但正式执行需待独立 Holdout 数据封存完毕。** 当前状态为 `QUALIFICATION_PROTOCOL_READY_WITH_LIMITATIONS`。

---

### Final Architectural Disposition

```text
RCA-2A.11:   EXPERIMENT_HALTED (FROZEN)
RCA-2A.11a:  AUDIT_COMPLETED (FROZEN)
RCA-2A.11b:  BENCHMARK_HARDENED (FROZEN)
RCA-2A.12:   CROSS_CASE_COMPARISON_COMPLETED (FROZEN)
RCA-2A.13:   QUALIFICATION_PROTOCOL_READY_WITH_LIMITATIONS
RCA-2A.14:   PROPOSED_NOT_AUTHORIZED

Production Prompt: UNCHANGED
Production Schema: UNCHANGED
Gen-5:             NOT_CREATED
RCA-2B:            NOT_AUTHORIZED
```

**MANDATORY HARD STOP ENFORCED.**
