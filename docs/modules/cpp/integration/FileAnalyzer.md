# FileAnalyzer（src/integration/LLMIntegration/FileAnalyzer.{h,cpp}）

> **一句话**："文件到 LLM"的完整流水线——把一个宿主文件变成模型可消化的文本（markitdown/本地解析器/原始读取三级取内容）、按上下文窗口预算截断、用结构化 prompt 让模型输出 SUMMARY/DESCRIPTION/KEYWORDS、再用正则把结果拆回结构体。

## 1. 为什么有这个模块

取证分析动辄面对成千上万个文件，人工逐一阅读不现实。这个模块回答三个问题：**文件内容怎么读出来**（PDF/Office/二进制/纯文本各不相同）、**读出来怎么塞进有限的上下文窗口**（截断策略与预算计算）、**模型输出怎么变成可入库的结构化字段**（summary/description/keywords）。

它刻意做成一个不关心"文件从哪来"的进程内库：输入永远是一个**宿主文件系统路径**。至于"从磁盘镜像里把这个文件解出来"这件事，属于上层 network/LLMAnalysisService 的职责（见第 2 节）——分层让同一套分析管线既能服务镜像内文件，也能服务散落文件。

## 2. 在系统中的位置

```
HTTP 客户端 ──► network/HTTPServer/LLMAnalysisService（及平台版 Linux/Windows/AndroidLLMAnalysisService）
                  │  职责：路径解析（镜像内→宿主临时文件）、任务调度、结果入库
                  │  resolveFileForAnalysis(): LLMAnalysisService.cpp:53-118
                  ▼
              FileAnalyzer（integration 层，进程内库）
                  │  职责：取内容 → 清洗 → 截断 → prompt → 解析
                  ├──► MarkitdownProxy（同目录，单例）──HTTP──► Python 服务 /api/markitdown/*
                  ├──► FileContentExtractor / FileTextProcessor（同目录，纯静态工具）
                  ├──► analyzers/PDFAnalyzer、OfficeAnalyzer（.pdf/.docx 的本地回退）
                  └──► ModelRouter ──► LLMClient ──► LLM 端点
```

分层口诀：**LLMAnalysisService 管"哪个文件、结果去哪"，FileAnalyzer 管"这个文件说了什么"**。生产代码里对 FileAnalyzer 的实际调用只有 `analyzeFile(localPath, options.maxContentLength)`（`LLMAnalysisService.cpp:163, 217`）和 DLLAnalyzerLLMService 的两个 `set*Prompt` 定制（`DLLAnalyzerLLMService.cpp:96-97`）；`summarize`/`extractKeywords`/`analyzeBatch`/`analyzeFileChunked` 目前没有生产调用方，是为批量与超大文件预留的能力。

与镜像的衔接值得一提：LLMAnalysisService 把镜像内路径经 FileExtractor 解到任务级临时目录（`llm_scratch::dirForTask(taskId)` = `<tempdir>/forensics_llm_extract/<task_id>/`，实现见 `src/network/HTTPServer/LLMScratch.cpp:11-13`；服务析构时 `cleanupTask` 清理，`LLMAnalysisService.cpp:16-20`），FileAnalyzer 拿到的已是普通文件。**刻意不走宿主机直读**——否则分析 `/etc/passwd` 时读到的是分析员自己机器的文件。

## 3. 核心概念与设计

### 3.1 输入输出结构：AnalysisResult 与 ChunkConfig

输出的核心契约是 `AnalysisResult`（`LLMDataTypes.h:150-164`）：

```cpp
// LLMDataTypes.h:150-164
struct AnalysisResult {
    std::string filePath;
    std::string summary;
    std::string description;
    std::vector<std::string> keywords;
    std::string fileType;
    int64_t fileSize = 0;
    bool success = false;
    std::string errorMessage;

    // Analysis metadata
    std::string modelUsed;      // router_->getLastUsedModel() 的值
    int tokensUsed = 0;         // promptTokens + completionTokens
    double analysisTimeMs = 0;  // high_resolution_clock 差值
};
```

