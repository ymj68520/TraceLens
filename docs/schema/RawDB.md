# raw.db 字段参考（定义位置：`src/core/DatabaseManager/DatabaseManager.cpp`）

> raw.db 是整条派生链的**唯一事实来源**（DatabaseSchema.md 决定二）：ImageAnalyzer 把 TSK 看到的一切原样落库，不加任何观点；它是唯一不可重建的库（重建等于重新解析镜像），也是 events.db / files.db / 各平台库的公共输入。建表 SQL 不在 `SQL/` 头文件里，而是内联在 `DatabaseManager::createTables()`（`DatabaseManager.cpp:78-148`），这是全项目唯一的例外——因为它是链的起点，早于"SQL-as-headers"约定（决定三）成型。

## 库概览

| 项 | 内容 |
|----|------|
| 谁写 | `ImageAnalyzer` 经 `DatabaseManager::insertFileRecord`（`DatabaseManager.cpp:150`）/ `insertPartitionInfo`（`DatabaseManager.cpp:189`）写入；调用点在 `src/analyzers/ImageAnalyzer/ImageAnalyzer.cpp:303`（分区）、`:408`、`:567`、`:622`、`:728`（文件，覆盖普通遍历 / 目录遍历 / 删除文件遍历 / VS 卷等路径） |
| 谁读 | `EventExtractor`（事件提取，`SELECT_FILES_FOR_EVENT_EXTRACTION`）、`FileClassifier`（分类，读 `type='REG'` 行）、场景检测、HTTP 查询路由、Python 侧重分析/报告/图谱摄取 |
| 文件位置 | HTTP 任务 `data/tasks/<task_id>/raw.db`；CLI 模式 `<image>_raw.db`（DatabaseSchema.md 产出位置表） |
| 连接参数 | `initialize()` 打开后统一设置 `PRAGMA journal_mode`（WAL）、`synchronous=OFF`（可配）、`foreign_keys=ON`、busy_timeout（`DatabaseManager.cpp:29-39`） |

## 表清单总表

| 表 | 分组 | 一句话用途 | 列数 |
|----|------|-----------|------|
| `files` | 事实层 | 完整文件系统元数据：路径、四个时间戳、删除/分配标志、md5、分区号 | 22 |
| `partitions` | 事实层 | 镜像内分区清单：起始偏移、长度、文件系统类型 | 6 |

## 逐表字段说明

### files

写入方：`insertFileRecord`（`DatabaseManager.cpp:150-187`），字段来自 `FileRecord` 结构体（`src/core/DatabaseManager/DatabaseManagerDataTypes.h:13-40`）。类型/约束逐列抄自 `DatabaseManager.cpp:81-104` 的 CREATE TABLE。

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号，无业务含义 |
| inode | INTEGER | — | TSK 元数据地址（inum）。多分区镜像中仅在分区内部唯一，须与 `partition_num` 联合使用；下游所有库用它逻辑对齐（DatabaseSchema.md 决定二） |
| name | TEXT | — | 文件名（不含目录部分），`FileRecord.name` |
| path | TEXT | — | TSK 规范化全路径（如 `/etc/passwd`），跨库 JOIN 的第二把键 |
| size | INTEGER | — | 文件字节数 |
| atime | INTEGER | — | 最后访问时间（unix 秒） |
| mtime | INTEGER | — | 最后修改时间（unix 秒） |
| ctime | INTEGER | — | inode/元数据最后变更时间（unix 秒） |
| crtime | INTEGER | — | 创建时间（unix 秒，NTFS/ext4 才有意义） |
| type | TEXT | — | TSK 名称类型：`REG`（常规文件）/`DIR`/`LNK` 等；下游全部以 `type='REG'` 过滤 |
| md5 | TEXT | — | 内容 MD5（按配置计算，可能为 NULL） |
| is_deleted | INTEGER | — | 1 = 已删除条目（未分配），0 = 在册 |
| is_allocated | INTEGER | — | 1 = 分配中（与 is_deleted 互补，TSK 原生语义） |
| permissions | TEXT | — | 权限字符串（如 `rwxr-xr-x`） |
| uid | INTEGER | — | 属主 UID |
| gid | INTEGER | — | 属组 GID |
| llm_summary | TEXT | — | **预留**：LLM 摘要。`insertFileRecord` 不写此列（INSERT 列表无它，`DatabaseManager.cpp:152-155`）；LLM 结论写 files.db 主表，raw.db 的这 5 列生产上恒 NULL |
| llm_description | TEXT | — | 预留，同上 |
| llm_keywords | TEXT | — | 预留，同上 |
| llm_analyzed_at | INTEGER | — | 预留，同上 |
| llm_model_used | TEXT | — | 预留，同上 |
| partition_num | INTEGER | DEFAULT 0 | 所属分区号（0 = 无分区表/单文件系统）。`DatabaseManagerDataTypes.h:32-34` 注释：用于消除多文件系统镜像中的 inode 碰撞 |

