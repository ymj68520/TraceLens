# AndroidAnalyzer（src/analyzers/AndroidAnalyzer/）

> **一句话**：从 Android 证据源（物理镜像、逻辑提取目录、zip/tar/7z/.ab 归档、MIUI 离线备份、鸿蒙已解密备份、雷电手机快取、EXT4/F2FS 逻辑分区镜像、iOS 备份、vivo 备份、统一取数包）里解析出"人"的痕迹——短信、通讯录、通话记录、微信/QQ/WhatsApp/Telegram 聊天、Chrome 历史、WiFi、已装应用、系统日志——统一写入 android.db 的近 40 张工件表。

## 1. 为什么有这个模块

手机取证要回答的问题和电脑很不一样。调查者关心的往往不是文件系统本身，而是**通信与行为记录**：谁给谁发了什么、什么时候装的什么 App、设备连过哪些 WiFi、崩溃日志里泄露了什么。这些证据散落在几十个固定的路径里——`/data/data/<包名>/databases/` 下的 SQLite、`/data/system/packages.xml`、`shared_prefs` 的 XML——每个都有自己的格式和坑（加密、WAL 边车、私有二进制格式）。AndroidAnalyzer 的价值就是把这套"路径 + 格式 + 解析"的知识固化下来，让一条命令就把一个 Android 证据源读完。

这个模块有两个显著的设计立场值得先知道。**第一是"证据源无关"**：真实案件里 Android 证据经常不是物理镜像，而是国产定制 ROM 的离线备份（MIUI）、厂商提取工程（雷电）、已解密的鸿蒙备份、iOS/vivo 备份或 EXT4/F2FS 逻辑分区镜像。为此模块定义了 `IFileExtractor` 抽象（`IFileExtractor.h:62-96`），十二个后端——TSK、目录、zip、MIUI、鸿蒙、雷电、tar、7z、Android Backup、EXT4/F2FS 逻辑分区（`FilesystemEvidenceSource`）、iOS、vivo——在解析器眼中完全透明，所有取文件都走 `fileExtractor_->extractFileByPath()`（`AndroidAnalyzerCore.cpp:109-111` 的注释明确说明了这一点）。部分品牌备份（鸿蒙/雷电/MIUI）的解析规则已迁移到统一取数包 `mobile_evidence` 层（见 [MobileEvidencePackage](MobileEvidencePackage.md)），本模块对它们仍是"提取器宿主 + 分析编排"。**第二是"诚实的证据观"**：对无法解析的私有格式（QQNT 的 MMKV、加密的 EnMicroMsg.db），宁可如实登记为"识别到但未解码的证据"，也不编造解码结果——`WechatArtifactParsers.h` 和 `QqntArtifactParsers.h` 的头注释把这条原则写得很清楚；每类证据的提取结果都会在 `android_source_coverage` 留状态行（`AndroidAnalyzerCore.cpp:303-315` 的 `stageKnownDatabase`）。对取证工具来说，这比"看起来功能多"更重要。

第三个背景是**微信加密库的现实**。微信的 EnMicroMsg.db 是 SQLCipher 加密的，密钥是 `MD5(IMEI + UIN)` 的前 7 位。模块内置了完整的解密链路（参数化密码 → 自动推导 → SQLCipher 版本矩阵重试），这是 Android 证据里价值最高也最难拿的一块。

## 2. 核心数据结构

**证据源抽象、MIUI 备份模型与 SQLCipher 解密参数**——三组核心结构如下。

**证据源模式与后端接口**（`AndroidAnalyzerDeclarations.h:32-45`、`IFileExtractor.h:62-96`）：

```cpp
enum class AndroidSourceMode {
    TSK,                   // 块级镜像 + _raw.db（老路径）
    LogicalDir,            // 已解包的 data/ 目录树
    Zip,                   // 打成 Image.zip 的逻辑提取（libzip）
    MiuiBackup,            // MIUI 离线备份目录
    HarmonyBackup,         // 已解密华为鸿蒙备份目录
    ThunderForensicBackup, // 雷电手机快取 tar / 工程目录（OPPO/vivo/一加等）
    Tar, SevenZip, AndroidBackup,   // tar / .7z / Android .ab 归档
    FilesystemImage,       // userdata EXT4/F2FS RAW/E01 逻辑分区镜像
    IosBackup,             // iOS iTunes/Finder 逻辑备份（Manifest.db 路由）
    VivoBackup             // vivo/iQOO PC 助手备份（.backup + LevelDB 索引）
};

class IFileExtractor {
public:
    virtual bool initialize() = 0;
    virtual bool extractFileByPath(const std::string& imageRelPath,
                                   const std::string& outPath) = 0;
    virtual std::vector<std::string> findPathsByFilename(
        const std::string& filename, std::size_t limit = 200) const;
    virtual std::vector<AndroidSourceProvenance> usedSourceProvenance() const;
};
```

`AndroidSourceMode` 的字符串取值分两个入口校验：CLI 校验集是 `CommandLineParser.cpp` 的 `isValidAndroidSource`（:79-94），共 15 个字符串（12 个模式 + `oppo-backup` 别名 + `mobile-evidence`/`meiya` 两个不走本类 switch 的特殊值）；HTTP 任务创建（`TaskCRUDRoutes.cpp:168-169` 的 `supportedSources`）另接受 `android-container` 与 `aliyun-image`，共 17 值；`IFileExtractor` 的契约是"给镜像内相对路径（容忍前导 `/`），把完整字节写到本地 outPath"，另有按文件名的有界发现（`findPathsByFilename`，微信库定位靠它，`AndroidAnalyzerCore.cpp:390`）与"实际取用过的成员"溯源（`usedSourceProvenance`，`IFileExtractor.h:84-95`）。换后端不动任何解析代码。

**MIUI 备份模型**（`MiuiBackupManifest.h:9-26`、`AndroidBackupHeader.h:5-12`、`TarIndex.h:10-18`）。三组结构串成 MIUI 模式的完整数据通路：`BackupMeta` 来自 descript.xml（清单），`AndroidBackupHeader` 解析每个 `.bak` 的私有头部（tar 载荷偏移与压缩标志），`TarIndex` 在该偏移上建成员名→`TarEntry` 的哈希表：
```cpp
struct BackupPackage {           // descript.xml 里的一个 <item>
    std::string packageName;
    std::string bakFile;         // UTF-8 文件名，如 "短信设置(com.android.mms).bak"
    int bakType = 0;             // 备份类型（应用数据/SD 卡等）
    int error = 0;
    int state = 0;               // 备份时记录的成功/失败状态
    uint64_t pkgSize = 0;
    uint64_t sdSize = 0;
};
struct BackupMeta {
    std::string device;          // 机型代号，如 "cepheus"
    std::string miuiVersion;     // 如 "V12.5.6.0.RFACNXM"
    uint64_t date = 0;           // epoch 毫秒
    std::vector<BackupPackage> packages;
};
struct AndroidBackupHeader {     // 每个 .bak 的私有头部
    int compression = 0;         // 0=裸 tar，1=zlib 压缩
    BackupEncryption encryption; // None / Aes256 / Unknown
    uint64_t payloadOffset = 0;  // tar 载荷在 .bak 内的起始偏移
    std::string encMarker;
};

struct TarEntry {                // tar 索引的一条成员记录
    uint64_t dataOffset;   // 在底层文件（或解压后临时文件）中的绝对字节偏移
    uint64_t size;
    uint64_t modifiedTime;
    char typeFlag;         // '0'=普通文件，'5'=目录
};
```

