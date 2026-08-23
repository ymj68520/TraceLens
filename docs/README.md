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
| [DataFlow.md](architecture/DataFlow.md) | CLI / HTTP 任务 / C/S 三条数据流 |
| [DatabaseSchema.md](architecture/DatabaseSchema.md) | 各 SQLite 库全部表 + C/S PostgreSQL 表 |
| [Deployment.md](architecture/Deployment.md) | 单机 run.sh、分布式 C/S、外部依赖 |
| [Security.md](architecture/Security.md) | 审计日志、任务数据边界、认证现状 |

### 🧩 模块文档（docs/modules/）
索引见 **[modules/README.md](modules/README.md)**，按 `docs/modules/cpp/** ↔ src/**`、`docs/modules/python/** ↔ python_service/**` 对应。覆盖 C++ 分析器（Android/Windows/Linux/DLL/数据库/OSS/PDF/Office/雕刻/镜像）、核心基础设施（数据库/分类/事件/搜索/TOON/审计/线程池等）、网络层（HTTPServer/TaskManager/路由）、LLM 集成（LLMClient/ModelRouter/MCP）、Python 服务（httpserver/Graphiti 集成/服务层）。

部分模块文档含已标注的**死代码/未注册**条目（VisionAnalysis、AndroidAdbExtractor、OSSRoutes），详见模块索引中的标注。

### 🧪 测试文档（docs/testing/）
| 文档 | 内容 |
|------|------|
| [test-profiles.md](testing/test-profiles.md) | Python 测试档案（fast/focused/investigation/full） |
| [live-integration.md](testing/live-integration.md) | 真实环境集成测试 |
| [browser-e2e.md](testing/browser-e2e.md) | 浏览器端到端验证 |

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
