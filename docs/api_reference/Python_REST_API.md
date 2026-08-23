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

**Redis 状态与系统信息**：

```bash
curl http://localhost:8090/api/system/redis/status
curl http://localhost:8090/api/system/info
```

响应要点：redis 为 `{connected, in_use, status, url(已脱敏), timestamp}`；info 的 `config` 含 `http_port / cpp_backend_url / neo4j_uri / llm_text_model` 等（Dashboard 页经 systemService 消费）。

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

```bash
curl -X POST http://localhost:8090/api/graphiti/ingest/file \
  -H "Content-Type: application/json" \
  -d '{"task_id": "task_xxx", "file_id": 4096, "update_analysis": false}'
```

- **POST /api/graphiti/ingest/events**：事件同步 `{task_id, events: [<事件字典>]}`。

```bash
curl -X POST http://localhost:8090/api/graphiti/ingest/events \
  -H "Content-Type: application/json" \
  -d '{"task_id": "task_xxx", "events": [{"timestamp": 1770000000, "event_type": "CREATED", "file_path": "/etc/ssh/sshd_config"}]}'
```

### 2.2 任务（Job）

- `GET /api/graphiti/jobs/{job_id}`：任务状态 `{job_id, status, progress, current_phase, created_at, started_at?, completed_at?, error?, result?}`。
- `DELETE /api/graphiti/jobs/{job_id}`：取消任务。
- `GET /api/graphiti/jobs`：任务列表。

```bash
curl http://localhost:8090/api/graphiti/jobs/job_aaa
curl -X DELETE http://localhost:8090/api/graphiti/jobs/job_aaa
```

响应要点：`status` 在 `PENDING / RUNNING / COMPLETED / FAILED / CANCELLED` 间迁移，`progress` 为整数百分比；graphitiService 的 `pollGraphitiJob` 即轮询 `GET /jobs/{job_id}`。

### 2.3 迁移

- `POST /api/graphiti/migrate/task/{task_id}`：把任务数据迁移到 Graphiti 结构。
- `POST /api/graphiti/migrate/deduplicate`：去重。
- `GET /api/graphiti/migrate/status/{task_id}`：迁移状态。
- `POST /api/graphiti/migrate/cleanup/{task_id}`：清理迁移产物。

```bash
curl -X POST http://localhost:8090/api/graphiti/migrate/task/task_xxx
curl "http://localhost:8090/api/graphiti/migrate/status/task_xxx"
```

### 2.4 查询

- `POST /api/graphiti/search`：图搜索（自然语言查询）。
- `GET /api/graphiti/entities`：实体列表。
- `GET /api/graphiti/relationships`：关系列表。

**图搜索**（`SearchRequest`：`query` 必填 min_length=1、`task_id` 必填、`entity_types?`、`limit=100`(1–1000)、`include_relationships=true`）：

```bash
curl -X POST http://localhost:8090/api/graphiti/search \
  -H "Content-Type: application/json" \
  -d '{"task_id": "task_xxx", "query": "谁在案发时间段删除了日志", "limit": 20}'
```

响应要点（`SearchResponse`）：`{success, query, task_id, results: [{entity_id, entity_type, name, properties, score, relationships?}], total_count, timestamp}`。

**实体 / 关系分页列表**：

```bash
curl "http://localhost:8090/api/graphiti/entities?task_id=task_xxx&entity_type=&page=1&page_size=50"
curl "http://localhost:8090/api/graphiti/relationships?task_id=task_xxx&relationship_type=&page=1&page_size=50"
```

响应要点：`EntityListResponse` 为 `{success, task_id, entities[], total_count, page, page_size, timestamp}`；`RelationshipListResponse` 同构（`relationships[]`，另支持 `source_id / target_id` 过滤，page_size 上限 500）。

### 2.5 管理

- `GET /api/graphiti/status`：服务状态。
- `GET /api/graphiti/tasks`：已建图任务列表。
- `DELETE /api/graphiti/tasks/{task_id}`：删除任务的图谱数据。
- `GET /api/graphiti/graph`：可视化图数据。

```bash
curl http://localhost:8090/api/graphiti/status
curl http://localhost:8090/api/graphiti/tasks
curl "http://localhost:8090/api/graphiti/graph?task_id=task_xxx"
curl -X DELETE http://localhost:8090/api/graphiti/tasks/task_xxx
```

响应要点：`status` 为 `{status, neo4j_connected, total_entities, total_relationships, task_id?, timestamp}`；`tasks` 为 `{success, task_ids[], count, timestamp}`；`graph` 为可视化用的节点/边数据（KnowledgeGraph 页消费）。

---

## 3. LLM 分析 API

> 源码：`routes/llm.py` 挂载 `routes/llm_endpoints/`（前缀 `/api/llm`），另挂 `routes/dll.py`

### POST /api/llm/analyze

分析文本或文件。请求体（`AnalyzeRequest`，已验证）：`task_id?`（持久化目标任务）、`file_path?` / `db_file_path?`（文件路径，二选一时与 content 互补）、`content?`（直接分析文本）、`model_type`（默认 `text`，可选 `vision`）、`prompt?`、`max_tokens?`（1–8192）、`temperature?`（0–2）、`files_db_path?`（结果持久化的 `_files.db` 路径）。

**直接分析文本**：

```bash
curl -X POST http://localhost:8090/api/llm/analyze \
  -H "Content-Type: application/json" \
  -d '{"content": "分析这份聊天摘要中的可疑行为…", "model_type": "text", "max_tokens": 2048}'
```

**分析任务内文件并持久化**：

```bash
curl -X POST http://localhost:8090/api/llm/analyze \
  -H "Content-Type: application/json" \
  -d '{"task_id": "task_xxx", "file_path": "/ws/extract/report.docx", "model_type": "text"}'
```

响应要点（`AnalyzeResponse`）：`{success, analysis{...LLM 结构化输出}, model_used, tokens_used, processing_time_ms}`。

**事件簇分析**（`EventClusterAnalyzeRequest`：`task_id` 必填；`group_descriptor{bucket_index, bucket_seconds, event_type}` 为后端 Timeline Group 描述符；兼容旧式 `time_window / event_type / parent_directory / bucket_seconds=60`；`prompt?`）：

```bash
curl -X POST http://localhost:8090/api/llm/analyze-event-cluster \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "task_xxx",
    "group_descriptor": {
      "bucket_index": 4938271,
      "bucket_seconds": 60,
      "event_type": "CREATED",
      "parent_directory": "/etc/ssh/"
    }
  }'
```

