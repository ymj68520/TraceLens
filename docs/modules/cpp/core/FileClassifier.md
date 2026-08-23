# FileClassifier（src/core/DatabaseManager/FileClassifier/）

> **一句话**：把 raw.db 的文件清单翻译成"分类后的 files.db"——为每个文件判定 24 个类别之一，写入主 files 表（带 category 与场景标注）和对应的分类分表，为后续的 LLM 分析、TOON 导出、前端筛选提供类别维度。

## 1. 为什么有这个模块

几十万个文件的原始清单对调查者几乎不可用："找出所有图片"、"只看加密卷"、"排除系统缓存"是第一层诉求，纯扩展名判断又过于粗糙——`.db` 可能是聊天证据、加密容器或者是浏览器缓存。分类器要综合扩展名、路径、文件名模式、甚至文件内容（熵与魔数）来给出一个稳定的类别标签。

第二个动机是**削减下游成本**。LLM 分析、全文索引、人工翻看都不应该处理全部文件：类别决定谁值得送进 LLM（文档/数据库类）、谁可以直接跳过（FS_METADATA/缓存）。类别同时是 files.db 里 24 张分表的行路由依据——"每类一张表"的设计让"给我所有 Databases"变成一张表的扫描。

第三个动机是**场景感知（scene-aware）**。同一个文件在不同调查场景下价值不同：Android 取证里 `/data/` 下的 db 是高价值证据，Windows 场景里它可能只是缓存。`setSceneType()` 让分类器在判类之外再打上 `scene_priority`（0-100）与 `scene_relevant` 标志，HTTP 流水线的 LLM 阶段据此挑选"值得花 token"的文件。

## 2. 在系统中的位置

分类是 HTTP 流水线 FILE_CLASSIFICATION 阶段（权重 15）与 CLI 流水线第 3 步的执行者，调用点：`src/network/HTTPServer/TaskManagerAnalysis.cpp:313` 与 `src/AnalysisOrchestrator.cpp:249-269`（后者还会按 `--android-analyze` 等旗标设置 SceneType，`:252-264`）。

数据流：读 raw.db（或过滤后的 `<base>_filtered.db`）files 表 → 写 files.db。输出库中，主 files 表是权威（含 category、llm_*、scene_* 列），24 张分类表是按类别的物化视图（**没有 llm 列**，`SQL/file_classifier_sql.h:41-55` 的模板与 `:14-38` 的主表对比可见）。下游：LLMAnalysisService 按 category 挑文件、TOONExporter 查主表、前端按类别统计。

```
raw.db files(type='REG') ──classifyFiles──> files.db
                                             ├─ files（主表: category/scene_*/llm_*）
                                             └─ images / videos / ... / unknown_files（24 张分表）
```

## 3. 核心概念与设计

**24 值的类别枚举是唯一权威**（`FileClassifier.h:11-43`）：12 个通用类（IMAGE…ENCRYPTED）+ OS 三类（OS_CONFIG/OS_BOOT/OS_LIBRARY）+ 文件系统两类（FS_JOURNAL/FS_METADATA）+ 精化七类（LOG_FILE/CACHE/TEMP/BACKUP/FONT/CERTIFICATE）+ UNKNOWN。类别名到表名的映射集中在 `getCategoryTableName`（`FileClassifier.cpp:453-481`），如 `AUDIO → audio_files`、`FS_JOURNAL → fs_journal`。

**判定链按优先级短路**（`determineCategory`，`FileClassifier.cpp:310-421`），顺序本身就是取证判断的排序：

1. **加密检测**（`:331-333`）调 `EncryptionUtils::isEncrypted(path)`（魔数 + 高熵，`EncryptionUtils.cpp`）——最高优先级，因为加密文件的真实类型不可知；
2. 文件名模式：系统配置名 / 启动文件 / 日志名（`:336-346`），NTFS 元数据文件（`$MFT`、`$LogFile` 等，`:349-364`），ext4 元数据（`lost+found`、`.journal`，`:366-370`）；
3. **数据库保护条款**（`:378-382`）：扩展名判为 DATABASE 的文件即使名字带 "backup"/".bak" 也保持 DATABASE——注释点名了 `wechat_backup.db` 这类聊天证据不能被埋进 Backup 分表；
4. 路径模式（/etc、/boot、库目录、日志/缓存/临时目录，`:388-411`）；
5. 扩展扩展名表（`:414-417`），最后回落基础扩展名表（`:319-325` 初始化于 `FileClassifierMappings.cpp`）。

