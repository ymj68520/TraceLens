# ImageAnalyzer（src/analyzers/ImageAnalyzer/）

> **一句话**：把磁盘镜像（E01/DD/RAW）"读薄"——枚举分区、遍历每个分区里的每一个文件（包括已删除的），把文件系统元数据整体落成 `_raw.db` 的 `files` 和 `partitions` 两张表，供流水线里所有下游分析器当作"证据目录"使用。

## 1. 为什么有这个模块

磁盘取证的第一步从来不是"分析"，而是"看见"。一块 500GB 的取证镜像里有几百万个文件，调查者不可能逐个翻看；而且关键证据往往是已删除文件——目录项还在、数据块尚未被覆盖，普通挂载方式根本看不到它们。因此需要一个模块在镜像与后续分析之间做一次彻底的"翻译"：不解释文件内容，只把"镜子里有哪些文件、每个文件的四组时间戳（atime/mtime/ctime/crtime）、inode、属主、分配状态"忠实地编进数据库。这一层翻译的质量直接决定了后面所有平台分析器（Windows/Linux/Android）能找到多少证据——它们全部是拿着这个模块产出的路径清单去工作的。

这个模块的第二个存在理由是**打通 TSK 覆盖不到的死角**。The Sleuth Kit（TSK 4.14.0）是业界标准的镜像解析库，支持 NTFS/FAT/EXT2/3/4 等主流文件系统，但对 XFS 的支持在不同平台上表现不稳定，对 BitLocker/LUKS/VeraCrypt 加密卷则完全无能为力。TraceLens 为此在 TSK 之外自建了三条补充通道：纯用户态 XFS 解析器（`XFSHelper`）、Linux 原生 loop 挂载（`NativeFilesystemWalker`）、以及调用系统加密工具的外挂解密层（`DecryptionModule`）。理解这个"一主三辅"的结构，就理解了整个模块。

第三个理由是多分区完整性。真实磁盘几乎都是多分区的（EFI 分区 + 系统分区 + 恢复分区……）。历史上的实现曾在打开第一个可解析分区后就停止，静默丢掉其余分区上的全部证据（源码注释明确记录了这个教训，见 `ImageAnalyzer.cpp:137-139` 对 `scripts/FINDINGS_MULTI_PARTITION.md` 的引用）。现在的实现保证每个可遍历分区都会被走到，这也解释了为什么代码里到处是"per-partition"的循环结构。

## 2. 在流水线中的位置

ImageAnalyzer 是**所有 TSK 流水线的第一站**，两条入口都会跑到它：

- **HTTP 模式**（Web 界面发起任务）：`TaskManager::start_analysis` 的第 1 步就是 `ImageAnalyzer`（`src/network/HTTPServer/TaskManagerAnalysis.cpp:204-225`），产出写到任务独立目录 `data/tasks/<id>/<镜像名>_raw.db`。随后 SceneDetector 扫描这个 raw.db 自动判定平台场景，再依次跑各平台分析器。
- **CLI 模式**：`AnalysisOrchestrator::runAnalysis` 的 "[1/4] Analyzing image"（`src/AnalysisOrchestrator.cpp:206-219`），产出 `<镜像名>_raw.db`（可用 `--db-dir` 改目录）。

输入是一个镜像文件路径（E01/DD/RAW 均可，TSK 自动识别）；输出是 raw.db 中的两张表：

- `files`：每行一个文件/目录项。关键字段是 `inode/name/path/size/atime/mtime/ctime/crtime/type/is_deleted/is_allocated/uid/gid/permissions/partition_num`，建表语句见 `src/core/DatabaseManager/DatabaseManager.cpp:81-100`（其中 `llm_summary` 等 5 列是后来为 LLM 分析迁移加的，见同文件 `checkAndMigrate()`，第 53-73 行）。
- `partitions`：每个被成功打开文件系统的分区一行（`partition_num/start_offset/description/fs_type`），写入点在 `ImageAnalyzer.cpp:302-306`。

注意一个分工：ImageAnalyzer **只记元数据、不导出文件内容**。下游（FileClassifier、平台分析器、LLM）需要读某个文件的实际字节时，会拿着 raw.db 里的 inode/offset 回到镜像里去读（FileExtractor 就是干这个的）。

## 3. 证据来源与覆盖范围

它不去"找"特定证据，而是把整个镜像的文件系统结构无差别地铺开。但有几个覆盖维度值得了解：

