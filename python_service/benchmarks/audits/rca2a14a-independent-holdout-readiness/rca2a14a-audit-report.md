# TraceLens Agent v0 — RCA-2A.14a Audit Report
## Independent Holdout Construction, Custody & Qualification Gate Closure

**Status: PROTOCOL_READY_CUSTODY_BLOCKED**  
**Execution Mode: STRICT OFFLINE PREPARATION (0 Real Provider Requests)**  
**Target Next Phase: RCA-2A.14 (NOT_AUTHORIZED)**  
**Parent Baseline Commit (RCA-2A.13):** `82227677a4ce4f68bde393c3e22c677bb411fb66`

---

### Executive Summary

Phase **RCA-2A.14a** audited the qualification preparation state, resolved core semantic and statistical discrepancies in the qualification protocol, established independent custody data structures and anti-leakage safeguards, and conducted exhaustive offline deterministic regression.

1. **Risk Taxonomy & Metric Contract Closure:**  
   Resolved the semantic conflation between model natural language output and state mutation:
   - Differentiated `MODEL_TEXT_OVERASSERTION` (semantic quality flaw) from `UNSUPPORTED_FACT_PROMOTION_COMMITTED` (security boundary breach). An overasserted natural language string inside a hypothesis action does not constitute an illegal canonical commit when blocked by policy or contained in scratch.
   - Closed formal metric definitions for `unsupported_fact_assertion_rate`, `unauthorized_fact_commit_count`, `identity_overreach_rate`, `causal_overreach_rate`, `citation_invalidity_rate`, and `question_closure_error_rate`, specifying exact numerators, denominators, observation units, and exclusion rules.
   - Disentangled **Tier A Hard Gates** (zero tolerance for illegal state promotion) from **Tier B Quality Gates** (evaluating model semantic adequacy regardless of server-side containment).

2. **Holdout Custody & Independence Ruling:**  
   - Established a 5-role custody matrix: Prompt Candidate Owner, Holdout Fixture Author, Holdout Custodian, Qualification Executor, and Independent Semantic Adjudicator.
   - **P0 Hard Rule Enforcement:** Because the current execution environment operates as a single coding agent session with repository-wide read access, the agent **cannot and does not** claim that authentic independent holdout custody has been achieved.
   - Final custody status is honestly declared as **`PROTOCOL_READY_CUSTODY_BLOCKED`**. Formal sealed holdout case count is set to **`0`** (`PENDING_INDEPENDENT_CUSTODIAN`).

3. **Battery Design & Sealing Protocol:**  
   - Formalized case contracts across 6 capability families (Q1 Evidence Absence, Q2 Temporal Reasoning, Q3 Cross-System Entity Identity, Q4 Evidence Citation, Q5 Negative Grounding, Q6 Investigation State).
   - Designed cryptographic commitment protocols ($\text{SHA256}(\text{Case} \parallel \text{Nonce})$) separating content integrity from confidentiality.
   - Current sealing status is declared as **`HOLDOUT_NOT_SEALED`**.

4. **Statistical Power & Battery Size Reconciliation:**  
   - **Corrected Sample Size Discrepancy:** Clarified that a 48-seat paired A/B battery yields exactly **24 pairs**, which achieves only $\approx 62\%$ power at $\alpha=0.05$ for detecting a +30pp advantage (underpowered for confirmatory qualification).
   - Derived exact sample size requirements for 80% power: **38 pairs (76 seats)** for a +30pp effect; **52 pairs (104 seats)** for a +25pp effect.
   - Established three pre-registered battery tiers: Compact Screening (12 pairs / 24 seats), Extended Screening (24 pairs / 48 seats), and Confirmatory Qualification (40 pairs / 80 seats). Rule: Underpowered screening runs yielding $p \ge 0.05$ with positive effect must be declared `QUALIFICATION_INCONCLUSIVE`, not `PASS`.

5. **Acceptance Profile Closure (`PROPOSED_NOT_AUTHORIZED`):**  
   - Disentangled **Absolute Quality Gates** (meeting baseline validity thresholds) from **Relative Improvement Gates** (demonstrating paired statistical advantage over Control).
   - Pre-registered 5 allowed final qualification verdicts: `QUALIFICATION_PASS`, `SCOPED_QUALIFICATION`, `QUALIFICATION_FAIL`, `QUALIFICATION_INCONCLUSIVE`, `QUALIFICATION_INVALID`.

