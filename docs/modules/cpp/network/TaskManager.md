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

## 3. 核心数据结构

### 3.1 枚举：状态、优先级、阶段（HTTPServerDataTypes.h:20-31）

```cpp
// HTTPServerDataTypes.h:20-31
enum class TaskStatus { PENDING, RUNNING, COMPLETED, FAILED, CANCELLED };
enum class TaskPriority { LOW = 0, NORMAL = 1, HIGH = 2, CRITICAL = 3 };
enum class TaskPhase {
    INITIALIZING,
    IMAGE_ANALYSIS,
    EVENT_EXTRACTION,
    FILE_CLASSIFICATION,
    LLM_ANALYSIS,        // LLM file description generation
    PLATFORM_ANALYSIS,   // Platform-specific analysis (Android/Windows/Linux/Server)
    FILE_CARVING,        // Signature-based carving of unallocated space
    FINALIZING
};
```

TaskStatus 是五态机：PENDING→RUNNING→{COMPLETED|FAILED|CANCELLED}，没有回边（FAILED 任务不能重启，只能删了重建）。TaskPriority 带显式数值 0-3，`priority_queue` 的比较器依赖它（TaskManager.h:306-308）。TaskPhase 是"进度坐标系"——注意 FILE_CLASSIFICATION 阶段名下实际干的事包括场景探测与文件过滤（TaskManagerAnalysis.cpp:232-298），阶段名与流水线步骤并非一一对应。

### 3.2 TaskProgress：进度与心跳（HTTPServerDataTypes.h:79-86）

```cpp
// HTTPServerDataTypes.h:79-86
struct TaskProgress {
    TaskPhase current_phase;
    int phase_percentage;
    int overall_percentage;
    std::string phase_description;
    std::chrono::steady_clock::time_point phase_start_time;
    std::chrono::steady_clock::time_point estimated_completion;
};
```

| 字段 | 谁写 → 谁读 | 语义 |
|---|---|---|
| current_phase / phase_percentage | 流水线各步 update_progress → progress 端点、统计 | 当前阶段与阶段内 0-100 |
| overall_percentage | calculate_overall_percentage 折算后写入 → 前端进度条 | 全局 0-100 |
| phase_description | 各步骤描述 → progress 端点 | 如 "Analyzing image structure..." |
| phase_start_time | 每次 update_progress 刷新为 now（TaskManager.cpp:187）→ **TaskWatchdog 心跳依据** | 距今超 30 分钟无更新判挂死 |
| estimated_completion | update_progress 线性外推写入（TaskManager.cpp:190-194）→ 预留 | ETA = 执行时长 × 100 / 当前总进度 |

phase_start_time 用 steady_clock 是刻意的：挂钟在 NTP 校时会跳变，心跳判定若用 system_clock 可能出现"负时长秒回"或"瞬间超时"的假象。

### 3.3 AnalysisTask：任务实体的逐字段解释（HTTPServerDataTypes.h:99-165）

```cpp
// HTTPServerDataTypes.h:99-165（节选）
struct AnalysisTask {
    struct SceneConfig {
        bool enabled = false;
        // ...
    };

    std::string id;
    std::string image_path;
    TaskStatus status;
    std::string message;
    std::string output_files_db;
    std::string output_raw_db;
    std::string output_events_db;
    TaskPriority priority;
    TaskProgress progress;
    // ...
    std::atomic<bool> cancellation_requested{false};
    std::string error_details;
    std::map<std::string, std::string> metadata;
    // ...
```

