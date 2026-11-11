# CLI 参考：forensic_analyzer 命令行手册

> 唯一来源：`src/CommandLineParser.cpp`（`printUsage` 与 `parse`），
> 辅以 `src/main.cpp`（模式路由与退出码）、`src/AnalysisOrchestrator.cpp`（各模式实现）、
> `src/analyzers/AndroidAnalyzer/AndroidAnalyzerCore.cpp`（`--android-source` 后端选择）。
> 所有 file:line 均相对仓库根 `/home/ymj68520/projects/Forensics/TraceLens`。

## 1. 总览

- 可执行文件：`build/forensic_analyzer`（run.sh:130 检查该路径）。
- 启动流程：`PathManager` 初始化 → 加载 `.env`（main.cpp:53-56）→ 审计日志 →
  参数解析（main.cpp:82）→ 依次判定模式。
- 模式路由顺序（main.cpp:102-123，先命中先执行）：

| 优先级 | 触发条件 | 入口函数 | 位置 |
|---|---|---|---|
| 1 | `http_port > 0`（`--http-server`） | `runHTTPServer` | main.cpp:102；AnalysisOrchestrator.cpp:703 |
| 2 | `--index` 或 `--search` | `runFullTextSearch` | main.cpp:106；AnalysisOrchestrator.cpp:634 |
| 3 | `--carve` | `runFileCarving` | main.cpp:110；AnalysisOrchestrator.cpp:690 |
| 4 | `--extract-all/--extract-file/--extract-ext` | `runExtraction` | main.cpp:114；AnalysisOrchestrator.cpp:567 |
| 5 | `--analyze-dlls-only` | `runDLLAnalysis` | main.cpp:118；AnalysisOrchestrator.cpp:710 |
| 6 | 其余（默认） | `runAnalysis` | main.cpp:123；AnalysisOrchestrator.cpp:149 |

`runAnalysis` 内部还有两个旁路（AnalysisOrchestrator.cpp:298-330）：
`--android-analyze` 且数据源属于逻辑源清单（dir / zip / miui-backup / thunder-backup|oppo-backup / tar / seven-zip / android-backup / filesystem-image / mobile-evidence / meiya，含雷电/美亚自动识别与 `--mobile-extract` / `--mobile-package` 运行）→ `runAndroidLogicalAnalysis`（:736）；
`--memory-analyze` → `runMemoryAnalysis`（:329，实现 :1035 起）。

## 2. 通用参数

| 参数 | 取值 | 默认 | 说明 / 代码路径 |
|---|---|---|---|
| `<image_path>`（位置参数） | 路径 | 无 | 解析于 CommandLineParser.cpp:326-327；分析模式要求存在（AnalysisOrchestrator.cpp:151-165），雕刻/内存模式仅要求非空 |
| `--help` / `-h` | 标志 | — | 打印用法并退出 0（main.cpp:90-93） |
| `--version` / `-v` | 标志 | — | 输出 "Forensic Image Analyzer v1.0 / Using The Sleuth Kit 4.14.0"，退出 0（main.cpp:95-99） |
| `--db-dir <path>` | 目录 | 空（当前目录） | 产物前缀目录，尾随 `/` 会被剥掉（AnalysisOrchestrator.cpp:137-147）；亦用于全文索引路径（:636-639） |
| `--overwrite` | 标志 | false | 解析于 CommandLineParser.cpp:200-201；**现在有消费者**：强制删除 CLI 阶段台账 `<stem>_stages.json`，下次运行全量重跑各阶段（AnalysisOrchestrator.cpp:353-356 注释明确"finally gives that flag the meaning its help text always implied"）；http_agent 启动 CLI 时也会传它（http_agent/command_executor.cpp） |
| `--xfs-mode <mode>` | `auto` / `native` / `pure` | `Auto` | CommandLineParser.cpp:202-210 → `ImageAnalyzer::setXFSMode`（AnalysisOrchestrator.cpp:208）。非法值仅打印错误，不置 `parse_error`，继续用原值 |
| `--http-server [port]` | 可选端口 | 8080 | CommandLineParser.cpp:211-215；无值或下一 token 以 `-` 开头则用 8080。端口经 `std::stoi` 解析，非数字会抛未捕获异常。进入 Crow HTTP 服务（AnalysisOrchestrator.cpp:703-708） |

