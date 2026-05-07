// AndroidLogParser.cpp
// Implementation of Android system log parsing

#include "AndroidAnalyzer.h"
#include "AndroidDataTypes.h"
#include "PathManager/PathManager.h"
#include "AuditLog/AuditLog.h"
#include <sstream>
#include <iomanip>
#include <ctime>
#include <algorithm>
#include <regex>

// ============================================================================
// AndroidLogParser
// ============================================================================

class AndroidLogParser {
public:
    // Parse Android logcat format
    static SystemLogEntry parseLogcatLine(const std::string& line, 
                                         const std::string& logFile) {
        SystemLogEntry entry;
        entry.logFile = logFile;
        entry.pid = -1;
        entry.timestamp = 0;

        // Android logcat format: "MM-DD HH:MM:SS.mmm PID-TID TAG: MESSAGE"
        // Example: "01-05 10:23:45.123 1234-5678 SystemServer: Started ActivityManager"

        if (line.length() < 18) {
            entry.message = line;
            entry.logLevel = "INFO";
            entry.tag = "UNKNOWN";
            entry.process = "UNKNOWN";
            entry.logSource = "logcat";
            return entry;
        }

        // Extract timestamp (first 17 characters: "MM-DD HH:MM:SS.mmm")
        std::string timestampStr = line.substr(0, 17);
        entry.timestamp = parseLogcatTimestamp(timestampStr);

        // Find PID-TID (after timestamp)
        size_t pos = 18;
        size_t tagPos = line.find(' ', pos);
        if (tagPos == std::string::npos) {
            entry.message = line;
            entry.logLevel = "INFO";
            entry.tag = "UNKNOWN";
            entry.process = "UNKNOWN";
            entry.logSource = "logcat";
            return entry;
        }

        std::string pidTidStr = line.substr(pos, tagPos - pos);
        size_t dashPos = pidTidStr.find('-');
        if (dashPos != std::string::npos) {
            std::string pidStr = pidTidStr.substr(0, dashPos);
            try {
                entry.pid = std::stoi(pidStr);
            } catch (...) {
                entry.pid = -1;
            }
        }

        // Find tag (after PID-TID, before colon)
        pos = tagPos + 1;
        size_t colonPos = line.find(':', pos);
        if (colonPos == std::string::npos) {
            entry.message = line.substr(pos);
            entry.logLevel = "INFO";
            entry.tag = "UNKNOWN";
            entry.process = "UNKNOWN";
            entry.logSource = "logcat";
            return entry;
        }

        entry.tag = line.substr(pos, colonPos - pos);

        // Extract message (everything after colon and space)
        if (colonPos + 2 < line.length()) {
            entry.message = line.substr(colonPos + 2);
        }

        // Infer log level and process
        entry.logLevel = inferLogLevel(entry.message);
        entry.process = inferProcess(entry.tag);
        entry.logSource = "logcat";

        return entry;
    }

    // Parse Android kernel log format
    static SystemLogEntry parseKernelLogLine(const std::string& line, 
                                            const std::string& logFile) {
        SystemLogEntry entry;
        entry.logFile = logFile;
        entry.pid = -1;
        entry.logLevel = "INFO";
        entry.tag = "KERNEL";
        entry.process = "kernel";
        entry.logSource = "kernel";

        // Kernel log format: "[timestamp] message" or "[timestamp] [level] message"
        // Example: "[    0.000000] Linux version 5.4.0"

        size_t bracketOpen = line.find('[');
        size_t bracketClose = line.find(']');

        if (bracketOpen != std::string::npos && bracketClose != std::string::npos &&
            bracketClose > bracketOpen) {
            entry.timestamp = parseKernelTimestamp(line.substr(bracketOpen + 1, bracketClose - bracketOpen - 1));

            if (bracketClose + 2 < line.length()) {
                entry.message = line.substr(bracketClose + 2);
            }
        } else {
            entry.message = line;
        }

        return entry;
    }

