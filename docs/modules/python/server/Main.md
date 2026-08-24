# server 服务入口与基础设施（python_service/server/main.py、config.py、db/、middleware/auth.py、models/）

> **一句话**：装配分布式 C/S 后端的 FastAPI 应用——lifespan 里以 `DB_STARTUP_TIMEOUT=30s` 做有界数据库初始化（失败不退出、liveness 仍活、`/health/ready` 503），叠加 JWT Bearer 依赖与 Pydantic schema 层，是 8091 端口多租户服务端的进程入口。

## 1. 为什么有这个模块

TraceLens 有两种运行形态：**本地模式**（C++ :8666 单机一体，httpserver :8090 做其 LLM/graphiti 代理）与**分布式模式**（本模块，多租户后端 + 远端 tracelens_agent 客户端轮询取证）。分布式形态需要一个与本地栈完全独立的进程：自己的端口（8091）、自己的数据库（PostgreSQL 而非 C++ 产出的 SQLite）、自己的认证模型（多组织 JWT 而非无鉴权代理）。这个模块回答的问题是：**这个新进程如何装配起来，并且在 PostgreSQL 尚未就绪时仍以降级姿态活着**。它本身不含业务逻辑——业务在 `services/`（见 [Services.md](./Services.md)）与 `api/` 路由层。

## 2. 在系统中的位置

- **谁启动它**：`run.sh` 与 httpserver 并行拉起——同一 venv（`python_service/.venv`，两份 requirements 都装进去，run.sh:219-231）、同一仓库根 `.env`，但独立子进程（run.sh:243-249）`exec $PY_EXEC -m server.main`，日志单独落 `build/logs/cs_server.log`，健康检查失败**不阻断** C++/httpserver。也可手动 `python -m server.main`（main.py:196-203，uvicorn 监听 `HOST:PORT`）。
- **谁调用它**：web 前端的 `csApi` axios 客户端（`/csapi` 代理 → 8091，登录/客户端/任务管理）；C++ `tracelens_agent`（src/http_agent/）持 client JWT 轮询 `/api/commands/poll`、上报状态、上传索引与结果工件。
- **它调用谁**：只依赖 PostgreSQL（`DATABASE_URL`）；不调用 C++、Neo4j、LLM——那些是本地栈 httpserver 的职责。
- **与本地栈的共存关系**：config.py:33-39 的注释锁定了端口边界——8090 归 httpserver，8091 归本服务；两者读同一个 `.env` 但字段不相交（为此 `extra="ignore"`，见下）。

## 3. 核心数据结构

**（a）Settings（config.py:19-91）。** 全部运行参数的唯一真相源（模块级 `settings` 单例），关键段：

```python
# server/config.py:38-57（节选）
HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.getenv("PORT", "8091"))

DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/tracelens",
)
# Keep driver, pool checkout, and lifespan budgets independent.  The
# driver timeout must be shorter than DB_STARTUP_TIMEOUT because cancelling
# a worker thread cannot interrupt an in-flight socket operation.
DB_CONNECT_TIMEOUT: int = int(os.getenv("DB_CONNECT_TIMEOUT", "5"))
DB_POOL_TIMEOUT: int = int(os.getenv("DB_POOL_TIMEOUT", "5"))
DB_STARTUP_TIMEOUT: float = float(os.getenv("DB_STARTUP_TIMEOUT", "30"))

JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "change-this-in-production")
JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
USER_TOKEN_EXPIRE_HOURS: int = 1
CLIENT_TOKEN_EXPIRE_DAYS: int = 30
```

`model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")`（:88）——注释解释了 `extra="ignore"` 的必要性：共享 `.env` 带 httpserver 专属变量（GRAPHITI_*/DB_NAME/LOG_LEVEL...），pydantic-settings 对 env_file 来源的未知键会**拒绝启动**（不像 os.environ 会静默忽略）。时间预算三层刻意分离：驱动 5s < 池 5s < 启动 30s，原因见下节。

**（b）clients / command_queue ORM（models/database.py，镜像 001 迁移）。** 协议的两张核心表：

