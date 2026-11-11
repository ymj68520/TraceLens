# MeiyaBackupExtractor（src/analyzers/AndroidAnalyzer/Meiya*）

> **一句话**：解码美亚柏科取证工作站（MobileMaster FL-901）的案件导出——`.mf`/`.dmf`/`.amf` 等按 1024 字节周期 XOR 混淆的 SQLite 容器——掩码不硬编码、运行时从检材自身统计推导并用 SQLite `integrity_check` 客观验证，再经统一取数适配器翻译成 `.mep.db`。

## 1. 为什么有这个模块

美亚柏科的取证软件把中间结果存成一批自有容器：案件库 `.mf`、笔录/标记库 `MFCExcerpt.db`/`MFCMark.db`/`.bm`、每设备一个的规范化业务库 `.dmf`（表名 `TBL_PR_*`）、设备配置库 `config.db`、操作审计流水 `<设备>_RECORD_MFC.DB`、每应用的 `AppsAmf/*.amf`（`MeiyaBackupExtractor.h:4-13`）。这些文件不是真正的加密：内容是标准 SQLite，只是按 1024 字节周期与一段固定掩码逐字节 XOR；**同一案件内多个容器共用同一套掩码**（软件版本常量派生），因此掩码既与案件无关、也与设备无关（`MeiyaContainerCrypto.h:5-8`）。

模块的设计红线写在头注释里：**不硬编码任何厂商掩码**。掩码在运行时从检材自身推导（`MeiyaContainerCrypto.h:10-24`）：

1. 按 1024 字节切页；
2. 用两种统计假设各自生成候选掩码——`zero_page`（最高频页被当作 SQLite 的全零空闲页）与 `byte_mode`（逐字节取众数，多数页的多数偏移为 0）；
3. 用 SQLite 页 0 的已知头部 `SQLite format 3\0` 修正掩码前 16 字节（`MeiyaContainerCrypto.cpp:99-105`）；
4. 用 SQLite 自己执行 `PRAGMA integrity_check` 验证，通过者才算解出。

第 4 步是关键：统计假设在小文件上可能失效，而完整性校验是客观判据——任何候选不被 SQLite 接受就丢弃，**不存在"静默解错"**（`MeiyaContainerCrypto.h:19-22`）。同族文件合并取页则解决了"4 KB 的标记库单独没有足够页做统计"的问题（`MeiyaContainerCrypto.h:22-24`）。

## 2. 在系统中的位置

- **来源值**：`--android-source meiya`（`CommandLineParser.cpp:89-91`）；错误提示串（`:221-223`）漏列 `meiya`，但它是合法值——帮助文本在 `:132`，属于提示文案与实际校验集不同步的小瑕疵。
- **自动识别**：HTTP 侧，路径被 `MeiyaBackupExtractor::recognizes()` 识别为美亚案件时，即使来源字段为空也会自动归一为 `meiya` 并在任务元数据记 `device_brand=Meiya MobileMaster FL-901`（`TaskManagerAnalysis.cpp:584-604`）；CLI 侧同样支持来源为空时自动进入美亚分支（`AnalysisOrchestrator.cpp:318-320, 746-747`）。
- **专用执行分支**：meiya **不走 AndroidAnalyzer**——容器解码、统一包构建、统一分析由任务/编排层的独立分支全程负责（HTTP：`TaskManagerAnalysis.cpp:1836-1923`；CLI：`AnalysisOrchestrator.cpp:743-831`）。`AndroidSourceMode` 枚举里**没有** Meiya 取值，这是它与 vivo/ios 接线方式的结构性差异。
- **取数-分析分离的标准样板**：meiya 分支产出的就是统一取数包 `.mep.db`（`<baseName>_mobile_evidence.mep.db`），再由 `mobile_evidence::analyzePackage` 写 android.db（`<baseName>_files.db`）——它不经过"适配器直写 android.db"的旧路径，是三段式（解码→包→分析）最纯粹的实现。

## 3. 核心概念与设计