> 前端 `forensicsService.analyzeEventCluster` 用的正是 `group_descriptor` 形态（发送前校验三个整型/字符串字段）。

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

**上传文件分析**（multipart，查询参数 `model_type=text`、`prompt?`）：

```bash
curl -X POST "http://localhost:8090/api/llm/analyze/file?model_type=vision&prompt=%E8%AF%86%E5%88%AB%E5%9B%BE%E7%89%87%E4%B8%AD%E7%9A%84%E5%B1%8F%E5%B9%95%E5%86%85%E5%AE%B9" \
  -F "file=@/tmp/screenshot.png"
```

**批量分析**（`BatchAnalyzeRequest`：`task_id` 必填、`file_types?`、`file_paths?`、`limit=100`(1–1000)、`model_type="text"`）：

```bash
curl -X POST http://localhost:8090/api/llm/batch \
  -H "Content-Type: application/json" \
  -d '{"task_id": "task_xxx", "file_types": [".docx", ".pdf"], "limit": 200}'
```

响应要点（`BatchAnalyzeResponse`）：`{success, task_id, job_id, message, total_files}`；随后轮询 `GET /api/llm/batch/{job_id}` 得 `{success, job_id, status, progress, files_processed, files_total, errors[], results[]}`（llmService.pollBatchStatus 的数据源）。

**切换文件相关性**（`ToggleRelevanceRequest`：`task_id / file_path / is_relevant` 全必填）：

```bash
curl -X POST http://localhost:8090/api/llm/toggle-relevance \
  -H "Content-Type: application/json" \
  -d '{"task_id": "task_xxx", "file_path": "/ws/extract/report.docx", "is_relevant": true}'
```

**模型列表与状态**：

```bash
curl http://localhost:8090/api/llm/models
curl http://localhost:8090/api/llm/status
```

响应要点：models 为 `{success, models: [{name, type, base_url, max_tokens, temperature, status}]}`；status 为 `{status, text_model{}, vision_model{}}`。

**DLL 安全分析**（`DLLAnalysisRequest`：`task_id?`（持久化必带）、`file_path` 必填、`files_db_path?`（已弃用，传入必须与服务端解析一致）、`prompt?`）：

```bash
curl -X POST http://localhost:8090/api/llm/analyze/dll \
  -H "Content-Type: application/json" \
  -d '{"task_id": "task_xxx", "file_path": "/ws/extracted/usr/lib/suspicious.so"}'
```

响应要点（`DLLAnalysisResponse`）：`{success, analysis{}, model_used, tokens_used, processing_time_ms, timestamp}`——内部先调 C++ `/api/forensics/dlls/analyze` 解析 PE/ELF，再做 LLM 安全评估。

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

**保存案情描述**（`CaseDescriptionRequest`：`task_id` 必填、`case_description=""`，转发持久化到 C++ tasks.json）：

```bash
curl -X POST http://localhost:8090/api/llm/case-description \
  -H "Content-Type: application/json" \
  -d '{"task_id": "task_xxx", "case_description": "受害人手机被植入远控 APP，重点排查 1-3 月通信记录"}'
```

响应要点：`{success, task_id, message, timestamp}`。

**重跑文件分析**（`ReanalyzeRequest`：`task_id / file_paths(至少 1 项) / user_hint(非空)` 必填，`case_description?`、`files_db_path?`（弃用））：

```bash
curl -X POST http://localhost:8090/api/llm/reanalyze-files \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "task_xxx",
    "file_paths": ["/ws/extract/chat.db", "/ws/extract/notes.txt"],
    "user_hint": "重点关注转账话题和联系人张三",
    "case_description": "电信诈骗案"
  }'
```

响应要点：`{success, job_id, file_count, message, timestamp}`，随后用 `GET /api/llm/case-analysis/{job_id}` 轮询（`AnalysisStatusResponse`：`status / current_step / detail / result`）。

**读取任务级案件报告 / AI 过滤文件列表**：

```bash
curl http://localhost:8090/api/llm/case-report/task_xxx
curl http://localhost:8090/api/llm/filtered-files/task_xxx
```

响应要点：报告为 `{success, task_id, case_description, report(Markdown 文本), filtered_files[], files_analyzed, generated_at, timestamp}`；过滤列表为 `{success, filtered_files[], total_count, timestamp}`。

**Windows 场景分析**（复用 `CaseAnalysisRequest` 模型：`task_id` 必填、`case_description?`、`max_filter_files=200`、`run_filtering=false`、`report_only=false`、`files_db_path?`（弃用））：

```bash
curl -X POST http://localhost:8090/api/llm/windows-analysis \
  -H "Content-Type: application/json" \
  -d '{"task_id": "task_xxx", "case_description": "域控服务器被入侵", "max_filter_files": 300}'
```

**情报报告读取与检索**：

```bash
curl "http://localhost:8090/api/llm/intelligence-report/task_xxx"
curl "http://localhost:8090/api/llm/intelligence-report/task_xxx/records?page=1&page_size=50"
curl "http://localhost:8090/api/llm/intelligence-report/task_xxx/search?q=%E8%BD%AC%E8%B4%A6"
```

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

**示例——创建案件并添加任务**：

```bash
curl -X POST http://localhost:8090/api/llm/cases \
  -H "Content-Type: application/json" \
  -d '{"name": "多镜像并案", "description": "手机 + 服务器", "task_ids": []}'
```

响应 `201`：C++ `case_to_json` 的原样转发（`{id, name, description, task_ids, status, cross_analysis_job_id, created_at, updated_at}`）。

```bash
curl -X POST http://localhost:8090/api/llm/cases/case_zzz/associate-tasks \
  -H "Content-Type: application/json" \
  -d '{"task_ids": ["task_xxx", "task_yyy"]}'
```

> `associate-tasks` 只关联**已完成分析**的任务（已分析的复用结论不重跑）；空数组 400。

**多镜像关联分析 job**（`MultiImageAnalysisRequest`：`case_id / task_ids / files_db_paths / case_description` 四项必填，`task_ids` 与 `files_db_paths` 顺序一一对应；`max_filter_files=400`(1–2000)）：

```bash
curl -X POST http://localhost:8090/api/llm/multi-image-analysis \
  -H "Content-Type: application/json" \
  -d '{
    "case_id": "case_zzz",
    "task_ids": ["task_xxx", "task_yyy"],
    "files_db_paths": ["/data/tasks/task_xxx/files.db", "/data/tasks/task_yyy/files.db"],
    "case_description": "跨设备的诈骗团伙关联分析",
    "max_filter_files": 400
  }'
```

