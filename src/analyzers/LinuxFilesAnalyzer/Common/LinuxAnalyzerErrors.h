// LinuxAnalyzerErrors.h
// Error handling infrastructure for LinuxFilesAnalyzer
// Part of LinuxFilesAnalyzer module improvements

#pragma once
#ifndef LINUX_ANALYZER_ERRORS_H
#define LINUX_ANALYZER_ERRORS_H

#include <string>
#include <optional>
#include <variant>

namespace LinuxAnalysis {

/**
 * @brief Error codes for LinuxFilesAnalyzer operations
 */
enum class ErrorCode {
    SUCCESS = 0,
    
    // Database errors (100-199)
    DATABASE_OPEN_FAILED = 100,
    DATABASE_CREATE_TABLE_FAILED = 101,
    DATABASE_INSERT_FAILED = 102,
    DATABASE_QUERY_FAILED = 103,
    DATABASE_PREPARE_FAILED = 104,
    DATABASE_BIND_FAILED = 105,
    DATABASE_EXECUTE_FAILED = 106,
    DATABASE_TRANSACTION_FAILED = 107,
    DATABASE_NOT_INITIALIZED = 108,
    
    // File errors (200-299)
    FILE_NOT_FOUND = 200,
    FILE_READ_ERROR = 201,
    FILE_WRITE_ERROR = 202,
    FILE_ACCESS_DENIED = 203,
    FILE_EXTRACT_FAILED = 204,
    
    // Parse errors (300-399)
    PARSE_INVALID_FORMAT = 300,
    PARSE_INCOMPLETE_DATA = 301,
    PARSE_ENCODING_ERROR = 302,
    PARSE_TIMESTAMP_ERROR = 303,
    PARSE_BINARY_FORMAT_ERROR = 304,
    
    // Validation errors (400-499)
    VALIDATION_INVALID_COLUMN = 400,
    VALIDATION_INVALID_PARAMETER = 401,
    VALIDATION_EMPTY_INPUT = 402,
    
    // System errors (500-599)
    SYSTEM_MEMORY_ERROR = 500,
    SYSTEM_THREAD_ERROR = 501,
    SYSTEM_INITIALIZATION_FAILED = 502,
    
    // Unknown/other errors
    UNKNOWN_ERROR = 999
};

/**
 * @brief Get human-readable error message for error code
 */
inline std::string getErrorMessage(ErrorCode code) {
    switch (code) {
        case ErrorCode::SUCCESS:
            return "Success";
        
        // Database errors
        case ErrorCode::DATABASE_OPEN_FAILED:
            return "Failed to open database";
        case ErrorCode::DATABASE_CREATE_TABLE_FAILED:
            return "Failed to create database table";
        case ErrorCode::DATABASE_INSERT_FAILED:
            return "Failed to insert record into database";
        case ErrorCode::DATABASE_QUERY_FAILED:
            return "Database query failed";
        case ErrorCode::DATABASE_PREPARE_FAILED:
            return "Failed to prepare SQL statement";
        case ErrorCode::DATABASE_BIND_FAILED:
            return "Failed to bind parameter to SQL statement";
        case ErrorCode::DATABASE_EXECUTE_FAILED:
            return "Failed to execute SQL statement";
        case ErrorCode::DATABASE_TRANSACTION_FAILED:
            return "Database transaction failed";
        case ErrorCode::DATABASE_NOT_INITIALIZED:
            return "Database not initialized";
        
        // File errors
        case ErrorCode::FILE_NOT_FOUND:
            return "File not found";
        case ErrorCode::FILE_READ_ERROR:
            return "Error reading file";
        case ErrorCode::FILE_WRITE_ERROR:
            return "Error writing file";
        case ErrorCode::FILE_ACCESS_DENIED:
            return "File access denied";
        case ErrorCode::FILE_EXTRACT_FAILED:
            return "Failed to extract file from image";
        
        // Parse errors
        case ErrorCode::PARSE_INVALID_FORMAT:
            return "Invalid format";
        case ErrorCode::PARSE_INCOMPLETE_DATA:
            return "Incomplete data";
        case ErrorCode::PARSE_ENCODING_ERROR:
            return "Encoding error";
        case ErrorCode::PARSE_TIMESTAMP_ERROR:
            return "Timestamp parsing error";
        case ErrorCode::PARSE_BINARY_FORMAT_ERROR:
            return "Binary format error";
        
        // Validation errors
        case ErrorCode::VALIDATION_INVALID_COLUMN:
            return "Invalid column name";
        case ErrorCode::VALIDATION_INVALID_PARAMETER:
            return "Invalid parameter";
        case ErrorCode::VALIDATION_EMPTY_INPUT:
            return "Empty input provided";
        
        // System errors
        case ErrorCode::SYSTEM_MEMORY_ERROR:
            return "Memory allocation error";
        case ErrorCode::SYSTEM_THREAD_ERROR:
            return "Thread error";
        case ErrorCode::SYSTEM_INITIALIZATION_FAILED:
            return "System initialization failed";
        
        default:
            return "Unknown error";
    }
}

/**
 * @brief Error class with code, message, and optional context
 */
class LinuxAnalyzerError {
public:
    LinuxAnalyzerError() : code_(ErrorCode::SUCCESS) {}
    
