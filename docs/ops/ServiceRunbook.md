# 服务运行手册（ServiceRunbook）

> 适用场景：单机 all-in-one 部署下，启动 / 停止 / 重启 TraceLens 三服务（C++ forensic_analyzer、Python httpserver、分布式 C/S server），执行健康检查与端口故障排查。
> 前置：已按 `setup.sh` 完成依赖安装并构建过一次；`.env` 已就位（无则用 `cp .env.example .env`）。
> 端口口径：以仓库当前 `.env` 为准——C++ **8666**（`HTTP_SERVER_PORT`）、Python **8090**、C/S **8091**。`.env.example` 模板里 C++ 默认写的是 8080，`run.sh` 在 `.env` 缺失时的回退值也是 8666，操作前先确认自己的 `.env`。

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

# 综合诊断
./scripts/diagnose_services.sh
```

## 1. 三服务与启动方式总览

背景：TraceLens 本地栈 = C++ HTTP 服务（托管 Web 前端 + 取证 API）、Python httpserver（LLM/图谱代理）、C/S server（多租户 API，需 PostgreSQL）。三者的启动入口有 `run.sh`（推荐）与 `make start`（`scripts/start_all_services.sh`）两条等价路径。

| 服务 | 端口来源 | 进程 | 日志 |
|------|---------|------|------|
| C++ | `HTTP_SERVER_PORT`（当前 .env=8666；run.sh 回退 8666，.env.example=8080） | `build/forensic_analyzer --http-server <port>` | `build/logs/cpp_server.log` |
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

背景：`run.sh` 参数解析在 `run.sh:38-53`，默认值 `JOBS=4`、`DO_BUILD=1`、`BUILD_WEB=1`、`RUN_PYTHON=1`、`RUN_CPP=1`、`CLEAN_FIRST=0`。

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

`.env` 加载细节（`run.sh:62-77`）：run.sh 会过滤三类行再 source——`PYTHON_CORS_ORIGINS=`（C++ dotenv 解析不了 JSON 数组值，会告警）、`PROJECT_ROOT=`（空值会把项目根覆盖成 `/`，导致 `/python_service` 权限错误）、注释与空行；并用独立变量 `TRACELENS_ROOT` 锁定脚本算出的项目根。

## 3. 健康端点语义（三服务各自不同，务必区分）

背景：三套健康检查的"严格程度"刻意不同，run.sh 据此决定硬失败还是软告警。

### 3.1 C++ `/api/system/health` —— 硬检查

- 实现：`src/network/HTTPServer/routes/SystemHealthRoutes.cpp:34-62`。查询 `TaskManager::get_task_statistics()`，正常返回 200 `{"status":"healthy", "task_management":{...}, "services":{...}}`；查询抛异常返回 **500** `{"status":"unhealthy"}`。
- run.sh 用它做启动硬检查（`run.sh:206`，最多 15 次、每次 1s）；`scripts/start_all_services.sh:187` 同样硬检查（10 次）。失败 → 打日志尾部 → 退出。
- 同文件还注册了：`/api/health`（同 system/health）、`/api/health/live`（纯存活，永 200）、`/api/health/ready`（task_manager 异常时返回 **503**，`SystemHealthRoutes.cpp:79-116`）、`/api/health/dependencies`（列出 sqlite/llm_service/python_service 等依赖状态）。

### 3.2 Python httpserver `/health` 与 `/health/ready` —— 降级语义（HTTP 恒 200）

- `/health`（`python_service/httpserver/routes/health.py:49-67`）：纯存活，返回 uptime。
- `/health/ready`（`health.py:92-191`）：检查四类依赖并把结果放进 `checks`，**HTTP 始终 200，看 `ready` 字段**：
  - `cpp_backend`：**硬依赖**，不可达 → `ready=false`（`checks.cpp_backend.status=disconnected`）；
  - `neo4j`、`llm`、`redis`：**可选依赖**，失败只置 `status=unavailable/disconnected`，**不影响 ready**（代码注释明确 "Neo4j is optional, don't fail readiness" 等）。
- run.sh 对 Python 侧只做**软检查**：`http://localhost:8090/health` 超时仅打警告（`run.sh:239-240`）。
- Redis 状态另有独立端点 `GET /api/system/redis/status`（`health.py:194-230`），返回 `connected/in_use`（密码已脱敏）。