取值型参数白名单（缺值即报 "Missing value"，CommandLineParser.cpp:67-77）：
`--database --extract-file --extract-ext --output-dir --db-dir --xfs-mode --android-source
--wechat-password --backup-password --backup-password-fd --report-path --dump-text-max-size
--vol-symbols-dir --dll-db --index --search --filter-profile --key-dir --key-password --carve-out
--mobile-package --mobile-package-out`。

## 3. 分析模式（默认路径）

四步主管线（AnalysisOrchestrator.cpp:204-341）：TSK 解析 → `_raw.db`（:215）→
FileFilter 过滤 → `_filtered.db`（:228-245，默认 profile `general_forensics`）→
FileClassifier → `_files.db`（:249）→ EventExtractor → `_events.db`（:331）。
`--db-dir ./out` 时产物为 `./out/<镜像stem>_raw.db|_filtered.db|_files.db|_events.db`。

| 参数 | 取值 | 默认 | 说明 / 代码路径 |
|---|---|---|---|
| `--android-analyze` | 标志 | false | TSK 管线内启动 AndroidAnalyzer（AndroidAnalyzer 场景步骤，AnalysisOrchestrator.cpp:517-535），产物并入 `_files.db`；与逻辑源组合则改走逻辑旁路（:303-322） |
| `--android-source <mode>` | 15 值：`tsk`（默认，磁盘镜像）/ `dir`（已提取 data/ 树）/ `zip` / `miui-backup`（MIUI .bak 目录）/ `harmony-backup`（已解密鸿蒙目录）/ `thunder-backup`（雷电快取 tar 或工程目录）/ `oppo-backup`（thunder-backup 旧别名）/ `tar` / `seven-zip` / `android-backup`（.ab）/ `filesystem-image`（userdata EXT4/F2FS RAW/E01）/ `mobile-evidence`（统一 .mep.db 包）/ `meiya`（美亚 MobileMaster FL-901 案件导出）/ `ios-backup`（iOS iTunes/Finder 逻辑备份）/ `vivo-backup`（vivo/iQOO PC 助手备份） | 空（等效 `tsk`） | 15 值硬校验（CommandLineParser.cpp:79-94,218-229；**注意**：parse_error 提示文案漏列 `meiya`，实际可接受）。`harmony-backup / mobile-evidence / meiya / ios-backup / vivo-backup` 五值**自动隐含 `--android-analyze`**。后端实例化见第 4 节 |
| `--mobile-extract` | 标志 | false | **仅取数阶段**：跑适配器写出统一手机取数包 `.mep.db`（不产 android.db），并隐含 `--android-analyze`（CommandLineParser.cpp:230-232）。仅 `miui-backup / harmony-backup / thunder-backup(含 oppo-backup)` 源进入 extraction-only 分支（AnalysisOrchestrator.cpp:955-957），输出路径取 `--mobile-package-out` 或默认包路径 |
| `--mobile-package <path>` | `.mep.db` 路径 | 空 | **仅分析阶段**：直接分析既有统一取数包，替代原始取材（源路径可已不存在，AnalysisOrchestrator.cpp:277-296 `packageOnly` 豁免镜像存在性检查）；隐含 `--android-analyze`。产物为 `<包stem去.mep.db>_files.db`（:851-875） |
| `--mobile-package-out <path>` | 路径 | 默认包路径 | `--mobile-extract` 的输出位置（CommandLineParser.cpp:236-238；使用于 AnalysisOrchestrator.cpp:784-786） |
| `--wechat-password <pass>` | 字符串 | 空 | SQLCipher 微信库解密口令，`AndroidAnalyzer::setWeChatPassword`（AnalysisOrchestrator.cpp:947-949） |
| `--backup-password <pass>` | 字符串 | 空 | **已弃用**（argv 可被 ps 看到）。仅提示告警并保留 encrypted ADB v5 密文（CommandLineParser.cpp:252-257） |
| `--backup-password-stdin` | 标志 | false | 交互时关回显读一行（AnalysisOrchestrator.cpp:39-107；逻辑分析中读取于 :926-943） |
| `--backup-password-fd <fd>` | 非负整数 | -1 | 从已打开 fd 读，上限 4096 字节，遇 `\n` 截断（CommandLineParser.cpp:242-251；AnalysisOrchestrator.cpp:109-129） |
| `--windows-analyze` | 标志 | false | WindowsFilesAnalyzer，产物并入 `_files.db`（AnalysisOrchestrator.cpp:295-310）；`--no-ai` 透传 `setSkipAI`（:304） |
| `--linux-analyze` | 标志 | false | LinuxFilesAnalyzer，产物并入 `_files.db`（AnalysisOrchestrator.cpp:312-327） |
| `--no-ai` | 标志 | false | 跳过 AI/LLM 分析（离线/无 key），`skip_ai`（CommandLineParser.cpp:262-263） |
| `--memory-analyze` | 标志 | false | 旁路至 `runMemoryAnalysis`，Volatility3，仅产 `<stem>_memory.db`（AnalysisOrchestrator.cpp:179-181,534-565） |
| `--vol-symbols-dir <path>` | 目录 | 空（vol3 默认搜索） | ISF 符号目录，`MemoryAnalyzer::setSymbolDir`（AnalysisOrchestrator.cpp:548-550） |
| `--filter-profile <name>` | profile 名 | `general_forensics` | 从 `config/filter_profiles/` 加载；现有 `general_forensics / telecom_fraud / virus_intrusion / data_breach`（CommandLineParser.cpp:305-306；AnalysisOrchestrator.cpp:224-245；过滤失败回退未过滤数据） |

