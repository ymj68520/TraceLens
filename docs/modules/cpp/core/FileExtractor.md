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

### 3.1 核心数据结构（FileExtractor.h:34-59, 96-107）

```cpp
    enum class AtomicExtractionStatus : uint8_t {
        Extracted,
        Reused,
        Failed
    };

    struct AtomicExtractionResult {
        AtomicExtractionStatus status = AtomicExtractionStatus::Failed;
        std::filesystem::path output_path;
        uintmax_t previous_bytes = 0;
        uintmax_t output_bytes = 0;
        std::string error;
    };

    struct ExtractionLimits {
        int64_t max_files = 0;
        int64_t max_total_size = 0;
        int64_t max_file_size = 0;
        int* failed_count = nullptr;
        int* total_count = nullptr;
        int* processed_count = nullptr;
        int64_t* extracted_bytes = nullptr;
        bool* bounded = nullptr;
        std::string* limit_reason = nullptr;
        std::vector<std::string>* errors = nullptr;
    };
```

`AtomicExtractionStatus` 三态对账：`Extracted`（本次新写入）、`Reused`（已存在且大小一致，断点续跑不重做）、`Failed`（默认值——漏设 status 的代码路径也归入失败，fail-safe）。`AtomicExtractionResult` 的 `previous_bytes/output_bytes` 记录替换前后大小，TextDumpExporter 用它统计"本次实际新落盘字节"而非全量字节。`ExtractionLimits` 是**指针包结构**（全部成员是指向调用方栈变量的指针，0 = 不启用该统计）：三个上限 0 表示不限，非 0 时 max_file_size 逐条跳过、max_files/max_total_size 达到即置 `bounded=true` 并写 `limit_reason`（"max_files"/"max_total_size"），`errors` 上限 50 条防内存被错误刷爆。私有侧三张 map 是分区路由的核心状态：`fsByPartition_`（TSK 句柄）、`xfsByPartition_`（惰性 XFS 实例）、`xfsPartitionOffsets_`（openFileSystem 预登记的候选偏移，头文件 `:98-106` 的注释写明了"partition 0 是旧单文件系统情形"这一约定）。

### 3.2 核心接口清单

| 签名（FileExtractor.h） | 语义 | 主要调用方 | 失败行为 |
|---|---|---|---|
| `bool initialize() override` | 开库、开镜像（DETECT 失败重试 RAW）、开各分区文件系统 | 三条路径的入口 | 任一步失败返回 false |
| `int extractByName(pattern, outputDir, overwrite=false, skippedCount=nullptr, limits=nullptr)` | 逗号分隔通配符按文件名提取 | AnalysisOrchestrator.cpp:567-632 | 返回成功条数，失败进 limits/errors |
| `int extractByExtension(extensions, ...)` / `int extractAll(...)` / `int extractDeleted(...)` | 按扩展名/全量/已删除提取 | CLI 旗标对应入口 | 同上 |
| `bool extractFileByInode(inode, outputPath, partitionNum=-1)` | 按 inode 定点提取（可指定分区） | FileExtractionRoutes、平台分析 | 失败返回 false |
| `bool extractFileByPath(filePath, outputPath) override` | 按路径提取（IFileExtractor 接口） | AndroidAnalyzer | 多分区歧义时拒绝 |
| `static vector<FileRecord> queryRegularFilesOrdered(db, error=nullptr)` | 有序取全部 REG 记录（含分区消歧排序） | TextDumpSource | db null / prepare 失败返回空 + error |
| `static optional<path> resolveSafeOutputPath(outputRoot, imagePath, error=nullptr)` | 路径消毒（防穿越/symlink） | extractRecordAtomically | 拒绝时 nullopt + 原因 |
| `AtomicExtractionResult extractRecordAtomically(record, outputRoot)` | 单记录三段式原子提取 | TextDumpAdapters.cpp | 失败删临时文件、status=Failed |

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

### 4.1 代码走读：resolveSafeOutputPath 的两级防线（FileExtractor_Extract.cpp:257-326）

