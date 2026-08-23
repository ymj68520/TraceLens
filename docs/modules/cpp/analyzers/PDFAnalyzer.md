# PDFAnalyzer（src/analyzers/PDFAnalyzer/）

> **一句话**：基于 Poppler-cpp 的 PDF 内容与元数据提取器——逐页抽文本、读文档信息字典（作者/标题/创建工具等）、生成供 LLM 用的 Markdown 报告。与 OfficeAnalyzer 同类：无状态的文件级工具，不建库不落表。

## 1. 为什么有这个模块

PDF 在取证证据里的地位很特殊：它是"最终态"文档——合同签署版、正式报告、外发的材料——内容可信度高，且自带一套元数据（Author、Producer、CreationDate）经常泄露文档的真实来源和制作工具（"Producer: Microsoft Word"还是"Producer: 某些改稿工具"本身就是线索）。同时 PDF 的内部结构是对象流加压缩滤镜，手工解析不现实，需要一个成熟解析库。Poppler 是 Linux 世界事实标准的 PDF 渲染/解析引擎（xdft 系工具的底层），其 C++ 绑定（poppler-cpp）提供稳定的文本与元数据 API——这个模块就是 Poppler 的一层薄封装，把"打开文档、逐页取字、读信息字典"这三件事包装成三个静态方法。

第二个存在理由与 OfficeAnalyzer 相同：**给 LLM 喂干净文本**。PDF 抽出的原始文本充满多余空白和断行，直接进 prompt 会浪费 token 且干扰理解，所以这里专门实现了 `cleanText` 做空白规整（多个空格合一、按换行数量保留段落结构），这是"为下游消费者优化输出"的典型细节。

## 2. 核心数据结构与接口

全模块只有两个类型（`PDFAnalyzer.h:10-54`）：

```cpp
struct PDFMetadata {
    std::string title;
    std::string author;
    std::string subject;
    std::string keywords;
    std::string creator;      // 创建应用（写作软件）
    std::string producer;     // 生成引擎（打印/转换链），取证上常比 creator 更"诚实"
    int pageCount = 0;
    std::vector<std::string> permissions;
    int64_t creationTime = 0;     // 恒为 0（未实现 D: 时间解析，见下文）
    int64_t modificationTime = 0;
    bool isEncrypted = false;
};

class PDFAnalyzer {
public:
    static std::string extractText(const std::string& pdfPath);
    static PDFMetadata extractMetadata(const std::string& pdfPath);
    static bool createLLMReport(const std::string& pdfPath, const std::string& outputPath);
private:
    static std::string cleanText(const std::string& text);
};
```

接口清单（全静态、无实例状态）：

| 方法 | 语义 | 调用方 | 失败行为 |
|------|------|--------|---------|
| `extractText(pdfPath)` | 逐页抽文本，页前插 `--- Page N ---` 分隔 | `FileAnalyzer.cpp:166-170`（LLM 文件分析的 PDF 兜底）、测试 | 加载失败/异常返回空串；加密锁定返回占位串 `[Encrypted PDF - Content Locked]` |
| `extractMetadata(pdfPath)` | 读信息字典六键 + 页数 + 加密标志 | `createLLMReport` 内部、测试 | 失败返回全默认值的结构体 |
| `createLLMReport(pdfPath, outputPath)` | 生成 Markdown 报告文件 | **当前无生产调用方**（仅测试），即用型预留 | 文件不存在/打不开输出即 false |

`creator` 与 `producer` 的区分有取证意义：前者是用户可见的"创建程序"（可被改），后者是底层 PDF 引擎（Word 另存时是 "Microsoft Word"，LaTeX 编译是 pdfTeX）——两者不一致本身就是"文档被动过"的弱信号。

## 3. 在流水线中的位置

生产调用方是 LLM 集成层的 `FileAnalyzer`（`src/integration/LLMIntegration/FileAnalyzer.cpp:166-170`）：LLM 分析文件内容时，若 markitdown（Python 服务）不可用或失败，`.pdf` 文件降级到 `PDFAnalyzer::extractText(filePath)`。即它是 PDF 在"LLM 文件分析"链路上的本地兜底。

没有数据库输出、无实例状态（全静态方法），是最小耦合的工具模块。

## 4. 证据来源与覆盖范围

