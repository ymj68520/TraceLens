# RCA2AContractFeasibilityReportV1

RCA-2A — Supervisor INTEGRATE Contract Feasibility Audit（离线）
分支 `mvp/agent-v0-runtime-v3-requalification` · 基线 `6f768b25` · 2026-10-13
授权范围：OFFLINE CONTRACT AUDIT ONLY。零真实模型调用；生产 schema/prompt/policy/validator 零修改；holdout 零接触。

```text
RCA-1:            CLOSED / TESTED
RCA-2A:           AUDITED
RCA-2B:           NOT AUTHORIZED
Historical Gen-4: CLOSED_REJECTED / UNCHANGED
AcceptanceProfileV2: UNCHANGED (c40f1adc… 复测吻合)
Model calls:      0
Gen-5:            NOT CREATED
```

**处置（§12）：`PROPOSAL_FEASIBLE_NOT_IMPLEMENTED`** —— 可行性已证（语义等价 + 复杂度差已量化），仅提交设计、离线测试与评估，不实施到生产 Agent。

## 1. Baseline 与身份范围扩展

HEAD=`6f768b25`、树干净；AcceptanceProfileV2（c40f1adc…）与 RuntimeBaselineV3（b7ef22d6…）复测吻合。`RCA1RuntimeIdentityScopeAddendumV1` 已落盘（append-only）：补入 7 个 RCA-1 新增/修改面（taxonomy、diagnostics、facts、service_manager、config、runner、处置脚本）的 sha256、依赖边（orchestrator→taxonomy/diagnostics/executor、service_manager→sink 接线、config→sink 消费、runner→taxonomy、处置脚本→分类码）与"文件哈希≠语义等价、V3 资格身份不迁移"声明。原 13-file manifest 未被取代，仅扩展。

## 2. 已确认的结构复杂度（全部由生成 schema 实测）

来源：`integration-schema-audit-v1.json`（pydantic model_json_schema + pydantic-ai InlineDefsJsonSchemaTransformer，与模型面工具桥同一变换）。

| 指标 | INTEGRATE_V2（生产） | PLAN_V2（从未失败的基线） | Proposal 草案 |
| --- | --- | --- | --- |
| raw 字节 | 9,833 | 2,686 | 5,690 |
| 模型面字节（$defs 内联） | 8,494 | 2,457 | 5,249 |
| $defs | 19 | 3 | 6 |
| 最大嵌套深度 | 8（面 11） | 7 | 7 |
| anyOf 分支 | 48 | 7 | 34 |
| 枚举定义 / 值 | 9 / 43 | 0 / 0 | 0 / 0（见 §3 机制说明） |
| action 变体 | **10** | — | **6** |

19 个 $defs 的构成：**10 个 action 变体**（update_question/create_question/update_evidence_relevance/create_hypothesis/update_hypothesis/create_contradiction/update_contradiction/update_coverage/add_finding_reference/add_pending_proposal_reference）+ **9 个语义枚举**（7 个状态枚举 + disposition/severity/source/priority 等，共 43 个值）。update_question 最重（9 字段）。

**关键事实修正（相对 RCA-1 时的推断）**：V2 顶层**已经 identity-free**（task/run/state 身份、revision/hash、source ids 全部结构性缺席、服务端注入，required=[]，spec §7/§30）——A1-H 边界在顶层早已落实。handle 在模型面是**带正则锚点的纯字符串**（`Q\d+`/`E\d+`/`COV\d+`/`H\d+`/`X\d+`/`F\d+`/`P\d+`），身份绑定在服务端绑定表。schema 复杂度的真实来源 = **10 变体宽度 + 43 枚举值 + 48 anyOf**，不是身份回显。

## 3. Model-owned 与 Server-owned 字段（冻结责任边界，未动）

**Model-owned（语义选择，全部保留）**：每个 action 的 to_status/disposition/text/severity/limitation/attempted_resolution/impact/blocker/investigated_summary、basis/supporting/related handle 的**选择**、finding/proposal 引用的**选择**。
**Server-owned（结构性不可被模型指定）**：task/investigation/run 身份、state revision/hash、source_result ids+hashes、handle→canonical id 绑定（绑定表）、Evidence ref 解析（A1-S 快照域）、grounding 执行（P5A）、状态转换验证与提交（StateTransitionPolicy+SQLite）、finalization 裁决（FinalizationGate）。
**边界完整维持**：提案层不删语义能力、不硬编码语义判断、不自动创造语义对象、不降 grounding 要求、不放宽 enum/handle/Evidence 身份校验（枚举约束的执行点从 schema-parse 移至 resolver——接受集逐 kind 相同，等价测试钉死）、无证据 FACT 不可能自动通过（FACT 断言域在 specialist 层，未触碰）。

## 4. Action reachability matrix

`integration-action-reachability-matrix-v1.json`：10 个合法 action 的语义/操作数/handle 种类/server-owned/验证策略/结果转换全矩阵 + 10 条非 happy-path（缺失操作数、kind mismatch、unknown handle、stale、不可用 action、跨 task Evidence、grounding 不足、Analyst Note 非 Evidence、Claim assertion-strength、闭包验证不通过）的执行点与证据引用。结论：**十个 action 全部可表达、全部可达**；全部非 happy 路径由服务端强制且不受提案草案影响（提案汇入未变更的 canonical 路径）。

