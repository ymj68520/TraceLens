# 跨服务契约目录：C++ ↔ Python ↔ 前端

> 覆盖四类契约：C++→Python 的 HTTP 调用对、Python→C++ 的调用对、
> 前端↔双后端的代理与 axios 客户端、任务目录/数据库后缀的发现契约。
> 每条给出请求/响应字段要点与 file:line（相对仓库根）。
> 涉及文件：`src/network/HTTPServer/LLMPythonProxy.{h,cpp}`、`src/integration/LLMIntegration/MarkitdownProxy.{h,cpp}`、
> `src/analyzers/OfficeAnalyzer/OfficeAnalyzer.cpp`、`src/network/HTTPServer/CaseManager.{h,cpp}`、
> `python_service/httpserver/services/cpp_backend.py`、`python_service/httpserver/routes/graphiti_endpoints/*`、
> `web/vite.config.js`、`web/src/services/api.js`、`src/core/PathManager/PathManager.cpp`、
> `src/network/HTTPServer/routes/RouteHelpers.cpp` 等。

## 1. 拓扑总览

```text
浏览器 ──(dev: vite:3000 代理 / prod: 同源)──┬─ C++ forensic_analyzer :8080
                                            └─ httpserver(FastAPI) :8090
C++ :8080 ──LLMPythonProxy/MarkitdownProxy/OfficeAnalyzer──▶ Python :8090
Python :8090 ──CppBackendService / multi_analysis 回写──▶ C++ :8080
浏览器 ──csApi──▶ 分布式 C/S server :8091 ──PostgreSQL
http_agent（现场机）──▶ C/S :8091，本地拉起 CLI（http_agent/command_executor.cpp）
```

基址约定：C++ 调 Python 用 `ConfigManager::getPythonServiceUrl()`
（`PYTHON_SERVICE_URL`，否则 `http://localhost:<PYTHON_HTTP_PORT>`，ConfigManager.cpp:142）；
Python 调 C++ 用 `settings.cpp_backend_url`（`CPP_BACKEND_URL`，httpserver/config.py:141）。

## 2. C++ → Python：LLMPythonProxy（Graphiti 作业面）

单例持 Python 基址（LLMPythonProxy.h:68-71）。全部为同步 httplib 调用，
连接超时 5-10s、读超时 10-30s。

| # | 方法 | HTTP | 请求要点 | 响应要点 | C++ / Python |
|---|---|---|---|---|---|
| 1 | `isServiceAvailable` | GET `/health` | — | 200 即可用 | LLMPythonProxy.cpp:12-23 |
| 2 | `deleteGraphitiData` | DELETE `/api/graphiti/tasks/{task_id}` | body `{"task_id"}`；200 或 404 都算成功（幂等删除） | — | cpp:25-43；py:`graphiti_endpoints/_admin.py:79` |
| 3 | `async_ingest` | POST `/api/graphiti/ingest` | `{"task_id", "mode"}`；mode ∈ `full/files_only/events_only/single_file`（h:25-33） | `{"job_id","status":"PENDING","message"}`；取 `job_id` | cpp:49-86；py:`_ingest.py:27-87` |
| 4 | `async_ingest_file` | POST `/api/graphiti/ingest/file` | `{"file_id":int64, "task_id", "update_analysis":bool}` | 同上 | cpp:88-122；py:`_ingest.py:88-141` |
| 5 | `async_ingest_events` | POST `/api/graphiti/ingest/events` | `{"task_id", "events":[...]}` | 同上 | cpp:124-156；py:`_ingest.py:142+` |
| 6 | `get_job_status` | GET `/api/graphiti/jobs/{job_id}` | — | `status/progress/current_phase/created_at/started_at/completed_at/error/result`（JobStatus 映射，h:38-52）；404 时 C++ 置 `status="not_found"` | cpp:158-195；py:`_jobs.py:24-70` |
| 7 | `cancel_job` | DELETE `/api/graphiti/jobs/{job_id}` | — | `{"success":bool}`；404→false | cpp:197-218；py:`_jobs.py:72` |
| 8 | `wait_for_job_completion` | （轮询 #6） | 轮询 3s、超时 3600s，回调 `(progress, phase)` | COMPLETED→true；FAILED/CANCELLED/not_found→false | cpp:220-253 |