## 4. `--android-source` 各值的后端实例化

file-access 后端在 `AndroidAnalyzer::initialize()` 按源模式实例化（AndroidAnalyzerCore.cpp:112-167）：

| 值 | `AndroidSourceMode` | 实例化的 file-access 后端 | 备注 |
|---|---|---|---|
| `tsk`（默认） | `TSK` | `FileExtractor(imagePath, dbManager->getDbPath())`，依赖已生成的 `_raw.db` | 需 DatabaseManager |
| `dir` | `LogicalDir` | `LogicalDirExtractor(imagePath)` | 自动探测 MIUI 备份并提升为 `miui-backup`（descript.xml + .bak，:87-94） |
| `zip` | `Zip` | `ZipArchiveExtractor(imagePath)` | — |
| `tar` | `Tar` | `TarArchiveExtractor(imagePath)` | — |
| `seven-zip` | `SevenZip` | `SevenZipArchiveExtractor(imagePath, backupPassword_)` | 接受备份口令 |
| `android-backup` | `AndroidBackup` | `AndroidBackupExtractor(imagePath, backupPassword_)` | 加密 ADB v5 仍 locked |
| `miui-backup` | `MiuiBackup` | `MiuiBackupExtractor(imagePath)`，可注入备份口令 | 解密到安全临时根 |
| `harmony-backup` | `HarmonyBackup` | `HarmonyBackupExtractor(imagePath)` | `LogicalDir/TSK` 模式下识别到鸿蒙目录亦自动提升（:81-82） |
| `thunder-backup` / `oppo-backup` | `ThunderForensicBackup` | `ThunderForensicBackupExtractor(imagePath)` | 任何模式识别到雷电快取都自动提升（:100-107） |
| `filesystem-image` | `FilesystemImage` | `FilesystemEvidenceFileExtractor(imagePath, expectedPartitionOffset_)` | 可注入源镜像 SHA-256 |
| `ios-backup` | `IosBackup` | `IosBackupExtractor(imagePath)` | 初始化失败经共享 `sourceError_` 上报 |
| `vivo-backup` | `VivoBackup` | `VivoBackupExtractor(imagePath, vivoIndexPath_)` | 索引桥脚本 `scripts/vivo_backup_index_cli.py`（HTTP 管线自动生成 `vivo_index.json`，TaskManagerAnalysis.cpp:1990-2023；CLI 未接线该桥） |
| `mobile-evidence` | —（不走 AndroidAnalyzer） | `mobile_evidence::analyzePackage`（AnalysisOrchestrator.cpp:880-911） | 读 `.mep.db`，产物 `<stem>_files.db` |
| `meiya` | — | 美亚专用容器层（XOR 混淆 SQLite，运行期推导掩码；`meiya::MeiyaBackupExtractor`） | 源为空时自动识别美亚导出（AnalysisOrchestrator.cpp:318-320,746-747） |

