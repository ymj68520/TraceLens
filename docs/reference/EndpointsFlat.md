# 全端点平面清单（EndpointsFlat）

> 本文把三个服务的**全部** HTTP 端点压平成一张大表，供"找一个端点在哪、谁在调、详细文档在哪"的速查。端点数量与路径逐一抄录自 [CPP_REST_API.md](../api_reference/CPP_REST_API.md)、[Python_REST_API.md](../api_reference/Python_REST_API.md) 与 [RouteReference.md](../modules/cpp/network/routes/RouteReference.md)，未做增删；字段级语义请跳转"详细文档"列。末节单列**未注册/死端点**（运行时 404 或固定 410）。

| 服务 | 进程 | 默认端口 | 认证 | 详细 API 参考 |
|------|------|---------|------|--------------|
| C++ 服务 | `forensic_analyzer --http-server` | **8080**（run.sh 未设 `HTTP_SERVER_PORT` 时兜底 8666） | 无 | [CPP_REST_API.md](../api_reference/CPP_REST_API.md) |
| Python httpserver | `python -m httpserver.main` | **8090**（`PYTHON_HTTP_PORT`） | 无 | [Python_REST_API.md](../api_reference/Python_REST_API.md) |
| 分布式 C/S server | `python -m server.main` | **8091**（`PORT`） | JWT Bearer | [Python_REST_API.md §16](../api_reference/Python_REST_API.md) |

---

## 一、C++ 服务（:8080）

### 1.1 任务管理（TaskRoutes 族）

| 方法 | 路径 | 关键参数 | 语义 | 典型调用方 | 详细文档 |
|------|------|---------|------|-----------|---------|
| GET | `/tasks`、`/api/tasks`、`/api/tasks/list` | `status`、`priority`、`limit=100`、`offset` | 任务列表（过滤+分页） | taskService.js（fetchTasks/listTasks）→ Tasks 页 | [TaskRoutes.md](../modules/cpp/network/routes/TaskRoutes.md) |
| POST | `/tasks`、`/api/tasks` | `image_path`* 及 20 余个可选字段 | 创建取证分析任务（201） | taskService.createTask → CreateTaskModal | 同上 |
| GET/PUT | `/api/tasks/<task_id>` | 路径参数 | 任务详情（PUT 为别名 handler，不更新） | taskService.fetchTaskById | 同上 |
| GET | `/tasks/<task_id>` | 路径参数 | 任务详情（旧路径） | — | 同上 |
| GET | `/tasks/<task_id>/results`、`/api/tasks/<task_id>/results` | 路径参数 | 任务结果（未完成 202；含 `llm_results`） | taskService.getTaskResults → AnalysisCenter | 同上 |
| DELETE | `/api/tasks/<task_id>` | body 可带 `reason` | 删除（取消）任务 | taskService.cancelTask/deleteTask | 同上 |
| POST | `/api/tasks/cleanup` | `max_age_hours=24` | 清理已完成旧任务 | taskService.cleanupOldTasks | 同上 |
| GET | `/api/tasks/<task_id>/databases` | 路径参数 | 任务产物数据库列表 | Python task_store 类消费方 | 同上 |
| POST | `/api/tasks/batch-create` | `image_paths[]`、`priority` | 批量创建（201） | taskService.batchCreateTasks | 同上 |
| POST | `/api/tasks/batch-status` | `task_ids[]` | 批量查询状态 | taskService.batchGetTaskStatus | 同上 |
| POST | `/api/tasks/batch-cancel` | `task_ids[]`、`reason?` | 批量取消 | taskService.batchCancelTasks | 同上 |
| GET | `/api/tasks/<task_id>/progress` | 路径参数 | 任务进度快照 | useTaskPolling 轮询 | 同上 |
| GET | `/api/tasks/<task_id>/audit-log` | `limit=50`、`offset` | 任务审计日志 | taskService.getTaskAuditLog | 同上 |
| GET | `/api/tasks/statistics` | — | 系统级任务统计 | taskSlice → Dashboard | 同上 |
| PUT | `/api/tasks/<task_id>/priority` | `{"priority": "..."}` | 更新优先级（**只回显不生效**，源码显式 no-op） | taskService.updateTaskPriority | 同上 |
| OPTIONS | 16 个任务同名路径 | — | CORS 预检（TaskRoutes.cpp 注册） | 浏览器 | 同上 |

### 1.2 场景查询（SceneQueryRoutes）

| 方法 | 路径 | 关键参数 | 语义 | 典型调用方 | 详细文档 |
|------|------|---------|------|-----------|---------|
| GET | `/api/tasks/<task_id>/scene-stats` | 路径参数 | 按场景分组的文件/制品统计 | （暂无页面直调） | [TaskRoutes.md](../modules/cpp/network/routes/TaskRoutes.md) |
| GET | `/api/tasks/<task_id>/scene-artifacts` | `scene_type`*（android/windows/linux）、`limit=100`、`offset` | 场景制品分页列表 | （暂无页面直调） | 同上 |

### 1.3 案件管理（CaseCRUDRoutes，持久化 `data/cases.json`）

| 方法 | 路径 | 关键参数 | 语义 | 典型调用方 | 详细文档 |
|------|------|---------|------|-----------|---------|
| GET | `/api/cases` | — | 案件列表 | Python `/api/llm/cases` 代理（caseGroupService） | [CaseRoutes.md](../modules/cpp/network/routes/CaseRoutes.md) |
| POST | `/api/cases` | `name`、`description`、`task_ids?` | 创建案件（201） | 同上 → Cases 页 | 同上 |
| GET | `/api/cases/<case_id>` | 路径参数 | 案件详情（含任务列表） | 同上 | 同上 |
| PUT | `/api/cases/<case_id>/tasks` | `task_ids[]`* | 设置案件任务 | 同上 | 同上 |
| PUT | `/api/cases/<case_id>/status` | `status`、`cross_analysis_job_id?` | 更新案件状态 | 同上 | 同上 |
| DELETE | `/api/cases/<case_id>` | 路径参数 | 删除案件 | 同上 | 同上 |

### 1.4 时间线（TimelineRoutes，读 `_events.db`）