```python
# server/models/database.py:96-120（节选）
class Client(Base):
    """A registered forensic machine that polls for commands."""

    __tablename__ = "clients"
    __table_args__ = (
        UniqueConstraint("org_id", "hostname", name="clients_org_id_hostname_key"),
        CheckConstraint(
            "status IN ('online', 'offline', 'error')", name="clients_status_check"
        ),
        Index("idx_clients_org_status", "org_id", "status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"))
    hostname = Column(String(255), nullable=False)
    registration_token = Column(String(255), unique=True)
    jwt_secret = Column(String(255))
    capabilities = Column(JSONB, default=dict)
    status = Column(String(50), default="offline")
    last_poll = Column(DateTime)
    last_seen = Column(DateTime)
    version = Column(String(50))
    created_at = Column(DateTime, server_default=func.now())
```

逐列：`registration_token` 一次性注册凭据（unique）；`capabilities` JSONB 记录机器能力（供任务分派参考）；`last_poll`（由 poll 路由盖章）与 `last_seen`（由 get_commands_for_client 刷新）双时间戳支撑 60s 在线窗口判定；`(org_id, hostname)` 唯一——同组织不能注册两台同名机器。

```python
# server/models/database.py:199-222（节选）
class CommandQueue(Base):
    """Server-to-client command. Clients poll, claim, and report back."""

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    # Real FK to analysis_tasks (migration 002). Nullable because some commands
    # (health_check, extract_file) are not spawned by an analysis task. The soft
    # link still lives in ``parameters`` JSONB; the orchestrator is wired to set
    # this column in Task 5.
    task_id = Column(
        UUID(as_uuid=True),
        ForeignKey("analysis_tasks.id", ondelete="CASCADE"),
        nullable=True,
    )
    command_type = Column(String(100), nullable=False)  # analyze_disk, extract_file, health_check
    parameters = Column(JSONB, nullable=False)
    priority = Column(String(50), default="normal")
    status = Column(String(50), default="pending")
    ttl = Column(DateTime, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    assigned_at = Column(DateTime)
    completed_at = Column(DateTime)
    result_message = Column(Text)
    retry_count = Column(Integer, default=0)
```

`task_id` 是 002 迁移加的真 FK（ON DELETE CASCADE），`parameters` JSONB 里还保留一份软链接（过渡兼容）；`ttl` 是过期死线（critical 1h、其余默认 24h）；CHECK 约束把 command_type/priority/status 钉死在枚举集内。

## 4. 核心概念与设计

**（a）create_app() 是唯一装配点。** `create_app()`（main.py:103-189）创建 FastAPI 实例后叠加三层横切关注点：CORS（main.py:121-128，来源是 `CORS_ORIGINS` 固定三项 `localhost:5173` / `127.0.0.1:5173` / `localhost:3000`，config.py:60-64——注意与 httpserver 可通配的 CORS 策略不同，这里永远 `allow_credentials=True`，所以不能改成 `["*"]`）；全局 500 处理器（main.py:134-141，只回固定文案 `"Internal server error"`，真实异常进日志——Starlette 自己的 ExceptionMiddleware 先处理 HTTPException/422，所以 401/403/422 不会被它吞掉，见 main.py:130-133 注释）；六个路由模块各自声明前缀后无前缀挂载（main.py:147-152，前缀在各 router 内：`/api/auth`、`/api/organizations`、`/api/clients`、`/api/commands`、`/api/tasks`，其中 results 路由与 tasks 共用 `/api/tasks` 前缀，api/results.py:42）。

**（b）有界、可降级的启动。** lifespan（main.py:79-100）调用 `initialize_database()`，后者用 `asyncio.wait_for(asyncio.to_thread(init_db), timeout=DB_STARTUP_TIMEOUT)`（main.py:55-58）把同步建表包成线程并限时 30s（config.py:51）：

```python
await asyncio.wait_for(
    asyncio.to_thread(init_db),
    timeout=settings.DB_STARTUP_TIMEOUT,
)
# 超时 → _db_available=False, _db_error="database initialization timed out"
# 异常 → _db_available=False, _db_error=type(exc).__name__
```

结果写入模块级 `_db_available` / `_db_error`（main.py:47-48），进程**不退出**。时间预算刻意分层（config.py:46-51）：驱动层 `DB_CONNECT_TIMEOUT=5s`、连接池 `DB_POOL_TIMEOUT=5s`、启动总预算 30s——注释说明了原因：取消 worker 线程无法中断在途 socket 操作，所以必须由更短的驱动超时先兜底，30s 只是外层保险。