响应要点：`{success, job_id, message, ...}`（`CaseAnalysisResponse` 形态），随后轮询 `GET /api/llm/multi-image-analysis/{job_id}`（caseGroupService.pollMultiAnalysis 的数据源，完成后读 `GET /api/llm/case-report-by-case/{case_id}`）。

**智能建案 / 增量加任务 / 聚合状态**：

```bash
curl -X POST http://localhost:8090/api/llm/cases/smart-create \
  -H "Content-Type: application/json" \
  -d '{"name": "自动并案", "description": "", "auto_associate": true, "auto_analyze": true}'
```

> `SmartCreateCaseRequest` 默认 `auto_associate=true / auto_analyze=true`。增量接口：`POST .../tasks/incremental` 请求体为 `IncrementalAddTasksRequest{new_task_ids, auto_analyze=true}`；`POST .../incremental-analysis` 请求体为 `IncrementalAnalysisRequest{force_reanalyze=false, new_task_ids=[]}`；`GET .../analysis-status` 返回 `CaseAnalysisStatusResponse`（含 `tasks[]: TaskStatusItem{task_id, analysis_status, files_count, analyzed_files_count, ...}`）。

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

```bash
curl -X POST http://localhost:8090/api/reports \
  -H "Content-Type: application/json" \
  -d '{"scope_type": "task", "scope_id": "task_xxx"}'
```

响应 `202` 要点：新建报告版本的标识与初始状态（reportService.createVersion 的数据源）。

```bash
curl "http://localhost:8090/api/reports?scope_type=task&scope_id=task_xxx"
curl "http://localhost:8090/api/reports/r1/status"
curl "http://localhost:8090/api/reports/r1/manifest"
curl "http://localhost:8090/api/reports/r1/categories/android.wechat%2Fmessages/pages/2"
curl "http://localhost:8090/api/reports/r1/search?q=%E8%BD%AC%E8%B4%A6&limit=20"
```

响应要点：章节分页读取返回该 category 的正文块；search 为 `{total, offset, limit, hits[]}`（`SearchResponse` 模型，reportService.test.js 用这两个 URL 做契约测试）。

### 6.2 报告证据（report_evidence.py）

- `GET /api/reports/evidence`：证据列表。
- `POST /api/reports/evidence`（200）：登记证据（重复 409，绑定冲突 409）。
- `PUT /api/reports/evidence`（200）：更新证据（校验失败 422）。

```bash
curl -X POST http://localhost:8090/api/reports/evidence \
  -H "Content-Type: application/json" \
  -d '{"task_id": "task_xxx", "evidence_key": "file:/ws/extract/report.docx", "report_status": "main", "added_by": "analyst-zhang"}'
```

请求要点（`AddReportEvidenceRequest`，`extra="forbid"`）：`task_id / evidence_key / report_status("main"|"appendix") / added_by` 必填，`analysis_id?` 可选绑定已采纳分析。更新（`UpdateReportEvidenceRequest`）至少传一个字段，`report_status` 可为 `"excluded"|"main"|"appendix"`。

```bash
curl -X PUT http://localhost:8090/api/reports/evidence \
  -H "Content-Type: application/json" \
  -d '{"task_id": "task_xxx", "evidence_key": "file:/ws/extract/report.docx", "report_status": "appendix"}'
```

### 6.3 报告生成（report_generation.py）

- `POST /api/reports/generate`（**202**）：请求体 `{task_id, requested_by}`（`GenerateReportRequest`，`extra="forbid"`，已验证）；无报告证据 409。
- `GET /api/reports/generations/{generation_id}`：生成状态。

```bash
curl -X POST http://localhost:8090/api/reports/generate \
  -H "Content-Type: application/json" \
  -d '{"task_id": "task_xxx", "requested_by": "analyst-zhang"}'
```

响应 `202` 要点：`generation_id` 等（evidence/prompt/envelope 全部由服务端冻结，不接受客户端传入）。轮询：

```bash
curl "http://localhost:8090/api/reports/generations/gen_aaa?task_id=task_xxx"
```

响应要点（`GenerationStatusResponse`）：`{generation_id, task_id, status, requested_by, prompt_version, input_schema_version, input_hash, report_id?, produced_version?, model?}`——useReportGenerationPolling 坚持 exact id 轮询、绝不回退 latest。

### 6.4 报告叙事（report_narrative.py）

- `GET /api/reports/narrative/versions/{report_id}`：叙事版本记录。

```bash
curl http://localhost:8090/api/reports/narrative/versions/r1
```

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

**捕获证据快照**（严格 `{task_id, evidence_key}`，`extra="forbid"`）：

```bash
curl -X POST http://localhost:8090/api/investigation/snapshots \
  -H "Content-Type: application/json" \
  -d '{"task_id": "task_xxx", "evidence_key": "file:/ws/extract/report.docx"}'
```

响应要点：`EvidenceSnapshot`（不可变快照记录）。`evidence_key` 非法 400、找不到 404、证据库不可用 503。

**启动二级分析**（`CreateAnalysisRequest`：`task_id / evidence_key` 必填，`analyst_note?`(≤20000)、`case_context?`(≤20000)、`related_evidence?`(≤20 个 key)）：

```bash
curl -X POST http://localhost:8090/api/investigation/analyses \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "task_xxx",
    "evidence_key": "file:/ws/extract/report.docx",
    "analyst_note": "疑似伪造的转账凭证",
    "related_evidence": ["file:/ws/extract/chat.db"]
  }'
```

响应 `202` 要点：排队中的 `SecondaryAnalysis`（后台 LLM 执行），随后 `GET /analyses/{analysis_id}` 轮询或 `GET /analyses?evidence_key=&status=` 过滤。

**审阅分析结果**（`ReviewAnalysisRequest`：`task_id / decision / reviewer` 必填，`reason?`≤4000；冲突 409）：

```bash
curl -X POST http://localhost:8090/api/investigation/analyses/ana_1/review \
  -H "Content-Type: application/json" \
  -d '{"task_id": "task_xxx", "decision": "accepted", "reviewer": "analyst-zhang", "reason": "结论与聊天记录互证"}'
```

**创建调查事件 / 挂接证据**（`CreateInvestigationEventRequest`：`task_id / title(≤500) / created_by(≤256)` 必填、`summary?`(≤20000)，`extra="forbid"`）：

```bash
curl -X POST http://localhost:8090/api/investigation/events \
  -H "Content-Type: application/json" \
  -d '{"task_id": "task_xxx", "title": "伪造转账凭证", "summary": "…", "created_by": "analyst-zhang"}'
```