| 字段（行号） | 谁写 → 谁读 | 语义与注意点 |
|---|---|---|
| `id` / `image_path`（:108-109） | create_task 生成 UUID；请求体 → 全系统 / ImageAnalyzer | 主键（tasks_ 键与任务目录名）；镜像路径 exists() 不通过即 FAILED（TaskManagerAnalysis.cpp:83-86） |
| `status` / `message`（:110-111） | update_status/cancel/watchdog → 所有路由 | 五态机与人类可读状态；锁内改、改后落盘 |
| `output_raw/events/files_db`（:112-114） | 流水线前置阶段（TaskManagerAnalysis.cpp:113-119、589）→ RouteHelpers::get_database_path | 三大产出库路径，"任务→数据"的纽带；查询路由全靠它们 |
| `priority`（:115） | 创建时定死 → 统计、task_queue_ | **无 setter**——PUT priority no-op 的根因 |
| `progress`（:116） | update_progress → progress 端点、watchdog | 见 §3.2 |
| `created/started/completed_time`（:117-119） | create_task/update_status → 列表页耗时 | system_clock；创建时三者同值，首次转 RUNNING 才分开（TaskManager.cpp:161-163） |
| `execution_start_time`（:120） | 转 RUNNING 时 → ETA 外推 | steady_clock，跨重启重置（TaskSerialization.cpp:169） |
| `dependencies`（:121） | 请求体 → can_start_task | required 依赖需 COMPLETED 才放行（TaskManager.cpp:474-483） |
| `dependents` / `sceneConfigs`（:122、:125） | 预留 → — | 无写入方/流水线不消费；未接线字段（dependents_count 恒 0） |
| `result_cache`（:123） | cache_result → results 端点 | 结果 JSON 缓存；"缓存再校验"见 routes/TaskRoutes.md §3.5 |
| `scenarios`（:124） | 请求体或 SceneDetector 回填 → 平台分析调度 | 多值；空时触发自动探测（TaskManagerAnalysis.cpp:232） |
| `cancellation_requested`（:134） | cancel/delete/watchdog 置位 → is_task_cancelled、分析器回调 | 协作式取消核心；atomic 故拷贝构造须手工处理（:180） |
| `error_details`（:135） | 失败路径、看门狗 → 详情页 | FAILED 具体原因（"Interrupted by server restart" 等） |
| `metadata`（:136） | 请求体、runLogicalAndroidAnalysis → RouteHelpers 回退解析 | android_db/dll_db/memory_db 的覆盖入口 |
| `llm_analyze/llm_mode/case_description`（:139-142） | 请求体 → LLMAnalysisService | llm_analyze 只是开关，**results 端点判定 LLM 证据不依赖它**（TaskCRUDRoutes.cpp:360-375 注释） |
| `output_descriptions_db` / `graphiti_job_id`（:141、:143） | 预留 / Graphiti 触发后（TaskManagerAnalysis.cpp:573） | LLM 描述实际写在 _files.db；graphiti_job_id 是 fire-and-forget 作业 ID |
| `filter_profile` / `file_carving`（:146、:149） | 请求体 → FileFilter / FileCarver | filter_profile 空则默认 general_forensics（TaskManager.cpp:123-125） |
| `enable_decryption/key_file_dir/decrypt_password`（:152-154） | 请求体 → ImageAnalyzer | 密码用完即清（TaskManagerAnalysis.cpp:212-213），进终态再兜底清（TaskManager.cpp:166-167） |
| `android_source` / `backup_password`（:163、:165） | 请求体 → 流水线分叉 / AndroidAnalyzer | "tsk"/"dir"/"zip"/"miui-backup"，后三者短路 TSK；密码运行期专用绝不落盘 |

结构有 40+ 字段，因 `std::atomic` 成员手写了全部拷贝/移动构造（HTTPServerDataTypes.h:168-301）——每次 `get_task` 返回整结构拷贝（含可能很大的 result_cache），字段再扩张前值得先拆分。

## 4. 核心接口清单

