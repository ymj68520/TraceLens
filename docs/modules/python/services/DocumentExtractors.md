# DocumentExtractors（python_service/httpserver/services/document_extractor.py + extractors/ + config/extractor_mapping.json + config/artifact_whitelist.json）

> **一句话**：离线"任意证据文件 → Markdown"的提取器体系——`ExtractorLocator` 按文件名精确路由优先、扩展名路由其次（含无扩展名文件的头字节嗅探与 LevelDB 目录识别），注册表由 `config/extractor_mapping.json` 声明式驱动（markitdown 主路径 + 逐扩展名 legacy 回退链），ArchiveExtractor 再用 `config/artifact_whitelist.json` 做"高价值文件优先"的结构化聚合防爆上下文。

## 1. 为什么有这个模块

LLM 只吃文本。取证镜像里的证据是 PDF/Office/注册表/EVTX/压缩包/数据库/内存镜像……每个格式都要一个"转 Markdown"的插件，且路由规则必须可配置（新增格式不改代码）、失败必须可回退（markitdown 转不出来时退到专用提取器）、危险格式必须防上下文爆炸（解压一万个小文件会撑爆 prompt）。该体系的设计回答：

- **声明式路由**：扩展名→提取器类、文件名→提取器类（auth.log/wtmp/SAM 这类无独特扩展名的取证痕迹）都写在 JSON 里，代码只负责装载与实例化；
- **单例复用**：每个提取器类只实例化一次，`MarkItDown` 引擎等重资源全局共享；
- **主路径+回退**：markitdown 覆盖绝大多数文档格式，失败/为空/未安装时按 JSON 里的 `fallback` 表退到 legacy 提取器。

## 2. 在系统中的位置

- **谁调用它**：`routes/markitdown.py`（`/api/markitdown/convert*`：task_store 门卫后逐文件 `locator.get_extractor` → `extract_to_markdown`，无提取器时按二进制嗅探跳过或 latin-1 兜底，:374-389）；LLM FileAnalyzer 的文档通道（批量分析先抽取再喂模型）；legacy InvestigationService 的 `_extract_file_text`（investigation_service.py:782-797：抽取失败退原始读）。
- **它调用谁**：markitdown 库（MarkItDown 引擎）；各格式专用库（openpyxl/python-pptx/xlrd/EVTX 解析器等）；`office_service`（经 `extractors/office.py` 的 OfficeServiceAdapter 包装）；外部工具（catppt 等，经各提取器内部 subprocess）。
- **配置**：`python_service/config/extractor_mapping.json`（路由与回退）与 `python_service/config/artifact_whitelist.json`（ArchiveExtractor 的高价值清单）。

## 3. 核心数据结构：三个注册表

```python
# extractors/__init__.py:13-21
# The global registry acting as our routing map.
# Key: string extension (e.g. ".pdf", "leveldb"), Value: initialized Extractor instance
extractor_registry = {}

# Staging ground for subclasses that use @register_extractor
registered_extractor_classes = {}

# Filename-based routing for files without unique extensions (e.g. auth.log, wtmp, SAM)
filename_extractor_registry = {}
```

- `extractor_registry`：扩展名（小写）→ 提取器**实例**（不是类）——查找即命中，运行期零实例化开销；
- `registered_extractor_classes`：`@register_extractor` 装饰器（base.py:20-30）在插件模块 import 时填充的"类名→类"暂存区，装载器据此把 JSON 里的字符串类名解析成真类；
- `filename_extractor_registry`：精确文件名 → 实例（auth.log、wtmp、SAM 等无独特扩展名的取证痕迹），`get_extractor_by_filename` 用**大小写敏感的精确 dict 查找**（无前缀/通配）。

## 4. 核心接口清单

| 接口（真实签名） | 语义 | 调用方 | 失败行为 |
|---|---|---|---|
| `ExtractorLocator().get_extractor(file_path: str) -> Optional[BaseExtractor]` | LevelDB 目录/头字节嗅探 → 文件名路由 → 扩展名路由 | markitdown 路由、FileAnalyzer | 无匹配返回 None（调用方走二进制/latin-1 兜底） |
| `get_extractor(extension: str)` | 扩展名注册表查询 | locator | 未知扩展名 None |
| `get_extractor_by_filename(filename: str)` | 文件名注册表查询 | locator | 不匹配 None |
| `load_plugins()` | 动态 import 插件 → 读 JSON → 双趟建表 → 接线回退 | 包 import 时自动执行 | 单插件失败记日志跳过 |
| `BaseExtractor.extract_to_markdown(file_path: str) -> str`（各实现） | 单文件转 Markdown | 转换循环 | 抛异常/返回错误文本（实现而异） |
| `ArchiveExtractor.extract_to_markdown` | 白名单聚合（不解压） | 同上 | 同上 |
| `get_document_extractor_locator() -> ExtractorLocator` | 定位器单例 | 路由层 | 不失败 |