| 方法 | 路径 | 关键参数 | 语义 | 典型调用方 | 详细文档 |
|------|------|---------|------|-----------|---------|
| GET | `/api/forensics/timeline/comprehensive` | `task_id`*、`start_time/end_time`、`event_type`、`limit=1000`、`offset`、`cluster=false`、`bucket=60` | 综合时间线（可选聚簇） | forensicsService → Timeline 页 | [ForensicsRoutes.md](../modules/cpp/network/routes/ForensicsRoutes.md) |
| GET | `/api/forensics/timeline/full` | 同上（复用 handler） | 全量时间线 | 同上 | 同上 |
| GET | `/api/forensics/timeline/details` | `bucket_index`/`window`、`type`、`parent`/`dir`、`search` | 时间簇明细事件 | 同上 | 同上 |
| GET | `/api/forensics/timeline/distribution` | `task_id`* | 事件时间分布 | 同上 | 同上 |
| GET | `/api/forensics/timeline/statistics-by-period` | 同 distribution（复用 handler） | 按周期统计 | 同上 | 同上 |
| GET | `/api/forensics/timeline/file-activity` | `file_path`（LIKE）、`inode`（精确） | 单文件活动时间线 | 同上 | 同上 |
| GET | `/api/forensics/timeline/by-file` | 同 file-activity（复用 handler） | 按文件查询 | 同上 | 同上 |
| GET | `/api/forensics/timeline/suspicious-patterns` | `task_id`* | 可疑活动模式 | 同上 | 同上 |
| GET | `/api/forensics/timeline/user-activity` | `task_id`* | 用户活动分析 | 同上 | 同上 |
| GET | `/api/forensics/timeline/by-type` | `type`（CREATED/MODIFIED/…） | 按事件类型过滤 | 同上 | 同上 |
| GET | `/api/forensics/timeline/by-time-range` | `start`、`end`（注意参数名） | 按时间范围查询 | 同上 | 同上 |

### 1.5 事件簇分析（EventClusterRoutes；前端已切 Python 等价端点）

| 方法 | 路径 | 关键参数 | 语义 | 典型调用方 | 详细文档 |
|------|------|---------|------|-----------|---------|
| POST | `/api/forensics/timeline/clusters/analyze` | `task_id`*、`time_window`、`event_type`、`parent_directory?` | LLM 分析一个事件簇 | （保留注册；前端走 `/api/llm/analyze-event-cluster`） | [ForensicsRoutes.md](../modules/cpp/network/routes/ForensicsRoutes.md) |
| POST | `/api/forensics/timeline/clusters/batch-analyze` | `clusters[]`（空数组 400） | 批量分析 | 同上 | 同上 |
| POST | `/api/forensics/timeline/clusters/reanalyze` | 同 analyze | 重新分析 | 同上 | 同上 |
| GET | `/api/forensics/timeline/clusters/analyzed` | `task_id`* | 已分析簇列表 | forensicsService.getAnalyzedEventClusters | 同上 |

### 1.6 文件分析与提取（FileAnalysisRoutes / FileExtractionRoutes）

| 方法 | 路径 | 关键参数 | 语义 | 典型调用方 | 详细文档 |
|------|------|---------|------|-----------|---------|
| GET | `/api/forensics/files/largest` | `task_id`*、`limit=50` | 最大文件列表 | forensicsService → Files 页 | [ForensicsRoutes.md](../modules/cpp/network/routes/ForensicsRoutes.md) |
| GET | `/api/forensics/files/recent` | `task_id`*、`hours=24` | 最近 N 小时文件 | 同上 | 同上 |
| GET | `/api/forensics/files/suspicious` | `task_id`* | 可疑文件（按类别分组） | 同上 | 同上 |
| GET | `/api/forensics/files/duplicates` | `task_id`* | 重复文件（按哈希） | 同上 | 同上 |
| GET | `/api/forensics/files/extensions-analysis` | `task_id`* | 扩展名统计 | 同上 | 同上 |
| POST | `/api/forensics/extract` | `task_id`*、`mode`（all/extension/name/deleted）、`pattern`、`output_dir`（相对路径）、三限额 | 启动后台提取 job（202；就绪不足 409） | extractionService → Files 页/useFileExtraction | 同上 |
| GET | `/api/forensics/extract/<job_id>` | 路径参数 | 提取任务状态 | extractionService | 同上 |
| GET | `/api/forensics/extract/status` | `job_id`（查询参数） | 同上（查询参数形式，轮询用） | extractionService.pollExtractionStatus | 同上 |

### 1.7 DLL/共享库（DLLAnalysisRoutes，读 `_dll.db`）

| 方法 | 路径 | 关键参数 | 语义 | 典型调用方 | 详细文档 |
|------|------|---------|------|-----------|---------|
| GET | `/api/forensics/dlls` | `task_id`*、`limit` | DLL 列表 | Python dll 路由（内部） | [ForensicsRoutes.md](../modules/cpp/network/routes/ForensicsRoutes.md) |
| GET | `/api/forensics/dlls/<dll_id>` | 路径参数（inode 作 ID） | DLL 详情（PE/ELF 头、导入导出） | 同上 | 同上 |
| GET | `/api/forensics/dlls/suspicious` | `task_id`*、`limit`、`min_score` | 可疑 DLL（威胁分阈值） | 同上 | 同上 |
| GET | `/api/forensics/dlls/statistics` | `task_id`* | 统计 | 同上 | 同上 |
| GET | `/api/forensics/dlls/<dll_id>/anomalies` | 路径参数 | 单 DLL 异常 | 同上 | 同上 |
| POST | `/api/forensics/dlls/analyze` | `{"file_path"}`* | 分析单个 DLL 文件 | Python `/api/llm/analyze/dll` 内部调用 | 同上 |
| GET | `/api/forensics/dlls/health` | — | 分析器健康检查（固定 ok） | 运维 | 同上 |

### 1.8 统计（StatisticsRoutes）

| 方法 | 路径 | 关键参数 | 语义 | 典型调用方 | 详细文档 |
|------|------|---------|------|-----------|---------|
| GET | `/api/forensics/statistics/overview` | `task_id`* | 三库行数概览 | forensicsService → Statistics 页 | [ForensicsRoutes.md](../modules/cpp/network/routes/ForensicsRoutes.md) |
| GET | `/api/forensics/statistics/file-distribution` | `task_id`* | 大小/目录分布 | 同上 | 同上 |
| GET | `/api/forensics/statistics/activity-patterns` | `task_id`* | 日/周/类型活动模式 | 同上 | 同上 |
| GET | `/api/forensics/statistics/deleted-files-analysis` | `task_id`* | 已删除文件分析 | 同上 | 同上 |

### 1.9 Android 取证（AndroidForensicsRoutes，读 `_android.db`）

