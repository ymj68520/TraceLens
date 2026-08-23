# TextDumpExporter（src/export/TextDumpExporter.{h,cpp}、TextDumpAdapters.{h,cpp}）

> **一句话**：文本转储导出器——把镜像里**所有**常规文件经 FileExtractor 原子抽取成原件、再经 Python Markitdown 服务转成 Markdown，可用 `--dump-text-max-size 500M` 这类**软上限**控制"原件 + Markdown"总占用，超限即停但保留已完成的文件。

## 1. 为什么有这个模块

平台分析器只抽取"它们认识的系统文件"；LLM/RAG 生态吃的是纯文本。要给后续智能分析喂全量语料，需要一条"镜像 → 人类可读文本树"的通道。难点是**体积不可控**：全量抽取一个 500GB 镜像可能写满磁盘。本模块的核心贡献就是把"全量转储"做成**可预算的**：给定字节数上限，导出过程实时记账，到限即停（软限制——允许正在写的那个文件越线，已完成的不回收）。历史上它经历过一次拆解重构（`docs/superpowers/plans/2026-07-15-cli-text-dump-size-limit.md` 是当时的计划文档，**不可信，仅作背景**；以当前代码为准）。

## 2. 在系统中的位置

```
CLI: forensic_analyzer <镜像> … --dump-text [--dump-text-max-size 500M]
  └─ CommandLineParser.cpp:16-56 parseBinarySize（K/M/G/T 二进制乘数，正整数，无符号无小数）
       └─ AnalysisOrchestrator.cpp:396-445（Step 7，磁盘流水线尾部，可选）
            FileExtractorTextDumpSource(image, effectiveRawDb)   ← 源适配器（抽原件）
            MarkitdownTextDumpConverter(MarkitdownProxy::instance()) ← 转换适配器（Python 服务）
            TextDumpExporter(source, converter).run({originalRoot, markdownRoot, max_bytes})
                 ├─ <base>_extracted_files/   原件树（镜像目录结构）
                 └─ <base>_extracted_text/    Markdown 树（同构 + .md 后缀）
```

注意它在**磁盘流水线之后**运行且消费的是 `effectiveRawDb`（可能是 filtered.db）；任何失败（服务挂了、超限）都不影响核心取证库——orchestrator 明确 "Core forensic databases remain valid"（AnalysisOrchestrator.cpp:443-445）。

**CLI 参数与产出布局**：`--dump-text`（`CommandLineParser.cpp:235-236`，置位无值）；`--dump-text-max-size 500M`（`:237-248`，解析后**附带置位** `--dump-text`）。产出两棵树（`AnalysisOrchestrator.cpp:406-410`）：`<镜像目录>/<stem>_extracted_files/`（原件二进制原样落盘）与 `<stem>_extracted_text/`（Markdown，路径同构加 `.md`）；roots 都经 `weakly_canonical` 归一（Python 服务 CWD 可能不同）。

## 3. 核心概念与设计

### 3.1 两个接口，一个引擎

引擎只认接口不认实现（TextDumpExporter.h:44-67）：

```cpp
class ITextDumpFileSource {          // 回答"从哪拿文件"
public:
    virtual bool initialize(std::string& error) = 0;
    virtual std::vector<FileRecord> listRegularFilesOrdered(std::string& error) = 0;
    virtual FileDeltaResult extractOne(const FileRecord& record,
                                       const std::filesystem::path& outputRoot) = 0;
    virtual int extractAll(const std::filesystem::path& outputRoot, std::string& error) = 0;
};
class ITextDumpConverter {           // 回答"怎么变 Markdown"
public:
    virtual bool isAvailable() = 0;
    virtual MarkdownDeltaResult convertOne(const fs::path& inputRoot, const fs::path& inputFile,
                                           const fs::path& outputRoot, bool force) = 0;
    virtual BatchConversionResult convertBatch(const fs::path& inputRoot, const fs::path& outputRoot) = 0;
};
```

`force` 参数是续跑语义的关键（见 3.4）。生产实现在 TextDumpAdapters.cpp：`FileExtractorTextDumpSource` 包 FileExtractor 的**原子抽取 API**（`extractRecordAtomically`），`MarkitdownTextDumpConverter` 包 `LLMIntegration/MarkitdownProxy`。测试/未来扩展（如换转换服务）只需换 adapter。

### 3.2 状态机与记账结构

每文件两个阶段各有枚举状态（h:15-17），连同 delta 结构与汇总结果构成状态契约：

