# events.db 字段参考（定义位置：`src/core/DatabaseManager/SQL/event_extractor_sql.h` + `src/core/EventCorrelationEngine/Detail/EventCorrelationEngineCore.cpp`）

> events.db 是 raw.db 的**时间线观点**（DatabaseSchema.md 决定二："库之间是派生关系，不是引用关系"）：把"每文件四个时间戳"的矩阵翻译成"某时刻发生了某事"的事件流。主表 + 5 张按类型分表是查询优化（时间线页常按类型过滤），视图把常用聚合固化在库里，让路由层查询保持简单。表结构可以随时删库重跑 EventExtractor 重建——派生层的设计自由度正在于此。

## 库概览

| 项 | 内容 |
|----|------|
| 谁写 | `EventExtractor`：文件系统事件 `FileSystemEventExtractor.cpp:251`（`INSERT_EVENT`），系统事件 `SystemEventExtractor.cpp:211`（`INSERT_SYSTEM_EVENT`），标准化/分表落库在 `Detail/EventExtractorCore.cpp`；建表/建视图在 `EventExtractorCore.cpp:69-108`。因果链 3 张表由 `EventCorrelationEngine::createCorrelationTables`（`EventCorrelationEngineCore.cpp:121-221`）建，但引擎未接入流水线（见"已知边界"） |
| 谁读 | HTTP 查询路由（时间线/统计页）、Web 前端、LLM 事件簇分析（`UPDATE_EVENT_LLM_ANALYSIS` / `UPDATE_EVENT_CLUSTER_LLM_ANALYSIS`，`event_extractor_sql.h:343-364`）、Python 侧重分析与图谱摄取 |
| 文件位置 | HTTP 任务 `data/tasks/<task_id>/events.db`；CLI `<image>_events.db` |
| 写入性能 | 打开时设 `journal_mode=WAL`、`synchronous=NORMAL`、busy_timeout 5000（`EventExtractorCore.cpp:62-64`）；事件逐表批量事务写入（`BEGIN/COMMIT_TRANSACTION`，`event_extractor_sql.h:335-337`） |

## 表清单总表

| 表 | 分组 | 一句话用途 | 列数 |
|----|------|-----------|------|
| `events` | 主表 | 统一时间线事件流（文件 + 系统事件归一后的全量行） | 21 |
| `creation_events` | 类型分表 | 创建（crtime）事件 | 6 |
| `modification_events` | 类型分表 | 修改（mtime）事件 | 6 |
| `access_events` | 类型分表 | 访问（atime）事件 | 6 |
| `change_events` | 类型分表 | 元数据变更（ctime）事件，带 description | 7 |
| `deletion_events` | 类型分表 | 删除事件（is_deleted 文件入事件流） | 6 |
| `system_events` | 系统叙事 | 系统层事件（登录/服务/网络），字段面向"谁在哪台机做了什么" | 12 |
| `event_correlations` | 关联（未接线） | 两事件的关联对及置信度 | 6（见双定义说明） |
| `event_chains` | 因果链（未接线） | 事件链头（chain_id + 起止时间 + 置信度） | 6 |
| `event_chain_nodes` | 因果链（未接线） | 链内节点及父子关系 | 5 |
| `causal_relationships` | 因果链（未接线） | 因果对（cause→effect + 时延 + 机制） | 7 |

## 逐表字段说明

### events（主表）

