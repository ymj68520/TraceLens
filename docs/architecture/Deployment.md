# 部署架构

> 本文档以代码为准重写，只描述仓库中实际存在的启动脚本与配置。**仓库未提供 Docker/K8s 部署清单**，容器化部署仅给出参考架构说明。

## 1. 部署形态总览

```mermaid
graph TB
    subgraph "单机 all-in-one（run.sh）"
        CPP["forensic_analyzer<br/>:8080（.env HTTP_SERVER_PORT）<br/>run.sh 未设置时回退 8666"]
        PY["httpserver :8090"]
        CS["server :8091"]
        WEB["web/dist 由 C++ 托管"]
    end

    subgraph "外部依赖（可选/分级）"
        NEO4J[("Neo4j 7687")]
        REDIS[("Redis 6379（可选）")]
        LLM["LLM 端点<br/>LLM_BASE_URL"]
        PG[("PostgreSQL 5432<br/>C/S 必需")]
    end

    subgraph "分布式取证机"
        AGENT["tracelens_agent"]
    end

    CPP --- PY
    PY --> NEO4J
    PY --> REDIS
    PY --> LLM
    CS --> PG
    AGENT -->|JWT 轮询| CS

    style CPP fill:#c8e6c9
    style PY fill:#ffccbc
    style CS fill:#f3e5f5
    style AGENT fill:#e8f5e9
```

依赖分级（`httpserver` 启动逻辑）：**C++ 后端为硬依赖**（不可达时 readiness=false，但服务仍启动，进入降级）；**Neo4j / LLM / Redis 为可选依赖**。

---

## 2. 环境准备（setup.sh）

`setup.sh` 按 8 步安装依赖（步骤编号来自脚本注释）：

| 步骤 | 内容 |
|------|------|
| Step 0 | NVM + Node.js（LTS，npm 10+） |
| Step 1 | apt 系统包 |
| Step 2 | Java 21 + Neo4j |
| Step 3 | The Sleuth Kit 4.14.0（源码编译） |
| Step 4 | Crow 框架（源码安装） |
| Step 5 | Google Test |
| Step 6 | 阿里云 OSS C++ SDK（`libs/aliyun-oss-cpp-sdk`） |
| Step 7 | Python venv + 双 requirements（`python_service/requirements.txt` 与 `httpserver/requirements.txt`）+ 大包 + BitLocker FVEK volatility 插件（`scripts/bitlocker_fvek_decrypt.py`） |
| Step 8 | CMake Release 构建 |

## 3. 单机 all-in-one（推荐）

```bash
cp .env.example .env   # 按需修改端口/密码
./run.sh               # 编译 C++ + 构建前端 + 启动三服务（前台）
```

`run.sh` 行为（逐条对应脚本）：

1. **编译**：CMake Release 构建 `build/forensic_analyzer`（`BUILD_WEB_FRONTEND=OFF`，前端由脚本单独 npm 构建，避免 CMake 全量触发 npm 占满 CPU）；随后 `npm run build` 并把 `web/dist` 同步到 `build/web/dist`（C++ 从二进制相对路径 `web/dist` 托管前端）
2. **加载 .env**：过滤 `PYTHON_CORS_ORIGINS`（C++ dotenv 解析不了 JSON 值）与空 `PROJECT_ROOT` 后 source
3. **端口**：`CPP_PORT="${HTTP_SERVER_PORT:-8666}"`、`PYTHON_PORT="${PYTHON_HTTP_PORT:-8090}"`、`CS_PORT="${CS_PORT:-8091}"`；启动前清理占用端口的残留进程
4. **健康检查**：C++ 检查 `http://localhost:<port>/api/system/health`（**硬失败**，失败即退出）；Python 检查 `:8090/health`、C/S 检查 `:8091/health`（**软失败**，仅告警不阻断）
5. **日志**：`build/logs/cpp_server.log`、`build/logs/python_service.log`、`build/logs/cs_server.log`
6. `Ctrl+C` 停止全部服务（trap 清理子进程）

常用参数：`--build-only`、`--no-build`、`--no-web`、`--no-python`、`--no-cpp`、`--jobs N`、`--clean`。

## 4. 手动启动

```bash
# C++ 服务（默认端口 8080）
cd build && ./forensic_analyzer --http-server 8080

# Python httpserver（8090）
cd python_service
PYTHONPATH=. .venv/bin/python -m httpserver.main

# 分布式 C/S server（8091，需要 PostgreSQL）
cd python_service
PORT=8091 PYTHONPATH=. .venv/bin/python -m server.main
```

也可用 Makefile：`make build` / `make start`（= `start-all`，执行 `scripts/start_all_services.sh`）/ `make cpp` / `make python` / `make web`（web-dev）/ `make test*` / `make acceptance-*`（smoke/task/analyst/restart/matrix）。另有 `scripts/diagnose_services.sh` 诊断。

## 5. 前端开发模式

```bash
cd web && npm install && npm run dev   # Vite dev 端口 3000（web/vite.config.js）
```

代理规则（`web/vite.config.js`）：`/csapi` → 8091（去前缀）；`/tasks` → C++（`VITE_CPP_PROXY_TARGET` 或 `HTTP_SERVER_PORT`，默认 8080）；`/api/reports`、`/api/graphiti`、`/api/llm`、`/api/office`、`/api/db`、`/api/wechat`、`/api/investigation` → 8090；其余 `/api` → C++。生产模式无需 Node，前端由 C++ 从 `web/dist` 托管。

## 6. 分布式 C/S 部署（server + agent + PostgreSQL）

