# DatabaseManager - 数据库管理与存储核心

## 1. 模块概述 (Overview)

**DatabaseManager** 是整个数字取证分析平台的数据中枢,负责统一管理所有分析数据的存储、查询和索引。该模块采用三层架构数据库设计,将原始文件元数据、时间线事件和分类文件分别存储在三个独立的SQLite数据库中,既保证了数据的完整性,又提供了高效的查询性能。

该模块为客户解决"取证数据量大、格式复杂、难以高效查询"的核心痛点。无论是百万级别的文件清单,还是细粒度到秒的时间线事件,DatabaseManager都能提供快速、可靠的数据访问能力,是所有取证分析模块的基础设施。

**核心业务价值:**
- **统一数据管理**:单一模块管理所有取证数据库,避免数据分散和重复
- **高性能查询**:优化的索引设计和事务处理,支持百万级数据秒级响应
- **完整数据链**:三层架构确保数据可追溯、可关联、可验证
- **灵活扩展**:标准化接口设计,便于集成新模块和新功能
- **事务安全**:ACI D特性保证数据完整性,满足司法取证要求

---

## 2. 核心功能列表 (Key Features)

### 2.1 三层数据库架构

- **_raw.db (原始元数据库)**
  - 存储从磁盘镜像直接提取的文件系统元数据
  - `files`表:包含inode、路径、大小、时间戳、类型、删除标记等
  - `partitions`表:记录分区布局、文件系统类型、偏移量等信息
  - 保留最原始的数据状态,作为后续分析的源头

- **_events.db (时间线事件库)**
  - 从原始元数据中提取和衍生的事件数据
  - `events`主表:记录所有文件系统事件(创建、修改、访问、删除)
  - 专用事件表:creation_events、modification_events、access_events、deletion_events
  - 视图:`timeline`(完整时间线)、`event_statistics`(事件统计)、`hourly_activity`(小时级活动)
  - 支持时间范围查询、事件类型过滤、用户行为分析

- **_files.db (分类文件库)**
  - 将文件按类型自动分类到13个专用表中
  - 分类表:images、videos、audio_files、documents、archives、executables、databases、source_code、web_files、email_files、system_files、encrypted_files、unknown_files
  - 视图:`file_summary`(文件汇总)、`extension_statistics`(扩展名统计)、`deleted_files`(已删除文件)
  - 支持按类型快速筛选、统计分析、批量导出

### 2.2 数据库操作管理

- **自动初始化**
  - 检测并创建数据库文件(如不存在)
  - 自动创建所有必需的表和索引
  - 设置数据库参数优化性能(如PRAGMA设置)
  - 版本管理和迁移支持

- **事务处理**
  - 支持批量插入的事务模式
  - 自动回滚失败的操作,保证数据一致性
  - 提交时机优化,平衡性能与安全
  - 支持嵌套事务(通过SAVEPOINT)

- **连接池管理**
  - 高效的SQLite连接管理
  - 支持多线程并发访问
  - 连接复用,减少开销
  - 自动关闭未使用的连接

### 2.3 数据插入与更新

- **批量插入优化**
  - 支持1000+条记录的批量插入
  - 使用prepared statements提高效率
  - 自动分批处理超大事务
  - 进度回调支持,实时反馈插入进度

- **数据完整性保证**
  - 外键约束维护数据关联
  - 唯一性约束防止重复数据
  - 触发器自动更新衍生数据
  - 数据类型校验,防止脏数据

### 2.4 高级查询功能

- **复杂查询支持**
  - 多表关联查询(JOIN操作)
  - 子查询和嵌套查询
  - 聚合函数和分组统计
  - 窗口函数(如RANK、LEAD)

- **全文搜索集成**
  - 与FullTextSearch模块无缝集成
  - FTS5虚拟表支持
  - 高效的文本内容检索
  - 相关性排序和结果高亮

### 2.5 数据导出功能

- **多格式导出**
  - JSON格式:用于API返回和数据交换
  - CSV格式:用于Excel分析和报表生成
  - TOON格式:用于LLM高效提示输入
  - SQLite备份:用于数据迁移和归档