建表：`CREATE_EVENTS_TABLE`（`event_extractor_sql.h:14-38`）；写入：`INSERT_EVENT`（`:281-284`，14 列）+ 标准化 UPDATE（`normalized_type` 等，`EventExtractorCore.cpp:111` 起）+ LLM UPDATE（`:343-352`）。列注释直接抄自建表 SQL 的 `--` 注释。

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 事件 ID；分表与关联表都以它回指主表 |
| timestamp | INTEGER | NOT NULL | 事件时刻（unix 秒），来源是 raw.db 四时间戳之一 |
| event_type | TEXT | NOT NULL | 事件类型：`CREATION`/`MODIFICATION`/`ACCESS`/`CHANGE`/`DELETION`（文件系统五类）+ 系统事件类型 |
| file_path | TEXT | — | 关联文件全路径（系统事件可为 NULL） |
| inode | INTEGER | — | 关联文件 inode，回溯 raw.db 的事实行 |
| description | TEXT | — | 人读描述 |
| file_size | INTEGER | — | 事件发生时文件大小 |
| file_type | TEXT | — | 文件类型串 |
| system_context | TEXT | — | 系统上下文（标准化阶段补充） |
| priority | TEXT | — | 事件优先级：LOW, MEDIUM, HIGH, CRITICAL（SQL 注释原文） |
| severity | TEXT | — | 事件严重程度：INFO, WARNING, ERROR, CRITICAL（SQL 注释原文） |
| event_source | TEXT | — | 事件来源：FILE_SYSTEM, WINDOWS_EVENT_LOG, LINUX_SYSLOG, etc.（SQL 注释原文） |
| event_category | TEXT | — | 事件类别：FILE_OPERATION, SYSTEM_ACTIVITY, etc.（SQL 注释原文） |
| normalized_type | TEXT | — | 标准化事件类型（`standardizeEvents()` 回填，`EventExtractorCore.cpp:111-122`） |
| source_id | TEXT | — | 事件来源 ID（如日志 record_id） |
| llm_summary | TEXT | — | AI 生成的事件簇摘要（`UPDATE_EVENT_LLM_ANALYSIS`，`event_extractor_sql.h:343-352`） |
| llm_description | TEXT | — | AI 生成的详细描述 |
| llm_keywords | TEXT | — | AI 提取的关键词（逗号分隔，SQL 注释原文） |
| llm_analyzed_at | INTEGER | — | 分析时间戳 |
| llm_model_used | TEXT | — | 使用的 AI 模型 |
| llm_is_relevant | INTEGER | — | 事件簇是否有价值（0/1，SQL 注释原文） |

索引（`CREATE_EVENT_INDICES`，`event_extractor_sql.h:130-142`）：`idx_events_timestamp(timestamp)`、`idx_events_type(event_type)`、`idx_events_path(file_path)`、`idx_events_inode(inode)`；system_events/correlations 的索引见各自小节。

#### creation_events（`event_extractor_sql.h:40-49`，INSERT `:286-289`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 分表内行号（**不等于**主表 id，两套自增） |
| timestamp | INTEGER | NOT NULL | 对应 crtime（文件创建时刻） |
| file_path | TEXT | NOT NULL | 文件全路径 |
| inode | INTEGER | — | 文件 inode |
| file_size | INTEGER | — | 文件大小 |
| file_type | TEXT | — | 文件类型 |

#### modification_events（`:51-60`，INSERT `:291-294`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 分表内行号 |
| timestamp | INTEGER | NOT NULL | 对应 mtime |
| file_path | TEXT | NOT NULL | 文件全路径 |
| inode | INTEGER | — | 文件 inode |
| file_size | INTEGER | — | 文件大小 |
| file_type | TEXT | — | 文件类型 |

#### access_events（`:62-71`，INSERT `:296-299`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 分表内行号 |
| timestamp | INTEGER | NOT NULL | 对应 atime |
| file_path | TEXT | NOT NULL | 文件全路径 |
| inode | INTEGER | — | 文件 inode |
| file_size | INTEGER | — | 文件大小 |
| file_type | TEXT | — | 文件类型 |

#### deletion_events（`:85-94`，INSERT `:306-309`）

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 分表内行号 |
| timestamp | INTEGER | NOT NULL | 删除标记时刻（is_deleted 文件的 ctime） |
| file_path | TEXT | NOT NULL | 文件全路径 |
| inode | INTEGER | — | 文件 inode |
| file_size | INTEGER | — | 文件大小 |
| file_type | TEXT | — | 文件类型 |

