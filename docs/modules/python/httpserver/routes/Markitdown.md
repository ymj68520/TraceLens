# Markitdown 路由（python_service/httpserver/routes/markitdown.py + office.py，前缀 /api/markitdown 与 /api/office）

> **一句话**：C++ 分析管线的文本化后端——`/convert` 用进程级单例 MarkItDown 把单文件转 Markdown，`/convert-one`/`/batch-convert` 经 ExtractorLocator 走全谱提取器批量镜像转换，`/api/office/parse` 专供 C++ OfficeAnalyzer 解析表格与幻灯片；所有读取都过 task_store 门控。

## 1. 这组路由承担什么职责（为什么存在）

C++ 侧要把文件内容喂给 LLM，但文档解析生态（MarkItDown、openpyxl、xlrd、python-pptx、evtx/注册表/PE 等专业提取器）在 Python。这组路由把两种文本化能力暴露为服务：**单文件库转换**（只走 MarkItDown 库）与**目录级批量转换**（走 ExtractorLocator，让 evtx、registry、PE/ELF、归档、数据库等专业提取器也参与，markitdown.py:248-254 的注释明确了这条分界）。office.py 是更窄的入口：只认 4 种 Office 扩展名，直接调 OfficeService 的具体解析器。三类端点共同点是**D2b 门控**：文件必须属于发起任务的 workspace/已知记录，绝不做裸宿主机存在性检查。

## 2. 典型调用方（前端哪个页面/组件、或其他服务）

- **主调用方是 C++ 后端**（不是前端）：`src/integration/LLMIntegration/MarkitdownProxy.cpp:89/94` 调 `/api/markitdown/convert-one`，`:147/173` 调 `/convert`，`:214` 调 `/status`——转换失败时 C++ 回退本地旧解析器（这正是单例存在的理由，见第 4 节）；`src/analyzers/OfficeAnalyzer/OfficeAnalyzer.cpp:105` 调 `/api/office/parse`。
- 前端只直接用 office 面：`web/src/services/officeService.js:9/17`（`/api/office/parse` 与 `/supported-types`），供文件预览组件使用。
- 活体验收：live-integration.md 的 F 系列包含 live Markitdown/Office socket handoff。

## 3. 核心数据结构

`/convert` 的请求模型（markitdown.py:48-52）：

```python
# markitdown.py:48-52
class ConvertRequest(BaseModel):
    """Request model for file-to-markdown conversion."""
    task_id: str | None = Field(None, description="Task ID owning the file (workspace anchor)")
    workspace_root: str | None = Field(None, description="Deprecated standalone workspace anchor for CLI callers")
    file_path: str = Field(..., description="Absolute path to the file to convert")
```

锚点语义：`task_id` 是正规锚（解析出 workspace/extract_root/files_db 三重判定材料）；`workspace_root` 是给 CLI 调用者的 deprecated 独立锚（C++ MarkitdownProxy 历史上用它）；两者都缺即 400（:72-75）。批量族的 `BatchConvertRequest`（:256-261）把 `file_path` 换成 `input_dir`+`output_dir` 双根。批量结果用 frozen dataclass 承载（:278-285）：`FileConversionOutcome(status: Literal["converted","skipped","failed"], input_path, output_path, output_size, error)`——`status` 三值分别对应成功产出、无提取器/空产出/二进制跳过、异常失败（error 只放异常**类名**）。

## 4. 数据流（读什么库/服务、写什么；关键机制 file:line）

**单例是 /convert 的核心机制**。模块级 `_md_instance` + 双检锁（markitdown.py:32-45）：

```python
# markitdown.py:27-45
# Module-level singleton MarkItDown instance.
# Creating a new MarkItDown() per request reloads the magika ONNX model
# every time (~0.5s overhead), wastes memory, and can cause transient
# failures under concurrent load — which makes the C++ backend fall back
# to its legacy local parsers.  Reuse one instance instead.
_md_instance = None
_md_lock = threading.Lock()

def _get_markitdown():
    """Return a process-wide singleton MarkItDown instance (lazy init)."""
    global _md_instance
    if _md_instance is None:
        with _md_lock:
            if _md_instance is None:
                from markitdown import MarkItDown
                _md_instance = MarkItDown()
                logger.info("MarkItDown singleton initialised for /convert endpoint")
    return _md_instance
```

每次请求新建实例会重载 magika ONNX 模型（约 0.5s）并在并发下出现瞬时失败——那会让 C++ 误判"Python 转换坏了"而回退旧解析器，所以单例不是优化而是契约。转换本身 `asyncio.to_thread(md.convert, ...)`（:187），避免大文件阻塞事件循环。

**门控（D2b）**：`/convert` 的读取经 `_assert_file_readable_for_task`（:79-110）——三层判定，全部通过才放行：

```python
# markitdown.py:88-110（节选）
workspace, extract_root, files_db = await _task_conversion_anchors(task_id, workspace_root)
candidate = Path(file_path)
try:
    task_store.resolved_within(workspace, candidate)     # 1) workspace 成员
    return
except task_store.TaskStoreError:
    pass
if extract_root is not None:
    try:
        task_store.resolved_within(extract_root, candidate)  # 2) 服务端派生的抽取根
        return
    except task_store.TaskStoreError:
        pass
if files_db is not None:
    try:
        if task_store.file_known_to_task(files_db, file_path):  # 3) files.db 精确已知记录
            return
    except task_store.TaskStoreError:
        raise HTTPException(status_code=400, detail="task files database is unavailable") from None
raise HTTPException(status_code=400, detail="file is outside the task workspace")
```

