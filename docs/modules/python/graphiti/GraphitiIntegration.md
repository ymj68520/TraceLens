# GraphitiIntegration（python_service/graphiti_integration/ 包总览）

> **一句话**：把 C++ 产出的取证 SQLite 变成 Neo4j 知识图谱的独立库——发现/读取数据库、把记录变换成 episode、经 Graphiti SDK 摄取（本地 LLM 抽取实体关系），并提供 File 实体、关系构建与旧结构迁移等图运维工具。

## 1. 为什么有这个模块

httpserver 里的 GraphitiService 决定"何时、以什么隔离方式建图"，但"怎么读库、怎么把一条文件记录变成 LLM 能抽实体的文本、怎么跟 Graphiti SDK 和 Neo4j 打交道"是可独立测试的纯库问题。graphiti_integration 把这些沉淀为一个不依赖 FastAPI 的包（可命令行独立运行 pipeline），httpserver 通过 ServiceManager 的 sys.path 注入使用它（service_manager.py:230-233）。

## 2. 在系统中的位置

- **谁调用它**：httpserver 的 GraphitiService（GraphitiIngestor / TOONTransformer / MultiSourcePipeline / EpisodeData）、IngestionJobManager worker、MigrationManager（经 ServiceManager）；CLI 直接 `python -m graphiti_integration.pipeline` 亦可跑。
- **它调用谁**：SQLite（只读各 *_db）；Neo4j（异步驱动）；OpenAI 兼容推理端点（实体抽取 + 嵌入 + 重排，经 graphiti-core 的客户端）。
- **包内地图**：`config.py`（GraphitiConfig）→ `database_reader/`（读）→ `toon_transformer.py` + `forensic_episode_transformer.py` + `oss_transformer.py`（变换）→ `graphiti_ingestor.py`（摄取）→ `pipeline.py` / `pipeline_multi_source.py`（编排）；旁路：`llm_patch.py`（SDK 兼容补丁）、`file_entity_ingestor.py`、`entity_relation_builder.py`、`migration.py`（图运维）。
- **模块依赖顺序（导入时序）**：`llm_patch` 必须先于任何 `graphiti_core` 导入——包 `__init__.py` 第一件事就是导入它（__init__.py:7-8），`graphiti_ingestor.py` 也在文件头显式 apply（:12-13）。安全顺序：`config` / `database_reader` / `toon_transformer`（无 SDK 依赖）→ `llm_patch` → `graphiti_ingestor` → `pipeline*`。

## 3. 核心数据结构：GraphitiConfig

```python
# graphiti_integration/config.py:17-58（节选）
@dataclass
class GraphitiConfig:
    """Configuration for Graphiti integration pipeline."""

    # Neo4j connection
    neo4j_uri: str = "neo4j://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # LLM settings (supports local OpenAI-compatible servers like LM Studio)
    llm_base_url: str = "http://192.168.31.170:1234/v1"
    llm_model: str = "openai/gpt-oss-20b"
    llm_api_key: str = "local"  # Placeholder for local servers

    # Embedder settings (can use local or OpenAI)
    embedder_base_url: Optional[str] = None  # None = use OpenAI
    embedder_model: str = "text-embedding-nomic-embed-text-v1.5"
    embedder_api_key: Optional[str] = None
    embedder_dim: int = 768

    # Batch processing
    batch_size: int = 10  # Reduced from 50 to prevent token overflow
    max_retries: int = 3
    retry_delay: float = 1.0  # seconds

    # Token management (prevents 8096 context overflow)
    max_episode_tokens: int = 3000  # Per-episode safety limit (~7500 chars)
    include_full_description: bool = False  # Exclude large llm_description by default

    # Graphiti group_id for organizing data
    group_id: str = "forensics_files"

    # Use local LLM (LM Studio / Ollama compatible)
    use_local_llm: bool = True
```

两组默认值来源：`from_env()`（:60-110）读环境变量，或由 httpserver 的 `_build_graphiti_config` 显式构造（Settings → GraphitiConfig，见 GraphitiService.md）。关键项：嵌入模型默认 `text-embedding-nomic-embed-text-v1.5`、维度 768——**换嵌入模型必须同步改 `EMBEDDING_DIM`**，否则向量索引维度不匹配；`max_episode_tokens=3000` 限制单 episode 长度防上下文溢出；`include_full_description` 默认 False。`validate()`（:112-145）返回错误列表而非抛异常，Neo4j 密码为空会被点名（CLI 入口用它做前置检查）。env 装载会向上找 5 层目录的 `.env`（:74-80），`llm_base_url` 自动补 `/v1` 后缀（:83-86）。

## 4. 核心概念与设计

**（a）数据流水线的三段式。** 所有摄取都是"读 → 变换 → 摄取"：