### change_events

同上五列 + `description TEXT`（`event_extractor_sql.h:73-83`，INSERT 见 `:301-304`）——元数据变更比其他四类多一句"变了什么"。

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 分表内行号 |
| timestamp | INTEGER | NOT NULL | ctime 对应时刻 |
| file_path | TEXT | NOT NULL | 文件全路径 |
| inode | INTEGER | — | 文件 inode |
| file_size | INTEGER | — | 文件大小 |
| file_type | TEXT | — | 文件类型 |
| description | TEXT | — | 变更说明（如权限/属主变化） |

### system_events

建表 `event_extractor_sql.h:96-111`；写入 `INSERT_SYSTEM_EVENT`（`:311-314`，11 列），由 `SystemEventExtractor.cpp:211` 执行（从 Windows 事件日志 / Linux syslog 抽取）。

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 系统事件 ID |
| timestamp | INTEGER | NOT NULL | 事件时刻（unix 秒） |
| event_type | TEXT | NOT NULL | 系统事件类型（LOGIN/LOGOUT/SERVICE_START/NETWORK...） |
| source | TEXT | — | 来源（日志通道名/守护进程名） |
| user | TEXT | — | 涉及账户 |
| process | TEXT | — | 涉及进程 |
| ip_address | TEXT | — | 涉及 IP（远程登录/网络连接） |
| port | INTEGER | — | 涉及端口 |
| service | TEXT | — | 涉及服务名 |
| description | TEXT | — | 人读描述 |
| severity | TEXT | — | 严重程度（INFO/WARNING/...） |
| system_context | TEXT | — | 附加系统上下文 |

索引：`idx_system_events_timestamp(timestamp)`、`idx_system_events_type(event_type)`、`idx_system_events_source(source)`、`idx_system_events_user(user)`（`event_extractor_sql.h:135-138`）。

### event_correlations（注意：两处定义，列集不同）

这是全库唯一"同名两定义"的表：

1. **extractor 版**（先执行，生产生效）：`CREATE_EVENT_CORRELATIONS_TABLE`（`event_extractor_sql.h:113-124`），6 数据列 + 2 个声明式外键。
2. **engine 版**：`EventCorrelationEngineCore.cpp:123-138`，多 4 列（strength/direction/timestamp/rule_id）；因 `CREATE TABLE IF NOT EXISTS` 且 extractor 先建表，engine 版在生产库上**不会生效**。

生产表（extractor 版）列：

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 关联 ID |
| event_id1 | INTEGER | NOT NULL, FK→events(id) | 关联一侧事件 |
| event_id2 | INTEGER | NOT NULL, FK→events(id) | 关联另一侧事件 |
| correlation_type | TEXT | NOT NULL | 关联类型（TIME_BASED/SOURCE_BASED/TARGET_BASED/CONTEXT_BASED/SEQUENCE_BASED，规则注册见 `EventCorrelationEngineCore.cpp:35-95`） |
| confidence | REAL | NOT NULL | 置信度 0~1 |
| description | TEXT | — | 关联说明 |

engine 版多出的 4 列（写入方 `insertCorrelation`，`EventCorrelationEngineCore.cpp:223-249`）：`strength INTEGER`（强度枚举转 int）、`direction INTEGER`（方向枚举转 int）、`timestamp INTEGER`（关联发现时刻）、`rule_id TEXT`（命中规则 ID，如 `time_based_rule`）。

索引：`idx_event_correlations_event1/2(event_id1/2)`、`idx_event_correlations_type(correlation_type)`（两处都建，`event_extractor_sql.h:139-141` 与 `EventCorrelationEngineCore.cpp:211-212`）。

### event_chains（因果链）

