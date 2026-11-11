# 服务运行手册（ServiceRunbook）

> 适用场景：单机 all-in-one 部署下，启动 / 停止 / 重启 TraceLens 三服务（C++ forensic_analyzer、Python httpserver、分布式 C/S server），执行健康检查与端口故障排查。
> 前置：已按 `setup.sh` 完成依赖安装并构建过一次；`.env` 已就位（无则用 `cp .env.example .env`）。
> 端口口径：以仓库当前 `.env` 为准——C++ **8666**（`HTTP_SERVER_PORT`）、Python **8090**、C/S **8091**。`.env.example` 模板里 C++ 写的是 **8666**（`.env.example:185`）；未设置 `HTTP_SERVER_PORT` 时启动脚本的缺省回退是 **8080**（`scripts/lib/tracelens_env.sh:38` 的 `: "${HTTP_SERVER_PORT:=8080}"`，`run.sh:78` 直接取该值），操作前先确认自己的 `.env`。

## 速查卡

```bash
# 一键编译 + 启动三服务（前台，Ctrl+C 全停）
./run.sh

# 常用变体
./run.sh --no-build          # 跳过编译，直接启动（需已构建）
./run.sh --no-web            # 跳过前端 npm 构建
./run.sh --no-python         # 只启动 C++
./run.sh --build-only        # 只编译，不启动
./run.sh --jobs 8            # 指定编译并行数（默认 4）

# 健康检查（三服务）
curl -s http://localhost:8666/api/system/health   # C++（run.sh 用作硬检查）
curl -s http://localhost:8090/health              # Python 存活
curl -s http://localhost:8090/health/ready        # Python 就绪（依赖分级）
curl -s http://localhost:8091/health              # C/S（database 字段）
curl -s http://localhost:8091/health/ready        # C/S 就绪（失败=503）

# 端口占用 / 残留进程
lsof -i :8666 -i :8090 -i :8091
kill -9 $(lsof -t -i:8666)     # 逐端口清理（run.sh 启动前会自动做）

# 日志（每次启动用 > 覆盖重写，无轮转）
tail -f build/logs/cpp_server.log
tail -f build/logs/python_service.log
tail -f build/logs/cs_server.log

# 任务暂停 / 恢复（阶段边界协作式，见 §4.5）
curl -X POST http://localhost:8666/api/tasks/<id>/pause      # 当前阶段跑完即暂停（PENDING 立即暂停）
curl -X POST http://localhost:8666/api/tasks/<id>/resume     # 从阶段账本续跑（FAILED/CANCELLED/INTERRUPTED/PAUSED）

# 重启后检查被中断任务（stdout 与审计日志会报数量）
grep "interrupted task(s) are resumable" build/logs/cpp_server.log

# 综合诊断
./scripts/diagnose_services.sh
```

## 1. 三服务与启动方式总览

背景：TraceLens 本地栈 = C++ HTTP 服务（托管 Web 前端 + 取证 API）、Python httpserver（LLM/图谱代理）、C/S server（多租户 API，需 PostgreSQL）。三者的启动入口有 `run.sh`（推荐）与 `make start`（`scripts/start_all_services.sh`）两条等价路径。

| 服务 | 端口来源 | 进程 | 日志 |
|------|---------|------|------|
| C++ | `HTTP_SERVER_PORT`（当前 .env=8666；`.env.example:185` 模板值=8666；未设置时 `scripts/lib/tracelens_env.sh:38` 回退 8080） | `build/forensic_analyzer --http-server <port>` | `build/logs/cpp_server.log` |
| Python httpserver | `PYTHON_HTTP_PORT`（8090） | `.venv/bin/python -m httpserver.main` | `build/logs/python_service.log` |
| C/S server | `PORT`/`CS_PORT`（8091） | `.venv/bin/python -m server.main` | `build/logs/cs_server.log` |

操作（run.sh 路径）：

```bash
./run.sh                  # 编译 C++(-j4) → npm build → 同步 dist → 清理端口 → 启动三服务
```

