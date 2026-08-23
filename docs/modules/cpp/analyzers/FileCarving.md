# FileCarving（src/analyzers/FileCarving/FileCarver.{h,cpp}）

> **一句话**：文件雕刻——不管文件系统还认不认识这些数据，直接按魔数签名扫描镜像的**未分配块**，把残存的图片、文档、压缩包、数据库、可执行文件恢复到磁盘上的 `carved_files/` 目录。

## 1. 为什么有这个模块

"删除"从来不是消失。文件被删后，目录项释放、数据块标记为未分配，但字节还在原地，直到被新数据覆盖。文件系统层的方法（ImageAnalyzer 的 UNALLOC 遍历）只能找回目录项尚存的文件；当目录项本身被破坏（格式化、文件系统损坏、反取证工具擦目录）时，唯一的路是**放弃文件系统语义、直接在字节流里找文件开头的魔数**——JPEG 的 `FF D8 FF`、PDF 的 `%PDF`、ZIP 的 `PK..`——从头部开始向后读，直到遇到尾部签名或大小上限。这就是雕刻（carving），它是对文件系统解析的最后一道兜底。

这个模块选择雕刻的是**未分配空间**而非全盘：通过 TSK 的 `tsk_fs_block_walk` 只走 `TSK_FS_BLOCK_FLAG_UNALLOC` 的块（`FileCarver.cpp:472-475`）。这是个务实的取舍——已分配块里的文件理论上已被 ImageAnalyzer 收进 raw.db，再雕一遍是浪费；而未分配块正是"删除残留"最集中的地方。全盘裸雕（对付全盘加密或无文件系统镜像）留给未来扩展。

第三个设计立场是**验证降噪**。纯魔数匹配误报很多（随机字节撞上两字节 `MZ` 并不稀奇），所以雕刻后对常见格式做结构校验（JPEG 头尾齐全、PNG 头正确等），文件小于 100 字节直接丢弃（`FileCarver.cpp:405-409`），恢复结果带 `validated` 标记——调查者可以先看通过验证的，再看存疑的。

## 2. 核心数据结构

**签名表驱动**（`FileCarver.h:14-22`）是整个模块的"知识库"：

```cpp
struct CarvingSignature {
    std::string name;              // Human-readable name
    std::string extension;         // File extension
    std::vector<uint8_t> header;   // Header magic bytes
    std::vector<uint8_t> footer;   // Optional footer magic bytes
    size_t maxSize;                // Maximum file size to carve
    int headerOffset = 0;          // Offset from match to actual file start
    bool hasFixedSize = false;     // If true, maxSize is exact size
};
```

逐字段：`header` 是匹配用的魔数（越长越独特，SQLite 16 字节几乎零误报，BMP/MZ 两字节误报很多）；`footer` 留空则按 `maxSize` 截断、非空则边读边搜尾部实现精确截断；`headerOffset` 处理"魔数不在文件起点"的格式（MP4 的 `ftyp` 在偏移 4，用 -4 回拨）；`hasFixedSize` 表示 maxSize 是精确长度而非上限。整套行为完全由数据决定——加新格式不改代码，只加一行 `signatures_.push_back({...})`。

**产物与统计**（`FileCarver.h:27-50`）：

```cpp
struct CarvedFileInfo {
    std::string path;              // Output file path
    std::string signatureName;     // Which signature matched
    std::string extension;
    uint64_t sourceOffset;         // Offset in source image
    uint64_t size;                 // Actual carved size
    bool validated;                // Whether file passed validation
    std::string validationMessage; // Validation result message
};
struct CarvingStatistics {
    int totalFilesCarved = 0;
    uint64_t totalBytesCarved = 0;
    int validFiles = 0;
    int invalidFiles = 0;
    int errors = 0;
    std::map<std::string, int> filesByType;   // Count per signature type
    double elapsedSeconds = 0.0;
    uint64_t blocksScanned = 0;      // 扫过的块数（进度与统计双用）
    uint64_t unallocatedBlocks = 0;  // 其中未分配块数
};
```

