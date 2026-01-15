#pragma once

#include <string>
#include <variant>
#include <optional>

namespace forensics {

/**
 * @brief Error codes for the forensics system
 */
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
    LLMRequestFailed = 201,
    LLMResponseParseError = 202,
    LLMTimeout = 203,
    LLMRateLimited = 204,
    LLMContextOverflow = 205,
    
    // Model errors (300-399)
    NoModelsAvailable = 300,
    ModelNotFound = 301,
    AllModelsFailed = 302,
    
    // Configuration errors (400-499)
    InvalidConfiguration = 400,
    ConfigNotLoaded = 401,
    MissingConfigKey = 402,
    
    // Database errors (500-599)
    DatabaseOpenError = 500,
    DatabaseQueryError = 501,
    DatabaseWriteError = 502,
    DatabaseNotInitialized = 503,
    
    // Analysis errors (600-699)
    AnalysisFailed = 600,
    ContentTooLarge = 601,
    UnsupportedFileType = 602,
    ChunkingFailed = 603,
    
    // General errors (900-999)
    Unknown = 900,
    InternalError = 901,
    NotImplemented = 902,
    Cancelled = 903
};

/**
 * @brief Get human-readable description for an error code
 */
inline const char* errorCodeToString(ErrorCode code) {
    switch (code) {
        case ErrorCode::Success: return "Success";
        case ErrorCode::FileNotFound: return "File not found";
        case ErrorCode::FileReadError: return "File read error";
        case ErrorCode::FileWriteError: return "File write error";
        case ErrorCode::FileAccessDenied: return "File access denied";
        case ErrorCode::InvalidFilePath: return "Invalid file path";
        case ErrorCode::FileEmpty: return "File is empty";
        case ErrorCode::LLMConnectionFailed: return "LLM connection failed";
        case ErrorCode::LLMRequestFailed: return "LLM request failed";
        case ErrorCode::LLMResponseParseError: return "LLM response parse error";
        case ErrorCode::LLMTimeout: return "LLM request timeout";
        case ErrorCode::LLMRateLimited: return "LLM rate limited";
        case ErrorCode::LLMContextOverflow: return "LLM context window overflow";
        case ErrorCode::NoModelsAvailable: return "No LLM models available";
        case ErrorCode::ModelNotFound: return "Model not found";
        case ErrorCode::AllModelsFailed: return "All models failed";
        case ErrorCode::InvalidConfiguration: return "Invalid configuration";
        case ErrorCode::ConfigNotLoaded: return "Configuration not loaded";
        case ErrorCode::MissingConfigKey: return "Missing configuration key";
        case ErrorCode::DatabaseOpenError: return "Database open error";
        case ErrorCode::DatabaseQueryError: return "Database query error";
        case ErrorCode::DatabaseWriteError: return "Database write error";
        case ErrorCode::DatabaseNotInitialized: return "Database not initialized";
        case ErrorCode::AnalysisFailed: return "Analysis failed";
        case ErrorCode::ContentTooLarge: return "Content too large";
        case ErrorCode::UnsupportedFileType: return "Unsupported file type";
        case ErrorCode::ChunkingFailed: return "Content chunking failed";
        case ErrorCode::Unknown: return "Unknown error";
        case ErrorCode::InternalError: return "Internal error";
        case ErrorCode::NotImplemented: return "Not implemented";
        case ErrorCode::Cancelled: return "Operation cancelled";
        default: return "Unknown error code";
    }
}

/**
 * @brief Result type for operations that can fail
 * 
 * Similar to std::expected (C++23), provides either a value or an error.
 * 
 * Usage:
 *   Result<int> divide(int a, int b) {
 *       if (b == 0) return Result<int>::error(ErrorCode::InternalError, "Division by zero");
 *       return Result<int>::success(a / b);
 *   }
 *   
 *   auto result = divide(10, 2);
 *   if (result.isSuccess()) {
 *       std::cout << result.value() << std::endl;
 *   } else {
 *       std::cerr << result.errorMessage() << std::endl;
 *   }
 */
template<typename T>
class Result {
public:
    /**
     * @brief Create a successful result
     */
    static Result success(T value) {
        Result r;
        r.value_ = std::move(value);
        r.success_ = true;
        r.errorCode_ = ErrorCode::Success;
        return r;
    }
    
    /**
     * @brief Create an error result
     */
    static Result error(ErrorCode code, const std::string& message = "") {
        Result r;
        r.success_ = false;
        r.errorCode_ = code;
        r.errorMessage_ = message.empty() ? errorCodeToString(code) : message;
        return r;
    }
    
    /**
     * @brief Check if the result is successful
     */
    bool isSuccess() const { return success_; }
    bool isError() const { return !success_; }
    
    /**
     * @brief Get the value (throws if error)
     */
    const T& value() const {
        if (!success_) {
            throw std::runtime_error("Attempted to access value of error result: " + errorMessage_);
        }
        return *value_;
    }
    
    T& value() {
        if (!success_) {
            throw std::runtime_error("Attempted to access value of error result: " + errorMessage_);
        }
        return *value_;
    }
    
    /**
     * @brief Get value or default
     */
    T valueOr(T defaultValue) const {
        return success_ ? *value_ : std::move(defaultValue);
    }
    
    /**
     * @brief Get the error code
     */
    ErrorCode errorCode() const { return errorCode_; }
    
    /**
     * @brief Get the error message
     */
    const std::string& errorMessage() const { return errorMessage_; }
    
    /**
     * @brief Implicit conversion to bool
     */
    explicit operator bool() const { return success_; }

private:
    Result() = default;
    
    std::optional<T> value_;
    ErrorCode errorCode_ = ErrorCode::Unknown;
    std::string errorMessage_;
    bool success_ = false;
};

/**
 * @brief Specialization for void results (operations that don't return a value)
 */
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

} // namespace forensics