验证：终端最终打印 "全部服务启动成功" 框 + 三个 PID + 访问地址（Web `http://localhost:8666/`、API 文档 `/api/docs`）。

失败排查：
- C++ 启动失败时 run.sh 会打印 `cpp_server.log` 尾部 30 行并 `exit 1`（硬失败）。
- Python/C/S 健康检查失败只打黄色警告，**不阻断**（见 §3 语义），此时需自行 tail 对应日志。

## 2. run.sh 全参数

背景：`run.sh` 参数解析在 `run.sh:50-66`；默认值 `JOBS=4`、`DO_BUILD=1`、`BUILD_WEB=1`、`RUN_PYTHON=1`、`RUN_CPP=1`、`CLEAN_FIRST=0` 在其前的 `run.sh:43-48`（再往前 `:32-40` 是 `rotate_log` 日志轮转函数）。

| 参数 | 作用 | 备注 |
|------|------|------|
| （无参） | 编译 + 构建前端 + 启动全部 | |
| `--build-only` | 只编译 C++（和前端），不启动任何服务 | `RUN_CPP=0 RUN_PYTHON=0`，编译完 `exit 0` |
| `--no-build` | 跳过编译直接启动 | 若 `build/forensic_analyzer` 不存在则报错退出 |
| `--no-web` | 跳过 `npm run build` | 前端仍从已有 `build/web/dist` 托管 |
| `--no-python` | 只启动 C++（不启动 8090/8091） | |
| `--no-cpp` | 只启动 Python 侧 | |
| `--jobs N` / `-j N` | 编译并行数，默认 4 | 注释明确"限制 CPU 防止卡死" |
| `--clean` | 编译前清理 build 目录的**编译产物** | 范围见下 |
| `-h` / `--help` | 打印脚本头注释 | |

`--clean` 的精确范围（`run.sh:113-119`）：只删除 build 顶层 的 `CMakeFiles/`、`CMakeCache.txt`、`cmake_install.cmake`、`Makefile`、`CTestTestfile.cmake`、`Testing/`、`*.o`——**保留 `logs/`、`data/`、`*.db`**（脚本会打印"保留数据库等数据"）。注意与 `make clean`（`Makefile:109-114` 直接 `rm -rf build`，**数据全删**）语义完全不同，升级场景务必区分（见 UpgradeMigration.md）。

`.env` 加载细节（`run.sh:73-76` → `scripts/lib/tracelens_env.sh` 的 `tracelens_load_env()`，`tracelens_env.sh:10-35`）：机制已重写为**解析式加载**——逐行按 `KEY=VALUE` 拆分后 `printf -v` 赋值并 export，**不经 source/eval**（JSON/URL 值按数据处理，不会变成 shell 语法）；跳过注释、空行与非赋值行（`tracelens_env.sh:16-19`）；已存在于环境中的变量不被 `.env` 覆盖（`:25`）。`PROJECT_ROOT` 防护不再是"过滤该行"，而是加载后回写：run.sh 先 `TRACELENS_ROOT="$PROJECT_ROOT"`（`run.sh:73`），source 后 `PROJECT_ROOT="$TRACELENS_ROOT"`（`run.sh:76`）——无论 `.env` 里写了什么 `PROJECT_ROOT`，最终都锁定为脚本算出的仓库根（加载器对空 `TRACELENS_ROOT` 也会按自身位置推回项目根，`tracelens_env.sh:6-8`）。

## 3. 健康端点语义（三服务各自不同，务必区分）

背景：三套健康检查的"严格程度"刻意不同，run.sh 据此决定硬失败还是软告警。

### 3.1 C++ `/api/system/health` —— 硬检查

