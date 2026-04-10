// NginxParser.cpp
// Implementation of Nginx web server parser

#include "NginxParser.h"
#include "AuditLog/AuditLog.h"
#include <sstream>
#include <iomanip>
#include <ctime>
#include <algorithm>

NginxParser::ParseResult NginxParser::parseAccessLog(const std::string& logContent,
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
            auto entry = parseLogLine(line);
            if (entry.statusCode > 0) {
                result.accessLogs.push_back(entry);
            }
        } catch (const std::exception& e) {
            result.error = "Error parsing line " + std::to_string(lineNum) + ": " + e.what();
            AuditLog::instance().log("ERROR", "NGINX_PARSE_ERROR",
                                      "Failed to parse " + logFilePath + ":" +
                                      std::to_string(lineNum) + " - " + e.what());
        }
    }

    AuditLog::instance().log("SUCCESS", "NGINX_LOG_PARSED",
                              "Parsed " + std::to_string(result.accessLogs.size()) +
                              " entries from " + logFilePath);
    return result;
}

NginxParser::ParseResult NginxParser::parseServerBlocks(const std::string& configContent,
                                                          const std::string& configFilePath) {
    ParseResult result;
    result.success = true;

    // Find all server blocks
    // Nginx uses braces {} for blocks
    std::vector<size_t> serverStarts;
    std::vector<size_t> serverEnds;

    size_t pos = 0;
    while (pos < configContent.length()) {
        size_t serverPos = configContent.find("server", pos);
        if (serverPos == std::string::npos) {
            break;
        }

        // Check if it's actually "server {" (not "server_name" etc)
        size_t bracePos = configContent.find('{', serverPos);
        if (bracePos != std::string::npos && bracePos - serverPos < 20) {
            // Find matching closing brace
            int braceCount = 0;
            bool foundOpening = false;
            for (size_t i = bracePos; i < configContent.length(); i++) {
                if (configContent[i] == '{') {
                    braceCount++;
                    foundOpening = true;
                } else if (configContent[i] == '}') {
                    braceCount--;
                    if (braceCount == 0 && foundOpening) {
                        serverStarts.push_back(serverPos);
                        serverEnds.push_back(i + 1);
                        pos = i + 1;
                        break;
                    }
                }
            }
        } else {
            pos = serverPos + 6;
        }
    }

    // Extract and parse each server block
    for (size_t i = 0; i < serverStarts.size(); i++) {
        try {
            std::string block = configContent.substr(serverStarts[i],
                                                      serverEnds[i] - serverStarts[i]);
            auto serverBlock = parseServerBlock(block, configFilePath);
            if (!serverBlock.serverName.empty()) {
                result.serverBlocks.push_back(serverBlock);
            }
        } catch (const std::exception& e) {
            result.error = "Error parsing server block: " + std::string(e.what());
        }
    }

    AuditLog::instance().log("SUCCESS", "NGINX_SERVER_PARSED",
                              "Parsed " + std::to_string(result.serverBlocks.size()) +
                              " server blocks from " + configFilePath);
    return result;
}

NginxAccessLogEntry NginxParser::parseLogLine(const std::string& line) {
    return parseDefaultLogLine(line);
}

NginxAccessLogEntry NginxParser::parseCustomLogLine(const std::string& line,
                                                      const std::regex& pattern) {
    NginxAccessLogEntry entry;

    std::smatch match;
    if (std::regex_search(line, match, pattern)) {
        if (match.size() > 1) entry.remoteIp = match[1].str();
        if (match.size() > 2) entry.timestamp = parseTimestamp(match[2].str());
        if (match.size() > 3) entry.method = match[3].str();
        if (match.size() > 4) entry.url = match[4].str();
        if (match.size() > 5) {
            try {
                entry.statusCode = std::stoi(match[5].str());
            } catch (...) {
                entry.statusCode = 0;
            }
        }
        if (match.size() > 6) {
            try {
                entry.responseSize = std::stoi(match[6].str());
            } catch (...) {
                entry.responseSize = 0;
            }
        }
        if (match.size() > 7) entry.referer = match[7].str();
        if (match.size() > 8) entry.userAgent = match[8].str();
        if (match.size() > 9) {
            try {
                entry.requestTime = std::stof(match[9].str());
            } catch (...) {
                entry.requestTime = 0.0f;
            }
        }
    }

    return entry;
}

NginxAccessLogEntry NginxParser::parseDefaultLogLine(const std::string& line) {
    NginxAccessLogEntry entry;

    // Nginx default format (similar to Apache Combined)
    // IP - - [timestamp] "METHOD URL HTTP/Version" status size "referer" "user-agent"
    std::regex defaultRegex(
        "^([^\\s]+)\\s+-\\s+-\\s+\\[([^\\]]+)\\]\\s+\"(\\w+)\\s+([^\\s]+)\\s+([^\"]+)\"\\s+(\\d+)\\s+(\\d+)\\s+\"([^\"]*)\"\\s+\"([^\"]*)\""
    );

    std::smatch match;
    if (std::regex_search(line, match, defaultRegex) && match.size() >= 10) {
        entry.remoteIp = match[1].str();
        entry.timestamp = parseTimestamp(match[2].str());
        entry.method = match[3].str();
        entry.url = match[4].str();

        // Skip HTTP version (not stored in NginxAccessLogEntry)

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

        // Nginx may include request time at end (if using custom format)
        // Default format doesn't have it, so requestTime stays 0.0
    }

    return entry;
}