### 3.3 C/S `/health` 与 `/health/ready` —— DB 就绪 503

- `/health`（`python_service/server/main.py:155-163`）：恒 200，`database: "available"|"degraded"`（取决于启动时 `init_db` 是否成功/超时，`main.py:51-76`，受 `DB_STARTUP_TIMEOUT=30` 约束）。
- `/health/ready`（`main.py:165-177`）：数据库不可用返回 **503** `{"ready":false,"database":"unavailable","error":...}`。这是三服务中唯一"就绪失败给 503"的 Python 端点。

### 3.4 注意：run.sh 的 check_service 接受 200 或 404

`run.sh:95-107` 的 `check_service` 用 `curl ... | grep -qE "200|404"` 判定就绪——HTTP 404 也算"存活"。这对"服务在但路由没挂对"的场景不设防，深检请手动 curl 具体端点看响应体。

## 4. 启动 / 停止 / 重启操作

### 4.1 启动（make 路径）

```bash
make start          # = start-all → ./scripts/start_all_services.sh
```

`start_all_services.sh` 与 run.sh 的差异：不编译（要求二进制已存在）、.env 直接 `set -a source`（不过滤 PYTHON_CORS_ORIGINS）、启动前同样 `lsof`+`kill -9` 清端口（`start_all_services.sh:141-165`）、C++ 硬检查 10 次 / Python 与 C/S 软检查 30 次（`:241`、`:267`）。

另有单服务目标（Makefile）：`make cpp`（`cd build && ./forensic_analyzer --http-server ${HTTP_SERVER_PORT:-8080}`）、`make python`（venv 不存在时自动创建并装 httpserver 依赖）。

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

### 4.4 重启

没有专门的 restart 命令：再次执行 `./run.sh --no-build`（或 `make start`）即可——脚本会先杀掉三个端口上的残留进程再启动。C/S 场景注意：任务队列状态在 PostgreSQL，重启不丢；本地任务状态在 `data/tasks.json`，重启后 RUNNING 任务由 TaskWatchdog/load_tasks 恢复处理。

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

**仓库不提供任何 TraceLens 的 systemd unit 文件。** `setup.sh` 仅对两个外部依赖做 systemd 管理：
- Redis：`systemctl enable redis-server && systemctl start redis-server`，systemd 不可用时回退 `redis-server --daemonize yes`（`setup.sh:287-302`）；
- Neo4j：`systemctl enable --now neo4j`（`setup.sh:394-409`）。

TraceLens 三服务只能通过上述脚本/手动方式前台启动。需要开机自启时请自行编写 unit（ExecStart 分别对应 §4.2 三条命令，`WorkingDirectory` 必须正确），仓库内没有现成模板可抄。

## 与代码的对应

| 机制 | 位置 |
|------|------|
| run.sh 参数解析 | `run.sh:38-53` |
| 端口变量（8666/8090/8091 回退） | `run.sh:79-81` |
| .env 过滤（CORS/PROJECT_ROOT） | `run.sh:62-77` |
| `--clean` 清理范围 | `run.sh:113-119` |
| 启动前残留进程清理 | `run.sh:172-180`；`scripts/start_all_services.sh:141-165` |
| trap 退出清理（CS→PY→CPP） | `run.sh:184-197`；`scripts/start_all_services.sh:98-133` |
| C++ 硬健康检查 | `run.sh:206-210`；`start_all_services.sh:187-190` |
| Python/C/S 软检查 | `run.sh:239-240, 249-250`；`start_all_services.sh:241, 267` |
| check_service 接受 200/404 | `run.sh:95-107` |
| C++ 健康端点族 | `src/network/HTTPServer/routes/SystemHealthRoutes.cpp:13-31, 34-62, 79-116, 118-148` |
| Python /health、/health/ready 降级语义 | `python_service/httpserver/routes/health.py:49-67, 92-191` |
| Redis 状态端点 | `python_service/httpserver/routes/health.py:194-230` |
| C/S /health、/health/ready 503 | `python_service/server/main.py:155-177`（DB 超时 `main.py:51-76`） |
| make start/cpp/python/clean | `Makefile:52-57, 79-97, 109-114` |
| 诊断脚本 | `scripts/diagnose_services.sh`（端口/二进制/端点/LLM 五段检查） |

**最后更新**: 2026-08-24（新建，运维手册）
