# TaskInfrastructure（TaskManager 的内部支撑组件群）

> **一句话**：TaskManager 身后四个不出风头的零件——流水线执行体（TaskManagerAnalysis.cpp）、JSON 持久化（TaskPersistence）、序列化（TaskSerialization）、停滞任务看门狗（TaskWatchdog），它们让任务状态能落盘、能恢复、不会悄悄卡死。

## 1. 为什么有这个模块

TaskManager.cpp 如果把执行、持久化、序列化、巡检全部塞下，会是上千行的大杂烩。这个"组件群"按职责拆开：

| 组件 | 文件 | 一句话职责 |
|---|---|---|
| 流水线执行体 | TaskManagerAnalysis.cpp | `TaskManager::start_analysis` 的实现（仍是成员函数，只是换了文件） |
| 持久化 | TaskPersistence.{h,cpp} | tasks_ 字典 ↔ data/tasks.json，含重启恢复与孤儿目录清理 |
| 序列化 | TaskSerialization.{h,cpp} | AnalysisTask/枚举 ↔ JSON 的唯一权威定义 |
| 看门狗 | TaskWatchdog.{h,cpp} | 周期巡检，把停滞的 PENDING/RUNNING 任务判 FAILED |

> ⚠️ **死文件警示**：`src/network/HTTPServer/TaskAnalysisRunner.h` 是**未被任何代码引用的遗留头文件**（无对应 .cpp、无人 include，里面的 `TaskAnalysisRunner` 类从未实现）。实际的执行逻辑在 `TaskManagerAnalysis.cpp:26` 的 `TaskManager::start_analysis`。不要在 TaskAnalysisRunner.h 上开发。

## 2. 在系统中的位置

```
TaskManager (TaskManager.cpp)
   ├─ 构造时: load_tasks()  ─────▶ TaskPersistence::load_tasks + cleanup_orphan_directories
   ├─ 每次状态变化: save_tasks_internal() ─▶ TaskPersistence::save_tasks (内部调 TaskSerialization)
   ├─ 构造时: watchdog_thread_ ───▶ TaskWatchdog::run（共享 tasks_/mtx_）
   └─ start_analysis() ──────────▶ TaskManagerAnalysis.cpp（流水线，见 TaskManager.md §6）
```

这些组件不对外暴露——外界只看得到 TaskManager 的公共 API。TaskWatchdog 直接持有 `tasks_` 引用和锁引用，是"共享状态而非消息传递"的省事设计：

```cpp
// TaskWatchdog.cpp:9-18
TaskWatchdog::TaskWatchdog(
    std::map<std::string, AnalysisTask>& tasks,
    const std::atomic<bool>& shutdown,
    std::function<void()> save_callback,
    std::mutex& task_mutex)
    : tasks_(tasks)
    , shutdown_requested_(shutdown)
    , save_callback_(std::move(save_callback))
    , task_mutex_(task_mutex) {
}
```

四个参数全是引用/回调：tasks_ 是 TaskManager 的字典本体（不是副本），task_mutex_ 是同一把 mtx_，shutdown 直接共享原子变量，save_callback 指向 `save_tasks_internal`（TaskManager.cpp:538-540）。这个注入方式决定了 TaskWatchdog **必须**在 TaskManager 析构前退出（否则引用悬垂）——TaskManager 析构函数先置 shutdown_requested_ 再 join 看门狗线程（TaskManager.cpp:41-46）正是履约。若给看门狗加新逻辑，同样必须遵守"所有访问都先拿 task_mutex_"的纪律。

## 3. 核心概念与设计

### 3.1 重启恢复：宁可信其坏

```cpp
// TaskPersistence.cpp:50-65（load_tasks 的恢复段）
for (const auto& element : j) {
    AnalysisTask task;
    from_json(element, task);

    // Fix up state for restarted tasks (Recovery Logic)
    if (task.status == TaskStatus::RUNNING || task.status == TaskStatus::PENDING) {
        task.status = TaskStatus::FAILED;
        task.message = "Interrupted by server restart";
        task.error_details = "The server was restarted while this task was in queue or running. Please delete and recreate if necessary.";

        // Reset timestamps to current for visibility
        task.completed_time = std::chrono::system_clock::now();
    }

    tasks[task.id] = task;
}
```

