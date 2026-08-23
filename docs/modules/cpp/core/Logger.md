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

**宏与编译期消除**（`Logger.h:126-136`）：四个 `LOG_*` 宏只是转调；真正有编译期优化的是 `LOG_DEBUG_ONLY`——release 构建（定义 `NDEBUG`）下整体消失，连字符串构造都不发生。热循环里的高频调试输出应使用它而不是 `LOG_DEBUG`，后者即使被级别过滤掉，msg 字符串（往往是拼接产物）也已经构造完了。

**FILE 模式的失败回退**：`setOutput` 打不开文件时回退 STDOUT 并打一条 stderr 提示（`Logger.cpp:33-41`），保证"日志系统自身失败不拖死进程"。

### 3.1 核心数据结构（Logger.h:16-30, 115-119）

```cpp
enum class LogLevel {
    DEBUG = 0,
    INFO = 1,
    WARNING = 2,
    ERROR = 3
};

enum class LogOutput {
    STDOUT,   // Output to console
    FILE,     // Output to file
    NONE      // No output (silent)
};

// class Logger 私有状态（Logger.h:115-119）：
    LogLevel level_ = LogLevel::INFO;
    LogOutput output_ = LogOutput::STDOUT;
    std::string filePath_;
    std::ofstream file_;
    mutable std::mutex mutex_;
```

- `LogLevel`：枚举值即过滤阈值序数，`log()` 里 `static_cast<int>(level) < static_cast<int>(level_)` 一行完成比较；`INFO=1` 是"调试之上皆可见"的默认档。
- `LogOutput`：三态输出目标。`NONE` 不是"错误"而是**显式静默**——压测或生产降噪时可切到它，`log()` 在 `:69-71` 早退，连格式化都不做。
- 成员默认值（`:115-116`）就是"当前生产实际行为"的来源：没有任何调用方改它，所以永远是 INFO+STDOUT。`file_` 只在 FILE 模式下有意义；`mutex_` 声明为 `mutable`，因为 `getLevel()/getOutput()` 是 const 方法但内部不加锁（见第 6 节）。

### 3.2 核心接口清单

| 签名（Logger.h） | 语义 | 主要调用方 | 失败行为 |
|---|---|---|---|
| `static Logger& instance()` | 取单例（首次调用构造） | 所有 `LOG_*` 宏展开点 | 不会失败 |
| `void setLevel(LogLevel)` | 设最低可见级别（持锁写 `level_`） | 仅测试代码（生产未接线） | 无 |
| `void setOutput(LogOutput, filePath="debug.log")` | 切输出模式；FILE 时以 append 打开文件 | 仅测试代码 | 打不开文件回退 STDOUT + stderr 提示（`Logger.cpp:35-40`） |
| `void debug/info/warning/error(const std::string&)` | 四级便捷入口，转调 `log()` | `LOG_*` 宏（133 处） | 无返回值，静默 |
| `void log(LogLevel, const std::string&)` | 通用写入口：过滤+格式化+写出 | 四个便捷方法 | 无 |
| `void flush()` | FILE 模式刷 ofstream；STDOUT 刷 cout | 需要即时落盘的调用方（当前无人调用） | 无 |
| `LogLevel getLevel() const` / `LogOutput getOutput() const` | 读当前配置（无锁） | 诊断用途 | 无 |

宏层（`Logger.h:126-136`）：`LOG_DEBUG/LOG_INFO/LOG_WARNING/LOG_ERROR` 全部展开为 `::forensics::Logger::instance().<level>(msg)`；`LOG_DEBUG_ONLY` 在 `NDEBUG` 下展开为 `((void)0)`。

## 4. 工作流程走读

一次 `LOG_WARNING("low disk: " + path)` 的完整路径：

