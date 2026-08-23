# OfficeAnalyzer（src/analyzers/OfficeAnalyzer/）

> **一句话**：单个 Office 文档的内容提取器——docx 用本地 DuckX 解析，doc 用外部工具 antiword，xlsx/xls/pptx/ppt 通过 HTTP 转发给 Python 服务的 markitdown 管线，统一返回 Markdown 文本。它不建库、不跑流水线，是给 LLM 文件分析喂内容的"翻译件"。

## 1. 为什么有这个模块

取证镜像里最常见的"有内容"证据就是办公文档：合同、账单、通讯录、嫌疑人写的计划书。但 Office 格式是压缩 XML（新版 OOXML）或复合二进制（旧版 OLE2），裸读全是乱码；LLM 也吃不下二进制。所以需要一个稳定的"文档→Markdown"转换层：文本类证据进了这个漏斗，才能参与后续的 LLM 摘要、全文检索和报告生成。

这个模块最有意思的设计是**混合执行策略**：docx 用 C++ 本地库（`libs/DuckX`，随项目源码编译，无外部依赖），doc 用系统工具 antiword，而表格/幻灯片类（xlsx/xls/pptx/ppt）没有找到满意的 C++ 库，干脆转发给 Python 服务——那边的生态（markitdown/openpyxl/python-pptx）成熟得多。这是一个务实的"跨语言分工"：C++ 管镜像和流水线，Python 管文档解析。代价是产生了一个跨服务依赖（见第 4、6 节），且两者必须能访问**同一个文件路径**。

定位上要注意：它不是 AndroidAnalyzer 那种"阶段分析器"，而是**无状态的文件级工具类**——输入一个绝对路径，输出一段 Markdown，仅此而已。所有取证语义（这个文档重要吗、属于哪个任务）都在调用方。

## 2. 类结构与核心接口

整个模块就是一个 200 余行的类（`OfficeAnalyzer.h:8-70`、`OfficeAnalyzer.cpp`），无继承无依赖注入，唯一的成员状态是 Python 服务地址：

```cpp
// OfficeAnalyzer.h（节选）
class OfficeAnalyzer {
public:
    std::string analyze(const std::string& filePath);        // 主入口：按扩展名分派，返回 Markdown
    std::string analyzeToFile(const std::string& filePath,
                               const std::string& outputDir = "");  // 落成同名 .md 文件
    void setPythonServiceUrl(const std::string& url);        // 覆盖默认服务地址
private:
    std::string pythonServiceUrl_;
    std::string analyzeDocx(const std::string& filePath);    // 本地 DuckX
    std::string analyzeDoc(const std::string& filePath);     // 外部 antiword
    std::string analyzeXlsx/Xls/Pptx/Ppt(...);               // 四个转发壳，全部调 callPythonService
    bool hasExtension(const std::string& filePath, const std::string& ext);
    std::string execCommand(const std::string& cmd);         // popen 封装
    std::string callPythonService(const std::string& filePath);
    std::string getBaseName(const std::string& filePath);
};
```

核心接口清单（含调用方与失败行为）：

| 方法 | 语义 | 调用方 | 失败行为 |
|------|------|--------|---------|
| `std::string analyze(filePath)` | 六种扩展名分派，返回 Markdown 或错误串 | `FileAnalyzer.cpp:166-175`（LLM 文件分析的本地兜底）、测试 | 不支持的扩展名返回 "Error: Unsupported file format..."；解析异常包成 "Error parsing ..." |
| `std::string analyzeToFile(filePath, outputDir="")` | `analyze` 后按 `content.find("Error:") == 0` 判错，成功则写 `<基名>.md` | 独立用法 | 出错或写失败返回空串 |
| `void setPythonServiceUrl(url)` | 覆盖转发目标 | `FileAnalyzer` 把 `ConfigManager::getPythonServiceUrl()` 传进来 | — |
| 构造函数 | 读 `PYTHON_SERVICE_URL` 环境变量，默认 `http://localhost:8090` | — | 环境变量缺失走默认值 |

## 3. 在流水线中的位置