`sourceOffset` 是镜像绝对偏移，直接进文件名（`carved_<绝对偏移>.<扩展名>`），天然可溯源。

**块遍历上下文**（`FileCarver.cpp:13-26`）：TSK 的 C 风格回调不能带闭包，`CarvingContext` 把 carver 指针、文件系统句柄、输出目录、统计、已雕区域表、进度回调等打包成一个结构体传 `void* ptr`——这是把 C API 接进 C++ 类的标准桥接手法。

### 2.1 核心接口清单

`FileCarver`（`FileCarver.h:64-151`）的公开 API：

| 方法 | 语义 | 调用方 | 失败行为 |
|------|------|--------|---------|
| `int carve(imagePath, outputDir, partitionOffset=0)` | 主入口：开镜像 → 单 FS 或逐分区雕刻，返回恢复数 | HTTP `TaskManagerAnalysis.cpp:531-556`（第 7 步）；CLI `AnalysisOrchestrator.cpp:690-701`（`--carve`） | 镜像打不开返回 0；FS/卷系统都打不开只报错不抛异常 |
| `const std::vector<CarvingSignature>& getSignatures()` | 取签名表 | 回调内部遍历 | — |
| `const std::vector<CarvedFileInfo>& getCarvedFiles()` / `getStatistics()` | 取上次结果/统计 | 调用方汇报 | — |
| `void setProgressCallback(cb)` | 按块数报进度（每 1000 块） | HTTP 任务的进度通道 | — |
| `void setCancelCallback(cb)` | 任务取消时立即 `TSK_WALK_STOP` | HTTP 任务取消 | — |
| `void setDatabasePath(dbPath)` | 指定 SQLite 库落 carved_files 表 | **无生产调用方**（预留，见第 6 节） | — |
| `void setValidationEnabled(bool)` | 开关雕刻后验证 | 默认 true | — |
| `void addSignature(sig)` | 运行时注入自定义签名 | 预留 | — |

## 3. 在流水线中的位置

两种触发方式：

- **HTTP 模式**：任务勾选 `file_carving` 后，在 PLATFORM_ANALYSIS 之后作为第 7 步运行（`TaskManagerAnalysis.cpp:531-556`），输出到 `data/tasks/<id>/carved_files/`。它在总进度里占 3% 权重（`TaskManager.cpp:547-556` 的 phase_weights 表），支持取消（cancelCallback）与进度回调（按扫描块数汇报）。
- **CLI 模式**：`--carve` 独立子命令 `runFileCarving`（`AnalysisOrchestrator.cpp:690-701`），输出目录默认 `carved_files/`（可用 carve_output_dir 覆盖）。

输入：镜像路径（TSK 自动识别格式）+ 输出目录。输出有两路：**文件本体**落 `carved_files/`（多分区镜像按 `part<N>/` 子目录分放）；**记录**可选写入 SQLite 的 `carved_files` 表（`setDatabasePath()` 指定库后自动建表插入，schema 见 `FileCarver.cpp:565-590`）。注意：当前 HTTP 流水线和 CLI 子命令都**没有**调用 `setDatabasePath`，所以默认只有文件输出、没有表记录——这个库表接口是留给后续集成的（第 6 节详述）。

## 4. 证据来源与覆盖范围

29 个内置签名（`initializeSignatures()`，`FileCarver.cpp:34-283`），按类型分组：

| 类型 | 签名（数量） | 尾部签名/大小上限特点 |
|------|-------------|---------------------|
| 图片 | JPEG、PNG、GIF87a/89a、BMP、WebP、TIFF-LE/BE（8 个） | JPEG/PNG/GIF 有尾部魔数（精确截断）；BMP/WebP/TIFF 无（按上限截断） |
| 文档 | PDF（1 个） | 尾部 `%%EOF` |
| 压缩包 | ZIP、RAR5、RAR4、7z、gzip、bzip2、xz（7 个） | ZIP 有 EOCD 尾部；其余无尾部，上限 200-500MB |
| 音视频 | MP3×2（ID3/帧同步）、WAV、FLAC、OGG、MP4/MOV、AVI、MKV/WebM、FLV（9 个） | MP4 的 `ftyp` 在偏移 4，用 `headerOffset=-4` 回退到真文件头（第 214-220 行） |
| 数据库/可执行/邮件 | SQLite、ELF、PE(MZ)、Outlook PST（4 个） | SQLite 魔数 16 字节含结尾 NUL，误报率极低 |

