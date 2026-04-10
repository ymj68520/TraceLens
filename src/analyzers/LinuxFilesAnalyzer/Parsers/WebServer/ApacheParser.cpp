// ApacheParser.cpp
// Implementation of Apache web server parser

#include "ApacheParser.h"
#include "AuditLog/AuditLog.h"
#include <sstream>
#include <iomanip>
#include <ctime>
#include <algorithm>

ApacheParser::ParseResult ApacheParser::parseAccessLog(const std::string& logContent, const std::string& logFilePath) {
    ParseResult result;
    result.success = true;
    std::istringstream stream(logContent);
    std::string line;
    int lineNum = 0;

    while (std::getline(stream, line)) {
        lineNum++;
        if (line.empty() || line[0] == '#') continue;

        try {
            auto entry = parseLogLine(line, "");
            if (entry.statusCode > 0) result.accessLogs.push_back(entry);
        } catch (const std::exception& e) {
            result.error = "Error parsing line " + std::to_string(lineNum) + ": " + e.what();
            AuditLog::instance().log("ERROR", "APACHE_PARSE_ERROR",
                "Failed to parse " + logFilePath + ":" + std::to_string(lineNum) + " - " + e.what());
        }
    }

    AuditLog::instance().log("SUCCESS", "APACHE_LOG_PARSED",
        "Parsed " + std::to_string(result.accessLogs.size()) + " entries from " + logFilePath);
    return result;
}

ApacheParser::ParseResult ApacheParser::parseVHostConfigs(const std::string& configContent, const std::string& configFilePath) {
    ParseResult result;
    result.success = true;
    std::regex startRegex("<VirtualHost[^>]*>", std::regex_constants::icase);
    std::regex endRegex("</VirtualHost>", std::regex_constants::icase);
    auto it = configContent.cbegin();

    while (it != configContent.cend()) {
        std::smatch startMatch, endMatch;
        if (!std::regex_search(it, configContent.cend(), startMatch, startRegex)) break;

        auto startPos = startMatch[0].second, endIt = startPos;
        if (!std::regex_search(endIt, configContent.cend(), endMatch, endRegex)) break;

        auto endPos = endMatch[0].first;
        std::string vhostBlock(startPos, endPos);

        try {
            auto vhost = parseVHostBlock(vhostBlock, configFilePath);
            if (!vhost.serverName.empty()) result.vhosts.push_back(vhost);
        } catch (const std::exception& e) {
            result.error = "Error parsing VirtualHost: " + std::string(e.what());
        }

        it = endMatch[0].second;
    }

    AuditLog::instance().log("SUCCESS", "APACHE_VHOST_PARSED",
        "Parsed " + std::to_string(result.vhosts.size()) + " virtual hosts from " + configFilePath);
    return result;
}

ApacheAccessLogEntry ApacheParser::parseLogLine(const std::string& line, const std::string& vhost) {
    ApacheAccessLogEntry entry;
    entry.vhost = vhost;

    // Combined regex pattern (handles both combined and common formats)
    std::regex logRegex("^([^\\s]+)\\s+-\\s+-\\s+\\[([^\\]]+)\\]\\s+\"(\\w+)\\s+([^\\s]+)\\s+([^\"]+)\"\\s+(\\d+)\\s+(\\d+)(?:\\s+\"([^\"]*)\"\\s+\"([^\"]*)\")?");
    std::smatch match;

    if (std::regex_search(line, match, logRegex) && match.size() >= 8) {
        entry.remoteIp = match[1].str();
        entry.timestamp = parseTimestamp(match[2].str());
        entry.method = match[3].str();
        entry.url = match[4].str();
        entry.httpVersion = match[5].str();

        try { entry.statusCode = std::stoi(match[6].str()); } catch (...) { entry.statusCode = 0; }
        try { entry.responseSize = std::stoi(match[7].str()); } catch (...) { entry.responseSize = 0; }
        if (match.size() >= 10) { entry.referer = match[8].str(); entry.userAgent = match[9].str(); }
    }

    return entry;
}

int64_t ApacheParser::parseTimestamp(const std::string& timestampStr) {
    std::tm tm = {};
    std::istringstream ss(timestampStr);
    std::string cleanTs = timestampStr;

    if (!cleanTs.empty() && cleanTs[0] == '[') cleanTs = cleanTs.substr(1);
    if (!cleanTs.empty() && cleanTs.back() == ']') cleanTs.pop_back();

    ss >> std::get_time(&tm, "%d/%b/%Y:%H:%M:%S");
    if (ss.fail()) return 0;

    time_t time = timegm(&tm);
    size_t tzPos = cleanTs.find(' ');

    if (tzPos != std::string::npos && tzPos + 1 < cleanTs.length()) {
        std::string tzStr = cleanTs.substr(tzPos + 1);
        if (tzStr.length() == 5 && (tzStr[0] == '+' || tzStr[0] == '-')) {
            try {
                int tzHours = std::stoi(tzStr.substr(1, 2)), tzMins = std::stoi(tzStr.substr(3, 2));
                int tzOffsetSec = (tzHours * 3600) + (tzMins * 60);
                time += (tzStr[0] == '+') ? -tzOffsetSec : tzOffsetSec;
            } catch (...) { }
        }
    }

    return static_cast<int64_t>(time);
}

ApacheVHostConfig ApacheParser::parseVHostBlock(const std::string& block, const std::string& configFilePath) {
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
    if (std::regex_search(config.cbegin(), config.cend(), match, serverNameRegex)) return match[1].str();
    return "";
}

std::string ApacheParser::extractDocumentRoot(const std::string& config) {
    std::regex docRootRegex(R"(DocumentRoot\s+(?:")?([^"\s]+)(?:")?)", std::regex_constants::icase);
    std::smatch match;
    if (std::regex_search(config.cbegin(), config.cend(), match, docRootRegex)) return match[1].str();
    return "";
}

std::vector<std::string> ApacheParser::extractServerAliases(const std::string& config) {
    std::vector<std::string> aliases;
    std::regex aliasRegex(R"(ServerAlias\s+(\S+))", std::regex_constants::icase);
    std::sregex_iterator it(config.begin(), config.end(), aliasRegex), end;
    for (; it != end; ++it) aliases.push_back((*it)[1].str());
    return aliases;
}

std::vector<std::string> ApacheParser::extractSSLCertificates(const std::string& config) {
    std::vector<std::string> certs;
    std::regex certFileRegex(R"(SSLCertificateFile\s+(?:")?([^"\s]+)(?:")?)", std::regex_constants::icase);
    std::sregex_iterator it(config.begin(), config.end(), certFileRegex), end;
    for (; it != end; ++it) certs.push_back((*it)[1].str());
    return certs;
}