    // Parse Android event log format
    static SystemLogEntry parseEventLogLine(const std::string& line, 
                                           const std::string& logFile) {
        SystemLogEntry entry;
        entry.logFile = logFile;
        entry.pid = -1;
        entry.logLevel = "INFO";
        entry.logSource = "event";

        // Event log format varies, but typically includes timestamp and event type
        // Example: "12-31 23:59:59.999 I/EventLog(1234): event_type=1234, value=5678"

        if (line.length() < 18) {
            entry.message = line;
            entry.tag = "UNKNOWN";
            entry.process = "UNKNOWN";
            return entry;
        }

        // Extract timestamp
        std::string timestampStr = line.substr(0, 17);
        entry.timestamp = parseLogcatTimestamp(timestampStr);

        // Extract log level and tag
        size_t pos = 18;
        if (pos + 2 < line.length() && line[pos] == 'I' && line[pos+1] == '/') {
            entry.logLevel = "INFO";
            pos += 2;
        } else if (pos + 2 < line.length() && line[pos] == 'E' && line[pos+1] == '/') {
            entry.logLevel = "ERROR";
            pos += 2;
        } else if (pos + 2 < line.length() && line[pos] == 'W' && line[pos+1] == '/') {
            entry.logLevel = "WARNING";
            pos += 2;
        } else if (pos + 2 < line.length() && line[pos] == 'D' && line[pos+1] == '/') {
            entry.logLevel = "DEBUG";
            pos += 2;
        }

        size_t tagEnd = line.find('(', pos);
        if (tagEnd != std::string::npos) {
            entry.tag = line.substr(pos, tagEnd - pos);
            // Extract PID from parentheses
            size_t pidEnd = line.find(')', tagEnd + 1);
            if (pidEnd != std::string::npos) {
                std::string pidStr = line.substr(tagEnd + 1, pidEnd - tagEnd - 1);
                try {
                    entry.pid = std::stoi(pidStr);
                } catch (...) {
                    entry.pid = -1;
                }
            }
            // Extract message
            if (pidEnd + 3 < line.length() && line.substr(pidEnd + 1, 2) == ": ") {
                entry.message = line.substr(pidEnd + 3);
            }
        } else {
            entry.message = line.substr(pos);
            entry.tag = "UNKNOWN";
        }

        entry.process = inferProcess(entry.tag);
        return entry;
    }

private:
    // Parse logcat timestamp (MM-DD HH:MM:SS.mmm)
    static int64_t parseLogcatTimestamp(const std::string& timestamp) {
        if (timestamp.length() < 17) {
            return 0;
        }

        struct tm tm = {};
        
        // Parse month and day
        int month = std::stoi(timestamp.substr(0, 2));
        int day = std::stoi(timestamp.substr(3, 2));
        
        // Parse time
        int hour = std::stoi(timestamp.substr(6, 2));
        int minute = std::stoi(timestamp.substr(9, 2));
        int second = std::stoi(timestamp.substr(12, 2));
        
        // Get current year
        time_t now = time(nullptr);
        struct tm* nowTm = localtime(&now);
        
        tm.tm_year = nowTm->tm_year;
        tm.tm_mon = month - 1; // 0-based
        tm.tm_mday = day;
        tm.tm_hour = hour;
        tm.tm_min = minute;
        tm.tm_sec = second;
        
        return mktime(&tm);
    }

    // Parse kernel timestamp (seconds since boot)
    static int64_t parseKernelTimestamp(const std::string& timestamp) {
        try {
            double bootSeconds = std::stod(timestamp);
            // Convert to approximate timestamp (would need boot time for accurate conversion)
            return static_cast<int64_t>(bootSeconds);
        } catch (...) {
            return 0;
        }
    }

    // Infer log level from message content
    static std::string inferLogLevel(const std::string& message) {
        std::string lowerMsg = message;
        std::transform(lowerMsg.begin(), lowerMsg.end(), lowerMsg.begin(), ::tolower);

        if (lowerMsg.find("error") != std::string::npos ||
            lowerMsg.find("failed") != std::string::npos ||
            lowerMsg.find("exception") != std::string::npos ||
            lowerMsg.find("crash") != std::string::npos) {
            return "ERROR";
        }
        if (lowerMsg.find("warning") != std::string::npos ||
            lowerMsg.find("warn") != std::string::npos ||
            lowerMsg.find("deprecated") != std::string::npos) {
            return "WARNING";
        }
        if (lowerMsg.find("debug") != std::string::npos ||
            lowerMsg.find("verbose") != std::string::npos) {
            return "DEBUG";
        }
        return "INFO";
    }

    // Infer process name from tag
    static std::string inferProcess(const std::string& tag) {
        // Common Android tags and their corresponding processes
        std::map<std::string, std::string> tagToProcess = {
            {"SystemServer", "system_server"},
            {"ActivityManager", "system_server"},
            {"PackageManager", "system_server"},
            {"WindowManager", "system_server"},
            {"BluetoothManagerService", "system_server"},
            {"WifiService", "system_server"},
            {"TelephonyManager", "system_server"},
            {"PowerManagerService", "system_server"},
            {"InputManager", "system_server"},
            {"AudioService", "system_server"},
            {"CameraService", "cameraserver"},
            {"SurfaceFlinger", "surfaceflinger"},
            {"Zygote", "zygote"},
            {"Init", "init"},
            {"Kernel", "kernel"},
            {"ADB", "adbd"},
            {"Logcat", "logd"}
        };

        auto it = tagToProcess.find(tag);
        if (it != tagToProcess.end()) {
            return it->second;
        }

        // For app tags (usually package names)
        if (tag.find('.') != std::string::npos) {
            return tag;
        }

        return "unknown";
    }
};

