# ImageAnalyzer（src/analyzers/ImageAnalyzer/）

> **一句话**：把磁盘镜像（E01/DD/RAW）"读薄"——枚举分区、遍历每个分区里的每一个文件（包括已删除的），把文件系统元数据整体落成 `_raw.db` 的 `files` 和 `partitions` 两张表，供流水线里所有下游分析器当作"证据目录"使用。

## 1. 为什么有这个模块

磁盘取证的第一步从来不是"分析"，而是"看见"。一块 500GB 的取证镜像里有几百万个文件，调查者不可能逐个翻看；而且关键证据往往是已删除文件——目录项还在、数据块尚未被覆盖，普通挂载方式根本看不到它们。因此需要一个模块在镜像与后续分析之间做一次彻底的"翻译"：不解释文件内容，只把"镜子里有哪些文件、每个文件的四组时间戳（atime/mtime/ctime/crtime）、inode、属主、分配状态"忠实地编进数据库。这一层翻译的质量直接决定了后面所有平台分析器（Windows/Linux/Android）能找到多少证据——它们全部是拿着这个模块产出的路径清单去工作的。

这个模块的第二个存在理由是**打通 TSK 覆盖不到的死角**。The Sleuth Kit（TSK 4.14.0）是业界标准的镜像解析库，支持 NTFS/FAT/EXT2/3/4 等主流文件系统，但对 XFS 的支持在不同平台上表现不稳定，对 BitLocker/LUKS/VeraCrypt 加密卷则完全无能为力。TraceLens 为此在 TSK 之外自建了三条补充通道：纯用户态 XFS 解析器（`XFSHelper`）、Linux 原生 loop 挂载（`NativeFilesystemWalker`）、以及调用系统加密工具的外挂解密层（`DecryptionModule`）。理解这个"一主三辅"的结构，就理解了整个模块。

第三个理由是多分区完整性。真实磁盘几乎都是多分区的（EFI 分区 + 系统分区 + 恢复分区……）。历史上的实现曾在打开第一个可解析分区后就停止，静默丢掉其余分区上的全部证据（源码注释明确记录了这个教训，见 `ImageAnalyzer.cpp:308-309` 对 `scripts/FINDINGS_MULTI_PARTITION.md` 的引用）。现在的实现保证每个可遍历分区都会被走到，这也解释了为什么代码里到处是"per-partition"的循环结构。

## 2. 核心数据结构

**分区登记项**（`ImageAnalyzer.h:26-35`）：

```cpp
struct PartitionEntry {
    TSK_PNUM_T num = 0;        // TSK partition slot index
    uint64_t offset = 0;       // byte offset into the image
    std::string desc;          // human-readable description (e.g. "NTFS / exFAT (0x07)")
    std::string fsType;        // filesystem type name from TSK (e.g. "ntfs", "ext4")
    bool isXfs = false;        // true if TSK failed but partition looks like XFS
    bool isEncrypted = false;  // true if this partition was decrypted before extraction
    EncryptionType encType = EncryptionType::NONE;
    std::string decryptedPath; // path to the decrypted volume (device-mapper / file) when isEncrypted
};
```

头注释说明了它的设计动机：ImageAnalyzer 持有一组 `PartitionEntry`（每个可遍历分区一个），提取阶段遍历全部而不是停在第一个。三个标志位对应三条非默认路径：`isXfs` 走 XFS 降级链、`isEncrypted + decryptedPath` 走解密卷提取、`fsType = "xfs?"` 是"TSK 打不开但描述含 Linux"的候选标记。

**单文件记录 `FileRecord`**（`DatabaseManagerDataTypes.h:13-40`，全流水线通用的文件单元）：

