# GraphitiIngestor（python_service/graphiti_integration/graphiti_ingestor.py）

> **一句话**：Graphiti SDK 的取证专用封装——把 episode 渲染成抽取友好的文本、强制取证实体抽取指令、限制 token 预算、带退避重试地把 episode 灌进 Neo4j，并组装本地 LLM/嵌入/重排三件套。

## 1. 为什么有这个模块

Graphiti（graphiti-core）的默认用法是为通用 RAG 设计的，直接把取证数据丢进去会得到一张几乎空的图：默认抽取提示词**主动丢弃**日期、哈希、ID、路径、IP 这类"通用字段值"——而这恰恰是取证最有价值的实体。GraphitiIngestor 存在的意义就是纠正这组默认行为，并解决本地模型生态的兼容问题。

## 2. 在系统中的位置

- **谁调用它**：httpserver 的 GraphitiService（`_get_task_graph` 为每个 task/case 缓存一个实例）、MultiSourcePipeline（旧摄取路径）、包内测试。
- **它调用谁**：graphiti-core 的 `Graphiti` 客户端（`add_episode` / `build_indices_and_constraints`）、`OpenAIGenericClient`（实体抽取，被 llm_patch 修补）、`OpenAIEmbedder`（nomic 系，dim 768）、`OpenAIRerankerClient`（重排）；Neo4j。
- **输入/输出**：吃 `EpisodeData`（toon_transformer.py:17），吐 `IngestionResult`（graphiti_ingestor.py:75-93，successful/failed/errors 逐条记录）。

## 3. 核心数据结构

```python
# graphiti_ingestor.py:75-93
@dataclass
class IngestionResult:
    """Result of an ingestion operation."""

    total_episodes: int = 0
    successful: int = 0
    failed: int = 0
    errors: list = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []

    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage."""
        if self.total_episodes == 0:
            return 0.0
        return (self.successful / self.total_episodes) * 100
```

- `total_episodes`：本批 episode 总数，构造时由 `batch_ingest` 以 `len(episodes)` 传入；
- `successful` / `failed`：逐条累加，二者之和恒等于 total（没有"半成功"状态）；
- `errors`：**逐条失败明细**列表，元素是 `{"episode": 名, "file_path": 路径, "error": 错误串}`（:433-437）——`file_path` 字段来自 EpisodeData 的回溯字段，供上层（ingest_task_episodes）把失败定位回具体文件；
- `success_rate`：派生属性，仅供日志（`Batch ingestion complete: X/Y (Z%)`，:453-456）。

## 4. 核心接口清单

| 方法（真实签名） | 语义 | 主要调用方 | 失败行为 |
|---|---|---|---|
| `async initialize() -> None` | 构造 Graphiti 客户端三件套并 `build_indices_and_constraints()` | GraphitiService._get_task_graph、batch/ingest 前置自检 | 抛异常（Neo4j/LLM 端点不可达），由上层 initialized-but-disabled 降级兜住 |
| `async ingest_episode(episode: EpisodeData, group_id: Optional[str] = None) -> bool` | 渲染→限 token→重试 `add_episode` | batch_ingest 循环体 | 重试耗尽抛 `IngestionError` |
| `async batch_ingest(episodes: list[EpisodeData], group_id=None, progress_callback=None) -> IngestionResult` | 顺序摄取一批并记账 | GraphitiService.ingest_task_episodes、MultiSourcePipeline | 单条失败进 result.errors，不中断批次 |
| `_render_episode_for_extraction(episode) -> tuple[str, EpisodeType]`（静态） | JSON body → `# 标题` + `Field: value` 文本 | ingest_episode / _validate_and_prepare | 解析失败按纯文本原样返回 |
| `_validate_and_prepare_episode(episode) -> tuple[str, bool]` | 渲染 + token 预算 + 截断，返回 (body, was_truncated) | 需要独立预检体的调用方 | 只告警不抛 |
| `async close() -> None` | 关闭自有 LLM/embedder 连接池与 Graphiti 驱动 | GraphitiService.shutdown、`__aexit__` | 收集全部异常后抛第一个 |
| `__aenter__ / __aexit__` | async 上下文管理器（initialize/close） | CLI/测试 | 同上 |