`TarIndex::build` 若被告知 `inflate=true` 会先把 zlib 载荷解到临时文件（上限 16GB，`TarIndex.h:30-32`），之后所有偏移都指这个临时文件——换取的是"按需单取一个成员"而不用反复解压整个包。

**SQLCipher 解密参数**（`SqlCipherDatabase.h:36-46`）：
```cpp
struct SqlCipherConfig {
    int compatibility = 0;    // SQLCipher 主版本（1-4），0=自动
    int pageSize = 0;         // 页大小（字节），0=按 compat 默认
    std::string hmacAlgo;     // ""（自动）/"sha1"/"sha256"/"sha512"
    int kdfIterations = 0;    // PBKDF2 轮数，0=按 compat 默认；raw-key 模式忽略
};
```

这个结构是"精确配置"与"自动重试"的开关：任何字段留默认值，`SqlCipherDatabase` 就会在该维度上遍历候选矩阵。它的头注释点明动机：其他捆绑 libsqlcipher 的 Flutter 应用把密钥放在 password.json、shared_prefs 等可发现的位置，只是 SQLCipher 参数各异——把这个"打开内核"抽出来，每个 App 解析器都能复用。

## 3. 在流水线中的位置

三种触发方式：

- **HTTP + 物理镜像**：SceneDetector 从 raw.db 探测到 ANDROID 场景后，`TaskManagerAnalysis.cpp:1392` 构造 `AndroidAnalyzer(imagePath, dbManager)`（TSK 模式），输出到 `data/tasks/<id>/<镜像名>_android.db`（近 40 张表）。
- **HTTP + 逻辑源短路**：任务指定 `android_source` 为 `dir | zip | miui-backup | meiya | mobile-evidence | thunder-backup(-oppo) | tar | seven-zip | android-backup | filesystem-image | android-container | ios-backup | vivo-backup` 时，整个 TSK 流水线被跳过（短路判断 `TaskManagerAnalysis.cpp:717-729`），`runLogicalAndroidAnalysis`（`:1714` 起）直接跑 AndroidAnalyzer（`:2027` 构造，dbManager 为 nullptr），android.db 就是任务的最终结果库。其中 **meiya 与 mobile-evidence 不进入 AndroidAnalyzer**：meiya 由独立分支解码容器并产出统一包（`:1836-1923`），mobile-evidence 只读 `.mep.db`；**ios-backup/vivo-backup 仅 HTTP 侧接线**（CLI 侧缺失，见第 7 节）。
- **CLI**：`--android-analyze`（TSK 模式，写 `<镜像>_files.db`）或 `--android-analyze --android-source <逻辑源>`（独立逻辑路径 `runAndroidLogicalAnalysis`，`AnalysisOrchestrator.cpp:736` 起，写 `<镜像名>_files.db`）。路由进逻辑路径的条件见 `:303-321`；`--mobile-extract` / `--mobile-package <pkg>` / `--mobile-package-out` 三个新选项（`CommandLineParser.cpp:133-137`）把"取数"与"分析"拆成两阶段——前者只产出统一取数包 `.mep.db`，后者只读包分析（`AnalysisOrchestrator.cpp:880-911, 953-1014`）。

输入：镜像路径或逻辑源路径；TSK 模式下还需要 raw.db（通过 `DatabaseManager` 查路径→inode，再回镜像读内容）。输出：android.db，表结构集中在 `src/core/DatabaseManager/SQL/android_analysis_sql.h`（`CREATE_ALL_TABLES` 21 张通用工件表 + `CREATE_MIUI_TABLES` 12 张 MIUI/微信/QQNT 专项表，另有进度/来源覆盖/溯源/容器覆盖/文件系统溯源与度量 6 张，合计 39 条 CREATE TABLE）。

入口流程（`AndroidAnalyzerCore.cpp:79-239`）：`initialize()` 选后端并建库 → `analyzeAndroidData()`（`:241-502`）按固定清单依次解析（见第 4 节）→ 最后 `analyzeWithLLM()`（`:615-692`）做工件级 AI 分析。`initialize()` 开头有三处**自动晋升**，让用户随手选错来源也能正确解析：LogicalDir/TSK 路径被识别为鸿蒙备份时晋升 HarmonyBackup（`:81-82`）；`dir` 源检测到 `descript.xml`+`.bak` 时晋升 MiuiBackup（`:87-94`，识别逻辑 `dirLooksLikeMiuiBackup` 在 `:35-59`）；任何来源被雷电头扫描命中时晋升 ThunderForensicBackup（`:100-107`）。三次晋升都写审计 `ANDROID_SOURCE_PROMOTED`（MIUI/雷电）。

取数-分析分离开关：`setExtractionOnly(true)`（`AndroidAnalyzerDeclarations.h:85-94`）后 `initialize()` 只建提取器、**不建 android.db**（`AndroidAnalyzerCore.cpp:216-235`），调用方经 `fileExtractor()` 拿到后端去构建统一取数包（`AndroidAnalyzerDeclarations.h:110-118`）。

### 3.1 核心接口清单
`AndroidAnalyzer` 的公开 API（真实签名见 `AndroidAnalyzerDeclarations.h:51-148`）：