**（c）liveness 与 readiness 分离。** `GET /health`（main.py:155-163）永远 200，`status` 恒为 `healthy`，仅附带 `database: "available"|"degraded"` 快照；`GET /health/ready`（main.py:165-177）在 DB 不可用时返回 **503** 并携带 `_db_error`：

```python
if _db_available:
    return {"ready": True, "database": "available"}
return JSONResponse(
    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    content={"ready": False, "database": "unavailable", "error": _db_error},
)
```

这让编排器（如 run.sh 的 check_service 打 `/health`）能区分"进程活着"与"依赖就绪"。

**（d）数据库会话与惰性包初始化。** `session.py:18-32` 构建引擎：QueuePool（10 连接 + 20 溢出）、`pool_pre_ping=True`（防 stale 连接）、PostgreSQL URL 时注入驱动级 `connect_timeout`；导入本模块**不开连接**（docstring session.py:5-6）。`get_db()`（session.py:46-52）是请求级 session 依赖；`init_db()`（session.py:55-70）导入全部 ORM 模型后 `create_all`（幂等，只补缺表）。`db/__init__.py:50-58` 用 PEP 562 `__getattr__` 惰性再导出模型，规避 `server.db → server.models.database → server.db.session` 的包级循环导入。

**（e）迁移：001 是规范路径，002/003 靠手工。** `db/init_db.py` 是 CLI（`python -m server.db.init_db --migrate --init --seed`，init_db.py:6）：

- `--migrate`（init_db.py:122-132）在单事务里应用 **仅 001_initial_schema.sql**（路径按仓库根相对解析，init_db.py:42-56）——10 张表（organizations/users/clients/disk_images/command_queue/analysis_tasks/analysis_results/llm_analysis/task_history/registration_tokens）+ 6 个性能索引 + 默认组织与 super_admin 种子；
- `002_command_task_fk.sql`：把 `command_queue.parameters->>'task_id'` 软链接升级为真 FK（ON DELETE CASCADE）并回填旧行、建 `idx_command_queue_task`；
- `003_fix_super_admin_seed_credentials.sql`：修复 001 的坏种子——001 里 super_admin 的 bcrypt 哈希无法验证文档口令 `admin123`（登录恒 401），且 `super_admin@tracelens.local` 的 `.local` 保留 TLD 被 Pydantic EmailStr 拒绝（/api/auth/me 序列化 500）。003 只改仍是坏值的行（非破坏性、幂等）。

注意：`run_migrations()` **不会**应用 002/003——仓库里没有任何脚本或代码遍历 `migrations/postgresql/`，这两个文件只能手工 `psql -f` 应用（详见第 8 节）。

**（f）JWT Bearer 依赖层。** `middleware/auth.py` 提供三个 FastAPI 依赖（不是 ASGI 中间件，靠 `Depends` 挂进路由）：`get_current_user`（auth.py:29-74）、`get_current_client`（auth.py:77-121）、`get_optional_user`（auth.py:124-141）。两类 token 靠 payload 里的 `type` 声明**严格互斥**——client token 打 user 路由（或反之）返回 401（auth.py:59-64、106-111）：

```python
# server/middleware/auth.py:52-64（get_current_user 的类型门）
payload = verify_token(token)

if payload is None:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

if payload.get("type") != "user":
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="User token required",
        headers={"WWW-Authenticate": "Bearer"},
    )
```

验签与 ORM 回查委托给 `services/auth_service`（见 [Services.md](./Services.md)）。`require_permission()`（auth.py:144-164）目前是**存根**：super_admin 直通，其余只查"已认证"，真正的 RBAC 还是 TODO（auth.py:160-161）——组织隔离实际由路由层比较 `org_id` 实现。

**（g）models/：忠实镜像 + 保留名映射。** `models/database.py` 的 10 个 ORM 模型逐列镜像 001 的 CHECK/UNIQUE/FK/索引（database.py:9-21 注释）。两个易踩的点：多张表有名为 `metadata` 的数据库列，而 `metadata` 是 SQLAlchemy 声明类的保留属性，故映射为 `image_metadata` / `task_metadata` / `result_metadata`（database.py:152-153、279-280、327-328）；`AnalysisTask.commands` 用 `passive_deletes=True`（database.py:292-301），否则 unit of work 会先把子命令的 `task_id` UPDATE 成 NULL，让 002 的 DB 级联永远不触发。`models/schemas.py` 是 Pydantic 请求/响应层（`from_attributes=True` 直接吃 ORM 对象，schemas.py:29-37），字段名沿用上述 `*_metadata` 属性名，约束如 `ttl_hours: 1..168`（schemas.py:174）、密码 ≥8 字符、role 正则白名单（schemas.py:59）。