```cpp
std::optional<fs::path> FileExtractor::resolveSafeOutputPath(
        const fs::path& outputRoot, const std::string& imagePath,
        std::string* error) {
    // ... prepareOutputRoot 见 :262-265
    fs::path relative = fs::path(imagePath).relative_path().lexically_normal();
    if (relative.empty() || relative == ".") {
        if (error) {
            *error = "Image path does not identify a file";
        }
        return std::nullopt;
    }
    for (const auto& component : relative) {
        if (component == "..") {
            if (error) {
                *error = "Image path escapes the output root: " + imagePath;
            }
            return std::nullopt;
        }
    }

    std::error_code ec;
    fs::path current = outputRoot;
    for (const auto& component : relative.parent_path()) {
        current /= component;
        const auto status = fs::symlink_status(current, ec);
        if (!ec && fs::is_symlink(status)) {
            if (error) {
                *error = "Output path contains a symlink: " + current.string();
            }
            return std::nullopt;
        }
        // ... 非目录 / 无法检查的拒绝分支见 :309-320
    }
    const fs::path result = outputRoot / relative;
    const auto finalStatus = fs::symlink_status(result, ec);
    // ... 最终文件本身是 symlink 也拒绝（:321-326）
    return result;
}
```

逐块解释：第一道防线是**词法层**——`relative_path().lexically_normal()` 把镜像内路径归一（`a/./b` 折叠、`a/x/../b` 化简）后检查是否残留 `..` 组件；归一化先行是关键，否则 `foo/../..` 这类写法能绕过朴素的子串检查。第二道防线是**文件系统层**——逐级 `symlink_status` 检查输出路径上的每个已存在组件：symlink 一律拒绝（哪怕它指向输出目录内部），因为链接目标可以在检查与写入之间被换掉（TOCTOU）；不存在（`no_such_file_or_directory`）是唯一被放行的"异常"，其余 I/O 错误全部拒绝。**注意消毒作用在 `relative.parent_path()` 上、最终文件名单独再查一次 symlink**——目录级与文件级分开把关。error 出参让每个拒绝分支都带可读原因，TextDump 的失败清单因此能告诉用户"哪个文件因什么被拒"。

### 4.2 代码走读：extractRecordAtomically 的三段式（FileExtractor_Extract.cpp:328-380）

```cpp
FileExtractor::AtomicExtractionResult FileExtractor::extractRecordAtomically(
        const FileRecord& record, const fs::path& outputRoot) {
    AtomicExtractionResult result;
    auto finalPath = resolveSafeOutputPath(outputRoot, record.path, &result.error);
    if (!finalPath) {
        result.status = AtomicExtractionStatus::Failed;
        return result;
    }
    result.output_path = *finalPath;

    std::error_code ec;
    const auto finalStatus = fs::symlink_status(*finalPath, ec);
    if (!ec && fs::is_regular_file(finalStatus)) {
        result.previous_bytes = fs::file_size(*finalPath, ec);
        if (!ec && record.size >= 0 &&
            result.previous_bytes == static_cast<uintmax_t>(record.size)) {
            result.status = AtomicExtractionStatus::Reused;
            result.output_bytes = result.previous_bytes;
            return result;
        }
    }
    ec.clear();
    // ... prepareOutputParent、temporaryPathFor 见 :349-352
    const fs::path temporaryPath = temporaryPathFor(*finalPath, record);
    if (!extractFile(record, temporaryPath.string(), true, nullptr)) {
        fs::remove(temporaryPath, ec);
        result.status = AtomicExtractionStatus::Failed;
        result.error = "Failed to extract " + record.path;
        return result;
    }
    if (!validateTemporaryExtraction(temporaryPath, record, result.error)) {
        fs::remove(temporaryPath, ec);
        result.status = AtomicExtractionStatus::Failed;
        return result;
    }
    if (!atomicReplace(temporaryPath, *finalPath, result.error)) {
        fs::remove(temporaryPath, ec);
        result.status = AtomicExtractionStatus::Failed;
        return result;
    }
    result.status = AtomicExtractionStatus::Extracted;
    result.output_bytes = fs::file_size(*finalPath, ec);
    // ... stat 失败回退 Failed 见 :377-380
    return result;
}
```