生产调用方是 LLM 集成层的 `FileAnalyzer`（`src/integration/LLMIntegration/FileAnalyzer.cpp:166-175`）：LLM 分析一个文件时，首选 Python 的 markitdown 做转换；markitdown 不可用或失败时，按扩展名降级——`.pdf` 给 PDFAnalyzer，`.docx/.doc` 给 OfficeAnalyzer，其余走原始文本读取。因此 OfficeAnalyzer 实际上是"LLM 文件分析的本地兜底解析器"，服务对象是 `LLMAnalysisService`/`EventClusterAnalyzer` 这条文件内容分析链。

也提供独立用法：`analyze(filePath)` 返回 Markdown 字符串；`analyzeToFile(filePath, outputDir)` 落成同名 `.md` 文件（`OfficeAnalyzer.cpp:168-201`）。没有数据库输出，不写任何表。

## 4. 解析机制走读

**链路一：docx 的本地解析（`analyzeDocx`，`OfficeAnalyzer.cpp:47-65`）。**

```cpp
// OfficeAnalyzer.cpp:47-65
std::string OfficeAnalyzer::analyzeDocx(const std::string& filePath) {
    try {
        duckx::Document doc(filePath);
        doc.open();

        std::stringstream ss;

        for (auto p : doc.paragraphs()) {
            for (auto r : p.runs()) {
                ss << r.get_text();
            }
            ss << "\n\n"; // New paragraph in Markdown
        }

        return ss.str();
    } catch (const std::exception& e) {
        return std::string("Error parsing DOCX: ") + e.what();
    }
}
```

做什么：两层循环遍历——外层 paragraphs，内层 runs（同一段落里格式不同的文本片段），逐 run 拼接文本，段落结尾加 `\n\n` 变成 Markdown 段落。为什么按 run 拼：Word 把"加粗了一半的句子"存成多个 run，只读段落级文本会丢内容。异常整体捕获包成错误串返回——调用方靠 "Error" 前缀判断成败。DuckX 的能力边界就是这里的天花板——它能拿正文文本，但页眉页脚、表格、嵌入对象、修订记录都不在遍历范围里。对"文档写了什么"这个问题够用，对"文档隐藏了什么"则不足。

**链路二：跨服务转发（`callPythonService`，`OfficeAnalyzer.cpp:98-145`）。**

```cpp
// OfficeAnalyzer.cpp:104-121（节选）
    std::string readBuffer;
    std::string url = pythonServiceUrl_ + "/api/office/parse";

    // Prepare JSON payload
    json payload;
    payload["file_path"] = filePath;
    std::string jsonStr = payload.dump();

    // Set headers
    struct curl_slist* headers = nullptr;
    headers = curl_slist_append(headers, "Content-Type: application/json");

    curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, jsonStr.c_str());
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, WriteCallback);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &readBuffer);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 60L);  // 60 second timeout
```

做什么：目标是 `POST {PYTHON_SERVICE_URL}/api/office/parse`，请求体是 JSON `{"file_path": "<绝对路径>"}`——**传的是路径不是文件内容**，所以 C++ 与 Python 必须共享文件系统（通常都在同一台分析机上，提取出的文件在共享工作区）。libcurl 带 60 秒超时；响应处理在第 133-144 行：`success=true` 取 `content`，否则把 Python 的错误信息包在 "Error from Python service:" 里返回，JSON 解析失败再包一层 "Error parsing Python service response"。三条错误路径返回三种前缀，但 `analyzeToFile` 只认 `"Error:" == 0` 一种（见第 6 节的坑）。

Python 侧（`python_service/httpserver/routes/office.py` + `services/office_service.py`）：`parse` 端点有任务归属校验（文件必须是该任务的已知记录或位于共享提取区），`OfficeService.parse_file` 按后缀分派 openpyxl/python-pptx 等，同步解析扔进 worker 线程避免阻塞事件循环（`office_service.py:44-60`）：

