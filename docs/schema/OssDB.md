# oss.db 字段参考（定义位置：`src/core/DatabaseManager/SQL/oss_sql.h`）

> 这是阿里云 OSS 对象存储取证的库：3 张表 + 2 视图，schema 完整（含 LLM 列与全套查询），**但 OSSAnalyzer 当前无生产调用方**——消费路由未注册，仅单测调用（DatabaseSchema.md 第 8 节）。注意同名陷阱：SERVER_CLOUD 场景任务目录里的 `oss.db` 实际是 LinuxFilesAnalyzer 写的 `linux_*` 表族（见 [LinuxDB.md](./LinuxDB.md)），与本库同名不同物。

## 库概览

| 项 | 内容 |
|----|------|
| 谁建/谁写 | `OSSAnalyzer` 的 `OSSAnalysisDatabase`：建表/索引/视图执行 `oss_sql.h` 的 `CREATE_OBJECTS_TABLE`（`:16-40`）等常量；写入 `INSERT_OBJECT`（`OSSAnalysisDatabase.cpp:73`）、`INSERT_BUCKET`（`OSSAnalysisDatabase_Queries.cpp:151`） |
| 谁读 | OSSAnalyzer 查询族（`SELECT_*`/统计语句，`oss_sql.h:129-239`）；**无生产入口** |
| 文件位置 | 设计上随任务/独立产出 `oss.db`；因无调用方，任务产出中不会出现 |

## 表清单总表

| 表 | 分组 | 一句话用途 | 列数 |
|----|------|-----------|------|
| `oss_objects` | 对象 | OSS 对象清单（含版本/删除标记/LLM） | 20 |
| `oss_access_logs` | 日志 | OSS 访问日志（谁在何时动了哪个对象） | 17 |
| `oss_buckets` | 桶 | bucket 清单与配置（版本化/日志/统计） | 15 |

## 逐表字段说明

### oss_objects（`oss_sql.h:16-40`，写入 `INSERT_OBJECT` `:102-107` 13 列）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| bucket | TEXT | NOT NULL, UNIQUE 组合 | 所属 bucket |
| key | TEXT | NOT NULL, UNIQUE 组合 | 对象键（全路径） |
| size | INTEGER | DEFAULT 0 | 字节 |
| etag | TEXT | — | ETag（≈MD5，分片上传时非） |
| last_modified | INTEGER | — | 最近修改（有索引） |
| storage_class | TEXT | — | 存储 类型（Standard/IA/Archive） |
| content_type | TEXT | — | MIME |
| owner | TEXT | — | 属主 |
| user_metadata | TEXT | — | 自定义元数据（序列化） |
| version_id | TEXT | — | 版本 ID（UNIQUE 组合第三键——多版本对象各占一行） |
| is_deleted | INTEGER | DEFAULT 0 | 1 = 删除标记版本 |
| md5_hash | TEXT | — | 内容 MD5 |
| analyzed_at | INTEGER | — | 分析时刻 |
| llm_summary / llm_description / llm_keywords | TEXT | — | LLM 三件套 |
| llm_analyzed_at | INTEGER | — | 分析时间 |
| llm_model_used | TEXT | — | 模型 |
| llm_is_relevant | INTEGER | DEFAULT 1 | 是否有价值（OSS 侧多一列，默认 1，与 events.db 的 0 默认不同） |

唯一约束：`UNIQUE(bucket, key, version_id)`（`:38`）。
索引（`CREATE_OBJECTS_INDEX`，`:42-47`）：`idx_oss_objects_bucket(bucket)`、`idx_oss_objects_key(key)`、`idx_oss_objects_last_modified(last_modified)`、`idx_oss_objects_storage_class(storage_class)`。

### oss_access_logs（`:49-69`，写入 `INSERT_ACCESS_LOG` `:109-115` 16 列）

OSS 访问日志（阿里云访问日志格式）逐条落库。

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| request_id | TEXT | — | 请求 ID |
| timestamp | INTEGER | — | 时刻 |
| operation | TEXT | — | 操作（GetObject/PutObject/DeleteObject...） |
| bucket | TEXT | — | 目标 bucket |
| object_key | TEXT | — | 目标对象键 |
| remote_ip | TEXT | — | 客户端 IP |
| user_agent | TEXT | — | UA |
| accesser_id | TEXT | — | 访问者（RAM 子账号；列名照抄阿里云拼写） |
| http_status | INTEGER | — | HTTP 状态码 |
| bytes_sent | INTEGER | — | 发送字节 |
| object_size | INTEGER | — | 对象大小 |
| time_taken_ms | INTEGER | — | 耗时毫秒 |
| referer / host | TEXT | — | 头 |
| signature_version | TEXT | — | 签名版本 |
| ssl_enabled | INTEGER | DEFAULT 0 | 是否 HTTPS |

索引（`:71-76`）：`timestamp`、`operation`、`object_key`、`remote_ip` 四列各一。