逐块解释：函数的不变量是"**最终路径上要么是从未动过的旧文件，要么是校验过的完整新文件**"。入口先消毒（失败即 Failed，不碰磁盘）；随后是 Reused 快路径——目标已是常规文件且大小等于记录 size 就直接复用，这让 `--dump-text` 中断后重跑能跳过已完成的几十万个文件（大小判据的弱点见第 6 节）。慢路径三段：临时文件名与最终文件同目录（`temporaryPathFor` 拼在 `finalPath.parent_path()` 下，保证 rename 是同文件系统操作、天然原子）；`extractFile` 以 overwrite=true 写临时名；`validateTemporaryExtraction` 只校验**字节数等于记录 size**（快、无哈希）；`atomicReplace` 才把临时名换成最终名。三个失败分支都先 `fs::remove(temporaryPath)` 再返回——半成品永远留在隐藏的临时名下而非最终名。结尾对最终文件再 stat 一次拿 output_bytes，连这一步失败也回退为 Failed：结果的每个字段要么可信、要么整体判败。

### 4.3 代码走读：atomicReplace 与临时名生成（FileExtractor_Extract.cpp:28-61）

```cpp
bool atomicReplace(const fs::path& temporaryPath, const fs::path& finalPath,
                   std::string& error) {
#ifdef _WIN32
    if (MoveFileExW(temporaryPath.wstring().c_str(), finalPath.wstring().c_str(),
                    MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) {
        return true;
    }
    error = "Cannot replace output file: " + std::to_string(GetLastError());
    return false;
#else
    std::error_code ec;
    fs::rename(temporaryPath, finalPath, ec);
    if (!ec) {
        return true;
    }
    error = "Cannot replace output file: " + ec.message();
    return false;
#endif
}

fs::path temporaryPathFor(const fs::path& finalPath, const FileRecord& record) {
    static std::atomic_uint64_t sequence{0};
    const auto nonce = static_cast<uint64_t>(
        std::chrono::steady_clock::now().time_since_epoch().count());
    // ... processId 取 GetCurrentProcessId()/getpid()（:53-55）
    return finalPath.parent_path() /
           (".tracelens-textdump-tmp-" + std::to_string(record.partitionNum) + "-" +
            std::to_string(record.inode) + "-" + std::to_string(processId) + "-" +
            std::to_string(nonce) + "-" + std::to_string(sequence.fetch_add(1)));
}
```

逐块解释：POSIX 的 `rename(2)` 对已存在目标是原子的覆盖替换，这是三段式的最后一块基石；Windows 的 `std::filesystem::rename` 语义不完全一致，所以显式用 `MoveFileExW` 带 `MOVEFILE_REPLACE_EXISTING`（允许覆盖）+ `MOVEFILE_WRITE_THROUGH`（元数据落盘再加返回）——两个平台的差异被隔离在这一个函数里，调用方无需感知。临时文件名的五个组成部分各有用途：`partitionNum-inode` 定位记录（崩后残留的临时文件可以从名字反查出属于哪条记录）、`processId` 隔离并发实例、`steady_clock` nonce + 原子序号保证同进程同记录多次提取不重名（steady_clock 还不受系统时间回调影响）。前缀 `.tracelens-textdump-tmp-` 是**清理锚点**——目录扫描器可凭前缀识别并清除孤儿临时文件。

### 4.4 代码走读：queryRegularFilesOrdered 的确定性排序（FileExtractor_Extract.cpp:185-228）

```cpp
    const char* sql = R"SQL(
        SELECT inode, name, path, size, mtime, ctime, type, is_deleted, md5,
               COALESCE(partition_num, 0)
        FROM files
        WHERE type = 'REG'
          AND is_deleted = 0
          AND COALESCE(is_allocated, 1) = 1
        ORDER BY path COLLATE BINARY ASC,
                 COALESCE(partition_num, 0) ASC,
                 inode ASC
    )SQL";
    // ... 逐行读入 FileRecord，atime/crtime/permissions/uid/gid 等缺省列
    // 以回填值补齐（record.atime = record.mtime; record.isAllocated = 1; 等，:227-236）
```

逐块解释：WHERE 三条件圈定"活的常规文件"——REG、未删除、已分配（`COALESCE(is_allocated,1)` 把旧库 NULL 行当已分配，读取侧兜底）。ORDER BY 是**确定性契约**：path 用 `COLLATE BINARY` 强制字节序（避免不同 locale 的排序差异导致两次运行顺序不同），同路径再按分区号、inode 决出唯一序——断点续跑时"处理到哪"才有可比性，软限额（max_total_size）截断的位置也可复现。SELECT 只取 10 列，FileRecord 里没有的 atime/crtime/权限字段用回填值（atime←mtime、permissions="0644"）补齐——**这些字段对提取无意义**，回填只为结构完整，下游不要把它们当真实元数据用。

