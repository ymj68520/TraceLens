# IosAnalyzer（src/analyzers/IosAnalyzer/）

> **一句话**：解析 iOS（iTunes/Finder）逻辑备份目录——`Manifest.plist`（设备身份与加密标志）+ `Manifest.db`（SQLite 索引）+ 按 SHA-1 前两字符分片的 shard 文件——把短信、通讯录、备忘录、日历、通话、Safari 历史写入 android.db 的共享表，加密备份明确拒绝而不是报空表。

## 1. 为什么有这个模块

iOS 备份在取证上与 Android 有一个本质差异：**它不是容器，而是一张索引 + 一堆内容寻址的分片**。备份目录里没有 `data/data/<包名>/databases/…` 这样的路径体系——每个文件的内容存在 `<备份根>/<fileID 前两位>/<fileID>` 的 shard 里，`Manifest.db` 的 `Files` 表把 `fileID` 映射回 `domain + relativePath`（例如 `HomeDomain/Library/SMS/sms.db`）（`IosBackupExtractor.h:4-13`）。因此"取一个文件"必须先查索引再拷分片，这正是 `IFileExtractor` 抽象的另一类后端。

三个源文件分工：

- `IosBackupExtractor`：`IFileExtractor` 后端，解析 Manifest.plist、建立逻辑路径→shard 的内存索引（`IosBackupExtractor.h:31-76`）。
- `BinaryPlist`：Apple 二进制 plist（`bplist00`）的最小读取器（`BinaryPlist.h:1-13`）。
- `IosArtifactParsers`：把六个 Apple 数据存储解析进 android.db 共享 schema（`IosArtifactParsers.h:28-59`）。

两条设计立场写在头注释里。**其一，schema 与 Android 有意共享**：下游所有读取方（工件卡片、覆盖状态、结果集、报告证据链）都按同一批表取数，iOS 任务因此不需要独立的查询层（`IosArtifactParsers.h:3-8`）。**其二，只处理明文备份**：加密备份在 `initialize()` 阶段就以 `IOS_BACKUP_ENCRYPTED` 失败，而不是静默产出全零的工件表（`IosArtifactParsers.h:9-12`、`IosBackupExtractor.cpp:169-174`）。

`BinaryPlist` 的存在理由也很具体：真实备份的 `Manifest.plist` 是二进制 plist 而非 XML；用 XML 正则去解析会"安静地"得到空设备身份和一个**假的**"未加密"判定（`BinaryPlist.h:4-8`）——这是取证工具最危险的一类错误，所以必须有真正的读取器。

## 2. 在系统中的位置

- **枚举与后端**：`AndroidSourceMode::IosBackup` 是十二个取值之一（`AndroidAnalyzerDeclarations.h:32-45`）；`AndroidAnalyzer::initialize()` 在该模式下构造 `IosBackupExtractor`（`AndroidAnalyzerCore.cpp:149-153`），失败原因经 `sourceError()` 透出（`:175-176`）。
- **分析分支**：`analyzeAndroidData()` 用 `dynamic_cast<IosBackupExtractor*>` 识别后端后走 `ios_artifacts::analyzeIosBackup()` 专用分支——注释明确说明 iOS 备份没有 Android provider 数据库，下方通用的 data/data 扫描将一无所获（`AndroidAnalyzerCore.cpp:249-271`），审计条目 `IOS_ANALYSIS_COMPLETE`。
- **HTTP 任务链路（当前唯一接线）**：`android_source = "ios-backup"` 的任务进入逻辑分析短路（`TaskManagerAnalysis.cpp:717-729`），mode 映射到 `AndroidSourceMode::IosBackup`（`:2037`）；建任务校验归类为"目录源"（`TaskCRUDRoutes.cpp:169, 180`）。
- **CLI 侧未接线（已知缺口）**：`--android-source ios-backup` 是合法值且自动置 `--android-analyze`（`CommandLineParser.cpp:82-83, 226-229`），但 `AnalysisOrchestrator` 的逻辑路由条件（`AnalysisOrchestrator.cpp:303-321`）与 mode 映射（`:916-924`）都不含它，CLI 会落回 TSK 磁盘镜像流水线。
- **不产出统一取数包**：`TaskManagerAnalysis.cpp:2079-2081` 的 .mep.db 构建白名单只有 miui/harmony/thunder 三个来源，iOS 走 android.db 直写。

## 3. 核心概念与设计

**备份识别**：目录同时存在 `Manifest.db` + `Manifest.plist` 即为备份，支持嵌套一或两层（解压产物常见）（`IosBackupExtractor.cpp:66-93`）；找不到时报 `IOS_BACKUP_MANIFEST_NOT_FOUND`（`:128-129`）。

