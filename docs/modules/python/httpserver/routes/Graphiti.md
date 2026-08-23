# Graphiti 路由（python_service/httpserver/routes/graphiti.py + graphiti_endpoints/，前缀 /api/graphiti）

> **一句话**：知识图谱的完整 HTTP 表面——摄取（同步排队）、后台作业跟踪、图结构迁移、混合检索与可视化数据，全部按 task_id 隔离在各自的图命名空间里。

## 这组路由承担什么职责

模块本体是聚合器（graphiti.py:49-54 把 5 个子 router 串成一个），端点按领域拆在 `graphiti_endpoints/` 下：`_ingest.py`（摄取）、`_jobs.py`（作业）、`_migrate.py`（迁移）、`_query.py`（查询）、`_admin.py`（状态/任务图管理）。Pydantic 模型集中在 `graphiti_models.py`。路由层做三件事：校验 task 存在（经 C++）、在"新作业系统 vs 旧服务"之间选路径、把服务层结果映射为响应模型。

## 典型调用方

- 前端 `/knowledge-graph` 页（web/src/services/graphitiService.js：ingest :19/:114、search :36、entities :45、relationships :61、status :79、tasks :86、jobs :102、graph :123，全部 pythonApi）。
- C++ `LLMPythonProxy`（src/network/HTTPServer/LLMPythonProxy.cpp:63,104,138）在流水线节点回调 `POST /api/graphiti/ingest*`——这是本目录最重要的**服务间**调用方。
- 迁移/清理端点主要由运维或维护脚本使用。

## 核心数据结构

摄取的请求模型与模式枚举（graphiti_models.py:21-40）：

```python
# graphiti_models.py:21-27
class IngestionMode(str, Enum):
    """Ingestion operation modes."""
    FULL = "full"
    FILES_ONLY = "files_only"
    EVENTS_ONLY = "events_only"
    SINGLE_FILE = "single_file"
    ANALYZED_ONLY = "analyzed_only"

# graphiti_models.py:34-40
class IngestRequest(BaseModel):
    task_id: str = Field(..., description="Task ID to ingest data from (also used as graph namespace)")
    mode: IngestionMode = Field(default=IngestionMode.FULL, description="Ingestion mode")
    include_llm_descriptions: bool = Field(default=True, description="Include LLM-generated descriptions")
    batch_size: int = Field(default=50, ge=1, le=500, description="Batch size for processing")
    max_episodes: int = Field(default=100, ge=0, le=10000, description="Maximum episodes to process (0 = unlimited)")
```

逐字段：`task_id` 同时是图命名空间（graphiti group_id 与 Neo4j 过滤键，串数据防护的根基）；`mode` 由 worker 分派（见下）；`max_episodes` 是限流阀（0=不限），旧回退路径消费它、新作业系统暂不透传。作业侧的等价物是 dataclass `IngestionJob`（ingestion_job_models.py:31-48）：

```python
# ingestion_job_models.py:31-48（节选）
@dataclass
class IngestionJob:
    job_id: str
    task_id: str
    mode: IngestionMode
    status: JobStatus = JobStatus.PENDING      # pending/running/completed/failed/cancelled
    progress: int = 0                          # 0-100
    current_phase: str = "queued"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    # ...
    file_id: Optional[int] = None              # For SINGLE_FILE mode
    events_count: int = 0                      # For EVENTS_ONLY mode
```

谁写：manager 在 `queue_*` 建 PENDING 行、worker 随阶段更新 status/progress/current_phase；谁读：`GET /jobs/{id}` 路由。progress 是 0-100 整数（与旧服务的 0-1 浮点不同，见"边界"）。

## 端点分组语义

（完整契约见 docs/api_reference/Python_REST_API.md）