**契约漂移点**：
- 端点名是 `/api/graphiti/ingest/file`（单数 `file`），**不是** `ingest-file`（cpp:104）。
- Python `IngestionMode` 多一个 `analyzed_only`（graphiti_models.py:21-27），C++ 侧枚举不发该值。
- Python `IngestRequest` 还有 `include_llm_descriptions/batch_size/max_episodes` 字段
  （models.py:34-40），C++ 不传，全部走服务端默认。
- Python 状态统一大写化后返回（`_jobs.py:52`），C++ 按大写字面量比较（cpp:242-244）。

### 2.1 Graphiti 请求/响应模型字段（Python 侧权威定义）

`python_service/httpserver/routes/graphiti_models.py`：

| 模型 | 字段 | 位置 |
|---|---|---|
| `IngestRequest` | `task_id:str`（必填，兼作图命名空间）、`mode:full`（默认）、`include_llm_descriptions:True`、`batch_size:50(1..500)`、`max_episodes:100(0..10000)` | models.py:34-40 |
| `FileIngestRequest` | `file_id:int`（必填）、`task_id:str`（必填）、`update_analysis:False` | models.py:43-46 |
| `EventSyncRequest` | `task_id:str`、`events:List[Dict]`（均必填） | models.py:49-52 |
| `IngestionResponse` | `job_id:str`、`status:str`、`message:str`（均必填）——C++ 只消费 `job_id` | models.py:55-59 |
| `JobStatusResponse` | `job_id/status/progress:int/current_phase/created_at`（必填）+ `started_at/completed_at/error/result`（可选）——与 C++ `JobStatus` 一一对应 | models.py:62-71 |

注意 `IngestionResponse` 与旧版 `IngestResponse`（`success/task_id/job_id?/message/
entities_created/relationships_created/timestamp`，models.py:74-82）是两个模型，
作业型端点返回前者；C++ 永远只读 `job_id`，多余字段无害。

### 2.2 Graphiti 作业生命周期时序（一次 ingest 的完整往返）

```text
C++ (TaskManager 尾部触发, TaskManagerAnalysis.cpp:177-179)
  │ POST /api/graphiti/ingest {task_id, mode}
  ▼
Python _ingest.py:27
  │ ① cpp_backend.check_task_exists(task_id)   ← 回调 C++ GET /api/tasks/{id}
  │ ② ingestion_job_manager.queue_ingestion(...) 或降级 graphiti_service
  ▼ 返回 {job_id, status:"PENDING", message}
C++ 轮询 GET /api/graphiti/jobs/{job_id}（默认 3s 间隔, 3600s 超时）
  │ status: PENDING → RUNNING(progress%, current_phase) → COMPLETED | FAILED | CANCELLED
  ▼（异常路径）
C++ DELETE /api/graphiti/jobs/{job_id}（取消）或 DELETE /api/graphiti/tasks/{task_id}（清图）
```

## 3. C++ → Python：MarkitdownProxy（文档转 Markdown）

单例基址同上（MarkitdownProxy.cpp:20-25）。安全前提：所有路径必须共享一个
`workspace_root`（公共前缀计算 cpp:27-58），不共享即客户端侧拒绝，不发请求。

| # | 方法 | HTTP | 请求要点 | 响应要点 | 位置 |
|---|---|---|---|---|---|
| 1 | `convertToMarkdown` | POST `/api/markitdown/convert` | `{"file_path", "workspace_root"}` | `{"success":bool,"content":str,"error"}`；失败时 C++ 返回以 `"Error: "` 开头的字符串 | cpp:133-206（POST :147/:173）；py:`markitdown.py:141` |
| 2 | `convertOneToMarkdown` | POST `/api/markitdown/convert-one` | `{"input_root","input_file","output_root","workspace_root"}` | `{"status":"converted/skipped/failed","output_path","output_size","error"}`；HTTP≥500 → ServiceError，≥400 → Failed | cpp:66-131（POST :89/:94）；py:`markitdown.py:400` |
| 3 | `batchConvertToMarkdown` | POST `/api/markitdown/batch-convert` | `{"input_dir","output_dir","workspace_root"}` | `{"success","total_files","converted","skipped","failed"}` | cpp:226-288（POST :246）；py:`markitdown.py:523` |
| 4 | `isServiceAvailable` | GET `/api/markitdown/status` | — | `{"available":bool}` | cpp:208-224；py:`markitdown.py:225` |

