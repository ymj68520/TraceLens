# LLMService（python_service/httpserver/services/llm/ 子包，门面 services/llm_service.py）

> **一句话**：AI 分析的编排层——持有 text/vision 两个 OpenAI 兼容客户端，把单文件、图像、批量、事件簇分析委托给三个子模块，并把结果直接回写 C++ 产出的 `_files.db` / `_events.db`（fail-closed）。

## 1. 为什么有这个模块

系统需要一个统一的"跟推理端点说话"的地方：模型端点与参数来自配置（text/vision 分离）、请求要发到 OpenAI 兼容的 `/v1/chat/completions`、结果要按取证语义（description/summary/keywords/is_relevant）解析、并且要落回 C++ 生成的 SQLite（让 C++ 的报告链路和 Python 的图谱链路共享同一份分析结果）。LLMService 把这四件事集中起来，路由与上层服务只面对稳定的 Python API。

## 2. 在系统中的位置

- **谁调用它**：routes/llm_endpoints（analyze/batch/事件簇/模型状态）、case_analysis 文件分析器、SecondaryAnalysis 与 EventRefresh 执行器（chat_completion）、ReportGenerationExecutor（llm_service 可为 None，提交以 `llm_unavailable` 持久失败）。
- **它调用谁**：本地/远端 OpenAI 兼容推理服务（`LLM_TEXT_BASE_URL` / `LLM_VISION_BASE_URL`）；SQLite（C++ 产出的 `<image>_files.db`、`<image>_events.db`）。
- **结构**：`services/llm_service.py` 只是向后兼容的 re-export 门面（llm_service.py:15-17）；实现都在 `services/llm/` 子包：`llm_service.py`（编排+持久化）、`file_analyzer.py`、`model_manager.py`、`event_analyzer.py`。

## 3. 核心概念与设计

**（a）两个客户端、零网络初始化。** `initialize()`（llm/llm_service.py:59-77）只创建两个 `httpx.AsyncClient`——text 指向 `LLM_TEXT_BASE_URL`、vision 指向 `LLM_VISION_BASE_URL`，超时统一 `LLM_TIMEOUT_SECONDS=120s`。不做任何 ping，所以启动几乎不可能失败（ServiceManager 里它没有 12s 上限的烦恼）。模型名/温度/max_tokens 全部来自 Settings（config.py:172-184）。

**（b）委托而非继承。** 服务本体是编排壳：`analyze` → `FileAnalyzer.analyze_file`（:316-344），`analyze_image` → 同一分析器（:346-364），模型状态 → `ModelManager`（:459-473），事件簇 → `EventAnalyzer`（:479-506）。子模块无状态、客户端由服务传入，这使测试可以注入假客户端。

**（c）`chat_completion()`——留给受控提示的裸通道。** 与 `analyze` 不同，它不注入预定义 system prompt，调用方完全掌控两条消息（:366-421）。这是为 Secondary Analysis（提示词带版本绑定）开的口子；新代码若不需要精确控制提示，优先用 `analyze`。

**（d）持久化：fail-closed 与两步写入。** `persist_to_files_db()`（:118-218）是本服务最需要读懂的方法：

1. **fail-closed**：目标库不存在直接返回 False、绝不回退写到别的库（:141-148 注释与实现）——历史上曾静默写到 `build/test_image_files.db` 之类的错误目标。
2. **路径规范化**：`normalize_evidence_path()` 把反斜杠/重复分隔符对齐到 files.path 的规范形式（:154）。
3. **两步写入**：先 `UPDATE files SET llm_* WHERE path = ?` 且**要求命中行**（:156-186），确认证据行真实存在后才 upsert `file_descriptions`（:190-208）——描述表永远不领先于证据表。

`persist_to_events_db()`（:232-283）按 event_id 更新 events 表的 LLM 列并自动补齐缺失列（`_ensure_events_schema`，:220-230）；`set_file_relevance()`（:285-306）切换 `file_descriptions.is_relevant`，被标记无关的文件不进最终报告。

