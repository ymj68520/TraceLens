# 分布式 C/S 实操教程（server :8091 + tracelens_agent）

> **目标读者**：需要用一台中心服务端管理多台取证机（下发磁盘分析命令、回收结果索引）的取证平台运维/开发人员。
> **前置条件**：PostgreSQL 可用（唯一硬依赖）；服务端与取证机各自完成 [快速入门](../getting-started/QuickStart.md) 的构建。
> **预计耗时**：60–90 分钟（首次含迁移与编译）。
> **端口约定**：本地栈 = C++ 8666/8080 + httpserver 8090；本教程的 C/S server 独占 **8091**（`PORT`）。三者同 `.env` 共存，字段不相交。

---

## 0. 场景设定

市局实验室要统管三个区县送检点的取证机。设计约束：**磁盘镜像字节永不离开取证机**，服务端只保存产物引用（`file_path + storage_location + result_metadata.base_name`）与命令队列。你要搭起：PostgreSQL → C/S server → 组织与注册令牌 → 在一台取证机上编译运行 `tracelens_agent` → 下发一次 `analyze_disk` 命令并回收结果 → 用 `/distributed` 页面冒烟验证。

---

## 1. PostgreSQL 准备与迁移

```bash
# 建库（示例；账号密码按环境替换）
sudo -u postgres createdb tracelens
# .env 中配置连接串
grep DATABASE_URL .env
# DATABASE_URL=postgresql://postgres:<密码>@localhost:5432/tracelens
```

应用迁移（在 `python_service/` 目录，同一 venv）：

```bash
cd python_service
.venv/bin/python -m server.db.init_db --migrate --seed
# --migrate 只应用 001_initial_schema.sql（10 张表 + 索引 + 默认组织与 super_admin 种子）
# --seed 幂等补种子（默认组织 + super_admin，口令 bcrypt 化）

# 002/003 必须手工执行（启动时的自动迁移只认 001）：
psql "$DATABASE_URL" -f ../migrations/postgresql/002_command_task_fk.sql
psql "$DATABASE_URL" -f ../migrations/postgresql/003_fix_super_admin_seed_credentials.sql
```

三个迁移的分工（`migrations/postgresql/`）：

| 迁移 | 内容 |
|------|------|
| 001 | 建全 schema：organizations / users / clients / registration_tokens / disk_images / command_queue / analysis_tasks / analysis_results / llm_analysis / task_history |
| 002 | 把 `command_queue.parameters->>'task_id'` 软链接升级为真 FK（ON DELETE CASCADE）并回填 |
| 003 | 修复 001 的坏种子：super_admin 的 bcrypt 哈希对不上文档口令、`.local` 邮箱被 Pydantic 拒绝 |

**预期看到**：`--migrate` 单事务完成无报错；002/003 幂等可重放。之后用内置账号登录（**应用 003 之后才可用**）：

```bash
curl -X POST http://localhost:8091/api/auth/login \
  -d "username=super_admin&password=admin123"     # OAuth2 密码流（form-urlencoded）
# → {"access_token": "<JWT>", "token_type": "bearer", "expires_in": 3600}
```

**为什么要看**：不应用 003 时 super_admin 登录**恒 401**、`/api/auth/me` 序列化 500——这是已知的"开箱不可用"坑（[server/Main](../modules/python/server/Main.md) 注意事项）。`admin123` 标注 CHANGE IN PRODUCTION，生产必改。

---

## 2. 启动 server

```bash
# 方式一：随本地栈一起（run.sh 会拉起 :8091，健康检查软失败）
./run.sh

# 方式二：独立进程
cd python_service && PORT=8091 PYTHONPATH=. .venv/bin/python -m server.main
```

```bash
curl http://localhost:8091/health        # 恒 200，database: available|degraded
curl http://localhost:8091/health/ready  # DB 不可用时 503（启动快照）
```

**预期看到**：`/health` 返回 healthy；DB 掉线时进程仍存活（降级），碰 DB 的端点报错但 liveness 不死。

---

## 3. 组织与注册令牌

```bash
BASE=http://localhost:8091
AUTH="Authorization: Bearer <user_token>"

curl -X POST $BASE/api/organizations -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"name": "市局实验室"}'
curl $BASE/api/organizations -H "$AUTH"

# 为组织签发客户端注册令牌（一次性注册凭据，有过期与最大客户端数）
curl -X POST $BASE/api/organizations/<org_id>/registration-tokens -H "$AUTH"
curl $BASE/api/organizations/<org_id>/registration-tokens -H "$AUTH"    # 令牌列表
```

**预期看到**：创建组织返回 org_id；签发返回 token 串（registration_tokens 表，unique、可吊销 `DELETE /api/organizations/registration-tokens/<token_id>`）。

**为什么要看**：取证机不直接持有用户账号——注册令牌是"新机器入网"的唯一入口，方便吊销与计数。

---

## 4. 取证机：编译并注册 tracelens_agent

`tracelens_agent` 是**独立 CMake 目标**（`src/http_agent/CMakeLists.txt:71`，`add_executable(tracelens_agent http_agent_main.cpp)` 链接 `tracelens_agent_lib`）：

