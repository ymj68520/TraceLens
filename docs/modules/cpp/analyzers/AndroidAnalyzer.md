# AndroidAnalyzer（src/analyzers/AndroidAnalyzer/）

> **一句话**：从 Android 证据源（物理镜像、逻辑提取目录、zip 包、MIUI 离线备份）里解析出"人"的痕迹——短信、通讯录、通话记录、微信/QQ/WhatsApp/Telegram 聊天、Chrome 历史、WiFi、已装应用、系统日志——统一写入 android.db 的 30 多张工件表。

## 1. 为什么有这个模块

手机取证要回答的问题和电脑很不一样。调查者关心的往往不是文件系统本身，而是**通信与行为记录**：谁给谁发了什么、什么时候装的什么 App、设备连过哪些 WiFi、崩溃日志里泄露了什么。这些证据散落在几十个固定的路径里——`/data/data/<包名>/databases/` 下的 SQLite、`/data/system/packages.xml`、`shared_prefs` 的 XML——每个都有自己的格式和坑（加密、WAL 边车、私有二进制格式）。AndroidAnalyzer 的价值就是把这套"路径 + 格式 + 解析"的知识固化下来，让一条命令就把一个 Android 证据源读完。

这个模块有两个显著的设计立场值得先知道。**第一是"证据源无关"**：真实案件里 Android 证据经常不是物理镜像，而是国产定制 ROM 的离线备份（MIUI）或 adb 逻辑导出的目录/zip。为此模块定义了 `IFileExtractor` 抽象（`IFileExtractor.h`），四个后端——TSK 镜像、目录、zip、MIUI 备份——在解析器眼中完全透明，所有取文件都走 `fileExtractor_->extractFileByPath()`（`AndroidAnalyzerCore.cpp:75-77` 的注释明确说明了这一点）。**第二是"诚实的证据观"**：对无法解析的私有格式（QQNT 的 MMKV、加密的 EnMicroMsg.db），宁可如实登记为"识别到但未解码的证据"，也不编造解码结果——`WechatArtifactParsers.h` 和 `QqntArtifactParsers.h` 的头注释把这条原则写得很清楚。对取证工具来说，这比"看起来功能多"更重要。

第三个背景是**微信加密库的现实**。微信的 EnMicroMsg.db 是 SQLCipher 加密的，密钥是 `MD5(IMEI + UIN)` 的前 7 位。模块内置了完整的解密链路（参数化密码 → 自动推导 → SQLCipher 版本矩阵重试），这是 Android 证据里价值最高也最难拿的一块。

## 2. 核心数据结构

**证据源抽象、MIUI 备份模型与 SQLCipher 解密参数**——三组核心结构如下。

**证据源模式与后端接口**（`AndroidAnalyzerDeclarations.h:29-34`、`IFileExtractor.h:41-62`）：

```cpp
enum class AndroidSourceMode {
    TSK,           // 块级镜像 + _raw.db（老路径）
    LogicalDir,    // 已解包的 data/ 目录树
    Zip,           // 打成 Image.zip 的逻辑提取（libzip）
    MiuiBackup     // MIUI 离线备份目录
};

class IFileExtractor {
public:
    virtual bool initialize() = 0;
    virtual bool extractFileByPath(const std::string& imageRelPath,
                                   const std::string& outPath) = 0;
};
```

`AndroidSourceMode` 就是 CLI `--android-source` 与 HTTP `android_source` 字段的四个取值；`IFileExtractor` 的契约是"给镜像内相对路径（容忍前导 `/`），把完整字节写到本地 outPath"。头注释统计过：模块内九处取文件调用全部走这一个方法，换后端不动任何解析代码。

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

- **HTTP + 物理镜像**：SceneDetector 从 raw.db 探测到 ANDROID 场景后，`TaskManagerAnalysis.cpp:454-468` 构造 `AndroidAnalyzer(imagePath, dbManager)`（TSK 模式），输出到 `data/tasks/<id>/<镜像名>_android.db`（33 张表）。
- **HTTP + 逻辑源短路**：任务指定 `android_source = dir | zip | miui-backup` 时，整个 TSK 流水线被跳过，`runLogicalAndroidAnalysis` 直接跑 AndroidAnalyzer（`TaskManagerAnalysis.cpp:123-199, 600-668`），此时 dbManager 为 nullptr，android.db 就是任务的最终结果库。
- **CLI**：`--android-analyze`（TSK 模式，写 `<镜像>_files.db`，`AnalysisOrchestrator.cpp:276-293`）或 `--android-analyze --android-source dir|zip|miui-backup`（独立逻辑路径，写 `<镜像名>_files.db`，`AnalysisOrchestrator.cpp:468-532`）。