## 5. 核心概念与设计

**（a）FORENSIC_EXTRACTION_INSTRUCTIONS——本模块的灵魂。** 一段注入 `add_episode(custom_extraction_instructions=...)` 的指令（:42-72），逐条点名要"慷慨抽取"的实体类型，并要求用 SCREAMING_SNAKE_CASE 谓词建关系。关键片段：

```python
# graphiti_ingestor.py:46-57（节选）
EXTRACT these entities liberally (they are NOT "generic values" here):
- Usernames, account names, group names (e.g. "Administrator", "root", "nobody")
- Hostnames, computer names, domain names, workgroup names
- IP addresses, MAC addresses, SSIDs, network share paths
- File paths and file names (full paths are meaningful identifiers here)
- Registry key paths, service names, scheduled task names
- Executable / process names (e.g. "cmd.exe", "powershell.exe", "svchost.exe")
# ...
- MD5 / SHA hashes and file-inode references as Identifier entities
- Event IDs, log source names (e.g. "Security", "Syslog")
```

代码注释（:29-41）讲清了动机：Graphiti 默认 `extract_json` 提示词明令"NEVER extract dates/hashes/IDs"——这是"取证图谱近乎为空"这个历史上最大问题的根因。指令后半段（:59-68）给出关系谓词范例（`USER LOGGED_IN_FROM IP`、`HASH_IDENTIFIES FILE` 等），这正是前端可视化所依赖的 RELATES_TO 边的来源。

**（b）JSON → 文本渲染。** `_render_episode_for_extraction()`（:195-238）把 episode_body 从 JSON 字符串渲染成文本并以 `EpisodeType.text` 摄取：

```python
# graphiti_ingestor.py:218-233
body = episode.episode_body or ""
try:
    data = json.loads(body)
    if isinstance(data, dict):
        lines = []
        # Header gives the extractor strong semantic context.
        title = episode.name or data.get("category") or "Forensic analysis"
        lines.append(f"# {title}")
        for key, value in data.items():
            if value is None or value == "":
                continue
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            lines.append(f"{key}: {value}")
        rendered = "\n".join(lines)
        return rendered, EpisodeType.text
    # Non-dict JSON (list/scalar): fall back to the raw text.
    return body, EpisodeType.text
except (json.JSONDecodeError, TypeError):
    # Already plain text — ingest as text unchanged.
    return body, EpisodeType.text
```

三个要点：`# 标题` 行给抽取器强语义锚点；空值键被跳过（不产生 `field: ` 噪声行）；嵌套 dict/list（如 metadata/analysis 子对象）二次 `json.dumps` 后作为值出现在同一行——结构信息不丢，路径/哈希/用户名对抽取器保持"一等公民"。原因（:199-213 注释）：json 源会选择 `extract_json` 提示词（丢弃见上），text 源走 `extract_text`，对自由文本的命名实体抽取宽松得多。

**（c）token 预算与截断。** `ingest_episode()`（:330-401）在**渲染后的文本**上执行 `max_episode_tokens`（默认 3000）：

```python
# graphiti_ingestor.py:357-361
rendered_body, source_type = self._render_episode_for_extraction(episode)
max_tokens = self.config.max_episode_tokens
if TOONTransformer.estimate_episode_tokens(rendered_body) > max_tokens:
    rendered_body = TOONTransformer.truncate_if_needed(rendered_body, max_tokens)
    logger.debug(f"Truncated rendered body for '{episode.name}' to ~{max_tokens} tokens")
```

估算用 `TOONTransformer.estimate_episode_tokens`（~4 字符/token + 20% 缓冲），截断用 `truncate_if_needed` 做 JSON 感知的按值截断（工具详见 [TOONTransformer.md](../graphiti_integration/TOONTransformer.md)）。这是对本地模型 8K 上下文的保护。注意截断发生在渲染文本上，因此截断的是整段 `analysis: ...` 行，而非原始 JSON 值。

**（d）重试与逐条报错。** 每个 episode 最多 `GRAPHITI_MAX_RETRIES`（默认 3）次尝试，退避 `retry_delay × (attempt + 1)`（:364-397）：

