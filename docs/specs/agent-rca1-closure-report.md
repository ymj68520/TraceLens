# RCA1ClosureReportV1

RCA-1.8 Contract Closure & Final Verification — TraceLens Agent v0
分支 `mvp/agent-v0-runtime-v3-requalification` · 基线 `798f088c` · 2026-10-13
范围：零模型、确定性验证与必要的 benchmark 契约修正。Supervisor schema、Prompt、ToolRegistry、StateTransitionPolicy、retry/timeout budget、AcceptanceProfileV2 均未修改。

```text
RCA-1:            CLOSED / TESTED
RCA-2:            NOT STARTED
Model calls:      0
Historical Gen-4: UNCHANGED (CLOSED_REJECTED / CONSUMED / NO RETRY)
Gen-5:            NOT CREATED
```

## 1. ScreeningContractV1（CC-1/CC-2 正式裁决）

`benchmarks/audits/cross-model-root-cause-audit-v1/screening-contract-v1.json` — 机器可验证规范（8 条原则 R1-R8、9 道 gate、3 项独立指标），回归测试逐条对应。

**CC-1 RESOLVED**："8/8 通过"在 screening 层裁决为"全部 scheduled runs 计账且零阻断性 gate/失败发现"（R1+R2+R5+R6+R7+G8）；acceptance 级读法按 R1 出界。
**CC-2 RESOLVED**：终态化不是 READY 门（R4/M1）——8/8 终态、门控全净、终态化不足 100% 的 series 仍可 READY（指标独立上报，测试 S4 钉死）。

**门槛出处审计（不得伪称历史冻结）**：

| gate | 值 | 出处 | 状态 |
| --- | --- | --- | --- |
| G5 委派轴 schema 率 | 0.5 | "§15 frozen reliability collapse ceiling (AcceptanceProfile era freeze)"，e3962940 起，**原始分母=委派尝试** | FROZEN |
| G6 run 轴输出重试率 | 0.5 | **无独立历史规范**——space-bunny/stepfun 筛选期复用委派轴常量于 run 轴分数 | **CONTRACT_UNRESOLVED**（值保留为操作门，出处如实标记） |
| G1/G2/G3/G4 结构/grounding/负向/身份 | 0 容忍 | P8A §51、wave-2 §20/§1、B5.5 | FROZEN |
| G7 配额主导公式 | — | wave-2 §7/§28（e3962940 谱系） | FROZEN |
| G8 分类失败阻断 READY / G9 未分类→REVIEW_REQUIRED | 定性 | RCA-1/RCA-1.8 指令（无新数字阈值，R8） | ADOPTED_UNDER_DIRECTIVE |

## 2. Screening deterministic regression（八组 series）

`tests/unit/benchmarks/test_screening_contract_v1.py` — 9 测试全过，契约↔代码一致性（常量相等、CONTRACT_UNRESOLVED 标记在案、处置词汇集合校验）+ 全矩阵：

| series | 期望 | 实测 |
| --- | --- | --- |
| S1 8/8 终态门净终态化 100% | READY_FOR_8X3 | ✓ |
| S2 7 终态 + 1 分类超时 | NOT_QUALIFIED_SCREENING | ✓ |
| S3 2 终态 + 6 超时 | NOT_QUALIFIED_SCREENING | ✓ |
| S4 8/8 终态门净但终态化 4/8 | READY_FOR_8X3（CC-2 裁决落地） | ✓ |
| S5 schema 失败 62.5%>0.5 | NOT_QUALIFIED_SCREENING（systemic） | ✓ |
| S6 结构违规（graph id 作证据） | NOT_QUALIFIED_SCREENING | ✓ |
| S7 未分类 runtime 失败 | REVIEW_REQUIRED | ✓ |
| S8 失败 run 无 result.json 有 failure.json | 计账正确（4/4/4/4） | ✓ |

四种处置词表互不混淆（VOCABULARY 集合校验常驻）。

## 3. INTEGRATE persistence invariants

`tests/unit/investigation/test_integrate_persistence_invariants.py` — 4 测试全过：