模式数据在构造时一次性初始化（`FileClassifier.cpp:26-29` 调 initialize 四兄弟），全部是小写子串匹配（`pathContains`/`filenameMatches`，`:566-607`）——简单但意味着 "debug" 模式会命中任何包含它的路径，接受这种保守误报。

**场景标注**是分类后的附加维度：`calculateScenePriority`/`isSceneRelevant` 按 SceneType 分派到四个规则函数（`FileClassifier_SceneRules.cpp`），priority 常量 CRITICAL=100…IRRELEVANT=0（`FileClassifier.h:55-61`）。SceneType 为 NONE 时全部写 0/空，不改变行为。

**陈旧遗留**：`FileClassifierTypes.h:7-21` 定义了 `forensics` 命名空间下**另一套 13 值的 FileCategory**（IMAGES/VIDEOS…复数命名）。它与 `FileClassifier.h` 的 24 值枚举同名不同义，当前生产代码不使用——新代码一律用 `FileClassifier.h` 的版本，看到复数形式（IMAGES）即知是旧物。

### 3.1 核心数据结构：24 值 FileCategory 枚举（FileClassifier.h:11-43）

```cpp
enum class FileCategory {
	IMAGE,
	VIDEO,
	AUDIO,
	DOCUMENT,
	ARCHIVE,
	EXECUTABLE,
	DATABASE,
	SOURCE_CODE,
	WEB,
	EMAIL,
	SYSTEM,
	ENCRYPTED,

	// Operating System specific files
	OS_CONFIG,      // OS configuration files (/etc/passwd, /etc/fstab)
	OS_BOOT,        // Boot and kernel files (vmlinuz, initrd, grub.cfg)
	OS_LIBRARY,     // System libraries (.so, .dylib, .a)

	// Filesystem specific files
	FS_JOURNAL,     // Filesystem journal files
	FS_METADATA,    // Filesystem metadata

	// Refined general categories
	LOG_FILE,       // Log files
	CACHE,          // Cache files
	TEMP,           // Temporary files
	BACKUP,         // Backup files
	FONT,           // Font files
	CERTIFICATE,    // Certificates and keys

	UNKNOWN
};
```

分组语义逐段看：前 12 个是**内容型通用类**——按"文件承载什么"划分（图片/文档/数据库/加密卷……），是 LLM 分析与人工翻看的主要对象。OS_* 三类按注释是**系统位置型**——`/etc/passwd`、vmlinuz、`.so` 这类"属于操作系统"的文件，取证价值在于重构系统状态而非内容本身。FS_* 两类是**文件系统自体**——$MFT/$LogFile/ext4 journal 是"关于文件系统的文件"，几乎永远是噪声，单独分表是为了能一条 WHERE 排除掉。精化七类是从 SYSTEM/UNKNOWN 里二次剥离的高频类别：LOG_FILE（时间线素材）、CACHE/TEMP（可排除）、BACKUP（旧版本证据）、FONT（噪声）、CERTIFICATE（密钥与证书——安全审计的入口）。UNKNOWN 兜底不解释。三套伴生字典把枚举值射到三个字符串空间：`getCategoryName`（人读名 "Databases"，`:423-451`）、`getCategoryTableName`（表名 "databases"，`:453-481`）、主表 category 列存的是前者——**前端看到的类别字符串是人读名**，写查询时别拿表名去匹配 category 列。

同文件还有两个结构：`SceneType`（NONE/ANDROID/WINDOWS/LINUX/SERVER_CLOUD，`:46-52`）决定场景规则集；`ScenePriority` 常量结构（CRITICAL=100/HIGH=75/MEDIUM=50/LOW=25/IRRELEVANT=0，`:55-61`）是 priority 列的取值刻度，五档之间的语义间距（25 分一档）由场景规则函数内部解释。

### 3.2 核心接口清单

| 签名（FileClassifier.h） | 语义 | 主要调用方 | 失败行为 |
|---|---|---|---|
| `FileClassifier(sourceDbPath, fileDbPath)` | 构造并初始化全部模式表（扩展名/路径/文件名） | TaskManagerAnalysis.cpp:313、AnalysisOrchestrator.cpp:249-269 | 无（初始化是纯内存） |
| `bool classifyAndExtract()` | 全流程：开库→建表→分类→审计 | 两个编排方 | 任一步失败返回 false；行级 INSERT 失败被忽略 |
| `FileCategory determineCategory(filename, path)`（公开供测试） | 单文件判类（判定链入口） | classifyFiles 内部 + 单元测试 | 恒有返回值（UNKNOWN 兜底） |
| `void setSceneType(SceneType)` / `SceneType getSceneType() const` | 设置/读取调查场景 | AnalysisOrchestrator.cpp:252-264 | 无 |
| `int calculateScenePriority(path, filename, category)` | 算场景优先级（0-100） | classifyFiles 主表写入 | SceneType 为 NONE 时上层短路不调 |
| `bool isSceneRelevant(path, filename)` | 场景相关性判定 | 同上 | 同上 |
| `~FileClassifier()` | closeDatabases 释放双库句柄 | 编排方 reset/析构 | 无 |