- 实现：`src/network/HTTPServer/routes/SystemHealthRoutes.cpp:34-62`。查询 `TaskManager::get_task_statistics()`，正常返回 200 `{"status":"healthy", "task_management":{...}, "services":{...}}`；查询抛异常返回 **500** `{"status":"unhealthy"}`。
- run.sh 用它做启动硬检查（`run.sh:206`，最多 15 次、每次 1s）；`scripts/start_all_services.sh:174` 同样硬检查（10 次）。失败 → 打日志尾部 → 退出。
- 同文件还注册了：`/api/health`（同 system/health）、`/api/health/live`（纯存活，永 200）、`/api/health/ready`（task_manager 异常时返回 **503**，`SystemHealthRoutes.cpp:79-116`）、`/api/health/dependencies`（列出 sqlite/llm_service/python_service 等依赖状态）。

### 3.2 Python httpserver `/health` 与 `/health/ready` —— 降级语义（HTTP 恒 200）

- `/health`（`python_service/httpserver/routes/health.py:49-67`）：纯存活，返回 uptime。
- `/health/ready`（`health.py:92-191`）：检查四类依赖并把结果放进 `checks`，**HTTP 始终 200，看 `ready` 字段**：
  - `cpp_backend`：**硬依赖**，不可达 → `ready=false`（`checks.cpp_backend.status=disconnected`）；
  - `neo4j`、`llm`、`redis`：**可选依赖**，失败只置 `status=unavailable/disconnected`，**不影响 ready**（代码注释明确 "Neo4j is optional, don't fail readiness" 等）。
- run.sh 对 Python 侧只做**软检查**：`http://localhost:8090/health` 超时仅打警告（`run.sh:239-240`）。
- Redis 状态另有独立端点 `GET /api/system/redis/status`（`health.py:194-230`），返回 `connected/in_use`（密码已脱敏）。

### 3.3 C/S `/health` 与 `/health/ready` —— DB 就绪 503

- `/health`（`python_service/server/main.py:159-167`）：恒 200，`database: "available"|"degraded"`（取决于启动时 `init_db` 是否成功/超时，`initialize_database()` 定义 `main.py:51-76`、超时分支 `:59-67`，受 `DB_STARTUP_TIMEOUT=30` 约束）。
- `/health/ready`（`main.py:169-181`，503 在 `:175`）：数据库不可用返回 **503** `{"ready":false,"database":"unavailable","error":...}`。这是三服务中唯一"就绪失败给 503"的 Python 端点。

### 3.4 注意：run.sh 的 check_service 接受 200 或 404

`run.sh:95-107` 的 `check_service` 用 `curl ... | grep -qE "200|404"` 判定就绪——HTTP 404 也算"存活"。这对"服务在但路由没挂对"的场景不设防，深检请手动 curl 具体端点看响应体。

## 4. 启动 / 停止 / 重启操作

### 4.1 启动（make 路径）

```bash
make start          # = start-all → ./scripts/start_all_services.sh
```

`start_all_services.sh` 与 run.sh 的差异：不编译（要求二进制已存在）、.env 直接 `set -a source`（不过滤 PYTHON_CORS_ORIGINS）、启动前同样 `lsof`+`kill -9` 清端口（`start_all_services.sh:129-152`）、C++ 硬检查 10 次（`:174`）/ Python 与 C/S 软检查 30 次（`:228`、`:254`）。

另有单服务目标（Makefile）：`make cpp`（Makefile:84 先 source `scripts/lib/tracelens_env.sh`，再 `./forensic_analyzer --http-server "$HTTP_SERVER_PORT"` **原样传值，无内联兜底**——缺省 8080 由 `scripts/lib/tracelens_env.sh:38` 的 `: "${HTTP_SERVER_PORT:=8080}"` 提供）、`make python`（venv 不存在时自动创建并装 httpserver 依赖）。

### 4.2 手动启动三条命令（排查用）

```bash
# C++（cwd 必须在 build/，data/ 与 web/dist 都按可执行文件位置解析）
cd build && ./forensic_analyzer --http-server 8666

# Python httpserver（cwd 必须在 python_service/，PYTHONPATH 指向自身）
cd python_service
PYTHONPATH=. .venv/bin/python -m httpserver.main

# 分布式 C/S（需要 PostgreSQL；PORT 显式传入保证与端口清理一致）
cd python_service
PORT=8091 PYTHONPATH=. .venv/bin/python -m server.main
```

