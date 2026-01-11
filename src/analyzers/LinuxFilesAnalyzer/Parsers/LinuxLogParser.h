// LinuxLogParser.h
// Header for Linux log file parsing

#pragma once
#ifndef LINUX_LOG_PARSER_H
#define LINUX_LOG_PARSER_H

#include <string>
#include <vector>
#include <ctime>
#include <regex>
#include "Common/LinuxDataTypes.h"

// Log parsing utility class
class LinuxLogParser {
public:
    // Parse standard syslog format (auth.log, syslog, messages)
    static LinuxLogEntry parseSyslogLine(const std::string& line, 
                                          const std::string& logFile);

    // Parse timestamp from syslog format (e.g., "Jan  5 10:23:45")
    static int64_t parseSyslogTimestamp(const std::string& timestamp, 
                                         int assumedYear = 0);

    // Parse kernel log format (dmesg, kern.log)
    static LinuxLogEntry parseKernelLogLine(const std::string& line,
                                             const std::string& logFile);

    // Parse dpkg log format (for package installation tracking)
    static LinuxLogEntry parseDpkgLogLine(const std::string& line,
                                           const std::string& logFile);

    // Parse apt history log
    static LinuxLogEntry parseAptHistoryLine(const std::string& line,
                                              const std::string& logFile);

    // Determine log level from message content
    static std::string inferLogLevel(const std::string& message);

    // Determine facility from log file name
    static std::string inferFacility(const std::string& logFile);
};

#endif // LINUX_LOG_PARSER_H
