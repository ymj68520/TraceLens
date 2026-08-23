# TOONTransformer（python_service/graphiti_integration/toon_transformer.py）

> **一句话**：数据变换枢纽——定义贯穿全链路的 `EpisodeData` 结构，把 `FileRecord` 变成可被 LLM 抽实体的 episode（带开关控制元数据/分析字段），并提供 token 估算与截断这两个摄取安全的基石工具。

## 1. 为什么有这个模块

"一条数据库记录"和"一段能让 LLM 抽实体的文本"之间需要一层显式变换：哪些字段进、哪些不进（大描述可能 3000+ 字符）、以什么结构表达、超长怎么办。命名致敬 C++ 侧的 `TOONExporter`（同为"表格 → 结构化文本"的思路），但产物不是导出文件而是内存中的 `EpisodeData`。把这一层独立出来，读取（reader）、摄取（ingestor）才能各自演进。

## 2. 在系统中的位置

- **谁调用它**：`MultiSourcePipeline`（files 通道的变换器，pipeline_multi_source.py:137-139）、`GraphitiPipeline`（CLI 路径）、httpserver 的 GraphitiService（只用 `EpisodeData` 类型与 token 工具，任务级 episode 在服务层手工构造）；`ForensicEpisodeTransformer`/`OSSTransformer` 复用 EpisodeData。
- **它调用谁**：只依赖 `database_reader.FileRecord` 与标准库——纯函数层，无 I/O 副作用。

## 3. 核心概念与设计

**（a）EpisodeData 是全链路的通用货币。** dataclass（toon_transformer.py:17-47）携带 name、episode_body（JSON 字符串）、source_description、reference_time，以及回溯字段 file_path/file_id/category。无论 episode 来自文件、事件簇、案情描述还是 OSS 对象，进入 `GraphitiIngestor.batch_ingest` 的都是它——httpserver 的 `ingest_task_episodes` 也手工构造它（graphiti_parts/_ingest.py:105、:266、:312）。

**（b）三个内容开关。** 构造参数（:58-77）决定 episode_body 的丰满程度：`include_metadata`（size/md5/is_deleted/时间戳进 `metadata` 子对象，:166-178）、`include_analysis`（llm_summary/keywords/model 进 `analysis` 子对象，:180-194）、`include_full_description`（**默认 False**，:62——完整 llm_description 可达 3000+ 字符，是否值得为更丰富的抽取付出 token 由配置决定，:186-188 的注释与 httpserver 的 `GRAPHITI_INCLUDE_FULL_DESC` 对应）。episode 名取 `category:文件名`（:198-205），reference_time 优先用 LLM 分析时间（:100-105）。

**（c）token 估算：~4 字符/token 启发式。** `estimate_episode_tokens()`（:256-272）按"1 token ≈ 4 英文字符"估算再加 20% 缓冲（容纳 JSON 结构开销）。它不精确（中文约 1-2 字符/token），但作为**预算闸门**足够——GraphitiIngestor 用它决定是否截断（graphiti_ingestor.py:358-361），`GRAPHITI_MAX_EPISODE_TOKENS=3000` 由此落到实际字节。

**（d）JSON 感知截断。** `truncate_if_needed()`（:274-317）超预算时不是粗暴砍字符串：先 `json.loads`，递归地把**过长的字符串值**截到目标长度并追加 `... [truncated]`（:297-305），保持结构完整（键名、小字段不受影响）；解析失败才退化为整体截断（:312-317）。目标长度用 `max_tokens × 3`（保守取 3 字符/token，:308-309）。

**（e）批处理与容错。** `transform_batch()`（:122-150）默认 `skip_errors=True`：单条变换失败（如缺必填字段抛 TransformationError）收集为 `(record, error)` 对，不中断批次——与 GraphitiIngestor 的逐 episode 报错策略配套。

**（f）TOON 文本格式导出。** `to_toon_format()`（:207-239）把记录渲染回 `TOON.schema: a | b | c` 开头的行式文本（含转义规则，:241-254），主要用于调试——与 C++ `TOONExporter` 的导出格式对齐，方便对照两侧数据。

**（g）家族分工。** 本文件只管 FileRecord → EpisodeData；事件与平台 artifacts 的变换在 `forensic_episode_transformer.py`（ForensicEpisodeTransformer，文件头注明"extracted ... for maintainability"），OSS 对象在 `oss_transformer.py`；前者在本文件尾部 re-export 保持旧导入路径（:319-321）。

## 4. 工作流程走读：files 通道的一次变换

MultiSourcePipeline 拿到一批 FileRecord → `TOONTransformer(include_full_description=config.include_full_description)` 已在管道初始化时构造（pipeline_multi_source.py:137-139）→ `transform(record)`：构造 body dict（基础字段 + 可选 metadata/analysis，:152-196）→ `json.dumps(ensure_ascii=False)` 成 episode_body → 生成 `category:name` 名称与分析时间 → 返回 EpisodeData → 批量交给 GraphitiIngestor（摄取前的 token 闸门见上）。`transform_batch` 的 errors 列表进流水线统计的 transformation_errors。

## 5. 与其他模块的协作

| 模块 | 协作方式 |
|---|---|
| database_reader.FileRecord | 唯一输入类型 |
| GraphitiIngestor | EpisodeData 消费者；token 工具调用方 |
| ForensicEpisodeTransformer / OSSTransformer | 共享 EpisodeData 与同一变换哲学 |
| httpserver GraphitiService | 手工构造 EpisodeData + 复用 token 工具 |
| C++ TOONExporter | 命名与文本格式上的对应物（非代码依赖） |

## 6. 注意事项与已知问题

- token 估算对中文内容会**低估**（4 字符/token 是英文启发式）：中文长描述即便通过 3000 估算也可能实际超模型上下文——必要时调低 `GRAPHITI_MAX_EPISODE_TOKENS`。
- `include_full_description` 默认关闭意味着默认 episode 只有 summary/keywords；若发现图谱实体偏少，第一步检查该开关是否打开（httpserver 侧 `GRAPHITI_INCLUDE_FULL_DESC`）。
- 截断按"每字符串值"进行：一条超长 analysis 被截，但多个中等字段可能合计仍超预算（截断后不复查）；极端数据下保守调低上限。
- 变换器无状态，可全局复用；但开关不同的实例不要混用（episode 丰满度不一致会稀释抽取质量）。

## 7. 如何验证与扩展

- `python_service/graphiti_integration/tests/test_toon_transformer.py`（变换开关、批处理容错、token 工具；单独跑：`python -m pytest graphiti_integration/tests/test_toon_transformer.py`）。
- 手工验证：构造带 5000 字符 llm_description 的 FileRecord → `estimate_episode_tokens` / `truncate_if_needed` 观察截断点与 JSON 结构保持。
- 新记录类型：效仿 ForensicEpisodeTransformer 建独立 transformer，产出同一个 EpisodeData，勿往本文件塞异构逻辑。

**最后更新**: 2026-08-23（解释式重写）
