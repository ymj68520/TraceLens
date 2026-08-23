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

## 5. 与其他模块的协作

- **理想协作模型**（尚未大规模落地）：分析器返回 `Result<...>`，TaskManager 据此决定任务阶段成败并写 AuditLog；ThreadPool worker 里的 Result 通过 future 传回（异常路径由 packaged_task 接住，见 ThreadPool.md 第 3 节）。
- **LinuxFilesAnalyzer**：唯一采用同型设计的模块，但用的是自己的 `LinuxAnalyzerErrors.h`（:297 起的 `Result<T>`/`makeSuccess`/`makeError` 工厂）。若要统一，方向是把该文件改为薄封装转发到 core/ErrorHandling，而不是反向。
- **Logger/AuditLog**：Result 本身不写日志（保持纯值语义）；落日志是调用方在 `else` 分支的职责。

## 6. 注意事项与已知问题

- **最大的已知问题就是无人使用**（见第 2 节）。阅读旧代码时不要假设"返回 Result"是全项目惯例——DatabaseManager 等返回的是裸 bool。
- `value()` 的抛异常设计意味着它**不是** noexcept 的安全接口；在 noexcept 上下文只能用 `valueOr`。
- 错误码分段是约定而非编译期约束，新增码时须手动放进正确区间（`ErrorHandling.h` 对应注释块），并在 `errorCodeToString`（:63-98）同步加分支，否则显示 "Unknown error code"。
- 没有错误堆栈/链（cause 链）能力；包装下层错误时只能把消息拼进 `errorMessage`。
- `Result<void>` 与 `Result<T>` 无隐式转换，泛型代码里需 `if constexpr` 区分处理。

## 7. 如何验证与扩展

- 单元测试：`tests/UnitTest/test_error_handling.cpp`（注册于 `tests/CMakeLists.txt:792-794`，目标 `test_error_handling`），覆盖工厂构造、value 抛异常、valueOr、void 特化。
- 扩展路径：(1) 新增错误码——在 `ErrorHandling.h` 对应分段加枚举值 + `errorCodeToString` 分支；(2) 推广落地——给新写的分析器直接返回 `Result<T>`，旧模块在重构时逐个迁移；迁移时可参考 LinuxAnalyzerErrors.h 的调用面写法。
- 与 C++23 `std::expected` 的关系：接口刻意相似（`error()`/`value()` 语义对齐），未来切换成本主要在工厂函数形态，业务代码结构可保留。

**最后更新**: 2026-08-23（解释式重写）