进程没了，工作线程必然消失，"假装还在跑"只会让前端永远转圈。PENDING 也一并判死是因为调度器（本应立即 start_analysis 的路由层）同样不存在了。completed_time 重置为当前时刻是给 cleanup_completed_tasks 的年龄计算一个合理起点。用户看到明确失败信息后可以重建任务。同时 `cleanup_orphan_directories`（TaskPersistence.cpp:74-99）把 `data/tasks/` 下不在 tasks_ 字典里的 UUID 目录整体删除——防止删除任务时崩溃留下的垃圾数据无限累积。

### 3.2 保存：全量覆写，一把梭

```cpp
// TaskPersistence.cpp:12-29
void TaskPersistence::save_tasks(
    const std::map<std::string, AnalysisTask>& tasks,
    const std::string& tasksPath) {

    nlohmann::json j = nlohmann::json::array();
    for (const auto& pair : tasks) {
        nlohmann::json task_json;
        to_json(task_json, pair.second);
        j.push_back(task_json);
    }

    std::ofstream out(tasksPath);
    if (out.is_open()) {
        out << j.dump(4);
    } else {
        std::cerr << "CRITICAL: Failed to save tasks to " << tasksPath << std::endl;
    }
}
```

每次保存都是**全量数组 dump(4) 直接覆写**——没有临时文件+rename 的原子替换。打开失败只打 CRITICAL 日志、不抛异常、不重试，调用方（save_tasks_internal）也无从感知失败。这组合出两个后果：文件打开失败时内存态与磁盘态静默分叉；写入中途被杀会留下半截 JSON（后果见 §6）。写成 map 迭代还有一个隐含特性：任务按 id 字典序落盘，与创建顺序无关。

### 3.3 序列化的"只写真相"原则

TaskSerialization 是 AnalysisTask 的 JSON 形态唯一定义：

- 枚举用 `NLOHMANN_JSON_SERIALIZE_ENUM` 映射为字符串（TaskSerialization.cpp:9-45）。**注意 TaskStatus/Priority/Phase 在这里是大写**（"PENDING"...），而 REST 层用小写（TaskHelpers.cpp:117-126）——两套转换互不相干，排查时别混淆。宏必须放在全局作用域（文件头注释解释了 ADL 查找的原因）。
- 密码绝不落盘：`decrypt_password`/`backup_password` 不进 to_json，from_json 里显式 clear（TaskSerialization.cpp:95-96、148、154）。
- 不可序列化的运行时字段在加载时重置：`phase_start_time` 重置为 now（:63）、`cancellation_requested` 归 false（:170）、`execution_start_time` 重置（:169）——时间点类字段跨进程没有意义。

```cpp
// TaskSerialization.cpp:106-135、148-154（from_json 的容错骨架，节选）
void from_json(const nlohmann::json& j, AnalysisTask& t) {
    j.at("id").get_to(t.id);
    j.at("image_path").get_to(t.image_path);
    j.at("status").get_to(t.status);
    // ...
    if(j.contains("result_cache")) j.at("result_cache").get_to(t.result_cache);
    if(j.contains("scenarios")) {
        t.scenarios.clear();
        for (const auto& s : j.at("scenarios")) {
            std::optional<ForensicScenario> scenario;
            if (s.is_string()) {
                scenario = string_to_scenario(s.get<std::string>());
            } else if (s.is_number_integer()) {
                const auto value = s.get<int>();
                if (value >= static_cast<int>(ForensicScenario::ANDROID) &&
                    value <= static_cast<int>(ForensicScenario::SERVER_CLOUD)) {
                    scenario = static_cast<ForensicScenario>(value);
                }
            }
            if (scenario.has_value()) {
                t.scenarios.push_back(scenario.value());
            }
        }
    }
    else if(j.contains("android_analyze") && j["android_analyze"].get<bool>()) t.scenarios = {ForensicScenario::ANDROID};
    // ...
    t.decrypt_password.clear();
    // ...
    t.backup_password.clear();
}
```

这里能看到三层容错设计：核心字段（id/status）用 `j.at()` 硬取——旧文件缺这些键属数据损坏，抛异常由 load_tasks 的 catch 兜住；可选字段一律 `j.contains() ? ... : 默认值`——旧版本 tasks.json 缺新字段也能加载，向前兼容；scenarios 同时接受字符串与整数两种形态（历史上枚举曾被序列化成数字），越界整数被丢弃而非报错。`android_source` 会被持久化（:151-153）：逻辑 Android 任务重启后仍知道自己该走哪条短路。

### 3.4 看门狗：两类停滞，两个阈值

