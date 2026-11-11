# VivoAnalyzer（src/analyzers/VivoAnalyzer/）

> **一句话**：解析 vivo/iQOO 手机"互传/PC 助手"导出的备份目录——一个 `.backup` JSON 头 + 一个 LevelDB `db/` 索引 + 按 SHA-1 命名的载荷文件——把备份清单事实落进 android.db 的 `mobile_backup_manifest` / `installed_packages` / `mobile_artifacts`，并对厂商 XOR 混淆的载荷做反演。

## 1. 为什么有这个模块

vivo 的 PC 端备份工具导出的不是 tar/zip 这类通用容器，而是一套自有布局：`.backup`（JSON 头，声明机型、备份时间、是否加密）+ `db/`（LevelDB 键值索引，`<类别>_<7 位序号>_<sha1>` 形式的键把内容哈希映射回原机文件名/大小/mtime）+ 每个条目一个以其 SHA-1 命名的载荷文件（`VivoBackupExtractor.h:4-9`）。三个源文件各管一件事：

- `VivoBackupExtractor`：识别与读取这份布局，实现 `IFileExtractor` 后端接口，把"逻辑路径 → 载荷字节"翻译出来（`VivoBackupExtractor.h:36-54`）。
- `VivoDeobfuscator`：反演部分备份对载荷施加的 8 字节循环 XOR 混淆（`VivoDeobfuscator.h:31-48`）。
- `VivoArtifactParsers`：把索引事实持久化进 android.db 共享 schema（`VivoArtifactParsers.h:29-41`）。

模块头注释交代了两个关键取舍。**其一，不引入 LevelDB 依赖**：从 C++ 读 LevelDB 需要新的第三方库，而 Python 预检已经用成熟库解析过索引，所以提取器只消费预检规范化产物 `index.json`，C++ 侧只做它必须自己做的事——把逻辑路径解析成载荷文件并拷贝字节（`VivoBackupExtractor.h:11-15`）。**其二，两条诚实规则**：被标记混淆的载荷即使拷出来了也要如实报告不可读，绝不当作数据库塞给 SQLite 解析器；载荷文件缺失要报告"缺失"，而不是当成"空工件"（`VivoBackupExtractor.h:17-21`）。

## 2. 在系统中的位置

- **枚举与后端**：`AndroidSourceMode::VivoBackup` 是 `AndroidSourceMode` 十二个取值之一（`AndroidAnalyzerDeclarations.h:32-45`）；`AndroidAnalyzer::initialize()` 在该模式下构造 `VivoBackupExtractor(imagePath, vivoIndexPath)`（`AndroidAnalyzerCore.cpp:154-156`），索引 JSON 路径经 `setVivoIndexPath()` 注入（`AndroidAnalyzerDeclarations.h:105-106`）。
- **分析分支**：`analyzeAndroidData()` 用 `dynamic_cast<VivoBackupExtractor*>` 识别该后端后走专用分支 `vivo_artifacts::analyzeVivoBackup()`，结束即返回——不走后续的 Android provider 数据库扫描（`AndroidAnalyzerCore.cpp:252-261`），审计条目为 `VIVO_ANALYSIS_COMPLETE`。
- **HTTP 任务链路（当前唯一接线）**：`android_source = "vivo-backup"` 的任务进入逻辑分析短路（`TaskManagerAnalysis.cpp:717-729`），并在分析前通过固定 argv 的 Python 桥把 LevelDB 索引一次性物化为 `vivo_index.json`（`TaskManagerAnalysis.cpp:1983-2023`）：脚本路径 `<项目根>/scripts/vivo_backup_index_cli.py`、解释器 `python_service/.venv/bin/python`，任一缺失即失败码 `VIVO_INDEX_BRIDGE_MISSING` / `VIVO_INDEX_BRIDGE_FAILED`。桥只是数据变换，不做分析。
- **CLI 侧未接线（已知缺口）**：`--android-source vivo-backup` 是合法值且会自动置 `--android-analyze`（`CommandLineParser.cpp:84-85, 226-229`），但 `AnalysisOrchestrator` 的逻辑源路由条件（`AnalysisOrchestrator.cpp:303-321`）与 `AndroidSourceMode` 映射（`AnalysisOrchestrator.cpp:916-924`）都不含 `vivo-backup`，命令行会落回 TSK 磁盘镜像流水线。要在 CLI 用 vivo 备份，需先在路由条件与 mode 映射各补一个分支。
- **任务校验**：HTTP 建任务时 `vivo-backup` 归类为"目录源"（`TaskCRUDRoutes.cpp:169, 180`）。

