# ForensicsRoutes（src/network/HTTPServer/routes/ForensicsRoutes.cpp 及 11 个子路由文件）

> **职责**：任务**结果侧**的只读查询大门——时间线、文件分析、统计、Android/MIUI、内存、DLL、系统事件、导出、文件提取、场景查询共 11 组子路由，全部围绕"拿 task_id → 解析产出库 → SQLiteHelper 查询"这一条链。
> **端点全量清单**：见 [CPP_REST_API.md](../../../../api_reference/CPP_REST_API.md) 与 [RouteReference.md](./RouteReference.md)。

## 1. 这组路由承担什么

任务完成后，调查员的全部"看结果"动作都在这里：时间线页翻事件与簇、文件页找大文件/可疑文件/重复文件、统计页看分布、Android 页看通信与应用、内存页看进程、导出成 CSV/JSON。写操作只有两类：**触发文件提取作业**与**触发事件簇重分析**——其余全是 SELECT。

它与 TaskRoutes 的分界线：TaskRoutes 管"任务的生命周期"，ForensicsRoutes 管"任务产出的内容"。

## 2. 典型调用方

| 前端页面 | 主要消费的子路由 |
|---|---|
| /timeline 时间线页（含簇抽屉） | timeline/* 全套 + timeline/clusters/*（EventClusterRoutes） |
| /files 文件页 | files/largest、files/recent、files/suspicious、files/duplicates、files/extensions-analysis |
| /statistics 统计页 | statistics/overview、file-distribution、activity-patterns、deleted-files-analysis |
| /android 页 | android/communication-summary、app-usage、device-info、media-analysis、miui-* 全套、llm-summary |
| /memory 页 | memory/summary、processes、network、bash-history、boot-info |
| 导出/报告 | export/events/{csv,json,visualization} |
| 文件提取对话框 | /api/forensics/extract（异步作业） |

## 3. 端点分组与语义

### 3.1 聚合器本身几乎为空

`ForensicsRoutes` 构造函数组合 11 个子路由成员（ForensicsRoutes.cpp:31-45）；自己保留了一套**遗留的提取作业跟踪表**（create/get/update/cleanup_extraction_job，:51-119），注释说明文件提取路由现在自管作业、这些方法"kept for potential backward compatibility"——读代码时可跳过。

### 3.2 时间线组（TimelineRoutes + EventClusterRoutes）

- `timeline/comprehensive`：一网打尽的主查询，支持时间范围/类型过滤、分页，`cluster_events=true` 时按 60 秒窗聚簇（与 EventClusterAnalyzer 同语义）；
- `timeline/details`：展开某簇的明细（time_window+event_type+parent_dir 三元组定位，bucket_seconds 须与聚簇一致）；
- 辅助视角：by-type / by-time-range / by-file / full / distribution / statistics-by-period / file-activity / suspicious-patterns / user-activity；
- **clusters/ 组是写端点**：analyze/batch-analyze/reanalyze 触发 LLM 簇分析（复用 EventClusterAnalyzer），analyzed 读取已分析簇——这是时间线页簇抽屉里"AI 分析"按钮的后端。

### 3.3 文件与统计组

files/* 全部映射 SQLiteHelper::FileAnalysisQueries（largest/recent/suspicious/duplicates/extensions-analysis + llm 结果）；statistics/* 映射 StatisticsQueries。语义上都是"一个维度一个端点"的平铺设计，参数基本是 task_id + limit。

### 3.4 Android/MIUI 组（AndroidForensicsRoutes，14 个端点）

最大的一组：通信摘要/应用使用/设备信息/媒体分析四个通用端点，加上 MIUI 离线备份的 overview/installed-apps/db-inventory，以及 QQNT、微信两族 artifacts/records/overview 端点（敏感字段默认脱敏，revealSensitive 参数控制）。数据全部来自 `android.db`（经 RouteHelpers 的多级回退解析）。

### 3.5 专项组

- **memory/***：读 `_memory.db`（Volatility 产物），路径解析见 RouteHelpers.cpp:72-86 的 `_raw` 后缀剥离逻辑；
- **dlls/***：DLL 异常分析端点组（含独立的 analyze 触发与 health）；
- **system/events|summary**：系统事件视图；
- **export/***：事件导出三格式；自定义 `query` 参数必须通过 `SQLiteHelper::is_readonly_select` 校验；
- **/api/forensics/extract**：异步文件提取作业（提交→轮询 extract/status）。

## 4. 数据从哪张表来

统一模式：`task_id` + `db` 类型 → `RouteHelpers::get_database_path`（RouteHelpers.cpp:35-90）→ SQLiteHelper 对应域模块：

| 端点组 | 产出库 | SQLiteHelper 模块 |
|---|---|---|
| timeline/*、system/events | `_events.db`（events 表） | TimelineQueries / StatisticsQueries |
| files/*、statistics/file-* | `_files.db`（files、file_descriptions 表） | FileAnalysisQueries / StatisticsQueries |
| statistics/overview、deleted-files | `_raw.db` + `_files.db` + `_events.db` | StatisticsQueries |
| android/*、miui-* | `android.db` | AndroidQueries |
| memory/* | `_memory.db` | MemoryForensicsRoutes 内联查询 |
| clusters/*（分析写入） | `_events.db` 簇 LLM 列 | EventClusterAnalyzer（非 SQLiteHelper） |

## 5. 常见错误与边界

- **404 语义混杂**：task_id 不存在（RouteHelpers 抛 runtime_error）与"库文件还没生成"都可能以 404/错误 JSON 返回——任务未完成就调结果端点是常见时序问题，前端应以任务状态为先导。
- **limit 未钳制的端点存在**：新代码都应走 clamp_limit；给老端点传超大 limit 可能拖垮大库。
- **bucket_seconds 错位**：details 端点的 bucket 必须与聚簇时一致（默认 60），否则簇明细为空。
- **导出自定义 query 被拒**：含分号/注释/非 SELECT 关键词一律 400——这是特性不是 bug（防注入）。
- **extract 作业是内存态**：服务重启后未完成作业的状态查询 404。

## 6. 如何验证与扩展

- 冒烟：完成任务后依次 curl `timeline/comprehensive?task_id=...&cluster_events=true`、`files/largest?task_id=...&limit=5`、`android/communication-summary?task_id=...`，与 `sqlite3 data/tasks/<id>/*.db` 的行数互相印证。
- 扩展新查询端点：选好所属域 → 在 SQLiteHelper 对应 Queries 文件加方法 → 子路由文件注册端点（+Swagger RegisterEndpoint）→ 若是新域则建子路由类并在 ForensicsRoutes.cpp:31-45 挂载。

**最后更新**: 2026-08-23（解释式重写）
