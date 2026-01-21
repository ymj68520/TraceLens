# ThreadPool - 线程池组件

## 1. 模块概述 (Overview)

**ThreadPool** 是取证分析平台的高性能并行执行引擎,为整个系统提供简单、高效、线程安全的任务并行化能力。该模块采用C++17标准库实现,基于生产者-消费者模式,通过任务队列和工作线程池实现CPU资源的最大化利用。

该模块虽然代码量不大,但对平台性能至关重要。在文件分析、数据处理、批量操作等计算密集型场景中,ThreadPool能够将任务分配到多个工作线程并行执行,充分利用多核CPU性能,显著提升处理效率。

**核心业务价值:**
- **简化并行编程**:自动管理线程生命周期,开发者无需手动创建和销毁线程
- **提升处理性能**:充分利用多核CPU,并行执行任务,大幅缩短处理时间
- **线程安全设计**:基于互斥锁和条件变量,保证多线程环境下的数据安全
- **优雅资源管理**:析构时自动等待所有任务完成,避免资源泄漏
- **通用任务接口**:支持任意可调用对象,灵活适应各种业务场景

---

## 2. 核心功能列表 (Key Features)

### 2.1 线程池管理

- **自动线程创建**
  - 默认根据硬件并发度(CPU核心数)创建工作线程
  - 支持自定义线程数量,适应不同场景需求
  - 保证至少创建1个工作线程

- **工作线程生命周期**
  - 构造时创建所有工作线程
  - 工作线程阻塞等待任务,避免CPU空转
  - 析构时优雅关闭,等待所有任务完成

### 2.2 任务调度

- **任务队列**
  - 无界队列,支持任意数量的待执行任务
  - FIFO(先进先出)调度策略
  - 线程安全的入队和出队操作

- **负载均衡**
  - 空闲线程自动从队列获取任务
  - 任务分配完全自动,无需手动干预
  - 充分利用所有工作线程

### 2.3 结果返回

- **Future机制**
  - 通过`std::future`返回任务执行结果
  - 支持同步等待(`get()`)和异步查询(`wait_for()`)
  - 异常会在调用`get()`时重新抛出

- **任意返回类型**
  - 支持返回任意类型的值
  - 支持返回`void`(无返回值)
  - 使用`std::invoke_result`自动推断返回类型

### 2.4 状态监控

- **线程数量查询**:获取工作线程数量
- **待处理任务数**:查询队列中待执行的任务数量
- **停止状态**:检查线程池是否已停止接受新任务

### 2.5 线程安全保证

- **互斥锁保护**:任务队列操作完全线程安全
- **条件变量同步**:高效的任务通知和等待机制
- **原子状态标志**:停止标志的原子访问

---

## 3. 业务流程/使用场景 (Use Cases)

### 场景一:批量文件并行分析

**背景**:取证分析需要处理10万个文件,单线程串行处理需要数小时。

**使用方式**:
```cpp
#include "ThreadPool/ThreadPool.h"

void analyzeFiles(const std::vector<std::string>& files) {
    // 创建线程池(使用CPU核心数)
    ThreadPool pool(std::thread::hardware_concurrency());

    // 存储所有任务的future
    std::vector<std::future<AnalysisResult>> futures;

    // 提交所有文件分析任务
    for (const auto& file : files) {
        auto future = pool.enqueue([&file]() {
            return analyzeSingleFile(file);
        });
        futures.push_back(std::move(future));
    }

    // 收集所有结果
    std::vector<AnalysisResult> results;
    for (auto& future : futures) {
        results.push_back(future.get());
    }

    LOG_INFO("Analyzed " + std::to_string(results.size()) + " files");
}
```

**价值体现**:
- 8核CPU上处理时间从数小时缩短到数十分钟
- 线程管理完全自动化,代码简洁清晰
- 异常安全,单个文件分析失败不影响其他文件

---

### 场景二:并行数据库查询

**背景**:需要从数据库查询多个时间范围的数据,每个查询相互独立。

**使用方式**:
```cpp
class DatabaseQueryEngine {
    ThreadPool pool_;

public:
    DatabaseQueryEngine() : pool_(4) {}

    std::vector<QueryResult> queryMultipleTimeRanges(
        const std::vector<TimeRange>& ranges
    ) {
        std::vector<std::future<QueryResult>> futures;

        for (const auto& range : ranges) {
            auto future = pool_.enqueue([this, range]() {
                return executeQuery(range);
            });
            futures.push_back(std::move(future));
        }

        std::vector<QueryResult> results;
        for (auto& future : futures) {
            results.push_back(future.get());
        }

        return results;
    }
};
```

**价值体现**:
- 多个数据库查询并行执行,大幅提升响应速度
- 线程池复用,避免频繁创建销毁线程
- 资源控制,限制并发查询数量

