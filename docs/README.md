# TraceLens 技术文档索引

**TraceLens**（数字取证镜像分析平台）的文档入口。文档已按当前代码重写；如与代码不一致，以代码为准。

> 说明：`docs/hardening/`、`docs/investigation/`、`docs/security/`、`docs/performance/`、`docs/releases/`、`docs/integration/`、`docs/features/`、`docs/superpowers/` 为**历史调查/加固/评审记录**（point-in-time 存档），不随代码同步更新，仅作过程追溯用。

---

## 快速导航

### 🚀 新手入门
- **[快速入门指南](getting-started/QuickStart.md)** — setup.sh → .env → run.sh → 第一次分析
- **[安装指南](getting-started/Installation.md)** — 依赖、外部服务（Neo4j/Redis/PostgreSQL/LLM）、.env 变量表
- **[开发指南](getting-started/Development.md)** — 目录结构、构建、测试、vite 代理
- **[常见任务](getting-started/CommonTasks.md)** — 创建任务、API 工作流、C/S 分布式流程
- **[故障排查](getting-started/Troubleshooting.md)** — 健康检查、日志、常见问题
- **[架构总览](architecture/Overview.md)** — 三服务 + 代理架构、模块职责
- **[C++ REST API 参考](api_reference/CPP_REST_API.md)** — C++ 服务（:8080，run.sh 回退 8666）
- **[Python REST API 参考](api_reference/Python_REST_API.md)** — Python 服务（:8090）与分布式 C/S（:8091）

### 📚 核心架构文档
| 文档 | 内容 |
|------|------|
| [Overview.md](architecture/Overview.md) | 系统组成、技术栈、模块依赖、扩展点 |
| [DataFlow.md](architecture/DataFlow.md) | 一个任务的一生：CLI / HTTP / C/S 数据流（含核心代码走读） |
| [Concurrency.md](architecture/Concurrency.md) | 线程/协程/锁全景与已知并发坑速查表 |
| [Interactions.md](architecture/Interactions.md) | 九个关键交互时序与调试观察点 |
| [DesignDecisions.md](architecture/DesignDecisions.md) | 24 条 ADR 风格设计决策记录 |
| [History.md](architecture/History.md) | 从单体 CLI 到三服务与全链实测的演进史 |
| [ThreatModel.md](architecture/ThreatModel.md) | 信任边界、威胁矩阵与残留风险 |
| [DatabaseSchema.md](architecture/DatabaseSchema.md) | 各库表清单与分层理由（逐列参考见 [schema/](schema/)） |
| [Deployment.md](architecture/Deployment.md) | 单机 run.sh、分布式 C/S、外部依赖 |
| [Security.md](architecture/Security.md) | 审计日志、任务数据边界、认证现状 |

### 🗄️ 数据库字段参考（docs/schema/）
逐表逐列字段说明（列名/类型/含义/写入方），全部取自建表 SQL：[raw](schema/RawDB.md) · [events](schema/EventsDB.md) · [files](schema/FilesDB.md) · [android（41 表）](schema/AndroidDB.md) · [统一取数包 .mep.db](schema/MobileEvidenceDB.md) · [windows](schema/WindowsDB.md) · [linux（76 表）](schema/LinuxDB.md) · [memory](schema/MemoryDB.md) · [oss](schema/OssDB.md) · [C/S PostgreSQL](schema/PostgreSQLCS.md)

### 📖 分析师教程（docs/tutorials/）
端到端实操主线（命令全部核实）：[Linux 入侵排查](tutorials/LinuxIntrusion.md) · [Windows 取证](tutorials/WindowsCase.md) · [Android/微信取证](tutorials/AndroidWechat.md) · [手机备份取证（iOS/vivo/鸿蒙/MIUI/美亚·统一取数包）](tutorials/MobileBackupForensics.md) · [内存取证](tutorials/MemoryForensics.md) · [知识图谱与报告](tutorials/KnowledgeGraphReports.md) · [分布式 C/S 实操](tutorials/DistributedCS.md) · [过滤画像](tutorials/FilterProfiles.md) · [全文搜索](tutorials/FullTextSearch.md) · [未知镜像分流](tutorials/IncidentTriage.md)

IM 取证教程族：[微信导入](tutorials/WeChatForensicsImport.md)（含密钥自动推导） · [微信解密过程](tutorials/WeChatDecryptionProcess.md) · [QQ 导入（NTQQ + 老版 4.x/qq_legacy）](tutorials/QQForensicsImport.md) · [QQ 解密过程](tutorials/QQDecryptionProcess.md) · [WhatsApp 导入](tutorials/WhatsAppForensicsImport.md)