三个 metadata 字段是服务层入库的记账依据：`modelUsed` 标识这次实际命中的模型（Fallback 场景下可能与"首选"不同），`tokensUsed` 供用量统计，`analysisTimeMs` 供慢文件排查。批量请求结构 `BatchAnalysisRequest`（`LLMDataTypes.h:169-175`）则带 `filePaths`、三个生成交错开关和 `maxContentLength = 10000`（每文件送 LLM 的默认字符上限）。分块参数集中在 `ChunkConfig`（`LLMDataTypes.h:35-40`）：`chunkSize = 2000` 字符、`overlapSize = 200`、`maxChunks = 5`、`smartBoundary = true`。

### 3.2 公开接口清单（FileAnalyzer.h:42-138）

| 方法（真实签名节选） | 语义 | 调用方 | 失败行为 |
|---|---|---|---|
| `AnalysisResult analyzeFile(const std::string& filePath, size_t maxContentLength = 10000)` | 单文件全管线 | LLMAnalysisService（唯一生产调用） | 文件不存在/读不到内容/router 缺失/LLM 失败 → `success=false` + errorMessage |
| `std::vector<AnalysisResult> analyzeBatch(const BatchAnalysisRequest&)` | 线程池批量 | 无生产调用方 | 逐文件失败不拖垮整批 |
| `std::string summarize(content, context = "")` | 纯文本摘要（用 summaryPrompt_） | 无生产调用方 | 返回 `"Error: ..."` 字符串 |
| `std::string generateDescription(filePath)` / `generateDescription(vector<filePath>)` | 单/多文件描述 | 无生产调用方 | 同上；多文件版只看前 5 个（`:363-364`） |
| `std::vector<std::string> extractKeywords(content, maxKeywords = 10)` | 关键词抽取 | 无生产调用方 | 失败返回空向量 |
| `void setSummaryPrompt/` `setDescriptionPrompt/` `setKeywordPrompt(prompt)` | 替换默认 prompt | DLLAnalyzerLLMService（`:96-97`） | — |
| `void setProgressCallback(ProgressCallback)` / `setChunkConfig(ChunkConfig)` | 批量进度回调 / 分块参数 | 无生产调用方 | — |
| `static size_t estimateTokens(content, charsPerToken = 4.0)` | token 估算 | 内部 | — |
| `size_t calculateMaxContentLength() const` | 按模型窗口算字符预算 | analyzeFile 内部 | 无 router 时回落 10000 |
| `std::string truncateContent(content, maxLength) const` | 聪明截断（转调 FileTextProcessor） | 内部 | — |
| `AnalysisResult analyzeFileChunked(filePath)` | 分块分析 + 合并 | 无生产调用方 | 见 4.3 |

### 3.3 三级取内容策略与 markitdown 白名单

`analyzeFile()` 的第一步是决定"怎么读"。首选 MarkitdownProxy（C++ 经 HTTP 调 Python 服务的 `/api/markitdown/convert`，把 PDF/Office/图片/音频转成 Markdown 文本），但 markitdown 只认文档类格式——把磁盘镜像、PE/ELF 二进制、注册表 hive、evtx 喂给它，Python 端会抛 UnsupportedFormatException 并以 HTTP 500 刷爆后端日志（源码注释在 `FileAnalyzer.cpp:35-53` 记录了这段事故）。因此引入了扩展名白名单：

```cpp
// FileAnalyzer.cpp:59-71（节选）
static const std::set<std::string> supported = {
    // Office documents
    ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt",
    // Web / structured text
    ".html", ".htm", ".ipynb", ".rss",
    // Images (EXIF + OCR)
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif",
    // Audio (transcription)
    ".mp3", ".wav",
    // Plain text / data formats markitdown reads directly
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".xml",
    ".yaml", ".yml", ".rst", ".log"
};
```

只有扩展名命中白名单才尝试 markitdown；其余（.img/.exe/.evtx/.hiv/...）直接走本地回退链（`FileAnalyzer.cpp:166-182`）：`.pdf` 用 PDFAnalyzer、`.doc(x)` 用 OfficeAnalyzer、判定为 Archive/Binary/Database 的放占位文本只做元数据分析、其余原始字节读入。markitdown 失败（返回空或 `"Error:"` 前缀，这是 MarkitdownProxy 的错误约定）也落入同一回退链。**先白名单、再降级**是这条管线最重要的设计决策。门控与降级的真实代码（`FileAnalyzer.cpp:148-163`）：