```python
# python_service/httpserver/services/office_service.py:33-56（节选）
        suffix = path.suffix.lower()

        # The concrete parsers (openpyxl / python-pptx / subprocess) are
        # synchronous and can take seconds on large files; offload them to a
        # worker thread so the async event loop is not blocked.
        if suffix == ".xlsx":
            return await asyncio.to_thread(self._parse_xlsx, file_path)
        elif suffix == ".xls":
            return await asyncio.to_thread(self._parse_xls, file_path)
        elif suffix == ".pptx":
            return await asyncio.to_thread(self._parse_pptx, file_path)
        elif suffix == ".ppt":
            return await asyncio.to_thread(self._parse_ppt, file_path)
        else:
            raise ValueError(f"Unsupported file type: {suffix}")
```

`asyncio.to_thread` 是关键一行：大 xlsx 解析可能耗时数秒，直接在事件循环里跑会把整个 HTTP 服务卡死。这条链路就是本项目"跨服务协作"的代表案例：C++ 负责找文件和取证上下文，Python 负责格式生态。

**链路三：doc 的外部工具（`analyzeDoc`，第 67-80 行）。**

```cpp
// OfficeAnalyzer.cpp:67-76
std::string OfficeAnalyzer::analyzeDoc(const std::string& filePath) {
    std::string safePath = "'" + filePath + "'";
    std::string command = "antiword " + safePath;

    try {
        std::string output = execCommand(command);
        if (output.empty()) {
            return "Warning: No content extracted from DOC file or antiword failed.";
        }
        return output;
    } catch (const std::exception& e) {
        return std::string("Error parsing DOC using antiword: ") + e.what();
    }
}
```

老版 .doc 是 OLE2 二进制，C++ 侧没有好库，直接 `popen("antiword '<路径>'")` 取 stdout。工具缺失时输出为空，返回警告字符串（注意是 "Warning:" 前缀，不是 "Error:"）。`execCommand`（第 155-166 行）是标准 popen/pclose 封装，用 RAII unique_ptr 管 FILE*。路径被单引号包进 shell 命令——这条注入面在第 6 节详述。

### 4.1（补充）分派表与六个私有解析器的执行方式对照

`analyze()`（OfficeAnalyzer.cpp:29-44）的六分支 if-else 链即完整分派表：

| 扩展名 | 解析器 | 执行位置 | 依赖 |
|---|---|---|---|
| .docx | analyzeDocx | C++ 进程内 | DuckX（libs/DuckX） |
| .doc | analyzeDoc | 外部进程 popen | antiword（PATH） |
| .xlsx | analyzeXlsx | Python 服务 HTTP | openpyxl |
| .xls | analyzeXls | Python 服务 HTTP | Python 侧（xlrd 或兼容层） |
| .pptx | analyzePptx | Python 服务 HTTP | python-pptx |
| .ppt | analyzePpt | Python 服务 HTTP | Python 侧转换 |
| 其他 | — | — | 返回 "Error: Unsupported..." |

三种执行形态（进程内库/本机子进程/远程 HTTP）在同一个类里并存——按扩展名选路的背后实际是"哪里有生态就走哪里"的工程决策。四个转发壳（xlsx/xls/pptx/ppt）实现完全相同（调 callPythonService），Python 侧按后缀二次分派；这意味着**格式识别做了两遍**（C++ 一遍、Python 一遍），C++ 侧认错时 Python 侧会再报 "Unsupported file type"——两层错误消息不一致是排障时的小陷阱。

### 4.2 代码走读：analyzeToFile 的写盘与判错（OfficeAnalyzer.cpp:168-201）

```cpp
std::string OfficeAnalyzer::analyzeToFile(const std::string& filePath,
                                          const std::string& outputDir) {
    std::string content = analyze(filePath);
    if (content.find("Error:") == 0) {
        return "";
    }
    std::string baseName = getBaseName(filePath);
    std::string outputPath = outputDir.empty() ? baseName + ".md"
                                               : outputDir + "/" + baseName + ".md";
    std::ofstream outFile(outputPath);
    if (!outFile.is_open()) {
        return "";
    }
    outFile << content;
    outFile.close();
    return outputPath;
}
```