| 维度 | 覆盖情况 |
|------|---------|
| 镜像格式 | E01/EWF、DD/RAW、AFF；先 `TSK_IMG_TYPE_DETECT` 自动探测，失败后强制按 RAW 再试一次（`ImageAnalyzer.cpp:104-111`） |
| 文件系统 | NTFS、FAT12/16/32、exFAT、EXT2/3/4、XFS（部分平台）、HFS、ISO9660——凡是 TSK `tsk_fs_open_img` 能打开的 |
| 已删除文件 | 走 `ALLOC \| UNALLOC` 合并遍历，未分配目录项也会入表（`TskFilesystemWalker.cpp:43-47`） |
| 加密分区 | BitLocker、LUKS、VeraCrypt（需 `--decrypt` + 密钥，见第 6 节） |
| 多分区 | 全部 allocated 分区逐一尝试；无分区表时退化为整盘单文件系统（`ImageAnalyzer.cpp:234-267`） |

对分区的处理有个值得注意的启发式：当 TSK 打不开某个分区、但其分区描述含 "Linux" 字样时，会在 Linux 平台上把它登记为 XFS 候选（`fsType = "xfs?"`），留给提取阶段的原生挂载兜底去试（`ImageAnalyzer.cpp:197-215`）。这就是为什么某些"打不开"的分区最终仍能出文件。

## 4. 解析机制走读

**链路一：常规分区如何变成 files 表的行。** `analyze()` 先 `openImage()`（tsk_img_open，记录镜像类型与大小并写审计日志），再 `openFileSystem()` 枚举分区。对每个 allocated 分区调用 `tsk_fs_open_img(imgInfo_, offset, TSK_FS_TYPE_DETECT)`；能打开的记录为一个 `PartitionEntry`（结构定义在 `ImageAnalyzer.h:26-35`，含分区号、字节偏移、文件系统类型、是否 XFS/是否加密）。随后 `extractToDatabase()`（`ImageAnalyzer.cpp:293-345`）对每个 entry 调 `extractPartition()`，后者为该分区实例化一个 `TskFilesystemWalker`（第 380 行）。walker 的核心是 `tsk_fs_dir_walk` 递归遍历（`TskFilesystemWalker.cpp:43-47`），在回调 `dirWalkCallback` 里把 TSK 的相对路径规范成以 `/` 开头的绝对路径——这一步很关键，下游分析器全靠 `path LIKE '/var/log/%'` 这种前缀匹配找文件（第 56-64 行注释）。`processFile` 把 TSK 的 meta 结构逐字段映射成 `FileRecord`：inode 取 `name->meta_addr`，四个时间戳取 `meta->atime/mtime/ctime/crtime`，类型映射成 REG/DIR/LNK/FIFO/SOCK 字符串，删除状态看 `name->flags & TSK_FS_NAME_FLAG_UNALLOC`（第 77-114 行）。最后由 `DatabaseManager::insertFileRecord` 落表。

**链路二：XFS 分区的三级降级。** `extractPartition()` 对 `isXfs` 分区按 `--xfs-mode` 分流（`ImageAnalyzer.cpp:360-376`）：`native`（仅 Linux）走 `extractWithNativeMount`，用 losetup + mount 只读挂载后用 POSIX 遍历（需要 root，`NativeFilesystemWalker` 初始化失败时的提示"requires root privileges"见 `ImageAnalyzer.cpp:763`）；`pure` 走 `extractWithXFS`，即 `XFSHelper`——一个自己读超级块（magic `XFSB`）、算 inode 偏移、解析目录项的纯用户态解析器（`XFSHelper.h`，覆盖 short-form/block/leaf/btree 四种目录格式，并提供 `readFileByInode` 供后续按 inode 读内容）；默认 `auto` 则先让 TSK 走，走空了或打不开再依次尝试 native、pure（第 385-395、429-439 行）。降级链的意义：同一份镜像在有 root 的 Linux 现场和受限环境里都能出结果，只是覆盖度不同。