签名定义的真实代码（注意 MP4 的 headerOffset 与 PST 的 2GB 上限）：

```cpp
// FileCarver.cpp:213-220、248-254
// MP4/MOV: ftyp at offset 4
signatures_.push_back({
    "MP4/MOV Video", "mp4",
    {0x66, 0x74, 0x79, 0x70},  // "ftyp"
    {},
    2ULL * 1024 * 1024 * 1024,  // 2GB
    -4  // ftyp appears at offset 4, so go back 4 bytes
});
// SQLite: 53 51 4C 69 74 65 20 66 6F 72 6D 61 74 20 33 00
signatures_.push_back({
    "SQLite Database", "sqlite",
    {0x53, 0x51, 0x4C, 0x69, 0x74, 0x65, 0x20, 0x66, 0x6F, 0x72, 0x6D, 0x61, 0x74, 0x20, 0x33, 0x00},
    {},
    500 * 1024 * 1024
});
```

MP4 案例解释了 `headerOffset` 的用途：匹配到 `ftyp` 时它在文件内偏移 4（前面还有 4 字节的 box 长度），回拨 -4 才是真正的文件起点，否则恢复出的 mp4 缺头无法播放。SQLite 的 16 字节魔数带结尾 NUL（`SQLite format 3\0`），随机数据撞上它的概率约为 2^-128，是全表最可靠的签名。覆盖策略上另有两个细节：同一格式的新旧版本分开注册（GIF87a/89a、RAR4/5），避免长魔数匹配不到老文件；WAV/AVI/WebP 共用 RIFF 头但扩展名不同，靠先注册先匹配的顺序决定归属——这是签名雕刻的固有模糊性，结果里 `signature_name` 会告诉你当时判定成了什么。

### 4.1 产出表结构说明（carved_files 表）

`setDatabasePath` 指定库后建的表（`FileCarver.cpp:574-586`）：

| 列 | 取证含义 |
|----|---------|
| `path` | 恢复文件落盘路径 |
| `signature_name` / `extension` | 按哪个签名恢复、判定成的类型 |
| `source_offset` | **镜像内绝对字节偏移**——与文件名中的偏移一致，回镜像定位原始数据的依据 |
| `size` | 实际恢复字节数 |
| `validated` / `validation_message` | 结构验证结果（0/1）与信息（"Invalid JPEG header" 等） |
| `carved_at` | 雕刻时间（DEFAULT CURRENT_TIMESTAMP） |

这张表让"恢复出的证据"可以像其他工件一样被 SQL 查询（按类型、按验证状态、按偏移排序），而不是散在目录里只能靠文件名——但如第 3 节所述，当前生产入口都没接 `setDatabasePath`。

## 5. 解析机制走读

**链路一：整体扫描流程（`carve`，`FileCarver.cpp:481-563`）。** 打开镜像后先尝试在 `partitionOffset`（默认 0）处直接开文件系统；成功就对这一个文件系统雕刻。失败且偏移为 0 时，按"分区磁盘镜像"处理：