## 4. 工作流程走读

`classifyAndExtract()`（`FileClassifier.cpp:36-55`）四步：

1. `openDatabases()`（`:57-81`）：对输出 files.db 应用 WAL + synchronous=NORMAL + busy_timeout（`:76-78`）。此处代码注释（`:70-75`）详细记录了不开 PRAGMA 的后果——真实磁盘上每 commit fsync 卡 jbd2、进程 D 态数分钟，是全系统最重要的性能教训之一。
2. `createCategoryTables()`（`:83-190`）：先建主表（模板 `CREATE_MAIN_FILES_TABLE`）并做 partition_num 的 ALTER 迁移（`:94-97`），然后遍历 24 个类别，用 `%TABLE_NAME%` 占位符模板替换生成每张分表的 DDL（`:130-181`），同样附 ALTER 迁移与三个索引；最后建 summary/统计/已删除三个视图（`:184-187`）。
3. `classifyFiles()`（`:192-308`）：单个大事务内逐行读 raw.db 的 REG 文件（`:193-198`），`determineCategory` 判类后**双写**：分类分表 INSERT（`:240-260`）与主表 INSERT（`:267-291`，携带 category 与场景三列）。结束提交并打印各类统计（`:300-305`）。
4. 关库、审计（`:52`）。

注意每行的两条 INSERT 都是现场 prepare/finalize（`:246, 273`）——正确但慢，是大镜像分类的已知优化点（见第 6 节）。

### 4.1 代码走读：openDatabases 的 PRAGMA 教训（FileClassifier.cpp:57-81）

```cpp
	// Apply write-performance pragmas to the output database. Without these,
	// SQLite defaults to journal_mode=DELETE + synchronous=FULL, which forces
	// an fsync (jbd2_log_wait_commit) on every transaction commit. On a real
	// disk this manifests as the classifier stalling for minutes in D state;
	// tmpfs hides it because tmpfs has no journal to wait on.
	// Match the settings DatabaseManager applies: WAL + relaxed sync.
	sqlite3_exec(fileDb_, "PRAGMA journal_mode=WAL;", nullptr, nullptr, nullptr);
	sqlite3_exec(fileDb_, "PRAGMA synchronous=NORMAL;", nullptr, nullptr, nullptr);
	sqlite3_busy_timeout(fileDb_, 5000);
```

逐块解释：注意 PRAGMA 只打在 `fileDb_`（输出库）上，`sourceDb_`（raw.db，只读）不需要。注释记录的是一次真实事故的根因链：DELETE journal + FULL sync 意味着**每个事务提交都等 fsync 返回**，ext4 上 fsync 又要等 jbd2 日志提交（`jbd2_log_wait_commit`），机械盘上就是分钟级 D 态卡顿；而 tmpfs 没有日志层，同一份代码在 /tmp 下测试永远复现不了——"测试环境掩盖性能问题"的教科书案例。WAL 把随机写转成 WAL 追加写，NORMAL 允许提交不等 fsync，两者叠加把每次提交成本降到内存操作级别。busy_timeout 固定 5000ms（硬编码，不走 ConfigManager 的 `DB_BUSY_TIMEOUT_MS`——与 DatabaseManager 的小差异）。三条 exec 的返回值都不检查：PRAGMA 失败只是回退默认性能，不值得中断分类。

### 4.2 代码走读：classifyFiles 的单事务双写（FileClassifier.cpp:192-260）