| 方法 | 路径 | 关键参数 | 语义 | 典型调用方 | 详细文档 |
|------|------|---------|------|-----------|---------|
| GET | `/api/forensics/android/communication-summary` | `task_id`* | 通信摘要（短信/通话） | forensicsService → Android 页 | [ForensicsRoutes.md](../modules/cpp/network/routes/ForensicsRoutes.md) |
| GET | `/api/forensics/android/app-usage` | `task_id`* | 应用使用统计 | 同上 | 同上 |
| GET | `/api/forensics/android/device-info` | `task_id`* | 设备信息 | 同上 | 同上 |
| GET | `/api/forensics/android/media-analysis` | `task_id`* | 媒体文件分析 | 同上 | 同上 |
| GET | `/api/forensics/android/miui-overview` | `task_id`* | MIUI 备份总览 | 同上 | 同上 |
| GET | `/api/forensics/android/miui-installed-apps` | `task_id`*、`limit/offset/category/status/query` | 已安装应用 | 同上 | 同上 |
| GET | `/api/forensics/android/miui-db-inventory` | `task_id`*、`kind=kv`、`reveal_sensitive=0` | 备份数据库清单 | 同上 | 同上 |
| GET | `/api/forensics/android/miui-qqnt-overview` | `task_id`* | QQNT 概览 | 同上 | 同上 |
| GET | `/api/forensics/android/miui-qqnt-artifacts` | `task_id`*、分页/过滤 | QQNT 制品 | 同上 | 同上 |
| GET | `/api/forensics/android/miui-qqnt-records` | `task_id`*、分页/过滤 | QQNT 聊天记录 | 同上 | 同上 |
| GET | `/api/forensics/android/miui-wechat-overview` | `task_id`* | 微信概览 | 同上 | 同上 |
| GET | `/api/forensics/android/miui-wechat-artifacts` | `task_id`*、`kind` 等 | 微信制品 | 同上 | 同上 |
| GET | `/api/forensics/android/miui-wechat-records` | `task_id`*、分页/过滤 | 微信聊天记录 | 同上 | 同上 |
| GET | `/api/forensics/android/llm-summary` | `task_id`* | 各制品表 AI 分析覆盖率 | 同上 | 同上 |

### 1.10 内存取证（MemoryForensicsRoutes，只读 `_memory.db`）

| 方法 | 路径 | 关键参数 | 语义 | 典型调用方 | 详细文档 |
|------|------|---------|------|-----------|---------|
| GET | `/api/forensics/memory/summary` | `task_id`* | 各表行数概览 | memoryService → Memory 页 | [ForensicsRoutes.md](../modules/cpp/network/routes/ForensicsRoutes.md) |
| GET | `/api/forensics/memory/processes` | `task_id`*、`search`（参数化 LIKE） | linux.pslist 进程（上限 1000） | 同上 | 同上 |
| GET | `/api/forensics/memory/network` | `task_id`* | linux.sockstat 网络连接 | 同上 | 同上 |
| GET | `/api/forensics/memory/bash-history` | `task_id`*、`keyword` | linux.bash 历史 | 同上 | 同上 |
| GET | `/api/forensics/memory/boot-info` | `task_id`* | linux.boottime 键值对 | 同上 | 同上 |

### 1.11 系统事件 / 导出（SystemEventRoutes / ExportRoutes）

| 方法 | 路径 | 关键参数 | 语义 | 典型调用方 | 详细文档 |
|------|------|---------|------|-----------|---------|
| GET | `/api/forensics/system/events` | `task_id`*、`start_time/end_time`、`limit/offset` | 系统叙事事件 | （暂无页面直调） | [ForensicsRoutes.md](../modules/cpp/network/routes/ForensicsRoutes.md) |
| GET | `/api/forensics/system/summary` | `task_id`* | 系统事件摘要 | 同上 | 同上 |
| GET | `/api/forensics/export/toon` | `task_id`*、`fields`、`filter`（过 `is_safe_filter_clause`） | TOON 文本导出（`text/toon` 附件） | systemService.exportToon | 同上 |
| GET | `/api/forensics/export/events/json` | `task_id`*、`query`（只读 SELECT） | 事件 JSON 导出 | （暂无页面直调） | 同上 |
| GET | `/api/forensics/export/events/csv` | `task_id`*、`query` | 事件 CSV 导出 | 同上 | 同上 |
| GET | `/api/forensics/export/events/visualization` | `task_id`* | 可视化用事件导出 | 同上 | 同上 |

### 1.12 全文搜索（SearchRoutes，Xapian）

| 方法 | 路径 | 关键参数 | 语义 | 典型调用方 | 详细文档 |
|------|------|---------|------|-----------|---------|
| GET | `/api/search/fulltext` | `q`*、`index`*（越 `FTS_ALLOWED_ROOT` 拒绝）、`limit=50`、`offset` | 全文搜索 | searchService → Search 页 | [SearchRoutes.md](../modules/cpp/network/routes/SearchRoutes.md) |
| POST | `/api/search/index` | `source_path`*、`index_path`*、`recursive=true` | 建立索引 | searchService.createSearchIndex | 同上 |

### 1.13 文件过滤（FilterRoutes，唯一 ApiResponse 封装路由组）

| 方法 | 路径 | 关键参数 | 语义 | 典型调用方 | 详细文档 |
|------|------|---------|------|-----------|---------|
| GET | `/api/filter/profiles` | — | 过滤配置列表 | filterService → FileFilters 页 | [FilterRoutes.md](../modules/cpp/network/routes/FilterRoutes.md) |
| GET | `/api/filter/profiles/<name>` | 路径参数 | 配置详情 | 同上 | 同上 |
| POST | `/api/filter/profiles` | `name`*、`include/exclude`、`combine_mode` | 创建/更新（内置配置 403 不可覆盖） | 同上 | 同上 |
| DELETE | `/api/filter/profiles/<name>` | 路径参数 | 删除自定义配置（内置 403） | 同上 | 同上 |
| POST | `/api/filter/apply` | `task_id`*、`profile_name`* | 应用到任务（生成 `_filtered.db`） | 同上 | 同上 |

### 1.14 系统与文档（SystemRoutes：Health + Info + Docs）