```cpp
// FileCarver.cpp:507-525（节选）
} else if (partitionOffset == 0) {
    // Partitioned disk image: offset 0 holds a volume system, not a
    // filesystem. Carve every openable partition into its own subdirectory.
    TSK_VS_INFO* vs = tsk_vs_open(img, 0, TSK_VS_TYPE_DETECT);
    if (vs) {
        for (TSK_PNUM_T i = 0; i < vs->part_count; i++) {
            const TSK_VS_PART_INFO* part = tsk_vs_part_get(vs, i);
            if (!part || !(part->flags & TSK_VS_PART_FLAG_ALLOC)) continue;
            TSK_OFF_T off = part->start * vs->block_size;
            TSK_FS_INFO* pfs = tsk_fs_open_img(img, off, TSK_FS_TYPE_DETECT);
            if (!pfs) continue;
            std::string subDir = outputDir + "/part" + std::to_string(i);
            uint64_t partitionBlocks = pfs->last_block - pfs->first_block + 1;
            recoveredTotal += carveFilesystem(pfs, subDir, statistics_.blocksScanned,
                                              statistics_.blocksScanned + partitionBlocks);
            tsk_fs_close(pfs);
        }
        tsk_vs_close(vs);
    }
}
```

做什么：偏移 0 开不出 FS 说明那里是分区表（卷系统）而不是文件系统，于是枚举每个 allocated 分区、按 `分区起始扇区 × 卷块大小` 换算字节偏移再开 FS，各自雕到 `part<N>/` 子目录。跳过未分配分区（扩展分区容器等）与打不开 FS 的分区（swap/LUKS）。进度设计的细节：`carveFilesystem` 的 `progressBase/progressTotal` 用"已扫块数 / 已扫+本分区块数"累计，多分区场景进度条也是连贯的。每个文件系统的雕刻由 `carveFilesystem` 驱动 `tsk_fs_block_walk(UNALLOC)`（第 472-475 行），回调里逐块处理。

**链路二：块内匹配与文件截取（`carving_block_walk_ctx`，`FileCarver.cpp:298-448`）。** 这是最核心的一段：

```cpp
// FileCarver.cpp:315-346（节选）
if (block->flags & TSK_FS_BLOCK_FLAG_UNALLOC) {
    ctx->stats->unallocatedBlocks++;
    const auto& signatures = ctx->carver->getSignatures();
    for (const auto& sig : signatures) {
        auto it = std::search(
            (uint8_t*)block->buf, (uint8_t*)block->buf + blockSize,
            sig.header.begin(), sig.header.end()
        );
        if (it != (uint8_t*)block->buf + blockSize) {
            // Found a header!
            size_t offsetInBlock = it - (uint8_t*)block->buf;
            uint64_t startByteAddr = block->addr * blockSize + offsetInBlock;
            const uint64_t fsBase = static_cast<uint64_t>(ctx->fs->offset);
            // Apply header offset adjustment
            if (sig.headerOffset != 0) {
                if (sig.headerOffset < 0 && static_cast<size_t>(-sig.headerOffset) > startByteAddr) {
                    continue;  // Can't go before start of image
                }
                startByteAddr += sig.headerOffset;
            }
            // Check if this region was already carved
            if (isRegionCarved(*ctx->carvedRegions,
                               fsBase + startByteAddr,
                               fsBase + startByteAddr + sig.maxSize)) {
                continue;
            }
            std::string filename = "carved_" + std::to_string(fsBase + startByteAddr) + "." + sig.extension;
```

做什么：对每个未分配块，用 `std::search`（朴素子串搜索）在块缓冲里逐个签名找头部魔数；命中后先把"块内偏移"换算成**文件系统内字节地址**（块号×块大小+偏移），再加上 `fs->offset`（分区基址）得到**镜像绝对地址**。为什么必须换算到绝对坐标：重叠表 `carvedRegions_` 与文件名都以镜像绝对偏移记录，两个分区的相对偏移相同也不会互相抑制（第 411-415 行注释特意说明）；也正因此产品名 `carved_<绝对偏移>.<扩展名>` 天然可溯源。`headerOffset` 为负时的越界保护（回拨不能越过镜像起点）在第 335-337 行。之后从该地址开始用 `tsk_img_read` 以 4KB 缓冲分块读出数据边写文件：有尾部签名的格式边读边搜尾部、命中即把尾部魔数一并写入后停止（第 379-391 行）；没有尾部的读到 `maxRead`（min(maxSize, 文件系统末尾可用字节)）上限。产物小于 100 字节直接删（防碎片噪声），成功后登记 `CarvedFileInfo`、更新统计，验证开关开着就跑 `validateCarvedFile`。

