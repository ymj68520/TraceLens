# LLM 路由（python_service/httpserver/routes/llm.py + llm_endpoints/ + case_analysis_endpoints/，前缀 /api/llm）

> **一句话**：AI 分析的 HTTP 表面——单文件/图像/文档分析、事件簇摘要、批量后台作业、模型状态与相关性开关；分析结果直接回写 C++ 产出的 SQLite，成为报告与图谱的共同数据源。

## 这组路由承担什么职责

`/api/llm` 前缀下实际挂了三个模块：llm.py（聚合 `llm_endpoints/` 的 `_analysis.py` 与 `_management.py`）、case_analysis.py（聚合 `case_analysis_endpoints/`，案情描述/二次分析等）、dll.py。路由层的实质工作是**内容路由**：根据输入形态（文件路径 / 上传 / 直接文本；图像 / 文档 / 纯文本）选择正确的分析通道，以及**持久化的信任边界**（服务端解析数据库路径，客户端只给提示）。

## 典型调用方

- 前端 `/files`、`/analysis-center`、`/llm-descriptions`（web/src/services/llmService.js、forensicsService.js）。
- 前端 `/case-intelligence` 使用同前缀下的 intelligence-report 与二次分析端点。

## 端点分组语义

（完整契约见 docs/api_reference/Python_REST_API.md）

- **分析**：`POST /analyze`（_analysis.py:145，给定路径或直接内容）；`POST /analyze/file`（:336，multipart 上传）；`POST /analyze-event-cluster`（:28，事件簇摘要）。
- **批量**：`POST /batch`（:430，返回 job_id 后台跑）+ `GET /batch/{job_id}`（:496，进度/结果/错误）。
- **管理**：`GET /models`、`GET /status`（_management.py:27,147）；`POST /toggle-relevance`（:70，文件级）、`POST /toggle-cluster-relevance`（:101，簇级）——被标记无关的文件/簇不进最终报告。
- **case_analysis（同前缀）**：案情描述保存、`POST /reanalyze-files`（带用户提示的二次分析，_case.py:95-130）等。
- **dll（同前缀）**：`POST /analyze/dll`（dll.py:86）——DLL/PE/ELF 的"C++ 解析 + LLM 安全评估"两段式分析（详见下节）。

## 数据流（读写什么）

**`POST /analyze` 的内容路由**（_analysis.py:176-276）是理解本模块的关键：

1. 图像后缀 → 读二进制走 vision 模型（:221-236）；
2. 有注册的文档抽取器（markitdown 等）→ 抽成 Markdown 再走 text 模型（:238-257）；
3. 否则按文本读（:259-267）；直接给 content 则纯文本分析（:269-276）。

镜像内路径（如 `/etc/motd`）先经 `resolve_analysis_path` 映射到任务的抽取目录（:187-200），文件不存在时 404 并提示"先抽取再分析"（:206-216）。

**持久化的信任边界（D2b）**：分析结果要落库时，数据库路径由服务端用 `task_store.resolve_task_files_db(task_id)` 解析，请求里的 `files_db_path` 只是"精确校验的过时提示"，绝非权威（:283-305 的注释与实现）。这防止客户端把结果写进任意 SQLite。

**事件簇分析**直接打开 `<image>_events.db`：读取 `(timestamp / bucket_seconds) = time_window AND event_type = ?` 的行（:60-77，bucket 必须与建簇时一致，默认 60，:53-57），LLM 摘要后把整簇事件的 `llm_*` 列一次性 UPDATE（:97-131）。toggle-cluster-relevance 用同样的定位方式只改 `llm_is_relevant`（_management.py:126-135）。

**批量作业**：`/batch` 可由前端给 file_paths 白名单，否则按 file_types/limit 自动发现（:459-470）；作业在 FileAnalyzer 内逐文件顺序执行（详见 [services/LLMService.md](../../services/LLMService.md)）。

