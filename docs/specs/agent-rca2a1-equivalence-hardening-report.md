# RCA2A1EquivalenceHardeningReportV1

RCA-2A.1 — Proposal Equivalence & Retry Semantics Hardening（离线）
分支 `mvp/agent-v0-runtime-v3-requalification` · 基线 `7382c562` · 2026-10-13
生产零修改（schema/prompt/validator/policy/retry/timeout/grounding/gate）；零模型调用；holdout 零接触。

```text
RCA-1:            CLOSED / TESTED
RCA-2A:           AUDITED
RCA-2A.1:         OFFLINE VALIDATED
RCA-2B:           NOT AUTHORIZED
Production Runtime: UNCHANGED
Historical Gen-4: CLOSED_REJECTED / UNCHANGED
Model calls:      0
Gen-5:            NOT CREATED
```

**处置（§11）：`PROPOSAL_READY_FOR_DIAGNOSTIC_COMPARISON`** —— 加固后的草案（含 Option B Strict/CompactTyped 变体）已通过穷举矩阵、原子性、availability 纪律与 retry 边界验证；下一步（需独立授权）是在冻结 runtime 上开启诊断 sink 做真实系列的 diagnostic comparison，不自动授权 RCA-2B。

## 1. 语义等价的重新界定（§1）

`16/16` 此前证明的是**已选样本**的等价性——本阶段将其降格并代之以三维判据，**分开报告、永不合并为单一 PASS**：

| 维度 | 验证方式 | 结果 |
| --- | --- | --- |
| ACCEPTANCE_SET_EQUIVALENCE | (kind, to_status) 全枚举 own-status 组合双路接受且 canonical 决策全量相等 | 25 组合 ✓（计数见矩阵工件） |
| REJECTION_SET_EQUIVALENCE | 跨 kind 状态 + 非法值（大小写/未知/空串）全枚举双路拒绝 | 全部 ✓ |
| EXECUTION_BEHAVIOR_EQUIVALENCE（反超集） | NEW 接受 ⇒ OLD 接受等价语义动作且 canonical 相等 | 全部 ✓ |

## 2. 状态×字段组合矩阵（§2，穷举非采样）

`ProposalConstraintMatrixV1`（测试生成）。域有限故**全枚举**优于 property-based 采样。覆盖：5 kind 各自合法状态、跨 kind 非法状态、非法大小写（`Answered`/`COVERED`）、未知值、空串、非预期类型（int → 双路 parse 拒绝）、None/缺失/空串三分（外来字段 ""/None/缺失=缺席不违规；非空外来值=硬违规 `P_FIELD_NOT_VALID_FOR_KIND`；自有字段 ""与 old 透传一致）、basis×disposition 组合、create 枚举（source/priority/severity）resolver 强制。

**穷举抓到并已修复一个真实 REPRESENTATION GAP**：草案曾把 `basis_handles` 定为 `()`-默认，使显式 `[]`（"无 basis"，必须触发 CLOSURE_BASIS_REQUIRED）与省略（保持现状）不可区分——A1 §26 语义被破坏。已修复为 `Optional[Tuple]`（None=省略 / []=显式空）并加回归等价断言。这正是"不得将样本等价描述为完整等价"的价值实证。

## 3. 多动作原子性（§3）

valid+valid（顺序保持、canonical 相等）、schema-invalid+valid（提案层快速失败）、resolve-only-invalid（unknown handle E99：提案层接受、**未变更的 canonical resolve 全有或全无拒绝**，violation 码集相等）、重复 update（两路解析出等数转换）、冲突 update（answered+in_progress：resolver 层保序，冲突归 policy）——**无部分提交、无状态漂移、无虚假集成记录**；纯函数性（双次运行逐字节一致）。编排器级"失败不改 state revision"由 RCA-1.8 持久化不变量覆盖。

## 4. A1-H availability 纪律（§4）

`proposal_affordances(table)`（实验代码）与生产 `availability_projection` 逐 case 对照（no-Q / no-COV / no-H/X / only-F/P / mixed 五种绑定域）：**handle 计数完全一致**；统一 update 的每个 kind "有 handle 才 offered"与生产零域纪律一致；add_finding/add_pending 镜像精确；每个 offered update 携带其冻结状态词表。统一 update **不暗示**可更新一切 kind——零域 kind 不会被 offered，F/P 目标在 resolver 被拒（`P_HANDLE_NOT_UPDATABLE`）。

## 5. Retry feedback boundary（§5，TestModel + capture_run_messages）

`RetryFeedbackBoundaryReportV1`（测试生成）。三层成功语义**严格区分**：schema parse success ≠ proposal resolution success ≠ canonical integration success；**提案 parse 成功绝不是集成成功**。

