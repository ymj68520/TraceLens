# SQLiteHelper（src/network/HTTPServer/SQLiteHelper.{h,cpp} + Queries/）

> **一句话**：HTTP 层的只读数据访问层——40 多个静态方法把"打开任务产出库 → 查询 → 组装 JSON"固化成可复用单元，实现按查询域拆在 Queries/ 六个文件里；顺带提供 LIMIT/OFFSET 钳制与 SQL 注入防御工具。

## 1. 为什么有这个模块

路由 handler 如果各自手写 sqlite3_open/prepare/step/close，会产生三重复制：连接管理样板、行→JSON 转换样板、以及每个端点一份的安全边界（limit 钳制、只读校验）。SQLiteHelper 把这些收拢为静态方法库：**handler 只负责解析 HTTP 参数与选择查询，SQL 与防御逻辑集中在一处**。它不写业务数据——产出库由流水线写入，本模块几乎全是 SELECT（唯一的写是导出文件）。

## 2. 在系统中的位置

```
查询类路由（Timeline/FileAnalysis/Statistics/AndroidForensics/EventCluster...）
   │  RouteHelpers::get_database_path(task_id, "events"/"files"/...)
   ▼
SQLiteHelper::get_xxx(db_path, 参数...)
   │  open_database → execute_query(参数化) → json 数组
   ▼
任务的 _raw.db / _events.db / _files.db / android.db / _oss.db ...
```

