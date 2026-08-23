# LLMService（python_service/httpserver/services/llm/ 子包，门面 services/llm_service.py）

> **一句话**：AI 分析的编排层——持有 text/vision 两个 OpenAI 兼容客户端，把单文件、图像、批量、事件簇分析委托给三个子模块，并把结果直接回写 C++ 产出的 `_files.db` / `_events.db`（fail-closed）。

## 1. 为什么有这个模块

系统需要一个统一的"跟推理端点说话"的地方：模型端点与参数来自配置（text/vision 分离）、请求要发到 OpenAI 兼容的 `/v1/chat/completions`、结果要按取证语义（description/summary/keywords/is_relevant）解析、并且要落回 C++ 生成的 SQLite（让 C++ 的报告链路和 Python 的图谱链路共享同一份分析结果）。LLMService 把这四件事集中起来，路由与上层服务只面对稳定的 Python API。

## 2. 在系统中的位置

- **谁调用它**：routes/llm_endpoints（analyze/batch/事件簇/模型状态）、case_analysis 文件分析器、SecondaryAnalysis 与 EventRefresh 执行器（chat_completion）、ReportGenerationExecutor（llm_service 可为 None，提交以 `llm_unavailable` 持久失败）。
- **它调用谁**：本地/远端 OpenAI 兼容推理服务（`LLM_TEXT_BASE_URL` / `LLM_VISION_BASE_URL`）；SQLite（C++ 产出的 `<image>_files.db`、`<image>_events.db`）。
- **结构**：`services/llm_service.py` 只是向后兼容的 re-export 门面（llm_service.py:15-17）；实现都在 `services/llm/` 子包：`llm_service.py`（编排+持久化）、`file_analyzer.py`、`model_manager.py`、`event_analyzer.py`。
- **链路**：前端"AI 分析"按钮 → `/api/llm/batch`（task_store 门卫）→ 本服务批量作业 → `_files.db` llm_* 列 → GraphitiService 摄取 episode / C++ 报告链读取。

## 3. 核心数据结构：持久化目标表

LLM 分析结果落在两张 C++ 侧已有/惰性补建的表上。`file_descriptions` 由本服务负责补齐 schema（llm/llm_service.py:98-116）：

```python
# httpserver/services/llm/llm_service.py:98-108（节选）
cur.execute("""
    CREATE TABLE IF NOT EXISTS file_descriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_path TEXT UNIQUE,
        description TEXT,
        summary TEXT,
        keywords TEXT,
        model_used TEXT,
        is_relevant INTEGER DEFAULT 1,
        created_at INTEGER
    )
""")
# 之后 PRAGMA table_info 检查并 ALTER TABLE 补 is_relevant 列（:112-116）
```

- `file_path`：**UNIQUE 冲突键**，存规范化后的证据路径——它是描述表与 files 表的身份桥梁；
- `description` / `summary` / `keywords`：LLM 三件套（summary 兜底为 description 前 200 字）；
- `model_used` / `created_at`：可审计性（哪个模型、何时分析）；
- `is_relevant`：人工/流水线相关性开关，`set_file_relevance` 切换它；被标 0 的文件不进最终报告，但**仍是图谱 episode 的候选**（ingest 只看 description 非空）。

events 表的 llm 列由 `_ensure_events_schema`（:220-230）逐列 `ALTER TABLE ... ADD COLUMN`（重复添加靠 OperationalError 静默吞掉），列集是 `llm_summary/llm_description/llm_keywords/llm_analyzed_at/llm_model_used/llm_is_relevant`。

## 4. 核心接口清单

