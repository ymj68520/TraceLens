# MemoryForensicsRoutes（src/network/HTTPServer/routes/MemoryForensicsRoutes.{h,cpp}）

> **一句话**：内存取证结果的五个只读查询端点——对任务产物 `_memory.db`（processes/network_connections/bash_history/sockets/boot_info 五张表）做分页上限 1000 的 SELECT 直读，`search`/`keyword` 过滤一律参数绑定防注入，库缺失固定 404 绝不凭空建库。

## 1. 为什么有这个模块

内存镜像的分析产物（ volatility 类工具的结构化输出）被规整进任务目录下的 `<task>_memory.db`。前端 `/memory` 页（`web/src/pages/Memory.jsx`，经 `web/src/services/memoryService.js:7-23` 消费）需要五个视图：概览计数、进程列表（可搜索）、网络连接、bash 历史（可按关键词过滤）、启动信息。这组路由就是它们的最小读面：构造函数里五条 `CROW_ROUTE` 一次注册（MemoryForensicsRoutes.cpp:11-21），每个 handler 都是"解析库路径 → 只读开库 → 固定 SQL → JSON 行数组"的同构三步。

## 2. 在系统中的位置

- **路由注册**：`MemoryForensicsRoutes(HttpApp& app)` 构造即注册（MemoryForensicsRoutes.h:10-11；HttpApp 是带 FieldAuthMiddleware 的 app，见 [FieldApp.md](FieldApp.md)）。
- **它调用谁**：`RouteHelpers::get_database_path(task_id, "memory")`（:37 注释："same helper AndroidForensicsRoutes uses with 'android'"——任务产物的统一三级回退解析）；SQLiteHelper/sqlite3 C API（只读打开）。
- **它被谁依赖**：前端 Memory 页唯一消费；无服务间调用。

## 3. 端点清单（5 个，全部 GET）

| 端点 | handler | SQL 形态 | 过滤参数 |
|---|---|---|---|
| `/api/forensics/memory/summary` | `handle_memory_summary`（:85-113） | 四表 `SELECT COUNT(*)`（processes/network_connections/bash_history/sockets） | — |
| `/api/forensics/memory/processes` | `handle_memory_processes`（:115-130） | `SELECT pid, ppid, comm, uid, creation_time FROM processes ORDER BY pid LIMIT 1000` | `search` → `WHERE comm LIKE ?`（参数绑定） |
| `/api/forensics/memory/network` | `handle_memory_network`（:132-139） | `SELECT pid, comm, proto, local_addr, local_port, remote_addr, remote_port, state FROM network_connections ORDER BY pid LIMIT 1000` | — |
| `/api/forensics/memory/bash-history` | `handle_memory_bash_history`（:141-156） | `SELECT pid, comm, command, history_index FROM bash_history ORDER BY history_index LIMIT 1000` | `keyword` → `WHERE command LIKE ?`（参数绑定） |
| `/api/forensics/memory/boot-info` | `handle_memory_boot_info`（:158-163） | `SELECT key, value FROM boot_info` | — |

## 4. 核心机制走读

### 4.1 库解析与"404 而非建库"（MemoryForensicsRoutes.cpp:36-56）

`resolveMemoryDb`（:34-38）经 `RouteHelpers::get_database_path(task_id, "memory")` 定位任务产物库，任务不存在/解析失败抛异常 → `taskNotFound()` 404（:26-33，固定 `{"error":"task not found"}`）。开库用 `sqlite3_open_v2(..., SQLITE_OPEN_READONLY, ...)`，:51-52 的注释写明红线："READONLY (no CREATE): a missing _memory.db must 404, not be fabricated as an empty file inside the forensic evidence directory."——普通的 `sqlite3_open` 会在缺库时**创建空文件**，在证据目录里这是污染。两处 handler（summary :92-95 与 jsonRows :53-55）都显式用 READONLY。

### 4.2 参数化查询的两个重载（:41-83）

`jsonRows(dbPath, sql, params)` 是参数绑定版（:41-49，`sqlite3_bind_text` 逐个左绑 `?`），注释明说用途："Used for handlers that accept user-supplied filters (search/keyword) to avoid SQL injection via string concatenation"；无参版（:81-83）直接转发。LIKE 模式 `%search%` 在调用侧拼好但仍作为**绑定参数**传入（:121-127、:146-152）——模式字符串里的 `%`/`_` 来自用户也不会破坏 SQL 结构。

### 4.3 行到 JSON 的直映射（:51-79）

`sqlite3_step` 循环里按列名构造 `json::object`，NULL 列统一落空字符串（`t ? reinterpret_cast<const char*>(t) : ""`，:74）——响应是同形 JSON 数组，前端无需判空类型。

## 5. 数据流（读什么、写什么）

**读**：仅任务产物 `_memory.db`，只读连接用后即关（每个 handler 独立开/关，无连接池）。**写**：无——这组路由没有任何写路径，`summary` 的 COUNT 也不落缓存。

## 6. 边界与已知状态

- **错误码只有三档**：404（任务不存在 / 库不存在）、500（`query failed`，SQL prepare 失败——固定短句不泄异常）、200。没有 400：过滤参数是可选自由文本，任何值都合法。
- **LIMIT 1000 是硬上限**：四个行端点都没有分页参数（前端 Memory 页是概览页不是全量浏览器）——超千行的完整分析走导出/专门工具，不挤这个端点。
- **bash_history 的 keyword 前后端二选一**：后端支持 `keyword` 参数，前端也可拉全量后本地过滤（Memory 页现状，见 web Pages.md）——语义一致但注意 LIKE 是子串匹配、前端是任意包含。
- **无认证豁免特判**：五个端点都走全局中间件；现场模式下 `/api/forensics/*` 恰在 python-service 白名单的 GET 范围内（FieldApp.cpp:83）。

## 7. 如何验证

- 冒烟：对一个完成内存分析的任务 `curl ":8080/api/forensics/memory/summary?task_id=<id>"` 应返回四计数；`processes?search=smbd` 核对 LIKE 命中且 SQL 日志无拼接痕迹。
- 404 语义：对无内存产物的任务请求任意端点 → `{"error":"memory db not found"}`，且任务目录**不得**出现新建的空 `_memory.db`。
- 前端契约：`web/src/services/memoryService.js`、`/memory` 页五卡片。

相关阅读：[ForensicsRoutes.md](routes/ForensicsRoutes.md)（同族取证读面的注册惯例）、[RouteReference.md](routes/RouteReference.md)（全路由表）、[FieldApp.md](FieldApp.md)（现场模式下的访问控制）、web 侧 Pages.md 的 /memory 走读。

## 8. 二轮深化 A：READONLY 开库为什么值得写成注释红线

SQLite 的默认 `sqlite3_open` 语义是"不存在就创建"——对应用库是便利，对取证产物是事故：一个打错 task_id 的请求会在 `data/tasks/<别的目录>/` 或证据目录里留下一个合法的空 `_memory.db`，之后所有"库存在"判断都会被它污染（summary 变成全 0 的"成功"响应，404 语义永久丢失）。`sqlite3_open_v2(..., SQLITE_OPEN_READONLY)` 让"库不存在"成为明确的错误返回值，路由把它翻译成 404——缺数据是**可发现的**。这与 Python 侧 timeline_sources 的 `SourceUnavailable`、AndroidReport 路由的 `_verified_import_root` 同属一条纪律：**读路径绝不创建存储**（read paths never fabricate）。三处实现、同一句话写在各自的注释里，是本仓库读面一致性的直接证据。

**最后更新**: 2026-11-10（新建：内存取证查询路由文档）
