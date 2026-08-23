# FileExtractor（src/core/DatabaseManager/FileExtractor/）

> **一句话**：把文件从磁盘镜像里"捞出来"的组件——按 inode/路径/模式/扩展名在 raw.db 里定位记录，再通过 TSK（或 XFS 自研解析器）把字节流读出镜像、以原子写落盘到输出目录；它同时实现 `IFileExtractor` 接口，让 AndroidAnalyzer 能把 TSK 后端和目录/zip 逻辑后端一视同仁。

## 1. 为什么有这个模块

raw.db 记录了"镜像里有什么"，但很多下游工作需要**文件内容本身**：聊天数据库要用 SQLite 打开才能解析、DLL 要读到字节才能查签名、LLM 要内容才能摘要。取证语境下的"读文件"远比 `open()` 复杂：文件在镜像内部，必须经文件系统驱动按 inode 读扇区；删除的文件内容仍在未分配空间里；一个镜像可能有多个分区，inode 在分区之间会撞号；TSK 不支持 XFS，得有自研回退。

安全是另一层必须内建的约束。输出路径由**镜像内的文件路径**拼接而来——取证镜像里完全可能存在 `/../../etc/passwd` 这样的路径条目或指向敏感位置的名称。如果没有路径消毒，解出来的文件能写到输出目录之外的任意位置（路径穿越），symlink 还可能让后续流程写坏系统文件。本模块把这些防御做成了硬性关卡。

最后是**取证级可靠性**：部分读取的文件如果以最终名字留在盘上，会被下游当成完整证据。模块采用"临时文件 + 校验 + 原子 rename"三段式，保证磁盘上要么是旧文件、要么是完整新文件，不存在中间态。

## 2. 在系统中的位置

三条生产路径使用 FileExtractor：

- **CLI 提取模式**：`AnalysisOrchestrator::runExtraction`（`src/AnalysisOrchestrator.cpp:567-632`），即 `--extract-all/--extract-by-name/--extract-by-extension` 子命令；
- **平台 Analyzer 的内容后端**：通过 `IFileExtractor` 接口注入 AndroidAnalyzer（`FileExtractor.h:32` 的继承声明，接口在 `src/analyzers/AndroidAnalyzer/IFileExtractor.h`），AndroidAnalyzer 拿它按路径取应用数据库；
- **HTTP 提取路由与 TextDump 导出**：`FileExtractionRoutes` 调按 inode/路径提取；`textdump::FileExtractorTextDumpSource` 包装 `extractRecordAtomically` 做全量文本导出（`src/export/TextDumpAdapters.cpp`）。

输入三元组：镜像文件路径 + 元数据库（raw.db/files.db）+ 输出目录。它组合持有 `DatabaseManager`（`FileExtractor.h:107`）做记录查询。

```
files/raw.db(记录) ──searchFiles──> FileRecord(含 partitionNum)
       + 磁盘镜像 ──TSK(tsk_fs_file_read) / XFSHelper──> 字节流
                                          └─ 临时文件 → 校验 → 原子 rename → 输出目录
```

## 3. 核心概念与设计

**每分区一个文件系统句柄**是正确性的根基。`openFileSystem()`（`FileExtractor.cpp:96-154`）枚举分区表，对每个已分配分区尝试 `tsk_fs_open_img`，成功则存入 `fsByPartition_[分区号]`；TSK 打不开的分区记录偏移到 `xfsPartitionOffsets_` 留给 XFS 惰性初始化（`:112-116`）。无分区表时整镜像当单文件系统、键为 0（`:122-130`）。

路由与拒绝规则在 `fsForPartition()`（`:172-188`）：优先精确匹配分区号；**分区号非 0 时绝不回退到其他分区的句柄**——inode 会跨分区撞号，"在错误的文件系统上成功打开"意味着静默提取错误内容，这是取证不可接受的；只有分区 0（旧库的遗留值）允许在"仅有一个句柄"时借用。查询侧同步携带 `partition_num`（`searchFiles`，`:220-228`，注释同样强调消歧）。

**XFS 回退**：`xfsForPartition()`（`:190-218`）首次访问某分区时才构造 `XFSHelper`（自研 XFS 读取器，`src/analyzers/ImageAnalyzer/XFSHelper.h`），初始化失败则把偏移从候选表删除避免反复重试。读路径 `readFileContent()`（`:329-358`）先 TSK 后 XFS。

**路径消毒**（`resolveSafeOutputPath`，`FileExtractor_Extract.cpp:257-326`）：逐条检查相对路径组件，`..` 直接拒绝（`:275-282`）；输出路径上任何一级是 symlink 也拒绝（`:286-317`，防 TOCTOU 与替换攻击）；每级必须已是目录。返回 `std::optional`，失败原因写进 error 出参。

**原子提取**（`extractRecordAtomically`，`:328-380`）三段式：先消毒出最终路径；若目标已存在且大小与记录一致则返回 `Reused`（幂等断点续跑的关键，`:339-348`）；否则写临时文件 → `validateTemporaryExtraction` 校验 → `atomicReplace` rename（`:351-373`）。任何一步失败删除临时文件，最终路径不受污染。`AtomicExtractionResult` 的 status（Extracted/Reused/Failed）让调用方（如 TextDumpExporter）能区分"新提取/复用/失败"三种账目。

