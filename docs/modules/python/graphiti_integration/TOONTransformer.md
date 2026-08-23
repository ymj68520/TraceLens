# TOONTransformer（python_service/graphiti_integration/toon_transformer.py）

> **一句话**：数据变换枢纽——定义贯穿全链路的 `EpisodeData` 结构，把 `FileRecord` 变成可被 LLM 抽实体的 episode（带开关控制元数据/分析字段），并提供 token 估算与截断这两个摄取安全的基石工具。

## 1. 为什么有这个模块

"一条数据库记录"和"一段能让 LLM 抽实体的文本"之间需要一层显式变换：哪些字段进、哪些不进（大描述可能 3000+ 字符）、以什么结构表达、超长怎么办。命名致敬 C++ 侧的 `TOONExporter`（同为"表格 → 结构化文本"的思路），但产物不是导出文件而是内存中的 `EpisodeData`。把这一层独立出来，读取（reader）、摄取（ingestor）才能各自演进。

## 2. 在系统中的位置

- **谁调用它**：`MultiSourcePipeline`（files 通道的变换器，pipeline_multi_source.py:137-139）、`GraphitiPipeline`（CLI 路径）、httpserver 的 GraphitiService（只用 `EpisodeData` 类型与 token 工具，任务级 episode 在服务层手工构造）；`ForensicEpisodeTransformer`/`OSSTransformer` 复用 EpisodeData。
- **它调用谁**：只依赖 `database_reader.FileRecord` 与标准库——纯函数层，无 I/O 副作用。

## 3. 核心数据结构：EpisodeData

```python
# toon_transformer.py:17-47
@dataclass
class EpisodeData:
    """
    Data structure representing a Graphiti episode.

    Each episode corresponds to a file record with LLM analysis,
    formatted for knowledge graph ingestion.
    """

    # Episode metadata
    name: str
    episode_body: str  # JSON string
    source_description: str
    reference_time: datetime

    # Original record reference
    file_path: str
    file_id: int

    # Optional: for saga grouping
    category: Optional[str] = None

    @property
    def as_dict(self) -> dict:
        """Convert to dictionary for Graphiti add_episode()."""
        return {
            "name": self.name,
            "episode_body": self.episode_body,
            "source_description": self.source_description,
            "reference_time": self.reference_time,
        }
```

逐字段：`name` 是 episode 显示名（本变换器产出 `category:文件名`；httpserver 侧则是"文件分析: /path"本地化名）；`episode_body` 是 **JSON 字符串**（不是 dict——GraphitiIngestor 渲染时会重新 loads）；`source_description` 记录来源语义（"forensics_file_analysis"）；`reference_time` 进入 Graphiti 的时间线索；`file_path`/`file_id` 是回溯字段，只在失败记账（IngestionResult.errors 的 file_path）里被消费；`category` 供 saga 分组（当前无人使用）。它是全链路的通用货币——文件、事件簇、案情描述、OSS 对象四类 episode 都以它进入 `batch_ingest`（httpserver 的 ingest_task_episodes 手工构造它：graphiti_parts/_ingest.py:105、:266、:312）。

## 4. 核心接口清单

| 方法（真实签名） | 语义 | 主要调用方 | 失败行为 |
|---|---|---|---|
| `transform(record: FileRecord) -> EpisodeData` | 单条记录 → episode（body 构造 + 命名 + 时间） | transform_batch、流水线循环 | 任何异常包成 `TransformationError` |
| `transform_batch(records, skip_errors=True) -> tuple[list[EpisodeData], list[tuple[FileRecord, Exception]]]` | 批量变换，失败收集为 (record, error) 对 | MultiSourcePipeline | skip_errors=False 时首个错误上抛 |
| `_build_episode_body(record) -> dict` | 组装 body：基础字段 + 可选 metadata/analysis | transform | 不抛（字段全部容错取值） |
| `to_toon_format(records) -> str` | 渲染回 TOON 行式文本（调试用） | 调试/对照 | 不抛 |
| `estimate_episode_tokens(episode_body: str) -> int`（静态） | ~4 字符/token + 20% 缓冲 | GraphitiIngestor 预算闸门 | 不抛 |
| `truncate_if_needed(episode_body, max_tokens=3000) -> str`（静态） | JSON 感知截断 | GraphitiIngestor | 解析失败退化为整体截断 |

