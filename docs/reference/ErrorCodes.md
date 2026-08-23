# 错误码目录：C++ 枚举、HTTP 形态与 Python 错误体系

> 来源：`src/core/ErrorHandling/ErrorHandling.h`、`src/analyzers/LinuxFilesAnalyzer/Common/LinuxAnalyzerErrors.h`、
> `src/network/HTTPServer/HTTPserver.{h,cpp}`、`src/network/HTTPServer/routes/FilterRoutes.cpp`、
> `python_service/httpserver/main.py`、`python_service/httpserver/services/task_store.py`、
> `python_service/httpserver/routes/investigation.py`、`python_service/httpserver/routes/case_analysis_endpoints/_case.py`、
> `python_service/server/middleware/auth.py` 等。file:line 相对仓库根。

## 1. 导览：三套并行的错误体系

TraceLens 没有统一的错误注册中心，实际存在**三套互不感知的体系**：

1. **`forensics::ErrorCode`（1xx–9xx）**：`src/core/ErrorHandling/ErrorHandling.h` 定义的"全局"枚举 + `Result<T>` 模板。
   **现状是孤岛**——全仓库唯一 include 它的是单元测试 `tests/UnitTest/test_error_handling.cpp:4`，
   没有任何生产模块使用（grep `forensics::ErrorCode` 仅命中定义文件本身）。
2. **`LinuxAnalysis::ErrorCode`（0–999 + 1xxx–4xxx 段）**：Linux 分析器自带的平行枚举，
   是真正在用的 C++ 错误码，被 LinuxFilesAnalyzer 的 10 个头文件 include（见第 3 节）。
3. **HTTP/服务边界错误**：C++ HTTP 层的 `ApiResponse.error_code`（仅 FilterRoutes 使用）+
   大量裸 `{"error": ...}`；Python httpserver 的固定文案 500/422 + `TaskStoreError` 稳定码；
   分布式 C/S 的 JWT 401/403 与跨组织 403。

两套 C++ 枚举的**同号不同义**（例如 100 在前者是 FileNotFound、在后者是 DATABASE_OPEN_FAILED），
排查时必须先确认是哪个命名空间。

## 2. forensics::ErrorCode（ErrorHandling.h:12-58，孤岛枚举）

配套：`errorCodeToString()`（:63-98）与 `Result<T>` / `Result<void>`（:118-232，类似 std::expected，
错误侧携带 code+message）。逐号含义：

| 号 | 枚举 | 文案（errorCodeToString） | 分组 |
|---|---|---|---|
| 0 | `Success` | Success | 成功 |
| 100 | `FileNotFound` | File not found | 文件 (1xx) |
| 101 | `FileReadError` | File read error | 文件 |
| 102 | `FileWriteError` | File write error | 文件 |
| 103 | `FileAccessDenied` | File access denied | 文件 |
| 104 | `InvalidFilePath` | Invalid file path | 文件 |
| 105 | `FileEmpty` | File is empty | 文件 |
| 200 | `LLMConnectionFailed` | LLM connection failed | LLM (2xx) |
| 201 | `LLMRequestFailed` | LLM request failed | LLM |
| 202 | `LLMResponseParseError` | LLM response parse error | LLM |
| 203 | `LLMTimeout` | LLM request timeout | LLM |
| 204 | `LLMRateLimited` | LLM rate limited | LLM |
| 205 | `LLMContextOverflow` | LLM context window overflow | LLM |
| 300 | `NoModelsAvailable` | No LLM models available | 模型 (3xx) |
| 301 | `ModelNotFound` | Model not found | 模型 |
| 302 | `AllModelsFailed` | All models failed | 模型 |
| 400 | `InvalidConfiguration` | Invalid configuration | 配置 (4xx) |
| 401 | `ConfigNotLoaded` | Configuration not loaded | 配置 |
| 402 | `MissingConfigKey` | Missing configuration key | 配置 |
| 500 | `DatabaseOpenError` | Database open error | 数据库 (5xx) |
| 501 | `DatabaseQueryError` | Database query error | 数据库 |
| 502 | `DatabaseWriteError` | Database write error | 数据库 |
| 503 | `DatabaseNotInitialized` | Database not initialized | 数据库 |
| 600 | `AnalysisFailed` | Analysis failed | 分析 (6xx) |
| 601 | `ContentTooLarge` | Content too large | 分析 |
| 602 | `UnsupportedFileType` | Unsupported file type | 分析 |
| 603 | `ChunkingFailed` | Content chunking failed | 分析 |
| 900 | `Unknown` | Unknown error | 通用 (9xx) |
| 901 | `InternalError` | Internal error | 通用 |
| 902 | `NotImplemented` | Not implemented | 通用 |
| 903 | `Cancelled` | Operation cancelled | 通用 |

