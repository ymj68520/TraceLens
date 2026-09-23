# Agent v0 — Phase 5B: CorrelationAgent / Semantic Verification / AssertionPolicy / Review-Pending Closure

## 0. Baseline / branch / commits

```text
baseline: 7c6bebf1  (P5A frozen HEAD)
branch:   mvp/agent-v0-phase5-correlation-grounding-verification  (same branch)
schema:   investigation.db v13 -> v14 (additive)
```

| Commit | Content |
| --- | --- |
| `3e47b83e` | P5B-1 schema v14 + semantic verification contracts + multi-mode verifier |
| `b894576b` | P5B-2 bounded CorrelationAgent + proposal→claim seam |
| `e3724f57` | P5B-3 deterministic AssertionPolicy + starter registry + ClaimDisposition |
| `b72de4d2` | P5B-4 review-pending Findings + Analyst Review handoff + AddFindingReference |
| (P5B-5) | question_closure + finalization_review + E2E pipeline + docs + freeze gate |

## 1. Repository findings

1. 无现成 canonical semantic store（P5A 只有 proposals）→ v14 新建。
2. SecondaryAnalysis/Claim 表职责不同（文件分析链），按 §38 不伪装复用——Finding
   走独立表 + 独立 human-only review service，不建第二 accepted/rejected 权威
   （每个对象类型恰一个权威 service）。
3. accepted/rejected 现有权威：`investigation_persistence.py` 的
   `accept_analysis/reject_analysis/review_event_claim/accept|reject_event_version`。
4. review_pending 语义已存在于 analyses/versions/claims；Finding 采用同一词汇。
5. **FinalizationGate 读 `state.pending_verifications`**（P2 留好的占位，注释即
   "P5 provides the real SemanticVerifier"）：required 且
   pending/failed/unavailable → MANDATORY_VERIFICATION_BLOCKING。P5B 不改 Gate。
6. P4B IntegrationContext 经 `pending_proposal_refs` 引用 proposal（P5A 已加
   resolver seam）；P5B 同型开放 AddFindingReference。
7. P5A support bundle reader：`list_support_bundles` + bundle row digest。
8. review history 原语：现有 review 均为 exact task-bound；Finding 复刻该模式
   （append-only `investigation_finding_reviews` + 状态机守卫触发器）。
9. v13 trajectory 枚举 34 值；v14 +5（P5B 审计事件）。
10. v13 无法表达 verifier/disposition/finding → **v14**。

## 2. SemanticVerifierAgent（一个 Agent、四个 mode，§4）

`agent_verification.py`。`read + reason + structured output`；Tools = none（§6，
bundle 即冻结输入）；无 profile/skill 套壳（§47）。四个 mode：

| mode | 冻结输入 | 输出 |
| --- | --- | --- |
| claim_sufficiency | `SemanticVerificationContextV1`（§7） | `SemanticVerificationResultV1` |
| correlation_sufficiency | 同上（correlation 派生 claim） | 同上 |
| question_closure | `QuestionClosureContextV1` | `QuestionClosureReviewV1`（仅建议） |
| finalization_review | `FinalSemanticReviewContextV1`（§50 digest-only） | `FinalSemanticReviewOutputV1`（pass/issues_found） |

- 权限（§5）：不写 Working State、不 accept/reject、不改 Evidence/Graph、不发
  Report、不创建 Analyst Review——§60 测试证明无 agent 组件 import review 权威。
- 状态词汇精确五值（§8）；无任何数值置信度（模型字段结构性不存在，§63）。
- §11 八项 QC 检查逐字进入 instructions。
- **raw-first 验证**：模型输出先对 frozen context 做确定性验证（§17 十四项），
  伪造 identity/proposal/bundle 或引用 bundle 外 Evidence ref（§10）→
  `output_invalid` 失败审计；合规后才绑定 runtime 事实（模型不可控）。
- Provider 失败（§19/§48）：P4A `map_provider_exception` 归一到 §19 词汇，
  写 `agent_semantic_verification_failures` 审计行——"没有 row ≠ 没问题"，
  runtime failure 永不伪装成 indeterminate。

## 3. CorrelationAgent（§20-§25）

`agent_correlation_agent.py`。仅当 relation question 存在且确定性引擎已产出
bounded candidates 时运行（§20）；输入 `CorrelationContextPackV1` 只有候选、
occurrence digests 与 allowlist（§21，无全案 KG/Evidence 面）。输出
`CorrelationProposalV1` 恒为 proposal（§22）。因果硬边界（§23）：
temporal_overlap 恒 HYPOTHESIS + not_assessed；causal_hypothesis 必须
HYPOTHESIS 类；`causal_confirmed` 在输出词汇中不可构造。§24 seam
`proposal_to_claim`：进 claim 管线仍过 grounding→bundle→verifier→policy 全链；
高风险 correlation 走 `correlation_sufficiency` mode（§25），不能自评。

## 4. AssertionPolicy（starter registry，§26-§33）

`agent_assertion_policy.py`。确定性两阶段（§55）：`classify → preflight →
（需要则跑 verifier）→ finalize → ClaimDispositionV1`。