响应 `201` 要点：新事件对象（含 v1 叙事）。事件挂接证据（`LinkEventEvidenceRequest`：`task_id / evidence_key / linked_by`；重复挂接 409）：

```bash
curl -X POST http://localhost:8090/api/investigation/events/evt_1/evidence \
  -H "Content-Type: application/json" \
  -d '{"task_id": "task_xxx", "evidence_key": "file:/ws/extract/report.docx", "linked_by": "analyst-zhang"}'
```

查询侧（`max_base_nodes` 默认 200，1–1000）：

```bash
curl "http://localhost:8090/api/investigation/events?task_id=task_xxx&limit=20"
curl "http://localhost:8090/api/investigation/evidence?task_id=task_xxx"
curl "http://localhost:8090/api/investigation/graph?task_id=task_xxx&max_base_nodes=120"
```

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

**总览与引导初始化**：

```bash
curl http://localhost:8090/api/investigation/workbench/task_xxx
curl -X POST http://localhost:8090/api/investigation/workbench/task_xxx/bootstrap \
  -H "Content-Type: application/json" \
  -d '{"mode": "cluster_seed", "generate_llm_summaries": false}'
```

请求要点（`BootstrapRequest`，`extra="forbid"`）：`mode="cluster_seed"`、`generate_llm_summaries=false`——正是前端 `bootstrapInvestigation` 的默认载荷。

**触发证据分析 job 并轮询**（`WorkbenchAnalysisRequest`：`evidence_key` 必填，`analyst_note? / case_context? / related_evidence?(≤20) / event_id? / include_case_context=true / include_related_evidence=true`）：

```bash
curl -X POST http://localhost:8090/api/investigation/workbench/task_xxx/evidence/analyze \
  -H "Content-Type: application/json" \
  -d '{"evidence_key": "file:/ws/extract/report.docx", "analyst_note": "重点核对金额时间线"}'
```

```bash
curl http://localhost:8090/api/investigation/workbench/task_xxx/analysis-jobs/job_aaa
```

响应要点：job 状态经 `pollAnalysisJob`（1.5s 间隔，completed/failed/invalid 终止）轮询。

**事件列表 / 详情 / 证据 / 版本链**：

```bash
curl "http://localhost:8090/api/investigation/workbench/task_xxx/events?limit=20"
curl http://localhost:8090/api/investigation/workbench/task_xxx/events/evt_1
curl "http://localhost:8090/api/investigation/workbench/task_xxx/evidence/detail?evidence_key=file%3A%2Fws%2Fextract%2Freport.docx"
curl http://localhost:8090/api/investigation/workbench/task_xxx/events/evt_1/versions
curl http://localhost:8090/api/investigation/workbench/task_xxx/events/evt_1/claims/effective
curl http://localhost:8090/api/investigation/workbench/task_xxx/claims/claim_1
```

**审阅 / 采纳**（`WorkbenchReviewRequest`：`decision / reviewer="workbench" / reason? / acknowledge_warnings=false`）：

```bash
curl -X POST http://localhost:8090/api/investigation/workbench/task_xxx/analysis/ana_1/accept \
  -H "Content-Type: application/json" \
  -d '{"decision": "accepted", "reviewer": "analyst-zhang", "reason": "结论可靠"}'
```

**报告证据集管理**（`WorkbenchReportEvidenceRequest`：`evidence_key` 必填、`usage="excluded"`、`role? / report_note? / analysis_id? / added_by="workbench"`）：

```bash
curl http://localhost:8090/api/investigation/workbench/task_xxx/report-evidence
curl -X POST http://localhost:8090/api/investigation/workbench/task_xxx/report-evidence \
  -H "Content-Type: application/json" \
  -d '{"evidence_key": "file:/ws/extract/report.docx", "usage": "main", "added_by": "analyst-zhang"}'
```

**终版报告读取与发布**：

```bash
curl http://localhost:8090/api/investigation/workbench/task_xxx/final-reports
curl http://localhost:8090/api/investigation/workbench/task_xxx/final-reports/rep_1/markdown
curl http://localhost:8090/api/investigation/workbench/task_xxx/final-reports/rep_1/html
curl -X POST http://localhost:8090/api/investigation/workbench/task_xxx/final-reports/rep_1/publish
```

响应要点：markdown/html/print 为文本响应（前端以 `responseType: 'text'` 消费）；publish 返回发布结果与 publication 引用。

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

**示例——任务清单与数据库定位**（代理 C++ 后端）：

```bash
curl "http://localhost:8090/api/db/tasks?status=completed&page=1&page_size=20"
curl http://localhost:8090/api/db/tasks/task_xxx
curl http://localhost:8090/api/db/tasks/task_xxx/databases
```

响应要点：列表为 `{success, tasks[], total_count, page, page_size, timestamp}`（`page=1` 起、`page_size≤100`）；databases 为 `TaskDatabasesResponse{success, task_id, databases[], timestamp}`。

**文件 / 事件分页读取**（读任务的 `_files.db` / `_events.db`）：

```bash
curl "http://localhost:8090/api/db/tasks/task_xxx/files?page=1&page_size=50"
curl "http://localhost:8090/api/db/tasks/task_xxx/events?page=1&page_size=100"
```

响应要点：`FileListResponse / EventListResponse` 形态（`success + 记录数组 + 分页字段`）。

**导出**：

```bash
curl "http://localhost:8090/api/db/tasks/task_xxx/export/toon" -o export.toon
curl "http://localhost:8090/api/db/tasks/task_xxx/export/json" -o export.json
```

---

## 10. Office 文档 API

> 源码：`routes/office.py`（前缀 `/api/office`）

- `POST /api/office/parse`：解析 Office 文档（docx/xlsx/pptx）为 Markdown；需 `task_id` 或 `workspace_root` 锚定工作区，文件必须在任务工作区内。
- `GET /api/office/supported-types`：支持的文件类型列表。

```bash
curl -X POST http://localhost:8090/api/office/parse \
  -H "Content-Type: application/json" \
  -d '{"task_id": "task_xxx", "file_path": "/ws/extract/账目.xlsx"}'
```

请求要点（`ParseRequest`）：`file_path` 必填；`task_id`（归属锚）或 `workspace_root`（已弃用的独立锚）二选一——文件必须是该任务的已知记录（files.path 精确匹配）或位于共享提取暂存根内，裸主机存在性检查不算数。响应（`ParseResponse`）：`{success, content(Markdown), file_type, error?}`。

