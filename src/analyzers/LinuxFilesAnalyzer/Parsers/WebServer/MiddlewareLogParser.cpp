// MiddlewareLogParser.cpp
// Implementation of web server error log and middleware log parser
// Phase 7: Web and Middleware Log Enhancement

#ifdef linux
#undef linux
#endif

#include "MiddlewareLogParser.h"
#include "Parsers/TimestampNormalizer.h"
#include <sstream>
#include <regex>
#include <algorithm>
#include <iostream>
#include <ctime>

using namespace forensics::linux;

// ============================================================================
// Apache Error Log Parsing
// ============================================================================

std::vector<WebErrorLogEntry> MiddlewareLogParser::parseApacheErrorLog(
    const std::string& content, const std::string& filePath) {
    std::vector<WebErrorLogEntry> entries;
    std::istringstream stream(content);
    std::string line;

    while (std::getline(stream, line)) {
        if (line.empty()) continue;
        auto entry = parseApacheErrorLine(line, filePath);
        if (!entry.message.empty()) {
            entries.push_back(entry);
        }
    }
    return entries;
}

WebErrorLogEntry MiddlewareLogParser::parseApacheErrorLine(
    const std::string& line, const std::string& filePath) {
    WebErrorLogEntry entry;
    entry.filePath = filePath;
    entry.source = "Apache";

    // Apache error log format: [Fri Oct 06 10:23:45.123456 2023] [module:level] [pid 1234] [client ip:port] Message
    // Or: [Fri Oct 06 10:23:45 2023] [module:level] Message
    std::regex apacheErrorRegex(
        "\\[([^\\]]+)\\]\\s+\\[([^:]+):([^\\]]+)\\]\\s+(.*)");
    std::smatch match;

    if (std::regex_match(line, match, apacheErrorRegex)) {
        std::string timestampStr = match[1].str();
        entry.module = match[2].str();
        entry.level = match[3].str();
        entry.message = match[4].str();

        // Parse timestamp: "Fri Oct 06 10:23:45.123456 2023"
        entry.timestamp = parseErrorLogTimestamp(timestampStr, "apache_error");

        // Extract client IP if present
        std::regex clientRegex("client\\s+([\\d.]+)");
        std::smatch clientMatch;
        if (std::regex_search(entry.message, clientMatch, clientRegex)) {
            entry.clientIp = clientMatch[1].str();
        }
    } else {
        // Fallback: treat entire line as message
        entry.message = line;
        entry.level = "error";
    }

    entry.provenance.parserName = "MiddlewareLogParser";
    entry.provenance.parserVersion = "1.0.0";
    entry.provenance.sourceFile = filePath;
    entry.provenance.rawRecord = line;

    return entry;
}

// ============================================================================
// Nginx Error Log Parsing
// ============================================================================

std::vector<WebErrorLogEntry> MiddlewareLogParser::parseNginxErrorLog(
    const std::string& content, const std::string& filePath) {
    std::vector<WebErrorLogEntry> entries;
    std::istringstream stream(content);
    std::string line;

    while (std::getline(stream, line)) {
        if (line.empty()) continue;
        auto entry = parseNginxErrorLine(line, filePath);
        if (!entry.message.empty()) {
            entries.push_back(entry);
        }
    }
    return entries;
}

WebErrorLogEntry MiddlewareLogParser::parseNginxErrorLine(
    const std::string& line, const std::string& filePath) {
    WebErrorLogEntry entry;
    entry.filePath = filePath;
    entry.source = "Nginx";

    // Nginx error log: 2023/10/06 10:23:45 [error] 1234#0: *5678 message, client: ip, server: host
    std::regex nginxErrorRegex(
        "(\\d{4}/\\d{2}/\\d{2}\\s+\\d{2}:\\d{2}:\\d{2})\\s+\\[([^\\]]+)\\]\\s+(?:(\\d+)#\\d+:\\s+(?:\\*\\d+\\s+)?)?(.*)");
    std::smatch match;

    if (std::regex_match(line, match, nginxErrorRegex)) {
        std::string timestampStr = match[1].str();
        entry.level = match[2].str();
        if (match[3].matched) entry.pid = match[3].str();
        entry.message = match[4].str();

        // Parse timestamp: "2023/10/06 10:23:45"
        entry.timestamp = parseErrorLogTimestamp(timestampStr, "nginx_error");

        // Extract client IP
        std::regex clientRegex("client:\\s+([\\d.]+)");
        std::smatch clientMatch;
        if (std::regex_search(entry.message, clientMatch, clientRegex)) {
            entry.clientIp = clientMatch[1].str();
        }
    } else {
        entry.message = line;
        entry.level = "error";
    }

    entry.provenance.parserName = "MiddlewareLogParser";
    entry.provenance.parserVersion = "1.0.0";
    entry.provenance.sourceFile = filePath;
    entry.provenance.rawRecord = line;

    return entry;
}

// ============================================================================
// PHP-FPM Log Parsing
// ============================================================================


// Middleware parsers (php-fpm/tomcat/jetty/pm2/gunicorn/uwsgi/ModSecurity) live in MiddlewareLogParser_Middleware.cpp