验证：分别 curl §3 对应端点。
失败排查：手动启动常见错误是 cwd 不对——C++ 不在 `build/` 下运行会新建一套空的 `data/`；Python 不设 `PYTHONPATH=.` 会报 `No module named 'graphiti_integration'`（`scripts/start_services.sh:96-101` 注释）。

### 4.3 停止

- 前台脚本（run.sh / make start）：**Ctrl+C**。`trap cleanup EXIT INT TERM`（`run.sh:184-197`）按 **C/S → Python → C++** 顺序 `kill` + `wait`，正常情况下子进程全部回收。
- 后台/失联进程：`kill -9 $(lsof -t -i:<port>)`。run.sh 与 start_all_services.sh 每次启动前也会自动做这一步（`run.sh:172-180`），所以"重启"直接再跑一次启动脚本即可。

### 4.4 重启（RUNNING 任务不再静默续跑，而是停账待命）

没有专门的 restart 命令：再次执行 `./run.sh --no-build`（或 `make start`）即可——脚本会先杀掉三个端口上的残留进程再启动。

**重启对本地任务的影响（阶段账本引入后的语义，`src/network/HTTPServer/TaskManager.cpp:90-113`）**：启动时 `load_tasks()` 发现 `tasks.json` 里有 RUNNING 状态的任务，会把它们停在 **INTERRUPTED** 状态（不自动重跑），写审计日志 `INTERRUPTED: Task interrupted by server restart; resumable from stage ledger`，并在 stdout 打 `[TaskManager] N interrupted task(s) are resumable (stage ledger present).`。是否重新花费算力由操作员决定：`POST /api/tasks/<id>/resume` 续跑（§4.5）。TaskWatchdog 只负责运行中的僵死检测（PENDING 卡 `TASK_WATCHDOG_PENDING_MINUTES`、RUNNING 超时无进度；阈值变量与默认值在 `TaskWatchdog.cpp:27-33`——`_STALE_MINUTES`/`_PENDING_MINUTES` 默认各 30 分钟，`.h` 头注释只有笼统的 stale task 检测说明），**不负责重启后的任务恢复**。

C/S 场景注意：任务队列状态在 PostgreSQL，重启不丢；本地任务状态在 `data/tasks.json`，重启后 RUNNING → INTERRUPTED → 等 resume。

### 4.5 任务暂停 / 恢复的运维语义（pause/resume 与阶段账本）

背景：任务级生命周期 API（`src/network/HTTPServer/routes/TaskCRUDRoutes.cpp:119-145`）+ 阶段检查点账本（`src/network/HTTPServer/TaskStageLedger.h`，header-only，CLI 与 HTTP 共用）。

**pause（协作式，不杀阶段）**：`POST /api/tasks/<id>/pause`，body 可带 `{"reason": "..."}`。
- RUNNING 任务：只置 `pause_requested` 标志，**当前阶段跑完后**在阶段边界停靠为 PAUSED（与取消同一检查点机制，`TaskManager.cpp:788-814`）——立即 kill 进程不等于 pause，那会走 §4.4 的 INTERRUPTED 路径；
- PENDING（排队未开始）任务：立即停靠 PAUSED；
- 其余状态 409（`Only running or queued tasks can be paused`）。

**resume（从账本续跑，同一任务 id）**：`POST /api/tasks/<id>/resume`。前提（不满足即 409，`reason` 字段原样返回，`TaskManager.cpp:816-850`）：
- 状态为 FAILED / CANCELLED / INTERRUPTED / PAUSED 之一；
- 元数据里有至少一条非空 `stage.*` 账本记录（证明管线至少跑完过一个阶段；一条都没有则提示**重建任务**而非 resume）；
- 镜像文件仍在原路径可读（`tasks.json` 存绝对路径，跨机恢复后路径失效的任务不可 resume）；
- 元数据无 `resume.exhausted`（该标记 = 所有剩余阶段都已完成，无活可干）。

