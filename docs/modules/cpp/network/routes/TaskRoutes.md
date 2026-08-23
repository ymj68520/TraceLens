# TaskRoutes（src/network/HTTPServer/routes/TaskRoutes.cpp 及 TaskCRUDRoutes/TaskBatchRoutes/TaskMonitoringRoutes）

> **职责**：任务全生命周期的 REST 门面——创建/查询/删除/批量/监控五组端点，全部落在 TaskManager 单例上；`/tasks` 与 `/api/tasks` 双前缀并存，并为 16 个路径注册了 OPTIONS 预检。
> **端点全量清单**：见 [CPP_REST_API.md](../../../../api_reference/CPP_REST_API.md) 与 [RouteReference.md](./RouteReference.md)。

## 1. 这组路由承担什么

前端"任务页"的一切交互都从这里走：提交镜像开始分析、轮询进度与阶段、查看结果摘要、取消/删除、批量提交一批镜像。此外系统健康页（运行中任务数）与看板也间接消费这里的统计数据。这组路由是**唯一的任务写入口**——任务的创建、取消、删除语义都在 handler 里定型。

## 2. 典型调用方

- **/tasks 任务页（Tasks.jsx）**：创建表单（POST /api/tasks）、任务列表轮询（GET /api/tasks?status=...）、进度条（GET /api/tasks/{id}/progress）、删除按钮（DELETE /api/tasks/{id}）、批量操作（batch-create/batch-status/batch-cancel）。
- **Dashboard/健康检查**：GET /api/tasks/statistics。
- **脚本/CI**：常走 `/tasks` 短前缀（与 `/api/tasks` 完全等价，同一 handler）。

## 3. 端点分组与语义

### 3.1 组合结构

`TaskRoutes` 是纯聚合器：构造 TaskCRUDRoutes + TaskBatchRoutes + TaskMonitoringRoutes 三个子聚合器（TaskRoutes.cpp:9-18），自己只额外注册 **16 个 OPTIONS 预检路由**（TaskRoutes.cpp:20-134）——因为部分浏览器预检不命中通用 CORS 逻辑，这里逐路径兜底返回 204。

### 3.2 创建任务（POST /tasks、POST /api/tasks）

核心在 `handle_create_task`（TaskCRUDRoutes.cpp:127-262）。请求体语义（常用字段）：

- `image_path`（必填）：镜像/数据源路径；
- `priority`：**小写** low/normal/high/critical（TaskHelpers::priority_from_string，TaskHelpers.cpp:99-105）；
- `scenarios`：字符串数组 android/windows/linux/server_cloud（旧的 `android_analyze` 布尔仍兼容，:166-169）；
- `llm_analyze` + `llm_mode`（full|smart，默认 smart）、`case_description`；
- `filter_profile`（空则 TaskManager 默认 general_forensics）、`xfs_mode`（native|pure|auto）、`db_output_dir`；
- 解密：`enable_decryption`/`key_file_dir`（兼容旧拼写 key_dir，:192-194）/`decrypt_password`；
- Android 逻辑源：`android_source`（tsk|dir|zip|miui-backup）+ `backup_password`；
- `file_carving`（同时接受顶层与 `options.file_carving` 两种拼写，:203-209）；
- `metadata`（string→string 映射）、`dependencies`（task_id+required）。

流程是一次**原子创建**（全部参数一次进 create_task，TaskCRUDRoutes.cpp:211-230）→ 依赖满足则立刻 start_analysis（:233-235）→ 201 返回任务摘要。依赖未满足的任务停在 PENDING 等待。

### 3.3 查询与监控

- 列表 GET /tasks（status/priority 过滤 + limit/offset 分页，:394-461）；
- 详情 **GET 与 PUT /api/tasks/{id} 是同一个 handler**（TaskCRUDRoutes.cpp:85-87）——PUT 实为 GET 别名，不做任何更新；
- 进度 GET /api/tasks/{id}/progress（TaskMonitoringRoutes.cpp:46-80，返回阶段/阶段百分比/总百分比）；
- 审计 GET /api/tasks/{id}/audit-log（:98-139）；统计 GET /api/tasks/statistics（:82-96）；
- **PUT /api/tasks/{id}/priority 是 no-op**：解析新优先级后直接返回 success，注释直言 "This would need to be implemented in TaskManager / For now, return success"（TaskMonitoringRoutes.cpp:148-149）——前端显示"已更新"但实际什么都没变，排查优先级问题时别被它骗。

### 3.4 删除与清理

- DELETE /api/tasks/{id} 走 `handle_cancel_task`→`delete_task`（TaskCRUDRoutes.cpp:90-92、463-494）：内存移除 + tasks.json 落盘 + Python 侧清 Graphiti + 清 LLM 抽取临时目录 + 删任务目录（运行中的任务由工作线程退出时兜底删）；
- POST /api/tasks/cleanup 按小时数清理终态旧任务（:496-525）。

### 3.5 结果与批量

- GET /tasks/{id}/results（:294-392）：未完成返回 202；完成后带**缓存**返回，但缓存会做"LLM 证据再校验"——若 `_files.db` 在缓存生成后新写入了 file_descriptions（Python 案例分析或手动标注都可能写），缓存作废重建（:319-350）；`llm_results` 的判定**探测数据库而非看 llm_analyze 标志**（:360-375 注释解释了原因）。
- 批量三件套 batch-create/batch-status/batch-cancel（TaskBatchRoutes.cpp:13-48）：create 是循环调 create_task 并逐个尝试启动（:50-79）。

## 4. 数据从哪来

- **任务列表/详情/进度/统计**：TaskManager 内存态（data/tasks.json 的运行时镜像）；
- **results 摘要与 LLM 证据**：`SQLiteHelper::get_file_summary` 与 `get_llm_results`（FileAnalysisQueries）直接查任务的 `_files.db`；
- **databases 端点**：AnalysisTask 上的 output_*_db 字段。
- 产出库路径解析统一走 `RouteHelpers::get_database_path`。

## 5. 常见错误与边界

- **状态值大小写**：API 返回小写（pending/running/completed/failed/cancelled，TaskHelpers.cpp:117-126）；`?status=RUNNING` 过滤会得到空列表。tasks.json 里则是大写，两套别混。
- **路径碰撞守卫**：GET /api/tasks/{id} 拦截 `list/statistics/cleanup/batch-*` 等保留字（TaskCRUDRoutes.cpp:269-276），否则它们会被 `<string>` 通配吃掉。
- **PUT 的两种"假"**：PUT /{id} 是只读别名、PUT /{id}/priority 是 no-op——客户端不要依赖 PUT 语义。
- **创建请求缺 image_path**：json 解析直接抛异常 → 400 "Invalid request"（:257-260），错误信息较粗糙。
- **批量创建无部分失败语义**：一批路径中某个路径非法不影响其他，返回的 task_ids 数组可能少于输入。

## 6. 如何验证与扩展

- curl 冒烟：`POST /api/tasks`（最小 body `{"image_path":"..."}`）→ 轮询 progress → completed 后 GET results → DELETE 后 GET 应 404。
- 扩展：新任务字段在 handle_create_task 解析 → 传入 create_task（TaskManager.cpp:73-89 的参数表已很长，考虑改用 struct）；新只读监控端点放 TaskMonitoringRoutes 并在 TaskRoutes.cpp:20-134 补对应 OPTIONS 预检。

**最后更新**: 2026-08-23（解释式重写）