```cpp
struct FileRecord {
    int64_t inode;
    std::string name, path;
    int64_t size;
    std::string extension, category;
    int64_t atime, mtime, ctime, crtime;   // 四组时间戳
    std::string type;                       // REG/DIR/LNK/FIFO/SOCK
    std::string md5;
    int isDeleted, isAllocated;
    std::string permissions;                // 八进制 mode 串
    int uid, gid;
    int partitionNum = 0;   // 消除多分区镜像里 inode 撞号（注释原文）
    std::string sceneType;  // Scene 分类字段（下游 SceneDetector 用）
    int scenePriority = 0, sceneRelevant = 0;
};
```

`partitionNum` 字段的存在本身就是一个教训的产物：多文件系统镜像里两个分区可以各有 inode=100 的文件，不带分区号无法区分。`sceneType/sceneRelevant` 是给下游场景检测预留的列，ImageAnalyzer 只填默认值。

**解密层结构**（`DecryptionModule.h:15-41`）：

```cpp
enum class EncryptionType {
    NONE,        ///< Not encrypted (or signature unrecognised)
    BITLOCKER,   ///< Microsoft BitLocker ("-FVE-FS-" signature)
    LUKS,        ///< Linux Unified Key Setup ("LUKS\xba\xbe" signature)
    VERACRYPT,   ///< VeraCrypt container ("TRUE" / "VERA" signature)
    UNKNOWN      ///< Looks encrypted but type cannot be determined
};
struct DecryptedPartition {
    EncryptionType encType = EncryptionType::NONE;
    std::string accessiblePath;  ///< 下游真正读取的路径：/dev/mapper/<name>（LUKS）
                                 ///< 或 dislocker/bdemount 产出的明文文件、或挂载点
    std::string mapperName;      // cryptsetup/dm name (for cleanup)
    std::string loopDevice;      // associated loop device (for cleanup)
    std::string tempFile;        // temp file created (for cleanup), if any
    std::string mountPoint;      // mount point created (for cleanup), if any
    bool mounted = false;
};
```

`DecryptedPartition` 的后四个字段全部为 cleanup 服务——析构函数按"卸载 → 删 mapper 节点 → detach loop → 删临时文件"的逆序释放，漏一步就会在分析机上留下设备节点或临时明文卷（后者是证据泄露面）。

### 2.1 核心接口清单

`ImageAnalyzer`（`ImageAnalyzer.h:41-149`）的公开 API：

| 方法 | 语义 | 调用方 | 失败行为 |
|------|------|--------|---------|
| `bool analyze()` | 开镜像 + 枚举分区，填 `partitions_` | HTTP `TaskManagerAnalysis.cpp:204-225` 第 1 步；CLI `AnalysisOrchestrator.cpp:206-219` | 打不开镜像/无任何可遍历分区返回 false |
| `bool extractToDatabase(dbPath)` | 建 raw.db、写 partitions 表、逐分区遍历落 files 表 | 两个入口在 analyze() 后调用 | 0 文件返回 false；单分区失败继续其他分区 |
| `void setXFSMode(XFSMode)` | native/pure/auto 三态 | CLI `--xfs-mode` | — |
| `void setEnableDecryption(bool)` | 开启加密分区自动解密 | `--decrypt` | — |
| `void setKeyFileDir(dir)` / `setDecryptPassword(p)` | 密钥文件目录 / 显式密码（绕过 .key 查找） | `--key-password(-stdin)` 解析结果 | — |
| `void setCancellationCallback(cb)` | 每分区遍历前检查取消 | HTTP 任务的 cancel | — |
| `const std::vector<PartitionEntry>& partitions()` | 取可遍历分区清单 | 下游/测试 | — |

## 3. 在流水线中的位置

ImageAnalyzer 是**所有 TSK 流水线的第一站**，两条入口都会跑到它：