- **摄取**：`POST /ingest`（_ingest.py:27，mode 取 full / files_only / events_only / analyzed_only，docstring :40-48 逐一说明语义；`max_episodes` 可限流）；`POST /ingest/file`（:88，单文件更新）；`POST /ingest/events`（:142，把时间线事件同步到 File 实体）。
- **作业**：`GET /jobs/{id}`（_jobs.py:24）、`DELETE /jobs/{id}`（:72，已完成/失败的作业不可取消）、`GET /jobs`（:118，按 task/status 过滤）。
- **迁移**：`POST /migrate/task/{id}`、`POST /migrate/deduplicate`（MD5 跨任务去重）、`GET /migrate/status/{id}`、`POST /migrate/cleanup/{id}?confirm=true`（_migrate.py:20-193；cleanup 必须显式 confirm，:167-171）。
- **查询**：`POST /search`、`GET /entities`、`GET /relationships`（_query.py:28-151）。
- **管理**：`GET /status`、`GET /tasks`、`DELETE /tasks/{id}`、`GET /graph?task_id=`（_admin.py:25-135，graph 返回 force-graph 兼容的 `{nodes, links}`）。

## 数据流（读写什么）

**摄取（写）走双路径选择**，这是本模块最重要的机制（_ingest.py:54-82）：

```python
# _ingest.py:54-77（节选）
task_exists = await service_manager.cpp_backend.check_task_exists(request.task_id)
if not task_exists:
    raise HTTPException(status_code=404, detail=f"Task {request.task_id} not found")

# Use new IngestionJobManager if available
if hasattr(service_manager, 'ingestion_job_manager') and service_manager.ingestion_job_manager:
    job_id = await service_manager.ingestion_job_manager.queue_ingestion(
        task_id=request.task_id,
        mode=request.mode,
    )
    return IngestionResponse(job_id=job_id, status="PENDING", ...)
else:
    # Fallback to old GraphitiService
    job_id = await service_manager.graphiti_service.start_ingestion(
        task_id=request.task_id,
        include_llm_descriptions=request.include_llm_descriptions,
        batch_size=request.batch_size,
        max_episodes=request.max_episodes,
    )
```

404 前置（:55-57）之后**优先**走 `IngestionJobManager.queue_ingestion`（作业持久化在 Redis，不可用回退内存），仅当管理器不可用时才回落到旧的 `GraphitiService.start_ingestion`。入队本身（ingestion_job_parts/_manager.py:307-341）：

```python
# _manager.py:322-338（节选）
job = IngestionJob(job_id=job_id, task_id=task_id, mode=mode)
await self._save_job(job)
# Signal worker by adding to queue
if self._use_redis:
    await self._redis.lpush("ingestion_queue", json.dumps({
        "job_id": job_id, "task_id": task_id, "mode": mode.value,
    }))
```

job_id 形如 `job_{uuid4.hex[:16]}`（:303-305）。`_save_job`（:210-247）先剔除 None 值（Redis HSET 不收 None），再把 dict/list 序列化成 JSON 字符串（Redis 只存标量），内存模式则直接存 dataclass；`_load_job`（:249-269）反向把 mode/status 字符串还原成枚举、result 还原成 dict——这就是重启后作业仍可查询的原因。worker 侧的分派（ingestion_job_parts/_worker.py:76-107）按 mode 走五条分支（full/files_only/events_only/single_file/analyzed_only），异常统一转 `JobStatus.FAILED + error`。摄取 worker 最终仍汇聚到同一张 Episodic → Entity → RELATES_TO 图（`GraphitiService.ingest_task_episodes` 系列实现）——所有代码路径产出同构数据。

**查询（读）**：search 走 Graphiti 的 COMBINED_HYBRID_SEARCH_RRF 混合检索，Graphiti 不可用时回退 Neo4j CONTAINS 文本匹配（graphiti_parts/_query.py:40-42 的 `if not self._initialized: return await self._neo4j_text_search(...)`）；entities/relationships/graph 是直接 Cypher 分页查询。所有查询都带 task_id 过滤（group_id 隔离），不会跨任务串数据。

