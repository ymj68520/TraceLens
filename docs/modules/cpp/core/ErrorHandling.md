# ErrorHandling - 错误处理模块

> **模块定位**: 提供统一的错误处理机制，包括错误码定义和 `Result<T>` 类型安全返回值

---

## 1. 模块概述

### 位置

`src/core/ErrorHandling/ErrorHandling.h`

### 设计目标

- **类型安全**: 使用 `Result<T>` 替代异常和错误码，编译期保证错误处理
- **统一错误码**: 覆盖文件、LLM、模型、配置、数据库、分析等所有模块的错误类型
- **零开销**: 基于 `std::optional` 实现，无异常抛出开销
- **C++23 前向兼容**: 类似 `std::expected` 的设计，未来可无缝迁移

---

## 2. 错误码体系

```cpp
enum class ErrorCode {
    Success = 0,

    // 文件错误 (100-199)
    FileNotFound = 100,
    FileReadError = 101,
    FileWriteError = 102,
    FileAccessDenied = 103,
    InvalidFilePath = 104,
    FileEmpty = 105,

    // LLM 错误 (200-299)
    LLMConnectionFailed = 200,
    LLMRequestFailed = 201,
    LLMResponseParseError = 202,
    LLMTimeout = 203,
    LLMRateLimited = 204,
    LLMContextOverflow = 205,

    // 模型错误 (300-399)
    NoModelsAvailable = 300,
    ModelNotFound = 301,
    AllModelsFailed = 302,

    // 配置错误 (400-499)
    InvalidConfiguration = 400,
    ConfigNotLoaded = 401,
    MissingConfigKey = 402,

    // 数据库错误 (500-599)
    DatabaseOpenError = 500,
    DatabaseQueryError = 501,
    DatabaseWriteError = 502,
    DatabaseNotInitialized = 503,

    // 分析错误 (600-699)
    AnalysisFailed = 600,
    ContentTooLarge = 601,
    UnsupportedFileType = 602,
    ChunkingFailed = 603,

    // 通用错误 (900-999)
    Unknown = 900,
    InternalError = 901,
    NotImplemented = 902,
    Cancelled = 903
};
```

错误码按模块分段，便于快速定位错误来源。

---

## 3. Result<T> 类型

### 基本用法

```cpp
#include "ErrorHandling/ErrorHandling.h"

using namespace forensics;

// 返回成功结果
Result<int> divide(int a, int b) {
    if (b == 0) {
        return Result<int>::error(ErrorCode::InternalError, "Division by zero");
    }
    return Result<int>::success(a / b);
}

// 使用结果
auto result = divide(10, 2);
if (result.isSuccess()) {
    std::cout << result.value() << std::endl;  // 5
} else {
    std::cerr << result.errorMessage() << std::endl;
}
```

### API 参考

#### 创建结果

```cpp
// 成功结果
Result<T>::success(value)

// 错误结果
Result<T>::error(ErrorCode code, const std::string& message = "")
```

#### 查询状态

```cpp
result.isSuccess()   // bool: 是否成功
result.isError()     // bool: 是否失败
explicit operator bool()  // 隐式转换为 bool
```

#### 获取值

```cpp
result.value()       // const T&: 获取值（失败时抛出 std::runtime_error）
result.valueOr(defaultValue)  // T: 获取值或默认值
```

#### 获取错误信息

```cpp
result.errorCode()     // ErrorCode: 错误码
result.errorMessage()  // const std::string&: 错误描述
```

### Result<void> 特化

用于不返回值的操作：

```cpp
Result<void> saveToFile(const std::string& path) {
    if (path.empty()) {
        return Result<void>::error(ErrorCode::InvalidFilePath);
    }
    // ... 保存逻辑 ...
    return Result<void>::success();
}
```

### 错误码转字符串

```cpp
const char* desc = errorCodeToString(ErrorCode::FileNotFound);
// 返回 "File not found"
```

---

## 4. 使用模式

### 早期返回模式

```cpp
Result<Data> processFile(const std::string& path) {
    auto readResult = readFile(path);
    if (readResult.isError()) {
        return Result<Data>::error(readResult.errorCode(), readResult.errorMessage());
    }

    auto parseResult = parseData(readResult.value());
    if (parseResult.isError()) {
        return Result<Data>::error(parseResult.errorCode());
    }

    return Result<Data>::success(parseResult.value());
}
```

---

## 5. 与其他模块的集成

`Result<T>` 在以下模块中使用：
- **LLMIntegration**: LLM 调用结果
- **DatabaseManager**: 数据库操作结果
- **ConfigManager**: 配置加载结果
- **FileAnalyzer**: 文件分析结果

---

**最后更新**: 2026-05-19