## 5. 核心概念与设计

**（a）定位器（document_extractor.py）。** `ExtractorLocator.get_extractor`（:27-63）的判定顺序：

```python
# document_extractor.py:29-63（节选）
path = Path(file_path)

# Special fallback for LevelDB directories
if path.is_dir() and (path / "CURRENT").exists():
    ext = "leveldb"
elif not path.suffix:
    head = b""
    try:
        with open(file_path, "rb") as f:
            head = f.read(8)
    except Exception:
        pass
    text_mime_candidates = {b"\xEF\xBB\xBF", b"#!", b"<?xml", b"<html", b"<!DOC", b"{\n", b"[{", b"# "}
    if head and any(head.startswith(candidate) for candidate in text_mime_candidates):
        ext = ".txt"
    else:
        logger.info("No extractor available for empty extension: %s", file_path)
        return None
else:
    ext = path.suffix.lower()

# Try filename-based routing first (for auth.log, wtmp, SAM, etc.)
extractor = get_extractor_by_filename(path.name)
if extractor:
    logger.info(f"Routed '{path.name}' to {extractor.__class__.__name__} (by filename)")
    return extractor

# Fall back to extension-based routing
extractor = get_extractor(ext)
```

四级判定：目录含 `CURRENT` → leveldb（微信等应用的 KV 存储）；**无扩展名** → 读 8 字节头，命中 BOM/`#!`/`<?xml`/`<html`/`<!DOC`/`{\n`/`[{`/`# ` 等文本特征则当 `.txt`，否则放弃（:32-46）；有扩展名 → 先查**文件名精确路由**（:51-54），再查扩展名路由（:57-63）。注意文件名路由优先于扩展名——`auth.log` 不会落进日志类的扩展名分支。定位器本身是模块级单例（:66-72），无状态。

**（b）注册表装载（extractors/__init__.py）。** 包 import 即执行 `load_plugins()`（:156），四步。第 2 步读 JSON（路径经三层 dirname 回溯定位，:46-55）；第 3 步双趟建表——**主提取器**（带 `fallback` 字段的复合条目，如 MarkitdownExtractor）先注册并把其扩展名记入 `primary_extensions`；**简单提取器**后注册且跳过已被主提取器认领的扩展名：

```python
# extractors/__init__.py:92-105（节选）
instance = instances[class_name]

# Skip simple extractors whose extensions are already claimed by a primary extractor
if not fallback_map:
    ext_list = [ext for ext in ext_list if ext.lower() not in primary_extensions]

if class_name == "SQLiteExtractor":
    ext_list = [ext for ext in ext_list if ext.lower() != ".db"]
    primary_extensions.add(".sqlite")
    primary_extensions.add(".sqlite3")

# Register the extensions pointing to the singleton instance
for ext in ext_list:
    extractor_registry[ext.lower()] = instance
```

特殊规则：SQLiteExtractor 不得认领通用 `.db`（:98-102），兜底把 `.db` 指给 GenericDatabaseExtractor 防止非 SQLite 库走错解析器（:143-146），并给无扩展名路由 `.` 配一个通用文本兜底（:148-153）。回退链在装载期"接线"：`instance._fallback_map[ext] = fallback_instance`（:107-125），运行期零查表开销。

**（c）markitdown 主路径（extractors/markitdown_extractor.py）。** 构造函数只建一次 `MarkItDown()`，且**故意捕获所有异常**而非只 ImportError——注释记录了 magika ONNX 模型加载失败曾让构造抛错、`load_plugins` 静默跳过、所有文档格式无声跌回 legacy 提取器的事故（:42-50）。`extract_to_markdown`（:57-136）的三个防御点：同步 `convert` 丢进执行器（:88-91，保持 async 契约）；markitdown 把读失败**包进 markdown 正文**而不是抛异常，这里显式检测错误文本并转 `FileNotFoundError`，防止把"读文件出错"当证据喂给 LLM（:96-102）；输出为空或异常时按 `_fallback_map` 退到 legacy 提取器，回退也失败才 raise（:107-135）。

**（d）路由配置（config/extractor_mapping.json）。** 主条目示意（:2-17）：

