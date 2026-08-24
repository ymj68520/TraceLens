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

## 13. 深挖工具箱

常规症状查不通时，按本节五件工具深挖：sqlite3 直查、三方日志对时、任务库解剖、
性能定位、已知问题索引。

### 13.1 sqlite3 常用诊断 SQL

**任务注册表（tasks.json）**——JSON 不是 SQL，配 `jq`：

```bash
TJ=build/data/tasks.json

# 全部任务的 id/状态/镜像（注意：文件内状态是大写，API 返回是小写）
jq '.tasks[] | {id, status, image_path}' $TJ | head -40

# 卡 RUNNING 的任务及其库产物
jq '.tasks[] | select(.status=="RUNNING") | {id, created_at, output_files_db, error_details}' $TJ

# 某任务的全部产物路径（raw/events/files）
jq '.tasks[] | select(.id=="task_aaa") | {output_raw_db, output_events_db, output_files_db}' $TJ
```

> 大小写陷阱：REST API 与 tasks.json 的状态值**一套小写一套大写**
> （TaskHelpers.cpp vs TaskSerialization.cpp），jq 过滤用大写、API 比较用小写。

**任务库完整性与 WAL 状态**（对任务目录下任一库）：

```bash
DB=build/data/tasks/task_aaa/files.db
sqlite3 $DB "PRAGMA integrity_check;"            # 应返回 ok
sqlite3 $DB "PRAGMA journal_mode;"               # 应为 wal（DB_JOURNAL_MODE=WAL）
ls -la build/data/tasks/task_aaa/ | grep -E '\-wal|\-shm'   # 残留大小
sqlite3 $DB "PRAGMA wal_checkpoint(TRUNCATE);"   # 手动合并 WAL（无人占用时）
sqlite3 $DB ".tables"                            # 该库到底有哪些表
sqlite3 $DB "SELECT COUNT(*) FROM files;"        # 主表行数（先看规模再看细节）
```

**时间线分布**（events.db，判断"哪天出的事"最快的 SQL）：

```bash
EDB=build/data/tasks/task_aaa/events.db
sqlite3 $EDB "SELECT date(timestamp, 'unixepoch') d, event_type, COUNT(*) c
  FROM events GROUP BY d, event_type ORDER BY d;"
sqlite3 $EDB "SELECT COUNT(*) FROM system_events;"       # 系统叙事事件量
sqlite3 $EDB "SELECT * FROM deletion_events ORDER BY timestamp DESC LIMIT 10;"
```

> 字段名以 [docs/schema/](../schema/) 各库文档为准（上表用 events 主表的
> timestamp/event_type 列；不同版本列名有差异时先 `.schema events` 看真实定义）。

### 13.2 日志关联定位法（三方对时间戳）

三个独立日志源各有时间基准，对齐后才能还原"同一时刻系统在干什么"：

| 源 | 位置 | 时间格式 |
|----|------|----------|
| C++ 应用日志 | `build/data/logs/forensics.log`（DEBUG_LOG_FILE 另出 debug.log） | 行内时间戳（本地时区） |
| 服务启动日志 | `build/logs/{cpp_server,python_service,cs_server}.log` | run.sh/进程输出 |
| Python 日志 | `build/logs/python_service.log` 或 `GET :8090/api/system/logs?lines=200` | 行内时间戳 |
| 审计库 | `forensics_audit.db`（相对服务 CWD，run.sh 下即 `build/`） | **Unix 毫秒** |

操作流程：

```bash
# ① 先在审计库锁定可疑时刻（毫秒 → 人类可读）
sqlite3 build/forensics_audit.db "SELECT datetime(timestamp/1000,'unixepoch','localtime') t,
  action, task_id FROM audit_logs WHERE task_id='task_aaa' ORDER BY timestamp;" | less

# ② 用同一时间窗 grep 两个服务日志（按上一步的 t 前后各放宽 1 分钟）
grep -n "14:23:" build/data/logs/forensics.log | head -40      # C++ 侧
grep -n "14:23:" build/logs/python_service.log | head -40      # Python 侧

# ③ 前端视角补充：/terminal 页 web Tab 收录了浏览器端请求日志（api.js 拦截器）
```

对齐要点：审计毫秒时间戳是**最权威**的排序基准（`datetime(ts/1000,'unixepoch')` 转
换）；C++/Python 日志行内时间通常是本地时区字符串，直接字符串前缀 grep 即可；三方
对出同一分钟后再看该任务的 phase/事件，基本能定位到具体模块。

### 13.3 任务库"解剖"流程（哪个表看什么）

拿到一个任务目录 `build/data/tasks/<task_id>/` 后，按依赖顺序看：

