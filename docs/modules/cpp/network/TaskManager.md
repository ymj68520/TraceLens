# TaskManager（src/network/HTTPServer/TaskManager.{h,cpp} + TaskManagerAnalysis.cpp）

> **一句话**：任务世界的"操作系统"——单例管理所有取证分析任务的生命周期（创建/调度/取消/删除/恢复），并把每条任务放进受控线程池执行八阶段流水线，全程进度上报、持久化与审计。

## 1. 为什么有这个模块

磁盘镜像分析是典型的长耗时、资源密集、可中断作业。若没有集中的任务管理，会遇到：并发分析互相踩踏、服务器重启后任务状态丢失、卡死的任务永远占着坑、取消请求无法传到流水线深处。TaskManager 用四件事解决这些问题：

1. **受控并发**：固定大小线程池（而非无界 detach 线程）执行任务，防止资源失控；
2. **崩溃恢复**：任务状态持久化到 `data/tasks.json`，重启时把中断任务标记为 FAILED 而不是假装还在跑；
3. **看门狗**：后台巡检停滞任务，超时判 FAILED；
4. **协作式取消**：`cancellation_requested` 原子标志 + 流水线各阶段检查点，做到"尽快停但不强杀"。

## 2. 在系统中的位置

```
TaskRoutes (REST) ──创建/查询/取消──▶ TaskManager (单例)
                                        │ enqueue
                                        ▼
                                   ThreadPool (THREAD_POOL_SIZE, 默认 4)
                                        │ start_analysis (TaskManagerAnalysis.cpp)
        ┌───────────┬───────────┬──────┴──────┬────────────┬──────────┐
   ImageAnalyzer  EventExtractor FileClassifier LLM 系列服务  平台分析器  FileCarver
                                        │ 任务完成（fire-and-forget）
                                        ▼
                                  LLMPythonProxy → Python Graphiti 摄取
```

- **上游**：任务类路由（TaskCRUDRoutes/TaskBatchRoutes/TaskMonitoringRoutes）是它唯一的写入口；查询类路由经 `RouteHelpers::get_database_path` 读取任务记录的产出库路径。
- **下游**：见上图，几乎驱动所有分析器；任务状态同时喂给 `/api/system/health` 的统计。
- **持久化**：`data/tasks.json`（PathManager::getTasksJsonPath，PathManager.cpp:84-85），每任务目录 `data/tasks/<task_id>/`。

## 3. 核心概念与设计

### 3.1 单例 + 一把大锁

`TaskManager::instance()`（TaskManager.h:37-40）是进程内唯一实例。所有任务字典 `tasks_` 的读写都经同一把 `mtx_` 串行化——简单粗暴但对 HTTP 层的读写频率完全够用；代价是保存 JSON 也在锁内（作者注释承认这是权衡，TaskManager.cpp:144-146）。

### 3.2 任务状态机

`TaskStatus`（HTTPServerDataTypes.h:20）：`PENDING → RUNNING → COMPLETED | FAILED | CANCELLED`。要点：

- 取消只允许从 PENDING/RUNNING 发起（TaskManager.cpp:297-299）；取消是**置位 `cancellation_requested` 原子标志 + 状态直接改 CANCELLED**（TaskManager.cpp:302-303），正在跑的工作线程在下一个检查点自行退出。
- 进入终态时自动清除 `decrypt_password`/`backup_password`（TaskManager.cpp:164-168），密码只在运行期存在，绝不落盘（TaskSerialization.cpp:95-96、148、154 同样保证）。
- `is_task_cancelled` 对"任务不存在"返回 true（TaskManager.cpp:526-532）——这让被删除任务的执行线程自然退出，配合 `start_analysis` 里的 RAII 清理（TaskManagerAnalysis.cpp:34-53）删除磁盘目录。

### 3.3 八阶段进度模型

`TaskPhase` 有 8 个阶段，`calculate_overall_percentage`（TaskManager.cpp:545-566）用固定权重把"当前阶段内百分比"折算成总进度：

```
INITIALIZING 5 | IMAGE_ANALYSIS 25 | EVENT_EXTRACTION 10 | FILE_CLASSIFICATION 15
LLM_ANALYSIS 20 | PLATFORM_ANALYSIS 20 | FILE_CARVING 3 | FINALIZING 2
```

权重反映真实耗时分布：镜像解析和两大 LLM/平台阶段占了 90%。进度更新同时维护基于线性外推的 ETA（TaskManager.cpp:190-194）。

### 3.4 线程池与优先级队列

构造函数从 ConfigManager 读 `THREAD_POOL_SIZE`（默认 4，ConfigManager.cpp:138；≤0 修正为 2，>16 告警，TaskManager.cpp:23-29）建 `ThreadPool`。这个池**只有 TaskManager 在用**。`task_queue_` 是带优先级的队列（TaskManager.h:302-312），但目前只在 `create_task` 里 push（TaskManager.cpp:139）——真正的启动由路由层"创建即尝试启动"（TaskCRUDRoutes.cpp:233-235），队列更像是为未来调度器预留的结构。

### 3.5 看门狗

构造时起独立线程跑 `TaskWatchdog`（TaskManager.cpp:37、537-542），共享 tasks_ 与锁。详见 TaskInfrastructure.md。

## 4. 工作流程走读（start_analysis）