```cpp
	const char* query = R"(
        SELECT inode, name, path, size, mtime, ctime, type, is_deleted, md5,
               COALESCE(partition_num, 0)
        FROM files
        WHERE type = 'REG';
    )";
    // ... prepare 检查见 :200-206
	std::unordered_map<FileCategory, int> categoryCounts;

	// Begin transaction for better performance
	sqlite3_exec(fileDb_, "BEGIN TRANSACTION;", nullptr, nullptr, nullptr);

	while (sqlite3_step(stmt) == SQLITE_ROW) {
		// ... 10 列读入局部变量（:214-224）
		FileCategory category = determineCategory(name, path);
		categoryCounts[category]++;
		// ... 扩展名提取（:232-237）
		std::string tableName = getCategoryTableName(category);
		std::string insertSql = "INSERT INTO " + tableName +
			" (inode, name, path, size, extension, mtime, ctime, is_deleted, md5, partition_num) "
			"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);";

		sqlite3_stmt* insertStmt;
		sqlite3_prepare_v2(fileDb_, insertSql.c_str(), -1, &insertStmt, nullptr);
		// ... 10 个参数绑定（:248-257）
		sqlite3_step(insertStmt);
		sqlite3_finalize(insertStmt);
```

逐块解释：SELECT 用 `COALESCE(partition_num, 0)` 把旧库（无此列时由迁移补默认 0）与 NULL 行都归一成 0——读侧防御配合写侧迁移。`WHERE type='REG'` 是"只分类常规文件"的硬过滤（`:197`），目录/符号链接直接不进 files.db。整个 while 循环被**一个大事务**包裹（`:211` BEGIN / `:297` COMMIT）：几十万行若逐条自动提交，WAL 下也要付几十万次提交协议成本，事务化是本函数能跑完的前提；代价是中途失败整体回滚、redo 从头来。表名 `INSERT INTO " + tableName` 是字符串拼接——安全的前提是 tableName 来自 `getCategoryTableName` 的 switch 白名单而非用户输入，这是"拼接但可控"的边界案例。每行 prepare/finalize 两条语句（分表 + 主表），SQLite 每次 parse SQL 约 微秒级 × 双倍 × 几十万行，是最大的可优化点；语句缓存（24 张分表 + 主表各留一个常驻 stmt）可整段消除。

### 4.3 代码走读：主表 INSERT 与场景标注（FileClassifier.cpp:262-291）

```cpp
		// Compute scene information
		std::string sceneTypeStr = (sceneType_ != SceneType::NONE) ? getSceneTypeName(sceneType_) : "";
		int priority = (sceneType_ != SceneType::NONE) ? calculateScenePriority(path, name, category) : 0;
		bool relevant = (sceneType_ != SceneType::NONE) ? isSceneRelevant(path, name) : false;

		// Also insert into main files table
		std::string categoryName = getCategoryName(category);
		std::string filesInsertSql = "INSERT INTO files "
			"(inode, name, path, size, extension, category, type, mtime, ctime, is_deleted, md5, partition_num, scene_type, scene_priority, scene_relevant) "
			"VALUES (?, ?, ?, ?, ?, ?, 'REG', ?, ?, ?, ?, ?, ?, ?, ?);";

		sqlite3_prepare_v2(fileDb_, filesInsertSql.c_str(), -1, &insertStmt, nullptr);
		// ... 14 个绑定（inode 到 relevant?1:0，:275-288）
		sqlite3_step(insertStmt);
		sqlite3_finalize(insertStmt);
```

逐块解释：三条三元表达式实现了"场景信息按需计算"——NONE 场景下连规则函数都不调用，priority 写 0、relevant 写 false、scene_type 写空串，列值本身就能区分"没开场景"与"开了但 IRRELEVANT"（后者 priority 为 0 但 scene_type 非空）。主表 INSERT 的 15 列里 `type` 直接内联字面量 `'REG'`（VALUES 段而非占位符）——因为 SELECT 已过滤，这是把不变量写进 SQL 的做法；category 存的是**人读名**（"Databases"），与分表表名（"databases"）是两个字符串空间，跨表对账时要做大小写与格式转换。`relevant ? 1 : 0` 是 SQLite 无布尔类型的惯用收纳。这一段与分表 INSERT 构成双写：两处 step 返回值都不检查，单行失败静默跳过——统计口径以主表为准的原因（见第 6 节）。

### 4.4 代码走读：determineCategory 的判定链头部（FileClassifier.cpp:310-333, 377-386）