std::vector<WebErrorLogEntry> MiddlewareLogParser::parseErrorLogAuto(
    const std::string& content, const std::string& filePath) {
    // Try to detect format from first line
    if (content.empty()) return {};

    std::string firstLine = content.substr(0, content.find('\n'));

    // Apache error log starts with [Day Month DD HH:MM:SS.ffffff YYYY]
    if (firstLine.find("[") == 0 && firstLine.find("] [") != std::string::npos) {
        return parseApacheErrorLog(content, filePath);
    }

    // Nginx error log starts with YYYY/MM/DD
    if (firstLine.length() >= 10 && firstLine[4] == '/' && firstLine[7] == '/') {
        return parseNginxErrorLog(content, filePath);
    }

    // Default to Apache format
    return parseApacheErrorLog(content, filePath);
}

// ============================================================================
// Timestamp Parsing
// ============================================================================

int64_t MiddlewareLogParser::parseErrorLogTimestamp(
    const std::string& timestampStr, const std::string& format) {
    struct tm tm = {};
    int microseconds = 0;

    if (format == "apache_error") {
        // "Fri Oct 06 10:23:45.123456 2023" or "Fri Oct 06 10:23:45 2023"
        std::string ts = timestampStr;
        // Try with microseconds first
        std::regex usRegex("(\\w{3}\\s+\\w{3}\\s+\\d{2}\\s+\\d{2}:\\d{2}:\\d{2})\\.(\\d+)\\s+(\\d{4})");
        std::smatch match;
        if (std::regex_search(ts, match, usRegex)) {
            microseconds = std::stoi(match[2].str());
            std::string parseStr = match[1].str() + " " + match[3].str();
            if (strptime(parseStr.c_str(), "%a %b %d %H:%M:%S %Y", &tm)) {
                return static_cast<int64_t>(timegm(&tm)) * 1000000LL + microseconds;
            }
        }
        // Without microseconds: "Fri Oct 06 10:23:45 2023"
        if (strptime(ts.c_str(), "%a %b %d %H:%M:%S %Y", &tm)) {
            return static_cast<int64_t>(timegm(&tm)) * 1000000LL;
        }
    } else if (format == "nginx_error") {
        // "2023/10/06 10:23:45"
        if (strptime(timestampStr.c_str(), "%Y/%m/%d %H:%M:%S", &tm)) {
            return static_cast<int64_t>(timegm(&tm)) * 1000000LL;
        }
    } else if (format == "php_fpm") {
        // "06-Oct-2023 10:23:45"
        if (strptime(timestampStr.c_str(), "%d-%b-%Y %H:%M:%S", &tm)) {
            return static_cast<int64_t>(timegm(&tm)) * 1000000LL;
        }
    } else if (format == "tomcat") {
        // "06-Oct-2023 10:23:45.123" or "06-Oct-2023 10:23:45"
        std::regex tomcatRegex("(\\d{2}-\\w{3}-\\d{4}\\s+\\d{2}:\\d{2}:\\d{2})(?:\\.(\\d+))?");
        std::smatch match;
        if (std::regex_search(timestampStr, match, tomcatRegex)) {
            if (match[2].matched) {
                microseconds = std::stoi(match[2].str());
            }
            if (strptime(match[1].str().c_str(), "%d-%b-%Y %H:%M:%S", &tm)) {
                return static_cast<int64_t>(timegm(&tm)) * 1000000LL + microseconds;
            }
        }
    } else if (format == "jetty") {
        // "2023-10-06 10:23:45.123"
        std::regex jettyRegex("(\\d{4}-\\d{2}-\\d{2}\\s+\\d{2}:\\d{2}:\\d{2})(?:\\.(\\d+))?");
        std::smatch match;
        if (std::regex_search(timestampStr, match, jettyRegex)) {
            if (match[2].matched) {
                microseconds = std::stoi(match[2].str());
            }
            if (strptime(match[1].str().c_str(), "%Y-%m-%d %H:%M:%S", &tm)) {
                return static_cast<int64_t>(timegm(&tm)) * 1000000LL + microseconds;
            }
        }
    } else if (format == "pm2") {
        // "2023-10-06T10:23:45"
        if (strptime(timestampStr.c_str(), "%Y-%m-%dT%H:%M:%S", &tm)) {
            return static_cast<int64_t>(timegm(&tm)) * 1000000LL;
        }
    } else if (format == "gunicorn") {
        // "2023-10-06 10:23:45 +0000"
        std::string ts = timestampStr;
        // Strip timezone for strptime
        size_t tzPos = ts.find_last_of("+-");
        if (tzPos != std::string::npos && tzPos > 10) {
            ts = ts.substr(0, tzPos);
        }
        // Trim trailing space
        while (!ts.empty() && ts.back() == ' ') ts.pop_back();
        if (strptime(ts.c_str(), "%Y-%m-%d %H:%M:%S", &tm)) {
            return static_cast<int64_t>(timegm(&tm)) * 1000000LL;
        }
    }

    return 0;
}