**链路三：加密分区的解锁。** 当某分区文件系统打不开且开启了 `--decrypt` 时（`ImageAnalyzer.cpp:189-196`），`tryDecryptPartition()` 先用 `DecryptionModule::detect()` 读分区首扇区匹配魔数（`-FVE-FS-`→BitLocker、`LUKS\xba\xbe`→LUKS、`TRUE/VERA`→VeraCrypt，枚举见 `DecryptionModule.h:15-21`）。密码解析顺序：CLI 显式密码 → 同名 `.key` 文件（约定 `<镜像基名>.part<N>.key`，回退 `<镜像基名>.key/.txt/.password`，见 `KeyFileLoader.h:9-23`）。解密本体是调用外部工具：LUKS 用 cryptsetup 产出 `/dev/mapper/<name>` 设备节点，BitLocker 优先 bdemount、退 dislocker，VeraCrypt 用 veracrypt CLI（`DecryptionModule.h:44-54` 的类注释写明了这个分工）。解密成功后，`PartitionEntry.decryptedPath` 指向可读的明文卷，`extractDecryptedPartition()` 用一个**新的 TSK image 句柄**直接打开该路径来遍历（`ImageAnalyzer.cpp:544-548`）；TSK 仍解析不了（如某些 NTFS 变体）时再退到 native mount（第 595-631 行）。析构函数统一 `cleanup()`：卸载、删 device-mapper 节点、detach loop、删临时文件（第 45-51 行）。

## 5. 与 LLM 的协作

ImageAnalyzer 本身不碰 LLM。但它建的 `files` 表预留了 `llm_summary/llm_description/llm_keywords/llm_analyzed_at/llm_model_used` 五列（`DatabaseManager.cpp` 的 `checkAndMigrate()` 负责给旧库补列），流水线后面的 LLMAnalysisService 会把每文件的分析结论写回这里。可以把它理解为"LLM 的桌子先摆好，饭后面来吃"。

## 6. 与其他模块的协作 / 注意事项

- **消费方**：SceneDetector（从 raw.db 的路径探测平台）、FileFilter（按 profile 过滤出 `_filtered.db`）、EventExtractor（时间线）、FileClassifier（`_files.db`）、各平台分析器（通过 `DatabaseManager` 查询 raw.db 再回镜像读文件）。HTTP 模式下平台分析器读的是（可能被过滤后的）effectiveRawDb。
- **外部依赖**：TSK 4.14.0（必须）；cryptsetup/dislocker/bdemount/veracrypt（解密时按需，运行时 PATH 查找，缺失报错而非崩溃，见 `DecryptionModule.h:52-54`）；native XFS 挂载需要 root 和 Linux 内核 XFS 支持。另有 `DecryptionModuleStub.cpp` 提供无外部工具环境下的桩实现。
- **密码安全**：CLI 支持 `--key-password-stdin`（不回显读入，见 `AnalysisOrchestrator.cpp:39-107` 的 termios 实现），显式 `--key-password` 已标记 deprecated；HTTP 模式在分析启动后立刻 `clear_decryption_password`（`TaskManagerAnalysis.cpp:212-213`）。
- **BitLocker 特例**：密码解锁失败时可尝试 FVEK 直解——读 `<镜像>.part<N>.fvek`（32 字节，volatility3 的 bitlocker_fvek_scan 插件可从内存导出），由 `scripts/bitlocker_fvek_decrypt.py` 做 AES-XTS-128 解密（`ImageAnalyzer.cpp:473-488`，设计说明在 `DecryptionModule.h:129-144`）。这是为老版本 dislocker 不支持 AES-XTS-128 准备的旁路。
- **坑**：XFS 的 crtime 一律填 0（XFS 没有创建时间，`ImageAnalyzer.cpp:703`）；`partitions.length` 目前恒为 0（`insertPartitionInfo` 调用处第三个参数硬编码）；进度回调只有"取消检查"没有百分比，HTTP 端 IMAGE_ANALYSIS 阶段的进度条实际是阶段标记。

## 7. 如何验证与扩展

- 单元测试：`tests/UnitTest/test_image_analyzer_gtest.cpp` 覆盖 XFS 数据结构（超级块魔数、dinode、extent、目录项）；集成验证可直接用仓库根目录的 `test_image.img`（单分区无分区表场景）跑 CLI 全流程，检查 `_raw.db` 的 `files`/`partitions` 行数。
- 加新文件系统支持：优先看 TSK 是否原生支持（能打开就自动覆盖）；否则参照 `XFSHelper` 的模式写一个"从超级块到目录树"的解析器，在 `extractPartition()` 的降级链里挂上自己的分支，输出统一回调 `FileRecord`。
- 加新加密类型：在 `EncryptionType` 枚举（`DecryptionModule.h:15-21`）加值、在 `detect()` 加魔数、在 `decrypt()` 分派表加一个 `decryptXxx`，产出 `DecryptedPartition.accessiblePath` 即可被现有提取链复用。

**最后更新**: 2026-08-23（解释式重写）
