# 部署架构

> 本文档以代码为准重写，只描述仓库中实际存在的启动脚本与配置。**仓库未提供 Docker/K8s 部署清单**，容器化部署仅给出参考架构说明。

## 1. 部署形态总览

```mermaid
graph TB
    subgraph "单机 all-in-one（run.sh）"
        CPP["forensic_analyzer<br/>HTTP_SERVER_PORT（.env 示例值 8666）<br/>未设置时 tracelens_env.sh 回退 8080"]
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

受控现场/隔离网段另有第四种形态：**野外（field）单机部署**（强制认证、仅 loopback 后端、禁出网、systemd 托管，资产在 `deploy/field/`），见 §10。

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
2. **加载 .env**：经 `scripts/lib/tracelens_env.sh` 的 `tracelens_load_env()` 解析式加载（逐行拆 `KEY=VALUE`，不经 source/eval；跳过注释/空行/非赋值行），详见 ServiceRunbook.md §2
3. **端口**：`run.sh:78-80` 直接取 `CPP_PORT="$HTTP_SERVER_PORT"`、`PYTHON_PORT="$PYTHON_HTTP_PORT"`、`CS_PORT="$CS_PORT"`（**无内联兜底**）；缺省回退统一在 `scripts/lib/tracelens_env.sh:37-44`——`HTTP_SERVER_PORT:=8080`、`PYTHON_HTTP_PORT:=8090`、`CS_PORT:=8091`。**8666 只是 `.env.example:185`（及 `deploy/field/` 各 env 样例）的模板示例值，不是代码兜底**。启动前清理占用端口的残留进程
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
| C++ forensic_analyzer | httpserver 硬依赖 | `CPP_BACKEND_URL=http://localhost:8666`（`.env.example:173`；未设时 `tracelens_env.sh:46` 按 `HTTP_SERVER_HOST:HTTP_SERVER_PORT` 推导）、`CPP_STARTUP_REQUEST_TIMEOUT=5`、`CPP_RECOVERY_TIMEOUT=8` | readiness=false，服务仍启动（降级） |
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

## 10. 野外（field）单机部署（deploy/field/）

> 适用：受控现场、隔离网段的单机形态。与 §3 工作台形态的本质区别：**强制认证（fail-closed）、后端只绑 loopback、出网默认禁用、systemd 托管、可选 release 冻结布局**。三服务只启动 C++（8666）+ Python（8090）两个，**8091 C/S 不随 field unit 启动**。

### 10.1 资产清单（deploy/field/，逐文件核实）

| 文件 | 作用 |
|------|------|
| `field.env.example` | 基础现场 profile 环境样例（复制到 `/etc/tracelens/field.env`，0600，替换 `REPLACE_*` 后用） |
| `field-release-local.env.example` | 6C release 冻结布局 profile：本机 loopback 入口 |
| `field-release-lan.env.example` | 6C release 冻结布局 profile：经审批的 HTTPS LAN 网关 |
| `tracelens-field-cpp.service.example` / `tracelens-field-python.service.example` | 基础 profile 的 systemd unit 模板（安全加固：`ProtectSystem=strict`、`IPAddressAllow=localhost`、`UnsetEnvironment=FIELD_JWT_SECRET FIELD_USER_FILE` 等） |
| `tracelens-field-6c-cpp.service.example` / `tracelens-field-6c-python.service.example` | 6C release 布局的 unit 模板（工作目录在 `/opt/tracelens/releases/<RELEASE_ID>/`，多 `TRACELENS_REQUIRE_RELEASE_LAYOUT=1`） |
| `nginx-field.conf.example` | HTTPS LAN 网关样例：443 监听，`/python/` → 127.0.0.1:8090，其余 → 127.0.0.1:8666；清空 `X-User`/`X-Forwarded-User`/服务令牌头 |
| `nginx-field-local.conf.example` | 本机 same-origin 网关样例：仅监听 127.0.0.1:8668 |
| `nginx-local-no-login.conf.example` | 临时单操作员本机 UI：`/_local/session` 自动建短期会话、登录表单不显示（语义与边界见 `docs/local-no-login-mode.md`） |
| `python-linux-cp310-x86_64.lock` | hash 锁定的离线 Python 依赖清单（目标 CPython 3.10.12 / Ubuntu 22.04 x86_64，`--no-index --require-hashes` 安装） |
| `python-linux-cp310-x86_64.material.json` | 上述 wheelhouse 逐包清单：版本/sha256/许可证表达式/用途角色（验收审计用） |