- **HTTP 模式**（Web 界面发起任务）：`TaskManager::start_analysis` 的第 1 步就是 `ImageAnalyzer`（`src/network/HTTPServer/TaskManagerAnalysis.cpp:204-225`），产出写到任务独立目录 `data/tasks/<id>/<镜像名>_raw.db`。随后 SceneDetector 扫描这个 raw.db 自动判定平台场景，再依次跑各平台分析器。
- **CLI 模式**：`AnalysisOrchestrator::runAnalysis` 的 "[1/4] Analyzing image"（`src/AnalysisOrchestrator.cpp:206-219`），产出 `<镜像名>_raw.db`（可用 `--db-dir` 改目录）。

输入是一个镜像文件路径（E01/DD/RAW 均可，TSK 自动识别）；输出是 raw.db 中的两张表：

- `files`：每行一个文件/目录项。关键字段是 `inode/name/path/size/atime/mtime/ctime/crtime/type/is_deleted/is_allocated/uid/gid/permissions/partition_num`，建表语句见 `src/core/DatabaseManager/DatabaseManager.cpp:79-105`（其中 `llm_summary` 等 5 列是后来为 LLM 分析迁移加的，见同文件 `checkAndMigrate()`，第 53-73 行）。
- `partitions`：每个被成功打开文件系统的分区一行（`partition_num/start_offset/description/fs_type`），写入点在 `ImageAnalyzer.cpp:302-306`。

注意一个分工：ImageAnalyzer **只记元数据、不导出文件内容**。下游（FileClassifier、平台分析器、LLM）需要读某个文件的实际字节时，会拿着 raw.db 里的 inode/offset 回到镜像里去读（FileExtractor 就是干这个的）。

## 4. 证据来源与覆盖范围

它不去"找"特定证据，而是把整个镜像的文件系统结构无差别地铺开。但有几个覆盖维度值得了解：

| 维度 | 覆盖情况 |
|------|---------|
| 镜像格式 | E01/EWF、DD/RAW、AFF；先 `TSK_IMG_TYPE_DETECT` 自动探测，失败后强制按 RAW 再试一次（`ImageAnalyzer.cpp:104-111`） |
| 文件系统 | NTFS、FAT12/16/32、exFAT、EXT2/3/4、XFS（部分平台）、HFS、ISO9660——凡是 TSK `tsk_fs_open_img` 能打开的 |
| 已删除文件 | 走 `ALLOC \| UNALLOC` 合并遍历，未分配目录项也会入表（`TskFilesystemWalker.cpp:43-47`） |
| 加密分区 | BitLocker、LUKS、VeraCrypt（需 `--decrypt` + 密钥，见第 5 节） |
| 多分区 | 全部 allocated 分区逐一尝试；无分区表时退化为整盘单文件系统（`ImageAnalyzer.cpp:234-267`） |

对分区的处理有个值得注意的启发式：当 TSK 打不开某个分区、但其分区描述含 "Linux" 字样时，会在 Linux 平台上把它登记为 XFS 候选（`fsType = "xfs?"`），留给提取阶段的原生挂载兜底去试（`ImageAnalyzer.cpp:197-215`）。这就是为什么某些"打不开"的分区最终仍能出文件。

### 4.1 产出表结构说明（raw.db 两张表）

**`files`**（`DatabaseManager.cpp:79-105`）——每行一个目录项，取证含义最密的列：

| 列 | 取证含义 |
|----|---------|
| `inode` + `partition_num` | 文件的物理定位键：FileExtractor 靠"inode+分区号"回镜像读内容 |
| `atime/mtime/ctime/crtime` | 四组时间戳并列是取证库的标配——反取证常改 mtime 而漏 crtime，交叉比对即穿帮 |
| `is_deleted` / `is_allocated` | 两个独立维度：目录项未分配（删了）与 meta 已释放（可被覆盖），组合出"删除但数据可能还在"的判断 |
| `uid/gid/permissions` | 属主与八进制权限——找 setuid 文件、异常属主文件的原始素材 |
| `llm_summary/llm_description/llm_keywords/llm_analyzed_at/llm_model_used` | LLM 回写列（`checkAndMigrate()` 给旧库补） |
| `md5` | 预留哈希列（本模块不填，下游分类时算） |