## 关键接口/方法签名

| 端点/方法 | 签名要点 | 失败行为 |
|---|---|---|
| `POST /ingest` | `IngestRequest → IngestionResponse{job_id,status,message}` | 任务不存在 404；其余 500 `str(e)` |
| `POST /ingest/file` | `FileIngestRequest{file_id:int,task_id,update_analysis}` | 404/501（无管理器时 :133-136） |
| `POST /ingest/events` | `EventSyncRequest{task_id,events:List[dict]}` | 404/501（:178-181） |
| `GET /jobs/{id}` | → `JobStatusResponse`（含 progress:int、result） | 404；500 `str(e)` |
| `DELETE /jobs/{id}` | → `{success,job_id,message}` | 已完成/失败返回 success:false（不 4xx） |
| `manager.queue_ingestion(task_id, mode) -> str` | 建行 + LPUSH | Redis 断连时 lpush 抛异常向上传播 |
| `manager.get_job_status(job_id) -> Optional[dict]` | 读 Redis HGETALL / 内存 | 无行返回 None（路由转 404） |
| `manager.cancel_job(job_id) -> bool` | 终态返回 False | —— |

## 边界与已知状态

- **404 前置**：摄取/迁移先查 C++ 任务存在性，不存在直接 404（_ingest.py:57）。
- **501 降级**：`ingest/file`、`ingest/events` 与全部 migrate 端点在对应管理器（IngestionJobManager / MigrationManager）未初始化时返回 501（_ingest.py:133-136、_migrate.py:46-50、:170-173）——例如 Neo4j 没起来时启动阶段跳过了 MigrationManager。
- **进度单位不一致**：新作业系统返回 0-100 整数进度，旧回退路径乘 100（_jobs.py:47 vs :56 `int(status.get("progress", 0) * 100)`）——前端按百分比理解即可。
- **错误脱敏**：search/entities 等查询失败时 detail 传的是 `str(e)`（_query.py:73），与全局"固定文案"纪律不完全一致，属于已知瑕疵。
- cleanup 不可逆，confirm 参数是唯一的护栏（_migrate.py:167-171，未 confirm 直接 400）。
- env：`NEO4J_URI/USER/PASSWORD`（驱动参数）、`NEO4J_CONNECT/QUERY_TIMEOUT=5s`、`GRAPHITI_BATCH_SIZE=50`、`GRAPHITI_MAX_EPISODES=3000`、`GRAPHITI_INCLUDE_FULL_DESC=true`、`REDIS_URL`（作业持久层，断连回退内存）。

## 如何验证与扩展

- `python_service/tests/unit/test_graphiti_integration_fixes.py`（摄取契约与修复回归）、`test_ingestion_analyzed_only.py`（analyzed_only 模式）、`test_d4b_graphiti_cleanup.py`（任务图删除边界）。
- 手工链路：`POST /api/graphiti/ingest {"task_id": "..."}` → 轮询 `GET /api/graphiti/jobs/{job_id}` → `GET /api/graphiti/graph?task_id=...` 看节点。
- 新增摄取模式：在 `IngestionMode`（graphiti_models.py 与 ingestion_job_models.py 各一处）加枚举 → worker `_process_job`（_worker.py:76-107）加分支 → 端点 docstring 同步。

相关阅读：[HTTPRoutes.md](../HTTPRoutes.md)、[services/GraphitiService.md](../../services/GraphitiService.md)、[graphiti/GraphitiIntegration.md](../../graphiti/GraphitiIntegration.md)。

## 二轮深化 A：Pydantic 模型全表（graphiti_models.py，15 个模型逐字段）