| 方法 | 路径 | 关键参数 | 语义 | 典型调用方 | 详细文档 |
|------|------|---------|------|-----------|---------|
| GET | `/api/system/health` | — | 系统健康（任务统计+依赖） | systemService → Dashboard | [SystemRoutes.md](../modules/cpp/network/routes/SystemRoutes.md) |
| GET | `/api/health` | — | 同上（别名） | 运维脚本 | 同上 |
| GET | `/api/health/live` | — | 存活探针 | run.sh 健康门 | 同上 |
| GET | `/api/health/ready` | — | 就绪探针（未就绪 503） | 部署编排 | 同上 |
| GET | `/api/health/dependencies` | — | 依赖服务状态明细 | 运维 | 同上 |
| GET | `/api/system/info` | — | 服务/构建信息 | systemService → Settings | 同上 |
| GET | `/api/system/databases` | `task_id` | 任务数据库文件 | 同上 | 同上 |
| GET | `/api/system/database-schema/<db_type>` | 路径参数 | 指定库的表结构 | 同上 | 同上 |
| GET | `/api/system/logs` | `lines` | 系统日志 | systemService → Terminal | 同上 |
| POST | `/api/export/<task_id>` | body `{format}` 可选 | 导出任务数据 | systemService.exportTaskData → Settings | 同上 |
| GET | `/api/docs` | — | Swagger UI | 浏览器 | 同上 |
| GET | `/api/docs/endpoints` | — | 全部端点清单（JSON） | systemService.getEndpoints → Settings | 同上 |
| GET | `/api/docs/database-schema` | — | 全库模式文档 | 同上 | 同上 |
| GET | `/api/docs/openapi.json` | — | OpenAPI 规范 | 工具链 | 同上 |
| GET | `/`、`/<path>` | — | 托管 `web/dist` 前端 SPA | 浏览器 | [HTTPServer.md](../modules/cpp/network/HTTPServer.md) |

---

## 二、Python httpserver（:8090，FastAPI）

### 2.1 健康与系统（health.py / system.py）

| 方法 | 路径 | 关键参数 | 语义 | 典型调用方 | 详细文档 |
|------|------|---------|------|-----------|---------|
| GET | `/health` | — | 基础健康 | systemService.getPythonHealth → Dashboard | [Health.md](../modules/python/httpserver/routes/Health.md) |
| GET | `/health/live` | — | 存活探针 | 运维 | 同上 |
| GET | `/health/ready` | — | 就绪（C++ 硬依赖；Neo4j/LLM/Redis 可选） | 部署编排 | 同上 |
| GET | `/api/system/redis/status` | — | Redis 状态（URL 脱敏） | systemService.getRedisStatus → Dashboard | 同上 |
| GET | `/api/system/info` | — | 服务信息（config 摘要） | 同上 | 同上 |
| GET | `/api/system/logs` | `lines` | 读取服务日志 | systemService → Terminal | [System.md](../modules/python/httpserver/routes/System.md) |
| GET | `/api/system/logs/{service}` | 路径参数 | 指定服务日志（找不到 404） | 同上 | 同上 |
| GET | `/api/system/logs-stream/{service}` | 路径参数 | SSE 日志流 | TerminalOutput | 同上 |

### 2.2 Graphiti 知识图谱（/api/graphiti）

| 方法 | 路径 | 关键参数 | 语义 | 典型调用方 | 详细文档 |
|------|------|---------|------|-----------|---------|
| POST | `/api/graphiti/ingest` | `task_id`*、`mode=full`、`batch_size=50`、`max_episodes=100` | 启动图谱摄取 job | graphitiService → KnowledgeGraph 页；C++ fire-and-forget 触发 | [Graphiti.md](../modules/python/httpserver/routes/Graphiti.md) |
| POST | `/api/graphiti/ingest/file` | `file_id`*、`task_id`*、`update_analysis` | 单文件摄取 | 同上 | 同上 |
| POST | `/api/graphiti/ingest/events` | `task_id`、`events[]` | 事件同步 | 同上 | 同上 |
| GET | `/api/graphiti/jobs/{job_id}` | 路径参数 | 摄取 job 状态 | graphitiService.pollGraphitiJob | 同上 |
| DELETE | `/api/graphiti/jobs/{job_id}` | 路径参数 | 取消 job | 同上 | 同上 |
| GET | `/api/graphiti/jobs` | — | job 列表 | 同上 | 同上 |
| POST | `/api/graphiti/migrate/task/{task_id}` | 路径参数 | 任务数据迁移到 Graphiti 结构 | （暂无页面直调） | 同上 |
| POST | `/api/graphiti/migrate/deduplicate` | — | 去重 | 同上 | 同上 |
| GET | `/api/graphiti/migrate/status/{task_id}` | 路径参数 | 迁移状态 | 同上 | 同上 |
| POST | `/api/graphiti/migrate/cleanup/{task_id}` | 路径参数 | 清理迁移产物 | 同上 | 同上 |
| POST | `/api/graphiti/search` | `query`*、`task_id`*、`limit=100` | 自然语言图搜索 | graphitiService | 同上 |
| GET | `/api/graphiti/entities` | `task_id`*、`entity_type`、分页 | 实体列表 | 同上 | 同上 |
| GET | `/api/graphiti/relationships` | `task_id`*、`relationship_type`、分页 | 关系列表 | 同上 | 同上 |
| GET | `/api/graphiti/status` | — | 服务状态（Neo4j 连通性） | 同上 | 同上 |
| GET | `/api/graphiti/tasks` | — | 已建图任务列表 | 同上 | 同上 |
| DELETE | `/api/graphiti/tasks/{task_id}` | 路径参数 | 删除任务图谱数据 | 同上 | 同上 |
| GET | `/api/graphiti/graph` | `task_id` | 可视化图数据 | graphitiService → KnowledgeGraph 页 | 同上 |

### 2.3 LLM 分析（/api/llm + dll）

| 方法 | 路径 | 关键参数 | 语义 | 典型调用方 | 详细文档 |
|------|------|---------|------|-----------|---------|
| POST | `/api/llm/analyze` | `content`/`file_path` 二选一、`model_type=text`、`max_tokens` 等 | 分析文本或文件（可持久化到 `_files.db`） | llmService.analyzeContent → Files 页 | [LLM.md](../modules/python/httpserver/routes/LLM.md) |
| POST | `/api/llm/analyze-event-cluster` | `task_id`*、`group_descriptor{...}`（兼容旧式 time_window） | LLM 分析事件簇 | forensicsService.analyzeEventCluster → Timeline/AnalysisCenter | 同上 |
| POST | `/api/llm/analyze/file` | multipart + `model_type`、`prompt` | 上传文件分析 | llmService.analyzeFile | 同上 |
| POST | `/api/llm/batch` | `task_id`*、`file_types/file_paths`、`limit=100` | 批量分析（后台 job） | llmService.startBatchAnalysis | 同上 |
| GET | `/api/llm/batch/{job_id}` | 路径参数 | 批量进度 | llmService.pollBatchStatus | 同上 |
| GET | `/api/llm/models` | — | 可用模型列表 | llmService.getModels → Settings | 同上 |
| POST | `/api/llm/toggle-relevance` | `task_id/file_path/is_relevant` 全必填 | 切换文件相关性标记 | llmService.toggleFileRelevance → AnalysisCenter | 同上 |
| POST | `/api/llm/toggle-cluster-relevance` | 同构 | 切换事件簇相关性标记 | 同上 | 同上 |
| GET | `/api/llm/status` | — | LLM 服务状态 | llmService.getLLMStatus → Dashboard | 同上 |
| POST | `/api/llm/analyze/dll` | `file_path`*、`task_id?` | DLL 安全分析（先调 C++ 解析再 LLM） | llmService.analyzeDLL → Files 页 | 同上 |