```cpp
bool useMarkitdown = isMarkitdownSupportedExt(ext);

if (useMarkitdown) {
    auto& markitdown = MarkitdownProxy::instance();
    if (markitdown.isServiceAvailable()) {
        content = markitdown.convertToMarkdown(filePath);
        if (!content.empty() && content.find("Error:") != 0) {
            LOG_DEBUG("Successfully converted via markitdown: " + filePath);
        } else {
            LOG_WARNING("markitdown failed for " + filePath + ", falling back to local parsers");
            content.clear();          // 置空 → 落入下方本地回退链
        }
    }
} else {
    LOG_DEBUG("Skipping markitdown for unsupported extension " + ext + " (" + filePath + ")");
}
```

### 3.4 上下文窗口预算与"聪明截断"

三个上限取最小值作为生效长度（`FileAnalyzer.cpp:198-200`）：

```cpp
// FileAnalyzer.cpp:197-206（Issue 7）
size_t calculatedMaxLength = calculateMaxContentLength();
size_t configLimit = static_cast<size_t>(ConfigManager::instance().getLLMMaxContentLength());
size_t effectiveMaxLength = std::min({maxContentLength, calculatedMaxLength, configLimit});

if (content.size() > effectiveMaxLength) {
    LOG_DEBUG("Content exceeds limit (" + std::to_string(content.size()) +
              " > " + std::to_string(effectiveMaxLength) + "), applying smart truncation");
    content = FileTextProcessor::truncateContent(content, effectiveMaxLength);
}
```

三个来源各管一层：调用方传参（任务级）、模型窗口推算（模型级）、`LLM_MAX_CONTENT_LENGTH` env（全局运维级，默认 10000）。`calculateMaxContentLength()` 的预算公式（`FileAnalyzer.cpp:433-451`）：

```cpp
// FileAnalyzer.cpp:433-451（节选）
const auto& config = router_->getConfig();   // 首选模型的 LLMConfig（无模型时是静态默认）

// Available tokens = context length - reserved tokens - max output tokens
int availableTokens = config.contextLength - config.reservedTokens - config.maxTokens;
if (availableTokens < 100) {
    availableTokens = 100; // Minimum
}

// Convert to characters
size_t maxChars = static_cast<size_t>(availableTokens * config.charsPerToken);
```

即：`可用 token = contextLength − reservedTokens − maxTokens`（下限 100），`最大字符 = 可用 token × charsPerToken`（默认 4.0，中文约 1.5）。默认配置（4096−512−2048=1536 token × 4.0）算出 6144 字符——比 env 默认 10000 还小，说明**默认情况下模型窗口才是最紧的约束**。

超长内容的截断不是简单砍尾，而是"头 70% + 截断标记 + 尾 30%"（`FileTextProcessor.cpp:41-80`）：

```cpp
// FileTextProcessor.cpp:50-77（节选）
const std::string indicator = "\n\n[... Content truncated due to context window limit ...]\n\n";
size_t effectiveMax = maxLength - indicator.size();   // 给标记留位

// Split: 70% from beginning, 30% from end
size_t headSize = static_cast<size_t>(effectiveMax * 0.7);
size_t tailSize = effectiveMax - headSize;

// Find smart boundaries
size_t headEnd = findSmartBoundary(content, headSize);   // 头部向后找边界
size_t tailStart = content.size() - tailSize;

// Adjust tail start to a smart boundary (look forward)
for (size_t i = tailStart; i < content.size() && i < tailStart + 200; ++i) {
    char c = content[i];
    if (c == '\n' || c == '.' || c == '!' || c == '?') {
        tailStart = i + 1;
        break;
    }
}

std::string result;
result.reserve(maxLength);
result += content.substr(0, headEnd);
result += indicator;
if (tailStart < content.size()) {
    result += content.substr(tailStart);   // 尾段从边界后开始
}
```

