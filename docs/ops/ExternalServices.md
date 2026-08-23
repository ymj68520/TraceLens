# 外部依赖服务手册（ExternalServices）

> 适用场景：安装/配置/验证 Neo4j、Redis、PostgreSQL、LLM 端点四个外部依赖，理解各自的降级语义与常见坑。
> 前置：所有连接参数集中在仓库根 `.env`（模板 `.env.example`）；安装由 `setup.sh` 统一负责（Neo4j/Redis/Java 由 apt + systemd 管理，PostgreSQL 与 LM Studio 需自备）。

## 速查卡

```bash
# Neo4j
systemctl status neo4j                       # bolt 7687 / http 7474
curl -s http://localhost:8090/health/ready | python3 -m json.tool | grep -A2 neo4j
cypher-shell -u neo4j -p "$NEO4J_PASSWORD" "MATCH (n) RETURN count(n);"   # 数据量

# Redis
redis-cli ping                               # PONG
redis-cli -u "$REDIS_URL" ping               # 带密码的 REDIS_URL
curl -s http://localhost:8090/api/system/redis/status

# PostgreSQL（C/S 8091 用）
pg_isready -h localhost -p 5432 -d tracelens
psql "$DATABASE_URL" -c "\dt"
curl -s http://localhost:8091/health/ready   # 503 = DB 不可用

# LLM 端点（LM Studio 等 OpenAI 兼容服务）
curl -s http://192.168.31.170:1234/v1/models | python3 -m json.tool   # 已加载模型名
curl -s http://localhost:8090/health/ready | python3 -m json.tool | grep -A2 '"llm"'

# Neo4j 全量清空（危险）
cd python_service && .venv/bin/python wipe_neo4j.py
```

## 1. Neo4j（Graphiti 知识图谱后端）

背景：Python httpserver 通过 Graphiti 把 LLM 分析结果写入 Neo4j 图谱。**可选依赖**——连不上时 GraphitiService 自动降级，不影响主分析。

### 1.1 安装与初始密码（来自 setup.sh）

- `setup.sh` Step 2（`setup.sh:307-410`）：装 openjdk-21 → 添加官方源 `https://debian.neo4j.com stable latest`（keyring `/etc/apt/keyrings/neotechnology.gpg`）→ `apt-get install neo4j` → `systemctl enable --now neo4j`。
- **NEO4J_PASSWORD 初始化**：仅当本次是**新装** Neo4j 时，setup.sh 读取环境变量或 `.env` 的 `NEO4J_PASSWORD`，以 neo4j 用户执行 `neo4j-admin dbms set-initial-password`（`setup.sh:379-391`）。`.env` 未设密码时只打警告，需手工初始化。
- 已有实例改密**不走** set-initial-password（那只对新库有效），用：`cypher-shell -u neo4j -p <旧密码> "ALTER CURRENT USER SET PASSWORD FROM '<旧>' TO '<新>';"`，然后同步改 `.env` 的 `NEO4J_PASSWORD` 并重启 Python 服务。

### 1.2 连接配置

`.env`：`NEO4J_URI=neo4j://127.0.0.1:7687`（bolt）、`NEO4J_USER=neo4j`、`NEO4J_PASSWORD=...`；超时 `NEO4J_CONNECT_TIMEOUT=5`、`NEO4J_QUERY_TIMEOUT=5`（`httpserver/config.py:153-154`）。

### 1.3 连接失败 = GraphitiService disabled（降级语义）

`GraphitiService.initialize()`（`python_service/httpserver/services/graphiti_parts/_core.py:21-46`）：
1. 先探测 Neo4j 连接，不可达 → 日志 `Neo4j is not available. Graphiti service will be disabled.` + 提示检查 NEO4J_URI/USER/PASSWORD，标记 `_initialized=True`（**初始化过但禁用**），直接返回；
2. `graphiti-core` 未安装（ImportError）→ 同样降级，提示 `pip install graphiti-core>=0.3.0`。

