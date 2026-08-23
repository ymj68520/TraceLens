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

### 3.1 三级取内容策略与 markitdown 白名单

`analyzeFile()` 的第一步是决定"怎么读"。首选 MarkitdownProxy（C++ 经 HTTP 调 Python 服务的 `/api/markitdown/convert`，把 PDF/Office/图片/音频转成 Markdown 文本），但 markitdown 只认文档类格式——把磁盘镜像、PE/ELF 二进制、注册表 hive、evtx 喂给它，Python 端会抛 UnsupportedFormatException 并以 HTTP 500 刷爆后端日志（源码注释在 `FileAnalyzer.cpp:35-53` 记录了这段事故）。因此引入了扩展名白名单：

```cpp
// FileAnalyzer.cpp:59-71（节选）
static const std::set<std::string> supported = {
    ".pdf", ".docx", ".doc", ".xlsx", ".pptx",      // Office 文档
    ".html", ".jpg", ".png", ".mp3", ".wav",         // 网页/图片/音频
    ".txt", ".md", ".csv", ".json", ".xml", ".log"   // 纯文本与数据格式
};
```

只有扩展名命中白名单才尝试 markitdown；其余（.img/.exe/.evtx/.hiv/...）直接走本地回退链（`FileAnalyzer.cpp:166-182`）：`.pdf` 用 PDFAnalyzer、`.doc(x)` 用 OfficeAnalyzer、判定为 Archive/Binary/Database 的放占位文本只做元数据分析、其余原始字节读入。markitdown 失败（返回空或 `"Error:"` 前缀，这是 MarkitdownProxy 的错误约定）也落入同一回退链。**先白名单、再降级**是这条管线最重要的设计决策。

### 3.2 上下文窗口预算与"聪明截断"

三个上限取最小值作为生效长度（`FileAnalyzer.cpp:198-200`）：调用方传入的 `maxContentLength`、按模型窗口算出的 `calculateMaxContentLength()`、配置项 `getLLMMaxContentLength()`。预算公式（`FileAnalyzer.cpp:433-451`）：

```
可用 token = contextLength − reservedTokens − maxTokens   （下限 100）
最大字符   = 可用 token × charsPerToken                    （默认 4.0，中文约 1.5）
```

超长内容的截断不是简单砍尾，而是"头 70% + 截断标记 + 尾 30%"（`FileTextProcessor.cpp:41-80`）——保留结尾是因为日志、配置类证据的关键信息（报错、结论）常在文件末尾。切点由 `findSmartBoundary()`（`FileTextProcessor.cpp:82-138`）按优先级回退寻找：段落断点 > 句号/叹号/问号 > 换行 > 空格 > 硬切。

### 3.3 结构化输出协议与容错解析

prompt 要求模型**逐字**按 `SUMMARY: ... DESCRIPTION: ... KEYWORDS: ...` 格式回答（`FileAnalyzer.cpp:209-223`），解析侧用三个预编译的静态正则提取（`FileAnalyzer.cpp:28-33`，预编译避免每文件重复构造的开销）。容错：正则全部落空时，把整段回复同时当 summary 和 description 存（`FileAnalyzer.cpp:263-266`）——宁可存原始文本，不存空串。这个"格式约定 + 宽松解析"的组合代价是：模型不守格式时字段语义会退化，但没有数据丢失。

### 3.4 周边静态工具

- **FileContentExtractor**（`FileContentExtractor.cpp`）：`detectFileType()` 先查约 150 项扩展名→类型映射（`:49-200`），查不到再嗅探前 512 字节有无 `\0` 判二进制（`:202-220`）；`readFileContent()` 带上限的原始读取。类型字符串（"PDF"、"Archive"...）会进 prompt，帮助模型定向。
- **FileTextProcessor**（`FileTextProcessor.cpp`）：无状态纯函数集——逗号分隔关键词解析（含 `- `/`*` 前缀清理，`:9-32`）、token 估算、截断、分块（`splitIntoChunks`，块间 200 字符重叠保上下文连续，`:140-175`）、宽松版 UTF-8 清洗（`:177-217`）。
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

超大文件路径（`analyzeFileChunked`，`:465-554`）：把内容切成重叠块，逐块分析，最后 `mergeChunkResults()`（`:556-616`）——摘要拼接后再让 LLM 做一次"合并成连贯摘要"（`:573-583`），关键词做集合去重（`:587-593`）。

## 5. 与其他模块的协作

| 协作方 | 关系 |
|---|---|
| network/LLMAnalysisService 及三个平台版 | 上层编排者：注入 router、把镜像内文件解到 LLMScratch 临时目录后调 `analyzeFile` |
| llm_scratch（LLMScratch.h/.cpp） | 每任务独立临时目录 `<tempdir>/forensics_llm_extract/<task_id>/`，隔离并发任务的拍平文件名，服务析构时清理 |
| ModelRouter/LLMClient | 所有模型调用出口；`router_->getConfig()` 提供上下文预算参数 |
| MarkitdownProxy + Python 服务 | 文档类格式的首选文本化通道（HTTP 到 `/api/markitdown/*`） |
| PDFAnalyzer / OfficeAnalyzer | markitdown 不可用时的本地回退（integration 层反向依赖 analyzers 层，属已知的层次交叉） |
| ThreadPool（core） | 批量分析的并发执行器 |
| ConfigManager | 线程池大小、`LLM_MAX_CONTENT_LENGTH` 等运行参数 |

## 6. 注意事项与已知问题

- **批量并行的收益有限**：线程池并行的是"取内容/清洗"阶段；所有线程最终过同一个 router 的同一个 LLMClient，而 LLMClient 的重试循环持锁，HTTP 请求实际串行。想要真并发要么注册多模型，要么给 LLMClient 做实例池。
- **`analyzeFileChunked` 与 `enableChunkedAnalysis` 没有联动**：`LLMConfig.enableChunkedAnalysis`（`LLMDataTypes.h:28`）看起来像开关，但 `analyzeFile()` 并不会据此自动转分块——分块路径必须显式调 `analyzeFileChunked`，而当前无人调用。配置项是"预订的接口"。
- **白名单是静态副本**：`markitdownSupportedExtensions()` 注释说明它镜像 Python 侧 `extractor_mapping.json`，但两边靠人工同步；Python 侧新增格式不会自动生效。
- **"Error:" 前缀协议脆弱**：用 `content.find("Error:") != 0` 判断 markitdown 失败（`FileAnalyzer.cpp:154`），若文件转换结果本身以 "Error:" 开头会被误判为失败（实际只是走了回退，损失的是 markitdown 质量，不致命）。
- **多文件描述只看前 5 个**：`generateDescription(vector)` 用前 5 个文件的元数据当上下文（`FileAnalyzer.cpp:363-364`），其余只计数；大文件集的描述偏前部样本。
- **UTF-8 清洗有两套实现**：本模块用 FileTextProcessor 的宽松版，LLMClient 内部还有严格版（见 LLMClient.md 第 6 节），规则不一致但方向一致（都是替换为 `?`）。

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

**最后更新**: 2026-08-23（解释式重写）