保留结尾是因为日志、配置类证据的关键信息（报错、结论）常在文件末尾。头部切点由 `findSmartBoundary()`（`FileTextProcessor.cpp:82-138`）按优先级回退寻找：段落断点（`\n\n`）> 句号/叹号/问号（且后跟空格/换行/串尾）> 换行 > 空格 > 硬切，回看窗口 200 字符；尾部切点则**向前**找 200 字符内的首个边界。两个方向的搜索窗口都只有 200 字符——找不到就接受不完美切点，避免为边界扫描付出 O(n) 代价。

### 3.5 结构化输出协议与容错解析

prompt 要求模型**逐字**按 `SUMMARY: ... DESCRIPTION: ... KEYWORDS: ...` 格式回答（`FileAnalyzer.cpp:209-223`），三个解析正则在文件级静态预编译（`FileAnalyzer.cpp:28-33`）：

```cpp
// FileAnalyzer.cpp:28-33（Issue 9 - pre-compiled for performance）
const std::regex FileAnalyzer::SUMMARY_REGEX(
    "SUMMARY:\\s*(.+?)(?=DESCRIPTION:|$)", std::regex::icase);
const std::regex FileAnalyzer::DESCRIPTION_REGEX(
    "DESCRIPTION:\\s*(.+?)(?=KEYWORDS:|$)", std::regex::icase);
const std::regex FileAnalyzer::KEYWORD_REGEX(
    "KEYWORDS:\\s*(.+)$", std::regex::icase);
```

三段正则用**前瞻断言**（`(?=DESCRIPTION:|$)`）在无分隔符的连续文本里切字段：SUMMARY 段吃到下一个 `DESCRIPTION:` 或串尾为止；`icase` 容忍模型输出小写标签。容错：正则全部落空时，把整段回复同时当 summary 和 description 存（`FileAnalyzer.cpp:263-266`）——宁可存原始文本，不存空串。这个"格式约定 + 宽松解析"的组合代价是：模型不守格式时字段语义会退化，但没有数据丢失。

### 3.6 周边静态工具

- **FileContentExtractor**（`FileContentExtractor.cpp`）：`detectFileType()` 先查约 150 项扩展名→类型映射（`:49-200`），查不到再嗅探前 512 字节有无 `\0` 判二进制（`:202-220`）；`readFileContent()` 带上限的原始读取。类型字符串（"PDF"、"Archive"...）会进 prompt，帮助模型定向。
- **FileTextProcessor**（`FileTextProcessor.cpp`）：无状态纯函数集——逗号分隔关键词解析（含 `- `/`*` 前缀清理，`:9-32`）、token 估算（`content.size() / charsPerToken`，`:34-39`）、截断、分块（`splitIntoChunks`，块间 200 字符重叠保上下文连续，`:140-175`）、宽松版 UTF-8 清洗（`:177-217`）。
- **MarkitdownProxy**（`MarkitdownProxy.h/.cpp`）：单例（`MarkitdownProxy.cpp:20-22`，URL 取自 `ConfigManager::getPythonServiceUrl()`），封装 `/api/markitdown/convert|batch-convert|status`。文件→LLM 之外的另一条"integration 层 HTTP 出口"。

## 4. 工作流程走读

以 LLMAnalysisService 处理一个镜像内 PDF 为例（`analyzeFile()`，`FileAnalyzer.cpp:110-273`）：

1. **前置**：服务层已把 `grub/grub.cfg` 这类镜像相对路径解析成 `forensics_llm_extract/<task_id>/grub_grub.cfg` 宿主路径（`LLMAnalysisService.cpp:53-118`，路径分隔符拍平防穿越）。
2. **元数据**：FileAnalyzer 确认存在、取大小、`detectFileType()` 定类型（`:118-125`）。
3. **取内容**：`.pdf` 命中白名单 → `MarkitdownProxy::instance().isServiceAvailable()` 探活 → `convertToMarkdown()`；若 Python 服务没起或转换失败，回退 `PDFAnalyzer::extractText()`（`:148-169`）。二进制/压缩包类到此为止，直接用占位文本（`:175-177`）。
4. **清洗与预算**：`FileTextProcessor::sanitizeUTF8` 去非法字节（`:190`）；三重最小值算出预算，超限则聪明截断并插入 `[... Content truncated ...]` 标记（`:198-206`）。
5. **调用模型**：拼 combined prompt（含文件路径/类型/大小 + 内容），system prompt 锁定输出格式，`router_->chat()` 发出（`:225`）。
6. **解析入库**：三个正则分别抽 SUMMARY/DESCRIPTION/KEYWORDS，关键词经 `parseKeywords` 拆成数组（`:239-260`）；`modelUsed` 取自 `router_->getLastUsedModel()`，token 用量与耗时写入 `AnalysisResult`（`:233-234, 268-270`）。