索引（`DatabaseManager.cpp:141-145`，均在 `initialize` 时建）：

- `idx_files_inode ON files(inode)`
- `idx_files_path ON files(path)`
- `idx_files_type ON files(type)`
- `idx_files_deleted ON files(is_deleted)`
- `idx_files_partition ON files(partition_num)`

迁移逻辑：旧库若缺 `llm_summary`，`checkAndMigrate()`（`DatabaseManager.cpp:53-76`）执行 `FileClassifierSQL::ALTER_FILES_ADD_LLM_COLUMNS`（5 条 ALTER，`file_classifier_sql.h:75-82`）；`createTables()` 后再无脑补一次 `ALTER TABLE files ADD COLUMN partition_num ...`（`DatabaseManager.cpp:115-122`），已存在时报错被忽略。

### partitions

写入方：`insertPartitionInfo`（`DatabaseManager.cpp:189-214`），实参来自 ImageAnalyzer 的分区扫描（`ImageAnalyzer.cpp:303`）。

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| partition_num | INTEGER | — | 分区序号，与 `files.partition_num` 对应；0 保留给"无分区表/单 FS" |
| start_offset | INTEGER | — | 分区起始字节偏移（TSK 布局换算） |
| length | INTEGER | — | 分区字节长度 |
| description | TEXT | — | 分区表项描述文本（TSK 提供） |
| fs_type | TEXT | — | 文件系统类型（NTFS/EXT4/FAT32...，TSK 检测） |

索引/触发器：无。

## FileRecord ↔ files 列对照（`DatabaseManagerDataTypes.h:13-40`）

写入 `insertFileRecord` 时的字段映射（数据库列 ← 结构体字段）：

| 表列 | FileRecord 字段 | 备注 |
|------|----------------|------|
| inode | `inode` (int64_t) | |
| name | `name` (string) | |
| path | `path` (string) | |
| size | `size` (int64_t) | |
| atime / mtime / ctime / crtime | 同名 (int64_t) | 四时间戳 |
| type | `type` (string) | 'REG'/'DIR'... |
| md5 | `md5` (string) | |
| is_deleted | `isDeleted` (int) | |
| is_allocated | `isAllocated` (int) | |
| permissions | `permissions` (string) | |
| uid / gid | 同名 (int) | |
| partition_num | `partitionNum` (int, 默认 0) | |
| （无对应列） | `id`/`extension`/`category`/`sceneType`/`scenePriority`/`sceneRelevant` | 结构体有、raw.db 不收——观点字段留给下游 |

## 下游读取方清单（谁在扫 raw.db）

| 读取方 | 语句 | 过滤条件 |
|--------|------|---------|
| EventExtractor | `SELECT_FILES_FOR_EVENT_EXTRACTION`（`event_extractor_sql.h:325-329`） | `type='REG'`，取 inode/path/四时间戳/type/size/is_deleted |
| FileClassifier | `classifyFiles` 内联查询（`FileClassifier.cpp:193-198`） | `type='REG'` + `COALESCE(partition_num,0)` |
| DatabaseManager | `getFileCount`（`DatabaseManager.cpp:216-227`） | COUNT(*) |

## 写入路径全景（ImageAnalyzer 的 5 个 insertFileRecord 调用点）

| 调用点 | 场景 |
|--------|------|
| `ImageAnalyzer.cpp:408` | 主遍历（普通文件） |
| `ImageAnalyzer.cpp:567` | 目录遍历 |
| `ImageAnalyzer.cpp:622` | 已删除条目遍历 |
| `ImageAnalyzer.cpp:728` | 卷/分区扫描分支 |
| `ImageAnalyzer.cpp:303` | `insertPartitionInfo`：分区清单 |

## 跨表关联键

raw.db 内部仅两表，键的用法体现在"向外"派生：