## 5. 核心概念与设计

**（a）三个内容开关。** 构造参数（:58-77）决定 episode_body 的丰满程度：`include_metadata`（size/md5/is_deleted/时间戳进 `metadata` 子对象）、`include_analysis`（llm_summary/keywords/model 进 `analysis` 子对象）、`include_full_description`（**默认 False**——完整 llm_description 可达 3000+ 字符，是否值得为更丰富的抽取付出 token 由配置决定，httpserver 的 `GRAPHITI_INCLUDE_FULL_DESC` 对应）。body 的组装逻辑：

```python
# toon_transformer.py:159-196（节选）
body = {
    "file_name": record.name,
    "file_path": record.path,
    "category": record.category,
    "file_extension": record.extension,
}

if self.include_metadata:
    body["metadata"] = {
        "size_bytes": record.size,
        "md5_hash": record.md5,
        "is_deleted": record.is_deleted,
        "file_type": record.file_type,
    }
    # Add timestamps if available
    if record.mtime_datetime:
        body["metadata"]["modified_at"] = record.mtime_datetime.isoformat()
    # ...

if self.include_analysis and record.has_llm_analysis:
    body["analysis"] = {}
    if record.llm_summary:
        body["analysis"]["summary"] = record.llm_summary
    # Only include full description if explicitly enabled (can be 3000+ chars)
    if self.include_full_description and record.llm_description:
        body["analysis"]["description"] = record.llm_description
    if record.llm_keywords:
        body["analysis"]["keywords"] = record.keywords_list
```

结构是分层的（基础字段平铺、元数据/分析各归子对象），渲染成 `Field: value` 文本后每个键（含子对象的键，二次 json.dumps 成一行）都成为抽取器可见的一行内容——md5_hash、category 正是默认提示词会丢弃的高价值信号。

**（b）episode 名与分析时间。** 名字取 `category:文件名`（:198-205，category 缺省 "file"、name 缺省 `file_{id}`）；reference_time 优先用 LLM 分析时间：

```python
# toon_transformer.py:100-105
if record.llm_analyzed_at and record.llm_analyzed_at > 0:
    reference_time = datetime.fromtimestamp(
        record.llm_analyzed_at, tz=timezone.utc
    )
else:
    reference_time = datetime.now(timezone.utc)
```

用分析时间而非文件 mtime 的含义：episode 代表"一次分析行为"而非"文件本身的年代"，Graphiti 的时间衰减检索按分析时间排布。

**（c）token 估算：~4 字符/token 启发式。** `estimate_episode_tokens()`（:256-272）按"1 token ≈ 4 英文字符"估算再加 20% 缓冲（容纳 JSON 结构开销）：

```python
# toon_transformer.py:270-272
# Rough estimate: 1 token ≈ 4 characters for English text
# Add 20% buffer for JSON structure and metadata
return int(len(episode_body) / 4) + (len(episode_body) // 20)
```

它不精确（中文约 1-2 字符/token），但作为**预算闸门**足够——GraphitiIngestor 用它决定是否截断（graphiti_ingestor.py:358-361），`GRAPHITI_MAX_EPISODE_TOKENS=3000` 由此落到实际字节。

**（d）JSON 感知截断。** `truncate_if_needed()`（:274-317）超预算时不是粗暴砍字符串：先 `json.loads`，递归地把**过长的字符串值**截到目标长度并追加 `... [truncated]`，保持结构完整：

