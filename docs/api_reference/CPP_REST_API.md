# C++ REST API 参考文档

> 本文档基于 `src/network/HTTPServer/routes/` 下的路由源码逐文件重写，所有路径、参数与响应字段均以代码为准。

## 概述

C++ HTTP 服务（Crow 框架）提供取证分析任务管理、时间线/文件/内存取证查询、案件管理、全文搜索与文件过滤等功能。

| 项目 | 说明 |
|------|------|
| 默认端口 | **8080**（`ConfigManager::getHTTPServerPort()`，读配置项 `HTTP_SERVER_PORT`，见 `src/core/ConfigManager/ConfigManager.cpp:140`） |
| run.sh 启动 | `run.sh` 中 `CPP_PORT="${HTTP_SERVER_PORT:-8666}"`，**未设置该变量时回退 8666** |
| scripts 启动 | `scripts/start_services.sh`、`start_all_services.sh` 均为 `${HTTP_SERVER_PORT:-8080}` |
| 认证 | 无（本地服务，未实现鉴权） |
| CORS | 所有路由经 `RouteHelpers::add_cors_headers` 添加跨域头；16 个任务路径另注册同名 OPTIONS 预检路由（`TaskRoutes.cpp`） |
| Swagger UI | `GET /api/docs`（注意：是 `/api/docs`，不是旧文档写的 `/api/docs/ui`） |
| OpenAPI JSON | `GET /api/docs/openapi.json` |
| 端点清单 | `GET /api/docs/endpoints` |
| 静态资源 | `GET /` 与 `GET /<path>` 托管 `web/dist` 下的前端 SPA（`HTTPserver.cpp::setup_static_routes`） |

**服务器地址**：`http://localhost:8080`（或 `http://localhost:8666`，取决于启动方式）

## 响应约定（以代码为准，与旧文档不同）

- 仅 `/api/filter/*`（FilterRoutes）使用统一封装 `ApiResponse`：`{success, message, data, timestamp, pagination, error_code}`（定义在 `src/network/HTTPServer/HTTPserver.h:35`）。
- **其余所有路由直接返回领域 JSON 对象**（如 `{tasks: [...]}`、`{task_id: ...}`），不套 ApiResponse 外壳。
- 失败时绝大多数路由返回 `{"error": "<原因>"}`（部分附 `task_id`/`message` 字段），HTTP 状态码为 400/404/500。
- 任务状态与优先级值**均为小写字符串**（`TaskHelpers.cpp`）：状态 `pending / running / completed / failed / cancelled`；优先级 `low / normal / high / critical`；阶段 `initializing / image_analysis / event_extraction / file_classification / llm_analysis / platform_analysis / file_carving / finalizing`。

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
> `/tasks*` 与 `/api/tasks*` 两组路径多数共用同一 handler。

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/tasks`、`/api/tasks`、`/api/tasks/list` | 列出任务（过滤+分页） |
| POST | `/tasks`、`/api/tasks` | 创建取证分析任务 |
| GET/PUT | `/api/tasks/<task_id>` | 获取任务详情（PUT 为同一 handler 的别名，不执行更新） |
| GET | `/tasks/<task_id>` | 获取任务详情（旧路径） |
| GET | `/tasks/<task_id>/results`、`/api/tasks/<task_id>/results` | 获取任务结果 |
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

另有 16 个同名路径的 `OPTIONS` CORS 预检路由（`TaskRoutes.cpp`，含 `/api/tasks/<string>/priority`、`/api/tasks/<string>/databases` 等）。

### POST /api/tasks —— 创建任务

`POST /tasks` 与之完全相同。请求体字段（验证自 `TaskCRUDRoutes.cpp::handle_create_task`）：

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
| `llm_analyze` | bool | false | 是否执行 LLM 分析 |
| `llm_mode` | string | `smart` | `full / smart` |
| `case_description` | string | 空 | 案情描述（LLM 分析上下文） |
| `filter_profile` | string | 空 | 文件过滤配置名 |
| `enable_decryption` | bool | false | 启用解密 |
| `key_file_dir` | string | 空 | 密钥目录（接受旧拼写 `key_dir`） |
| `decrypt_password` | string | 空 | 解密口令 |
| `android_source` | string | `tsk` | `tsk / dir / zip / miui-backup`；非 `tsk` 时跳过磁盘管线直达 Android 分析器（不产 `_raw.db`） |
| `backup_password` | string | 空 | MIUI/Android 备份 AES-256 口令（仅运行期使用，不落盘） |
| `file_carving` | bool | false | 文件雕刻；同时接受顶层与 `options.file_carving` 两种写法 |

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
  "llm_mode": "smart",
  "file_carving": false,
  "filter_profile": "",
  "android_source": "miui-backup",
  "dependencies_count": 0
}
```

