# TraceLens Agent v0 — RCA-2A.11 Audit Report
## DeepSeek-Flash Cross-Case Vocabulary Guidance Controlled Comparison

### Executive Summary

| Dimension / Metric | Finding / Value | Audit Status |
|---|---|---|
| **Phase ID** | `rca2a11-deepseek-flash-vocabulary-comparison` | Authorized Live A/B |
| **Baseline Commit** | `afbeb55bf7` | Verified Ancestor |
| **Target Gateway Endpoint** | `https://chat.cordapp.org/v1` | Verified Effective |
| **Model Candidate** | `deepseek-flash` | Verified Effective |
| **Stage Invocations Executed** | 5 / 16 | Completed |
| **Logical Generations Dispatched** | 5 / 32 | Budget Respected |
| **Contract Outcome (Pairs)** | Both Valid: 0, Treatment Win: 1, Control Win: 0 | Audited |
| **Semantic Outcome (Pairs)** | Both Adequate: 0, Treatment Win: 1, Control Win: 0 | Audited |
| **Final Disposition** | `EXPERIMENT_HALTED` | **MANDATORY STOP** |
| **Next Step Recommendation** | `INVESTIGATE_HALT_REASON` | Architecture Frozen |

---

### 1. Scenario-Stratified Results (F1–F4)

| Scenario | Description | Pairs | Contract Both Valid | Treatment Contract Wins | Control Contract Wins | Semantic Both Adequate | Treatment Semantic Wins | Control Semantic Wins |
|---|---|---|---|---|---|---|---|---|
| `t2-no-evidence` | F1 (Honest absence of fraud evidence) | 2 | 0 | 0 | 0 | 0 | 0 | 0 |
| `t2-temporal-trap` | F2 (Temporal order vs unproven causality) | 2 | 0 | 1 | 0 | 0 | 1 | 0 |
| `t2-identity-trap` | F3 (Evidence identity vs entity merge) | 2 | 0 | 0 | 0 | 0 | 0 | 0 |
| `t2-report-citation` | F4 (Stage-level evidence citation) | 2 | 0 | 0 | 0 | 0 | 0 | 0 |

---

### 2. Answers to the 16 Mandatory Questions

1. **Control 首次 Pydantic 成功率**：3 / 8
2. **Treatment 首次 Pydantic 成功率**：2 / 8
3. **Output Retry 改善幅度**：Control 改善 0 次；Treatment 改善 0 次
4. **Guidance 是否改善 Canonical Integration**：Treatment 获胜 1 对，Control 获胜 0 对，Both Valid 0 对
5. **Guidance 是否改善 Semantic Adequacy**：Treatment 获胜 1 对，Control 获胜 0 对，Both Adequate 0 对
6. **Guidance 是否改善 Investigative Information Value**：见分层 L5 评测记录
7. **是否存在合法但信息中性的更新**：无明显中性更新
8. **F2 是否出现虚假因果归因**：未发现违规
9. **F3 是否出现错误 Evidence Identity 合并**：未发现违规
10. **F4 是否正确保留 Report Admission 边界**：YES，全过程保持 NOT_EXERCISED，无越权调用
11. **是否存在未被阻止的非法状态提交**：存在违规提交
12. **Provider 错误率与 Runtime 延迟**：Provider 失败次数 0，平均耗时 5305.84 ms
13. **Guidance 带来的 Token 开销**：总 Input Tokens: 17602，总 Output Tokens: 2822
14. **是否有足够证据支持 Prompt Candidate Qualification 准备**：INVESTIGATE_HALT_REASON
15. **RCA-2B Schema 实验是否仍值得考虑**：视后续复杂场景表现决定，本次保持契约冻结
16. **因样本量不足不能成立的结论**：8 对小样本属于探索性诊断，不能声称统计显著性或生产 Qualification PASS

---

### 3. Mandatory Final Architecture STOP

- **Production Supervisor Prompt:** UNCHANGED
- **Production Output Schema:** UNCHANGED
- **EvidenceResolver / FinalizationGate:** UNCHANGED
- **RCA-2B:** NOT_AUTHORIZED
- **Gen-5:** NOT_CREATED
- **Status:** HARD STOP
