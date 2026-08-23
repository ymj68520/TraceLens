# FileCarving（src/analyzers/FileCarving/FileCarver.{h,cpp}）

> **一句话**：文件雕刻——不管文件系统还认不认识这些数据，直接按魔数签名扫描镜像的**未分配块**，把残存的图片、文档、压缩包、数据库、可执行文件恢复到磁盘上的 `carved_files/` 目录。

## 1. 为什么有这个模块

"删除"从来不是消失。文件被删后，目录项释放、数据块标记为未分配，但字节还在原地，直到被新数据覆盖。文件系统层的方法（ImageAnalyzer 的 UNALLOC 遍历）只能找回目录项尚存的文件；当目录项本身被破坏（格式化、文件系统损坏、反取证工具擦目录）时，唯一的路是**放弃文件系统语义、直接在字节流里找文件开头的魔数**——JPEG 的 `FF D8 FF`、PDF 的 `%PDF`、ZIP 的 `PK..`——从头部开始向后读，直到遇到尾部签名或大小上限。这就是雕刻（carving），它是对文件系统解析的最后一道兜底。

这个模块选择雕刻的是**未分配空间**而非全盘：通过 TSK 的 `tsk_fs_block_walk` 只走 `TSK_FS_BLOCK_FLAG_UNALLOC` 的块（`FileCarver.cpp:472-475`）。这是个务实的取舍——已分配块里的文件理论上已被 ImageAnalyzer 收进 raw.db，再雕一遍是浪费；而未分配块正是"删除残留"最集中的地方。全盘裸雕（对付全盘加密或无文件系统镜像）留给未来扩展。

第三个设计立场是**验证降噪**。纯魔数匹配误报很多（随机字节撞上两字节 `MZ` 并不稀奇），所以雕刻后对常见格式做结构校验（JPEG 头尾齐全、PNG 头正确等），文件小于 100 字节直接丢弃（`FileCarver.cpp:413-416`），恢复结果带 `validated` 标记——调查者可以先看通过验证的，再看存疑的。

## 2. 在流水线中的位置

两种触发方式：

- **HTTP 模式**：任务勾选 `file_carving` 后，在 PLATFORM_ANALYSIS 之后作为第 7 步运行（`TaskManagerAnalysis.cpp:531-556`），输出到 `data/tasks/<id>/carved_files/`。它在总进度里占 3% 权重（`TaskManager.cpp:547-556` 的 phase_weights 表），支持取消（cancelCallback）与进度回调（按扫描块数汇报）。
- **CLI 模式**：`--carve` 独立子命令 `runFileCarving`（`AnalysisOrchestrator.cpp:690-701`），输出目录默认 `carved_files/`（可用 carve_output_dir 覆盖）。

输入：镜像路径（TSK 自动识别格式）+ 输出目录。输出有两路：**文件本体**落 `carved_files/`（多分区镜像按 `part<N>/` 子目录分放）；**记录**可选写入 SQLite 的 `carved_files` 表（`setDatabasePath()` 指定库后自动建表插入，schema 见 `FileCarver.cpp:565-590`）。注意：当前 HTTP 流水线和 CLI 子命令都**没有**调用 `setDatabasePath`，所以默认只有文件输出、没有表记录——这个库表接口是留给后续集成的（第 6 节详述）。

## 3. 证据来源与覆盖范围

29 个内置签名（`initializeSignatures()`，`FileCarver.cpp:34-283`），按类型分组：

| 类型 | 签名（数量） | 尾部签名/大小上限特点 |
|------|-------------|---------------------|
| 图片 | JPEG、PNG、GIF87a/89a、BMP、WebP、TIFF-LE/BE（8 个） | JPEG/PNG/GIF 有尾部魔数（精确截断）；BMP/WebP/TIFF 无（按上限截断） |
| 文档 | PDF（1 个） | 尾部 `%%EOF` |
| 压缩包 | ZIP、RAR5、RAR4、7z、gzip、bzip2、xz（7 个） | ZIP 有 EOCD 尾部；其余无尾部，上限 200-500MB |
| 音视频 | MP3×2（ID3/帧同步）、WAV、FLAC、OGG、MP4/MOV、AVI、MKV/WebM、FLV（9 个） | MP4 的 `ftyp` 在偏移 4，用 `headerOffset=-4` 回退到真文件头（第 214-220 行） |
| 数据库/可执行/邮件 | SQLite、ELF、PE(MZ)、Outlook PST（4 个） | SQLite 魔数 16 字节含结尾 NUL，误报率极低 |

覆盖策略上的两个细节：同一格式的新旧版本分开注册（GIF87a/89a、RAR4/5），避免长魔数匹配不到老文件；WAV/AVI/WebP 共用 RIFF 头但扩展名不同，靠先注册先匹配的顺序决定归属——这是签名雕刻的固有模糊性，结果里 `signature_name` 会告诉你当时判定成了什么。