CLI 分派注意：

- **逻辑旁路清单**（AnalysisOrchestrator.cpp:303-321）包含 dir / zip / miui-backup / thunder-backup(oppo-backup) / tar / seven-zip / android-backup / filesystem-image / mobile-evidence / meiya，外加雷电/美亚包自动识别与 `--mobile-extract`、`--mobile-package` 运行；`runAndroidLogicalAnalysis` 内的模式映射（:916-924）覆盖 zip/miui/thunder/tar/seven-zip/android-backup/filesystem-image，其余归 `LogicalDir`（供 `dir` 使用）。
- **`harmony-backup` 不在逻辑旁路清单内**：其前置校验（:257-275 的 `INVALID_HARMONY_BACKUP` / 输出目录隔离检查）后走标准管线，`AndroidAnalyzer::initialize()` 内由 TSK/LogicalDir 自动提升为 Harmony 后端；HTTP 任务管线同理（Harmony 走 ANDROID 场景分支而非逻辑短路，TaskManagerAnalysis.cpp:1407-1436，并额外落 `<stem>_mobile_evidence.mep.db` 包）。
- **`ios-backup` / `vivo-backup` 目前仅在 HTTP 任务管线的逻辑分析路径接线**（TaskManagerAnalysis.cpp:2030-2042 的 `setSourceMode` 映射）；CLI 的逻辑旁路清单与模式映射均未包含这两个取值，CLI 下它们会随 `--android-analyze` 进入 TSK 管线且不会切到专用后端——CLI 使用这两个源暂不可用，属已知接线缺口。
- 逻辑模式产物统一写 `<stem>_files.db`（AnalysisOrchestrator.cpp:875），并跳过 TSK/事件/分类管线。

## 5. 解密（BitLocker / LUKS / VeraCrypt）

| 参数 | 取值 | 默认 | 说明 / 代码路径 |
|---|---|---|---|
| `--decrypt` | 标志 | false | 自动探测加密分区并解锁（CommandLineParser.cpp:307-308）；`ImageAnalyzer::setEnableDecryption/setKeyFileDir/setDecryptPassword`（AnalysisOrchestrator.cpp:209-213） |
| `--key-dir <path>` | 目录 | 镜像所在目录 | `.key` 文件搜索目录（AnalysisOrchestrator.cpp:211） |
| `--key-password-stdin` | 标志 | false | 无回显读口令；与弃用 argv 口令同时给出时 stdin 优先（AnalysisOrchestrator.cpp:184-190） |
| `--key-password <pass>` | 字符串 | 空 | **已弃用**，仅打印安全告警（CommandLineParser.cpp:313-317） |

密钥文件约定（printUsage:138-139）：`<imageBase>.part<N>.key`（分区级，如 `disk.part2.key`）
或 `<imageBase>.key`（整盘加密）。

## 6. 提取模式

入口 `runExtraction`（AnalysisOrchestrator.cpp:567-632）。要求 `--database`；
若传入 `_raw.db` 会自动换成同基名 `_files.db`（:576-579）；随后按
`.dd/.DD/.001/.e01/.E01/.raw/.RAW` 探测镜像文件（:592-597）。

