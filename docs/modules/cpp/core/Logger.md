# Logger（src/core/Logger/）

> **一句话**：进程级单例的极简同步日志器，提供 DEBUG/INFO/WARNING/ERROR 四级过滤和 STDOUT/FILE/静默三种输出，通过 `LOG_*` 宏被约 30 个源文件、上百处调用点使用——注意它目前在生产路径上从不被配置，实际始终以 INFO 级别打到标准输出。

## 1. 为什么有这个模块

取证分析器是一个多线程长任务进程：镜像解析、平台工件分析、LLM 调用同时跑在 ThreadPool 的 worker 里（见 ThreadPool.md）。没有统一日志时，开发者会各写各的 `std::cout`/`std::cerr`，结果有两个：一是多线程交错输出导致一行日志被撕碎，二是无法事后过滤——出了问题想在生产上只看 ERROR，只能靠肉眼。

Logger 解决的就是这两件最小的事：**一把互斥锁保证行完整性**，**一个级别阈值做运行时过滤**。它刻意不做异步队列、滚动文件、结构化字段——那些重量级需求由另外两个组件分担：业务/审计追溯走 AuditLog（落 SQLite），HTTP API 层有自己的 JSON 响应。Logger 只面向开发者在控制台看执行过程。

模块是零依赖设计（仅标准库，`Logger.h:3-9`），因此它可以被任何层包括最底层的基础模块引用，而不会引入循环依赖——这是它作为"地基"的必要条件。

## 2. 在系统中的位置

Logger 在依赖图的最底层，被全栈使用：`grep` 统计 `LOG_INFO/LOG_DEBUG/LOG_WARNING/LOG_ERROR` 在 `src/` 下有 133 处调用，分布在 DLLAnalyzer、WindowsFilesAnalyzer、OSSAnalyzer、LLMIntegration、HTTPServer 路由等约 29 个文件。它是纯输出端：不读配置、不感知任务，谁都能调 `LOG_INFO(...)`。

一个重要的事实是：**没有任何生产代码调用 `setLevel`/`setOutput`**（全仓库检索仅测试文件调用）。因此单例永远以默认配置运行——级别 INFO、输出 STDOUT（`Logger.h:115-116` 的成员默认值）。换句话说，`.env` 里的 `LOG_LEVEL`、`LOG_FILE`、`DEBUG_OUTPUT_MODE` 虽然有对应的 ConfigManager getter（`src/core/ConfigManager/ConfigManager.cpp:181-183`），但从未被接到 Logger 上；PathManager 提供的 `getLogFilePath()`/`getDebugLogPath()`（`PathManager.cpp:92-98`）也只在系统信息接口里展示（`src/network/HTTPServer/routes/SystemInfoRoutes.cpp:242`），没有真正写日志文件。

## 3. 核心概念与设计

**Meyer's 单例**（`Logger.cpp:5-8`）：函数内 `static Logger instance;`，C++11 起初始化线程安全。所有状态（级别、输出模式、文件流、互斥锁）都在实例里，全局唯一入口是 `Logger::instance()`。

**两级过滤模型**。`log()` 是唯一的写入口（`Logger.cpp:60-75`）：先比级别（DEBUG=0 到 ERROR=3 的整数序，`Logger.h:16-21`），低于 `level_` 直接返回；再看输出模式，`NONE` 直接返回；通过后才格式化并写出。级别比较用 `static_cast<int>` 而非关系符重载，简单且无坑。

**行格式**：`2026-08-23 14:03:21.123 [INFO] message`（`Logger.cpp:102-114`）。毫秒部分单独用 `duration_cast` 取余得到（`Logger.cpp:105-110`），因为 `put_time` 不支持毫秒。注意 `WARNING` 级别输出成 `[WARN]`（`Logger.cpp:120`）——解析日志时不要按完整单词匹配。

**宏与编译期消除**（`Logger.h:126-136`）：

```cpp
#define LOG_DEBUG(msg) ::forensics::Logger::instance().debug(msg)
...
#ifdef NDEBUG
    #define LOG_DEBUG_ONLY(msg) ((void)0)
#else
    #define LOG_DEBUG(msg) LOG_DEBUG(msg)
#endif
```

四个 `LOG_*` 宏只是转调；真正有编译期优化的是 `LOG_DEBUG_ONLY`——release 构建（定义 `NDEBUG`）下整体消失，连字符串构造都不发生。热循环里的高频调试输出应使用它而不是 `LOG_DEBUG`，后者即使被级别过滤掉，msg 字符串（往往是拼接产物）也已经构造完了。