`resolved_within` 是组件感知包含（task_store.py:122-137，resolve 后 `relative_to`，兄弟前缀 `/t/a` vs `/t/abc` 不可混）；`internal_extract_root` 固定为 `<tempdir>/forensics_llm_extract`（task_store.py:158-160）——与 C++ `LLMAnalysisService::resolveFileForAnalysis` 的共享契约；`file_known_to_task` 用只读 URI 打开 files.db 查 `files.path` 精确命中（task_store.py:163-191）。三层全不过即 400 fail-closed。批量族用写锚：`_task_workspace_or_400` 解析 workspace（:113-130）后 `task_store.resolved_within` 强制 input/output 都在 workspace 内，且**拒绝任何符号链接组件**（:410-414、:555-559，`has_symlink_component` 在 lexical 层检查、先于 resolve——task_store.py:140-155 注释说明原因）。

**批量防自毁**：输出树与输入树重叠（含互相嵌套）一律 400（:434-465）；镜像命名会把输入 `x` 写成 `x.md`，与同名兄弟输入冲突也 400（:604-613）；写入走同目录临时文件 + `os.replace` 原子替换（:358-368）：

```python
# markitdown.py:358-368
def _write_markdown_atomic(output_path: Path, markdown: str) -> int:
    """Write Markdown through a reserved same-directory temporary file."""
    temp_path = output_path.parent / (
        f".tracelens-textdump-tmp-{uuid.uuid4().hex}-{output_path.name}"
    )
    try:
        temp_path.write_text(markdown, encoding="utf-8")
        os.replace(temp_path, output_path)
        return output_path.stat().st_size
    finally:
        temp_path.unlink(missing_ok=True)
```

同目录保证 `os.replace` 原子（同文件系统）；finally 的 `unlink(missing_ok=True)` 清理替换后残留的临时名。批量并发用 `Semaphore(4)` 限内存（:626）；错误清单封顶 50 条（:636-637）。错误文本只回异常**类名**（`_exception_text`，:297-301）——库错误消息可能内嵌服务器解析路径。

**提取器选择**：批量/单条转换经 `get_document_extractor_locator()`（:377），扩展名→提取器映射及回退链定义在 `python_service/config/extractor_mapping.json`（如 `.docx`→DocxExtractor、`.xlsx/.pptx`→OfficeServiceAdapter、`.docx` 缺 MarkItDown 时回退 DocxExtractor）；无匹配提取器时回退原始文本直读（UTF-8 严格→latin-1，二进制启发式 `_is_likely_binary`——NUL 字节或非文本字节 >30% 即跳过，:508-520、:382-389）。office /parse 的解析器在 services/office_service.py：openpyxl（:63）/ xlrd（:106）/ python-pptx（:143），内部再兜底 subprocess。office 的门控（office.py:58-105）是"已知记录或抽取目录"二选一，未知即 404 "file is not part of the current task"——即使宿主机上存在。

## 5. 端点签名速查

- `POST /api/markitdown/convert`：`ConvertRequest → ConvertResponse{success,content,title,processing_time_ms}`（:141-222）。
- `GET /api/markitdown/status`：可用性 + 支持格式清单（:225-245）。
- `POST /api/markitdown/convert-one`：`ConvertOneRequest{task_id?,workspace_root?,input_root,input_file,output_root} → ConvertOneResponse`（:400-485）。
- `POST /api/markitdown/batch-convert`：`BatchConvertRequest → BatchConvertResponse{total_files,converted,skipped,failed,errors≤50,output_dir}`（:523-653）。
- `POST /api/office/parse`：`ParseRequest{task_id?,workspace_root?,file_path} → ParseResponse{success,content,file_type,error?}`（office.py:39-148）。
- `GET /api/office/supported-types`：静态清单（:151-161）。

## 6. 边界与已知状态（400/404/降级）

- **门控优先于存在性**：office /parse 里文件"不在本任务已知记录且不在抽取目录"时 404 "file is not part of the current task"（office.py:63-105），即使宿主机上该路径存在——这是设计而非 bug。markitdown /convert 则先门控（400）后查存在（404，markitdown.py:163-180），错误码顺序有讲究。
- **库缺失降级**：markitdown 未安装时 /status 返回 `available:false`（:241-245），/convert 抛 ImportError → 500 并给出安装提示（:206-210）。
- **office /parse 的软失败**：解析异常返回 200 + `success:false` + `error:"office parse failed"`（office.py:141-148），而非 5xx——调用方（C++ OfficeAnalyzer）按 success 字段走回退。
- 批量的 `_exception_text` 纪律同样适用于响应里的 errors 列表；`/batch-convert` 的 `success:true` 只表示"批跑完了"，要看 failed 计数。
- 两个模块都接受 deprecated `workspace_root`，新调用应带 `task_id`（office.py:26、markitdown.py:51 注释）。
- env：无本组专属 env；task_store 锚定依赖 C++ 任务元数据（`CPP_BACKEND_URL`）。

## 7. 如何验证

- `python_service/tests/unit/test_markitdown_routes.py`（convert/convert-one/batch-convert 的门控、重叠拒绝、镜像命名）、`test_d2b_office_routes.py`（office 成员门控）、`test_d2b_task_store.py`（锚解析）、`test_forensic_extractors.py`（提取器映射与回退链）。
- 活体：live-integration.md 的 Markitdown/Office socket handoff（C++ 真实发起到 :8090 的调用链）。
- 手工：`curl -XPOST :8090/api/markitdown/status` → 带 task_id 调 `/convert` → 在 workspace 内建 testdir 调 `/batch-convert` 检查镜像 `.md` 树。

相关阅读：[HTTPRoutes.md](../HTTPRoutes.md)、[LLM.md](LLM.md)（消费这些文本的 LLM 分析链）、[Database.md](Database.md)。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