| 方法（TaskManager.h） | 一行语义 | 主要调用方 | 失败行为 |
|---|---|---|---|
| `create_task`（:68-84，17 参数） | 锁内建 UUID、初始化全字段、入 map+优先队列、落盘 | TaskCRUDRoutes/batch | 无失败返回值；非法路径到 start_analysis 才暴露 |
| `get_task(id)`（:139） | 锁内拷贝返回；找不到返回空 ID 对象 | 几乎所有任务路由 | 调用方判 `task.id.empty()` 转 404 |
| `get_all_tasks / by_status / by_priority`（:146-160） | 全量/按状态/按优先级拷贝列表 | 列表端点（过滤在路由层） | 无 |
| `update_status / update_progress`（:93、:102） | 改状态（终态清密码）/ 折算进度+刷心跳 | 流水线、取消、看门狗 | 任务不存在时静默 no-op |
| `cancel_task(id, reason)`（:169） | 仅 PENDING/RUNNING；置标志+直接改 CANCELLED | DELETE 路由、batch-cancel | 终态/不存在返回 false |
| `delete_task(id)`（:176） | 移出内存+清 Graphiti+删目录（运行中由线程退出兜底） | DELETE /api/tasks/{id} | 不存在返回 false |
| `can_start_task(id)`（:217） | required 依赖全 COMPLETED 才 true | 创建后决定是否立即启动 | 不存在 false |
| `get_task_statistics()`（:201） | 锁内聚合五态/优先级/阶段分布/平均耗时 | statistics 端点、health | 不抛错 |
| `cleanup_completed_tasks(hours)`（:209） | 删超龄终态任务（仅内存不删磁盘） | cleanup 端点 | 无 |
| `is_task_cancelled(id)`（:278） | **任务不存在也返回 true**（:526-532） | 流水线检查点、取消回调 | — |
| `cache_result / get_cached_result`（:233、:240） | results JSON 存取 | results 端点 | 未命中返回空串 |
| `start_analysis(id)`（:267） | 流水线 lambda 丢进线程池 | TaskCRUDRoutes/batch | 池不存在仅打 CRITICAL（TaskManagerAnalysis.cpp:27-30） |

## 5. 核心概念与设计

### 5.1 单例 + 一把大锁

`TaskManager::instance()`（TaskManager.h:37-40）是进程内唯一实例。所有任务字典 `tasks_` 的读写都经同一把 `mtx_` 串行化——简单粗暴但对 HTTP 层的读写频率完全够用；代价是保存 JSON 也在锁内（作者注释承认这是权衡，TaskManager.cpp:144-146）。大锁纪律的具体形态（以 create_task 为例，TaskManager.cpp:90-148）：**UUID 在锁内生成**（杜绝并发生成撞 ID）→ 初始化 PENDING + 零进度 → `tasks_[id]` 入 map → `task_queue_.push({priority, id})` → `add_audit_log(CREATED)` → **创建即一次全量落盘**（把创建到启动的多次状态变化合并成一次 I/O，即注释所说的 3x 提速）→ 返回 id。审计走锁内（add_audit_log 只查 tasks_ 存在性，AuditLog 自有锁）；锁内不做网络调用——Graphiti 清理在 delete_task 里被刻意放到锁外（TaskManager.cpp:340-341）。

### 5.2 任务状态机

`PENDING → RUNNING → COMPLETED | FAILED | CANCELLED`。要点：

- 取消只允许从 PENDING/RUNNING 发起（TaskManager.cpp:297-299）；取消是**置位 `cancellation_requested` 原子标志 + 状态直接改 CANCELLED**（TaskManager.cpp:302-303），正在跑的工作线程在下一个检查点自行退出。cancel_task 的完整序列（:291-311）：锁内 find → 终态拒绝 → 置标志+改状态+写 message+completed_time → 清双密码 → CANCELLED 审计 → 落盘。**不等待工作线程确认**——前端立刻看到"已取消"，线程此后每个检查点发现标志才真正退出；存在窗口期（线程还在跑最后一段代码），对磁盘只读的分析流水线可接受。
- 进入终态时自动清除 `decrypt_password`/`backup_password`（TaskManager.cpp:164-168），密码只在运行期存在，绝不落盘（TaskSerialization.cpp:95-96、148、154 同样保证）。
- `is_task_cancelled` 对"任务不存在"返回 true（TaskManager.cpp:526-532）——这让被删除任务的执行线程自然退出，配合 `start_analysis` 里的 RAII 清理（TaskManagerAnalysis.cpp:34-53）删除磁盘目录。