### 2.4 案件分析与情报报告（/api/llm）

| 方法 | 路径 | 关键参数 | 语义 | 典型调用方 | 详细文档 |
|------|------|---------|------|-----------|---------|
| POST | `/api/llm/case-description` | `task_id`*、`case_description` | 保存案情描述（转发 C++ tasks.json） | caseAnalysisService → AnalysisCenter | [CaseAnalysis.md](../modules/python/httpserver/routes/CaseAnalysis.md) |
| POST | `/api/llm/case-analysis` | — | **已退役：固定 410**（见第五节） | — | 同上 |
| POST | `/api/llm/reanalyze-files` | `task_id`*、`file_paths[]`、`user_hint`* | 重跑文件分析 job | caseAnalysisService | 同上 |
| GET | `/api/llm/case-analysis/{job_id}` | 路径参数 | 分析 job 状态（轮询） | caseAnalysisService | 同上 |
| GET | `/api/llm/case-report/{task_id}` | 路径参数 | 任务级案件报告 | caseAnalysisService | 同上 |
| GET | `/api/llm/case-report-by-case/{case_id}` | 路径参数 | 案件级报告 | caseGroupService（multi 完成后读） | 同上 |
| GET | `/api/llm/filtered-files/{task_id}` | 路径参数 | AI 过滤后文件列表 | caseAnalysisService | 同上 |
| POST | `/api/llm/windows-analysis` | `task_id`*、`max_filter_files=200` | Windows 场景分析 | （暂无页面直调） | 同上 |
| GET | `/api/llm/windows-report/{task_id}` | 路径参数 | Windows 报告 | 同上 | 同上 |
| GET | `/api/llm/windows-export/{task_id}/toon` | 路径参数 | Windows 报告 TOON 导出 | 同上 | 同上 |
| GET | `/api/llm/intelligence-report/{task_id}` | 路径参数 | 情报报告正文（分章节） | intelligenceReportService → CaseIntelligence | 同上 |
| GET | `/api/llm/intelligence-report/{task_id}/records` | 分页 | 报告记录 | 同上 | 同上 |
| GET | `/api/llm/intelligence-report/{task_id}/search` | `q` | 报告内检索 | 同上 | 同上 |
| GET/PUT | `/api/llm/intelligence-report/{task_id}/metadata` | 路径参数 | 读/更新报告元数据 | 同上 | 同上 |

### 2.5 多镜像/案件聚合（multi_analysis.py，代理/编排 C++）

| 方法 | 路径 | 关键参数 | 语义 | 典型调用方 | 详细文档 |
|------|------|---------|------|-----------|---------|
| POST | `/api/llm/cases` | `name`*、`description`、`task_ids?` | 创建案件（201，转发 C++） | caseGroupService → Cases 页 | [CaseAnalysis.md](../modules/python/httpserver/routes/CaseAnalysis.md) |
| GET | `/api/llm/cases` | — | 案件列表 | 同上 | 同上 |
| GET/DELETE | `/api/llm/cases/{case_id}` | 路径参数 | 案件详情/删除 | 同上 | 同上 |
| POST | `/api/llm/cases/{case_id}/tasks` | `task_ids[]`* | 添加任务 | 同上 | 同上 |
| POST | `/api/llm/cases/{case_id}/associate-tasks` | `task_ids[]`（空 400） | 关联**已完成**分析的任务 | 同上 | 同上 |
| POST | `/api/llm/multi-image-analysis` | `case_id/task_ids/files_db_paths/case_description` 四必填 | 多镜像关联分析 job | caseGroupService.startMultiAnalysis | 同上 |
| GET | `/api/llm/multi-image-analysis/{job_id}` | 路径参数 | 分析 job 状态 | caseGroupService.pollMultiAnalysis | 同上 |
| POST | `/api/llm/cases/smart-create` | `name`*、`description`、`auto_associate/auto_analyze=true` | 智能建案（201） | caseGroupService | 同上 |
| POST | `/api/llm/cases/{case_id}/tasks/incremental` | `new_task_ids`、`auto_analyze=true` | 增量加任务 | 同上 | 同上 |
| GET | `/api/llm/cases/{case_id}/analysis-status` | 路径参数 | 聚合分析状态 | 同上 | 同上 |
| POST | `/api/llm/cases/{case_id}/incremental-analysis` | `force_reanalyze=false` | 触发增量分析 | 同上 | 同上 |

### 2.6 报告（/api/reports）

| 方法 | 路径 | 关键参数 | 语义 | 典型调用方 | 详细文档 |
|------|------|---------|------|-----------|---------|
| POST | `/api/reports` | `scope_type`*、`scope_id`*（不支持 501/不存在 404） | 创建报告版本（202） | reportService.createVersion → ForensicReportPage | [ForensicReports.md](../modules/python/httpserver/routes/ForensicReports.md) |
| GET | `/api/reports` | `scope_type`、`scope_id` | 按范围列报告版本 | 同上 | 同上 |
| GET | `/api/reports/{report_id}/status` | 路径参数 | 报告状态 | 同上 | 同上 |
| GET | `/api/reports/{report_id}/manifest` | 路径参数 | 报告清单 | 同上 | 同上 |
| GET | `/api/reports/{report_id}/categories/{category_id}/pages/{page}` | 路径参数 | 分页读取章节内容 | reportDataSource（HttpReportDataSource） | 同上 |
| GET | `/api/reports/{report_id}/search` | `q`、分页 | 报告内检索 | 同上 | 同上 |
| GET/POST/PUT | `/api/reports/evidence` | `task_id/evidence_key/report_status/added_by` 必填 | 证据列表/登记（重复 409）/更新 | investigationService（list/add/updateReportEvidence） | 同上 |
| POST | `/api/reports/generate` | `task_id`*、`requested_by`*（无证据 409） | 冻结式报告生成（202；输入全服务端组装） | reportGenerationService → GenerateReportPanel | 同上 |
| GET | `/api/reports/generations/{generation_id}` | `task_id` 查询参数 | 生成状态（exact id 轮询） | useReportGenerationPolling | 同上 |
| GET | `/api/reports/narrative/versions/{report_id}` | 路径参数 | 叙事版本记录 | 同上 | 同上 |

### 2.7 调查 API（/api/investigation，规范扁平命名空间）