批量路径（`analyzeBatch`，`:275-312`）：线程池大小取 `ConfigManager::getThreadPoolSize()`，大于 1 且文件数大于 1 时并发跑 `analyzeFile`，逐个 future 收集并回调进度。

超大文件路径（`analyzeFileChunked`，`:465-554`）：把内容切成重叠块，逐块分析（每块 prompt 自带 `(i+1)/N` 序号，`:506-512`），最后 `mergeChunkResults()`（`:556-616`）——摘要拼接后再让 LLM 做一次"合并成连贯摘要"（`:573-583`，合并失败则直接用拼接原文），关键词做集合去重（`:587-593`），token 与耗时跨块累加（`:604-612`）。

**错误处理矩阵**：

| 故障点 | 行为 |
|---|---|
| 文件不存在 | `errorMessage = "File not found: ..."`，立即返回（`:118-121`） |
| markitdown 服务不可用/转换失败 | 降级本地解析链，不报错（`:150-159`） |
| Archive/Binary/Database | 占位文本继续元数据分析，不算失败（`:175-177`） |
| 内容为空（全部取内容手段失败） | `errorMessage = "Failed to read file content or content is empty"`（`:184-187`） |
| router 未注入 | `errorMessage = "No LLM router configured"`（`:192-195`） |
| LLM 调用失败 | `errorMessage = "LLM analysis failed: ..."`（`:228-231`）——继承 router/LLMClient 的重试与 Fallback |
| 正则全落空 | 整段回复同时当 summary/description，`success` 仍为 true（`:263-266`） |

## 5. 与其他模块的协作

| 协作方 | 关系 |
|---|---|
| network/LLMAnalysisService 及三个平台版 | 上层编排者：注入 router、把镜像内文件解到 LLMScratch 临时目录后调 `analyzeFile` |
| llm_scratch（LLMScratch.h/.cpp） | 每任务独立临时目录 `<tempdir>/forensics_llm_extract/<task_id>/`，隔离并发任务的拍平文件名，服务析构时清理 |
| ModelRouter/LLMClient | 所有模型调用出口；`router_->getConfig()` 提供上下文预算参数 |
| MarkitdownProxy + Python 服务 | 文档类格式的首选文本化通道（HTTP 到 `/api/markitdown/*`） |
| PDFAnalyzer / OfficeAnalyzer | markitdown 不可用时的本地回退（integration 层反向依赖 analyzers 层，属已知的层次交叉） |
| ThreadPool（core） | 批量分析的并发执行器 |
| ConfigManager | 线程池大小、`LLM_MAX_CONTENT_LENGTH`（默认 10000）等运行参数 |

## 6. 注意事项与已知问题

- **批量并行的收益有限**：线程池并行的是"取内容/清洗"阶段；所有线程最终过同一个 router 的同一个 LLMClient，而 LLMClient 的重试循环持锁，HTTP 请求实际串行。想要真并发要么注册多模型，要么给 LLMClient 做实例池。
- **`analyzeFileChunked` 与 `enableChunkedAnalysis` 没有联动**：`LLMConfig.enableChunkedAnalysis`（`LLMDataTypes.h:28`）看起来像开关，但 `analyzeFile()` 并不会据此自动转分块——分块路径必须显式调 `analyzeFileChunked`，而当前无人调用。配置项是"预订的接口"。
- **白名单是静态副本**：`markitdownSupportedExtensions()` 注释说明它镜像 Python 侧 `extractor_mapping.json`，但两边靠人工同步；Python 侧新增格式不会自动生效。
- **"Error:" 前缀协议脆弱**：用 `content.find("Error:") != 0` 判断 markitdown 失败（`FileAnalyzer.cpp:154`），若文件转换结果本身以 "Error:" 开头会被误判为失败（实际只是走了回退，损失的是 markitdown 质量，不致命）。
- **多文件描述只看前 5 个**：`generateDescription(vector)` 用前 5 个文件的元数据当上下文（`FileAnalyzer.cpp:363-364`），其余只计数；大文件集的描述偏前部样本。
- **UTF-8 清洗有两套实现**：本模块用 FileTextProcessor 的宽松版，LLMClient 内部还有严格版（见 LLMClient.md 第 6 节），规则不一致但方向一致（都是替换为 `?`）。
- **预算公式依赖"首选模型"的配置**：`router_->getConfig()` 返回 preferred 模型的 LLMConfig；Fallback 切到备用模型后预算仍按首选算——两模型窗口差异大时会失准。

