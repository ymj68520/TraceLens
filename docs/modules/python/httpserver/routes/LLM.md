# LLM 路由（python_service/httpserver/routes/llm.py + llm_endpoints/ + case_analysis_endpoints/，前缀 /api/llm）

> **一句话**：AI 分析的 HTTP 表面——单文件/图像/文档分析、事件簇摘要、批量后台作业、模型状态与相关性开关；分析结果直接回写 C++ 产出的 SQLite，成为报告与图谱的共同数据源。

## 这组路由承担什么职责

`/api/llm` 前缀下实际挂了三个模块：llm.py（聚合 `llm_endpoints/` 的 `_analysis.py` 与 `_management.py`）、case_analysis.py（聚合 `case_analysis_endpoints/`，案情描述/二次分析等）、dll.py。路由层的实质工作是**内容路由**：根据输入形态（文件路径 / 上传 / 直接文本；图像 / 文档 / 纯文本）选择正确的分析通道，以及**持久化的信任边界**（服务端解析数据库路径，客户端只给提示）。

## 典型调用方

- 前端 `/files`、`/analysis-center`、`/llm-descriptions`（web/src/services/llmService.js：analyze :29、analyze/file :48、analyze/dll :60、batch :84、batch 轮询 :92、models :164、status :171、toggle-relevance :181；forensicsService.js：analyze-event-cluster :39,:62）。
- 前端 `/case-intelligence` 使用同前缀下的 intelligence-report 与二次分析端点。
- 全部经 `pythonApi`（:8090，timeout 60s）。

## 核心数据结构

主分析端点的请求/响应模型（llm_models.py:20-39）：

```python
# llm_models.py:20-30
class AnalyzeRequest(BaseModel):
    """Request model for file analysis."""
    task_id: Optional[str] = Field(None, description="Task ID owning the persistence target (required to persist)")
    file_path: Optional[str] = Field(None, description="Path to file to analyze")
    db_file_path: Optional[str] = Field(None, description="Path to file in DB (for persistence)")
    content: Optional[str] = Field(None, description="Direct content to analyze")
    model_type: str = Field(default="text", description="Model type: 'text' or 'vision'")
    prompt: Optional[str] = Field(None, description="Custom analysis prompt")
    max_tokens: Optional[int] = Field(None, ge=1, le=8192, description="Max response tokens")
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0, description="Model temperature")
    files_db_path: Optional[str] = Field(None, description="Path to _files.db for persisting result")
```

逐字段：`task_id` 是持久化的钥匙（没有它最多 400，见 :165-169 的前置校验）；`file_path`/`content` 二选一（都给时 file_path 优先）；`db_file_path` 是"镜像内路径→DB 行"的定位键，缺省回落 file_path；`files_db_path` 是 deprecated 提示，服务端只做精确校验；`max_tokens≤8192`、`temperature≤2.0` 由 Pydantic 硬约束（越界 422）。事件簇模型（llm_models.py:101-111）的关键字段是 `time_window`（bucket 索引 = timestamp/bucket_seconds）、`bucket_seconds`（默认 60，**必须与建簇时一致**）与新的 `group_descriptor`（后端 Timeline Group 描述符，新旧两代入参并存）。

## 端点分组语义

（完整契约见 docs/api_reference/Python_REST_API.md）

- **分析**：`POST /analyze`（_analysis.py:145，给定路径或直接内容）；`POST /analyze/file`（:336，multipart 上传）；`POST /analyze-event-cluster`（:28，事件簇摘要）。
- **批量**：`POST /batch`（:430，返回 job_id 后台跑）+ `GET /batch/{job_id}`（:496，进度/结果/错误）。
- **管理**：`GET /models`、`GET /status`（_management.py:27,147）；`POST /toggle-relevance`（:70，文件级）、`POST /toggle-cluster-relevance`（:101，簇级）——被标记无关的文件/簇不进最终报告。
- **case_analysis（同前缀）**：案情描述保存、`POST /reanalyze-files`（带用户提示的二次分析，_case.py:95-130）等。
- **dll（同前缀）**：`POST /analyze/dll`（dll.py:86）——DLL/PE/ELF 的"C++ 解析 + LLM 安全评估"两段式分析（详见下节）。

