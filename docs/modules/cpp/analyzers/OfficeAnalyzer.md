# OfficeAnalyzer（src/analyzers/OfficeAnalyzer/）

> **一句话**：单个 Office 文档的内容提取器——docx 用本地 DuckX 解析，doc 用外部工具 antiword，xlsx/xls/pptx/ppt 通过 HTTP 转发给 Python 服务的 markitdown 管线，统一返回 Markdown 文本。它不建库、不跑流水线，是给 LLM 文件分析喂内容的"翻译件"。

## 1. 为什么有这个模块

取证镜像里最常见的"有内容"证据就是办公文档：合同、账单、通讯录、嫌疑人写的计划书。但 Office 格式是压缩 XML（新版 OOXML）或复合二进制（旧版 OLE2），裸读全是乱码；LLM 也吃不下二进制。所以需要一个稳定的"文档→Markdown"转换层：文本类证据进了这个漏斗，才能参与后续的 LLM 摘要、全文检索和报告生成。

这个模块最有意思的设计是**混合执行策略**：docx 用 C++ 本地库（`libs/DuckX`，随项目源码编译，无外部依赖），doc 用系统工具 antiword，而表格/幻灯片类（xlsx/xls/pptx/ppt）没有找到满意的 C++ 库，干脆转发给 Python 服务——那边的生态（markitdown/openpyxl/python-pptx）成熟得多。这是一个务实的"跨语言分工"：C++ 管镜像和流水线，Python 管文档解析。代价是产生了一个跨服务依赖（见第 4、6 节），且两者必须能访问**同一个文件路径**。

定位上要注意：它不是 AndroidAnalyzer 那种"阶段分析器"，而是**无状态的文件级工具类**——输入一个绝对路径，输出一段 Markdown，仅此而已。所有取证语义（这个文档重要吗、属于哪个任务）都在调用方。

## 2. 在流水线中的位置

生产调用方是 LLM 集成层的 `FileAnalyzer`（`src/integration/LLMIntegration/FileAnalyzer.cpp:166-175`）：LLM 分析一个文件时，首选 Python 的 markitdown 做转换；markitdown 不可用或失败时，按扩展名降级——`.pdf` 给 PDFAnalyzer，`.docx/.doc` 给 OfficeAnalyzer，其余走原始文本读取。因此 OfficeAnalyzer 实际上是"LLM 文件分析的本地兜底解析器"，服务对象是 `LLMAnalysisService`/`EventClusterAnalyzer` 这条文件内容分析链。

也提供独立用法：`analyze(filePath)` 返回 Markdown 字符串；`analyzeToFile(filePath, outputDir)` 落成同名 `.md` 文件（`OfficeAnalyzer.cpp:168-201`）。没有数据库输出，不写任何表。

## 3. 证据来源与覆盖范围

按扩展名六种（`analyze` 的分派，`OfficeAnalyzer.cpp:29-45`）：

| 扩展名 | 处理方 | 说明 |
|-------|--------|------|
| .docx | 本地 DuckX（`analyzeDocx`） | 段落→run→文本，段落间补空行形成 Markdown 段落 |
| .doc | 外部 antiword（`analyzeDocx` 的兄弟 `analyzeDoc`） | popen 调命令行工具，取 stdout |
| .xlsx / .xls / .pptx / .ppt | Python 服务（`callPythonService`） | HTTP 转发，见第 4 节 |

注意覆盖的边界：只认扩展名不看魔数（`hasExtension` 是大小写不敏感的字符串后缀比较，第 147-153 行），改名的文件会走错分支。表格类被 Python 侧拒绝时会返回错误字符串（以 "Error:" 开头），调用方靠这个前缀判断成败（`analyzeToFile:173-175`）。

## 4. 解析机制走读

**链路一：docx 的本地解析（`analyzeDocx`，`OfficeAnalyzer.cpp:47-65`）。** `duckx::Document` 打开文件后，两层循环遍历：外层 paragraphs，内层 runs（同一段落里格式不同的文本片段），逐 run 拼接文本，段落结尾加 `\n\n` 变成 Markdown 段落。DuckX 的能力边界就是这里的天花板——它能拿正文文本，但页眉页脚、表格、嵌入对象、修订记录都不在遍历范围里。对"文档写了什么"这个问题够用，对"文档隐藏了什么"则不足。