1. **读**：`ForensicsDatabaseFactory.discover()` 按后缀发现 `<base>_raw/_files/_events/_windows/_linux/_android.db`，`create_readers()` 为每个库配专用 reader（→ [DatabaseReader.md](../graphiti_integration/DatabaseReader.md)）。
2. **变换**：`TOONTransformer` 把 FileRecord 变 EpisodeData（文件通道）；`ForensicEpisodeTransformer` 处理事件与平台 artifacts（→ [TOONTransformer.md](../graphiti_integration/TOONTransformer.md)）。
3. **摄取**：`GraphitiIngestor.batch_ingest()` 把每个 episode 交给 Graphiti 的 `add_episode`，由 LLM 抽取实体/关系（→ [GraphitiIngestor.md](../graphiti_integration/GraphitiIngestor.md)）。

两个编排器：`GraphitiPipeline`（pipeline.py，仅 files 库，CLI 入口）与 `MultiSourcePipeline`（pipeline_multi_source.py:73-190，全部库种，按 discover → files → events → platform 顺序处理，finally 关闭 ingestor）。

**（b）llm_patch：必须在 graphiti_core 之前导入。** 本地推理模型（qwen3、deepseek-r1 等）会把输出包在 `<think>` 标签或 Markdown 围栏里，直接打爆 Graphiti 内部的 `json.loads`。清洗函数是纯文本操作：

```python
# llm_patch.py:23-34
def _strip_llm_artifacts(text: str) -> str:
    """Strip <think> tags, markdown fences, and other LLM artifacts from response."""
    # Strip <think>...</think> tags (qwen3, deepseek-r1, etc.)
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    # Strip  channel  tags (some models)
    text = re.sub(r'<channel>.*?</channel>', '', text, flags=re.DOTALL)
    # Strip markdown code fences
    text = text.strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
    return text.strip()
```

`apply_patch()`（llm_patch.py:37-149）monkey-patch `OpenAIGenericClient._generate_response`：先清洗再解析；解析失败则去掉 `response_format` 并在 system prompt 注入 `/no_think` 重试一次：

```python
# llm_patch.py:98-107（第二次尝试的提示注入）
logger.info("Retrying without response_format and with /no_think hint")
fallback_messages = list(openai_messages)
# Inject /no_think into system prompt to suppress reasoning output
if fallback_messages and fallback_messages[0]['role'] == 'system':
    fallback_messages[0] = {
        'role': 'system',
        'content': fallback_messages[0]['content']
            + '\n/no_think\nRespond ONLY with valid JSON. No explanations, no thinking, no markdown.'
    }
```

若第二次仍拿不到 JSON，抛 ValueError 让上层按 episode 级失败记账。幂等保护靠 `_think_patch_applied` 类标记（:46-47），重复 apply 是 no-op。包的 `__init__.py` 第一件事就是导入它（__init__.py:7-8），graphiti_ingestor.py 也在任何 graphiti_core 导入前显式 apply（:12-13）。**任何新模块若先 import 了 graphiti_core 再 import 本包，补丁仍会生效（patch 的是类方法），但请保持"先 llm_patch"的惯例**——这是本包最著名的坑。

**（c）group_id 即隔离。** GraphitiConfig.group_id（config.py:55）默认 `forensics_files`，但 httpserver 侧总是传 task_id/case_id 覆盖。库本身对 group_id 无假设，隔离语义由调用方赋予。

**（d）File 实体旁路。** 除 episode 主链路外，`FileEntityIngestor`（file_entity_ingestor.py:47）用原生 Neo4j 驱动直接建 File 实体节点，ID 为**路径的 SHA-256**（:50-52）——保证唯一又保留可读路径；`EntityRelationBuilder`（entity_relation_builder.py:27）补 MENTIONED_IN 回边并做跨任务实体合并；`MigrationManager`（migration.py:55）负责 episode 中心旧结构 → File 实体中心新结构的一次性迁移、MD5 去重（SAME_CONTENT_AS 边）与清理。这组工具对应 `/api/graphiti/migrate*` 端点。

**（e）异常层次。** `exceptions.py` 定义四个域错误：`GraphitiIntegrationError`（基类）、`DatabaseError`（库不存在/坏库）、`TransformationError`（记录变换失败）、`IngestionError`（重试耗尽）——调用方可以按层捕获并区分"读失败/变失败/摄失败"。

## 5. env 全表（from_env 读取项与默认值）