降级后的表现：`/health/ready` 的 `checks.neo4j.status=disconnected/unavailable` 但 `ready` 仍为 true（可选依赖不阻断，`httpserver/routes/health.py:129-144`）；图谱摄取/查询接口报错但任务分析照常。

### 1.4 wipe_neo4j.py 工具

`python_service/wipe_neo4j.py:12-31`：从 `../.env`（相对脚本）读 NEO4J_URI/USER/PASSWORD，执行 `MATCH (n) DETACH DELETE n` 并打印删除的节点/关系数。**全库清空、无确认**，仅在打算重建图谱时使用。按任务清理不需要它——`DELETE /api/tasks/<id>` 已联动删除该任务的图（见 DataAndBackup.md §3）。

失败排查：`Failed to wipe database: ...` 多为密码错（默认 neo4j/neo4j 首次登录强制改密）或 7687 未监听（`systemctl status neo4j`、`ss -ltn | grep 7687`）。

## 2. Redis（摄取任务持久化队列，可选）

背景：`IngestionJobManager` 用 Redis 持久化摄取 job（hash `job:<id>`、队列 `ingestion_queue`、事件缓存 1h TTL）；**可选依赖**。

- 安装：`setup.sh` Step 1 的 apt 包含 `redis-server redis-tools`，随后 `systemctl enable redis-server && systemctl start redis-server`；systemd 不可用时回退 `redis-server --daemonize yes`；仍不可用只警告 "IngestionJobManager will fall back to in-memory storage"（`setup.sh:287-302`）。Redis 属 OPTIONAL_APT_PACKAGES——无 sudo 环境会跳过安装（`setup.sh:226-284`）。
- 配置：`.env` `REDIS_URL`（默认 `redis://localhost:6379`，`httpserver/config.py:186-187`；当前 `.env` 用带密码形式 `redis://:123456@localhost:6379`）。
- **内存回退语义**：连接失败/未安装时 `_use_redis=False`，job 全部存进程内存（`ingestion_job_parts/_manager.py:38-89`）——**服务重启丢队列**。日志特征：`Redis not available, using in-memory storage: ...`。
- 验证：`curl http://localhost:8090/api/system/redis/status` 返回 `{"connected":true,"in_use":true,...}`（URL 密码脱敏）；`/health/ready` 的 `checks.redis` 同样信息。

失败排查：`connected:false` 时依次 `redis-cli ping`（本机无密码场景）/ `redis-cli -u "$REDIS_URL" ping`；密码含特殊字符时 URL 需百分号编码。

## 3. PostgreSQL（分布式 C/S server 专用）

背景：`:8091` 的多租户 API（组织/用户/客户端/命令队列/任务）全部落在 PostgreSQL；本地 C++ 分析栈不使用它。

### 3.1 配置

- `.env` `DATABASE_URL=postgresql://postgres:<pwd>@localhost:5432/tracelens`（`server/config.py:42-45` 默认 `postgres:postgres@localhost:5432/tracelens`）；三个独立预算：`DB_CONNECT_TIMEOUT=5`（驱动连接）、`DB_POOL_TIMEOUT=5`（连接池 checkout）、`DB_STARTUP_TIMEOUT=30`（启动初始化总预算，必须大于前两者，`server/config.py:47-51` 注释）。
- 装法：仓库不含 PG 安装步骤（setup.sh 只装 `libpq-dev` 客户端库）。自备 `sudo apt-get install postgresql`，建库：`sudo -u postgres createdb tracelens`。

### 3.2 迁移：001 可自动、002/003 手工 psql

`migrations/postgresql/` 下三个文件：

| 迁移 | 内容 | 应用方式 |
|------|------|---------|
| `001_initial_schema.sql` | 全部表 + 索引 + 种子（Default Organization、super_admin/admin123） | `python -m server.db.init_db --migrate --init --seed`（从 python_service 目录）；**server 启动时的 lifespan 只做 `Base.metadata.create_all`（ORM 建表），不执行 SQL 迁移文件**（`server/main.py:79-97`、`server/db/session.py:init_db`） |
| `002_command_task_fk.sql` | command_queue.task_id 真外键 + JSONB 回填 + 索引 | 手工：`psql "$DATABASE_URL" -f migrations/postgresql/002_command_task_fk.sql` |
| `003_fix_super_admin_seed_credentials.sql` | 修复 001 种子 super_admin 的坏密码哈希与 `.local` 邮箱 | 手工：`psql "$DATABASE_URL" -f migrations/postgresql/003_fix_super_admin_seed_credentials.sql` |