| 参数 | 取值 | 默认 | 说明 |
|---|---|---|---|
| `--database <db_path>` | 路径 | 无（必需） | 提取所依据的库（CommandLineParser.cpp:183-184） |
| `--extract-file <pattern>` | 通配 `*`/`?` | — | 按文件名提取（CommandLineParser.cpp:185-187；执行 :613） |
| `--extract-ext <exts>` | 逗号分隔 | — | 按扩展名提取（CommandLineParser.cpp:188-190；执行 :615） |
| `--extract-all` | 标志 | — | 全量提取（CommandLineParser.cpp:191-192；执行 :617） |
| `--include-deleted`（别名 `--extract-deleted`） | 标志 | false | 含已删除文件；仅作用于 `extractAll`（CommandLineParser.cpp:193-195；AnalysisOrchestrator.cpp:617） |
| `--output-dir <path>` | 目录 | `extracted_files` | 输出目录（CommandLineParser.cpp:196-197；默认值 CommandLineParser.h:17） |

## 7. DLL 分析

| 参数 | 取值 | 默认 | 说明 / 代码路径 |
|---|---|---|---|
| `--analyze-dlls` | 标志 | false | 在分析管线第 4 步内附加 DLL 分析（AnalysisOrchestrator.cpp:344-377） |
| `--analyze-dlls-only` | 标志 | false | **独立模式**：跳过其余步骤（main.cpp:118-120 → runDLLAnalysis:710-752），同时隐含 `analyze_dlls=true`（CommandLineParser.cpp:290-292） |
| `--dll-db <path>` | 路径 | `<prefix><stem>_dll.db` | DLL 数据库路径（CommandLineParser.cpp:293-294；AnalysisOrchestrator.cpp:346、716-722） |
| `--dll-threshold <score>` | 整数 | 30 | **解析后无消费者**：`args.dll_threshold` 无人读取（CommandLineParser.cpp:295-296；默认值 CommandLineParser.h:25） |
| `--no-verify-signatures` | 标志 | 验证开启 | `verify_signatures=false` → `DLLAnalyzer::enableSignatureVerification(false)`（CommandLineParser.cpp:297-298；AnalysisOrchestrator.cpp:349、730） |

与 `--windows-analyze` 组合时会只读挂接 `_files.db` 做关联（AnalysisOrchestrator.cpp:354-366）。

## 8. 全文检索 / 雕刻

| 参数 | 取值 | 默认 | 说明 / 代码路径 |
|---|---|---|---|
| `--index <dir>` | 目录 | 无 | 递归索引文本文件，Xapian 索引默认 `search_index_xapian`（受 `--db-dir` 影响）（CommandLineParser.cpp:299-301；AnalysisOrchestrator.cpp:641-667） |
| `--search <query>` | 查询串 | 无 | 在已建索引上检索，输出 top 10（CommandLineParser.cpp:302-304；AnalysisOrchestrator.cpp:670-685） |
| `--carve` | 标志 | false | 雕刻模式，需位置参数镜像路径（CommandLineParser.cpp:318-319；AnalysisOrchestrator.cpp:690-701） |
| `--carve-out <dir>` | 目录 | `carved_files` | 雕刻输出目录（CommandLineParser.cpp:320-321；默认值 CommandLineParser.h:20） |

## 9. 报告与文本导出（分析模式内的可选步骤）

| 参数 | 取值 | 默认 | 说明 / 代码路径 |
|---|---|---|---|
| `--report` | 标志 | false | 生成人类可读 Markdown 报告，无需 AI（CommandLineParser.cpp:264-265；`ReportGenerator::writeMarkdown`，AnalysisOrchestrator.cpp:380-391） |
| `--report-path <path>` | 路径 | `<prefix><stem>_report.md` | 自定义报告路径，**给出即隐含 `--report`**（CommandLineParser.cpp:266-268） |
| `--dump-text` | 标志 | false | 经 python_service 将提取文件转 Markdown，需 `--linux/--windows-analyze`（printUsage:124-125；TextDumpExporter 流程 AnalysisOrchestrator.cpp:404-455） |
| `--dump-text-max-size <SIZE>` | `正整数+K/M/G/T` | 无限制 | 二进制软上限（如 `500M`、`2G`），**给出即隐含 `--dump-text`**；拒绝符号/小数/0/溢出（解析器 CommandLineParser.cpp:16-60、271-283）。产物：`<stem>_extracted_files/` 原件 + `<stem>_extracted_text/` Markdown（AnalysisOrchestrator.cpp:408-411） |

