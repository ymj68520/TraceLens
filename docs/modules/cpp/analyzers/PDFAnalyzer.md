# PDFAnalyzer（src/analyzers/PDFAnalyzer/）

> **一句话**：基于 Poppler-cpp 的 PDF 内容与元数据提取器——逐页抽文本、读文档信息字典（作者/标题/创建工具等）、生成供 LLM 用的 Markdown 报告。与 OfficeAnalyzer 同类：无状态的文件级工具，不建库不落表。

## 1. 为什么有这个模块

PDF 在取证证据里的地位很特殊：它是"最终态"文档——合同签署版、正式报告、外发的材料——内容可信度高，且自带一套元数据（Author、Producer、CreationDate）经常泄露文档的真实来源和制作工具（"Producer: Microsoft Word"还是"Producer: 某些改稿工具"本身就是线索）。同时 PDF 的内部结构是对象流加压缩滤镜，手工解析不现实，需要一个成熟解析库。Poppler 是 Linux 世界事实标准的 PDF 渲染/解析引擎（xdft 系工具的底层），其 C++ 绑定（poppler-cpp）提供稳定的文本与元数据 API——这个模块就是 Poppler 的一层薄封装，把"打开文档、逐页取字、读信息字典"这三件事包装成三个静态方法。

第二个存在理由与 OfficeAnalyzer 相同：**给 LLM 喂干净文本**。PDF 抽出的原始文本充满多余空白和断行，直接进 prompt 会浪费 token 且干扰理解，所以这里专门实现了 `cleanText` 做空白规整（多个空格合一、按换行数量保留段落结构），这是"为下游消费者优化输出"的典型细节。

## 2. 在流水线中的位置

生产调用方是 LLM 集成层的 `FileAnalyzer`（`src/integration/LLMIntegration/FileAnalyzer.cpp:166-170`）：LLM 分析文件内容时，若 markitdown（Python 服务）不可用或失败，`.pdf` 文件降级到 `PDFAnalyzer::extractText(filePath)`。即它是 PDF 在"LLM 文件分析"链路上的本地兜底。

三个公开静态方法（`PDFAnalyzer.h:24-41`）：`extractText`（纯文本，带页分隔）、`extractMetadata`（`PDFMetadata` 结构：title/author/subject/keywords/creator/producer/pageCount/permissions/creationTime/modificationTime/isEncrypted）、`createLLMReport`（生成 Markdown 报告文件）。其中 `createLLMReport` 当前**没有生产调用方**（仅测试使用），是为"把 PDF 分析结果固化为报告"预留的能力。

没有数据库输出、无实例状态（全静态方法），是最小耦合的工具模块。

## 3. 证据来源与覆盖范围

- **正文文本**：逐页 `poppler::page::text()`，每页前插入 `--- Page N ---` 分隔行（`PDFAnalyzer.cpp:45`），页与页之间空行分隔。加密锁定文档返回占位串 `[Encrypted PDF - Content Locked]` 而不是空串（第 28-31 行）——调用方能区分"没内容"和"读不了"。
- **元数据**：信息字典六键（Title/Author/Subject/Keywords/Creator/Producer，第 80-85 行）+ 页数 + 加密标志 + 权限（锁定时记 "Read Locked"）。
- **明确不覆盖的**：PDF 里的嵌入图片（OCR 不做）、附件文件、注释/批注、JavaScript；时间戳字段当前恒为 0——源码注释直言 PDF 的 `D:YYYYMMDDHHmmSS` 格式解析"留待以后"（第 87-89 行）。做时间线时别指望这里的 creationTime。

## 4. 解析机制走读

**链路一：逐页文本提取（`extractText`，`PDFAnalyzer.cpp:16-56`）。** `poppler::document::load_from_file` 打开文档（失败或异常返回空串并打日志），先查 `is_locked()`——有口令的加密 PDF 在这里就被挡下并返回占位串。然后循环 `create_page(i)`，每页 `text()` 拿到 poppler 的 `ustring`，`to_utf8()` 转字节再拼成 `std::string`，经 `cleanText` 规整后追加。UTF-8 直通意味着中日韩文本只要字体嵌入正确就能正常抽出。

**链路二：空白规整（`cleanText`，第 102-159 行）。** 单趟扫描维护两个状态（连续换行计数、上一字符是否空格）：水平空白只在"非段落开头且前一字符非空格"时折叠成一个空格；遇到内容字符时先兑现挂起的换行——2 个以上换行视为段落断（输出 `\n\n`），单个换行保留为单个 `\n`，且兑现前把尾部空格擦掉。最后整体 trim。效果是把 Poppler 按布局吐出来的碎文本整理成接近 Markdown 段落结构的可读文本，这对 LLM 的摘要质量有直接帮助。

**链路三：LLM 报告生成（`createLLMReport`，第 161-228 行）。** 汇总前两条链路：先写报告头与元数据表格（文件名、生成时间、六个信息字典字段、页数、加密状态），再逐页写 `### Page N` 加正文（锁定文档写占位说明）。输出是自包含的 Markdown 文件，可直接作为 LLM 的输入文档或人工审阅材料。该方法封装完整但目前无调用方，属"即用型预留能力"。

## 5. 与 LLM 的协作

间接协作：`extractText` 的产出经 `FileAnalyzer` 进入 LLM prompt（与 OfficeAnalyzer 同一条降级链）。`createLLMReport` 的设计意图是给 LLM 提供更结构化的输入（元数据+分页正文），但尚未接线。

## 6. 与其他模块的协作 / 注意事项

- **依赖**：poppler-cpp（`poppler-document.h`/`poppler-page.h`，需系统安装 poppler 及其 C++ 绑定）。无其他依赖。
- **加密 PDF**：只识别"锁定"，不做解密（没有密码参数）。遇到加密文档时 extractText 返回占位串、报告里写明原因——诚实地报告能力边界而不是假装成功。
- **全静态设计**：没有实例状态，天然线程安全、无初始化顺序问题；代价是无法缓存文档句柄，`createLLMReport` 内部会把文档打开两次（一次取元数据、一次取正文，第 167 与 196 行），大文件场景有优化空间。
- **与 MarkitdownProxy 的关系**：同 OfficeAnalyzer——markitdown 是首选（Python 生态还能处理 OCR 等），本模块是 C++ 侧兜底，保证 Python 服务不在时 PDF 证据仍可进入 LLM 分析。
- 时间戳未实现（见第 3 节），需要时应解析 CreationDate/ModDate 两个键的 `D:` 格式字符串。

## 7. 如何验证与扩展

- 测试：`tests/UnitTest/test_pdf_analyzer.cpp` 覆盖 extractMetadata/extractText/createLLMReport 及不存在文件的处理；测试用 PDF 缺失时会 GTEST_SKIP（仓库不携带大二进制测试资产），本地验证可在测试期望的路径放一个已知内容的 PDF。
- 手工验证：任选一个 PDF，`extractText` 看分页与段落规整效果，`extractMetadata` 看信息字典（可用 `pdfinfo` 命令交叉核对）。
- 扩展方向：补 `D:` 时间戳解析（十几行正则的事）；`createLLMReport` 接入流水线（如在 FileClassifier 或报告生成阶段调用）；如需注释/附件，Poppler API 有对应能力（`poppler::annotation` 等），在此模块加方法即可。

**最后更新**: 2026-08-23（解释式重写）