### 10.2 认证模型（独立签发方，不复用 C/S 的 JWT）

- 开关：`TRACELENS_FIELD_AUTH=enabled`；`TRACELENS_REQUIRE_FIELD_AUTH=1` 时未启用**拒绝启动**——Python 侧 `load_policy()` 直接抛 `FieldConfigurationError`（`python_service/httpserver/services/field_security.py:97-101`），C++ 侧 `field_runtime_ready()` 自检失败（`src/network/HTTPServer/FieldApp.cpp:91-120`）。这是 fail-closed 的第一层：认证配置坏了就拒绝变成匿名服务。
- **三个互不相同的密钥**（各 ≥32 字节、非 `REPLACE_` 占位符、字符多样性校验）：`FIELD_JWT_SECRET`（用户 JWT：HS256，签发方 `tracelens-field`，aud `tracelens-api`，**有效期 900 秒**）、`FIELD_CPP_TO_PYTHON_TOKEN`（C++→Python 服务令牌）、`FIELD_PYTHON_TO_CPP_TOKEN`（Python→C++）。
- 用户文件 `FIELD_USER_FILE`：必须绝对路径、普通文件、非符号链接、**owner-only 权限**（`field_security.py:71-76`）。格式 `{"users": {"<用户名>": {"password_hash": "<bcrypt>", "active": true, "role": "viewer|analyst|reviewer|admin", "token_version": 0}}}`；登录对未知用户也校验一个备用 bcrypt 哈希，避免用户名存在性时序侧信道（`field_security.py:157-175`）；**吊销已签发令牌 = 改大 `token_version`**。
- 角色权限（`field_security.py:31-36, 199-206`）：viewer=read；analyst=+write；reviewer=+review（`/review`、`/accept`、`/reject`、`/publish`、证据判定写操作）；admin=+admin（DELETE 与 `/delete`、`/export`、`/download`、`/cleanup` 路径）。
- 身份只来自签发方校验，**不读 `X-User`/`X-Forwarded-User` 等请求头**（nginx 样例也在网关层把这些头清空，双保险）。

### 10.3 fail-closed 请求链与端点

- **Python 侧**（8090）：`httpserver/main.py` 全局中间件 `field_authentication` 放行 `/health/live`、`/api/field-auth/login`、`/api/field-auth/introspect` 三个豁免路径，其余一律要求用户 Bearer 或 loopback 服务令牌（scope 白名单：`/health`、`/api/graphiti/*`、`/api/llm/file-analysis/record`）。
- **C++ 侧**（8666）：`FieldApp` 中间件（`src/network/HTTPServer/FieldApp.cpp`）对 `/api`、`/tasks`、`/python/`、`/cs/`、`/cs-disabled/` 前缀强制认证。C++ **不自行验签**：把 Bearer 转发 `POST /api/field-auth/introspect` 问 Python（`FIELD_AUTH_URL` 只接受 `http://127.0.0.1:<port>`；连接 1s/读 2s 超时），**认证服务不可达 → 503 拒绝业务请求**（fail-closed，而非放行）。服务令牌仅接受 loopback 来源 + `FIELD_PYTHON_TO_CPP_TOKEN` 常数时间比对，且限白名单（`python_service_scope`：如 `GET /api/tasks*`、`GET /api/forensics/*`、`POST /api/forensics/extract`）。
- 端点（挂载于 8090，`httpserver/routes/field_auth.py`）：

| 端点 | 作用 |
|------|------|
| `GET /api/field-auth/status` | 自报策略状态：field_security 版本、`release_id`、`source_tree_sha256`、认证是否启用、出网策略 |
| `POST /api/field-auth/login` | 用户名+口令 → 短期 JWT（900s）+ principal（id/role） |
| `GET /api/field-auth/me` | 当前用户 id/role（需用户令牌） |
| `POST /api/field-auth/introspect` | C++ 每请求调用的验签端点（仅内部服务令牌 + loopback） |

