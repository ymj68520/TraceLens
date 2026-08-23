# ErrorHandling（src/core/ErrorHandling/ErrorHandling.h）

> **一句话**：一个只有头文件的错误处理工具箱，定义了分段编号的 `ErrorCode` 枚举和 `Result<T>` 值-或-错误返回类型——注意它目前只被自己的单元测试引用，各分析器实际使用的是各自独立的错误定义（详见第 6 节）。

## 1. 为什么有这个模块

C++ 没有语言级的"可失败返回值"（C++23 才有 `std::expected`），项目面对两个原始选择：返回 bool 加出参（丢失"为什么失败"），或到处抛异常（跨线程、跨 SQLite C API 边界时传播路径混乱，且取证流程里"某一步失败、其余步骤继续"是常态而非例外）。`Result<T>` 的目标是把错误变成**值**：一个要么装着结果、要么装着错误码和消息的对象，调用方必须显式检查才能取值。

`ErrorCode` 枚举解决的是另一半问题：错误码的语义分段。散落的 magic number（"返回 -3 是什么意思？"）在跨模块调试时无法沟通；按百位分段（1xx 文件、2xx LLM……）后，看到码就知道该去哪个子系统查。

## 2. 在系统中的位置

这是**设计上的公共地基、现实中的孤岛**。全仓库检索显示，`src/core/ErrorHandling/ErrorHandling.h` 唯一的 include 者是它自己的单元测试 `tests/UnitTest/test_error_handling.cpp:4`。生产代码中不存在消费者。

与它平行存在两套"局部错误体系"：

- `src/analyzers/LinuxFilesAnalyzer/Common/LinuxAnalyzerErrors.h`——LinuxFilesAnalyzer 自带的 `LinuxAnalysis::ErrorCode` 枚举和独立的 `Result<T>`/`Result<void>`（该文件 :297-410），机制几乎相同但命名空间独立；
- 其余模块基本沿用 bool 返回 + `std::cerr` 日志（如 DatabaseManager、EventExtractor）。

因此准确地说：ErrorHandling 定义的是**全项目期望统一到的目标规范**，新代码应当使用它，而不是再复制第四套。理解它的设计仍然是必要的——LinuxAnalyzerErrors.h 就是它的翻版。

## 3. 核心概念与设计

**错误码分段**（`ErrorHandling.h:12-58`）。段边界即排障指引：

| 区间 | 语义 | 典型值 |
|---|---|---|
| 0 | 成功 | `Success` |
| 100-199 | 文件错误 | `FileNotFound`、`FileReadError`、`InvalidFilePath` |
| 200-299 | LLM 错误 | `LLMConnectionFailed`、`LLMTimeout`、`LLMRateLimited`、`LLMContextOverflow` |
| 300-399 | 模型错误 | `NoModelsAvailable`、`AllModelsFailed` |
| 400-499 | 配置错误 | `ConfigNotLoaded`、`MissingConfigKey` |
| 500-599 | 数据库错误 | `DatabaseOpenError`、`DatabaseQueryError` |
| 600-699 | 分析错误 | `ContentTooLarge`、`ChunkingFailed` |
| 900-999 | 通用错误 | `InternalError`、`Cancelled` |

（表只列代表性值；完整定义见源文件。）`errorCodeToString`（`ErrorHandling.h:63-98`）为每个码提供人类可读描述，`Result::error` 在调用方没给自定义消息时用它兜底——保证错误永远"有话说"。

**Result<T> 的三态纪律**。私有成员是 `std::optional<T> value_` + `bool success_` + 码/消息（`ErrorHandling.h:188-194`），只能通过两个静态工厂构造：`success(value)` 或 `error(code, msg)`（`ErrorHandling.h:124-141`），不存在"成功但没值"或"失败但带值"的非法态。取值接口分层：

- `value()`：错误态下取值直接 `throw std::runtime_error`（`ErrorHandling.h:152-164`）——这是给"已检查过还想偷懒"的场景兜底的雷，宁可在开发期炸出来也不返回垃圾值；
- `valueOr(default)`：安全取值；
- `operator bool` / `isSuccess()`：惯用的检查入口（`ErrorHandling.h:146-147, 186`）。