**`partitions`**——`partition_num/start_offset/description/fs_type`：`start_offset` 是回镜像定位分区的字节数，`fs_type="xfs?"` 会原样入库（带问号的候选标记）。

## 5. 解析机制走读

**链路一：多分区遍历骨架（`extractToDatabase`，`ImageAnalyzer.cpp:293-345`）。**

```cpp
// ImageAnalyzer.cpp:301-323（节选）
// Record partition metadata into the partitions table (previously dead code).
for (const auto& part : partitions_) {
    dbManager_->insertPartitionInfo(static_cast<int>(part.num),
                                    static_cast<int64_t>(part.offset),
                                    0, part.desc, part.fsType);
}
// Walk EVERY walkable partition. Previously only the first openable partition
// was walked, silently discarding all others. See FINDINGS_MULTI_PARTITION.md.
int totalFiles = 0;
int okPartitions = 0;
for (const auto& part : partitions_) {
    if (isCancelled()) return false;
    std::cout << "\n=== Partition " << part.num << " (offset " << part.offset
              << ", " << part.fsType << ", " << part.desc << ") ===" << std::endl;
    if (extractPartition(part)) {
        okPartitions++;
    } else {
        std::cout << "  Partition " << part.num << " yielded no files." << std::endl;
    }
}
```

做什么：先把全部分区登记进 partitions 表，再逐分区提取。注释里两处历史标注值得读：`insertPartitionInfo` 这段曾是死代码（"previously dead code"）；主循环明确记录了旧行为"只走第一个可打开的分区、静默丢弃其余"并指向 `FINDINGS_MULTI_PARTITION.md`。单分区失败只计数不中断；总文件数最后从数据库 `getFileCount()` 反查而不是累加计数器——因为 XFS/native 降级路径各自独立插库，计数器会漏（第 327-329 行注释）。每个 allocated 分区调用 `tsk_fs_open_img(imgInfo_, offset, TSK_FS_TYPE_DETECT)`，能打开的记为 `PartitionEntry`；第一个成功打开的 FS 句柄被保留为"代表"（供 `detectOSType()` 与遗留降级路径用），后续分区先关闭句柄、提取时由 walker 重开。

**链路二：dir_walk 回调——TSK 元数据到 FileRecord 的翻译（`TskFilesystemWalker.cpp:38-114`）。**

```cpp
// TskFilesystemWalker.cpp:43-71（节选）
int result = tsk_fs_dir_walk(fsInfo_, fsInfo_->root_inum,
    static_cast<TSK_FS_DIR_WALK_FLAG_ENUM>(
        TSK_FS_DIR_WALK_FLAG_RECURSE | TSK_FS_DIR_WALK_FLAG_ALLOC |
        TSK_FS_DIR_WALK_FLAG_UNALLOC),
    dirWalkCallback, this);

TSK_WALK_RET_ENUM TskFilesystemWalker::dirWalkCallback(TSK_FS_FILE* fsFile, const char* path, void* ptr) {
    TskFilesystemWalker* walker = static_cast<TskFilesystemWalker*>(ptr);
    if (fsFile && fsFile->name) {
        // Construct full path. TSK's `path` is the directory path relative to
        // the filesystem root and may or may not begin with '/'. Normalise to an
        // absolute path (leading '/') so downstream consumers (Linux/Windows
        // analyzers querying `path LIKE '/var/log/%'`) can match consistently.
        std::string dir = path ? path : "";
        std::string fullPath = dir + fsFile->name->name;
        if (fullPath.empty() || fullPath[0] != '/') {
            fullPath = "/" + fullPath;
        }
        // Skip . and ..
        if (std::string(fsFile->name->name) == "." || std::string(fsFile->name->name) == "..") {
            return TSK_WALK_CONT;
        }
        walker->processFile(fsFile, fullPath);
    }
    return TSK_WALK_CONT;
}
```