| 方法（真实签名） | 语义 | 调用方 | 失败行为 |
|---|---|---|---|
| `async initialize()` | 创建 text/vision 两个 httpx.AsyncClient（120s 超时） | ServiceManager | 不做 ping，几乎不会失败 |
| `persist_to_files_db(db_path, file_path, description, summary, keywords, model_used="") -> bool` | fail-closed 两步写入 `_files.db` | FileAnalyzer 持久化回调 | 目标库缺失/路径不匹配→False |
| `persist_to_events_db(db_path, event_id, description, summary, keywords, model_used="", is_relevant=True) -> bool` | 按 event_id 更新事件簇 LLM 列 | EventAnalyzer | 库缺失/无命中行→False |
| `set_file_relevance(db_path, file_path, is_relevant: bool) -> bool` | 切换 file_descriptions.is_relevant | 前端相关性按钮路由 | 库缺失→False |
| `async analyze(content, model_type="text", ...) -> dict` | 预定义 system prompt 的结构化分析 | routes/llm_endpoints、case_analysis | 解析失败抛/返回错误结构 |
| `async analyze_image(image_path, ...) -> dict` | vision 通道（含压缩） | 同上 | 同上 |
| `async chat_completion(system_prompt, user_prompt, ...) -> str` | 裸通道：调用方全控两条消息 | SecondaryAnalysis/EventRefresh/ReportGeneration 执行器 | 异常上抛给执行器分类为稳定 error_code |
| `async start_batch_analysis(files, ..., files_db_path, extraction_dir) -> str` | 注册内存作业并起后台任务 | `/api/llm/batch` | 立即失败抛出 |
| `get_batch_status(batch_id) -> Optional[dict]` | 读内存作业进度 | 前端轮询 | 重启后 None→路由 404 |

## 5. 核心概念与设计

**（a）两个客户端、零网络初始化。** `initialize()`（llm/llm_service.py:59-77）只创建两个 `httpx.AsyncClient`——text 指向 `LLM_TEXT_BASE_URL`、vision 指向 `LLM_VISION_BASE_URL`，超时统一 `LLM_TIMEOUT_SECONDS=120s`。不做任何 ping，所以启动几乎不可能失败（ServiceManager 里它没有 12s 上限的烦恼）。模型名/温度/max_tokens 全部来自 Settings（config.py:172-184）。

**（b）委托而非继承。** 服务本体是编排壳：`analyze` → `FileAnalyzer.analyze_file`（:316-344），`analyze_image` → 同一分析器（:346-364），模型状态 → `ModelManager`（:459-473），事件簇 → `EventAnalyzer`（:479-506）。子模块无状态、客户端由服务传入，这使测试可以注入假客户端。

**（c）`chat_completion()`——留给受控提示的裸通道。** 与 `analyze` 不同，它不注入预定义 system prompt，调用方完全掌控两条消息（:366-421）。这是为 Secondary Analysis（提示词带版本绑定）开的口子；新代码若不需要精确控制提示，优先用 `analyze`。

**（d）持久化：fail-closed 与两步写入。** `persist_to_files_db()`（:118-218）是本服务最需要读懂的方法：

```python
# httpserver/services/llm/llm_service.py:141-148
# Fail-closed: never fall back to another DB (e.g. build/test_image_files.db).
# A missing target DB is a genuine error — refuse to write anywhere else.
if not db_path or not Path(db_path).exists():
    logger.warning(
        f"persist_to_files_db: target db not found at {db_path!r}; "
        "refusing to write anywhere else (fail-closed)"
    )
    return False
```

```python
# httpserver/services/llm/llm_service.py:156-186（节选）
update_files_sql = """
    UPDATE files SET
        llm_summary = ?, llm_description = ?, llm_keywords = ?,
        llm_analyzed_at = ?, llm_model_used = ?
    WHERE path = ?
"""
# 1) Update the main files table FIRST and require an exact match on
#    the canonical path. Only proceed if the Evidence row really exists.
cur.execute(update_files_sql, (
    summary or description[:200], description, keywords,
    int(time.time()), model_used, norm_path,
))
if cur.rowcount <= 0:
    logger.warning(
        f"Path match failed for {file_path!r} "
        f"(normalized: {norm_path!r}) in {db_path!r}"
    )
    return False
```