## 7. 如何验证与扩展

**验证**：
1. 起本地 LLM 端点 + Python markitdown 服务，对一份 .pdf 与一份 .img 各跑一次平台 LLM 分析接口：日志应出现 "Successfully converted via markitdown"（pdf）与 "Skipping markitdown for unsupported extension .img"（`FileAnalyzer.cpp:155, 162` 的两条 DEBUG 日志就是这条管线的观测点）。
2. 停掉 Python 服务再跑 pdf：日志应出现 "markitdown failed ... falling back to local parsers"，结果仍能出来（走 PDFAnalyzer）。
3. 构造一个远超 `LLM_MAX_CONTENT_LENGTH` 的大文本，检查入库摘要对应的请求内容里有 `[... Content truncated due to context window limit ...]` 标记，且切点落在句/行边界。
4. 单元测试可直接测纯函数：`findSmartBoundary` 的四级优先级、`splitIntoChunks` 的重叠与 maxChunks、`parseKeywords` 的前缀清理。

**扩展方向**：
- 新增格式支持：优先改 Python 侧 extractor 映射 + 同步 `markitdownSupportedExtensions()`；纯本地格式则在回退链（`:166-182`）加分支；
- 打通分块：在 `analyzeFile()` 里按 `enableChunkedAnalysis && 内容超预算` 自动转 `analyzeFileChunked`；
- 结构化输出升级：改用 LLM 的 tool-calling/JSON mode 强制格式，可去掉正则解析的容错复杂度（LLMClient 已支持 tools 参数）。

## 8. 三级取内容的完整决策表（二轮补全）

`analyzeFile` 的取内容路径按扩展名/类型穷举（门控 :148-163、回退链 :166-182）：

| 输入 | 第一选择 | 失败回退 | 最终内容形态 |
|---|---|---|---|
| .pdf/.doc(x)/.xls(x)/.ppt(x)/.html/.htm/.ipynb/.rss | markitdown（白名单命中） | PDFAnalyzer/OfficeAnalyzer（本地库） | 提取文本 |
| .jpg/.jpeg/.png/.gif/.bmp/.webp/.tiff/.tif | markitdown（EXIF+OCR） | 无专门回退（原始字节读入） | 占位/元数据文本 |
| .mp3/.wav | markitdown（转写） | 同上 | 同上 |
| .txt/.md/.markdown/.csv/.tsv/.json/.xml/.yaml/.yml/.rst/.log | markitdown | **原始读取**（这些格式本地读无损） | 原文 |
| .pdf 且 markitdown 服务未起 | —（isServiceAvailable=false 跳过） | PDFAnalyzer | 提取文本 |
| Archive/压缩类（detectFileType 判定） | 跳过 markitdown | 占位文本（"binary/archive, metadata only"语义） | 元数据分析 |
| Database/Binary（含 .img/.exe/.evtx/.hiv） | 跳过 | 占位文本 | 同上 |
| 其余文本类 | 跳过 | 原始字节读入 | 原文 |

判定次序：**扩展名白名单 → 服务可用性 → 转换结果前缀**——三层任一不过都落本地链，本地链内部再按 detectFileType 分四支。观测点：`Successfully converted via markitdown` / `markitdown failed ... falling back` / `Skipping markitdown for unsupported extension` 三条日志分别对应三层的结局。

