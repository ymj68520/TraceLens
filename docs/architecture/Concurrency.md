# 并发模型：TraceLens 里的线程、协程与锁

> 配套文档：[Overview.md](./Overview.md)（系统组成）、[DataFlow.md](./DataFlow.md)（任务生命周期）。本文回答一个问题：**多个分析任务、多个 LLM 调用、多个服务同时跑时，谁在等谁，为什么不会（或为什么会）打架。** 所有机制均标注源码位置。

## 1. 全景：四种并发主体

TraceLens 运行时的并发发生在四个层面，各自有独立的"调度器"：

| 层面 | 调度器 | 并发单位 | 典型并发度 |
|------|--------|---------|-----------|
| C++ 服务 | Crow 线程池（`app_.multithreaded()`，`HTTPserver.cpp`） | HTTP 请求 | 数十 |
| C++ 分析 | `ThreadPool`（`THREAD_POOL_SIZE`，默认 4） | 分析任务 | ≤4 个任务并行 |
| Python 服务 | asyncio 事件循环（uvicorn 单进程） | 协程 + `to_thread` 线程 | 事件循环 1 + 少量线程 |
| C/S 轮询 | agent 侧 poller（每个取证机一个） | 命令 | 每机串行 |

一个容易误解的点：**分析并发和 HTTP 并发是两回事**。Crow 可以同时服务一百个前端请求（查进度、查时间线都是毫秒级 SQLite 读），但真正吃 CPU 的分析任务最多同时跑 `THREAD_POOL_SIZE` 个——这是有意为之的背压设计（见 [ThreadPool 模块文档](../modules/cpp/core/ThreadPool.md)），防止多个镜像解析把磁盘和内存打爆。

## 2. C++ 侧：一把大锁、一个池、一个看门狗

### 2.1 TaskManager 的大锁纪律

任务状态的全部真相在 `TaskManager` 的 `tasks_` map 里，受一把互斥锁 `mtx_` 保护。纪律是：**任何读写 tasks_ 的地方先拿锁，拿锁区间内不做耗时操作**（不调 LLM、不碰文件系统）。流水线工作线程在阶段边界用 `update_progress`/`update_status` 短暂加锁更新状态后立刻释放（`TaskManagerAnalysis.cpp` 各阶段调用点），前端轮询的 GET 请求 likewise 短暂加锁拷贝快照——所以"看进度"永远不会阻塞"跑分析"。

需要理解的一个推论：**进度更新是任务线程主动做的，不是中心调度的**。如果某个分析器在一个大文件上卡十分钟不汇报，锁不会阻塞任何人，但进度条也不动——这正是 TaskWatchdog 存在的原因（见 2.3）。

### 2.2 线程池的三个调用方与两种生命周期

[ThreadPool](../modules/cpp/core/ThreadPool.md) 是全项目唯一的通用池实现，但有三种用法：

- **TaskManager 常驻池**（`TaskManager.cpp:31` 构造）：服务启动时创建、退出时析构，跑任务流水线；
- **LLM FileAnalyzer 临时池**（`FileAnalyzer.cpp:280-289`）：批量文件分析时按需创建、用完即析构（仅当 poolSize>1 且文件数>1）；
- **DLLAnalyzer 临时池**：目录扫描与并发解析。

注意 `THREAD_POOL_SIZE` 同时影响任务并发与 LLM 并发（两处读同一个配置）——调大它是在同时放开两个闸门，这在 [PerformanceTuning](../ops/PerformanceTuning.md) 里展开。池本身的语义：固定 worker、无界队列、退出时**排干**（已提交任务保证执行完）、任务异常经 `std::future` 传回调用方——`future.get()` 不调用的异常会被静默吞掉，这是使用纪律。

### 2.3 看门狗与协作式取消

取消与超时都是**协作式**的，没有强杀：

- 取消：API 置 `cancellation_requested` 原子标志，流水线在每个阶段边界检查（`TaskManagerAnalysis.cpp` 各阶段前的 `is_task_cancelled`），当前阶段跑完后任务以 `cancelled` 终止。阶段内部（比如一个巨大的 SQL）无法被打断。
- 看门狗：独立线程每秒醒一次（注释写 60s，实现是 1s，`TaskWatchdog.cpp:38-43`），对 RUNNING 超过 `TASK_WATCHDOG_STALE_MINUTES`（默认 30 分钟）无进度、或 PENDING 超过 `TASK_WATCHDOG_PENDING_MINUTES` 的任务置 FAILED。它判断"无进度"用的是进度百分比是否变化——一个诚实汇报内部进度的大任务不会被误杀。

### 2.4 SQLite 并发：靠隔离而非锁

TraceLens 几乎不做跨连接的库级并发控制，而是用三个结构性手段绕开问题：

