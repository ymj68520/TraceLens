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

## 3. 核心概念与设计

### 3.1 两个接口，一个引擎

引擎只认接口不认实现（TextDumpExporter.h:44-67）：

- `ITextDumpFileSource`：`initialize / listRegularFilesOrdered / extractOne / extractAll`——"从哪拿文件"；
- `ITextDumpConverter`：`isAvailable / convertOne / convertBatch`——"怎么变 Markdown"。

生产实现在 TextDumpAdapters.cpp：`FileExtractorTextDumpSource` 包 FileExtractor 的**原子抽取 API**（`extractRecordAtomically`），`MarkitdownTextDumpConverter` 包 `LLMIntegration/MarkitdownProxy`。测试/未来扩展（如换转换服务）只需换 adapter。

### 3.2 状态机与记账

每文件两个阶段各有枚举状态（h:15-17）：原件 `Extracted/Reused/Failed/UnsafePath`，Markdown `Converted/Reused/Skipped/Failed/ServiceError`；整体 `StopReason`：`Completed / SizeLimitReached / ServiceUnavailable / OutputError`。`FileDeltaResult/MarkdownDeltaResult` 携带 `previous_bytes/output_bytes`，引擎用 `applyDelta`（TextDumpExporter.cpp:80-86）增量记账，避免每写一个文件就全树重扫。

### 3.3 用量统计的安全底线

`scanRoot`（:34-78）递归扫描时：跳过符号链接（目录型 symlink 还要 `disable_recursion_pending`，:56-59）；顺手清理上次中断留下的 `.tracelens-textdump-tmp-*` 残块（:61-69）；溢出 uint64 显式报错。`prepareRoot`（:18-32）拒绝 root 本身是 symlink——防止预算记账被链接绕过。

## 4. 工作流程走读

`run`（TextDumpExporter.cpp:125-278）两条路径：

**无上限**（max_bytes 为空，:136-169）：`extractAll` 全量抽取 → `convertBatch` 批量转换 → 事后 calculateUsage 只为汇报。行为等价旧版"不设限"。

**有上限**（:171-271）：

1. `calculateUsage` 起始记账（含清理残块）；已到限 → 立即 `SizeLimitReached`（:181-187），**已完成文件保留**；
2. 取有序文件清单，逐文件：查余量 → `extractOne`（Reused 说明上次已抽过，直接复用）→ 记账 → `convertOne(force=是否新抽)`；
3. 关键的软限制语义（:261-270 注释）：循环每轮**开始前**检查余量，正在处理的文件允许把总量推过上限；结束后只有"还有未处理候选 **且** 用量已达限"才标 truncated。也就是说上限是"停机线"不是"硬顶"。

转换适配器的**续跑快路径**值得注意（TextDumpAdapters.cpp:94-98）：原件不是新抽的（force=false）且目标 `.md` 已存在 → 直接 Reused，完全不碰 Python 服务；反之 force=true 而转换失败时**删掉旧 .md**（:127-131），防止下一轮复用与旧原件不匹配的 Markdown——这是数据一致性上容易漏的一手。

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

## 7. 如何验证与扩展

- **验证**：`--dump-text --dump-text-max-size 1M` 跑小镜像 → stdout 出现 "N / M files processed" 与 "size: X / 1.0 MiB soft limit"（AnalysisOrchestrator.cpp:426-437）；再原样跑第二次，计数应大量走 reused（续跑生效）；`ls <base>_extracted_text` 确认目录结构与镜像同构。
- **扩展**：换转换后端 → 实现一个新的 `ITextDumpConverter`（参考 MarkitdownTextDumpConverter 的 Reused/Skipped 语义，务必实现 force 删除旧件逻辑）；换文件来源（如只导出某分类）→ 实现 `ITextDumpFileSource`，在 orchestrator 装配点（:413-416）替换。引擎本身无需改动。

**最后更新**: 2026-08-23（新建，解释式）
