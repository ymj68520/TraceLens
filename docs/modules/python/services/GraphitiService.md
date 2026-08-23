# GraphitiService（python_service/httpserver/services/graphiti_service.py + graphiti_parts/）

> **一句话**：Neo4j 知识图谱的应用服务层——按 task_id/case_id 缓存互相隔离的 GraphitiIngestor（"任务隔离图谱"），把 LLM 分析文本切成 episode 交给 Graphiti 抽取实体关系，并提供混合检索、后台摄取作业与任务图管理。

## 1. 为什么有这个模块

取证分析的产出是大量非结构化文本（文件描述、事件簇摘要）。要回答"这个 IP 出现在哪些文件里""哪些用户与涉案路径关联"这类问题，需要把这些文本变成实体-关系图。GraphitiService 是 httpserver 与 graphiti_integration 库之间的服务边界：它处理**多租户隔离**（每个任务一张图）、**降级**（Neo4j 不在时服务仍启动）、**异步作业**（摄取是长任务）这三件路由层不该关心的事。

## 2. 在系统中的位置

- **谁调用它**：routes/graphiti_endpoints（摄取/查询/管理）、routes/llm_endpoints 的分析流水线（摄取入口汇聚）、investigation_graph_service（作为 `base_graph_provider` lambda 惰性注入，service_manager.py:493-499）、IngestionJobManager 的 worker（_worker.py:583 调 `ingest_task_episodes`）。
- **它调用谁**：graphiti_integration 的 GraphitiIngestor / MultiSourcePipeline / TOONTransformer；Neo4j 异步驱动（查询路径）；C++ 后端（摄取前取任务数据库路径）。
- **服务↔路由↔前端链**：前端"知识图谱"页 → `/api/graphiti/*`（graphiti_endpoints）→ 本服务；前端"摄取"按钮 → `POST /api/graphiti/ingest` → IngestionJobManager（失败回落本服务旧作业）；报告生成（report_generator）→ `search()` 检索增强章节。

## 3. 核心接口清单

| 方法（真实签名） | 语义 | 调用方 | 失败行为 |
|---|---|---|---|
| `async initialize()` | 探测 Neo4j 并装载 GraphitiIngestor 类 | ServiceManager | 任何失败仍置 `_initialized=True`（initialized-but-disabled） |
| `_build_graphiti_config(group_id: str) -> GraphitiConfig` | 从 Settings 组装库配置 | _get_task_graph/_get_case_graph | 不抛 |
| `async _get_task_graph(task_id: str) / _get_case_graph(case_id: str)` | 按键缓存 `{config, ingestor}`（group_id=task/case id） | 全部摄取/检索路径 | 创建失败抛异常 |
| `async ingest_task_episodes(task_id, file_descriptions, cluster_descriptions=None, case_description=None, progress_callback=None) -> Dict[str, Any]` | path-A 统一入口：构造 episode 并 batch_ingest | 分析流水线、手动 Ingest、JobManager worker | 返回 `{success: False, error, episodes_built: 0}` |
| `async ingest_case_data(case_id, task_ids, files_db_paths, events_db_paths=None, progress_callback=None) -> bool` | 跨镜像聚合进 case 图 | multi_analysis 路径 | 返回 False |
| `async ingest_case_data_incremental(case_id, new_task_ids, existing_task_ids, ...) -> Dict` | 只摄取新任务并带 related_tasks | 增量分析 | 返回 error dict |
| `async search(query, task_id, entity_types=None, limit=100, include_relationships=True) -> List[Dict]` | 混合检索（RRF）三层结果 | 图谱页、报告生成 | 回退 `_neo4j_text_search`，再失败返回 [] |
| `async start_ingestion(task_id, ...) -> str` / `get_job_status` / `cancel_job` | 旧式内存后台作业 | 路由回落路径 | 见第 6 节 |
| `async shutdown()` | 关闭全部缓存图 | ServiceManager 关停 | 逐个容忍异常 |