1. 宏展开为 `Logger::instance().warning(msg)`（`Logger.h:128`），`warning` 转调 `log(LogLevel::WARNING, msg)`（`Logger.cpp:52-54`）。
2. `log()` 拿 `mutex_`（`Logger.cpp:61`），此后整个"过滤 + 格式化 + 写出"都在锁内——行完整性由此保证。
3. 级别检查：WARNING(2) >= INFO(1)，通过（`Logger.cpp:64-66`）；若是 DEBUG 则在此被丢弃。
4. `formatMessage` 生成带时间戳和级别标签的行（`Logger.cpp:73, 102-114`）。
5. `write` 按当前模式输出：STDOUT 走 `std::cout << ... << std::endl`（每次 flush，`Logger.cpp:88-90`）；FILE 模式写入 `ofstream`（`Logger.cpp:91-94`），注意文件模式不会自动 flush，需要调用 `flush()`（`Logger.cpp:77-84`）才落盘。

### 4.1 代码走读：log() 的两级早退（Logger.cpp:60-75）

```cpp
void Logger::log(LogLevel level, const std::string& msg) {
    std::lock_guard<std::mutex> lock(mutex_);
    
    // Check log level
    if (static_cast<int>(level) < static_cast<int>(level_)) {
        return;
    }
    
    // Check output mode
    if (output_ == LogOutput::NONE) {
        return;
    }
    
    std::string formatted = formatMessage(level, msg);
    write(formatted);
}
```

逐块解释：这是全模块最热的一条路径（133 个调用点都汇到这里），写法上每一步都在为"尽快返回"服务——先锁（行完整性是硬需求，无法省），锁内第一件事就是级别比较，被过滤的消息只付出一次锁获取 + 一次整数比较的代价；第二道闸门挡住静默模式。**过滤在格式化之前**，所以被过滤的消息不产生 `ostringstream`、不做 `localtime`、不拼字符串——但要注意调用方那侧 `"a" + var` 的 msg 构造已经发生（这正是 `LOG_DEBUG_ONLY` 存在的原因）。锁覆盖 formatMessage 顺带保护了 `std::localtime` 这个静态缓冲区函数（见第 6 节）。

### 4.2 代码走读：formatMessage 的毫秒拼接（Logger.cpp:102-114）

```cpp
std::string Logger::formatMessage(LogLevel level, const std::string& msg) {
    auto now = std::chrono::system_clock::now();
    auto time = std::chrono::system_clock::to_time_t(now);
    auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        now.time_since_epoch()) % 1000;
    
    std::ostringstream oss;
    oss << std::put_time(std::localtime(&time), "%Y-%m-%d %H:%M:%S");
    oss << '.' << std::setfill('0') << std::setw(3) << ms.count();
    oss << " [" << levelToString(level) << "] " << msg;
    
    return oss.str();
}
```

逐块解释：`put_time` 只能格式化到秒，毫秒因此独立计算——对 epoch 毫秒数取模 1000 得到秒内余量，再用 `setfill('0')/setw(3)` 补零，保证 `...:21.007` 而不是 `...:21.7`（宽度不足时右对齐补零是这里唯一正确的写法）。时间源是墙钟 `system_clock`：回调系统时间会使日志时间倒跳，做性能分析时应改用 AuditLog 的 id 序或单调钟。`localtime` 返回静态缓冲区指针，线程不安全，靠外层 `mutex_` 兜底——这是一个"锁保护第三方非重入函数"的隐式契约，重构时把格式化移出锁就会引入数据竞争。

### 4.3 代码走读：setOutput 的失败回退（Logger.cpp:21-42）

```cpp
void Logger::setOutput(LogOutput output, const std::string& filePath) {
    std::lock_guard<std::mutex> lock(mutex_);
    
    // Close existing file if open
    if (file_.is_open()) {
        file_.close();
    }
    
    output_ = output;
    filePath_ = filePath;
    
    // Open new file if FILE mode
    if (output_ == LogOutput::FILE && !filePath_.empty()) {
        file_.open(filePath_, std::ios::app);
        if (!file_.is_open()) {
            // Fallback to stdout if file open fails
            output_ = LogOutput::STDOUT;
            std::cerr << "[Logger] Failed to open log file: " << filePath_ 
                      << ", falling back to stdout" << std::endl;
        }
    }
}
```

逐块解释：切换是"先关旧再开新"的顺序，FILE→FILE 切换会关闭上一个文件句柄——若 open 新文件失败，`output_` 已被改写为 STDOUT，日志不至于写进已关闭的流。`std::ios::app` 意味着追加而非截断，重复启动不会清掉历史日志（也因此没有轮转，文件无限增长）。错误提示走 `std::cerr` 而非 Logger 自身——日志器报告自己的失败不能递归调用自己。整个函数持锁执行 open（磁盘操作），运行期频繁切换输出会阻塞写日志的线程；当前无生产调用方，实际无影响。