逐块解释：写盘路径拼接是朴素字符串相加（`outputDir + "/" + baseName`）——没有创建目录，outputDir 不存在时 open 失败静默返回空串（与"解析失败"同返回值，调用方无法区分）。判错只认 `Error:` 前缀（第 6 节的坑在此），`Warning:`（antiword 空输出）与 `Error parsing DOCX:`（前缀是 "Error " 带空格）都漏网——**会被写成 .md 文件的内容**。baseName 取自 getBaseName（去扩展名的文件名，不含目录）——两个不同目录的同名文档会写同一个 .md（后者覆盖前者）。返回输出路径（成功）或空串（一切失败），无部分写出的中间态（ofstream 一次 << 全量）。


## 5. 与 LLM 的协作

它本身就是 LLM 链路的一环，但自己不调 LLM。产出直接成为 `FileAnalyzer` 拼进 prompt 的文件内容；文本质量（干净的段落结构）直接影响 LLM 摘要质量，这也是 `cleanText` 类整理逻辑存在的意义（PDFAnalyzer 侧有更完整实现，可对照）。

## 6. 与其他模块的协作 / 注意事项

- **依赖**：DuckX（`libs/DuckX`，随项目编译）、libcurl + nlohmann/json（HTTP 转发）、可选外部工具 antiword（PATH 探测，缺失时 doc 解析降级）、Python 服务（xlsx/xls/pptx/ppt 的硬依赖，没起服务时这四类全部失败）。
- **启动顺序**：依赖 Python 服务的功能要求 `python_service` 先跑起来（`./scripts/start_python_service.sh`）；`PYTHON_SERVICE_URL` 不对时所有转发都会以 "Error: HTTP request failed" 返回。
- **`analyzeDoc` 的命令注入面**：路径被单引号包进 shell 命令（第 68-69 行），文件名里含单引号的证据文件可逃逸引号。恶意构造的文件名来自镜像，属于真实风险，改用 execve 数组形式（参考 `DecryptionModule::runProcess` 的做法）是正确的修法。使用时避免让不可信文件名直达此函数。
- **错误前缀不一致**：`analyzeToFile:173-175` 只把 `Error:` 开头当失败，但三类失败路径的前缀并不统一——`"Error: Unsupported..."/"Error: HTTP request failed"` 能被命中；`"Error parsing DOCX: ..."` 同样以 `Error` 开头但第五个字符是空格，`find("Error:") == 0` **不**命中；`analyzeDoc` 失败返回的是 `Warning:` 前缀。结果是非 `Error:` 前缀的失败会被当成有效内容写进 .md 文件，语义上是个坑。
- **只认扩展名不看魔数**：`hasExtension`（第 147-153 行）是大小写不敏感的字符串后缀比较，改名的文件会走错分支（伪装成 .docx 的加密 zip 会进 DuckX 然后报解析错误）。
- **与 MarkitdownProxy 的关系**：两者都调 Python，但走的端点不同（MarkitdownProxy 是通用文本转换，`/api/office/parse` 是 Office 专用）；FileAnalyzer 里 markitdown 是首选、OfficeAnalyzer 是 docx/doc 的本地兜底，xlsx/pptx 反而只有 Python 一条路。

## 7. 如何验证与扩展

- 测试：`tests/UnitTest/test_office_analyzer.cpp` 覆盖 docx 提取（无 Python 服务也能跑）、非法扩展名的报错、四种扩展名的识别。跨服务链路要起 python_service 后手工验证（放一个 xlsx 到工作区，调 `analyze` 看返回的 Markdown）。
- 加新格式：本地库能搞定的（如 odt——本质是 zip+xml）在 `analyze` 分派表加分支写 `analyzeOdt`；只有 Python 生态能搞定的，确认 Python 侧 office_service 支持后同样加分支转发即可，`callPythonService` 是格式无关的。
- 提升方向：docx 提取补充表格与页眉页脚（DuckX 能力有限，可能要换库或解压 XML 直接解析）；给 doc 分支换成无 shell 的调用方式；返回值区分"空文档"与"解析失败"（现在都可能是空串或 Error/Warning 前缀，语义模糊）。

## 8. 方法全清单（OfficeAnalyzer.h:8-70 / cpp 234 行）