## 10. 退出码

| 退出码 | 含义 | 来源 |
|---|---|---|
| 0 | 成功 / `--help` / `--version` | main.cpp:92、98；各模式正常返回 |
| 1 | 运行期错误（镜像缺失、库缺失、初始化失败、异常） | 例：AnalysisOrchestrator.cpp:153-159、217、571、582、600、646、665、682、712、733；异常兜底 :460-463 等 |
| 2 | 命令行解析错误（缺值、非法 `--android-source`、非法 `--backup-password-fd`、非法 SIZE） | main.cpp:84-87；置 `parse_error` 于 CommandLineParser.cpp:177-180（缺值）、221-224（android-source）、248-250（fd）、272-280（SIZE） |

未定义其他退出码；HTTP 服务模式正常路径恒返回 0（AnalysisOrchestrator.cpp:703-708）。

## 11. `--help` 全文（printUsage 原样，CommandLineParser.cpp:98-169）

```text
Forensic Image Analyzer with File Extraction

Usage:
  Analysis mode:
    <program> <image_path> [options]

  Extraction mode:
    <program> --database <db_path> [extraction options]

Analysis options:
  --xfs-mode <mode>           XFS parsing mode (auto/native/pure)
  --db-dir <path>             Directory to store databases

DLL Analysis:
  --analyze-dlls              Enable DLL analysis
  --analyze-dlls-only         DLL analysis only (skip other steps)
  --dll-db <path>             DLL database path (default: <image>_dll.db)
  --dll-threshold <score>     Threat score threshold (default: 30)
  --no-verify-signatures      Disable signature verification (faster)

Extraction options:
  --extract-file <pattern>    Extract files by name (wildcards: *, ?)
  --extract-ext <extensions>  Extract by extension (comma-separated)
  --extract-all               Extract all files
  --output-dir <path>         Output directory
  --include-deleted           Include deleted files

HTTP Server options:
  --http-server [port]        Start HTTP server (default 8080)

Platform Analysis:
  --android-analyze           Analyze Android data
  --android-source <mode>     Android data source: tsk (default, disk image),
                              dir (extracted data/ tree), zip (Image.zip),
                              miui-backup (Xiaomi MIUI .bak folder), harmony-backup (decrypted Huawei folder),
                              thunder-backup (雷电手机快取 tar or project folder; any Android brand),
                              oppo-backup (legacy alias of thunder-backup),
                              tar, seven-zip, android-backup (.ab),
                              filesystem-image (userdata EXT4/F2FS RAW/E01),
                              mobile-evidence (unified .mep.db package),
                              meiya (MobileMaster FL-901 case export)
  --mobile-extract            Extraction stage only: write a unified
                              mobile evidence package (.mep.db); no android.db
  --mobile-package <path>     Analysis stage only: read an existing .mep.db
                              instead of the original acquisition
  --mobile-package-out <path> Output path for --mobile-extract
  --wechat-password <pass>    WeChat SQLCipher decryption password
  --backup-password-stdin     Read backup password from stdin (no echo when interactive)
  --backup-password-fd <fd>   Read backup password from an already-open file descriptor
  --backup-password <pass>    Deprecated: password in argv; rejected for 7z/Android Backup
  --windows-analyze           Analyze Windows artifacts
  --linux-analyze             Analyze Linux artifacts
  --no-ai                     Skip AI/LLM analysis (for offline/no-key environments)
  --report                    Generate human-readable Markdown report (no AI needed)
  --report-path <path>        Custom output path for the report
  --dump-text                 Convert extracted files to text via Python extractors
                              (requires python_service running; needs --linux/windows-analyze)
  --dump-text-max-size <SIZE> Limit dump originals + Markdown (e.g. 500M, 2G)
                              Binary K/M/G/T soft limit; implies --dump-text
  --memory-analyze            Analyze a RAM memory image (LiME/raw) via Volatility3
  --vol-symbols-dir <path>    ISF symbol dir for vol3 (else vol3 default search)

File Filter:
  --filter-profile <name>     Apply filter profile (e.g., telecom_fraud, virus_intrusion)
                              Profiles are loaded from config/filter_profiles/

Decryption (BitLocker / LUKS / VeraCrypt):
  --decrypt                   Auto-detect & decrypt encrypted partitions
  --key-dir <path>            Directory holding sibling .key files (default: image dir)
  --key-password-stdin        Read password from stdin (no echo when interactive)
  --key-password <pass>       Deprecated: password in argv (insecure; may be exposed)
  Password file convention: <imageBase>.part<N>.key (e.g. disk.part2.key)
                              or <imageBase>.key for whole-image encryption

Full-Text Search:
  --index <dir>               Index text files
  --search <query>            Search indexed database

File Carving:
  --carve                     Recover deleted files
  --carve-out <dir>           Carving output directory
```