// ============================================================================
// AndroidAnalyzer::analyzeSystemLogs
// ============================================================================

void AndroidAnalyzer::analyzeSystemLogs() {
    std::cout << "Analyzing Android System Logs..." << std::endl;
    AuditLog::instance().log("SYSTEM", "ANDROID_LOG_ANALYSIS_START", 
        "Starting Android system log analysis");

    // Common Android log files paths
    std::vector<std::string> logPaths = {
        "system/logs/main.txt",
        "system/logs/event.txt",
        "system/logs/kernel.txt",
        "data/log/dmesg",
        "data/log/last_kmsg",
        "data/system/dropbox/system_server_crash",
        "data/system/dropbox/data_app_crash",
        "data/tombstones/tombstone_00",
        "data/tombstones/tombstone_01"
    };

    int processedCount = 0;
    int totalRecords = 0;

    for (const auto& logPath : logPaths) {
        std::string tempPath = forensics::PathManager::instance().makeTempPath(
            "android_log_" + std::to_string(std::time(nullptr)) + "_" +
            logPath.substr(logPath.find_last_of('/') + 1));

        if (fileExtractor_->extractFileByPath(logPath, tempPath)) {
            std::vector<SystemLogEntry> entries = parseSystemLogFile(tempPath, logPath);

            if (!entries.empty()) {
                for (const auto& entry : entries) {
                    androidDb_->insertSystemLog(entry);
                }
                processedCount++;
                totalRecords += entries.size();

                std::cout << "  Processed: " << logPath 
                         << " (" << entries.size() << " records)" << std::endl;
            }

            // Clean up temporary file
            std::filesystem::remove(tempPath);
        } else {
            // File not found, continue to next one
            continue;
        }
    }

    std::cout << "  Processed " << processedCount << " log files" 
             << " with " << totalRecords << " total records." << std::endl;

    AuditLog::instance().log("SYSTEM", "ANDROID_LOG_ANALYSIS_COMPLETE", 
        "Completed Android system log analysis: " + std::to_string(processedCount) +
        " files, " + std::to_string(totalRecords) + " records");
}

// ============================================================================
// AndroidAnalyzer::parseSystemLogFile
// ============================================================================

std::vector<SystemLogEntry> AndroidAnalyzer::parseSystemLogFile(const std::string& filePath, 
                                                              const std::string& originalPath) {
    std::vector<SystemLogEntry> entries;
    std::ifstream file(filePath);
    std::string line;

    if (!file) {
        AuditLog::instance().log("ERROR", "ANDROID_LOG_OPEN_FAILED", 
            "Cannot open log file for reading: " + filePath);
        return entries;
    }

    // Determine log type based on file path
    std::string logType = getLogTypeFromPath(originalPath);

    while (std::getline(file, line)) {
        if (line.empty()) {
            continue;
        }

        SystemLogEntry entry;
        if (logType == "kernel") {
            entry = AndroidLogParser::parseKernelLogLine(line, originalPath);
        } else if (logType == "event") {
            entry = AndroidLogParser::parseEventLogLine(line, originalPath);
        } else {
            // Default to logcat format
            entry = AndroidLogParser::parseLogcatLine(line, originalPath);
        }

        entries.push_back(entry);
    }

    file.close();
    return entries;
}

// ============================================================================
// AndroidAnalyzer::getLogTypeFromPath
// ============================================================================

std::string AndroidAnalyzer::getLogTypeFromPath(const std::string& path) {
    std::string lowerPath = path;
    std::transform(lowerPath.begin(), lowerPath.end(), lowerPath.begin(), ::tolower);

    if (lowerPath.find("kernel") != std::string::npos || 
        lowerPath.find("dmesg") != std::string::npos ||
        lowerPath.find("kmsg") != std::string::npos) {
        return "kernel";
    }
    if (lowerPath.find("event") != std::string::npos) {
        return "event";
    }
    if (lowerPath.find("tombstone") != std::string::npos) {
        return "tombstone";
    }
    return "logcat";
}