## 9. analyzeBatch 的临时池细节（新走读分支）

批量路径（:275-312）每次调用**现场构造一个 ThreadPool**（:284），批完即析构——与 TaskManager 的常驻池是两个独立实例，互不影响排队。三个此前未展开的细节：

1. **future.get() 的顺序语义**：结果按提交顺序收集（:295-300），不是完成顺序——先提交的慢文件会阻塞后续已 finished 结果的回调触发，进度条呈现"卡在第 N 个"的假象，实际后续文件早已分析完。
2. **progressCallback_ 无锁读**：回调在收集循环里裸读成员（:297），若另一线程并发 setProgressCallback 是数据竞争——当前无人用，休眠风险。
3. **单文件退化**：`poolSize>1 && size>1` 不满足时走串行分支（:301-309）——单文件批量请求不起池，避免为 1 个任务付线程创建成本。THREAD_POOL_SIZE=1 的部署则永远串行。

## 10. 配置影响表（全集，含三重截断的来源）

| 配置 | 默认 | 消费点 | 效果 |
|---|---|---|---|
| `LLM_MAX_CONTENT_LENGTH` | 10000 | :199（configLimit） | 三重最小值之一（全局运维层） |
| `LLM_CONTEXT_LENGTH` | C++ 4096 / .env.example 163840 | calculateMaxContentLength :433-451 | 模型窗口层；**代码缺省远小于示例值**——按默认算出的 6144 字符是最紧约束 |
| `LLM_RESERVED_TOKENS` | 512（LLMConfig 结构体默认） | 同上 | **env 未接线**（Environment.md 已记）：只能靠结构体默认，改 env 不生效 |
| `LLM_CHARS_PER_TOKEN` | 4.0（结构体默认） | 同上 | 同上未接线 |
| 调用方传参 maxContentLength | LLMAnalysisService 传 LLM_MAX_CONTENT_LENGTH 的值 | analyzeFile 形参 | 与 configLimit 同源时实际是两层重复约束 |
| `LLM_TEXT_MAX_TOKENS` | 2048 | 预算公式的 maxTokens 项 | 调大它会**缩小**内容预算（可用 token = ctx − reserved − maxTokens）——反直觉的联动 |
| `THREAD_POOL_SIZE` | 4 | analyzeBatch :280 | 批量并发度（受 LLMClient 锁串行化，§6） |
| `FILE_ANALYSIS_MAX_CONTENT` | 10000 | **Python 侧同位配置** | 不影响本模块；两组变量名近似易混（Environment.md §5） |
| `PYTHON_SERVICE_URL` | http://localhost:8090 | MarkitdownProxy 单例 | markitdown 通道可达性 |

**三重截断的生效次序实验**：默认 env 全缺省时 effectiveMaxLength = min(10000 传入, 6144 窗口推算, 10000 env) = **6144**——即默认最紧的是模型窗口；把 LLM_CONTEXT_LENGTH 提到 163840 后（.env.example 的写法）窗口层变 ~647 616 字符，env 的 10000 反过来成为约束。调优时先想清楚想让哪层说话。

## 11. 关联矩阵（补全版）

| 方向 | 对象 | 交互点 |
|---|---|---|
| 被调 | LLMAnalysisService.cpp:163/217 | analyzeFile（唯一生产入口） |
| 被调（定制） | DLLAnalyzerLLMService.cpp:96-97 | setSummaryPrompt/setDescriptionPrompt |
| 依赖（注入） | shared_ptr<ModelRouter> | chat/getConfig/getLastUsedModel |
| 依赖 | MarkitdownProxy 单例 | 文档格式首选通道 |
| 依赖 | FileContentExtractor/FileTextProcessor | 静态工具 |
| 依赖（反向） | PDFAnalyzer/OfficeAnalyzer | 本地回退（层次交叉，§5） |
| 依赖 | ThreadPool（临时实例） | 批量 |
| 临时目录 | llm_scratch（上游管理） | 输入文件来源 |
| 死位 | summarize/extractKeywords/analyzeBatch/analyzeFileChunked/进度回调/ChunkConfig | 零生产调用方 |

**最后更新**: 2026-08-24（二轮深化：补全方法清单与契约细节）