| 场景 | parse | retry prompt | Agent.run 返回 | resolver | 提交 |
| --- | --- | --- | --- | --- | --- |
| A 旧契约枚举错误 | 拒 | ≥1 | 否（UnexpectedModelBehavior） | 未到 | 否 |
| B 草案非法 to_status | **过** | 0 | **是** | `proposal_status_not_in_kind_enum` | 否 |
| C 草案跨 kind 字段 | 过 | 0 | 是 | `proposal_field_not_valid_for_kind` | 否 |
| D 草案未知 handle | 过 | 0 | 是 | `proposal_unknown_handle_prefix` | 否 |
| E 草案合法 | 过 | 0 | 是 | 通过 | 否（canonical 正确） |
| B-strict（Option B） | **拒** | ≥1 | 否 | 未到 | 否 |

**Option A vs Option B 评估（§6，均未接入生产）**：
- **A（现状草案）**：resolver 类违规无 in-band 重试反馈——fail closed 到 cycle 层；无重复提交；完整类型约束由 resolver 维护；符合现有 API。
- **B（Strict 变体，已实现为实验代码）**：`StrictUpdateAction` 的 parse 层前缀条件校验 → ValidationError → pydantic-ai **有界输出重试 + 结构化反馈**（纯 pydantic `model_post_init`，无 monkey-patch、无私有 API）；handle **存在性**仍需绑定表、留在 resolver——两层校验互补，不重复提交（重试消耗同一次 agent.run 的预算）。
- **B 改变 retry 行为**（违规从 cycle 失败变为 in-band 重试）**且扩大模型输入**（retry prompt）——是否净收益需真实模型 diagnostic comparison，本阶段不下结论。

## 6. Model-facing information preservation（§7）

`ModelFacingInformationComparisonV1`（指令用生产 v2 集成指令实测 + 提案补充说明为离线草稿，从未触碰生产 prompt）：

| | 指令字符 | 模型面 schema | 总字符 | 估算 tokens | vs 旧 |
| --- | --- | --- | --- | --- | --- |
| 旧（typed schema 自描述） | 1,828 | 8,494 | 10,322 | ~2,580 | — |
| 草案 + 必需补充说明 | 1,828+1,379 | 5,249 | 8,456 | ~2,114 | **−18.1%** |
| Strict/CompactTyped + 补充 | 同上 | 5,152 | 8,359 | ~2,090 | **−19.0%** |

**信息本身零丢失**（旧 schema 传达的每 kind 合法状态、字段映射、规则全部保留）——**载体从 schema 迁移到 instructions**；schema 字节节省在计入必需指令补充后仍净省 18-19%。若不给补充说明，模型输入信息不足将表现为可避免的 resolver 违规/重试。

## 7. Alternative assessment（§8）

方案 B"保留 per-kind 类型约束的紧凑 typed schema"= `CompactTypedUpdateAction`（to_status 用**合并状态枚举** MergedStatusEnum——23 个唯一值单一枚举定义保留在 schema 中=部分类型信息回到模型面；per-kind scoping 由 parse 层校验器强制）——**可行**（实测 5,152B 模型面，比草案还小 97B；无需回到 5 变体），且恢复了枚举维度的 retry 反馈。结论：A 的 38% 缩减**不必以类型信息完全损失为代价**；Strict+CompactTyped 组合是当前最优草案形态。未创造新生产 contract。

## 8. 明确区分（指令要求）

- **Semantic equivalence demonstrated on tested domain**：有限域全枚举 + 既有 16 样本——域内完备，**不是**无限输入空间的数学等价。
- **Rejection behavior differences**：执行点移动 2 处（状态枚举 parse→resolver/strict-parse；跨 kind 字段不可表达→拒绝）；新拒绝类 1 个；None-vs-[] 表述缺口已修复。
- **Retry behavior differences**：A/B 两方案行为不同（见 §5 表）；均不改生产 retry 次数。
- **Unverified model reliability**：一切复杂度/反馈改进对模型失败率的净效应未知——历史失败无字段级证据（F-3/F-10）。
- **Production implementation risks**：同 RCA-2A §9 + 新增：Strict 变体的 parse 层校验使"错误计数"从 cycle 级变为 run 内重试级，遥测聚合口径需在实施前重定义。

## 9. 测试

新增 `test_rca2a1_hardening.py` **6 测试**（穷举矩阵含三维断言、字段矩阵、原子性、affordances×5 域、retry 边界 A-E+strict、矩阵工件生成）；RCA-2A 原 16 等价测试继续通过；全量 `tests/unit/investigation/` + `tests/unit/benchmarks/` = **1134 passed / 1 skipped / 0 failed**。

## 10. 交付物

| 交付物 | 位置 |
| --- | --- |
| RCA2A1EquivalenceHardeningReportV1 | 本文件 |
| ProposalConstraintMatrixV1 | audits/…/proposal-constraint-matrix-v1.json（测试生成） |
| RetryFeedbackBoundaryReportV1 | audits/…/retry-feedback-boundary-report-v1.json（测试生成） |
| ModelFacingInformationComparisonV1 | audits/…/model-facing-information-comparison-v1.json |
| 实验模块扩展 | integration_proposal_v1.py：StrictUpdateAction / CompactTypedUpdateAction / SupervisorIntegrationProposalV1Strict / proposal_affordances |

**STOP**：等待审查；RCA-2B 未授权；生产 Runtime UNCHANGED。
