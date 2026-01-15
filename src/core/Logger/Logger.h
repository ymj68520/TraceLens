#pragma once

#include <string>
#include <fstream>
#include <mutex>
#include <iostream>
#include <chrono>
#include <iomanip>
#include <sstream>

namespace forensics {

/**
 * @brief Log level enumeration
 */
enum class LogLevel {
    DEBUG = 0,
    INFO = 1,
    WARNING = 2,
    ERROR = 3
};

/**
 * @brief Log output mode
 */
enum class LogOutput {
    STDOUT,   // Output to console
    FILE,     // Output to file
    NONE      // No output (silent)
};

/**
 * @brief Configurable logging system
 * 
 * Singleton logger with configurable output mode and log level.
 * Supports stdout, file, or silent modes.
 * 
 * Usage:
 *   Logger::instance().setOutput(LogOutput::FILE, "debug.log");
 *   Logger::instance().setLevel(LogLevel::DEBUG);
 *   LOG_DEBUG("This is a debug message");
 *   LOG_INFO("Processing file: " + filename);
 */
class Logger {
public:
    /**
     * @brief Get singleton instance
     */
    static Logger& instance();
    
    /**
     * @brief Set minimum log level
     */
    void setLevel(LogLevel level);
    
    /**
     * @brief Get current log level
     */
    LogLevel getLevel() const { return level_; }
    
    /**
     * @brief Set output mode
     * @param output Output mode (STDOUT, FILE, or NONE)
     * @param filePath Path to log file (only used if output == FILE)
     */
    void setOutput(LogOutput output, const std::string& filePath = "debug.log");
    
    /**
     * @brief Get current output mode
     */
    LogOutput getOutput() const { return output_; }
    
    /**
     * @brief Log a debug message
     */
    void debug(const std::string& msg);
    
    /**
     * @brief Log an info message
     */
    void info(const std::string& msg);
    
    /**
     * @brief Log a warning message
     */
    void warning(const std::string& msg);
    
    /**
     * @brief Log an error message
     */
    void error(const std::string& msg);
    
    /**
     * @brief Generic log method
     */
    void log(LogLevel level, const std::string& msg);
    
    /**
     * @brief Flush the log output
     */
    void flush();

private:
    Logger() = default;
    ~Logger();
    
    // Non-copyable
    Logger(const Logger&) = delete;
    Logger& operator=(const Logger&) = delete;
    
    void write(const std::string& formattedMsg);
    std::string formatMessage(LogLevel level, const std::string& msg);
    const char* levelToString(LogLevel level);
    
    LogLevel level_ = LogLevel::INFO;
    LogOutput output_ = LogOutput::STDOUT;
    std::string filePath_;
    std::ofstream file_;
    mutable std::mutex mutex_;
};

// ============================================================================
// Convenience Macros
// ============================================================================

#define LOG_DEBUG(msg) ::forensics::Logger::instance().debug(msg)
#define LOG_INFO(msg) ::forensics::Logger::instance().info(msg)
#define LOG_WARNING(msg) ::forensics::Logger::instance().warning(msg)
#define LOG_ERROR(msg) ::forensics::Logger::instance().error(msg)

// Conditional debug logging (only in debug builds)
#ifdef NDEBUG
    #define LOG_DEBUG_ONLY(msg) ((void)0)
#else
    #define LOG_DEBUG_ONLY(msg) LOG_DEBUG(msg)
#endif

} // namespace forensics