**链路三：结构验证（`validateCarvedFile`，`FileCarver.cpp:628-640` 及以下）。** 只对 jpg/png/pdf/zip 四类有验证器：

```cpp
// FileCarver.cpp:628-640
bool FileCarver::validateCarvedFile(const std::string& filepath, const CarvingSignature& sig, std::string& message) {
    if (sig.extension == "jpg" || sig.extension == "jpeg") {
        return validateJPEG(filepath, message);
    } else if (sig.extension == "png") {
        return validatePNG(filepath, message);
    } else if (sig.extension == "pdf") {
        return validatePDF(filepath, message);
    } else if (sig.extension == "zip") {
        return validateZIP(filepath, message);
    }
    message = "No content validator for this type";
    return false;
}
```

按扩展名分派到四个具体验证器（JPEG 查头尾魔数齐全、PNG/PDF/ZIP 查头部正确，`validateJPEG` 等在第 642 行起）。其余 25 种类型统一返回 "No content validator"——验证结果不影响文件保存（都保留），只影响 `validated` 字段与统计里的 valid/invalid 计数——把"判断真伪"留给调查者，工具只负责给线索排序。注意"未验证"与"验证失败"在 `validated=0` 上不可区分，要看 `validation_message` 才知道是哪种。

## 6. 与 LLM 的协作

没有。雕刻产物是原始文件，不经过 LLM。如果未来要让 LLM 分析恢复出的文件，路径是把 `carved_files/` 里的产物接入 FileClassifier/LLMAnalysisService 流程（目前未接）。

## 7. 与其他模块的协作 / 注意事项

- **依赖**：仅 TSK（块遍历与镜像读取），无其他外部库——这是全项目依赖最轻的分析器。
- **carved_files 表默认不落**：`setDatabasePath` 的两个生产入口（HTTP 第 537 行、CLI 第 697 行）都没调用它，表只在显式指定库路径时创建。审计日志（`add_audit_log(task_id, "FILE_CARVING", ...)`）记录了恢复数量与目录，算是当前的"账本"。
- **已知局限**：碎裂文件（fragmented）无法恢复——签名雕刻只能处理头部起连续存储的文件；无尾部签名的格式按上限截断，文件可能包含尾部垃圾；EXE（MZ）两字节头部误报多，依赖验证器缺失现状，看 `exe` 结果要谨慎。
- **与 ImageAnalyzer 的关系**：互补而非重叠。ImageAnalyzer 遍历目录项（含 UNALLOC 目录项），覆盖"文件系统还认得"的删除文件；FileCarver 扫未分配数据块，覆盖"目录项没了但数据还在"的部分。HTTP 流水线里 carving 在所有平台分析之后跑，失败只告警不失败任务（`TaskManagerAnalysis.cpp:552-555`）。
- **死代码**：`processUnallocatedBlock` 与 `extractFile` 两个成员函数是空壳占位（`FileCarver.cpp:730-736`），真实逻辑都在 `carving_block_walk_ctx` 回调里，读代码时不要被它们误导。

## 8. 如何验证与扩展

- 测试：`tests/UnitTest/test_file_carving.cpp` 覆盖签名定义（JPEG/PNG/PDF/ZIP 魔数与上限）、CarvedFileInfo/Statistics 结构；端到端验证可手工构造一个含已知文件的 DD 镜像、删除文件后跑 `--carve` 检查恢复结果与命名偏移是否对得上。
- 加新签名：`initializeSignatures()` 里追加一个 `CarvingSignature`（name/extension/header/footer/maxSize，可选 headerOffset/hasFixedSize），或运行时 `addSignature()` 注入；签名越独特（魔数越长）误报越低。
- 提升方向：把 `setDatabasePath` 接到任务库（让 HTTP 模式也落 carved_files 表）；为更多类型补验证器（ogg/flac 头部结构都很规整）；对 PST/SQLite 这类"内部有结构"的格式做二次解析而非只存原文件。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
