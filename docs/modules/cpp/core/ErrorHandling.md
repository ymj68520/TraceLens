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

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