```cpp
// TextDumpExporter.h:15-17
enum class OriginalStatus { Extracted, Reused, Failed, UnsafePath };
enum class MarkdownStatus { Converted, Reused, Skipped, Failed, ServiceError };
enum class StopReason { Completed, SizeLimitReached, ServiceUnavailable, OutputError };

// TextDumpExporter.h:19-33（节选，两结构同构）
struct FileDeltaResult {
    OriginalStatus status = OriginalStatus::Failed;
    std::filesystem::path output_path;
    uint64_t previous_bytes = 0;   // 该文件替换前在盘上的旧大小（Reused 时 = output_bytes）
    uint64_t output_bytes = 0;     // 本次落盘大小
    std::string error;
};

// TextDumpExporter.h:75-91（节选）
struct TextDumpResult {
    StopReason stop_reason = StopReason::Completed;
    size_t candidate_files = 0;      // 有序清单里的文件总数
    size_t processed_files = 0;      // 本轮真正处理过的
    size_t originals_extracted = 0;  size_t originals_reused = 0;  size_t originals_failed = 0;
    size_t markdown_converted = 0;   size_t markdown_reused = 0;
    size_t markdown_skipped = 0;     size_t markdown_failed = 0;
    uint64_t initial_bytes = 0;      // 起始记账（含上次残留）
    uint64_t final_bytes = 0;        // 结束时用量
    std::optional<uint64_t> max_bytes;
    bool truncated = false;
    std::string message;
};
```

`StopReason` 四值对应四类终点：正常完成、软限制触发、转换服务不可用、输出/扫描错误。`previous_bytes/output_bytes` 是增量记账的输入：引擎不必知道文件多大，只需知道"这个文件让总用量变化了多少"，用 `applyDelta`（TextDumpExporter.cpp:80-86）更新——`usage -= min(usage, before); usage += after`，`min` 防向下溢出，向上溢出抛异常由 `run()` 最外层 catch 转 `OutputError`，避免每写一个文件就全树重扫。

### 3.3 用量统计的安全底线

`scanRoot`（:34-78）递归扫描时的真实代码（节选）：

```cpp
// TextDumpExporter.cpp:34-78（节选）
fs::recursive_directory_iterator it(
    root, fs::directory_options::skip_permission_denied, ec);   // 权限不足不中断
for (; it != end; it.increment(ec)) {
    const auto status = it->symlink_status(ec);
    if (fs::is_symlink(status)) {
        if (fs::is_directory(status)) it.disable_recursion_pending();  // 目录型链接不递归
        continue;                                  // 符号链接一律不计入
    }
    if (!fs::is_regular_file(status)) continue;
    if (it->path().filename().string().starts_with(kTempPrefix)) {
        fs::remove(it->path(), ec);                // 清理上次中断的 .tracelens-textdump-tmp-* 残块
        continue;
    }
    const uint64_t size = fs::file_size(it->path(), ec);
    if (ec || size > std::numeric_limits<uint64_t>::max() - total) {
        error = ec ? ec.message() : "Text dump usage overflows uint64_t";
        return std::nullopt;
    }
    total += size;
}
```

三个安全点：跳过符号链接（目录型 symlink 还要 `disable_recursion_pending`，:56-59）防止链接绕过预算；顺手清理残块（:61-69）；溢出 uint64 显式报错。`prepareRoot`（:18-32）拒绝 root 本身是 symlink。`calculateUsage`（:94-109）对两个 root 分别 `prepareRoot` + `scanRoot` 后相加——**原件与 Markdown 合并计费**。

## 4. 工作流程走读

`run`（TextDumpExporter.cpp:125-278）两条路径：

**无上限**（max_bytes 为空，:136-169）：`extractAll` 全量抽取 → `convertBatch` 批量转换 → 事后 calculateUsage 只为汇报。行为等价旧版"不设限"。

**有上限**（:171-271），有界循环的核心段（:204-259 节选）：

```cpp
uint64_t current = result.initial_bytes;
for (const auto& fileRecord : records) {
    if (current >= *options.max_bytes) {          // ← 每轮开始前查余量（软限制的关键）
        result.truncated = true;
        result.stop_reason = StopReason::SizeLimitReached;
        result.message = "size limit reached; completed files were preserved";
        break;
    }
    ++result.processed_files;
    const auto original = source_.extractOne(fileRecord, options.original_root);
    switch (original.status) {
        case OriginalStatus::Extracted: ++result.originals_extracted; break;
        case OriginalStatus::Reused:     ++result.originals_reused;   break;  // 上次已抽过，直接复用
        case OriginalStatus::Failed:
        case OriginalStatus::UnsafePath: ++result.originals_failed;  continue; // 放弃本文件，继续
    }
    applyDelta(current, original.previous_bytes, original.output_bytes);   // 增量记账

    const auto markdown = converter_.convertOne(
        options.original_root, original.output_path, options.markdown_root,
        original.status == OriginalStatus::Extracted);   // force = 是否新抽
    // ... Converted/Reused/Skipped 计数；Failed 只计数不终止；
    //     ServiceError 记账后立即返回 StopReason::ServiceUnavailable ...
    applyDelta(current, markdown.previous_bytes, markdown.output_bytes);
    result.final_bytes = current;
}
```

流程逐步读：

