# Markitdown 路由（python_service/httpserver/routes/markitdown.py + office.py，前缀 /api/markitdown 与 /api/office）

> **一句话**：C++ 分析管线的文本化后端——`/convert` 用进程级单例 MarkItDown 把单文件转 Markdown，`/convert-one`/`/batch-convert` 经 ExtractorLocator 走全谱提取器批量镜像转换，`/api/office/parse` 专供 C++ OfficeAnalyzer 解析表格与幻灯片；所有读取都过 task_store 门控。

## 1. 这组路由承担什么职责（为什么存在）

C++ 侧要把文件内容喂给 LLM，但文档解析生态（MarkItDown、openpyxl、xlrd、python-pptx、evtx/注册表/PE 等专业提取器）在 Python。这组路由把两种文本化能力暴露为服务：**单文件库转换**（只走 MarkItDown 库）与**目录级批量转换**（走 ExtractorLocator，让 evtx、registry、PE/ELF、归档、数据库等专业提取器也参与，markitdown.py:248-254 的注释明确了这条分界）。office.py 是更窄的入口：只认 4 种 Office 扩展名，直接调 OfficeService 的具体解析器。三类端点共同点是**D2b 门控**：文件必须属于发起任务的 workspace/已知记录，绝不做裸宿主机存在性检查。

## 2. 典型调用方（前端哪个页面/组件、或其他服务）

- **主调用方是 C++ 后端**（不是前端）：`src/integration/LLMIntegration/MarkitdownProxy.cpp:89/94` 调 `/api/markitdown/convert-one`，`:147/173` 调 `/convert`，`:214` 调 `/status`——转换失败时 C++ 回退本地旧解析器（这正是单例存在的理由，见第 4 节）；`src/analyzers/OfficeAnalyzer/OfficeAnalyzer.cpp:105` 调 `/api/office/parse`。
- 前端只直接用 office 面：`web/src/services/officeService.js:9/17`（`/api/office/parse` 与 `/supported-types`），供文件预览组件使用。
- 活体验收：live-integration.md 的 F 系列包含 live Markitdown/Office socket handoff。

## 3. 端点语义分组（散文）

完整契约见 docs/api_reference/Python_REST_API.md 第 10/11 节。分组：

- **单文件（markitdown.py）**：`POST /convert`（:141）——task_id/workspace_root 锚定 + file_path，返回 markdown/title/耗时，支持 PDF/DOC(X)/XLS(X)/PPT(X)/HTML/CSV/JSON/XML/EPUB/IPYNB/图片(EXIF+OCR)/音频等；`GET /status`（:225）——库可用性与支持格式清单（库未装时 `available: false`，不是 500）。
- **批量族（markitdown.py）**：`POST /convert-one`（:400）——input_root 下的一个文件转成镜像 `.md`（原子写）；`POST /batch-convert`（:523）——递归整目录，converted/skipped/failed 计数，单文件失败不中止批（错误清单封顶 50 条，:636-637）。
- **Office（office.py）**：`POST /parse`（:39）——.xlsx/.xls/.pptx/.ppt 专用，返回 Markdown 与大写类型名；`GET /supported-types`（:151）——静态类型清单。

## 4. 数据流（读什么库/服务、写什么；关键机制 file:line）

**单例是 /convert 的核心机制**。模块级 `_md_instance` + 双检锁（markitdown.py:32-45）：

```python
# markitdown.py:27-31（注释，解释为什么必须单例）
# Creating a new MarkItDown() per request reloads the magika ONNX model
# every time (~0.5s overhead), ... can cause transient failures under
# concurrent load — which makes the C++ backend fall back to its legacy
# local parsers.
```

转换本身 `asyncio.to_thread(md.convert, ...)`（:187），避免大文件阻塞事件循环。

**门控（D2b）**：`/convert` 的读取经 `_assert_file_readable_for_task`（:79-110）——task workspace 成员、或服务端派生的 internal extract root、或 files.db 精确已知记录（`task_store.file_known_to_task`），三层全不过即 400 "file is outside the task workspace"；fail-closed。批量族用写锚：`_task_workspace_or_400` 解析 workspace（:113-130）后 `task_store.resolved_within` 强制 input/output 都在 workspace 内，且**拒绝任何符号链接组件**（:410-414、:555-559）。`workspace_root` 是给 CLI 调用者的 deprecated 独立锚（:51、:259）。

**批量防自毁**：输出树与输入树重叠（含互相嵌套）一律 400（:434-465）；镜像命名会把输入 `x` 写成 `x.md`，与同名兄弟输入冲突也 400（:604-613）；写入走同目录临时文件 + `os.replace` 原子替换（:358-368）。批量并发用 `Semaphore(4)` 限内存（:626）。错误文本只回异常**类名**——库错误消息可能内嵌服务器解析路径（:297-301）。

**提取器选择**：批量/单条转换经 `get_document_extractor_locator()`（:377），扩展名→提取器映射及回退链定义在 `python_service/config/extractor_mapping.json`（如 `.docx`→DocxExtractor、`.xlsx/.pptx`→OfficeServiceAdapter、`.docx` 缺 MarkItDown 时回退 DocxExtractor）；无匹配提取器时回退原始文本直读（UTF-8 严格→latin-1，二进制启发式跳过，:382-389、:508-520）。office /parse 的解析器在 services/office_service.py：openpyxl（:63）/ xlrd（:106）/ python-pptx（:143），内部再兜底 subprocess。

## 5. 边界与已知状态（400/404/降级）

- **门控优先于存在性**：office /parse 里文件"不在本任务已知记录且不在抽取目录"时 404 "file is not part of the current task"（office.py:63-105），即使宿主机上该路径存在——这是设计而非 bug。markitdown /convert 则先门控（400）后查存在（404，markitdown.py:163-180），错误码顺序有讲究。
- **库缺失降级**：markitdown 未安装时 /status 返回 `available:false`（:241-245），/convert 抛 ImportError → 500 并给出安装提示（:206-210）。
- **office /parse 的软失败**：解析异常返回 200 + `success:false` + `error:"office parse failed"`（office.py:141-148），而非 5xx——调用方（C++ OfficeAnalyzer）按 success 字段走回退。
- 批量的 `_exception_text` 纪律同样适用于响应里的 errors 列表；`/batch-convert` 的 `success:true` 只表示"批跑完了"，要看 failed 计数。
- 两个模块都接受 deprecated `workspace_root`，新调用应带 `task_id`（office.py:26、markitdown.py:51 注释）。

## 6. 如何验证

- `python_service/tests/unit/test_markitdown_routes.py`（convert/convert-one/batch-convert 的门控、重叠拒绝、镜像命名）、`test_d2b_office_routes.py`（office 成员门控）、`test_d2b_task_store.py`（锚解析）、`test_forensic_extractors.py`（提取器映射与回退链）。
- 活体：live-integration.md 的 Markitdown/Office socket handoff（C++ 真实发起到 :8090 的调用链）。
- 手工：`curl -XPOST :8090/api/markitdown/status` → 带 task_id 调 `/convert` → 在 workspace 内建 testdir 调 `/batch-convert` 检查镜像 `.md` 树。

相关阅读：[HTTPRoutes.md](../HTTPRoutes.md)、[LLM.md](LLM.md)（消费这些文本的 LLM 分析链）、[Database.md](Database.md)。

**最后更新**: 2026-08-23（新建，解释式）
