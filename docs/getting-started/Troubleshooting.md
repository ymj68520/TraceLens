# 故障排查指南

本文档按"症状 → 原因 → 命令"组织 TraceLens 的常见问题诊断。所有端点、路径、参数均与当前代码一致。

端口速查：

| 端口 | 服务 |
|------|------|
| 8666 | `./run.sh` 启动的 C++ 服务（`HTTP_SERVER_PORT` 未设置时的兜底默认） |
| 8080 | C++ 服务默认端口（`.env.example` / `make cpp` / `--http-server` 无参时） |
| 8090 | Python httpserver |
| 8091 | 分布式 C/S server（`PORT`） |
| 7687 / 7474 | Neo4j Bolt / 浏览器 |
| 8890 | MCP server |
| 3000 | vite 开发服务器 |

---

## 1. 健康检查

```bash
# C++ 服务（8666 为例）
curl http://localhost:8666/api/system/health      # 别名 /api/health
curl http://localhost:8666/api/health/live
curl http://localhost:8666/api/health/ready
curl http://localhost:8666/api/health/dependencies

# Python httpserver
curl http://localhost:8090/health
curl http://localhost:8090/health/live
curl http://localhost:8090/health/ready
#   - C++ 后端是硬依赖：断开时 ready=false（checks.cpp_backend=disconnected）
#   - Neo4j / LLM / Redis 为可选依赖：失败仅降级，不阻断启动

# 分布式 C/S server
curl http://localhost:8091/health           # database: available / degraded
curl http://localhost:8091/health/ready     # 数据库不可用时返回 503
```

`./run.sh` 的启动健康检查行为：C++ 服务失败会**硬失败并退出**（打印日志尾部）；Python 与 C/S 失败只打警告，不阻断。

---

## 2. 日志

| 来源 | 位置 / 获取方式 |
|------|----------------|
| run.sh 启动的三个服务 | `build/logs/cpp_server.log`、`build/logs/python_service.log`、`build/logs/cs_server.log` |
| C++ 运行时 | `<DATA_DIR>/logs/`（默认 `data/logs/`，相对可执行文件，即 `build/data/logs/`），文件名由 `.env` 的 `LOG_FILE=forensics.log` 与 `DEBUG_LOG_FILE=debug.log` 决定 |
| C++ 日志 API | `GET http://localhost:8666/api/system/logs` |
| Python 日志 API | `GET http://localhost:8090/api/system/logs?lines=200&level=ERROR`（解析本服务日志）；`GET /api/system/logs/{service}`（cpp/python，读取 `build/logs/` 下对应文件）；`GET /api/system/logs-stream/{service}`（SSE 流式） |

```bash
tail -f build/logs/cpp_server.log
tail -f build/logs/python_service.log
tail -f build/data/logs/forensics.log      # C++ 应用日志（路径相对二进制）

# 提高日志级别复现问题
# .env: LOG_LEVEL=DEBUG  DEBUG_OUTPUT_MODE=stdout
```

---

## 3. 端口被占用

**症状**：`Failed to bind` / 服务起不来 / 前端拿不到数据。

```bash
lsof -i :8666    # 或 8080/8090/8091
```

`./run.sh` 启动前会自动 `lsof -ti :<port>` 并 `kill -9` 残留进程；手动启动时需自行清理：

```bash
kill -9 $(lsof -ti :8090)
# 或换端口：.env 设 HTTP_SERVER_PORT，然后 ./run.sh
```

---

## 4. Redis 未安装/未运行（摄取任务不持久化）

**症状**：Python 日志出现 `Redis not available, using in-memory storage`；重启后 Graphiti 摄取任务状态丢失。

**原因**：`IngestionJobManager` 优先用 Redis（`redis_url`），连不上自动退化为进程内存。

```bash
redis-cli ping                    # 非 PONG 即未运行
sudo apt-get install -y redis-server redis-tools
sudo systemctl enable --now redis-server
```

---

## 5. Neo4j 连接失败（Graphiti 降级）

**症状**：`GET /api/graphiti/status` 显示 disabled；知识图谱相关接口不可用，但服务本身正常。