```cpp
	// Priority 0: Check for encryption (Magic Bytes & High Entropy)
	// This overrides extension based check if meaningful encryption is detected
	if (EncryptionUtils::isEncrypted(path)) {
		return FileCategory::ENCRYPTED;
	}

	// Priority 1: Check filename patterns for known system files
	if (isSystemConfigFile(filename)) {
		return FileCategory::OS_CONFIG;
	}

	if (isBootFile(filename)) {
		return FileCategory::OS_BOOT;
	}

	if (isLogFile(filename)) {
		return FileCategory::LOG_FILE;
	}

	// ... NTFS/ext4 元数据规则见 :348-375

	// A genuine database file keeps its category even when the name says
	// "backup"/".bak" — e.g. chat-evidence exports like wechat_backup.db must
	// stay visible to database parsers instead of hiding in Backup Files.
	if (category == FileCategory::DATABASE) {
		return FileCategory::DATABASE;
	}

	if (isBackupFile(filename)) {
		return FileCategory::BACKUP;
	}
```

逐块解释：函数开头（`:312-325`）先做扩展名提取与基础判类（结果暂存 `category`），随后才开始覆盖链——这个顺序意味着扩展名结果可以被任何高优先级规则推翻，但最终又作为 Priority 4 的回落值，一次计算两处使用。加密检测放在一切之前：一个 VeraCrypt 容器哪怕叫 `family_photos.jpg`，真实类型也只能是 ENCRYPTED——内容优先于名字是取证判类的基本价值观；代价是**每个文件都要读内容**（魔数+熵采样），这是判定链的主要 I/O 成本。数据库保护条款是判定链里唯一一条"阻止降级"的规则：它夹在"backup 检测"之前，让 `.db` 扩展名优先于 "backup" 名字模式——注释直接给出理由（wechat_backup.db 是聊天证据，埋进 Backup 分表会让数据库解析器看不见）。规则顺序即产品决策，调序前先想清楚证据可见性后果。

### 4.5 代码走读：场景工件表模板与 CREATE_ARTIFACT_TABLE_TEMPLATE（SQL/file_classifier_sql.h:334-357）

```cpp
inline constexpr const char* CREATE_ARTIFACT_TABLE_TEMPLATE = R"(
    CREATE TABLE IF NOT EXISTS %TABLE_NAME% (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id INTEGER REFERENCES files(id),
        artifact_type TEXT NOT NULL,
        artifact_data TEXT,
        extracted_at INTEGER,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
)";

inline constexpr const char* CREATE_SCENE_ARTIFACTS_INDICES = R"(
    CREATE INDEX IF NOT EXISTS idx_android_artifacts_file_id ON android_artifacts(file_id);
    ...
    CREATE INDEX IF NOT EXISTS idx_linux_artifacts_type ON linux_artifacts(artifact_type);
)";
```

逐块解释：files.db 里还有一族**场景工件表**——`android_artifacts`/`windows_artifacts`/`linux_artifacts` 三张，同一模板 `%TABLE_NAME%` 替换生成，各带 file_id/type 两索引。设计意图是"工件挂在主表 files(id) 下"（真正的外键引用，`REFERENCES files(id)`——files.db 全库唯一显式 FK）；但生产平台分析器实际写的是各自的专用工件表（registry_values、prefetch_info 等，见各 Analyzer 文档），**这三张泛型 artifacts 表当前没有写入方**——是"统一场景工件"构想的 schema 预留，与 EventExtractor 的 system_events 同属建而不用的表。查库时看到它们为空属正常，不要当成平台分析失败的信号。

## 5. 与其他模块的协作

- **上游 DatabaseManager/raw.db**：只读输入；FileFilter 若生效则输入是过滤库（CLI 流水线 `AnalysisOrchestrator.cpp:232-245`）。
- **ConfigManager**：`EXTRA_<类别>_EXTS` 提供运行时扩展名增补（`ConfigManager.cpp:159-173`），初始化映射时合并（键名为大写类别名，如 `EXTRA_IMAGE_EXTS`）。
- **EncryptionUtils**（同目录）：加密判定是判定链第一环；它直接读磁盘上的（解密后）内容，因此分类前若镜像仍加密，结果会偏向 ENCRYPTED。
- **平台 Analyzer**（下游反向依赖）：AndroidAnalyzer 等写 files.db 的 artifacts 表时依赖主表已存在——所以 CLI 流水线在平台分析前 `classifier.reset()` 释放锁（`AnalysisOrchestrator.cpp:272-273`）。
- **LLMAnalysisService / TOONExporter**：按主表 category/llm_* 列工作；TOON 默认导出字段含 category（TOONExporter.cpp:236-238）。
- 出错时行为：建表失败返回 false 中止；逐行 INSERT 失败被忽略（未检查 step 返回值），表现为分表行数略少——统计对账时以主表为准。
- 表契约：files.db = 主表 files（含 category/scene_type/scene_priority/scene_relevant/llm_*）+ 24 张 `<category>_files` 分表（无 llm 列，各带 path/extension/size 三索引）+ summary/extension 统计/deleted 三视图。

