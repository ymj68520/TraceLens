# RCA2A2StepFunDiagnosticReportV1

RCA-2A.2 StepFun 诊断执行 · 基线 `0090a1ca` · 2026-10-13 · 诊断实验（非资格筛选）

```text
RCA-1:            CLOSED / TESTED
RCA-2A:           AUDITED
RCA-2A.1:         OFFLINE VALIDATED
RCA-2A.2-StepFun: DIAGNOSTIC_COMPLETED
RCA-2B:           NOT AUTHORIZED
Historical Gen-4: UNCHANGED
AcceptanceProfileV2: UNCHANGED (c40f1adc… 复测)
Gen-5:            NOT CREATED
```

## 执行摘要

4 个预登记案例 × 1 次尝试，StepFun `step-3.7-flash`（**直连**，无 OpenRouter），历史冻结 exact 配置零调整，诊断开启。**4/4 run 的 INTEGRATE 全部在输出验证层失败**（遏制生效、无非法提交）——与 582bc443 筛选期的历史失败层**精确复现**；PLAN 与 specialist 委派每次都成功（委派失败 0、完成 4/4）。字段级原因 = `FIELD_LEVEL_CAUSE_UNKNOWN`（原因见 §4 接线缺口，已修复）。

## 基线与身份

- HEAD `0090a1ca`、树干净；AcceptanceProfileV2 `c40f1adc…` 复测吻合；RCA-1/2A/2A.1/2A.2-BLOCKED 工件链在案。
- `RCA2A2ConnectivityAttributionAmendmentV1`：原 OpenRouter 阻断精确归因为 `CONNECTIVITY / PROVIDER_ENDPOINT_UNREACHABLE`，provider_capacity 与 model_semantics 均 NOT_EVALUATED；原始 3/3 连接错误与代理不可达记录字节不动。
- 模型身份：requested==returned==`step-3.7-flash`（4 run 全部 identity 记录，共 73 条）；配置哈希 `3b9f33ec…`/`7646dad5…`（历史冻结工件原样）。

## V2 就绪门（真实调用前，PASSED）

生产契约版本路径（v2）专项验证 8 项全过：V2 schema hash 对应实际失败契约；验证错误字段路径完整（union 成员全路径）；`retry_attempts=1`；`tool_name=final_result`；`run_id`==AgentRun；`supervisor_integration_failed` 持久化；无非法 IntegrationDecision 提交；input 值/Evidence 正文/key 不落盘。错误类型形态实测：`extra_forbidden` + `literal_error`（pydantic v2 对 Literal 状态错值的可观察形态 = INVALID_ENUM 类）。

## Preflight（一次性）

3/3 HTTP 成功、身份逐一精确、无 429/配额/连接失败 → CAPACITY_PREFLIGHT_PASS。未启动 watcher/循环。

## 四案例运行状态

| # | 案例 | elapsed | 身份记录 | 模型请求 | tokens in/out | INTEGRATE | 硬门 | q-1 | coverage |
|---|---|---|---|---|---|---|---|---|---|
| 1 | t2-identity-trap | 152.6s | 20 ✓ | 16 | 121,007/10,117 | **失败（遏制）** | PASS | open | not_started |
| 2 | t2-no-evidence | 151.8s | 24 ✓ | 20 | 134,986/8,216 | **失败（遏制）** | PASS | open | not_started |
| 3 | t2-temporal-trap | 171.8s | 15 ✓ | 11 | 63,893/7,527 | **失败（遏制）** | PASS | open | not_started |
| 4 | t2-report-citation | 189.2s | 14 ✓ | 10 | 72,314/7,986 | **失败（遏制）** | PASS | open | not_started |

遏制生产链全程验证（事件序列 27 集成失败→28 run_failed→29 finalization_requested→30 **finalization_denied** [UNINTEGRATED_COMPLETED_DELEGATION + COVERAGE_NOT_TERMINAL]）；工作状态 revision 零非法推进。

