// LinuxLogParser.cpp
// Implementation of Linux log file parsing

#include "LinuxLogParser.h"
#include <sstream>
#include <iomanip>
#include <ctime>
#include <algorithm>

LinuxLogEntry LinuxLogParser::parseSyslogLine(const std::string& line, 
                                               const std::string& logFile) {
    LinuxLogEntry entry;
    entry.logFile = logFile;
    entry.pid = -1;
    entry.unixTimestamp = 0;

    // Standard syslog format: "Mon DD HH:MM:SS hostname process[pid]: message"
    // Example: "Jan  5 10:23:45 server sshd[1234]: Accepted publickey for user"

    if (line.length() < 16) {
        entry.message = line;
        return entry;
    }

    // Extract timestamp (first 15 characters)
    entry.timestamp = line.substr(0, 15);
    entry.unixTimestamp = parseSyslogTimestamp(entry.timestamp);

    // Find hostname (after timestamp, before process)
    size_t pos = 16;
    size_t hostnameEnd = line.find(' ', pos);
    if (hostnameEnd == std::string::npos) {
        entry.message = line;
        return entry;
    }
    entry.hostname = line.substr(pos, hostnameEnd - pos);

    // Find process name and optional PID
    pos = hostnameEnd + 1;
    size_t colonPos = line.find(':', pos);
    if (colonPos == std::string::npos) {
        entry.message = line.substr(pos);
        return entry;
    }

    std::string processInfo = line.substr(pos, colonPos - pos);

    // Check for PID in brackets: process[pid]
    size_t bracketOpen = processInfo.find('[');
    size_t bracketClose = processInfo.find(']');

    if (bracketOpen != std::string::npos && bracketClose != std::string::npos && 
        bracketClose > bracketOpen) {
        entry.process = processInfo.substr(0, bracketOpen);
        std::string pidStr = processInfo.substr(bracketOpen + 1, 
                                                  bracketClose - bracketOpen - 1);
        try {
            entry.pid = std::stoi(pidStr);
        } catch (...) {
            entry.pid = -1;
        }
    } else {
        entry.process = processInfo;
    }

    // Extract message (everything after colon and space)
    if (colonPos + 2 < line.length()) {
        entry.message = line.substr(colonPos + 2);
    }

    // Infer log level and facility
    entry.level = inferLogLevel(entry.message);
    entry.facility = inferFacility(logFile);

    return entry;
}

int64_t LinuxLogParser::parseSyslogTimestamp(const std::string& timestamp, 
                                              int assumedYear) {
    // Format: "Mon DD HH:MM:SS" or "Mon  D HH:MM:SS"
    // Example: "Jan  5 10:23:45"

    if (timestamp.length() < 15) {
        return 0;
    }

    struct tm tm = {};

    // Parse month
    std::string monthStr = timestamp.substr(0, 3);
    static const char* months[] = {
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
    };
    
    for (int i = 0; i < 12; ++i) {
        if (monthStr == months[i]) {
            tm.tm_mon = i;
            break;
        }
    }

    // Parse day (positions 4-5, may have leading space)
    std::string dayStr = timestamp.substr(4, 2);
    // Remove leading space
    if (dayStr[0] == ' ') {
        dayStr = dayStr.substr(1);
    }
    try {
        tm.tm_mday = std::stoi(dayStr);
    } catch (...) {
        return 0;
    }

    // Parse time (positions 7-14)
    if (timestamp.length() >= 15) {
        try {
            tm.tm_hour = std::stoi(timestamp.substr(7, 2));
            tm.tm_min = std::stoi(timestamp.substr(10, 2));
            tm.tm_sec = std::stoi(timestamp.substr(13, 2));
        } catch (...) {
            return 0;
        }
    }

    // Use assumed year or current year
    if (assumedYear > 0) {
        tm.tm_year = assumedYear - 1900;
    } else {
        time_t now = time(nullptr);
        struct tm* nowTm = localtime(&now);
        tm.tm_year = nowTm->tm_year;
    }

    return mktime(&tm);
}

