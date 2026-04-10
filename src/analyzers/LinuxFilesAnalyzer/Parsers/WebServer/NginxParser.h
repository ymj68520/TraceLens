// NginxParser.h
// Nginx web server log and configuration parser

#pragma once
#ifndef NGINX_PARSER_H
#define NGINX_PARSER_H

#include <string>
#include <vector>
#include <regex>
#include "Common/LinuxDataTypes.h"

// Nginx web server parser
class NginxParser {
public:
    // Parse result structure
    struct ParseResult {
        std::vector<NginxAccessLogEntry> accessLogs;
        std::vector<NginxServerBlock> serverBlocks;
        std::string error;
        bool success = true;
    };

    // Parse Nginx access log file (default format)
    // Default format similar to Apache Combined but with request time
    static ParseResult parseAccessLog(const std::string& logContent,
                                       const std::string& logFilePath = "");

    // Parse Nginx server block configurations
    // Extracts server_name, root, locations, upstreams, SSL settings
    static ParseResult parseServerBlocks(const std::string& configContent,
                                          const std::string& configFilePath = "");

    // Parse a single access log line (default format)
    static NginxAccessLogEntry parseLogLine(const std::string& line);

    // Parse custom log format using regex pattern
    static NginxAccessLogEntry parseCustomLogLine(const std::string& line,
                                                    const std::regex& pattern);

private:
    // Parse Nginx default log format
    // Format: IP - - [timestamp] "METHOD URL HTTP/Version" status size "referer" "user-agent" request_time
    static NginxAccessLogEntry parseDefaultLogLine(const std::string& line);

    // Convert Nginx timestamp to Unix timestamp (same as Apache format)
    static int64_t parseTimestamp(const std::string& timestampStr);

    // Parse server block from Nginx config
    static NginxServerBlock parseServerBlock(const std::string& block,
                                              const std::string& configFilePath);

    // Extract server_name directive
    static std::string extractServerName(const std::string& config);

    // Extract root directive
    static std::string extractRoot(const std::string& config);

    // Extract location blocks
    static std::vector<std::string> extractLocations(const std::string& config);

    // Extract upstream blocks
    static std::vector<std::string> extractUpstreams(const std::string& config);

    // Extract SSL certificate directives
    static std::string extractSSLCertificate(const std::string& config);

    // Extract SSL certificate key directive
    static std::string extractSSLCertificateKey(const std::string& config);
};

#endif // NGINX_PARSER_H