### 5.3 八阶段进度模型

`calculate_overall_percentage`（TaskManager.cpp:545-566）用固定权重把"阶段内百分比"折算成总进度：INITIALIZING 5 | IMAGE_ANALYSIS 25 | EVENT_EXTRACTION 10 | FILE_CLASSIFICATION 15 | LLM_ANALYSIS 20 | PLATFORM_ANALYSIS 20 | FILE_CARVING 3 | FINALIZING 2（权重反映真实耗时：镜像解析和两大 LLM/平台阶段占了 90%）。

```cpp
// TaskManager.cpp:545-566
int TaskManager::calculate_overall_percentage(TaskPhase phase, int phase_percentage) {
    std::map<TaskPhase, int> phase_weights = {
        {TaskPhase::INITIALIZING, 5},
        // ...（其余 7 个阶段，权重见上）
    };

    int total_percentage = 0;
    for (const auto& p : phase_weights) {
        if (p.first < phase) {
            total_percentage += p.second;
        } else if (p.first == phase) {
            total_percentage += (p.second * phase_percentage) / 100;
        }
    }
    return std::min(total_percentage, 100);
}
```

实现依赖枚举的**声明顺序即阶段顺序**（`p.first < phase` 是枚举比较），TaskPhase 的枚举值顺序本身就是流水线顺序，乱序插入阶段会算错进度。跳过可选阶段（如未开 LLM）时，被跳段的权重经 `< phase` 直接计入，总进度单调不减但中间有跳变。进度更新同时维护基于线性外推的 ETA（TaskManager.cpp:190-194）。

### 5.4 线程池与优先级队列

构造函数从 ConfigManager 读 `THREAD_POOL_SIZE`（默认 4，ConfigManager.cpp:138；≤0 修正为 2，>16 告警，TaskManager.cpp:23-29）建 `ThreadPool`。这个池**只有 TaskManager 在用**。`task_queue_` 是带优先级的队列（TaskManager.h:302-312，QueueItem 的 `operator<` 按 priority 比较高优先在前），但目前只在 `create_task` 里 push（TaskManager.cpp:139）——真正的启动由路由层"创建即尝试启动"（TaskCRUDRoutes.cpp:233-235），队列更像是为未来调度器预留的结构。私有区的 `cv_`、`dependents`、`sceneConfigs` 同属"声明了但没人用"；`shutdown_requested_` 由析构置位并 join 看门狗（TaskManager.cpp:41-46）——但**不等待池中在跑的分析**，进程退出时分析线程随进程消亡，这正是重启恢复机制存在的原因。构造时还起独立线程跑 `TaskWatchdog`（TaskManager.cpp:37、537-542），共享 tasks_ 与锁，详见 TaskInfrastructure.md。

## 6. 工作流程走读（start_analysis）

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

RAII 清理的实际代码：

```cpp
// TaskManagerAnalysis.cpp:33-53（TaskCleanup，节选）
struct TaskCleanup {
    TaskManager& tm;
    const std::string& id;
    ~TaskCleanup() {
        bool is_deleted = false;
        {
            std::lock_guard<std::mutex> lock(tm.mtx_);
            is_deleted = (tm.tasks_.count(id) == 0);
        }
        if (is_deleted) {
            // ...（getTaskDir + exists + remove_all，异常吞掉）
        }
    }
} cleanup_handler{*this, task_id};
```