建表 `EventCorrelationEngineCore.cpp:141-150`；写入 `insertEventChain`（`:251-326`）。

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| chain_id | TEXT | NOT NULL | 链标识（引擎生成的串） |
| description | TEXT | — | 链描述 |
| confidence | REAL | NOT NULL | 整链置信度 |
| start_time | INTEGER | — | 链内最早事件时刻 |
| end_time | INTEGER | — | 链内最晚事件时刻 |

### event_chain_nodes（因果链节点）

建表 `EventCorrelationEngineCore.cpp:153-162`；写入与链头同事务递归插入（`:277-325`，含防环 visitedNodes 逻辑，注释 `:283-286`）。

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 节点行号 |
| chain_id | TEXT | NOT NULL, FK→event_chains(chain_id) | 所属链 |
| event_id | INTEGER | NOT NULL, FK→events(id) | 该节点对应的 events 行 |
| parent_event_id | INTEGER | — | 父节点事件 ID（根节点为 NULL，`:299-303` 按 0/null 分支绑定） |

索引：`idx_event_chain_nodes_chain(chain_id)`（`EventCorrelationEngineCore.cpp:213`）。

### causal_relationships（因果关系对）

建表 `EventCorrelationEngineCore.cpp:165-177`；写入 `insertCausalRelationship`（`:328-351`）。

| 列 | 类型 | 约束/默认 | 含义 |
|----|------|-----------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 行号 |
| cause_event_id | INTEGER | NOT NULL, FK→events(id) | 因事件 |
| effect_event_id | INTEGER | NOT NULL, FK→events(id) | 果事件 |
| confidence | REAL | NOT NULL | 因果置信度 |
| description | TEXT | — | 因果说明 |
| time_delay | INTEGER | — | 因到果的时延（秒） |
| mechanism | TEXT | — | 因果机制描述 |

索引：`idx_causal_relationships_cause(cause_event_id)`、`idx_causal_relationships_effect(effect_event_id)`（`EventCorrelationEngineCore.cpp:214-215`）。

## 视图（SELECT 语义）

全部在 `EventExtractorCore.cpp:99-105` 执行创建，定义于 `event_extractor_sql.h:148-275`。

| 视图 | 定义行 | SELECT 语义 |
|------|--------|-------------|
| `timeline` | `:148-160` | events 主表投影：`datetime(timestamp,'unixepoch','localtime') AS event_time` + 类型/路径/inode/大小/描述，按 timestamp 倒序——人读时间线 |
| `event_statistics` | `:162-173` | 按事件类型聚合：count、首末事件（unix + 本地时间双格式）——"哪类事最多、何时开始结束" |
| `hourly_activity` | `:175-184` | 按 `strftime('%Y-%m-%d %H:00:00')` 小时桶 × 类型计数，倒序——活动热力图 |
| `system_event_view` | `:186-203` | system_events 的全列 + 本地时间化，倒序 |
| `event_correlation_view` | `:205-224` | 关联对两侧事件（id/类型/时间/路径）JOIN 展开，按置信度倒序 |
| `enhanced_timeline` | `:226-250` | events ∪ system_events 归一成 8 列流，`event_source` 常量列区分 'file'/'system'；注意末尾 `ORDER BY timestamp` 引用的是**内层列名**（输出列叫 event_time，SQLite 允许这种引用，实际按原始 timestamp 排） |
| `enhanced_event_statistics` | `:252-275` | 两表分别按类型聚合后 UNION，同 `event_source` 常量列区分 |

视图输出列速查（前端/查询方按列名取数）：

| 视图 | 输出列 |
|------|--------|
| timeline | event_time, event_type, file_path, inode, file_size, file_type, description |
| event_statistics | event_type, event_count, first_event, last_event, first_event_time, last_event_time |
| hourly_activity | hour, event_type, event_count |
| system_event_view | id, event_time, event_type, source, user, process, ip_address, port, service, description, severity, system_context |
| event_correlation_view | id, event_id1, event_type1, timestamp1, file_path1, event_id2, event_type2, timestamp2, file_path2, correlation_type, confidence, description |
| enhanced_timeline | id, event_time, event_type, file_path, inode, description, system_context, event_source |
| enhanced_event_statistics | event_type, event_count, first_event, last_event, first_event_time, last_event_time, event_source |