## 4. C++ → Python：OfficeAnalyzer（表格/幻灯解析）

- 端点：`POST {pythonServiceUrl}/api/office/parse`，body `{"file_path": ...}`
  （OfficeAnalyzer.cpp:105-110）。
- 仅 `.xlsx/.xls/.pptx/.ppt` 走该服务（:82-96）；`.docx` 用本地 duckx，`.doc` 用 antiword（:47-80）。
- 响应：`{"success":bool, "content":str, "error"}`（:133-141）；curl 总超时 60s（:121）。
- **基址特例**：直接 `getenv("PYTHON_SERVICE_URL")`，缺省硬编码 `http://localhost:8090`，
  **不回退 PYTHON_HTTP_PORT**（OfficeAnalyzer.cpp:21）。FileAnalyzer 会用
  ConfigManager 的 URL 覆盖它（FileAnalyzer.cpp:173）。
- Python 侧：`office.py:39`（`/parse`）、`office.py:151`（`/supported-types`，后者 C++ 不调）。

## 5. C++ ↔ Python：案件（Case）跨镜像分析 job

C++ 的 CaseManager 持久化 `cross_analysis_job_id`（CaseManager.h:55-56；
CaseCRUDRoutes.cpp:144-145 接收、:169 回显；cases.json 持久化 CaseManager.cpp:129,161）。
作业本体在 Python 侧：

| 步骤 | 调用 | 字段要点 | 位置 |
|---|---|---|---|
| 发起 | POST `/api/llm/multi-image-analysis` | `{"case_id","task_ids":[],"files_db_paths":[],"case_description","max_filter_files"}`；两数组等长（400）；files_db_paths 为**弃用的精确校验提示**，权威路径服务端从 task 解析 | multi_analysis.py:220-249 |
| 回写状态 | PUT `{cpp_backend_url}/api/cases/{case_id}/status` | `{"status":"analysing","cross_analysis_job_id"}` → 运行完 `completed` / 失败 `failed`；失败不阻断 | multi_analysis.py:266-274,291-305；C++ 侧 CaseCRUDRoutes.cpp:144-145 |
| 轮询 | GET `/api/llm/multi-image-analysis/{job_id}` | 返回内存 job dict：`job_id/case_id/status(running/completed/failed)/progress{stage,message}/result/error`；404=job 不存在 | multi_analysis.py:311-317 |
| 关联 | POST `/api/llm/cases/{case_id}/tasks`、`/associate-tasks`、`smart-create`、增量分析 | 见该文件 :163-216、:322-418 | multi_analysis.py |

## 6. Python → C++：CppBackendService（13 个方法 / 10 个端点）

`python_service/httpserver/services/cpp_backend.py`。公共行为：httpx 连接池
（:54-58）；`_request` 重试 3 次、**响应为 text/html 时折叠为
`{"success":false,"error":"Backend returned HTML"}`**（:100-109）、≥400 折叠为
`{"success":false,"error":<body>,"status":<code>}`（:110-118）、异常折叠为
`{"success":false,"error":"<异常类型名>"}`（:124-131）。