**Manifest.plist（loadManifestPlist，`IosBackupExtractor.cpp:132-176`）**：`parsePlistFile` 同时接受二进制与 XML 编码（`BinaryPlist.cpp:344-360`）。设备身份在 `<Lockdown>` 字典下，键回退到根级查找以兼容把键摊平的变体（`:147-160`）：`ProductType/ProductVersion/BuildVersion/UniqueDeviceID/SerialNumber/IMEI`。`IsEncrypted=true` 时立即失败（`IOS_BACKUP_ENCRYPTED`，`:169-174`）；`Applications` 字典的大小是最便宜的"备份里有几个 App"的诚实计数（`:164-167`）。

**Manifest.db 索引（loadManifestIndex，`IosBackupExtractor.cpp:178-230`）**：以 `file:...?mode=ro` URI 只读打开（检材不可写，`:183-190`），`SELECT fileID, domain, relativePath FROM Files WHERE flags = 1` 只取文件（目录 flags≠1）。逻辑路径键是 `<domain>/<relativePath>`（反斜杠归一、去前导斜杠，`:59-64, 211`），值是 shard 元数据；shard 路径为 `<备份根>/<fileID 前两位>/<fileID>`，其存在性与大小在建索时核实（`:212-216`）。索引条目上限 200 万（`kMaxIndexEntries`，`:22`），防畸形索引撑爆内存。`Manifest.db` 的 SHA-256 在建索前一次性计算（`:179-180`），作为后续溯源行的容器哈希。

**Apple 纪元时间（toUnixSeconds，`IosArtifactParsers.cpp:512-526`）**：Core Data 时间是 2001-01-01 起算（偏移 978307200 秒，`:25-26`），且**纳秒/秒/Unix 秒三种量纲并存**——按数量级判别：`>1e14` 是 Apple 纳秒（除以 1e9 加偏移），`<1.2e9` 是 Apple 秒（加偏移），其余按 Unix 秒直通。`classifyTimestamp` 给出同一个判别的标签形式（`:521-526`）。

**BinaryPlist 读取器**：按 trailer 解析 offset 表与对象引用宽度，所有偏移访问都有界检查；数组/字典的引用表长度上限 1000 万并做 `payload + count*refSize ≤ 文件长` 校验，畸形检材读不出界（`BinaryPlist.cpp:155-195`）；支持 0xF 扩展长度（`:202-217`）、UTF-16LE 字符串含代理对转 UTF-8（`:219-251`）；XML 只做 `<key>/<string>` 对的最小回退（`:261-…`）。

## 4. 工作流程走读

**取分片（extractFileByPath，`IosBackupExtractor.cpp:254-287`）**：逻辑路径归一 → 查内存索引 → shard 文件必须存在 → `copy_file` 到输出路径 → 溯源行记录 `sourceContainer=备份根`、`containerSha256=Manifest.db 哈希`、`sourceMemberPath=fileID`、`normalizedAndroidPath=<domain>/<relativePath>`、成员级 SHA-256、`adapterType=ios-backup`、`adapterVersion=ios-backup-v1`（`:289-303`）。`shardPathFor`/`listDomain`/`domains` 三个只读查询供解析器与盘点用（`:244-251, 329-342`）。

**解析主流程（analyzeIosBackup，`IosArtifactParsers.cpp:528-595`）**：对六个固定来源逐个处理（`kSources`，`:32-41`）：

| kind | 逻辑路径 | 解析函数 | 落表 |
|---|---|---|---|
| sms | `HomeDomain/Library/SMS/sms.db` | parseSms（`:149-203`） | sms_messages |
| contacts | `HomeDomain/Library/AddressBook/AddressBook.sqlitedb` | parseContacts（`:207-249`） | contacts |
| notes | `HomeDomain/Library/Notes/notes.sqlite` | parseNotes（`:253-306`） | app_notes |
| calendar | `HomeDomain/Library/Calendar/Calendar.sqlitedb` | parseCalendar（`:310-348`） | app_notes（包名 com.apple.mobilecal） |
| call_logs | `HomeDomain/Library/CallHistoryDB/CallHistory.storedata` | parseCallHistory（`:352-400`） | call_logs |
| safari | `HomeDomain/Library/Safari/History.db` | parseSafariHistory（`:404-436`） | chrome_history |

每个工件独立容错：索引无此路径 → coverage `no_candidate_path`（"不是不存在于设备的证据"，`:535-541`）；拷贝失败 → `extract_failed`；解析出 0 行 → `staged_for_parser`，detail 写明"存储为空或 schema 变体未覆盖"——0 行不是解析失败，要说清是哪种情况让读者不把沉默当 bug（`:568-578`）。

四个值得注意的解析细节：

- **暂存与边车**：每个库先拷到安全临时根（`stage`，`:108-123`），再尝试同逻辑路径 + `-wal/-shm` 的边车——iOS 把活库的边车也当普通文件索引，所以要一并暂存给 SQLite 读（`stageSidecars`，`:125-137`）；用完清理（`cleanup`，`:139-145`）。
- **排序规则兜底**：Apple 工具链构建的库常声明宿主库没有注册的 BINARY collation，`installCollations` 注册一个 memcmp 替身让语句能 prepare（`:43-55`）。
- **短信方向与正文**：`is_from_me` 映射为 Android 语义的 type（1=收 2=发），对端号码来自 `handle` 表 join（ROWID→号码）；`text` 为空时回退 `attributedBody` blob 并把不可打印字节替换为空格（`parseSms`，`:149-198`）。
- **通话库的列名适配**：`CallHistory.storedata` 是 Core Data 存储（Z 前缀列），老版本地址列名不同，先用 `PRAGMA table_info` 解析一次可用列再拼 SQL（`parseCallHistory`，`:356-375`）。