```bash
curl http://localhost:8090/api/office/supported-types
```

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

```bash
curl http://localhost:8090/api/markitdown/status
curl -X POST http://localhost:8090/api/markitdown/convert-one \
  -H "Content-Type: application/json" \
  -d '{"task_id": "task_xxx", "input_root": "/ws/extract", "input_file": "/ws/extract/report.docx", "output_root": "/ws/md"}'
curl -X POST http://localhost:8090/api/markitdown/batch-convert \
  -H "Content-Type: application/json" \
  -d '{"task_id": "task_xxx", "input_dir": "/ws/extract/docs", "output_dir": "/ws/md/docs"}'
```

响应要点：`convert-one` 返回单文件转换结果（含输出路径）；`batch-convert` 返回 `{success, total_files, converted, ...}`（failed/skipped 计数随实现字段附带）。三个边界（任务工作区 / 提取根 / 任务 files.db）之外的路径一律 400。

---

## 12. 微信关系图谱 API

> 源码：`routes/wechat_graph.py` 挂载 `wechat_graph_endpoints/`（前缀 `/api/wechat`）；所有 GET 均需 `task_id` 查询参数（必填）

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/api/wechat/chat` | 双人会话记录（参数 `user1`、`user2`、`offset=0`、`limit=50`(1–500)） |
| GET | `/api/wechat/chat/group` | 群聊记录（参数 `chatroom`、`offset`、`limit`） |
| GET | `/api/wechat/owner` | 账号所有者信息 |
| GET | `/api/wechat/contacts` | 联系人列表（`include_chatrooms=false` 可含群组条目） |
| GET | `/api/wechat/graph` | 关系图谱数据（`include_metrics=true` 含 PageRank/介数/社区） |
| GET | `/api/wechat/graph/timeline` | 通信时间线（参数 `interval="month"|"week"`，非法值 400） |
| GET | `/api/wechat/graph/community` | 社区发现（Louvain） |
| GET | `/api/wechat/graph/person/{username}` | 个人 ego 网络 |
| POST | `/api/wechat/graph/invalidate` | 清除图谱缓存（`task_id` 为查询参数） |

> **参数勘误（本次核对源码 `wechat_graph_endpoints/_data.py`、`_graph.py` 后修正）**：旧表写"按 talker 过滤"、"chatroom_name"、"start_time/end_time"均不正确——实际为 `user1/user2`、`chatroom`、`interval`。

**示例——双人会话与群聊**：

```bash
curl "http://localhost:8090/api/wechat/chat?task_id=task_xxx&user1=wxid_owner&user2=wxid_zhangsan&offset=0&limit=50"
curl "http://localhost:8090/api/wechat/chat/group?task_id=task_xxx&chatroom=12345678@chatroom&offset=0&limit=100"
```

响应要点（`ChatResponse`）：`{success, task_id, messages[], total, page, page_size, total_pages, timestamp}`——消息行含 `sender / receiver / content / timestamp / media_url / media_type / msg_type / is_send / chatroom_name / sender_nickname` 等可空字段。

**关系图谱与时间线**：

```bash
curl "http://localhost:8090/api/wechat/graph?task_id=task_xxx&include_metrics=true"
curl "http://localhost:8090/api/wechat/graph/timeline?task_id=task_xxx&interval=week"
curl "http://localhost:8090/api/wechat/graph/community?task_id=task_xxx"
curl "http://localhost:8090/api/wechat/graph/person/wxid_zhangsan?task_id=task_xxx"
```

响应要点：graph 为 `GraphResponse{success, task_id, nodes[], edges[], communities[], metadata}`；timeline 为 `TimelineResponse{success, task_id, granularity, intervals[]}`；community 为 `CommunityResponse{success, task_id, communities[], total_communities}`；person 为 `PersonEgoResponse{success, task_id, username, node, connections[]}`。

**联系人与缓存失效**：

```bash
curl "http://localhost:8090/api/wechat/contacts?task_id=task_xxx&include_chatrooms=false"
curl -X POST "http://localhost:8090/api/wechat/graph/invalidate?task_id=task_xxx"
```

---

## 13. 事件关联 API

> 源码：`routes/associations.py`（前缀 `/api/associations`）

- `POST /api/associations/cluster-files`：事件簇 → 关联文件（`{task_id, ...}`；无 files 数据库 400）。
- `POST /api/associations/file-clusters`：文件 → 关联事件簇（无 events 数据库 400）。

**事件簇 → 关联文件**（`ClusterFilesRequest`：`task_id / time_window / event_type` 必填、`parent_directory=""`、`limit=100`(1–1000)、`timestamp?`(弃用)）：

```bash
curl -X POST http://localhost:8090/api/associations/cluster-files \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "task_xxx",
    "time_window": 4938271,
    "event_type": "CREATED",
    "parent_directory": "/etc/ssh/",
    "limit": 50
  }'
```

响应要点（`ClusterFilesResponse`）：`{success, files[], total_count, cluster_info{}}`。

**文件 → 关联事件簇**（`FileClustersRequest`：`task_id / file_path` 必填、`limit=100`(1–1000)）：

```bash
curl -X POST http://localhost:8090/api/associations/file-clusters \
  -H "Content-Type: application/json" \
  -d '{"task_id": "task_xxx", "file_path": "/etc/ssh/sshd_config", "limit": 50}'
```

响应要点（`FileClustersResponse`）：`{success, clusters[], total_count, file_info{}}`。AnalysisCenter 双抽屉消费这两个端点（associationService）。

---

## 14. OSS AI 分析 API

> 源码：`routes/oss_analysis.py`（router 自带前缀 `/api/forensics/oss/ai`）——这是 Python 服务中唯一存在的 OSS 能力（C++ 侧 OSS 路由未注册，见 CPP_REST_API.md）

### POST /api/forensics/oss/ai/filter

LLM 过滤 OSS 对象。请求体（`OSSFilterRequest`，已验证）：`{task_id, oss_db_path, case_description, bucket?, max_objects}`（`max_objects` 默认 200，范围 1–2000）。

### POST /api/forensics/oss/ai/analyze

LLM 分析已过滤对象。请求体（`OSSAnalyzeRequest`，已验证）：`{task_id, object_ids: [int], oss_db_path, download_dir, model_type="text"（仅 text|vision）}`。

**过滤示例**：

```bash
curl -X POST http://localhost:8090/api/forensics/oss/ai/filter \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "task_xxx",
    "oss_db_path": "/data/tasks/task_xxx/oss.db",
    "case_description": "排查泄露的客户名单与内部文档",
    "bucket": "backup-prod",
    "max_objects": 500
  }'