| # | 方法 | HTTP 端点 | 请求要点 | 响应要点 | 位置 |
|---|---|---|---|---|---|
| 1 | `health_check` | GET `/api/health` | — | 仅看状态码 200 | :136-148 |
| 2 | `list_tasks` | GET `/api/tasks/list` | `page/page_size/status` | 任务分页对象 | :152-172 |
| 3 | `get_task` | GET `/api/tasks/{task_id}` | task_id URL-quote；`.`/`..` 拒绝 | 返回体须含相同 `id` 否则判 None；**补齐 `image_name`←`image_path`** | :174-201 |
| 4 | `check_task_exists` | （复用 #3） | — | bool | :203-206 |
| 5 | `get_task_databases` | GET `/api/tasks/{task_id}/databases` | — | `{"databases":[{type,path,name}...],"count"}` | :208-211；C++ 产 TaskCRUDRoutes.cpp:527-582 |
| 6 | `get_task_files` | GET `/api/forensics/files/largest` | `task_id/limit` | 兼容裸数组或 `{"largest_files"|"files"}`；**file_types 过滤在客户端做** | :215-236 |
| 7 | `get_task_files_paginated` | GET `/api/forensics/files/largest` | `limit=page_size+offset` | **分页/类型/扩展名/已删除过滤全在客户端做**，返回 `{files,total_count}` | :238-283 |
| 8 | `get_task_events` | GET `/api/forensics/timeline/comprehensive` | `task_id/limit/offset/event_type/start_time/end_time` | 兼容 `{timeline,metadata.total_events}` 或裸数组 → `{events,total_count}` | :287-322 |
| 9 | `extract_files` | POST `/api/forensics/extract` | `{"task_id","mode":"name","pattern":paths.join(","),"output_dir","overwrite"}`——**列表模式是逗号拼接模拟** | 含 `job_id` | :326-356 |
| 10 | `get_extraction_status` | GET `/api/forensics/extract/status` | `job_id` | 进度/结果 | :358-369 |
| 11 | `export_toon` | GET `/api/forensics/export/toon` | `task_id/include_llm` | 原始 TOON 文本（不走 `_request`，`raise_for_status`） | :373-385 |
| 12 | `get_files_toon_stream` | （复用 #11） | `batch_size/include_llm` | **客户端切分** `TOON.schema:` 行与数据行 → `{schema,data_lines,total_files,batch_size}` | :387-427 |
| 13 | `export_json` | GET `/api/forensics/export/events/json` | `task_id` | dict 或 `{"data":...}` | :429-442 |

**客户端侧补齐汇总**（服务端能力缺口在 Python 侧模拟）：任务字段别名（#3）、
文件过滤（#6）、完整分页（#7）、事件包格式归一（#8）、列表提取（#9）、
TOON 流切分（#12）。

**该文件之外的 Python→C++ 调用**：
- PUT `/api/tasks/{task_id}`，body `{"case_description"}`（案情描述回写，容忍非 200/204）
  ——`case_analysis_endpoints/_case.py:60-67`。
- PUT `/api/cases/{case_id}/status`（第 5 节）。
- Graphiti ingest 前的 `check_task_exists`（`_ingest.py:55,111`）——即 C++ 发起的
  ingest 会在 Python 侧回调 C++ 验证任务存在，形成一次往返。

## 7. 前端 ↔ 双后端

### 7.1 vite 开发代理前缀表（web/vite.config.js:20-64，dev server :3000）

| 前缀 | 目标 | 说明 |
|---|---|---|
| `/csapi` | `http://localhost:8091` | **rewrite 去掉 `/csapi` 前缀**（:25-27），指向 C/S server |
| `/tasks` | `{cppTarget}` | C++ 后端 |
| `/api/reports` | `http://localhost:8090` | Python（报告族） |
| `/api/graphiti` | `http://localhost:8090` | Python |
| `/api/llm` | `http://localhost:8090` | Python |
| `/api/office` | `http://localhost:8090` | Python |
| `/api/db` | `http://localhost:8090` | Python |
| `/api/wechat` | `http://localhost:8090` | Python |
| `/api/investigation` | `http://localhost:8090` | Python |
| `/api`（兜底） | `{cppTarget}` | 其余 API 归 C++ |

`cppTarget = VITE_CPP_PROXY_TARGET || http://localhost:${HTTP_SERVER_PORT||8080}`
（:9-10，可读父目录 .env）。**生产不走代理**：前端构建产物由 C++ 以静态文件托管
（HTTPserver.cpp:109-151，`web/dist`），Python/C/S 走绝对地址直连（见下）。

dev 与 prod 的双形态：

