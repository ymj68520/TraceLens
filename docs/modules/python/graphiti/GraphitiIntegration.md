# GraphitiIntegration（python_service/graphiti_integration/ 包总览）

> **一句话**：把 C++ 产出的取证 SQLite 变成 Neo4j 知识图谱的独立库——发现/读取数据库、把记录变换成 episode、经 Graphiti SDK 摄取（本地 LLM 抽取实体关系），并提供 File 实体、关系构建与旧结构迁移等图运维工具。

## 1. 为什么有这个模块

httpserver 里的 GraphitiService 决定"何时、以什么隔离方式建图"，但"怎么读库、怎么把一条文件记录变成 LLM 能抽实体的文本、怎么跟 Graphiti SDK 和 Neo4j 打交道"是可独立测试的纯库问题。graphiti_integration 把这些沉淀为一个不依赖 FastAPI 的包（可命令行独立运行 pipeline），httpserver 通过 ServiceManager 的 sys.path 注入使用它（service_manager.py:230-233）。

## 2. 在系统中的位置

- **谁调用它**：httpserver 的 GraphitiService（GraphitiIngestor / TOONTransformer / MultiSourcePipeline / EpisodeData）、IngestionJobManager worker、MigrationManager（经 ServiceManager）；CLI 直接 `python -m graphiti_integration.pipeline` 亦可跑。
- **它调用谁**：SQLite（只读各 *_db）；Neo4j（异步驱动）；OpenAI 兼容推理端点（实体抽取 + 嵌入 + 重排，经 graphiti-core 的客户端）。
- **包内地图**：`config.py`（GraphitiConfig）→ `database_reader/`（读）→ `toon_transformer.py` + `forensic_episode_transformer.py` + `oss_transformer.py`（变换）→ `graphiti_ingestor.py`（摄取）→ `pipeline.py` / `pipeline_multi_source.py`（编排）；旁路：`llm_patch.py`（SDK 兼容补丁）、`file_entity_ingestor.py`、`entity_relation_builder.py`、`migration.py`（图运维）。

## 3. 核心概念与设计

**（a）数据流水线的三段式。** 所有摄取都是"读 → 变换 → 摄取"：

1. **读**：`ForensicsDatabaseFactory.discover()` 按后缀发现 `<base>_raw/_files/_events/_windows/_linux/_android.db`，`create_readers()` 为每个库配专用 reader（→ [DatabaseReader.md](../graphiti_integration/DatabaseReader.md)）。
2. **变换**：`TOONTransformer` 把 FileRecord 变 EpisodeData（文件通道）；`ForensicEpisodeTransformer` 处理事件与平台 artifacts（→ [TOONTransformer.md](../graphiti_integration/TOONTransformer.md)）。
3. **摄取**：`GraphitiIngestor.batch_ingest()` 把每个 episode 交给 Graphiti 的 `add_episode`，由 LLM 抽取实体/关系（→ [GraphitiIngestor.md](../graphiti_integration/GraphitiIngestor.md)）。

两个编排器：`GraphitiPipeline`（pipeline.py，仅 files 库，CLI 入口）与 `MultiSourcePipeline`（pipeline_multi_source.py:73-190，全部库种，按 discover → files → events → platform 顺序处理，finally 关闭 ingestor）。

**（b）llm_patch：必须在 graphiti_core 之前导入。** 本地推理模型（qwen3、deepseek-r1 等）会把输出包在 `<think>` 标签或 Markdown 围栏里，直接打爆 Graphiti 内部的 `json.loads`。`llm_patch.apply_patch()`（llm_patch.py:37-149）monkey-patch `OpenAIGenericClient._generate_response`：先清洗 `<think>`/围栏再解析；解析失败则去掉 `response_format` 并在 system prompt 注入 `/no_think` 重试一次（:79-131）。包的 `__init__.py` 第一件事就是导入它（__init__.py:7-8），graphiti_ingestor.py 也在任何 graphiti_core 导入前显式 apply（:12-13）。**任何新模块若先 import 了 graphiti_core 再 import 本包，补丁仍会生效（patch 的是类方法），但请保持"先 llm_patch"的惯例**——这是本包最著名的坑。