输入：镜像路径或逻辑源路径；TSK 模式下还需要 raw.db（通过 `DatabaseManager` 查路径→inode，再回镜像读内容）。输出：android.db，表结构集中在 `src/core/DatabaseManager/SQL/android_analysis_sql.h`（21 张通用工件表 + 11 张 MIUI/微信/QQNT 证据表 + 1 张进度表）。

入口流程（`AndroidAnalyzerCore.cpp:61-148, 150-258`）：`initialize()` 选后端并建库 → `analyzeAndroidData()` 按固定清单依次解析（见第 4 节）→ 最后 `analyzeWithLLM()` 做工件级 AI 分析。MIUI 模式还有一个贴心的自动晋升：用户把 MIUI 备份目录当成普通"目录"源提交时，`initialize()` 检测到 `descript.xml` 根标签是 `<MIUI-backup>` 且有 `.bak` 文件就自动切到 miui-backup 模式（`AndroidAnalyzerCore.cpp:61-73`）。

### 3.1 核心接口清单
`AndroidAnalyzer` 的公开 API（真实签名见 `AndroidAnalyzerDeclarations.h:40-136`）：

| 方法 | 语义 | 调用方 | 失败行为 |
|------|------|--------|---------|
| `bool initialize()` | 按模式选后端、建安全临时根、初始化 android.db；MIUI 模式顺带落清单 | TaskManagerAnalysis / AnalysisOrchestrator 在构造后第一步 | 返回 false + 审计日志 `ANDROID_INIT_FAILED`；TSK 模式缺 dbManager 直接拒绝 |
| `void analyzeAndroidData()` | 主分析：系统目录→packages.xml→usage→WiFi→各聊天库→Chrome→日志→Phase2 工件→LLM | 上述两个入口的第二步 | 逐工件容错：单个库提取/解析失败只打日志，不中断整体 |
| `void setSourceMode(AndroidSourceMode)` | 切换证据源后端；必须在 `initialize()` 之前调 | `runLogicalAndroidAnalysis`、CLI `--android-source` 分支 | 无（inline setter），晚了不生效 |
| `void setOutputDatabasePath(const std::string&)` | 指定 android.db 输出路径 | CLI（默认 `<镜像>_files.db`）与 HTTP 任务路径 | 无；空则用 `imagePath_ + "_android.db"` |
| `void setWeChatPassword / setBackupPassword` | 注入微信 SQLCipher 密码 / MIUI 备份 AES 口令 | `--wechat-password`、`--backup-password-stdin/-fd` 的解析结果 | 无；空密码时走自动推导或按"加密锁定"登记 |
| `void analyzeWithLLM()` | 14 类工件的 LLM 增强分析（也是 `analyzeAndroidData()` 的最后一步） | 主流程自动调用 | `--no-ai` 或无 `LLM_BASE_URL` 时跳过 |
| `void analyze(rootPath)` / `parseWhatsApp` 等一批 | **早期遗留接口**，现行流水线不走（见第 8 节） | 无生产调用方 | — |

## 4. 证据来源与覆盖范围

`analyzeAndroidData()`（`AndroidAnalyzerCore.cpp:150-258`）按四类证据依次取用，所有路径都是证据源内的相对路径：

| 证据类别 | 典型来源（相对路径） | 落表 |
|---------|---------------------|------|
| 通信记录 | `data/data/com.android.providers.telephony/databases/mmssms.db`（短信）、`...contacts/databases/contacts2.db`、`.../calllog.db`、`com.whatsapp/databases/msgstore.db`、`org.telegram.messenger/files/cache4.db`、微信 EnMicroMsg.db | sms_messages / contacts / call_logs / whatsapp_messages / telegram_messages / wechat_messages 等 |
| 系统配置 | `data/system/packages.xml`、`data/system/usagestats/daily`、`data/misc/wifi/WifiConfigStore.xml`（新）或 `wpa_supplicant.conf`（旧）、`system/build.prop`、`/system/app` 与 `/system/framework` 扫描 | installed_packages / usage_stats / wifi_networks / system_build_properties / system_apps / framework_files |
| 行为痕迹 | Chrome `app_chrome/Default/History`、系统日志（`system/logs/*.txt`、`data/log/dmesg`、`data/system/dropbox/*`、`data/tombstones/*`）、SSAID（`data/system/users/0/settings_ssaid.xml`）、记事本应用明文库 | chrome_history / system_logs / device_identifiers / app_notes |
| MIUI 备份 | `descript.xml` 清单 + 各 `.bak`（tar 打包，可能 zlib 压缩）里的 `apps/<包名>/db/*.db`、微信 r/MicroMsg、QQNT 工件 | miui_backup_manifest / installed_apps / app_db_inventory / wechat_* / qqnt_* 共 11 张表 |

