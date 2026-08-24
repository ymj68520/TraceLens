# files.db 字段参考（定义位置：`src/core/DatabaseManager/SQL/file_classifier_sql.h`；`analysis_progress`/`file_descriptions` 补充定义见文内）

> files.db 是 raw.db 的**分拣 + LLM 观点**（DatabaseSchema.md 决定二）：回答"几十万个文件里哪些值得看"。分类是手段，场景优先级和 LLM 结论才是目的——所以 LLM 列和场景列放在**每行都在**的主 `files` 表上，而 24 张分类表只是按类别物化的查询副本。schema 就是代码（决定三）：全部建表语句以常量形式集中在 `file_classifier_sql.h`，改表必须过编译。

## 库概览

| 项 | 内容 |
|----|------|
| 谁写 | `FileClassifier::createCategoryTables()`（`FileClassifier.cpp:83-190`：主表、24 分类表、索引、3 视图）与 `classifyFiles()`（写主表 + 分类表，INSERT 模板 `file_classifier_sql.h:302-308`）；`LLMAnalysisService` 写 `analysis_progress` 与 `file_descriptions`（`src/network/HTTPServer/LLMAnalysisService.cpp:399`）；平台分析器在 CLI 集成模式写 `android/windows/linux_artifacts`（如 `AndroidAnalysisDatabase.cpp:57-66`） |
| 谁读 | HTTP 查询路由、Web 前端文件页、LLM 分析调度（`SELECT_FILES_PENDING_ANALYSIS`/`SELECT_SCENE_FILES_FOR_LLM`）、Python 侧重分析/报告/图谱摄取（`persist_to_files_db` 回写主表 llm_*，见 `LLMAnalysisService.cpp:394-397` 注释） |
| 文件位置 | HTTP 任务 `data/tasks/<task_id>/files.db`；CLI `<image>_files.db`（CLI 模式下平台工件并入本库） |
| 写入性能 | 打开即设 WAL + synchronous=NORMAL（`FileClassifier.cpp:76-77`） |

## 表清单总表

| 表 | 分组 | 一句话用途 | 列数 |
|----|------|-----------|------|
| `files` | 主表 | 全量文件分类结果：category + LLM 列 + 场景列 | 21 |
| `images` … `unknown_files`（24 张） | 分类物化 | 按 `FileCategory` 物化的查询副本 | 各 11 |
| `analysis_progress` | LLM 进度 | LLM 批量分析的任务级进度 | 8 |
| `file_descriptions` | LLM 证据 | 调查中心证据清单（含 is_relevant） | 7 |
| `android_artifacts` | 场景工件 | Android 场景工件（CLI 集成模式） | 10 |
| `windows_artifacts` | 场景工件 | Windows 场景工件（CLI 集成模式） | 10 |
| `linux_artifacts` | 场景工件 | Linux 场景工件（CLI 集成模式） | 10 |

### 24 张分类表与 `FileCategory` 的对应（`FileClassifier.cpp:103-128` 枚举顺序）

| FileCategory | 表名 | FileCategory | 表名 |
|--------------|------|--------------|------|
| IMAGE | `images` | FS_JOURNAL | `fs_journal` |
| VIDEO | `videos` | FS_METADATA | `fs_metadata` |
| AUDIO | `audio_files` | LOG_FILE | `log_files` |
| DOCUMENT | `documents` | CACHE | `cache_files` |
| ARCHIVE | `archives` | TEMP | `temp_files` |
| EXECUTABLE | `executables` | BACKUP | `backup_files` |
| DATABASE | `databases` | FONT | `font_files` |
| SOURCE_CODE | `source_code` | CERTIFICATE | `certificates` |
| WEB | `web_files` | UNKNOWN | `unknown_files` |
| EMAIL | `email_files` | SYSTEM | `system_files` |
| ENCRYPTED | `encrypted_files` | OS_CONFIG | `os_config_files` |
| | | OS_BOOT | `os_boot_files` |
| | | OS_LIBRARY | `os_libraries` |

（表名由 `getCategoryTableName()` 映射，建表循环见 `FileClassifier.cpp:130-182`。）

## 逐表字段说明

### files（主表）