| 方法 | 语义 | 调用方 | 失败行为 |
|------|------|--------|---------|
| `bool initialize()` | 三处自动晋升后按模式选后端、建证据隔离临时根、初始化 android.db（`extractionOnly_` 时跳过建库）；MIUI 模式顺带落清单 | TaskManagerAnalysis / AnalysisOrchestrator 在构造后第一步（Core:79-239） | 返回 false + 审计日志 `ANDROID_INIT_FAILED`；来源错误码经 `sourceError()` 透出（Declarations:108）；TSK 模式缺 dbManager 直接拒绝 |
| `void analyzeAndroidData()` | 主分析：按后端 dynamic_cast 分派（鸿蒙/vivo/iOS/雷电各有专用分支，见第 4 节），通用路径走系统目录→packages.xml→usage→WiFi→各聊天库→Chrome→日志→Phase2 工件→LLM（Core:241-502） | 上述两个入口的第二步 | 逐工件容错：单个库提取/解析失败只写 coverage 与日志，不中断整体 |
| `void setSourceMode(AndroidSourceMode)` | 切换证据源后端；必须在 `initialize()` 之前调（Declarations:104） | `runLogicalAndroidAnalysis`、CLI `--android-source` 分支 | 无（inline setter），晚了不生效 |
| `void setOutputDatabasePath(const std::string&)` | 指定 android.db 输出路径（Declarations:77） | CLI（默认 `<镜像>_files.db`）与 HTTP 任务路径 | 无；空则用 `imagePath_ + "_android.db"` |
| `void setWeChatPassword / setBackupPassword` | 注入微信 SQLCipher 密码 / MIUI 备份 AES 口令（Declarations:81-83） | `--wechat-password`、`--backup-password-stdin/-fd` 的解析结果 | 无；空密码时走自动推导或按"加密锁定"登记 |
| `void setExtractionOnly(bool)` | 取数-only：不建 android.db，供统一取数包构建（Declarations:85-94） | CLI `--mobile-extract`（Orchestrator:955-959） | 无 |
| `void setVivoIndexPath(const std::string&)` | vivo 备份的 `index.json` 路径（Python 桥产物）（Declarations:105-106） | HTTP vivo 分支（TaskManagerAnalysis:2042） | 无 |
| `void setSourceImageSha256 / setExpectedPartitionOffset` | filesystem-image 来源的完整性校验与分区偏移（Declarations:78-79） | HTTP 归档/容器分支（TaskManagerAnalysis:2043-2053） | 无 |
| `IFileExtractor* fileExtractor()` | 取已初始化的后端（供取数适配器枚举成员；分析代码不得依赖）（Declarations:110-118） | 取数-分析分离路径 | `initialize()` 之前无意义 |
| `const std::string& sourceError()` | 后端初始化失败的原因码（如 `IOS_BACKUP_ENCRYPTED`）（Declarations:108） | HTTP 任务失败信息（TaskManagerAnalysis:2068） | 无错误时为空 |
| `void analyzeWithLLM()` | 14 类工件的 LLM 增强分析（也是通用路径的最后一步）（Core:615-692） | 主流程自动调用 | `--no-ai` 或无 LLM 端点时跳过 |
| `void analyze(rootPath)` / `parseWhatsApp` 等一批 | **早期遗留接口**，现行流水线不走（见第 8 节） | 无生产调用方 | — |

## 4. 证据来源与覆盖范围

`analyzeAndroidData()`（`AndroidAnalyzerCore.cpp:241-502`）开头按 `dynamic_cast` 分派后端：鸿蒙 → vivo → iOS → 雷电各有**专用分支后提前返回**（`:242-281`，各自的解析规则见对应模块文档与 ThunderForensicBackup.md），其余模式走通用路径，按四类证据依次取用，所有路径都是证据源内的相对路径：

| 证据类别 | 典型来源（相对路径） | 落表 |
|---------|---------------------|------|
| 通信记录 | `data/data/com.android.providers.telephony/databases/mmssms.db`（短信）、`...contacts/databases/contacts2.db`、`.../calllog.db`、`com.whatsapp/databases/msgstore.db`、`org.telegram.messenger/files/cache4.db`、微信 EnMicroMsg.db | sms_messages / contacts / call_logs / whatsapp_messages / telegram_messages / wechat_messages 等 |
| 系统配置 | `data/system/packages.xml`、`data/system/usagestats/daily`、`data/misc/wifi/WifiConfigStore.xml`（新）或 `wpa_supplicant.conf`（旧）、`system/build.prop`、`/system/app` 与 `/system/framework` 扫描 | installed_packages / usage_stats / wifi_networks / system_build_properties / system_apps / framework_files |
| 行为痕迹 | Chrome `app_chrome/Default/History`、系统日志（`system/logs/*.txt`、`data/log/dmesg`、`data/system/dropbox/*`、`data/tombstones/*`）、SSAID（`data/system/users/0/settings_ssaid.xml`）、记事本应用明文库 | chrome_history / system_logs / device_identifiers / app_notes |
| MIUI 备份 | `descript.xml` 清单 + 各 `.bak`（tar 打包，可能 zlib 压缩）里的 `apps/<包名>/db/*.db`、`<包>/miui_bak/_tmp_bak` 私有 protobuf（联系人/通话/短信/笔记）、微信 r/MicroMsg、QQNT 工件 | miui_backup_manifest / installed_apps / app_db_inventory / wechat_* / qqnt_* 等 12 张专项表 |

通用路径的覆盖语义（`stageKnownDatabase`，`AndroidAnalyzerCore.cpp:303-315`）：每个已知库的提取结果都写一行 `android_source_coverage`——`staged_for_parser`（源字节已暂存，解析行数另查对应表）、`LOCKED`（filesystem-image 模式检测到 `ENCRYPTED_FILE`，注明 EXT4/F2FS per-file 加密）、`not_found_or_unreadable`（预期路径缺失或打不开，"不是设备上不存在的证据"）。三个派生细节：calllog.db 缺失时回退解析 contacts2.db 的 `calls` 表再下结论（`:320-326`）；MIUI 备份没有 provider 库，联系人/通话/短信/笔记改从 `miui_bak/_tmp_bak` protobuf 恢复并**替换**先前写的"sms 缺失"覆盖行（`parseMiuiProtoBakArtifacts`，`:328-335, 504-613`）；微信库不再走固定路径而是经 `findPathsByFilename("EnMicroMsg.db")` 全源搜索、过滤 `com.tencent.mm/` 后逐个尝试（`:389-417`）。

两个解析细节体现工程质量：其一，所有 SQLite 都按"bundle"暂存——主库加上 `-wal/-shm/-journal` 边车一起提取到安全临时目录再打开（`stageSqliteBundle`，`AndroidDataParsers.cpp:48-67`），避免 WAL 未合并导致读到旧数据；临时目录刻意与证据源隔离（`miui_secure_temp`，`AndroidAnalyzerCore.cpp:196-214`），析构时清理；provider 库打开时对未知 collation 注册 memcmp 替身（`openProviderDb`，`AndroidDataParsers.cpp:19-35`）。其二，MIUI 备份的 `.bak` 用 `TarIndex` 建一次内存索引（成员名→字节偏移），之后按需单取某个成员而不用反复解压（`TarIndex.h:24-27`，inflate 上限 16GB）。

