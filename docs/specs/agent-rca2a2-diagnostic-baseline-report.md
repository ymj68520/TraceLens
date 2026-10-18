# RCA2A2DiagnosticBaselineReportV1 — DIAGNOSTIC BLOCKED

RCA-2A.2 — Bounded Real-Model Diagnostic Canary · 基线 `4a4b5b6a` · 2026-10-13

```text
RCA-1:            CLOSED / TESTED
RCA-2A:           AUDITED
RCA-2A.1:         OFFLINE VALIDATED
RCA-2A.2:         DIAGNOSTIC BLOCKED（Provider 不可达）
RCA-2B:           NOT AUTHORIZED
Historical Gen-4: UNCHANGED
Gen-5:            NOT CREATED
```

## 结论

**诊断被 Provider 阻断，4 个预登记样本零消耗、零 run 启动。** 但本阶段最重要的产出为**阳性**：§2 确定性就绪门通过——RCA-1 遥测缺口（F-3/F-10：字段级错误不可观察）**已在代码层关闭**。未来任何真实模型 INTEGRATE 失败都将留下字段级可归因证据。

## §2 就绪门（真实模型调用前完成，PASSED）

`test_rca2a2_diagnostic_readiness.py`：TestModel 驱动真实 orchestrator 遏制路径 + 真实文件 sink，逐项证明可观察：

- stage / 异常类型+模块 / 归一化分类（`model_output_retry_exhausted`, classified）
- **验证错误类型 + 位置**（union 成员完整路径，末位精确到冒犯字段 `tool_call_count`）
- schema hash（对照 orchestrator 实际输出契约）/ 重试计数（=1，supervisor 预算）/ output-tool 名（`final_result`）
- **run-id 精确关联**（entry.context.run_id == failed AgentRun）
- 脱敏保持：ValidationError input 值不落盘（断言）

→ **NOT** `DIAGNOSTIC_INSTRUMENTATION_BLOCKED`。

## §6 容量门（STOP 触发点）

| 尝试 | 结果 |
| --- | --- |
| 直连 preflight（3×256-token 探针） | **PROVIDER_CAPACITY_BLOCKED** — 3/3 `APIConnectionError`（capacity-preflight.json） |
| 单次文档化代理校正（192.168.31.19:7897，非 watcher/循环） | 代理 TCP 不可达（局域网拓扑已变化）+ 3/3 `APIConnectionError`（capacity-preflight-proxy.json） |

按指令 §6 STOP：无 watcher、无窗口等待、无模型切换。探针请求不进入实验测量。

## §4/§5/§7 状态

- 模型选择：space-bunny-alpha@openrouter，**历史冻结 exact 配置原样复用，零参数调整**。
- 预登记样本：4 案例（t2-identity-trap=历史成功对照 + 三个语义失败类型）已在 Manifest 中冻结于任何模型调用之前，**零消耗**——连通性恢复后 Manifest 可原样重执行（需新时间戳 + 新 preflight）。
- 执行：4 scheduled / 0 started；结构不变量未被行使（武装状态保持）。

## §12 解释

`INSUFFICIENT_DIAGNOSTIC_EVIDENCE`——无 INTEGRATE attempt 被观察，历史跨模型失败归因维持 **SUSPECTED + INSUFFICIENT_TELEMETRY** 不变。四案例不能也未被用于任何资格判定。

## RCA-2B 价值评估

RCA-2B 保持 NOT AUTHORIZED；本阻断不改变其价值判断——反而**强化**了未来诊断运行的理由：字段级证据现在保证可归因。恢复连通后重执行成本低（Manifest + 就绪门 + preflight 全部就位）。

## 交付物（benchmarks/audits/rca2a2-diagnostic/）

- rca2a2-diagnostic-experiment-manifest-v1.json（首调前冻结：runtime/model-config/corpus/诊断代码/输出契约哈希 + 样本排序 + 停止条件）
- rca2a2-integration-failure-matrix-v1.json（零观察 + 9 类归因全零 + PROVIDER 阻断记录）
- capacity-preflight.json / capacity-preflight-proxy.json
- 本报告（JSON 版同目录）

**STOP**：实验终止，生产代码零修改（仅诊断 sink 字段补齐与 orchestrator 透传参数——RCA-1.3 授权范围内的诊断接线），等待架构审查。
