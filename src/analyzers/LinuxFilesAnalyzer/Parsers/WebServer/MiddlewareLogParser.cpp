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

std::vector<MiddlewareLogEntry> MiddlewareLogParser::parsePhpFpmLog(
    const std::string& content, const std::string& filePath) {
    std::vector<MiddlewareLogEntry> entries;
    std::istringstream stream(content);
    std::string line;
    std::string currentException;
    bool inException = false;

    while (std::getline(stream, line)) {
        if (line.empty()) continue;

        // PHP-FPM log: [06-Oct-2023 10:23:45] PHP Fatal error: message
        // Also handles: [06-Oct-2023 10:23:45] PHP Warning: message
        std::regex phpRegex("\\[(\\d{2}-\\w{3}-\\d{4}\\s+\\d{2}:\\d{2}:\\d{2})\\]\\s+PHP\\s+(\\w+(?:\\s+\\w+)?):\\s*(.*)");
        std::smatch match;

        if (std::regex_match(line, match, phpRegex)) {
            // Save previous exception if any
            if (inException && !currentException.empty()) {
                if (!entries.empty()) {
                    entries.back().exception = currentException;
                }
                currentException.clear();
                inException = false;
            }

            MiddlewareLogEntry entry;
            entry.filePath = filePath;
            entry.source = "PHP-FPM";

            std::string timestampStr = match[1].str();
            entry.level = match[2].str();  // Fatal, Warning, Notice, etc.
            entry.message = match[3].str();

            entry.timestamp = parseErrorLogTimestamp(timestampStr, "php_fpm");
            entry.provenance.parserName = "MiddlewareLogParser";
            entry.provenance.parserVersion = "1.0.0";
            entry.provenance.sourceFile = filePath;
            entry.provenance.rawRecord = line;

            entries.push_back(entry);

            // Check if this starts an exception
            if (entry.message.find("Uncaught") != std::string::npos ||
                entry.message.find("Stack trace:") != std::string::npos) {
                inException = true;
            }
        } else if (inException) {
            // Continuation of exception/stack trace
            currentException += line + "\n";
        }
    }

    // Save last exception
    if (inException && !currentException.empty() && !entries.empty()) {
        entries.back().exception = currentException;
    }

    return entries;
}

// ============================================================================
// Tomcat Log Parsing
// ============================================================================

std::vector<MiddlewareLogEntry> MiddlewareLogParser::parseTomcatLog(
    const std::string& content, const std::string& filePath) {
    std::vector<MiddlewareLogEntry> entries;
    std::istringstream stream(content);
    std::string line;

    while (std::getline(stream, line)) {
        if (line.empty()) continue;
        auto entry = parseTomcatLine(line, filePath);
        if (!entry.message.empty()) {
            entries.push_back(entry);
        }
    }
    return entries;
}

MiddlewareLogEntry MiddlewareLogParser::parseTomcatLine(
    const std::string& line, const std::string& filePath) {
    MiddlewareLogEntry entry;
    entry.filePath = filePath;
    entry.source = "Tomcat";

    // Tomcat catalina.out: 06-Oct-2023 10:23:45.123 INFO [main] org.apache.catalina.startup.Catalina.start Message
    std::regex tomcatRegex(
        "(\\d{2}-\\w{3}-\\d{4}\\s+\\d{2}:\\d{2}:\\d{2}\\.\\d+)\\s+(\\w+)\\s+\\[([^\\]]+)\\]\\s+(\\S+)\\s+(.*)");
    std::smatch match;

    if (std::regex_match(line, match, tomcatRegex)) {
        std::string timestampStr = match[1].str();
        entry.level = match[2].str();
        entry.thread = match[3].str();
        entry.logger = match[4].str();
        entry.message = match[5].str();

        entry.timestamp = parseErrorLogTimestamp(timestampStr, "tomcat");
    } else {
        // Fallback for other formats (e.g., JULI format)
        std::regex juliRegex(
            "(\\d{2}-\\w{3}-\\d{4}\\s+\\d{2}:\\d{2}:\\d{2})\\s+(\\w+)\\s+(.*)");
        if (std::regex_match(line, match, juliRegex)) {
            entry.timestamp = parseErrorLogTimestamp(match[1].str(), "tomcat");
            entry.level = match[2].str();
            entry.message = match[3].str();
        } else {
            entry.message = line;
            entry.level = "INFO";
        }
    }

    entry.provenance.parserName = "MiddlewareLogParser";
    entry.provenance.parserVersion = "1.0.0";
    entry.provenance.sourceFile = filePath;
    entry.provenance.rawRecord = line;

    return entry;
}