### 4.1 产出表结构说明（android.db 关键表）
android.db 的 39 张表全部定义在 `android_analysis_sql.h`（`CREATE_ALL_TABLES` 通用表 + `CREATE_MIUI_TABLES` 专项表 + 覆盖/溯源/度量表）。最有取证意义的几张：

| 表 | 关键列（取自真实 schema） | 取证含义 |
|----|--------------------------|---------|
| `sms_messages`（:37-49） | `thread_id/address/date/date_sent/type/body/service_center` | 短信全文+收发方向（type）+会话分组；`date_sent` 与 `date` 差值可暴露时钟篡改 |
| `wechat_messages`（:90-103） | `sender/receiver/content/timestamp/msg_type/is_send/chatroom_name/sender_nickname/talker` | 微信消息与"我在群里的身份"；`is_send` 区分收发，`talker` 是消息所属会话 |
| `wechat_owner_info`（:125-130） | `username/nickname/uin/imei` | 机主身份——uin 就是解密密钥的原料，此表本身就是"密钥线索登记" |
| `wifi_networks`（:132-137） | `ssid/pre_shared_key/key_mgmt/last_connected` | 连接过的 WiFi 及明文口令，用于地理画像与路由器取证 |
| `installed_packages`（:147-155） | `package_name/code_path/first_install_time/last_update_time/version/installer` | 装过什么、何时装、从哪个市场装（installer 列可暴露侧载） |
| `device_identifiers`（:184-190） | `identifier_type/value/package_name/source_path` | 每应用的 SSAID（Android 8+ 各 App 不同），关联 App 数据与设备 |
| `app_db_inventory`（:228-232） | `package_name/db_path/table_name/row_count/columns/open_status` | MIUI 备份里每个应用库的"盘点行"——包括打不开的（加密/损坏），`open_status` 如实记录失败原因 |
| `qqnt_artifact_inventory`（:244-251） | `source_path/artifact_category/format/size/parse_status/summary/source_hash` | QQNT 私有格式证据的登记册：识别到什么、解析到什么程度、内容哈希 |

值得注意：`encrypted_db_inventory`（:205-213）的注释直说"密钥提示本身就是答案（the hint itself is the contest answer）"——找不到密钥时把发现的提示原样入库，而不是假装解不出来。

### 4.2 产出表全清单（39 张，android_analysis_sql.h）

`CREATE_ALL_TABLES`（通用 21）+ `CREATE_MIUI_TABLES`（专项 12）+ 覆盖与溯源 6 张，按证据域分组：

| 域 | 表 | 关键列（节选） | 写入方 |
|---|---|---|---|
| 系统属性 | system_build_properties | property_name/property_value | BuildPropAnalyzer |
| 系统应用 | system_apps / framework_files | app_name/path/size | 系统目录扫描 |
| 通信 | sms_messages（12 列）/ contacts（7 列）/ call_logs | 见 4.1 | AndroidDataParsers |
| IM | whatsapp_messages / telegram_messages / wechat_messages（13 列） | 各自 msg 表解析 | 同上+WeChat 链路 |
| 微信身份 | wechat_contacts / wechat_chatrooms / wechat_owner_info | username/uin/imei | WeChat 增强解析 |
| 网络 | wifi_networks / chrome_history | ssid/pre_shared_key；url/title/visit_count | WiFi/Chrome 解析 |
| 应用 | installed_packages（8 列）/ usage_stats / app_database_files | package_name/first_install_time/installer | packages.xml/usagestats |
| 行为 | system_logs / device_identifiers / app_notes | log 内容/SSAID/明文笔记 | 日志与记事本解析 |
| 诚实登记 | encrypted_db_inventory / qqnt_artifact_inventory | open_status/parse_status/source_hash | 盘点逻辑 |
| MIUI | miui_backup_manifest / installed_apps / app_db_inventory / miui_external_files | 见 4.1；miui_external_files 是外部存储文件清单（统一包 `mirrorFiles` 的落点，`MobileEvidenceAnalysis.cpp:296-309`） | MiuiBackupManifest / analyzePackage |
| MIUI 结构化 | qqnt_kv_records / qqnt_sqlite_records / qqnt_log_events / wechat_artifact_inventory / wechat_kv_records / wechat_sqlite_records / wechat_log_events（7 张，MIUI 专项） | 各私有格式的可解析子集 | MiuiArtifactParsers |
| 覆盖与溯源 | android_analysis_progress / android_source_coverage / android_source_provenance / android_container_coverage / android_filesystem_provenance / android_filesystem_metrics（android_analysis_sql.h:376-416 一带） | "应有而没取到"的状态行、成员级哈希溯源、容器级覆盖、逻辑分区读取度量——诚实登记的落点 | 分析主流程与各后端 |

列级细节的三个代表（其余表同风格，全量见 `android_analysis_sql.h`）：

**sms_messages（:37-49，12 列）**：`id`（PK 自增）、`thread_id`（会话分组，同 thread 按时间串起来就是一段对话）、`address`（对端号码）、`person`（通讯录匹配名，可为空）、`date`（接收方设备时间，ms）、`date_sent`（发送方时间戳，ms）、`read`/`status`（已读/送达状态）、`type`（1=收 2=发，方向证据）、`body`（全文）、`service_center`（短信中心，运营商定位线索）。写入条件：mmssms.db 的 sms 表逐行；`date_sent=0`（老设备不填）时与 date 的差值分析不可用。

**contacts（:53-61，7 列）**：`raw_contact_id`（contacts2.db 的原始 ID，跨库关联键）、`display_name`、`phone_number`、`email`、`account_type/account_name`（联系人属于哪个账户：本地/Google/微信）——账户维度可以区分"机主手动存的"与"App 自动同步的"。

**installed_packages（:147-155，8 列）**：`package_name/code_path/version/installer` 等；`installer` 为空通常意味着 adb 侧载（非应用市场），是"手动装了什么"的直接证据。

**LLM 侧的 15 条 SQL**（android_analysis_sql_llm.h）：14 条 `SELECT_<TYPE>_PENDING_ANALYSIS`（与 `kLlmTables` 的 14 张表一一对应，取 `llm_analyzed_at IS NULL` 的行）+ 1 条 `INSERT_ANDROID_ANALYSIS_PROGRESS`。AndroidAnalysisDatabase 建库时对 14 张表幂等 ALTER 补 5 个 llm_* 列（`AndroidAnalysisDatabase.cpp:62-77`），另给旧库补 `sms_messages/call_logs.date_seconds` 与 `wechat_contacts.mobile` 迁移列（`:54-61`）。


## 5. 解析机制走读

