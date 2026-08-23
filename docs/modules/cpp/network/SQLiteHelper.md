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

**实现细节**：Queries/*.cpp 不是独立编译单元，而是被 `SQLiteHelper.cpp:10-15` **以 #include 方式聚合**成一个翻译单元（所以它们仍能使用类的 private 成员）。Queries/README.md 里"registered in CMakeLists.txt"的说法与现状不符——CMake 只编译 SQLiteHelper.cpp。

### 3.2 基座三件套（SQLiteHelperCore.cpp）

- `open_database`（:17-25）：统一失败即返回错误 JSON 的打开；
- `execute_query`（:27-67 无参版；:69-99 参数化版）：执行 SELECT 并把每行按**列名→值**动态转成 JSON 对象（BLOB 显示为占位符）。参数化版把用户输入一律按 TEXT 绑定，是防注入的主通道；
- schema 容错：`table_exists`/`column_exists` 让查询在旧版本产出库（缺新表/新列）上优雅降级而不是 500。

### 3.3 防御工具：HTTP 参数不能直接进 SQL

四个公开的加固函数（SQLiteHelper.h:338-356）：

- `clamp_limit` / `clamp_offset`：把 limit 钳到 [默认 1000, 上限 100000]、offset 钳非负——防"limit=999999999"式 DoS；
- `is_readonly_select(sql)`：只有"单条只读 SELECT/CTE、无分号无注释无 DDL/DML/ATTACH/PRAGMA"才放行——导出端点的自定义 `query` 参数靠它防二次注入；
- `is_safe_filter_clause(clause)`：对 WHERE 片段做同类 token 黑名单校验。

### 3.4 时间线簇：与 EventClusterAnalyzer 同一套语义

`get_comprehensive_timeline` 的 `cluster_events=true` 时按"同 bucket_seconds（默认 60）窗口 + 同类型 + 同父目录"聚合（SQLiteHelper.h:22-32 文档注释），与 EventClusterAnalyzer 的簇定义（EventClusterAnalyzer.cpp:443-451 的 GROUP BY）对齐——展示分组与分析单元一致，簇抽屉里的 LLM 结果才能对得上号。`get_timeline_details` 要求传入与聚簇时相同的 bucket_seconds（h:36-38）。

## 4. 工作流程走读

以"时间线页请求某任务的簇列表"为例：

1. 路由层拿到 task_id 与 db=events，经 RouteHelpers 解析出 `_events.db` 绝对路径；
2. handler 解析 HTTP 参数（limit 经 clamp_limit 钳制）后调 `SQLiteHelper::get_comprehensive_timeline(raw_db, events_db, ..., cluster_events=true, bucket_seconds=60)`；
3. TimelineQueries 里 open_database → execute_query（用户时间串经 parse_timestamp 转换后参数绑定）→ 逐行组 JSON；
4. 缺表/缺列时经 table_exists 分支返回空集或降级字段；
5. handler 包一层 CORS 头后返回。

导出路径（EventExportQueries）多一步：校验 `query` 参数通过 `is_readonly_select` 后才允许执行，结果写输出文件并回 JSON 状态。

## 5. 与其他模块的协作

| 协作方 | 关系 |
|---|---|
| 查询路由（ForensicsRoutes 族） | 主要消费者，一一对应查询域 |
| RouteHelpers | 前置的 db 路径解析 |
| 流水线产出库 | 数据来源（结构由各分析器的 SQL 头文件定义） |
| EventClusterAnalyzer | 共享簇定义（60 秒窗） |
| Swagger 注册 | 无——本模块不感知 HTTP，只产出 JSON 值 |

## 6. 注意事项与已知问题

- **每次查询重开连接**：每个静态方法自开自关 sqlite3 句柄；单次请求多次查询时有开销，但避免了跨线程共享连接的坑——当前 QPS 下合理。
- **错误返回在 JSON 值里而非状态码**：open 失败时 error 塞进结果 JSON（Core.cpp:19-21），由路由决定怎么呈递；新 handler 记得检查。
- **Queries/README.md 的 CMake 说法过时**：见 §3.1；新查询文件务必加入 SQLiteHelper.cpp 的 include 列表而不是 CMake。
- **簇 bucket 必须两侧一致**：前端改 bucket_seconds 传参后，簇分析（60 秒硬编码）不会跟着变，会出现"展示有簇、分析对不上"的错位。

## 7. 如何验证与扩展

- **验证**：对任一完成任务 `sqlite3 data/tasks/<id>/*_events.db ".tables"` 确认表存在，再 curl 对应 /api/forensics/timeline/... 端点比对行数；构造 `?limit=-5` 与 `?limit=99999999` 观察钳制；对导出端点传 `query=DROP TABLE events` 应被拒。
- **扩展新查询**：在对应域文件加静态方法（新域则新建文件并加入 SQLiteHelper.cpp:10-15 的 include）；规则——用户输入一律走参数化 execute_query，limit/offset 必经 clamp，新表访问前先 table_exists 降级。

**最后更新**: 2026-08-23（解释式重写）