- `files.partition_num` ↔ `partitions.partition_num`：库内无外键，靠值对齐；查"某分区下全部文件"即 `JOIN partitions p ON p.partition_num = f.partition_num`。
- `files.(inode, partition_num)` 与 `files.path` 是下游 events.db / files.db 回溯事实行的两把逻辑键（DatabaseSchema.md 第 10 节）。

真实 JOIN 示例（分区 × 文件计数，直接可在 raw.db 上跑）：

```sql
SELECT p.partition_num, p.fs_type, COUNT(f.id) AS file_count
FROM partitions p
LEFT JOIN files f ON f.partition_num = p.partition_num
GROUP BY p.partition_num, p.fs_type;
```

## 已知边界

- **llm_* 5 列为死列**：建表带出但 `insertFileRecord` 从不写，C++ 侧也没有任何 UPDATE raw.db files 的路径；LLM 结论一律落在 files.db 主表（见 [FilesDB.md](./FilesDB.md)）。
- **`FileRecord` 与表列并非一一对应**：结构体多出 `extension`、`category`、`sceneType/scenePriority/sceneRelevant`（`DatabaseManagerDataTypes.h:19-39`）——这些是下游观点字段，raw.db 刻意不存（"忠实记录，不加观点"）。
- **时间列无索引**：`atime/mtime/ctime/crtime` 均无索引，按时间范围扫 raw.db 是全表扫描；事件提取因此按 `type='REG'` 索引列过滤后整批读出（`SELECT_FILES_FOR_EVENT_EXTRACTION`，`event_extractor_sql.h:325-329`）。
- **`type='DIR'` 行也存在**：目录也入 files 表，`size` 通常为 0；统计文件数时应过滤。

---


## 附录：写入时序与查询手册

### 写入时序

| 表 | 写入方 | 时机 | 量级 |
|----|--------|------|------|
| `files` | DatabaseManager::insertFileRecord（ImageAnalyzer 遍历回调） | IMAGE_ANALYSIS 阶段，每文件一行 | 大（900M 真实镜像实测约 3.5k 行/GB 级） |
| `partitions` | ImageAnalyzer 分区枚举 | IMAGE_ANALYSIS 开始时 | 每分区一行 |
| （`_filtered.db` 副本） | FileFilter::applyFilterByName | FILE_CLASSIFICATION 开头、SceneDetector 之后 | 按画像筛选后的行数 |

注意：`files` 的 `llm_*` 5 列为死列（建表带出但从不写，LLM 结论只落 files.db 主表）；md5 按配置计算可能为 NULL。

### 查询手册

**1. 大文件 Top（先看什么占了空间）**
```sql
SELECT path, size, is_deleted, partition_num FROM files
WHERE type='REG' ORDER BY size DESC LIMIT 50;
```

**2. 已删除但可观的大文件（雕刻前评估）**
```sql
SELECT path, size FROM files
WHERE is_deleted=1 AND size > 1048576 ORDER BY size DESC LIMIT 50;
```
读法：is_deleted=1 是未分配条目——配合雕刻阶段（file_carving）产出实体文件。

**3. 分区分布与各分区体量**
```sql
SELECT p.partition_num, p.fs_type, COUNT(f.id) files, ROUND(SUM(f.size)/1048576.0,1) mb
FROM partitions p LEFT JOIN files f ON f.partition_num=p.partition_num
GROUP BY p.partition_num ORDER BY mb DESC;
```

**4. 时间戳四元组健全性（哪些文件可做时间线）**
```sql
SELECT
  SUM(crtime>0) has_crtime, SUM(mtime>0) has_mtime,
  SUM(atime>0) has_atime, SUM(ctime>0) has_ctime, COUNT(*) total
FROM files WHERE type='REG';
```
读法：crtime 覆盖率低是正常的（只有 NTFS/ext4 有意义）；全 0 说明镜像缺时间戳，时间线要换证据源。

**5. raw 与下游对账基线**
```sql
SELECT COUNT(*) raw_regs FROM files WHERE type='REG';
-- 与 files.db 主表行数比对：差值=被过滤画像排除+非 REG（正常）；
-- 差值异常大时先查任务的 filter_profile 与 output_raw_db 指向。
```

**6. 同名文件跨分区消歧示例**
```sql
SELECT partition_num, inode, path, size FROM files
WHERE name='passwd' OR path LIKE '%/passwd' ORDER BY partition_num;
```
读法：inode 仅分区内唯一，多分区联查必须带 partition_num（决定二）。
**最后更新**: 2026-08-24（补：写入时序与查询手册）