建表：`CREATE_MAIN_FILES_TABLE`（`file_classifier_sql.h:14-38`）；写入：`INSERT_INTO_FILES_TABLE`（`:306-308`，14 列，`type` 固定 `'REG'`）；LLM 回写：`UPDATE_FILE_LLM_ANALYSIS`（`:85-94`）。

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| inode | INTEGER | — | 源自 raw.db 的文件 inode（跨库逻辑键之一） |
| name | TEXT | — | 文件名 |
| path | TEXT | — | 全路径；索引列，LLM 回写按它定位 |
| size | INTEGER | — | 字节数 |
| extension | TEXT | — | 扩展名（分类输入，raw.db files 无此列） |
| category | TEXT | — | 24 类分类结果（`FileClassifier::determineCategory`，`FileClassifier.cpp:310` 起） |
| type | TEXT | — | 恒 `'REG'`（INSERT 模板字面量，`:308`） |
| mtime | INTEGER | — | 修改时间（unix 秒） |
| ctime | INTEGER | — | 元数据变更时间（unix 秒） |
| is_deleted | INTEGER | — | 1 = 已删除文件 |
| md5 | TEXT | — | 内容 MD5 |
| partition_num | INTEGER | DEFAULT 0 | 分区号，多分区镜像与 inode 联合定位 |
| llm_summary | TEXT | — | LLM 摘要（`UPDATE_FILE_LLM_ANALYSIS`） |
| llm_description | TEXT | — | LLM 详细描述 |
| llm_keywords | TEXT | — | LLM 关键词 |
| llm_analyzed_at | INTEGER | — | 分析时间戳；NULL/0 表示未分析（调度依据） |
| llm_model_used | TEXT | — | 模型名 |
| scene_type | TEXT | — | 场景类型（如 ANDROID/WINDOWS_SERVER/SERVER_CLOUD） |
| scene_priority | INTEGER | DEFAULT 0 | 场景内优先级（>0 才入选 LLM 批，`SELECT_SCENE_FILES_FOR_LLM`，`:424-434`） |
| scene_relevant | INTEGER | DEFAULT 0 | 1 = 场景相关 |

索引（`CREATE_MAIN_FILES_INDICES`，`:141-145`）：`idx_files_path(path)`、`idx_files_category(category)`、`idx_files_llm_analyzed(llm_analyzed_at)`。

迁移：旧库补 LLM 列用 `ALTER_FILES_ADD_LLM_COLUMNS`（5 条，`:75-82`，由 `DatabaseManager::checkAndMigrate` 执行）；补场景列用 `ALTER_FILES_ADD_SCENE_COLUMNS`（3 条，`:401-405`）；补分区列用 `FileClassifier.cpp:95-97` 的内联 ALTER。

**与 raw.db files 的列差异**（同名不同物的典型）：本表多 `extension/category/scene_*`，少 `atime/crtime/is_allocated/permissions/uid/gid`——分拣层只保留排序与展示所需的最小列集。

### 24 张分类表（统一模板 `CREATE_CATEGORY_TABLE_TEMPLATE`，`file_classifier_sql.h:41-55`）

分类表是"按类别物化的查询副本"：仅基础列 + `partition_num`，**不含** LLM/场景列（DatabaseSchema.md 4.1 节强调）。写入：`INSERT_INTO_CATEGORY_TABLE_TEMPLATE`（`:302-304`，9 列）。

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| inode | INTEGER | — | 文件 inode |
| name | TEXT | — | 文件名 |
| path | TEXT | — | 全路径 |
| size | INTEGER | — | 字节数 |
| extension | TEXT | — | 扩展名 |
| mtime | INTEGER | — | 修改时间 |
| ctime | INTEGER | — | 元数据变更时间 |
| is_deleted | INTEGER | — | 删除标志 |
| md5 | TEXT | — | 内容 MD5 |
| partition_num | INTEGER | DEFAULT 0 | 分区号（建表循环里的增量 ALTER，`FileClassifier.cpp:151-156`） |

索引（每表 3 个，模板 `:148-150`，循环替换生成）：`idx_<表>_path(path)`、`idx_<表>_extension(extension)`、`idx_<表>_size(size)`。

逐表小节（列集全部同上模板，索引全部为 path/extension/size 三件套，写入语句同为 `INSERT_INTO_CATEGORY_TABLE_TEMPLATE` 9 列；每表一段取证含义。`file_summary` 视图标签见各节括号）：

