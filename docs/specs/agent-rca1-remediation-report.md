# RCA1RemediationReportV1

RCA-1 Correctness & Observability Remediation — TraceLens Agent v0
分支 `mvp/agent-v0-runtime-v3-requalification` · 审计基线 `a79bf406` · 2026-10-13
范围：已确认的 Runtime 失败处理 + Benchmark 正确性缺陷。不触碰未确认的模型能力问题。

**最终状态**

```text
RCA-1:            REMEDIATED / TESTED
RCA-2:            NOT STARTED
Historical Gen-4: CLOSED_REJECTED / UNCHANGED
Model qualification: NOT RESUMED
Model calls:      0
```

## 0. 基线确认（执行前实测）

- HEAD = `a79bf406`（审计提交），工作树干净。
- `precalibration-runtime-baseline-v3.json` sha256 `b7ef22d6…`；`agent-v0-acceptance-profile-v2.json` sha256 `c40f1adc…`——修复后复测**逐字节相同**。
- 改动前受影响套件基线：86 passed + 1 xfailed，零失败。

## 1. Added / Modified / Reused

**Added**
- `httpserver/services/investigation/agent_failure_taxonomy.py` — 类型驱动失败分类器（RCA-1.2）
- `httpserver/services/investigation/agent_failure_diagnostics.py` — 结构化诊断 sink（RCA-1.3，默认关）
- `httpserver/services/investigation/agent_retry_timeout_facts.py` — 生效预算事实记录（RCA-1.4，只读）
- `tests/unit/investigation/test_rca1_remediation.py` — 11 测试
- `benchmarks/audits/cross-model-root-cause-audit-v1/screening-contract-reconciliation-v1.json`（RCA-1.0）
- `benchmarks/audits/cross-model-root-cause-audit-v1/runtime-behavior-compatibility-assessment-v1.json`（RCA-1.7）
- 本报告

**Modified**
- `agent_orchestrator.py` — INTEGRATE 两个调用点异常遏制 + PLAN/INTEGRATE 诊断发射 + 可选 sink 构造参数（RCA-1.1/1.3）
- `agent_specialist_executor.py` — `map_provider_exception` 类型优先修分类（F-4）；新枚举成员 `SUPERVISOR_INTEGRATION_FAILED`；specialist 失败路径诊断发射；`import time`
- `benchmarks/runner.py` — FailedRunRecordV1 增可选分类字段；except 块类型分类（保留 legacy 平面记录兼容）
- `disposition_openrouter_8x1.py` — RCA-1.5 重写决策树与记账
- `service_manager.py` / `config.py` — 诊断 sink 接线（默认关）
- 测试更新：`test_screening_disposition_regression.py`（xfail 转正 + 3 新测试）、`test_protocol_feasibility_audit.py`（历史签名测试改钉遏制语义）

**Reused**：P4B 离线闭环设施、处置脚本 `_walk_runs`/共享常量、`diagnose_specialist_output.py` 的诊断经验（重试反馈结构、脱敏思路）——但以显式注入点取代 monkey-patch。

## 2. 修复前后的阶段失败路径

**修复前（审计实证）**：INTEGRATE 模型/Provider 异常 → 无 catch → 逃逸 run_loop → BenchmarkRunner 塌缩 `RUNTIME`+`str(exc)[:500]` → 无轨迹事件、无阶段、无 cause 链 → 处置脚本靠字符串 marker 分类 → 未识别类失败落入 READY_FOR_8X3 兜底。

**修复后**：INTEGRATE 异常 → `except Exception` 遏制（`CancelledError` 等 BaseException 穿透）→ `classify_failure` 类型分类 → 轨迹事件 `supervisor_integration_failed`（含 `underlying_code`/异常类型/cause 链）→ `fail_run(internal_failure)` + `run_stop_reason` 终止循环（不自动重执行）→ 快照诚实记录 failed/未终态化 → 处置脚本按类分派（timeout → NOT_QUALIFIED_SCREENING；未分类 → REVIEW_REQUIRED）。specialist 层失败照旧委派内处置，但获得诊断发射与正确的 timeout 分类。

