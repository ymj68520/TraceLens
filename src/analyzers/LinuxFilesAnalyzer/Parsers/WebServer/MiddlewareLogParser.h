// MiddlewareLogParser.h
// Parser for web server error logs and middleware logs
// Phase 7: Web and Middleware Log Enhancement

#pragma once
#ifndef MIDDLEWARE_LOG_PARSER_H
#define MIDDLEWARE_LOG_PARSER_H

#include <string>
#include <vector>
#include <regex>
#include "Common/LinuxDataTypes.h"

// linux is a predefined macro on Linux systems, must undef to use as namespace
#ifdef linux
#undef linux
#endif

namespace forensics {
namespace linux {

// Web server error log entry
struct WebErrorLogEntry {
    int64_t timestamp = 0;
    std::string level;              // error, warn, notice, info, debug
    std::string source;             // Apache, Nginx, PHP-FPM, etc.
    std::string clientIp;
    std::string message;
    std::string module;             // Apache module or Nginx module
    std::string pid;
    std::string filePath;           // Source log file
    NormalizedTimestamp normalizedTime;
    EvidenceProvenance provenance;
};

// Middleware log entry (Tomcat, Jetty, PM2, Gunicorn, uWSGI)
struct MiddlewareLogEntry {
    int64_t timestamp = 0;
    std::string level;              // ERROR, WARN, INFO, DEBUG
    std::string source;             // Tomcat, Jetty, PM2, Gunicorn, uWSGI
    std::string logger;             // Logger name
    std::string message;
    std::string thread;
    std::string exception;          // Stack trace if present
    std::string pid;                // Process ID
    std::string filePath;           // Source log file
    NormalizedTimestamp normalizedTime;
    EvidenceProvenance provenance;
};

// ModSecurity audit log entry
struct ModSecurityAuditEntry {
    int64_t timestamp = 0;
    std::string clientIp;
    std::string method;
    std::string uri;
    std::string ruleId;
    std::string ruleMessage;
    std::string severity;
    std::string action;             // blocked, allowed, logged
    std::string filePath;
    NormalizedTimestamp normalizedTime;
    EvidenceProvenance provenance;
};

class MiddlewareLogParser {
public:
    // Apache error.log parsing
    static std::vector<WebErrorLogEntry> parseApacheErrorLog(
        const std::string& content, const std::string& filePath = "");

    // Nginx error.log parsing
    static std::vector<WebErrorLogEntry> parseNginxErrorLog(
        const std::string& content, const std::string& filePath = "");

    // PHP-FPM log parsing
    static std::vector<MiddlewareLogEntry> parsePhpFpmLog(
        const std::string& content, const std::string& filePath = "");

    // Tomcat catalina.out parsing
    static std::vector<MiddlewareLogEntry> parseTomcatLog(
        const std::string& content, const std::string& filePath = "");

    // Jetty log parsing
    static std::vector<MiddlewareLogEntry> parseJettyLog(
        const std::string& content, const std::string& filePath = "");

    // PM2 log parsing
    static std::vector<MiddlewareLogEntry> parsePm2Log(
        const std::string& content, const std::string& filePath = "");

    // Gunicorn log parsing
    static std::vector<MiddlewareLogEntry> parseGunicornLog(
        const std::string& content, const std::string& filePath = "");

    // uWSGI log parsing
    static std::vector<MiddlewareLogEntry> parseUwsgiLog(
        const std::string& content, const std::string& filePath = "");

    // ModSecurity audit.log parsing
    static std::vector<ModSecurityAuditEntry> parseModSecurityLog(
        const std::string& content, const std::string& filePath = "");

    // Auto-detect log format and parse
    static std::vector<WebErrorLogEntry> parseErrorLogAuto(
        const std::string& content, const std::string& filePath = "");

private:
    // Parse Apache error log line: [Fri Oct 06 10:23:45.123456 2023] [core:error] [pid 1234] [client 192.168.1.1:12345] AH00128: File does not exist
    static WebErrorLogEntry parseApacheErrorLine(const std::string& line, const std::string& filePath);

    // Parse Nginx error log line: 2023/10/06 10:23:45 [error] 1234#0: *5678 open() "/var/www/html/favicon.ico" failed (2: No such file or directory), client: 192.168.1.1, server: example.com
    static WebErrorLogEntry parseNginxErrorLine(const std::string& line, const std::string& filePath);

    // Parse PHP-FPM log line: [06-Oct-2023 10:23:45] PHP Fatal error: Uncaught Error: Call to undefined function foo() in /var/www/html/index.php:10
    static MiddlewareLogEntry parsePhpFpmLine(const std::string& line, const std::string& filePath);

    // Parse Tomcat log line: 06-Oct-2023 10:23:45.123 INFO [main] org.apache.catalina.startup.Catalina.start Server startup in [1234] milliseconds
    static MiddlewareLogEntry parseTomcatLine(const std::string& line, const std::string& filePath);

    // Parse timestamp from various formats
    static int64_t parseErrorLogTimestamp(const std::string& timestampStr, const std::string& format);
};

} // namespace linux
} // namespace forensics

#endif // MIDDLEWARE_LOG_PARSER_H