#### images（Images）
图片文件。案件里最常见的"内容证据"载体：EXIF 定位、隐写排查、CSAM/涉案影像筛查的第一入口。
#### videos（Videos）
视频文件。与 images 同属多媒体证据组，时长/编码信息常需播放器复核。
#### audio_files（Audio）
音频文件。通话录音、语音备忘。
#### documents（Documents）
文档（Office/PDF/txt）。内容证据主力，LLM 分析的重点对象。
#### archives（Archives）
压缩包。数据外带高发区；解包后的内层文件走雕刻/二次分类。
#### executables（Executables）
可执行文件。恶意样本排查面，与 windows.db 的 amcache/dll 组互证。
#### databases（Databases）
数据库文件（SQLite/bdb 等）。平台库（android/windows/linux.db）的抽取对象正是它们。
#### source_code（Source Code）
源代码与脚本。脚本=行为证据（攻击落地的工具）。
#### web_files（Web Files）
Web 资产（html/js/php/jsp）。webshell 排查的第一过滤器。
#### email_files（Email）
邮件容器（pst/ost/eml/mbox）。
#### system_files（System Files）
系统文件。
#### encrypted_files（Encrypted）
加密容器（gpg/truecrypt/encfs）。密钥线索（android.db 的 encrypted_db_inventory 同思路）。
#### os_config_files（OS Config）
OS 配置文件（sysctl、注册表导出、服务定义）。
#### os_boot_files（OS Boot）
引导链文件（MBR/BCD/grub）。bootkit 排查面。
#### os_libraries（OS Libraries）
系统库（DLL/so）。替换/DLL 劫持攻击面，与 dll_* 表对齐。
#### fs_journal（FS Journal）
文件系统日志（$LogFile/ext4 journal）。反取证（删除后覆写）的取证面。
#### fs_metadata（FS Metadata）
文件系统元数据（$MFT/inode 表）。与 windows.db mft_entries 互补。
#### log_files（Logs）
日志文件。时间线事件（events.db）与平台日志表的主原料。
#### cache_files（Cache）
缓存。用户行为残影（浏览器缩略图、应用 cache）。
#### temp_files（Temp）
临时目录。工具与攻击载荷的落盘痕迹。
#### backup_files（Backup）
备份文件。历史版本证据（改过的文件看旧版）。
#### font_files（Fonts）
字体文件。文档伪造检测（字体嵌入指纹）。
#### certificates（Certificates）
证书与密钥文件。身份锚点与时间锚点。
#### unknown_files（Unknown）
未识别文件（无扩展名等）。兜底分类，防漏。

### analysis_progress（LLM 分析进度）

建表：`file_classifier_sql.h:62-72`（注释标注 Issue 6）；写入：`INSERT_ANALYSIS_PROGRESS`（`:111-114`）→ `UPDATE_ANALYSIS_PROGRESS`（`:116-122`）→ `COMPLETE_ANALYSIS_PROGRESS`（`:124-130`）。

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| task_id | TEXT | PRIMARY KEY | 任务标识（HTTP 任务 id） |
| total_files | INTEGER | — | 本批待分析文件总数 |
| completed_files | INTEGER | — | 已完成数 |
| current_file | TEXT | — | 正在分析的文件路径 |
| started_at | INTEGER | — | 批开始时刻（unix 秒） |
| last_updated | INTEGER | — | 最近进度刷新时刻 |
| status | TEXT | DEFAULT 'running' | 'running' → 'completed'（COMPLETE 语句置位） |

索引：无（task_id 主键即索引）。

### file_descriptions（LLM 描述副本 / 证据清单）

建表 + 写入都是**运行时懒建**：`LLMAnalysisService.cpp:398-408`（CREATE TABLE IF NOT EXISTS 紧跟 UPDATE 主表之后执行），UPSERT 在 `:411-419`。该表是"调查中心证据清单"的落地：C++ 主流水线每写一条 LLM 结论，就同步 `is_relevant=1` 插一行，与 Python 侧 `persist_to_files_db` 行为对齐（`:394-397` 注释）。

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| file_path | TEXT | PRIMARY KEY | 文件全路径（与主表 path 对齐） |
| description | TEXT | — | LLM 描述 |
| summary | TEXT | — | LLM 摘要 |
| keywords | TEXT | — | LLM 关键词 |
| model_used | TEXT | — | 模型名 |
| is_relevant | INTEGER | DEFAULT 0 | C++ 流水线恒写 1（`:413` 字面量），Python 侧可按结论写 0/1 |
| created_at | INTEGER | DEFAULT 0 | 写入时刻 |

