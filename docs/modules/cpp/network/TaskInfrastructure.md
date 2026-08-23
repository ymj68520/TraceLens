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
   └─ start_analysis() ──────────▶ TaskManagerAnalysis.cpp（流水线，见 TaskManager.md §4）
```

这些组件不对外暴露——外界只看得到 TaskManager 的公共 API。TaskWatchdog 直接持有 `tasks_` 引用和锁引用（TaskWatchdog.cpp:9-18），是"共享状态而非消息传递"的省事设计。

## 3. 核心概念与设计

### 3.1 重启恢复：宁可信其坏

`load_tasks` 读回 JSON 后，把状态为 RUNNING/PENDING 的任务一律改为 FAILED，并写明原因（TaskPersistence.cpp:55-62）：

> "The server was restarted while this task was in queue or running."

理由：进程没了，工作线程必然消失，"假装还在跑"只会让前端永远转圈。用户看到明确失败信息后可以重建任务。同时 `cleanup_orphan_directories`（TaskPersistence.cpp:74-99）把 `data/tasks/` 下不在 tasks_ 字典里的 UUID 目录整体删除——防止删除任务时崩溃留下的垃圾数据无限累积。

### 3.2 序列化的"只写真相"原则

TaskSerialization 是 AnalysisTask 的 JSON 形态唯一定义：

- 枚举用 `NLOHMANN_JSON_SERIALIZE_ENUM` 映射为字符串（TaskSerialization.cpp:9-45）。**注意 TaskStatus/Priority/Phase 在这里是大写**（"PENDING"...），而 REST 层用小写（TaskHelpers.cpp:117-126）——两套转换互不相干，排查时别混淆。
- 密码绝不落盘：`decrypt_password`/`backup_password` 不进 to_json，from_json 里显式 clear（TaskSerialization.cpp:95-96、148、154）。
- 不可序列化的运行时字段在加载时重置：`phase_start_time` 重置为 now（:63）、`cancellation_requested` 归 false（:170）、`execution_start_time` 重置（:169）——时间点类字段跨进程没有意义。
- `android_source` 会被持久化（:151-153）：逻辑 Android 任务重启后仍知道自己该走哪条短路。

### 3.3 看门狗：两类停滞，两个阈值

TaskWatchdog::run（TaskWatchdog.cpp:24-89）循环巡检 `tasks_`：

- **PENDING 超时**：创建后超过 `TASK_WATCHDOG_PENDING_MINUTES`（默认 30 分钟）仍是 PENDING → 判 FAILED"调度失败"（:53-65）；
- **RUNNING 心跳超时**：`progress.phase_start_time` 距今超过 `TASK_WATCHDOG_STALE_MINUTES`（默认 30 分钟）没有进度更新 → 判 FAILED"执行超时"（:70-82）。LLM 阶段每个文件/簇都会打心跳，所以该阈值只在真挂死时触发。

有变更才回调保存（:85-87），避免无谓写盘。

## 4. 工作流程走读

**启动**：TaskManager 构造 → `load_tasks`（TaskManager.cpp:63-70）→ TaskPersistence 读 tasks.json、执行恢复改写、清理孤儿目录 → 起看门狗线程（TaskManager.cpp:37）。

**运行中**：任何 `update_status`/`create_task`/`set_result_db` 都会在锁内调 `save_tasks_internal`（TaskManager.cpp:53-61）→ TaskPersistence::save_tasks 把全量任务数组 dump(4) 写文件（TaskPersistence.cpp:12-29）。**直接覆写、无临时文件**——断电瞬间可能得到半截 JSON（见 §6）。

**巡检**：看门狗每轮加锁扫描，发现停滞任务就改状态并经回调持久化；随后路由层轮询到的就是 FAILED + error_details 解释。

**反序列化容错**：from_json 大量使用 `j.contains(...) ? ... : 默认值`（TaskSerialization.cpp:116-154），旧版本 tasks.json 缺新字段也能加载，向前兼容。

## 5. 与其他模块的协作

- **TaskManager**：唯一调用方；save/load 的锁语义由它保证（`save_tasks_internal` 必须在 mtx_ 内调用）。
- **PathManager**：tasks.json 路径与任务目录的唯一来源（TaskPersistence.cpp:3、79）。
- **ConfigManager**：看门狗两个阈值的环境变量读取（TaskWatchdog.cpp:28-35）。
- **流水线各分析器**：仅经 TaskManagerAnalysis.cpp 间接相关（该文件的走读放在 TaskManager.md）。

## 6. 注意事项与已知问题

- **保存不是原子的**：`std::ofstream` 直接打开目标文件覆写（TaskPersistence.cpp:23-25），进程在写入中途被杀会留下损坏的 tasks.json；下次 `load_tasks` 解析失败则**全部任务丢失**（catch 后只打印错误，TaskPersistence.cpp:69-71）。重要场景建议先备份该文件。
- **FILE_CARVING 缺席枚举映射**：TaskPhase 的序列化映射（TaskSerialization.cpp:24-32）没有 FILE_CARVING 这一项——若任务在雕复阶段崩溃，落盘的 current_phase 处理是未定义边界。补映射是一行修复。
- **看门狗注释与实现不符**：注释说"每 60 秒检查一次"（TaskWatchdog.cpp:38-39），实际 `wait_for` 是 1 秒（:41-43）。行为无害（阈值是分钟级），但读代码别被注释带偏。
- **状态字符串大小写分裂**：tasks.json 大写、REST 小写（§3.2）。手工编辑 tasks.json 时必须用大写。
- **TaskAnalysisRunner.h 是死文件**：再次强调，别引用它。

## 7. 如何验证与扩展

- **验证重启恢复**：跑一个任务，中途 `kill -9` 服务进程，重启后该任务应为 FAILED 且 error_details 含 "Interrupted by server restart"；同时在 `data/tasks/` 下手工建一个假 UUID 目录、重启，它应被清掉。
- **验证看门狗**：把 `TASK_WATCHDOG_PENDING_MINUTES` 设为 1，创建一个依赖未完成任务的 PENDING 任务，等 1 分钟观察其变 FAILED。
- **扩展**：新增 AnalysisTask 字段时，同步改 TaskSerialization 的 to_json/from_json（from_json 记得用 contains 容错）；新增阶段时补 TaskSerialization.cpp:24 的 Phase 映射与 TaskManager.cpp:546 的权重表。

**最后更新**: 2026-08-23（解释式重写）