---

### 场景三:并行图像视觉分析

**背景**:对大量图像进行OCR和视觉识别,单张图像处理耗时较长。

**使用方式**:
```cpp
class ImageAnalysisService {
    ThreadPool pool_;

public:
    ImageAnalysisService() : pool_(8) {}  // 图像分析用更多线程

    std::vector<VisionResult> analyzeImages(
        const std::vector<std::string>& imagePaths
    ) {
        std::vector<std::future<VisionResult>> futures;

        // 批量提交图像分析任务
        for (const auto& path : imagePaths) {
            auto future = pool_.enqueue([this, path]() {
                try {
                    return visionAnalyzer_.analyze(path);
                } catch (const std::exception& e) {
                    LOG_ERROR("Failed to analyze " + path + ": " + e.what());
                    return VisionResult{};  // 返回空结果
                }
            });
            futures.push_back(std::move(future));
        }

        // 等待所有任务完成并收集结果
        std::vector<VisionResult> results;
        for (auto& future : futures) {
            results.push_back(future.get());
        }

        return results;
    }

    // 监控任务进度
    size_t getPendingTasks() const {
        return pool_.pendingTasks();
    }
};
```

**价值体现**:
- I/O密集型任务受益于更多工作线程
- 异常隔离,单张图像失败不影响其他图像
- 支持进度监控,用户体验更好

---

## 4. 部署与配置要求 (Deployment & Configuration)

### 环境依赖

**编译器要求**:
- GCC 9.0+ 或 Clang 10.0+
- 支持 C++17 标准
- 链接选项:`-lstdc++ -lpthread`

**系统要求**:
- 多核CPU以充分发挥并行优势
- 足够的内存支持多线程并发执行

### 线程池大小配置建议

**CPU密集型任务** (如数据加密、哈希计算):
```cpp
// 设置为核心数或核心数+1
ThreadPool pool(std::thread::hardware_concurrency());
// 8核CPU → 8个工作线程
```

**I/O密集型任务** (如文件读写、网络请求、数据库查询):
```cpp
// 设置为核心数的2-3倍
ThreadPool pool(std::thread::hardware_concurrency() * 2);
// 8核CPU → 16个工作线程
```

**混合型任务** (如文件分析包含读取和处理):
```cpp
// 根据实际情况调整,通常1.5-2倍核心数
ThreadPool pool(std::thread::hardware_concurrency() * 1.5);
// 8核CPU → 12个工作线程
```

**保守配置** (低内存环境):
```cpp
// 限制线程数量,避免资源耗尽
ThreadPool pool(4);  // 固定4个工作线程
```

### 最佳实践

**1. 合理设置线程池大小**
```cpp
// 不好:线程过多导致上下文切换开销
ThreadPool pool(100);

// 好:根据任务类型和CPU核心数设置
ThreadPool pool(std::thread::hardware_concurrency() * 2);
```

**2. 处理任务异常**
```cpp
auto future = pool.enqueue([]() {
    // 可能抛出异常的任务
    return riskyOperation();
});

try {
    auto result = future.get();
} catch (const std::exception& e) {
    LOG_ERROR("Task failed: " + std::string(e.what()));
}
```

**3. 避免长时间阻塞任务**
```cpp
// 不好:阻塞工作线程
auto future = pool.enqueue([]() {
    while (true) {  // 死循环阻塞线程
        // ...
    }
});

// 好:使用异步I/O或定时任务
auto future = pool.enqueue([]() {
    return performAsyncOperation();
});
```

**4. 监控任务队列**
```cpp
ThreadPool pool(8);

// 提交任务前检查队列长度
if (pool.pendingTasks() < 100) {
    pool.enqueue(task);
} else {
    // 队列过长,延迟提交或拒绝
    LOG_WARNING("Task queue too long, throttling");
}
```

---

## 5. 接口与集成说明 (API & Integration)

### 核心接口

**构造函数**:
```cpp
explicit ThreadPool(size_t threads = std::thread::hardware_concurrency());
```
- `threads`: 工作线程数量,默认为硬件并发度(CPU核心数)
- 如果传入0,自动设置为1

**提交任务**:
```cpp
template<class F, class... Args>
auto enqueue(F&& f, Args&&... args)
    -> std::future<typename std::invoke_result<F, Args...>::type>;
```
- `f`: 可调用对象(函数、lambda、成员函数等)
- `args`: 参数列表
- 返回:`std::future<ReturnType>`,用于获取任务结果
- 注意:如果线程池已停止,抛出`std::runtime_error`

**状态查询**:
```cpp
size_t size() const;           // 获取工作线程数量
size_t pendingTasks() const;   // 获取队列中待处理的任务数
bool isStopped() const;        // 检查线程池是否已停止
```