## 3. 核心概念与设计

**备份识别（recognizes）**：目录里存在 `<root>/.backup` 文件 + `<root>/db/` 目录即为 vivo 备份；支持备份目录嵌套在包装目录下一到两层（解压产物常见）（`VivoBackupExtractor.cpp:78-99`）。`resolveBackupRoot()` 按同样的三级向下策略解析出真实备份根并做 `weakly_canonical`（`VivoBackupExtractor.cpp:101-136`），失败错误码：`VIVO_BACKUP_NOT_A_DIRECTORY` / `VIVO_BACKUP_HEADER_NOT_FOUND`。

**JSON 头（loadHeader）**：读 `model`（机型）、`createTime`（epoch 毫秒）、`backupPackageVer`（备份组件版本）；**头里 `encrypted=true` 直接判失败**（`VIVO_BACKUP_ENCRYPTED`）——加密备份没有密钥材料，模块不假装能解（`VivoBackupExtractor.cpp:138-160`）。

**规范化索引（loadIndex）**：读 `index.json`（提取器构造时未指定索引路径则在备份根找，`VivoBackupExtractor.cpp:162-164`）。`obfuscated` 布尔字段声明载荷是否 XOR 混淆；`items` 数组每条含 `category/hash/original_path/size/mtime_ms`，`hash` 非空才收，`original_path` 反斜杠归一成 `/` 并去前导斜杠后建 `byOriginalPath_` 哈希表（`VivoBackupExtractor.cpp:71-76, 162-195`）；`applications` 数组每条是一个 App 包（`package/app_name/version_name/file_name/size/hash`），去重后得 `applicationCount_`（`VivoBackupExtractor.cpp:197-214`）。索引错误码：`VIVO_BACKUP_INDEX_MISSING` / `VIVO_BACKUP_INDEX_MALFORMED`。

**XOR 混淆与反演（VivoDeobfuscator）**：固定 8 字节循环密钥 `7f a3 c8 e1 5b 9d 2e f4`（`VivoDeobfuscator.h:33-35`），变换按**绝对文件偏移**对齐——`bytes[i] ^= key[(offset + i) % 8]`，所以解"切片"时必须传对起始偏移（`VivoDeobfuscator.cpp:22-26`）。头注释记录了密钥的来历与定性：这是**混淆不是加密**——没有 per-file nonce、没有 KDF、没有完整性标签；密钥靠已知明文恢复（独立 JPEG 以 `FF D8 FF E1` 开头，APP1 长度与 `Exif\0\0` 标记补齐其余字节），并用整个索引范围内"解码后头部落在已知 magic"做了交叉验证（`VivoDeobfuscator.h:11-19`）。`hasKnownMagic`/`describeDecodedType` 识别 16 族容器 magic（JPEG/PNG/ZIP/RAR/7z/GIF/PDF/OLE/FLAC/RIFF/MP3/Ogg/PE/CHM/MP4-ftyp/JSON 或 XML 文本）（`VivoDeobfuscator.cpp:35-86`）。