请求体非法时返回 `400`，body 为文本 `Invalid request: <原因>`。

### GET /api/tasks —— 任务列表

查询参数：`status`、`priority`（值为 `all` 或具体小写状态/优先级）、`limit`（默认 **100**）、`offset`（默认 0）。

响应：`{tasks: [<task 对象>], pagination: {total, limit, offset, has_more}, filters: {status, priority}}`

`task` 对象字段（`TaskHelpers::task_to_json`）：`id, image_path, status, priority, message, output_files_db, output_raw_db, output_events_db, progress{current_phase, phase_percentage, overall_percentage, phase_description}, timestamps{created, started, completed, execution_time_seconds}(Unix 毫秒), scenarios, scenario_databases, android_analyze, android_source, llm_analyze, llm_mode, file_carving, filter_profile, case_description, xfs_mode, db_output_dir, extraction_directory, cancellation_requested, dependencies, dependents_count, metadata, error_details`。

> 注意：`task_id` 为 `list / statistics / cleanup / batch-create / batch-status / batch-cancel` 时，`GET /api/tasks/<task_id>` 显式返回 404，避免与子路由冲突。

### GET /api/tasks/{task_id}/results —— 任务结果

- 任务未完成：`202`，`{status, message: "Task not completed yet", task_id}`。
- 已完成：`200`，`{task_id, status: "completed", results: <文件摘要>, output_files_db}`；若 `_files.db` 中有 LLM 证据则追加 `llm_results` 与 `output_descriptions_db`（后者为 `output_files_db` 的别名）。结果带缓存，DB 新增 LLM 证据后会自动重建。

### DELETE /api/tasks/{task_id}

调用 `TaskManager::delete_task`。成功 `200` `{success: true, task_id, message: "Task deleted successfully"}`；不存在 `404`。

### POST /api/tasks/cleanup

请求体 `{max_age_hours: 24}`（可选，默认 24）。响应 `{success, removed_count, message}`。

### GET /api/tasks/{task_id}/databases

响应 `{task_id, databases: [{type: "raw|events|files", path, name}], count}`。

### POST /api/tasks/batch-create

请求体 `{image_paths: ["/path/a.E01", ...], priority: "normal"}`。响应 `201` `{success, task_ids: [...], count}`。

### POST /api/tasks/batch-status

请求体 `{task_ids: [...]}`。响应 `{statuses: [{task_id, status, progress} | {task_id, error: "Task not found"}], count}`。

### POST /api/tasks/batch-cancel

请求体 `{task_ids: [...], reason: "Batch cancel via API"}`（reason 可选）。响应 `{success, cancelled_task_ids, cancelled_count}`。

### GET /api/tasks/{task_id}/progress

响应 `{task_id, status, progress: {current_phase, phase_percentage, overall_percentage, phase_description}}`。

```bash
curl http://localhost:8080/api/tasks/task_xxx/progress
```

### GET /api/tasks/{task_id}/audit-log

查询参数 `limit`（默认 50）、`offset`（默认 0）。响应 `{task_id, logs: [{timestamp(Unix 毫秒), action, details, user_id}], count}`。

### GET /api/tasks/statistics

返回 `TaskManager::get_task_statistics()` 的原始 JSON（任务总数、按状态/优先级分布等）。

### PUT /api/tasks/{task_id}/priority

请求体 `{"priority": "high"}`。响应 `{success: true, task_id, new_priority}`。
> **备注**：源码注释明确 "This would need to be implemented in TaskManager / For now, return success"——该端点目前**只回显不生效**。

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

```bash
curl "http://localhost:8080/api/forensics/timeline/comprehensive?task_id=task_xxx&cluster=true&bucket=300&limit=500"
```

### 2.2 事件簇分析（EventClusterRoutes）

| 方法 | 路径 | 请求体（已验证） | 用途 |
|------|------|------------------|------|
| POST | `/api/forensics/timeline/clusters/analyze` | `{task_id, time_window, event_type, parent_directory?}` | LLM 分析一个事件簇（`time_window`+`event_type` 唯一标识簇） |
| POST | `/api/forensics/timeline/clusters/batch-analyze` | `{task_id, clusters: [{time_window, event_type, parent_directory?}, ...]}` | 批量分析（clusters 为空数组返回 400） |
| POST | `/api/forensics/timeline/clusters/reanalyze` | `{task_id, time_window, event_type, parent_directory?}` | 重新分析已有簇 |
| GET | `/api/forensics/timeline/clusters/analyzed` | 查询参数 `task_id`（必填） | 已分析簇列表 |