## 4. 核心概念与设计

**（a）Mixin 组合。** 类本体只有构造器（graphiti_service.py:55-65），方法按领域拆进 `graphiti_parts/` 五个 mixin：`_core.py`（生命周期/图实例/健康）、`_ingest.py`（数据摄取）、`_query.py`（检索）、`_status.py`（状态统计）、`_jobs.py`（旧式后台作业）。公共表面不变，阅读时按 mixin 找对应文件即可。

**（b）initialized-but-disabled 降级。** `initialize()`（_core.py:21-46）先探测 Neo4j；不可用时**仍然置 `_initialized=True`**（:31-32）但 `_graphiti` 为 None——服务"存在但禁用"。所有依赖它的端点由此获得统一的软失败行为，而进程照常启动（这就是 ServiceManager 里 12s 超时失败后整体继续的原因）。

**（c）任务隔离图谱 = group_id。** `_get_task_graph(task_id)`（_core.py:77-105）按 task_id 缓存 `{config, ingestor}`，构造时 `group_id=task_id`（:90）。Graphiti/Neo4j 的 group_id 是图的命名空间：摄取、检索、统计全部带 task_id 过滤，任务之间天然不串数据；`DELETE /api/graphiti/tasks/{id}` 即删一个命名空间。`_get_case_graph(case_id)`（:107-135）是同一机制在案件层的复用——跨镜像分析把多个 task 的分析结果汇入 case_id 图。配置统一经 `_build_graphiti_config()`（:48-75）从服务 Settings 生成：

```python
# graphiti_parts/_core.py:59-75（节选）
base = self.settings.llm_text_base_url.rstrip("/")
llm_base_url = base if base.endswith("/v1") else base + "/v1"

return GraphitiConfig(
    neo4j_uri=self.settings.neo4j_uri,
    neo4j_user=self.settings.neo4j_user,
    neo4j_password=self.settings.neo4j_password,
    llm_base_url=llm_base_url,
    llm_model=self.settings.llm_text_model,
    llm_api_key=self.settings.llm_api_key or "local",
    batch_size=self.settings.graphiti_batch_size,
    max_retries=self.settings.graphiti_max_retries,
    group_id=group_id,
    use_local_llm=self.settings.graphiti_use_local_llm,
    include_full_description=self.settings.graphiti_include_full_desc,
    max_episode_tokens=self.settings.graphiti_max_episode_tokens,
)
```

集中构造的意义（docstring）：`GRAPHITI_INCLUDE_FULL_DESC` / `GRAPHITI_MAX_EPISODE_TOKENS` 曾经在这里被丢掉，导致 episode 缺少抽取 LLM 需要的 llm_description——这两个值直接影响抽取质量（见 [graphiti_integration/GraphitiIngestor.md](../graphiti_integration/GraphitiIngestor.md)）。

**（d）主摄取路径：episode 化。** `ingest_task_episodes()`（_ingest.py:210-381）是所有摄取代码的汇聚点（分析流水线、手动 ingest 按钮、作业 worker 都走它）。它把输入变成三类 episode：案情描述（分块）、每个分析成功的文件、每个事件簇，然后 `batch_ingest`（:355）。文件 episode 的富 body 构造：

```python
# graphiti_parts/_ingest.py:288-311（节选）
# Build a rich episode body. The renderer in GraphitiIngestor
# turns each dict key into a "Field: value" line, so every
# key here becomes visible to the entity extractor. Including
# summary/keywords/category/md5/name means the LLM can extract
# hash identifiers, file-type entities, and category-derived
# relationships it would otherwise discard as "generic values".
body = {
    "file_path": file_path,
    "analysis": chunk,
}
if desc.get("summary"):
    body["summary"] = desc["summary"]
if desc.get("keywords"):
    body["keywords"] = desc["keywords"]
if desc.get("category"):
    body["category"] = desc["category"]
if desc.get("md5"):
    body["md5"] = desc["md5"]
if desc.get("name"):
    body["filename"] = desc["name"]
# ...
if desc.get("is_relevant") is not None:
    body["is_relevant"] = bool(desc["is_relevant"])
```