```python
# graphiti_ingestor.py:379-397（节选）
await self._client.add_episode(
    name=episode.name,
    episode_body=rendered_body,
    source_description=episode.source_description,
    reference_time=episode.reference_time,
    source=source_type,
    group_id=group_id,
    custom_extraction_instructions=FORENSIC_EXTRACTION_INSTRUCTIONS,
)
return True
# except 分支：
if attempt < self.config.max_retries - 1:
    await asyncio.sleep(self.config.retry_delay * (attempt + 1))
# 循环耗尽后：
raise IngestionError(
    f"Failed to ingest episode {episode.name} after {self.config.max_retries} attempts: {last_error}"
)
```

`add_episode` 的六个参数各司其职：`name` 是 episode 显示名（"文件分析: /path"）、`source_description` 记录来源、`reference_time` 供 Graphiti 建时间线索、`group_id` 是 Neo4j 命名空间（任务隔离的关键）、`custom_extraction_instructions` 覆盖默认抽取行为。`batch_ingest()`（:403-458）捕获每个 episode 的失败进 `result.errors`，**不因单条失败中断整批**——调用方据此向用户暴露"图为什么稀疏"。

**（e）客户端组装与资源所有权。** `initialize()`（:240-290）：本地模式显式构造三件套——OpenAIGenericClient（small_model 与主模型相同，:127）、OpenAIEmbedder（`EMBEDDING_BASE_URL` 可与聊天 LLM 分离，例如云端聊天 + 本地 nomic 嵌入；dim 取配置，:132-155）、OpenAIRerankerClient（复用聊天客户端，:260-268）——然后 `build_indices_and_constraints()`（:288）建索引/约束：

```python
# graphiti_ingestor.py:270-277
self._client = Graphiti(
    uri=self.config.neo4j_uri,
    user=self.config.neo4j_user,
    password=self.config.neo4j_password,
    llm_client=llm_client,
    embedder=embedder,
    cross_encoder=cross_encoder,
)
```

`close()`（:292-328）区分"自有资源"（初始化时创建的客户端，需逐一关闭）与"外部注入的 Graphiti 实例"（调用方自负其责）——注释标明这是 D4b 资源治理决策。

**（f）llm_patch 的导入时序。** 文件头（:12-13）在任何 `graphiti_core` 导入前 `apply_patch()`——修补 `OpenAIGenericClient._generate_response` 清洗 `<think>` 标签/markdown 围栏、失败时去 `response_format` 加 `/no_think` 重试（详见 [../graphiti/GraphitiIntegration.md](../graphiti/GraphitiIntegration.md) 第 4(b) 节）。换用 qwen3/deepseek-r1 类推理模型时这个补丁是硬前提。

## 6. 关联配置（env 全表）

| env（GraphitiConfig.from_env 读取） | 默认值 | 作用 |
|---|---|---|
| `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` | `neo4j://127.0.0.1:7687` / `neo4j` / 空 | 图存储连接 |
| `LLM_TEXT_BASE_URL` / `LLM_TEXT_MODEL` / `LLM_API_KEY` | `http://192.168.31.170:1234/v1` / `openai/gpt-oss-20b` / `local` | 抽取 LLM（from_env 自动补 `/v1` 后缀） |
| `EMBEDDING_BASE_URL` / `EMBEDDING_MODEL` / `EMBEDDING_API_KEY` | None（回落 LLM 端点）/ `text-embedding-nomic-embed-text-v1.5` / 回落 OPENAI_API_KEY | 嵌入端点可独立于聊天 LLM |
| `EMBEDDING_DIM` | 768 | 向量维度，**必须与模型匹配** |
| `GRAPHITI_BATCH_SIZE` / `GRAPHITI_MAX_RETRIES` / `GRAPHITI_GROUP_ID` | 10 / 3 / `forensics_files` | 批大小（从 50 调低防 token 溢出）、重试、默认命名空间 |
| `GRAPHITI_MAX_EPISODE_TOKENS` / `GRAPHITI_INCLUDE_FULL_DESC` / `GRAPHITI_USE_LOCAL_LLM` | 3000 / false / true | 单 episode 预算、长描述开关、本地模式 |