## 6. 注意事项与已知问题

- **分表与主表数据重复且无事务外的一致性校验**；分表没有 llm_/scene_ 列，任何"按 LLM 结果筛选"都必须查主表。
- **子串匹配的误报面**：`filenameMatches` 的第三条规则是"包含即命中"（`FileClassifier.cpp:601-603`），`isLogFile` 同样（`:538-547`）。名为 `access_notes.docx` 的文档会被 pathContains/文件名规则带偏的概率存在，判定链前段的高优先级规则（加密/数据库）已尽量兜住高价值场景。
- **性能**：逐行 prepare、每行两次 INSERT；几十万文件时分类阶段耗时可观。WAL PRAGMA 已是底线保障，进一步优化方向是语句复用 + 批量绑定。
- `FileClassifier.cpp.backup` 是同一目录下的历史备份文件，不参与编译，勿引用。
- 分类只在 `type='REG'` 上进行（`:197`），目录/符号链接不进 files.db——前端"文件总数"与 raw.db 行数的差额由此而来。
- **单事务的内存/锁代价**：BEGIN 到 COMMIT 之间 files.db 持有写锁，分类期间其他进程只能读（WAL 下读不阻塞）——这也是编排方强调"分类完 reset 再让平台分析器写"的原因。
- `EncryptionUtils::isEncrypted(path)` 按路径读的是**运行环境下的磁盘文件**（CLI 挂载目录或提取产物），不是镜像内偏移——镜像未先解密/挂载时判类会系统性偏向 ENCRYPTED。

## 7. 如何验证与扩展

- 单元测试：`tests/UnitTest/test_file_classifier.cpp`（`tests/CMakeLists.txt:474`，测试名 `FileClassifierTests`），覆盖判定链与表名映射。
- 手工验证：`sqlite3 <files.db> "SELECT category, COUNT(*) FROM files GROUP BY 1 ORDER BY 2 DESC"` 应与控制台打印的统计一致；抽查 `SELECT name FROM encrypted_files LIMIT 5` 验证判定链第一环。
- 扩展新类别：(1) `FileClassifier.h` 枚举加值；(2) `getCategoryName`/`getCategoryTableName` 加分支；(3) `FileClassifier.cpp:103-128` 的类别向量加入新值（分表自动由模板生成）；(4) 视需要往判定链插入规则——注意插入位置即优先级，越靠前越强势；(5) 旧 files.db 不会自动长出新分表，重跑分类才生成。

## 8. 产出表列级说明（files.db 全量）

**主表 files（21 列，SQL/file_classifier_sql.h:14-37）**：

| 列名 | 类型 | 含义 | 写入条件 |
|---|---|---|---|
| `id` | INTEGER PK 自增 | 行号 | 自动 |
| `inode`/`name`/`path`/`size` | INTEGER/TEXT | 从 raw.db 复制 | classifyFiles 每行（type='REG'） |
| `extension` | TEXT | 小写扩展名（无点） | 提取自 name |
| `category` | TEXT | **人读名**（"Databases"，getCategoryName） | determineCategory 结果 |
| `type` | TEXT | 恒 'REG'（字面量内联） | 同上 |
| `mtime`/`ctime` | INTEGER | 两时间戳（注意 raw.db 四个里只带两个） | 复制 |
| `is_deleted` | INTEGER | 删除标志 | 复制 |
| `md5` | TEXT | 哈希 | 复制 |
| `partition_num` | INTEGER DEFAULT 0 | 分区号 | COALESCE 归一后复制 |
| `llm_summary`/`llm_description`/`llm_keywords`/`llm_analyzed_at`/`llm_model_used` | TEXT/INTEGER | LLM 回写五列 | 建表即有；分类不写，LLMAnalysisService UPDATE（storeDescription，LLMAnalysisService.cpp:367 一带） |
| `scene_type` | TEXT | 场景名（空串=未开场景） | sceneType_!=NONE 时写 |
| `scene_priority` | INTEGER DEFAULT 0 | 0-100 | 同上 |
| `scene_relevant` | INTEGER DEFAULT 0 | 0/1 | 同上 |

主表索引 3 个（:142-144）：path、category、llm_analyzed_at——category 索引是前端类别筛选的支点，llm 索引服务"未分析文件"扫描（`WHERE llm_analyzed_at IS NULL`，file_classifier_sql.h:105）。