| 方法 | 路径 | 关键参数 | 语义 | 典型调用方 | 详细文档 |
|------|------|---------|------|-----------|---------|
| POST | `/api/investigation/snapshots` | `task_id/evidence_key`（extra=forbid） | 捕获不可变证据快照（200） | investigationService（冻结契约组） | [Investigation.md](../modules/python/httpserver/routes/Investigation.md) |
| POST | `/api/investigation/analyses` | `task_id/evidence_key`*、`analyst_note?` 等 | 启动二级分析（202） | 同上 | 同上 |
| POST | `/api/investigation/analyses/{analysis_id}/review` | `task_id/decision/reviewer`*（冲突 409） | 审阅分析结果 | 同上 | 同上 |
| GET | `/api/investigation/analyses/{analysis_id}` | 路径参数 | 分析详情 | 同上 | 同上 |
| GET | `/api/investigation/analyses` | `evidence_key`、`status` 过滤 | 分析列表 | 同上 | 同上 |
| GET | `/api/investigation/analyses/{analysis_id}/claims` | 路径参数 | 分析声明（claims） | 同上 | 同上 |
| POST | `/api/investigation/events` | `task_id/title/created_by`*（201） | 创建调查事件 | 同上 | 同上 |
| GET | `/api/investigation/events` | `task_id`、`limit` | 事件列表 | 同上 | 同上 |
| GET | `/api/investigation/events/{event_id}` | 路径参数 | 事件详情 | 同上 | 同上 |
| GET | `/api/investigation/events/{event_id}/versions` | 路径参数 | 事件版本历史 | 同上 | 同上 |
| POST/GET | `/api/investigation/events/{event_id}/evidence` | `task_id/evidence_key/linked_by`（重复 409） | 挂接/查询事件证据 | 同上 | 同上 |
| POST | `/api/investigation/events/{event_id}/refresh` | 路径参数 | 触发事件刷新（201） | 同上 | 同上 |
| GET | `/api/investigation/events/{event_id}/refreshes` | 路径参数 | 刷新历史 | 同上 | 同上 |
| GET | `/api/investigation/evidence` | `task_id` | 证据列表 | 同上 | 同上 |
| GET | `/api/investigation/evidence/snapshot` | `task_id/evidence_key` | 证据快照 | 同上 | 同上 |
| GET | `/api/investigation/graph` | `task_id`、`max_base_nodes=200` | 调查图（overlay + Base KG） | 同上 | 同上 |

### 2.8 调查工作台（/api/investigation/workbench，远程形态门面）

前缀 `/api/investigation/workbench/{task_id}`，下表省略前缀；标注 **409** 者为"已注册、按契约固定拒绝"。

| 方法 | 路径（前缀内） | 语义 | 典型调用方 | 详细文档 |
|------|------|------|-----------|---------|
| GET | `/` | 工作台总览 | investigationService（workbench 组）→ /investigation 页 | [Investigation.md](../modules/python/httpserver/routes/Investigation.md) |
| POST | `/bootstrap` | 引导初始化（`mode=cluster_seed`） | bootstrapInvestigation | 同上 |
| GET | `/events`、`/events/{event_id}` | 事件列表/详情 | 同上 | 同上 |
| POST | `/events/{event_id}/review` | **固定 409**（review 不在本地契约） | — | 同上 |
| GET | `/events/{event_id}/evidence` | 事件证据 | 同上 | 同上 |
| POST | `/events/{event_id}/evidence/link` | 挂接证据 | 同上 | 同上 |
| GET | `/evidence/detail` | 证据详情 | 同上 | 同上 |
| POST | `/evidence/analyze` | 触发证据分析 job | 同上 | 同上 |
| GET | `/analysis-jobs/{job_id}` | 分析 job 状态 | pollAnalysisJob | 同上 |
| GET | `/evidence/analysis` | 证据分析结果 | 同上 | 同上 |
| POST | `/analysis/{analysis_id}/accept`、`/reject` | 采纳/驳回分析 | 同上 | 同上 |
| POST | `/events/{event_id}/refresh` | 刷新事件 | 同上 | 同上 |
| GET | `/events/{event_id}/versions` | 版本历史 | 同上 | 同上 |
| POST | `/events/{event_id}/versions/{version_id}/accept` | 采纳版本 | 同上 | 同上 |
| POST | `/events/{event_id}/versions/{version_id}/reject` | **固定 409** | — | 同上 |
| GET | `/events/{event_id}/versions/{version_id}/claims` | 版本声明 | 同上 | 同上 |
| GET | `/events/{event_id}/claims/effective` | 生效声明 | 同上 | 同上 |
| POST | `/events/{event_id}/versions/{version_id}/claims/{claim_id}/accept` | 采纳声明 | 同上 | 同上 |
| POST | `.../claims/{claim_id}/reject` | **固定 409** | — | 同上 |
| GET | `/claims/{claim_id}` | 声明溯源 | 同上 | 同上 |
| POST | `/notes` | **固定 409**（等规范 schema 决策） | — | 同上 |
| GET | `/notes` | 笔记只读 | 同上 | 同上 |
| PUT/GET/POST | `/report-evidence`（+ `/remove`） | 管理报告证据集 | 同上 | 同上 |
| GET | `/graph/local` | 本地调查图 | 同上 | 同上 |
| GET | `/final-reports` | 终版报告列表 | 同上 | 同上 |
| GET | `/final-reports/{report_id}`（+`/markdown`、`/html`、`/print`、`/publication`） | 终版报告各渲染形式 | FinalReportViewer | 同上 |
| POST | `/final-reports/{report_id}/publish` | 发布终版报告 | 同上 | 同上 |

### 2.9 数据库访问 / Office / Markitdown（/api/db、/api/office、/api/markitdown）