三步语义：**fail-closed**（库不存在直接 False，绝不回退写别的库——历史上曾静默写 `build/test_image_files.db`）；**路径规范化**（`normalize_evidence_path()` 把反斜杠/重复分隔符对齐到 files.path 规范形式，:154）；**两步写入**（先 `UPDATE files ... WHERE path = ?` 且要求 `rowcount > 0` 确认证据行存在，:156-186，然后才 upsert `file_descriptions`，:190-208——描述表永远不领先于证据表）。upsert 用 `ON CONFLICT(file_path) DO UPDATE SET ...`，重复分析覆盖旧描述但保留行身份。`persist_to_events_db()`（:232-283）按 event_id 更新 events 表并自动补齐缺失列；`set_file_relevance()`（:285-306）切换 `file_descriptions.is_relevant`，被标记无关的文件不进最终报告。

**（e）批量作业：顺序、先持久化后记成功。** `start_batch_analysis()`（:423-449）把 `persist_to_files_db` 作为回调注入 FileAnalyzer。作业在 `_run_batch_analysis`（file_analyzer.py:437-557）里**逐文件顺序**执行（无并发信号量），每个文件的内容路由是：文档抽取器优先 → 失败则图像走 vision、其余按文本读 → 二进制文件跳过不计错误（:474-519）。关键不变量：**持久化成功才记入 results**（:524-540），一个文件不会同时出现在 results 和 errors 里。作业状态存内存 dict（:418-425），进程重启即失——前端轮询 `GET /api/llm/batch/{id}` 会 404。

**（f）证据路径解析。** `resolve_analysis_path()`（file_analyzer.py:31）把镜像内路径（`/etc/motd`）映射到任务抽取目录下的宿主副本；批量分析开始前统一解析，未抽取的文件报 "evidence file not available on host"。

## 6. 关联配置（env）

| env | 默认 | 作用 |
|---|---|---|
| `LLM_TEXT_BASE_URL` / `LLM_TEXT_MODEL` | `http://192.168.31.170:1234` / `openai/gpt-oss-20b` | 文本通道端点/模型 |
| `LLM_VISION_BASE_URL` / `LLM_VISION_MODEL` | 同上 / `qwen/qwen3-vl-4b` | vision 通道（可独立部署） |
| `LLM_TEXT_MAX_TOKENS` / `LLM_TEXT_TEMPERATURE` | 4096 / 0.7 | 生成参数 |
| `LLM_TIMEOUT_SECONDS` / `LLM_MAX_RETRIES` | 120 / 3 | 单请求超时（批量最坏耗时基数）/重试 |
| `FILE_ANALYSIS_MAX_CONTENT` / `_LIMIT` | 10000 / 12000 | 喂给 LLM 的内容上限 |

## 7. 注意事项与已知问题

- 批量作业无并发上限：一次喂太多文件会长时间占用单个 worker 顺序处理；耗时 ≈ 文件数 × 单次推理延迟（默认 120s 超时是最坏情况）。
- 作业状态不持久化（内存 dict），重启后 batch/{id} 全部 404。
- `persist_to_files_db` 对"路径不匹配"只告警返回 False（:180-185）——批量作业里表现为该文件进 errors；排查先比对规范化路径。
- vision 大图会被压缩（_compress_image，file_analyzer.py:345），PIL 缺失时原样发送。
- 别把 markitdown 抽取器的生命周期算在本服务头上：那是 routes/markitdown.py 的模块级单例（markitdown.py:36-44），经 task_store 做 workspace/task 门控。
- 并发边界：`file_descriptions.file_path` 是 UNIQUE 键，两个并发批量分析同一文件时 upsert 语义为"后写覆盖"，无版本冲突检测——设计上接受（分析可重放）。

## 8. 如何验证与扩展

- `python_service/tests/unit/test_persist_to_files_db.py`（fail-closed、两步写入、路径规范化）、`test_batch_persist_callback.py`（先持久化后记成功）、`test_normalize_evidence_path.py`、`test_llm_endpoint.py`、`test_custom_prompt_preserves_content.py`。
- 手工验证：`POST /api/llm/analyze` 后 `sqlite3 <task>_files.db "SELECT path, llm_summary, llm_analyzed_at FROM files WHERE llm_analyzed_at IS NOT NULL LIMIT 5"`。
- 新增分析类型：优先扩展 FileAnalyzer/EventAnalyzer（保持"客户端由外部传入"的模式），编排方法加在 llm/llm_service.py 并经门面 re-export。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