002/003 均幂等：002 用 `ADD COLUMN IF NOT EXISTS`/`CREATE INDEX IF NOT EXISTS`（`002:5-15`）；003 只 UPDATE 仍携带已知坏值的行，操作员改过密码/邮箱则不动（`003:14-18`）。

**不应用 003 的症状**：`POST /api/auth/login` 对内置 super_admin **恒 401**（001 里的字面哈希与文档口令 admin123 不匹配），且 `GET /api/auth/me` 对该用户 500（`.local` 保留 TLD 被 Pydantic EmailStr 拒绝）——003 文件头注释即此说明。

### 3.3 验证与失败排查

```bash
pg_isready -h localhost -p 5432
psql "$DATABASE_URL" -c "SELECT username, email FROM users WHERE role='super_admin';"
psql "$DATABASE_URL" -c "SELECT column_name FROM information_schema.columns WHERE table_name='command_queue' AND column_name='task_id';"   # 002 生效证据
curl -s http://localhost:8091/health/ready      # {"ready":true} 或 503
```

DB 不可用时：8091 的 `/health` 返回 `database:"degraded"`（仍 200）、`/health/ready` 返回 503（`server/main.py:155-177`）；启动日志会记 `database initialization timed out`（超 DB_STARTUP_TIMEOUT）或具体异常类名。

### 3.4 TEST_DATABASE_URL（仅测试）

`python_service/tests/conftest.py:340-360`：DB 集成测试 fixture 独立连 `TEST_DATABASE_URL`（默认 `postgresql://postgres:postgres@localhost:5432/tracelens_test`），每个测试 `create_all`/`drop_all`，**不清空业务库**。跑测试前建一次性库：`sudo -u postgres createdb tracelens_test`。

## 4. LLM 端点（LM Studio / OpenAI 兼容服务）

背景：文件描述、事件簇分析、Vision、Graphiti 实体抽取、报告生成全部依赖一个 OpenAI 兼容端点；**可选依赖**（不可达时相应功能降级）。`.env.example` 默认指向局域网 LM Studio `http://192.168.31.170:1234`。

### 4.1 双模型要求

`.env.example:29-34` 注释明确：完整 Graphiti/知识图谱功能要求 LLM 后端**同时加载**两个模型：
1. 主推理：`openai/gpt-oss-20b`（`LLM_TEXT_MODEL`）；
2. 嵌入：`text-embedding-nomic-embed-text-v1.5`（`graphiti_integration/config.py:33` 的 embedder 默认名，env 键为 `EMBEDDING_MODEL`）。

嵌入端点可独立配置（`EMBEDDING_BASE_URL`/`EMBEDDING_API_KEY`），不设时回退用 LLM 主端点（单台 LM Studio 全包的场景无需额外配置，`graphiti_integration/config.py:94-102`）。嵌入维度默认 768（`EMBEDDING_DIM`）。

### 4.2 模型名一致性坑（最高频故障）

- 请求体里的 `model` 必须与后端**已加载的模型标识完全一致**（含 `openai/`、`qwen/` 等前缀）。`.env` 改了 `LLM_TEXT_MODEL` 而服务未重载、或 LM Studio 换了模型没改 `.env`，都会得到 404 model not found 类错误。
- `.env.example` 里 `LLM_TEXT_MODEL=qwen/qwen3.6-35b-a3b` 是示例值，当前环境 `.env` 又用了别的名字——**以 `curl http://<LLM_BASE_URL>/v1/models` 的输出为准**逐字对照。
- Vision 独立一组：`LLM_VISION_BASE_URL`/`LLM_VISION_MODEL`，同样要求一致。
- Graphiti 侧读的是同一组 `LLM_TEXT_*`，另加 `GRAPHITI_USE_LOCAL_LLM=true`（false 则要求 OPENAI_API_KEY）。