- **正文文本**：逐页 `poppler::page::text()`，每页前插入 `--- Page N ---` 分隔行（`PDFAnalyzer.cpp:45`），页与页之间空行分隔。加密锁定文档返回占位串 `[Encrypted PDF - Content Locked]` 而不是空串（第 28-31 行）——调用方能区分"没内容"和"读不了"。
- **元数据**：信息字典六键（Title/Author/Subject/Keywords/Creator/Producer，第 80-85 行）+ 页数 + 加密标志 + 权限（锁定时记 "Read Locked"）。
- **明确不覆盖的**：PDF 里的嵌入图片（OCR 不做）、附件文件、注释/批注、JavaScript；时间戳字段当前恒为 0——源码注释直言 PDF 的 `D:YYYYMMDDHHmmSS` 格式解析"留待以后"（第 87-89 行）。做时间线时别指望这里的 creationTime。

### 2.1（补充）PDFMetadata 逐字段与写入条件对照（PDFAnalyzer.cpp:58-97）

| 字段 | 来源 | 写入条件 | 取证备注 |
|---|---|---|---|
| title/author/subject/keywords/creator/producer | doc->info_key("...") 六键 | 打开成功且键存在 | 空键返回空串（Poppler 的 optional 语义） |
| pageCount | doc->pages() | 打开成功 | 加锁文档也可读页数 |
| permissions | 硬编码 "Read Locked" 一项 | is_locked() 为真 | 无细粒度权限位（打印/复制权限不读） |
| creationTime/modificationTime | **恒 0** | 从不写 | 源码注释（:86-88）明言 D: 格式解析留待以后 |
| isEncrypted | doc->is_encrypted() | 打开成功 | 与 is_locked 语义差：加密但可读时 true/false 并存 |


## 5. 解析机制走读

**链路一：逐页文本提取（`extractText`，`PDFAnalyzer.cpp:16-56`）。**

```cpp
// PDFAnalyzer.cpp:22-49（节选）
        std::unique_ptr<poppler::document> doc(poppler::document::load_from_file(pdfPath));
        if (!doc) {
            std::cerr << "Failed to load PDF document: " << pdfPath << std::endl;
            return "";
        }

        if (doc->is_locked()) {
            std::cerr << "PDF document is locked: " << pdfPath << std::endl;
            return "[Encrypted PDF - Content Locked]";
        }

        std::stringstream ss;
        int pages = doc->pages();

        for (int i = 0; i < pages; ++i) {
            std::unique_ptr<poppler::page> p(doc->create_page(i));
            if (p) {
                poppler::ustring ustr = p->text();
                // to_utf8() returns std::vector<char>, convert to std::string
                auto bytes = ustr.to_utf8();
                std::string pageText(bytes.begin(), bytes.end());

                if (!pageText.empty()) {
                    ss << "--- Page " << (i + 1) << " ---\n";
                    ss << cleanText(pageText) << "\n\n";
                }
            }
        }
```

做什么：`load_from_file` 打开文档（失败或异常返回空串并打日志），先查 `is_locked()`——有口令的加密 PDF 在这里就被挡下并返回占位串。然后循环 `create_page(i)`，每页 `text()` 拿到 poppler 的 `ustring`，`to_utf8()` 转字节再拼成 `std::string`，经 `cleanText` 规整后追加。三个边界值得注意：单页创建失败（损坏页）只是跳过该页不中断；空页不写分隔行（避免连续的空 Page 标头污染输出）；UTF-8 直通意味着中日韩文本只要字体嵌入正确就能正常抽出。页分隔标记让 LLM 可以引用"第 N 页说了什么"——对审阅者对回原件很有用。

**链路二：空白规整（`cleanText`，第 102-159 行）。**

```cpp
// PDFAnalyzer.cpp:108-149（节选）
    // Track newlines to preserve paragraphs
    int newlineCount = 0;
    bool lastWasSpace = false;

    for (char c : text) {
        if (c == '\n') {
            newlineCount++;
            lastWasSpace = false;
        } else if (std::isspace(static_cast<unsigned char>(c))) {
            // Horizontal whitespace
            if (!lastWasSpace && newlineCount == 0) {
                cleaned += ' ';
                lastWasSpace = true;
            }
        } else if (std::isprint(static_cast<unsigned char>(c)) || (static_cast<unsigned char>(c) & 0x80)) {
            // Content character

            // Handle pending newlines before adding content
            if (newlineCount > 0) {
                if (newlineCount >= 2) {
                    // Paragraph break (2+ newlines) -> 2 newlines
                    // But ensure we don't have trailing spaces before it
                    size_t lastNonSpace = cleaned.find_last_not_of(' ');
                    if (lastNonSpace != std::string::npos) {
                        cleaned.erase(lastNonSpace + 1);
                    }
                    cleaned += "\n\n";
                } else {
                    // Single newline -> 1 newline
                    // ...
                    cleaned += '\n';
                }
                newlineCount = 0;
                lastWasSpace = false;
            }
            cleaned += c;
            lastWasSpace = false;
        }
    }
```