**ExtractionLimits**（`FileExtractor.h:48-59`）：max_files/max_total_size/max_file_size 三个上限加一组的出参计数器（成功/失败/字节数），HTTP 任务的提取阶段用它防止失控提取撑爆磁盘（`extractRecords`，`FileExtractor_Extract.cpp:382-442` 的逐条检查与 bounded 标记）。

## 4. 工作流程走读

以 `--extract-by-name "wechat*.db"` 为例：

1. `initialize()`（`FileExtractor.cpp:26-56`）：先开库（提示"请先跑分析"，`:35-37`）再开镜像（DETECT 失败重试 RAW，`:58-94`）再开各分区文件系统。
2. `extractByName`（`FileExtractor_Extract.cpp:444-484`）：逗号拆分模式 → `searchFiles("type='REG' AND is_allocated=1")` 全量取 REG 记录 → 自研通配符匹配器筛选（`matchWildcard`，`FileExtractor.cpp:298-324`，回溯式 `*`/`?` 匹配）。
3. `extractRecords` 逐条调 `extractFile`（`FileExtractor_Extract.cpp:660-869`）：
   - 跳过目录；输出已存在且大小一致且未要求覆盖则计 skipped（`:667-682`）；
   - 大小为 0 直接创建空文件（`:685-692`）；
   - TSK 路径：按记录的 partitionNum 取句柄（`:696`），`tsk_fs_file_open_meta` 失败且库是多分区旧数据时尝试其他句柄消歧（`:701-714`，注释解释了这一遗留兼容）；随后 1MB 缓冲循环读（`:742-795`），按 size 读取失败时切换到"固定 1MB 块直读到 EOF"的回退模式（`:755-761`）；
   - 全程写临时文件，成功后 rename（`:802-817`）；XFS 记录走 `xfsForPartition` 分支整读后同样原子落盘（`:819-868`）。
4. 统计返回：提取数/skipped/失败数（含上限截断原因）。

## 5. 与其他模块的协作

- **DatabaseManager**：记录查询的数据源（组合持有，`FileExtractor.h:107`）。
- **IFileExtractor / AndroidAnalyzer**：接口把"按路径取文件"抽象掉后端差异——TSK 镜像、Android 逻辑目录、zip、MIUI 备份四种来源对上层同构（接口声明见 `FileExtractor.h:70-77` 的 override）。
- **XFSHelper**：TSK 无 XFS 支持的补位者；偏移表由 `openFileSystem` 预登记。
- **TextDumpExporter / FileExtractorTextDumpSource**：把原子提取 + Reused 语义包装成"断点续跑的全量文本导出"（CLI `--dump-text`，`AnalysisOrchestrator.cpp:404-455`）。
- **AnalysisOrchestrator.runExtraction**：CLI 入口；它还会做库名换算（传 `_raw.db` 自动改用 `_files.db`，`AnalysisOrchestrator.cpp:575-579`）和镜像名猜测（按 `.dd/.e01/.raw` 等扩展名，`:586-597`）。
- 出错时行为：单文件失败返回 false 并 stderr 记录，不中断批量；路径消毒失败在 limits->errors 里留痕（最多 50 条，`FileExtractor_Extract.cpp:402-404`）。

## 6. 注意事项与已知问题

- **多分区歧义是硬约束**：`extractFileByPath` 遇到一路径对应多分区记录时直接拒绝（`FileExtractor_Extract.cpp:651-655`），错误信息明确要求"partition-aware metadata"；调用方应改用带 partitionNum 的接口（如 `extractFileByInode(inode, out, partition)`，`:566-601`）。
- 旧库（所有记录 partition_num=0）依赖 `:701-714` 的句柄试探消歧——"能打开就认为对了"在 inode 撞号时仍可能取错内容，升级库比依赖试探更可靠。
- `generateOutputPath` 对已删除文件加 inode 后缀防覆盖（`FileExtractor.cpp:386-395`），但已分配文件假设路径唯一——与 raw.db 的现实（不同分区同路径）存在理论冲突，多用按 inode 接口。
- 通配符匹配在**文件名**上做（`:469`），不是全路径；要按目录提取请用 extractAll + limits 或 FileFilter。
- 大小校验只比对记录 size，不做哈希——TSK 读出的内容若在镜像层面就损坏，提取流程不会发现。

## 7. 如何验证与扩展

- 单元测试：`tests/UnitTest/test_file_extractor_text_dump.cpp`（含原子提取/路径消毒行为）；手工冒烟可用仓库根的 `test_image.img`：`./forensic_analyzer --database test_image_raw.db --extract-all --extract-output-dir /tmp/out`（需先跑一次分析生成库）。
- 安全回归：构造含 `..` 的文件名记录插入测试库，断言提取被拒——`resolveSafeOutputPath` 的两个拒绝分支（`..` 与 symlink）是必须保持的防线，任何重构不得放松。
- 扩展方向：(1) 新文件系统支持——优先评估给 TSK 打补丁，其次仿照 XFSHelper 做"偏移登记 + 惰性初始化 + readFileContent 分派"三件套；(2) 增量提取——当前 Reused 判定基于大小一致，可升级为 mtime+size 双因子；(3) 校验增强——提取完成后对比记录 md5（raw.db 有该列）。

**最后更新**: 2026-08-23（解释式重写）