## 数据流（读写什么）

**`POST /analyze` 的内容路由**（_analysis.py:176-276）是理解本模块的关键：

```python
# _analysis.py:218-236（节选）——图像分支
file_ext = Path(request.file_path).suffix.lower()
is_image = file_ext in IMAGE_EXTENSIONS        # .jpg/.png/.heic/... 共 15 种（:176-179）

if is_image:
    # Read as binary and use vision model
    logger.info(f"Auto-detected image file: {request.file_path}, using vision model")
    try:
        with open(request.file_path, 'rb') as f:
            image_data = f.read()
        result = await service_manager.llm_service.analyze_image(
            image_data=image_data,
            prompt=request.prompt,
        )
```

```python
# _analysis.py:238-267（节选）——文档抽取与纯文本分支
else:
    doc_locator = get_document_extractor_locator()
    extractor = doc_locator.get_extractor(request.file_path)
    if extractor:
        # 文档（markitdown/office/evtx/...）→ 先抽 Markdown 再走 text 模型
        content = await extractor.extract_to_markdown(request.file_path)
        result = await service_manager.llm_service.analyze(
            content=content, model_type=request.model_type or "text", ...)
    else:
        # 按纯文本读
        content = await service_manager.llm_service.read_file_content(request.file_path)
        result = await service_manager.llm_service.analyze(...)
```

直接给 content 时走纯文本分析（:269-276）。镜像内路径（如 `/etc/motd`）先经 `resolve_analysis_path` 映射到任务的抽取目录（:187-200），文件不存在时 404 并提示"先抽取再分析"（:206-216）。

**持久化的信任边界（D2b）**：分析结果要落库时，数据库路径由服务端用 `task_store.resolve_task_files_db(task_id)` 解析，请求里的 `files_db_path` 只是"精确校验的过时提示"，绝非权威（:283-305 的注释与实现）：

```python
# _analysis.py:283-318（节选）
# Persist to the task-owned _files.db. The persistence target is
# resolved server-side from task_id (D2b); a supplied files_db_path
# is a deprecated exact-validated hint, never the authority.
if (request.files_db_path or request.task_id) and (
    request.db_file_path or request.file_path
) and description:
    from ...services import task_store
    # ...
    trusted_files_db = await task_store.resolve_task_files_db(request.task_id)
    task_store.validate_legacy_db_path(request.files_db_path, trusted_files_db)
    # ...
    service_manager.llm_service.persist_to_files_db(
        db_path=str(trusted_files_db),
        file_path=db_path_to_save,
        description=description,
        summary=analysis.get("summary") or description[:200],
        keywords=keywords_str,
        model_used=result.get("model", "unknown")
    )
```

`validate_legacy_db_path`（task_store.py:104-119）对两侧 `resolve(strict=False)` 后**精确比较**——不做 basename/后缀/父目录/大小写模糊匹配，不匹配即 `path_mismatch` 契约错误。

落库本体 `LLMService.persist_to_files_db`（services/llm/llm_service.py:118-218）是 fail-closed 设计的样板：

```python
# llm_service.py:141-154（节选）
# Fail-closed: never fall back to another DB (e.g. build/test_image_files.db).
# A missing target DB is a genuine error — refuse to write anywhere else.
if not db_path or not Path(db_path).exists():
    logger.warning(
        f"persist_to_files_db: target db not found at {db_path!r}; "
        "refusing to write anywhere else (fail-closed)"
    )
    return False

# Canonicalize once for consistent Evidence identity matching.
norm_path = normalize_evidence_path(file_path)
```

写入顺序有讲究（:171-208）：先 `UPDATE files SET llm_* WHERE path = ?`，`rowcount<=0` 即返回 False（路径必须在 files 表真实存在）；成功后才 `_ensure_file_descriptions_schema`（惰性建表 + ALTER 补列，:95-116）并对 file_descriptions 做 `ON CONFLICT(file_path) DO UPDATE` 的 upsert——规范化路径 `norm_path` 同时是两个表的身份键，与 Investigation 证据身份（`file:<normalized_path>`）对齐。**返回 False 不抛异常**，调用方必须检查。