三个设计要点：

- **3000 字分块**：`_chunk_text_for_graph()`（:383-400）按段落边界切，保证单 episode 不超抽取 LLM 的上下文预算：

```python
# graphiti_parts/_ingest.py:383-400（节选）
@staticmethod
def _chunk_text_for_graph(text: str, max_chars: int = 3000) -> List[str]:
    """Split text into chunks for graph ingestion."""
    if len(text) <= max_chars:
        return [text]
    chunks = []
    paragraphs = text.split("\n\n")
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 2 > max_chars and current:
            chunks.append(current.strip())
            current = para
        else:
            current = current + "\n\n" + para if current else para
```

按 `\n\n` 段落聚合而非按字符硬切——超长段落整体另起一块，语义单元尽量完整。

- **富 episode body**：如上代码，键越多，LLM 能抽到的实体（哈希、文件类型、类别关系）越多；
- **逐 episode 报错**：返回 `{success, successful, total, failed, errors, episodes_built}`（:370-377），失败样本打进日志前 5 条（:363-365）——旧实现静默吞错导致"图谱莫名稀疏"，这是针对性修复（docstring :226-229）。

案件级摄取 `ingest_case_data()`（:21-208）读取各镜像 `_files.db` 中 `is_relevant=1` 的描述并打 `[IMG{n}]` 来源标签（:87、:96）；`ingest_case_data_incremental()`（:402-624）只处理新任务，并在 episode body 里附 `related_tasks` 供抽取器建立跨任务关联（:504）。

**（e）检索：混合优先、文本兜底。** `search()`（_query.py:21-132）优先用 Graphiti 的 `COMBINED_HYBRID_SEARCH_RRF` 配方调 `search_()`（:54-60），一次拿全三层结果：

```python
# graphiti_parts/_query.py:51-60
from graphiti_core.search.search_config_recipes import COMBINED_HYBRID_SEARCH_RRF
from graphiti_core.search.search_filters import SearchFilters

config = COMBINED_HYBRID_SEARCH_RRF.model_copy(update={'limit': limit})
search_results = await ingestor._client.search_(
    query=query,
    config=config,
    group_ids=[task_id],
    search_filter=SearchFilters(),
)
```

注释（:49-50）说明为何不用 `search()`：那只返回边（facts）；`search_()` 返回 edges/nodes/episodes 三层。三层各自格式化为 `{id, name, type, properties{body...}, score}`（边→fact、节点→summary、episode→content，:64-122），按 reranker 分数降序再截 limit（:125-126）。Graphiti 不可用或异常时回退 `_neo4j_text_search()`：直接 Cypher `CONTAINS` 匹配实体名/摘要（:134-169），命中即打固定分 0.8。混合检索服务于报告生成（facts 有语义分），文本兜底保证降级时图谱页还能用。

**（f）两代作业系统并存。** `_jobs.py` 的 `start_ingestion()`（:21-47）是旧路径：内存 `_jobs` dict + `asyncio.create_task` 跑 MultiSourcePipeline（:49-143，从 C++ 拿数据库路径，:66；按 `output_files_db` 推断 output_dir/base_name，:85-101）。新路径是 IngestionJobManager（Redis 持久化、不可用回退内存），路由层优先选它、失败才回落旧路径（routes/graphiti_endpoints/_ingest.py:60-77：`hasattr(service_manager, 'ingestion_job_manager')` 为真即走队列，否则 `start_ingestion`）。注意旧路径的 `cancel_job` 只改状态不真正停止任务（_jobs.py:154-168 的注释）。