三个 POST 均另注册 OPTIONS 预检。

### 2.3 文件分析（FileAnalysisRoutes）

| 方法 | 路径 | 关键参数 | 用途 |
|------|------|----------|------|
| GET | `/api/forensics/files/largest` | `task_id`*、`limit=50` | 最大文件列表 |
| GET | `/api/forensics/files/recent` | `task_id`*、`hours=24` | 最近 N 小时文件 |
| GET | `/api/forensics/files/suspicious` | `task_id`* | 可疑文件 |
| GET | `/api/forensics/files/duplicates` | `task_id`* | 重复文件（按哈希） |
| GET | `/api/forensics/files/extensions-analysis` | `task_id`* | 扩展名统计 |

### 2.4 文件提取（FileExtractionRoutes）

**POST /api/forensics/extract**（含 OPTIONS）：启动后台提取任务。请求体（已验证）：

```json
{
  "task_id": "task_xxx",
  "mode": "all",              // all | extension | name | deleted（非法值 400）
  "pattern": ".pdf,.docx",    // extension/name 模式必填（非空白）
  "output_dir": "/out/dir",
  "include_deleted": false,
  "overwrite": false,
  "max_files": 0,             // 三个限额必须为非负整数
  "max_total_size": 0,
  "max_file_size": 0
}
```

- `GET /api/forensics/extract/<job_id>`：按路径参数查任务状态。
- `GET /api/forensics/extract/status?job_id=...`：同上（查询参数形式）。

### 2.5 统计（StatisticsRoutes）

`GET /api/forensics/statistics/{overview, file-distribution, activity-patterns, deleted-files-analysis}` —— 均只需 `task_id`（必填）。

### 2.6 Android 取证（AndroidForensicsRoutes）

| 路径（前缀 `/api/forensics/android/`） | 参数 | 用途 |
|----------|------|------|
| `communication-summary` | `task_id`* | 通信摘要（短信/通话） |
| `app-usage` | `task_id`* | 应用使用统计 |
| `device-info` | `task_id`* | 设备信息 |
| `media-analysis` | `task_id`* | 媒体文件分析 |
| `miui-overview` | `task_id`* | MIUI 备份总览 |
| `miui-installed-apps` | `task_id`*、`limit=100`、`offset=0`、`category`、`status`、`query` | 已安装应用 |
| `miui-db-inventory` | `task_id`*、`kind=kv`、`limit`、`offset`、`reveal_sensitive=0`、`query` | 备份数据库清单（`reveal_sensitive=1` 才显示敏感值） |
| `miui-qqnt-overview` | `task_id`* | QQNT 概览 |
| `miui-qqnt-artifacts` | `task_id`*、分页/过滤参数同上 | QQNT 制品 |
| `miui-qqnt-records` | `task_id`*、分页/过滤参数同上 | QQNT 聊天记录 |
| `miui-wechat-overview` | `task_id`* | 微信概览 |
| `miui-wechat-artifacts` | `task_id`*、`kind` 等 | 微信制品 |
| `miui-wechat-records` | `task_id`*、分页/过滤参数同上 | 微信聊天记录 |

### 2.7 内存取证（MemoryForensicsRoutes）

数据来自 `--memory-analyze` 产生的 `<镜像名>_memory.db`（Volatility3），只读打开；无 `_memory.db` 时返回 `404 {"error":"memory db not found"}`。所有端点需 `task_id`。

| 路径（前缀 `/api/forensics/memory/`） | 额外参数 | 说明 |
|----------|----------|------|
| `summary` | - | 各表行数概览 |
| `processes` | `search`（进程名过滤，参数化绑定） | `linux.pslist`，最多 1000 行，按 pid 排序 |
| `network` | - | `linux.sockstat` 网络连接 |
| `bash-history` | `keyword`（命令过滤） | `linux.bash` |
| `boot-info` | - | `linux.boottime` 键值对 |

### 2.8 系统事件（SystemEventRoutes）

- `GET /api/forensics/system/events`：`task_id`*、`start_time`、`end_time`、`limit=1000`、`offset=0`。
- `GET /api/forensics/system/summary`：`task_id`*。

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

