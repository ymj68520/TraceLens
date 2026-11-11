# C++ REST API 参考文档

> 本文档基于 `src/network/HTTPServer/routes/` 下的路由源码逐文件重写，所有路径、参数与响应字段均以代码为准。

## 概述

C++ HTTP 服务（Crow 框架）提供取证分析任务管理、时间线/文件/内存取证查询、案件管理、全文搜索与文件过滤等功能。

| 项目 | 说明 |
|------|------|
| 默认端口 | **8080**（`ConfigManager::getHTTPServerPort()`，读配置项 `HTTP_SERVER_PORT`，见 `src/core/ConfigManager/ConfigManager.cpp:140`） |
| run.sh 启动 | `run.sh:78` 为 `CPP_PORT="$HTTP_SERVER_PORT"`（无内联兜底）；缺省兜底在 `scripts/lib/tracelens_env.sh:38` 的 `: "${HTTP_SERVER_PORT:=8080}"`，**未设置该变量时回退 8080**（8666 只是 `.env.example` 的 `HTTP_SERVER_PORT` 示例值） |
| scripts 启动 | `scripts/start_services.sh`、`start_all_services.sh` 均为 `${HTTP_SERVER_PORT:-8080}` |
| 认证 | 默认无（本地服务）。`TRACELENS_FIELD_AUTH=enabled` 时启用现场认证中间件（`FieldApp.cpp::FieldAuthMiddleware`）：Bearer 令牌经 Python 服务 `POST /api/field-auth/introspect` 校验；服务间调用走 `X-TraceLens-Service-Token`（作用域受限，见 FieldApp.cpp::python_service_scope）；失败按 401/403/503 拒绝 |
| CORS | 所有路由经 `RouteHelpers::add_cors_headers` 添加跨域头（现场认证开启时不再回 `Access-Control-Allow-Origin: *`，见 `HTTPserver.cpp` 全局 CORS 中间件）；13 个任务路径另注册同名 OPTIONS 预检路由（`TaskRoutes.cpp`） |
| 安全状态 | `GET /api/security/status`——现场安全模式自检（release 指纹与出站策略，见第 6 节） |
| Python 网关 | `/python/<path>`——把前端同源 `/python` 前缀的 GET/POST/PUT/DELETE/PATCH 请求转发到 Python 服务（`HTTPserver.cpp::proxy_python_request`，生产前端免跨域） |
| Swagger UI | `GET /api/docs`（注意：是 `/api/docs`，不是旧文档写的 `/api/docs/ui`） |
| OpenAPI JSON | `GET /api/docs/openapi.json` |
| 端点清单 | `GET /api/docs/endpoints` |
| 静态资源 | `GET /` 与 `GET /<path>` 托管 `web/dist` 下的前端 SPA（`HTTPserver.cpp::setup_static_routes`） |

**服务器地址**：`http://localhost:8080`（或 `http://localhost:8666`，取决于启动方式）

## 响应约定（以代码为准，与旧文档不同）

- 仅 `/api/filter/*`（FilterRoutes）使用统一封装 `ApiResponse`：`{success, message, data, timestamp, pagination, error_code}`（定义在 `src/network/HTTPServer/HTTPserver.h:35`）。
- **其余所有路由直接返回领域 JSON 对象**（如 `{tasks: [...]}`、`{task_id: ...}`），不套 ApiResponse 外壳。
- 失败时绝大多数路由返回 `{"error": "<原因>"}`（部分附 `task_id`/`message` 字段），HTTP 状态码为 400/404/500。
- 任务状态与优先级值**均为小写字符串**（`TaskHelpers.cpp`）：状态 `pending / running / completed / failed / cancelled / interrupted / paused`（`interrupted` = 进程重启中断、可 resume；`paused` = 协作式暂停）；优先级 `low / normal / high / critical`；阶段 `initializing / image_analysis / event_extraction / file_classification / llm_analysis / platform_analysis / file_carving / finalizing`。

---

## 目录

