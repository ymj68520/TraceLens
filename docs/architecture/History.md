# 演进史：TraceLens 是怎么长成现在这样的

> 依据 git 历史（1284 个提交，2025-11-20 起）与 `docs/hardening|investigation|security|performance|releases/` 存档的标题和结论段整理。每个阶段回答三件事：做了什么、为什么、留下了什么（今天的哪些机制源于此）。细节以存档原文档为准，本文只提供主线地图。

## 阶段 0：单体 CLI 工具（2025-11 ~ 2026-01）

最初的项目（git 首提交 2025-11-20，早期名 ForensicsProject）是一个命令行取证工具：TSK 解析镜像 → 产出 `_raw/_events/_files.db` 三层库。这一阶段定下的地基今天仍在：三层数据库的派生链（[DatabaseSchema §1](./DatabaseSchema.md)）、SQL-as-headers 的 schema 管理、24 分类的前身（当时确实是 13 类，2026 年扩展到 24）。

**留下**：CLI 主链（AnalysisOrchestrator 编排至今仍在用）、`forensic_analyzer` 这个二进制名。

## 阶段 1：服务化与双服务（2026-01 ~ 2026-03）

提交记录里出现 `client-server-architecture`（docs/superpowers/plans/2025-01-15，实际落地在 2026 年初）：C++ 加上 Crow HTTP 服务器（任务/时间线/文件查询路由），Python FastAPI 服务作为"智能层"加入（LLM 描述、后来的 Graphiti）。三服务的雏形在此成型。

同期的重要一步：**任务目录隔离**——HTTP 任务产出从镜像旁边挪进 `data/tasks/<id>/`，这是后来一切数据边界加固（D2b）的物理基础。

**留下**：三服务架构（ADR-1）、TaskManager 单例 + 线程池 + tasks.json 持久化。

## 阶段 2：智能层扩张（2026-03 ~ 2026-06）

- **2026-03**：Graphiti 摄取链成型，嵌入模型改为可配置（git: "Use configurable embedding model in the Graphiti ingestor"）。知识图谱从实验特性变为主线。
- **2026-04**：前端功能化——重摄取工具栏、OSS 路由注册（后来又被移出注册，见 D 阶段）、任务数据库路径端点。
- **2026-05**：DLL 分析器（PEHeaderParser、DLL 配置项）、取证报告适配器系列（docs/superpowers/plans/2026-07-30 的 cross-platform-forensic-report 五部曲在同期孕育）。
- **2026-06**：密集的功能月——场景选择（forensic-scenario-selection）、微信关系图、场景感知流水线（scene-aware-pipeline）、取证提取器扩展、Windows 常见文件类型、内存取证设计（2026-06-22 设计文档列 7 张内存表，实现收敛为 6 张——sockstat 并入 network_connections，见 [schema/MemoryDB](../schema/MemoryDB.md)）。

**留下**：场景自动检测（SceneDetector）、平台 LLM 服务三兄弟、微信/QQNT/MIUI 工件链、内存取证旁路。

## 阶段 3：报告与调查域（R 系列，2026 年中）

`docs/investigation/` 的 r1/r2a-d/r3 与 `docs/integration/m1.5` 记录了这条线：

- **R1 证据基础**：证据键语法（`file:`/`cluster:v1:` 冻结格式）、证据快照与 SHA-256 不变量——"任何结论可回溯到证据"成为硬约束。
- **R2 报告生成**：从直出到版本化快照（A 链）、202+轮询的生成任务（R2c）、引用回溯（citation traceback，R2d 前端）。R2b 冻结了生成准入（input_hash 信封）。
- **R3 端到端评审**：把 分析→评审→事件→图谱→报告 的完整旅程验收化。
- **M1.5 适配器契约**：跨平台报告的平台适配器接口冻结（今天的 forensic_report/adapters/）。

**留下**：今天 Python 侧最重的两个域——取证报告与调查工作台——的骨架与不变量（E1-E11、R2C1-C7）。

## 阶段 4：加固（D 系列，2026-07 ~ 2026-08）

`docs/hardening/` + `docs/security/` 记录的系统化加固：