TaskWatchdog::run（TaskWatchdog.cpp:24-89）循环巡检 `tasks_`，双阈值都从 ConfigManager 读环境变量、非法值回落 30 分钟：

```cpp
// TaskWatchdog.cpp:28-35
const long stale_minutes = []() {
    int v = ConfigManager::instance().getInt("TASK_WATCHDOG_STALE_MINUTES", 30);
    return v > 0 ? static_cast<long>(v) : 30L;
}();
const long pending_minutes = []() {
    int v = ConfigManager::instance().getInt("TASK_WATCHDOG_PENDING_MINUTES", 30);
    return v > 0 ? static_cast<long>(v) : 30L;
}();
```

两个判定分支的代码形态几乎对称，但计时基准不同——这是理解它们的钥匙：

```cpp
// TaskWatchdog.cpp:51-82（巡检循环体，节选）
for (auto& [id, task] : tasks_) {
    // Case A: PENDING tasks stuck beyond the pending threshold (scheduler loss)
    if (task.status == TaskStatus::PENDING) {
        auto elapsed = std::chrono::duration_cast<std::chrono::minutes>(
            now_system - task.created_time).count();
        if (elapsed > pending_minutes) {
            task.cancellation_requested = true;
            task.status = TaskStatus::FAILED;
            task.message = "Stale task detected (Pending timeout)";
            task.error_details = "The task remained in pending state for over " + std::to_string(pending_minutes) + " minutes. This usually indicates a system scheduling failure.";
            task.completed_time = now_system;
            changed = true;
            std::cout << "[Watchdog] Failed stale pending task: " << id << std::endl;
        }
    }

    // Case B: RUNNING tasks with no progress update beyond the stale
    // threshold (C++ thread hang). LLM-heavy phases emit per-file /
    // per-cluster heartbeats, so this only trips on genuine hangs.
    if (task.status == TaskStatus::RUNNING) {
        auto elapsed = std::chrono::duration_cast<std::chrono::minutes>(
            now_steady - task.progress.phase_start_time).count();
        if (elapsed > stale_minutes) {
            task.cancellation_requested = true;
            task.status = TaskStatus::FAILED;
            // ...
            changed = true;
            std::cout << "[Watchdog] Failed hung running task: " << id << std::endl;
        }
    }
}

if (changed && save_callback_) {
    save_callback_();
}
```

**PENDING 用 system_clock 比 created_time**（等待时长，挂钟即可）；**RUNNING 用 steady_clock 比 phase_start_time**（心跳间隔，必须不受挂钟跳变影响）。PENDING 超时通常意味着调度丢失——任务建了但没人 start 它（依赖链断裂、路由层异常）；RUNNING 心跳超时意味着 C++ 线程真挂死——LLM 阶段每个文件/簇都会打心跳，所以该阈值只在真挂死时触发。两个分支都置 `cancellation_requested = true`：若线程其实还活着（误判场景），它会在下一个检查点配合退出，不至于出现"状态 FAILED 但线程还在写库"的精神分裂。有变更才回调保存（:85-87），避免每秒一次的无谓全量写盘——巡检周期实际是 1 秒（见 §6 的注释不符项）。

## 4. 工作流程走读

**启动**：TaskManager 构造 → `load_tasks`（TaskManager.cpp:63-70）→ TaskPersistence 读 tasks.json、执行恢复改写、清理孤儿目录 → 起看门狗线程（TaskManager.cpp:37）。加载入口还有一个防御分支：tasks_ 为空且磁盘无 tasks.json 时 save_tasks_internal 直接返回（TaskManager.cpp:55-57），防止首次启动就把空数组写出去覆盖旧数据。

**运行中**：任何 `update_status`/`create_task`/`set_result_db` 都会在锁内调 `save_tasks_internal`（TaskManager.cpp:53-61）→ TaskPersistence::save_tasks 把全量任务数组 dump(4) 写文件（TaskPersistence.cpp:12-29）。**直接覆写、无临时文件**——断电瞬间可能得到半截 JSON（见 §6）。

**巡检**：看门狗每轮加锁扫描，发现停滞任务就改状态并经回调持久化；随后路由层轮询到的就是 FAILED + error_details 解释。

**反序列化容错**：from_json 大量使用 `j.contains(...) ? ... : 默认值`（TaskSerialization.cpp:116-154），旧版本 tasks.json 缺新字段也能加载，向前兼容。

## 5. 与其他模块的协作