// ============================================================================
// Jetty Log Parsing
// ============================================================================

std::vector<MiddlewareLogEntry> MiddlewareLogParser::parseJettyLog(
    const std::string& content, const std::string& filePath) {
    std::vector<MiddlewareLogEntry> entries;
    std::istringstream stream(content);
    std::string line;

    while (std::getline(stream, line)) {
        if (line.empty()) continue;

        MiddlewareLogEntry entry;
        entry.filePath = filePath;
        entry.source = "Jetty";

        // Jetty uses java.util.logging format or custom format
        // Example: 2023-10-06 10:23:45.123:INFO:oejs.Server:main: Message
        std::regex jettyRegex(
            "(\\d{4}-\\d{2}-\\d{2}\\s+\\d{2}:\\d{2}:\\d{2}\\.\\d+):(\\w+):(\\S+):(\\S+):\\s+(.*)");
        std::smatch match;

        if (std::regex_match(line, match, jettyRegex)) {
            entry.timestamp = parseErrorLogTimestamp(match[1].str(), "jetty");
            entry.level = match[2].str();
            entry.logger = match[3].str();
            entry.thread = match[4].str();
            entry.message = match[5].str();
        } else {
            entry.message = line;
            entry.level = "INFO";
        }

        entry.provenance.parserName = "MiddlewareLogParser";
        entry.provenance.parserVersion = "1.0.0";
        entry.provenance.sourceFile = filePath;
        entry.provenance.rawRecord = line;

        entries.push_back(entry);
    }
    return entries;
}

// ============================================================================
// PM2 Log Parsing
// ============================================================================

std::vector<MiddlewareLogEntry> MiddlewareLogParser::parsePm2Log(
    const std::string& content, const std::string& filePath) {
    std::vector<MiddlewareLogEntry> entries;
    std::istringstream stream(content);
    std::string line;

    while (std::getline(stream, line)) {
        if (line.empty()) continue;

        MiddlewareLogEntry entry;
        entry.filePath = filePath;
        entry.source = "PM2";

        // PM2 log format: 2023-10-06T10:23:45: app[0]: message
        // Or: app-0  | 2023-10-06T10:23:45: message
        std::regex pm2Regex(
            "(?:\\S+\\s*\\|\\s*)?(\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2})(?::\\s*|\\s+)(.*)");
        std::smatch match;

        if (std::regex_match(line, match, pm2Regex)) {
            entry.timestamp = parseErrorLogTimestamp(match[1].str(), "pm2");
            entry.message = match[2].str();

            // Detect level from message
            if (entry.message.find("Error") != std::string::npos ||
                entry.message.find("error") != std::string::npos) {
                entry.level = "ERROR";
            } else if (entry.message.find("Warn") != std::string::npos) {
                entry.level = "WARN";
            } else {
                entry.level = "INFO";
            }
        } else {
            entry.message = line;
            entry.level = "INFO";
        }

        entry.provenance.parserName = "MiddlewareLogParser";
        entry.provenance.parserVersion = "1.0.0";
        entry.provenance.sourceFile = filePath;
        entry.provenance.rawRecord = line;

        entries.push_back(entry);
    }
    return entries;
}

// ============================================================================
// Gunicorn Log Parsing
// ============================================================================

std::vector<MiddlewareLogEntry> MiddlewareLogParser::parseGunicornLog(
    const std::string& content, const std::string& filePath) {
    std::vector<MiddlewareLogEntry> entries;
    std::istringstream stream(content);
    std::string line;

    while (std::getline(stream, line)) {
        if (line.empty()) continue;

        MiddlewareLogEntry entry;
        entry.filePath = filePath;
        entry.source = "Gunicorn";

        // Gunicorn log: [2023-10-06 10:23:45 +0000] [1234] [ERROR] message
        std::regex gunicornRegex(
            "\\[(\\d{4}-\\d{2}-\\d{2}\\s+\\d{2}:\\d{2}:\\d{2}\\s+[+-]\\d{4})\\]\\s+\\[(\\d+)\\]\\s+\\[(\\w+)\\]\\s+(.*)");
        std::smatch match;

        if (std::regex_match(line, match, gunicornRegex)) {
            entry.timestamp = parseErrorLogTimestamp(match[1].str(), "gunicorn");
            entry.pid = match[2].str();
            entry.level = match[3].str();
            entry.message = match[4].str();
        } else {
            entry.message = line;
            entry.level = "INFO";
        }

        entry.provenance.parserName = "MiddlewareLogParser";
        entry.provenance.parserVersion = "1.0.0";
        entry.provenance.sourceFile = filePath;
        entry.provenance.rawRecord = line;

        entries.push_back(entry);
    }
    return entries;
}

