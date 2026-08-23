# GraphitiIngestor（python_service/graphiti_integration/graphiti_ingestor.py）

> **一句话**：Graphiti SDK 的取证专用封装——把 episode 渲染成抽取友好的文本、强制取证实体抽取指令、限制 token 预算、带退避重试地把 episode 灌进 Neo4j，并组装本地 LLM/嵌入/重排三件套。

## 1. 为什么有这个模块

Graphiti（graphiti-core）的默认用法是为通用 RAG 设计的，直接把取证数据丢进去会得到一张几乎空的图：默认抽取提示词**主动丢弃**日期、哈希、ID、路径、IP 这类"通用字段值"——而这恰恰是取证最有价值的实体。GraphitiIngestor 存在的意义就是纠正这组默认行为，并解决本地模型生态的兼容问题。

## 2. 在系统中的位置

- **谁调用它**：httpserver 的 GraphitiService（`_get_task_graph` 为每个 task/case 缓存一个实例）、MultiSourcePipeline（旧摄取路径）、包内测试。
- **它调用谁**：graphiti-core 的 `Graphiti` 客户端（`add_episode` / `build_indices_and_constraints`）、`OpenAIGenericClient`（实体抽取，被 llm_patch 修补）、`OpenAIEmbedder`（nomic 系，dim 768）、`OpenAIRerankerClient`（重排）；Neo4j。
- **输入/输出**：吃 `EpisodeData`（toon_transformer.py:17），吐 `IngestionResult`（graphiti_ingestor.py:75-93，successful/failed/errors 逐条记录）。

## 3. 核心概念与设计

**（a）FORENSIC_EXTRACTION_INSTRUCTIONS——本模块的灵魂。** 一段注入 `add_episode(custom_extraction_instructions=...)` 的指令（:42-72），逐条点名要"慷慨抽取"的实体类型（用户名、主机名、IP/MAC/SSID、完整路径、注册表键、进程名、USB 序列号、MD5/SHA、Event ID……），并要求用 SCREAMING_SNAKE_CASE 谓词建关系（USER LOGGED_IN_FROM IP、HASH_IDENTIFIES FILE 等）。代码注释（:29-41）讲清了动机：Graphiti 默认 `extract_json` 提示词明令"NEVER extract dates/hashes/IDs"——这是"取证图谱近乎为空"这个历史上最大问题的根因。

**（b）JSON → 文本渲染。** `_render_episode_for_extraction()`（:195-238）把 episode_body 从 JSON 字符串渲染成 `# 标题` + 每键一行的 `Field: value` 文本，并以 `EpisodeType.text`（而非 json）摄取。原因（:199-213 注释）：json 源会选择 `extract_json` 提示词（丢弃见上），text 源走 `extract_text`，对自由文本的命名实体抽取宽松得多。结构信息不丢——每个键成为一行显式内容，路径/哈希/用户名对抽取器保持"一等公民"。

**（c）token 预算。** `ingest_episode()`（:330-401）在渲染文本上执行 `max_episode_tokens`（默认 3000）：先用 `TOONTransformer.estimate_episode_tokens`（~4 字符/token + 20% 缓冲）估算，超限则 `truncate_if_needed` 做 JSON 感知的字符串截断（:357-361）。这是对本地模型 8K 上下文的保护。

**（d）重试与逐条报错。** 每个 episode 最多 `GRAPHITI_MAX_RETRIES`（默认 3）次尝试，退避 `retry_delay × attempt`（:364-397）；耗尽抛 `IngestionError`。`batch_ingest()`（:403-458）捕获每个 episode 的失败进 `result.errors`（episode 名 + file_path + 错误），**不因单条失败中断整批**——调用方（ingest_task_episodes）据此向用户暴露"图为什么稀疏"。