**Result\<void\> 特化**（`ErrorHandling.h:200-232`）：无值操作（如"执行一次迁移"）同样需要错误通道，特化版去掉 value 相关接口，保留错误语义。

### 3.1 核心数据结构：ErrorCode 枚举全文（ErrorHandling.h:12-58）

```cpp
enum class ErrorCode {
    Success = 0,

    // File errors (100-199)
    FileNotFound = 100,
    FileReadError = 101,
    FileWriteError = 102,
    FileAccessDenied = 103,
    InvalidFilePath = 104,
    FileEmpty = 105,

    // LLM errors (200-299)
    LLMConnectionFailed = 200,
    // ... LLMRequestFailed/ResponseParseError/Timeout/RateLimited/ContextOverflow(201-205)

    // Model errors (300-399)
    NoModelsAvailable = 300,
    // ... ModelNotFound/AllModelsFailed(301-302)

    // Configuration errors (400-499)
    InvalidConfiguration = 400,
    // ... ConfigNotLoaded/MissingConfigKey(401-402)

    // Database errors (500-599)
    DatabaseOpenError = 500,
    // ... DatabaseQueryError/WriteError/NotInitialized(501-503)

    // Analysis errors (600-699)
    AnalysisFailed = 600,
    // ... ContentTooLarge/UnsupportedFileType/ChunkingFailed(601-603)

    // General errors (900-999)
    Unknown = 900,
    InternalError = 901,
    NotImplemented = 902,
    Cancelled = 903
};
```

分组语义与设计意图：`enum class` 保证码不会隐式转成 int 混用（比较必须写全 `ErrorCode::X`）；每个分段留了几十个空号，新增码不必重排旧值——**错误码是会被日志和数据库长期留存的，重排等于篡改历史语义**。三组值得注意的细分：文件段区分"读/写/拒绝访问"（100 段的 102/103），因为取证场景下权限问题（镜像只读挂载）和真实 IO 故障的处置完全不同；LLM 段的 `LLMContextOverflow`(205) 是**可预测**的错误（内容长度可先量出来），调用方可以在发送前自查规避；`Cancelled`(903) 独立于失败——任务被用户取消时不应计入错误统计，TaskManager 的取消路径靠这类码区分。

### 3.2 Result<T> 的内部表示（ErrorHandling.h:118-195）

```cpp
template<typename T>
class Result {
public:
    // ... 工厂/取值接口见 3.3
private:
    Result() = default;

    std::optional<T> value_;
    ErrorCode errorCode_ = ErrorCode::Unknown;
    std::string errorMessage_;
    bool success_ = false;
};
```

私有构造 + 静态工厂是三态纪律的实现手段：外部**无法**构造出 `success_ = true` 但 `value_` 为空的实例（工厂里两步赋值顺序保证）。冗余是刻意的一份——理论上 `value_.has_value()` 就能判断成败，独立 `success_` 让 `Result<void>` 特化能复用同一套字段形状，也让检查路径（热操作）完全绕开 optional。`errorCode_` 默认 `Unknown` 而非 `Success`：默认构造的中间态被视为"未成功"，宁可错报失败也不错报成功。对比 LinuxAnalyzerErrors.h 的实现用 `std::variant<T, LinuxAnalyzerError>` 存储（该文件 :326），类型安全更强但 `holds_alternative` 检查略贵——两种实现是同一设计的两种权衡。

### 3.3 核心接口清单

| 签名（ErrorHandling.h） | 语义 | 备注 |
|---|---|---|
| `static Result<T> success(T value)` | 构造成功态（move 入 optional） | 私有构造器保证只有此路 |
| `static Result error(ErrorCode, msg="")` | 构造错误态；空消息用 errorCodeToString 兜底 | 消息永远非空 |
| `bool isSuccess() / isError() const` | 显式检查 | isError 即 !isSuccess |
| `const T& value() const / T& value()` | 取值；错误态抛 `std::runtime_error` | 非 noexcept |
| `T valueOr(T defaultValue) const` | 安全取值，失败返回默认 | noexcept 场景的选择 |
| `ErrorCode errorCode() const` | 取错误码（成功态为 Success） | 分段策略判断的依据 |
| `const std::string& errorMessage() const` | 取错误消息 | 成功态为空串 |
| `explicit operator bool() const` | `if (result)` 惯用检查 | explicit 防止意外数值转换 |
| `inline const char* errorCodeToString(ErrorCode)` | 码→描述的自由函数 | default 分支返回 "Unknown error code" |
| `Result<void>` 特化（:200-232） | 无值操作的错误通道 | 无 value/valueOr，其余同形 |