- **TaskManager**：唯一调用方；save/load 的锁语义由它保证（`save_tasks_internal` 必须在 mtx_ 内调用）。
- **PathManager**：tasks.json 路径与任务目录的唯一来源（TaskPersistence.cpp:3、79）。
- **ConfigManager**：看门狗两个阈值的环境变量读取（TaskWatchdog.cpp:28-35）。
- **流水线各分析器**：仅经 TaskManagerAnalysis.cpp 间接相关（该文件的走读放在 TaskManager.md）。
- **TaskProgress.phase_start_time**：看门狗 Case B 的心跳依据——流水线必须持续调 update_progress，否则被误判挂死。

## 6. 注意事项与已知问题

- **保存不是原子的**：`std::ofstream` 直接打开目标文件覆写（TaskPersistence.cpp:23-25），进程在写入中途被杀会留下损坏的 tasks.json；下次 `load_tasks` 解析失败则**全部任务丢失**（catch 后只打印错误，TaskPersistence.cpp:69-71）。重要场景建议先备份该文件。
- **FILE_CARVING 缺席枚举映射**：TaskPhase 的序列化映射（TaskSerialization.cpp:24-32）没有 FILE_CARVING 这一项——若任务在雕复阶段崩溃，落盘的 current_phase 处理是未定义边界。补映射是一行修复。
- **看门狗注释与实现不符**：注释说"每 60 秒检查一次"（TaskWatchdog.cpp:38-39），实际 `wait_for` 是 1 秒（:41-43）。行为无害（阈值是分钟级），但读代码别被注释带偏。1 秒醒来+无变更不写盘，代价只是一次空锁。
- **状态字符串大小写分裂**：tasks.json 大写、REST 小写（§3.3）。手工编辑 tasks.json 时必须用大写。
- **TaskAnalysisRunner.h 是死文件**：再次强调，别引用它。
- **孤儿清理按目录名查 tasks_ 键**：`data/tasks/` 下任何"不在字典里的目录"都会被删（TaskPersistence.cpp:85-94）——若有人手工把无关资料放进 tasks/ 目录，重启即被清走；注释说"If directory name is a UUID (common for tasks)"，但代码实际不校验 UUID 形态，任何目录名都删。

## 7. 如何验证与扩展

- **验证重启恢复**：跑一个任务，中途 `kill -9` 服务进程，重启后该任务应为 FAILED 且 error_details 含 "Interrupted by server restart"；同时在 `data/tasks/` 下手工建一个假 UUID 目录、重启，它应被清掉。
- **验证看门狗**：把 `TASK_WATCHDOG_PENDING_MINUTES` 设为 1，创建一个依赖未完成任务的 PENDING 任务，等 1 分钟观察其变 FAILED。
- **扩展**：新增 AnalysisTask 字段时，同步改 TaskSerialization 的 to_json/from_json（from_json 记得用 contains 容错）；新增阶段时补 TaskSerialization.cpp:24 的 Phase 映射与 TaskManager.cpp:546 的权重表；若想根治原子性问题，save_tasks 改为"写 tasks.json.tmp → fsync → rename"三步即可，签名无需变化。

## 8. tasks.json 的完整键契约（二轮补全）

to_json（TaskSerialization.cpp:66-104）写出的全部键——这是磁盘格式的权威清单（时间戳为**秒**级 epoch，注意与 REST 层 TaskHelpers 的毫秒不同）：