- **上游**：所有 /api/forensics/* 查询路由；TaskCRUDRoutes 的结果端点（get_file_summary、get_llm_results）。
- **路径解析**：路由先经 `RouteHelpers::get_database_path`（routes/RouteHelpers.cpp:35-90）把 task_id+db 类型解析成实际文件路径——android 类型带三级回退（metadata.android_db → 同目录 android.db → raw 库旁路推导），memory 类型会剥掉 `_raw` 后缀。
- **下游**：只有 SQLite 文件，无其他服务依赖。

## 3. 核心概念与设计

### 3.1 为什么按"查询域"拆到 Queries/

原 SQLiteHelper.cpp 曾是 1519 行的单体（Queries/README.md 的历史记录）。拆分的轴线不是技术层（不是"DAO/服务"两层），而是**查询域**——因为消费它们的前端页面就是按域划分的：

| 文件 | 域 | 典型消费者 |
|---|---|---|
| SQLiteHelperCore.cpp | 连接/执行/钳制/校验等基座 | 全部 |
| TimelineQueries.cpp | 综合时间线、簇详情、分布、按类型/时间/文件过滤 | /timeline 页 |
| FileAnalysisQueries.cpp | 最大/最近/可疑/重复文件、扩展分析、LLM 结果 | /files 页 |
| StatisticsQueries.cpp | 总览、文件分布、活跃模式、删除文件、用户活动 | /statistics 页 |
| AndroidQueries.cpp | 通信摘要、应用使用、设备信息、媒体、MIUI/QQNT/微信 | /android 页 |
| EventExportQueries.cpp | JSON/CSV/可视化导出 | 导出按钮 |

拆分带来的直接收益：改时间线查询不用重读 Android 查询；新查询域加一个文件即可（见 §7）。

**实现细节**：Queries/*.cpp 不是独立编译单元，而是被 `SQLiteHelper.cpp:10-15` **以 #include 方式聚合**成一个翻译单元（所以它们仍能使用类的 private 成员）：

```cpp
// SQLiteHelper.cpp:1-15（节选）
#include "SQLiteHelper.h"
// ...
// Include modular query implementations
#include "Queries/SQLiteHelperCore.cpp"
#include "Queries/TimelineQueries.cpp"
#include "Queries/FileAnalysisQueries.cpp"
#include "Queries/StatisticsQueries.cpp"
#include "Queries/AndroidQueries.cpp"
#include "Queries/EventExportQueries.cpp"
```

include .cpp 是有意的权衡：private 方法（execute_query、table_exists 等）不必暴露成 public 或 friend。代价是这些文件**不能进 CMake 独立编译**——Queries/README.md 里"registered in CMakeLists.txt"的说法与现状不符，CMake 只编译 SQLiteHelper.cpp。

### 3.2 基座三件套（SQLiteHelperCore.cpp）

`open_database`（:17-25）统一失败即返回错误 JSON 的打开；`execute_query` 把每行按**列名→值**动态转成 JSON 对象：

```cpp
// SQLiteHelperCore.cpp:69-99（参数化 execute_query，节选）
json SQLiteHelper::execute_query(sqlite3* db, const std::string& sql,
                                 const std::vector<std::string>& params) {
    json result = json::array();
    sqlite3_stmt* stmt = nullptr;

    if (sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        // ...（仅打日志、finalize、返回空数组）
    }
    for (size_t i = 0; i < params.size(); ++i) {
        sqlite3_bind_text(stmt, static_cast<int>(i + 1), params[i].c_str(), -1, SQLITE_TRANSIENT);
    }
    int column_count = sqlite3_column_count(stmt);
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        json row = json::object();
        for (int i = 0; i < column_count; i++) {
            const char* column_name = sqlite3_column_name(stmt, i);
            switch (sqlite3_column_type(stmt, i)) {
                case SQLITE_INTEGER: row[column_name] = sqlite3_column_int64(stmt, i); break;
                case SQLITE_FLOAT:   row[column_name] = sqlite3_column_double(stmt, i); break;
                case SQLITE_TEXT:    row[column_name] = std::string(reinterpret_cast<const char*>(sqlite3_column_text(stmt, i))); break;
                case SQLITE_BLOB:    row[column_name] = "<BLOB_DATA>"; break;
                case SQLITE_NULL:    row[column_name] = nullptr; break;
            }
        }
        result.push_back(row);
    }
    sqlite3_finalize(stmt);
    return result;
}
```

三处细节值得注意：**参数按顺序全绑成 TEXT**——即使值是数字也以字符串绑定，SQLite 的动态类型会按列亲和性转换，换来的是"用户输入永不拼接进 SQL"这条铁律；BLOB 显示为 `<BLOB_DATA>` 占位符，二进制证据内容不会撑爆 JSON 响应（代价是没有任何端点能取回 BLOB 原文）；prepare 失败只 cerr + 返回空数组，**不把错误塞进结果**——调用方拿到的空数组与"真的没数据"无法区分，排障要看服务端日志。schema 容错靠 `table_exists`/`column_exists`（:167-201）：查询在旧版本产出库（缺新表/新列）上优雅降级而不是 500。

### 3.3 防御工具：HTTP 参数不能直接进 SQL

四个公开的加固函数（SQLiteHelper.h:338-356）：

- `clamp_limit` / `clamp_offset`：把 limit 钳到 [默认 1000, 上限 100000]、offset 钳非负——防"limit=999999999"式 DoS；
- `is_readonly_select(sql)`：只有"单条只读 SELECT/CTE、无分号无注释无 DDL/DML/ATTACH/PRAGMA"才放行——导出端点的自定义 `query` 参数靠它防二次注入；
- `is_safe_filter_clause(clause)`：对 WHERE 片段做同类 token 黑名单校验。

```cpp
// SQLiteHelperCore.cpp:101-108
int SQLiteHelper::clamp_limit(int limit, int def_val, int max_val) {
    if (limit <= 0) return def_val;
    return limit > max_val ? max_val : limit;
}

int SQLiteHelper::clamp_offset(int offset) {
    return offset < 0 ? 0 : offset;
}
```

钳制的语义：非正数（含缺省 0/负数/解析失败）回落默认值而非报错——前端传错值时端点仍可用，只是行数变默认；超过上限直接截断。这让 DoS 防御对客户端完全透明。

```cpp
// SQLiteHelperCore.cpp:130-153
bool SQLiteHelper::is_readonly_select(const std::string& sql) {
    // Trim leading/trailing whitespace.
    size_t b = sql.find_first_not_of(" \t\r\n");
    if (b == std::string::npos) return true;  // empty -> caller uses default
    size_t e = sql.find_last_not_of(" \t\r\n");
    std::string trimmed = sql.substr(b, e - b + 1);

    // No SQL comments (could hide a second statement or bypass checks).
    if (trimmed.find("--") != std::string::npos || trimmed.find("/*") != std::string::npos) {
        return false;
    }
    // Single statement only: allow a single optional trailing ';'.
    size_t semi = trimmed.find(';');
    if (semi != std::string::npos && semi != trimmed.size() - 1) return false;

    std::string upper = trimmed;
    std::transform(upper.begin(), upper.end(), upper.begin(), ::toupper);
    // Must begin with SELECT or WITH (CTE ending in SELECT).
    if (upper.rfind("SELECT", 0) != 0 && upper.rfind("WITH", 0) != 0) return false;

    return !contains_forbidden_token(upper,
        {"ATTACH", "DETACH", "PRAGMA", "INSERT", "UPDATE", "DELETE", "DROP",
         "ALTER", "CREATE", "REPLACE", "VACUUM", "REINDEX"});
}
```

校验是五道闸门按序过滤：空串放行（调用方替换默认查询）；**注释先杀**——`--`/`/*` 可能藏第二条语句或干扰后续 token 匹配；分号只允许出现在末尾一位（挡 `SELECT 1; DROP TABLE x`）；必须以 SELECT/WITH 开头（挡 `xxx UNION SELECT` 前缀、也挡内置函数如 `load_extension` 起头）；最后 `contains_forbidden_token`（:112-128）做**整词**黑名单匹配——`left_ok`/`right_ok` 检查词边界，所以 `CREATED` 里的 "CREATE" 子串不会误伤（事件类型恰好叫 CREATED/MODIFIED，不做词边界匹配会把合法过滤全拒掉）。空格+大小写变形（`sElEcT`、`SELECT/**/...`）分别被 toupper 与注释禁令覆盖；但注意它防的是"自定义 query 参数被塞进第二条语句"，不是通用 SQL 注入——常规查询的用户输入全走参数绑定，根本不经过这里。

### 3.4 时间线簇：与 EventClusterAnalyzer 同一套语义

`get_comprehensive_timeline` 的 `cluster_events=true` 时按"同 bucket_seconds（默认 60）窗口 + 同类型 + 同父目录"聚合（SQLiteHelper.h:22-32 文档注释），与 EventClusterAnalyzer 的簇定义（EventClusterAnalyzer.cpp:443-451 的 GROUP BY）对齐——展示分组与分析单元一致，簇抽屉里的 LLM 结果才能对得上号。`get_timeline_details` 要求传入与聚簇时相同的 bucket_seconds（h:36-38）。

聚合 SQL 的核心（TimelineQueries.cpp，详见 §4.2 的走读）：`GROUP BY parent_directory, (timestamp / bucket_seconds), event_type`——父目录表达式 `RTRIM(file_path, REPLACE(file_path,'/',''))`（:132-133）用"先删掉所有斜杠得到 basename 字符集、再从右剥离该集合字符"的手法求父目录，能正确处理多级路径（/etc/ssh/sshd_config → /etc/ssh/），注释里记录了旧 INSTR 方案只找第一个斜径导致聚簇失效的教训。

## 4. 工作流程走读

### 4.1 以"时间线页请求某任务的簇列表"为例

1. 路由层拿到 task_id 与 db=events，经 RouteHelpers 解析出 `_events.db` 绝对路径；
2. handler 解析 HTTP 参数（limit 经 clamp_limit 钳制）后调 `SQLiteHelper::get_comprehensive_timeline(raw_db, events_db, ..., cluster_events=true, bucket_seconds=60)`；
3. TimelineQueries 里 open_database → execute_query（用户时间串经 parse_timestamp 转换后参数绑定）→ 逐行组 JSON；
4. 缺表/缺列时经 table_exists 分支返回空集或降级字段；
5. handler 包一层 CORS 头后返回。

```cpp
// TimelineQueries.cpp:87-116（防御性准备段，节选）
// Ensure events table has AI columns (Self-healing)
const char* ai_cols[] = {"llm_summary", "llm_description", "llm_keywords", "llm_analyzed_at", "llm_model_used", "llm_is_relevant"};
for (const char* col : ai_cols) {
    std::string type = (std::string(col).find("_at") != std::string::npos || std::string(col).find("_is_") != std::string::npos) ? "INTEGER" : "TEXT";
    std::string alter_sql = "ALTER TABLE events ADD COLUMN " + std::string(col) + " " + type + ";";
    sqlite3_exec(events, alter_sql.c_str(), nullptr, nullptr, nullptr);
}