**容器族（family）**：按文件名后缀分六族——`record`（`*_record_mfc.db`）、`case`（`.mf`/`.bm`）、`device`（`.dmf`，以及与 `<设备>.dmf` 同目录共存的 `config.db`）、`appdb`（`.amf`）、`mark`（`MFC*` 开头的 `.db`）、`unknown`（`MeiyaContainerCrypto.cpp:107-139`）。后缀判定按"最具体优先"，否则 `_RECORD_MFC.DB` 与 `MFCExcerpt.db` 都会落进 `.db` 兜底（`:119-121` 的注释）。

**容器识别（looksLikeEncryptedContainer，`MeiyaContainerCrypto.cpp:143-161`）**：文件长度是 1024 的整数倍、首 16 字节不是明文 SQLite 头、且首字节不全相同（全零/全同的文件没有混淆信息量）。

**掩码求解（deriveMask，`MeiyaContainerCrypto.cpp:305-389`）**：

- 合并同族全部文件的页参与统计（小文件合并后才有代表性，`:310-329`）；
- 保留一个 ≤64 MiB（`kValidationImageLimit`，`:29`）的同族文件全文作验证样本；同族没有小文件时退化为最大文件的前 64 MiB，后续逐容器复核兜底（`:313-350`）；
- 生成 `zero_page`（至少两页相同才有统计意义，`:58-76`）与 `byte_mode`（`:78-97`）两个候选，各自用已知头部修正前缀；
- 逐候选解码验证样本跑 `integrity_check`，通过即采信并记录 `label/pagesUsed/validationEntries`（`DerivedKey`，`MeiyaContainerCrypto.h:40-45`）；全败则返回 false，error 带最后一个候选的失败原因（`:369-388`）。

**验证（validateSqlite，`MeiyaContainerCrypto.cpp:163-268`）**：镜像必须有 SQLite 头；截断的镜像（快速族判定只读前几页时）无法跑完整 `integrity_check`，改为校验页类型自洽（页首字节必须是 0x02/0x05/0x0a/0x0d 之一）作为"掩码看起来属于该族"的快速判据，**最终采信仍以整库校验为准**（`:176-208`）。完整校验用 `mkstemp` 落临时文件（退火到系统临时目录、不污染证据目录）后 `PRAGMA integrity_check` 必须返回 `ok`，再数 `sqlite_master` 行数（`:210-267`）。

**族间借掩码**：初始化按"大容器优先"顺序（device → unknown → appdb → record → mark → case）推导——大容器页数最多、统计最稳；其余族先复用已解出的掩码，失败再各自推导，仍失败则尝试借用他族掩码（前 16 页快速判据，标签记 `+borrowed_from_<族>`）（`MeiyaBackupExtractor.cpp:142-184, 202-222`）。

**逐容器整库复核（decryptFamily，`MeiyaBackupExtractor.cpp:224-290`）**：同族掩码在个别成员上仍可能不适用，而只看前几页会把"开头像"误判成"整库可读"，所以每个容器解出后**整个文件**再过一次 `validateSqlite`，不过者删临时副本、记 `failed` + 原因（`:260-280`）。解密输出为 `container-<n>.db`，落在 mkdtemp 创建、经"不落证据目录内"校验的私有临时根（`:20-44`），析构时整体删除（`:71-76`）。

**设备摘要（readDeviceSummary，`MeiyaBackupExtractor.cpp:292-321`)**：从解出的 `.dmf` 读 `TBL_PR_DEVICE_INFO` 一行（MANUFACTURER/MODEL/IMEI_ESN_MEID/MAC/BLUETOOTH_MAC/CHARACTERISTIC_DESC），尽力而为、失败不影响其他容器；设备目录名即序列号（V1824BA / GM1910 / PBEM00，`:51-54`）。

## 4. 工作流程走读（以 HTTP 任务为例，`TaskManagerAnalysis.cpp:1836-1923`）