**（e）批量作业：顺序、先持久化后记成功。** `start_batch_analysis()`（:423-449）把 `persist_to_files_db` 作为回调注入 FileAnalyzer。作业在 `_run_batch_analysis`（file_analyzer.py:437-557）里**逐文件顺序**执行（无并发信号量），每个文件的内容路由是：文档抽取器优先 → 失败则图像走 vision、其余按文本读 → 二进制文件跳过不计错误（:474-519）。关键不变量：**持久化成功才记入 results**（:524-540），一个文件不会同时出现在 results 和 errors 里。作业状态存内存 dict（:418-425），进程重启即失——前端轮询 `GET /api/llm/batch/{id}` 会 404。

**（f）证据路径解析。** `resolve_analysis_path()`（file_analyzer.py:31）把镜像内路径（`/etc/motd`）映射到任务抽取目录下的宿主副本；批量分析开始前统一解析，未抽取的文件报 "evidence file not available on host"。

## 4. 工作流程走读：一次批量分析

`POST /api/llm/batch`（路由解析任务、拿 `output_files_db` 与抽取目录）→ `start_batch_analysis(files, ..., files_db_path, extraction_dir)`（llm/llm_service.py:423）→ FileAnalyzer 建作业 dict 并 `asyncio.create_task(_run_batch_analysis ...)`（file_analyzer.py:416-435）→ 循环内每个文件：resolve 路径 → 选通道 → `analyze_file`（发 OpenAI 兼容请求、解析出结构化 analysis）→ `persist_to_files_db` 回调（失败即把该文件记 errors）→ 更新进度。前端轮询 `get_batch_status`（:559-561）直到 completed/failed。

## 5. 与其他模块的协作

| 模块 | 协作方式 |
|---|---|
| routes/llm_endpoints | 全部分析端点的服务端 |
| markitdown / document_extractor | FileAnalyzer 的文档→Markdown 通道（注意：markitdown 路由侧是进程级单例 + task 工作区门控，与本服务无直接耦合） |
| SecondaryAnalysis / EventRefresh / ReportGeneration 执行器 | 经 chat_completion 使用；LLM 缺失时执行器容忍 None |
| GraphitiService | 下游消费者：`_files.db` 里的 llm_* 列是图谱 episode 的原料 |
| CppBackendService | 任务元数据（数据库路径、抽取目录）来源 |

## 6. 注意事项与已知问题

- 批量作业无并发上限：一次喂太多文件会长时间占用单个 worker 顺序处理；耗时 ≈ 文件数 × 单次推理延迟（默认 120s 超时是最坏情况）。
- 作业状态不持久化（内存 dict），重启后 batch/{id} 全部 404。
- `persist_to_files_db` 对"路径不匹配"只告警返回 False（:180-185）——批量作业里表现为该文件进 errors；排查先比对规范化路径。
- vision 大图会被压缩（_compress_image，file_analyzer.py:345），PIL 缺失时原样发送。
- 别把 markitdown 抽取器的生命周期算在本服务头上：那是 routes/markitdown.py 的模块级单例（markitdown.py:36-44），经 task_store 做 workspace/task 门控。

## 7. 如何验证与扩展

- `python_service/tests/unit/test_persist_to_files_db.py`（fail-closed、两步写入、路径规范化）、`test_batch_persist_callback.py`（先持久化后记成功）、`test_normalize_evidence_path.py`、`test_llm_endpoint.py`、`test_custom_prompt_preserves_content.py`。
- 手工验证：`POST /api/llm/analyze` 后 `sqlite3 <task>_files.db "SELECT path, llm_summary, llm_analyzed_at FROM files WHERE llm_analyzed_at IS NOT NULL LIMIT 5"`。
- 新增分析类型：优先扩展 FileAnalyzer/EventAnalyzer（保持"客户端由外部传入"的模式），编排方法加在 llm/llm_service.py 并经门面 re-export。

**最后更新**: 2026-08-23（解释式重写）