**收尾三件事**（`:588-593`）：`recordInstalledApps` 按 `AppDomain-<bundle>` / `AppDomainPlugin-<bundle>` 域盘点——注释点明这是"备份捕获了什么"的诚实清单，不是"设备装了什么"；`installer=ios-backup` 标记来源（`:440-473`）。`recordManifest` 复用厂商中立的单行 `mobile_backup_manifest`（platform=`iOS`，device=`<机型> / iOS <版本>`，manifest_sha256=Manifest.db 哈希，adapter=`ios-backup-v1`），让 iOS 任务沿用既有清单展示（`:475-508`）。最后把提取器累积的 `usedSourceProvenance` 逐条入库（`:591-593`）。

## 5. 与其他模块的协作

| 对端 | 方向 | 交互点 |
|---|---|---|
| `AndroidAnalyzer`（`AndroidAnalyzerCore.cpp:149-153, 262-271`） | 上游 | 后端构造 + iOS 专用分析分支 |
| `AndroidAnalysisDatabase` | 下游 | 六工件表 + manifest + installed_packages + coverage + provenance（`IosArtifactParsers.cpp:528-595`） |
| `mobile_backup_schema::DDL` | 下游 | 共享 manifest 表结构（`MobileBackupSchema.h:15-26`） |
| `IFileExtractor` 契约 | 接口 | `extractFileByPath` / `findPathsByFilename`（`IosBackupExtractor.cpp:315-327`）/ `usedSourceProvenance`（`:305-313`） |
| OpenSSL（SHA-256） | 外部依赖 | Manifest 与成员哈希（`IosBackupExtractor.cpp:25-50`） |
| AndroidLLMAnalysisService | 无交互 | iOS 分支不调用 `analyzeWithLLM()`（`AndroidAnalyzerCore.cpp:262-271`），llm_* 列保持空 |

## 6. 注意事项与已知问题

- **CLI 未接线**：只有 HTTP 任务链路可用；CLI 接线点同 vivo（`AnalysisOrchestrator.cpp:303-321` 与 `:916-924` 两处补分支）。
- **加密备份无解**：需要用户口令的加密备份在初始化即失败（`IOS_BACKUP_ENCRYPTED`），没有解密路径；这也是文档与代码都强调的行为——**拒绝产出比伪造空表诚实**。
- **部分备份没有通话与 Safari**：iCloud 式部分备份常缺 `CallHistory.storedata` 与 `History.db`，coverage 行会如实报 `no_candidate_path`（`IosArtifactParsers.cpp:37-38` 的注释）。
- **日历落在 app_notes 而非独立表**：`parseCalendar` 用 `insertAppNote("com.apple.mobilecal", …)` 落表（`:336-339`），日历条目在 app_notes 里按包名区分；这是共享 schema 现状，不是独立 calendar 表。
- **attributedBody 有损**：短信正文回退读 `attributedBody` blob 时仅保留可打印字符与换行（`:177-179`），blob 中的二进制附件/表情结构不还原。
- **whatsapp/telegram 等跨平台 App 不在本模块**：iOS 侧的第三方 IM 库（如 `AppDomain-net.whatsapp…`）当前没有解析器，其分片只在索引与 installed_apps 盘点中可见。
- **toUnixSeconds 的量纲启发式**：`1.2e9` 与 `1e14` 两个分界是按真实数据范围取的经验值（`:512-526` 注释给出推理）；2023 年前后的时间戳判定正确，极端 future/past 值理论上可能误判，`classifyTimestamp` 可用于核查。

## 7. 如何验证与扩展

- 构建：仓库根 `CMakeLists.txt:408-410` 将三个源文件编入 `forensic_analyzer`。
- 测试入口：`grep -rl "IosBackup\|analyzeIosBackup" tests/`；合成备份可用最小夹具手拼——`Manifest.plist`（XML 形态即可，读取器兼容）+ 一个 `Manifest.db`（`Files` 表 flags=1 的行）+ 若干 shard 目录。
- 加新工件：`kSources`（`IosArtifactParsers.cpp:32-41`）加一条 `<kind, 逻辑路径>`，写一个 `parseXxx(dbPath, database)` 并在 `analyzeIosBackup` 的分派链（`:553-565`）挂上；时间值一律过 `toUnixSeconds`。
- 加 App 域盘点：`recordInstalledApps`（`:440-473`）目前只认 `AppDomain-` / `AppDomainPlugin-` 前缀，`AppDomainGroup-` 前缀在注释中被提及但未计入 bundle 盘点——接入时注意这个差异。

**最后更新**: 2026-11-10（按代码重写）