## 5. 候选 Proposal Contract（`IntegrationProposalContractDraftV1`）

模块：`benchmarks/contracts/experimental/integration_proposal_v1.py`（**生产导入图之外**，httpserver 零引用；仅测试/审计显式加载）。

设计：`SupervisorIntegrationProposalV1 → resolve_proposal_to_canonical → SupervisorIntegrationDecisionV2 → resolve_integration_proposal_v2（未变更）→ Validator/Policy/Gate（未变更）`。

核心简化：**统一 update 信封**——5 个 per-entity update_* 变体合一；实体 kind 从 handle 前缀**精确双射推断**（COV/Q/E/H/X，非模糊匹配）；每 kind 的 to_status 冻结枚举成员资格在 resolver 强制（fail-closed）。question 专属字段（disposition/investigated_summary/blocker/superseded_by）在非 question 目标上被 `P_FIELD_NOT_VALID_FOR_KIND` 拒绝。10 变体→6。

**不能简化的约束（如实清单）**：10 个语义动作本身（删除=降能力）、43 个枚举值的词表（放宽=违禁）、handle 精确格式与绑定表校验、闭包验证前置（P5B）、basis 不代填（A1 §26）、fail-closed 全有或全无。

## 6. Semantic equivalence 结果

`semantic-equivalence-test-report-v1.json`；`test_integration_proposal_equivalence.py` **16/16 过**：

- **11 个合法 action**（10 canonical + update in_progress 无 disposition 变体）：两路汇入同一冻结绑定表/context/state → canonical v1 决策**全量 model_dump 相等**；
- **old-rejects ⇒ new-rejects**：unknown handle（Q99）、跨 kind basis、状态越枚举——双方全拒，violation 码集相等；
- **2 个 enforcement-point 移动**（逐条文档化）：状态枚举成员资格 parse→resolve（接受集不变）；**1 个新拒绝类**：跨 kind 字段在旧契约不可表达、新契约可表达但被拒——接受集零增长；
- **7 维对比全部一致**：接受集/拒绝集/canonical identity/Evidence refs/state revision/grounding status/verification requirements/finalization eligibility——**零未解释语义差异**。

## 7. 复杂度对比（§7 区分声明）

**已证（demonstrated）**：模型面字节 −38%（8,494→5,249）、$defs 19→6、action 变体 10→6、anyOf 48→34、嵌套 −1、枚举面 9→0（机制=执行点移至 resolver）。
**未验证（unverified）**：模型可靠性改善——11 次历史 INTEGRATE 重试耗尽没有任何 output-tool 参数与字段级错误被持久化（RCA-1 F-3/F-10），**不能声称提案可避免这些失败**。schema 更小≠必然更可靠。
**已知代价**：统一信封使 schema 自描述性下降——kind↔字段映射必须由 instructions 承载（对任何未来 RCA-2B 实现，这是 prompt 侧的真实成本且 prompt 现为冻结面）。

## 8. 历史失败证据的使用边界

允许引用：11 次 INTEGRATE 输出重试耗尽、5 次 INTEGRATE provider 超时（RCA-1 公开 calibration 统计）。禁止并已遵守：不把 schema 复杂度当作已确认根因（RCA-1 归因为 SUSPECTED+INSUFFICIENT_TELEMETRY）；不声称 Proposal 已解决历史模型失败。RCA-2A 仅证明协议可行性与复杂度差异。

## 9. 生产实施回归风险（若未来授权 RCA-2B）

1. 模型可见 schema 变更 → 触发全新 Runtime identity + 全新 qualification/calibration（不可继承 Gen-4/历史测量资格——RCA-2A §10 已明示）；
2. instructions 必须承载 kind↔字段映射——prompt 变更与有效性未经验证；
3. 状态枚举执行点后移：错误输入的报错通道从 pydantic 解析错误变为 resolver violation——retry 反馈内容改变（对模型自纠行为的净效应未知）；
4. 统一信封的跨 kind 字段拒绝是新的失败面（现有生产模型从未见过）；
5. 观测基线：RCA-1 遏制+分类遥测尚未在真实系列中积累 INTEGRATE 失败的字段级证据——建议任何 RCA-2B 之前先在冻结 runtime 上开启诊断 sink 跑一轮 screening（需独立授权）。

## 10. 交付物

| 交付物 | 位置 |
| --- | --- |
| RCA2AContractFeasibilityReportV1 | 本文件 |
| IntegrationActionReachabilityMatrixV1 | audits/…/integration-action-reachability-matrix-v1.json |
| IntegrationProposalContractDraftV1 | audits/…/integration-proposal-contract-draft-v1.json + benchmarks/contracts/experimental/integration_proposal_v1.py |
| SemanticEquivalenceTestReportV1 | audits/…/semantic-equivalence-test-report-v1.json |
| RCA1RuntimeIdentityScopeAddendumV1 | audits/…/rca1-runtime-identity-scope-addendum-v1.json |
| 附加 | integration-schema-audit-v1.json（三模型实测指标）+ 新测试 25 个（等价 16 + 契约/持久化/sink 边界于 RCA-1.8 基础上） |

**STOP**：等待架构审查；RCA-2B 未获授权。