| 方法 | 定义位置 | 语义 | 调用方 |
|---|---|---|---|
| `OfficeAnalyzer()` | cpp:20 | getenv PYTHON_SERVICE_URL，缺省硬编码 8090 | FileAnalyzer/测试 |
| `analyze(filePath)` | cpp:29-44 | 六扩展名分派 | FileAnalyzer.cpp:166-175 |
| `analyzeToFile(filePath, outputDir="")` | cpp:168-201 | 转 Markdown 落盘 | 独立用法/测试 |
| `setPythonServiceUrl(url)` | cpp:25-27 | 覆盖转发地址 | FileAnalyzer（注入 ConfigManager 值） |
| 私有 `analyzeDocx` | cpp:47-65 | DuckX 段落/run 遍历 | analyze |
| 私有 `analyzeDoc` | cpp:67-80 | antiword popen | analyze |
| 私有 `analyzeXlsx/Xls/Pptx/Ppt` | cpp:82-96 一带 | 四个转发壳（同构） | analyze |
| 私有 `hasExtension(path, ext)` | cpp:147-153 | 大小写不敏感后缀比较 | 分派 |
| 私有 `execCommand(cmd)` | cpp:155-166 | popen/RAII 封装 | analyzeDoc |
| 私有 `callPythonService(filePath)` | cpp:98-145 | libcurl POST /api/office/parse | 四个转发壳 |
| 私有 `getBaseName(path)` | cpp:约 203-210 | 去扩展名基名 | analyzeToFile |

## 9. 关联矩阵

| 对端 | 方向 | 交互点 | 数据形态 |
|---|---|---|---|
| FileAnalyzer.cpp:166-175 | 上游 | markitdown 失败后的本地兜底（.docx/.doc） | string Markdown |
| ConfigManager.getPythonServiceUrl | 上游 | setPythonServiceUrl 注入 | url |
| DuckX（libs/DuckX） | 下游 | 进程内解析 | C++ API |
| antiword（PATH） | 下游 | popen | stdout |
| python_service /api/office/parse | 下游 | libcurl POST（60s 超时） | JSON{file_path}→{content} |
| office_service.py（Python 侧） | 对端 | openpyxl/python-pptx + asyncio.to_thread | Markdown |
| MarkitdownProxy | 平行 | 不同端点、不同格式面（第 6 节） | — |
| 测试 test_office_analyzer | 消费者 | docx/扩展名识别 | — |

## 10. 配置影响表

| 参数 | 默认 | 影响 | 备注 |
|---|---|---|---|
| `PYTHON_SERVICE_URL`（env，直接 getenv） | `http://localhost:8090`（硬编码） | 转发目标 | **不经 ConfigManager、不回退 PYTHON_HTTP_PORT**（Environment.md 第 7 节已标注）；换端口必须设此变量 |
| `setPythonServiceUrl` 注入 | — | 运行期覆盖 | FileAnalyzer 用 ConfigManager 值注入（两默认值不一致时以注入为准） |
| antiword 在 PATH | — | doc 解析可用性 | 缺失返回 Warning 前缀 |
| curl 超时 | 60s（硬编码） | 转发上限 | 大 ppt 超时即失败 |
| 无 CLI 参数 | — | — | |

## 11. 性能与并发细节

- **三种执行形态的成本差三个量级**：docx 本地解析（毫秒级，zip 解压+XML 遍历）；antiword 子进程（进程创建 ~10ms + 解析）；HTTP 转发（网络往返 + Python 异步队列 + to_thread 解析，大 xlsx 秒级）。批量分析混合文档时耗时由 Python 转发主导。
- **每次转发独立 curl 句柄**：callPythonService 每次 easy_init/cleanup——无连接复用，批量时有可测的握手开销；Keep-Alive 复用是现成优化。
- **线程安全**：类无可变共享状态（pythonServiceUrl_ 构造后只读）——实例可跨线程共用；popen 与 curl 各自线程安全。DuckX 的 Document 是局部对象，无竞争。
- **内存**：整文档文本一次性成串（stringstream 累积），超大 pptx 的 Markdown 输出（数十 MB 级）全驻内存；无流式接口。
- **超时叠加**：调用方（FileAnalyzer）自身有 LLM 超时预算，转发 60s 占用其中大头——超长文档会让 LLM 请求在文档转换阶段就耗尽耐心。

**最后更新**: 2026-08-24（二轮深化：补全表列说明与方法清单）