使用状况：**仅测试引用**。生产代码路径上的失败传播仍以布尔返回值 + stderr 日志为主
（见 CLI.md 退出码节）。

## 3. LinuxAnalysis::ErrorCode（LinuxAnalyzerErrors.h:19-84，在用）

配套：`getErrorMessage()`（:89-199）、`LinuxAnalyzerError` 富错误对象（:204-291，含
component/filePath/lineNumber/suggestion/isRecoverable，`toString()` 输出
`[code] message [Component: ...] (File: path:line) [Suggestion: ...] [FATAL]`），
以及 `Result<T>`/`makeSuccess`/`makeError` 辅助（:304-421）。

### 3.1 通用段

| 号 | 枚举 | 文案 | 分组 |
|---|---|---|---|
| 0 | `SUCCESS` | Success | 成功 |
| 100 | `DATABASE_OPEN_FAILED` | Failed to open database | 数据库 (1xx) |
| 101 | `DATABASE_CREATE_TABLE_FAILED` | Failed to create database table | 数据库 |
| 102 | `DATABASE_INSERT_FAILED` | Failed to insert record into database | 数据库 |
| 103 | `DATABASE_QUERY_FAILED` | Database query failed | 数据库 |
| 104 | `DATABASE_PREPARE_FAILED` | Failed to prepare SQL statement | 数据库 |
| 105 | `DATABASE_BIND_FAILED` | Failed to bind parameter to SQL statement | 数据库 |
| 106 | `DATABASE_EXECUTE_FAILED` | Failed to execute SQL statement | 数据库 |
| 107 | `DATABASE_TRANSACTION_FAILED` | Database transaction failed | 数据库 |
| 108 | `DATABASE_NOT_INITIALIZED` | Database not initialized | 数据库 |
| 200 | `FILE_NOT_FOUND` | File not found | 文件 (2xx) |
| 201 | `FILE_READ_ERROR` | Error reading file | 文件 |
| 202 | `FILE_WRITE_ERROR` | Error writing file | 文件 |
| 203 | `FILE_ACCESS_DENIED` | File access denied | 文件 |
| 204 | `FILE_EXTRACT_FAILED` | Failed to extract file from image | 文件 |
| 300 | `PARSE_INVALID_FORMAT` | Invalid format | 解析 (3xx) |
| 301 | `PARSE_INCOMPLETE_DATA` | Incomplete data | 解析 |
| 302 | `PARSE_ENCODING_ERROR` | Encoding error | 解析 |
| 303 | `PARSE_TIMESTAMP_ERROR` | Timestamp parsing error | 解析 |
| 304 | `PARSE_BINARY_FORMAT_ERROR` | Binary format error | 解析 |
| 400 | `VALIDATION_INVALID_COLUMN` | Invalid column name | 校验 (4xx) |
| 401 | `VALIDATION_INVALID_PARAMETER` | Invalid parameter | 校验 |
| 402 | `VALIDATION_EMPTY_INPUT` | Empty input provided | 校验 |
| 500 | `SYSTEM_MEMORY_ERROR` | Memory allocation error | 系统 (5xx) |
| 501 | `SYSTEM_THREAD_ERROR` | Thread error | 系统 |
| 502 | `SYSTEM_INITIALIZATION_FAILED` | System initialization failed | 系统 |
| 999 | `UNKNOWN_ERROR` | Unknown error | 兜底 |

### 3.2 域专属段

| 号 | 枚举 | 文案 | 分组 |
|---|---|---|---|
| 1001 | `DOCKER_DIR_NOT_FOUND` | Docker directory not found | 容器 (1xxx) |
| 1002 | `DOCKER_CONFIG_PARSE_FAILED` | Failed to parse Docker configuration | 容器 |
| 1003 | `PODMAN_DIR_NOT_FOUND` | Podman directory not found | 容器 |
| 1004 | `DOCKER_INVALID_JSON` | Invalid JSON in Docker configuration | 容器 |
| 2001 | `APACHE_LOG_PARSE_FAILED` | Failed to parse Apache log file | Web 服务 (2xxx) |
| 2002 | `NGINX_LOG_PARSE_FAILED` | Failed to parse Nginx log file | Web 服务 |
| 2003 | `VHOST_CONFIG_INVALID` | Invalid virtual host configuration | Web 服务 |
| 2004 | `LOG_FILE_NOT_FOUND` | Log file not found | Web 服务 |
| 3001 | `SETUID_SCAN_FAILED` | Failed to scan for setuid files | 安全 (3xxx) |
| 3002 | `CAPABILITY_PARSE_FAILED` | Failed to parse file capabilities | 安全 |
| 3003 | `SELINUX_NOT_ENABLED` | SELinux is not enabled | 安全 |
| 3004 | `APPARMOR_NOT_ENABLED` | AppArmor is not enabled | 安全 |
| 3005 | `PERMISSION_DENIED` | Permission denied | 安全 |
| 4001 | `CORRELATION_ENGINE_FAILED` | Correlation engine failed | 增强分析 (4xxx) |
| 4002 | `TIMELINE_RECONSTRUCTION_FAILED` | Timeline reconstruction failed | 增强分析 |
| 4003 | `ANOMALY_DETECTION_FAILED` | Anomaly detection failed | 增强分析 |
| 4004 | `INSUFFICIENT_DATA` | Insufficient data for analysis | 增强分析 |