- starter registry（`assertion-policy:v1`，**明确非永久 taxonomy**，P8 校准）：
  低风险 artifact 语句 deterministic_only（未验证封顶 INFERENCE）；
  on-demand 类型缺验证时安全封顶；§29 十类高风险 semantic_required +
  HYPOTHESIS 未验证封顶；UNKNOWN → 保守默认（§28/§57）。
- §33 禁自动升强：proposal 自身类是 ceiling 的一部分——sufficient 最多保留
  requested 类，HYPOTHESIS 永不升 FACT。
- §48：provider 失败时 semantic_required → `blocked_verification_required`
  （永不降验证标准保强 finding）；on-demand → 安全降级。
- §31 词汇无 accepted/rejected；disposition 绑定 proposal/grounding/verification/
  policy registry 四重 hash，immutable、content-addressed、INSERT-only。

## 5. Canonical Finding + review_pending ceiling（§34-§42）

- `investigation_findings`：唯一状态机表（review_pending → accepted/rejected；
  identity 触发器锁死内容行；review 必须带 reviewed_at/reviewer/review_id；
  terminal 无出边）。finding_id 确定性绑定 investigation/proposal/disposition/
  effective class → crash+retry 不重复（§35）。
- `FindingReviewService`：唯一 accepted/rejected 写者，human-only（显式
  reviewer 必填 + §60 import 扫描）；review history append-only。
- rejected Finding 不删除（§42）——行保留、退出可引用集。
- Agent 管线自动天花板 = review_pending（§37）；Finding 持久化零 revision
  消耗（§45），Working State 唯一经 Supervisor Integration →
  AddFindingReference → StateTransitionPolicy 改变（§78）。
- **AddFindingReference 开放**（§40）：typed union + allowed set +
  `INTEGRATION_FINDING_REF_UNRESOLVED` seam——只解析 same-task 持久化且
  review_pending/accepted 的 Finding；AddEntityReference/ModifyScope 仍拒绝
  （无 canonical entity store，P6 边界）。

## 6. Atomicity（§43/§44/§74）

- `record_semantic_verification`：verification 行 + trajectory 单事务；非法
  输出不写 valid 行，只写 failure 审计。
- `commit_claim_disposition`：单事务内重校验 proposal hash / grounding 存在 /
  verification id → INSERT disposition →（可 canonicalize 时）INSERT
  review_pending Finding → trajectory；任一失败整体回滚——Finding 无
  disposition（或反之）结构上不可能。

## 7. Orchestrator seam（§77/§78）

无自动接线：`process_claim_verification(...)`（agent_verification.py）是显式
入口——policy preflight 决定是否跑 verifier（§54），Supervisor/调用方请求、
Orchestrator 准入、Verifier 执行、Integration 消费。静态测试钉死
orchestrator/ServiceManager 不 import 任何 P5B 模块；FinalizationGate 不变，
verifier pass 永不绕过 hard blocker（§68）。

## 8. Schema v14

五张新表：`agent_semantic_verifications`、`agent_semantic_verification_failures`
（INSERT-only）、`agent_claim_dispositions`（INSERT-only）、
`investigation_findings`（状态机 + 3 守卫触发器）、
`investigation_finding_reviews`（append-only）。trajectory 枚举 +5：
correlation_semantic_verified / claim_semantic_verified /
claim_disposition_recorded / finding_review_pending_created /
final_semantic_review_recorded（载荷仅 ids/hashes/status/counts）。
v13→v14 additive，P1–P5A 行原样保留；future v15 fail closed。

## 9. Tests

新增 55 个（全套件 778 → 833 passed + 1 opt-in skip）：

```text
test_agent_schema_v14_migration.py          4  fresh/v13→v14 保全/状态机守卫/future v15
test_agent_semantic_verification.py        14  §17 验证器矩阵/§63/§10 allowlist/持久化/失败审计
test_agent_correlation_agent.py             8  §62 全矩阵（因果边界/allowlist/proposal）
test_agent_assertion_policy.py             15  §64 全矩阵（保守默认/不升强/§48/确定性）
test_agent_findings.py                     11  §65/§66/§67/§60/§74
test_agent_semantic_pipeline_e2e.py         7  §70/§71/§72/§68/§69
```

## 10. Known limitations

- verifier 的 question_closure/finalization_review 输出目前不持久化专用表
  （v14 表面向 claim verification）；final review 结果经 trajectory
  `final_semantic_review_recorded` 事件 + 调用方留档，专用落表待 P6 前需要时加。
- starter registry 的 ceiling 表是保守起步值；`partially_sufficient` 一律落
  HYPOTHESIS（不保留 INFERENCE 中间档）。
- CorrelationAgent 的生产 provider 路径复用 TestModel 兼容入口，真实云跑批
  校准（阈值/温度/prompt 打磨）留给 P8。
- `_apply_verification` 的 sufficient + 超 ceiling 降级（FACT→INFERENCE）记
  ELIGIBLE（按 capped class 入 review_pending），决策词表无中间降级名。

## 11. P6 deferred scope

GraphCandidate / GraphAdmissionPolicy / Frozen ForensicGraphEpisode /
materialization manifest / Graphiti-Neo4j materialization / logical
invalidation / investigation retrieval mode / report retrieval filtering。
P5B 中即使 canonical 的 Entity/Correlation/Finding 也不自动写 Graph；保持
SQLite canonical provenance > Graphiti derived index。