## 4. 工作流程走读

以源码注释中的除法示例（`ErrorHandling.h:104-116`）走一遍完整生命周期：

```cpp
Result<int> divide(int a, int b) {
    if (b == 0) return Result<int>::error(ErrorCode::InternalError, "Division by zero");
    return Result<int>::success(a / b);
}

auto result = divide(10, 2);
if (result.isSuccess()) {
    std::cout << result.value() << std::endl;   // 5
} else {
    std::cerr << result.errorMessage() << std::endl;
}
```

`divide` 是"构造即分类"的写法：两个 return 各对应一种终态，没有中间状态。调用方先 `isSuccess()` 分流，成功路径才碰 `value()`。若调用方忘了检查直接 `value()`，错误态下立即抛异常暴露误用（而不是默默读到未定义值）。错误链传播时，上层可以拿 `errorCode()` 决定策略（重试 2xx 的超时、放弃 4xx 的配置错），拿 `errorMessage()` 记入日志或 AuditLog。

### 4.1 代码走读：两个静态工厂（ErrorHandling.h:124-141）

```cpp
    static Result success(T value) {
        Result r;
        r.value_ = std::move(value);
        r.success_ = true;
        r.errorCode_ = ErrorCode::Success;
        return r;
    }

    static Result error(ErrorCode code, const std::string& message = "") {
        Result r;
        r.success_ = false;
        r.errorCode_ = code;
        r.errorMessage_ = message.empty() ? errorCodeToString(code) : message;
        return r;
    }
```

逐块解释：`success` 先 move 值再翻 `success_` 标志——顺序无关紧要但一行不多余；注意成功态的 `errorMessage_` 保持默认空串，所以"成功但有警告"这种信息**没有通道**，只能靠调用方另行记日志。`error` 工厂的关键在最后一行三元：消息参数为空时回填 `errorCodeToString(code)`，这保证 `errorMessage()` 永不为空——下游格式化 `"错误: " + msg` 时不会产出裸前缀。两个工厂都返回值类型（RVO 拷贝消除），`Result` 整体可自由拷贝移动，跨线程/跨 future 传递无额外约束。

### 4.2 代码走读：value() 的雷区设计（ErrorHandling.h:152-171）

```cpp
    const T& value() const {
        if (!success_) {
            throw std::runtime_error("Attempted to access value of error result: " + errorMessage_);
        }
        return *value_;
    }

    // ... 非 const 重载同构（:159-164）

    T valueOr(T defaultValue) const {
        return success_ ? *value_ : std::move(defaultValue);
    }
```

逐块解释：`value()` 的抛异常不是缺陷而是**故障保护**——错误态下 `value_` 是空 optional，`*value_` 是 UB；用确定性异常替代 UB，把"忘了检查"从静默内存错误升级为带错误消息的崩溃，附带的 errorMessage 还能指出是哪条错误路径漏检。代价是 `value()` 不能标 noexcept、不能在 noexcept 上下文调用。`valueOr` 是温和版：按值返回，失败路径 `std::move(defaultValue)` 避免一次多余拷贝（注意 defaultValue 按值传入，调用处已发生过一次构造）。const/非 const 两个 `value()` 重载覆盖"只读消费"与"移出内容"两种用法，LinuxAnalyzerErrors.h 的同名接口语义一致（该文件 :330-341）。

### 4.3 代码走读：errorCodeToString 的兜底分支（ErrorHandling.h:63-65, 92-98）