**24 张分类分表（各 11 列，:41-55 模板）**：`id`（PK 自增）、`inode`、`name`、`path`、`size`、`extension`、`mtime`、`ctime`、`is_deleted`、`md5`、`partition_num DEFAULT 0`——即主表去掉 category/type/llm_*/scene_* 的精简集。每分表 3 索引（path/extension/size 模板，:148-150）。表名映射 24 对（getCategoryTableName，FileClassifier.cpp:453-481），如 IMAGE→images、DATABASE→databases、FS_JOURNAL→fs_journal、UNKNOWN→unknown_files。

**analysis_progress（:63 附近）**：分类进度表（由模板建出但当前分类路径不写行——进度审计走 AuditLog）。

**android/windows/linux_artifacts 三张（:334 模板）**：10 列（id/file_id FK/artifact_type/artifact_data/extracted_at/llm_* 5 列），无生产写入方（4.5 节）。

**视图 4 个**：`file_summary`（:157，按类别聚合）、`extension_statistics`（:214）、`deleted_files`（:247）、`scene_file_summary`（:360，带场景维度）。

**file_descriptions（运行期建）**：不在 SQL 头文件里——LLMAnalysisService 在首次写入时 `CREATE TABLE IF NOT EXISTS`（LLMAnalysisService.cpp:399-411，file_path/description/summary/keywords/model_used/is_relevant/created_at 7 列），作为主表 llm_* 的平行副本供调查中心读取（:394 注释）。schema 审计时别漏了这张"代码里建的表"。

## 9. 方法全清单（含私有与伴生文件）

| 方法 | 定义位置 | 语义 | 调用方 |
|---|---|---|---|
| `classifyAndExtract()` | FileClassifier.cpp:36-55 | 四步主流程 | TMA:313、Orchestrator:249 |
| `openDatabases()`（私有） | :57-81 | 双库连接+输出库 PRAGMA | classifyAndExtract |
| `createCategoryTables()`（私有） | :83-190 | 主表+24 分表+工件表+3 索引模板+4 视图 | 同上 |
| `classifyFiles()`（私有） | :192-308 | 单事务双写循环 | 同上 |
| `determineCategory(name, path)` | :310-421 | 判定链（公开供测试） | classifyFiles/测试 |
| `getCategoryName(category)` | :423-451 | 枚举→人读名 | 主表写入/前端 |
| `getCategoryTableName(category)` | :453-481 | 枚举→分表名 | 分表写入 |
| `calculateScenePriority(path,name,cat)` | FileClassifier_SceneRules.cpp | 场景分派四规则 | 主表写入 |
| `isSceneRelevant(path,name)` | 同上 | 相关性判定 | 同上 |
| `setSceneType/getSceneType` | .h | 场景开关 | Orchestrator:252-264 |
| `closeDatabases()`（私有） | :57 一带 | 双库关闭 | 析构 |
| 模式初始化四兄弟 | FileClassifierMappings.cpp | 扩展名/路径/文件名/元数据模式表（含 EXTRA_* 合并，12 处调用 getExtraExtensions） | 构造（:26-29） |
| 匹配三件套 `pathContains/filenameMatches/isLogFile 等` | :566-607 | 小写子串匹配 | 判定链 |

## 10. 关联矩阵

| 对端 | 方向 | 交互点 | 数据形态 |
|---|---|---|---|
| raw.db / filtered.db | 输入 | `SELECT ... WHERE type='REG'` 10 列 | 流式 |
| files.db 28+ 对象 | 输出 | 主表/24 分表/3 空工件表/4 视图 | 参数化 INSERT（表名拼接白名单） |
| ConfigManager | 上游 | EXTRA_<12 类>_EXTS（FileClassifierMappings.cpp 12 处） | vector<string> |
| EncryptionUtils | 下游 | isEncrypted(path) 每文件一次 | bool |
| TaskManagerAnalysis:313 / Orchestrator:249-273 | 上游 | 构造/sceneType/分类/reset | 生命周期 |
| 平台 Analyzer | 下游（锁依赖） | 等 classifier.reset() 后写 files.db | 工件表 |
| LLMAnalysisService | 下游 | 主表 category 挑选 + llm_* UPDATE + file_descriptions | SELECT/UPDATE |
| TOONExporter | 下游 | 主表全列查询 | SELECT |
| AuditLog | 下游 | CLASSIFICATION_* 两条 | 审计 |

## 11. 配置影响表