### DLL 安全评估（dll.py）

`POST /api/llm/analyze/dll` 是"结构解析在 C++、语义评估在 LLM"的四步流水线（dll.py:100-189）：`DLLAnalyzerClient` 调 C++ `POST /api/forensics/dlls/analyze`（services/dll/dll_analyzer.py:54）拿二进制结构 → `DLLMarkdownGenerator` 生成 Markdown 报告（dll.py:113）→ 用内置的中文安全评估提示词（含威胁分级标准与 MITRE ATT&CK 映射要求，dll.py:56-83）走 `llm_service.analyze`（:126-132，max_tokens 2000、temperature 0.3）→ `normalize_threat_level` 把 LLM 可能返回的"低/中/高/严重"归一成小写英文枚举，无法映射时按 C++ 数值评分落档（:20-32）。

落库遵循同一条 D2b 纪律：持久化目标由 `task_store.resolve_task_files_db(task_id)` 服务端解析，请求里的 `files_db_path` 只是精确校验的过时提示（dll.py:144-162），经 `persist_to_files_db` 回写 description/summary/keywords（:170-177）；持久化失败仅 warning、不影响 200 响应（:179-180）。超时链为 settings.dll_analysis_timeout → `DLL_ANALYSIS_TIMEOUT` 环境变量，默认 30s（config.py:148、dll_analyzer.py:28）。一个已知配置陷阱：`DLL_CPP_BACKEND_URL`（config.py:147 的 dll_cpp_backend_url）已定义但**无任何消费者**——路由实际取的是通用 `settings.cpp_backend_url`（dll.py:105），改 DLL 专用地址不会生效。验证：`tests/unit/test_dll_route.py`、`test_dll_analyzer.py`、`test_dll_markdown_generator.py`；活体链路见 live-integration.md 的 DLL socket handoff。

## 边界与已知状态

- **410 退役**：`POST /api/llm/case-analysis` 与旧的 `GET /api/llm/case-analysis/{job_id}` 固定 410"legacy case analysis generation has been retired; use report generation"（_case.py:80-92、:183-195）。替代能力在 multi_analysis 与 `/api/reports` 报告服务——任何把旧端点当活接口的调用都会拿到 410。
- **持久化失败即失败**：批量作业里 persist 回调返回 False 会把该文件记入 errors 而不是静默丢（file_analyzer.py:537-540），所以 `_files.db` 缺失时批量作业会大量报错——这是 fail-closed 设计，不是 bug。
- 上传分析的文档抽取走临时文件并保证清理（_analysis.py:386-400）。
- `toggle-cluster-relevance` 的 SQL 失败会返回 500 且 detail 带 `str(e)`（_management.py:139），与全局脱敏纪律略有出入。

## 如何验证与扩展

- `python_service/tests/unit/`：`test_llm_endpoint.py`、`test_persist_to_files_db.py`（fail-closed 与路径规范化）、`test_batch_persist_callback.py`（先持久化后记成功的顺序不变量）、`test_custom_prompt_preserves_content.py`、`test_case_analysis_routes.py`、`test_d2b_db_ownership.py` / `test_d2b_task_store.py`（路径信任边界）。
- 手工链路：`POST /api/llm/analyze {"task_id","file_path","prompt"}` → 查 SQLite `files.llm_description` → `POST /api/llm/batch` + 轮询 `GET /api/llm/batch/{id}`。
- 新增分析通道：优先改 LLMService/FileAnalyzer（内容路由逻辑集中在那），路由层只加参数透传。

相关阅读：[HTTPRoutes.md](../HTTPRoutes.md)、[services/LLMService.md](../../services/LLMService.md)。

**最后更新**: 2026-08-23（补充 dll.py 路由一节：POST /api/llm/analyze/dll 的四步流水线、DLL_ANALYSIS_TIMEOUT 超时链与 DLL_CPP_BACKEND_URL 无消费者的说明）