### 使用示例

**基本用法**:
```cpp
#include "ThreadPool/ThreadPool.h"

void example() {
    // 1. 创建线程池
    ThreadPool pool(4);

    // 2. 提交无返回值任务
    pool.enqueue([]() {
        LOG_INFO("Task 1 executing");
    });

    // 3. 提交有返回值任务
    auto future = pool.enqueue([](int x, int y) {
        return x + y;
    }, 10, 20);

    // 4. 获取结果
    int result = future.get();  // 30
    LOG_INFO("Result: " + std::to_string(result));

    // 5. 查询状态
    LOG_INFO("Thread count: " + std::to_string(pool.size()));
    LOG_INFO("Pending tasks: " + std::to_string(pool.pendingTasks()));
}
```

**提交成员函数**:
```cpp
class Database {
public:
    std::vector<File> query(const std::string& sql);
};

void example() {
    ThreadPool pool(4);
    Database db;

    // 使用 std::bind
    auto future1 = pool.enqueue(
        std::bind(&Database::query, &db, "SELECT * FROM files")
    );

    // 使用 lambda
    auto future2 = pool.enqueue([&db]() {
        return db.query("SELECT * FROM events");
    });

    auto files1 = future1.get();
    auto files2 = future2.get();
}
```

**批量任务处理**:
```cpp
void processBatch(const std::vector<std::string>& items) {
    ThreadPool pool(8);
    std::vector<std::future<Result>> futures;

    for (const auto& item : items) {
        futures.push_back(pool.enqueue([&item]() {
            return processItem(item);
        }));
    }

    // 等待所有任务完成
    for (auto& future : futures) {
        future.wait();
    }

    // 或收集结果
    std::vector<Result> results;
    for (auto& future : futures) {
        results.push_back(future.get());
    }
}
```

**异常处理**:
```cpp
void exampleWithErrorHandling() {
    ThreadPool pool(4);

    auto future = pool.enqueue([]() -> int {
        if (errorCondition) {
            throw std::runtime_error("Task failed");
        }
        return 42;
    });

    try {
        int result = future.get();
        LOG_INFO("Result: " + std::to_string(result));
    } catch (const std::runtime_error& e) {
        LOG_ERROR("Task error: " + std::string(e.what()));
    }
}
```

### 集成到现有模块

**在HTTP服务中使用**:
```cpp
class HTTPServer {
    ThreadPool requestPool_;

public:
    HTTPServer() : requestPool_(16) {}

    void handleRequest(const Request& req) {
        // 异步处理请求
        requestPool_.enqueue([this, req]() {
            auto response = processRequest(req);
            sendResponse(req.connId, response);
        });
    }
};
```

**在数据库操作中使用**:
```cpp
class DatabaseManager {
    ThreadPool ioPool_;

public:
    DatabaseManager() : ioPool_(4) {}

    std::future<std::vector<File>> queryFilesAsync(const std::string& condition) {
        return ioPool_.enqueue([this, condition]() {
            return queryFiles(condition);
        });
    }
};
```

---

## 6. 常见问题 (FAQ)

**Q1:ThreadPool和直接创建std::thread有什么区别?**

A:线程池的优势:

| 特性 | ThreadPool | 直接创建std::thread |
|------|-----------|-------------------|
| **性能** | 线程复用,避免创建销毁开销 | 每次创建新线程,开销大 |
| **资源控制** | 限制并发数量,避免资源耗尽 | 容易创建过多线程 |
| **代码复杂度** | 简单,自动管理 | 复杂,手动join和异常处理 |
| **任务队列** | 内置队列,自动调度 | 需要自己实现 |
| **结果返回** | 通过future方便获取 | 需要手动同步 |

**使用建议**:
- 短期任务(一次性) → `std::thread`
- 长期运行、频繁提交任务 → `ThreadPool`

---

**Q2:如何确定最优的线程池大小?**

A:根据任务类型和系统资源:

**公式参考**:
- **CPU密集型**: `线程数 = CPU核心数 + 1`
- **I/O密集型**: `线程数 = CPU核心数 × (1 + I/O等待时间/CPU时间)`
- **混合型**: 通过性能测试确定

**测试方法**:
```cpp
// 测试不同线程池大小的性能
for (size_t threads = 1; threads <= 16; threads *= 2) {
    ThreadPool pool(threads);
    auto start = std::chrono::high_resolution_clock::now();

    // 执行相同任务
    runTasks(pool);

    auto end = std::chrono::high_resolution_clock::now();
    auto duration = std::chrono::duration_cast<std::chrono::milliseconds>(end - start);
    LOG_INFO("Threads: " + std::to_string(threads) + ", Time: " + std::to_string(duration.count()) + "ms");
}
```