索引：无。

### android_artifacts / windows_artifacts / linux_artifacts（场景工件表，CLI 集成模式）

统一模板 `CREATE_ARTIFACT_TABLE_TEMPLATE`（`file_classifier_sql.h:333-346`，`%TABLE_NAME%` 替换为 `android_artifacts` 等）；由各平台分析库在集成模式创建（`AndroidAnalysisDatabase.cpp:57-66`、`WindowsAnalysisDatabase.cpp:48` 附近、`LinuxFilesAnalyzer/Database/Detail/LinuxAnalysisDatabaseCore.cpp:71`）。写入：`INSERT_ARTIFACT_TEMPLATE`（`:409-410`，4 列）；LLM 回写：`UPDATE_ARTIFACT_LLM_TEMPLATE`（`:413-421`）。

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 工件行号 |
| file_id | INTEGER | REFERENCES files(id) | 源文件行（本库主表的外键——全库唯一显式 FK） |
| artifact_type | TEXT | NOT NULL | 工件类型（解析器命名） |
| artifact_data | TEXT | — | 工件内容（序列化文本/JSON） |
| extracted_at | INTEGER | — | 抽取时刻 |
| llm_summary | TEXT | — | LLM 摘要 |
| llm_description | TEXT | — | LLM 描述 |
| llm_keywords | TEXT | — | LLM 关键词 |
| llm_analyzed_at | INTEGER | — | 分析时刻 |
| llm_model_used | TEXT | — | 模型名 |

索引（`CREATE_SCENE_ARTIFACTS_INDICES`，`:349-356`）：每表 `idx_<平台>_artifacts_file_id(file_id)`、`idx_<平台>_artifacts_type(artifact_type)`，共 6 个。

## 视图（SELECT 语义）

| 视图 | 定义行 | SELECT 语义 |
|------|--------|-------------|
| `file_summary` | `:156-211` | 24 个 UNION ALL 分支各算一个类别的 count/SUM(size)/AVG/MAX——分类总览一行一类 |
| `extension_statistics` | `:213-244` | 24 表 UNION 出 (extension,size) 后按扩展名 GROUP BY，按 count 倒序 |
| `deleted_files` | `:246-295` | 24 表各自 `WHERE is_deleted=1` 后 UNION，投影 (类别标签, name, path, size, extension)——已删除文件全景 |
| `scene_file_summary` | `:359-370` | 主表按 scene_type 聚合：总数 / scene_relevant=1 数 / 总大小 / 已 LLM 数 |
| `scene_artifact_summary` | `:373-398` | 三张工件表按 (scene, artifact_type) 聚合计数 + 已分析数 |

执行位置：前 3 个在 `FileClassifier.cpp:185-187`；后 2 个在场景工件库初始化时执行（消费方 `FileClassifierSQL::CREATE_SCENE_*`）。

## 场景列与 LLM 列的消费链

| 消费方 | 语句（`file_classifier_sql.h`） | 用到的列 |
|--------|------|---------|
| LLM 批量调度 | `SELECT_FILES_PENDING_ANALYSIS`（`:103-108`） | path, size, llm_analyzed_at（NULL 判定 + 小文件优先） |
| 场景优先调度 | `SELECT_SCENE_FILES_FOR_LLM`（`:424-434`） | type, llm_analyzed_at, scene_priority（>0 才入选，按优先级降序 + 小文件优先） |
| LLM 回写 | `UPDATE_FILE_LLM_ANALYSIS`（`:85-94`） | llm_* 5 列 + path（且要求 path 唯一） |
| 读回 | `SELECT_FILE_LLM_ANALYSIS`（`:97-100`） | llm_* 5 列 |
| 进度页 | `SELECT_ANALYSIS_PROGRESS`（`:132-135`） | analysis_progress 全列 |

## 增量迁移矩阵（三组 ALTER，全部幂等容错）