## 5. 与其他模块的协作

- **ThreadPool 的 worker**：绝大多数调用发生在 worker 线程里，靠 Logger 内部互斥锁保证交错安全；Logger 不区分线程，输出里没有线程 ID——排查并发问题时可配合 AuditLog 的 task 维度。
- **AuditLog**：分工是"Logger 给人看控制台，AuditLog 给系统留证据"。业务关键节点（任务创建、阶段切换、DB 初始化）两边都会写：例如 DatabaseManager 初始化同时打 `std::cout` 和 `AuditLog::instance().log("SYSTEM","DB_INIT",...)`（`DatabaseManager.cpp:49`）。
- **ConfigManager / PathManager**：如第 2 节所述，配置项与路径函数已备好但未接线。相关 .env 键及其 getter 默认值：`LOG_LEVEL`（getLogLevel，默认 `"INFO"`）、`LOG_FILE`（getLogFile，默认 `"forensics.log"`）、`DEBUG_OUTPUT_MODE`（getDebugOutputMode，默认 `"stdout"`）——三个 getter 返回字符串，接到 Logger 还需做 `LogLevel`/`LogOutput` 的映射转换。如果要让 LOG_LEVEL 生效，应在 `main.cpp` 的启动序列里（`main.cpp:53-74`，PathManager/ConfigManager/AuditLog 初始化的同一段）加 `Logger::instance().setLevel(...)`。
- 出错时行为：写文件失败不抛异常（ofstream 静默置错），最坏情况是日志丢失，进程不受影响——这是刻意的设计取舍。

## 6. 注意事项与已知问题

- **配置未接线是最大的坑**：`.env` 的 `LOG_LEVEL=DEBUG` 不会生效，服务永远只输出 INFO 及以上。需要 DEBUG 时当前只能改代码重新编译，或补上 main.cpp 里的初始化调用。
- **每条日志一次锁 + 一次 endl flush**：STDOUT 模式下高频日志（如分类器逐文件打印）会成为吞吐瓶颈。现有代码里 FileClassifier 的逐文件统计是在循环结束后汇总打印（`FileClassifier.cpp:300-305`），遵守了这一约定。
- FILE 模式无轮转：文件会无限增长，且当前没有生产调用方使用 FILE 模式，属于半成品能力。
- `std::localtime` 非线程安全（`Logger.cpp:109`），但因为整段格式化都在 `mutex_` 内，实际被锁保护住了；如果将来把格式化移出锁，这里要换成 `localtime_r`。
- **读接口无锁**：`getLevel()/getOutput()`（`Logger.h:59,71`）直接返回成员，若与并发 `setLevel` 交错，读到的新旧值取决于时序——诊断用途可容忍，不能当作同步原语。
- **msg 是 const 引用**：`"x" + std::string` 的临时串在调用前已构造，级别过滤救不了这层开销；热路径请用 `LOG_DEBUG_ONLY` 或条件判断包裹。

## 7. 如何验证与扩展

- 单元测试：`tests/UnitTest/test_logger.cpp`（`tests/CMakeLists.txt:782-789`，测试名 `LoggerTests`），覆盖级别过滤、输出模式切换等。
- 快速验证：在任一 analyzer 里临时加 `LOG_DEBUG(...)`，默认配置下看不到输出；改 `LOG_INFO` 后可见——这个实验能直观确认"默认 INFO"。再验证格式：`grep -E '\[WARN\]'` 能命中 WARNING 行，`[WARNING]` 永远命中不了。
- 扩展建议：(1) 启动时从 ConfigManager 读取 LOG_LEVEL/LOG_FILE 完成接线（改动点在 `main.cpp:53` 之后）；(2) 输出行加线程 ID（`std::this_thread::get_id()`，改 `formatMessage`）；(3) 若需要异步化，参考 AuditLog 的写缓冲 + 后台刷盘线程模式（AuditLog.md 第 3 节），不要直接在 Logger 上加无界队列。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