1. **初始化（`MeiyaBackupExtractor::initialize`，`MeiyaBackupExtractor.cpp:112-200`）**：定位案件根（传设备目录或 `.mf` 文件路径时向上归一到案件根，`:118-125`）→ `enumerateContainers` 只向下两层枚举候选（案件根 → 设备目录 → 容器文件；再深是应用私有数据，不属于容器层，`MeiyaContainerCrypto.cpp:391-434`）→ 无候选即失败 → 建证据隔离临时根 → 按族分组推导掩码 → 逐族解密 → 全部容器都解不出时初始化失败（`no container could be decoded`，`:193-199`）。每个容器结果（`DecryptedContainer`，`MeiyaBackupExtractor.h:34-44`）带 `family/deviceSerial/encryptionLabel/schemaEntries/status/detail`，逐条进任务审计（`TaskManagerAnalysis.cpp:1853-1858`）。
2. **构建统一包（buildPackageFromMeiya，`MobileEvidenceMeiyaAdapter.cpp`）**：读各设备已解密 `.dmf`，把 `TBL_PR_*` 表翻译成 `mobile_evidence::Record`。映射表（`:101-193`）覆盖 13 张语义明确的表：`TBL_PR_SMS_INFO`→sms、`TBL_PR_CONTACT_INFO`→contact、`TBL_PR_DIALOG_INFO`→call_log、`TBL_PR_NOTES_INFO`→note、`TBL_PR_CALENDAR_INFO`→calendar_event、两张 WiFi 表→wifi_network、`TBL_PR_INSTALL_INFO`→installed_app、`TBL_PR_MEDIA_INFO`→media_file、`TBL_PR_FILE_DOCUMENT_INFO`→document_file、`TBL_PR_SYS_ACCOUNT_INFO`→account、`TBL_PR_SYS_BOOT_TIME_INFO`→system_log、`TBL_PR_BT_INFO`→generic。只打 `TBL_PR_*` 的理由：它是美亚自己的跨设备统一 schema，各应用 `*.amf` 私有表结构各异，作为后续扩展保留在文件清单里（`MobileEvidenceMeiyaAdapter.h:4-7`）。每行导出时**完整原始行进 `raw_json`**（blob 记字节数占位，`:56-80`），规范化投影进 `payload_json`——每个规范键给若干候选原始列按序取第一个非空值，因为美亚各版本表列名不完全一致（`:82-98`）。
3. **时间语义（parseMeiyaTime，`MobileEvidenceMeiyaAdapter.cpp:34-53`）**：美亚时间统一是 `YYYY-MM-DD HH:MM:SS` 本地时间、无时区标记——`timestamp_raw` 原样保留，规范化秒值按 UTC 解析**仅用于排序**，不虚构时区。
4. **落盘与分析**：`mobile_evidence::Writer` 单事务写 `<baseName>_mobile_evidence.mep.db`（失败码 `MEIYA_PACKAGE_WRITE_FAILED`）；`mobile_evidence::analyzePackage(packagePath, database, …)` 只读包写 android.db（HTTP 侧写 `<任务>/android.db`，CLI 写 `<baseName>_files.db`），每步失败都有独立错误码（`MEIYA_CONTAINER_DECODE_FAILED` / `MEIYA_PACKAGE_BUILD_FAILED` / `MEIYA_ANALYSIS_DB_INIT_FAILED` / `MEIYA_PACKAGE_ANALYSIS_FAILED`，`TaskManagerAnalysis.cpp:1846-1890`）。
5. **元数据留痕**：`meiya_containers_total` / `meiya_containers_decrypted` / `meiya_records` 与包路径 `mobile_evidence_package` 写进任务元数据（`:1892-1909`），审计摘要带 contacts/call_logs/sms 计数（`:1914-1921`）。

CLI 侧同一链路（`AnalysisOrchestrator.cpp:743-831`）额外提供 `--mobile-extract` 拆分：只解码建包不分析；`--mobile-package-out` 自定义包路径。

## 5. 与其他模块的协作