单趟扫描维护两个状态：连续换行计数 `newlineCount`、上一字符是否空格 `lastWasSpace`。规则读起来是三句话：水平空白只在"非段落开头且前一字符非空格"时折叠成一个空格；换行不立即输出而是**挂起**，直到遇到内容字符才兑现——2 个以上换行视为段落断（输出 `\n\n`），单个换行保留单个 `\n`，且兑现前把尾部空格擦掉；高位字节（`c & 0x80`）无条件当内容字符放行，这是 UTF-8 多字节序列能存活的原因。最后整体 trim。效果是把 Poppler 按布局吐出来的碎文本整理成接近 Markdown 段落结构的可读文本，这对 LLM 的摘要质量有直接帮助。

**链路三：LLM 报告生成（`createLLMReport`，第 161-228 行）。** 汇总前两条链路：先 `extractMetadata`，写报告头与元数据表格（文件名、生成时间、Title/Author/Subject/Keywords/Pages/Encrypted 的 Markdown 表），然后**重新打开文档**逐页写 `### Page N` 加 `cleanText` 后的正文（锁定文档写占位说明 `*Content could not be extracted...*`）。输出是自包含的 Markdown 文件，可直接作为 LLM 的输入文档或人工审阅材料。该方法封装完整但目前无调用方，属"即用型预留能力"。注意它把文档打开两次（一次取元数据、一次取正文，第 167 与 196 行）——全静态设计的代价，大文件场景有优化空间。

### 5.1 代码走读：extractMetadata 的容错与 UTF-8 转换（PDFAnalyzer.cpp:58-97）

```cpp
    try {
        std::unique_ptr<poppler::document> doc(poppler::document::load_from_file(pdfPath));
        if (!doc) return meta;

        meta.isEncrypted = doc->is_encrypted();
        meta.pageCount = doc->pages();

        auto to_string = [](const std::vector<char>& bytes) -> std::string {
            if (bytes.empty()) return "";
            return std::string(bytes.begin(), bytes.end());
        };

        meta.title = to_string(doc->info_key("Title").to_utf8());
        // ... Author/Subject/Keywords/Creator/Producer 同构六连
        if (doc->is_locked()) {
            meta.permissions.push_back("Read Locked");
        }
    } catch (const std::exception& e) {
        std::cerr << "Error extracting metadata from PDF " << pdfPath << ": " << e.what() << std::endl;
    }
    return meta;
```

逐块解释：三个层次的容错——空路径早退（全默认结构体）、load 失败返回（同）、异常 catch 后仍返回**已填充部分**（页数/加密标志可能已写）——调用方拿到"部分成功"的结构体而非报错，与 extractText 的空串/占位串语义可对照。六键读取用同一个 `to_string` lambda 抹平 Poppler 的 `vector<char>` 返回（ustring→utf8 的两步转换收口在一处）；键不存在时 info_key 返回空 ustring、to_string 归一空串——六字段无 null/空之分。is_encrypted 在 is_locked 检查**之前**读——意味着加锁文档的元数据六键与页数照样尽力读（多数加密 PDF 的 Info 字典本身不加密），这是"能拿多少拿多少"的取证姿势。整个函数一次开文档，与 createLLMReport 的双开形成对照。


## 6. 与 LLM 的协作

间接协作：`extractText` 的产出经 `FileAnalyzer` 进入 LLM prompt（与 OfficeAnalyzer 同一条降级链）。`createLLMReport` 的设计意图是给 LLM 提供更结构化的输入（元数据+分页正文），但尚未接线。

## 7. 与其他模块的协作 / 注意事项