```

响应要点（`OSSFilterResponse`）：过滤作业结果（相关对象标记与计数）。`max_objects` 默认 200、范围 1–2000。

**分析示例**：

```bash
curl -X POST http://localhost:8090/api/forensics/oss/ai/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "task_xxx",
    "object_ids": [101, 102, 205],
    "oss_db_path": "/data/tasks/task_xxx/oss.db",
    "download_dir": "/data/tasks/task_xxx/oss_download",
    "model_type": "text"
  }'
```

响应要点（`OSSAnalyzeResponse`）：逐对象 LLM 分析结论。注意 `model_type` 仅接受 `text|vision`。

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

```bash
curl "http://localhost:8090/api/system/logs?lines=200"
curl http://localhost:8090/api/system/logs/httpserver
curl -N http://localhost:8090/api/system/logs-stream/httpserver
```

响应要点：logs 返回日志文本/行数组（`lines` 可截取尾部）；`logs/{service}` 找不到服务 404；`logs-stream/{service}` 为 SSE（`curl -N` 才能看到流式推送）。

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

```bash
curl http://localhost:8091/api/auth/me -H "Authorization: Bearer $USER_TOKEN"
curl -X POST http://localhost:8091/api/auth/refresh -H "Authorization: Bearer $USER_TOKEN"
```

角色权限矩阵（`auth.py`）：`super_admin`（全量）、`org_admin`、`analyst`（create_tasks/view_results）、`auditor`（view_results）。

### 16.2.1 完整连环示例（login → 注册令牌 → register → poll → status → results）

```bash
# ① 管理员登录，换 JWT（OAuth2 密码流，必须 form-encoded）
curl -X POST http://localhost:8091/api/auth/login \
  -d "username=admin&password=secret"
# → {access_token: "<JWT>", token_type: "bearer", expires_in: 3600}
export USER_TOKEN="<上一步的 access_token>"

# ② 为组织签发客户端注册令牌（org_admin 及以上）
curl -X POST http://localhost:8091/api/organizations/org_uuid/registration-tokens \
  -H "Authorization: Bearer $USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"org_id": "org_uuid", "max_clients": 10, "expires_in_hours": 720}'
# → RegistrationTokenResponse{id, org_id, token, max_clients, used_count, expires_at, created_by}

# ③ 客户端凭令牌注册（拿 client credential；hostname 重复 409、令牌过期/超限 401）
curl -X POST http://localhost:8091/api/clients/register \
  -H "Content-Type: application/json" \
  -d '{
    "registration_token": "<②的 token>",
    "hostname": "lab-agent-01",
    "capabilities": {"max_concurrent_tasks": 2, "supported_formats": ["E01", "DD", "Directory"], "version": "1.0.0"}
  }'
# → ClientCredentialResponse{client_id, jwt_token, poll_interval: 10, server_url}
export CLIENT_TOKEN="<上一步的 jwt_token>"

# ④ 客户端上报本机镜像索引（仅元数据；镜像字节永不上传）
curl -X POST http://localhost:8091/api/clients/client_uuid/index-images \
  -H "Authorization: Bearer $CLIENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '[{"path": "/dev/nvme0n1", "size_bytes": 512110190592, "format": "DD", "md5_hash": null, "image_metadata": {}}]'

# ⑤ 分析师对已索引镜像建任务（org_id 取自登录用户，不收 body）
curl -X POST http://localhost:8091/api/tasks \
  -H "Authorization: Bearer $USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "client_uuid",
    "disk_image_id": "image_uuid",
    "task_name": "lab-01 磁盘全量分析",
    "analysis_type": "full",
    "priority": "normal",
    "ttl_hours": 24
  }'
# → AnalysisTaskResponse{id, org_id, client_id, user_id, disk_image_id, task_name,
#    analysis_type, status, progress, started_at?, completed_at?, error_message?,
#    task_metadata, created_at}

# ⑥ 客户端轮询待执行命令（同时刷新 last_poll 在线心跳）
curl http://localhost:8091/api/commands/poll \
  -H "Authorization: Bearer $CLIENT_TOKEN"
# → CommandPollResponse{commands: [CommandResponse...], server_time}
#    CommandResponse 含 id/client_id/command_type/parameters/priority/status/ttl/
#    assigned_at?/completed_at?/result_message?/retry_count

# ⑦ 客户端上报命令状态（会传播到关联分析任务的 progress/status）
curl -X POST http://localhost:8091/api/commands/cmd_uuid/status \
  -H "Authorization: Bearer $CLIENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command_id": "cmd_uuid", "status": "in_progress", "progress": 45, "message": "parsing filesystem"}'
# → {"updated": true}

# ⑧ 客户端批量上传产物引用（不传文件本体）
curl -X POST http://localhost:8091/api/tasks/task_uuid/results \
  -H "Authorization: Bearer $CLIENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "artifacts": [
      {
        "result_type": "database",
        "file_path": "/var/forensics/out/case_files.db",
        "file_size": 10485760,
        "storage_location": "client-local",
        "result_metadata": {"base_name": "case"}
      },
      {
        "result_type": "file",
        "file_path": "/var/forensics/out/carved/report.pdf",
        "file_size": 204800,
        "storage_location": "client-local",
        "result_metadata": {"base_name": "report"}
      }
    ]
  }'
# → list[AnalysisResultResponse]（每条含 task_id/client_id/result_type/file_path/
#    file_size/storage_location/result_metadata/created_at）

# ⑨ 用户侧查看任务结果与 LLM 分析
curl http://localhost:8091/api/tasks/task_uuid/results \
  -H "Authorization: Bearer $USER_TOKEN"
curl http://localhost:8091/api/tasks/task_uuid/llm-analyses \
  -H "Authorization: Bearer $USER_TOKEN"
```

要点：`result_type` 仅 `database|file|metadata`；`result_metadata` 原样入库以保留 `base_name`；跨组织访问一律 403、非属主上报 403、任务/命令不存在 404。

### 16.3 组织（/api/organizations）

- `POST /api/organizations`：创建组织。
- `GET /api/organizations`：组织列表。
- `GET /api/organizations/{org_id}`：组织详情。
- `POST /api/organizations/{org_id}/registration-tokens`：签发客户端注册令牌。
- `GET /api/organizations/{org_id}/registration-tokens`：令牌列表。
- `DELETE /api/organizations/registration-tokens/{token_id}`：吊销令牌。

```bash
curl -X POST http://localhost:8091/api/organizations \
  -H "Authorization: Bearer $USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "第一取证实验室", "subscription_tier": "free", "settings": {}}'