1. `calculateUsage` 起始记账（含清理残块）；已到限 → 立即 `SizeLimitReached`（:181-187），**已完成文件保留**；
2. 取有序文件清单，逐文件：查余量 → `extractOne` → 记账 → `convertOne(force=是否新抽)`；
3. 关键的软限制语义（:261-270 注释原话："The active file was allowed to push final usage over the limit"）：循环每轮**开始前**检查余量，正在处理的文件允许把总量推过上限；结束后只有"还有未处理候选 **且** 用量已达限"（`processed_files < candidate_files && current >= max_bytes`）才标 truncated。上限是"停机线"不是"硬顶"。
4. `ServiceError` 与单文件 `Failed` 的处理截然不同：后者只计数、继续循环，前者立即返回——服务挂了意味着后面所有转换都会失败，继续没有意义。

转换适配器的**续跑快路径**与 **force 失败删旧件**（TextDumpAdapters.cpp:80-131 节选）：

```cpp
const fs::path relative = fs::relative(inputFile, inputRoot);
const fs::path expected = outputRoot / (relative.string() + ".md");
// ... existingRegular = 目标 .md 已存在且是普通文件（拒绝 symlink），previous = 其大小 ...

// Resume fast path: an existing valid Markdown is reused as-is when the
// original was not freshly extracted, skipping the service entirely.
if (!force && existingRegular) {
    return {MarkdownStatus::Reused, expected, previous, previous, ""};
}
// ...调 proxy_.convertOneToMarkdown(...)，映射 Converted/Skipped/Failed/ServiceError...

// The proxy did not replace the file. When force=true the original was
// freshly extracted, so any prior Markdown is stale: remove it and report
// output_bytes=0 so a later run cannot reuse mismatched Markdown.
if (force && existingRegular) {
    std::error_code removeEc;
    fs::remove(expected, removeEc);
    return {status, expected, previous, 0U, converted.error};
}
```

原件不是新抽的（force=false）且目标 `.md` 已存在 → 直接 Reused，**完全不碰 Python 服务**；反之 force=true 而转换失败时**删掉旧 .md** 并报 `output_bytes=0`，防止下一轮复用与旧原件不匹配的 Markdown——这是数据一致性上容易漏的一手。

## 5. 与其他模块的协作

| 协作方 | 关系 |
|---|---|
| FileExtractor | 原件抽取的实际执行者；`listRegularFilesOrdered` 决定导出顺序（也就决定了软限制下"谁先被转出"） |
| MarkitdownProxy / python_service | Markdown 转换的实际执行者；`isServiceAvailable()` 为假时整个 run 直接 ServiceUnavailable（:130-134） |
| AnalysisOrchestrator | 唯一调用方；roots 用 `weakly_canonical` 归一（Python 服务 CWD 可能不同，:406-410 注释） |
| CommandLineParser | `--dump-text-max-size` 解析（附带置位 `--dump-text`，CommandLineParser.cpp:242-248） |

## 6. 注意事项与已知问题

- **需要 python_service 在跑**：Markitdown 转换是远程调用；服务不在时即使不设限也会在 `isAvailable` 处停（原件都不抽）。
- **UnsafePath 状态实际上不可达**：FileExtractor 的原子抽取把不安全路径归并为 Failed（TextDumpAdapters.cpp:33-36 注释明说 by design）——读代码时别去找它的赋值点。
- **记账≠精确**：`applyDelta` 只对引擎经手的文件生效；期间有外部进程往两个 root 写文件不会被察觉，直到下一轮 `calculateUsage` 全树重扫。
- **`convertBatch`（无上限路径）绕过逐文件记账**：批量转换的成败只汇总成计数，超限语义只在逐文件路径上存在——因此"想要限制就必须传 max_bytes"，没有隐式默认值。
- **原件树可能很大**：即使 Markdown 很小，原件（二进制原样落盘）也占大头；预算把两者合并计算正是为此（calculateUsage 两 root 相加，:94-109）。
- **force 失败删旧件是单向的**：删除失败（`removeEc` 非零）时不重试也不报错，仅靠 `output_bytes=0` 让记账自洽；下一轮若删除仍未生效，理论上存在复用陈旧 .md 的窗口（实践概率极低）。

## 7. 如何验证与扩展

- **验证**：`--dump-text --dump-text-max-size 1M` 跑小镜像 → stdout 出现 "N / M files processed" 与 "size: X / 1.0 MiB soft limit"（AnalysisOrchestrator.cpp:426-437）；再原样跑第二次，计数应大量走 reused（续跑生效）；`ls <base>_extracted_text` 确认目录结构与镜像同构。
- **扩展**：换转换后端 → 实现一个新的 `ITextDumpConverter`（参考 MarkitdownTextDumpConverter 的 Reused/Skipped 语义，务必实现 force 删除旧件逻辑）；换文件来源（如只导出某分类）→ 实现 `ITextDumpFileSource`，在 orchestrator 装配点（:413-416）替换。引擎本身无需改动。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