### 4.3 验证

```bash
curl -s http://<LLM_BASE_URL>/v1/models                       # 模型在列且名字与 .env 一致
curl -s http://localhost:8090/health/ready                    # checks.llm.status=available
scripts/verify_llm_analysis.py                                # 仓库自带的 LLM 分析验证脚本
./scripts/diagnose_services.sh                                # 第 4 段会 POST 8090/api/llm/analyze 实测
```

失败排查：`llm: unavailable` 时先 curl `/v1/models`（网络/端口）→ 再核对模型名（§4.2）→ 最后看 `build/logs/python_service.log` / `cpp_server.log` 中的具体报错。无 LLM 环境想先跑通主流程：创建任务时不勾 LLM 分析（`llm_analyze=false`），全部分析仍可完成。

## 5. 依赖分级总表（谁挂了影响什么）

背景：来自 httpserver 启动/就绪逻辑与各服务初始化代码的分级（同 `docs/architecture/Deployment.md` §7）。

| 依赖 | 服务的角色 | 配置键 | 挂了的表现 |
|------|-----------|--------|-----------|
| C++ forensic_analyzer | **httpserver 硬依赖** | `CPP_BACKEND_URL`、`CPP_STARTUP_REQUEST_TIMEOUT=5`、`CPP_RECOVERY_TIMEOUT=8` | `/health/ready` 的 `ready=false`（服务仍启动、降级运行） |
| PostgreSQL | **C/S(8091) 必需** | `DATABASE_URL` + 三个 DB_*_TIMEOUT | `/health` `database:degraded`；`/health/ready` 503 |
| Neo4j | 可选 | `NEO4J_URI/USER/PASSWORD` | GraphitiService disabled（§1.3） |
| Redis | 可选 | `REDIS_URL` | 摄取队列回退内存，重启丢队列（§2） |
| LLM 端点 | 可选 | `LLM_BASE_URL`/`LLM_TEXT_*`/`LLM_VISION_*` | LLM 分析降级；主流程可跑（§4） |
| MCP 服务器 | 可选 | `MCP_SERVER_PORT=8890`、`MCP_ALLOWED_PATHS` | MCP 集成不可用 |

排障时先 curl `http://localhost:8090/health/ready` 拿到 `checks` 全景，再按行对号入座，不要逐个猜。

## 6. LM Studio 双模型加载操作

背景：LM Studio 的模型加载是显式的——"装了"不等于"加载了"，Graphiti 同时需要 chat 与 embedding 两个模型在同一个端点上可用。

操作：
1. 打开 LM Studio，在 Developer/Server 标签页启动服务（确认端口 = `LLM_BASE_URL` 的端口，默认示例 1234）；
2. 加载主推理模型，**记录其完整标识**（如 `openai/gpt-oss-20b`）；
3. 加载嵌入模型 `text-embedding-nomic-embed-text-v1.5`（nomic-embed）；
4. `curl -s http://<host>:1234/v1/models` 确认两个模型都在列表中且名字与 `.env` 的 `LLM_TEXT_MODEL`、`EMBEDDING_MODEL`（未设则为默认 nomic 名）逐字一致；
5. 实测一次 embedding 可用性（Graphiti 才会用到）：
```bash
curl -s http://<host>:1234/v1/embeddings -H 'Content-Type: application/json' \
     -d '{"model":"text-embedding-nomic-embed-text-v1.5","input":"probe"}' | head -c 200
```

常见坑：
- 只加载了 chat 模型 → 文件分析正常、图谱摄取报 embedding 模型不存在；
- LM Studio 重启后未重新加载模型 → 上一轮还好的任务突然失败，先查 `/v1/models`；
- 显存不够同时装两个 → 换小量化版本，或把 embedder 指到另一台机器（`EMBEDDING_BASE_URL`，`graphiti_integration/config.py:94-102` 支持分离部署）。