## 5. env 全表（本进程消费的变量）

| env | 默认 | 说明 |
|---|---|---|
| `HOST` / `PORT` | 0.0.0.0 / **8091** | 8090 归 httpserver，勿混用 |
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/tracelens` | 唯一外部依赖 |
| `DB_CONNECT_TIMEOUT` / `DB_POOL_TIMEOUT` / `DB_STARTUP_TIMEOUT` | 5 / 5 / 30 | 三层时间预算 |
| `JWT_SECRET_KEY` / `JWT_ALGORITHM` | `change-this-in-production` / HS256 | **必须**在生产覆盖密钥 |
| `USER_TOKEN_EXPIRE_HOURS` / `CLIENT_TOKEN_EXPIRE_DAYS` | 1 / 30 | 两类 token 时效 |
| `CORS_ORIGINS` | 固定三项 | 带 credentials，不能 `*` |
| `ENVIRONMENT` | development | 日志级别/热重载开关 |
| 其余 httpserver 变量（GRAPHITI_*/NEO4J_*/REDIS_URL/LLM_* 等） | — | 经 `extra="ignore"` 被无视 |

## 6. 工作流程走读：一次冷启动

`run.sh` 编译 C++、起 :8666 与 :8090 后，在 `python_service/` 里 `PORT=8091 python -m server.main` → `app = create_app()`（模块级实例，main.py:193）。装配顺序：CORS → 全局异常处理器 → 六个 router → `/health`、`/health/ready`、`/`。

uvicorn 监听后触发 lifespan：`initialize_database()` 在线程里执行 `init_db()`——导入 10 个模型注册到 `Base.metadata`，`create_all` 补缺表。PostgreSQL 正常则 `_db_available=True`，`/health/ready` 就绪；DB 不在/超 30s 则进程照常服务，`/health` 报 `degraded`、`/health/ready` 503，登录等一切碰 DB 的端点开始报错，但 liveness 探针永远通过。

生产首次部署的完整路径是手工三步：`--migrate`（001）→ 手工 `psql -f` 002/003 → `--seed`（幂等：默认组织 + super_admin，口令 bcrypt 哈希化，init_db.py:96-119）。日常开发若不想跑 SQL 迁移，`create_all` 也能建出等价 schema（ORM 已带全约束），只是没有种子数据。

## 7. 与其他模块的协作

| 协作方 | 关系 |
|---|---|
| `server/services/` | 路由层调用的业务四件套（auth/command_queue/task_orchestrator/result_aggregator），见 [Services.md](./Services.md) |
| `server/api/` | 六个路由模块自带前缀，`create_app` 只做 include；`get_db` 是它们的公共 session 依赖 |
| httpserver（:8090） | 同 venv、同 `.env`（`extra="ignore"` 兼容 httpserver 专属变量 GRAPHITI_*/DB_NAME 等，config.py:81-88，缺了它共享 .env 存在时服务起不来）；端口/数据库/认证模型完全独立 |
| tracelens_agent（src/http_agent/） | 轮询客户端：JWT 轮询 `/api/commands/poll`、本地跑 forensic_analyzer 子进程、经 result_uploader/index_uploader/status_reporter 回传 |
| migrations/postgresql/ | 001 由 `--migrate` 应用；002/003 手工应用；ORM metadata 与之保持逐列一致 |

## 8. 注意事项与已知问题

- **002/003 迁移没有自动化应用路径**：`run_migrations()` 只认 001（init_db.py:45-52 的候选列表里写死了文件名）。已有 001 环境升级时必须手工执行 002/003，否则 `command_queue.task_id` FK 不存在、super_admin 仍是坏种子（登录 401）。三个迁移本身都幂等，可安全重放。
- **`/health/ready` 是启动快照不是活性探测**：`_db_available` 只在 lifespan 初始化时写入，DB 中途挂掉后 `/health` 仍显示 available，直到进程重启。
- **CORS 固定三源**且 `allow_credentials=True`：部署前端到其他域名需改 `CORS_ORIGINS`，且不能写 `*`（与凭据互斥）。
- **`require_permission` 是存根**：细粒度权限检查未实现，越权防护依赖路由层的 org_id 比较；新增管理端点时要自己补 scope 检查。
- **JWT_SECRET_KEY 默认值是 `change-this-in-production`**（config.py:54）：不设环境变量等于公开签名密钥。
- `--drop` 会交互确认后删全表（init_db.py:147-154）；`--seed` 的 super_admin 口令是 `admin123`，两处都标注 CHANGE IN PRODUCTION。

## 9. 如何验证与扩展

- 应用装配/健康端点/CORS/异常脱敏：`python_service/tests/test_main_app.py`（TestClient 故意不进 `with` 块以跳过 lifespan，避免测试碰 PostgreSQL）。
- 端口与双栈区分：`tests/test_config_port.py`；JWT 算法/中间件类型互斥：`tests/test_auth_algorithm.py`、`tests/test_auth_middleware.py`。
- FK/级联等需要真库的测试走 `conftest.py` 的 `db_session` fixture——自建引擎绑 `TEST_DATABASE_URL`（默认 `postgresql://postgres:postgres@localhost:5432/tracelens_test`），每测试 `create_all`/`drop_all`，不跑 SQL 迁移文件。
- 手工验证：`./run.sh` 后访问 `http://localhost:8091/docs`（Swagger）与 `http://localhost:8091/health/ready`；停掉 PostgreSQL 再起服务可观察降级路径。
- 新增一组路由：`server/api/` 建模块（自带 `prefix="/api/xxx"`）→ 在 `create_app` 加一行 `include_router` → schema 进 `models/schemas.py`，表进 `models/database.py` 并同步补 SQL 迁移。

