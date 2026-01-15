#include "Logger.h"

namespace forensics {

Logger& Logger::instance() {
    static Logger instance;
    return instance;
}

Logger::~Logger() {
    if (file_.is_open()) {
        file_.close();
    }
}

void Logger::setLevel(LogLevel level) {
    std::lock_guard<std::mutex> lock(mutex_);
    level_ = level;
}

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

void Logger::debug(const std::string& msg) {
    log(LogLevel::DEBUG, msg);
}

void Logger::info(const std::string& msg) {
    log(LogLevel::INFO, msg);
}

void Logger::warning(const std::string& msg) {
    log(LogLevel::WARNING, msg);
}

void Logger::error(const std::string& msg) {
    log(LogLevel::ERROR, msg);
}

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

void Logger::flush() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (output_ == LogOutput::FILE && file_.is_open()) {
        file_.flush();
    } else if (output_ == LogOutput::STDOUT) {
        std::cout.flush();
    }
}

void Logger::write(const std::string& formattedMsg) {
    switch (output_) {
        case LogOutput::STDOUT:
            std::cout << formattedMsg << std::endl;
            break;
        case LogOutput::FILE:
            if (file_.is_open()) {
                file_ << formattedMsg << std::endl;
            }
            break;
        case LogOutput::NONE:
            // Do nothing
            break;
    }
}

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

const char* Logger::levelToString(LogLevel level) {
    switch (level) {
        case LogLevel::DEBUG:   return "DEBUG";
        case LogLevel::INFO:    return "INFO";
        case LogLevel::WARNING: return "WARN";
        case LogLevel::ERROR:   return "ERROR";
        default:                return "UNKNOWN";
    }
}

} // namespace forensics