| 方法 | 路径 | 关键参数 | 语义 | 典型调用方 | 详细文档 |
|------|------|---------|------|-----------|---------|
| GET | `/api/db/tasks` | `status`、`page=1`、`page_size≤100` | 任务列表（含库位置，代理 C++） | 调试/集成 | [Database.md](../modules/python/httpserver/routes/Database.md) |
| GET | `/api/db/tasks/{task_id}` | 路径参数 | 任务详情 | 同上 | 同上 |
| GET | `/api/db/tasks/{task_id}/databases` | 路径参数 | 任务数据库清单 | 同上 | 同上 |
| GET | `/api/db/tasks/{task_id}/files` | 分页 | 文件记录（读 `_files.db`） | 同上 | 同上 |
| GET | `/api/db/tasks/{task_id}/events` | 分页 | 事件记录（读 `_events.db`） | 同上 | 同上 |
| GET | `/api/db/tasks/{task_id}/export/toon` | 路径参数 | TOON 导出 | 同上 | 同上 |
| GET | `/api/db/tasks/{task_id}/export/json` | 路径参数 | JSON 导出 | 同上 | 同上 |
| POST | `/api/office/parse` | `file_path`*、`task_id`/`workspace_root` 锚 | 解析 Office 文档为 Markdown | officeService → Files 页 Office Tab | [Markitdown.md](../modules/python/httpserver/routes/Markitdown.md) |
| GET | `/api/office/supported-types` | — | 支持类型列表 | officeService.getSupportedFormats | 同上 |
| POST | `/api/markitdown/convert` | `file_path`*、锚定参数 | 单文件转 Markdown | C++ MarkitdownProxy / 集成方 | 同上 |
| GET | `/api/markitdown/status` | — | 服务状态 | 同上 | 同上 |
| POST | `/api/markitdown/convert-one` | `input_root/input_file/output_root` | root 下转换单文件 | 同上 | 同上 |
| POST | `/api/markitdown/batch-convert` | `input_dir`*、`output_dir`* | 目录批量转换（Semaphore(4)） | 同上 | 同上 |

### 2.10 微信关系图谱 / 事件关联 / OSS AI

| 方法 | 路径 | 关键参数 | 语义 | 典型调用方 | 详细文档 |
|------|------|---------|------|-----------|---------|
| GET | `/api/wechat/chat` | `task_id`*、`user1`、`user2`、分页 | 双人会话记录 | wechatService → useWeChatGraph | [WechatGraph.md](../modules/python/httpserver/routes/WechatGraph.md) |
| GET | `/api/wechat/chat/group` | `task_id`*、`chatroom`、分页 | 群聊记录 | 同上 | 同上 |
| GET | `/api/wechat/owner` | `task_id`* | 账号所有者信息 | 同上 | 同上 |
| GET | `/api/wechat/contacts` | `task_id`*、`include_chatrooms=false` | 联系人列表 | 同上 | 同上 |
| GET | `/api/wechat/graph` | `task_id`*、`include_metrics=true` | 关系图谱（PageRank/社区） | 同上 | 同上 |
| GET | `/api/wechat/graph/timeline` | `task_id`*、`interval=month`（非法 400） | 通信时间线 | 同上 | 同上 |
| GET | `/api/wechat/graph/community` | `task_id`* | 社区发现（Louvain） | 同上 | 同上 |
| GET | `/api/wechat/graph/person/{username}` | `task_id`* | 个人 ego 网络 | 同上 | 同上 |
| POST | `/api/wechat/graph/invalidate` | `task_id`*（查询参数） | 清除图谱缓存 | 同上 | 同上 |
| POST | `/api/associations/cluster-files` | `task_id/time_window/event_type`*、`limit=100` | 事件簇 → 关联文件 | associationService → AnalysisCenter 双抽屉 | [Associations.md](../modules/python/httpserver/routes/Associations.md) |
| POST | `/api/associations/file-clusters` | `task_id/file_path`*、`limit=100` | 文件 → 关联事件簇 | 同上 | 同上 |
| POST | `/api/forensics/oss/ai/filter` | `task_id/oss_db_path/case_description`*、`max_objects=200` | LLM 过滤 OSS 对象 | 集成方（前端 ossService 指向 C++ 死路由，见第五节） | [OssAnalysis.md](../modules/python/httpserver/routes/OssAnalysis.md) |
| POST | `/api/forensics/oss/ai/analyze` | `task_id/object_ids/oss_db_path/download_dir`*、`model_type=text` | LLM 分析已过滤对象 | 同上 | 同上 |

另有 FastAPI 内建交互文档：`GET /docs`（Swagger）、`/redoc`、`/openapi.json`。

---

## 三、分布式 C/S 服务（:8091，JWT）

用户端点以用户 JWT 调用；标注"客户端"者以 client credential JWT 调用，二者严格互斥（payload `type` 不符即 401）。

| 方法 | 路径 | 关键参数 | 语义 | 典型调用方 | 详细文档 |
|------|------|---------|------|-----------|---------|
| GET | `/health` | — | 存活 | 运维 | [Python_REST_API §16](../api_reference/Python_REST_API.md) |
| GET | `/health/ready` | — | 就绪（数据库不可用 503） | run.sh 健康门 | 同上 |
| GET | `/` | — | 服务发现信息 | 浏览器 | 同上 |
| POST | `/api/auth/login` | form-encoded `username/password` | OAuth2 密码流换 JWT（401 带 WWW-Authenticate） | csAuthService.csLogin → /distributed 页 | 同上 |
| POST | `/api/auth/refresh` | 当前 token | 刷新 token | csAuthService.csRefresh | 同上 |
| GET | `/api/auth/me` | Bearer | 当前用户信息 | csAuthService.csMe | 同上 |
| POST | `/api/organizations` | `name`* 等 | 创建组织 | 运维脚本 | 同上 |
| GET | `/api/organizations` | — | 组织列表 | 同上 | 同上 |
| GET | `/api/organizations/{org_id}` | 路径参数 | 组织详情 | 同上 | 同上 |
| POST | `/api/organizations/{org_id}/registration-tokens` | `max_clients`、`expires_in_hours` | 签发客户端注册令牌 | 运维 | 同上 |
| GET | `/api/organizations/{org_id}/registration-tokens` | 路径参数 | 令牌列表 | 运维 | 同上 |
| DELETE | `/api/organizations/registration-tokens/{token_id}` | 路径参数 | 吊销令牌 | 运维 | 同上 |
| POST | `/api/clients/register` | `registration_token`*、`hostname`*、`capabilities` | 客户端注册（拿 client credential） | tracelens_agent | 同上 |
| GET | `/api/clients` | — | 客户端列表 | csClientService.listClients → /distributed | 同上 |
| GET | `/api/clients/{client_id}` | 路径参数 | 客户端详情 | csClientService.getClient | 同上 |
| DELETE | `/api/clients/{client_id}` | 路径参数 | 删除客户端 | 运维 | 同上 |
| POST | `/api/clients/{client_id}/index-images` | 镜像元数据数组 | 登记镜像索引（**只元数据**） | tracelens_agent | 同上 |
| GET | `/api/clients/{client_id}/images` | 路径参数 | 镜像列表 | 建任务前选择 | 同上 |
| POST | `/api/commands` | `client_id`*、`command_type`（analyze_disk/extract_file/health_check）、`ttl_hours=24` | 用户下发命令（跨组织 403） | 运维/上层系统 | 同上 |
| GET | `/api/commands/poll` | — | **客户端**拉取待执行命令（刷新 last_poll） | tracelens_agent 轮询 | 同上 |
| POST | `/api/commands/{command_id}/status` | `command_id/status/progress/message` | **客户端**上报状态（传播到任务） | tracelens_agent status_reporter | 同上 |
| GET | `/api/commands/{command_id}` | 路径参数 | 命令详情 | 运维 | 同上 |
| GET | `/api/commands/client/{client_id}` | `status_filter` | 按客户端查历史 | 运维 | 同上 |
| POST | `/api/commands/expire` | — | 过期滞留命令（仅 super_admin） | 运维 | 同上 |
| POST | `/api/tasks` | `client_id/disk_image_id/task_name/analysis_type`* 等 | 创建分析任务 | csTaskService → /distributed | 同上 |
| GET | `/api/tasks` | — | 任务列表 | csTaskService | 同上 |
| GET | `/api/tasks/{task_id}` | 路径参数 | 任务详情 | csTaskService | 同上 |
| POST | `/api/tasks/{task_id}/cancel` | 路径参数 | 取消任务 | csTaskService | 同上 |
| POST | `/api/tasks/{task_id}/results` | `artifacts[]`（`result_type/file_path/storage_location/result_metadata`） | **客户端**批量上传产物引用（字节不上传） | tracelens_agent result_uploader | 同上 |
| GET | `/api/tasks/{task_id}/results` | 路径参数 | 任务结果列表（用户） | 上层系统 | 同上 |
| GET | `/api/tasks/{task_id}/llm-analyses` | 路径参数 | 任务 LLM 分析结果 | 上层系统 | 同上 |