相关阅读：[Services.md](./Services.md)（services 四件套）、[httpserver/Main.md](../httpserver/Main.md)（本地栈对照）、`docs/architecture/DatabaseSchema.md` 第 9 节（C/S PostgreSQL ER 图）、`docs/superpowers/plans/2026-07-27-cs-integration-hardening.md`（双栈端口责任表）。

## 10. 二轮深化 A：端点全表（28 个，源码核对，含认证类型）

**auth（3 个）**

| 方法 | 路径 | 认证 | 说明 |
|---|---|---|---|
| POST | /api/auth/login | 无（OAuth2PasswordRequestForm，**form-encoded**） | 用户名或邮箱登录 |
| POST | /api/auth/refresh | user token | 滑移续期 |
| GET | /api/auth/me | user token | 当前用户（EmailStr 序列化） |

**organizations（6 个，全 user token）**：POST/GET `/api/organizations`、GET `/{org_id}`、POST/GET `/{org_id}/registration-tokens`、DELETE `/registration-tokens/{token_id}`。

**clients（6 个）**

| 方法 | 路径 | 认证 | 说明 |
|---|---|---|---|
| POST | /api/clients/register | 注册 token（body） | 机器注册、发 client JWT |
| GET | /api/clients | user | super_admin 全组织、其余限本组织 |
| GET | /api/clients/{client_id} | user | 详情 |
| DELETE | /api/clients/{client_id} | user | 删除 |
| POST | /api/clients/{client_id}/index-images | **client token** | 触发镜像索引命令 |
| GET | /api/clients/{client_id}/images | user | 已上报镜像列表 |

**commands（6 个）**

| 方法 | 路径 | 认证 | 说明 |
|---|---|---|---|
| POST | /api/commands | user | 下发命令 |
| GET | /api/commands/poll | **client token** | 客户端轮询认领（60s 在线窗口盖章） |
| POST | /api/commands/{id}/status | **client token** | 回报执行状态 |
| GET | /api/commands/{id} | user | 单条查询 |
| GET | /api/commands/client/{client_id} | user | 按机器查队列 |
| POST | /api/commands/expire | user | 手动过期清扫 |

**tasks（4 个，全 user token）**：POST/GET `/api/tasks`、GET `/{task_id}`、POST `/{task_id}/cancel`。
**results（3 个）**：POST `/api/tasks/{task_id}/results`（**client token**，上报）、GET 同路径（user）、GET `/{task_id}/llm-analyses`（user）。

