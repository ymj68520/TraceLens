# CrossModelFailureRootCauseAuditV1

Failure Attribution Audit — TraceLens Agent v0, branch `mvp/agent-v0-runtime-v3-requalification`
Created: 2026-10-13 · Scope: public calibration artifacts only · Zero model calls · Original artifacts untouched

**任务性质**：根因归因审计，不是模型资格测试。解释为什么多个不同 provider 的模型在同一冻结 runtime 下大量失败，确认是否存在共享的 Runtime / Adapter / Protocol / Benchmark Harness 缺陷。

**最终处置（§14，多处置并存）**：

| 处置 | 状态 |
| --- | --- |
| BENCHMARK_DISPOSITION_DEFECT_CONFIRMED | **CONFIRMED**（F-1/F-6/F-7/F-8：READY_FOR_8X3 假阳性、run 级超时未武装、归因文案误标、0.5 天花板双语义） |
| RUNTIME_OR_ADAPTER_DEFECT_CONFIRMED | **CONFIRMED**（F-2/F-4/F-5：INTEGRATE 无异常遏制的不对称、APITimeoutError 错分类、LLM_MAX_RETRIES 死配置） |
| PROVIDER_LIMITATION_CONFIRMED | **CONFIRMED**（F-9：step-5-preview 在冻结 120s/次预算下 5/5 无法完成 INTEGRATE 请求；wave-2 配额封锁维持） |
| MODEL_COMPATIBILITY_FAILURE_CONFIRMED | **PARTIAL — 仅延迟维度**（超时=候选延迟属性已证；schema 维度维持 SUSPECTED + INSUFFICIENT_TELEMETRY，实际模型输出从未落盘，按 §14 不强行归因） |
| INSUFFICIENT_EVIDENCE | schema 失败的输出级根因（11 次 "Exceeded maximum output retries (1)" 的具体验证错误） |

---

## 1. Repository Investigation（Added / Modified / Reused）

**Added（本阶段全部新增物）**
- `python_service/scripts/audit_cross_model_failure.py` — 确定性审计引擎（matrix / retries / timeouts / terminalization 四个子命令，只读）
- `python_service/tests/unit/investigation/test_protocol_feasibility_audit.py` — §6 协议可达性 10 测试
- `python_service/tests/unit/benchmarks/test_screening_disposition_regression.py` — §8/§12 处置契约 6 测试（1 个 xfail 钉死假阳性）
- `python_service/benchmarks/audits/cross-model-root-cause-audit-v1/` — 本报告 + failure-matrix.{json,csv} + matrix-summary.json + output-retry-forensics.json + timeout-forensics.json + terminalization-audit.json + audit-findings.json + interpretation-amendment-v1.json

**Modified**：无（production runtime / prompt / retry / timeout / budget / AcceptanceProfileV2 / 历史工件全部未动）

**Reused**：P4B 离线闭环测试设施（`OfflineSupervisor` / `OfflineSpecialistDispatcher` / `FakeCppBackend` + pydantic-ai `TestModel`）作为 §6 的驱动底座。

**关键调用链（实测定位，非文档推断）**：

| 组件 | 位置 | 要点 |
| --- | --- | --- |
| `build_chat_model` / `resolve_adapter_config` | `httpserver/services/investigation/agent_model_adapter.py:162/125` | 单一配置源；profile 全局：`supports_json_schema_output=False`、strict 工具关、`default_structured_output_mode` 未覆盖 → pydantic-ai 默认 `'tool'`（结构化输出=output tool 函数调用，文本输出被禁止） |
| pydantic-ai 版本 | 2.30.0（pin 断言在 adapter:31） | `Exceeded maximum output retries (N)` 来自 `_agent_graph.py:377` / `_tool_execution.py:501,519` |
| Supervisor PLAN/INTEGRATE | `agent_supervisor.py:571-616` | 四个 Agent **均未传 retries** → pydantic-ai 默认 retries=1（输出重试预算 1，marker 显示 "(1)"） |
| Specialist | `agent_specialist_executor.py:890` + `pydantic_bridge.py:174` | `Agent(retries=AgentRunPolicy.max_output_retries)` 默认 2（marker "(2)"） |
| 异常遏制 | `agent_orchestrator.py:~1318（PLAN 有 catch+事件化）vs :1596/:1681（INTEGRATE 无 catch）` | 不对称是 16/16 run 级失败从 INTEGRATE 逃逸的直接机制 |
| 失败记录 | `benchmarks/runner.py:300-307` | 全部异常塌缩为 `FailureLayer.RUNTIME` + `str(exc)[:500]`；18 成员枚举只用 1 个 |
| 处置脚本 | `scripts/disposition_openrouter_8x1.py`（§21 决策树）、`disposition_wave2_final.py`（OPEN_STATUSES、0.5 天花板）、`disposition_wave2_screening.py`（QUOTA_CODES、_walk_runs） | 见 §7/§8 |
| FinalizationGate | `agent_finalization.py:171+` | 必答问题 open/in_progress/deferred 拒、answered 需 disposition、unresolved 需 basis、required coverage 需终态 |