**可解性探测（evidence-based，而非信任标志）**：`initialize()` 在 `obfuscated=true` 时最多取 8 个载荷的头部解码，`≥半数` 命中已知 magic 才把 `deobfuscationSucceeded_` 置真——厂商换密钥时，"obfuscated"标志仍在但内置密钥不再适用，此时 `payloadReadable()` 返回 false，后续按不可读登记（`VivoBackupExtractor.cpp:224-241`，`VivoBackupExtractor.h:62-63`）。

## 4. 工作流程走读

**取一个文件（extractFileByPath，`VivoBackupExtractor.cpp:251-299`）**：逻辑路径归一 → `byOriginalPath_` 查条目 → 载荷文件 `<备份根>/<hash>` 必须真实存在（缺失返回 false，即"缺失报告为缺失"）→ `copy_file` 到输出路径 → 若 `obfuscated_` 则**在提取出的副本上**做原地 XOR 反演，检材本身从不改写（`:280-293` 的注释明确了这条边界）→ 记录来源溯源（`recordProvenance`，`:301-313`）：容器为备份根、成员路径是 SHA-1、成员哈希是提取后副本的 SHA-256（OpenSSL 分块计算，`:25-50`）、`adapterType=vivo-backup`、`adapterVersion=vivo-backup-v1`。只有**真正被取用过的条目**才进 `usedSourceProvenance()`——"成功暂存的字节"而非"所有发现的成员"（`IFileExtractor.h:92-95` 的接口契约）。

**落库（analyzeVivoBackup，`VivoArtifactParsers.cpp:108-197`）**：四步，全在一个事务里（`:123-126` 的注释解释：5000 条级别的备份若每行一个隐式事务会逐条 fsync，任务看起来像挂死；单事务让它落在亚秒级）。

1. **清单单行**：`mobile_backup_manifest` 固定 `id=1`，platform 恒 `Android`，device 取机型（空则字面 `vivo`），并写备份版本/时间/应用数/适配器版本 `vivo-backup-v1`（`VivoArtifactParsers.cpp:82-104`）。`mobile_backup_schema::DDL` 先行创建共享表（`:116-119`）。
2. **每应用一行 installed_packages**：`code_path` 与 `installer` 恒为 `vivo-backup`——这两个列的值本身就是"来源是 vivo 备份清单而非 packages.xml"的标记（`:128-144`）。
3. **每个索引条目一行 mobile_artifacts**：kind 由类别映射（`categoryKind`，`:19-29`：album→media_photo、video→media_video、music→media_audio、record→recording、document→document、zip_file→archive、settings_file→app_settings、app→app_package、其余→backup_file），`record_json` 携带类别/原路径/哈希/大小/mtime 与 **`payload_state`**（`readable`=未混淆 / `deobfuscated`=混淆且内置密钥可解 / `obfuscated`=混淆且密钥不适用）（`:146-164`）；`source_key` 是合法 JSON（`{"category":…,"hash":…}`），因为下游 `android_artifact_reader` 会直接 `json.loads` 它作为行主键（`:165-168`）。
4. **每类别一行 coverage**：未混淆或可解记 `PARSED`，混淆且不可解说 `locked_or_unsupported`，detail 里写明"载荷字节以未知密钥 XOR 混淆"（`:180-193`）。

头注释把底线写在明处：**它绝不从"类别计数"往 `sms_messages`/`contacts` 写行——计数不是证据**（`VivoArtifactParsers.h:14-17`）。当前索引里没有可解析的业务库载荷（短信/通话以混淆二进制形式存在），所以那些标准表在 vivo 任务里就是空，这是诚实登记而不是遗漏。

## 5. 与其他模块的协作

