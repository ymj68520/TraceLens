// ApacheParser.cpp
// Implementation of Apache web server parser

#include "ApacheParser.h"
#include "AuditLog/AuditLog.h"
#include <sstream>
#include <iomanip>
#include <ctime>
#include <algorithm>

ApacheParser::ParseResult ApacheParser::parseAccessLog(const std::string& logContent,
                                                         const std::string& logFilePath) {
    ParseResult result;
    result.success = true;

    std::istringstream stream(logContent);
    std::string line;

    int lineNum = 0;
    while (std::getline(stream, line)) {
        lineNum++;

        // Skip empty lines and comments
        if (line.empty() || line[0] == '#') {
            continue;
        }

        try {
            auto entry = parseLogLine(line, "");
            if (entry.statusCode > 0) {
                result.accessLogs.push_back(entry);
            }
        } catch (const std::exception& e) {
            result.error = "Error parsing line " + std::to_string(lineNum) + ": " + e.what();
            AuditLog::instance().log("ERROR", "APACHE_PARSE_ERROR",
                                      "Failed to parse " + logFilePath + ":" +
                                      std::to_string(lineNum) + " - " + e.what());
        }
    }

    AuditLog::instance().log("SUCCESS", "APACHE_LOG_PARSED",
                              "Parsed " + std::to_string(result.accessLogs.size()) +
                              " entries from " + logFilePath);
    return result;
}

ApacheParser::ParseResult ApacheParser::parseVHostConfigs(const std::string& configContent,
                                                            const std::string& configFilePath) {
    ParseResult result;
    result.success = true;

    // Find all VirtualHost blocks
    // Use sed-like regex to match multi-line content
    std::regex vhostRegex("<VirtualHost[^>]*>.*?</VirtualHost>",
                           std::regex_constants::icase |
                           std::regex_constants::ECMAScript |
                           std::regex_constants::optimize);

    // Use iterator with different approach for multi-line
    auto it = configContent.cbegin();
    std::regex startRegex("<VirtualHost[^>]*>", std::regex_constants::icase);
    std::regex endRegex("</VirtualHost>", std::regex_constants::icase);

    while (it != configContent.cend()) {
        // Find opening tag
        std::smatch startMatch;
        if (!std::regex_search(it, configContent.cend(), startMatch, startRegex)) {
            break;
        }

        auto startPos = startMatch[0].second;
        auto endIt = startPos;

        // Find matching closing tag
        std::smatch endMatch;
        if (!std::regex_search(endIt, configContent.cend(), endMatch, endRegex)) {
            break;
        }

        auto endPos = endMatch[0].first;
        std::string vhostBlock(startPos, endPos);

        try {
            auto vhost = parseVHostBlock(vhostBlock, configFilePath);
            if (!vhost.serverName.empty()) {
                result.vhosts.push_back(vhost);
            }
        } catch (const std::exception& e) {
            result.error = "Error parsing VirtualHost: " + std::string(e.what());
        }

        it = endMatch[0].second;
    }

    AuditLog::instance().log("SUCCESS", "APACHE_VHOST_PARSED",
                              "Parsed " + std::to_string(result.vhosts.size()) +
                              " virtual hosts from " + configFilePath);
    return result;
}

ApacheAccessLogEntry ApacheParser::parseLogLine(const std::string& line,
                                                  const std::string& vhost) {
    std::string format = detectLogFormat(line);

    if (format == "combined") {
        return parseCombinedLogLine(line, vhost);
    } else if (format == "common") {
        return parseCommonLogLine(line, vhost);
    }

    // Return empty entry if format not recognized
    ApacheAccessLogEntry entry;
    entry.vhost = vhost;
    return entry;
}

std::string ApacheParser::detectLogFormat(const std::string& line) {
    // Combined format has 2 quoted strings at end (referer, user-agent)
    // Count quoted strings
    int quoteCount = 0;
    bool inQuote = false;
    int consecutiveQuotes = 0;

    for (char c : line) {
        if (c == '"') {
            if (inQuote) {
                consecutiveQuotes++;
                inQuote = false;
            } else {
                inQuote = true;
            }
        }
    }

    // Combined format typically has 4+ quoted strings (request, referer, user-agent)
    // Simple heuristic: if we find "referer" pattern near end, it's combined
    if (line.find("\" \"") != std::string::npos) {
        size_t lastSpace = line.rfind(' ');
        if (lastSpace != std::string::npos && lastSpace > 0) {
            size_t secondLast = line.rfind(' ', lastSpace - 1);
            if (secondLast != std::string::npos && line[secondLast + 1] == '"') {
                return "combined";
            }
        }
    }

    return "common";
}

ApacheAccessLogEntry ApacheParser::parseCombinedLogLine(const std::string& line,
                                                          const std::string& vhost) {
    ApacheAccessLogEntry entry;
    entry.vhost = vhost;

    // Combined Log Format regex
    // IP - - [timestamp] "METHOD URL HTTP/Version" status size "referer" "user-agent"
    // Using escaped quotes in regex pattern
    std::regex combinedRegex(
        "^([^\\s]+)\\s+-\\s+-\\s+\\[([^\\]]+)\\]\\s+\"(\\w+)\\s+([^\\s]+)\\s+([^\"]+)\"\\s+(\\d+)\\s+(\\d+)\\s+\"([^\"]*)\"\\s+\"([^\"]*)\""
    );

    std::smatch match;
    if (std::regex_search(line, match, combinedRegex) && match.size() >= 10) {
        entry.remoteIp = match[1].str();
        entry.timestamp = parseTimestamp(match[2].str());
        entry.method = match[3].str();
        entry.url = match[4].str();
        entry.httpVersion = match[5].str();

        try {
            entry.statusCode = std::stoi(match[6].str());
        } catch (...) {
            entry.statusCode = 0;
        }

        try {
            entry.responseSize = std::stoi(match[7].str());
        } catch (...) {
            entry.responseSize = 0;
        }

        entry.referer = match[8].str();
        entry.userAgent = match[9].str();
    }

    return entry;
}