**链路一：短信从镜像到 sms_messages 表。** `analyzeAndroidData()` 经 `stageKnownDatabase("sms", "data/data/com.android.providers.telephony/databases/mmssms.db", "parseSMS")` 进入（`AndroidAnalyzerCore.cpp:303-317`），它包着 `extractAndParseDB` 并负责写覆盖行。`extractAndParseDB`（`AndroidDataParsers.cpp:69-106`）先 `makeAnalysisTempPath` 生成临时路径，`stageSqliteBundle` 通过当前后端把库（和边车）复制出来，然后按字符串分派到 `parseSMS`。解析完立刻删临时文件——原始证据从头到尾只读不写。暂存与分派的真实代码：

```cpp
// AndroidDataParsers.cpp:48-67
bool AndroidAnalyzer::stageSqliteBundle(const std::string& dbPathInImage,
                                        const std::string& primaryTempPath,
                                        std::vector<std::string>& stagedPaths) {
    stagedPaths.clear();
    if (!fileExtractor_->extractFileByPath(dbPathInImage, primaryTempPath)) {
        std::filesystem::remove(primaryTempPath);
        return false;
    }
    stagedPaths.push_back(primaryTempPath);
    for (const char* suffix : {"-wal", "-shm", "-journal"}) {
        const std::string sidecarSource = dbPathInImage + suffix;
        const std::string sidecarTemp = primaryTempPath + suffix;
        if (fileExtractor_->extractFileByPath(sidecarSource, sidecarTemp)) {
            stagedPaths.push_back(sidecarTemp);
        } else {
            std::filesystem::remove(sidecarTemp);
        }
    }
    return true;
}
```

这段做的事：把"镜像内的主库路径"翻译成本地临时副本，再对三种边车后缀各试一次提取。为什么必须这样做：SQLite 在 WAL 模式下最新事务可能只在 `-wal` 文件里，主库是旧快照，只拷主库会系统性读到旧数据。边车不存在时不进 `stagedPaths`——"有就带上，没有不报错"。错误路径：主库提取失败直接 return false，调用方写一行 `not_found_or_unreadable` 覆盖后返回，不影响后续工件。`parseSMS`（第 108 行起）随后 `sqlite3_open` 打开临时副本，`SELECT address, body, date, type FROM sms` 逐行读出，经 `insertSMS` 参数化插入。

**链路二：微信 EnMicroMsg.db 的解密。** 非 MIUI 路径不再依赖固定位置：`findPathsByFilename("EnMicroMsg.db", 200)` 全源搜索、剔除不含 `com.tencent.mm/` 的命中后逐个尝试（`AndroidAnalyzerCore.cpp:389-417`），找到即暂存并交给 `parseWeChatEnhanced(tempPath, wechatPassword_, wechatDbPath)`；一个都没找到时写 `no_candidate_path` 覆盖行。密码来源有三层：`--wechat-password` 参数显式给；不给时 `WeChatDecryptor::derivePassword` 从镜像里找 UIN，IMEI 无从获取时用占位值，拼起来做 `MD5(IMEI+UIN)` 取前 7 位。推导与版本矩阵的真实代码：

```cpp
// WeChatDecryptor.cpp:62-111（节选）
std::string WeChatDecryptor::derivePassword(const std::string& imageMountPath) {
    std::string uin;
    std::vector<std::string> uinPaths = {
        "/data/data/com.tencent.mm/shared_prefs/auth_info_key_prefs.xml",
        "/data/data/com.tencent.mm/shared_prefs/system_config_prefs.xml"
    };
    for (const auto& path : uinPaths) {
        // ... 读文件内容，找 "_auth_uin" 或 "default_uin" 属性值
        size_t pos = content.find("_auth_uin");
        if (pos == std::string::npos) pos = content.find("default_uin");
        // ... valueAttr 距 pos 200 字符内才算命中，取引号之间的值并去空白
    }
    if (uin.empty()) return "";
    // Try to find IMEI (may be empty on newer devices)
    std::string imei = "1234567890ABCDEF";   // 占位：新版设备 IMEI 不可读
    std::string combined = imei + uin;
    std::string hash = md5(combined);
    OPENSSL_cleanse(&combined[0], combined.size());  // 中间量清零
    if (hash.length() >= 7) return hash.substr(0, 7);
    return "";
}
```

做什么/为什么：微信把 UIN 存在两个 shared_prefs XML 里（`<int name="_auth_uin" value="..."/>`），这里不做完整 XML 解析而是字符串定位 + 200 字符窗口约束，防误命中同名属性；IMEI 在镜像里拿不到（新版 Android 限制），硬编码占位值——所以**自动推导在无 IMEI 的设备上大概率失败，需要人工给密码**（已登记的坑）。`OPENSSL_cleanse` 清掉拼接串是密钥卫生习惯。拿到密码后 `openDatabase`（第 28-60 行）按"SQLCipher v4 默认 → v2 传统参数（4000 轮 KDF + SHA1 HMAC）→ 全版本矩阵"的顺序尝试打开。矩阵本体在 `SqlCipherDatabase.cpp:98-114`：

```cpp
// SqlCipherDatabase.cpp:98-114（节选）
std::vector<SqlCipherConfig> candidateConfigs() {
    struct P { int c; int ps; const char* h; int k; };
    const P presets[] = {
        {4, 0, "", 0},       // SQLCipher 4 defaults (256000/sha512/4096)
        {3, 0, "", 0},       // SQLCipher 3 defaults (64000/sha1/1024)
        {2, 0, "", 0},       // SQLCipher 2 defaults (4000/sha1/1024)
        {1, 0, "", 0},       // SQLCipher 1 defaults (4000/sha1/1024)
        {0, 4096, "sha512", 0},
        {0, 1024, "sha1", 0},
        // ... 4096/sha256、4096/sha1、1024/sha512
    };
    std::vector<SqlCipherConfig> v;
    for (const auto& p : presets) { /* 逐 preset 组装 SqlCipherConfig */ }
    return v;
}
```

边界与错误路径：每个候选配置的验证方式是 `PRAGMA key` 之后读 `sqlite_master`（`SqlCipherDatabase.h:63` 的返回值契约），读得出 schema 才算密码+参数都对了；全部失败则 `lastError_` 记 "Failed to decrypt database with provided password"。打开成功后走 `parseWeChatContacts/parseWeChatChatrooms/identifyWeChatOwner` 加增强消息解析（声明在 `AndroidAnalyzerDeclarations.h:218-222`），分别落 wechat_contacts、wechat_chatrooms、wechat_owner_info、wechat_messages 表。MIUI 模式则改成枚举备份里所有微信库成员逐个处理（`AndroidAnalyzerCore.cpp:344-388`）。