- **增量导出**
  - 支持按时间范围增量导出
  - 按文件类型选择性导出
  - 支持查询结果直接导出

---

## 3. 业务流程/使用场景 (Use Cases)

### 场景一:百万级文件的快速查询

**背景**:某大型企业服务器磁盘包含500万个文件,需要快速定位特定时间范围内创建的文档。

**业务流程**:
1. **数据初始化**:ImageAnalyzer分析完成后,DatabaseManager自动创建三层架构数据库
2. **批量插入**:500万条文件元数据通过事务批量插入,耗时约15分钟
3. **索引优化**:系统自动在时间字段和类型字段上创建索引
4. **快速查询**:
   ```sql
   SELECT * FROM files
   WHERE creation_time BETWEEN '2024-01-01' AND '2024-01-31'
   AND extension IN ('docx', 'xlsx', 'pdf')
   ORDER BY creation_time DESC;
   ```
   查询响应时间:0.8秒
5. **结果导出**:将查询结果导出为CSV,提交给调查团队

**价值体现**:从海量数据中快速定位目标,大幅缩短调查时间,提升取证效率。

### 场景二:跨数据表关联分析

**背景**:需要分析某个用户在一周内的所有活动,包括文件操作、程序执行、网络访问等。

**业务流程**:
1. **多源数据整合**:
   - `_raw.db.files`:提供文件操作记录
   - `_events.db.events`:提供时间线事件
   - `_files.db.executables`:提供程序执行历史
   - `_windows.db`:提供Windows特定事件(如注册表修改)

2. **关联查询**:
   ```sql
   SELECT
     f.path,
     f.size,
     e.event_type,
     e.timestamp,
     'file' as source
   FROM files f
   JOIN events e ON f.inode = e.inode
   WHERE e.timestamp BETWEEN '2024-01-01' AND '2024-01-07'
   AND f.path LIKE '%suspect_user%'
   UNION ALL
   SELECT
     reg.key_path,
     reg.value_data,
     'REGISTRY_CHANGE',
     reg.timestamp,
     'registry' as source
   FROM registry_changes reg
   WHERE reg.timestamp BETWEEN '2024-01-01' AND '2024-01-07'
   ORDER BY timestamp;
   ```

3. **时间线可视化**:将查询结果导入时间线分析工具,生成可视化报告

**价值体现**:通过多维度数据关联,全面还原用户行为轨迹,为案件调查提供完整证据链。

---

## 4. 部署与配置要求 (Deployment & Configuration)

### 环境依赖

**必需的外部库:**
- SQLite 3.35.0 或更高版本
  - 推荐使用3.38.0+以获得更好的性能
  - 编译时需启用:JSON1、FTS5、RTREE扩展

**编译器要求:**
- GCC 9.0+ 或 Clang 10.0+
- 支持 C++20 标准
- 链接选项:`-lsqlite3 -lpthread`

**系统要求:**
- **内存**:最低2GB,推荐4GB以上(处理大数据库时)
- **存储**:至少预留10倍于镜像文件大小的空间用于数据库
- **文件描述符**:系统限制`ulimit -n`建议设置为65536

### 关键配置项

**数据库创建参数:**
```cpp
DatabaseManager::Config config;

// 数据库路径配置
config.rawDbPath = "evidence_raw.db";
config.eventsDbPath = "evidence_events.db";
config.filesDbPath = "evidence_files.db";

// 性能优化参数
config.cacheSize = -64000;  // 64MB负缓存
config.journalMode = "WAL"; // Write-Ahead Logging
config.synchronous = "NORMAL"; // 平衡性能与安全
config.lockingMode = "NORMAL"; // 多进程安全
config.tempStore = "MEMORY"; // 临时表存储在内存

// 批处理配置
config.batchSize = 1000; // 批量插入每批记录数
config.transactionTimeout = 30000; // 事务超时时间(毫秒)
```