- **依赖**：poppler-cpp（`poppler-document.h`/`poppler-page.h`，需系统安装 poppler 及其 C++ 绑定）。无其他依赖。
- **加密 PDF**：只识别"锁定"，不做解密（没有密码参数）。遇到加密文档时 extractText 返回占位串、报告里写明原因——诚实地报告能力边界而不是假装成功。注意 `extractMetadata` 用的判定是 `is_encrypted()` 而 `extractText` 用 `is_locked()`，前者在"加密但已可解密打开"时也为真，两者语义有细微差别。
- **全静态设计**：没有实例状态，天然线程安全、无初始化顺序问题；代价是无法缓存文档句柄（见链路三的双开问题）。
- **与 MarkitdownProxy 的关系**：同 OfficeAnalyzer——markitdown 是首选（Python 生态还能处理 OCR 等），本模块是 C++ 侧兜底，保证 Python 服务不在时 PDF 证据仍可进入 LLM 分析。
- 时间戳未实现（见第 4 节），需要时应解析 CreationDate/ModDate 两个键的 `D:` 格式字符串。

## 8. 如何验证与扩展

- 测试：`tests/UnitTest/test_pdf_analyzer.cpp` 覆盖 extractMetadata/extractText/createLLMReport 及不存在文件的处理；测试用 PDF 缺失时会 GTEST_SKIP（仓库不携带大二进制测试资产），本地验证可在测试期望的路径放一个已知内容的 PDF。
- 手工验证：任选一个 PDF，`extractText` 看分页与段落规整效果，`extractMetadata` 看信息字典（可用 `pdfinfo` 命令交叉核对）。
- 扩展方向：补 `D:` 时间戳解析（十几行正则的事）；`createLLMReport` 接入流水线（如在 FileClassifier 或报告生成阶段调用）；如需注释/附件，Poppler API 有对应能力（`poppler::annotation` 等），在此模块加方法即可。

## 9. 方法全清单（PDFAnalyzer.h:10-54，全静态）

| 方法 | 定义位置 | 语义 | 调用方 |
|---|---|---|---|
| `extractText(pdfPath)` | cpp:16-56 | 逐页文本+页分隔+cleanText | FileAnalyzer.cpp:166-170、测试 |
| `extractMetadata(pdfPath)` | cpp:58-97 | 六键信息字典+页数+加密/锁定 | createLLMReport、测试 |
| `createLLMReport(pdfPath, outputPath)` | cpp:161-228 | Markdown 报告（元数据表+分页正文） | **无生产调用方**（即用型预留） |
| 私有 `cleanText(text)` | cpp:102-159 | 空白规整（段落保留） | extractText/createLLMReport |

无实例方法、无成员变量——并发调用安全，无需单例。

## 10. 关联矩阵

| 对端 | 方向 | 交互点 | 数据形态 |
|---|---|---|---|
| FileAnalyzer.cpp:166-170 | 上游 | markitdown 失败后 .pdf 降级 | string |
| Poppler-cpp | 下游 | document/page API | C++ 库 |
| MarkitdownProxy | 平行首选 | Python 侧转换 | — |
| OfficeAnalyzer | 平行同类 | 同一条降级链的 .docx/.doc 分支 | — |
| test_pdf_analyzer | 消费者 | 三方法+缺文件路径 | GTEST_SKIP 兜底 |
| 无数据库/无 AuditLog/无配置 | — | 纯函数工具 | — |

## 11. 配置影响表

无任何 env/CLI/ConfigManager 键。唯一环境依赖：系统安装 poppler 与 poppler-cpp（编译期链接，运行期无 PATH 探测——与 antiword 的动态探测不同）。

## 12. 性能与并发细节

- **成本线性于页数**：每页一次 create_page+text+UTF-8 转换；Poppler 的 text() 对复杂字体（多字节 CJK、扫描件的隐形 OCR 层）更贵。百页文档毫秒到秒级。
- **内存**：整文档文本一次性成串（stringstream 累积）——千页大书的全文本可能几十 MB；cleanText 再复制一份（峰值翻倍）。无页级流式接口。
- **无锁并发**：全静态无状态，多线程并行分析多个 PDF 安全；Poppler 库本身线程安全（文档级隔离）。
- **createLLMReport 的双开成本**：文档解析两遍（元数据+正文），大文件可先 extractText 一次复用——接线时的顺手优化。
- **可调参数影响**：无参数可调；页分隔标记格式（`--- Page N ---`）是输出契约的一部分，改动会影响下游引用习惯。

**最后更新**: 2026-08-24（二轮深化：补全表列说明与方法清单）