**（e）客户端组装与资源所有权。** `initialize()`（:240-290）：本地模式显式构造三件套——OpenAIGenericClient（small_model 与主模型相同，:127）、OpenAIEmbedder（`EMBEDDING_BASE_URL` 可与聊天 LLM 分离，例如云端聊天 + 本地 nomic 嵌入；dim 取配置，:132-155）、OpenAIRerankerClient（复用聊天客户端，:260-268）——然后 `build_indices_and_constraints()`（:288）建索引/约束。`close()`（:292-328）区分"自有资源"（初始化时创建的客户端，需逐一关闭）与"外部注入的 Graphiti 实例"（调用方自负其责）——注释标明这是 D4b 资源治理决策。

**（f）llm_patch 的导入时序。** 文件头（:12-13）在任何 `graphiti_core` 导入前 `apply_patch()`——修补 `OpenAIGenericClient._generate_response` 清洗 `<think>` 标签/markdown 围栏、失败时去 `response_format` 加 `/no_think` 重试（详见 [../graphiti/GraphitiIntegration.md](../graphiti/GraphitiIntegration.md) 第 3(b) 节）。换用 qwen3/deepseek-r1 类推理模型时这个补丁是硬前提。

## 4. 工作流程走读：一个 episode 的入库

调用方给出 `EpisodeData`（name、JSON body、group_id=task_id）→ `ingest_episode()` 渲染为文本（:357）→ 估算 token，必要时截断（:358-361）→ 重试循环内 `self._client.add_episode(name, episode_body=渲染文本, source=EpisodeType.text, group_id, custom_extraction_instructions=FORENSIC_EXTRACTION_INSTRUCTIONS)`（:379-387）→ Graphiti 内部：LLM 抽实体与 RELATES_TO 边、embedder 生成向量、写入 Neo4j（group_id 命名空间）→ 成功返回 True；失败退避重试，最终抛 IngestionError，由 batch_ingest 记账。

## 5. 与其他模块的协作

| 模块 | 协作方式 |
|---|---|
| GraphitiService（httpserver） | 实例的创建/缓存方；search 路径借用其 `_client` |
| toon_transformer.TOONTransformer | token 估算与截断工具来源；EpisodeData 类型来源 |
| llm_patch | 模块导入即生效的 SDK 兼容层 |
| config.GraphitiConfig | 全部参数（模型、嵌入、重试、token 上限、group_id） |
| MultiSourcePipeline | 旧摄取路径的批量调用方 |

## 6. 注意事项与已知问题

- 换嵌入模型必须同步 `EMBEDDING_DIM`（默认 768 对应 nomic-embed-v1.5），否则索引维度不匹配。
- `batch_ingest` 是顺序逐条（无并发）——大批量耗时 ≈ episode 数 × 单次抽取延迟；进度靠 progress_callback。
- `include_full_description=False`（配置默认）时长描述不进 episode；httpserver 可用 `GRAPHITI_INCLUDE_FULL_DESC=true` 打开换取更丰富的抽取。
- 抽取质量依赖本地模型能力：模型太小会出现 JSON 解析失败重试链（llm_patch 的第二次尝试），日志里出现 "Retrying without response_format" 是征兆。
- `close()` 任一资源关闭失败会抛第一个异常（:327-328）——关闭路径的异常应被调用方容忍（GraphitiService.shutdown 即如此）。

## 7. 如何验证与扩展

- `python_service/graphiti_integration/tests/test_graphiti_ingestor.py`（渲染、截断、重试、结果记账；单独跑：`python -m pytest graphiti_integration/tests/`）。
- httpserver 侧回归：`tests/unit/test_graphiti_integration_fixes.py`。
- 调整抽取行为：改 `FORENSIC_EXTRACTION_INSTRUCTIONS`（:42）即可，无需动 Graphiti 版本；抽取效果验证用固定 episode + 小模型目检节点数。
- 手工验证：构造 3 个含用户名/IP/路径的 EpisodeData → batch_ingest → Neo4j Browser 按 group_id 查 Entity 数量。

**最后更新**: 2026-08-23（解释式重写）