| 顺序 | 库 | 重点表 | 看什么 |
|------|----|--------|--------|
| 1 | raw.db | `files`、`partitions` | 输入全貌：文件数、分区、四时间戳、md5、is_deleted 分布 |
| 2 | events.db | `events`（主表）、`{creation,modification,access,change,deletion}_events`、`system_events` | 时间线总量与按天/类型分布；系统叙事事件 |
| 3 | files.db | `files`（主表）、24 张分类物化表（images…unknown_files）、`analysis_progress`、`file_descriptions`、`{android,windows,linux}_artifacts` | 分类结果、LLM 进度与证据、平台工件 |
| 4 | 各平台库 | android.db / windows.db / linux.db | 场景工件明细（HTTP 任务为纯名，CLI 为镜像前缀名） |
| 5 | 可选 | `_memory.db`、`_dll.db`、investigation.db | 仅对应专项任务存在 |

```bash
# 典型解剖三连：
sqlite3 raw.db "SELECT COUNT(*) total, SUM(is_deleted) deleted FROM files;"
sqlite3 files.db "SELECT category, COUNT(*) FROM files GROUP BY category ORDER BY 2 DESC;"
sqlite3 files.db "SELECT COUNT(*) FROM analysis_progress;"      # LLM 批量进度行
```

排障判读：raw 有量而 events 为 0 → 事件提取阶段失败（看任务 error_details 与审计
EVENT_EXTRACTION_* 动作）；files 主表有量而 LLM 列全空 → llm_analyze 未开或 LLM 不可达；
artifacts 表恒空 → 场景未选或分析器未接线（Windows 部分解析器"实现未接线"，见
[WindowsFilesAnalyzer](../modules/cpp/analyzers/WindowsFilesAnalyzer.md)）。

### 13.4 性能问题定位

**SQLite/WAL 层**：

```bash
ls -la build/data/tasks/<id>/                 # -wal 巨大 → 长事务未提交或进程僵死
lsof build/data/tasks/<id>/files.db           # 谁占着库（锁等待排查）
sqlite3 <db> "EXPLAIN QUERY PLAN SELECT * FROM files WHERE path LIKE '%etc%';"
# 全表扫描（SCAN）且表大 → 确认索引（idx_files_path 等，建库时创建）未被破坏
```

慢的常见根因：`files/largest` 是"假分页"——无服务端分页，Python 侧取
`page_size+offset` 全量再切片（ServiceContracts §9-6），超大任务放大传输；对策是前端
传更小 limit、或直接 sqlite3 查库绕过 API。

**LLM 队列层**：

```bash
curl http://localhost:8090/api/llm/status                       # LLM 服务状态
curl http://localhost:8090/api/llm/batch/<job_id>               # 批量 job 进度/排队
curl http://localhost:8090/api/graphiti/jobs                    # 摄取队列
redis-cli ping                                                  # 队列持久化是否退化内存
grep -E "LLM_TIMEOUT|LLM_MAX_RETRIES|batch_size" .env           # 超时/重试/批大小
```

判读：批量 job 长时间 queued → LLM 端点吞吐不足或前一批未消化；Graphiti job 卡
RUNNING → Neo4j 慢或嵌入模型未加载（缺嵌入模型在摄取时直接报错）；任务在 llm_analysis
阶段超 30 分钟无进度更新 → 会被看门狗误杀（§7），必要时调大
`TASK_WATCHDOG_STALE_MINUTES`。

**吞吐层**：并发任务各自写独立库（无锁竞争），瓶颈通常在外部（LLM/Neo4j/磁盘 IO）；
先看 `GET /api/system/health` 的 `task_management.system_load` 与
`/api/health/dependencies` 再下结论。

### 13.5 已知问题索引表

各文档已记录、尚未修复的缺陷与坑（排障时先对照，避免重复定位）：