**注意事项**:
- 线程数过多会导致上下文切换开销
- 线程数过少无法充分利用CPU
- 考虑系统内存限制(每个线程约占用8MB栈空间)

---

**Q3:任务执行顺序是否保证?**

A:不保证顺序。ThreadPool的特点:

**FIFO提交,不保证执行顺序**:
- 任务按提交顺序进入队列
- 但多个线程竞争获取任务
- 执行顺序取决于线程调度和任务执行时间

**如果需要顺序执行**:
```cpp
// 方案1:串行提交并等待
std::vector<Result> results;
for (const auto& item : items) {
    auto future = pool.enqueue([&item]() { return process(item); });
    results.push_back(future.get());  // 等待完成
}

// 方案2:使用有序容器
std::map<int, std::future<Result>> orderedFutures;
for (size_t i = 0; i < items.size(); i++) {
    orderedFutures[i] = pool.enqueue([&items, i]() { return process(items[i]); });
}

// 按顺序获取结果
for (auto& [index, future] : orderedFutures) {
    results[index] = future.get();
}
```

---

**Q4:如何优雅地关闭线程池?**

A:ThreadPool析构时自动优雅关闭:

**自动关闭**:
```cpp
{
    ThreadPool pool(4);
    pool.enqueue(task1);
    pool.enqueue(task2);
}  // 离开作用域,自动等待所有任务完成
```

**手动控制时机**:
```cpp
class Service {
    std::unique_ptr<ThreadPool> pool_;

public:
    void start() {
        pool_ = std::make_unique<ThreadPool>(8);
    }

    void shutdown() {
        // 显式销毁线程池,等待任务完成
        pool_.reset();
        LOG_INFO("Thread pool shutdown complete");
    }
};
```

**注意事项**:
- 析构函数会阻塞等待所有任务完成
- 确保任务不会死循环,否则无法关闭
- 析构后不能再提交新任务

---

**Q5:ThreadPool能否用于嵌套并行(任务内再提交任务)?**

A:技术上可以,但需要谨慎:

**死锁风险**:
```cpp
ThreadPool pool(2);

// 危险:可能死锁
pool.enqueue([&pool]() {
    // 外部任务占用1个线程
    auto future = pool.enqueue([]() {
        // 内部任务等待2个线程,但只剩1个空闲
        // 如果所有外部线程都等待内部任务,死锁
    });
    future.get();  // 等待内部任务
});
```

**避免死锁的方法**:
```cpp
// 方案1:使用更大的线程池
ThreadPool pool(16);  // 足够的线程

// 方案2:内部任务使用独立线程池
ThreadPool outerPool(4);
ThreadPool innerPool(8);

outerPoolenqueue([&innerPool]() {
    auto future = innerPool.enqueue([]() {
        // 使用不同的线程池,避免竞争
    });
    future.get();
});

// 方案3:避免嵌套,改为批量提交
std::vector<std::future<Result>> futures;
for (int i = 0; i < 10; i++) {
    futures.push_back(pool.enqueue(task));
}
for (auto& f : futures) f.get();
```

---

**Q6:如何监控线程池的运行状态?**

A:使用状态查询接口:

**实时监控**:
```cpp
class ThreadPoolMonitor {
    ThreadPool& pool_;
    std::thread monitorThread_;

public:
    ThreadPoolMonitor(ThreadPool& pool) : pool_(pool) {
        monitorThread_ = std::thread([this]() {
            while (!pool_.isStopped()) {
                size_t pending = pool_.pendingTasks();
                size_t threads = pool_.size();

                LOG_INFO("Pool status - Threads: " + std::to_string(threads) +
                        ", Pending: " + std::to_string(pending));

                std::this_thread::sleep_for(std::chrono::seconds(5));
            }
        });
    }

    ~ThreadPoolMonitor() {
        if (monitorThread_.joinable()) {
            monitorThread_.join();
        }
    }
};
```

**性能统计**:
```cpp
class InstrumentedThreadPool : public ThreadPool {
    std::atomic<uint64_t> tasksSubmitted_{0};
    std::atomic<uint64_t> tasksCompleted_{0};

public:
    template<class F, class... Args>
    auto enqueue(F&& f, Args&&... args) {
        tasksSubmitted_++;
        auto future = ThreadPool::enqueue(std::forward<F>(f), std::forward<Args>(args)...);

        // 包装任务以完成计数
        return std::async(std::launch::deferred, [this, future = std::move(future)]() mutable {
            auto result = future.get();
            tasksCompleted_++;
            return result;
        });
    }

    double getProgress() const {
        if (tasksSubmitted_ == 0) return 1.0;
        return static_cast<double>(tasksCompleted_) / tasksSubmitted_;
    }
};
```

---