**事件簇分析**直接打开 `<image>_events.db`：读取 `(timestamp / bucket_seconds) = time_window AND event_type = ?` 的行（_analysis.py:62-69，bucket 必须与建簇时一致，默认 60，:53-57），LLM 摘要后把整簇事件的 `llm_*` 列一次性 UPDATE（:97-131）：

```python
# _analysis.py:97-106（节选）
sql_update = """
    UPDATE events SET
        llm_summary = ?, llm_description = ?, llm_keywords = ?,
        llm_analyzed_at = ?, llm_model_used = ?, llm_is_relevant = ?
    WHERE (timestamp / ?) = ? AND event_type = ?
"""
```

持久化失败仅 warning 不影响响应（:130-131）。toggle-cluster-relevance 用同样的定位方式只改 `llm_is_relevant`（_management.py:126-135）。

**批量作业**：`/batch` 可由前端给 file_paths 白名单，否则按 file_types/limit 自动发现（:459-470）；作业在 FileAnalyzer 内逐文件顺序执行，**先持久化后记成功**的不变量（file_analyzer.py:523-541）：

```python
# file_analyzer.py:523-541（节选）
# Persist results if a callback is provided. Persistence runs
# BEFORE recording success so that a file can never appear in
# both `results` and `errors` (A7). The callback contract here
# is synchronous (returns bool); do NOT await it (A6).
if persist_callback and description:
    persisted = persist_callback(
        db_path=files_db_path, file_path=file_path, ...)
    if not persisted:
        raise RuntimeError(f"Failed to persist analysis result for {file_path}")
self._jobs[job_id]["results"].append({...})
```

persist 回调即 `LLMService.persist_to_files_db`（llm_service.py:445-449 显式注入）——它返回 False 时抛 RuntimeError 进入 errors 分支，这就是"持久化失败即失败"的实现点。

### DLL 安全评估（dll.py）

`POST /api/llm/analyze/dll` 是"结构解析在 C++、语义评估在 LLM"的四步流水线（dll.py:100-189）：`DLLAnalyzerClient` 调 C++ `POST /api/forensics/dlls/analyze`（services/dll/dll_analyzer.py:54）拿二进制结构 → `DLLMarkdownGenerator` 生成 Markdown 报告（dll.py:113）→ 用内置的中文安全评估提示词（含威胁分级标准与 MITRE ATT&CK 映射要求，dll.py:56-83）走 `llm_service.analyze`（:126-132，max_tokens 2000、temperature 0.3）→ `normalize_threat_level` 把 LLM 可能返回的"低/中/高/严重"归一成小写英文枚举，无法映射时按 C++ 数值评分落档（:20-32）：

```python
# dll.py:20-32
def normalize_threat_level(raw: str, numeric_score: int) -> str:
    """Normalize threat level string to consistent English values."""
    mapping = {
        "低": "low", "低风险": "low", "low": "low", "safe": "low",
        "中": "medium", "中风险": "medium", "medium": "medium",
        "高": "high", "高风险": "high", "high": "high",
        "严重": "critical", "critical": "critical",
    }
    key = raw.strip().lower()
    return mapping.get(key, "low" if numeric_score < 30
                       else "medium" if numeric_score < 60
                       else "high" if numeric_score < 80
                       else "critical")
```

落库遵循同一条 D2b 纪律：持久化目标由 `task_store.resolve_task_files_db(task_id)` 服务端解析，请求里的 `files_db_path` 只是精确校验的过时提示（dll.py:144-162），经 `persist_to_files_db` 回写 description/summary/keywords（:170-177）；持久化失败仅 warning、不影响 200 响应（:179-180）。超时链为 settings.dll_analysis_timeout → `DLL_ANALYSIS_TIMEOUT` 环境变量，默认 30s（config.py:148、dll_analyzer.py:28）。一个已知配置陷阱：`DLL_CPP_BACKEND_URL`（config.py:147 的 dll_cpp_backend_url）已定义但**无任何消费者**——路由实际取的是通用 `settings.cpp_backend_url`（dll.py:105），改 DLL 专用地址不会生效。验证：`tests/unit/test_dll_route.py`、`test_dll_analyzer.py`、`test_dll_markdown_generator.py`；活体链路见 live-integration.md 的 DLL socket handoff。