| 键 | 类型 | 序列化行为 | from_json 容错 |
|---|---|---|---|
| id / image_path / status / message | string | 恒写 | **j.at() 硬取**（缺即抛异常，load catch 兜底全损） |
| output_files_db / output_raw_db / output_events_db | string | 恒写 | j.at() 硬取 |
| priority | enum→大写串 | 恒写 | j.at() 硬取 |
| progress | object | 子序列化（current_phase 大写枚举/phase_percentage/overall_percentage/phase_description 四键） | j.at() 硬取；**phase_start_time/estimated_completion 不落盘**，from_json 重置 phase_start_time=now（:63） |
| result_cache | string | 恒写（可能很大） | contains 可选 |
| scenarios | array of 小写串 | 恒写（恒为串数组） | contains 可选；**兼容旧整数形态**（0-3 越界丢弃，:123-129） |
| android_analyze | bool | 恒写（scenarios 的投影，向后兼容） | 仅在 scenarios 缺失且为 true 时回填 [ANDROID]（:135） |
| xfs_mode | enum→首字母大写串（"Auto"/"Native"/"Pure"） | 恒写 | contains 可选 |
| db_output_dir / error_details / metadata / llm_analyze / llm_mode | 混合 | 恒写 | contains 可选 |
| output_descriptions_db / case_description / filter_profile / file_carving | 混合 | 恒写 | contains 可选 |
| enable_decryption / key_file_dir | 混合 | 恒写 | contains 可选 |
| android_source | string | 恒写（:97） | contains 可选（:151-153） |
| extraction_directory | string | **写时推导**（PathManager::getTaskExtractDir，:99）——不读回 | from_json **不读此键**（加载后由 get_task 调用方重新推导） |
| created_time / started_time / completed_time | 秒 epoch int64 | 恒写 | contains 可选（:156-167） |
| **decrypt_password / backup_password** | — | **绝不写出**（:95-96 注释） | **显式 clear**（:148、:154） |
| graphiti_job_id | — | **不写出**（重启丢失，作业号只活在内存） | — |
| cancellation_requested | — | 不写出 | 显式 false（:170） |
| execution_start_time | — | 不写出 | 重置 now（:169，steady_clock） |

REST 层 task_to_json（毫秒、小写状态、含 extraction_directory 等 30 键）与这份磁盘契约是**两套独立序列化**——改字段要三处同步（TaskSerialization、TaskHelpers、create_task）。

## 9. 新发现的三处接口死位

1. **load_tasks 的 runningTaskIds 出参从未被填充**（TaskPersistence.cpp:31-34 签名带 `std::unordered_set<std::string>& runningTaskIds`，函数体全程不写它；TaskManager.cpp:66-68 传入局部变量后也无人读）。这是"恢复时收集 RUNNING 任务 ID"设计的残迹——实际恢复逻辑直接把 RUNNING 改写 FAILED，不再需要 ID 集合。参数纯死位。
2. **TaskWatchdog::stop() 无调用方**（TaskWatchdog.h:36 声明、cpp:20-22 实现 notify_all）——析构路径走的是 shutdown_requested_ + wait_for 1s 自然退出，stop() 的唤醒加速从未被接线。无害但多余。
3. **TaskWatchdog 的 wait_mutex_/wait_cv_ 每轮新建锁**（cpp:40-43）——run() 里 `std::unique_lock waitLock(wait_mutex_)` 与 `task_mutex_` 是两把锁，唤醒等待与任务扫描互不阻塞；但 wait_cv_ 从未被 notify（stop() 无人调），`wait_for(1s)` 实为固定 sleep。若想析构即时退出，正确接线是把 TaskManager 析构里的 `shutdown_requested_ = true` 后补一次 `watchdog.stop()`——当前实现靠 1 秒超时轮询发现关闭标志。

## 10. 看门狗的时钟与锁细节补充

- **双时钟快照在锁外取**（cpp:46-47 的 now_system/now_steady 在拿 task_mutex_ 之前），扫描循环里直接用——锁持有时间最短化；代价是单轮扫描内所有任务共用同一时刻，误差 ≤ 扫描时长（微秒级），远小于分钟阈值。
- **巡检不写 audit log**——Case A/B 都只改任务字段 + stdout，不经 add_audit_log（对比：cancel/delete/重启恢复都有审计）。看门狗杀掉的任务在审计日志里查不到"谁杀的"，只有任务的 error_details 文本可查。
- **changed 批量保存**（:85-87）：一轮杀 N 个任务只触发一次 save_callback_（= save_tasks_internal，在 task_mutex_ 已持有的状态下调用——save_tasks_internal 自身不加锁，依赖"调用方持锁"的纪律，TaskManager.cpp:53-61 的公开 save_tasks 才加锁。看门狗在 taskLock 存活期间回调，正是这个纪律的履约）。

## 11. 配置影响表（TaskInfrastructure 视角）

| 配置 | 默认 | 消费点 | 说明 |
|---|---|---|---|
| `TASK_WATCHDOG_STALE_MINUTES` | 30 | TaskWatchdog.cpp:29 | RUNNING 无心跳判 FAILED；≤0 回落 30 |
| `TASK_WATCHDOG_PENDING_MINUTES` | 30 | :33 | PENDING 停滞判 FAILED；≤0 回落 30 |
| `DATA_DIR` | `data` | PathManager → tasks.json 与 tasks/ 目录 | 孤儿清理的扫描根 |
| `THREAD_POOL_SIZE` | 4 | TaskManager.cpp:23-31 | 影响流水线（TaskManagerAnalysis）而非本组件群其余部分 |
| （无巡检周期 env） | 1 秒硬编码 | :42 | 注释写 60s（§6 已记不符项） |

