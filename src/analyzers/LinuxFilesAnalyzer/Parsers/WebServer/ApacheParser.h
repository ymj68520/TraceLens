// ApacheParser.h
// Apache web server log and configuration parser

#pragma once
#ifndef APACHE_PARSER_H
#define APACHE_PARSER_H

#include <string>
#include <vector>
#include <regex>
#include "Common/LinuxDataTypes.h"

// Apache web server parser
class ApacheParser {
public:
    // Parse result structure
    struct ParseResult {
        std::vector<ApacheAccessLogEntry> accessLogs;
        std::vector<ApacheVHostConfig> vhosts;
        std::string error;
        bool success = true;
    };

    // Parse Apache access log file
    // Supports Combined Log Format and Common Log Format
    static ParseResult parseAccessLog(const std::string& logContent,
                                       const std::string& logFilePath = "");

    // Parse Apache virtual host configuration files
    // Searches for <VirtualHost> blocks and extracts key directives
    static ParseResult parseVHostConfigs(const std::string& configContent,
                                          const std::string& configFilePath = "");

    // Parse a single access log line (supports both Combined and Common formats)
    static ApacheAccessLogEntry parseLogLine(const std::string& line,
                                              const std::string& vhost = "");

private:
    // Convert Apache timestamp to Unix timestamp
    // Format: [05/Oct/2023:10:23:45 +0000]
    static int64_t parseTimestamp(const std::string& timestampStr);

    // Parse VirtualHost block from Apache config
    static ApacheVHostConfig parseVHostBlock(const std::string& block,
                                              const std::string& configFilePath);

    // Extract ServerName directive
    static std::string extractServerName(const std::string& config);

    // Extract DocumentRoot directive
    static std::string extractDocumentRoot(const std::string& config);

    // Extract ServerAlias directives
    static std::vector<std::string> extractServerAliases(const std::string& config);

    // Extract SSL certificate directives
    static std::vector<std::string> extractSSLCertificates(const std::string& config);
};

#endif // APACHE_PARSER_H