| 形态 | C++ API | Python API | C/S API |
|---|---|---|---|
| dev（vite :3000） | 相对路径（`/api`、`/tasks` 经代理） | 相对路径（`/api/llm` 等经代理）或 pythonApi 绝对地址 | `/csapi` 代理剥离前缀，或 csApi 绝对地址 |
| prod（C++ 托管 :8080） | 同源相对路径（默认 `api` 客户端） | `http://<host>:8090` 绝对地址（pythonApi） | `http://<host>:8091` 绝对地址（csApi） |

`.env` 的 `VITE_CPP_PROXY_TARGET / VITE_API_BASE_URL / VITE_PYTHON_API_URL /
VITE_CPP_API_URL / VITE_CS_API_URL / VITE_CPP_PORT` 只影响前端构建/开发期
（vite.config.js:9-10；api.js:4,21-26,131-132），与后端进程无关。

### 7.2 三个 axios 客户端（web/src/services/api.js）

| 客户端 | baseURL | 超时 | token | 401 行为 | 位置 |
|---|---|---|---|---|---|
| `api`（默认导出） | `VITE_API_BASE_URL` 或空（同源/代理 → C++） | 30s | `localStorage.auth_token` → `Authorization: Bearer` | 清 token 并跳 `/login` | :29-35,47-90 |
| `pythonApi` | `VITE_PYTHON_API_URL` 或 `http://<当前host>:8090`（动态 host，跨机可访） | 60s（LLM 慢） | 无 | 不特殊处理 | :38-44,92-125 |
| `csApi` | `VITE_CS_API_URL` 或 `http://<当前host>:8091` | 30s | `localStorage.cs_auth_token`（**与本地 token 分离**） | 仅清 `cs_auth_token`，**不跳转** | :131-184 |

token 约定：两类 token 独立存储（`auth_token` vs `cs_auth_token`，:142 注释）；
均以 `Authorization: Bearer <jwt>` 头发送；`currentHost()` 动态推导解决跨机访问时
`localhost` 指向客户端自身的问题（:12-17）。

## 8. 任务目录与数据库后缀发现契约

### 8.1 生产端：谁在什么路径落什么库

| 场景 | 路径规则 | 位置 |
|---|---|---|
| CLI 分析 | `<--db-dir>/<镜像stem>_raw/_filtered/_files/_events.db`；无 db-dir 即当前目录 | AnalysisOrchestrator.cpp:200-202,228 |
| CLI 内存 | `<stem>_memory.db` | AnalysisOrchestrator.cpp:543 |
| CLI DLL | `<stem>_dll.db` | AnalysisOrchestrator.cpp:346 |
| HTTP 任务（默认） | `data/tasks/<task_id>/{raw,events,files,android,oss,windows,linux}.db`（**纯名，无镜像前缀**） | TaskManagerAnalysis.cpp:104-109；PathManager.cpp:102-115 |
| HTTP 任务（legacy db_output_dir） | `<dir>/<镜像stem>_raw/_events/_files.db`；filter 时 `_raw.db`→`_filtered.db`（无后缀则 `.filtered`），并把 `output_raw_db` 指向过滤库 | TaskManagerAnalysis.cpp:96-102,264-296 |
| 平台分析器默认 | `<imagePath>_windows.db` / `_linux.db`（Orchestrator 显式改指 files.db） | WindowsFilesAnalyzerCore.cpp:34；LinuxFilesAnalyzerCore.cpp:52 |
| 调查库 | 与任务可信库同目录的 `investigation.db` | httpserver/services/investigation/paths.py:16-37 |

### 8.2 发现端 A：C++ `RouteHelpers::get_database_path`（RouteHelpers.cpp:35-90）

| db_type | 解析顺序 |
|---|---|
| `raw`/`events`/`files` | 直接取任务字段 |
| `android` | ① `metadata["android_db"]`（存在时）② `<files.db 目录>/android.db`（任务目录纯名）③ `<raw 去扩展名>_android.db`（legacy 前缀名）④ 兜底 files.db |
| `dll` | ① `metadata["dll_db"]` ② `<raw 去扩展名>_dll.db` |
| `memory` | ① `metadata["memory_db"]` ② `<raw 去掉 .db 与末尾 _raw>_memory.db`（`img_raw.db`→`img_memory.db`，**不是** `img_raw_memory.db`） |