httpserver 侧由 `_build_graphiti_config` 显式构造同名参数（Settings 别名一致），两条配置路径语义对齐。

## 7. 工作流程走读：一个 episode 的入库

调用方给出 `EpisodeData`（name、JSON body、group_id=task_id）→ `ingest_episode()` 渲染为文本（:357）→ 估算 token，必要时截断（:358-361）→ 重试循环内 `add_episode(...)`（:379-387）→ Graphiti 内部：LLM 抽实体与 RELATES_TO 边、embedder 生成向量、写入 Neo4j（group_id 命名空间）→ 成功返回 True；失败退避重试，最终抛 IngestionError，由 batch_ingest 记账。

## 8. 与其他模块的协作

| 模块 | 协作方式 |
|---|---|
| GraphitiService（httpserver） | 实例的创建/缓存方；search 路径借用其 `_client` |
| toon_transformer.TOONTransformer | token 估算与截断工具来源；EpisodeData 类型来源 |
| llm_patch | 模块导入即生效的 SDK 兼容层 |
| config.GraphitiConfig | 全部参数（模型、嵌入、重试、token 上限、group_id） |
| MultiSourcePipeline | 旧摄取路径的批量调用方 |

## 9. 注意事项与已知问题

- 换嵌入模型必须同步 `EMBEDDING_DIM`（默认 768 对应 nomic-embed-v1.5），否则索引维度不匹配。
- `batch_ingest` 是顺序逐条（无并发）——大批量耗时 ≈ episode 数 × 单次抽取延迟；进度靠 progress_callback。
- `include_full_description=False`（配置默认）时长描述不进 episode；httpserver 可用 `GRAPHITI_INCLUDE_FULL_DESC=true` 打开换取更丰富的抽取。
- 抽取质量依赖本地模型能力：模型太小会出现 JSON 解析失败重试链（llm_patch 的第二次尝试），日志里出现 "Retrying without response_format" 是征兆。
- `close()` 任一资源关闭失败会抛第一个异常（:327-328）——关闭路径的异常应被调用方容忍（GraphitiService.shutdown 即如此）。
- 截断后不复查（truncate_if_needed 逐字符串值截断，多个中等字段合计仍可能超预算）；中文内容下 4 字符/token 估算偏低，极端数据需调低上限。

## 10. 如何验证与扩展

- `python_service/graphiti_integration/tests/test_graphiti_ingestor.py`（渲染、截断、重试、结果记账；单独跑：`python -m pytest graphiti_integration/tests/`）。
- httpserver 侧回归：`tests/unit/test_graphiti_integration_fixes.py`。
- 调整抽取行为：改 `FORENSIC_EXTRACTION_INSTRUCTIONS`（:42）即可，无需动 Graphiti 版本；抽取效果验证用固定 episode + 小模型目检节点数。
- 手工验证：构造 3 个含用户名/IP/路径的 EpisodeData → batch_ingest → Neo4j Browser 按 group_id 查 Entity 数量。

## 11. 二轮深化 A：抽取指令的实体类型与关系谓词全表

FORENSIC_EXTRACTION_INSTRUCTIONS（:42-72）点名 **11 类实体**与 **8 个关系谓词范例**：

| 实体类别 | 示例（指令原文） |
|---|---|
| 账户 | usernames/account/group（Administrator、root、nobody） |
| 主机 | hostname/computer/domain/workgroup |
| 网络 | IP、MAC、SSID、share path |
| 文件 | **全路径**与文件名（明示"full paths are meaningful identifiers"） |
| 注册表/服务 | key path、service name、scheduled task |
| 进程 | cmd.exe、powershell.exe、svchost.exe |
| 通信 | URL、domain、email、phone |
| 设备 | USB 名称、vendor/product ID、serial |
| 标识 | **MD5/SHA 哈希与 inode 作 Identifier 实体** |
| 软件 | 应用/包名与版本 |
| 日志 | Event ID、log source（Security、Syslog） |