    LinuxAnalyzerError(ErrorCode code)
        : code_(code), message_(getErrorMessage(code)) {}
    
    LinuxAnalyzerError(ErrorCode code, const std::string& details)
        : code_(code), message_(getErrorMessage(code)), details_(details) {}
    
    LinuxAnalyzerError(ErrorCode code, const std::string& message, const std::string& details)
        : code_(code), message_(message), details_(details) {}
    
    // Check if this is an error (not success)
    bool isError() const { return code_ != ErrorCode::SUCCESS; }
    
    // Check if this is success
    bool isSuccess() const { return code_ == ErrorCode::SUCCESS; }
    
    // Get error code
    ErrorCode code() const { return code_; }
    
    // Get error message
    const std::string& message() const { return message_; }
    
    // Get additional details
    const std::string& details() const { return details_; }
    
    // Get full error string
    std::string toString() const {
        std::string result = "[" + std::to_string(static_cast<int>(code_)) + "] " + message_;
        if (!details_.empty()) {
            result += ": " + details_;
        }
        return result;
    }
    
    // Implicit bool conversion (true = error exists)
    explicit operator bool() const { return isError(); }

private:
    ErrorCode code_;
    std::string message_;
    std::string details_;
};

/**
 * @brief Result type for operations that may fail
 * 
 * Usage:
 *   Result<std::vector<LinuxLogEntry>> result = queryLogEntries(qb);
 *   if (result.hasValue()) {
 *       auto entries = result.value();
 *   } else {
 *       std::cerr << result.error().toString() << std::endl;
 *   }
 */
template<typename T>
class Result {
public:
    // Success constructor
    Result(const T& value) : storage_(value) {}
    Result(T&& value) : storage_(std::move(value)) {}
    
    // Error constructor
    Result(const LinuxAnalyzerError& error) : storage_(error) {}
    Result(LinuxAnalyzerError&& error) : storage_(std::move(error)) {}
    Result(ErrorCode code) : storage_(LinuxAnalyzerError(code)) {}
    Result(ErrorCode code, const std::string& details) 
        : storage_(LinuxAnalyzerError(code, details)) {}
    
    // Check if has value
    bool hasValue() const {
        return std::holds_alternative<T>(storage_);
    }
    
    // Check if has error
    bool hasError() const {
        return std::holds_alternative<LinuxAnalyzerError>(storage_);
    }
    
    // Get value (throws if error)
    T& value() {
        if (hasError()) {
            throw std::runtime_error(error().toString());
        }
        return std::get<T>(storage_);
    }
    
    const T& value() const {
        if (hasError()) {
            throw std::runtime_error(error().toString());
        }
        return std::get<T>(storage_);
    }
    
    // Get value or default
    T valueOr(const T& defaultValue) const {
        if (hasValue()) {
            return std::get<T>(storage_);
        }
        return defaultValue;
    }
    
    // Get error (throws if value)
    const LinuxAnalyzerError& error() const {
        if (hasValue()) {
            throw std::runtime_error("Result contains value, not error");
        }
        return std::get<LinuxAnalyzerError>(storage_);
    }
    
    // Implicit bool conversion (true = has value)
    explicit operator bool() const { return hasValue(); }

private:
    std::variant<T, LinuxAnalyzerError> storage_;
};

/**
 * @brief Result specialization for void operations
 */
template<>
class Result<void> {
public:
    // Success constructor
    Result() : error_(std::nullopt) {}
    
    // Error constructor
    Result(const LinuxAnalyzerError& error) : error_(error) {}
    Result(ErrorCode code) : error_(LinuxAnalyzerError(code)) {}
    Result(ErrorCode code, const std::string& details) 
        : error_(LinuxAnalyzerError(code, details)) {}
    
    bool hasValue() const { return !error_.has_value(); }
    bool hasError() const { return error_.has_value(); }
    bool isSuccess() const { return !error_.has_value(); }
    
    const LinuxAnalyzerError& error() const {
        if (!error_.has_value()) {
            throw std::runtime_error("Result is success, not error");
        }
        return error_.value();
    }
    
    explicit operator bool() const { return hasValue(); }

private:
    std::optional<LinuxAnalyzerError> error_;
};

// Helper functions to create results
template<typename T>
Result<T> makeSuccess(T&& value) {
    return Result<T>(std::forward<T>(value));
}

inline Result<void> makeSuccess() {
    return Result<void>();
}

template<typename T = void>
Result<T> makeError(ErrorCode code) {
    return Result<T>(code);
}

template<typename T = void>
Result<T> makeError(ErrorCode code, const std::string& details) {
    return Result<T>(code, details);
}

template<typename T = void>
Result<T> makeError(const LinuxAnalyzerError& error) {
    return Result<T>(error);
}

} // namespace LinuxAnalysis

#endif // LINUX_ANALYZER_ERRORS_H