## 5. 与其他模块的协作

- **DatabaseManager**：记录查询的数据源（组合持有，`FileExtractor.h:107`）；读 files/raw.db 的 files 表（inode/path/size/type/is_deleted/is_allocated/md5/partition_num 列）。
- **IFileExtractor / AndroidAnalyzer**：接口把"按路径取文件"抽象掉后端差异——TSK 镜像、Android 逻辑目录、zip、MIUI 备份四种来源对上层同构（接口声明见 `FileExtractor.h:70-77` 的 override）。
- **XFSHelper**：TSK 无 XFS 支持的补位者；偏移表由 `openFileSystem` 预登记。
- **TextDumpExporter / FileExtractorTextDumpSource**：把原子提取 + Reused 语义包装成"断点续跑的全量文本导出"（CLI `--dump-text`，`AnalysisOrchestrator.cpp:404-455`；软限额 `--dump-text-max-bytes` 映射到 ExtractionLimits.max_total_size）。
- **AnalysisOrchestrator.runExtraction**：CLI 入口；它还会做库名换算（传 `_raw.db` 自动改用 `_files.db`，`AnalysisOrchestrator.cpp:575-579`）和镜像名猜测（按 `.dd/.e01/.raw` 等扩展名，`:586-597`）。
- 出错时行为：单文件失败返回 false 并 stderr 记录，不中断批量；路径消毒失败在 limits->errors 里留痕（最多 50 条，`FileExtractor_Extract.cpp:402-404`）。

## 6. 注意事项与已知问题

- **多分区歧义是硬约束**：`extractFileByPath` 遇到一路径对应多分区记录时直接拒绝（`FileExtractor_Extract.cpp:651-655`），错误信息明确要求"partition-aware metadata"；调用方应改用带 partitionNum 的接口（如 `extractFileByInode(inode, out, partition)`，`:566-601`）。
- 旧库（所有记录 partition_num=0）依赖 `:701-714` 的句柄试探消歧——"能打开就认为对了"在 inode 撞号时仍可能取错内容，升级库比依赖试探更可靠。
- `generateOutputPath` 对已删除文件加 inode 后缀防覆盖（`FileExtractor.cpp:386-395`），但已分配文件假设路径唯一——与 raw.db 的现实（不同分区同路径）存在理论冲突，多用按 inode 接口。
- 通配符匹配在**文件名**上做（`:469`），不是全路径；要按目录提取请用 extractAll + limits 或 FileFilter。
- 大小校验只比对记录 size，不做哈希——TSK 读出的内容若在镜像层面就损坏，提取流程不会发现。
- **Reused 判据是大小相等**：同大小的不同版本（编辑前后恰好等长）会被误判为已提取；升级方向见第 7 节。
- 临时文件失败即删，但**进程崩溃**（SIGKILL/断电）会留下 `.tracelens-textdump-tmp-*` 孤儿——重跑不会清理它们（前缀可识别，需运维脚本偶尔扫除）。
- ExtractionLimits 的三个上限都是"0 = 不限"，调用方传负值等于关闭该限制；bounded 只在 max_files/max_total_size 触发时置位。

## 7. 如何验证与扩展

- 单元测试：`tests/UnitTest/test_file_extractor_text_dump.cpp`（含原子提取/路径消毒行为）；手工冒烟可用仓库根的 `test_image.img`：`./forensic_analyzer --database test_image_raw.db --extract-all --extract-output-dir /tmp/out`（需先跑一次分析生成库）。
- 安全回归：构造含 `..` 的文件名记录插入测试库，断言提取被拒——`resolveSafeOutputPath` 的两个拒绝分支（`..` 与 symlink）是必须保持的防线，任何重构不得放松。
- 扩展方向：(1) 新文件系统支持——优先评估给 TSK 打补丁，其次仿照 XFSHelper 做"偏移登记 + 惰性初始化 + readFileContent 分派"三件套；(2) 增量提取——当前 Reused 判定基于大小一致，可升级为 mtime+size 双因子；(3) 校验增强——提取完成后对比记录 md5（raw.db 有该列）；(4) 孤儿清理——extractRecords 入口扫一遍输出目录删除带 `.tracelens-textdump-tmp-` 前缀的残留。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