**原因**：Neo4j 未启动或 `NEO4J_PASSWORD` 不匹配。GraphitiService 连接失败会标记 disabled（降级，不阻断）。

```bash
sudo systemctl status neo4j
sudo systemctl enable --now neo4j
grep NEO4J_ .env                  # NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD
# setup.sh 安装 Neo4j 时会用环境变量或 .env 中的 NEO4J_PASSWORD 设置初始密码：
sudo -u neo4j neo4j-admin dbms set-initial-password '<密码>'   # 仅首次
```

Graphiti 全功能还要求 LLM 端点同时加载 `openai/gpt-oss-20b` 与 `text-embedding-nomic-embed-text-v1.5`（`.env.example` 注释），缺嵌入模型会在摄取时报错。

---

## 6. LLM 连不上 / 模型名不对

**症状**：AI 分析报 `LLMConnectionFailed`(200) 或超时；报告缺少 LLM 描述。

```bash
# 1. 端点可达性（.env.example 默认是局域网 LM Studio：192.168.31.170:1234）
curl http://192.168.31.170:1234/v1/models

# 2. 模型名必须与 LLM_TEXT_MODEL / LLM_VISION_MODEL 完全一致
grep LLM_ .env

# 3. 实测一次 chat
curl -X POST http://192.168.31.170:1234/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "<LLM_TEXT_MODEL 的值>", "messages": [{"role": "user", "content": "ping"}]}'

# 无 LLM 环境先跳过 AI
./build/forensic_analyzer image.dd --no-ai
```

超时可调 `LLM_TIMEOUT_SECONDS`（默认 120）/ `LLM_MAX_RETRIES`（默认 3）。

---

## 7. 任务卡在 RUNNING

**症状**：任务长时间 RUNNING 无进展。

**原因与机制**：C++ `TaskWatchdog` 每 **60 秒**巡检一次：RUNNING 任务超过 `TASK_WATCHDOG_STALE_MINUTES`（默认 **30 分钟**）无进度更新会被标记 FAILED（错误详情写明 inactivity）；PENDING 超过 `TASK_WATCHDOG_PENDING_MINUTES`（默认 30 分钟）同样处理。任务持久化在 `data/tasks.json`。

```bash
curl http://localhost:8666/api/tasks/<task_id>/progress
curl -X POST http://localhost:8666/api/tasks/cleanup      # 手动清理
tail -f build/data/logs/forensics.log | grep -i watchdog
```

若确属误杀（超大镜像单阶段超 30 分钟），可在 `.env`/配置中调大 `TASK_WATCHDOG_STALE_MINUTES` 后重启 C++ 服务。

---

## 8. 前端访问不了 / 请求 404

**症状**：页面空白或 API 404。

**要点**：生产模式 SPA 由 **C++ 服务托管**（从二进制相对路径 `web/dist` 读取，run.sh 会同步 `build/web/dist`），必须访问 C++ 端口：

```bash
# 正确：http://localhost:8666/（run.sh 默认）
# 错误：访问 8090/8091 不会有前端页面

# 若 run.sh --no-web 跳过了前端构建，dist 不存在 → 重新构建
./run.sh            # 或 cd web && npm run build 后重跑
```

开发模式（`make web-dev`，端口 3000）出问题时查 `web/vite.config.js` 代理表：

- `/tasks` 与兜底 `/api` → C++（目标取 `VITE_CPP_PROXY_TARGET` 或 `http://localhost:${HTTP_SERVER_PORT || 8080}`，并向上读取仓库根 `.env`）；
- `/api/{reports,graphiti,llm,office,db,wechat,investigation}` → `http://localhost:8090`；
- `/csapi` → `http://localhost:8091`（重写去掉前缀）。

跨机访问 dev 模式时注意 C++ 实际端口与代理目标是否一致。

---

## 9. Python 服务启动慢/卡住（分层超时）

**机制**：`PYTHON_STARTUP_TIMEOUT=30s` 是启动总预算；C++ 后端为硬依赖，Neo4j/LLM/Redis 等可选服务各受 `OPTIONAL_SERVICE_INIT_TIMEOUT=12s` 约束。超时会回滚已初始化的项，但服务仍以**降级模式**启动（不是启动失败）。