### 3.3 真实使用方（include LinuxAnalyzerErrors.h 的 11 个文件）

`Analysis/AnomalyDetector.h`、`Analysis/LogCorrelationEngine.h`、`Analysis/TimelineReconstructor.h`、
`Database/LinuxAnalysisDatabase.h`（及 `Database/Detail/LinuxAnalysisDatabaseCore.cpp`）、
`Parsers/Container/DockerContainerParser.{h,cpp}`、`Parsers/Container/PodmanParser.{h,cpp}`、
`Parsers/Security/AppArmorParser.{h,cpp}`、`Parsers/Security/CapabilityAnalyzer.{h,cpp}`、
`Parsers/Security/SELinuxAnalyzer.{h,cpp}`、`Parsers/Security/SetuidAnalyzer.{h,cpp}`——
全部位于 `src/analyzers/LinuxFilesAnalyzer/`。

## 3.4 两套 C++ 枚举的同号冲突对照（易混淆点）

| 号 | forensics::ErrorCode | LinuxAnalysis::ErrorCode |
|---|---|---|
| 100 | FileNotFound（文件） | DATABASE_OPEN_FAILED（数据库） |
| 101 | FileReadError | DATABASE_CREATE_TABLE_FAILED |
| 200 | LLMConnectionFailed（LLM） | FILE_NOT_FOUND（文件） |
| 300 | NoModelsAvailable（模型） | PARSE_INVALID_FORMAT（解析） |
| 400 | InvalidConfiguration（配置） | VALIDATION_INVALID_COLUMN（校验） |
| 500 | DatabaseOpenError（数据库） | SYSTEM_MEMORY_ERROR（系统） |
| 900/999 | Unknown / — | — / UNKNOWN_ERROR |

**判别方法**：错误对象类型。`forensics::Result<T>`/`ErrorCode::` 前缀属于孤岛体系；
`LinuxAnalyzerError` 的 `toString()` 总是以 `[<号>]` 开头（LinuxAnalyzerErrors.h:255-277），
出现 `[100]`~`[4004]` 这类方括号短码即可断定是 Linux 平行体系。

## 3.5 Result API 速览（两套的用法差异）

```cpp
// forensics::（ErrorHandling.h:118-195）——工厂函数构造
forensics::Result<int> r = forensics::Result<int>::error(
    forensics::ErrorCode::LLMTimeout, "timeout");
if (r.isError()) std::cerr << r.errorMessage();   // code 经 r.errorCode()

// LinuxAnalysis::（LinuxAnalyzerErrors.h:304-421）——构造函数 + helper
auto res = LinuxAnalysis::makeError<std::vector<LinuxLogEntry>>(
    LinuxAnalysis::ErrorCode::PARSE_TIMESTAMP_ERROR, "bad ts");
if (res.hasError()) std::cerr << res.error().toString();  // [303] Timestamp parsing error: bad ts
```

差异要点：前者用 `isSuccess()/value()`，错误消息缺省取 `errorCodeToString`；
后者错误侧是富对象，可继续 `setComponent/setFilePath/setLineNumber/setSuggestion`
（:248-252），`isRecoverable` 缺省 true，置 false 后 `toString()` 追加 `[FATAL]`（:273-275）。

## 4. C++ HTTP 层错误形态

### 4.1 ApiResponse 信封（结构化错误）

定义于 `src/network/HTTPServer/HTTPserver.h:41,63`，序列化于 `HTTPserver.cpp:21-34`：

```json
{ "success": false, "message": "<人读信息>", "data": {}, "timestamp": "...", "error_code": "<机读码>" }
```