## 12. 关联矩阵（补全版）

| 方向 | 对象 | 交互点 | 说明 |
|---|---|---|---|
| 被调 | TaskManager 构造/析构 | load_tasks / watchdog 线程 / join | 唯一装配点 |
| 依赖 | PathManager | tasks.json、tasks/、extract 目录 | extraction_directory 写时推导 |
| 依赖 | ConfigManager | 看门狗双阈值 | ≤0 回落 |
| 产出 | data/tasks.json | save_tasks（全量覆写） | 键契约见 §8 |
| 消费 | data/tasks.json | load_tasks（恢复改写） | RUNNING/PENDING→FAILED |
| 副作用 | data/tasks/ 目录 | cleanup_orphan_directories | 任意非任务目录即删（§6） |
| 死位 | runningTaskIds / TaskWatchdog::stop() | — | §9 |
| 间接 | TaskManagerAnalysis（流水线） | phase_start_time 心跳 | Case B 的判定依据 |

## 13. tasks.json 与 cases.json 的持久化对照表

两份 JSON 文件是 C++ 侧仅有的两份"内存态镜像"持久化，逐维对照：

| 维度 | tasks.json | cases.json |
|---|---|---|
| 路径 | PathManager::getTasksJsonPath（data/tasks.json） | getDataDir()/cases.json（CaseManager.cpp:91-93） |
| 顶层结构 | 数组 | 数组 |
| 缩进 | dump(4) | dump(2) |
| 时间单位 | **秒** epoch | **毫秒** epoch |
| 枚举大小写 | 大写（PENDING） | 小写（open） |
| 写入时机 | 每次状态变化（锁内） | 每次 CRUD（锁内） |
| 原子性 | 无（ofstream 覆写） | 无（同款） |
| 损坏后果 | 全部任务丢失（catch 打日志） | 全部案件丢失 |
| 恢复改写 | RUNNING/PENDING→FAILED | 无（案件无运行态） |
| 孤儿清理 | data/tasks/ 目录级 | 无 |
| 密码字段 | 显式不写+加载清空 | 无密码概念 |

写跨两份文件的脚本时四个差异点（缩进/时间单位/大小写/恢复行为）都容易踩。

## 14. 启动时序（TaskManager 构造的严格顺序）

```
TaskManager::TaskManager()                        TaskManager.cpp:21-38
  1 读 THREAD_POOL_SIZE → 建池                    :23-31   （池先建——load 不需要它，但保证后续任何 start 可用）
  2 load_tasks()                                  :34
     2.1 mtx_ 加锁                                :64
     2.2 TaskPersistence::load_tasks              读取+恢复改写+入 map
     2.3 cleanup_orphan_directories               删不在 map 的目录
  3 起 watchdog 线程                              :37      （共享 tasks_/mtx_/shutdown_——此时 map 已就绪）
main 继续 → AnalysisOrchestrator → HTTPServer（TaskManager::instance() 首次调用在 HTTPServer 构造）
```

顺序保证：看门狗启动时 tasks_ 必已装载完毕（同一线程内顺序执行）——不存在"看门狗扫描半载 map"的窗口。反之，**析构顺序**是 shutdown → join 看门狗（:41-46）→ 成员逆序销毁（watchdog_thread_ 先于 tasks_）——引用悬垂被 join 语义挡住（§2 已记）。

## 15. 验证 runbook（补充版）

```bash
# 1. 时间单位对照（一张表看两个文件的差异）
jq '.[0] | {created: .created_time}' data/tasks.json          # 秒（10 位）
jq '.[0] | {created: .created_at}' data/cases.json            # 毫秒（13 位）
# 2. FILE_CARVING 缺席的枚举映射边界（§6）
jq '[.[].progress.current_phase] | unique' data/tasks.json    # 不含 "FILE_CARVING"
# 3. 孤子清理的白名单行为
mkdir data/tasks/not-a-uuid && systemctl restart tracelens && ls data/tasks/   # 目录消失
# 4. runningTaskIds 死位验证（§9.1）
grep -n "runningTaskIds" src/network/HTTPServer/TaskPersistence.cpp   # 仅签名，无写入
```

**最后更新**: 2026-08-24（二轮深化：补全方法清单与契约细节）