## 索引清单

extractor 建 11 个（`CREATE_EVENT_INDICES`，`event_extractor_sql.h:130-142`）：

| 索引 | 表.列 |
|------|-------|
| idx_events_timestamp | events(timestamp) |
| idx_events_type | events(event_type) |
| idx_events_path | events(file_path) |
| idx_events_inode | events(inode) |
| idx_system_events_timestamp | system_events(timestamp) |
| idx_system_events_type | system_events(event_type) |
| idx_system_events_source | system_events(source) |
| idx_system_events_user | system_events(user) |
| idx_event_correlations_event1 | event_correlations(event_id1) |
| idx_event_correlations_event2 | event_correlations(event_id2) |
| idx_event_correlations_type | event_correlations(correlation_type) |

EngineCore 另建 5 个（`EventCorrelationEngineCore.cpp:210-216`）：上表最后 3 个与之同名（幂等跳过），新增 `idx_event_chain_nodes_chain(chain_id)`、`idx_causal_relationships_cause/effect`。

## 写入列 vs 建表列对照（INSERT 覆盖面）

| 表 | 建表列数 | INSERT 写入列 | 恒 NULL 的列（写入方不碰） |
|----|---------|--------------|---------------------------|
| events | 21 | 14（`INSERT_EVENT`，`event_extractor_sql.h:281-284`） | llm_* 6 列 + normalized_type/source_id/system_context（后三者由标准化/系统抽取阶段另行 UPDATE） |
| creation/modification/access/deletion_events | 6 | 5 | 无 |
| change_events | 7 | 6 | 无 |
| system_events | 12 | 11 | 无 |
| event_correlations | 6 | 5 | 无 |
| event_chains / event_chain_nodes / causal_relationships | 6/5/7 | 5/3/6 | 引擎写全量（但引擎无生产入口） |

## 跨表关联键

- **库内**：`event_correlations.event_id1/2`、`event_chain_nodes.event_id`、`causal_relationships.cause/effect_event_id` → `events.id`（本库仅有的显式 FOREIGN KEY 声明，但 SQLite 逻辑对齐文化下它们只是文档性的）。
- **跨库**：`events.inode` → raw.db `files.inode`（+partition_num），`events.file_path` → files.db `files.path`。

真实 JOIN 示例（把事件与 files.db 的分类/LLM 结论拼成完整时间线，DatabaseSchema.md 第 10 节原例）：

```sql
ATTACH DATABASE 'data/tasks/<task_id>/files.db' AS f;
SELECT e.timestamp, e.event_type, f.name, f.category, f.llm_summary
FROM events e JOIN f.files f ON e.inode = f.inode
ORDER BY e.timestamp DESC;
```

库内关联示例（视图 `event_correlation_view` 的手工等价写法）：

```sql
SELECT ec.id, e1.event_type AS t1, e2.event_type AS t2, ec.confidence
FROM event_correlations ec
JOIN events e1 ON ec.event_id1 = e1.id
JOIN events e2 ON ec.event_id2 = e2.id;
```

## 已知边界