1. [任务管理 API](#1-任务管理-api)
2. [取证分析 API](#2-取证分析-api)
3. [案件管理 API](#3-案件管理-api)
4. [全文搜索 API](#4-全文搜索-api)
5. [文件过滤配置 API](#5-文件过滤配置-api)
6. [系统与文档 API](#6-系统与文档-api)
7. [已知未注册路由](#7-已知未注册路由)

---

## 1. 任务管理 API

> 源码：`TaskCRUDRoutes.cpp`、`TaskBatchRoutes.cpp`、`TaskMonitoringRoutes.cpp`、`TaskRoutes.cpp`（仅 OPTIONS）
> 任务 API 只注册 `/api` 前缀路径（`TaskCRUDRoutes.cpp:22-23` 注释明确此约定）；非 `/api` 前缀的 `/tasks` 是前端 SPA 页面路径，不注册为 API。

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/api/tasks`、`/api/tasks/list` | 列出任务（过滤+分页） |
| POST | `/api/tasks` | 创建取证分析任务 |
| GET/PUT | `/api/tasks/<task_id>` | 获取任务详情（PUT 为同一 handler 的别名，不执行更新） |
| GET | `/api/tasks/<task_id>/results` | 获取任务结果 |
| DELETE | `/api/tasks/<task_id>` | 删除（取消）任务 |
| POST | `/api/tasks/cleanup` | 清理已完成的旧任务 |
| GET | `/api/tasks/<task_id>/databases` | 任务产物数据库列表 |
| POST | `/api/tasks/batch-create` | 批量创建任务 |
| POST | `/api/tasks/batch-status` | 批量查询状态 |
| POST | `/api/tasks/batch-cancel` | 批量取消 |
| GET | `/api/tasks/<task_id>/progress` | 任务进度 |
| GET | `/api/tasks/<task_id>/audit-log` | 任务审计日志 |
| GET | `/api/tasks/statistics` | 系统级任务统计 |
| PUT | `/api/tasks/<task_id>/priority` | 更新优先级（见下方备注） |
| POST | `/api/tasks/<task_id>/resume` | 从阶段台账恢复 stopped 任务（见下方专节） |
| POST | `/api/tasks/<task_id>/pause` | 协作式暂停（见下方专节） |

另有 13 个同名路径的 `OPTIONS` CORS 预检路由（`TaskRoutes.cpp`，含 `/api/tasks/<string>/priority`、`/api/tasks/<string>/databases` 等；resume/pause 的 OPTIONS 并在 `TaskCRUDRoutes.cpp` 的 methods 内，不占这 13 个名额）。

### POST /api/tasks —— 创建任务

请求体字段（验证自 `TaskCRUDRoutes.cpp::handle_create_task`）：

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `image_path` | string | **必填** | 磁盘镜像/数据源路径 |
| `priority` | string | `normal` | `low / normal / high / critical` |
| `metadata` | object(string→string) | 空 | 附加元数据 |
| `dependencies` | array | 空 | `[{task_id, required=true}]`，依赖任务 |
| `scenarios` | string[] | 空 | 取证场景：`android / windows / linux / server_cloud` |
| `android_analyze` | bool | false | 旧版兼容：true 时等价 `scenarios:["android"]` |
| `xfs_mode` | string | `auto` | `native / pure / auto` |
| `db_output_dir` | string | 空 | 数据库输出目录 |
| `llm_analyze` | bool | **true** | 是否执行 LLM 分析。现场模式（`TRACELENS_FIELD_AUTH=enabled` 且 `FIELD_OUTBOUND_POLICY` 缺省/disabled）下服务端强制置 false，且 `scenarios` 含 `server_cloud` 时返回 400 `cloud scenario is disabled by field outbound policy` |
| `llm_event_analyze` | bool | false | 任务级事件簇 LLM 分析开关（默认关） |
| `llm_mode` | string | `smart` | `full / smart` |
| `llm_max_files` | int | 0 | 任务级分析文件预算。`0`（或缺省/null）= 继承全局 `LLM_MAX_FILES`；`1..100000` = 本任务预算，同时约束逐文件 LLM 分析、知识图谱摄取与报告证据 seed。非整数或越界返回 400 + `INVALID_LLM_MAX_FILES`（不静默回落）；smart 模式下超过 `LLM_SMART_CANDIDATE_FILES` 会被钳到候选池并写入 `LLM_CONFIG` 审计 |
| `case_description` | string | 空 | 案情描述（LLM 分析上下文） |
| `filter_profile` | string | 空 | 文件过滤配置名 |
| `enable_decryption` | bool | false | 启用解密 |
| `key_file_dir` | string | 空 | 密钥目录（接受旧拼写 `key_dir`） |
| `decrypt_password` | string | 空 | 解密口令 |
| `android_source` | string | `tsk` | 合法值（`TaskCRUDRoutes.cpp::supportedSources`）：`tsk / dir / zip / miui-backup / harmony-backup / thunder-backup / oppo-backup / meiya / mobile-evidence / tar / seven-zip / android-backup / filesystem-image / android-container / aliyun-image / ios-backup / vivo-backup`。非法值 400 `UNSUPPORTED_ANDROID_SOURCE`。路径类型校验：`dir / miui-backup / harmony-backup / ios-backup / vivo-backup` 须为**目录**；`thunder-backup / oppo-backup / meiya` 接受目录或文件；其余须为**常规文件**（不存在或类型不符 400）。`android-container / aliyun-image` 禁止自定义 `db_output_dir`（400 `TASK_WORKDIR_REQUIRED`）；`aliyun-image` 强制 `scenarios:["linux"]`。注意：`android-container / aliyun-image` 仅 HTTP 管线可用，CLI 不支持 |
| `backup_password` | string | 空 | 备份 AES-256 口令（仅运行期使用，不落盘；服务端用后即清并从回显中抹除）。加密 ADB v5（Android Backup）暂不支持解密，保持 `encrypted_locked` |
| `platform_analyze` | bool | **true** | 平台制品分析开关；`aliyun-image` 与归档类新源（tar/seven-zip/android-backup/filesystem-image/android-container）置 false 时分别返回 400 `ALIYUN_LINUX_ANALYSIS_REQUIRED` / `ANDROID_ANALYSIS_REQUIRED` |
| `image_source` | string | `tsk` | 置 `raid` 进入 RAID 标准镜像准入（见下） |
| `raid_job_id` / `raid_manifest_sha256` / `raid_allow_partial` | string / string / bool | 空 / 空 / false | RAID 准入参数。仅当 `image_source="raid"` 且 `android_source=tsk`、`db_output_dir` 为空、现场认证开启时受理（否则 400 `RAID_TASK_ADMISSION_REQUIRED`）；清单哈希不符 409，部分成员缺失需 `raid_allow_partial=true`。`metadata` 中调用方伪造的 `raid_*` / `source_kind` / `source_label` 键一律被服务端剔除 |
| `preflight_job_id` / `preflight_source_sha256` / `preflight_detected_kind`（归档类新源必带） | string | 空 | 归档/容器/文件系统镜像与阿里云镜像的证据准入指纹（`tar / seven-zip / android-backup / filesystem-image / android-container / aliyun-image`）。`android-container` 另需 `preflight_plan_sha256 / preflight_selected_slot`。准入失败 400，证据变更 409 `EVIDENCE_CHANGED_AFTER_PREFLIGHT`；通过后 `metadata.source_verification=VERIFIED_PREFLIGHT` |
| `file_carving` | bool | false | 文件雕刻；同时接受顶层与 `options.file_carving` 两种写法 |

现场认证附加行为：`TRACELENS_FIELD_AUTH=enabled` 时创建任务要求已认证主体（缺失 401 `{"detail":"authentication required"}`），并在 metadata 写入 `requested_by` / `requested_by_source=field_jwt`。

**请求示例**：

```bash
curl -X POST http://localhost:8080/api/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "image_path": "/evidence/miui_backup.zip",
    "scenarios": ["android"],
    "priority": "high",
    "android_source": "miui-backup",
    "backup_password": "…",
    "llm_analyze": true,
    "llm_mode": "smart",
    "llm_max_files": 300,
    "case_description": "调查手机数据泄露"
  }'
```

**响应 `201`**（原始 JSON，非 ApiResponse 封装）：

```json
{
  "id": "task_xxx",
  "status": "created",
  "priority": "high",
  "scenarios": ["android"],
  "llm_analyze": true,
  "llm_event_analyze": false,
  "llm_mode": "smart",
  "llm_max_files": 300,
  "file_carving": false,
  "filter_profile": "",
  "android_source": "miui-backup",
  "dependencies_count": 0
}
```

请求体非法时返回 `400`，body 为文本 `Invalid request: <原因>`；`llm_max_files` 非法时 body 为 JSON `{"error": "...", "error_code": "INVALID_LLM_MAX_FILES"}`。

**全字段请求体示例**（字段逐一对应上表，验证自 `TaskCRUDRoutes.cpp::handle_create_task` 的 `body.value(...)` 解析）：

```bash
curl -X POST http://localhost:8080/api/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "image_path": "/evidence/disk.E01",
    "priority": "high",
    "metadata": {"case_no": "2026-0417", "analyst": "zhang"},
    "dependencies": [{"task_id": "task_prev", "required": true}],
    "scenarios": ["windows", "linux"],
    "xfs_mode": "auto",
    "db_output_dir": "/data/out",
    "llm_analyze": true,
    "llm_mode": "full",
    "case_description": "服务器入侵事件溯源",
    "filter_profile": "general_forensics",
    "enable_decryption": true,
    "key_file_dir": "/keys",
    "decrypt_password": "…",
    "file_carving": true
  }'
```

响应 `201` 固定为：`{id, status: "created", priority, scenarios[], llm_analyze, llm_event_analyze, llm_mode, llm_max_files, file_carving, filter_profile, android_source, dependencies_count}`（注意：回显体不含 `case_description / metadata` 等输入字段，完整状态需再 GET 任务详情）。

### GET /api/tasks —— 任务列表

查询参数：`status`、`priority`（值为 `all` 或具体小写状态/优先级）、`limit`（默认 **100**）、`offset`（默认 0）。

响应：`{tasks: [<task 对象>], pagination: {total, limit, offset, has_more}, filters: {status, priority}}`

`task` 对象字段（`TaskHelpers::task_to_json`）：`id, image_path, status, priority, message, interrupted_by_restart, output_files_db, output_raw_db, output_events_db, progress{current_phase, phase_percentage, overall_percentage, phase_description}, timestamps{created, started, completed, execution_time_seconds}(Unix 毫秒), scenarios, scenario_databases, output_windows_db, output_linux_db, output_android_db, output_oss_db（扁平场景库路径，供 Python 读取方按名解析）, android_analyze, android_source, llm_analyze, llm_event_analyze, llm_mode, llm_max_files, file_carving, filter_profile, case_description, xfs_mode, db_output_dir, extraction_directory, cancellation_requested, pause_requested, resumable, resume_stage, resume_count, dependencies, dependents_count, metadata, error_details`。

**示例——列出运行中的任务（分页）**：

```bash
curl "http://localhost:8080/api/tasks?status=running&priority=all&limit=20&offset=0"
```

响应要点：`tasks[]`（每项字段见上）、`pagination{total, limit, offset, has_more}`、`filters{status, priority}`。`status=completed` 过滤示例：

```bash
curl "http://localhost:8080/api/tasks?status=completed&limit=5"
```

> 注意：`task_id` 为 `list / statistics / cleanup / batch-create / batch-status / batch-cancel` 时，`GET /api/tasks/<task_id>` 显式返回 404，避免与子路由冲突。

### GET /api/tasks/{task_id}/results —— 任务结果

- 任务未完成：`202`，`{status, message: "Task not completed yet", task_id}`。
- 已完成：`200`，`{task_id, status: "completed", results: <文件摘要>, output_files_db}`；若 `_files.db` 中有 LLM 证据则追加 `llm_results` 与 `output_descriptions_db`（后者为 `output_files_db` 的别名）。结果带缓存，DB 新增 LLM 证据后会自动重建。

```bash
curl http://localhost:8080/api/tasks/task_xxx/results
```

响应要点（已完成）：`results` 来自 `SQLiteHelper::get_file_summary`（files 表聚合摘要），`llm_results.descriptions[]` 为逐文件 LLM 证据（含 `file_path / description / keywords` 等列，具体以 `_files.db` 的 `file_descriptions` 表为准）。

### GET /api/tasks/{task_id} —— 任务详情

```bash
curl http://localhost:8080/api/tasks/task_xxx
```

响应要点：单个 `task` 对象（字段同任务列表）。不存在时 `404 {"error": "Task not found", "task_id": ...}`。

### DELETE /api/tasks/{task_id}

调用 `TaskManager::delete_task`。成功 `200` `{success: true, task_id, message: "Task deleted successfully"}`；不存在 `404`。

```bash
# 取消/删除任务（带原因，前端 taskService.cancelTask 的形态）
curl -X DELETE http://localhost:8080/api/tasks/task_xxx \
  -H "Content-Type: application/json" \
  -d '{"reason": "operator requested"}'

# 直接删除（前端 deleteTask 的形态，无 body）
curl -X DELETE http://localhost:8080/api/tasks/task_xxx
```

### POST /api/tasks/cleanup

请求体 `{max_age_hours: 24}`（可选，默认 24）。响应 `{success, removed_count, message}`。

```bash
curl -X POST http://localhost:8080/api/tasks/cleanup \
  -H "Content-Type: application/json" \
  -d '{"max_age_hours": 72}'
```

响应要点：`success(bool)`、`removed_count(int)`、`message`。

### GET /api/tasks/{task_id}/databases

响应 `{task_id, databases: [{type: "raw|events|files", path, name}], count}`。

```bash
curl http://localhost:8080/api/tasks/task_xxx/databases
```

### POST /api/tasks/batch-create

请求体 `{image_paths: ["/path/a.E01", ...], priority: "normal"}`。响应 `201` `{success, task_ids: [...], count}`。

```bash
curl -X POST http://localhost:8080/api/tasks/batch-create \
  -H "Content-Type: application/json" \
  -d '{
    "image_paths": ["/evidence/disk1.E01", "/evidence/disk2.E01"],
    "priority": "normal"
  }'
```

响应要点：`task_ids[]` 顺序与 `image_paths` 对应，`count` 为创建数。

### POST /api/tasks/batch-status

请求体 `{task_ids: [...]}`。响应 `{statuses: [{task_id, status, progress} | {task_id, error: "Task not found"}], count}`。

```bash
curl -X POST http://localhost:8080/api/tasks/batch-status \
  -H "Content-Type: application/json" \
  -d '{"task_ids": ["task_aaa", "task_bbb"]}'
```

### POST /api/tasks/batch-cancel

请求体 `{task_ids: [...], reason: "Batch cancel via API"}`（reason 可选）。响应 `{success, cancelled_task_ids, cancelled_count}`。

```bash
curl -X POST http://localhost:8080/api/tasks/batch-cancel \
  -H "Content-Type: application/json" \
  -d '{"task_ids": ["task_aaa", "task_bbb"], "reason": "wrong image set"}'
```

### GET /api/tasks/{task_id}/progress

响应 `{task_id, status, progress: {current_phase, phase_percentage, overall_percentage, phase_description}}`。

```bash
curl http://localhost:8080/api/tasks/task_xxx/progress
```

### GET /api/tasks/{task_id}/audit-log

查询参数 `limit`（默认 50）、`offset`（默认 0）。响应 `{task_id, logs: [{timestamp(Unix 毫秒), action, details, user_id}], count}`。

```bash
curl "http://localhost:8080/api/tasks/task_xxx/audit-log?limit=20&offset=0"
```

### GET /api/tasks/statistics

返回 `TaskManager::get_task_statistics()` 的原始 JSON（任务总数、按状态/优先级分布等）。

```bash
curl http://localhost:8080/api/tasks/statistics
```

响应要点：Dashboard 页直接消费（taskSlice → Dashboard），字段以 `get_task_statistics()` 输出为准（总数与按状态/优先级计数，未套 ApiResponse 外壳）。

### PUT /api/tasks/{task_id}/priority

请求体 `{"priority": "high"}`。响应 `{success: true, task_id, new_priority}`。
> **备注**：源码注释明确 "This would need to be implemented in TaskManager / For now, return success"——该端点目前**只回显不生效**。

```bash
curl -X PUT http://localhost:8080/api/tasks/task_xxx/priority \
  -H "Content-Type: application/json" \
  -d '{"priority": "critical"}'
```

> 该 no-op 行为是源码显式声明的事实，非文档错误。

### POST /api/tasks/{task_id}/resume —— 从阶段台账恢复

`OPTIONS` 预检返回 204。仅 `failed / cancelled / interrupted / paused` 且产物（镜像、库、提取目录）仍完好可指纹校验的任务可恢复（`TaskHelpers::is_resumable`）；已完成阶段输入未变的会被跳过，任务保留原 id、输出目录与配置。

```bash
curl -X POST http://localhost:8080/api/tasks/task_xxx/resume
```

响应 `200`：`{success: true, task_id, status, resume_count, resume_stage, message: "Task resumed from its stage ledger"}`。

- `404`：任务不存在（`task_id` 为 `list / statistics / cleanup / batch-*` 等子路由名同样 404）。
- `409`：`{success: false, task_id, error: "Task cannot be resumed", reason: "<不可恢复的具体原因>", status}`——`reason` 原样透出，便于运维判断哪个前提不满足。

### POST /api/tasks/{task_id}/pause —— 协作式暂停

`OPTIONS` 预检返回 204。请求体可选 `{"reason": "..."}`（body 非法不阻塞暂停，走默认原因）。暂停在**当前阶段跑完后的阶段边界**生效：任务停为 `paused`，之后可用 resume 以同一 id 继续。

```bash
curl -X POST http://localhost:8080/api/tasks/task_xxx/pause \
  -H "Content-Type: application/json" \
  -d '{"reason": "换班前暂停"}'
```

响应 `200`：`{success: true, task_id, status, message: "Pause requested; the current stage will finish first"}`。

- `404`：任务不存在（同上）。
- `409`：`{success: false, task_id, error: "Task cannot be paused", reason: "Only running or queued tasks can be paused", status}`。

暂停/恢复状态会体现在任务详情的 `pause_requested / resumable / resume_stage / resume_count` 字段上。

---

## 2. 取证分析 API

由 `ForensicsRoutes` 聚合注册（`ForensicsRoutes.h`），除特别说明外查询参数均需 `task_id`（必填，缺失返回 `400 {"error": "task_id parameter is required"}`），数据来自任务的 `_raw.db` / `_events.db` / 场景数据库。

### 2.1 时间线（TimelineRoutes）

| 方法 | 路径 | 关键参数（已验证） | 用途 |
|------|------|--------------------|------|
| GET | `/api/forensics/timeline/comprehensive` | `task_id`*、`start_time`、`end_time`、`event_type`、`limit=1000`、`offset=0`、`cluster=false`、`bucket=60`（聚簇秒窗，钳制到 [1,86400]） | 综合时间线，可选事件聚簇 |
| GET | `/api/forensics/timeline/full` | 同 comprehensive（直接复用同一 handler） | 全量时间线（分页） |
| GET | `/api/forensics/timeline/details` | `task_id`*、`bucket_index` 或 `window`（二者同传必须相等）、`type`、`parent` 或 `dir`（同传必须相等）、`limit=1000`、`offset=0`、`search`、`bucket=60` | 时间簇/目录明细事件 |
| GET | `/api/forensics/timeline/distribution` | `task_id`* | 事件时间分布 |
| GET | `/api/forensics/timeline/statistics-by-period` | 同 distribution（复用 handler） | 按周期统计（Swagger 声明 `period`，实际走 distribution） |
| GET | `/api/forensics/timeline/file-activity` | `task_id`*、`file_path`、`inode` | 单文件活动时间线 |
| GET | `/api/forensics/timeline/by-file` | 同 file-activity（复用 handler） | 按文件查询 |
| GET | `/api/forensics/timeline/suspicious-patterns` | `task_id`* | 可疑活动模式 |
| GET | `/api/forensics/timeline/user-activity` | `task_id`* | 用户活动分析 |
| GET | `/api/forensics/timeline/by-type` | `task_id`*、`type`（CREATED/MODIFIED/ACCESSED/CHANGED/DELETED） | 按事件类型过滤 |
| GET | `/api/forensics/timeline/by-time-range` | `task_id`*、`start`、`end` | 按时间范围查询（**本次核对源码补充**：该路由已在 `TimelineRoutes.cpp` 注册，此前文档遗漏） |

```bash
curl "http://localhost:8080/api/forensics/timeline/comprehensive?task_id=task_xxx&cluster=true&bucket=300&limit=500"
```

响应要点（`SQLiteHelper::get_comprehensive_timeline`）：顶层 `metadata{total_events, returned_events, limit, offset, has_more, start_time, end_time, event_type_filter, clustered, bucket_seconds}` + `timeline[]`。非聚簇行含 `timestamp / end_timestamp / event_type / cluster_count=1 / file_path / inode / description / file_size / file_type`；聚簇行额外含 `bucket_index / parent_directory / SUM 后的 file_size` 与 `group_descriptor{bucket_index, bucket_seconds, event_type, parent_directory, bucket_start_timestamp}`，并带 `llm_summary / llm_description / llm_keywords / llm_is_relevant`（events 表自愈补列）。

**按时间窗 + 事件类型过滤**：

```bash
curl "http://localhost:8080/api/forensics/timeline/comprehensive?task_id=task_xxx&start_time=2026-01-01&end_time=2026-02-01&event_type=DELETED&limit=200&offset=0"
```

**时间簇明细**（`bucket_index` × `type` × `parent` 定位一个簇）：

```bash
curl "http://localhost:8080/api/forensics/timeline/details?task_id=task_xxx&bucket_index=4938271&type=CREATED&parent=/etc/ssh/&bucket=60&search=sshd&limit=100"
```

响应要点：`events[]`（`id / timestamp / event_type / file_path / inode / description / file_size / file_type`）+ `descriptor{bucket_index, bucket_seconds, event_type, parent_directory, bucket_start_timestamp}`。`bucket_index` 与 `window` 同传必须相等，`parent` 与 `dir` 同传必须相等（否则 400）。

**事件时间分布**：

```bash
curl "http://localhost:8080/api/forensics/timeline/distribution?task_id=task_xxx"
```

响应要点：`distribution[]`（按 `event_date`(YYYY-MM-DD，本地时区) × `event_type` 分组的 `count`）+ `metadata.total_days`（源码注明由客户端自行计算，固定为 0）。

**按事件类型**：

```bash
curl "http://localhost:8080/api/forensics/timeline/by-type?task_id=task_xxx&type=MODIFIED"
```

响应要点：与 comprehensive 相同的 `metadata + timeline` 结构（复用同一 handler，`type` 即 `event_type`）。

**按时间范围**（注意参数名是 `start`/`end`，不是 comprehensive 的 `start_time`/`end_time`）：

```bash
curl "http://localhost:8080/api/forensics/timeline/by-time-range?task_id=task_xxx&start=1767225600&end=1770000000"
```

响应要点：复用 `get_comprehensive_timeline`，返回 `metadata + timeline`（limit 固定走 handler 默认）。

**单文件活动时间线**：

```bash
curl "http://localhost:8080/api/forensics/timeline/file-activity?task_id=task_xxx&file_path=/etc/ssh/sshd_config&inode=12345"
```

响应要点：`file_metadata`（`_raw.db` files 表单行，无匹配为 null）+ `activities[]`（events 表行）+ `total_activities`；`file_path` 为 LIKE 模糊匹配、`inode` 为精确匹配，二者可只用其一。

**可疑模式 / 用户活动**：

```bash
curl "http://localhost:8080/api/forensics/timeline/suspicious-patterns?task_id=task_xxx"
curl "http://localhost:8080/api/forensics/timeline/user-activity?task_id=task_xxx"
```

响应要点：可疑模式为 `suspicious_patterns[]` + `total_patterns_detected`（`StatisticsQueries.cpp`）；用户活动为 `hourly_activity_pattern[] / most_active_directories[] / user_directory_activity[]`。

### 2.2 事件簇分析（EventClusterRoutes）

| 方法 | 路径 | 请求体（已验证） | 用途 |
|------|------|------------------|------|
| POST | `/api/forensics/timeline/clusters/analyze` | `{task_id, time_window, event_type, parent_directory?}` | **已退役**（源码 `#if 0` 保留，未注册）：单簇 LLM 分析请走 Python `POST /api/llm/analyze-event-cluster` |
| POST | `/api/forensics/timeline/clusters/batch-analyze` | `{task_id, clusters: [...]}` | **已退役**（同上，曾为绕过 Python 护栏的 C++ LLM 路径） |
| POST | `/api/forensics/timeline/clusters/reanalyze` | `{task_id, time_window, event_type, parent_directory?}` | **已退役**（同上） |
| GET | `/api/forensics/timeline/clusters/analyzed` | 查询参数 `task_id`（必填） | **已弃用**（Phase D）：AnalysisCenter 已改用 Python `GET /api/llm/event-cluster-analyses`（分析记录真相源，多版本）；本端点为旧 60s 聚合实现，保留一个版本周期后移除 |

三个 POST 均另注册 OPTIONS 预检（现已随端点一并注释）。

**示例——单簇 LLM 分析**：

```bash
curl -X POST http://localhost:8080/api/forensics/timeline/clusters/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "task_xxx",
    "time_window": 4938271,
    "event_type": "CREATED",
    "parent_directory": "/etc/ssh/"
  }'
```

响应要点：簇分析结果（写入 events 表的 `llm_*` 自愈列，含 `llm_summary / llm_description` 类字段）。**批量分析**（clusters 为空数组返回 400）：

```bash
curl -X POST http://localhost:8080/api/forensics/timeline/clusters/batch-analyze \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "task_xxx",
    "clusters": [
      {"time_window": 4938271, "event_type": "CREATED", "parent_directory": "/etc/ssh/"},
      {"time_window": 4938272, "event_type": "MODIFIED", "parent_directory": "/tmp/"}
    ]
  }'
```

**已分析簇列表**：

```bash
curl "http://localhost:8080/api/forensics/timeline/clusters/analyzed?task_id=task_xxx"
```

响应要点：`task_id`（必填查询参数）对应 events 表中已有 `llm_analyzed_at` 的簇清单。

### 2.3 文件分析（FileAnalysisRoutes）

| 方法 | 路径 | 关键参数 | 用途 |
|------|------|----------|------|
| GET | `/api/forensics/files/paged` | `task_id`*、`page=1`、`page_size=100`(1–200)、`view=all\|analyzed\|documents\|media`、`extension`（逗号分隔白名单）、`exclude_extension`（黑名单，隐藏匹配项）、`min_size`、`max_size`（字节） | 文件列表服务端分页（Files 页主列表数据源） |
| GET | `/api/forensics/files/largest` | `task_id`*、`limit=50` | 最大文件列表 |
| GET | `/api/forensics/files/recent` | `task_id`*、`hours=24` | 最近 N 小时文件 |
| GET | `/api/forensics/files/suspicious` | `task_id`* | 可疑文件 |
| GET | `/api/forensics/files/duplicates` | `task_id`* | 重复文件（按哈希） |
| GET | `/api/forensics/files/extensions-analysis` | `task_id`* | 扩展名统计 |

**示例——文件分页列表 / 最大文件**：

```bash
curl "http://localhost:8080/api/forensics/files/paged?task_id=task_xxx&view=documents&extension=pdf,docx&page=1&page_size=50&exclude_extension=tmp"
curl "http://localhost:8080/api/forensics/files/largest?task_id=task_xxx&limit=10"
```

响应要点（`SQLiteHelper::get_files_paged`，读 `_files.db`）：`{files[]（files 表整行，按 size DESC、id ASC 排序）, total, page, page_size, total_pages, view}`。`view` 语义：`all` 不过滤；`analyzed` = 已有 LLM 描述（`llm_description` 非空）；`documents` = `category='Documents'`；`media` = `category IN ('Images','Videos','Audio Files')`。`extension`/`exclude_extension` 令牌只保留字母数字；`page`/`page_size`/`min_size`/`max_size` 非法时静默回落默认值，不报 400。

**最大 / 最近 / 可疑 / 重复 / 扩展名**：

```bash
curl "http://localhost:8080/api/forensics/files/recent?task_id=task_xxx&hours=48"
```

响应要点（`SQLiteHelper::get_largest_files`，读 `_files.db`）：`largest_files[]`（files 表行，含 path/size 等）+ `limit`。

**可疑文件 / 重复文件 / 扩展名统计**：

```bash
curl "http://localhost:8080/api/forensics/files/suspicious?task_id=task_xxx"
curl "http://localhost:8080/api/forensics/files/recent?task_id=task_xxx&hours=48"
```

响应要点：可疑文件为 `suspicious_files[]`（按类别分组的数组）；最近文件为 `recent_files[]` + `time_filter_hours`；重复文件为 `duplicates[]`（按哈希聚合）；扩展名统计为 `extension_analysis[]` + `category_analysis[]`。字段名均验证自 `Queries/FileAnalysisQueries.cpp` 的 `result["..."]` 赋值。

### 2.4 文件提取（FileExtractionRoutes）

**POST /api/forensics/extract**（含 OPTIONS）：启动后台提取任务。请求体（已验证）：

```json
{
  "task_id": "task_xxx",
  "mode": "all",              // all | extension | name | deleted（非法值 400）
  "pattern": ".pdf,.docx",    // extension/name 模式必填（非空白）
  "output_dir": "out/dir",    // 必须为任务提取目录下的相对路径（绝对路径/含 .. 会 400）
  "include_deleted": false,
  "overwrite": false,
  "max_files": 0,             // 三个限额必须为非负整数
  "max_total_size": 0,
  "max_file_size": 0
}
```

- `GET /api/forensics/extract/<job_id>`：按路径参数查任务状态。
- `GET /api/forensics/extract/status?job_id=...`：同上（查询参数形式）。

**POST /api/forensics/files/materialize**（含 OPTIONS）：把镜像内单个文件按需落地到任务提取目录。请求体：

```json
{
  "task_id": "task_xxx",
  "path": "Users/admin/Documents/contract.pdf"
}
```

- `path` 必须是**镜像内相对路径**（前导 `/` 会被剥掉；含 `..` 或为空返回 400 `path must be an image-relative file path without '..'`）。
- 只有 `_raw.db` 中有登记的文件记录才能提取（`FileExtractor::extractFileByPath`，同时尝试带/不带前导斜杠两种锚定）；输出固定写入任务提取目录（`PathManager::getTaskExtractDir`）下的同名相对路径，永不越出该目录。
- 任务或镜像未就绪 `404 {"error": "task not found"}` / `409 {"error": "task extraction inputs are not ready"}`；镜像打不开 500；文件不在镜像或不在 raw 记录中 `404 {"error": "file could not be extracted from the image"}`。

响应 `200`：`{success: true, materialized_path: "<任务提取目录内绝对路径>", bytes: <落盘字节数>}`。

```bash
curl -X POST http://localhost:8080/api/forensics/files/materialize \
  -H "Content-Type: application/json" \
  -d '{"task_id": "task_xxx", "path": "etc/ssh/sshd_config"}'
```

**示例——按扩展名提取到任务提取目录下的子目录**：

```bash
curl -X POST http://localhost:8080/api/forensics/extract \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "task_xxx",
    "mode": "extension",
    "pattern": ".pdf,.docx",
    "output_dir": "docs_only",
    "include_deleted": false,
    "overwrite": false,
    "max_files": 1000,
    "max_total_size": 0,
    "max_file_size": 0
  }'
```

响应 `202`：`{success: true, message: "Extraction job started", job_id, status: "pending"}`。注意 `output_dir` 必须是**相对**路径（绝对路径或含 `..` 返回 400），实际落盘位置为任务提取根目录（`PathManager::getTaskExtractDir`）下。

**轮询提取进度**（前端 `extractionService.pollExtractionStatus` 即轮此端点）：

```bash
curl "http://localhost:8080/api/forensics/extract/status?job_id=job_yyy"
```

响应要点：`{job_id, task_id, status, progress 类字段, output_path, ...}`——status 在 pending/running/completed/failed 间迁移；任务镜像/DB 未就绪时启动提取会得到 `409 {"error": "task extraction inputs are not ready"}`。

### 2.5 统计（StatisticsRoutes）

`GET /api/forensics/statistics/{overview, file-distribution, activity-patterns, deleted-files-analysis}` —— 均只需 `task_id`（必填）。

```bash
curl "http://localhost:8080/api/forensics/statistics/overview?task_id=task_xxx"
curl "http://localhost:8080/api/forensics/statistics/file-distribution?task_id=task_xxx"
curl "http://localhost:8080/api/forensics/statistics/activity-patterns?task_id=task_xxx"
curl "http://localhost:8080/api/forensics/statistics/deleted-files-analysis?task_id=task_xxx"
```

响应要点（字段名验证自 `Queries/StatisticsQueries.cpp`）：
- `overview`：`raw_database_stats / events_database_stats / files_database_stats`（三库各自的表行数统计）。
- `file-distribution`：`size_distribution[]` + `directory_sizes[]`（读 `_files.db`）。
- `activity-patterns`：`daily_pattern[] / weekly_pattern[] / event_type_distribution[]`（读 `_events.db`）。
- `deleted-files-analysis`：`deleted_summary / recently_deleted[] / deleted_by_type[]`（读 `_raw.db`）。

### 2.6 Android 取证（AndroidForensicsRoutes）

| 路径（前缀 `/api/forensics/android/`） | 参数 | 用途 |
|----------|------|------|
| `backup-overview` | `task_id`* | 手机备份总览（清单 + 制品计数 + 应用库解密状态 + 微信数据摘要） |
| `communication-summary` | `task_id`* | 通信摘要（短信/通话） |
| `app-usage` | `task_id`* | 应用使用统计 |
| `device-info` | `task_id`* | 设备信息 |
| `media-analysis` | `task_id`* | 媒体文件分析 |
| `miui-overview` | `task_id`* | MIUI 备份总览 |
| `miui-installed-apps` | `task_id`* | 已安装应用（其余查询参数被忽略） |
| `miui-db-inventory` | `task_id`* | 备份数据库清单（其余查询参数被忽略） |
| `miui-qqnt-overview` | `task_id`* | QQNT 概览 |
| `miui-qqnt-artifacts` | `task_id`*、`category`、`status`、`query`、`limit=100`、`offset=0` | QQNT 制品 |
| `miui-qqnt-records` | `task_id`*、`kind=kv`、`query`、`limit=100`、`offset=0`、`reveal_sensitive=0` | QQNT 聊天记录 |
| `miui-wechat-overview` | `task_id`* | 微信概览 |
| `miui-wechat-artifacts` | `task_id`*、`category`、`status`、`query`、`limit=100`、`offset=0` | 微信制品 |
| `miui-wechat-records` | `task_id`*、`kind=kv`、`query`、`limit=100`、`offset=0`、`reveal_sensitive=0` | 微信聊天记录 |
| `llm-summary` | `task_id`* | Android 各制品表 AI 分析覆盖率 |

所有端点均读任务的 `_android.db`（`RouteHelpers::get_database_path(task_id, "android")`）。响应字段名验证自 `Queries/AndroidQueries.cpp`。

**示例——通信摘要 / 应用使用**：

```bash
curl "http://localhost:8080/api/forensics/android/communication-summary?task_id=task_xxx"
curl "http://localhost:8080/api/forensics/android/app-usage?task_id=task_xxx"
```

响应要点：通信摘要为 `sms_summary / sms_by_type / whatsapp_summary / contacts_summary / call_summary / call_by_type`（表缺失时为空数组）；应用使用为 `installed_apps[] / usage_statistics[] / system_apps_count / app_database_files[]`。

**MIUI 分页过滤**（QQNT 制品，微信制品同构）：

```bash
curl "http://localhost:8080/api/forensics/android/miui-qqnt-artifacts?task_id=task_xxx&category=&status=&query=转账&limit=50&offset=0"
curl "http://localhost:8080/api/forensics/android/miui-wechat-records?task_id=task_xxx&kind=sqlite&query=&limit=100&offset=0&reveal_sensitive=0"
```

响应要点：`kind` 取值 `kv / sqlite / logs`（非法值 400 `kind must be one of: kv, sqlite, logs`）；`reveal_sensitive=1` 才会返回敏感值明文；分页为 `limit`（默认 100，最小 1）+ `offset`（默认 0）。

**MIUI 概览与 AI 覆盖率**：

```bash
curl "http://localhost:8080/api/forensics/android/backup-overview?task_id=task_xxx"
curl "http://localhost:8080/api/forensics/android/miui-overview?task_id=task_xxx"
curl "http://localhost:8080/api/forensics/android/llm-summary?task_id=task_xxx"
```

响应要点：`backup-overview`（`SQLiteHelper::get_miui_backup_overview`）为 `{manifest, artifact_counts[], decryption_status[], wechat{available, status, messages, contacts, chatrooms, owners}}`——`manifest` 优先读统一备份清单表 `mobile_backup_manifest`（`platform / device / backup_version / backup_date / package_count / manifest_sha256 / adapter_version`），老库回退 `miui_backup_manifest`（`device / miui_version / backup_date / total_size / package_count / source_folder`）；`decryption_status[]` 为 `app_db_inventory.open_status` 分布；`wechat` 汇总同库微信表行数，无数据时 `status` 反映 `com.tencent.mm` 的锁定状态；`miui-overview` 为备份清单（设备/版本/日期/尺寸）与 app 库解密状态分布；`llm-summary` 为各 Android 制品表"已分析 / 总数"覆盖率聚合。

### 2.7 内存取证（MemoryForensicsRoutes）

数据来自 `--memory-analyze` 产生的 `<镜像名>_memory.db`（Volatility3），只读打开；无 `_memory.db` 时返回 `404 {"error":"memory db not found"}`。所有端点需 `task_id`。

| 路径（前缀 `/api/forensics/memory/`） | 额外参数 | 说明 |
|----------|----------|------|
| `summary` | - | 各表行数概览 |
| `processes` | `search`（进程名过滤，参数化绑定） | `linux.pslist`，最多 1000 行，按 pid 排序 |
| `network` | - | `linux.sockstat` 网络连接 |
| `bash-history` | `keyword`（命令过滤） | `linux.bash` |
| `boot-info` | - | `linux.boottime` 键值对 |

**示例——内存概览与进程过滤**：

```bash
curl "http://localhost:8080/api/forensics/memory/summary?task_id=task_xxx"
curl "http://localhost:8080/api/forensics/memory/processes?task_id=task_xxx&search=sshd"
curl "http://localhost:8080/api/forensics/memory/bash-history?task_id=task_xxx&keyword=wget"
```

响应要点：`summary` 为对象 `{processes, network_connections, bash_history, sockets}`（各表 COUNT）；`processes` 为行数组（列名即 SQL 投影：`pid / ppid / comm / uid / creation_time`，按 pid 排序、上限 1000）；`network` 行含 `pid / comm / proto / local_addr / local_port / remote_addr / remote_port / state`；`bash-history` 行含 `pid / comm / command / history_index`；`boot-info` 行为 `key / value`。`search`/`keyword` 为参数化 LIKE 绑定（`%kw%`），防注入。

### 2.8 系统事件（SystemEventRoutes）

- `GET /api/forensics/system/events`：`task_id`*、`start_time`、`end_time`、`limit=1000`、`offset=0`。
- `GET /api/forensics/system/summary`：`task_id`*。

```bash
curl "http://localhost:8080/api/forensics/system/events?task_id=task_xxx&start_time=2026-01-01&end_time=2026-06-01&limit=200&offset=0"
curl "http://localhost:8080/api/forensics/system/summary?task_id=task_xxx"
```

响应要点（`Queries/StatisticsQueries.cpp`）：`events` 为 `metadata{...分页与过滤元信息} + system_events[]`；`summary` 为 `event_type_distribution[]` 与预留的 `priority_distribution / severity_distribution / source_distribution`（后三者源码固定为空数组）。

### 2.9 DLL/共享库分析（DLLAnalysisRoutes）

| 方法 | 路径 | 关键参数 | 用途 |
|------|------|----------|------|
| GET | `/api/forensics/dlls` | `task_id`*、`limit` | DLL 列表 |
| GET | `/api/forensics/dlls/<int>` | 路径参数 dll_id | DLL 详情（PE/ELF 头、导入导出、异常） |
| GET | `/api/forensics/dlls/suspicious` | `task_id`*、`limit`、`min_score` | 可疑 DLL（威胁分阈值） |
| GET | `/api/forensics/dlls/statistics` | `task_id`* | 统计 |
| GET | `/api/forensics/dlls/<int>/anomalies` | 路径参数 dll_id | 单 DLL 异常详情 |
| POST | `/api/forensics/dlls/analyze` | 请求体 `{file_path}`（必填，字符串） | 分析单个 DLL 文件 |
| GET | `/api/forensics/dlls/health` | - | 分析器健康检查 |

**示例——DLL 列表与可疑 DLL**：

```bash
curl "http://localhost:8080/api/forensics/dlls?task_id=task_xxx&limit=50"
curl "http://localhost:8080/api/forensics/dlls/suspicious?task_id=task_xxx&limit=20&min_score=0.7"
```

响应要点：列表为 JSON 数组，行含 `id(inode 充当临时 ID) / file_path / file_name / file_size / threat_score / format / machine_type / signature_status`；详情（`GET /dlls/<int>`）额外含 `md5 / sha1 / sha256 / imp_hash / compile_timestamp / subsystem / entry_point / image_base / is_dll / signer_name / file_version / company_name / llm_summary / llm_description / llm_keywords / sections[] / imports[]`（sections 行含 `name / virtual_address / virtual_size / entropy / is_writeable / is_executable / is_readable`）。不存在时 `404 {"error": "DLL not found"}`。

**按需分析单个 DLL**：

```bash
curl -X POST http://localhost:8080/api/forensics/dlls/analyze \
  -H "Content-Type: application/json" \
  -d '{"file_path": "/extracted/usr/lib/malicious.so"}'
```

**统计 / 单 DLL 异常 / 健康检查**：

```bash
curl "http://localhost:8080/api/forensics/dlls/statistics?task_id=task_xxx"
curl "http://localhost:8080/api/forensics/dlls/12345/anomalies"
curl "http://localhost:8080/api/forensics/dlls/health"
```

响应要点：`health` 固定 `{status: "ok", service: "dll-analyzer", version: "1.0", timestamp}`；详情级端点的 DLL id 即 `id` 字段（inode）。

### 2.10 场景查询（SceneQueryRoutes）

| 方法 | 路径 | 关键参数 | 用途 |
|------|------|----------|------|
| GET | `/api/tasks/<task_id>/scene-stats` | 路径参数 task_id | 按场景分组的文件/制品统计（`scene_stats[].scene_type/total_files/relevant_files/total_size/llm_analyzed_files`、`artifact_stats[]`） |
| GET | `/api/tasks/<task_id>/scene-artifacts` | `scene_type`*（白名单 `android/windows/linux`）、`limit=100`、`offset=0` | 场景制品分页列表（含关联源文件与 LLM 字段） |

**示例**：

```bash
curl "http://localhost:8080/api/tasks/task_xxx/scene-stats"
curl "http://localhost:8080/api/tasks/task_xxx/scene-artifacts?scene_type=android&limit=50&offset=0"
```

响应要点：`scene-stats` 为 `{task_id, scene_stats[], artifact_stats[]}`——`scene_stats` 行含 `scene_type / total_files / relevant_files / total_size / llm_analyzed_files`（GROUP BY files.scene_type），`artifact_stats` 行含 `scene_type / artifact_count / analyzed_count`（UNION 查询 `android_artifacts / windows_artifacts / linux_artifacts` 三表，表不存在时该段为空数组）；`scene-artifacts` 为场景制品分页行（含关联源文件与 LLM 分析字段）。`scene_type` 非白名单值返回 400。

### 2.11 导出（ExportRoutes）

| 方法 | 路径 | 关键参数 | 用途 |
|------|------|----------|------|
| GET | `/api/forensics/export/toon` | `task_id`*、`fields`（列选择）、`filter` | TOON 文本格式导出 |
| GET | `/api/forensics/export/events/json` | `task_id`*、`query` | 事件 JSON 导出 |
| GET | `/api/forensics/export/events/csv` | `task_id`*、`query` | 事件 CSV 导出 |
| GET | `/api/forensics/export/events/visualization` | `task_id`* | 可视化用事件导出 |

**示例——TOON 文本导出（列选择 + 过滤）**：

```bash
curl -o files_export.toon \
  "http://localhost:8080/api/forensics/export/toon?task_id=task_xxx&fields=path,size,md5&filter=size%20%3E%201048576"
```

响应要点：`200` 时 Content-Type 为 `text/toon; charset=utf-8`，带 `Content-Disposition: attachment; filename="files_export.toon"`，正文为 TOON 文本；`filter` 是原始 WHERE 片段，经 `SQLiteHelper::is_safe_filter_clause` 校验，越权片段返回 `400 {"error": "invalid filter clause"}`。

**事件 JSON/CSV 导出（限定只读 SELECT）**：

```bash
curl "http://localhost:8080/api/forensics/export/events/json?task_id=task_xxx&query=SELECT%20*%20FROM%20events%20WHERE%20event_type%20%3D%20%27DELETED%27"
curl "http://localhost:8080/api/forensics/export/events/csv?task_id=task_xxx"
```

响应要点：`{success: true, output_file: "<task_id>_events.json|csv", events_count, format: "json|csv"}`；`query` 必须是单条只读 SELECT（`is_readonly_select` 校验，否则 400），输出文件落在服务端工作目录。

---

## 3. 案件管理 API

> 源码：`CaseCRUDRoutes.cpp`（案例管理器 `CaseManager.h`）

| 方法 | 路径 | 请求体/参数 | 用途 |
|------|------|-------------|------|
| GET | `/api/cases` | - | 案件列表 |
| POST | `/api/cases` | `{name="Unnamed Case", description="", task_ids?[]}` | 创建案件 |
| GET | `/api/cases/<case_id>` | 路径参数 | 案件详情（含任务列表） |
| PUT | `/api/cases/<case_id>/tasks` | `{task_ids: [...]}`（必填数组） | 设置案件任务 |
| PUT | `/api/cases/<case_id>/status` | `{status, cross_analysis_job_id?}` | 更新案件状态 |
| DELETE | `/api/cases/<case_id>` | 路径参数 | 删除案件 |

**示例——创建案件并挂任务**：

```bash
curl -X POST http://localhost:8080/api/cases \
  -H "Content-Type: application/json" \
  -d '{
    "name": "2026-电信诈骗案",
    "description": "两部手机 + 一台服务器镜像",
    "task_ids": ["task_xxx", "task_yyy"]
  }'
```

响应 `201`：`{id, name, description, task_ids, status: "open", cross_analysis_job_id, created_at(Unix 毫秒), updated_at}`——`case_to_json` 的全部字段。status 取值 `open / analysing / completed / failed`。

**更新案件状态（联动交叉分析 job）**：

```bash
curl -X PUT http://localhost:8080/api/cases/case_zzz/status \
  -H "Content-Type: application/json" \
  -d '{"status": "analysing", "cross_analysis_job_id": "job_aaa"}'
```

**案件列表 / 详情 / 追加任务 / 删除**：

```bash
curl http://localhost:8080/api/cases
curl http://localhost:8080/api/cases/case_zzz
curl -X PUT http://localhost:8080/api/cases/case_zzz/tasks \
  -H "Content-Type: application/json" \
  -d '{"task_ids": ["task_xxx"]}'
curl -X DELETE http://localhost:8080/api/cases/case_zzz
```

响应要点：列表为 `{cases: [...], total}`；`PUT .../tasks` 成功后回写更新后的完整案件对象；删除成功 `{success: true, message: "Case deleted"}`，不存在 `404 {"error": "Case not found"}`。案件持久化在 `data/cases.json`（`CaseManager.cpp` 的 `cases_json_path()`）。

---

## 4. 全文搜索 API

> 源码：`SearchRoutes.cpp`（索引路径受 `FTS_ALLOWED_ROOT` 环境变量约束，默认限 PathManager 数据目录内，防任意文件读取）

### GET /api/search/fulltext

查询参数：`q`（**必填**）、`index`（索引路径）、`limit=50`、`offset=0`。返回匹配文档列表与分页信息。

```bash
curl "http://localhost:8080/api/search/fulltext?q=%E8%BD%AC%E8%B4%A6&index=/data/idx&limit=20&offset=0"
```

响应要点：`{query, results: [{path, score, snippet}], count, limit, offset}`。`q` 为空 `400 {"error": "Query parameter 'q' is required"}`；`index` 为空同样 400（**注意：index 实为必传**，缺失即被 handler 拒绝，Swagger 标注 optional 与代码不符——以代码为准）。索引路径受 `FTS_ALLOWED_ROOT` 约束，越界读取会被 `POST /api/search/index` 拒绝（搜索端点打开的索引同样应位于该根下）。

### POST /api/search/index

请求体 `{source_path, index_path, recursive=true}`——`source_path` 与 `index_path` **均必填**，缺失返回 `400`。

```bash
curl -X POST http://localhost:8080/api/search/index \
  -H "Content-Type: application/json" \
  -d '{"source_path": "/data/extracted", "index_path": "/data/idx"}'
```

响应要点：`{success: true, source_path, index_path, indexed_count}`；`indexed_count` 为成功抽取文本并入索引的文件数（无法抽取文本的文件跳过）。路径越出允许根时 `403 {error, allowed_root, hint}`；`source_path` 不存在 `400 {"error": "Source path does not exist"}`。

---

## 5. 文件过滤配置 API

> 源码：`FilterRoutes.cpp` —— **唯一使用 ApiResponse 封装的路由组**，响应形如 `{success, message, data, timestamp, pagination, error_code}`。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/filter/profiles` | 列出全部过滤配置 |
| GET | `/api/filter/profiles/<name>` | 配置详情 |
| POST | `/api/filter/profiles` | 创建/更新配置：`{name(必填), description, version="1.0", combine_mode="exclude_wins", include{...}, exclude{...}}` |
| DELETE | `/api/filter/profiles/<name>` | 删除自定义配置 |
| POST | `/api/filter/apply` | 应用到任务：`{task_id(必填), profile_name(必填)}` |

**示例——列出 / 读取配置**：

```bash
curl http://localhost:8080/api/filter/profiles
curl http://localhost:8080/api/filter/profiles/telecom_fraud
```

响应要点（ApiResponse 封装）：`{success: true, message, data: {profiles: [{filename, name, description}], count}}`；详情为 `data: {name, description, version, include{...}, exclude{...}, combine_mode}`，其中 `include` 含 `extensions / path_patterns / filename_patterns / min_size / max_size / include_deleted / include_allocated`。

**创建自定义配置**：

```bash
curl -X POST http://localhost:8080/api/filter/profiles \
  -H "Content-Type: application/json" \
  -d '{
    "name": "docs_only",
    "description": "只要文档类文件",
    "version": "1.0",
    "combine_mode": "exclude_wins",
    "include": {"extensions": [".pdf", ".docx", ".xlsx"], "include_deleted": true},
    "exclude": {"path_patterns": ["/proc/", "/sys/"]}
  }'
```

响应要点：新建 `201`、更新 `200`，`data: {name, path}`；内置配置（`general_forensics / telecom_fraud / data_breach / virus_intrusion`）不可覆盖或删除（`403 FORBIDDEN`）。

**应用到任务（生成 `_filtered.db`）**：

```bash
curl -X POST http://localhost:8080/api/filter/apply \
  -H "Content-Type: application/json" \
  -d '{"task_id": "task_xxx", "profile_name": "docs_only"}'
```

响应要点：`data: {task_id, profile_name, filtered_db, total_files, included_files, excluded_files}`；任务或 raw 库不存在 `404`。

---

## 6. 系统与文档 API

> 由 `SystemRoutes` 聚合：SystemHealthRoutes + SystemInfoRoutes + SystemDocsRoutes。

### 健康检查

| 方法 | 路径 | 响应要点 |
|------|------|----------|
| GET | `/api/system/health` | `{status:"healthy", timestamp(ms), version, task_management{total_tasks,running_tasks,failed_tasks,system_load}, services{...}}` |
| GET | `/api/health` | 同上的别名 |
| GET | `/api/health/live` | `{status:"alive", timestamp(ms)}` |
| GET | `/health/live` | `{status:"alive"}`（根前缀别名，`HTTPserver.cpp` 注册；现场认证下亦免鉴权） |
| GET | `/api/health/ready` | `{ready: bool, checks{task_manager, database}, timestamp}`；未就绪时 `503` |
| GET | `/api/health/dependencies` | 依赖服务状态明细 |
| GET | `/api/security/status` | 现场安全模式自检：`{field_security_version:"6a-v1", release_id, release_layout_version:"6c-v1", source_commit, source_tree_sha256, field_auth: bool, required_auth: bool, outbound_policy}`（响应带 `Cache-Control: no-store`） |

```bash
curl http://localhost:8080/api/system/health
curl http://localhost:8080/api/health/ready
curl http://localhost:8080/api/health/dependencies
curl http://localhost:8080/api/security/status
```

响应要点：`/api/system/health` 含 `status / timestamp / version / task_management{total_tasks, running_tasks, failed_tasks, system_load} / services{...}`；`ready` 未通过检查时返回 `503`；`dependencies` 列出 C++/Python/Neo4j 等依赖的连通状态明细；`security/status` 的取值来自环境变量 `TRACELENS_FIELD_AUTH`（`field_auth`）、`TRACELENS_REQUIRE_FIELD_AUTH=1`（`required_auth`）与 `FIELD_OUTBOUND_POLICY`（`outbound_policy`，缺省 `disabled`），release 指纹为编译期注入。

### 系统信息

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/system/info` | 服务/构建信息 |
| GET | `/api/system/databases?task_id=...` | 任务数据库文件 |
| GET | `/api/system/database-schema/<db_type>` | 指定类型数据库的表结构 |
| GET | `/api/system/logs?lines=...` | 系统日志（`lines` 可选） |
| ANY | `/python/<path>` | 同源网关：把带 `/python` 前缀的 GET/POST/PUT/DELETE/PATCH 请求转发到 Python 服务（生产前端所有 Python 调用统一走此网关，免跨域） |
| POST | `/api/export/<task_id>` | 导出任务数据；请求体 `{format: ...}` 可选 |

```bash
curl http://localhost:8080/api/system/info
curl "http://localhost:8080/api/system/databases?task_id=task_xxx"
curl "http://localhost:8080/api/system/database-schema/events"
curl "http://localhost:8080/api/system/logs?lines=100"
curl -X POST http://localhost:8080/api/export/task_xxx \
  -H "Content-Type: application/json" \
  -d '{"format": "json"}'
```

### 文档

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/docs` | Swagger UI 页面 |
| GET | `/api/docs/endpoints` | 全部端点清单（JSON） |
| GET | `/api/docs/database-schema` | 全部数据库模式文档 |
| GET | `/api/docs/openapi.json` | OpenAPI 规范 |

```bash
curl http://localhost:8080/api/docs/endpoints | head
curl http://localhost:8080/api/docs/openapi.json | python3 -m json.tool | head
```

用途：`/api/docs/endpoints` 输出的端点清单可与本文的路径表交叉验证（systemService 即消费它做 Settings 页的端点浏览）；`openapi.json` 与 Swagger UI 一致，均为 `Swagger::RegisterEndpoint` 注册内容的渲染。注意：个别参数在 Swagger 中标注为可选而 handler 实际必填（如 `/api/search/fulltext` 的 `index`），**以 handler 代码为准**。

---

## 7. 已知未注册路由

以下 OSS 路由文件存在于源码树并参与编译，但**从未被任何聚合器注册**（`ForensicsRoutes.h` 不含 OSSRoutes*，运行时访问将 404）：

- `OSSRoutes.cpp` / `OSSRoutes_new.cpp`
- `OSSAnalysisRoutes.cpp`（`/api/forensics/oss/analyze` 等）
- `OSSQueryRoutes.cpp`（`/api/forensics/oss/objects`、`/logs` 等）
- `OSSStatsRoutes.cpp`（`/api/forensics/oss/stats/*` 等）

旧文档中的整个"OSS 对象存储分析 API"章节在 C++ 服务上**不可用**，请勿调用。Python 侧 OSS AI 能力见 `/api/forensics/oss/ai/*`（Python_REST_API.md）。

---

## 附录：端点 ↔ 前端页面 ↔ 后端数据源映射

前端服务层（`web/src/services/`）是页面与后端之间唯一边界；`import api from './api'` 即指向本 C++ 服务（同源代理 :8080）。下表整理各端点组的真实调用方、后端查询实现与读写的库表（页面消费者详见 `docs/modules/web/Services.md` 与 `Pages.md`）。

| 端点组 | 前端调用方（web/src/services/） | 页面/组件消费者 | 后端查询/服务 | 读写的库表/文件 |
|--------|--------------------------------|----------------|----------------|------------------|
| `POST/GET /api/tasks`（创建/列表） | taskService.js（createTask/fetchTasks/listTasks） | taskSlice、TaskSelector、Tasks 页 | TaskManager（create_task/start_analysis/get_all_tasks） | data/tasks.json + 任务产物库 |
| `GET /api/tasks/{id}`（详情/results） | taskService.js（fetchTaskById/getTaskResults） | AnalysisCenter（llm_results.descriptions） | TaskManager + SQLiteHelper::get_file_summary | `_files.db`（files / file_descriptions） |
| `GET /api/tasks/{id}/progress` | taskService.js（getTaskProgress） | taskSlice.fetchTaskProgress → useTaskPolling | TaskManager 进度快照 | 内存（tasks.json 状态） |
| `DELETE /api/tasks/{id}` | taskService.js（cancelTask/deleteTask） | Tasks / Cases 页 | TaskManager::delete_task（取消+清理） | data/tasks.json + 任务目录 |
| `POST /api/tasks/batch-*`、audit-log、priority、cleanup、statistics | taskService.js（batchCreateTasks/batchGetTaskStatus/batchCancelTasks/getTaskAuditLog/updateTaskPriority/cleanupOldTasks/getTaskStatistics） | statistics→Dashboard；其余暂无页面 | TaskManager / AuditLog | data/tasks.json、审计日志存储 |
| `POST /api/tasks/{id}/pause`、`/resume` | taskService.js（pauseTask/resumeTask） | Tasks 页操作菜单（仅 failed/cancelled/interrupted/paused 可 resume） | TaskManager 阶段台账（stage ledger） | data/tasks.json + 任务目录 |
| timeline（comprehensive/details/distribution/file-activity/suspicious-patterns/user-activity/by-type、clusters/analyzed） | forensicsService.js（getComprehensiveTimeline 等 7 个 + getAnalyzedEventClusters） | Timeline 页、AnalysisCenter | SQLiteHelper::get_comprehensive_timeline / get_timeline_details / get_timeline_distribution / get_file_activity_timeline / get_suspicious_patterns / get_user_activity_analysis | `_events.db`(events 含 llm_* 自愈列)、`_raw.db`(files) |
| timeline/clusters/analyze（C++ 侧） | 前端已切 Python `/api/llm/analyze-event-cluster`（forensicsService 注释明示） | — | EventClusterRoutes（保留注册） | `_events.db` llm_* 列 |
| files（paged/largest/recent/suspicious/duplicates/extensions-analysis） | forensicsService.js（paged + 5 个 get* 函数） | Files 页 | `get_files_paged`（服务端分页）+ SQLiteHelper::get_largest_files / get_recent_files / get_suspicious_files / get_duplicate_files / get_extensions_analysis | `_files.db`(files)、`_raw.db`(files) |
| `POST /api/forensics/files/materialize` | （暂无前端直调；预留给证据查看深链） | — | FileExtractor::extractFileByPath（raw 记录成员校验） | 镜像（只读）→ 任务提取目录 |
| statistics（overview/file-distribution/activity-patterns/deleted-files-analysis） | forensicsService.js（4 个） | Statistics 页 | SQLiteHelper::get_overview_statistics / get_file_distribution_analysis / get_activity_patterns / get_deleted_files_analysis | `_raw.db` / `_files.db` / `_events.db` |
| android（含 backup-overview、miui-*、llm-summary） | forensicsService.js（getMiui*/getAndroid*） | Android 页 | SQLiteHelper::get_android_* / get_miui_backup_overview 等（AndroidQueries.cpp） | `_android.db`（sms_messages、call_logs、contacts、android_artifacts 等表） |
| memory（summary/processes/network/bash-history/boot-info） | memoryService.js（5 个 getMemory*） | Memory 页 | MemoryForensicsRoutes 直查 `_memory.db`（只读） | `<镜像名>_memory.db`（processes、network_connections、bash_history、sockets、boot_info） |
| system/events、system/summary | （暂无直接页面调用） | — | SQLiteHelper::get_system_events / get_system_event_summary | `_events.db`(events) |
| dlls（列表/详情/suspicious/statistics/anomalies/analyze/health） | llmService.js（analyzeDLL 走 Python）；C++ 直连调用方为 Python dll 路由 | Files 页（经 Python） | DLLAnalysisDatabase（getAllDLLs/getDLLById） | `_dll.db`（DLL 分析库） |
| scene-stats / scene-artifacts | （暂无直接页面调用） | — | SceneQueryRoutes 直查 | `_files.db`(files.scene_type、android/windows/linux_artifacts) |
| export/toon | systemService.js（exportToon） | Terminal / 导出入口 | TOONExporter | `_files.db`(files，只读) |
| export/events/{json,csv,visualization} | （暂无直接页面调用） | — | SQLiteHelper::export_events_to_json/csv/for_visualization | `_events.db`(events) + 服务端输出文件 |
| extract / extract/status | extractionService.js（startExtraction/getExtractionStatus/pollExtractionStatus） | Files 页、useFileExtraction | FileExtractor 后台 job（内存 job 表 + 工作线程） | 任务提取目录（extract_dir）、`_raw.db`(只读) |
| cases（/api/cases CRUD） | （前端案件走 Python caseGroupService `/api/llm/cases` 代理，最终落到这组 C++ 端点） | caseSlice / Cases 页 | CaseManager | data/cases.json |
| search/fulltext、search/index | searchService.js（searchFulltext/createSearchIndex） | Search 页 | XapianSearcher / XapianIndexer + TextExtractor | Xapian 索引目录（FTS_ALLOWED_ROOT 内） |
| filter/profiles、filter/apply | filterService.js（5 个函数） | filterSlice、FileFilters / FilterProfileSelector | FileFilter::listProfiles/loadProfile/applyFilterByName | config/filter_profiles/*.json、`_raw.db`→`_filtered.db` |
| system/health、health/* | systemService.js（getSystemHealth 等） | Dashboard | SystemHealthRoutes（TaskManager 统计） | 内存 |
| system/info、databases、database-schema、logs | systemService.js | Settings、Dashboard | SystemInfoRoutes | 任务库文件、日志文件 |
| docs/endpoints、docs/database-schema | systemService.js（getEndpoints/getDatabaseSchema） | Settings | Swagger 注册表 / 模式文档 | 内存（注册内容） |
| `POST /api/export/{task_id}` | systemService.js（exportTaskData） | Settings / 导出 | SystemInfoRoutes 导出 handler | 任务产物库 |

> 说明：OSS 相关 6 个前端读端点（ossService.js 的 `/api/forensics/oss/*`）在本服务无对应实现（见第 7 节"已知未注册路由"），运行时 404——`Pages.md` 与 `Services.md` 已标注。

---

## 相关文档

- [Python REST API 参考](./Python_REST_API.md)
- [快速入门指南](../getting-started/QuickStart.md)
- 前端服务映射细节：[web/Services 模块文档](../modules/web/Services.md)

---

**最后更新**: 2026-11-10（增量核对分支 feature/model-routing：新增任务 pause/resume、files/paged、files/materialize、backup-overview、security/status、/python 网关；创建任务字段与 android_source 取值按现源码重核）