| 参数 | 默认 | 影响 | 备注 |
|---|---|---|---|
| `EXTRA_<CATEGORY>_EXTS`（12 类） | 空 | 运行时扩展名增补（ConfigManager.cpp:159-173） | 逗号分隔；不强制带点/大小写 |
| `DB_JOURNAL_MODE` 等 | — | **不适用**：openDatabases 硬编码 WAL+NORMAL+5000（:76-78），不走 ConfigManager | 与 DatabaseManager 的差异 |
| 无其他键 | — | 判定链/场景规则硬编码 | |

## 12. 性能与并发细节

- **判定链的 IO 大头是加密检测**：每文件一次 `EncryptionUtils::isEncrypted(path)` 读文件头与熵采样——几十万文件时是分类阶段的磁盘主成本（其余判定全内存）。镜像内容若在远端挂载，分类时长≈网络读头时长。
- **双写 + 三索引的写放大**：主表 INSERT 维护 path/category/llm_analyzed 三索引，分表维护三索引；单大事务包裹下提交一次，B 树维护是 CPU 端大头。
- **prepare 次数 = 行数 × 2**：两条 INSERT 均现场 prepare（:246,273）；语句常驻可省约 30-50% 分类时长（经验值，取决于行数）。
- **锁语义**：大事务期间 files.db 独占写（WAL 读不阻塞）；sourceDb（raw/filtered）全程只读共享。分类器对象存活即持双连接——编排方必须 reset（Orchestrator:273）才释放。
- **内存**：流式行处理 + categoryCounts 一个 map；模式表（构造期一次性，百级字符串）常驻 KB 级。峰值内存 ≈ 单行数据。
- **可调参数影响**：EXTRA_* 只影响扩展名层（判定链第 5 优先级），无法覆盖加密/元数据等高优先级规则；无并发参数。


## 13. 类别→表名全映射与场景规则速查

**24 对映射**（getCategoryTableName，FileClassifier.cpp:453-481；default 分支兜底 unknown_files）：

| 类别 | 表名 | 类别 | 表名 |
|---|---|---|---|
| IMAGE | images | FS_JOURNAL | fs_journal |
| VIDEO | videos | FS_METADATA | fs_metadata |
| AUDIO | audio_files | LOG_FILE | log_files |
| DOCUMENT | documents | CACHE | cache_files |
| ARCHIVE | archives | TEMP | temp_files |
| EXECUTABLE | executables | BACKUP | backup_files |
| DATABASE | databases | FONT | font_files |
| SOURCE_CODE | source_code | CERTIFICATE | certificates |
| WEB | web_files | UNKNOWN | unknown_files |
| EMAIL | email_files | SYSTEM | system_files |
| OS_CONFIG | os_config_files | OS_BOOT | os_boot_files |
| ENCRYPTED | encrypted_files | OS_LIBRARY | os_libraries |

命名风格不统一（复数 files 后缀 vs 裸复数 vs 无后缀，audio_files vs images），是 grep 表名时容易漏的原因——写查询请以本表为准。人读名（getCategoryName，:423-451）是另一套："Images"/"Videos"/"Audio Files"/"Databases"/"Encrypted Files" 等，存进主表 category 列。

**场景优先级规则**（FileClassifier_SceneRules.cpp:41-174，四场景各一张"路径→档位"表，relevant = priority ≥ MEDIUM(50)）：

| 场景 | CRITICAL(100) 路径 | HIGH(75) 路径 | 其他 |
|---|---|---|---|
| ANDROID | /data/data/、/data/system/、含 com.android.providers.contacts/telephony 的路径（:70-85） | /data/misc/、/system/build.prop、/data/app/、/data/user/、含 com.tencent.mm/org.telegram.messenger/com.whatsapp 的路径（:87-97） | IM 应用包名单内建 |
| WINDOWS | Windows/System32/config/、Windows/System32/winevt/ | Windows/Prefetch/、$Recycle.Bin/ | :122-131 |
| LINUX | /var/log/、/etc/、/var/spool/cron/ | /home/、/root/、/var/lib/docker/ | :163-174 |
| SERVER_CLOUD | （按类别：配置/日志类 CRITICAL，:141-153） | — | |

SceneType::NONE 短路（第 3 节）；scene_type 列存小写名（"android"/"windows"/"linux"/"server_cloud"，:33-36）。`server_cloud` 场景无 CLI 旗标入口（SceneType 枚举有值但编排层不设置），属于 HTTP 侧预留。

**最后更新**: 2026-08-24（二轮深化：补全表列说明与方法清单）