`error_code` 仅在非空时输出（HTTPserver.cpp:30-32）。**全仓库唯一传入 error_code 的模块是
FilterRoutes**（`routes/FilterRoutes.cpp`，25 处调用），稳定码共 12 个：

| error_code | 语义 | 出现次数（FilterRoutes.cpp） |
|---|---|---|
| `VALIDATION_ERROR` | 请求字段/名称非法 | 7（:144,208,217,338,406,414,425 等） |
| `NOT_FOUND` | profile 或任务库不存在 | 3（:163,357 等） |
| `DIR_NOT_FOUND` | `config/filter_profiles/` 不存在 | 3（:105,154,348） |
| `FORBIDDEN` | 改/删内置 profile | 2（:230,370） |
| `PARSE_ERROR` | 请求体非法 JSON | 2（:316 等） |
| `CREATE_ERROR` / `DELETE_ERROR` / `LIST_ERROR` / `LOAD_ERROR` / `WRITE_ERROR` / `DB_NOT_FOUND` / `FILTER_ERROR` | 各自的 IO/应用失败 | 各 1 |

其余路由即使返回 `ApiResponse`，也只填 `message`，不填 `error_code`。

### 4.2 裸 `{"error": ...}` 形态

大量路由（约 230 处含 `"error"` 的写响应）直接写裸对象并自设状态码，例：

```json
// 404
{"error":"task not found"}            // MemoryForensicsRoutes.cpp:30
{"error":"memory db not found"}       // MemoryForensicsRoutes.cpp:55,95
// 500
{"error":"query failed"}              // MemoryForensicsRoutes.cpp:59
```

任务数据库路由的 404 形态则是 `{"error":"Task not found","task_id":...}`
（TaskCRUDRoutes.cpp:535-576 多处）。**前端必须同时兼容两种信封**。

### 4.3 状态码约定（C++ 侧）

| 状态码 | 用途 | 例 |
|---|---|---|
| 200/201/202 | 成功 / 创建 / 已受理 | TaskCRUDRoutes、FilterRoutes |
| 204 | OPTIONS 预检（CORS 中间件，HTTPserver.cpp:97-100） | |
| 400 | 请求参数/JSON 非法 | 各路由散见 |
| 404 | 资源不存在 | RouteHelpers 抛 runtime_error 后由路由转 404 |
| 500 | 内部失败 | MemoryForensicsRoutes.cpp:59 等 |

补充约定：

- C++ 侧**没有全局异常中间件**，状态码由各 handler 手工设置；同一资源在不同路由
  可能混用 ApiResponse 与裸 JSON 两种失败形态。
- `_memory.db` 查询路由刻意用 `SQLITE_OPEN_READONLY` 打开——库缺失必须 404，
  而不是被空开成假库（MemoryForensicsRoutes.cpp:51 注释）。
- `RouteHelpers::get_database_path`（RouteHelpers.cpp:35-90）在 task_id 不存在时抛
  `std::runtime_error("Task not found: ...")`，在 db_type 未知时抛
  `std::runtime_error("Unknown database type: ...")`；调用方负责转 HTTP 状态。
- CORS 失败路径不产生错误体：`CORS_ALLOW_ORIGIN`（RouteHelpers.cpp:16-17）只改响应头。

## 5. Python httpserver（8090）错误体系

### 5.1 全局兜底：固定文案（防泄漏）

`python_service/httpserver/main.py`：

| HTTP | 触发 | 响应体 | 位置 |
|---|---|---|---|
| 500 | 任何未捕获异常 | `{"success":false,"message":"Internal server error","error":"An unexpected error occurred","timestamp":...}` | main.py:156-171（即使 DEBUG 也不回显 str(exc)，防路径/内部细节泄漏） |
| 422 | Pydantic `RequestValidationError` | `{"success":false,"message":"Validation error","errors":[...],"timestamp":...}` | main.py:174-188（详细错误只进日志） |

### 5.2 TaskStore 五个稳定错误码

`python_service/httpserver/services/task_store.py:34-38` 定义、`TaskStoreError(code, message)`
（:41-46）携带。这是 Python 侧**唯一成体系的稳定机读码**：

| code | 语义 | 典型 HTTP 映射 |
|---|---|---|
| `task_not_found` | task_id 缺失或 C++ 查无此任务（:57-63） | 404 |
| `task_store_unavailable` | 任务记录缺可信 DB 路径 / 多库目录不一致（:74-77,93-100） | 400 |
| `path_mismatch` | 客户端提供的 files_db_path 与任务可信路径精确比对不符（:113-119） | 400 |
| `path_outside_workspace` | 解析后的路径逃出任务工作区（:135） | 400 |
| `input_output_overlap` | 转换输入/输出目录重叠（:166-187 区域） | 400 |

