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
| [DatabaseSchema.md](architecture/DatabaseSchema.md) | 各库表清单与分层理由（逐列参考见 [schema/](schema/)） |
| [Deployment.md](architecture/Deployment.md) | 单机 run.sh、分布式 C/S、外部依赖 |
| [Security.md](architecture/Security.md) | 审计日志、任务数据边界、认证现状 |

### 🗄️ 数据库字段参考（docs/schema/）
逐表逐列字段说明（列名/类型/含义/写入方），全部取自建表 SQL：[raw](schema/RawDB.md) · [events](schema/EventsDB.md) · [files](schema/FilesDB.md) · [android](schema/AndroidDB.md) · [windows](schema/WindowsDB.md) · [linux（73 表）](schema/LinuxDB.md) · [memory](schema/MemoryDB.md) · [oss](schema/OssDB.md) · [C/S PostgreSQL](schema/PostgreSQLCS.md)

### 📖 分析师教程（docs/tutorials/）
端到端实操主线（命令全部核实）：[Linux 入侵排查](tutorials/LinuxIntrusion.md) · [Windows 取证](tutorials/WindowsCase.md) · [Android/微信取证](tutorials/AndroidWechat.md) · [内存取证](tutorials/MemoryForensics.md) · [知识图谱与报告](tutorials/KnowledgeGraphReports.md) · [分布式 C/S 实操](tutorials/DistributedCS.md)

### 🛠️ 运维手册（docs/ops/）
[服务启停 Runbook](ops/ServiceRunbook.md) · [数据与备份](ops/DataAndBackup.md) · [外部服务（Neo4j/Redis/PG/LLM）](ops/ExternalServices.md) · [升级与迁移](ops/UpgradeMigration.md) · [性能调优](ops/PerformanceTuning.md) · [安全加固清单](ops/SecurityHardening.md)

### 📐 参考手册（docs/reference/）
[CLI 完整参数](reference/CLI.md) · [.env 全变量](reference/Environment.md)（含未接线/默认值漂移标注） · [错误码目录](reference/ErrorCodes.md) · [跨服务契约](reference/ServiceContracts.md)

### 🧩 模块文档（docs/modules/）
索引见 **[modules/README.md](modules/README.md)**，按 `docs/modules/cpp/** ↔ src/**`、`docs/modules/python/** ↔ python_service/**` 对应。覆盖 C++ 分析器（Android/Windows/Linux/DLL/数据库/OSS/PDF/Office/雕刻/镜像）、核心基础设施（数据库/分类/事件/搜索/TOON/审计/线程池等）、网络层（HTTPServer/TaskManager/路由）、LLM 集成（LLMClient/ModelRouter/MCP）、Python 服务（httpserver/Graphiti 集成/服务层）。

部分模块文档含已标注的**死代码/未注册**条目（VisionAnalysis、AndroidAdbExtractor、OSSRoutes），详见模块索引中的标注。

### 🧪 测试文档（docs/testing/）
| 文档 | 内容 |
|------|------|
| [CppTestCatalog.md](testing/CppTestCatalog.md) | C++ 全部 61+1 个测试目标目录（怎么跑/测什么/依赖） |
| [PythonTestCatalog.md](testing/PythonTestCatalog.md) | Python 117 个测试文件目录与标记体系 |
| [AcceptanceHarness.md](testing/AcceptanceHarness.md) | live_services.py 验收框架：隔离契约/五 profile 旅程/fake LLM |
| [TestFixtures.md](testing/TestFixtures.md) | 测试数据与镜像生成脚本全景 |
| [test-profiles.md](testing/test-profiles.md) | Python 测试档案（fast/focused/investigation/full） |
| [live-integration.md](testing/live-integration.md) | 真实环境集成测试（历史记录） |
| [browser-e2e.md](testing/browser-e2e.md) | 浏览器端到端验证（历史记录） |

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

**文档版本**: 2.0（以代码为准重写）
**最后更新**: 2026-08-23
**维护者**: ymj68520