| 对端 | 方向 | 交互点 |
|---|---|---|
| `MeiyaContainerCrypto` | 内部 | 掩码推导/解码/验证（`MeiyaBackupExtractor.cpp:159, 214, 253, 273`） |
| `mobile_evidence::buildPackageFromMeiya` | 下游 | 容器 → 统一包（`AnalysisOrchestrator.cpp:779`、`TaskManagerAnalysis.cpp:1864`） |
| `mobile_evidence::Writer` / `Reader` | 下游 | `.mep.db` 落盘与只读回读 |
| `mobile_evidence::analyzePackage` → `AndroidAnalysisDatabase` | 下游 | 包 → android.db 标准表（contacts/call_logs/sms/notes/installed_apps/wifi 等，`MobileEvidenceAnalysis.cpp:257-294`） |
| 任务元数据/审计 | 下游 | `meiya_*` 元数据键与逐容器审计条目 |
| SQLite（integrity_check） | 外部依赖 | 掩码的客观判据 |

适配器选项（`MeiyaAdapterOptions`，`MobileEvidenceMeiyaAdapter.h:20-26`）：`inventoryApplicationDatabases`（未逐行解析的 `.amf` 等是否登记进文件清单，默认 true）、`maximumRowsPerTable`（单表导出行上限，默认 50 万，0 不限——防单表失控）。

## 6. 注意事项与已知问题

- **错误提示串漏列 meiya**：`CommandLineParser.cpp:221-223` 的报错文案没把 `meiya` 列进合法值清单，实际校验集（`:79-94`）包含它——用户传错值时会看到不完整的提示。
- **`enumerateContainers` 只向下两层**：更深层的应用私有数据不会被容器层看到（`MeiyaContainerCrypto.cpp:405-407` 的注释）， AppsAmf 若嵌套更深则漏枚举。
- **掩码推导需要足够页**：全部同族容器都过小（页数不足且无 ≤64 MiB 验证样本）时 `deriveMask` 失败（`no container large enough to validate the derived mask`，`:347-350`）；族内全部失败且无处借掩码时该族按 `failed` 登记。
- **厂商掩码轮换是设计预期内的风险**：掩码运行时推导意味着新版本软件换常量不需要改代码，但"同案件共享同一掩码"的前提若被打破（各族掩码独立），借掩码路径会失效——此时逐族独立推导仍可工作。
- **`unknown` 族**：既不是已知后缀又像混淆容器的文件会落入 `unknown` 族参与推导（`MeiyaContainerCrypto.cpp:136`），解不出只记失败，不会阻塞其它族。
- **本地时间无时区**：所有 `TBL_PR_*` 时间按 UTC 解析的秒值仅用于排序（见第 4 节），做绝对时间线还原时要意识到这层近似。

## 7. 如何验证与扩展

- 规范文档：`docs/specs/meiya-container-parsing.md`（现象、推导算法、容器族、样本实测与已知限制的权威描述；本文档不重复其全部内容）。
- 单元测试：`grep -rl "MeiyaContainerCrypto\|buildPackageFromMeiya" tests/`（掩码推导用合成容器：明文 SQLite 按 1024 字节 XOR 一段随机掩码即可造出）。
- 端到端：CLI `./build/forensic_analyzer <案件目录> --android-source meiya --db-dir <输出>`（可加 `--mobile-extract` 只出包）；HTTP 任务来源选 `meiya` 或留空依赖自动识别。
- 扩展新表：在 `mappings()`（`MobileEvidenceMeiyaAdapter.cpp:101-193`）加一条 `TableMapping`（表名/kind/关键列/时间列/规范投影）；语义尚未明确的表先经 coverage 声明"已盘点未映射"（`:100` 注释），给 `kind::*` 加新类别时按 `docs/specs/mobile-evidence-package.md` §3.5 的流程在 `MobileEvidenceAnalysis.cpp::analyzePackage` 补落表分支。

**最后更新**: 2026-11-10（按代码重写）