- 前端：构建时 `VITE_FIELD_AUTH=enabled` 让页面启用登录页与 Bearer 附加（`web/src/config/runtime.js:6`，`api.js` 按 `FIELD_AUTH_ENABLED` 取 field token）。

### 10.4 出网策略与启动自检

- `FIELD_OUTBOUND_POLICY=disabled`（两个 env 样例的默认值）：`/oss`、`/graphiti`、`/embedding`、`/api/graphiti`、`/api/llm/` 一律 **503**（C++ `optional_outbound_blocked`、Python 中间件同规则）——现场 AI/云上传默认关死。
- `local_only`：必须显式给 `FIELD_MODEL_ORIGINS`（**只允许数字 loopback HTTP origin**，如 `http://127.0.0.1:1234`；域名因可重绑定被拒绝），且 `.env` 已配置的 `LLM_BASE_URL`/`LLM_TEXT_BASE_URL`/`LLM_VISION_BASE_URL`/`EMBEDDING_BASE_URL` 逐一在列，`GRAPHITI_USE_LOCAL_LLM` 不得关闭（`field_security.py:125-143`）。
- 两个形态都**禁止设置六个代理环境变量**（`HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY` 及小写），任一非空即拒绝启动。

### 10.5 部署步骤（以实际资产为准）

**A. 基础 profile**（工作目录 `/opt/tracelens`，unit `tracelens-field-{cpp,python}.service`）：

1. 专用用户与数据目录：`useradd -r tracelens`；`mkdir -p /srv/tracelens-field/data && chown tracelens: /srv/tracelens-field/data`（unit `ReadWritePaths` 指向它，`ProtectSystem=strict` 下唯一可写点）；
2. `cp deploy/field/field.env.example /etc/tracelens/field.env && chmod 0600`，替换三个 `REPLACE_*` 令牌（JWT 密钥 + 两方向服务令牌，三者互不相同）；生成 owner-only 用户文件 `FIELD_USER_FILE` 指向的 JSON（bcrypt 哈希：`python_service/.venv/bin/python -c "from passlib.context import CryptContext; print(CryptContext(schemes=['bcrypt']).hash('<口令>'))"`）；
3. 前端按现场入口构建：`cd web && VITE_FIELD_AUTH=enabled VITE_PYTHON_API_URL=/python VITE_FIELD_RELEASE_BUILD=1 npm run build`。前两个变量的口径来自 `nginx-field.conf.example` 头注释（该注释只列 `VITE_FIELD_AUTH=enabled VITE_PYTHON_API_URL=/python`，`:3`）；`VITE_FIELD_RELEASE_BUILD=1` **关闭 sourcemap** 的依据是 `web/vite.config.js:101`（`sourcemap: env.VITE_FIELD_RELEASE_BUILD === '1' ? false : true`），nginx 头注释并不涉及它；
4. unit 安装：复制两份 `.service.example` 到 `/etc/systemd/system/`（去后缀），`systemctl daemon-reload && systemctl enable --now tracelens-field-cpp tracelens-field-python`（python unit 声明 `After=tracelens-field-cpp.service`）；
5. 网关按需三选一（§10.1 nginx 样例）；确认 `HTTP_SERVER_HOST`/`PYTHON_HTTP_HOST` 均为 `127.0.0.1`，`ss -ltn` 验证 8666/8090 未暴露到外卡。

**B. 6C release 冻结布局 profile**（`/opt/tracelens/releases/<RELEASE_ID>/`，unit `tracelens-field-6c-{cpp,python}.service`）：env 换 `field-release-local.env.example`（loopback）或 `field-release-lan.env.example`（审批 HTTPS 域名），其余同 A。差异点：