```cpp
inline const char* errorCodeToString(ErrorCode code) {
    switch (code) {
        case ErrorCode::Success: return "Success";
        // ... 每个枚举值一个 case，共 31 个分支
        case ErrorCode::Cancelled: return "Operation cancelled";
        default: return "Unknown error code";
    }
}
```

逐块解释：函数是 `inline` 自由函数而非成员——错误码与 Result 解耦，光有个码也能查描述（比如解析历史日志时）。全 switch 无表驱动，编译器会优化成跳转表；每加一个枚举值必须同步加一个 case，否则落到 `default: return "Unknown error code"`——这是一个**可观测的失配信号**：日志里出现该字样即说明"枚举加了但 toString 忘了"，比静默返回空串可诊断得多。返回 `const char*` 字面量而非 `std::string`，零分配；也因此调用方不应持有指针做格式化之外的事。

### 4.4 代码走读：Result\<void\> 特化的减法（ErrorHandling.h:200-232）

```cpp
template<>
class Result<void> {
public:
    static Result success() {
        Result r;
        r.success_ = true;
        r.errorCode_ = ErrorCode::Success;
        return r;
    }

    static Result error(ErrorCode code, const std::string& message = "") {
        Result r;
        r.success_ = false;
        r.errorCode_ = code;
        r.errorMessage_ = message.empty() ? errorCodeToString(code) : message;
        return r;
    }

    bool isSuccess() const { return success_; }
    bool isError() const { return !success_; }

    ErrorCode errorCode() const { return errorCode_; }
    const std::string& errorMessage() const { return errorMessage_; }

    explicit operator bool() const { return success_; }

private:
    Result() = default;

    ErrorCode errorCode_ = ErrorCode::Unknown;
    std::string errorMessage_;
    bool success_ = false;
};
```

逐块解释：特化做的是**减法**——去掉 value_/value()/valueOr()，保留全部错误面。这证明 3.2 节说的"独立 success_ 字段让 void 版复用同一形状"：三个成员（code/message/flag）在两个版本间完全同构，泛型代码模板参数换成 void 也能编译通过相同的状态查询调用。与 `std::expected<void, E>` 的对齐度也在这里体现（expected 的 void 特化同样只有错误面）。注意 `success()` 工厂无参——void 没有可 move 的东西，调用形态是 `Result<void>::success()`；而 Linux 版用 `makeSuccess()` 无参重载达成同一目的（LinuxAnalyzerErrors.h:404），形态差异是"静态工厂 vs 自由函数"的路线分歧。特化版保留了 `errorCode_ = Unknown` 的默认——中间态不安全的原则贯穿两个版本。

### 4.5 对照走读：LinuxAnalyzerErrors.h 的同型异构（:19-71, 297-360）

```cpp
// LinuxAnalyzerErrors.h:19-31 —— 分段方案完全不同
enum class ErrorCode {
    SUCCESS = 0,
    // Database errors (100-199)
    DATABASE_OPEN_FAILED = 100,
    DATABASE_CREATE_TABLE_FAILED = 101,
    ...
    // Container-specific errors (1000-1999)
    DOCKER_DIR_NOT_FOUND = 1001,
    ...
    UNKNOWN_ERROR = 999      // 注意：排在 4000 段之后声明，值却回到 999
};

// :304-311 —— 公开构造器而非私有+工厂
Result(const T& value) : storage_(value) {}
Result(T&& value) : storage_(std::move(value)) {}
Result(const LinuxAnalyzerError& error) : storage_(error) {}
Result(ErrorCode code) : storage_(LinuxAnalyzerError(code)) {}
```

逐块解释：两套实现的分歧逐条对照——**分段语义互斥**：core 版 1xx=文件、2xx=LLM、5xx=数据库；Linux 版 1xx=数据库、2xx=文件，同一个数字在两个命名空间里语义完全不同（core 的 500 是 DatabaseOpenError，Linux 的 500 是 SYSTEM_MEMORY_ERROR）——这是"两套码表并存"最危险的一点，日志聚合时必须先判断来源模块。**Linux 版多了千位段**（1xxx 容器、2xxx Web 服务器、3xxx 安全、4xxx 增强分析），领域粒度更细。**构造纪律**：core 版私有构造+双工厂（构造即分类强制检查），Linux 版公开 5 个构造器（含从 ErrorCode 隐式构造错误 Result），写起来短但允许跳过显式分类。**存储**：variant vs optional（3.2 节）。**错误对象**：Linux 版的 LinuxAnalyzerError 是完整类（code/message/details/isRecoverable 四字段，:206-290），`isRecoverable()` 给调用方"要不要重试"的策略信号——core 版没有这个语义，是其功能缺口。**UNKNOWN_ERROR=999 声明位置**：在 4004 之后却回到 999，纯可读性排版，无语义影响。