### oss_buckets（`:78-96`，写入 `INSERT_BUCKET` `:117-123` 14 列）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| name | TEXT | UNIQUE NOT NULL | bucket 名 |
| region / endpoint / acl / owner | TEXT | — | 地域/端点/ACL/属主 |
| creation_date | INTEGER | — | 创建时刻 |
| versioning_enabled | INTEGER | DEFAULT 0 | 版本化开启（取证关键：可找回删除版本） |
| logging_enabled | INTEGER | DEFAULT 0 | 访问日志开启 |
| logging_bucket / logging_prefix | TEXT | — | 日志落点 |
| storage_class | TEXT | — | 默认存储类型 |
| object_count | INTEGER | DEFAULT 0 | 对象数（汇总） |
| total_size | INTEGER | DEFAULT 0 | 总字节（汇总） |
| analyzed_at | INTEGER | — | 分析时刻 |

## 视图（SELECT 语义）

`CREATE_VIEWS`（`:245-265`）：

| 视图 | 定义行 | SELECT 语义 |
|------|--------|-------------|
| `oss_objects_summary` | `:246-254` | 按 bucket 聚合 objects：count、SUM(size)、最早/最晚 last_modified |
| `oss_access_timeline` | `:256-264` | 访问日志按 `DATE(timestamp,'unixepoch')` × operation 分组：计数 + SUM(bytes_sent)，按日期/操作排序——访问行为日历 |

## 查询与统计语句族（`oss_sql.h`，schema 消费面全景）

| 常量 | 行 | 语义 |
|------|----|------|
| SELECT_ALL_OBJECTS | `:129` | 按 last_modified 倒序全量对象 |
| SELECT_OBJECTS_BY_BUCKET | `:133` | 桶内按 key 排序 |
| SELECT_OBJECTS_BY_PREFIX | `:157` | 桶内 key 前缀（LIKE） |
| SELECT_OBJECTS_BY_EXTENSION | `:141` | 按扩展名（key LIKE） |
| SELECT_ACCESS_LOGS_BY_TIMERANGE | `:145` | 时间窗访问日志 |
| SELECT_ACCESS_LOGS_BY_OPERATION | `:151` | 按操作类型 |
| SELECT_ACCESS_LOGS_BY_OBJECT | `:157` | 按对象键（"谁动过它"） |
| SELECT_ALL_BUCKETS | `:163` | 桶清单 |
| UPDATE_OSS_OBJECT_LLM_ANALYSIS | `:171-180` | 回写 LLM 6 列（含 llm_is_relevant） |
| SELECT_OSS_OBJECTS_FOR_FILTERING | `:182-188` | llm_analyzed_at IS NULL 的待分析批 |
| SELECT_OSS_OBJECTS_BY_IDS | `:190-195` | 批量取（IN 列表拼接） |
| SELECT_OSS_ANALYZED_OBJECTS | `:197-201` | 已分析对象倒序 |
| COUNT_OBJECTS_BY_STORAGE_CLASS | `:207` | 按存储类型聚合 |
| COUNT_OBJECTS_BY_EXTENSION | `:213-224` | 按扩展名聚合（SQL 内 SUBSTR/INSTR 提取扩展名） |
| COUNT_OPERATIONS | `:226` | 操作分布 |
| GET_ANALYSIS_SUMMARY | `:233-239` | 总量/总大小/已删数/日志条数四合一 |

## 跨表关联键

- `oss_objects.bucket` ↔ `oss_buckets.name`、`oss_access_logs.bucket`（值对齐）。
- 对象与日志：`oss_access_logs.object_key` ↔ `oss_objects.key`——"谁动过这个对象"的问答。

真实 JOIN 示例（对某对象拼出访问史与当前状态）：

```sql
SELECT o.key, o.size, o.last_modified, o.is_deleted,
       a.timestamp, a.operation, a.remote_ip
FROM oss_objects o
LEFT JOIN oss_access_logs a ON a.object_key = o.key AND a.bucket = o.bucket
ORDER BY o.key, a.timestamp;
```

## 已知边界

- **整库无生产调用方**：OSSAnalyzer 未注册进消费路由（DatabaseSchema.md 第 8 节明言），所有表/视图仅存在于代码与单测。任务目录里不会出现这份 schema 的 oss.db。
- **同名不同物**：SERVER_CLOUD 场景任务的 `oss.db` 是 linux_* 表族（LinuxFilesAnalyzer 写入）；拿到一个 oss.db 先看表名前缀判断是哪个。
- **`llm_is_relevant` 默认 1**：与其他库相关列默认 0 的惯例相反（events.db 的 `llm_is_relevant` 无默认）。
- **`accesser_id` 拼写**：沿用阿里云日志原文（非 accessor），对接时别"纠正"它。

---

**最后更新**: 2026-08-24（新建，字段级参考）