| 模型 | 字段 | 类型/默认 | 校验 | 消费方 |
|---|---|---|---|---|
| IngestRequest | task_id | str 必填 | — | worker 分派 + 图命名空间 |
| | mode | IngestionMode=full | 枚举五值 | worker 五分支 |
| | include_llm_descriptions | bool=True | — | 仅旧回退路径消费（新作业系统不透传） |
| | batch_size | int=50 | ge=1 le=500 | 仅旧回退路径 |
| | max_episodes | int=100 | ge=0 le=10000（0=不限） | 仅旧回退路径 |
| FileIngestRequest | file_id | int 必填 | — | SINGLE_FILE worker（files.db 主键） |
| | task_id | str 必填 | — | 命名空间 |
| | update_analysis | bool=False | — | True 时强制 LLM 重分析再摄取 |
| EventSyncRequest | task_id | str 必填 | — | 命名空间 |
| | events | List[Dict] 必填 | —（无逐元素校验，信任 C++ 发来的形状） | EVENTS_ONLY worker |
| IngestionResponse | job_id/status/message | str×3 | — | ingest 系列三端点共用 |
| JobStatusResponse | job_id/status/progress/current_phase/created_at | 必填 | progress int | GET /jobs/{id} |
| | started_at/completed_at/error/result | Optional | — | result 仅终态有值 |
| IngestResponse | success/task_id/message/timestamp | 必填 | — | 旧回退路径（罕见） |
| | job_id | Optional[str] | — | |
| | entities_created / relationships_created | int=0 | — | |
| SearchRequest | query | str 必填 | min_length=1 | search |
| | task_id | str 必填 | — | 命名空间过滤 |
| | entity_types | Optional[List[str]]=None | — | |
| | limit | int=100 | ge=1 le=1000 | |
| | include_relationships | bool=True | — | |
| SearchResult | entity_id/entity_type/name/properties/score | 必填 | — | score 缺省 0.5（RRF 分数缺失时，服务层） |
| | relationships | Optional[List[Dict]] | — | |
| SearchResponse | success/query/task_id/results/total_count/timestamp | 必填 | total_count=len(results) | search |
| EntityListResponse / RelationshipListResponse | success/task_id/{entities\|relationships}/total_count/page/page_size/timestamp | 必填 | — | 分页列表两端点 |
| GraphitiStatusResponse | status/neo4j_connected/total_entities/total_relationships/timestamp | 必填 | — | GET /status |
| | task_id | Optional | — | |
| TaskGraphsResponse | success/task_ids/count/timestamp | 必填 | — | GET /tasks |

注意 IngestRequest 三个调优字段（include_llm_descriptions/batch_size/max_episodes）在新作业系统路径上是**接受但忽略**——`queue_ingestion(task_id, mode)` 只透传两个参数（_ingest.py:58-61）；真正生效的是 Settings 的 GRAPHITI_* env。这是"请求字段 ≠ 生效配置"的典型案例，排障时别在请求体里调 batch_size。

## 二轮深化 B：作业状态机与 phase 全表

JobStatus 五态（ingestion_job_models.py:24-30）的合法转移（源码核对）：

| 转移 | 触发 | 写入点 | 附带效果 |
|---|---|---|---|
| → pending | queue_* 入队 | _manager.py（_save_job） | created_at 填 UTC isoformat |
| pending → running | worker 取到作业 | _worker.py:83 | 补 started_at（_manager.py:296-297） |
| running → completed | 分派函数正常返回 | _worker.py:97、:114、:227 等 | progress=100、completed_at、result 摘要 |
| running → failed | 分派函数抛异常 | _worker.py:105 | error=str(e)、completed_at |
| pending → cancelled | DELETE /jobs/{id} 在 worker 触达前 | _manager.py:467-470 | cancel_job 返回 True |
| （终态不变） | DELETE 已完成/失败/取消的作业 | _manager.py:467 | 返回 False（路由 200 + success:false） |

**没有 running → cancelled**：worker 一旦开始执行，DELETE 无法中断——取消只在排队窗口有效。这解释了 DELETE 端点的 success:false 文案（"job already in terminal state or running"语义）。

running 态的 current_phase 枚举（worker 实测写入值，非 Enum、自由字符串）与 progress 里程碑：