6. **Offline Deterministic Verification & Regression:**  
   - Implemented 28 deterministic offline simulation tests (T01–T28) in `test_rca2a14a_holdout_readiness.py`: **28/28 PASSED (100%)** in 3.22s.
   - Focused regression: **118/118 PASSED (100%)** in 40.72s.
   - Benchmark regression: **436/436 PASSED (100%)** in 228.62s.
   - Investigation safety regression: **1067 PASSED (1 skipped, 0 failed)** in 67.86s.
   - Real provider requests: **0** (strictly offline).

---

### Component Accounting: Added / Modified / Reused

| Component | Status | Location / Details |
|---|---|---|
| `test_rca2a14a_holdout_readiness.py` | **ADDED** | 28 deterministic simulation tests (T01–T28) validating holdout readiness and fail-closed paths. |
| 12 Versioned Audit Reports (JSON) | **ADDED** | `benchmarks/audits/rca2a14a-independent-holdout-readiness/` |
| `rca2a14a-audit-report.md` | **ADDED** | In-tree formal audit report. |
| `rca2a14a_audit_report.md` | **ADDED** | User-facing brain artifact. |
| `SupervisorIntegrationDecisionV2` | **REUSED (UNCHANGED)** | Output schema hash `a214ec4f5e81fcbb` untouched. |
| `GUIDANCE_TEXT` / `guidance_sha256()` | **REUSED (UNCHANGED)** | Guidance V1 hash `e00c1549...` confirmed identical. |
| Production Supervisor Prompt | **REUSED (UNCHANGED)** | Production instructions untouched. |
| `STOP_POLICY_CONTRACT_V2` | **REUSED (UNCHANGED)** | Reused StopPolicyV2 decoupled containment logic. |
| Semantic Oracle L1–L5 | **REUSED (UNCHANGED)** | Tiered oracle reused for arm-blind evaluation. |
| `cross_case_runner.py` | **REUSED (UNCHANGED)** | Runner scheduling, claims, and telemetry reused. |
| Production Resolver, Policy, Gates | **REUSED (UNCHANGED)** | Zero production code touched. |

---

### Actual Holdout Case & Custody Accounting

```text
Actual Holdout Case Count:     0 (SPECIFICATION_FROZEN_CASES_PENDING)
Actual Custody Status:         PROTOCOL_READY_CUSTODY_BLOCKED
Actual Truth Sealing Status:   HOLDOUT_NOT_SEALED
Production Prompt Status:      UNCHANGED (supervisor-v2)
Production Schema Status:      UNCHANGED (SupervisorIntegrationDecisionV2)
Gen-5 Status:                  NOT_CREATED
RCA-2B Status:                 NOT_AUTHORIZED
Next Phase (RCA-2A.14):        NOT_AUTHORIZED
```

---

### Answers to All 20 Exit Gate Questions

1. **RCA-2A.13 的历史成果是否完整保留？**  
   **完整保留。** RCA-2A.13 的全部 13 项 JSON 工件哈希均已通过 SHA-256 校验，祖先提交链完整，无任何工件漂移。

2. **Unsupported FACT 的模型语义与实际提交是否已经准确区分？**  
   **已严格区分。** 模型自然语言过度断言（`MODEL_TEXT_OVERASSERTION`）计入 L4 语义缺陷与质量门；未经授权的事实持久化（`UNSUPPORTED_FACT_PROMOTION_COMMITTED`）作为 L3 权限突破与零容忍硬门。

3. **Identity Overreach、Causal Overreach 的分母是否明确？**  
   **明确。** 分母严格限定为各自领域内的“可评价模型决策数”（例如 Identity Overreach 的分母为评估实体身份场景的决策总数，Causal Overreach 的分母为时序推理场景决策总数），排除了模式解析失败和网络不可观测异常。

4. **Qualification 的 Absolute Gate 与 Relative Improvement Gate 是否独立？**  
   **完全独立。** 绝对质量门考核候选模型自身是否达到基准可用性（如规范有效率 $\ge 80\%$）；相对改善门考核 Treatment 相比 Control 是否具有统计显著的配对优势（$p < 0.05$）。两者互不替代。

5. **是否存在真实独立的 Holdout Author/Custodian？**  
   **当前环境不存在。** 当前处于单一 Coding Agent 对话环境，客观上存在对代码和协议的全知访问。必须如实判定为 `PROTOCOL_READY_CUSTODY_BLOCKED`。

6. **Prompt Owner 能否读取隐藏测试或 Ground Truth？**  
   **在协议层面被严格禁止。** 协议规定 Prompt Owner 仅可访问公共能力契约，隐藏测试与 Truth Manifest 只能在模型响应冻结落盘后由独立 Custodian 向评审方披露。