做什么：一次 `tsk_fs_dir_walk` 递归走完整个目录树，`ALLOC|UNALLOC` 合并标志让已删除目录项也进回调——这是"看见已删除文件"的机制所在。路径规范化（补前导 `/`）这一步很关键，注释直接点明动机：下游分析器全靠 `path LIKE '/var/log/%'` 这种前缀匹配找文件，TSK 的相对路径风格不一致就会系统性漏检。`processFile`（第 77-114 行）把 TSK 的 meta 结构逐字段映射成 `FileRecord`：inode 取 `name->meta_addr`，四个时间戳取 `meta->atime/mtime/ctime/crtime`，类型映射成 REG/DIR/LNK/FIFO/SOCK 字符串，删除状态看 `name->flags & TSK_FS_NAME_FLAG_UNALLOC`，权限把 `meta->mode` 格式化成八进制串。边界：`fsFile->meta` 为空（名称项存在但元数据已不可读的删除文件）直接跳过——宁可少一条也不写半条错误记录。最后由 `DatabaseManager::insertFileRecord` 落表。

**链路三：XFS 分区的三级降级（`extractPartition`，`ImageAnalyzer.cpp:347-440`）。** 对 `isXfs` 分区按 `--xfs-mode` 分流：`native`（仅 Linux）走 `extractWithNativeMount`，用 losetup + mount 只读挂载后用 POSIX 遍历（需要 root，`NativeFilesystemWalker` 初始化失败时的提示"requires root privileges"见 `ImageAnalyzer.cpp:763`）；`pure` 走 `extractWithXFS`，即 `XFSHelper`——一个自己读超级块（magic `XFSB`）、算 inode 偏移、解析目录项的纯用户态解析器（`XFSHelper.h`，覆盖 short-form/block/leaf/btree 四种目录格式，并提供 `readFileByInode` 供后续按 inode 读内容）；默认 `auto` 则先让 TSK 走，走空了或打不开再依次尝试 native、pure（第 385-395、429-439 行）。注意第 348-350 行的小细节：降级辅助函数读的是成员变量 `partitionOffset_`，所以在每个分区开头把它指向当前分区——多分区镜像里 XFS 才不会雕错目标。XFS 的 crtime 一律填 0（XFS 没有创建时间，`ImageAnalyzer.cpp:703` 及 782 行两处注释）。降级链的意义：同一份镜像在有 root 的 Linux 现场和受限环境里都能出结果，只是覆盖度不同。

**链路四：加密分区的解锁（`tryDecryptPartition`，`ImageAnalyzer.cpp:443+`）。** 当某分区文件系统打不开且开启了 `--decrypt` 时（`ImageAnalyzer.cpp:189-196` 的分支，见上文链路一的分区循环），`DecryptionModule::detect()` 读分区首扇区匹配魔数（`-FVE-FS-`→BitLocker、`LUKS\xba\xbe`→LUKS、`TRUE/VERA`→VeraCrypt，枚举即第 2 节的 `EncryptionType`）。密码解析顺序：CLI 显式密码 → 同名 `.key` 文件（约定 `<镜像基名>.part<N>.key`，回退 `<镜像基名>.key/.txt/.password`，见 `KeyFileLoader.h:9-23`）。解密本体是调用外部工具（头文件类注释 `DecryptionModule.h:44-54` 写明分工）：LUKS 用 cryptsetup 产出 `/dev/mapper/<name>` 设备节点，BitLocker 优先 bdemount、退 dislocker，VeraCrypt 用 veracrypt CLI；子进程执行用无 shell 的 `runProcess`（argv 数组直传，避免路径注入）。解密成功后，`PartitionEntry.decryptedPath` 指向可读的明文卷，`extractDecryptedPartition()`（第 530 行起）用一个**新的 TSK image 句柄**直接打开该路径来遍历（第 544-548 行）；TSK 仍解析不了（如某些 NTFS 变体）时再退到 native mount（第 595-631 行）。析构函数统一 `cleanup()`：卸载、删 device-mapper 节点、detach loop、删临时文件（第 45-51 行）。还有一条 BitLocker 特例旁路：密码解锁失败时可尝试 FVEK 直解——读 `<镜像>.part<N>.fvek`（32 字节 = 16 字节 key + 16 字节 tweak，volatility3 的 bitlocker_fvek_scan 插件可从内存导出），由 `scripts/bitlocker_fvek_decrypt.py` 做 AES-XTS-128 解密（`ImageAnalyzer.cpp:473-488`，设计说明在 `DecryptionModule.h:129-147`）。这是为老版本 dislocker 不支持 AES-XTS-128 准备的旁路。

