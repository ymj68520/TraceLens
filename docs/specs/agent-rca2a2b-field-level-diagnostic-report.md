# RCA-2A.2b StepFun INTEGRATE Field-Level Diagnostic Recovery — 报告

基线 `f566105d` · 2026-10-13 · 实验身份 `rca2a2b-stepfun-diagnostic` · 诊断实验（非资格筛选）

```text
RCA-1:            CLOSED / TESTED
RCA-2A:           AUDITED
RCA-2A.1:         OFFLINE VALIDATED
RCA-2A.2:         EXECUTION_COMPLETED / FIELD_LEVEL_OBJECTIVE_UNMET
RCA-2A.2b:        DIAGNOSTIC_COMPLETED
RCA-2B:           NOT AUTHORIZED
AcceptanceProfileV2: UNCHANGED (c40f1adc… 复测)
Historical Gen-4: UNCHANGED
Gen-5:            NOT CREATED
```

**解释（§8）：`FIELD_LEVEL_SCHEMA_FAILURE_IDENTIFIED`**——首次取得真实模型下生产 `SupervisorIntegrationDecisionV2` 输出验证失败的**字段级证据**；但失败发生在 **SUPERVISOR_PLAN 阶段**，本 attempt 未到达 INTEGRATE——INTEGRATE 位的字段级原因仍未建立（如实分开陈述）。

## §2 Benchmark-path 插桩硬门（真实调用前，PASSED）

**不再只测孤立 orchestrator**：sitecustomize 注入 FunctionModel（plan=合法 v2 参数 / integrate=已知非法参数 / specialist=两轮 search_evidence 后诚实空证据提案——捏造 key 被 fail-closed 正确拒绝），子进程跑**真实 `run_p8b_baseline` CLI 全链**（真实任务供给、真实 orchestrator 构造、真实 sink 注入、真实遏制与持久化）。8 项确认全过：

- sink enabled ✓ / 文件存在 ✓ / 条目 ≥1 ✓ / stage=SUPERVISOR_INTEGRATE ✓
- run_id == 持久化 AgentRun（failed/internal_failure）✓
- schema hash == 生产 V2 raw schema（`a214ec4f…` 精确匹配）✓
- validation_error_details 含完整 loc/type（union 成员全路径）✓
- retry_attempts 可观察（=1）✓、tool_name 可观察（`final_result`）✓
- 0600 ✓ / 无 Evidence 内容与 validation input 泄漏 ✓ / 无非法集成提交 ✓ / 与新 experiment 绑定 ✓

门迭代 5 次（指令提取、t2-no-evidence 的诚实空证据语义——捏造被正确拒绝），全部 FunctionModel，零真实调用。证据：`benchmark-instrumentation-gate-report-v1.json` + `gate-sink-evidence.jsonl`。

## §4-5 Preflight 与真实运行

Preflight 一次性 3/3（身份精确）；真实 run：fresh task `6ea05187…`、61.9s、身份 2 记录全精确（step-3.7-flash）、tokens 不可观察（run 未到 usage 记录点）。

## §7-8 字段级取证（核心）

| 项 | 值 |
|---|---|
| 失败阶段 | **SUPERVISOR_PLAN**（delegations_completed_before=0；INTEGRATE 未到达） |
| 异常 | `UnexpectedModelBehavior` ← `ValidationError`，`model_output_retry_exhausted` |
| 原始错误数 | **8**（同一 payload 的 union 级联 = **1 次模型失败**，非 8 次） |
| 分支分组 | DelegateInvestigationActionV2（extra×1）/ RequestFinalizationActionV2（extra×4 + missing×1）/ NoPlanActionV2（extra×2） |
| 错误类型 | extra_forbidden ×7、missing ×1 |
| 主违规（有证据） | **INVALID_UNION**：payload 不匹配任何 plan action 变体（无正确 discriminator；request-finalization 形缺 reason_code 且携带外来字段） |
| 重试 | 输出重试 1 次（冻结预算）后耗尽；feedback 机制正常运转但未促成修正 |
| 采集标记 | **TERMINAL_VALIDATION_ERROR_ONLY**（仅最终耗尽的 ValidationError；不宣称掌握每次重试的原始输出） |
| 遏制 | 快照侧 fail-closed（gates PASS、finalization DENIED COVERAGE_NOT_TERMINAL）；**一致性发现 CF-1**：PLAN 遏制不终止 AgentRun 行（running 残留，P4B 既有语义，重启恢复扫会终态化）——非本次变更引入 |

`RUN_ID` 与持久化 AgentRun 精确关联；无集成/提交事件（SQL 计数 0）。

## §10 统计（分母=1 个 scheduled attempt）

scheduled 1 / started 1 / benchmark-completed 1 / AgentRun contained-failed 1；total_integrate_attempts **0**；四层计数全 0（未到达）；output_retry_exhaustion 1；provider_timeout 0；question_terminalized 0/1；coverage_terminalized 0/1。

## §11 RCA-2B 评估

- **已证**：真实模型下 V2 输出验证失败**字段级可归因**（RCA-1 遥测缺口在生产闭环关闭）；失败发生于 supervisor 输出契约（本轮 PLAN、上轮 INTEGRATE）——跨阶段、跨模型的输出契约交互失败图景成形。
- **仍缺**：INTEGRATE 位的字段级原因（本次 PLAN 先失败，单 attempt 止步于此）；不建议在无新授权下扩大。
- **RCA-2B 价值**：维持 NOT AUTHORIZED；若授权，其收益论证现在有了首个字段级实例（union 载荷不匹配变体=INVALID_UNION 主违规——恰是 Strict+CompactTyped 的 uniform 信封所消除的形态之一，但**不据此宣称其有效**）。

## 历史完整性

原 RCA-2A.2 OpenRouter BLOCKED 工件、StepFun 4-run 工件、step-3.7-flash NOT_QUALIFIED_SCREENING 工件全部字节不动（amendment 均为 append-only）。全量测试 **1136 passed / 0 failed**（新增 V2 就绪门）。

**STOP**：单 attempt 完成（成功与否均止步）；禁止扩大至第二案例；等待架构审查。