curl http://localhost:8091/api/organizations -H "Authorization: Bearer $USER_TOKEN"
curl http://localhost:8091/api/organizations/org_uuid/registration-tokens -H "Authorization: Bearer $USER_TOKEN"
```

### 16.4 客户端（/api/clients）

- `POST /api/clients/register`：客户端凭注册令牌注册（返回 client credential）。
- `GET /api/clients`：客户端列表。
- `GET /api/clients/{client_id}`：客户端详情。
- `DELETE /api/clients/{client_id}`：删除客户端。
- `POST /api/clients/{client_id}/index-images`：登记客户端可见的磁盘镜像索引。
- `GET /api/clients/{client_id}/images`：镜像列表（`DiskImageResponse[]`）。

```bash
curl http://localhost:8091/api/clients -H "Authorization: Bearer $USER_TOKEN"
curl http://localhost:8091/api/clients/client_uuid/images -H "Authorization: Bearer $USER_TOKEN"
curl -X DELETE http://localhost:8091/api/clients/client_uuid -H "Authorization: Bearer $USER_TOKEN"
```

### 16.5 命令队列（/api/commands）

| 方法 | 路径 | 认证方 | 用途 |
|------|------|--------|------|
| POST | `/api/commands` | 用户 | 下发命令 `{client_id, ...}`；跨组织 403，客户端不存在 404 |
| GET | `/api/commands/poll` | **客户端** | 拉取待执行命令（同时刷新 `last_poll` 在线心跳） |
| POST | `/api/commands/{command_id}/status` | **客户端** | 上报命令状态（仅能上报自己的命令；状态会传播到关联分析任务） |
| GET | `/api/commands/{command_id}` | 用户 | 命令详情 |
| GET | `/api/commands/client/{client_id}` | 用户 | 按客户端查命令历史 |
| POST | `/api/commands/expire` | 用户 | 过期滞留命令 |

**用户下发命令**（`CommandCreate`：`client_id`、`command_type` 仅 `analyze_disk|extract_file|health_check`、`parameters{}`、`priority="normal"`、`ttl_hours=24`(1–168)）：

```bash
curl -X POST http://localhost:8091/api/commands \
  -H "Authorization: Bearer $USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "client_uuid",
    "command_type": "analyze_disk",
    "parameters": {
      "image_path": "/dev/nvme0n1",
      "analysis_type": "full",
      "output_format": "sqlite",
      "options": {"file_carving": true, "llm_text_extraction": true}
    },
    "priority": "high",
    "ttl_hours": 48
  }'