---

## 四、跨服务调用关系速记

- 浏览器 → C++ `:8080`：绝大多数 `/api/*` + 前端静态资源；→ Python `:8090`：`/api/llm|graphiti|reports|office|db|wechat|investigation`；→ C/S `:8091`：`/csapi`（dev 代理重写去前缀）。见 [Deployment.md](../architecture/Deployment.md)。
- C++ → Python：任务收尾 `LLMPythonProxy.async_ingest` 触发 `/api/graphiti/ingest`（fire-and-forget）；文档转换走 `MarkitdownProxy`。
- Python → C++：`CppBackendService` 回查任务/时间线/文件（硬依赖，C++ 不可用则 ready=false）。
- 前端服务层（`web/src/services/`）是页面与后端唯一边界，逐组映射见两篇 API 参考的附录表。

## 五、未注册 / 死端点（调用必失败或按契约拒绝）

| 端点 | 状态 | 原因与详细文档 |
|------|------|--------------|
| C++ `/api/forensics/oss/analyze`、`/objects`、`/logs`、`/stats/*` 等 OSS 族 | **运行时 404** | `OSSRoutes*.cpp` 等编译但从未被聚合器注册；前端 `/oss` 页因此不可用。见 [OSSRoutes.md](../modules/cpp/network/routes/OSSRoutes.md) 与 [CPP_REST_API.md §7](../api_reference/CPP_REST_API.md)。OSS AI 能力在 Python 侧（§2.10） |
| Python `/api/system/logs/stream` | **运行时 404** | `system_logs.py` 的 router 未在 main.py 注册（死代码）；注册版是 `/api/system/logs-stream/{service}`。见 [Python_REST_API.md §15](../api_reference/Python_REST_API.md) |
| Python `POST /api/llm/case-analysis` | **固定 410** | 旧 Chain B 案件分析已软退役，现行链路是 R2 报告生成（`/api/reports/generate`）。见 [d3b-legacy-chain-b-soft-retirement.md](../hardening/d3b-legacy-chain-b-soft-retirement.md) |
| Workbench `review` / 版本 reject / 声明 reject / `POST notes` | **固定 409** | 显式契约边界（拒绝语义不在本地规范内），非故障。见 [Python_REST_API.md §8](../api_reference/Python_REST_API.md) |
| Python `POST /api/db/query` | **不存在** | 旧文档写过的自定义 SQL 端点在代码中不存在；`/api/db/*` 全部只读。见 [Python_REST_API.md §9](../api_reference/Python_REST_API.md) |
| C++ `PUT /api/tasks/<id>/priority` | **注册但 no-op** | 只回显不实现（源码注释显式声明）。见 [CPP_REST_API.md §1](../api_reference/CPP_REST_API.md) |

---

## 相关文档

- [CPP_REST_API.md](../api_reference/CPP_REST_API.md) / [Python_REST_API.md](../api_reference/Python_REST_API.md) —— 字段级语义与示例
- [RouteReference.md](../modules/cpp/network/routes/RouteReference.md) —— C++ 路由源文件索引
- [ServiceContracts.md](ServiceContracts.md) —— 服务间契约与已知偏差
- [web/Services.md](../modules/web/Services.md) —— 前端调用方逐服务映射

---

## 附录 A：超时与错误形态速查

| 服务 | 请求超时 | 常见错误形态 | 说明 |
|------|---------|-------------|------|
| C++ :8080 | 无统一超时（Crow 默认）；同步端点（建索引）可能长阻塞 | `{"error":"..."}` + 4xx/5xx；部分带 error_code | ApiResponse 封装仅 FilterRoutes |
| Python :8090 | httpx 60s（前端 pythonApi）；LLM 120s（LLM_TIMEOUT_SECONDS） | 固定文案 500 / 422 校验详情 / 202+轮询（生成类） | 降级态 501（Graphiti disabled） |
| C/S :8091 | JWT 30 天（client token）；DB 池 5s | 401（token 缺/过期）/403（org 越权） | /health/ready 503=DB 不可用（启动快照） |

## 附录 B：端点别名与易混对照

| 易混项 | 实际情况 |
|--------|---------|
| /health vs /api/health vs /api/system/health（C++） | 三口径并存；run.sh 硬检查用 /api/system/health（SystemRoutes 文档） |
| /tasks vs /api/tasks（C++） | 前者是简化接口（创建/列表/详情/结果四件），后者全功能 |
| /api/graphiti/ingest-file | 实为 `/api/graphiti/ingest/file`（斜杠——契约目录勘误） |
| 状态字面量 | API 小写（pending）/tasks.json 大写（PENDING）；Graphiti job 大写（COMPLETED）——三处三样，见 Glossary 对照 |
| /api/llm/case-analysis | 410 退役；现行是 /api/llm/cases + /api/reports |
| /api/markitdown（dev 前端） | 无 vite 专属前缀，dev 下会被 /api 兜底打到 C++——生产无碍（同源走 C++ 转发? 不，生产 markitdown 由 C++ MarkitdownProxy 服务端调用） |

**最后更新**: 2026-08-24（扩充：超时与别名附录）