- **全链**：completed delegation → INTEGRATE 失败（真实 pydantic-ai 重试耗尽）→ 轨迹事件（typed cause）→ AgentRun failed(internal_failure) → 工作状态零 integration commit（revision 不变）→ Finalization deny（UNINTEGRATED_COMPLETED_DELEGATION）。
- **SQLite 写失败**：类级注入 containment 事件写失败 → 异常**响亮传播**（不吞、不产假 outcome；委派期写入不受影响）。
- **异步取消**：CancelledError 穿透（RCA-1.6 既有测试引用）。
- **服务重启**：遏制后新 orchestrator 实例 → 新 run id；旧 run 保持 failed；被中断委派永不恢复、永不伪造集成。
- **task store 删除**：missing store 的 `open_existing` 抛错=恢复扫描跳过契约；恢复扫描对已 failed 的遏制 run 零复活。

虚假 IntegrationDecision 与自动重执行：无（结构性不可能——遏制路径 return，不进入提交分支）。

## 4. Diagnostic sink operational boundary

`diagnostic-sink-operational-boundary-v1.json` 冻结七项边界，代码可机械校验的部分已测试钉死：

- **范围**：初始仅 synthetic/calibration；真实案件部署默认禁止启用，启用=运营者明示接受脱敏契约；模型原始响应与 Evidence 内容结构性不可记录。
- **默认关**：关闭时全部发射点 no-op。
- **路径/权限**：必须绝对路径（相对路径构造期抛 `DiagnosticsPathError`）、文件 0600 先于首写（测试断言 stat mode）。
- **并发**：进程级锁串行追加；支持形态=单进程单文件，跨进程不支持（文档化）。
- **脱敏**：只存 type+loc，input 恒丢；泄漏串断言常驻。
- **保留**：文件在一切 task store 之外，§18 清理与案件删除不可触及；显式运营者轮换，无自动过期。
- **失败隔离**：构造错配在接线期响亮失败；运行期写失败必吞（敌对目录测试钉死）——诊断故障永不改变调查结论或筛选处置。

## 5. RCA1RuntimeIdentityRecordV1

`rca1-runtime-identity-record-v1.json` — 13 文件生产 runtime 清单在三参照点的实际 sha256（985f09e1=V3 资格时代、a79bf406=审计基线、798f088c=RCA-1）：

- 与 V3 资格时代**逐字节相同**：agent_supervisor / agent_specialist_result / agent_transitions / agent_finalization / agent_integration / agent_integration_v2 / pydantic_bridge / production_executor（8/13）。
- 不同：agent_model_adapter（wave-2 OpenRouter 分支+identity sink，RCA-1 之前）、agent_orchestrator、agent_specialist_executor、runner、config（RCA-1 修改）。
- **声明**：Historical RuntimeBaselineV3 的资格身份不自动迁移至 RCA-1 modified runtime；未重跑 B2、未创建新正式 RuntimeBaseline；未来资格测试须按 §14 全新测量。
- 冻结 profile（V3 baseline + AcceptanceProfileV2）sha256 前后一致，再次复测吻合。

## 6. 回归与交付

- 全量：`tests/unit/investigation/` + `tests/unit/benchmarks/` = **1112 passed / 1 skipped / 0 failed**（RCA-1 收尾时 1098+1skip → 本阶段净增 14 测试：契约 9 + 持久化 4 + sink 边界 1）。
- 交付物：本报告、`ScreeningContractV1`、`RCA1RuntimeIdentityRecordV1`、`DiagnosticSinkOperationalBoundaryV1`、三个新测试文件。
- 历史工件完整性：amendment hash 链只读校验常驻测试通过；本阶段零次重放历史目录。

## 遗留与边界

- G6（run 轴 0.5）保持 `CONTRACT_UNRESOLVED`：值在用、出处未获历史规范支持——后续若要"转正"需要运营者明示批准，不得静默。
- Sink 首次实际启用仍待运营者指定输出路径与轮换节奏（边界已冻结）。
- 模型能力侧问题（INTEGRATE schema 复杂度、候选模型表现）不在本阶段范围，模型资格未恢复。

**STOP**：等待 RCA-2 独立授权。