- **D0a 认证边界**：确认"本地无认证"是设计而非疏漏，画出 C/S 才有的 JWT/组织/角色边界。
- **D1 错误与配置**：固定文案 500（不泄内部细节）、异常只回类名、Redis URL 掩码——错误脱敏纪律从此贯穿。
- **D2a/D2b 危险原语与数据边界**：task_store fail-closed 精确路径匹配、markitdown workspace 门控、跨任务数据不可达。**D2b 是安全上最重要的一步**。
- **D3a/D3b 旧链路退役**：调查旧链（chain B）软退役——`/api/llm/case-analysis` 固定 410、写路径封锁、schema/数据保留。
- **D4a/D4b 生命周期与资源**：任务删除后的终端写保护（existing-only）、TOCTOU 防复活、Graphiti 连接池/驱动关闭、PEM 临时文件、前端轮询 AbortSignal+过期守卫。
- **D5 预发布就绪**、**D6 性能与并发基线**（`docs/performance/`：并发测量、基准 harness、release candidate）。

**留下**：`docs/hardening/` 里的"冻结约束"至今是修改对应代码时的必读清单。

## 阶段 5：分布式与验收（E/F，2026-08）

- **Phase E**：浏览器 E2E harness（`scripts/browser_e2e.py`，CDP 直控，无 Playwright 依赖）、发布就绪检查。
- **Phase F**：live 验收框架（`scripts/acceptance/live_services.py`）——隔离工作区、真实进程、fake LLM、五个 profile 旅程（smoke/task/analyst/restart/matrix）。这是今天 `make acceptance-*` 的来源。
- 同期：`tracelens_agent`（C++ 分布式代理）与 C/S server（PG+JWT）成型，post-merge 可靠性修复集（启动分层超时/降级、LLM 端点统一、MarkItDown 契约、提取准入限额）落地——见 git `24103d0..ba9c022` 一线。

## 阶段 6：实测与文档重写（2026-08-23 ~ 24）

- **全链实测**：900M 稀疏真实 Ubuntu 镜像跑通 分析→提取→MarkItDown→LLM 落库→Graphiti→Neo4j，修复 3 个 P0（镜像内路径解析/graphiti DB 发现/模型名不匹配）。
- **文档四轮重写**（本文所属）：23 文件按代码重写 → 架构+62 模块改解释式 → 补 27 个无文档子系统 → 技术深化（真实代码+逐块解释）→ 扩容到 5 万行（schema 字段参考/教程/运维/参考手册/测试目录/二轮深化）。过程中顺带修复了案例级图谱静默为空的 NameError（commit 447714a），并把约 40 个代码级缺陷如实记录进文档"注意事项"。

## 怎么用这份历史

- 排障时：很多"奇怪的设计"（410 端点、双状态大小写、ApiResponse 只有 FilterRoutes 用）都是某个阶段的合理决策留下的化石——先查 [DesignDecisions](./DesignDecisions.md) 再下结论。
- 改代码前：若触碰 D2b/D4b 相关边界（任务删除、路径解析、资源关闭），先读 `docs/hardening/d2b`、`d4b` 的冻结约束。
- 想深入某阶段：直接读对应存档目录（它们是过程记录，不随代码更新，但结论段仍然准确）。

---


## 里程碑速查表（从 git 提炼）

| 时间 | 里程碑 | 对应存档/代码 |
|------|--------|--------------|
| 2025-11-20 | 仓库首提交（单体 CLI） | git 146bd61 |
| 2026-03-01 | Graphiti 嵌入模型可配置 | git 单行 |
| 2026-03-29 | 任务数据库路径端点（任务目录隔离期） | git |
| 2026-05-14/15 | DLL 分析器（PEHeaderParser+配置） | INTEGRATION_TEST_REPORT |
| 2026-06-04~22 | 场景选择/微信图/场景流水线/提取器/Windows 类型/内存设计（功能月） | docs/superpowers/plans |
| 2026-07-15 | CLI 文本转储大小限制 | plans/2026-07-15 |
| 2026-07-27 | CS 集成加固、确定性过滤 | plans/2026-07-27 ×2 |
| 2026-07-29/30 | MIUI 备份取证、跨平台报告五部曲 | plans 同日期 |
| 2026-08 中 | D 系列加固冻结（d2b/d3b/d4b…） | docs/hardening |
| 2026-08 下 | Phase E/F 验收、D5/D6、合并修复集、全链实测 | docs/releases、git 24103d0..ba9c022 |
| 2026-08-23/24 | 文档四轮重写与扩容（本套文档） | git 0b521dc 起 |
**最后更新**: 2026-08-24（新建：演进史主线，依据 git 历史与存档）