两个解析细节体现工程质量：其一，所有 SQLite 都按"bundle"暂存——主库加上 `-wal/-shm/-journal` 边车一起提取到安全临时目录再打开（`stageSqliteBundle`，`AndroidDataParsers.cpp:21-40`），避免 WAL 未合并导致读到旧数据；临时目录刻意与证据源隔离（`miui_secure_temp`），析构时清理。其二，MIUI 备份的 `.bak` 用 `TarIndex` 建一次内存索引（成员名→字节偏移），之后按需单取某个成员而不用反复解压（`TarIndex.h:24-27`，inflate 上限 16GB）。

### 4.1 产出表结构说明（android.db 关键表）
android.db 的 33 张表全部定义在 `android_analysis_sql.h`（`CREATE_ALL_TABLES` 通用表 + `CREATE_MIUI_TABLES` 专项表）。最有取证意义的几张：

| 表 | 关键列（取自真实 schema） | 取证含义 |
|----|--------------------------|---------|
| `sms_messages`（:37-49） | `thread_id/address/date/date_sent/type/body/service_center` | 短信全文+收发方向（type）+会话分组；`date_sent` 与 `date` 差值可暴露时钟篡改 |
| `wechat_messages`（:86-99） | `sender/receiver/content/timestamp/msg_type/is_send/chatroom_name/sender_nickname/talker` | 微信消息与"我在群里的身份"；`is_send` 区分收发，`talker` 是消息所属会话 |
| `wechat_owner_info`（:117-123） | `username/nickname/uin/imei` | 机主身份——uin 就是解密密钥的原料，此表本身就是"密钥线索登记" |
| `wifi_networks`（:124-130） | `ssid/pre_shared_key/key_mgmt/last_connected` | 连接过的 WiFi 及明文口令，用于地理画像与路由器取证 |
| `installed_packages`（:139-148） | `package_name/code_path/first_install_time/last_update_time/version/installer` | 装过什么、何时装、从哪个市场装（installer 列可暴露侧载） |
| `device_identifiers`（:176-182） | `identifier_type/value/package_name/source_path` | 每应用的 SSAID（Android 8+ 各 App 不同），关联 App 数据与设备 |
| `app_db_inventory`（:220-224） | `package_name/db_path/table_name/row_count/columns/open_status` | MIUI 备份里每个应用库的"盘点行"——包括打不开的（加密/损坏），`open_status` 如实记录失败原因 |
| `qqnt_artifact_inventory`（:225-232） | `source_path/artifact_category/format/size/parse_status/summary/source_hash` | QQNT 私有格式证据的登记册：识别到什么、解析到什么程度、内容哈希 |

值得注意：`encrypted_db_inventory`（:197-205）的注释直说"密钥提示本身就是答案（the hint itself is the contest answer）"——找不到密钥时把发现的提示原样入库，而不是假装解不出来。

## 5. 解析机制走读

**链路一：短信从镜像到 sms_messages 表。** `analyzeAndroidData()` 调 `extractAndParseDB("data/data/com.android.providers.telephony/databases/mmssms.db", "parseSMS")`（`AndroidAnalyzerCore.cpp:170`）。`extractAndParseDB`（`AndroidDataParsers.cpp:42-79`）先 `makeAnalysisTempPath` 生成临时路径，`stageSqliteBundle` 通过当前后端把库（和边车）复制出来，然后按字符串分派到 `parseSMS`。解析完立刻删临时文件——原始证据从头到尾只读不写。暂存与分派的真实代码：