- **`event_correlations` / `event_chains` / `event_chain_nodes` / `causal_relationships` 生产恒空**：写入方是 `EventCorrelationEngine`，其唯一入口 `EventExtractor::analyzeEventCorrelations()`（`EventCorrelationExtractor.cpp:31` 定义，`EventExtractor.h:116` 声明）**没有生产调用方**——任务流水线从不调它，只有单测调用。这 4 张表在任务产出中必然 0 行，查询它们不会报错但无数据。
- **event_correlations 的双定义陷阱**：若有人绕过 extractor 直跑 engine 建表（如单测环境先建 engine 版），engine 的 `INSERT`（9 列）与 extractor 版表（6 列）不兼容，prepare 会失败——两个模块各自假设"自己先建表"。以代码为准：生产顺序是 extractor 先建（6 列）。
- **分表 id 与主表 id 不同源**：类型分表是独立自增，不能拿 `creation_events.id` 去 JOIN `events.id`；分表与主表只能靠 `(timestamp, file_path, inode)` 对齐。
- **`llm_*` 列默认 NULL**：`INSERT_EVENT` 不含这些列；只有跑过 LLM 事件簇分析（`UPDATE_EVENT_CLUSTER_LLM_ANALYSIS` 按"分钟桶+类型+路径目录"定位簇，`event_extractor_sql.h:354-364`）后才有值。
- **关联表外键依赖 `PRAGMA foreign_keys`**：DatabaseManager 打开时开了 ON，但 EventExtractor 自开的连接未显式设置，FK 实际不强制——本就无外键文化（决定二），此处只是声明性残留。

---


## 附录：写入时序与查询手册

### 写入时序

| 表 | 写入方 | 时机 | 量级 |
|----|--------|------|------|
| `events` + 5 张类型表 | EventExtractor::extractEvents | EVENT_EXTRACTION 阶段一次写入（读 effectiveRawDb） | 每文件最多 5 事件 |
| `system_events` | EventExtractor（系统类） | 同上 | 少量 |
| `event_correlations` | extractor 版 DDL 建表 | 引擎未接线→**生产为空** | 0 |
| `event_chains/_nodes/causal_relationships` | EventCorrelationEngineCore | 引擎未接线→**生产为空** | 0 |
| LLM 列（6 个 ALTER 自愈列） | TimelineQueries 打开库时探测补列 | comprehensive 路径首次查询时 | — |

### 查询手册

**1. 时间窗内的事件（初筛主力）**
```sql
SELECT datetime(timestamp,'unixepoch') t, event_type, file_path, file_size
FROM events WHERE timestamp BETWEEN strftime('%s','2026-08-20 18:00') AND strftime('%s','2026-08-20 20:00')
ORDER BY timestamp;
```

**2. 删除事件专项（痕迹清除排查）**
```sql
SELECT datetime(timestamp,'unixepoch'), file_path, file_size
FROM deletion_events ORDER BY timestamp;
-- 或主表： WHERE event_type='DELETED'
```

**3. 按小时分布（找爆发/静默段）**
```sql
SELECT strftime('%Y-%m-%d %H:00', timestamp,'unixepoch') h, COUNT(*) c
FROM events GROUP BY h ORDER BY h;
```

**4. 目录活动热点**
```sql
SELECT rtrim(file_path, replace(file_path,'/','')) dir, COUNT(*) c
FROM events GROUP BY dir ORDER BY c DESC LIMIT 30;
```

**5. 主表与类型表对账（抽取完整性自检）**
```sql
SELECT (SELECT COUNT(*) FROM events) total,
       (SELECT COUNT(*) FROM creation_events) created,
       (SELECT COUNT(*) FROM modification_events) modified,
       (SELECT COUNT(*) FROM deletion_events) deleted;
```
读法：total ≈ 五表之和 + system_events；偏差大说明中途重跑/中断过（标准化幂等只扫 NULL 行）。

**6. 疑似模式直查（服务端 suspicious-patterns 的 SQL 版）**
```sql
SELECT file_path, COUNT(DISTINCT event_type) kinds, COUNT(*) c
FROM events WHERE file_path LIKE '%/tmp/%' OR file_path LIKE '%/dev/shm/%'
GROUP BY file_path HAVING kinds>=3 ORDER BY c DESC;
```
**最后更新**: 2026-08-24（补：写入时序与查询手册）