| phase | progress | 阶段语义 |
|---|---|---|
| queued | 0 | 入队初始值 |
| starting | — | worker 接手 |
| reading_databases | 5-10 | 打开 files.db/events.db |
| reading_files / reading_events | 10 | files_only/events_only 分支读取 |
| processing_files | 10-? | 逐批处理文件 |
| creating_file_entities | 10→? | 建实体 |
| attaching_events | 80 | 事件挂到 File 实体 |
| linking_entities | 85 | 实体间关系 |
| deduplicating_files | 90 | MD5 去重 |
| （终态 completed） | 100 | |

前端轮询可按 phase 文本显示阶段名；progress 在 10→80 之间是批次粒度推进（每批更新一次）。

## 二轮深化 C：新走读——search 的两级实现与降级路径

路由层（_query.py:40-49）只是参数透传 + 结果组装；值得走的是服务层的双路径（graphiti_parts/_query.py:38-42 与 44-70）：

```python
# graphiti_parts/_query.py:38-42
if not self._initialized:
    # Fallback: Neo4j full-text search
    return await self._neo4j_text_search(query, task_id, limit)
```

逐块解释：`_initialized=False` 是 GraphitiService 的"initialized-but-disabled"降级态（Neo4j 启动期连不上）——此时 search **不报错**，退到 `_neo4j_text_search` 的 CONTAINS 文本匹配。两级的差异是检索质量：降级路径无向量/全文索引、无 RRF 融合、无 entity_types 过滤（参数被丢弃）、无 relationships 附加——返回的 score 是固定值。也就是说**同一个端点在 Neo4j 部分可用时静默给出更差的结果**，前端无法从响应区分（success 恒 true）。判断当前在哪一级：`GET /api/graphiti/status` 的 neo4j_connected + 服务日志的降级 warning。

正常路径（:44-70）：从 `_task_graphs` 缓存拿该 task 的 ingestor → `ingestor._client.search_`（注意是三下划线结尾的 `search_`，返回 edges+nodes+episodes 三层；`search` 只回 edges——注释 :48-49 明说）→ `COMBINED_HYBRID_SEARCH_RRF` 配置改写 limit → 结果分三类格式化：Edges 的 `properties.body=fact`（LLM 抽取的关系文本）、Nodes 的 `summary`、Episodes 的 `content`。edge 分数缺失时补 0.5（:70-73 附近）。一个边界：`_task_graphs.get(task_id)` 未命中（进程重启后缓存为空但图在库里）时走不到 `search_`——会落入更外层的异常/空结果分支，重启后首次 search 可能返回空直到重新摄取或缓存重建。

## 二轮深化 D：前端方法 ↔ 端点 ↔ 状态码关联矩阵

| graphitiService.js 方法 | 端点 | 期望状态码 | 失败形态 |
|---|---|---|---|
| ingestTask（:19） | POST /ingest | 200 | 404 任务不存在 / 500 str(e) |
| ingestFile（:114） | POST /ingest/file | 200 | 404 / **501** 管理器缺失 |
| searchGraph（:36） | POST /search | 200 | 500 str(e)（含内部信息，已知瑕疵） |
| getEntities（:45） | GET /entities | 200 | 同上 |
| getRelationships（:61） | GET /relationships | 200 | 同上 |
| getStatus（:79） | GET /status | 200 | — |
| getTasks（:86） | GET /tasks | 200 | — |
| getJobs / getJobStatus（:102） | GET /jobs[/{id}] | 200 | 404 作业不存在（重启后内存态丢失） |
| deleteGraph（:123）→ | DELETE /tasks/{id} | 200 | cleanup 与它不同端点 |
| （C++ LLMPythonProxy） | POST /ingest、/ingest/file、/ingest/events | 200 | 同上，重试由 C++ 侧负责 |

**最后更新**: 2026-08-24（二轮深化：补全端点清单与模型契约）