### 8.3 发现端 B：Python

| 机制 | 规则 | 位置 |
|---|---|---|
| 任务权威解析 | `output_files_db/output_files_db_path` 为唯一持久化目标；工作区=三库父目录必须一致；客户端传路径仅做**精确相等**校验 | task_store.py:66-101,104-119 |
| 任务库清单 | GET `/api/tasks/{id}/databases` → `{type,path,name}` 数组（raw/events/files 三类） | TaskCRUDRoutes.cpp:549-577 |
| 原始库回退 | `raw_db = output_raw_db or files_db.replace("_files.db","_raw.db")` | associations.py:176-178,339-342 |
| 后缀工厂 | `DB_SUFFIXES = {_raw,_files,_events,_windows,_linux,_android}.db`；从任一库路径剥后缀得 base；**每个后缀还回退纯名**（`files.db` 等，适配任务目录布局） | graphiti_integration/database_reader.py:85-92,114-140 |

### 8.4 后缀总表（跨服务共识）

| 后缀 | 内容 | 生产者 | 消费者示例 |
|---|---|---|---|
| `_raw.db` / `raw.db` | TSK 全量文件表（含四时间戳） | ImageAnalyzer / TaskManager | associations.py、database_reader.py |
| `_filtered.db` | 过滤后子集（CLI 与 HTTP 均可能产出） | FileFilter | 下游 effective raw |
| `_files.db` / `files.db` | 分类+平台工件统一库 | FileClassifier+各平台分析器 | LLM/报告/图谱主数据源 |
| `_events.db` / `events.db` | 时间线 | EventExtractor | timeline 路由 |
| `_android.db` / `android.db` | Android 工件 | AndroidAnalyzer | MIUI 查询路由 |
| `_windows.db` / `windows.db` | Windows 工件 | WindowsFilesAnalyzer | `_windows.py:61,121` |
| `_linux.db` / `linux.db` | Linux 工件 | LinuxFilesAnalyzer | LinuxLLMAnalysisService |
| `_memory.db` | 内存取证结果 | MemoryAnalyzer | MemoryForensicsRoutes（只读，缺失 404） |
| `_dll.db` | DLL 分析 | DLLAnalyzer | DLL 路由（metadata 优先） |
| `investigation.db` | 调查工作台 | Python | investigation/paths.py |

## 8.5 典型任务全链路（各契约的串联顺序）

```text
① 前端 → C++   POST /api/tasks（创建任务，含 android_source/filter_profile 等）
② C++ TaskManager 分析：raw.db → (filter→_filtered.db) → files.db/events.db
   （逻辑 Android 任务短路：仅 android.db/files.db，TaskManagerAnalysis.cpp:123-160）
③ C++ → Python  LLMPythonProxy.async_ingest(task_id)（知识图谱，尽力而为）
④ 前端 → Python GET /api/graphiti/jobs/{id} 或经 C++ 透传查询进度
⑤ 前端 → Python POST /api/llm/reanalyze-files（TaskStore 解析任务权威 files.db）
⑥ 前端 → Python POST /api/llm/multi-image-analysis（案件级，回写 C++ case 状态）
⑦ 前端 → Python /api/reports/*（报告；FORENSIC_REPORT_DIR 输出）
⑧ http_agent（分布式）→ C/S :8091 领命令 → 本地起 CLI
   （http_agent/command_executor.cpp:76 传 --overwrite 等参数）→ 结果回传 C/S
```

## 9. 契约漂移与风险清单（本次核对发现）

1. **ingest 端点名**：C++ 用 `/api/graphiti/ingest/file`，常被误写成 `ingest-file`
   （LLMPythonProxy.cpp:104）。
2. **mode 集合不对齐**：Python 多 `analyzed_only`；`IngestRequest` 的
   `batch_size` 默认 50（graphiti_models.py:40）与 `GraphitiConfig` 的 10、
   .env.example 的 25 三方不一致（详见 Environment.md 第 6 节）。
3. **Android 库双命名**：任务目录纯名 `android.db` 与 legacy `<stem>_android.db`
   并存，RouteHelpers 四级回退即为此兜底（RouteHelpers.cpp:48-66）。