## 3. Failure taxonomy changes（RCA-1.2）

`classify_failure`（类型优先，永不以字符串为主信号）：`MODEL_OUTPUT_VALIDATION_ERROR` / `MODEL_OUTPUT_RETRY_EXHAUSTED`（含预算元数据）/ `PROVIDER_RATE_LIMITED` / `PROVIDER_REQUEST_TIMEOUT` / `PROVIDER_CONNECTION_ERROR` / `PROVIDER_SERVER_ERROR` / `PROVIDER_HTTP_ERROR`（其余 4xx）/ `SUPERVISOR_INTEGRATION_FAILED` / `BENCHMARK_RUNTIME_FAILURE`（fallback，`classified=False`）。每个分类保留原始 SDK 异常类名/模块/cause 链。`map_provider_exception` 修复：`APITimeoutError` → `agent_timeout`（可重试）、`APIConnectionError` → `agent_provider_unavailable`（F-4 关闭）。委派码词汇表兼容（digest 消费者 QUOTA_CODES 等不受影响）。

## 4. Benchmark disposition changes（RCA-1.5，依据 RCA-1.0）

- `ScreeningContractReconciliationV1`：7 条澄清（SC-1…SC-7）+ 2 条 `CONTRACT_REVIEW_REQUIRED`（CC-1："8/8 通过"语义无法从在库证据裁决；CC-2：READY 是否附加 100% 终态化。两者都不影响机器规则的保守性——任何 run 级失败已阻断 READY）。**未创造任何新阈值。**
- 穷尽性：未分类失败 → `REVIEW_REQUIRED`（合成 5×未知异常 series 测试钉死）；READY_FOR_8X3 仅在零 run 级失败时可达。
- 实测重放（合成 series）：2 终态 + 6 超时 → `NOT_QUALIFIED_SCREENING`（6×PROVIDER_REQUEST_TIMEOUT 分类理由），**不可能再经兜底变 READY**；xfail 已转正常 PASS。
- 计数器：`scheduled_count / run_terminal_count / run_failed_count / run_integration_failed_count / snapshot_reproduced_count / failure_classified_count / unclassified_failure_count / aggregate_disposition_verified`；`evaluate_only_coverage` 显式标注 `n/8`——2/2 复现永不再表述为 8/8 完整验证。
- M7 文案：按类分流（修复前超时 run 也被标 "M7 MODEL_OUTPUT_SCHEMA_FAILURE"）。
- 天花板：`RUN_AXIS_COLLAPSE_CEILING`（run 级输出失败/scheduled）与 `DELEGATION_AXIS_COLLAPSE_CEILING`（非配额委派失败/委派尝试）拆分命名，数值不变 0.5。
- 终态化保持独立报告指标（SC-5）。

## 5. Diagnostic sink 设计（RCA-1.3）

- 显式注入（构造参数）+ settings/env 解析工厂；**默认关**（关闭时全部发射点 no-op，字节等价旧行为）；JSONL 文件 sink + 测试用内存 sink；发射永不致命。
- 覆盖 SUPERVISOR_PLAN / SUPERVISOR_INTEGRATE / SPECIALIST 三阶段。
- 记录字段：stage、ts、normalized_failure_code、classified、exception_class/module、cause_class_chain、provider_status、validation_error_details（**只存 type+loc，input 值一律丢弃**——这是唯一结构性携带模型输出文本的通道）、schema_hash（契约身份，非载荷）、tool_name、retry_attempts、request_latency_ms、context（仅 id/计数）。
- 红线（测试钉死）：无 key/header、无案件 Evidence 正文、无推理内容、无完整 prompt/response dump、无 validation input 泄漏。

## 6. Retry/timeout observability（RCA-1.4）