## 5. 与其他模块的协作

- **理想协作模型**（尚未大规模落地）：分析器返回 `Result<...>`，TaskManager 据此决定任务阶段成败并写 AuditLog；ThreadPool worker 里的 Result 通过 future 传回（异常路径由 packaged_task 接住，见 ThreadPool.md 第 3 节）。
- **LinuxFilesAnalyzer**：唯一采用同型设计的模块，但用的是自己的 `LinuxAnalyzerErrors.h`（:297 起的 `Result<T>`/`makeSuccess`/`makeError` 工厂）。两个实现的关键差异：Linux 版用 `std::variant` 存储、错误是带 `isRecoverable_` 标志的 `LinuxAnalyzerError` 对象（可判断可恢复性），core 版是 optional + 独立字段、无恢复性语义。若要统一，方向是把该文件改为薄封装转发到 core/ErrorHandling，而不是反向。
- **Logger/AuditLog**：Result 本身不写日志（保持纯值语义）；落日志是调用方在 `else` 分支的职责。
- 测试契约：`tests/UnitTest/test_error_handling.cpp` 是唯一消费者，覆盖工厂、抛异常路径与 void 特化——它同时充当该头文件的"可编译性"回归。

## 6. 注意事项与已知问题

- **最大的已知问题就是无人使用**（见第 2 节）。阅读旧代码时不要假设"返回 Result"是全项目惯例——DatabaseManager 等返回的是裸 bool。
- `value()` 的抛异常设计意味着它**不是** noexcept 的安全接口；在 noexcept 上下文只能用 `valueOr`。
- 错误码分段是约定而非编译期约束，新增码时须手动放进正确区间（`ErrorHandling.h` 对应注释块），并在 `errorCodeToString`（:63-98）同步加分支，否则显示 "Unknown error code"。
- 没有错误堆栈/链（cause 链）能力；包装下层错误时只能把消息拼进 `errorMessage`。
- `Result<void>` 与 `Result<T>` 无隐式转换，泛型代码里需 `if constexpr` 区分处理。
- 成功态没有附载警告/部分结果的通道（`success_` + 单值模型所限），"成功但有 3 个文件跳过"这类信息只能另走 Logger。
- 头文件同时 include 了 `<variant>` 但 core 版 `Result` 并未使用它（:4）——是参考 Linux 版实现时留下的残留 include。

## 7. 如何验证与扩展

- 单元测试：`tests/UnitTest/test_error_handling.cpp`（注册于 `tests/CMakeLists.txt:792-794`，目标 `test_error_handling`），覆盖工厂构造、value 抛异常、valueOr、void 特化。
- 扩展路径：(1) 新增错误码——在 `ErrorHandling.h` 对应分段加枚举值 + `errorCodeToString` 分支；(2) 推广落地——给新写的分析器直接返回 `Result<T>`，旧模块在重构时逐个迁移；迁移时可参考 LinuxAnalyzerErrors.h 的调用面写法（`makeSuccess`/`makeError` 的自由函数形态更省字，可作为 core 版的语法糖补充）。
- 与 C++23 `std::expected` 的关系：接口刻意相似（`error()`/`value()` 语义对齐），未来切换成本主要在工厂函数形态，业务代码结构可保留。

## 8. 方法全清单（core 版 Result\<T\> / Result\<void\> 双表）