```bash
cmake -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build --target tracelens_agent -j$(nproc)
# 产物 build/tracelens_agent
```

注册（一次性，返回 30 天 client JWT）：

```bash
curl -X POST $BASE/api/clients/register -H "Content-Type: application/json" \
  -d '{"registration_token": "<令牌>", "hostname": "lab-client-1", "capabilities": {"platforms": ["linux","windows"]}}'
# → {client_id, jwt_token, poll_interval: 10, server_url}
```

把返回的 `jwt_token` 存成取证机上的 token 文件（如 `/etc/tracelens/client.token`，注意权限），写 agent 配置 `/etc/tracelens/agent.conf`（key=value 格式）：

```ini
server_base_url = http://localhost:8091
token_path = /etc/tracelens/client.token
analyzer_path = /opt/tracelens/build/forensic_analyzer
hostname = lab-client-1
work_base_dir = /var/tracelens/work
image_dirs = /evidence/districtA:/evidence/districtB
poll_interval_seconds = 10
```

约束（`ClientConfig::validate`）：`token_path` 与 `analyzer_path` 必填；`server_base_url` 必须带 scheme，**`http://` 仅允许 localhost/127.0.0.1/::1**，跨机部署必须 `https://`；`poll_interval_seconds` 限 5–30。也可用环境变量替代配置文件：`TRACELENS_SERVER_URL / TRACELENS_TOKEN_PATH / TRACELENS_POLL_INTERVAL / TRACELENS_HOSTNAME / TRACELENS_ANALYZER_PATH / TRACELENS_WORK_DIR / TRACELENS_STATE_DB / TRACELENS_IMAGE_DIRS`。

启动：

```bash
./tracelens_agent --config /etc/tracelens/agent.conf         # 常驻轮询
./tracelens_agent --config /etc/tracelens/agent.conf --once  # 单轮冒烟
```

**预期看到**：启动即做一次本地镜像索引上报（`image_dirs` 配置时打印 `indexed N local image(s)`；没配则提示跳过——best-effort，失败不致命）；随后进入轮询循环。服务端 `GET /api/clients/<client_id>` 的 `last_poll` 开始刷新。

**为什么要看**：`--once` 是最省事的冒烟开关；索引上报让第 5 步的命令可以直接引用真实存在的镜像路径。

---

## 5. 下发命令与轮询执行

```bash
# 下发 analyze_disk（用户 token；parameters.image_path 必填）
curl -X POST $BASE/api/commands -H "$AUTH" -H "Content-Type: application/json" \
  -d '{
    "client_id": "<client_id>",
    "command_type": "analyze_disk",
    "parameters": {
      "image_path": "/evidence/districtA/case_042.img",
      "analysis_type": "linux",
      "options": {"file_carving": true}
    },
    "priority": "normal",
    "ttl_hours": 24
  }'
```

`analysis_type` 映射（`command_executor.cpp` 的 `build_analyzer_argv`）：`windows → --windows-analyze`、`linux → --linux-analyze`、`android → --android-analyze`，其余（full/quick/未知）不带平台标志走分析器默认。取证机领到命令后在本地拼出并执行：

```
forensic_analyzer <image_path> --db-dir <work_dir> --no-ai --overwrite [--linux-analyze] [--carve]
```

两个刻意的 INVARIANT：**客户端永不运行 LLM**（硬编码 `--no-ai`，`options.llm_text_extraction` 被有意忽略）；每次在干净目录重新生成（`--overwrite`）。

**预期看到**：agent 轮询 `GET /api/commands/poll`（client token）领取命令 → 本地跑分析 → 收集 `<baseName>*.db`（排除 `-wal/-shm/-journal` 边车）为 result artifacts（`result_type=database`、`storage_location=hostname`、`result_metadata.base_name`）→ `POST /api/tasks/<task_id>/results` 上传产物引用 → `POST /api/commands/<command_id>/status` 回报，状态传播到关联分析任务。

不想编译 agent 也能用 curl 模拟一个"最小客户端"验证服务端行为：

```bash
CT="Authorization: Bearer <client_token>"
curl $BASE/api/commands/poll -H "$CT"                 # 领命令（同时刷新 last_poll 心跳）
# ...按需本地执行或不执行...
curl -X POST $BASE/api/commands/<command_id>/status -H "$CT" \
  -H "Content-Type: application/json" -d '{"status": "done"}'
```

**为什么要看**：排障时把"服务端问题"与"agent 问题"分开——curl 通而 agent 不通，问题在 agent 配置/token；curl 也不通再看服务端日志 `build/logs/cs_server.log`。

**为什么要看**：服务端全程拿不到镜像字节，只收到"哪个文件、多大、在哪个机器"——这是架构的安全边界，验证它就是验证部署正确性。

> **注意**：`command_type` 目前**只有 `analyze_disk` 会被真正执行**。`extract_file` / `health_check` 等命令在客户端被"确认即成功"（返回 `ignored non-analyze command: <type>`，不执行任何动作）——下发它们只能用于连通性确认，不能当功能用（`command_executor.cpp:145-150`）。`command_queue` 的 CHECK 约束把类型钉死在 `analyze_disk / extract_file / health_check` 枚举内。