**FILE 模式的失败回退**：`setOutput` 打不开文件时回退 STDOUT 并打一条 stderr 提示（`Logger.cpp:33-41`），保证"日志系统自身失败不拖死进程"。

## 4. 工作流程走读

一次 `LOG_WARNING("low disk: " + path)` 的完整路径：

1. 宏展开为 `Logger::instance().warning(msg)`（`Logger.h:128`），`warning` 转调 `log(LogLevel::WARNING, msg)`（`Logger.cpp:52-54`）。
2. `log()` 拿 `mutex_`（`Logger.cpp:61`），此后整个"过滤 + 格式化 + 写出"都在锁内——行完整性由此保证。
3. 级别检查：WARNING(2) >= INFO(1)，通过（`Logger.cpp:64-66`）；若是 DEBUG 则在此被丢弃。
4. `formatMessage` 生成带时间戳和级别标签的行（`Logger.cpp:73, 102-114`）。
5. `write` 按当前模式输出：STDOUT 走 `std::cout << ... << std::endl`（每次 flush，`Logger.cpp:88-90`）；FILE 模式写入 `ofstream`（`Logger.cpp:91-94`），注意文件模式不会自动 flush，需要调用 `flush()`（`Logger.cpp:77-84`）才落盘。

## 5. 与其他模块的协作

- **ThreadPool 的 worker**：绝大多数调用发生在 worker 线程里，靠 Logger 内部互斥锁保证交错安全；Logger 不区分线程，输出里没有线程 ID——排查并发问题时可配合 AuditLog 的 task 维度。
- **AuditLog**：分工是"Logger 给人看控制台，AuditLog 给系统留证据"。业务关键节点（任务创建、阶段切换、DB 初始化）两边都会写：例如 DatabaseManager 初始化同时打 `std::cout` 和 `AuditLog::instance().log("SYSTEM","DB_INIT",...)`（`DatabaseManager.cpp:49`）。
- **ConfigManager / PathManager**：如第 2 节所述，配置项与路径函数已备好但未接线。如果要让 LOG_LEVEL 生效，应在 `main.cpp` 的启动序列里（`main.cpp:53-74`，PathManager/ConfigManager/AuditLog 初始化的同一段）加 `Logger::instance().setLevel(...)`。
- 出错时行为：写文件失败不抛异常（ofstream 静默置错），最坏情况是日志丢失，进程不受影响——这是刻意的设计取舍。

## 6. 注意事项与已知问题

- **配置未接线是最大的坑**：`.env` 的 `LOG_LEVEL=DEBUG` 不会生效，服务永远只输出 INFO 及以上。需要 DEBUG 时当前只能改代码重新编译，或补上 main.cpp 里的初始化调用。
- **每条日志一次锁 + 一次 endl flush**：STDOUT 模式下高频日志（如分类器逐文件打印）会成为吞吐瓶颈。现有代码里 FileClassifier 的逐文件统计是在循环结束后汇总打印（`FileClassifier.cpp:300-305`），遵守了这一约定。
- FILE 模式无轮转：文件会无限增长，且当前没有生产调用方使用 FILE 模式，属于半成品能力。
- `std::localtime` 非线程安全（`Logger.cpp:109`），但因为整段格式化都在 `mutex_` 内，实际被锁保护住了；如果将来把格式化移出锁，这里要换成 `localtime_r`。

## 7. 如何验证与扩展

- 单元测试：`tests/UnitTest/test_logger.cpp`（`tests/CMakeLists.txt:782-789`，测试名 `LoggerTests`），覆盖级别过滤、输出模式切换等。
- 快速验证：在任一 analyzer 里临时加 `LOG_DEBUG(...)`，默认配置下看不到输出；改 `LOG_INFO` 后可见——这个实验能直观确认"默认 INFO"。
- 扩展建议：(1) 启动时从 ConfigManager 读取 LOG_LEVEL/LOG_FILE 完成接线（改动点在 `main.cpp:53` 之后）；(2) 输出行加线程 ID（`std::this_thread::get_id()`，改 `formatMessage`）；(3) 若需要异步化，参考 AuditLog 的写缓冲 + 后台刷盘线程模式（AuditLog.md 第 3 节），不要直接在 Logger 上加无界队列。

**最后更新**: 2026-08-23（解释式重写）