## INTEGRATE 字段级失败矩阵（核心交付）

`rca2a2-stepfun-integration-failure-matrix-v1.json`。**四层成功率**（分母=4 次观察到的 INTEGRATE attempt）：

- output_tool_received：逐次不可观察（见接线缺口）——重试耗尽类意味着输出验证发生
- pydantic_parse_success：**0/4**
- canonical_resolution_success：**0/4**
- integration_commit_success：**0/4**
- output_retry_exhaustion：**4/4**；provider timeout：**0**；输出验证重试次数：每次 1（frozen 预算）；SDK/HTTP 重试逐次不可观察

**字段级归因分布**：4× `FIELD_LEVEL_CAUSE_UNKNOWN`——九类全部 UNOBSERVABLE，不猜测。

**层复现结论（有轨迹+遏制负载证据）**：4/4 失败 = `UnexpectedModelBehavior`（pydantic_ai.exceptions）← `pydantic_core.ValidationError`，`underlying_code=model_output_retry_exhausted`——失败**稳定定位于 INTEGRATE 输出契约交互**，与历史跨模型失败同层同签名。

## 接线缺口（如实记录，已修复）

诊断 sink 为空的原因：`run_p8b_baseline` **直接构造** AgentOrchestrator（不经 ServiceManager），RCA-1.3 的 sink 接线未覆盖 benchmark 路径。本提交修复（benchmark runner 镜像 ServiceManager 接线，默认关、env/settings 选入）。**依据 §0"不得根据运行结果重复预登记案例"，4 个案例未用修复后的接线重跑**——字段级证据留待未来授权的诊断运行。

## §11 七问作答

1. **失败是否集中于某个 action variant？** 不可知（字段级未观察）。
2. **是否集中于 enum 或 union？** 不可知；canonical ValidationError 的 cause 链证明失败在 union 校验域内（46 错误级联的 V1 解析——见就绪门），但具体 member 未持久化。
3. **是否存在填写 server-owned 字段问题？** 不可知（b2-restart 时代的 specialist 层曾有此模式；INTEGRATE 层无证据）。
4. **extra/missing/类型错误何者为主？** 不可知（FIELD_LEVEL_CAUSE_UNKNOWN）。
5. **PydanticAI retry feedback 是否正常产生？** 是——重试耗尽本身证明 feedback-再生成循环发生了（有界 1 次后耗尽，机制正常）。
6. **Retry 后是否有效自我修正？** 无——4/4 耗尽（与历史一致：反馈循环未促成修正）。
7. **Strict+CompactTyped 能否减少结构性负担？** 有证据的假设（非结论）：失败稳定位于输出验证层且 4/4 耗尽，与 schema 复杂度相关的假设相容；但字段级缺失使我们不知道减少哪部分（枚举/字段宽/union）最有效——这正是需要 sink 完好的一次 diagnostic comparison 的原因。

## Evidence Integrity / Grounding

结构硬门 4/4 PASS（无跨 task 泄漏、无伪造证据、无 graph id、无权威旁路——零容忍全净）；finalization 全部 deny（正确阻止未集成状态）；grounding 路径未受诊断影响。

## 是否进入 RCA-2B

**建议：先重执行本诊断（sink 已修好），再评估 RCA-2B。** 字段级证据是 RCA-2B 决策的前提；本次已证明（a）失败层 4/4 稳定复现、（b）sink 修好后字段级可归因、（c）重执行成本约 12 分钟。RCA-2B 本身保持 NOT AUTHORIZED。

## 历史工件完整性

Amendment hash 链只读校验通过；OpenRouter BLOCKED 工件字节不动；step-3.7-flash 的 NOT_QUALIFIED_SCREENING 工件未改变（§12）。全量测试 **1136 passed / 0 failed**（新增 V2 就绪门）。

**STOP**：等待架构审查；禁止自动启动新模型或下一轮实验。