| env | 默认 | 说明 |
|---|---|---|
| `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` | `neo4j://127.0.0.1:7687` / `neo4j` / `""` | Neo4j 连接；密码为空是常见配置错误 |
| `LLM_TEXT_BASE_URL` / `LLM_TEXT_MODEL` / `LLM_API_KEY` | `http://192.168.31.170:1234/v1` / `openai/gpt-oss-20b` / `local` | 抽取 LLM |
| `EMBEDDING_BASE_URL` / `EMBEDDING_MODEL` / `EMBEDDING_API_KEY` / `EMBEDDING_DIM` | None / `text-embedding-nomic-embed-text-v1.5` / None→OPENAI_API_KEY / 768 | 嵌入可独立于聊天端点 |
| `GRAPHITI_DB_PATH` | None | CLI pipeline 的输入库 |
| `GRAPHITI_BATCH_SIZE` / `GRAPHITI_MAX_RETRIES` / `GRAPHITI_GROUP_ID` | 10 / 3 / `forensics_files` | 批/重试/默认命名空间 |
| `GRAPHITI_USE_LOCAL_LLM` / `GRAPHITI_MAX_EPISODE_TOKENS` / `GRAPHITI_INCLUDE_FULL_DESC` | true / 3000 / false | 本地模式、token 上限、长描述开关 |

注意 httpserver Settings 里 `GRAPHITI_BATCH_SIZE` 默认是 50、`GRAPHITI_INCLUDE_FULL_DESC` 默认 True（config.py:201/:207），与库内 from_env 默认（10/false）**不一致**——httpserver 构造路径总是显式传值所以实际以 Settings 为准；CLI 直跑本包时才用库内默认。这是个容易误判的坑。

## 6. 工作流程走读：一次全量摄取（旧路径视角）

`GraphitiService.start_ingestion(task_id)` → 构造 `MultiSourcePipeline(config)`（group_id=task_id）→ `ForensicsDatabaseFactory.discover(any_db_path=task.output_files_db)` 推断 base_name/output_dir → 逐库：reader 分批读记录（iter_files_batched）→ transformer 产出 EpisodeData → `GraphitiIngestor.batch_ingest`（渲染成文本、限 token、带 FORENSIC_EXTRACTION_INSTRUCTIONS 重试摄取）→ 汇总 MultiSourceResult。httpserver 的 IngestionJobManager 新路径则把 episode 构造上移到 `ingest_task_episodes`，但摄取内核同样是 batch_ingest。

## 7. 与其他模块的协作

| 模块 | 协作方式 |
|---|---|
| httpserver GraphitiService | 唯一的应用服务调用方（含 config 组装） |
| graphiti-core SDK | GraphitiIngestor 的底层（被 llm_patch 修补） |
| Neo4j | 图存储；FileEntityIngestor/MigrationManager 直连驱动 |
| C++ 产出的 SQLite | 只读输入（llm_* 列由 LLMService 写入） |

## 8. 注意事项与已知问题

- **导入顺序坑**：见 4(b)，llm_patch 必须先行。
- 包内同时存在 `database_reader.py`（文件）与 `database_reader/`（包）——**包优先**，同名模块的 .py 文件实际不会被导入（其内部 `from .database_reader.raw_reader import ...` 的相对导入也注定失败）；`database_reader_original.py` 是拆分前的遗留单体，仅作参考。详见 [DatabaseReader.md](../graphiti_integration/DatabaseReader.md)。
- graphiti_integration/tests/ 不在 pytest testpaths（pytest.ini 只收 `tests/`），改动后要手动单独跑。
- batch_size 默认 10（config.py:41，从 50 调低防 token 溢出）；大库摄取耗时主要花在逐 episode 的 LLM 抽取上。
- httpserver 与 CLI 的同名 env 默认值存在偏差（见第 5 节表后说明），排查行为差异先确认走的哪条配置路径。

## 9. 如何验证与扩展

- 包内测试：`cd python_service && python -m pytest graphiti_integration/tests/`（test_database_reader.py、test_toon_transformer.py、test_graphiti_ingestor.py、test_pipeline_multi_source.py）。
- httpserver 侧集成回归：`tests/unit/test_graphiti_integration_fixes.py`。
- 新数据源：在 database_reader/ 加 reader → DB_SUFFIXES 注册后缀 → ForensicEpisodeTransformer 加变换 → MultiSourcePipeline 加处理分支。

## 10. 二轮深化 A：包内文件全清单（26 个文件）