7. **Q1–Q6 是否有真正新颖的案例？**  
   **规范中已定义全新情境。** 包括跨 NAT 共享 IP、无跨域信任的同名本地账户、通用工具文件名冲突、并发无因果时序重叠等全新调查结构，彻底脱离 F1–F4 的实体与拓扑。

8. **新案例是否具有真实可解析的 Synthetic Evidence？**  
   **具备。** 契约强制要求每个证据项绑定为合法的 `(task_id, evidence_key)`，禁止跨任务引用，且支持底层解析器正常提取。

9. **Holdout 是否完成可信封存？**  
   **尚未完成（`HOLDOUT_NOT_SEALED`）。** 封存协议与承诺算法已就绪，但真实封存依赖独立 Author 和 Custodian 交付数据包，当前记录案例数为 0。

10. **封存前是否发生候选开发侧暴露？**  
    **未发生泄漏。** 历史 F1–F4 已被正确归类为 `EXPOSED_FOR_DEVELOPMENT`，全新 Q1–Q6 案例尚未在开发侧输入，未产生新的数据污染。

11. **24/48-seat 与统计功效目标是否一致？**  
    **不一致，已完成修正。** 48-seat 配对实验仅有 24 对，统计功效仅为 $\approx 62\%$，不足以作为 80% 功效的确认性检验；已将其重分类为 Extended Screening，并将确认性门槛修正为 38–52 对。

12. **是否需要更大的确认性样本？**  
    **需要。** 正式 Confirmatory Qualification 必须达到至少 38–40 对（76–80 席位）才能以 80% 功效检测 +30pp 改善。

13. **Qualification 阈值是否具备可审计依据？**  
    **具备。** 各项阈值（如规范有效率 $\ge 80\%$、过度断言 $\le 10\%$、引用有效率 $100\%$）均基于 RCA-2A.11/12 实证数据与取证安全容忍度制定，并在契约中完成闭环。

14. **Arm-Blind Adjudication 是否可执行？**  
    **已就绪。** 盲测数据包脱敏规范已冻结，自动剥离候选身份、席位号、Arm 标签及模型标识。

15. **高风险语义裁决是否需要独立人工复核？**  
    **必须复核。** 针对身份跨系统合并、因果机制推断及未证实事实断言，在正式资格认证中强制要求独立人工双盲审查。

16. **Qualification Runner 是否复用现有系统？**  
    **完全复用。** 基于 RCA-2A.12 的成熟 Runner、StopPolicyV2、Durable Claim 和 SQLite 物理隔离机制，未构建第二套执行器。

17. **所有 Failure Path 是否 fail closed？**  
    **全部 Fail Closed。** 经 T01–T28 离线模拟测试，涵盖丢失 Custodian、未封存数据、工件哈希漂移、跨任务引用等 14 条失败分支，全部正确触发中止。

18. **是否完成全部必要回归？**  
    **全部完成。** 118 项聚焦测试（100% 通过）、436 项基准测试（100% 通过）、1067 项调查安全测试（100% 通过）。

19. **是否有生产代码修改？**  
    **零修改。** 生产 Prompt、Schema、Policy、Resolver 保持 100% 原始基线。

20. **是否真正具备正式 RCA-2A.14 执行条件？**  
    **不具备。** 协议和 Harness 已就绪，但受限于独立 Custodian 和新颖 Holdout 封存未到位（`PROTOCOL_READY_CUSTODY_BLOCKED`），禁止进入 RCA-2A.14。

---

### Final Architectural Disposition

```text
RCA-2A.11:   EXPERIMENT_HALTED (FROZEN)
RCA-2A.11a:  AUDIT_COMPLETED (FROZEN)
RCA-2A.11b:  BENCHMARK_HARDENED (FROZEN)
RCA-2A.12:   CROSS_CASE_COMPARISON_COMPLETED (FROZEN)
RCA-2A.13:   QUALIFICATION_PROTOCOL_READY_WITH_LIMITATIONS (FROZEN)
RCA-2A.14a:  PROTOCOL_READY_CUSTODY_BLOCKED
RCA-2A.14:   NOT_AUTHORIZED

Production Prompt: UNCHANGED
Production Schema: UNCHANGED
Gen-5:             NOT_CREATED
RCA-2B:            NOT_AUTHORIZED
```

**MANDATORY HARD STOP ENFORCED.**