### ✨ 功能说明
- **[案情背景预设](case-background-presets.md)** — 28 个预制取证场景背景，创建任务/案件时可选用或手动输入；含文案写法约定与扩展指南
- **[两阶段报告研判](two-stage-report-analysis.md)** — 材料自主研判与案情对照研判
- **[案情报告证据分类](report-evidence-classification.md)** — 叙事报告证据分类契约
- **[案情管理与可选 AI 解耦](case-management-ai-independent.md)** — 案件 CRUD 走 C++ `/api/cases`，不依赖出站 AI
- **[常见问题 FAQ](faq.md)** — 70 问汇总（端口/认证/故障）

### 📥 输入通道说明（docs/ 根目录）
- **[Android 输入能力总表](android-input-support-matrix.md)** — 全部 `--android-source` 通道（15 CLI 值 + HTTP 专属）能力与边界
- **[iOS 逻辑备份](ios-logical-backup.md)** · **[vivo 备份](vivo-backup.md)** — 手机备份输入通道细节
- Android 分阶段实施记录：[逻辑归档/备份输入](android-logical-container-input.md) · [文件系统镜像](android-filesystem-image-input.md) · [sparse/super 规范化](android-sparse-super-input.md) · [离线报告导入](android-offline-report-import.md) · [第三方 HTML 报告导入](external-html-report-import.md)
- RAID 输入链：[只读重组](raid-readonly-input.md) · [无元数据 RAID0/5](raid-metadata-free-input.md) · [作为系统镜像接入](raid-system-image-integration.md)
- 现场与部署：[未知检材预检分流手册](evidence-intake-playbook.md) · [临时本机免登录模式](local-no-login-mode.md) · [本地大模型部署方案](local-llm-deployment.md)（point-in-time） · [演示阅读界面](demo-reading-presentation.md)（point-in-time）
- 历史过程记录（point-in-time 存档，不随代码同步）：android-field-acceptance / android-field-security-6a / android-investigation-6b / android-release-6c / preflight-252c7a9f-disposition / review-todo / neo4j_local_verification_notes / spark-4090-direct-network

### 📋 实施 SPEC（docs/specs/）
进行中的重构规范指南（评审锁定后作为实施唯一依据，完成后决策移交 schema/API 文档；已落地者文首含"实施状态"复核节）：
- **[事件簇分析重构](specs/event-cluster-analysis-redesign.md)** — 聚簇时间自适应（预算驱动）、分析记录一等实体（append-only 版本链）、"是否已分析"精确判定、时间窗本地对齐、全量 map-reduce（不采样）、Graphiti 统一摄入、C++ 遗留端点退役；含 Phase B1→B2→C→D 阶段划分与验收标准
- **[手机取证统一取数格式](specs/mobile-evidence-package.md)**（已实施） — `.mep.db` 三主表契约、取数-分析分离、多适配器；含实现差异记录
- **[美亚容器解析](specs/meiya-container-parsing.md)**（已实施） — MobileMaster FL-901 XOR 容器解密与掩码推导；含实现差异记录
- 其它 SPEC（过程存档）：[文件分析重构](specs/file-analysis-redesign.md) · [删除清理加固](specs/deletion-cleanup-hardening.md) · [KG 摄取加固](specs/kg-ingestion-hardening.md) · [LLM 吞吐加固](specs/llm-throughput-hardening.md) · [MVP 一期验收](specs/mvp-phase1-acceptance.md)

### 🛠️ 运维手册（docs/ops/）
[服务启停 Runbook](ops/ServiceRunbook.md) · [数据与备份](ops/DataAndBackup.md) · [外部服务（Neo4j/Redis/PG/LLM）](ops/ExternalServices.md) · [升级与迁移](ops/UpgradeMigration.md) · [性能调优](ops/PerformanceTuning.md) · [容量规划](ops/CapacityPlanning.md) · [监控](ops/Monitoring.md) · [应急 Runbook](ops/IncidentRunbook.md) · [LLM 运维](ops/LLMOperations.md) · [故障证据矩阵](ops/FailureEvidenceMatrix.md) · [发布前清单](ops/ReleaseChecklist.md) · [Schema 一致性](reference/SchemaConsistency.md) · [安全加固清单](ops/SecurityHardening.md)