`effective_retry_timeout_facts` 只记录实际生效值：`SDK_MAX_RETRIES=2`（=openai 常量，测试钉死）、每逻辑请求 ≤3 次 HTTP 尝试、`HTTP_ATTEMPT_TIMEOUT=LLM_TIMEOUT_SECONDS`（per-attempt）、supervisor 输出重试 1 / specialist 2、`RUN_TIMEOUT=disabled`、`LLM_MAX_RETRIES` 死配置**仅记录作用域与消费者为零的事实，语义未改**。四层词汇（HTTP 尝试/SDK 逻辑请求/输出重试/AgentRun）写入模块 docstring 与报告。**本阶段未动任何预算。**

## 7. Runtime compatibility assessment（RCA-1.7）

`RuntimeBehaviorCompatibilityAssessmentV1`：本次是 **observability/failure-path change**——不宣称冻结 RuntimeBaselineV3 的字节身份未变；RCA-1 后的 runtime **不得**当作产出 B2 24-run 或 Gen-4 系列的已测 runtime。Prompt/输出 schema/ToolRegistry/StateTransitionPolicy/重试预算/超时预算/证据完整性/FinalizationGate 全部未动（逐项列出证据），冻结文件 sha256 前后一致。

## 8. 测试结果（零模型调用）

- 全量：`tests/unit/investigation/` + `tests/unit/benchmarks/` = **1098 passed / 1 skipped / 0 failed**（改动前基线 86+1xfail 零失败）。
- 13 项要求覆盖：#1 可达性套件既有；#2/3/6/8 遏制套件；#4/5 分类学单测；#7/10 gate 交互；#9/11 处置套件；#12 泄漏测试；#13 历史工件 hash 链只读校验。
- 审计时代测试更新一处：schema 违规签名测试由"钉逃逸行为"（缺陷）改为"钉遏制语义"（修复），历史签名本身仍由轨迹载荷断言保留。
- 既有失败与新增回归的区分：无既有失败；全部失败均为 RCA-1 行为变更所致并在同一提交内更新钉定。

## 9. 历史工件完整性

- 所有 qualification/acceptance 历史工件未修改；amendment 链引用的 sha256 全部复算吻合（测试 #13 常驻校验）。
- **过程事故与恢复**：用真实 step-5-preview 系列目录直接重放新处置脚本时，`screening-report.json` 被覆盖一次——立即 `git checkout` 恢复，恢复后 sha256（`65edbe87…`）与修正案链比对吻合。教训已固化：重放必须以临时副本为 `--results-root`；只读校验测试防止回归。
- Gen-4：`CLOSED_REJECTED / CONSUMED / NO RETRY`——零接触。

## 10. 未解决问题

1. **CC-1/CC-2（CONTRACT_REVIEW_REQUIRED）**：历史指令文本需运营者批准入库成文（"8/8 通过"语义；READY 是否附加 100% 终态化）。
2. `LLM_MAX_RETRIES` 死配置：已记录作用域与消费者（仅 config 定义、agent 路径零消费），按指令未改语义；后续要么接线要么删除，属运营者决定。
3. 诊断 sink 已在 ServiceManager 的 supervisor 与 specialist 两个构造点接线（默认关）；首次实际启用（LLM_FAILURE_DIAGNOSTICS=1）尚待运营者决定输出路径与留存策略。
4. INTEGRATE schema 复杂度（19 $defs）是否做 A1-T 式提案简化——模型能力侧问题，明确不在本阶段范围（STOP 条款）。
5. 模型资格测试未恢复；三位候选的 NOT_QUALIFIED_SCREENING 结论不变（处置与审计结论一致，无翻案依据）。

## STOP 确认

未修改 INTEGRATE schema、未增加任何 retries、未执行 8×1/8×3、未创建 Gen-5、零模型调用。AcceptanceProfileV2 与 Gen-4 状态不变。