---

## 6. 结果与索引回收查询

```bash
curl $BASE/api/tasks/<task_id>/results -H "$AUTH"          # 任务产物引用列表
curl $BASE/api/tasks/<task_id>/llm-analyses -H "$AUTH"     # LLM 分析结果
curl $BASE/api/commands/client/<client_id> -H "$AUTH"      # 某客户端命令历史
curl $BASE/api/clients/<client_id>/images -H "$AUTH"       # 客户端上报的镜像索引
```

**预期看到**：results 里每条 artifact 带 `result_type / file_path / file_size / storage_location / result_metadata{base_name}`——要拿真实数据仍需到对应取证机上取文件（路径即线索）。

**为什么要看**：办案时"服务端查索引、取证机取证据"的分工由此确立；`base_name` 是跨表对齐的键。

---

## 7. /distributed 冒烟页

前端 `http://localhost:8666/distributed`（前端经 `/csapi` 代理到 :8091，代理规则见 [Deployment](../architecture/Deployment.md) 第 5 节）。用 super_admin 或 org 账号登录后：

1. 客户端列表应出现 `lab-client-1`，状态随 `last_poll`（约 60s 在线窗口）刷新；
2. 镜像列表应能看到第 4 步索引上报的 `case_042.img`；
3. 从页面下发一条 `health_check`，在命令历史里观察它被客户端领走并回报成功（对照第 5 节的"确认即成功"语义）。

**预期看到**：页面数据与第 6 节 curl 结果一致；vite 开发模式下 `/csapi` 代理同样指向 8091。

**为什么要看**：这是给非技术验收方看的"眼见为实"；也是前后端代理配置正确性的最短路检验。

---

## 8. 与本地栈共存的端口约定

| 端口 | 服务 | 说明 |
|------|------|------|
| 8666 / 8080 | C++ forensic_analyzer | run.sh 回退 8666；`.env HTTP_SERVER_PORT` 与 `make cpp` 默认 8080 |
| 8090 | httpserver | 本地 LLM/图谱/报告服务，`PYTHON_HTTP_PORT` |
| 8091 | server（本教程） | C/S 服务端，`PORT`；**勿与 8090 混用**（server/config.py 注释明确分工） |

三个服务可读同一个 `.env`：server 的 Settings 用 `extra="ignore"` 忽略 httpserver 专属变量（缺了这一条共享 `.env` 会让 server 拒绝启动）。取证机上 agent 与本地 `forensic_analyzer` CLI 互不干扰——agent 的一切产物写在自己的 `work_base_dir`。

---

## 排坑清单

1. **002/003 迁移没有自动化路径**：`run_migrations()` 只认 001（候选列表写死文件名）。已有环境升级必须手工 `psql -f` 002/003，否则 `command_queue.task_id` FK 缺失、super_admin 登录恒 401（[server/Main](../modules/python/server/Main.md) 第 8 节）。
2. **super_admin 401 ≠ 密码错**：大概率是 003 未应用（001 种子的哈希本就验不过 `admin123`）；应用 003 后再试（第 1 节）。
3. **`JWT_SECRET_KEY` 默认值是 `change-this-in-production`**：不覆盖等于公开签名密钥，生产必改（HS256）。
4. **`http://` 到非 localhost 会被 agent 拒绝**：`validate()` 强制 https 或 localhost 三种写法；报错原文会提示 "use https://"。
5. **agent 不执行 LLM**：命令参数里的 LLM 相关选项被有意忽略（`--no-ai` 硬编码）；需要 AI 分析时把产物拿回中心侧处理。
6. **`extract_file` / `health_check` 只确认不执行**：见第 5 节注记，别把它们写进自动化流程当功能依赖。
7. **`/health/ready` 是启动快照**：`_db_available` 只在 lifespan 初始化时写入，DB 中途挂掉后 `/health` 仍显示 available，直到重启。
8. **client token 与 user token 严格互斥**：payload 的 `type` 声明不匹配即 401（拿用户 token 调 `/api/commands/poll` 会失败）；token 文件权限过松时 JwtClient 直接抛错。
9. **CORS 固定三源**（localhost:5173 / 127.0.0.1:5173 / localhost:3000）且带 credentials：前端部署到其他域名需改 `CORS_ORIGINS`，不能写 `*`。

---

## 延伸阅读

- [server/Main 模块文档](../modules/python/server/Main.md) — 装配、降级启动、迁移细节
- [Deployment](../architecture/Deployment.md) 第 6 节 — C/S 部署架构图与 env 表
- [DatabaseSchema](../architecture/DatabaseSchema.md) 第 9 节 — PostgreSQL 10 张表 ER 图
- [Python REST API](../api_reference/Python_REST_API.md) 第 16 节 — 8091 全部端点（认证/组织/客户端/命令/结果）
- [C/S 集成加固计划](../superpowers/plans/2026-07-27-cs-integration-hardening.md) — 双栈端口责任表与产物上传契约

---

**最后更新**: 2026-08-24（新建，教程）