limit = clamp_limit(limit);
offset = clamp_offset(offset);
// Clamp bucket_seconds to a sane range. It is an integer derived from the
// query string and used directly in SQL via std::to_string (safe), but we
// guard against 0/negative to avoid divide-by-zero and absurd windows.
if (bucket_seconds < 1) bucket_seconds = 60;
if (bucket_seconds > 86400) bucket_seconds = 86400;
```

WHERE 构造段（:103-116）同样体现"按数据种类区别对待"：时间参数先经 `parse_timestamp` 转成 int64 再拼接（数字无注入面）；event_type 是文本，只能走 `?` 绑定（`bind.push_back(event_type)`）；bucket_seconds/limit/offset 先钳制成安全整数再 `std::to_string` 拼接（代码注释明说了各自安全的原因）。最有趣的是开头六条 ALTER TABLE"自愈"——打开 events 库时顺手补齐 LLM 六列，忽略失败（列已存在时 sqlite3_exec 报错被吞掉），这让旧版本产出库在查询时被升级到能承接簇分析回写。**这也意味着本模块并非纯只读**：对 events 表结构有一处固定的写操作。

### 4.2 聚簇主查询与计数查询

```cpp
// TimelineQueries.cpp:155-185（主查询构造，节选）
if (cluster_events) {
    // Reuse the parent directory expression (see comment above).
    const std::string& parent_dir_sql = parent_dir_expr;

    sql = R"(
        SELECT
            MIN(timestamp) as timestamp,
            MAX(timestamp) as end_timestamp,
            (timestamp / )" + std::to_string(bucket_seconds) + R"() as bucket_index,
            event_type,
            COUNT(*) as cluster_count,
            file_path, -- Representative file path
            )" + parent_dir_sql + R"( as parent_directory,
            inode,
            description,
            SUM(COALESCE(file_size, 0)) as file_size,
                file_type,
                llm_summary,
                // ...（llm_description / llm_keywords / llm_is_relevant）
            FROM events
        )";
    sql += where_clause;
    // Group by parent directory first, then time window and event type
    // This creates separate clusters for different directories.
    // bucket_seconds is a clamped integer (validated above), so std::to_string
    // is safe here — no injection risk.
    sql += " GROUP BY parent_directory, (timestamp / " + std::to_string(bucket_seconds) + "), event_type";
}
```

每行的语义：一簇 = 同目录+同时间窗+同事件类型的 N 个事件，`cluster_count` 是簇大小、MIN/MAX 时间戳给出簇的起止、file_path 是"代表文件"、llm_* 四列把簇级 AI 分析结果随簇带出（没有分析过就是 NULL）。计数查询（:135-141）必须数"组数"而不是"行数"——`SELECT COUNT(*) FROM (SELECT 1 ... GROUP BY 同三元组)`，注释强调两处 GROUP BY 必须完全一致否则分页 totalPages 就错。结果行还附带 `group_descriptor{bucket_index, bucket_seconds, event_type, parent_directory, bucket_start_timestamp}`（:209-221），前端拿它原样调 timeline/details 即可定位同一簇——`bucket_start_timestamp = bucket_index × bucket_seconds` 让"组下标"始终可还原为 Unix 起点。

导出路径（EventExportQueries）多一步：校验 `query` 参数通过 `is_readonly_select` 后才允许执行，结果写输出文件并回 JSON 状态。

## 5. 与其他模块的协作

| 协作方 | 关系 |
|---|---|
| 查询路由（ForensicsRoutes 族） | 主要消费者，一一对应查询域 |
| RouteHelpers | 前置的 db 路径解析 |
| 流水线产出库 | 数据来源（结构由各分析器的 SQL 头文件定义） |
| EventClusterAnalyzer | 共享簇定义（60 秒窗 + 同类型 + 同父目录）；前者写 llm_* 列，本模块读 |
| Swagger 注册 | 无——本模块不感知 HTTP，只产出 JSON 值 |

路由↔查询↔表 的对应链（部分）：

| 端点 | SQLiteHelper 方法 | 查询域文件 | 主要表 |
|---|---|---|---|
| timeline/comprehensive | get_comprehensive_timeline | TimelineQueries.cpp:76 | events |
| timeline/details | get_timeline_details | TimelineQueries.cpp:14 | events |
| files/largest | get_largest_files | FileAnalysisQueries | files |
| statistics/overview | get_overview_statistics | StatisticsQueries | files/events/partitions |
| android/communication-summary | get_android_communication_summary | AndroidQueries | android.db 各表 |
| tasks/{id}/results | get_file_summary + get_llm_results | FileAnalysisQueries | files、file_descriptions |

## 6. 注意事项与已知问题

- **每次查询重开连接**：每个静态方法自开自关 sqlite3 句柄；单次请求多次查询时有开销，但避免了跨线程共享连接的坑——当前 QPS 下合理。
- **错误返回在 JSON 值里而非状态码**：open 失败时 error 塞进结果 JSON（Core.cpp:19-21），由路由决定怎么呈递；新 handler 记得检查。而 execute_query 的 prepare 失败**连 error 字段都没有**，只打服务端日志。
- **Queries/README.md 的 CMake 说法过时**：见 §3.1；新查询文件务必加入 SQLiteHelper.cpp:10-15 的 include 列表而不是 CMake。
- **簇 bucket 必须两侧一致**：前端改 bucket_seconds 传参后，簇分析（60 秒硬编码）不会跟着变，会出现"展示有簇、分析对不上"的错位。
- **ALTER TABLE 自愈只在 comprehensive 路径触发**：只调 timeline/details 或其他 events 查询的旧库不会被补列，簇分析回写时会撞缺列错误——自愈不具全局性。
- **table_exists 用字符串拼接表名**（Core.cpp:168）：表名来自代码内常量而非用户输入，当前安全；若将来允许调用方传任意表名，这里就是注入点。

## 7. 如何验证与扩展

- **验证**：对任一完成任务 `sqlite3 data/tasks/<id>/*_events.db ".tables"` 确认表存在，再 curl 对应 /api/forensics/timeline/... 端点比对行数；构造 `?limit=-5` 与 `?limit=99999999` 观察钳制；对导出端点传 `query=DROP TABLE events` 应被拒、传 `query=SELECT * FROM events WHERE event_type LIKE '%DROP%'` 应放行（词边界不误伤）。
- **扩展新查询**：在对应域文件加静态方法（新域则新建文件并加入 SQLiteHelper.cpp:10-15 的 include）；规则——用户输入一律走参数化 execute_query，limit/offset 必经 clamp，新表访问前先 table_exists 降级，时间串先 parse_timestamp。

## 8. 公开方法全清单（二轮补全，按查询域）

SQLiteHelper.h 声明的全部公开静态方法（35 个查询 + 4 个加固工具），逐一标注所属域文件：

| 域 | 方法（h 行号） |
|---|---|
| 基础（Core） | get_file_summary（:11） |
| Timeline 基础 | get_comprehensive_timeline（:29）、get_timeline_details（:40）、get_timeline_distribution（:53）、get_file_activity_timeline（:63）、get_suspicious_patterns（:72）、get_user_activity_analysis（:80）、get_system_events（:91）、get_system_event_summary（:98） |
| Timeline 增强 | get_timeline_by_type（:273）、get_timeline_by_time_range（:283）、get_timeline_by_file（:292）、get_timeline_full（:301）、get_event_statistics_by_period（:309） |
| FileAnalysis | get_largest_files（:108）、get_recent_files（:116）、get_suspicious_files（:124）、get_duplicate_files（:131）、get_extensions_analysis（:138）、get_llm_results（:145） |
| Android | get_android_communication_summary（:154）、get_android_app_usage（:161）、get_android_device_info（:168）、get_android_media_analysis（:175）、get_android_llm_summary（:231） |
| MIUI | get_miui_backup_overview（:183）、get_miui_installed_apps（:190）、get_miui_db_inventory（:197）、get_miui_qqnt_overview/artifacts/records（:200-210）、get_miui_wechat_overview/artifacts/records（:213-223） |
| Statistics | get_overview_statistics（:242）、get_file_distribution_analysis（:249）、get_activity_patterns（:256）、get_deleted_files_analysis（:263） |
| Export | export_events_to_json（:319）、export_events_to_csv（:328）、export_events_for_visualization（:336） |
| 加固工具 | clamp_limit（:343）、clamp_offset（:345）、is_readonly_select（:351）、is_safe_filter_clause（:356） |

私有基座（h:358-372）：open_database、execute_query ×2（无参/参数化重载）、table_exists、column_exists、format_timestamp、parse_timestamp、is_suspicious_extension、is_suspicious_path、get_total_event_count。

## 9. 新走读分支：时间解析与格式化的时区不对称（新发现）

`parse_timestamp`（SQLiteHelperCore.cpp:212-246）按序尝试三种格式，**全部用 `std::mktime`（本地时区）**：

```cpp
// SQLiteHelperCore.cpp:212-246（三级解析，节选）
// 1. 首先尝试纯 Unix 秒数字（最常见路径，保持性能）
try { return std::stoll(time_str); } catch (...) {}

// 2. 尝试 ISO 8601 日期格式 "YYYY-MM-DD"
if (time_str.size() == 10) {
    // get_time + mktime（本地时区）
}
// 3. 尝试 ISO 8601 带时间 "YYYY-MM-DDTHH:MM:SS" 或 "YYYY-MM-DD HH:MM:SS"
if (time_str.size() >= 19) {
    std::string normalized = time_str.substr(0, 19);
    if (normalized[10] == 'T') normalized[10] = ' ';
    // get_time + mktime（本地时区）
}
```

而 `format_timestamp`（:203-210）用 `std::gmtime`（**UTC**）输出 `"YYYY-MM-DD HH:MM:SS UTC"`。组合效果：**入口把本地时间串解释成本地 epoch，出口把 epoch 显示成 UTC**——一个 `2026-08-24 10:00:00` 的过滤串在 UTC+8 机器上会变成 02:00 UTC 显示，前后差一个时区。纯 Unix 秒输入（最常见路径）不受影响（stoll 不涉及时区）。三格式细节：长度恰 10 走日期、≥19 截前 19 字符并把 T 换空格、毫秒后缀（.123Z 或 +08:00）**被静默丢弃**（截断在 19 位）；无法识别的串打 stderr 后返回 0——0 是"无过滤"的哨兵（调用方判 0 跳过 WHERE），所以垃圾时间串的语义是"不过滤"而非报错。

## 10. 连接行为的并发细节（新发现）

`open_database`（Core.cpp:17-25）是**裸 `sqlite3_open`**：不设 busy_timeout、不开 READONLY 标志、不设 WAL。三个推论：

1. **`DB_BUSY_TIMEOUT_MS` 不覆盖 HTTP 查询路径**——该配置只在 DatabaseManager（写侧）生效；查询侧遇写者持锁时 `sqlite3_step` 立即返回 SQLITE_BUSY，execute_query 的循环条件 `== SQLITE_ROW` 直接结束，返回**空数组**（不是错误）。实际被 WAL（写侧建库时已开）+ 每任务独立库的结构救场：多读者单写者在 WAL 下并存，BUSY 几乎不出现。但手工对产出库做非 WAL 写入（如用 sqlite3 CLI 改数据）期间查询会静默变空。
2. **查询连接具备写权限**——ALTER 自愈（§4.1）正依赖这一点；反过来也意味着 is_readonly_select 的防线是唯一阻止自定义 query 参数写库的东西，它漏什么就写什么。
3. 每方法自开自关（§6 已记）+ 无连接池；Crow 每 worker 并发查询时连接数 = 并发请求数，SQLite 文件锁页（POSIX advisory lock）在关闭时释放，无跨请求泄漏。

## 11. 可疑判定的完整模式表

`is_suspicious_extension`（:248-257）与 `is_suspicious_path`（:259-274）两个启发式列表，get_suspicious_files 的判定依据：

| 函数 | 匹配规则 | 命中即"可疑" |
|---|---|---|
| is_suspicious_extension | 扩展名（tolower 后精确等值） | .bat .cmd .scr .vbs .js .jar .exe .com .pif |
| is_suspicious_path | 路径（tolower 后子串） | /temp/ 、/tmp/ 、recycle 、$recycle 、system32 |

注意子串匹配的宽窄：`system32` 命中任何含该串的路径（包括 SysWOW64 下的 system32 引用、文档里提到 system32 的文件名）；`recycle` 双拼写覆盖 Windows 回收站两种大小写形态。改列表只动这两个函数，无其他配置点。

## 12. 配置影响表（SQLiteHelper 视角）

| 配置 | 默认 | 关系 | 说明 |
|---|---|---|---|
| `DB_JOURNAL_MODE` / `DB_BUSY_TIMEOUT_MS` | WAL / 5000 | **仅写侧（DatabaseManager）** | 查询侧不读这两个变量（§10.1）——WAL 是建库时落盘的库属性，查询连接间接受益 |
| `SEARCH_*` 四项 | 见 Environment.md | 不相关 | 全文检索走 Xapian（SearchRoutes），不经本模块 |
| `CORS_ALLOW_ORIGIN` | `*` | 路由层 | RouteHelpers 在 handler 里加头，与本模块无耦合 |
| （无 limit/offset 的 env） | 1000/100000 硬编码 | clamp_limit 参数 | 想改默认页大小只能改代码或各路由传参 |
| `bucket_seconds`（请求参数） | 60，钳制 [1, 86400] | TimelineQueries | §4.1 的钳制区间；与 EventClusterAnalyzer 硬编码 60 的错位见 §6 |

## 13. Queries 六文件的规模与承载（真实行数）

| 文件 | 行数 | 公开方法数（§8 清单） | 密度说明 |
|---|---|---|---|
| AndroidQueries.cpp | 651 | 14 | 最大——MIUI/QQNT/微信三族的脱敏与分页逻辑集中于此 |
| TimelineQueries.cpp | 444 | 13 | 聚簇 SQL + 自愈 ALTER 都在这 |
| StatisticsQueries.cpp | 456 | 4 | 单方法最重（overview 跨三库） |
| FileAnalysisQueries.cpp | 244 | 6 | |
| EventExportQueries.cpp | 200 | 3 | query 校验 + 文件写出 |
| SQLiteHelperCore.cpp | 288 | 基座 | 含 4 个加固函数 |

合计 2283 行实现（全部被 SQLiteHelper.cpp include 成单翻译单元，§3.1）。改动的编译放大效应：动任何一行 Queries/*.cpp 都重编整个 SQLiteHelper.cpp 及其下游——增量构建粒度是"整个查询层"。

## 14. 值序列化示例（execute_query 五分支的输入输出对照）

| SQLite 存储类型 | JSON 输出 | 备注 |
|---|---|---|
| INTEGER（如 file_size=1024） | `"file_size": 1024`（int64） | 无精度损失 |
| FLOAT（如 score=0.5） | `"score": 0.5`（double） | |
| TEXT（如 path） | `"path": "/etc/passwd"` | 非 UTF-8 字节**原样透传**——json dump 时若含非法 UTF-8 会抛 type_error.316！Core 的 execute_query 没有 sanitize（对比 LLMClient 的 sanitizeUtf8）——病态文件名能让查询端点 500 |
| BLOB | `"content": "<BLOB_DATA>"` | 恒占位串 |
| NULL | `"mtime": null` | 前端要判 null |

**TEXT 分支的 UTF-8 风险是本模块未设防的面**：产出库的 path/description 来自镜像文件系统，取证镜像里混入非 UTF-8 文件名是常态；一旦命中，json::array 的 dump() 在 handler 里抛异常 → 500。绕过手段是查询层加与 LLMClient 同款的清洗——目前两处实现（严格版/宽松版）都现成，只差接线。

## 15. 验证 runbook

```bash
# 1. 钳制行为
curl -s ":8080/api/forensics/timeline/comprehensive?task_id=<id>&limit=-5" | jq '.pagination // .limit'
curl -s ":8080/api/forensics/timeline/comprehensive?task_id=<id>&limit=99999999" | jq '.events | length'  # ≤100000
# 2. 注入防御（导出端点）
curl -s ":8080/api/forensics/export/events/json?task_id=<id>&query=SELECT%201;DROP%20TABLE%20events" | jq .   # 拒绝
curl -s ":8080/api/forensics/export/events/json?task_id=<id>&query=SELECT%20*%20FROM%20events%20WHERE%20event_type%20LIKE%20%27%25CREATED%25%27" | jq .  # 放行（词边界）
# 3. 时区不对称复现（§9）
TZ=Asia/Shanghai curl -s ":8080/api/forensics/timeline/comprehensive?task_id=<id>&start_time=2026-08-24%2010:00:00" | jq '.events[0].timestamp'
# 4. BUSY 行为（§10）：sqlite3 CLI 写期间查询
sqlite3 data/tasks/<id>/*_events.db "BEGIN; UPDATE events SET description='x' WHERE id=1;" &
curl -s ":8080/api/forensics/timeline/full?task_id=<id>" | jq '.events | length'   # WAL 下通常仍正常
```


## 8. 常见任务配方

### 配方 A：新增一个查询域方法
1. `Queries/` 对应域文件实现（或新建文件并在 `SQLiteHelper.cpp:10-15` 的 include 聚合里挂上——注意是 include 聚合不是独立编译单元）。
2. 头文件声明；参数走防御三件套（`clamp_limit`、`is_readonly_select`、参数化绑定）。
3. 路由接线：对应 Routes 调用。
4. 验证：对 fixture 库跑一遍 + 空/越界参数不炸。

### 配方 B：补索引的正确姿势
对照 [schema 各库"索引缺口"](../../schema/AndroidDB.md) 清单：在**建表 SQL 头文件**补 `CREATE INDEX IF NOT EXISTS`（SQL-as-headers 纪律），而不是对存量库手工加——代码路径的"探测+ALTER"不覆盖索引。

### 配方 C：慢查询定位
1. 打开库 `PRAGMA query_plan` 看扫描；2. 大表（files/events）优先查索引清单；3. 时间范围查询确认 timestamp 有索引（events 有 11 条单列索引，files 主表三索引）；4. 结果集大时分页（limit/offset 由 clamp 兜底）。
**最后更新**: 2026-08-24（二轮深化：补全方法清单与契约细节）