合计 3+6+6+6+4+3 = 28；外加 `/health`、`/health/ready`、`/` 三个框架端点。认证分布规律：**只有 poll/status/results 上报/index-images 四组走 client token（机器动作），其余全部 user token（人操作）**；类型错配一律 401（auth.py:59-64、:106-111 的严格互斥门）。

## 11. 二轮深化 B：两类 JWT 的 payload 契约对照（auth_service.py:66-117）

| claim | user token | client token |
|---|---|---|
| type | `"user"` | `"client"` |
| sub | user id（str(UUID)） | client id |
| exp | now + 1h（USER_TOKEN_EXPIRE_HOURS） | now + 30d（CLIENT_TOKEN_EXPIRE_DAYS） |
| 签发函数 | create_access_token | create_client_token |
| org 归属 | 不在 token（每次查库） | 同 |

两处实现共享同一段"本地时间偏移"注释（:68-70、:102-104）：`expires.timestamp()` 若用 naive 本地时间会被 epoch 偏移坑——代码刻意用带时区的 now。verify_token 只验签与 exp，**不查吊销**——泄露的 client token 在 30 天内一直有效（无黑名单机制，已知的运维风险）。

## 12. 二轮深化 C：ORM 10 表速查（models/database.py ↔ 001 迁移）

| 表 | 关键约束 | 说明 |
|---|---|---|
| organizations | — | 租户根 |
| users | role CHECK 白名单 | super_admin/admin/analyst/viewer 族 |
| clients | UNIQUE(org_id,hostname)、status CHECK(online/offline/error) | 轮询机器 |
| disk_images | image_metadata 保留名映射 | 镜像清单 |
| command_queue | command_type/priority/status CHECK、task_id FK（002） | 命令队列 |
| analysis_tasks | task_metadata | 任务聚合 |
| analysis_results | result_metadata | 结果工件 |
| llm_analysis | — | LLM 结论 |
| task_history | — | 状态流水 |
| registration_tokens | 一次性 | 机器注册凭据 |

保留名映射三处（image_metadata/task_metadata/result_metadata）是"DB 列名 metadata 与 SQLAlchemy 声明类保留属性冲突"的统一解法；schemas.py 的字段名沿用属性名（不是 DB 列名）。

## 13. 二轮深化 D：新走读——login 的双标识查找与 form-encoded 契约（auth.py:38-67）

```python
# api/auth.py:38-67（骨架）
form_data: OAuth2PasswordRequestForm = Depends(),
...
user = session.query(User).filter(
    (User.username == form_data.username) | (User.email == form_data.username)
).first()
if not user or not verify_password(form_data.password, user.password_hash):
    raise HTTPException(status_code=401, detail="Incorrect username or password")
```

逐块解释：① **form-encoded 是硬契约**——OAuth2PasswordRequestForm 只解析 `application/x-www-form-urlencoded`，JSON body 会 422；前端 csAuthService.js:3-11 用 URLSearchParams 正是为此（axios 对其自动设 Content-Type）；② 用户名**或邮箱**都可登录（OR 谓词）——文档化行为，审计日志里 login 标识可能是任一形态；③ 用户不存在与口令错误返回**同一个** 401 文案（不泄露账号存在性）；④ bcrypt 校验在 auth_service.verify_password。前置依赖：003 迁移修好 super_admin 种子之前，这套登录对默认账号恒 401（第 4(e) 节已记录的坑）。

## 14. 二轮深化 E：与 httpserver 入口的装配对照（速查）

| 维度 | server/main.py（:8091） | httpserver/main.py（:8090） |
|---|---|---|
| lifespan 初始化 | init_db（30s 上限，失败降级不退出） | ServiceManager.initialize（30s 上限，同样降级） |
| 降级观测 | /health 的 database 字段 + /health/ready 503 | /health/ready 的 ready 字段（200 语义） |
| CORS | 固定三源 + credentials 恒真 | PYTHON_CORS_ORIGINS 可通配（通配时关 credentials） |
| 500 处理器 | 固定文案（HTTPException/422 由内层先处理） | 同（含 422 结构化处理器） |
| 路由挂载 | 六模块自带前缀 | 19 模块集中分配前缀 |
| env 兼容 | case_sensitive=True + extra="ignore" | case_sensitive=False + extra="ignore" |
| 模块级 app | `app = create_app()`（main.py:193，uvicorn 直引） | 惰性 get_app() 单例 |

**最后更新**: 2026-08-24（二轮深化：补全端点清单与模型契约）