```json
"MarkitdownExtractor": {
  "extensions": [".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt",
                 ".html", ".htm", ".ipynb", ".rss", ".jpg", ...],
  "fallback": {
    ".pdf": "PDFExtractor", ".docx": "DocxExtractor",
    ".doc": "DocParserProxy",
    ".xlsx": "OfficeServiceAdapter", ".xls": "OfficeServiceAdapter",
    ".pptx": "OfficeServiceAdapter", ".ppt": "OfficeServiceAdapter"
  }
}
```

其余约 70 个提取器条目是简单扩展名列表（EvtxExtractor `.evtx`、PstExtractor `.pst/.ost`、PcapExtractor `.pcap/.pcapng`、RawMemoryExtractor `.raw/.mem/.bin` 等）。`_filename_routes`（:110-135）把 `auth.log*`→AuthLogExtractor、`wtmp/utmp/btmp`→WtmpExtractor、注册表五件套（SAM/SYSTEM/SOFTWARE/SECURITY/DEFAULT/NTUSER.DAT/UsrClass.dat）→RegistryExtractor、`places.sqlite`→FirefoxHistoryExtractor、`thumbcache_*.db`→ThumbcacheExtractor、`ActivitiesCache.db`→WindowsTimelineExtractor 等按**精确文件名**钉死。

**（e）白名单与压缩包聚合（extractors/archives.py）。** ArchiveExtractor **不解压**，做结构化聚合：遍历 zip/tar 成员树，`_load_whitelist`（:24-52）读 `config/artifact_whitelist.json`（缺失时用内置默认），`_is_high_value`（:54-60）按高价值文件名/扩展名（`.db/.sqlite/.evtx/.log`、SAM/shadow/passwd 等）筛出重点条目，配合 `max_tree_lines=50` 截断目录树——白名单文件永远展示，其余只给统计。

## 6. 工作流程走读：一次 convert-one

`POST /api/markitdown/convert-one`（routes/markitdown.py:399+）→ task_store 校验 workspace/symlink/包含性 → `_convert_file_to_output`（:374-395）：`locator.get_extractor(file_path)` → 命中则 `extractor.extract_to_markdown`（markitdown 失败自动走 fallback 链）→ 未命中任何提取器则读原始字节：疑似二进制跳过，文本按 UTF-8 严格解码失败退 latin-1，包成 fenced 代码块 → 原子写（临时文件 + `os.replace`）镜像路径下的 `.md`。

## 7. 与其他模块的协作

| 模块 | 协作方式 |
|---|---|
| routes/markitdown | 主要 HTTP 消费者；task_store 门卫 + 原子写出 |
| LLMService / FileAnalyzer | 批量分析的文档→文本通道 |
| office_service | 经 OfficeServiceAdapter 成为 Office 格式的 legacy 回退 |
| investigation（legacy `_extract_file_text`） | 二次分析读证据内容的抽取通道 |
| config JSON ×2 | 声明式路由与白名单，运行时唯一权威 |

## 8. 注意事项与已知问题

- `load_plugins` 在**包 import 时**执行（extractors/__init__.py:156）——任何插件模块的顶层异常都会在首次 import 时打日志并被跳过，表现为"某格式突然没有提取器"，排查先看启动日志的 `Failed to load extractor plugin`。
- mapping JSON 里类名拼错只在装载期 warning（`Mapped class not found`），不 fail-fast；新增提取器后建议对 `get_extractor(".xxx")` 做冒烟断言。
- markitdown 的错误文本检测（`"an error occurred while reading the file"` 前 300 字符）是对其行为契约的依赖，升级 markitdown 时需回归（markitdown_extractor.py:96-102）。
- 文件名路由是**精确匹配**（含大小写敏感的 `NTUSER.DAT`/`UsrClass.dat`），取证镜像里常见的大小写变体（ntuser.dat）不会被 `_filename_routes` 命中——白名单判断倒是 lower-case 的，两层行为不一致。
- LevelDB 目录检测要求传入的是目录路径；对"目录但无 CURRENT"的输入会落到无扩展名分支并大概率返回 None。
- 装载顺序敏感：`_filename_routes` 的解析在主表之后（:127-141），其引用的类若已在 instances 中则复用同一单例——文件名路由与扩展名路由共享实例，提取器实现必须保持无状态。

## 9. 如何验证（python_service/tests/unit/）

- `test_forensic_extractors.py`（各插件提取正确性/路由命中）、`test_media_metadata.py`（图像/视频元数据提取器）、`test_markitdown_routes.py`（路由门卫、输出原子性、回退链触发）。
- 手工验证：`python -c "from httpserver.services.extractors import get_extractor; print(get_extractor('.evtx'))"` 应返回 EvtxExtractor 实例；`GET /api/markitdown/...` 后检查镜像 `.md` 的产出与 `_filename_routes` 行为。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