## 2. Cross-model failure matrix

引擎：`scripts/audit_cross_model_failure.py matrix` → `failure-matrix.{json,csv}`（逐 run 22+ 字段）。

**144 runs / 10 series**（排除 acceptance-gen2/3/4、b6-holdout=已消费 holdout；a1-*/canary/ablation 非候选校准系列）：

| series | provider | model | runs | run 级失败 | 失败阶段 | 委派层失败码 |
| --- | --- | --- | --- | --- | --- | --- |
| baseline-mimo | hcnsec | MiMo-V2.6-Flash | 24 | 0 | —（0/24 终态化，死于集成**拒绝码** QUESTION_DISPOSITION_REQUIRED 等） | 0 |
| b2-restart | sensenova | sensenova-6.8-flash-lite | 24 | 0 | — | agent_output_invalid ×4 |
| b2-runtime-v3（在位者） | hcnsec | sensenova-6.8-flash-lite | 24 | 0 | — | agent_output_invalid ×1 |
| b2-runtime-v3-glm52 | sensenova | glm-5.2 | 24 | 0 | — | agent_rate_limited ×14 |
| wave2 / dsv4f | sensenova | deepseek-v4-flash | 8+8 | 0 | — | agent_rate_limited ×3 / ×6 |
| glm-5.2 8×1 | sensenova | glm-5.2 | 8 | 0 | — | agent_rate_limited ×1 |
| space-bunny 8×1 | openrouter | stealth/space-bunny-alpha | 8 | **5** | **SUPERVISOR_INTEGRATE ×5** | 0 |
| step-3.7-flash 8×1 | stepfun | step-3.7-flash | 8 | **5** | **SUPERVISOR_INTEGRATE ×5** | 0 |
| step-5-preview 8×1 | stepfun | step-5-preview | 8 | **6** | **SUPERVISOR_INTEGRATE ×6** | 0 |

**跨模型集中性**：16/16 run 级失败集中在**同一阶段（首次委派完成后的第一次 INTEGRATE）、同一协议位置（integration decision 的 output tool 调用）**；case 分布无特殊集中（t2-no-evidence/t2-temporal-trap ×3，其余 ×2，t2-identity-trap ×0——恰好与各系列终态 run 重叠）。**specialist 层在全部 post-A1-T 系列零失败**（A1-T 提案契约修复有效；失败位置整体迁移到了从未做过等价契约简化的 INTEGRATE 层）。

## 3. Structured-output failure forensic audit

11 次 `Exceeded maximum output retries (1)`（space-bunny ×5、step-3.7-flash ×5、step-5-preview ×1）逐条取证（`output-retry-forensics.json`）：

- **失败点定位（三重独立证据收敛）**：① marker "(1)" = supervisor 默认重试预算（specialist 是 2 会显示 "(2)"）；② PLAN 有 catch+事件化、INTEGRATE 无 catch 的拓扑 → 逃逸者只能是 INTEGRATE；③ 16/16 run 的持久 store 最后事件 = `delegation_completed`（12 个 store 仍在盘上，可直接验证）。
- **证据可用性**：`original_output_tool_call` / `actual_model_response` / `local_validation_errors` / `retry_feedback_content` / `last_failure_cause_chain` 全部 **False** —— runner 只存 `str(exc)[:500]`，`safe_failure_message` 消毒，`UnexpectedModelBehavior.__cause__`（含 pydantic 字段级错误的最后 ValidationError）从不序列化。**§3 规则"不得只依据异常字符串判断模型能力失败"被触发：历史归因降级为 SUSPECTED + INSUFFICIENT_TELEMETRY。**
- **历史对照**：b2-restart 时代存在过捕获机制——`scripts/diagnose_specialist_output.py`（monkey-patch dump pydantic-ai 消息历史）产出了 `specialist-output-diagnosis.v1.json`，里面有**真实验证错误**（模型填服务端字段 tool_call_count/observation_count → extra_forbidden；execution_digest 字符串化）并证明**重试反馈确实被模型读到**（部分恢复后耗尽预算）。该钩子只包 specialist，**INTEGRATE 从未被插桩**，且三位新候选筛选时未重新挂载。
- **schema 复杂度不对称（机制性解释）**：INTEGRATE_V2 schema 9,833 字节 / 19 $defs vs PLAN_V2 2,686 / 3（同 extra=forbid）——解释了为什么 PLAN 每次成功而 INTEGRATE 100% 失败，但不构成模型归因证明。
- **确定性机制复现**：`test_integrate_schema_violation_reproduces_historical_signature` 用 TestModel 发一个带多余字段的 INTEGRATE 输出 → 精确复现 `UnexpectedModelBehavior('Exceeded maximum output retries (1)')`、确认 `__cause__` 在内存中存在（只是从不落盘）、确认零 HTTP 参与（schema 重试 ≠ provider 重试）。
- output retry 与 HTTP request retry 未混淆：schema 重试在 pydantic-ai 内（TestModel 即可触发），provider 重试在 openai SDK 内（默认 2）。两者此前在 run 记录中不可区分（同一 str(exc) 通道）——审计后可区分（marker 位数 + store 时间线）。