**链路三：MIUI 备份的清单化、建索引与库盘点。** `initialize()` 识别 miui-backup 模式后立刻 `persistMiuiBackupAnalysis`（`AndroidAnalyzerCore.cpp:227-234`）：`writeMiuiManifest` 把 descript.xml 解析成 `BackupMeta`，写 miui_backup_manifest 和每个包一行 installed_apps；`writeAppDbInventory` 遍历 `apps/<包名>/db/` 下的每个 SQLite，能读的逐表记行数与列名，读不了的（加密/损坏）也写一行失败记录而不是静默跳过（`MiuiArtifactParsers.h:16-22` 注释），整个过程在一个事务里，失败不会留下"看似完整的半成品"（同文件第 25-26 行）。`.bak` 建索引的真实代码：

```cpp
// MiuiBackupExtractor.cpp:166-183
auto index = std::make_unique<TarIndex>();
if (!index->build(bakPath.string(), header.payloadOffset,
                  header.compression == 1, temporaryRoot_)) {
    std::cerr << "MiuiBackupExtractor: failed to index " << bakPath << std::endl;
    packageFailures_.push_back(
        {package.packageName, package.bakFile, "parse_error"});
    continue;
}

TarIndex* owner = index.get();
const std::string expectedPrefix = "apps/" + package.packageName + "/";
for (const auto& entry : index->entries()) {
    if (entry.first.rfind(expectedPrefix, 0) == 0) {
        entryOwner_.emplace(entry.first, owner);
    }
}
indexes_.push_back(std::move(index));
```

做什么：对清单里每个 `.bak`，先过一串安全校验（文件名不得绝对/含父目录、不得是符号链接、canonical 后不得逃出备份根，`MiuiBackupExtractor.cpp:106-141`），再用 `parseAndroidBackupHeader` 拿到 `payloadOffset/compression/encryption`（加密的登记 `encrypted_locked` 后跳过 `:151-157`、compression 非 0/1 报不支持 `:158-164`），然后 `TarIndex::build` 一次线性扫描建成员名→偏移表，最后只把属于 `apps/<包名>/` 前缀的成员挂进全局 `entryOwner_` 映射。为什么按前缀过滤：MIUI 备份的 tar 里还有缓存等无关内容，全挂进映射既浪费内存又可能让同名成员互相遮蔽。失败行为是登记一条 `parse_error` 后 `continue`——单个坏包不拖垮整个备份的解析。这个盘点有大量防失控限额（单库 512MB、bundle 768MB、清单 1 万行、候选 10 万个，见 `MiuiArtifactParsers.cpp:36-51` 的常量表，候选上限可用环境变量 `TRACELENS_MIUI_MAX_CANDIDATES` 收紧），防止一个畸形备份拖死分析。

### 5.1 代码走读：extractAndParseDB 的分派与清理（AndroidDataParsers.cpp:69-106）

```cpp
bool AndroidAnalyzer::extractAndParseDB(const std::string& dbPathInImage,
                                        const std::string& parserName) {
    const std::string tempPath = makeAnalysisTempPath("db");
    std::vector<std::string> staged;
    if (!stageSqliteBundle(dbPathInImage, tempPath, staged)) {
        AuditLog::instance().log("SYSTEM", "ANDROID_EXTRACT_FAILED", dbPathInImage);
        return false;
    }
    bool ok = false;
    if (parserName == "parseSMS") ok = parseSMS(tempPath);
    else if (parserName == "parseContacts") ok = parseContacts(tempPath);
    // ... 每个解析器一个分支
    for (const auto& p : staged) std::filesystem::remove(p);
    return ok;
}
```

逐块解释（骨架，全实现 `:69-106`）：三段式"暂存→分派→清理"。`makeAnalysisTempPath` 落在 `miui_secure_temp` 安全临时根下（与证据源物理隔离）；分派用**字符串 if-else 链**而非函数表——加解析器要同时改调用点字符串与分派链两处，是这个模块最明显的"约定耦合"（扩展清单第 8 节的步骤 (2) 由此而来）。清理循环在**所有路径**上执行（成功/解析失败都删暂存副本），RAII 意义由手写保证；若解析器中途 throw（如 SQLite open 后的意外异常），暂存文件会残留到进程退出——析构函数对临时根做兜底清理。审计只在**提取失败**时记一条，解析失败由各 parser 自行打日志——两类失败的观测渠道不同。

### 5.2 代码走读：MIUI 限额与防失控（MiuiBackupManifest.cpp:24-30、MiuiArtifactParsers.cpp:36-51）

```cpp
// MiuiBackupManifest.cpp:24-30 —— descript.xml 清单侧
constexpr uint64_t kMaximumManifestBytes = 16ULL * 1024 * 1024;
constexpr size_t kMaximumManifestPackages = 100000;
constexpr size_t kMaximumManifestFieldBytes = 4096;
constexpr size_t kMaximumManifestMetadataBytes = 16ULL * 1024 * 1024;
// 均有 TRACELENS_MIUI_MAX_MANIFEST_{PACKAGES,FIELD_BYTES,METADATA_BYTES} 环境变量覆写

// MiuiArtifactParsers.cpp:36-51 —— 盘点侧（节选）
constexpr uint64_t kMaximumExtractedDatabaseBytes = 512ULL * 1024 * 1024;  // 单库 512MB
constexpr uint64_t kMaximumBundleBytes = 768ULL * 1024 * 1024;             // bundle 768MB
constexpr uint64_t kMaximumInventoryRows = 10000;                          // 单库盘点行
constexpr size_t kMaximumCandidateDatabases = 100000;                      // 全局候选库
constexpr uint64_t kMaximumGlobalInventoryRows = 50000000;                 // 全局盘点行
constexpr uint64_t kMaximumGlobalSqliteInstructions = 2000000000ULL;       // 全局 VM 指令数
constexpr const char* kInventoryLimitEnvironment = "TRACELENS_MIUI_MAX_CANDIDATES";
```

逐块解释：限额覆盖四个失控维度——**清单解析**（descript.xml 总量 16MB/条目 10 万/单字段 4KB，防超大或海量条目的 manifest）、**枚举规模**（全局候选库 10 万 + 全局盘点行 5000 万，防 tar 炸弹式的海量成员）、**单件体积**（单库 512MB/bundle 768MB，防巨型 SQLite 把盘点变成全量拷贝）、**CPU**（全局 SQLite VM 指令数 20 亿与单查询 200 万指令上限，`kMaximumQueryInstructions`，防畸形库把盘点变成无限循环）。清单侧三个限额与盘点侧候选上限均可用环境变量收紧（`MiuiBackupManifest.cpp:166-170`、`MiuiArtifactParsers.cpp:51`）。超限行为是登记+跳过而非失败——盘点表里能看到"因超限未处理"的记录，与模块"诚实登记"的立场一致。


## 6. 与 LLM 的协作