LinuxLogEntry LinuxLogParser::parseKernelLogLine(const std::string& line,
                                                  const std::string& logFile) {
    LinuxLogEntry entry;
    entry.logFile = logFile;
    entry.pid = -1;
    entry.facility = "kern";

    // Kernel log format: "[timestamp] message" or "[ timestamp] message"
    // Example: "[    0.000000] Linux version 5.4.0"

    size_t bracketOpen = line.find('[');
    size_t bracketClose = line.find(']');

    if (bracketOpen != std::string::npos && bracketClose != std::string::npos &&
        bracketClose > bracketOpen) {
        entry.timestamp = line.substr(bracketOpen + 1, bracketClose - bracketOpen - 1);
        
        // Try to parse as seconds since boot
        try {
            double bootSeconds = std::stod(entry.timestamp);
            // Convert to approximate timestamp (would need boot time for accurate conversion)
            entry.unixTimestamp = static_cast<int64_t>(bootSeconds);
        } catch (...) {
            entry.unixTimestamp = 0;
        }

        if (bracketClose + 2 < line.length()) {
            entry.message = line.substr(bracketClose + 2);
        }
    } else {
        entry.message = line;
    }

    entry.level = inferLogLevel(entry.message);
    return entry;
}

LinuxLogEntry LinuxLogParser::parseDpkgLogLine(const std::string& line,
                                                const std::string& logFile) {
    LinuxLogEntry entry;
    entry.logFile = logFile;
    entry.pid = -1;
    entry.facility = "dpkg";

    // dpkg.log format: "YYYY-MM-DD HH:MM:SS action package version arch"
    // Example: "2024-01-05 10:23:45 install python3:amd64 3.10.12-1"

    if (line.length() < 20) {
        entry.message = line;
        return entry;
    }

    // Parse timestamp (first 19 characters)
    entry.timestamp = line.substr(0, 19);

    // Parse timestamp to unix time
    struct tm tm = {};
    if (strptime(entry.timestamp.c_str(), "%Y-%m-%d %H:%M:%S", &tm) != nullptr) {
        entry.unixTimestamp = mktime(&tm);
    }

    // Rest is the action and package info
    if (line.length() > 20) {
        entry.message = line.substr(20);
    }

    entry.level = "INFO";
    return entry;
}

LinuxLogEntry LinuxLogParser::parseAptHistoryLine(const std::string& line,
                                                   const std::string& logFile) {
    LinuxLogEntry entry;
    entry.logFile = logFile;
    entry.pid = -1;
    entry.facility = "apt";
    entry.message = line;
    entry.level = "INFO";

    // apt history format varies, often key: value pairs
    // Parse Start-Date: YYYY-MM-DD  HH:MM:SS
    if (line.find("Start-Date:") == 0) {
        std::string dateStr = line.substr(12);
        entry.timestamp = dateStr;
        
        struct tm tm = {};
        if (strptime(dateStr.c_str(), "%Y-%m-%d  %H:%M:%S", &tm) != nullptr) {
            entry.unixTimestamp = mktime(&tm);
        }
    }

    return entry;
}

std::string LinuxLogParser::inferLogLevel(const std::string& message) {
    std::string lowerMsg = message;
    std::transform(lowerMsg.begin(), lowerMsg.end(), lowerMsg.begin(), ::tolower);

    if (lowerMsg.find("error") != std::string::npos ||
        lowerMsg.find("failed") != std::string::npos ||
        lowerMsg.find("failure") != std::string::npos ||
        lowerMsg.find("critical") != std::string::npos) {
        return "ERROR";
    }
    if (lowerMsg.find("warning") != std::string::npos ||
        lowerMsg.find("warn") != std::string::npos) {
        return "WARNING";
    }
    if (lowerMsg.find("debug") != std::string::npos) {
        return "DEBUG";
    }
    return "INFO";
}

std::string LinuxLogParser::inferFacility(const std::string& logFile) {
    std::string lowerFile = logFile;
    std::transform(lowerFile.begin(), lowerFile.end(), lowerFile.begin(), ::tolower);

    if (lowerFile.find("auth") != std::string::npos) {
        return "auth";
    }
    if (lowerFile.find("kern") != std::string::npos) {
        return "kern";
    }
    if (lowerFile.find("syslog") != std::string::npos) {
        return "syslog";
    }
    if (lowerFile.find("daemon") != std::string::npos) {
        return "daemon";
    }
    if (lowerFile.find("cron") != std::string::npos) {
        return "cron";
    }
    if (lowerFile.find("mail") != std::string::npos) {
        return "mail";
    }
    return "user";
}