## 6. 与 LLM 的协作

ImageAnalyzer 本身不碰 LLM。但它建的 `files` 表预留了 `llm_summary/llm_description/llm_keywords/llm_analyzed_at/llm_model_used` 五列（`DatabaseManager.cpp` 的 `checkAndMigrate()` 负责给旧库补列），流水线后面的 LLMAnalysisService 会把每文件的分析结论写回这里。可以把它理解为"LLM 的桌子先摆好，饭后面来吃"。

## 7. 与其他模块的协作 / 注意事项

- **消费方**：SceneDetector（从 raw.db 的路径探测平台）、FileFilter（按 profile 过滤出 `_filtered.db`）、EventExtractor（时间线）、FileClassifier（`_files.db`）、各平台分析器（通过 `DatabaseManager` 查询 raw.db 再回镜像读文件）。HTTP 模式下平台分析器读的是（可能被过滤后的）effectiveRawDb。
- **外部依赖**：TSK 4.14.0（必须）；cryptsetup/dislocker/bdemount/veracrypt（解密时按需，运行时 PATH 查找，缺失报错而非崩溃，见 `DecryptionModule.h:52-54`）；native XFS 挂载需要 root 和 Linux 内核 XFS 支持。另有 `DecryptionModuleStub.cpp` 提供无外部工具环境下的桩实现。
- **密码安全**：CLI 支持 `--key-password-stdin`（不回显读入，见 `AnalysisOrchestrator.cpp:39-107` 的 termios 实现），显式 `--key-password` 已标记 deprecated；HTTP 模式在分析启动后立刻 `clear_decryption_password`（`TaskManagerAnalysis.cpp:212-213`）。
- **坑**：XFS 的 crtime 一律填 0（XFS 没有创建时间，`ImageAnalyzer.cpp:703`）；`partitions.length` 目前恒为 0（`insertPartitionInfo` 调用处第三个参数硬编码）；进度回调只有"取消检查"没有百分比，HTTP 端 IMAGE_ANALYSIS 阶段的进度条实际是阶段标记。

## 8. 如何验证与扩展

- 单元测试：`tests/UnitTest/test_image_analyzer_gtest.cpp` 覆盖 XFS 数据结构（超级块魔数、dinode、extent、目录项）；集成验证可直接用仓库根目录的 `test_image.img`（单分区无分区表场景）跑 CLI 全流程，检查 `_raw.db` 的 `files`/`partitions` 行数。
- 加新文件系统支持：优先看 TSK 是否原生支持（能打开就自动覆盖）；否则参照 `XFSHelper` 的模式写一个"从超级块到目录树"的解析器，在 `extractPartition()` 的降级链里挂上自己的分支，输出统一回调 `FileRecord`。
- 加新加密类型：在 `EncryptionType` 枚举（`DecryptionModule.h:15-21`）加值、在 `detect()` 加魔数、在 `decrypt()` 分派表加一个 `decryptXxx`，产出 `DecryptedPartition.accessiblePath` 即可被现有提取链复用。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