```cpp
// AndroidDataParsers.cpp:21-40
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

这段做的事：把"镜像内的主库路径"翻译成本地临时副本，再对三种边车后缀各试一次提取。为什么必须这样做：SQLite 在 WAL 模式下最新事务可能只在 `-wal` 文件里，主库是旧快照，只拷主库会系统性读到旧数据。边车不存在时不进 `stagedPaths`——"有就带上，没有不报错"。错误路径：主库提取失败直接 return false，调用方打一行日志后返回，不影响后续工件。`parseSMS`（第 81-109 行）随后 `sqlite3_open` 打开临时副本，`SELECT address, body, date, type FROM sms` 逐行读出，经 `insertSMS` 参数化插入。

**链路二：微信 EnMicroMsg.db 的解密。** 非 MIUI 路径固定取 `data/data/com.tencent.mm/MicroMsg/testuser/EnMicroMsg.db`（`AndroidAnalyzerCore.cpp:224`），暂存后交给 `parseWeChatEnhanced(tempPath, wechatPassword_)`。密码来源有三层：`--wechat-password` 参数显式给；不给时 `WeChatDecryptor::derivePassword` 从镜像里找 UIN，IMEI 无从获取时用占位值，拼起来做 `MD5(IMEI+UIN)` 取前 7 位。推导与版本矩阵的真实代码：

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

做什么/为什么：微信把 UIN 存在两个 shared_prefs XML 里（`<int name="_auth_uin" value="..."/>`），这里不做完整 XML 解析而是字符串定位 + 200 字符窗口约束，防误命中同名属性；IMEI 在镜像里拿不到（新版 Android 限制），硬编码占位值——所以**自动推导在无 IMEI 的设备上大概率失败，需要人工给密码**（已登记的坑）。`OPENSSL_cleanse` 清掉拼接串是密钥卫生习惯。拿到密码后 `openDatabase`（第 28-60 行）按"SQLCipher v4 默认 → v2 传统参数（4000 轮 KDF + SHA1 HMAC）→ 全版本矩阵"的顺序尝试打开。矩阵本体在 `SqlCipherDatabase.cpp:88-112`：

```cpp
// SqlCipherDatabase.cpp:88-112（节选）
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

边界与错误路径：每个候选配置的验证方式是 `PRAGMA key` 之后读 `sqlite_master`（`SqlCipherDatabase.h:63` 的返回值契约），读得出 schema 才算密码+参数都对了；全部失败则 `lastError_` 记 "Failed to decrypt database with provided password"。打开成功后走 `parseWeChatContacts/parseWeChatChatrooms/identifyWeChatOwner` 加增强消息解析（声明在 `AndroidAnalyzerDeclarations.h:166-169`），分别落 wechat_contacts、wechat_chatrooms、wechat_owner_info、wechat_messages 表。MIUI 模式则改成枚举备份里所有微信库成员逐个处理（`AndroidAnalyzerCore.cpp:185-222`）。

**链路三：MIUI 备份的清单化、建索引与库盘点。** `initialize()` 识别 miui-backup 模式后立刻 `persistMiuiBackupAnalysis`（`AndroidAnalyzerCore.cpp:137-144`）：`writeMiuiManifest` 把 descript.xml 解析成 `BackupMeta`，写 miui_backup_manifest 和每个包一行 installed_apps；`writeAppDbInventory` 遍历 `apps/<包名>/db/` 下的每个 SQLite，能读的逐表记行数与列名，读不了的（加密/损坏）也写一行失败记录而不是静默跳过（`MiuiArtifactParsers.h:16-22` 注释），整个过程在一个事务里，失败不会留下"看似完整的半成品"（同文件第 25-26 行）。`.bak` 建索引的真实代码：