### 2.10 场景查询（SceneQueryRoutes）

| 方法 | 路径 | 关键参数 | 用途 |
|------|------|----------|------|
| GET | `/api/tasks/<task_id>/scene-stats` | 路径参数 task_id | 按场景分组的文件/制品统计（`scene_stats[].scene_type/total_files/relevant_files/total_size/llm_analyzed_files`、`artifact_stats[]`） |
| GET | `/api/tasks/<task_id>/scene-artifacts` | `scene_type`*（白名单 `android/windows/linux`）、`limit=100`、`offset=0` | 场景制品分页列表（含关联源文件与 LLM 字段） |

### 2.11 导出（ExportRoutes）

| 方法 | 路径 | 关键参数 | 用途 |
|------|------|----------|------|
| GET | `/api/forensics/export/toon` | `task_id`*、`fields`（列选择）、`filter` | TOON 文本格式导出 |
| GET | `/api/forensics/export/events/json` | `task_id`*、`query` | 事件 JSON 导出 |
| GET | `/api/forensics/export/events/csv` | `task_id`*、`query` | 事件 CSV 导出 |
| GET | `/api/forensics/export/events/visualization` | `task_id`* | 可视化用事件导出 |

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

---

## 4. 全文搜索 API

> 源码：`SearchRoutes.cpp`（索引路径受 `FTS_ALLOWED_ROOT` 环境变量约束，默认限 PathManager 数据目录内，防任意文件读取）

### GET /api/search/fulltext

查询参数：`q`（**必填**）、`index`（索引路径）、`limit=50`、`offset=0`。返回匹配文档列表与分页信息。

### POST /api/search/index

请求体 `{source_path, index_path, recursive=true}`——`source_path` 与 `index_path` **均必填**，缺失返回 `400`。

```bash
curl -X POST http://localhost:8080/api/search/index \
  -H "Content-Type: application/json" \
  -d '{"source_path": "/data/extracted", "index_path": "/data/idx"}'
```

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

---

## 6. 系统与文档 API

> 由 `SystemRoutes` 聚合：SystemHealthRoutes + SystemInfoRoutes + SystemDocsRoutes。

### 健康检查

| 方法 | 路径 | 响应要点 |
|------|------|----------|
| GET | `/api/system/health` | `{status:"healthy", timestamp(ms), version, task_management{total_tasks,running_tasks,failed_tasks,system_load}, services{...}}` |
| GET | `/api/health` | 同上的别名 |
| GET | `/api/health/live` | `{status:"alive", timestamp(ms)}` |
| GET | `/api/health/ready` | `{ready: bool, checks{task_manager, database}, timestamp}`；未就绪时 `503` |
| GET | `/api/health/dependencies` | 依赖服务状态明细 |

### 系统信息

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/system/info` | 服务/构建信息 |
| GET | `/api/system/databases?task_id=...` | 任务数据库文件 |
| GET | `/api/system/database-schema/<db_type>` | 指定类型数据库的表结构 |
| GET | `/api/system/logs?lines=...` | 系统日志（`lines` 可选） |
| POST | `/api/export/<task_id>` | 导出任务数据；请求体 `{format: ...}` 可选 |

### 文档

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/docs` | Swagger UI 页面 |
| GET | `/api/docs/endpoints` | 全部端点清单（JSON） |
| GET | `/api/docs/database-schema` | 全部数据库模式文档 |
| GET | `/api/docs/openapi.json` | OpenAPI 规范 |

---

## 7. 已知未注册路由

以下 OSS 路由文件存在于源码树并参与编译，但**从未被任何聚合器注册**（`ForensicsRoutes.h` 不含 OSSRoutes*，运行时访问将 404）：

- `OSSRoutes.cpp` / `OSSRoutes_new.cpp`
- `OSSAnalysisRoutes.cpp`（`/api/forensics/oss/analyze` 等）
- `OSSQueryRoutes.cpp`（`/api/forensics/oss/objects`、`/logs` 等）
- `OSSStatsRoutes.cpp`（`/api/forensics/oss/stats/*` 等）

旧文档中的整个"OSS 对象存储分析 API"章节在 C++ 服务上**不可用**，请勿调用。Python 侧 OSS AI 能力见 `/api/forensics/oss/ai/*`（Python_REST_API.md）。

---

## 相关文档

- [Python REST API 参考](./Python_REST_API.md)
- [快速入门指南](../getting-started/QuickStart.md)

---

**最后更新**: 2026-08-23（以代码为准重写）