```

**用户侧查询**：

```bash
curl http://localhost:8091/api/commands/cmd_uuid -H "Authorization: Bearer $USER_TOKEN"
curl "http://localhost:8091/api/commands/client/client_uuid?status_filter=completed" -H "Authorization: Bearer $USER_TOKEN"
curl -X POST http://localhost:8091/api/commands/expire -H "Authorization: Bearer $USER_TOKEN"   # 仅 super_admin
```

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

```bash
curl http://localhost:8091/api/tasks -H "Authorization: Bearer $USER_TOKEN"
curl http://localhost:8091/api/tasks/task_uuid -H "Authorization: Bearer $USER_TOKEN"
curl -X POST http://localhost:8091/api/tasks/task_uuid/cancel -H "Authorization: Bearer $USER_TOKEN"
```

创建请求体见 16.2.1 第⑤步（`AnalysisTaskCreate`：`client_id / disk_image_id / task_name(1–255) / analysis_type(full|quick|windows|android|linux) / priority="normal" / ttl_hours=24`；`org_id` 一律取自登录用户）。

### 16.7 结果上报（/api/tasks，results.py）

- `POST /api/tasks/{task_id}/results`（**客户端**）：批量上传产物引用，请求体 `{artifacts: [ResultArtifact...]}`（`ResultUploadRequest`，已验证；artifact 含 `result_type / file_path / file_size / storage_location / result_metadata` 等，`result_metadata` 原样入库以保留 `base_name`）。
- `GET /api/tasks/{task_id}/results`（用户）：任务结果列表。
- `GET /api/tasks/{task_id}/llm-analyses`（用户）：任务 LLM 分析结果。

---

## 错误响应

httpserver 未捕获异常：`500 {success: false, message: "Internal server error", error, timestamp}`；参数校验失败：`422 {success: false, message: "Validation error", errors, timestamp}`。各路由业务错误为 FastAPI 标准 `{"detail": "..."}` + 4xx。C/S 服务未授权返回 `401`（Bearer）。

---

## 附录：端点 ↔ 前端页面 ↔ 后端数据源映射

前端 `import { pythonApi }` 的服务全部指向本服务（:8090），`import { csApi }` 指向 C/S 服务（:8091）。下表整理各端点组的真实调用方、后端服务实现与读写的存储（页面消费者详见 `docs/modules/web/Services.md`）。

### A. httpserver（:8090）

| 端点组 | 前端调用方（web/src/services/） | 页面/组件消费者 | 后端服务 | 读写的存储 |
|--------|--------------------------------|----------------|----------|------------|
| `/health`、`/health/ready` | systemService.js（getPythonHealth） | Dashboard | health.py | 内存（探测 C++/Neo4j/LLM/Redis） |
| `/api/system/redis/status`、`/api/system/info` | systemService.js（getRedisStatus） | Dashboard、Settings | health.py | Redis（可选；不可用回退内存） |
| graphiti ingest / ingest/file / ingest/events | graphitiService.js（startIngest 等） | KnowledgeGraph、Files 页导入按钮 | GraphitiService + IngestionJobManager | Neo4j（图）、`_files.db`/`_events.db`（读取源） |
| graphiti jobs | graphitiService.js（getGraphitiJob 等） | KnowledgeGraph | IngestionJobManager | 内存 job 表 |
| graphiti migrate | （暂无页面直调） | — | graphiti_parts 迁移器 | Neo4j |
| graphiti search / entities / relationships | graphitiService.js | KnowledgeGraph | GraphitiService | Neo4j |
| graphiti status / tasks / graph / 删除 | graphitiService.js | KnowledgeGraph | GraphitiService | Neo4j |
| `/api/llm/analyze` | llmService.js（analyzeContent） | Files、useFileLLMAnalysis | llm_service | LLM API；结果可选写 `_files.db` |
| `/api/llm/analyze/file`（multipart） | llmService.js（analyzeFile，暂无页面） | — | llm_service | LLM API |
| `/api/llm/batch`、`/api/llm/batch/{job_id}` | llmService.js（startBatchAnalysis/pollBatchStatus） | Files、useFileLLMAnalysis | llm_service 后台 job | 内存 job + `_files.db` |
| `/api/llm/models`、`/api/llm/status` | llmService.js（getModels/getLLMStatus） | Settings、Dashboard、Files | llm_service | 配置 |
| `/api/llm/toggle-relevance` | llmService.js（toggleFileRelevance） | AnalysisCenter | llm_service | `_files.db`（files.llm_is_relevant 等） |
| `/api/llm/analyze-event-cluster` | forensicsService.js（analyzeEventCluster/reanalyze） | Timeline、AnalysisCenter | case_analysis 服务 | `_events.db` llm_* 列 |
| `/api/llm/analyze/dll` | llmService.js（analyzeDLL） | Files 页 | dll 服务（调 C++ 解析） | `_files.db` + LLM API |
| case-description / reanalyze-files / case-analysis/{job} / case-report / filtered-files | caseAnalysisService.js | AnalysisCenter、Files | case_analysis_service | `_files.db`、tasks.json（经 C++） |
| windows-analysis / windows-report / windows-export | （暂无页面直调） | — | case_analysis（_windows） | `_files.db` |
| intelligence-report 系列 | intelligenceReportService.js | IntelligenceReportReader（case-intelligence Tab） | intelligence_report 读取器 | `_files.db` 等任务库 + 元数据持久化 |
| `/api/llm/cases` CRUD、associate-tasks、smart-create | caseGroupService.js | caseSlice、Cases 页 | httpx 代理 C++ `/api/cases` | data/cases.json（C++ 侧） |
| multi-image-analysis（+轮询）、analysis-status、incremental-* | caseGroupService.js（startMultiAnalysis/pollMultiAnalysis） | Cases 页 | CaseAggregationManager | 多任务 `_files.db`、案件报告文件 |
| `/api/reports`（版本/状态/清单/章节/检索） | reportService.js + reportDataSource.js（HttpReportDataSource） | ForensicReportPage | forensic_report.service/repository | 报告 SQLite 仓库（report_versions 等表）+ 快照目录（search.sqlite3） |
| `/api/reports/evidence` | investigationService.js（list/add/updateReportEvidence） | Investigation 域 | ReportEvidenceService | investigation.db |
| `/api/reports/generate`、`generations/{id}`、`narrative/versions` | reportGenerationService.js | GenerateReportPanel、useReportGenerationPolling | forensic_report.generation | 报告 SQLite 仓库（report_generation_inputs 等） |
| investigation snapshots/analyses/review/events/evidence/graph | investigationService.js（冻结契约组） | 死代码页面 pages/Investigation.jsx（在线页面走 workbench 组） | InvestigationCaptureService / SecondaryAnalysisExecutor / InvestigationEventService | investigation.db（快照/分析/事件表） |
| investigation workbench 全组 | investigationService.js（workbench 组 30 余端点） | `/investigation`、`/investigation/report` 路由页 + 轮询 hooks | investigation 工作台管理器 | investigation.db + final_report_repository |
| `/api/db/tasks*`、files、events、export | （暂无页面直调，调试/集成用） | — | database.py（代理 C++ / 直读任务库） | data/tasks.json（经 C++）、`_files.db`、`_events.db` |
| `/api/office/parse`、`supported-types` | officeService.js（parseFile/getSupportedFormats） | Files 页 Office 预览 Tab | office_service | 任务工作区文件（只读） |
| `/api/markitdown/convert`、`convert-one`、`batch-convert`、`status` | （C++ 侧与集成方调用为主） | — | markitdown 转换器 | 任务工作区/提取根（边界校验） |
| `/api/wechat/*` | wechatService.js（9 个方法） | useWeChatGraph | wechat_graph 服务（缓存于 Redis/内存） | `_android.db`（微信制表） |
| `/api/associations/cluster-files`、`file-clusters` | associationService.js | AnalysisCenter 双抽屉 | associations.py | `_files.db`（mtime/ctime）+ `_raw.db`（atime/crtime）+ `_events.db` |
| `/api/forensics/oss/ai/filter`、`analyze` | （前端 ossService 指向 C++ 未注册路由；Python AI 组为集成方入口） | — | oss_analysis_service | OSS 对象库（oss_db_path）+ 下载目录 |
| `/api/system/logs`、`logs/{service}`、`logs-stream/{service}` | systemService.js（部分） | Terminal | system.py | 服务日志文件 |

### B. 分布式 C/S 服务（:8091）

| 端点组 | 前端调用方 | 页面消费者 | 后端服务 | 读写的表 |
|--------|-----------|-----------|----------|-----------|
| `/api/auth/login`、`refresh`、`me` | csAuthService.js（csLogin/csRefresh/csMe） | `/distributed` 冒烟页 | auth_service（JWT） | users（读）、last_login 更新 |
| `/api/organizations`、registration-tokens | （暂无前端封装） | — | organizations.py | organizations、registration_tokens |
| `/api/clients/register`、列表/详情/删除、index-images、images | csClientService.js（listClients/getClient） | `/distributed` | clients.py + auth_service | clients、disk_images |
| `/api/commands`（下发/详情/历史/expire） | （暂无前端封装） | — | CommandQueueService | command_queue、analysis_tasks（状态传播） |
| `/api/commands/poll`、`/{id}/status` | 客户端 agent（非浏览器） | — | CommandQueueService | command_queue（领取/回写）、clients.last_poll |
| `/api/tasks`（创建/列表/详情/取消） | csTaskService.js（4 个方法） | `/distributed` | tasks.py | analysis_tasks、clients、disk_images（校验） |
| `/api/tasks/{id}/results`（上传=客户端 / 读取=用户）、`llm-analyses` | （结果查看暂无前端封装） | — | ResultAggregator | analysis_results（产物引用）、llm_analyses |

> 设计红线：`analysis_results` 只存 `file_path + storage_location + result_metadata`（含 `base_name`）引用，磁盘镜像字节永不离开客户端。

---

## 相关文档

- [C++ REST API 参考](./CPP_REST_API.md)
- FastAPI 交互文档：`http://localhost:8090/docs`
- 前端服务映射细节：[web/Services 模块文档](../modules/web/Services.md)

---

**最后更新**: 2026-08-24（扩充：全端点示例与映射附录）