```cpp
// MiuiBackupExtractor.cpp:138-154
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

做什么：对清单里每个 `.bak`，先用 `parseAndroidBackupHeader` 拿到 `payloadOffset/compression/encryption`（加密的登记 `encrypted_locked` 后跳过、compression 非 0/1 报不支持，见上方第 125-136 行），然后 `TarIndex::build` 一次线性扫描建成员名→偏移表，最后只把属于 `apps/<包名>/` 前缀的成员挂进全局 `entryOwner_` 映射。为什么按前缀过滤：MIUI 备份的 tar 里还有缓存等无关内容，全挂进映射既浪费内存又可能让同名成员互相遮蔽。失败行为是登记一条 `parse_error` 后 `continue`——单个坏包不拖垮整个备份的解析。这个盘点有大量防失控限额（单库 512MB、bundle 768MB、清单 1 万行、候选 10 万个，见 `MiuiArtifactParsers.cpp:32-50` 的常量表，候选上限可用环境变量 `TRACELENS_MIUI_MAX_CANDIDATES` 收紧），防止一个畸形备份拖死分析。

## 6. 与 LLM 的协作

`analyzeAndroidData()` 的最后一 phase 是 `analyzeWithLLM()`（`AndroidAnalyzerCore.cpp:260-332`）。跳过条件两条：`--no-ai`（`setSkipAI`）或未配置 `LLM_BASE_URL`（本地 LM Studio/Ollama/vLLM 不需要 key，所以门禁是 URL 而不是 key，见第 268-273 行注释）。真正干活的是 `AndroidLLMAnalysisService`（`src/network/HTTPServer/AndroidLLMAnalysisService.h`）：它覆盖 14 种工件类型（SMS、各聊天消息、联系人、通话、MIUI 清单、微信/QQNT 结构化记录、系统日志、设备标识、WiFi），模式与 Linux/Windows 的同名服务一致——建库时给 14 张工件表幂等地补 5 个 `llm_*` 列（`AndroidAnalysisDatabase.cpp:34-48` 的 `kLlmTables` 列表），分析时用 `SELECT_..._PENDING_ANALYSIS` 取未分析行、拼 JSON prompt 发给 `ModelRouter::chat()`、结果原地 UPDATE 回写。默认每类最多 1000 条（`options.maxArtifacts`，`AndroidAnalyzerCore.cpp:311`）。

## 7. 与其他模块的协作 / 注意事项

- **依赖**：TSK/FileExtractor（物理镜像模式）、libzip（zip 模式，编译期 `HAVE_LIBZIP`）、SQLCipher（`HAVE_SQLCIPHER`；没有它时加密库只能标记 `encrypted_no_sqlcipher_build`，见 `AndroidLogicalParsers.cpp:424`）、OpenSSL（MD5）。
- **密码参数**：`--wechat-password`（微信）、`--backup-password-stdin` / `--backup-password-fd <N>`（MIUI 备份 AES 口令，安全读入实现见 `AnalysisOrchestrator.cpp:39-129`）；HTTP 模式用完即 `clear_backup_password` 清除（`TaskManagerAnalysis.cpp:142`）。
- **坑**：`derivePassword` 的 IMEI 拿不到时硬编码占位 `1234567890ABCDEF`（`WeChatDecryptor.cpp:100`）——新版设备 IMEI 不可读，此时自动推导大概率失败，需要人工给密码；Chrome 历史按 `app_chrome/Default/History` 单 profile 取，多 profile（Profile 1/2…）不覆盖；zip 模式没编 libzip 时初始化直接失败。
- **`analyze(rootPath)` 与 `parseWhatsApp` 等一批公有接口是早期遗留**，现行流水线只走 `initialize() → analyzeAndroidData()`；阅读代码时以 `AndroidAnalyzerCore.cpp` 的调用顺序为准。
- **下游**：HTTP 模式下 android.db 的查询路由（含 MIUI 专用查询）会回退到任务的 output_files_db，逻辑任务里它就是 android.db 本身（`TaskManagerAnalysis.cpp:612-621` 的注释解释了这个约定）。

## 8. 如何验证与扩展

- 测试：`tests/UnitTest/test_android_analyzer_gtest.cpp`（核心解析）、`test_android_logical_source_gtest.cpp`（三种逻辑源后端）、`test_miui_backup_gtest.cpp`（备份清单/索引）、`test_wechat_decryptor_gtest.cpp`（SQLCipher 矩阵与密钥推导）、`test_sqlcipher_database_gtest.cpp`。构造假证据源的常用办法是手工 SQLite/zip/tar 组装。
- 加新应用证据：在 `analyzeAndroidData()` 里加一行 `extractAndParseDB(<镜像内相对路径>, "<解析器名>")`，在 `AndroidDataParsers.cpp` 写解析函数并在 `extractAndParseDB` 的分派链里挂上；新表加到 `android_analysis_sql.h` 的 `CREATE_ALL_TABLES`，插入方法加在 `AndroidAnalysisDatabase.cpp`。如果新证据也要 LLM 分析，记得把表名加进 `kLlmTables` 并在 `AndroidLLMAnalysisService` 注册类型。
- 加新证据源后端：实现 `IFileExtractor::extractFileByPath`，在 `initialize()` 的 switch 里挂分支，上游（TaskManager/AnalysisOrchestrator）加对应 `--android-source` 值即可，全部解析器自动可用。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