## 4. Provider timeout audit（step-5-preview ×5）

逐 run 时间线（`timeout-forensics.json`，task store 重建）：

| run | 最后事件 | 事件→失败缺口 | 签名 |
| --- | --- | --- | --- |
| t1-fraud-script-usb | delegation_completed 09:36:42Z | **362s** | 3×120s+开销 |
| t2-misleading-note | delegation_completed | **362s** | 同 |
| t2-no-evidence | delegation_completed | **362s** | 同 |
| t2-report-citation | delegation_completed | **362s** | 同 |
| t2-temporal-trap | delegation_completed | **362s** | 同 |

120s 预算的实际作用范围（代码审计）：
- `LLM_TIMEOUT_SECONDS=120` → adapter `model_settings['timeout']` → **每次 HTTP 尝试**（`pydantic_ai/models/openai.py:1141`），非每逻辑请求、非 run 级；
- openai SDK `DEFAULT_MAX_RETRIES=2`（`openai/_constants.py:10`）→ APITimeoutError 可重试 → **单逻辑请求最多 3×120s+退避**（362s 实测吻合）；
- **SDK 内部重试 = 唯一的放大器**；TraceLens 外部重试不存在（`LLM_MAX_RETRIES=3` 在 agent 路径零消费者，`config.py:263` 定义后无人使用）；pydantic-ai 不重试传输错误；Agent 语义重试（输出重试）无机会触发（传输异常直接终结 agent.run）；
- **run 级 `asyncio.wait_for` 预算未武装**：`production_executor.py:95-99` 读 `generation_params.timeout_seconds`，而 run manifest 的 generation_params 无此键 → `wait_for(timeout=None)`；
- 非流式（agent.run 非 run_stream）→ first_token_at 结构性不存在。

**分类（§4 taxonomy）**：primary = `PROVIDER_RESPONSE_LATENCY`（模型在 120s/次预算内无法产出 integration decision；5/5 gap 恒定 362s）；manifestation = `PROVIDER_TRANSPORT_TIMEOUT`；amplifier = SDK 内部重试 ×3。排除 `LOCAL_REQUEST_SCHEDULING`（同机同时段 specialist 阶段 11 次工具调用+3.5 分钟正常完成；step-3.7-flash 同配置零超时）、排除 `AGENT_RETRY_AMPLIFICATION`（TraceLens 层无重试）、排除 `PROVIDER_QUOTA`（全系列零 429）。**仅证据充分处归因**：单次尝试内部的服务端行为（排队 vs 生成）不可观测 → UNVERIFIED，不归因。

## 5. Adapter equivalence audit

实际 wire 参数（代码级推导 + smoke/运行工件印证）：所有非 OpenRouter 候选走**同一** `build_chat_model` 路径，参数逐项一致：`temperature=0.7`、`max_tokens=16384`、`timeout=120`（per-attempt）、`openai_reasoning_effort='none'`（`LLM_THINKING_MODE=disabled` 映射）、profile 全局（json_schema 关/strict 工具关/max_completion_tokens 关/单 system 消息）、输出模式 `'tool'`。**未设置**：`tool_choice`（API 默认 auto）、`parallel_tool_calls`、`response_format`（agent 路径不使用 json_object）、`extra_body`、SDK `max_retries`（默认 2）。Provider 分支只有 OpenRouter（base_url 已含 /v1、attribution 头、独立 key）。**静默参数转换清单**：`thinking_mode→reasoning_effort` 映射 + OpenRouter 上一候选曾将"端点强制 reasoning"冻结为"不发送 reasoning 参数"（§14 已记录，非静默）。运行时路由身份：88/88 + 117/117 + 86/86 记录 returned==requested，零错配。