| 对端 | 方向 | 交互点 |
|---|---|---|
| `AndroidAnalyzer`（`AndroidAnalyzerCore.cpp:154-156, 252-261`） | 上游 | 后端构造 + vivo 专用分析分支 |
| Python 桥 `scripts/vivo_backup_index_cli.py`（经 `TaskManagerAnalysis.cpp:1983-2023`） | 上游 | LevelDB 索引 → `index.json` 物化 |
| `AndroidAnalysisDatabase` | 下游 | manifest/installed_packages/mobile_artifacts/coverage 写入（`VivoArtifactParsers.cpp:82-193`） |
| `mobile_backup_schema::DDL` | 下游 | 共享表结构（`MobileBackupSchema.h:15-26`） |
| `IFileExtractor` 契约 | 接口 | `extractFileByPath` / `findPathsByFilename`（`:325-337`）/ `usedSourceProvenance`（`:315-323`） |
| OpenSSL（SHA-256） | 外部依赖 | 成员哈希（`VivoBackupExtractor.cpp:25-50`） |
| nlohmann/json | 外部依赖 | `.backup` 头与 `index.json` 解析 |

vivo 路径**不产出统一取数包**（.mep.db）：`TaskManagerAnalysis.cpp:2079-2081` 的包构建白名单只有 miui-backup/harmony-backup/thunder-backup 三个来源。

## 6. 注意事项与已知问题

- **CLI 未接线**：`--android-source vivo-backup` 在命令行会落入 TSK 流水线（见第 2 节），只有 HTTP 任务链路可用；CLI 接线需改 `AnalysisOrchestrator.cpp:303-321` 与 `:916-924` 两处。
- **依赖 Python 环境**：HTTP 侧运行 vivo 任务要求仓库内存在 `scripts/vivo_backup_index_cli.py` 与 `python_service/.venv/bin/python`，缺任一直接失败（`VIVO_INDEX_BRIDGE_MISSING`）；项目根的定位靠从可执行目录向上找 `scripts/`（最多 4 层，`TaskManagerAnalysis.cpp:1992-1997`）。
- **加密备份无解**：`.backup` 头 `encrypted=true` 时初始化即失败（`VIVO_BACKUP_ENCRYPTED`），没有密钥推导路径。
- **混淆密钥是观察结论不是保证**：密钥来自已知明文分析且经样本验证，但 `initialize()` 的探针保证了厂商换钥时**降级为如实登记**（`payload_state=obfuscated`、coverage `locked_or_unsupported`），不会产出伪造的解码结果。
- **无 LLM 段**：vivo 分支结束即返回，不调 `analyzeWithLLM()`（`AndroidAnalyzerCore.cpp:252-261`），mobile_artifacts 的 `llm_*` 列在 vivo 任务里保持空值。
- **载荷清单≠业务记录**：索引证明"备份里有什么文件"，不证明"载荷可读"；本模块的产出定位是**备份内容清单与可读性判定**，短信/通话/联系人业务表要等载荷侧解析接入（当前未实现）。

## 7. 如何验证与扩展

- 构建：Ios/Vivo 两组源文件在仓库根 `CMakeLists.txt:408-413` 编入 `forensic_analyzer`。
- 测试入口：`grep -rl "VivoBackup\|analyzeVivoBackup" tests/`（合成备份目录 + `index.json` 夹具可直接手拼：一个 `.backup` JSON、空的 `db/` 目录、若干以 SHA-1 命名的载荷文件、`index.json` 列出 items/applications 即可驱动 `VivoBackupExtractor`）。
- 接 CLI：在 `AnalysisOrchestrator.cpp:303-321` 的路由条件与 `:916-924` 的 mode 映射各加 `"vivo-backup"` 分支，并在 `runAndroidLogicalAnalysis` 里为 vivo 物化索引（CLI 侧目前没有 Python 桥调用）。
- 接新类别：`categoryKind`（`VivoArtifactParsers.cpp:19-29`）加映射即可让新类别落入 mobile_artifacts 的语义 kind；若载荷侧出现可解析业务库，解析函数应走 `extractAndParseDB` 同款"暂存→分派→清理"模式并写入标准表，而不是从计数推行。

**最后更新**: 2026-11-10（按代码重写）