```python
# toon_transformer.py:297-309（节选）
def truncate_strings(obj, max_chars: int = 500):
    """Recursively truncate string values in dict/list."""
    if isinstance(obj, dict):
        return {k: truncate_strings(v, max_chars) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [truncate_strings(item, max_chars) for item in obj]
    elif isinstance(obj, str) and len(obj) > max_chars:
        return obj[:max_chars] + "... [truncated]"
    return obj

# Target: ~4 chars per token, so max_chars = max_tokens * 4
max_chars = max_tokens * 3  # Conservative: 3 chars per token
truncated = truncate_strings(data, max_chars)
return json.dumps(truncated, ensure_ascii=False)
```

注意目标长度按 `max_tokens × 3`（保守取 3 字符/token，注释与代码不一致是刻意的保守化）；解析失败才退化为整体截断（:312-317）。

**（e）批处理与容错。** `transform_batch()`（:122-150）默认 `skip_errors=True`：单条变换失败（如缺必填字段抛 TransformationError）收集为 `(record, error)` 对，不中断批次——与 GraphitiIngestor 的逐 episode 报错策略配套，errors 列表进流水线统计的 transformation_errors。

**（f）TOON 文本格式导出。** `to_toon_format()`（:207-239）把记录渲染回 `TOON.schema: a | b | c` 开头的行式文本（含转义规则 `|"\n\r,` 触发引号包裹，:241-254），主要用于调试——与 C++ `TOONExporter` 的导出格式对齐，方便对照两侧数据。

**（g）家族分工。** 本文件只管 FileRecord → EpisodeData；事件与平台 artifacts 的变换在 `forensic_episode_transformer.py`（ForensicEpisodeTransformer，文件头注明"extracted ... for maintainability"），OSS 对象在 `oss_transformer.py`；前者在本文件尾部 re-export 保持旧导入路径（:319-321）。

## 6. 工作流程走读：files 通道的一次变换

MultiSourcePipeline 拿到一批 FileRecord → `TOONTransformer(include_full_description=config.include_full_description)` 已在管道初始化时构造（pipeline_multi_source.py:137-139）→ `transform(record)`：构造 body dict（基础字段 + 可选 metadata/analysis，:152-196）→ `json.dumps(ensure_ascii=False)` 成 episode_body → 生成 `category:name` 名称与分析时间 → 返回 EpisodeData → 批量交给 GraphitiIngestor（摄取前的 token 闸门见上）。`transform_batch` 的 errors 列表进流水线统计。

## 7. 与其他模块的协作

| 模块 | 协作方式 |
|---|---|
| database_reader.FileRecord | 唯一输入类型 |
| GraphitiIngestor | EpisodeData 消费者；token 工具调用方 |
| ForensicEpisodeTransformer / OSSTransformer | 共享 EpisodeData 与同一变换哲学 |
| httpserver GraphitiService | 手工构造 EpisodeData + 复用 token 工具 |
| C++ TOONExporter | 命名与文本格式上的对应物（非代码依赖） |

## 8. 注意事项与已知问题

- token 估算对中文内容会**低估**（4 字符/token 是英文启发式）：中文长描述即便通过 3000 估算也可能实际超模型上下文——必要时调低 `GRAPHITI_MAX_EPISODE_TOKENS`。
- `include_full_description` 默认关闭意味着默认 episode 只有 summary/keywords；若发现图谱实体偏少，第一步检查该开关是否打开（httpserver 侧 `GRAPHITI_INCLUDE_FULL_DESC`）。
- 截断按"每字符串值"进行：一条超长 analysis 被截，但多个中等字段可能合计仍超预算（截断后不复查）；极端数据下保守调低上限。
- 变换器无状态，可全局复用；但开关不同的实例不要混用（episode 丰满度不一致会稀释抽取质量）。

## 9. 如何验证与扩展

- `python_service/graphiti_integration/tests/test_toon_transformer.py`（变换开关、批处理容错、token 工具；单独跑：`python -m pytest graphiti_integration/tests/test_toon_transformer.py`）。
- 手工验证：构造带 5000 字符 llm_description 的 FileRecord → `estimate_episode_tokens` / `truncate_if_needed` 观察截断点与 JSON 结构保持。
- 新记录类型：效仿 ForensicEpisodeTransformer 建独立 transformer，产出同一个 EpisodeData，勿往本文件塞异构逻辑。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