**UNVERIFIED（不得假定兼容）**：① stepfun 对长请求（INTEGRATE 大 schema）上 `reasoning_effort=none` 是否仍被遵守（小探针 reasoning_tokens=0 已证，长请求无遥测）；② 各 provider 对 output-tool 大参数 JSON 的截断/限制行为；③ 负载下端点侧隐藏 reasoning 是否复活。无遥测支撑，全部保持 UNVERIFIED。

## 6. Deterministic protocol feasibility — 全链可达性成立

`tests/unit/investigation/test_protocol_feasibility_audit.py` **10/10 PASS**（TestModel 驱动真实 SupervisorAgentFactory/pydantic_bridge/StateTransitionPolicy/FinalizationGate，零模型调用）：

- **五种 disposition 全部可达终态化**：supported / not_supported / inconclusive / unavailable / not_applicable → 合法 INTEGRATE 输出（answered+disposition+真实 evidence ref）被接受、原子提交、charter q-1 离开 §17 开集；
- **W3 fail-closed**：answered 无 disposition → 具名拒绝 QUESTION_DISPOSITION_REQUIRED（正是老 baseline 时代的拒绝码——老系列 0/24 终态化是协议拒绝，不是静默丢失）；
- **证据冲突**：CreateContradiction 合法接受（枚举 low/material/critical 精确匹配）；
- **证据不足/无效引用**：不可解析 ref 在 specialist 层 fail-closed（§9），-contained 为委派失败，run 存活，问题不终态化；
- **FinalizationGate**：终态化状态 + request_finalization → **gate PASS**（violation_codes=()）。

**结论：不存在"合法输出被拒"的 Runtime/Protocol 死路。** 必答问题闭包需要预先通过的语义验证（QUESTION_CLOSURE_VERIFICATION_REQUIRED，P5B 检查器读 `state.pending_verifications`）——生产管线的验证层正常供给该前置。

## 7. Question terminalization audit

- **单一冻结定义**：charter q-1 离开 `{open, in_progress}`；`OPEN_STATUSES` 定义于 `disposition_wave2_final.py:41`，被 `disposition_wave2_screening.py` 与 `disposition_openrouter_8x1.py` 原样导入——三个脚本同一口径。
- **历史数字全部精确复算吻合**（`terminalization-audit.json`）：在位者 **20/24** ✓、glm-5.2 24-run **10/24** ✓、三个 8×1 的 x/8 口径（分母=scheduled，失败 run 计为未终态化）✓。附加实测：b2-restart 10/24、baseline MiMo 0/24、glm-5.2 8×1 6/8（其 8×1 终态化其实不差，死因是配额）。
- **status vs disposition 区分**：snapshot 两字段并列记录；指标只用 status。实测存在 `status=in_progress|disposition=inconclusive` 分歧对 ×1——该 run 被正确计为**未**终态化。`deferred` 等非终态不会被误计（OPEN_STATUSES 只含 open/in_progress；deferred 单独存在，gate 层另有 REQUIRED_QUESTION_DEFERRED 拒绝）。
- **无需修正式修正**：口径一致，输出为验证性记录（AMD-5）。

## 8. Benchmark gate contract audit

**规范来源**：在库机器契约 = `disposition_openrouter_8x1.py` 决策树（常量承自 wave-2 脚本）；指令化契约 = Wave-2 re-entry / screening 指令（会话级，§15/§17/§21/§22，由 qualification-status 工件与记忆转述）。**两者不一致，且没有任何在库文档把 8×1 契约完整成文**——这本身是缺陷的一部分。

| 问题 | 代码化契约（脚本现状） | 指令化契约（冻结验收） |
| --- | --- | --- |
| 8×1 是否要求 8/8 run successful？ | **否**（无完成度分支） | **是**（"硬门/负向门全净，8/8 通过"） |
| 是否要求 charter questions terminal？ | **否**（终态化仅信息性输出） | **是**（§17 q-1 终态化） |
| 只筛选 systemic structural/provider/schema？ | 是——identity/gates/negative/quota/schema>0.5/grounding 六分支，超时等其他 run 级失败**落入 READY_FOR_8X3 兜底** | 超时属 provider 类阻断，不得放行 |
| 0.5 collapse ceiling 直接适用于 8×1？ | 是（run 轴：输出失败 run/scheduled） | ceiling 原义是 wave-1 **委派轴**；筛选期被复用于 run 轴（F-8 双语义） |