## 5. 关联配置（env，经 Settings → _build_graphiti_config）

| env | 默认（httpserver Settings） | 作用 |
|---|---|---|
| `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` | `neo4j://127.0.0.1:7687` / `neo4j` / `""` | 图存储；密码空→initialize 告警并禁用 |
| `NEO4J_CONNECT_TIMEOUT` / `NEO4J_QUERY_TIMEOUT` | 5.0 / 5.0 | 探测与查询超时 |
| `LLM_TEXT_BASE_URL` / `LLM_TEXT_MODEL` / `LLM_API_KEY` | `http://192.168.31.170:1234` / `openai/gpt-oss-20b` / `""` | 抽取 LLM（自动补 /v1） |
| `GRAPHITI_USE_LOCAL_LLM` / `GRAPHITI_BATCH_SIZE` / `GRAPHITI_MAX_RETRIES` | true / 50 / 3 | 本地模式、批大小、重试 |
| `GRAPHITI_INCLUDE_FULL_DESC` / `GRAPHITI_MAX_EPISODE_TOKENS` | **true** / 3000 | episode 丰满度与预算 |
| `REDIS_URL` | `redis://localhost:6379` | IngestionJobManager 持久化（不在本服务直接用） |

## 6. 注意事项与已知问题

- `_task_graphs` 缓存无淘汰：每任务一个 GraphitiIngestor（各持连接），超多任务时长驻进程需留意资源；shutdown 会统一关闭（_core.py:137-148）。
- 旧作业的进度只在内存，重启即失；新作业系统 Redis 持久化解决这一点。
- `search()` 依赖 `ingestor._client` 私有属性（_query.py:48）——跨层触达实现细节，升级 graphiti-core 时需回归。
- Neo4j 密码为空是常见配置错误：initialize 的 warning（_core.py:29-30）会给出排查提示。
- **案例级摄取存在 NameError 隐患（本次核对源码新发现）**：`_ingest.py` 的 mixin 模块**没有导入 `Path`**（模块级 import 只有 asyncio/logging/uuid/os/typing，其余是函数内局部 import），但 `ingest_case_data`（:75、:130）与 `ingest_case_data_incremental`（:471、:529）都在用 `Path(files_db).exists()`——AST 核实确认该名字未导入。运行时每个镜像/任务的聚合块会因 `NameError` 落进各自的 `except Exception` 记 warning（"Failed to aggregate files from image N"），episodes 为空，最终以 "No episodes to ingest" 返回 True/成功字典——**症状是案例图静默为空**。任务级 `ingest_task_episodes` 不用 Path（路径来自调用方 dict），不受影响；修复只需在 `_ingest.py` 顶部补 `from pathlib import Path`。
- 错误处理边界：`ingest_task_episodes` 整体 try/except（:379-381），任何构造期异常返回 success=False 而非 500——调用方（作业 worker）把 error 记入 stats，path-B 结果不受影响。

## 7. 如何验证与扩展

- `python_service/tests/unit/test_graphiti_integration_fixes.py`（episode 摄取契约与修复回归）、`test_ingestion_analyzed_only.py`（analyzed_only 模式）、`test_d4b_graphiti_cleanup.py`（任务图删除）。
- graphiti_integration 自带 `graphiti_integration/tests/`（test_graphiti_ingestor.py 等），**不在 pytest testpaths 里**（pytest.ini 只收 `tests/`），需单独跑。
- 新增检索能力：改 `_query.py` 对应 mixin 方法；保持"带 task_id 过滤 + 降级路径"两个不变量。
- 手工链路：`POST /api/graphiti/ingest` → `GET /api/graphiti/jobs/{id}` → `POST /api/graphiti/search {"task_id","query"}` → `GET /api/graphiti/graph?task_id=`。
- 案例图验证注意第 6 节的 NameError：若跨镜像摄取后案例图无内容，先查日志里 "Failed to aggregate files from image" warning。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
