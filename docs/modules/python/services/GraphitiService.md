# GraphitiService（python_service/httpserver/services/graphiti_service.py + graphiti_parts/）

> **一句话**：Neo4j 知识图谱的应用服务层——按 task_id/case_id 缓存互相隔离的 GraphitiIngestor（"任务隔离图谱"），把 LLM 分析文本切成 episode 交给 Graphiti 抽取实体关系，并提供混合检索、后台摄取作业与任务图管理。

## 1. 为什么有这个模块

取证分析的产出是大量非结构化文本（文件描述、事件簇摘要）。要回答"这个 IP 出现在哪些文件里""哪些用户与涉案路径关联"这类问题，需要把这些文本变成实体-关系图。GraphitiService 是 httpserver 与 graphiti_integration 库之间的服务边界：它处理**多租户隔离**（每个任务一张图）、**降级**（Neo4j 不在时服务仍启动）、**异步作业**（摄取是长任务）这三件路由层不该关心的事。

## 2. 在系统中的位置

- **谁调用它**：routes/graphiti_endpoints（摄取/查询/管理）、routes/llm_endpoints 的分析流水线（摄取入口汇聚）、investigation_graph_service（作为 `base_graph_provider` lambda 惰性注入，service_manager.py:493-499）、IngestionJobManager 的 worker（_worker.py:583 调 `ingest_task_episodes`）。
- **它调用谁**：graphiti_integration 的 GraphitiIngestor / MultiSourcePipeline / TOONTransformer；Neo4j 异步驱动（查询路径）；C++ 后端（摄取前取任务数据库路径）。

## 3. 核心概念与设计

**（a）Mixin 组合。** 类本体只有构造器（graphiti_service.py:55-65），方法按领域拆进 `graphiti_parts/` 五个 mixin：`_core.py`（生命周期/图实例/健康）、`_ingest.py`（数据摄取）、`_query.py`（检索）、`_status.py`（状态统计）、`_jobs.py`（旧式后台作业）。公共表面不变，阅读时按 mixin 找对应文件即可。

**（b）initialized-but-disabled 降级。** `initialize()`（_core.py:21-46）先探测 Neo4j；不可用时**仍然置 `_initialized=True`**（:31-32）但 `_graphiti` 为 None——服务"存在但禁用"。所有依赖它的端点由此获得统一的软失败行为，而进程照常启动（这就是 ServiceManager 里 12s 超时失败后整体继续的原因）。

**（c）任务隔离图谱 = group_id。** `_get_task_graph(task_id)`（_core.py:77-105）按 task_id 缓存 `{config, ingestor}`，构造时 `group_id=task_id`（:90）。Graphiti/Neo4j 的 group_id 是图的命名空间：摄取、检索、统计全部带 task_id 过滤，任务之间天然不串数据；`DELETE /api/graphiti/tasks/{id}` 即删一个命名空间。`_get_case_graph(case_id)`（:107-135）是同一机制在案件层的复用——跨镜像分析把多个 task 的分析结果汇入 case_id 图。配置统一经 `_build_graphiti_config()`（:48-75）从服务 Settings 生成（含 `GRAPHITI_INCLUDE_FULL_DESC` / `GRAPHITI_MAX_EPISODE_TOKENS`，这两个值直接影响抽取质量，见 [graphiti_integration/GraphitiIngestor.md](../graphiti_integration/GraphitiIngestor.md)）。

**（d）主摄取路径：episode 化。** `ingest_task_episodes()`（_ingest.py:210-381）是所有摄取代码的汇聚点（分析流水线、手动 ingest 按钮、作业 worker 都走它）。它把输入变成三类 episode：案情描述（分块，:263-274）、每个分析成功的文件（:277-320）、每个事件簇（:323-345），然后 `batch_ingest`（:355）。三个设计要点：