| 成员（Result\<T\>，ErrorHandling.h:118-195） | 行 | 语义 | 调用方 |
|---|---|---|---|
| `static Result success(T)` | :124-130 | 成功态工厂（move 入 optional） | 任意返回 Result 的函数 |
| `static Result error(ErrorCode, msg="")` | :132-141 | 错误态工厂（空消息兜底 toString） | 同上 |
| `bool isSuccess() const` | :146 | 状态查询 | 调用方 if 分流 |
| `bool isError() const` | :147 | 即 !isSuccess | |
| `const T& value() const` | :152-156 | 取值，错误态抛 runtime_error | 已检查后 |
| `T& value()` | :159-164 | 可变取值（可移出） | |
| `T valueOr(T) const` | :168-171 | 安全取默认值 | noexcept 语境 |
| `ErrorCode errorCode() const` | :175 | 错误码（成功=Success） | 策略分发 |
| `const std::string& errorMessage() const` | :180 | 消息（成功=空串） | 日志/审计 |
| `explicit operator bool() const` | :186 | 惯用检查 | |
| 私有：`Result() = default`、四成员 | :189-194 | 中间态=未成功 | |

| 成员（Result\<void\> 特化，:200-232） | 语义 |
|---|---|
| `success()` / `error(code, msg="")` | 无值工厂 |
| `isSuccess()/isError()/errorCode()/errorMessage()/operator bool` | 与 T 版同形 |
| （无 value/valueOr） | 无值可取 |

自由函数：`errorCodeToString(ErrorCode)`（:63-98，31 个 case + default 兜底）。Linux 版对应物：`getErrorMessage`（43 个 case）、`makeSuccess(T&&)/makeSuccess()/makeError(code)/makeError(code, details)`（:400-417）、`LinuxAnalyzerError::toString()`。

## 9. 全仓库错误体系地图（关联矩阵）

| 体系 | 位置 | 形态 | 使用范围 |
|---|---|---|---|
| core ErrorHandling | src/core/ErrorHandling/ErrorHandling.h | optional+工厂 Result | **仅单元测试**（test_error_handling.cpp:4 唯一 include） |
| Linux AnalyzerErrors | src/analyzers/LinuxFilesAnalyzer/Common/LinuxAnalyzerErrors.h | variant Result + isRecoverable | LinuxFilesAnalyzer 全部 parser/analysis（17+ 文件） |
| TextDump 状态枚举 | src/export/TextDumpExporter.h:16-17 | MarkdownStatus/StopReason（非 Result，枚举+结果结构体） | TextDumpExporter/AnalysisOrchestrator 的 --dump-text 段 |
| bool + cerr 惯例 | DatabaseManager/EventExtractor/FileClassifier/FileExtractor/AuditLog 等核心链 | 返回 bool，stderr 打印，AuditLog 留痕 | 生产主流 |
| int 退出码 | AnalysisOrchestrator run* 系列 | 0/1 进程语义 | CLI 边界 |
| 异常 | runAnalysis 的 catch-all、AuditLog::value() | 跨阶段兜底 | 边界防护 |

推论：**生产代码的错误通道事实上是"bool+stderr+AuditLog"三件套**，两套 Result 都只覆盖各自角落。统一的最大阻力不是技术而是迁移面（core 链全部函数签名都要改）；务实的路径是 Linux 版保持现状、新模块用 core 版、老模块不动。

## 10. 与 std::expected 的接口映射

| 本头文件 | C++23 std::expected<T, E> | 差异 |
|---|---|---|
| `success(v)` | `return v;`（隐式构造） | expected 零样板 |
| `error(c, m)` | `return std::unexpected(err)` | expected 的 E 需自定义错误类型 |
| `isSuccess()` | `has_value()` | |
| `value()`（错误抛异常） | `value()`（抛 bad_expected_access） | 异常类型不同，语义一致 |
| `valueOr(d)` | `value_or(d)` | 同名近形 |
| `errorMessage()` | 无直接对应 | expected 无内建消息，需 E 自带 |
| `errorCode()` 分段策略 | 无对应 | expected 的 E 即错误对象本身 |
| `Result<void>` | `std::expected<void, E>` | 一致 |

切换评估：项目若升 C++23，core 版 Result 可用 typedef 过渡（`template<class T> using Result = std::expected<T, ForensicsError>`），但 errorCodeToString 的兜底、error() 的空消息回填这两个便利语义需要在新的 Error 类型构造器里复刻，否则调用方代码会多出空串判断。