| 关系谓词（SCREAMING_SNAKE） | 语义 |
|---|---|
| USER_ACCOUNT ACCESSED FILE | 账户↔文件 |
| PROCESS EXECUTED_FILE | 进程↔文件 |
| HOST CONNECTED_TO IP / DOMAIN | 主机↔网络 |
| USER LOGGED_IN_FROM IP | 登录溯源 |
| DEVICE_MOUNTED_AS DRIVE | 设备挂载 |
| APPLICATION ACCESSED URL | 应用↔URL |
| REGISTRY_KEY REFERENCES PATH | 注册表↔路径 |
| HASH_IDENTIFIES FILE | 哈希↔文件（去重基础） |

注意这 8 个谓词是**范例而非白名单**（"such as"）——LLM 可自造谓词；前端的关系类型过滤（`r.name = $rt`）因此是开放枚举。改指令只影响新摄取的 episode，已入库的旧边不会重抽。

## 12. 二轮深化 B：EpisodeData 字段契约（toon_transformer.py:17-36）

| 字段 | 类型 | 谁写 | 消费方 |
|---|---|---|---|
| name | str | transformer（episode 显示名） | add_episode(name)、失败记账 |
| episode_body | str（**JSON 串**） | transformer | 渲染器 json.loads |
| source_description | str | transformer | add_episode 溯源 |
| reference_time | datetime | transformer | Graphiti 时间线 |
| file_path / file_id | str/int | transformer（回溯锚） | IngestionResult.errors 定位回文件 |
| category | Optional[str] | transformer（saga 分组） | 渲染标题回退（`data.get("category")`） |

关键约束：`episode_body` 必须是 JSON 字符串——渲染器对非 dict JSON（list/标量）回退原文摄取（:234-237），语义降级但不失败；`file_path` 让"图稀疏"排查能从 errors 直接映射回 files.db 行。

## 13. 二轮深化 C：新走读——close() 的自有/注入资源分治（:292-328）

```python
# graphiti_ingestor.py:292-328（骨架）
errors = []
for resource in (self._owned_llm_client, self._owned_embedder):
    if resource is None:
        continue
    close = getattr(resource, "aclose", None) or getattr(resource, "close", None)
    try:
        result = close()
        if asyncio.iscoroutine(result):
            await result
    except Exception as exc:
        errors.append(exc)
self._owned_llm_client = None
self._owned_embedder = None
if self._client:
    try:
        await self._client.close()
    except Exception as exc:
        errors.append(exc)
    finally:
        self._client = None
        self._initialized = False
if errors:
    raise errors[0]
```

逐块解释：① **只关自有资源**——`_owned_*` 是 initialize() 里创建的客户端；调用方注入的 Graphiti 实例（若构造时传入）归调用方关，双关会 use-after-close；② `aclose or close` 双协议探测——httpx 系客户端用 aclose、部分 SDK 用同步 close，两种都兼容，同步 close 直接调用、异步的 await；③ **收集全部异常但只抛第一个**——一个资源关失败不阻断其余回收（对比 ServiceManager._rollback 的同款策略）；④ finally 里无论成败都置 `_client=None/_initialized=False`——半关状态的实例复用会显式失败而不是静默错用。

## 14. 二轮深化 D：重试时间线与最坏耗时表

| 尝试 | 前置退避（attempt 从 0 计） | 单次最坏（LLM 120s 超时传导） |
|---|---|---|
| 1（attempt 0） | 0 | 120s |
| 2（attempt 1） | retry_delay×1（默认 1s） | 120s |
| 3（attempt 2） | retry_delay×2（2s） | 120s |
| 耗尽 | — | 抛 IngestionError |

单 episode 最坏 ≈ 363s + 渲染/嵌入时间；N 条全失败的批次最坏 ≈ N×363s（顺序无并发）——这就是第 9 节"大批量耗时"的量化表达。退避是**线性**（×attempt）而非指数；想更激进可调小 `LLM_TIMEOUT_SECONDS`，但会同时影响 httpserver 的所有 LLM 调用（耦合点在 GraphitiService 复用同一 Settings 值——见 GraphitiService.md 第 5 节）。

**最后更新**: 2026-08-24（二轮深化：补全端点清单与模型契约）