成功响应带 `resume_count`（第几次续跑）与 `resume_stage`（将从哪个阶段继续，来自元数据 `resume.next_stage`）。

**账本如何决定"跳过哪些阶段"（排障必读，`TaskStageLedger.h` 文件头注释）**：每个阶段退出时把 `metadata["stage.<阶段名>"] = "done:<输入指纹>"` 写进任务元数据（随 `tasks.json` 持久化，任务 JSON 里可直接看到，便于追溯）。恢复时只有"账本写 done **且** 该阶段的输入重新哈希后指纹一致"才跳过该阶段。指纹覆盖文件内容/`path|size|mtime` 统计指纹，SQLite 库额外计入 `-wal` 边车（防止 WAL 未 checkpoint 导致"假未变、复用陈旧产物"）。因此：**上游阶段重跑会改写下游依赖的指纹，自动失效下游的 done 记录**——`/api/tasks/<id>/resume` 不会复用与当前产物不一致的旧结果，但也意味着重启/续跑不是零成本，阶段产物被人工动过的任务可能近乎全量重算。

运维操作建议：长任务计划内维护（升级/换电）先 `pause` 等停靠完成再停服，恢复最省；直接 Ctrl+C / 断电只产生 INTERRUPTED，resume 会从最近阶段边界重放，比 pause 多花一点重算时间。

## 5. 端口占用与残留进程

背景：三个服务端口固定，前一实例未退干净时新实例 bind 失败。

```bash
lsof -i :8666 -i :8090 -i :8091            # 看 PID
kill -9 $(lsof -t -i:8666)                  # 强杀单个端口
for p in 8666 8090 8091; do kill -9 $(lsof -t -i:$p) 2>/dev/null; done
```

失败排查：
- 端口被非 TraceLens 进程占用：改 `.env`（`HTTP_SERVER_PORT`/`PYTHON_HTTP_PORT`/`PORT`）后重启，注意 `CPP_BACKEND_URL` 与前端代理目标要同步。
- `lsof` 未安装：`sudo apt-get install lsof`（run.sh 依赖它做清理，缺失时静默跳过但不会报错）。
- 杀掉 C++ 后 `forensics_audit.db-wal/-shm` 可能残留，属正常（下次启动 checkpoint）。

## 6. 日志位置与轮转现状

| 日志 | 路径 | 写入方式 | 轮转 |
|------|------|---------|------|
| C++ 服务 stdout/stderr | `build/logs/cpp_server.log` | run.sh `>` 重定向 | **无**，每次启动覆盖 |
| Python httpserver | `build/logs/python_service.log` | 同上 | **无** |
| C/S server | `build/logs/cs_server.log` | 同上 | **无** |
| C++ 应用日志 | `build/data/logs/forensics.log`（`LOG_FILE`，PathManager 解析） | 应用内 | 无 |
| 审计库 | `build/forensics_audit.db`（+`-wal`/`-shm`） | SQLite WAL | `AuditLog::rotate()` 存在（>100MB 触发）但**当前无调用方**，详见 DataAndBackup.md |

操作建议：长期运行时自行外置轮转（logrotate 或 cron 归档），因为脚本每次启动 `>` 覆盖，单次长任务期间的日志在下次启动时**会丢失**——排查历史问题先拷贝再重启。

## 7. systemd 现状（如实说明）

**单机工作台（run.sh）形态：仓库不提供 systemd unit。** `setup.sh` 仅对两个外部依赖做 systemd 管理：
- Redis：`systemctl enable redis-server && systemctl start redis-server`（`setup.sh:450-451`），systemd 不可用时回退 `redis-server --daemonize yes`（`setup.sh:456`）；
- Neo4j：`systemctl enable --now neo4j`（`setup.sh:556`；安装 `:533`）。

TraceLens 三服务在该形态下只能通过上述脚本/手动方式前台启动。需要开机自启时请自行编写 unit（ExecStart 分别对应 §4.2 三条命令，`WorkingDirectory` 必须正确）。