ApacheAccessLogEntry ApacheParser::parseCommonLogLine(const std::string& line,
                                                         const std::string& vhost) {
    ApacheAccessLogEntry entry;
    entry.vhost = vhost;

    // Common Log Format regex
    // IP - - [timestamp] "METHOD URL HTTP/Version" status size
    std::regex commonRegex(
        "^([^\\s]+)\\s+-\\s+-\\s+\\[([^\\]]+)\\]\\s+\"(\\w+)\\s+([^\\s]+)\\s+([^\"]+)\"\\s+(\\d+)\\s+(\\d+)"
    );

    std::smatch match;
    if (std::regex_search(line, match, commonRegex) && match.size() >= 8) {
        entry.remoteIp = match[1].str();
        entry.timestamp = parseTimestamp(match[2].str());
        entry.method = match[3].str();
        entry.url = match[4].str();
        entry.httpVersion = match[5].str();

        try {
            entry.statusCode = std::stoi(match[6].str());
        } catch (...) {
            entry.statusCode = 0;
        }

        try {
            entry.responseSize = std::stoi(match[7].str());
        } catch (...) {
            entry.responseSize = 0;
        }
    }

    return entry;
}

int64_t ApacheParser::parseTimestamp(const std::string& timestampStr) {
    // Format: [05/Oct/2023:10:23:45 +0000]
    std::tm tm = {};
    std::istringstream ss(timestampStr);

    // Remove brackets if present
    std::string cleanTs = timestampStr;
    if (!cleanTs.empty() && cleanTs[0] == '[') {
        cleanTs = cleanTs.substr(1);
    }
    if (!cleanTs.empty() && cleanTs.back() == ']') {
        cleanTs.pop_back();
    }

    // Parse format: DD/Mon/YYYY:HH:MM:SS +TZ
    // Need to handle timezone offset
    std::string dtPart = cleanTs.substr(0, 19);

    ss >> std::get_time(&tm, "%d/%b/%Y:%H:%M:%S");
    if (ss.fail()) {
        return 0;
    }

    // Convert to time_t (UTC)
    time_t time = timegm(&tm);

    // Handle timezone offset if present
    size_t tzPos = cleanTs.find(' ');
    if (tzPos != std::string::npos && tzPos + 1 < cleanTs.length()) {
        std::string tzStr = cleanTs.substr(tzPos + 1);
        if (tzStr.length() == 5 && (tzStr[0] == '+' || tzStr[0] == '-')) {
            try {
                int tzHours = std::stoi(tzStr.substr(1, 2));
                int tzMins = std::stoi(tzStr.substr(3, 2));
                int tzOffsetSec = (tzHours * 3600) + (tzMins * 60);

                if (tzStr[0] == '+') {
                    time -= tzOffsetSec;
                } else {
                    time += tzOffsetSec;
                }
            } catch (...) {
                // Ignore timezone parse errors
            }
        }
    }

    return static_cast<int64_t>(time);
}

ApacheVHostConfig ApacheParser::parseVHostBlock(const std::string& block,
                                                  const std::string& configFilePath) {
    ApacheVHostConfig vhost;
    vhost.configFilePath = configFilePath;

    vhost.serverName = extractServerName(block);
    vhost.documentRoot = extractDocumentRoot(block);
    vhost.serverAliases = extractServerAliases(block);
    vhost.sslCertificates = extractSSLCertificates(block);

    return vhost;
}

std::string ApacheParser::extractServerName(const std::string& config) {
    std::regex serverNameRegex(R"(ServerName\s+(\S+))", std::regex_constants::icase);
    std::smatch match;

    std::string::const_iterator searchStart = config.cbegin();
    if (std::regex_search(searchStart, config.cend(), match, serverNameRegex)) {
        return match[1].str();
    }

    return "";
}

std::string ApacheParser::extractDocumentRoot(const std::string& config) {
    std::regex docRootRegex(R"(DocumentRoot\s+(?:")?([^"\s]+)(?:")?)", std::regex_constants::icase);
    std::smatch match;

    std::string::const_iterator searchStart = config.cbegin();
    if (std::regex_search(searchStart, config.cend(), match, docRootRegex)) {
        return match[1].str();
    }

    return "";
}

std::vector<std::string> ApacheParser::extractServerAliases(const std::string& config) {
    std::vector<std::string> aliases;
    std::regex aliasRegex(R"(ServerAlias\s+(\S+))", std::regex_constants::icase);

    std::sregex_iterator it(config.begin(), config.end(), aliasRegex);
    std::sregex_iterator end;

    for (; it != end; ++it) {
        aliases.push_back((*it)[1].str());
    }

    return aliases;
}

std::vector<std::string> ApacheParser::extractSSLCertificates(const std::string& config) {
    std::vector<std::string> certs;

    // SSLCertificateFile
    std::regex certFileRegex(R"(SSLCertificateFile\s+(?:")?([^"\s]+)(?:")?)",
                              std::regex_constants::icase);
    std::sregex_iterator it(config.begin(), config.end(), certFileRegex);
    std::sregex_iterator end;

    for (; it != end; ++it) {
        certs.push_back((*it)[1].str());
    }

    return certs;
}