**链路二：跨服务转发（`callPythonService`，`OfficeAnalyzer.cpp:98-145`）。** 目标 URL 是 `pythonServiceUrl_ + "/api/office/parse"`，基础地址来自 `PYTHON_SERVICE_URL` 环境变量，默认 `http://localhost:8090`（构造函数第 21 行），调用方可 `setPythonServiceUrl()` 覆盖（`FileAnalyzer` 就是把 `ConfigManager::getPythonServiceUrl()` 传了进来）。请求体是 JSON `{"file_path": "<绝对路径>"}`——**传的是路径不是文件内容**，所以 C++ 与 Python 必须共享文件系统（通常都在同一台分析机上，提取出的文件在共享工作区）。libcurl 带 60 秒超时；响应 JSON 里 `success=true` 取 `content`，否则把 Python 的错误信息包在 "Error from Python service:" 里返回。

Python 侧（`python_service/httpserver/routes/office.py` + `services/office_service.py`）：`parse` 端点有任务归属校验（文件必须是该任务的已知记录或位于共享提取区），`OfficeService.parse_file` 按后缀分派 openpyxl/python-pptx 等，同步解析扔进 worker 线程避免阻塞事件循环（`office_service.py:44-60`）。这条链路就是本项目"跨服务协作"的代表案例：C++ 负责找文件和取证上下文，Python 负责格式生态。

**链路三：doc 的外部工具（`analyzeDoc`，第 67-80 行）。** 老版 .doc 是 OLE2 二进制，C++ 侧没有好库，直接 `popen("antiword '<路径>'")` 取 stdout。工具缺失时输出为空，返回警告字符串。

## 5. 与 LLM 的协作

它本身就是 LLM 链路的一环，但自己不调 LLM。产出直接成为 `FileAnalyzer` 拼进 prompt 的文件内容；文本质量（干净的段落结构）直接影响 LLM 摘要质量，这也是 `cleanText` 类整理逻辑存在的意义（PDFAnalyzer 侧有更完整实现，可对照）。

## 6. 与其他模块的协作 / 注意事项

- **依赖**：DuckX（`libs/DuckX`，随项目编译）、libcurl + nlohmann/json（HTTP 转发）、可选外部工具 antiword（PATH 探测，缺失时 doc 解析降级）、Python 服务（xlsx/xls/pptx/ppt 的硬依赖，没起服务时这四类全部失败）。
- **启动顺序**：依赖 Python 服务的功能要求 `python_service` 先跑起来（`./scripts/start_python_service.sh`）；`PYTHON_SERVICE_URL` 不对时所有转发都会以 "Error: HTTP request failed" 返回。
- **`analyzeDoc` 的命令注入面**：路径被单引号包进 shell 命令（第 68-69 行），文件名里含单引号的证据文件可逃逸引号。恶意构造的文件名来自镜像，属于真实风险，改用 execve 数组形式（参考 `DecryptionModule::runProcess` 的做法）是正确的修法。使用时避免让不可信文件名直达此函数。
- **与 MarkitdownProxy 的关系**：两者都调 Python，但走的端点不同（MarkitdownProxy 是通用文本转换，`/api/office/parse` 是 Office 专用）；FileAnalyzer 里 markitdown 是首选、OfficeAnalyzer 是 docx/doc 的本地兜底，xlsx/pptx 反而只有 Python 一条路。

## 7. 如何验证与扩展

- 测试：`tests/UnitTest/test_office_analyzer.cpp` 覆盖 docx 提取（无 Python 服务也能跑）、非法扩展名的报错、四种扩展名的识别。跨服务链路要起 python_service 后手工验证（放一个 xlsx 到工作区，调 `analyze` 看返回的 Markdown）。
- 加新格式：本地库能搞定的（如 odt——本质是 zip+xml）在 `analyze` 分派表加分支写 `analyzeOdt`；只有 Python 生态能搞定的，确认 Python 侧 office_service 支持后同样加分支转发即可，`callPythonService` 是格式无关的。
- 提升方向：docx 提取补充表格与页眉页脚（DuckX 能力有限，可能要换库或解压 XML 直接解析）；给 doc 分支换成无 shell 的调用方式；返回值区分"空文档"与"解析失败"（现在都可能是空串或 Error 前缀，语义模糊）。

**最后更新**: 2026-08-23（解释式重写）
