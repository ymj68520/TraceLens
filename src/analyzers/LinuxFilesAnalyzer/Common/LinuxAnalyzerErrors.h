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

    // Container-specific errors (1000-1999)
    DOCKER_DIR_NOT_FOUND = 1001,
    DOCKER_CONFIG_PARSE_FAILED = 1002,
    PODMAN_DIR_NOT_FOUND = 1003,
    DOCKER_INVALID_JSON = 1004,

    // Web server-specific errors (2000-2999)
    APACHE_LOG_PARSE_FAILED = 2001,
    NGINX_LOG_PARSE_FAILED = 2002,
    VHOST_CONFIG_INVALID = 2003,
    LOG_FILE_NOT_FOUND = 2004,

    // Security analysis errors (3000-3999)
    SETUID_SCAN_FAILED = 3001,
    CAPABILITY_PARSE_FAILED = 3002,
    SELINUX_NOT_ENABLED = 3003,
    APPARMOR_NOT_ENABLED = 3004,
    PERMISSION_DENIED = 3005,

    // Enhanced analysis errors (4000-4999)
    CORRELATION_ENGINE_FAILED = 4001,
    TIMELINE_RECONSTRUCTION_FAILED = 4002,
    ANOMALY_DETECTION_FAILED = 4003,
    INSUFFICIENT_DATA = 4004,

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

        // Container-specific errors
        case ErrorCode::DOCKER_DIR_NOT_FOUND:
            return "Docker directory not found";
        case ErrorCode::DOCKER_CONFIG_PARSE_FAILED:
            return "Failed to parse Docker configuration";
        case ErrorCode::PODMAN_DIR_NOT_FOUND:
            return "Podman directory not found";
        case ErrorCode::DOCKER_INVALID_JSON:
            return "Invalid JSON in Docker configuration";

        // Web server-specific errors
        case ErrorCode::APACHE_LOG_PARSE_FAILED:
            return "Failed to parse Apache log file";
        case ErrorCode::NGINX_LOG_PARSE_FAILED:
            return "Failed to parse Nginx log file";
        case ErrorCode::VHOST_CONFIG_INVALID:
            return "Invalid virtual host configuration";
        case ErrorCode::LOG_FILE_NOT_FOUND:
            return "Log file not found";

        // Security analysis errors
        case ErrorCode::SETUID_SCAN_FAILED:
            return "Failed to scan for setuid files";
        case ErrorCode::CAPABILITY_PARSE_FAILED:
            return "Failed to parse file capabilities";
        case ErrorCode::SELINUX_NOT_ENABLED:
            return "SELinux is not enabled";
        case ErrorCode::APPARMOR_NOT_ENABLED:
            return "AppArmor is not enabled";
        case ErrorCode::PERMISSION_DENIED:
            return "Permission denied";

        // Enhanced analysis errors
        case ErrorCode::CORRELATION_ENGINE_FAILED:
            return "Correlation engine failed";
        case ErrorCode::TIMELINE_RECONSTRUCTION_FAILED:
            return "Timeline reconstruction failed";
        case ErrorCode::ANOMALY_DETECTION_FAILED:
            return "Anomaly detection failed";
        case ErrorCode::INSUFFICIENT_DATA:
            return "Insufficient data for analysis";

        default:
            return "Unknown error";
    }
}

/**
 * @brief Error class with code, message, and optional context
 */
class LinuxAnalyzerError {
public:
    LinuxAnalyzerError() : code_(ErrorCode::SUCCESS), isRecoverable_(true) {}

    LinuxAnalyzerError(ErrorCode code)
        : code_(code), message_(getErrorMessage(code)), isRecoverable_(true) {}

    LinuxAnalyzerError(ErrorCode code, const std::string& details)
        : code_(code), message_(getErrorMessage(code)), details_(details), isRecoverable_(true) {}

    LinuxAnalyzerError(ErrorCode code, const std::string& message, const std::string& details)
        : code_(code), message_(message), details_(details), isRecoverable_(true) {}

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

    // Get component that generated the error
    const std::string& component() const { return component_; }

    // Get file path where error occurred
    const std::string& filePath() const { return filePath_; }

    // Get line number where error occurred
    int lineNumber() const { return lineNumber_; }

    // Get suggestion for recovery
    const std::string& suggestion() const { return suggestion_; }

    // Check if error is recoverable
    bool isRecoverable() const { return isRecoverable_; }

    // Setters for extended fields
    void setComponent(const std::string& component) { component_ = component; }
    void setFilePath(const std::string& filePath) { filePath_ = filePath; }
    void setLineNumber(int lineNumber) { lineNumber_ = lineNumber; }
    void setSuggestion(const std::string& suggestion) { suggestion_ = suggestion; }
    void setRecoverable(bool recoverable) { isRecoverable_ = recoverable; }

    // Get full error string
    std::string toString() const {
        std::string result = "[" + std::to_string(static_cast<int>(code_)) + "] " + message_;
        if (!component_.empty()) {
            result += " [Component: " + component_ + "]";
        }
        if (!details_.empty()) {
            result += ": " + details_;
        }
        if (!filePath_.empty()) {
            result += " (File: " + filePath_;
            if (lineNumber_ > 0) {
                result += ":" + std::to_string(lineNumber_);
            }
            result += ")";
        }
        if (!suggestion_.empty()) {
            result += " [Suggestion: " + suggestion_ + "]";
        }
        if (!isRecoverable_) {
            result += " [FATAL]";
        }
        return result;
    }

    // Implicit bool conversion (true = error exists)
    explicit operator bool() const { return isError(); }

private:
    ErrorCode code_;
    std::string message_;
    std::string details_;
    std::string component_;
    std::string filePath_;
    int lineNumber_ = 0;
    std::string suggestion_;
    bool isRecoverable_ = true;
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