通用路径的最后一 phase 是 `analyzeWithLLM()`（`AndroidAnalyzerCore.cpp:615-692`；鸿蒙/雷电分支也会在自己的专用解析后显式调用它，vivo/iOS 分支不调用）。跳过条件两条：`--no-ai`（`setSkipAI`）或未配置 LLM 端点——门禁读 `getTextBaseUrl()` 与 `getLLMBaseUrl()`，两者都空才跳过（`:628-645`；本地 LM Studio/Ollama/vLLM 不需要 key，所以门禁是 URL 而不是 key）。真正干活的是 `AndroidLLMAnalysisService`（`src/network/HTTPServer/AndroidLLMAnalysisService.h`）：它覆盖 14 种工件类型（SMS、各聊天消息、联系人、通话、MIUI 清单、微信/QQNT 结构化记录、系统日志、设备标识、WiFi），模式与 Linux/Windows 的同名服务一致——建库时给 14 张工件表幂等地补 5 个 `llm_*` 列（`AndroidAnalysisDatabase.cpp:65-71` 的 `kLlmTables` 列表），分析时用 `SELECT_..._PENDING_ANALYSIS` 取未分析行、拼 JSON prompt 发给 `ModelRouter::chat()`、结果原地 UPDATE 回写。每类上限由 `LLM_MAX_ARTIFACTS` 配置控制（默认 500，上限 10 万，`0` 显式表示全量；`AndroidAnalyzerCore.cpp:666-671`、`ConfigManager.cpp:109-124`），HTTP 侧另有 `TRACELENS_FIELD_AUTH`+`FIELD_OUTBOUND_POLICY` 组合强制关停（`TaskManagerAnalysis.cpp:2055-2059`）。

## 7. 与其他模块的协作 / 注意事项

- **依赖**：TSK/FileExtractor（物理镜像模式）、libzip（zip 模式，编译期 `HAVE_LIBZIP`）、SQLCipher（`HAVE_SQLCIPHER`；没有它时加密库只能标记 `encrypted_no_sqlcipher_build`，见 `AndroidLogicalParsers.cpp:420`）、OpenSSL（MD5/SHA-256）。
- **密码参数**：`--wechat-password`（微信）、`--backup-password-stdin` / `--backup-password-fd <N>`（MIUI 备份 AES 口令，安全读入实现见 `AnalysisOrchestrator.cpp:39-129`；argv 形式的 `--backup-password` 对 7z/Android Backup 已被拒绝，`AnalysisOrchestrator.cpp:737-741`）；HTTP 模式用完即 `clear_backup_password` 清除（`TaskManagerAnalysis.cpp:742`）。
- **CLI 侧 ios-backup/vivo-backup 未接线**：两个值在 CLI 解析合法并自动置 `--android-analyze`（`CommandLineParser.cpp:226-229`），但逻辑源路由条件（`AnalysisOrchestrator.cpp:303-321`）与 mode 映射（`:916-924`）都不含它们，CLI 会落入 TSK 磁盘镜像流水线；只有 HTTP 任务链路可用（详见 [IosAnalyzer](IosAnalyzer.md) 与 [VivoAnalyzer](VivoAnalyzer.md) 的"在系统中的位置"）。
- **坑**：`derivePassword` 的 IMEI 拿不到时硬编码占位 `1234567890ABCDEF`（`WeChatDecryptor.cpp:100`）——新版设备 IMEI 不可读，此时自动推导大概率失败，需要人工给密码；Chrome 历史按 `app_chrome/Default/History` 单 profile 取，多 profile（Profile 1/2…）不覆盖；zip 模式没编 libzip 时初始化直接失败。
- **`analyze(rootPath)` 与 `parseWhatsApp` 等一批公有接口是早期遗留**，现行流水线只走 `initialize() → analyzeAndroidData()`；阅读代码时以 `AndroidAnalyzerCore.cpp` 的调用顺序为准。
- **下游**：HTTP 模式下 android.db 的查询路由（含 MIUI 专用查询）会回退到任务的 output_files_db，逻辑任务里它就是 android.db 本身（`TaskManagerAnalysis.cpp:759-764` 的注释解释了这个约定）；miui/harmony/thunder 三来源任务还会额外产出统一取数包并在元数据登记（`TaskManagerAnalysis.cpp:2073-2138`）。

## 8. 如何验证与扩展

- 测试：`tests/UnitTest/test_android_analyzer_gtest.cpp`（核心解析）、`test_android_logical_source_gtest.cpp`（逻辑源后端）、`test_android_archive_gtest.cpp`（tar/7z/.ab）、`test_miui_backup_gtest.cpp`（备份清单/索引）、`test_miui_proto_bak_gtest.cpp`（protobuf 恢复）、`test_ios_backup_gtest.cpp` / `test_vivo_backup_gtest.cpp`（两个新后端）、`test_meiya_container_gtest.cpp`（掩码推导）、`test_mobile_evidence_package_gtest.cpp` / `test_mobile_evidence_adapters_gtest.cpp`（统一取数包）、`test_wechat_decryptor_gtest.cpp`（SQLCipher 矩阵与密钥推导）、`test_sqlcipher_database_gtest.cpp`；集成侧 `tests/integration/test_android_filesystem_image_e2e.py`、`test_mobile_analysis_e2e.py` 等。构造假证据源的常用办法是手工 SQLite/zip/tar 组装。
- 加新应用证据：在 `analyzeAndroidData()` 里加一行 `stageKnownDatabase(<kind>, <镜像内相对路径>, "<解析器名>")`，在 `AndroidDataParsers.cpp` 写解析函数并在 `extractAndParseDB` 的分派链里挂上；新表加到 `android_analysis_sql.h` 的 `CREATE_ALL_TABLES`，插入方法加在 `AndroidAnalysisDatabase.cpp`。如果新证据也要 LLM 分析，记得把表名加进 `kLlmTables` 并在 `AndroidLLMAnalysisService` 注册类型。
- 加新证据源后端：实现 `IFileExtractor::extractFileByPath`（建议同时实现 `findPathsByFilename`/`usedSourceProvenance`），在 `initialize()` 的 switch 里挂分支，上游（TaskManager/AnalysisOrchestrator）加对应 `--android-source` 值即可，全部解析器自动可用；如果来源是"品牌备份"，优先评估直接实现 `buildPackageFromXxx` 适配器走统一取数包（见 [MobileEvidencePackage](MobileEvidencePackage.md) 第 7 节）。

## 9. 关联矩阵