```mermaid
graph LR
    subgraph "服务端机器"
        SRV["server :8091<br/>PORT / JWT_SECRET_KEY / DATABASE_URL"]
        PG[("PostgreSQL<br/>tracelens 库")]
        SRV --> PG
    end
    subgraph "取证机（可多台）"
        AG["tracelens_agent<br/>（src/http_agent 独立 CMake 目标）"]
        FA["forensic_analyzer<br/>本地分析"]
        AG --> FA
    end
    AG -->|"注册令牌 → JWT (HS256)<br/>轮询 /api/commands<br/>上传结果/索引"| SRV
```

步骤：

1. 准备 PostgreSQL 并设置 `DATABASE_URL`（如 `postgresql://postgres:***@localhost:5432/tracelens`），应用 `migrations/postgresql/` 下 3 个迁移。**注意**：服务端启动时的自动迁移只应用 `001`；`002`（命令-任务外键回填）和 `003`（修复 super_admin 种子凭据）需要已有环境手工执行 `psql -f`——不应用 003 时内置 super_admin 登录会恒 401（见 [server/Main](../modules/python/server/Main.md) 注意事项）
2. 启动 `server`（`:8091`），通过 `/api/auth`、`/api/organizations` 创建组织/用户、生成客户端注册令牌（`registration_tokens` 表）
3. 取证机上编译并运行 `tracelens_agent`（`--once` 可单轮轮询后退出，见 `http_agent_main.cpp`），配置服务端地址与注册令牌；代理本地调用 `forensic_analyzer` 执行分析并上传结果/索引

相关 `.env` 变量：`PORT=8091`、`JWT_SECRET_KEY`、`JWT_ALGORITHM=HS256`、`DATABASE_URL`、`DB_CONNECT_TIMEOUT`、`DB_POOL_TIMEOUT`、`DB_STARTUP_TIMEOUT`。

## 7. 外部依赖部署

| 依赖 | 用途 | 配置 | 缺失影响 |
|------|------|------|---------|
| Neo4j 5 | Graphiti 知识图谱后端 | `NEO4J_URI=neo4j://127.0.0.1:7687`、`NEO4J_USER/NEO4J_PASSWORD`（setup.sh Step 2 安装） | 图谱摄取/查询不可用（可选依赖） |
| Redis | 摄取任务持久化队列 | `REDIS_URL=redis://localhost:6379` | 回退到内存队列（可选依赖） |
| OpenAI 兼容 LLM | 文件/工件/事件/图谱分析 | `LLM_BASE_URL`（默认 `http://192.168.31.170:1234`）、`LLM_TEXT_MODEL`、`LLM_VISION_*`、`LLM_TIMEOUT_SECONDS` 等 | LLM 相关功能降级（可选依赖） |
| MCP 服务器 | LLM 工具协议 | `MCP_SERVER_PORT=8890`、`MCP_SERVER_HOST`、`MCP_ALLOWED_PATHS` | MCP 集成不可用 |
| C++ forensic_analyzer | httpserver 硬依赖 | `CPP_BACKEND_URL=http://localhost:8080`、`CPP_STARTUP_REQUEST_TIMEOUT=5`、`CPP_RECOVERY_TIMEOUT=8` | readiness=false，服务仍启动（降级） |
| PostgreSQL | C/S server 必需 | `DATABASE_URL` | server 无法工作 |

## 8. 日志与健康检查

| 服务 | 日志 | 健康检查端点 |
|------|------|-------------|
| C++ | `build/logs/cpp_server.log`；应用日志 `LOG_FILE=forensics.log`（`LOG_LEVEL`） | `GET /api/system/health`（run.sh 用作硬检查） |
| httpserver | `build/logs/python_service.log` | `GET /health`、`GET /health/live`、`GET /health/ready`（`routes/health.py`，ready 含依赖分级状态） |
| server | `build/logs/cs_server.log` | `GET /health` |

API 文档：C++ `http://localhost:<port>/api/docs`；Python 服务 `http://localhost:8090/docs`、`http://localhost:8091/docs`（FastAPI 自动文档）。

关键运维数据位置：任务数据库 `data/tasks/<task_id>/`、任务列表 `data/tasks.json`、审计日志 `data/audit/forensics_audit.db`（均为二进制/脚本相对路径）。

## 9. 容器化（参考架构，仓库未提供部署清单）

仓库不含 Dockerfile / K8s YAML。若需容器化，参考要点：

- **有状态工作负载**：C++ 分析直接读写本地磁盘（镜像、`data/` 目录、SQLite），适合单 Pod + PVC（证据与输出各自挂卷），不适合多副本共享同一 `data/`
- **httpserver**：无本地强状态（图谱在 Neo4j、队列在 Redis），可水平扩副本，经 `CPP_BACKEND_URL` 指向 C++ 服务
- **server**：依赖 PostgreSQL，无状态可扩副本
- **探针**：直接使用上表健康检查端点（C++ `/api/system/health`、Python `/health/live`、`/health/ready`）
- **密钥**：`NEO4J_PASSWORD`、`JWT_SECRET_KEY`、`DATABASE_URL`、OSS 凭据应走 Secret 注入而非写死镜像（见 Security.md）
- 需在镜像内预装 TSK 4.14.0、Crow 等系统依赖（参见 `setup.sh` 步骤）

---

## 相关文档

- **[架构总览](./Overview.md)** - 三服务 + 代理架构
- **[数据流架构](./DataFlow.md)** - 各服务间的数据流
- **[安全设计](./Security.md)** - 端口暴露与凭据管理

---

**最后更新**: 2026-08-23（以代码为准重写）