// ============================================================================
// uWSGI Log Parsing
// ============================================================================

std::vector<MiddlewareLogEntry> MiddlewareLogParser::parseUwsgiLog(
    const std::string& content, const std::string& filePath) {
    std::vector<MiddlewareLogEntry> entries;
    std::istringstream stream(content);
    std::string line;

    while (std::getline(stream, line)) {
        if (line.empty()) continue;

        MiddlewareLogEntry entry;
        entry.filePath = filePath;
        entry.source = "uWSGI";

        // uWSGI log: [pid: 1234|app: 0|req: 1/1] client (method) {vars} => generated bytes in msecs (HTTP/1.1 200)
        std::regex uwsgiRegex(
            "\\[pid:\\s+(\\d+)\\|(.*)\\]\\s+(.*)");
        std::smatch match;

        if (std::regex_match(line, match, uwsgiRegex)) {
            entry.pid = match[1].str();
            entry.thread = match[2].str();
            entry.message = match[3].str();
            entry.level = "INFO";
        } else {
            // Error format: --- uWSGI error ---
            entry.message = line;
            if (line.find("error") != std::string::npos ||
                line.find("Error") != std::string::npos) {
                entry.level = "ERROR";
            } else {
                entry.level = "INFO";
            }
        }

        entry.provenance.parserName = "MiddlewareLogParser";
        entry.provenance.parserVersion = "1.0.0";
        entry.provenance.sourceFile = filePath;
        entry.provenance.rawRecord = line;

        entries.push_back(entry);
    }
    return entries;
}

// ============================================================================
// ModSecurity Audit Log Parsing
// ============================================================================

std::vector<ModSecurityAuditEntry> MiddlewareLogParser::parseModSecurityLog(
    const std::string& content, const std::string& filePath) {
    std::vector<ModSecurityAuditEntry> entries;

    // ModSecurity audit log is section-based with --section-H-- markers
    std::istringstream stream(content);
    std::string line;
    std::string currentSection;
    ModSecurityAuditEntry currentEntry;
    currentEntry.filePath = filePath;

    while (std::getline(stream, line)) {
        // Section markers: --a1b2c3d4-H--
        if (line.length() > 4 && line.substr(0, 2) == "--" && line.substr(line.length()-2) == "--") {
            // Save previous entry if complete
            if (!currentEntry.clientIp.empty() && !currentEntry.uri.empty()) {
                currentEntry.provenance.parserName = "MiddlewareLogParser";
                currentEntry.provenance.parserVersion = "1.0.0";
                currentEntry.provenance.sourceFile = filePath;
                entries.push_back(currentEntry);
            }
            currentEntry = ModSecurityAuditEntry();
            currentEntry.filePath = filePath;
            continue;
        }

        // Section A: Request headers
        if (line.find("GET ") == 0 || line.find("POST ") == 0 ||
            line.find("PUT ") == 0 || line.find("DELETE ") == 0) {
            std::istringstream reqLine(line);
            std::string method, uri, version;
            reqLine >> method >> uri >> version;
            currentEntry.method = method;
            currentEntry.uri = uri;
        }

        // Section H: Audit log messages
        if (line.find("Message:") == 0) {
            // Extract rule ID and message
            std::regex ruleRegex("Message:\\s*.*?(?:id\\s*\"(\\d+)\").*?(?:msg\\s*\"([^\"]*)\")");
            std::smatch match;
            if (std::regex_search(line, match, ruleRegex)) {
                currentEntry.ruleId = match[1].str();
                currentEntry.ruleMessage = match[2].str();
            }
            currentEntry.action = "blocked";
        }

        // Extract client IP from section A or E
        if (line.find("X-Forwarded-For:") != std::string::npos) {
            size_t pos = line.find(":");
            if (pos != std::string::npos) {
                currentEntry.clientIp = line.substr(pos + 1);
                // Trim whitespace
                currentEntry.clientIp.erase(0, currentEntry.clientIp.find_first_not_of(" \t"));
            }
        }
    }

    // Save last entry
    if (!currentEntry.clientIp.empty() && !currentEntry.uri.empty()) {
        currentEntry.provenance.parserName = "MiddlewareLogParser";
        currentEntry.provenance.parserVersion = "1.0.0";
        currentEntry.provenance.sourceFile = filePath;
        entries.push_back(currentEntry);
    }

    return entries;
}

// ============================================================================
// Auto-detection
// ============================================================================

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