## 关键接口/方法签名

| 端点/方法 | 签名要点 | 失败行为 |
|---|---|---|
| `POST /analyze` | `AnalyzeRequest → AnalyzeResponse{analysis,model_used,tokens_used,processing_time_ms}` | 404（文件不存在/任务不存在）、400（缺 task_id、图像/文档失败）、500 固定文案 |
| `POST /analyze/file` | multipart `file` + query `model_type/prompt` | 400（校验）、500 "file analysis failed" |
| `POST /analyze-event-cluster` | `EventClusterAnalyzeRequest` | 404（任务/簇空）、400（无 events 库）、500 "database query failed"/"event cluster analysis failed" |
| `POST /batch` | `BatchAnalyzeRequest{task_id,file_types?,file_paths?,limit≤1000,model_type}` | 404（任务）、500 "batch analysis failed" |
| `GET /batch/{job_id}` | → `BatchStatusResponse` | 404（job）、500 "batch status is unavailable" |
| `llm_service.analyze(content,model_type,prompt,max_tokens,temperature)` | 组装 OpenAI 兼容请求，走 text/vision 客户端 | 未初始化时先自愈 `initialize()` |
| `llm_service.chat_completion(system_prompt,user_prompt,...)` | 二次分析专用：显式双消息、无预设 system prompt（llm_service.py:366-421） | raise_for_status 直抛 |
| `llm_service.persist_to_files_db(db_path,file_path,description,summary,keywords,model_used) -> bool` | 见上文 fail-closed 语义 | False（不抛） |

## 边界与已知状态

- **410 退役**：`POST /api/llm/case-analysis` 与旧的 `GET /api/llm/case-analysis/{job_id}` 固定 410"legacy case analysis generation has been retired; use report generation"（_case.py:80-92、:183-195）。替代能力在 multi_analysis 与 `/api/reports` 报告服务——任何把旧端点当活接口的调用都会拿到 410。
- **持久化失败即失败**：批量作业里 persist 回调返回 False 会把该文件记入 errors 而不是静默丢（file_analyzer.py:537-540），所以 `_files.db` 缺失时批量作业会大量报错——这是 fail-closed 设计，不是 bug。
- 上传分析的文档抽取走临时文件并保证清理（_analysis.py:386-400，`finally: os.unlink` + OSError 容忍）。
- `toggle-cluster-relevance` 的 SQL 失败会返回 500 且 detail 带 `str(e)`（_management.py:139），与全局脱敏纪律略有出入。
- env：`LLM_TEXT_BASE_URL/LLM_VISION_BASE_URL`（默认 http://192.168.31.170:1234）、`LLM_TEXT_MODEL=openai/gpt-oss-20b`、`LLM_VISION_MODEL=qwen/qwen3-vl-4b`、`LLM_TIMEOUT_SECONDS=120`、`LLM_MAX_RETRIES=3`、`LLM_CONTEXT_LENGTH=4096`、`DLL_ANALYSIS_TIMEOUT=30`。

## 如何验证与扩展

- `python_service/tests/unit/`：`test_llm_endpoint.py`、`test_persist_to_files_db.py`（fail-closed 与路径规范化）、`test_batch_persist_callback.py`（先持久化后记成功的顺序不变量）、`test_custom_prompt_preserves_content.py`、`test_case_analysis_routes.py`、`test_d2b_db_ownership.py` / `test_d2b_task_store.py`（路径信任边界）。
- 手工链路：`POST /api/llm/analyze {"task_id","file_path","prompt"}` → 查 SQLite `files.llm_description` → `POST /api/llm/batch` + 轮询 `GET /api/llm/batch/{id}`。
- 新增分析通道：优先改 LLMService/FileAnalyzer（内容路由逻辑集中在那），路由层只加参数透传。

相关阅读：[HTTPRoutes.md](../HTTPRoutes.md)、[services/LLMService.md](../../services/LLMService.md)。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
