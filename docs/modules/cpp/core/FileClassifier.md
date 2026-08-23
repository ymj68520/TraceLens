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

## 4. 工作流程走读

`classifyAndExtract()`（`FileClassifier.cpp:36-55`）四步：

1. `openDatabases()`（`:57-81`）：对输出 files.db 应用 WAL + synchronous=NORMAL + busy_timeout（`:76-78`）。此处代码注释（`:70-75`）详细记录了不开 PRAGMA 的后果——真实磁盘上每 commit fsync 卡 jbd2、进程 D 态数分钟，是全系统最重要的性能教训之一。
2. `createCategoryTables()`（`:83-190`）：先建主表（模板 `CREATE_MAIN_FILES_TABLE`）并做 partition_num 的 ALTER 迁移（`:94-97`），然后遍历 24 个类别，用 `%TABLE_NAME%` 占位符模板替换生成每张分表的 DDL（`:130-181`），同样附 ALTER 迁移与三个索引；最后建 summary/统计/已删除三个视图（`:184-187`）。
3. `classifyFiles()`（`:192-308`）：单个大事务内逐行读 raw.db 的 REG 文件（`:193-198`），`determineCategory` 判类后**双写**：分类分表 INSERT（`:240-260`）与主表 INSERT（`:267-291`，携带 category 与场景三列）。结束提交并打印各类统计（`:300-305`）。
4. 关库、审计（`:52`）。

注意每行的两条 INSERT 都是现场 prepare/finalize（`:246, 273`）——正确但慢，是大镜像分类的已知优化点（见第 6 节）。

## 5. 与其他模块的协作

- **上游 DatabaseManager/raw.db**：只读输入；FileFilter 若生效则输入是过滤库（CLI 流水线 `AnalysisOrchestrator.cpp:232-245`）。
- **ConfigManager**：`EXTRA_<类别>_EXTS` 提供运行时扩展名增补（`ConfigManager.cpp:159-173`），初始化映射时合并。
- **EncryptionUtils**（同目录）：加密判定是判定链第一环；它直接读磁盘上的（解密后）内容，因此分类前若镜像仍加密，结果会偏向 ENCRYPTED。
- **平台 Analyzer**（下游反向依赖）：AndroidAnalyzer 等写 files.db 的 artifacts 表时依赖主表已存在——所以 CLI 流水线在平台分析前 `classifier.reset()` 释放锁（`AnalysisOrchestrator.cpp:272-273`）。
- **LLMAnalysisService / TOONExporter**：按主表 category/llm_* 列工作；TOON 默认导出字段含 category（TOONExporter.cpp:236-238）。
- 出错时行为：建表失败返回 false 中止；逐行 INSERT 失败被忽略（未检查 step 返回值），表现为分表行数略少——统计对账时以主表为准。

## 6. 注意事项与已知问题

- **分表与主表数据重复且无事务外的一致性校验**；分表没有 llm_/scene_ 列，任何"按 LLM 结果筛选"都必须查主表。
- **子串匹配的误报面**：`filenameMatches` 的第三条规则是"包含即命中"（`FileClassifier.cpp:601-603`），`isLogFile` 同样（`:538-547`）。名为 `access_notes.docx` 的文档会被 pathContains/文件名规则带偏的概率存在，判定链前段的高优先级规则（加密/数据库）已尽量兜住高价值场景。
- **性能**：逐行 prepare、每行两次 INSERT；几十万文件时分类阶段耗时可观。WAL PRAGMA 已是底线保障，进一步优化方向是语句复用 + 批量绑定。
- `FileClassifier.cpp.backup` 是同一目录下的历史备份文件，不参与编译，勿引用。
- 分类只在 `type='REG'` 上进行（`:197`），目录/符号链接不进 files.db——前端"文件总数"与 raw.db 行数的差额由此而来。

## 7. 如何验证与扩展

- 单元测试：`tests/UnitTest/test_file_classifier.cpp`（`tests/CMakeLists.txt:474`，测试名 `FileClassifierTests`），覆盖判定链与表名映射。
- 手工验证：`sqlite3 <files.db> "SELECT category, COUNT(*) FROM files GROUP BY 1 ORDER BY 2 DESC"` 应与控制台打印的统计一致；抽查 `SELECT name FROM encrypted_files LIMIT 5` 验证判定链第一环。
- 扩展新类别：(1) `FileClassifier.h` 枚举加值；(2) `getCategoryName`/`getCategoryTableName` 加分支；(3) `FileClassifier.cpp:103-128` 的类别向量加入新值（分表自动由模板生成）；(4) 视需要往判定链插入规则——注意插入位置即优先级，越靠前越强势；(5) 旧 files.db 不会自动长出新分表，重跑分类才生成。

**最后更新**: 2026-08-23（解释式重写）
