# Python REST API 参考文档

> 本文档基于 `python_service/httpserver/main.py::_register_routes` 及 `python_service/httpserver/routes/`、`python_service/server/` 源码重写，所有路径与字段均以代码为准。

## 概述

Python 服务分两部分：

| 服务 | 端口 | 框架 | 认证 |
|------|------|------|------|
| **httpserver**（本地分析服务） | **8090**（`PYTHON_HTTP_PORT`，`httpserver/config.py:133`） | FastAPI | 无（本地服务） |
| **分布式 C/S server** | **8091**（`PORT`，`server/config.py:39`；注释明确 8091 与 8090 区分） | FastAPI | **JWT Bearer**（客户端走 client credential） |

- httpserver 交互式文档：`http://localhost:8090/docs`（Swagger）、`/redoc`、`/openapi.json`。
- httpserver 的就绪检查中 **C++ 后端为硬依赖**；Neo4j / LLM / Redis 为可选依赖（不可用不阻塞 ready）。
- 未捕获异常统一返回 `500 {success: false, message: "Internal server error", error: "...", timestamp}`；校验失败返回 `422 {success, message, errors, timestamp}`（main.py 全局 handler）。

---

## 目录

1. [健康检查 API](#1-健康检查-api)
2. [Graphiti 知识图谱 API](#2-graphiti-知识图谱-api)
3. [LLM 分析 API](#3-llm-分析-api)
4. [案件分析 API](#4-案件分析-api)
5. [多镜像/案件聚合 API](#5-多镜像案件聚合-api)
6. [报告 API](#6-报告-api)
7. [调查 API（/api/investigation）](#7-调查-apiapiinvestigation)
8. [调查工作台 API（/api/investigation/workbench）](#8-调查工作台-apiapiinvestigationworkbench)
9. [数据库访问 API](#9-数据库访问-api)
10. [Office 文档 API](#10-office-文档-api)
11. [Markitdown 转换 API](#11-markitdown-转换-api)
12. [微信关系图谱 API](#12-微信关系图谱-api)
13. [事件关联 API](#13-事件关联-api)
14. [OSS AI 分析 API](#14-oss-ai-分析-api)
15. [系统 API](#15-系统-api)
16. [分布式 C/S 服务（8091，JWT）](#16-分布式-cs-服务8091jwt)

---

## 1. 健康检查 API

> 源码：`routes/health.py`（无前缀）

| 方法 | 路径 | 用途 | 响应要点 |
|------|------|------|----------|
| GET | `/health` | 基础健康 | `{status:"healthy", timestamp, version:"1.0.0", uptime_seconds}` |
| GET | `/health/live` | 存活探针 | `{status:"alive", ...}` |
| GET | `/health/ready` | 就绪探针 | `{ready: bool, checks{cpp_backend, neo4j, llm, redis}, timestamp}`；仅 `cpp_backend` 不可用会置 `ready=false`，其余为可选项 |
| GET | `/api/system/redis/status` | Redis 状态 | `{connected, in_use, status, url(已脱敏), timestamp}`；Redis 不可用时任务管理器回退内存实现 |
| GET | `/api/system/info` | 系统信息 | `{service, version, python_version, config{http_port, cpp_backend_url, neo4j_uri, llm_text_model, ...}, timestamp}` |

```bash
curl http://localhost:8090/health/ready
```

---

## 2. Graphiti 知识图谱 API

> 源码：`routes/graphiti.py` 挂载 `routes/graphiti_endpoints/`（前缀 `/api/graphiti`）

### 2.1 摄取

**POST /api/graphiti/ingest** —— 启动图谱摄取（后台任务）。请求体（`IngestRequest`，已验证）：

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `task_id` | string | **必填** | 任务 ID（同时作为图命名空间）；任务不存在返回 404 |
| `mode` | string | `full` | `full / files_only / events_only / analyzed_only` |
| `include_llm_descriptions` | bool | true | 含 LLM 描述 |
| `batch_size` | int | 50 | 1–500 |
| `max_episodes` | int | 100 | 0–10000，0 = 不限 |

mode 语义：`full` 全量；`files_only` 仅文件实体；`events_only` 事件挂到既有文件；`analyzed_only` 仅重摄取 `llm_analyzed_at IS NOT NULL` 的文件与事件簇（不重跑 LLM）。

响应（`IngestionResponse`）：`{job_id, status: "PENDING", message}`

```bash
curl -X POST http://localhost:8090/api/graphiti/ingest \
  -H "Content-Type: application/json" \
  -d '{"task_id": "task_xxx", "mode": "analyzed_only"}'
```

- **POST /api/graphiti/ingest/file**：单文件摄取 `{file_id(int, 必填), task_id(必填), update_analysis=false}`。
- **POST /api/graphiti/ingest/events**：事件同步 `{task_id, events: [<事件字典>]}`。

### 2.2 任务（Job）

- `GET /api/graphiti/jobs/{job_id}`：任务状态 `{job_id, status, progress, current_phase, created_at, started_at?, completed_at?, error?, result?}`。
- `DELETE /api/graphiti/jobs/{job_id}`：取消任务。
- `GET /api/graphiti/jobs`：任务列表。

### 2.3 迁移

- `POST /api/graphiti/migrate/task/{task_id}`：把任务数据迁移到 Graphiti 结构。
- `POST /api/graphiti/migrate/deduplicate`：去重。
- `GET /api/graphiti/migrate/status/{task_id}`：迁移状态。
- `POST /api/graphiti/migrate/cleanup/{task_id}`：清理迁移产物。

### 2.4 查询

- `POST /api/graphiti/search`：图搜索（自然语言查询）。
- `GET /api/graphiti/entities`：实体列表。
- `GET /api/graphiti/relationships`：关系列表。

### 2.5 管理

- `GET /api/graphiti/status`：服务状态。
- `GET /api/graphiti/tasks`：已建图任务列表。
- `DELETE /api/graphiti/tasks/{task_id}`：删除任务的图谱数据。
- `GET /api/graphiti/graph`：可视化图数据。

---

## 3. LLM 分析 API

> 源码：`routes/llm.py` 挂载 `routes/llm_endpoints/`（前缀 `/api/llm`），另挂 `routes/dll.py`

### POST /api/llm/analyze

分析文本或文件。请求体（`AnalyzeRequest`，已验证）：`task_id?`（持久化目标任务）、`file_path?` / `db_file_path?`（文件路径，二选一时与 content 互补）、`content?`（直接分析文本）、`model_type`（默认 `text`，可选 `vision`）、`prompt?`、`max_tokens?`（1–8192）、`temperature?`（0–2）、`files_db_path?`（结果持久化的 `_files.db` 路径）。

其余端点：

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | `/api/llm/analyze-event-cluster` | LLM 分析事件簇 |
| POST | `/api/llm/analyze/file` | 上传文件分析（multipart） |
| POST | `/api/llm/batch` | 批量分析（后台 job） |
| GET | `/api/llm/batch/{job_id}` | 批量分析进度 |
| GET | `/api/llm/models` | 可用模型列表（text/vision） |
| POST | `/api/llm/toggle-relevance` | 切换文件相关性标记 |
| POST | `/api/llm/toggle-cluster-relevance` | 切换事件簇相关性标记 |
| GET | `/api/llm/status` | LLM 服务状态 |
| POST | `/api/llm/analyze/dll` | LLM 分析 DLL/共享库安全性（`routes/dll.py`） |

---

## 4. 案件分析 API

> 源码：`routes/case_analysis.py` 挂载 `case_analysis_endpoints/_case.py`、`_windows.py` 与 `routes/intelligence_report.py`（前缀 `/api/llm`）

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | `/api/llm/case-description` | 保存案情描述（转发持久化到 C++ 任务系统 tasks.json） |
| POST | `/api/llm/case-analysis` | **已退役**：固定返回 `410`，detail 为 "legacy case analysis generation has been retired; use report generation" |
| POST | `/api/llm/reanalyze-files` | 重跑文件分析 |
| GET | `/api/llm/case-analysis/{job_id}` | 分析 job 状态 |
| GET | `/api/llm/case-report/{task_id}` | 任务级案件报告 |
| GET | `/api/llm/case-report-by-case/{case_id}` | 案件级报告 |
| GET | `/api/llm/filtered-files/{task_id}` | AI 过滤后的文件列表 |
| POST | `/api/llm/windows-analysis` | Windows 场景分析 |
| GET | `/api/llm/windows-report/{task_id}` | Windows 报告 |
| GET | `/api/llm/windows-export/{task_id}/toon` | Windows 报告 TOON 导出 |

情报报告（`intelligence_report.py`）：

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/api/llm/intelligence-report/{task_id}` | 情报报告正文（分章节） |
| GET | `/api/llm/intelligence-report/{task_id}/records` | 报告记录 |
| GET | `/api/llm/intelligence-report/{task_id}/search` | 报告内检索 |
| GET / PUT | `/api/llm/intelligence-report/{task_id}/metadata` | 读取/更新报告元数据 |

---

## 5. 多镜像/案件聚合 API

> 源码：`routes/multi_analysis.py`（绝对路径，代理/编排 C++ 案件后端）

| 方法 | 路径 | 请求体要点 | 用途 |
|------|------|------------|------|
| POST | `/api/llm/cases`（201） | `{name, description="", task_ids?[]}` | 创建案件（`CreateCaseRequest`，已验证） |
| GET | `/api/llm/cases` | - | 案件列表 |
| GET / DELETE | `/api/llm/cases/{case_id}` | - | 案件详情 / 删除 |
| POST | `/api/llm/cases/{case_id}/tasks` | `{task_ids: [...]}` | 添加任务 |
| POST | `/api/llm/cases/{case_id}/associate-tasks` | `{task_ids: [...]}`（空数组 400） | 关联已完成分析的任务 |
| POST | `/api/llm/multi-image-analysis` | `{case_id, task_ids, files_db_paths, case_description, max_filter_files=400}`（均已验证，前三项必填） | 多镜像关联分析 job |
| GET | `/api/llm/multi-image-analysis/{job_id}` | - | 分析 job 状态 |
| POST | `/api/llm/cases/smart-create`（201） | `{name, description}` | 智能建案 |
| POST | `/api/llm/cases/{case_id}/tasks/incremental` | `{task_ids}` | 增量加任务 |
| GET | `/api/llm/cases/{case_id}/analysis-status` | - | 聚合分析状态 |
| POST | `/api/llm/cases/{case_id}/incremental-analysis` | - | 触发增量分析 |

---

## 6. 报告 API

> 源码：`forensic_reports.py`、`report_evidence.py`、`report_generation.py`、`report_narrative.py`（前缀 `/api/reports`）

### 6.1 报告版本（forensic_reports.py）

- `POST /api/reports`（**202**）：创建报告版本。请求体 `{scope_type, scope_id}`（`CreateReportRequest`，已验证；scope_type 不支持时 501，scope 不存在 404）。
- `GET /api/reports?scope_type=&scope_id=`：按范围列报告版本。
- `GET /api/reports/{report_id}/status`：报告状态。
- `GET /api/reports/{report_id}/manifest`：报告清单。
- `GET /api/reports/{report_id}/categories/{category_id}/pages/{page}`：分页读取章节内容。
- `GET /api/reports/{report_id}/search`：报告内检索（`{total, offset, limit, ...}`）。

### 6.2 报告证据（report_evidence.py）

- `GET /api/reports/evidence`：证据列表。
- `POST /api/reports/evidence`（200）：登记证据（重复 409，绑定冲突 409）。
- `PUT /api/reports/evidence`（200）：更新证据（校验失败 422）。

### 6.3 报告生成（report_generation.py）

- `POST /api/reports/generate`（**202**）：请求体 `{task_id, requested_by}`（`GenerateReportRequest`，`extra="forbid"`，已验证）；无报告证据 409。
- `GET /api/reports/generations/{generation_id}`：生成状态。

### 6.4 报告叙事（report_narrative.py）

- `GET /api/reports/narrative/versions/{report_id}`：叙事版本记录。

---

## 7. 调查 API（/api/investigation）

> 源码：`routes/investigation.py`。证据以不可变快照 + 二级分析 + 调查事件为核心。

| 方法 | 路径 | 状态码 | 用途 |
|------|------|--------|------|
| POST | `/snapshots` | 200 | 捕获证据快照；请求体严格限定 `{task_id, evidence_key}`（`extra="forbid"`，已验证） |
| POST | `/analyses` | **202** | 对证据启动二级分析 |
| POST | `/analyses/{analysis_id}/review` | 200 | 审阅分析结果（冲突 409） |
| GET | `/analyses/{analysis_id}` | 200 | 分析详情 |
| GET | `/analyses` | 200 | 分析列表（可按 evidence_key / status 过滤） |
| GET | `/analyses/{analysis_id}/claims` | 200 | 分析声明（claims） |
| POST | `/events` | **201** | 创建调查事件 |
| GET | `/events` | 200 | 事件列表 |
| GET | `/events/{event_id}` | 200 | 事件详情 |
| GET | `/events/{event_id}/versions` | 200 | 事件版本历史 |
| POST / GET | `/events/{event_id}/evidence` | 200 | 挂接/查询事件证据（重复挂接 409） |
| POST | `/events/{event_id}/refresh` | **201** | 触发事件刷新 |
| GET | `/events/{event_id}/refreshes` | 200 | 刷新历史 |
| GET | `/evidence` | 200 | 证据列表 |
| GET | `/evidence/snapshot` | 200 | 证据快照 |
| GET | `/graph` | 200 | 调查图数据 |

---

## 8. 调查工作台 API（/api/investigation/workbench）

> 源码：`routes/investigation_workbench.py`。按任务聚合的本地调查工作台。

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/{task_id}` | 工作台总览 |
| POST | `/{task_id}/bootstrap` | 引导初始化（生成事件/证据） |
| GET | `/{task_id}/events` | 事件列表 |
| GET | `/{task_id}/events/{event_id}` | 事件详情 |
| POST | `/{task_id}/events/{event_id}/review` | **固定 409**：源码注明 review 不属于本地规范契约 |
| GET | `/{task_id}/events/{event_id}/evidence` | 事件证据 |
| POST | `/{task_id}/events/{event_id}/evidence/link` | 挂接证据 |
| GET | `/{task_id}/evidence/detail` | 证据详情 |
| POST | `/{task_id}/evidence/analyze` | 触发证据分析 job |
| GET | `/{task_id}/analysis-jobs/{job_id}` | 分析 job 状态 |
| GET | `/{task_id}/evidence/analysis` | 证据分析结果 |
| POST | `/{task_id}/analysis/{analysis_id}/accept` / `reject` | 采纳/驳回分析 |
| POST | `/{task_id}/events/{event_id}/refresh` | 刷新事件 |
| GET | `/{task_id}/events/{event_id}/versions` | 版本历史 |
| POST | `/{task_id}/events/{event_id}/versions/{version_id}/accept` | 采纳版本 |
| POST | `/{task_id}/events/{event_id}/versions/{version_id}/reject` | **固定 409**：语义版本驳回不在本地契约内 |
| GET | `/{task_id}/events/{event_id}/versions/{version_id}/claims` | 版本声明 |
| GET | `/{task_id}/events/{event_id}/claims/effective` | 生效声明 |
| POST | `/{task_id}/events/{event_id}/versions/{version_id}/claims/{claim_id}/accept` | 采纳声明 |
| POST | `.../claims/{claim_id}/reject` | **固定 409**：声明驳回不在本地契约内 |
| GET | `/{task_id}/claims/{claim_id}` | 声明溯源 |
| POST / GET | `/{task_id}/notes` | POST **固定 409**（等待规范 schema 决策）；GET 可读 |
| PUT / GET / POST | `/{task_id}/report-evidence`（+/remove） | 管理报告证据集 |
| GET | `/{task_id}/graph/local` | 本地调查图 |
| GET | `/{task_id}/final-reports` | 终版报告列表 |
| GET | `/{task_id}/final-reports/{report_id}`（+/markdown、/html、/print、/publication） | 终版报告及各渲染形式 |
| POST | `/{task_id}/final-reports/{report_id}/publish` | 发布终版报告 |

> 上述标注"固定 409"的端点已注册但按设计拒绝执行，属于显式的契约边界，不是故障。

---

## 9. 数据库访问 API

> 源码：`routes/database.py`（前缀 `/api/db`）——只读查询，无自定义 SQL 端点（旧文档的 `POST /api/db/query` 不存在）。

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/api/db/tasks` | 任务列表（含数据库位置） |
| GET | `/api/db/tasks/{task_id}` | 任务详情 |
| GET | `/api/db/tasks/{task_id}/databases` | 任务数据库清单（`TaskDatabasesResponse`） |
| GET | `/api/db/tasks/{task_id}/files` | 文件记录（分页） |
| GET | `/api/db/tasks/{task_id}/events` | 事件记录（分页） |
| GET | `/api/db/tasks/{task_id}/export/toon` | TOON 文本导出 |
| GET | `/api/db/tasks/{task_id}/export/json` | JSON 导出 |

---

## 10. Office 文档 API

> 源码：`routes/office.py`（前缀 `/api/office`）

- `POST /api/office/parse`：解析 Office 文档（docx/xlsx/pptx）为 Markdown；需 `task_id` 或 `workspace_root` 锚定工作区，文件必须在任务工作区内。
- `GET /api/office/supported-types`：支持的文件类型列表。

---

## 11. Markitdown 转换 API

> 源码：`routes/markitdown.py`（前缀 `/api/markitdown`）；读取受任务工作区/提取根/任务 files.db 三重边界约束（越界 400）

### POST /api/markitdown/convert

单文件转 Markdown。请求体（`ConvertRequest`，已验证）：`{task_id? | workspace_root?(deprecated), file_path(必填)}`。响应（`ConvertResponse`）：`{success, content(Markdown 文本), title, processing_time_ms}`。

```bash
curl -X POST http://localhost:8090/api/markitdown/convert \
  -H "Content-Type: application/json" \
  -d '{"task_id": "task_xxx", "file_path": "/ws/extract/report.docx"}'
```

- `GET /api/markitdown/status`：服务状态。
- `POST /api/markitdown/convert-one`：`{task_id?|workspace_root?, input_root, input_file, output_root}`——在 input root 下转换单个文件。
- `POST /api/markitdown/batch-convert`：`{task_id?|workspace_root?, input_dir(必填), output_dir(必填)}`——目录批量转换，响应 `{success, total_files, converted, ...}`。

---

## 12. 微信关系图谱 API

> 源码：`routes/wechat_graph.py` 挂载 `wechat_graph_endpoints/`（前缀 `/api/wechat`）；所有 GET 均需 `task_id` 查询参数（必填）

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/api/wechat/chat` | 聊天记录（可按 talker 过滤、limit） |
| GET | `/api/wechat/chat/group` | 群聊记录（`chatroom_name`） |
| GET | `/api/wechat/owner` | 账号所有者信息 |
| GET | `/api/wechat/contacts` | 联系人列表 |
| GET | `/api/wechat/graph` | 关系图谱数据 |
| GET | `/api/wechat/graph/timeline` | 通信时间线（start_time/end_time） |
| GET | `/api/wechat/graph/community` | 社区发现（Louvain） |
| GET | `/api/wechat/graph/person/{username}` | 个人 ego 网络 |
| POST | `/api/wechat/graph/invalidate` | 清除图谱缓存 |

---

## 13. 事件关联 API

> 源码：`routes/associations.py`（前缀 `/api/associations`）

- `POST /api/associations/cluster-files`：事件簇 → 关联文件（`{task_id, ...}`；无 files 数据库 400）。
- `POST /api/associations/file-clusters`：文件 → 关联事件簇（无 events 数据库 400）。

---

## 14. OSS AI 分析 API

> 源码：`routes/oss_analysis.py`（router 自带前缀 `/api/forensics/oss/ai`）——这是 Python 服务中唯一存在的 OSS 能力（C++ 侧 OSS 路由未注册，见 CPP_REST_API.md）

### POST /api/forensics/oss/ai/filter

LLM 过滤 OSS 对象。请求体（`OSSFilterRequest`，已验证）：`{task_id, oss_db_path, case_description, bucket?, max_objects}`（`max_objects` 默认 200，范围 1–2000）。

### POST /api/forensics/oss/ai/analyze

LLM 分析已过滤对象。请求体（`OSSAnalyzeRequest`，已验证）：`{task_id, object_ids: [int], oss_db_path, download_dir, model_type="text"（仅 text|vision）}`。

---

## 15. 系统 API

> 源码：`routes/system.py`（前缀 `/api/system`）

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/api/system/logs` | 读取服务日志 |
| GET | `/api/system/logs/{service}` | 指定服务日志（找不到 404） |
| GET | `/api/system/logs-stream/{service}` | **SSE** 日志流（StreamingResponse） |

> `routes/system_logs.py` 中定义的 `/api/system/logs/stream` router **未在 main.py 注册**（死代码），运行时不存在。
> Redis 状态与系统信息在 `health.py` 中注册：`/api/system/redis/status`、`/api/system/info`（见第 1 节）。

---

## 16. 分布式 C/S 服务（8091，JWT）

> 源码：`python_service/server/`（`main.py` 挂载 api/ 下各 router）。**唯一带认证的服务**：用户走 JWT Bearer，客户端（agent）走 client credential。
> 设计要点：磁盘镜像字节永不离开客户端，服务端只存产物引用（`file_path` + `storage_location` + `result_metadata.base_name`），详见仓库内产物上传契约文档。

### 16.1 基础

- `GET /health`：存活。
- `GET /health/ready`：就绪（数据库等依赖）。
- `GET /`：服务发现信息。

### 16.2 认证（/api/auth）

**POST /api/auth/login** —— OAuth2 密码流（`application/x-www-form-urlencoded`）：

```bash
curl -X POST http://localhost:8091/api/auth/login \
  -d "username=admin&password=secret"
```

响应（`TokenResponse`，已验证）：`{access_token: "<JWT>", token_type: "bearer", expires_in: 3600}`。凭据错误返回 `401`（带 `WWW-Authenticate: Bearer`）。用户名可用 username 或 email。

- `POST /api/auth/refresh`：刷新 token（需当前 token）。
- `GET /api/auth/me`：当前用户信息 `{id, org_id, username, email, role, created_at, last_login}`。

角色权限矩阵（`auth.py`）：`super_admin`（全量）、`org_admin`、`analyst`（create_tasks/view_results）、`auditor`（view_results）。

### 16.3 组织（/api/organizations）

- `POST /api/organizations`：创建组织。
- `GET /api/organizations`：组织列表。
- `GET /api/organizations/{org_id}`：组织详情。
- `POST /api/organizations/{org_id}/registration-tokens`：签发客户端注册令牌。
- `GET /api/organizations/{org_id}/registration-tokens`：令牌列表。
- `DELETE /api/organizations/registration-tokens/{token_id}`：吊销令牌。

### 16.4 客户端（/api/clients）

- `POST /api/clients/register`：客户端凭注册令牌注册（返回 client credential）。
- `GET /api/clients`：客户端列表。
- `GET /api/clients/{client_id}`：客户端详情。
- `DELETE /api/clients/{client_id}`：删除客户端。
- `POST /api/clients/{client_id}/index-images`：登记客户端可见的磁盘镜像索引。
- `GET /api/clients/{client_id}/images`：镜像列表（`DiskImageResponse[]`）。

### 16.5 命令队列（/api/commands）

| 方法 | 路径 | 认证方 | 用途 |
|------|------|--------|------|
| POST | `/api/commands` | 用户 | 下发命令 `{client_id, ...}`；跨组织 403，客户端不存在 404 |
| GET | `/api/commands/poll` | **客户端** | 拉取待执行命令（同时刷新 `last_poll` 在线心跳） |
| POST | `/api/commands/{command_id}/status` | **客户端** | 上报命令状态（仅能上报自己的命令；状态会传播到关联分析任务） |
| GET | `/api/commands/{command_id}` | 用户 | 命令详情 |
| GET | `/api/commands/client/{client_id}` | 用户 | 按客户端查命令历史 |
| POST | `/api/commands/expire` | 用户 | 过期滞留命令 |

**客户端轮询示例**：

```bash
curl http://localhost:8091/api/commands/poll \
  -H "Authorization: Bearer <client-token>"
```

### 16.6 分析任务（/api/tasks）

- `POST /api/tasks`：创建分析任务（`AnalysisTaskResponse`）。
- `GET /api/tasks`：任务列表。
- `GET /api/tasks/{task_id}`：任务详情。
- `POST /api/tasks/{task_id}/cancel`：取消任务。

### 16.7 结果上报（/api/tasks，results.py）

- `POST /api/tasks/{task_id}/results`（**客户端**）：批量上传产物引用，请求体 `{artifacts: [ResultArtifact...]}`（`ResultUploadRequest`，已验证；artifact 含 `result_type / file_path / file_size / storage_location / result_metadata` 等，`result_metadata` 原样入库以保留 `base_name`）。
- `GET /api/tasks/{task_id}/results`（用户）：任务结果列表。
- `GET /api/tasks/{task_id}/llm-analyses`（用户）：任务 LLM 分析结果。

---

## 错误响应

httpserver 未捕获异常：`500 {success: false, message: "Internal server error", error, timestamp}`；参数校验失败：`422 {success: false, message: "Validation error", errors, timestamp}`。各路由业务错误为 FastAPI 标准 `{"detail": "..."}` + 4xx。C/S 服务未授权返回 `401`（Bearer）。

---

## 相关文档

- [C++ REST API 参考](./CPP_REST_API.md)
- FastAPI 交互文档：`http://localhost:8090/docs`

---

**最后更新**: 2026-08-23（以代码为准重写）