**野外（field）形态例外**：`deploy/field/` 提供 4 份现成 unit 模板（`tracelens-field-{cpp,python}.service.example` 与 6C release 布局的 `tracelens-field-6c-{cpp,python}.service.example`），自带安全 hardening（`ProtectSystem=strict`、`IPAddressAllow=localhost` 限定 loopback、`UnsetEnvironment` 摘除密钥等），配套 env 样例与 nginx 网关样例——安装步骤与验证见 Deployment.md §10。注意这些 unit 只覆盖"C++ 8666 + Python 8090"双服务现场子集（不含 8091 C/S），不能直接抄去做工作台形态的开机自启。

## 与代码的对应

| 机制 | 位置 |
|------|------|
| run.sh 参数解析 | `run.sh:50-66`（默认值 `:43-48`） |
| 端口变量（取值） | `run.sh:78-80`；缺省回退 `scripts/lib/tracelens_env.sh:37-44`（`HTTP_SERVER_PORT:=8080` 在 `:38`） |
| .env 解析式加载（不 source/eval）与 PROJECT_ROOT 回写 | `run.sh:73-76`；`scripts/lib/tracelens_env.sh:10-35`（跳过注释/空行/非赋值 `:16-19`，不覆盖已有环境变量 `:25`） |
| `--clean` 清理范围 | `run.sh:113-119` |
| 启动前残留进程清理 | `run.sh:172-180`；`scripts/start_all_services.sh:129-152` |
| trap 退出清理（CS→PY→CPP） | `run.sh:184-197`；`scripts/start_all_services.sh` cleanup `:85-117`（kill 顺序 `:90-109`）+ trap `:120` |
| C++ 硬健康检查 | `run.sh:206-210`；`start_all_services.sh:174` |
| Python/C/S 软检查 | `run.sh:239-240, 249-250`；`start_all_services.sh:228, 254` |
| check_service 接受 200/404 | `run.sh:95-107` |
| C++ 健康端点族 | `src/network/HTTPServer/routes/SystemHealthRoutes.cpp:13-31, 34-62, 79-116, 118-148` |
| Python /health、/health/ready 降级语义 | `python_service/httpserver/routes/health.py:49-67, 92-191` |
| Redis 状态端点 | `python_service/httpserver/routes/health.py:194-230` |
| C/S /health、/health/ready 503 | `python_service/server/main.py:159-181`（ready 503 `:175`；DB 超时 `initialize_database :51-76`，lifespan `:80`、调用 `:93`） |
| make start/cpp/python/clean | `Makefile:52-57, 79-97, 109-114` |
| 诊断脚本 | `scripts/diagnose_services.sh`（端口/二进制/端点/LLM 五段检查） |
| 重启后 RUNNING → INTERRUPTED 停账（不自动续跑） | `src/network/HTTPServer/TaskManager.cpp:90-113`（load_tasks） |
| pause 协作式停靠（RUNNING 阶段边界 / PENDING 立即） | 同上 `:788-814` |
| resume 前提校验（状态/账本/镜像/ exhausted）与 resume_count | 同上 `:816-883`；路由 `routes/TaskCRUDRoutes.cpp:119-145, 851-974` |
| 阶段账本（stage.* 元数据键、指纹含 -wal） | `src/network/HTTPServer/TaskStageLedger.h`（文件头注释 `:5-23`） |
| 僵死检测（PENDING/RUNNING 超时判 failed） | `src/network/HTTPServer/TaskWatchdog.cpp:27-33`（阈值变量；`.h` 头注释无具体变量） |
| field 形态 systemd unit 模板（含 hardening） | `deploy/field/tracelens-field-{,6c-}{cpp,python}.service.example` |

**最后更新**: 2026-11-10（补 §4.4 重启停账语义、§4.5 pause/resume 与阶段账本运维语义；§7 增补 deploy/field unit 模板现状；勘误端口兜底方向——.env.example:185=8666、未设置时 tracelens_env.sh:38 回退 8080；§2 .env 加载机制重写为 tracelens_env.sh 解析式加载；start_all_services.sh/TaskWatchdog/main.py/setup.sh 锚点校准）