**命令行参数:**
```bash
# 指定数据库输出目录
forensic_analyzer disk_image.dd --db-dir /path/to/output

# 启用详细日志
forensic_analyzer disk_image.dd --db-verbose

# 仅创建数据库结构不导入数据
forensic_analyzer disk_image.dd --db-schema-only
```

### 性能优化建议

**加速数据导入:**
1. 使用WAL模式(Write-Ahead Logging)
2. 增大SQLite缓存至256MB或更高
3. 批量插入使用事务(每1000-5000条提交一次)
4. 禁用不必要的索引,导入完成后重建
5. 使用`PRAGMA synchronous = OFF`(仅限导入阶段)

**加速查询性能:**
1. 为常用查询字段创建索引:
   - `files`表:inode、path、mtime、extension
   - `events`表:inode、timestamp、event_type
2. 使用ANALYZE命令更新统计信息
3. 复杂查询使用EXPLAIN QUERY PLAN分析
4. 考虑使用Covering Index减少磁盘I/O

**存储优化:**
1. 定期执行VACUUM清理数据库碎片
2. 使用`PRAGMA auto_vacuum = INCREMENTAL`
3. 大文本字段考虑压缩存储
4. 归档历史数据到单独数据库

---

## 5. 接口与集成说明 (API & Integration)

### C++ 编程接口

**初始化数据库管理器:**
```cpp
#include "DatabaseManager/DatabaseManager.h"

// 创建管理器实例
DatabaseManager dbManager;

// 配置数据库路径
DatabaseManager::Config config;
config.basePath = "/path/to/databases";
config.imageName = "evidence";

// 初始化
if (!dbManager.initialize(config)) {
    std::cerr << "数据库初始化失败" << std::endl;
    return -1;
}

// 检查数据库版本
std::string version = dbManager.getSchemaVersion();
```

**插入文件记录:**
```cpp
// 批量插入示例
std::vector<FileRecord> records = extractFileRecords(imagePath);

dbManager.beginTransaction();
for (const auto& record : records) {
    if (!dbManager.insertFileRecord(record)) {
        std::cerr << "插入记录失败: " << record.name << std::endl;
    }
    // 每1000条提交一次
    if (count % 1000 == 0) {
        dbManager.commitTransaction();
        dbManager.beginTransaction();
    }
}
dbManager.commitTransaction();
```

**查询数据:**
```cpp
// 查询特定inode的文件信息
FileRecord record;
if (dbManager.getFileByInode(12345, record)) {
    std::cout << "文件路径: " << record.path << std::endl;
    std::cout << "文件大小: " << record.size << std::endl;
    std::cout << "修改时间: " << record.mtime << std::endl;
}

// 查询时间范围事件
std::vector<EventRecord> events;
dbManager.getEventsByTimeRange(
    "2024-01-01 00:00:00",
    "2024-01-31 23:59:59",
    events
);

// 使用原生SQL查询
sqlite3* db = dbManager.getDatabase(DatabaseType::EVENTS);
const char* sql = "SELECT * FROM events WHERE event_type = ?";
sqlite3_stmt* stmt;
sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr);
sqlite3_bind_text(stmt, 1, "DELETED", -1, SQLITE_STATIC);
while (sqlite3_step(stmt) == SQLITE_ROW) {
    // 处理结果
}
sqlite3_finalize(stmt);
```

### REST API 集成

通过HTTPServer模块提供的查询接口:

**文件查询:**
- `GET /api/db/files?inode=12345` - 查询特定文件
- `GET /api/db/files?path=/home/user/document.pdf` - 按路径查询
- `GET /api/db/files?ext=docx,pdf` - 按扩展名查询
- `GET /api/db/files?start=2024-01-01&end=2024-01-31` - 按时间范围查询

**事件查询:**
- `GET /api/db/events?type=DELETED` - 查询删除事件
- `GET /api/db/timeline?start=...&end=...` - 查询时间线
- `GET /api/db/statistics` - 查询统计信息