| 迁移 | 常量/位置 | 加的列 | 执行方 |
|------|----------|--------|--------|
| LLM 列 | `ALTER_FILES_ADD_LLM_COLUMNS`（`:75-82`，5 条） | llm_summary/description/keywords/analyzed_at/model_used | `DatabaseManager::checkAndMigrate`（`DatabaseManager.cpp:53-76`，判 llm_summary 存在与否） |
| 场景列 | `ALTER_FILES_ADD_SCENE_COLUMNS`（`:401-405`，3 条） | scene_type/scene_priority/scene_relevant | 场景工件库初始化 |
| 分区列 | 内联 ALTER（`FileClassifier.cpp:95-97`；分类表版 `:151-156`） | partition_num | 无条件执行，报错忽略 |

## 跨表关联键

- **库内**：`*_artifacts.file_id` → 主表 `files.id`（唯一显式 FK，但依赖外键开关，逻辑上按值对齐）。
- **跨库**：主表 `(inode, partition_num)` → raw.db `files`；`path` → events.db `events.file_path`。

真实 JOIN 示例（分类副本与主表拼 LLM 结论——体现"副本无观点列，须回主表取"）：

```sql
SELECT i.name, i.size, f.category, f.llm_summary, f.scene_type
FROM images i
JOIN files f ON f.inode = i.inode AND f.partition_num = i.partition_num
WHERE f.scene_relevant = 1;
```

## 已知边界

- **分类表与主表双写但不事务绑定**：`classifyFiles()` 先写主表再写分类表，中途失败会出现两处不一致；分类表是纯副本，可删库重跑 FileClassifier 重建（决定二的派生自由度）。
- **`UPDATE_FILE_LLM_ANALYSIS` 拒绝歧义路径**：WHERE 子句要求该 path 在主表唯一（`:92-93` 子查询 COUNT=1），重名文件（不同分区同路径）的 LLM 结论会被丢弃（`changes==0` 时仅告警，`LLMAnalysisService.cpp:434-437`）。
- **`file_descriptions` 是懒建表**：没有任何前置迁移建它；只要 LLM 分析跑过至少一个文件它才存在。查一个"从未跑过 LLM"的任务库会报 no such table。
- **场景工件表只在 CLI 集成模式建**：HTTP 任务模式走独立 android.db/windows.db/linux.db，本库这 3 张表不建（CREATE ARTIFACT 调用点在各分析库的 `integratedMode_` 分支内，如 `AndroidAnalysisDatabase.cpp:26-29`）。
- **主表缺 `atime` 索引也无 atime 列**：按访问时间排序的需求须回 raw.db（见 [RawDB.md](./RawDB.md)）。

---


## 附录：写入时序与查询手册

### 写入时序

| 表 | 写入方 | 时机 | 量级 |
|----|--------|------|------|
| 主 `files`（含 category/scene_*） | FileClassifier::classifyAndExtract | FILE_CLASSIFICATION 阶段 | 每 REG 文件一行 |
| 24 张分类表 | 同上（按类物化） | 同上（同事务） | 主表行数的按类分布 |
| `llm_*` 5 列 + `file_descriptions` | LLMAnalysisService / Python LLMService | LLM_ANALYSIS 阶段或事后重分析 | 受 LLM_MAX_FILES/smart 粗选 |
| `android/windows/linux_artifacts` | CLI 模式平台工件并入 | CLI 平台分析 | HTTP 模式不写（走独立库） |
| `analysis_progress` | LLM 分析进度 | LLM 阶段节流更新 | 单行 |

### 查询手册

**1. 分类分布体检**
```sql
SELECT category, COUNT(*) c, ROUND(AVG(size)) avg_size FROM files
GROUP BY category ORDER BY c DESC;
```

**2. 场景相关且已有 LLM 结论的文件（最值得先看的集合）**
```sql
SELECT path, category, llm_summary FROM files
WHERE scene_relevant=1 AND llm_analyzed_at IS NOT NULL
ORDER BY scene_priority DESC LIMIT 100;
```

**3. LLM 覆盖率（SMART 是否淘汰太多）**
```sql
SELECT COUNT(*) total, SUM(llm_analyzed_at IS NOT NULL) done, SUM(scene_relevant) relevant FROM files;
```

**4. file_descriptions 与主表交叉（重分析痕迹）**
```sql
SELECT f.path, f.llm_summary, d.is_relevant, d.model_used
FROM files f JOIN file_descriptions d ON d.path=f.path
ORDER BY d.analyzed_at DESC LIMIT 100;
```