映射示例：`_case.py:142-145`——`TASK_NOT_FOUND` → 404，其余 TaskStoreError → 400；
`multi_analysis.py:245-248` 同款。设计原则（task_store.py 模块 docstring）：任务记录是唯一权威，
fail-closed，绝不"就近匹配"。

### 5.3 调查域（investigation）状态码契约

`python_service/httpserver/routes/investigation.py`：

| HTTP | detail 文案 | 位置 |
|---|---|---|
| 409 | `analysis review conflict`（分析复核冲突，乐观并发） | investigation.py:186 |
| 410 | `legacy case analysis generation has been retired; use report generation` | case_analysis_endpoints/_case.py:89-92（410=退役契约，非资源删除） |
| 400 | `invalid evidence key` / `invalid status filter` | investigation.py:78,135,220,227 |
| 404 | `evidence not found` / `analysis not found` / `task not found` / `investigation event not found` | investigation.py:80,184,200,291,322 |
| 503 | `evidence store unavailable` | investigation.py:82,139,188,293 等贯穿 |
| 202 | 二级分析已受理 | investigation.py:120 |

## 6. 分布式 C/S server（8091）错误体系

### 6.1 JWT 鉴权（401/403 分工）

`python_service/server/middleware/auth.py`：

| HTTP | 触发 | detail | 位置 |
|---|---|---|---|
| 401 | token 无效/过期 | `Invalid authentication credentials`（带 `WWW-Authenticate: Bearer`） | auth.py:52-57 |
| 401 | token 类型不匹配（client token 打 user 路由，反之亦然） | `User token required` / `Client token required` | auth.py:59-64,106-111 |
| 401 | token 有效但主体不存在 | `User not found` / `Client not found` | auth.py:66-72,113-119 |
| 403 | 跨组织访问 | clients.py:234,240,271,286,322,399；commands.py:87,144 等 | 组织隔离边界 |

前端约定（web/src/services/api.js）：本地模式 401 → 清 `auth_token` 并跳 `/login`（:73-77）；
C/S 401 → 仅清 `cs_auth_token`、不跳转（:168-171）。

### 6.2 其余状态码

C/S 的 DB 层另有 5xx 与 404 常规用法；命令队列的 4xx 语义见
`server/api/commands.py` 文档字符串（404=client/command 不存在，403=跨组织）。
启动期数据库不可达由 `DB_STARTUP_TIMEOUT`/`DB_CONNECT_TIMEOUT`/`DB_POOL_TIMEOUT`
三层预算控制（server/config.py:46-51，注释明确驱动超时必须短于启动超时），
超时表现为进程退出而非特定错误码。

## 6.3 分层错误视图（一次请求可能穿过全部三层）

```text
前端 axios（401 → 清 token / 跳转，见 api.js 拦截器）
  │
  ├─ C++ :8080  ApiResponse{success,message,error_code?} 或裸 {"error":...}
  │              └─ 内部：LinuxAnalysis::ErrorCode [1xx..4xxx]（Linux 管线）
  │                        forensics::ErrorCode（1xx..9xx，当前未接线）
  │
  ├─ httpserver :8090  500/422 固定文案 + TaskStoreError 五码 + 409/410/503 契约
  │              └─ 调 C++ 失败时折叠为 {"success":false,"error":"<类型名>"}（cpp_backend.py:124-134）
  │
  └─ C/S :8091   JWT 401 三态 + 跨组织 403 + 404
```

## 7. 排错速查

| 现象 | 先查 |
|---|---|
| CLI 退出码 2 | CommandLineParser 置 parse_error 的四个分支（缺值/非法 android-source/非法 fd/非法 SIZE） |
| HTTP 响应是 HTML | CppBackendService `_request` 会把 text/html 判为 `{"success":false,"error":"Backend returned HTML"}`（cpp_backend.py:100-109）——通常是 C++ 返回了 SPA 首页 |
| `error_code` 字段缺失 | 该路由不是 FilterRoutes；改看 `message` 或裸 `error` |
| Python 500 固定文案 | 真实堆栈在服务端日志（main.py:162 只 log 不回显） |
| `task_not_found` 但任务在 | C++ `GET /api/tasks/{id}` 返回体 `id` 与请求不符会被 get_task 判 None（cpp_backend.py:197-198） |
| Linux 模块日志出现 `[1xx]` 短码 | 是 LinuxAnalysis::ErrorCode（第 3 节），不是 forensics::ErrorCode（第 2 节），同号不同义 |

**最后更新**: 2026-08-24（新建，参考手册）