- `TRACELENS_REQUIRE_RELEASE_LAYOUT=1` 启动自检加验（C++ `FieldApp.cpp:97-105`）：`TRACELENS_RELEASE_ROOT`/`TRACELENS_PYTHON_BIN` 为绝对路径且真实存在，release 内 `scripts/android_container_pipeline_cli.py`、`scripts/android_image_reader_bridge.py` 齐备；
- Python 侧加验发布身份（`httpserver/main.py:118-127`）：`httpserver/release_info.py` 必须已被发布流程替换（`RELEASE_ID != "UNFROZEN_WORKTREE"` 且与 `TRACELENS_RELEASE_ID` 一致，`TRACELENS_RELEASE_ROOT` 解析到运行中模块的上两级）——**直接拿仓库工作树套 6C profile 会启动失败，属有意设计**（防止"未冻结"身份冒充 release）；
- 离线 Python 依赖按 `python-linux-cp310-x86_64.lock`（文件头注释：目标 CPython 3.10.12，`pip install --no-index --require-hashes`）配 wheelhouse；逐包来源与许可证见 `.material.json`。

### 10.6 验证与失败排查

```bash
systemctl status tracelens-field-cpp tracelens-field-python
curl -s http://127.0.0.1:8090/api/field-auth/status | python3 -m json.tool
#   期望 field_auth:true、required_auth:true、release_id 非 UNFROZEN_WORKTREE（6C）
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8666/api/tasks/list   # 期望 401（无 Bearer 拒绝）
curl -s -X POST http://127.0.0.1:8090/api/field-auth/login \
     -H 'Content-Type: application/json' -d '{"username":"<u>","password":"<p>"}'  # 得 access_token
# 带 token 复测业务接口；ss -ltn | grep -E '8666|8090|8091'  →  仅 loopback，8091 无监听
```

失败排查：
- **启动即退**：日志见 `FieldConfigurationError`/`RuntimeError`——密钥过弱/重复、`FIELD_USER_FILE` 权限不是 0600、代理变量未清、6C 布局校验不过，按报错键名对号；
- **业务接口全部 503 `field authentication unavailable`**：C++ fail-closed 触发——Python 认证服务没起来、`FIELD_AUTH_URL` 不是 loopback 形式、或 `FIELD_CPP_TO_PYTHON_TOKEN` 两端不一致；
- **401**：Bearer 缺失/过期（900 秒）或用户 `token_version` 已被吊销；`POST /login` 恒 401 → 核对 users.json 的 `active`/`role` 与 bcrypt 哈希；
- **503 `optional intelligence services disabled`**：`FIELD_OUTBOUND_POLICY=disabled` 下的预期行为，不是故障；要本机 LLM 才切 `local_only` 并配 `FIELD_MODEL_ORIGINS`。

---

## 相关文档

- **[架构总览](./Overview.md)** - 三服务 + 代理架构
- **[数据流架构](./DataFlow.md)** - 各服务间的数据流
- **[安全设计](./Security.md)** - 端口暴露与凭据管理

---


## 四套部署拓扑对比与选择树

| 维度 | A 单机 all-in-one | B 单机分进程（默认 run.sh） | C 分布式 C/S | D 野外单机（§10） |
|------|------------------|---------------------------|--------------|------------------|
| 适用 | 个人分析工作站 | 小团队内网共享一台工作站 | 多取证机集中管理 | 受控现场/隔离网段单机 |
| 认证 | 无（靠隔离） | 无（靠隔离） | JWT+组织 | 强制 field 认证（fail-closed，900s JWT） |
| 数据 | 本机 data/ | 本机 data/ | PG+agent 本地产物上传登记 | `/srv/tracelens-field/data`（只绑 loopback） |
| 出网 | 可选依赖自定 | 可选依赖自定 | 按需 | 默认全禁（`FIELD_OUTBOUND_POLICY=disabled`） |
| 前置 | setup.sh 全套 | +Node/Neo4j/Redis | +PG+每机编译 agent | deploy/field 资产+systemd+（6C）冻结 release |
| 运维成本 | 低 | 中（Monitoring 三通道） | 高（升级/迁移手册） | 中（认证配置一次性，升级走 release 换版） |

选择树：只有一个人用→A；多人同时用/要图谱报告→B；取证机分散多地→C（可 B+C 共存，端口天然分离）；现场/涉密网段单机→D（基于 B 的双服务子集，后端仅 loopback）。
**最后更新**: 2026-11-10（新增 §10 野外单机部署，deploy/field/ 资产逐文件核实；勘误端口兜底方向——run.sh:78 直接取 HTTP_SERVER_PORT，未设置时经 scripts/lib/tracelens_env.sh:38 回退 8080，8666 仅为 .env.example:185 模板示例值）