> 注意：`--help` 文案中的 `--android-source` 列表**不含** `ios-backup` / `vivo-backup`，但解析器实际接受这两个值（CommandLineParser.cpp:79-94）——帮助文本滞后于实现。

## 12. 参数解析行为与注意事项

以下行为直接来自 `CommandLineParser::parse`（CommandLineParser.cpp:171-332）的实现细节：

- **取值参数防漏读**：所有取值型参数（第 2 节白名单）若位于 argv 末尾或下一 token
  以 `-` 开头，立即置 `parse_error` 并退出码 2（CommandLineParser.cpp:177-180）。
  因此 `--output-dir -o` 会被判为缺值而非把 `-o` 当目录名。
- **`--xfs-mode` 非法值不致命**：仅向 stderr 打印
  `Error: Invalid XFS mode ... Valid options: auto, native, pure`（:208-209），
  不置 `parse_error`，进程继续且模式保持默认 `Auto`——与 `--android-source`
  的硬失败（退出码 2）行为不一致。
- **`--http-server` 端口用 `std::stoi` 裸解析**（:214）：`--http-server abc` 会抛
  未捕获的 `std::invalid_argument` 导致非正常终止，而非退出码 2。`--dll-threshold`
  同样用 `std::stoi`（:296）。
- **未识别的 `-` 开头 token 被静默忽略**（无 else 分支报错）；不以 `-` 开头的
  未知位置参数会覆盖先前的 `image_path`（:326-327，后值胜出）。
- **`--include-deleted` 与 `--extract-deleted` 双拼写等价**（:193-195，注释明确
  "printUsage documents --include-deleted"）。
- **`--report-path` 隐含 `--report`**（:266-268）；**`--dump-text-max-size` 隐含
  `--dump-text`**（:282-283）；**`--analyze-dlls-only` 隐含 `--analyze-dlls`**（:290-292）；
  **`--android-source harmony-backup|mobile-evidence|meiya|ios-backup|vivo-backup`
  与 `--mobile-extract` / `--mobile-package` 均隐含 `--android-analyze`**（:226-235）。
- **`--android-source` 校验失败信息滞后**：parse_error 文案列出 14 个值（漏列实际可接受的
  `meiya`，CommandLineParser.cpp:221-224 对 :80-93 的 `validSources`）；`--help` 文案同样
  未列 `ios-backup / vivo-backup`——以第 3/4 节的实现清单为准。
- **`--backup-password`（argv）优先级最低**：stdin/fd 读取成功时覆盖 argv 值并打
  告警（AnalysisOrchestrator.cpp:496-507）；解密口令同理（:184-190）。
- **口令读取的回显控制**：stdin 模式仅在 tty 上关闭回显（`isatty`/`tcsetattr`，
  AnalysisOrchestrator.cpp:68-95）；fd 模式按原始字节读到 4096 上限并在首个
  `\n` 截断（:109-129）。
- **提取模式的镜像探测**：`runExtraction` 把 `_raw.db` 换算成 `_files.db`
  （:576-579），再从库名剥掉 `_files/_events/_raw` 后按扩展名表探测镜像
  （:587-597）；探测失败报 "Cannot find image file" 退出 1（:599-601）。
- **`--dump-text` 的服务依赖**：python_service 未启动时导出中止但主分析不受影响，
  并提示 `./scripts/start_python_service.sh`（AnalysisOrchestrator.cpp:448-452）。