为什么用 RAII 而不是在 catch 里清理：流水线有十余个提前 return 的出口（每个取消检查点、每个失败分支），手动补磁盘清理必然遗漏；析构函数保证**唯一**退出路径上必查一次"任务还在不在 map"。而 delete_task（TaskManager.cpp:350-357）只对非运行中任务直接删目录——运行中的留给这个析构兜底，两边拼成完整的删除语义。收尾三连（:586-596）：set_result_db → FINALIZING 100% → COMPLETED，全部在 try 内；外层 catch 把任何异常统一转 FAILED + "Analysis error: ..." + ERROR 审计。**取消检查点遍布每个阶段开头**（`if (is_task_cancelled(task_id)) { update_status(..., CANCELLED, ...); return; }`），这是协作式取消落到实处的位置。

## 7. 与其他模块的协作

- **TaskRoutes 族**：REST 门面（见 routes/TaskRoutes.md）。
- **TaskPersistence / TaskSerialization / TaskWatchdog**：内部支撑组件（见 TaskInfrastructure.md）。
- **LLMAnalysisService / EventClusterAnalyzer / Linux·Windows·AndroidLLMAnalysisService**：LLM_ANALYSIS 与 PLATFORM_ANALYSIS 阶段的执行者（各见独立文档）。
- **LLMPythonProxy**：任务完成后的知识图谱摄取；`delete_task` 时反向调用 `deleteGraphitiData` 清理 Neo4j（TaskManager.cpp:340-341）。
- **PathManager**：所有任务目录/库路径的唯一来源；**AuditLog**：`add_audit_log` 贯穿所有状态变化（TaskManager.cpp:515-519）；**SceneDetector**：IMAGE_ANALYSIS 后回填 scenarios（见 SceneDetector.md）。

## 8. 注意事项与已知问题

- **取消是协作式的**：置位标志后工作线程要走到下一个检查点才停；LLM 单次调用若很慢，取消会延迟。看门狗的 30 分钟阈值就是为这种"合法慢"留的余量。
- **统计里的阶段缺失**：`get_task_statistics` 的 `running_phases` 只列了 6 个阶段，漏掉 LLM_ANALYSIS 与 FINALIZING（TaskManager.cpp:433-441）——统计页看不到这两阶段中的任务分布。
- **task_queue_ 未被消费**：优先级队列只有 push 没有 pop 消费者，优先级目前不影响执行顺序（创建即入池排队）。`cv_`、`dependents`、`sceneConfigs` 同属"声明了但没人用"。
- **锁内做文件 I/O**：save_tasks_internal 在 mtx_ 内写 JSON；任务多时 HTTP 读操作可能被拖慢（作者已知，见 TaskManager.cpp:144-146 注释）。
- **`PUT /api/tasks/{id}/priority` 是 no-op**：路由层返回成功但不改优先级（TaskMonitoringRoutes.cpp:148-149 注释"only return success"），根因是 TaskManager 没有实现改优先级的方法（priority 无 setter）。
- **大小写两套状态值**：REST API 用小写（TaskHelpers.cpp:117-126），tasks.json 里是大写（TaskSerialization.cpp:9-15）。跨层排查时注意。
- **get_task 返回整结构拷贝**：含 result_cache（可能很大的 JSON 串），列表页每次 get_all_tasks 拷贝全部任务的缓存——缓存大时有无谓开销。

## 9. 如何验证与扩展

- **验证**：建任务后 `cat data/tasks.json` 看持久化（状态为大写、无密码字段）；杀进程重启，原 RUNNING 任务应变为 FAILED"Interrupted by server restart"；删除运行中任务，确认 `data/tasks/<id>/` 目录稍后被清（TaskCleanup 兜底）。
- **扩展新分析阶段**：在 TaskManagerAnalysis.cpp 流水线里插入阶段调用 + `update_progress(TaskPhase::X, ...)`，并在 `calculate_overall_percentage` 权重表（TaskManager.cpp:546-555）里配权重；新阶段若要持久化进度，需同时在 TaskSerialization.cpp:24-32 补枚举映射（注意 FILE_CARVING 目前就漏在映射外，见 TaskInfrastructure.md）。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