**5. 主表 vs 分类表对账（双轨一致性）**
```sql
SELECT (SELECT COUNT(*) FROM files) main,
       (SELECT COUNT(*) FROM documents) documents_rows;
-- 主表 category='DOCUMENTS' 的行数应与 documents 表一致；不一致说明中途中断。
```

**6. 高价值加密/凭证类清单**
```sql
SELECT path, size, category FROM files
WHERE category IN ('ENCRYPTED','CERTIFICATE') AND is_deleted=0
ORDER BY size DESC LIMIT 50;
```

**7. 分类表直查（单表扫描的初衷）**
```sql
SELECT path, extension, mtime FROM databases ORDER BY size DESC LIMIT 50;
-- 换表名即换类：images/documents/archives/...
```

## 分析案例

查询手册是单条"食谱"；本节是多查询组合的叙事案例：从取证问题出发，串联主表/分类表/场景列/LLM 列与跨库对账，逐步解读中间结果。库路径约定：HTTP 任务 `data/tasks/<task_id>/files.db`，CLI `<镜像名>_files.db`。

### 案例一：高价值文件收敛

**取证问题**：一个 900G 镜像产出 300 万行文件记录，人工看不完。要求在 LLM 预算（LLM_MAX_FILES）有限的前提下，把"最值得人看/机器分析"的集合收敛到几百个文件以内。

**第 1 步：分类分布体检**——先知道这座山是什么构成的：

```sql
SELECT category, COUNT(*) AS c, ROUND(AVG(size)) AS avg_size,
       SUM(is_deleted) AS deleted_cnt
FROM files GROUP BY category ORDER BY c DESC;
```

读法：`category` 是 24 类之一（枚举表见前文）。海量 `OS_LIBRARY`/`SYSTEM` 属于背景噪音；取证价值密度通常在 `DOCUMENT/ARCHIVE/ENCRYPTED/CERTIFICATE/EXECUTABLE/SOURCE_CODE` 这几类。同时记下 `deleted_cnt`——已删除的文档类文件往往是"当事人以为删掉了"的关键证据。

**第 2 步：场景列初筛**——场景检测器（SceneDetector）已给每行打上场景观点，`scene_priority > 0` 才会入选 LLM 批（`SELECT_SCENE_FILES_FOR_LLM`）：

```sql
SELECT scene_type, scene_relevant, COUNT(*) AS c, SUM(size) AS bytes
FROM files GROUP BY scene_type, scene_relevant ORDER BY c DESC;
```

读法：本表只统计全量分布；`scene_type` 为 NULL 说明该任务没触发场景检测（例如通用镜像）。此时收敛只能靠第 1 步分类 + 第 3 步手工构造候选集。

**第 3 步：构造高价值候选集（分类 × 状态 × 体积三重过滤）**：

```sql
SELECT path, name, category, extension, size, is_deleted, mtime, partition_num
FROM files
WHERE category IN ('DOCUMENT','ARCHIVE','ENCRYPTED','CERTIFICATE','SOURCE_CODE')
  AND is_deleted = 0
  AND size BETWEEN 1024 AND 52428800
ORDER BY CASE category WHEN 'ENCRYPTED' THEN 0 WHEN 'CERTIFICATE' THEN 1
                       WHEN 'DOCUMENT' THEN 2 ELSE 3 END, mtime DESC
LIMIT 300;
```

读法：`size BETWEEN 1K..50M` 剔除空壳与超大二进制（LLM 分析超时高发区）；ORDER BY 让加密容器与证书（数量少、单件价值高）排前。这一步产出的路径清单可直接喂给 Files 页"批量分析"（`/api/llm/batch` 的 `file_paths` 参数），绕开 smart 粗选。

**第 4 步：核对 LLM 覆盖率与重分析痕迹**——分析跑完后验证有没有漏网：

```sql
SELECT COUNT(*) AS total,
       SUM(llm_analyzed_at IS NOT NULL) AS analyzed,
       SUM(scene_relevant) AS relevant
FROM files;
```

```sql
SELECT f.path, f.category, f.llm_summary, d.is_relevant, d.model_used
FROM files f JOIN file_descriptions d ON d.path = f.path
ORDER BY d.created_at DESC LIMIT 100;
```

读法：第一条算覆盖率（查询手册第 3 条的深化）；第二条把主表 LLM 结论与证据清单副本对齐——`d.created_at` 远晚于任务完成时间且 `model_used` 与主表 `llm_model_used` 不同，说明跑过二次分析（reanalyze），报告引用时注意版本口径。