1. **每任务一组独立库文件**（`data/tasks/<id>/`）——并发任务写不同的文件，天然无竞争；
2. **WAL + busy_timeout**：`DB_BUSY_TIMEOUT_MS`、`DB_JOURNAL_MODE` 可调；多读者（前端查询）与单写者（分析线程）在 WAL 下并存。三处代码注释记录了同一个教训：不开 WAL+NORMAL 时 fsync 会把 jbd2 拖进 D 态数分钟（`DatabaseManager.cpp:28-36` 等）；
3. **HTTP 查询侧防御**：`SQLiteHelper` 的 `is_readonly_select`（词边界匹配防 `CREATED` 误伤）与 `clamp_limit` 把用户输入挡在只读、有界查询之外。

跨任务需要聚合时（Python 案件分析、Graphiti 摄取），是**打开多个只读连接分别读**，而不是跨库写事务。

### 2.5 LLM 调用的串行化瓶颈

一个容易被忽略的事实：`LLMClient` 内部有一把互斥锁把 get/post 串行化（[LLMClient 模块文档](../modules/cpp/integration/LLMClient.md)）。这意味着**即使批量分析开了 N 个线程并发调 LLM，实际请求也是排队发出的**。在本地单模型端点（LM Studio 通常单槽）下这是合理的自我保护；如果未来接多槽位服务，这把锁是首先要重新审视的点。重试语义也在这层：`maxRetries=3` 实为最多 4 次尝试（首试 + 3 重试），4xx 也重试（对本地端点的宽容取舍）。

## 3. Python 侧：单事件循环 + 三处线程卸载

httpserver 是标准 asyncio 单循环模型，关键在于**哪些操作被推去了线程**（阻塞事件循环 = 所有请求卡住）：

- **报告生成执行器**：DDL/SQLite 初始化走 `asyncio.to_thread`（`service_manager.py:199-205`）；
- **启动初始化**：`asyncio.timeout(30s)` 包住整个初始化序列，每个可选服务再套 12s 上限，失败回滚已初始化项（详见 [ServiceManager 模块文档](../modules/python/httpserver/services/ServiceManager.md)）；
- **markitdown 批量转换**：`Semaphore(4)` 限流并发（[Markitdown 路由文档](../modules/python/httpserver/routes/Markitdown.md)）。

后台作业（Graphiti 摄取、二次分析、事件刷新、报告生成）各有自己的 manager/executor，作业状态在内存 + Redis（不可用时内存回退）。已知非抢占语义：`cancel_job` 只置标志，RUNNING 中的作业完成时会覆盖 CANCELLED 状态（IngestionJobManager 文档"注意事项"）——排障时见过的"取消了却显示完成"即此。

## 4. C/S 侧：轮询模型与两个已知缺口

分布式模式的并发模型是**拉取式**：每台取证机的 agent 独立轮询命令队列，天然无推送连接的管理成本。两个已记录的缺口（[server/Services 模块文档](../modules/python/server/Services.md)）：

1. 命令领取无 `FOR UPDATE SKIP LOCKED`——多 agent 抢同一条命令的理论竞态（单 poller 现状下风险低）；
2. `retry_count` 只递增无消费方、TTL 清扫无后台定时器（靠 expire 端点触发）。

## 5. 前端：轮询与"过期响应"防御

前端不建立长连接（除 TerminalOutput 的 WebSocket 与日志 SSE），页面数据靠 hooks 轮询。关键防御是**过期响应守卫**：任务切换/组件卸载后迟到的响应不得覆盖新状态（`useTaskPolling` 等的 AbortSignal/stale 检查，见 [web/Hooks 文档](../modules/web/Hooks.md)）。这是 D4b 加固的一部分。

## 6. 已知并发坑速查表

| 症状 | 根因 | 出处 |
|------|------|------|
| 进度条长时间不动但任务没死 | 阶段内不汇报；看门狗 30 分钟阈值内 | TaskWatchdog |
| LLM 批量"并发"实际串行 | LLMClient 内部互斥 | LLMClient |
| 取消的任务最终显示 completed | cancel 非抢占、完成覆盖 CANCELLED | IngestionJobManager |
| 微信图 invalidate 无效 | 路由每请求新建服务实例，缓存不共享 | WechatGraph |
| JSONB 参数更新丢失 | PostgreSQL JSONB 必须整体重赋值 | server/Services |
| 报告并发生成交叉 | flock 互斥 + staging 目录隔离（已防） | ForensicReportService |

## 相关文档

- [Overview.md](./Overview.md) / [DataFlow.md](./DataFlow.md) —— 系统与任务主线
- [ThreadPool](../modules/cpp/core/ThreadPool.md) / [TaskManager](../modules/cpp/network/TaskManager.md) / [TaskInfrastructure](../modules/cpp/network/TaskInfrastructure.md)
- [ops/PerformanceTuning.md](../ops/PerformanceTuning.md) —— 并发相关调优旋钮

---

**最后更新**: 2026-08-24（新建：并发模型专章）