| 对端 | 方向 | 交互点 | 数据形态 |
|---|---|---|---|
| TaskManagerAnalysis.cpp:1392 / :1714+ / :2027 | 上游 | TSK 模式构造、逻辑源短路、runLogicalAndroidAnalysis | imagePath+dbManager/nullptr |
| TaskManagerAnalysis.cpp:1836-1923 | 上游 | meiya 独立分支（不经本类） | 案件目录→包→android.db |
| AnalysisOrchestrator.cpp:303-321 / :736+ | 上游 | CLI 逻辑源路由与两阶段拆分 | 同上 |
| IFileExtractor 十二后端（FileExtractor/LogicalDir/ZipArchive/Miui/Harmony/Thunder/Tar/7z/AndroidBackup/FilesystemEvidence/Ios/Vivo） | 下游 | extractFileByPath / findPathsByFilename / usedSourceProvenance | 镜像相对路径→本地文件 |
| android_analysis_sql.h（39 表） | 输出 | CREATE_ALL/MIUI_TABLES + 覆盖/溯源 | DDL 常量 |
| AndroidAnalysisDatabase | 下游 | 建库+insert 系列+kLlmTables 补列 | 参数化 INSERT |
| mobile_evidence（适配器/Writer/analyzePackage） | 平行 | 取数-分析分离（见 MobileEvidencePackage.md） | Package / .mep.db |
| AndroidLLMAnalysisService | 下游 | 14 类工件 pending→chat→回写 | JSON prompt/llm_* 列 |
| WeChatDecryptor/SqlCipherDatabase | 内部 | 密钥推导+版本矩阵 | 7 位密码/SqlCipherConfig |
| TarIndex/AndroidBackupHeader | 内部 | MIUI .bak 索引 | 成员名→偏移 |
| scripts/vivo_backup_index_cli.py（HTTP 侧） | 上游 | LevelDB 索引→index.json | JSON |
| AuditLog | 下游 | ANDROID_* / VIVO_* / IOS_* 等 | 审计条目 |
| ConfigManager | 上游 | LLM 端点门禁与 LLM_MAX_ARTIFACTS（Core:628-645, 666-671） | string/int |
| OpenSSL/libzip/SQLCipher/TSK | 外部依赖 | MD5/zip/解密/镜像 | 编译期 HAVE_* |

## 10. 配置影响表

| 参数 | 默认 | 影响 | 备注 |
|---|---|---|---|
| `--android-source` | tsk | 后端选择（15 个合法字符串，12 模式） | dir 源可自动晋升 miui-backup/harmony/雷电（Core:81-107） |
| `--mobile-extract` / `--mobile-package(-out)` | 关 | 取数/分析两阶段拆分 | 仅 miui/harmony/thunder 支持取数侧（Orchestrator:955-957）；meiya 分支内建 |
| `--wechat-password` | 空 | 微信 SQLCipher 密码 | 自动推导是回退不是替代 |
| `--backup-password(-stdin/-fd)` | 空/−1 | MIUI AES 口令 | fd 优先；argv 形式对 7z/.ab 拒绝 |
| `LLM_BASE_URL` / `LLM_TEXT_BASE_URL` | 部署配置 | 两者都空则 LLM 段跳过 | 门禁是 URL 不是 key（Core:633） |
| `LLM_MAX_ARTIFACTS` | 500（上限 10 万，0=全量） | 每类工件 LLM 分析条数 | ConfigManager.cpp:124；Core:671 |
| `--no-ai`（skip_ai） | false | 平台段跳过 LLM | Core:617 |
| `TRACELENS_MIUI_MAX_*` | 见源文件 | MIUI 清单/候选防失控限额 | MiuiBackupManifest.cpp:24-30、MiuiArtifactParsers.cpp:51 |
| `HAVE_LIBZIP/HAVE_SQLCIPHER` | 编译期 | zip 后端/解密能力 | 缺失降级为登记 |

## 11. 性能与并发细节

- **IO 大头**：TSK 模式逐工件的 extractFileByPath（镜像随机读）；MIUI 模式的 zlib 解压（inflate 到临时文件一次，之后按偏移零解压单取）——TarIndex 的设计正是把 O(成员数) 次解压降为 1 次；filesystem-image 模式则是一次性的分区遍历（度量写 `android_filesystem_metrics`，Core:452-456）。
- **CPU 大头**：SQLCipher 矩阵重试——每个候选配置一次 PRAGMA key+schema 读，8 个 preset 全试最坏约秒级（PBKDF2 256000 轮的 v4 默认最贵）；密码正确时通常第一候选即中。
- **内存**：TarIndex 全量成员表（候选上限 × 每条约百字节）；单库暂存受 512MB 限额；解析行数据流式不入内存；iOS/vivo 索引分别为 200 万条目 / 全量 items 表。
- **并发**：分析主流程单线程顺序解析（工件间有审计依赖无数据依赖，理论上可并行但未做）；LLM 段由 AndroidLLMAnalysisService 内部并发（走 ModelRouter，批处理参数 `LLM_ARTIFACT_BATCH_SIZE`）。
- **可调参数影响**：LLM_MAX_ARTIFACTS 是 LLM token 预算的旋钮；MIUI 限额收紧可把畸形备份的分析时间封顶。


## 12. 常见任务配方

### 配方 A：新增一个应用工件解析器
1. `Parsers/` 或 `AndroidDataParsers.cpp` 加解析（经 `IFileExtractor` 取文件——九处取文件全走它，换后端零改动）。
2. 落表：`SQL/android_analysis_sql.h` 加 CREATE + INSERT。
3. 前端：`AndroidForensicsRoutes` 加端点 + web /android 页消费。
4. LLM：`AndroidLLMAnalysisService` 表驱动四件套（注意它有端点可用性门控——无 LLM_BASE_URL 自动跳过）。

### 配方 B：新增 MIUI 备份字段
`MiuiBackupManifest.h` 结构体 + descript.xml 解析点 + manifest 表列（SQL 头文件三处同步）。

### 配方 C：微信解密失败标准排查
1. 密码来源确认（--backup-password-stdin 优先，避免 argv 泄漏）；2. IMEI 缺失时密钥推导用占位 1234567890ABCDEF——新设备大概率失败，需人工从镜像其他位置找 IMEI；3. 查 `encrypted_db_inventory` 的 key_hint/open_status 留痕；4. 版本矩阵重试日志（WeChatDecryptor 的 1-4 版本尝试）。

### 配方 D：统一取数包两阶段排查
1. `--mobile-extract` 只出包不分析（仅 miui/harmony/thunder；meiya 分支内建两阶段）；2. 包写失败先看 Writer.error() 与任务元数据 `mobile_evidence_*`；3. `--mobile-package` 重建时 `looksLikePackage` 拒绝非本格式库；4. 检查 `mobile_evidence_coverage` vs android.db 的 `android_source_coverage`（nativeStatus 优先）。
**最后更新**: 2026-11-10（按代码重写：android-source 全值、取数-分析分离、覆盖语义、LLM 上限配置化）