**第 5 步：与 events.db 交叉（把高价值文件放回时间线）**：

```sql
ATTACH DATABASE 'data/tasks/<task_id>/events.db' AS e;
SELECT e.timestamp, e.event_type, f.path, f.category, f.llm_summary
FROM e.events e JOIN files f ON f.path = e.file_path
WHERE f.category IN ('DOCUMENT','ARCHIVE','ENCRYPTED')
ORDER BY e.timestamp DESC LIMIT 200;
```

读法：高价值文件的最后修改/删除时刻与其他事件（见 [EventsDB.md](./EventsDB.md) 分析案例）对窗，即可回答"这份关键文件是什么时候被动过的"。

**结论与下一步**：候选集 + LLM 结论 + 时间锚三者合并，即形成"高价值文件清单（含 AI 摘要与时间线位置）"的交付物。若第 4 步发现 `UPDATE_FILE_LLM_ANALYSIS` 因重名路径丢结论（已知边界第 2 条：path 不唯一即丢弃），应先排查多分区同名文件（用 `partition_num` 分组验证），再决定是否换路径维度重跑。

### 案例二：已删除文件与回收链对账

**取证问题**：委托方要求列举"镜像里已删除但仍可恢复的文件"，并区分"用户正常删除"与"批量清除"。

**第 1 步：deleted_files 视图全景**（视图三件套之一，按类别物化）：

```sql
SELECT category, COUNT(*) AS c, SUM(size) AS bytes
FROM deleted_files GROUP BY category ORDER BY bytes DESC;
```

读法：视图输出列是 (类别标签, name, path, size, extension)——类别标签来自 24 个 UNION 分支而非主表 `category` 列，两种口径理论上应一致；若某类主表计数与视图计数差很多，说明分类表与主表双写不一致（已知边界第 1 条），以主表为准。

**第 2 步：主表口径复核 + 时间聚集**：

```sql
SELECT strftime('%Y-%m-%d %H:00', ctime, 'unixepoch') AS hour, COUNT(*) AS c
FROM files WHERE is_deleted = 1
GROUP BY hour ORDER BY c DESC LIMIT 10;
```

读法：files.db 的 `ctime` 承自 raw.db（删除时刻近似）。单小时桶出现千级计数=批量清除，对照 [EventsDB.md](./EventsDB.md) 案例一的删除时段验证；均匀小桶=日常回收。

**第 3 步：回事实层确认可恢复性**（files.db 无 atime/crtime，也看不出分配状态细节）：

```sql
ATTACH DATABASE 'data/tasks/<task_id>/raw.db' AS r;
SELECT r.path, r.size, r.is_allocated, r.md5, r.partition_num
FROM r.files r
WHERE r.is_deleted = 1 AND r.size > 1048576
ORDER BY r.size DESC LIMIT 100;
```

读法：`is_allocated=0` 且有 `md5`（说明配置开了哈希计算）的大文件是雕刻优先对象。平台侧还有更精确的删除叙事源可交叉：Windows 回收站（[WindowsDB.md](./WindowsDB.md) `recycle_bin` 表，含 `deletion_time`/`original_path`/`user_sid`）与 Linux XDG 回收站（[LinuxDB.md](./LinuxDB.md) `linux_trash_entries` 表，含 `original_path`/`deletion_time`）——若平台库里有这些行，说明走了"图形界面回收站"路径，属于典型用户行为；反之大量直接删除更接近脚本/命令行操作。

**结论与下一步**：输出"已删除文件分级清单"（A 级=平台回收站在册、B 级=raw 未分配且哈希在、C 级=仅目录项残留），并对 A/B 级提交雕刻提取。注意本库 `android/windows/linux_artifacts` 三表只在 CLI 集成模式存在（已知边界），HTTP 任务查不到属正常。


## 自检清单

- [ ] 主表与 24 分类表行数对账（第 5 条）
- [ ] llm_analyzed_at 覆盖率与限额设置一致（第 3 条）
- [ ] scene_relevant 行数>0（场景检测生效）
- [ ] file_descriptions 与主表不矛盾（第 4 条）
- [ ] unknown_files 占比——分类器盲区信号（扩展名映射是否要补）
**最后更新**: 2026-08-24（补：写入时序与查询手册；扩充：分析案例）