```bash
# 诊断顺序
curl http://localhost:8090/health/ready            # 看 checks 各项
curl http://localhost:8666/api/system/health       # 确认 C++ 正常
tail -f build/logs/python_service.log

# 回连地址错了（C++ 不在 8080）
grep CPP_BACKEND_URL .env     # .env.example 默认 http://localhost:8080
                              # run.sh 用 8666 时应改为 http://localhost:8666
```

---

## 10. 构建缺库 / CMake 找不到包

**症状**：`cmake ..` 报 `Could not find HIVEX/LIBEVTX/...` 或链接失败。

**原因**：以下三项**不在 apt，必须源码安装**（setup.sh 已自动化）：

- The Sleuth Kit 4.14.0 → `/usr/local/lib/libtsk.so`
- Crow → `/usr/local/include/crow.h`
- 阿里云 OSS C++ SDK → `libs/aliyun-oss-cpp-sdk/build/lib/libalibabacloud-oss-cpp-sdk.a`

```bash
sudo bash setup.sh                          # 最省事（幂等）
ldconfig -p | grep -E "libtsk|libewf"       # 验证
tail -100 build/cmake-configure.log         # setup.sh 留下的配置日志
tail -100 build/forensic_analyzer-build.log # 构建日志
```

运行时报 `libtsk.so: cannot open shared object file`：

```bash
sudo ldconfig
export LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH   # 临时
```

---

## 11. 数据库锁 / 损坏

```bash
lsof <镜像>_raw.db                    # 谁占着
sqlite3 <db> "PRAGMA integrity_check;"
sqlite3 corrupted.db ".dump" | sqlite3 recovered.db
```

`.env` 默认 `DB_JOURNAL_MODE=WAL`，残留 `-wal/-shm` 文件在持有进程退出后自动合并；异常退出后可用上述 dump 恢复。

---

## 12. 错误码对照

错误码定义在 `src/core/ErrorHandling/ErrorHandling.h`：

| 区间 | 类别 | 示例 |
|------|------|------|
| 100-199 | 文件错误 | 100 FileNotFound、101 FileReadError、102 FileWriteError、103 FileAccessDenied、105 FileEmpty |
| 200-299 | LLM 错误 | 200 LLMConnectionFailed、201 LLMRequestFailed、202 LLMResponseParseError、203 LLMTimeout、204 LLMRateLimited、205 LLMContextOverflow |
| 300-399 | 模型错误 | 300 NoModelsAvailable、301 ModelNotFound、302 AllModelsFailed |
| 400-499 | 配置错误 | 400 InvalidConfiguration、401 ConfigNotLoaded、402 MissingConfigKey |
| 500-599 | 数据库错误 | 500 DatabaseOpenError、501 DatabaseQueryError、502 DatabaseWriteError、503 DatabaseNotInitialized |
| 600-699 | 分析错误 | 600 AnalysisFailed、601 ContentTooLarge、602 UnsupportedFileType、603 ChunkingFailed |
| 900-999 | 通用错误 | 900 Unknown、901 InternalError、902 NotImplemented、903 Cancelled |

---

## 13. 获取帮助

提交 Issue 前请收集：

```bash
uname -a && gcc --version | head -1 && cmake --version | head -1
./build/forensic_analyzer --version
tail -100 build/logs/cpp_server.log
tail -100 build/logs/python_service.log
cat .env          # 注意抹去密码/key
```

- GitHub Issues: https://github.com/ymj68520/TraceLens/issues
- C++ API 文档：`http://localhost:<C++端口>/api/docs`（Swagger）
- Python API 文档：`http://localhost:8090/docs`、`http://localhost:8091/docs`

---

## 相关文档

- **[安装指南](Installation.md)** - 依赖与 `.env`
- **[快速入门](QuickStart.md)** - 一键路径
- **[常见任务](CommonTasks.md)** - 工作流与 API 用法

---

**最后更新**: 2026-08-23（以代码为准重写）