- **3000 字分块**：`_chunk_text_for_graph()`（:383-400）按段落边界切，保证单 episode 不超抽取 LLM 的上下文预算；
- **富 episode body**：文件 episode 带上 summary/keywords/category/md5/name 等键（:294-311），因为 GraphitiIngestor 会把每个键渲染成 `Field: value` 行，键越多，LLM 能抽到的实体（哈希、文件类型、类别关系）越多；
- **逐 episode 报错**：返回 `{success, successful, total, failed, errors, episodes_built}`（:370-377），失败样本打进日志前 5 条（:363-365）——旧实现静默吞错导致"图谱莫名稀疏"，这是针对性修复（docstring :226-229）。

案件级摄取 `ingest_case_data()`（:21-208）读取各镜像 `_files.db` 中 `is_relevant=1` 的描述并打 `[IMG{n}]` 来源标签（:87、:96）；`ingest_case_data_incremental()`（:402-624）只处理新任务，并在 episode body 里附 `related_tasks` 供抽取器建立跨任务关联（:504）。

**（e）检索：混合优先、文本兜底。** `search()`（_query.py:21-132）优先用 Graphiti 的 `COMBINED_HYBRID_SEARCH_RRF` 配方调 `search_()`（:54-60），一次拿全三层结果——边（LLM 抽取的 fact）、节点（实体摘要）、episode（原始内容），统一格式化后按分数排序（:64-126）。Graphiti 不可用或异常时回退 `_neo4j_text_search()`：直接 Cypher `CONTAINS` 匹配实体名/摘要（:134-169）。混合检索服务于报告生成（facts 有语义分），文本兜底保证降级时图谱页还能用。

**（f）两代作业系统并存。** `_jobs.py` 的 `start_ingestion()`（:21-47）是旧路径：内存 `_jobs` dict + `asyncio.create_task` 跑 MultiSourcePipeline（:49-143，从 C++ 拿数据库路径，:66；按 `output_files_db` 推断 output_dir/base_name，:85-101）。新路径是 IngestionJobManager（Redis 持久化、不可用回退内存），路由层优先选它、失败才回落旧路径（routes/graphiti_endpoints/_ingest.py:60-77）。注意旧路径的 `cancel_job` 只改状态不真正停止任务（_jobs.py:154-168 的注释）。

## 4. 与其他模块的协作

| 模块 | 协作方式 |
|---|---|
| IngestionJobManager | 新摄取入口；worker 最终回调本服务的 ingest_task_episodes |
| graphiti_integration.GraphitiIngestor | 真正的 Graphiti SDK 封装（LLM/embedder/reranker 组装） |
| graphiti_integration.MultiSourcePipeline | 旧摄取路径的多数据库扫描引擎 |
| CppBackendService | 任务存在性与数据库路径 |
| investigation 图服务 | 惰性 lambda 注入，Neo4j 宕机时降级为 base_graph_available=false |

## 5. 注意事项与已知问题

- `_task_graphs` 缓存无淘汰：每任务一个 GraphitiIngestor（各持连接），超多任务时长驻进程需留意资源；shutdown 会统一关闭（_core.py:137-148）。
- 旧作业的进度只在内存，重启即失；新作业系统 Redis 持久化解决这一点。
- `search()` 依赖 `ingestor._client` 私有属性（_query.py:48）——跨层触达实现细节，升级 graphiti-core 时需回归。
- Neo4j 密码为空是常见配置错误：initialize 的 warning（_core.py:29-30）会给出排查提示。

## 6. 如何验证与扩展

- `python_service/tests/unit/test_graphiti_integration_fixes.py`（episode 摄取契约与修复回归）、`test_ingestion_analyzed_only.py`（analyzed_only 模式）、`test_d4b_graphiti_cleanup.py`（任务图删除）。
- graphiti_integration 自带 `graphiti_integration/tests/`（test_graphiti_ingestor.py 等），**不在 pytest testpaths 里**（pytest.ini 只收 `tests/`），需单独跑。
- 新增检索能力：改 `_query.py` 对应 mixin 方法；保持"带 task_id 过滤 + 降级路径"两个不变量。
- 手工链路：`POST /api/graphiti/ingest` → `GET /api/graphiti/jobs/{id}` → `POST /api/graphiti/search {"task_id","query"}` → `GET /api/graphiti/graph?task_id=`。

**最后更新**: 2026-08-23（解释式重写）
