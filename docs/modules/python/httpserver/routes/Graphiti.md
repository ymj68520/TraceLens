# Graphiti 路由（python_service/httpserver/routes/graphiti.py + graphiti_endpoints/，前缀 /api/graphiti）

> **一句话**：知识图谱的完整 HTTP 表面——摄取（同步排队）、后台作业跟踪、图结构迁移、混合检索与可视化数据，全部按 task_id 隔离在各自的图命名空间里。

## 这组路由承担什么职责

模块本体是聚合器（graphiti.py:49-54 把 5 个子 router 串成一个），端点按领域拆在 `graphiti_endpoints/` 下：`_ingest.py`（摄取）、`_jobs.py`（作业）、`_migrate.py`（迁移）、`_query.py`（查询）、`_admin.py`（状态/任务图管理）。Pydantic 模型集中在 `graphiti_models.py`。路由层做三件事：校验 task 存在（经 C++）、在"新作业系统 vs 旧服务"之间选路径、把服务层结果映射为响应模型。

## 典型调用方

- 前端 `/knowledge-graph` 页（web/src/services/graphitiService.js：ingest、search、entities、relationships、status、tasks、jobs 全套）。
- C++ `LLMPythonProxy`（src/network/HTTPServer/LLMPythonProxy.cpp:63,104,138）在流水线节点回调 `POST /api/graphiti/ingest*`——这是本目录最重要的**服务间**调用方。
- 迁移/清理端点主要由运维或维护脚本使用。

## 端点分组语义

（完整契约见 docs/api_reference/Python_REST_API.md）

- **摄取**：`POST /ingest`（_ingest.py:27，mode 取 full / files_only / events_only / analyzed_only，docstring :40-48 逐一说明语义；`max_episodes` 可限流）；`POST /ingest/file`（:88，单文件更新）；`POST /ingest/events`（:142，把时间线事件同步到 File 实体）。
- **作业**：`GET /jobs/{id}`（_jobs.py:24）、`DELETE /jobs/{id}`（:72，已完成/失败的作业不可取消）、`GET /jobs`（:118，按 task/status 过滤）。
- **迁移**：`POST /migrate/task/{id}`、`POST /migrate/deduplicate`（MD5 跨任务去重）、`GET /migrate/status/{id}`、`POST /migrate/cleanup/{id}?confirm=true`（_migrate.py:20-193；cleanup 必须显式 confirm，:167-171）。
- **查询**：`POST /search`、`GET /entities`、`GET /relationships`（_query.py:28-151）。
- **管理**：`GET /status`、`GET /tasks`、`DELETE /tasks/{id}`、`GET /graph?task_id=`（_admin.py:25-135，graph 返回 force-graph 兼容的 `{nodes, links}`）。

## 数据流（读写什么）

**摄取（写）**走双路径选择，这是本模块最重要的机制：`POST /ingest` 先经 C++ 确认 task 存在（_ingest.py:55），然后**优先**走 `IngestionJobManager.queue_ingestion`（:60-69，作业持久化在 Redis，不可用回退内存），仅当管理器不可用时才回落到旧的 `GraphitiService.start_ingestion`（:71-77）。摄取 worker 最终仍汇聚到 `GraphitiService.ingest_task_episodes`（ingestion_job_parts/_worker.py:583）——所有代码路径产出同一张 Episodic → Entity → RELATES_TO 图。

**查询（读）**：search 走 Graphiti 的 COMBINED_HYBRID_SEARCH_RRF 混合检索，Graphiti 不可用时回退 Neo4j CONTAINS 文本匹配（机制详见 [services/GraphitiService.md](../../services/GraphitiService.md)）；entities/relationships/graph 是直接 Cypher 分页查询。所有查询都带 task_id 过滤（group_id 隔离），不会跨任务串数据。

## 边界与已知状态

- **404 前置**：摄取/迁移先查 C++ 任务存在性，不存在直接 404（_ingest.py:57）。
- **501 降级**：`ingest/file`、`ingest/events` 与全部 migrate 端点在对应管理器（IngestionJobManager / MigrationManager）未初始化时返回 501（_ingest.py:133-136、_migrate.py:46-50）——例如 Neo4j 没起来时启动阶段跳过了 MigrationManager。
- **进度单位不一致**：新作业系统返回 0-100 整数进度，旧回退路径乘 100（_jobs.py:47 vs :56）——前端按百分比理解即可。
- **错误脱敏**：search/entities 等查询失败时 detail 传的是 `str(e)`（_query.py:73），与全局"固定文案"纪律不完全一致，属于已知瑕疵。
- cleanup 不可逆，confirm 参数是唯一的护栏（_migrate.py:167-171）。

## 如何验证与扩展

- `python_service/tests/unit/test_graphiti_integration_fixes.py`（摄取契约与修复回归）、`test_ingestion_analyzed_only.py`（analyzed_only 模式）、`test_d4b_graphiti_cleanup.py`（任务图删除边界）。
- 手工链路：`POST /api/graphiti/ingest {"task_id": "..."}` → 轮询 `GET /api/graphiti/jobs/{job_id}` → `GET /api/graphiti/graph?task_id=...` 看节点。
- 新增摄取模式：在 `IngestionMode`（graphiti_models.py）加枚举 → worker `_process_job`（_worker.py:76-107）加分支 → 端点 docstring 同步。

相关阅读：[HTTPRoutes.md](../HTTPRoutes.md)、[services/GraphitiService.md](../../services/GraphitiService.md)、[graphiti/GraphitiIntegration.md](../../graphiti/GraphitiIntegration.md)。

**最后更新**: 2026-08-23（解释式重写）