int64_t NginxParser::parseTimestamp(const std::string& timestampStr) {
    // Same format as Apache: [05/Oct/2023:10:23:45 +0000]
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

NginxServerBlock NginxParser::parseServerBlock(const std::string& block,
                                                 const std::string& configFilePath) {
    NginxServerBlock serverBlock;
    serverBlock.configFilePath = configFilePath;

    serverBlock.serverName = extractServerName(block);
    serverBlock.root = extractRoot(block);
    serverBlock.locations = extractLocations(block);
    serverBlock.upstreams = extractUpstreams(block);
    serverBlock.sslCertificate = extractSSLCertificate(block);
    serverBlock.sslCertificateKey = extractSSLCertificateKey(block);

    return serverBlock;
}

std::string NginxParser::extractServerName(const std::string& config) {
    std::regex serverNameRegex(R"(server_name\s+([^;]+);)");
    std::smatch match;

    std::string::const_iterator searchStart = config.cbegin();
    if (std::regex_search(searchStart, config.cend(), match, serverNameRegex)) {
        std::string name = match[1].str();
        // Trim whitespace
        size_t start = name.find_first_not_of(" \t");
        size_t end = name.find_last_not_of(" \t");
        if (start != std::string::npos && end != std::string::npos) {
            return name.substr(start, end - start + 1);
        }
    }

    return "";
}

std::string NginxParser::extractRoot(const std::string& config) {
    std::regex rootRegex(R"(root\s+([^;]+);)");
    std::smatch match;

    std::string::const_iterator searchStart = config.cbegin();
    if (std::regex_search(searchStart, config.cend(), match, rootRegex)) {
        std::string rootPath = match[1].str();
        // Trim whitespace and quotes
        size_t start = rootPath.find_first_not_of(" \t\"");
        size_t end = rootPath.find_last_not_of(" \t\"");
        if (start != std::string::npos && end != std::string::npos) {
            return rootPath.substr(start, end - start + 1);
        }
    }

    return "";
}

std::vector<std::string> NginxParser::extractLocations(const std::string& config) {
    std::vector<std::string> locations;

    // Find location blocks
    std::regex locationRegex(R"(location\s+([^{\s]+))");
    std::sregex_iterator it(config.begin(), config.end(), locationRegex);
    std::sregex_iterator end;

    for (; it != end; ++it) {
        std::string locationPath = (*it)[1].str();
        // Trim whitespace
        size_t start = locationPath.find_first_not_of(" \t");
        size_t end = locationPath.find_last_not_of(" \t");
        if (start != std::string::npos && end != std::string::npos) {
            locations.push_back(locationPath.substr(start, end - start + 1));
        }
    }

    return locations;
}

std::vector<std::string> NginxParser::extractUpstreams(const std::string& config) {
    std::vector<std::string> upstreams;

    // Find upstream blocks referenced in this server
    std::regex proxyRegex(R"(proxy_pass\s+(?:http://)?([^;]+);)");
    std::sregex_iterator it(config.begin(), config.end(), proxyRegex);
    std::sregex_iterator end;

    for (; it != end; ++it) {
        std::string upstream = (*it)[1].str();
        // Trim whitespace
        size_t start = upstream.find_first_not_of(" \t");
        size_t end = upstream.find_last_not_of(" \t");
        if (start != std::string::npos && end != std::string::npos) {
            upstreams.push_back(upstream.substr(start, end - start + 1));
        }
    }

    return upstreams;
}

std::string NginxParser::extractSSLCertificate(const std::string& config) {
    std::regex certRegex(R"(ssl_certificate\s+([^;]+);)");
    std::smatch match;

    std::string::const_iterator searchStart = config.cbegin();
    if (std::regex_search(searchStart, config.cend(), match, certRegex)) {
        std::string certPath = match[1].str();
        // Trim whitespace and quotes
        size_t start = certPath.find_first_not_of(" \t\"");
        size_t end = certPath.find_last_not_of(" \t\"");
        if (start != std::string::npos && end != std::string::npos) {
            return certPath.substr(start, end - start + 1);
        }
    }

    return "";
}

std::string NginxParser::extractSSLCertificateKey(const std::string& config) {
    std::regex keyRegex(R"(ssl_certificate_key\s+([^;]+);)");
    std::smatch match;

    std::string::const_iterator searchStart = config.cbegin();
    if (std::regex_search(searchStart, config.cend(), match, keyRegex)) {
        std::string keyPath = match[1].str();
        // Trim whitespace and quotes
        size_t start = keyPath.find_first_not_of(" \t\"");
        size_t end = keyPath.find_last_not_of(" \t\"");
        if (start != std::string::npos && end != std::string::npos) {
            return keyPath.substr(start, end - start + 1);
        }
    }

    return "";
}