| 症状/现象 | 根因 | 详见 |
|-----------|------|------|
| /oss 页各数据 Tab 全 404 | C++ OSS 查询路由未注册 | [web/Pages](../modules/web/Pages.md)、[CPP_REST_API §7](../api_reference/CPP_REST_API.md) |
| /analysis-center 整页错误兜底 | 误从孤儿 `common/useToast` 导入（Provider 不匹配） | [web/Pages](../modules/web/Pages.md)、[web/Components](../modules/web/Components.md) |
| 侧栏"调查图谱"点击 404 | 指向无路由的 `/investigation-graph` 死链 | [web/Pages](../modules/web/Pages.md) |
| 侧栏两项显示原始键名 | `nav.investigation_graph` 等键缺词表 | [web/I18nTheming](../modules/web/I18nTheming.md) |
| 5 个前端 hooks 零调用方 | 死代码（其一内含签名 bug） | [web/Hooks](../modules/web/Hooks.md) |
| 4 个前端页面无路由 | 死代码页面（测试仍绿） | [web/Pages](../modules/web/Pages.md) |
| 改主题不生效 | 改了 `uiSlice.setTheme`/ThemeProvider（平行假状态） | [web/Store](../modules/web/Store.md) |
| 重置设置后 Terminal 入口不变 | `resetSettings` 不含 showTerminal | [web/Store](../modules/web/Store.md) |
| PUT priority 无效果 | 端点只回显不实现 | [CPP_REST_API §1](../api_reference/CPP_REST_API.md) |
| Graphiti batch_size 三处默认不一致 | 模型 50 / Config 10 / .env 25 | [ServiceContracts §9-2](../reference/ServiceContracts.md)、[Environment](../reference/Environment.md) |
| 提取含逗号路径碎裂 | Python 列表模式是逗号拼接模拟 | [ServiceContracts §9-5](../reference/ServiceContracts.md) |
| dev 下直调 markitdown 错打 C++ | 前缀未入代理表，落 `/api` 兜底 | [ServiceContracts 附录 A](../reference/ServiceContracts.md) |
| 改端口后 Python 仍打 8080 | OfficeAnalyzer 不回退 PYTHON_HTTP_PORT | [ServiceContracts §9-9](../reference/ServiceContracts.md) |
| C++ 返回 HTML 被报"Backend returned HTML" | SPA 首页被折叠为错误 | [ServiceContracts §9-7](../reference/ServiceContracts.md) |
| 事件关联表恒空 | EventCorrelationEngine 未接流水线 | [modules/README](../modules/README.md) |
| 数据库取证不产出 | DatabaseAnalyzer 未接线（仅单测） | [modules/README](../modules/README.md) |
| 视觉分析无效果 | VisionAnalysis 死代码 | [modules/README](../modules/README.md) |
| MCP 端口不监听 | MCPIntegration 无生产调用方 | [modules/README](../modules/README.md) |
| 仓库根出现 forensics_audit.db | 审计库默认相对 CWD，PathManager 未接线 | [AuditLog §7](../modules/cpp/core/AuditLog.md) |
| `/api/system/logs/stream` 404 | system_logs.py 的 router 未注册（死代码） | [Python_REST_API §15](../api_reference/Python_REST_API.md) |
| legacy 案情分析报 410 | 端点已退役，须走报告生成 | [Python_REST_API §4](../api_reference/Python_REST_API.md)、[ErrorCodes](../reference/ErrorCodes.md) |
| run.sh 与 .env 端口口径打架 | run.sh 兜底 8666、其余默认 8080 | 本文 §1、[ServiceContracts 附录 B](../reference/ServiceContracts.md) |
| tasks.json 与 API 状态值大小写不同 | 序列化层两套字面量 | [TaskManager](../modules/cpp/network/TaskManager.md) |

---

| /analysis-center 整页崩溃 | 孤儿 useToast 导入 | web/Pages 已知问题 |
| 侧栏 /investigation-graph 死链 | 路由不存在 | web/Pages |
| 侧栏 nav 键显示原文 | en/zh 词表缺键 | web/I18nTheming |
| useFileLLMAnalysis 参数形态错 | 对象当第一参 | web/Hooks（死 hook） |
| TaskSelector 与侧栏清单不一致 | 两份清单不同步 | web/Overview |
| Office 错误前缀误判为内容 | "Error parsing DOCX:"/"Warning:" 不匹配 | OfficeAnalyzer |
| OSS AI filter 一调 500 | bucket 形参不匹配 | OssAnalysis |
| OSS 路由补注册即悬垂 | 聚合器栈对象捕获 this | OSSRoutes |
| wechat invalidate 无效 | 每请求新建实例 | WeChatGraphService |
| 案例级图谱曾静默为空 | 缺 Path 导入（已修 447714a） | GraphitiService |
| wait_for_job_completion 死等 | 终态不含 error/unknown | LLMPythonProxy |
| PUT /api/cases/{id}/* 200 空对象 | update 静默 no-op | CaseManager |
| 命令 TTL 无后台清扫 | 仅 expire 端点 | server/Services |
| /health/ready 启动快照 | 中途宕库不变红 | server/Main |
| GRAPHITI_BATCH_SIZE 三默认 | 50/10/25 | Environment |
| --overwrite/--dll-threshold 死参数 | 解析后无消费者 | CLI |
| --xfs-mode 非法仅警告 | 与 android-source 不一致 | CLI |
| run_server reload/workers 不生效 | 传对象需字符串工厂 | httpserver/Main |
| llm_files_test 等脱离 ctest | 独立 main 无 add_test | CppTestCatalog |
| 孤儿 python 测试不被收录 | 根目录无 pytest 配置 | PythonTestCatalog |
| create_pe_sample 旧路径已断 | 硬编码工程路径 | TestFixtures |
| 审计轮转/保留未接线 | rotate/cleanup 无调用方 | AuditLog |

## 14. 获取帮助

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

**最后更新**: 2026-08-24（扩充：高级工作流/深挖工具箱/产出导览）