## 13. 产物后缀速查（CLI 路径）

| 后缀 | 生成者 | 触发参数 | 位置 |
|---|---|---|---|
| `<stem>_raw.db` | ImageAnalyzer | 默认分析 | AnalysisOrchestrator.cpp:200 |
| `<stem>_filtered.db` | FileFilter | 默认（general_forensics）或 `--filter-profile` | :228 |
| `<stem>_files.db` | FileClassifier / 平台分析器 | 默认分析 / 逻辑 Android | :202、:485 |
| `<stem>_events.db` | EventExtractor | 默认分析 | :201 |
| `<stem>_dll.db` | DLLAnalyzer | `--analyze-dlls[-only]` | :346、:721 |
| `<stem>_memory.db` | MemoryAnalyzer | `--memory-analyze` | :543 |
| `<stem>_android.db` | AndroidAnalyzer（未指定输出库时的兜底名） | TSK 模式内 | AndroidAnalyzerCore.cpp:130 |
| `<stem>_stages.json` | CliStageLedger | 默认分析（阶段台账；`--overwrite` 强制删除以全量重跑） | AnalysisOrchestrator.cpp:356 |
| `<stem>_mobile_evidence.mep.db`（或 `--mobile-package-out`） | mobile_evidence::Writer | `--mobile-extract`（miui/harmony/thunder 源）；Harmony 任务在 HTTP 管线亦自动落包 | AnalysisOrchestrator.cpp:784-786、955-970 |
| `<stem>_report.md` | ReportGenerator | `--report` | :382 |
| `<stem>_extracted_files/` `_extracted_text/` | TextDumpExporter | `--dump-text` | :408-411 |
| `extracted_files/` | FileExtractor | 提取模式默认 | CommandLineParser.h:17 |
| `carved_files/` | FileCarver | 雕刻模式默认 | CommandLineParser.h:20 |
| `search_index_xapian` | XapianIndexer | `--index` | AnalysisOrchestrator.cpp:635 |

## 14. 常用组合示例

```bash
# 标准磁盘镜像分析（产物入 ./out）
./forensic_analyzer image.dd --db-dir ./out

# Windows 场景 + DLL 关联 + Markdown 报告，离线无 AI
./forensic_analyzer image.E01 --windows-analyze --analyze-dlls \
    --no-ai --report --report-path ./out/case.md

# 加密镜像 + 分区密钥目录 + stdin 口令
echo 'pass' | ./forensic_analyzer disk.dd --decrypt --key-dir ./keys --key-password-stdin

# Android MIUI 备份（逻辑路径，无 TSK / 无 _raw.db）
./forensic_analyzer ~/miui_backup/ --android-analyze --android-source miui-backup \
    --backup-password-stdin --db-dir ./out

# 手机取数-分析分离：先出统一包，再对包做分析（原始取材可下线）
./forensic_analyzer ~/miui_backup/ --android-source miui-backup --mobile-extract \
    --mobile-package-out ./out/case.mep.db
./forensic_analyzer --mobile-package ./out/case.mep.db --db-dir ./out

# RAM 镜像（Volatility3）
./forensic_analyzer lime.dump --memory-analyze --vol-symbols-dir ~/symbols

# 从既有 _raw.db 提取图片类文件
./forensic_analyzer --database ./out/image_raw.db --extract-ext jpg,png --output-dir ./photos

# 建索引并检索
./forensic_analyzer --index /mnt/evidence --db-dir ./idx
./forensic_analyzer --search "invoice" --db-dir ./idx

# 雕刻已删除文件
./forensic_analyzer image.dd --carve --carve-out ./carved

# 启动 HTTP 服务（默认 8080）
./forensic_analyzer --http-server
```

**最后更新**: 2026-11-10（增量核对分支 feature/model-routing：`--android-source` 扩到 15 值并补 `--mobile-extract` / `--mobile-package` / `--mobile-package-out`；第 4 节按 AndroidAnalyzerCore 现源码重写；`--overwrite` 台账语义、`_stages.json` / `.mep.db` 产物、parse_error 行号更新）