## 11. 性能与并发细节

- **零分配路径**：`success(v)` 的成本 = T 的一次 move + optional 装箱 + RVO 返回；`errorMessage_` 为空串（SSO，无堆分配）。错误路径有一次 string 拷贝（自定义消息）或零拷贝（用 toString 的 const char* 构造 SSO 串——超过 15 字符的消息会堆分配）。相较异常抛掷（栈展开微秒级），错误路径完全可预测，适合热循环。
- **体积特征**：`Result<T>` = optional<T>（T+1 字节对齐）+ string（32 字节）+ enum(4)+bool ≈ sizeof(T)+40 字节；返回大 vector 时整体按值返回依赖 RVO/移动，无拷贝放大。Linux 版 variant 形状相近（variant 自身带索引开销）。
- **线程语义**：纯值类型，无共享状态；跨线程经 future/promise 传递安全。`value()` 抛出的 runtime_error 在 packaged_task 中会被捕获并存入 future（ThreadPool.md 的 worker 契约），不会 terminate。
- **可调参数影响**：无（本模块不读任何配置）。



## 12. 测试契约细目（test_error_handling.cpp，182 行）

该测试文件是本头文件唯一的消费者，其断言事实上构成 ErrorCode 的**兼容性契约**——任何重排分段值的行为都会先红在这里：

| 测试组 | 覆盖 | 关键断言（行号） |
|---|---|---|
| `ErrorCodeTest.ErrorCodeValues` | 分段锚点值 | Success=0、FileNotFound=100、LLMConnectionFailed=200、NoModelsAvailable=300、InvalidConfiguration=400、DatabaseOpenError=500、AnalysisFailed=600（:16-22）——每段的**首码**被钉死 |
| `ErrorCodeTest.ErrorCodeToString` | 码→文案 | 7 个代表码的字符串精确匹配（:26-31），`Cancelled` 的注释 "// Check if correct" 是仓库里少见的存疑标记 |
| `ResultTest.SuccessWithValue` | 成功态全部查询面 | isSuccess/isError/value/errorCode/operator bool 五连（:41-45） |
| `ResultTest.ErrorWithCode` | 错误码兜底消息 | error 工厂不给消息时 errorMessage=="File not found"（:54）——兜底回填的行为被锁定 |
| `ResultTest.ErrorWithCustomMessage` | 自定义消息 | 自定义串覆盖兜底（:61-62） |
| `ResultTest.ValueThrows` | value() 雷区 | 错误态取值抛 runtime_error（EXPECT_THROW） |
| `ResultTest.ValueOr` | 安全取值 | 错误态返回默认值 |
| `VoidResultTest` | Result\<void\> 特化 | success()/error() 两工厂与状态查询 |

注意测试**没有**覆盖的：operator bool 在 void 特化上的行为、错误码段间空号的合法性、Result 的拷贝/移动语义、并发传递。迁移到 std::expected 时，前两组测试应原样保留（分段值与文案是外部可见契约），后几组改写为 expected 的对应断言。

## 13. 迁移剧本（若决定统一错误体系）

1. core 版补齐两个能力缺口再推广：错误对象化（带 details 字段）与可恢复性标志（对齐 LinuxAnalyzerErrors.h:245-252 的 isRecoverable/setRecoverable）——否则 Linux 侧迁移是功能回退。
2. LinuxAnalyzerErrors.h 改为薄层：`namespace LinuxAnalysis { using forensics::Result; ... }`，ErrorCode 保留本地枚举（分段已固化为日志契约，不能重映射），仅 Result/工厂转发 core。
3. 分段冲突的消解：core 1xx=文件与 Linux 1xx=数据库不可调和，统一方向是 core 版让出 1xx（文件移到 7xx 空段）或接受"枚举本地化、Result 全局化"的折中——后者改动面为零，推荐。
4. bool 惯例的渐进替换只做在新代码；存量核心链（DatabaseManager 等）改动收益低、回归风险高。

**最后更新**: 2026-08-24（二轮深化：补全表列说明与方法清单）