执行体在 **TaskManagerAnalysis.cpp**（不是 TaskManager.cpp；也**不是**未引用的死文件 `TaskAnalysisRunner.h`）。`start_analysis` 在 TaskManagerAnalysis.cpp:26 定义，把整个流水线 lambda 丢进线程池：

1. **入池与 RAII**：`analysis_pool_->enqueue`（TaskManagerAnalysis.cpp:32）；`TaskCleanup` 析构时若发现任务已被删除则清空任务目录（:34-53）——这是"运行中删除任务"的善后路径。
2. **前置检查**：重取任务、取消预检、防重跑（RUNNING/COMPLETED 直接返回）、依赖检查失败则回 PENDING（:57-77）。
3. **产出库路径**：`db_output_dir` 是遗留覆盖项；默认走 PathManager 每任务目录 `<base>_raw.db / _events.db / _files.db`（:96-110）。
4. **逻辑 Android 短路**：`android_source` 为 dir/zip/miui-backup 时跳过整个 TSK 流水线，直接跑 AndroidAnalyzer，产出 android.db 并作为 output_files_db（:128-199、600-668）。
5. **TSK 主流水线**：ImageAnalyzer→_raw.db（:201-225，解密口令用完即清 :212-213）→ 场景自动探测（:232-259）→ 文件过滤生成 `_filtered.db`（:261-298）→ EventExtractor→_events.db（:300-309）→ FileClassifier→_files.db（:311-332）。
6. **LLM 阶段**（`llm_analyze` 时）：文件级描述 LLMAnalysisService（full/smart，:334-391）+ 事件簇 EventClusterAnalyzer（:393-434）。
7. **平台分析**：按 scenarios 依次跑 Android/Windows/Linux/ServerCloud 分析器，各写 `android.db/windows.db/linux.db/oss.db`（:437-529）；单场景失败只记 WARNING 不终止任务（:519-522）。
8. **可选雕复**：`file_carving` 时对未分配空间做签名雕复到 `carved_files/`（:531-556）。
9. **Graphiti 摄取（fire-and-forget）**：调 `LLMPythonProxy::async_ingest`，job id 存进任务（:558-583）；失败不影响任务成功。
10. **收尾**：`set_result_db` + COMPLETED（:586-591）；任何异常统一转 FAILED + 审计（:593-596）。

## 5. 与其他模块的协作

- **TaskRoutes 族**：REST 门面（见 routes/TaskRoutes.md）。
- **TaskPersistence / TaskSerialization / TaskWatchdog**：内部支撑组件（见 TaskInfrastructure.md）。
- **LLMAnalysisService / EventClusterAnalyzer / Linux·Windows·AndroidLLMAnalysisService**：LLM_ANALYSIS 与 PLATFORM_ANALYSIS 阶段的执行者（各见独立文档）。
- **LLMPythonProxy**：任务完成后的知识图谱摄取；`delete_task` 时反向调用 `deleteGraphitiData` 清理 Neo4j（TaskManager.cpp:340-341）。
- **PathManager**：所有任务目录/库路径的唯一来源。
- **AuditLog**：`add_audit_log` 贯穿所有状态变化（TaskManager.cpp:515-519）。

## 6. 注意事项与已知问题

- **取消是协作式的**：置位标志后工作线程要走到下一个检查点才停；LLM 单次调用若很慢，取消会延迟。看门狗的 30 分钟阈值就是为这种"合法慢"留的余量。
- **统计里的阶段缺失**：`get_task_statistics` 的 `running_phases` 只列了 6 个阶段，漏掉 LLM_ANALYSIS 与 FINALIZING（TaskManager.cpp:433-441）——统计页看不到这两阶段中的任务分布。
- **task_queue_ 未被消费**：优先级队列只有 push 没有 pop 消费者，优先级目前不影响执行顺序（创建即入池排队）。
- **锁内做文件 I/O**：save_tasks_internal 在 mtx_ 内写 JSON；任务多时 HTTP 读操作可能被拖慢（作者已知，见 TaskManager.cpp:144-146 注释）。
- **`PUT /api/tasks/{id}/priority` 是 no-op**：路由层返回成功但不改优先级（TaskMonitoringRoutes.cpp:148-149 注释"only return success"），根因是 TaskManager 没有实现改优先级的方法。
- **大小写两套状态值**：REST API 用小写（TaskHelpers.cpp:117-126），tasks.json 里是大写（TaskSerialization.cpp:9-15）。跨层排查时注意。

## 7. 如何验证与扩展

- **验证**：建任务后 `cat data/tasks.json` 看持久化（状态为大写、无密码字段）；杀进程重启，原 RUNNING 任务应变为 FAILED"Interrupted by server restart"；删除运行中任务，确认 `data/tasks/<id>/` 目录稍后被清（TaskCleanup 兜底）。
- **扩展新分析阶段**：在 TaskManagerAnalysis.cpp 流水线里插入阶段调用 + `update_progress(TaskPhase::X, ...)`，并在 `calculate_overall_percentage` 权重表（TaskManager.cpp:546-555）里配权重；新阶段若要持久化进度，需同时在 TaskSerialization.cpp:24-32 补枚举映射（注意 FILE_CARVING 目前就漏在映射外，见 TaskInfrastructure.md）。

**最后更新**: 2026-08-23（解释式重写）