## 7. 症状速查表

| 症状 | 大概率原因 | 处置 |
|------|-----------|------|
| `/health/ready` 里 neo4j `disconnected` 但服务正常 | Neo4j 未启动/密码错 → Graphiti disabled | `systemctl status neo4j`；核 `.env` 三键；重启 8090 |
| `checks.redis.in_use=false` | Redis 未装/未启动/密码不符 | `redis-cli ping`；无 Redis 时确认可接受"重启丢队列" |
| 8091 `/health/ready` 503 | PG 不可达或超 `DB_STARTUP_TIMEOUT` | `pg_isready`；看 `build/logs/cs_server.log` 的异常类名 |
| super_admin 登录恒 401 | 003 未应用 | §3.2 应用 003；详见 UpgradeMigration.md §2.2 |
| LLM 404 model not found | `.env` 模型名与后端不一致 | `curl /v1/models` 逐字对照（§4.2） |
| 图谱摄取报 embedding 错误 | 只加载了 chat 模型 | §6 加载 nomic-embed |
| Graphiti 报 8096/overflow | 批量/episode token 超窗口 | 见 PerformanceTuning.md §4 |
| 集成测试连不上 `tracelens_test` | 测试库未创建 | §3.4 建 `tracelens_test` |

## 8. PostgreSQL 最小权限建议（可选加固）

背景：`DATABASE_URL` 默认用超级用户 postgres 连接；内网单机可接受，多机/多人共管时可收窄。

```sql
-- 专用角色 + 最小权限（在 postgres 超级会话执行）
CREATE ROLE tracelens_app LOGIN PASSWORD '<强口令>';
GRANT CONNECT ON DATABASE tracelens TO tracelens_app;
\c tracelens
GRANT USAGE, SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO tracelens_app;
GRANT USAGE, CREATE ON SCHEMA public TO tracelens_app;   -- 迁移/建表需要
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO tracelens_app;
```
随后 `.env` 的 `DATABASE_URL` 换成该角色；init_db 的 `create_all` 与 002/003 迁移仍可执行（需要 CREATE 表权限，上面已授）。回退方式即改回 postgres 连接串。

## 与代码的对应

| 机制 | 位置 |
|------|------|
| Neo4j 安装/enable/初始密码 | `setup.sh:307-410`（set-initial-password `:379-391`） |
| Graphiti 降级（disabled 语义） | `python_service/httpserver/services/graphiti_parts/_core.py:21-46` |
| Graphiti health_check | 同上 `:150-172` |
| neo4j 配置与超时 | `python_service/httpserver/config.py:153-154, 195-198` |
| wipe_neo4j 工具 | `python_service/wipe_neo4j.py:12-31` |
| Redis 安装/systemd/回退 | `setup.sh:287-302`；可选包跳过逻辑 `setup.sh:226-284` |
| Redis URL 与内存回退 | `python_service/httpserver/config.py:186-187`；`httpserver/services/ingestion_job_parts/_manager.py:38-89` |
| Redis 状态端点 | `python_service/httpserver/routes/health.py:194-230` |
| DATABASE_URL 与三超时 | `python_service/server/config.py:42-51` |
| server 启动仅 create_all（不跑 SQL 迁移） | `python_service/server/main.py:79-97`；`server/db/session.py`（init_db） |
| 001 应用入口（--migrate/--init/--seed） | `python_service/server/db/init_db.py:122-133, 135-164` |
| 002/003 手工迁移与幂等性 | `migrations/postgresql/002_command_task_fk.sql:5-15`；`003_fix_super_admin_seed_credentials.sql:1-28` |
| 8091 /health、/health/ready 503 | `python_service/server/main.py:155-177`（DB 超时 `:51-76`） |
| TEST_DATABASE_URL | `python_service/tests/conftest.py:333-360` |
| 双模型要求注释 | `.env.example:29-34` |
| embedder 默认/回退 | `python_service/graphiti_integration/config.py:32-35, 94-102` |

**最后更新**: 2026-08-24（新建，运维手册）