| 文件 | 职责 | 消费方 |
|---|---|---|
| `__init__.py` | 第一行导入 llm_patch（导入顺序锚点） | 全部 |
| `config.py` | GraphitiConfig + from_env + validate | 全部 |
| `exceptions.py` | 4 个域异常 | 全部 |
| `llm_patch.py` | SDK monkey-patch（清洗/二段重试/幂等） | graphiti_ingestor |
| `toon_transformer.py` | FileRecord→EpisodeData | pipeline |
| `forensic_episode_transformer.py` | 事件/平台 artifacts→EpisodeData | multi_source |
| `oss_transformer.py` | OSS 对象→EpisodeData | OSS 链 |
| `graphiti_ingestor.py` | add_episode 摄取内核 | 两条 pipeline |
| `file_entity_ingestor.py` | File 实体直建（SHA-256 id） | JobManager path-B |
| `entity_relation_builder.py` | MENTIONED_IN 回边/实体合并 | path-B |
| `migration.py` | 旧结构迁移/MD5 去重/清理 | /migrate 端点 |
| `pipeline.py` | files 单源编排 + CLI main | CLI |
| `pipeline_multi_source.py` | 全库种编排 | GraphitiService 旧路径 |
| `forensic_data_types.py` | FileRecord/EpisodeData 等数据类 | 全部 |
| `database_reader/`（包，7 文件） | 各库种 reader | 两条 pipeline |
| `database_reader.py`（同名文件） | **死代码**（包优先） | 无 |
| `database_reader_original.py` | 拆分前遗留单体，仅参考 | 无 |
| `tests/`（4 文件） | 包内测试（不在 pytest testpaths） | 手动跑 |

## 11. 二轮深化 B：三处 batch_size 默认值（二轮新发现）

同名参数在三条路径上各有一个默认，互不相同：

| 路径 | 默认 | 位置 | 生效条件 |
|---|---|---|---|
| httpserver Settings | **50** | config.py:201（GRAPHITI_BATCH_SIZE） | 经 /api/graphiti/* 的摄取 |
| GraphitiConfig.from_env | **10** | graphiti_integration/config.py:41 | CLI 未传 --batch-size 且 env 未设 |
| pipeline.py CLI 旗标 | **50** | pipeline.py:288-292（--batch-size default=50） | 旗标显式缺省时**覆盖** from_env 的 10 |

也就是说：`python -m graphiti_integration.pipeline --db-path ...` 不带 --batch-size 时实际跑 50（旗标默认），而任何直接构造 `GraphitiConfig.from_env()` 的代码拿到 10——"batch_size=10 防 token 溢出"的注释意图只在第三种路径外的一部分场景成立。加上 `GRAPHITI_INCLUDE_FULL_DESC` 的 Settings(True)/from_env(False) 分裂，本包是全仓默认值分歧最多的模块；对照实验必须显式设置这两个 env。

## 12. 二轮深化 C：CLI 入口契约（pipeline.py main，258-320）

| 旗标 | 默认 | 说明 |
|---|---|---|
| --db-path | 必填 | 输入 SQLite（files 库） |
| --neo4j-uri / --neo4j-user / --neo4j-password | 本地默认/neo4j/"" | 连接（同 from_env） |
| --batch-size | 50 | 见 11 节 |
| --group-id | forensics_files | 图命名空间 |
| --dry-run | false | **只变换不摄取**（验证 transformer 的工具） |
| -v/--verbose | false | 调试日志 |
| --analyzed-only | false | 只摄取已分析文件 |

dry-run 是本包独有的验证口——httpserver 侧没有等价开关；验证"变换是否产出预期 episode"时优先用它（不碰 Neo4j）。

## 13. 二轮深化 D：异常层次 × 消费方映射

| 异常（exceptions.py） | 语义 | 主要抛出点 | 消费方处置 |
|---|---|---|---|
| GraphitiIntegrationError | 基类 | — | 兜底捕获 |
| DatabaseError | 库不存在/坏库 | database_reader/* | pipeline 记 per-source 失败继续其他库 |
| TransformationError | 记录→episode 失败 | transformers | 逐记录跳过计数 |
| IngestionError | 摄取重试耗尽 | graphiti_ingestor | 逐 episode 失败计数（stats.failed） |

三层失败全部**不中断流水线**——MultiSourceResult 汇总各库的 success/failed 计数后一次返回；这与 httpserver 侧 ingest_task_episodes 的"逐 episode 报错"语义（GraphitiService.md 4d）对齐。

## 14. 二轮深化 E：新走读——pipeline_multi_source 的 finally 关闭（:185-190）

```python
# pipeline_multi_source.py:90-190 骨架
async def run(self, ...):
    try:
        databases = ForensicsDatabaseFactory.discover(...)
        # files → events → platform 顺序逐库处理
        ...
    finally:
        await self.ingestor.close()
```

逐块解释：ingestor 的 Neo4j 驱动与 Graphiti 客户端在 finally 中无条件关闭——摄取中途抛异常（哪怕 KeyboardInterrupt）也不泄漏连接；代价是**该 pipeline 实例不可复用**（关了再用会失败），GraphitiService 的旧作业路径因此每次 start_ingestion 新建 pipeline。对比 GraphitiService._task_graphs 缓存的长寿 ingestor（新路径）：两者的生命周期模型不同，混用会踩"已关闭的 ingestor"。处理顺序 files→events→platform 也有讲究：File 实体先落图，事件 episode 引用文件名时实体已存在（抽取 LLM 能建立引用边）。

**最后更新**: 2026-08-24（二轮深化：补全端点清单与模型契约）