**数据导出:**
- `GET /api/db/export?format=json&table=files` - 导出为JSON
- `GET /api/db/export?format=toon&table=events` - 导出为TOON
- `POST /api/db/query` - 执行自定义SQL查询

### 数据库维护接口

```cpp
// 数据库优化
dbManager.vacuum();          // 清理碎片
dbManager.analyze();         // 更新统计信息
dbManager.reindex();         // 重建索引

// 备份与恢复
dbManager.backup("/backup/path.db");
dbManager.restore("/backup/path.db");

// 数据库迁移
bool success = dbManager.migrateToVersion("2.0");
```

---

## 6. 常见问题 (FAQ)

**Q1:三个数据库之间如何关联?如何进行跨库查询?**

A:三个数据库通过`inode`字段(文件唯一标识)进行关联:
- `_raw.db.files.inode` → `_events.db.events.inode`
- `_raw.db.files.inode` → `_files.db.*.inode`

**跨库查询方法:**
```sql
-- 方法1:使用ATTACH DATABASE
ATTACH DATABASE 'evidence_events.db' AS events;
SELECT f.path, e.event_type, e.timestamp
FROM files f
JOIN events.events e ON f.inode = e.inode;

-- 方法2:通过DatabaseManager API
dbManager.joinQuery(
    "files",
    "events",
    "inode",
    "f.path, e.event_type"
);
```

---

**Q2:数据库文件过大如何处理?能否拆分或归档?**

A:数据库文件过大可通过以下方式处理:

**拆分策略:**
1. 按时间拆分:按月或季度创建独立数据库
2. 按类型拆分:不同文件类型使用不同数据库
3. 按分区拆分:每个磁盘分区对应一个数据库

**归档方案:**
```bash
# 1. 导出历史数据到单独数据库
sqlite3 evidence.db "ATTACH 'archive.db' AS archive;"
sqlite3 evidence.db "CREATE TABLE archive.files AS SELECT * FROM main.files WHERE mtime < '2023-01-01';"

# 2. 从主数据库删除已归档数据
sqlite3 evidence.db "DELETE FROM files WHERE mtime < '2023-01-01';"

# 3. 执行VACUUM释放空间
sqlite3 evidence.db "VACUUM;"
```

---

**Q3:如何处理数据库损坏或数据不一致?**

A:数据库损坏的检测和修复:

**检测方法:**
```bash
# 使用SQLite自带工具检测
sqlite3 evidence.db "PRAGMA integrity_check;"
sqlite3 evidence.db "PRAGMA foreign_key_check;"
```

**修复方法:**
```bash
# 1. 尝试自动修复
sqlite3 evidence.db ".recover" | sqlite3 recovered.db

# 2. 从备份恢复
# 使用DatabaseManager的备份功能恢复最近的备份

# 3. 导出可用数据
sqlite3 evidence.db ".dump" | grep -v "ROLLBACK" | sqlite3 new.db

# 4. 使用DatabaseManager API
dbManager.repairDatabase();
```

**预防措施:**
- 启用WAL模式提高容错性
- 定期执行数据库完整性检查
- 配置自动备份策略
- 使用事务保证操作原子性

---

**Q4:多线程并发访问数据库是否安全?如何处理锁冲突?**

A:SQLite支持多线程读,但写操作会锁数据库。

**安全模式:**
```cpp
// 配置为多线程安全模式
sqlite3_config(SQLITE_CONFIG_MULTITHREAD);
sqlite3_enable_shared_cache(1);

// 使用WAL模式提高并发
config.journalMode = "WAL";
```

**锁冲突处理:**
```cpp
// 设置忙碌超时
sqlite3_busy_timeout(db, 30000); // 30秒

// 重试机制
int retry = 0;
while (sqlite3_step(stmt) == SQLITE_LOCKED && retry < 5) {
    sqlite3_reset(stmt);
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    retry++;
}
```

**最佳实践:**
- 读操作可并发,写操作应串行
- 使用连接池避免频繁打开关闭连接
- 大批量写入使用单线程事务
- 考虑使用读写锁分离策略

---