4. **memory 后缀陷阱**：`_memory.db` 基名来自镜像 stem 而非 raw 库名，
   回退逻辑需剥 `_raw`（RouteHelpers.cpp:76-86）。
5. **extract 列表语义**：Python 把文件列表逗号拼进 `name` 模式 pattern
   （cpp_backend.py:345-353），含逗号路径会碎裂——C++ 端无真列表模式。
6. **文件分页是假分页**：`files/largest` 无服务端分页，Python 取
   `page_size+offset` 全量再切片（cpp_backend.py:253-278），大任务会放大传输。
7. **HTML 折叠**：C++ 返回 SPA 首页（如路由未命中落 index.html）会被 Python
   折叠成 `Backend returned HTML` 错误而非解析失败（cpp_backend.py:100-109）。
8. **双向健康检查口径不同**：C++ 探 Python 用 `/health`（LLMPythonProxy.cpp:18），
   markitdown 用 `/api/markitdown/status`；Python 探 C++ 用 `/api/health`
   （cpp_backend.py:144）；run.sh 探 C++ 用 `/api/system/health`（run.sh:206）——
   三个健康端点并存。
9. **OfficeAnalyzer 基址不走 PYTHON_HTTP_PORT 回退**（OfficeAnalyzer.cpp:21），
   改端口部署时必须显式设 `PYTHON_SERVICE_URL`。

## 附录 A：端点 ↔ 代理前缀 ↔ axios 客户端对齐表

| 端点 | 归属 | dev 前缀（vite） | 常用客户端 | 备注 |
|---|---|---|---|---|
| `/api/health`、`/api/system/*`、`/api/tasks*` | C++ | `/api`（兜底）、`/tasks` | `api` | 健康三口径见 §9-8 |
| `/api/forensics/*`（files/timeline/extract/export） | C++ | `/api`（兜底） | `api` | Python 侧 CppBackendService 也调 |
| `/api/cases*` | C++ | `/api`（兜底） | `api` | 案件 CRUD + 状态回写 |
| `/api/graphiti/*` | Python | `/api/graphiti` | `pythonApi`（前端）/ httplib（C++） | 作业面见 §2 |
| `/api/llm/*`（case-analysis、reanalyze、multi-image） | Python | `/api/llm` | `pythonApi` | 410/409 契约见 ErrorCodes.md §5.3 |
| `/api/markitdown/*` | Python | `/api`（兜底→**C++，冲突**） | 仅 C++ 调用 | 前端不直调；dev 下走兜底会错打到 C++ |
| `/api/office/*` | Python | `/api/office` | 仅 C++ 调用 | OfficeAnalyzer |
| `/api/reports/*`（报告四族） | Python | `/api/reports` | `pythonApi` | forensic_reports/report_evidence/report_generation/report_narrative |
| `/api/db/*`、`/api/wechat/*`、`/api/investigation*` | Python | 同名前缀 | `pythonApi` | |
| `/auth/*`、`/clients/*`、`/commands/*` 等 | C/S :8091 | `/csapi`（rewrite 剥离） | `csApi` | JWT 双 token 体系 |

注意 `/api/markitdown` 未列入 vite 专属前缀表（vite.config.js:22-63），dev 环境若
前端直调会落入 `/api` 兜底打到 C++——当前无前端调用方，属**潜在坑**而非现实故障。

## 附录 B：改端口时的检查清单

1. `.env`：`HTTP_SERVER_PORT`、`PYTHON_HTTP_PORT`、`CPP_BACKEND_URL` 三处同步
   （否则 Python 回调 C++ 仍打 8080）。
2. 显式设置 `PYTHON_SERVICE_URL`（OfficeAnalyzer 硬编码回退 8090）。
3. run.sh 独立回退 `CPP_PORT=${HTTP_SERVER_PORT:-8666}`、`CS_PORT`（run.sh:79-81）。
4. 前端：dev 重启 vite（代理表启动时求值）；prod 重新构建（`VITE_*` 构建期内联）。
5. C/S：`PORT`（server/config.py:39）与 run.sh 传入的 `CS_PORT` 需一致。

**最后更新**: 2026-08-24（新建，参考手册）