## 4. 解析机制走读

**链路一：整体扫描流程（`carve`，`FileCarver.cpp:465-563`）。** 打开镜像后先尝试在 `partitionOffset`（默认 0）处直接开文件系统；成功就对这一个文件系统雕刻。失败且偏移为 0 时，按"分区磁盘镜像"处理：枚举卷系统里每个 allocated 分区，逐个打开文件系统、在输出目录的 `part<N>/` 子目录里独立雕刻（第 490-509 行）。进度按"已扫块数 + 本分区块数"累计，多分区场景进度条也是连贯的。每个文件系统的雕刻由 `carveFilesystem` 驱动 `tsk_fs_block_walk(UNALLOC)`，回调里逐块处理。

**链路二：块内匹配与文件截取（`carving_block_walk_ctx`，`FileCarver.cpp:298-451`）。** 对每个未分配块，用 `std::search` 在块缓冲里找每个签名的头部魔数；命中后计算**镜像绝对地址**（分区基址 + 块号×块大小 + 块内偏移），先查 `carvedRegions_` 重叠表避免同一区域被多个签名反复恢复（第 341-346 行；区域按镜像绝对坐标记录，两个分区相对偏移相同也不会互相抑制，见第 421-425 行注释）。然后从该地址开始用 `tsk_img_read` 分块读出数据边写文件：有尾部签名的格式边读边搜尾部、命中即停（第 379-391 行）；没有尾部的读到 `maxSize` 上限或文件系统末尾。MP4 这类头不在文件起点的签名靠 `headerOffset` 把起点回拨（第 334-339 行）。产物命名 `carved_<绝对偏移>.<扩展名>`——偏移进文件名，天然可溯源。

**链路三：结构验证（`validateCarvedFile`，`FileCarver.cpp:621-637` 及其下）。** 只对 jpg/png/pdf/zip 四类有验证器：JPEG 查头尾魔数齐全、PNG/PDF/ZIP 查头部正确。其余类型标记 "No content validator"。验证结果不影响文件保存（都保留），只影响 `validated` 字段与统计里的 valid/invalid 计数——把"判断真伪"留给调查者，工具只负责给线索排序。

## 5. 与 LLM 的协作

没有。雕刻产物是原始文件，不经过 LLM。如果未来要让 LLM 分析恢复出的文件，路径是把 `carved_files/` 里的产物接入 FileClassifier/LLMAnalysisService 流程（目前未接）。

## 6. 与其他模块的协作 / 注意事项

- **依赖**：仅 TSK（块遍历与镜像读取），无其他外部库——这是全项目依赖最轻的分析器。
- **carved_files 表默认不落**：`setDatabasePath` 的两个生产入口（HTTP 第 537 行、CLI 第 697 行）都没调用它，表只在显式指定库路径时创建。审计日志（`add_audit_log(task_id, "FILE_CARVING", ...)`）记录了恢复数量与目录，算是当前的"账本"。
- **已知局限**：碎裂文件（fragmented）无法恢复——签名雕刻只能处理头部起连续存储的文件；无尾部签名的格式按上限截断，文件可能包含尾部垃圾；EXE（MZ）两字节头部误报多，依赖验证器缺失现状，看 `exe` 结果要谨慎。
- **与 ImageAnalyzer 的关系**：互补而非重叠。ImageAnalyzer 遍历目录项（含 UNALLOC 目录项），覆盖"文件系统还认得"的删除文件；FileCarver 扫未分配数据块，覆盖"目录项没了但数据还在"的部分。HTTP 流水线里 carving 在所有平台分析之后跑，失败只告警不失败任务（`TaskManagerAnalysis.cpp:552-555`）。
- **死代码**：`processUnallocatedBlock` 与 `extractFile` 两个成员函数是空壳占位（`FileCarver.cpp:730-736`），真实逻辑都在 `carving_block_walk_ctx` 回调里，读代码时不要被它们误导。

## 7. 如何验证与扩展

- 测试：`tests/UnitTest/test_file_carving.cpp` 覆盖签名定义（JPEG/PNG/PDF/ZIP 魔数与上限）、CarvedFileInfo/Statistics 结构；端到端验证可手工构造一个含已知文件的 DD 镜像、删除文件后跑 `--carve` 检查恢复结果与命名偏移是否对得上。
- 加新签名：`initializeSignatures()` 里追加一个 `CarvingSignature`（name/extension/header/footer/maxSize，可选 headerOffset/hasFixedSize），或运行时 `addSignature()` 注入；签名越独特（魔数越长）误报越低。
- 提升方向：把 `setDatabasePath` 接到任务库（让 HTTP 模式也落 carved_files 表）；为更多类型补验证器（ogg/flac 头部结构都很规整）；对 PST/SQLite 这类"内部有结构"的格式做二次解析而非只存原文件。

**最后更新**: 2026-08-23（解释式重写）