### 📐 参考手册（docs/reference/）
[CLI 完整参数](reference/CLI.md) · [.env 全变量](reference/Environment.md)（含未接线/默认值漂移标注） · [错误码目录](reference/ErrorCodes.md) · [跨服务契约](reference/ServiceContracts.md) · [端点平面](reference/EndpointsFlat.md) · [SQL 食谱](reference/SqlCookbook.md) · [字段映射](reference/FieldMappings.md) · [调查报告契约](reference/InvestigationContracts.md) · [schema 一致性](reference/SchemaConsistency.md) · [源码导览](reference/SourceMap.md) · [评审清单](reference/ReviewChecklist.md) · [阅读路线](reference/ReadingPaths.md) · [术语表](reference/Glossary.md)（160 条，含跨文档同名对照）

### 🧩 模块文档（docs/modules/）
索引见 **[modules/README.md](modules/README.md)**，按 `docs/modules/cpp/** ↔ src/**`、`docs/modules/python/** ↔ python_service/**`、`docs/modules/web/** ↔ web/**` 对应。覆盖 C++ 分析器（Android 多源/鸿蒙/雷电/美亚/vivo/iOS/统一取数包/Windows/Linux/DLL/数据库/内存/OSS/PDF/Office/雕刻/镜像）、核心基础设施（数据库/分类/事件/搜索/TOON/审计/线程池等）、网络层（HTTPServer/TaskManager/FieldApp/内存取证路由/路由组）、LLM 集成（LLMClient/ModelRouter/MCP）、Python 服务（httpserver 路由与服务层/Graphiti 集成/IM 三平台/报告/调查）、Web 前端。

部分模块文档含已标注的**死代码/未注册**条目（VisionAnalysis、AndroidAdbExtractor、OSSRoutes），详见模块索引中的标注。

### 🧪 测试文档（docs/testing/）
| 文档 | 内容 |
|------|------|
| [CppTestCatalog.md](testing/CppTestCatalog.md) | C++ 全部 61+1 个测试目标目录（怎么跑/测什么/依赖） |
| [PythonTestCatalog.md](testing/PythonTestCatalog.md) | Python 117 个测试文件目录与标记体系 |
| [AcceptanceHarness.md](testing/AcceptanceHarness.md) | live_services.py 验收框架：隔离契约/五 profile 旅程/fake LLM |
| [WritingTests.md](testing/WritingTests.md) | 如何写 C++/Python/前端/验收测试 |
| [TestFixtures.md](testing/TestFixtures.md) | 测试数据与镜像生成脚本全景 |
| [test-profiles.md](testing/test-profiles.md) | Python 测试档案（fast/focused/investigation/full） |
| [live-integration.md](testing/live-integration.md) | 真实环境集成测试（历史记录） |
| [browser-e2e.md](testing/browser-e2e.md) | 浏览器端到端验证（web/scripts/ Puppeteer 实测脚本全景） |
| RAID 验收过程记录（point-in-time） | [raid-authorized-sample-intake](testing/raid-authorized-sample-intake.md) · [raid-first-milestone](testing/raid-first-milestone.md) · [raid-metadata-free-validation](testing/raid-metadata-free-validation.md) |

验收框架：`make acceptance-{smoke,task,analyst,restart,matrix}`（scripts/acceptance/live_services.py，隔离环境）。

---

## 常用命令速查

```bash
# 构建 + 启动三服务（C++ :8666 回退 / Python :8090 / C/S :8091）
./run.sh                       # 或 make build && make start

# 开发模式
make cpp                       # build/forensic_analyzer --http-server ${HTTP_SERVER_PORT:-8080}
make python                    # python_service/.venv python -m httpserver.main
make web-dev                   # vite dev（:3000，代理已配好）

# 测试
cd build && ctest --output-on-failure    # C++（约 61 个 GTest 目标）
make test-python                         # Python（双应用 + 子包）
cd web && npm test                       # 前端 Vitest

# CLI 分析
./build/forensic_analyzer <镜像>          # 产出 *_raw/_events/_files.db
```

---

## 相关资源

- **GitHub 仓库**：https://github.com/ymj68520/TraceLens
- 运行时 API 文档：C++ 服务 `/api/docs`（Swagger UI）、`/api/docs/openapi.json`

---

**文档版本**: 2.1（2026-11-10 增补：手机取证四通道/统一取数包/IM 三平台/内存取证/Field 野外部署/任务 resume-pause/报告线索表；存量文档按代码复核勘误）
**最后更新**: 2026-11-10
**维护者**: ymj68520