**（c）group_id 即隔离。** GraphitiConfig.group_id（config.py:55）默认 `forensics_files`，但 httpserver 侧总是传 task_id/case_id 覆盖。库本身对 group_id 无假设，隔离语义由调用方赋予。

**（d）配置的两组默认值来源。** `GraphitiConfig`（config.py:17-58）既可 `from_env()`（:60-110，读 NEO4J_*/LLM_TEXT_*/EMBEDDING_*/GRAPHITI_* 环境变量）也可由 httpserver 的 `_build_graphiti_config` 显式构造。关键项：嵌入模型默认 `text-embedding-nomic-embed-text-v1.5`、维度 768（:33-35）——**换嵌入模型必须同步改 `EMBEDDING_DIM`**，否则向量索引维度不匹配；`max_episode_tokens=3000`（:47）限制单 episode 长度防上下文溢出；`include_full_description` 默认 False（:48），由 httpserver 的 `GRAPHITI_INCLUDE_FULL_DESC` 决定是否把完整 llm_description 带进 episode（带得多抽取更丰富但更费 token）。

**（e）File 实体旁路。** 除 episode 主链路外，`FileEntityIngestor`（file_entity_ingestor.py:47）用原生 Neo4j 驱动直接建 File 实体节点，ID 为**路径的 SHA-256**（:50-52）——保证唯一又保留可读路径；`EntityRelationBuilder`（entity_relation_builder.py:27）补 MENTIONED_IN 回边并做跨任务实体合并；`MigrationManager`（migration.py:55）负责 episode 中心旧结构 → File 实体中心新结构的一次性迁移、MD5 去重（SAME_CONTENT_AS 边）与清理。这组工具对应 `/api/graphiti/migrate*` 端点。

## 4. 工作流程走读：一次全量摄取（旧路径视角）

`GraphitiService.start_ingestion(task_id)` → 构造 `MultiSourcePipeline(config)`（group_id=task_id）→ `ForensicsDatabaseFactory.discover(any_db_path=task.output_files_db)` 推断 base_name/output_dir → 逐库：reader 分批读记录（iter_files_batched）→ transformer 产出 EpisodeData → `GraphitiIngestor.batch_ingest`（渲染成文本、限 token、带 FORENSIC_EXTRACTION_INSTRUCTIONS 重试摄取）→ 汇总 MultiSourceResult。httpserver 的 IngestionJobManager 新路径则把 episode 构造上移到 `ingest_task_episodes`，但摄取内核同样是 batch_ingest。

## 5. 与其他模块的协作

| 模块 | 协作方式 |
|---|---|
| httpserver GraphitiService | 唯一的应用服务调用方（含 config 组装） |
| graphiti-core SDK | GraphitiIngestor 的底层（被 llm_patch 修补） |
| Neo4j | 图存储；FileEntityIngestor/MigrationManager 直连驱动 |
| C++ 产出的 SQLite | 只读输入（llm_* 列由 LLMService 写入） |

## 6. 注意事项与已知问题

- **导入顺序坑**：见 3(b)，llm_patch 必须先行。
- 包内同时存在 `database_reader.py`（文件）与 `database_reader/`（包）——**包优先**，同名模块的 .py 文件实际不会被导入（其内部 `from .database_reader.raw_reader import ...` 的相对导入也注定失败）；`database_reader_original.py` 是拆分前的遗留单体，仅作参考。详见 [DatabaseReader.md](../graphiti_integration/DatabaseReader.md)。
- graphiti_integration/tests/ 不在 pytest testpaths（pytest.ini 只收 `tests/`），改动后要手动单独跑。
- batch_size 默认 10（config.py:41，从 50 调低防 token 溢出）；大库摄取耗时主要花在逐 episode 的 LLM 抽取上。

## 7. 如何验证与扩展

- 包内测试：`cd python_service && python -m pytest graphiti_integration/tests/`（test_database_reader.py、test_toon_transformer.py、test_graphiti_ingestor.py、test_pipeline_multi_source.py）。
- httpserver 侧集成回归：`tests/unit/test_graphiti_integration_fixes.py`。
- 新数据源：在 database_reader/ 加 reader → DB_SUFFIXES 注册后缀 → ForensicEpisodeTransformer 加变换 → MultiSourcePipeline 加处理分支。

**最后更新**: 2026-08-23（解释式重写）