**READY_FOR_8X3 假阳性已确定性钉死**：合成 2 终态+6 超时 series（正是 step-5-preview 形态）→ 脚本输出 READY_FOR_8X3（`test_timeout_series_currently_falls_through_to_ready_false_positive` 通过=缺陷在）；需求行为测试 xfail(strict) 挂起，修复授权后转正。新增回归覆盖：schema 主导（NOT_QUALIFIED ✓ 在）、quota 主导（PROVIDER_CAPACITY_BLOCKED ✓ 在）、identity 错配（✓ 在）、失败 run 记账（scheduled/terminal/failed + evaluate-only 只覆盖 snapshot-bearing runs ✓ 在）。

## 9. Evaluate-only completeness

`evaluate_only_reproduction=True` 的准确含义（`disposition_openrouter_8x1.py:144-158`）：**仅对带 result.json 的 run**（2/8）做 `structural_hard_gates` 持久 vs 重算比对；既不复算失败 run 的分类，也不验证聚合处置。step-5-preview 系列的"evaluate-only PASS"= 2/2 终态快照硬门复现，**不构成** 8-run 资格测量的 evaluator 完整验证。失败 run 的分类正确性来自 marker 字符串匹配（"Exceeded maximum output retries"）——超时 run 因此落进 RUNTIME_FAILURE_UNATTRIBUTED 且无处置分支消费该类别。已在回归测试 `test_failed_run_accounting_stays_visible` 中把 scheduled/terminal/evaluate-only 覆盖面的可见性钉死。

## 13. 交付物索引

| 文件 | 内容 |
| --- | --- |
| `REPORT.md` | 本报告 |
| `failure-matrix.json` / `.csv` | 144 run 逐条矩阵（§2 全部列 + 阶段证据 + 分类学） |
| `matrix-summary.json` | 集中度统计、stage/taxonomy 分布、status×disposition 对 |
| `output-retry-forensics.json` | 11 次 schema 失败逐条 + 证据可用性 + 历史对照 |
| `timeout-forensics.json` | 5 次超时时间线 + 预算作用域 + 分类 |
| `terminalization-audit.json` | §7 全 series 复算 + 口径验证 |
| `audit-findings.json` | 13 条结构化 findings（F-1…F-13，每条带文件/函数/证据路径） |
| `interpretation-amendment-v1.json` | 5 条 append-only 诠释修正（含原始工件 sha256 链） |

回归：新增 16 测试（15 passed + 1 xfail-pinned）；受影响既有套件（P4B 闭环、adapter、benchmarks）92 passed，零回归。

## Recommended remediation（不实施，待授权）

1. **处置决策树补分支**（F-1）：RUNTIME_FAILURE_UNATTRIBUTED 主导或终态化 < 100% → NOT_QUALIFIED_SCREENING；把指令化契约（8/8 + q-1 终态化）落成脚本断言；xfail 测试转正。
2. **对称化异常遏制**（F-2）：INTEGRATE 比照 PLAN catch+事件化（supervisor failure = first-class cycle outcome）。
3. **失败遥测落盘**（F-3）：runner 记录异常类名 + cause 链；把 `diagnose_specialist_output.py` 的 retry-prompt 捕获机制产品化（可选 sink，默认关），**覆盖 supervisor 两阶段**——否则未来任何 schema 归因仍是字符串推断。
4. **分类修复**（F-4）：`map_provider_exception` 增加对 `APITimeoutError`/`APIConnectionError` 的显式分支（`type(exc).__name__` 判断）。
5. **配置对齐**（F-5/F-6）：要么让 adapter 消费 `LLM_MAX_RETRIES`（显式传入 AsyncOpenAI(max_retries=…)），要么从配置中删除并注明 SDK 默认；给 benchmark 配置补 run 级 `timeout_seconds`。
6. **处置文案**（F-7/F-8）：M7 归因文本按分类分流；0.5 天花板按轴命名拆分（delegation-axis / run-axis 两个常量）。
7. **候选侧选项**（§14 边界内）：INTEGRATE 输出契约做 A1-T 式提案简化评估（19→n $defs）属于 runtime 变更，须显式授权 + 新 candidate_config_id 重测；超时预算调整同样=新候选。

**STOP**：本阶段未修改任何 production 代码，未发起新模型调用，未触碰 holdout；等待审查与修复授权。
