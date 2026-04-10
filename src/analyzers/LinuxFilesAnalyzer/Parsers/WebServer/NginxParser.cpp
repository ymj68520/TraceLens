// NginxParser.cpp
// Implementation of Nginx web server parser

#include "NginxParser.h"
#include "AuditLog/AuditLog.h"
#include <sstream>
#include <iomanip>
#include <ctime>
#include <algorithm>

namespace {
    std::string trim(const std::string& str) {
        size_t start = str.find_first_not_of(" \t\"");
        size_t end = str.find_last_not_of(" \t\"");
        return (start != std::string::npos && end != std::string::npos) ? str.substr(start, end - start + 1) : "";
    }

    int64_t parseTimestamp(const std::string& ts) {
        std::tm tm = {};
        std::istringstream ss(ts);
        std::string clean = ts;
        if (!clean.empty() && clean[0] == '[') clean = clean.substr(1);
        if (!clean.empty() && clean.back() == ']') clean.pop_back();
        ss >> std::get_time(&tm, "%d/%b/%Y:%H:%M:%S");
        if (ss.fail()) return 0;
        time_t time = timegm(&tm);
        size_t tzPos = clean.find(' ');
        if (tzPos != std::string::npos && tzPos + 1 < clean.length()) {
            std::string tzStr = clean.substr(tzPos + 1);
            if (tzStr.length() == 5 && (tzStr[0] == '+' || tzStr[0] == '-')) {
                try {
                    int tzHours = std::stoi(tzStr.substr(1, 2)), tzMins = std::stoi(tzStr.substr(3, 2));
                    time += (tzStr[0] == '+') ? -(tzHours * 3600 + tzMins * 60) : (tzHours * 3600 + tzMins * 60);
                } catch (...) { }
            }
        }
        return static_cast<int64_t>(time);
    }

    std::string extractSingle(const std::string& config, const std::string& pattern) {
        std::regex r(pattern);
        std::smatch match;
        return std::regex_search(config.cbegin(), config.cend(), match, r) ? trim(match[1].str()) : "";
    }

    std::vector<std::string> extractMulti(const std::string& config, const std::string& pattern) {
        std::vector<std::string> results;
        std::regex r(pattern);
        std::sregex_iterator it(config.begin(), config.end(), r), end;
        for (; it != end; ++it) results.push_back(trim((*it)[1].str()));
        return results;
    }
}

NginxParser::ParseResult NginxParser::parseAccessLog(const std::string& logContent, const std::string& logFilePath) {
    ParseResult result;
    result.success = true;
    std::istringstream stream(logContent);
    std::string line;
    int lineNum = 0;

    while (std::getline(stream, line)) {
        lineNum++;
        if (line.empty() || line[0] == '#') continue;
        try {
            auto entry = parseLogLine(line);
            if (entry.statusCode > 0) result.accessLogs.push_back(entry);
        } catch (const std::exception& e) {
            result.error = "Error parsing line " + std::to_string(lineNum) + ": " + e.what();
            AuditLog::instance().log("ERROR", "NGINX_PARSE_ERROR", "Failed to parse " + logFilePath + ":" + std::to_string(lineNum) + " - " + e.what());
        }
    }

    AuditLog::instance().log("SUCCESS", "NGINX_LOG_PARSED", "Parsed " + std::to_string(result.accessLogs.size()) + " entries from " + logFilePath);
    return result;
}

NginxParser::ParseResult NginxParser::parseServerBlocks(const std::string& configContent, const std::string& configFilePath) {
    ParseResult result;
    result.success = true;
    std::vector<size_t> serverStarts, serverEnds;
    size_t pos = 0;

    while (pos < configContent.length()) {
        size_t serverPos = configContent.find("server", pos);
        if (serverPos == std::string::npos) break;
        size_t bracePos = configContent.find('{', serverPos);
        if (bracePos != std::string::npos && bracePos - serverPos < 20) {
            int braceCount = 0;
            bool foundOpening = false;
            for (size_t i = bracePos; i < configContent.length(); i++) {
                if (configContent[i] == '{') { braceCount++; foundOpening = true; }
                else if (configContent[i] == '}' && --braceCount == 0 && foundOpening) {
                    serverStarts.push_back(serverPos);
                    serverEnds.push_back(i + 1);
                    pos = i + 1;
                    break;
                }
            }
        } else {
            pos = serverPos + 6;
        }
    }

    for (size_t i = 0; i < serverStarts.size(); i++) {
        try {
            std::string block = configContent.substr(serverStarts[i], serverEnds[i] - serverStarts[i]);
            auto serverBlock = parseServerBlock(block, configFilePath);
            if (!serverBlock.serverName.empty()) result.serverBlocks.push_back(serverBlock);
        } catch (const std::exception& e) {
            result.error = "Error parsing server block: " + std::string(e.what());
        }
    }

    AuditLog::instance().log("SUCCESS", "NGINX_SERVER_PARSED", "Parsed " + std::to_string(result.serverBlocks.size()) + " server blocks from " + configFilePath);
    return result;
}

NginxAccessLogEntry NginxParser::parseLogLine(const std::string& line) {
    NginxAccessLogEntry entry;
    std::regex logRegex("^([^\\s]+)\\s+-\\s+-\\s+\\[([^\\]]+)\\]\\s+\"(\\w+)\\s+([^\\s]+)\\s+([^\"]+)\"\\s+(\\d+)\\s+(\\d+)(?:\\s+\"([^\"]*)\"\\s+\"([^\"]*)\")?");
    std::smatch match;

    if (std::regex_search(line, match, logRegex) && match.size() >= 8) {
        entry.remoteIp = match[1].str();
        entry.timestamp = ::parseTimestamp(match[2].str());
        entry.method = match[3].str();
        entry.url = match[4].str();
        try { entry.statusCode = std::stoi(match[6].str()); } catch (...) { entry.statusCode = 0; }
        try { entry.responseSize = std::stoi(match[7].str()); } catch (...) { entry.responseSize = 0; }
        if (match.size() >= 10) { entry.referer = match[8].str(); entry.userAgent = match[9].str(); }
    }

    return entry;
}

NginxAccessLogEntry NginxParser::parseCustomLogLine(const std::string& line, const std::regex& pattern) {
    NginxAccessLogEntry entry;
    std::smatch match;
    if (std::regex_search(line, match, pattern)) {
        if (match.size() > 1) entry.remoteIp = match[1].str();
        if (match.size() > 2) entry.timestamp = ::parseTimestamp(match[2].str());
        if (match.size() > 3) entry.method = match[3].str();
        if (match.size() > 4) entry.url = match[4].str();
        if (match.size() > 5) { try { entry.statusCode = std::stoi(match[5].str()); } catch (...) { entry.statusCode = 0; } }
        if (match.size() > 6) { try { entry.responseSize = std::stoi(match[6].str()); } catch (...) { entry.responseSize = 0; } }
        if (match.size() > 7) entry.referer = match[7].str();
        if (match.size() > 8) entry.userAgent = match[8].str();
        if (match.size() > 9) { try { entry.requestTime = std::stof(match[9].str()); } catch (...) { entry.requestTime = 0.0f; } }
    }
    return entry;
}

int64_t NginxParser::parseTimestamp(const std::string& timestampStr) { return ::parseTimestamp(timestampStr); }

NginxServerBlock NginxParser::parseServerBlock(const std::string& block, const std::string& configFilePath) {
    NginxServerBlock sb;
    sb.configFilePath = configFilePath;
    sb.serverName = extractServerName(block);
    sb.root = extractRoot(block);
    sb.locations = extractLocations(block);
    sb.upstreams = extractUpstreams(block);
    sb.sslCertificate = extractSSLCertificate(block);
    sb.sslCertificateKey = extractSSLCertificateKey(block);
    return sb;
}

std::string NginxParser::extractServerName(const std::string& config) { return extractSingle(config, R"(server_name\s+([^;]+);)"); }
std::string NginxParser::extractRoot(const std::string& config) { return extractSingle(config, R"(root\s+([^;]+);)"); }
std::vector<std::string> NginxParser::extractLocations(const std::string& config) { return extractMulti(config, R"(location\s+([^{\s]+))"); }
std::vector<std::string> NginxParser::extractUpstreams(const std::string& config) { return extractMulti(config, R"(proxy_pass\s+(?:http://)?([^;]+);)"); }
std::string NginxParser::extractSSLCertificate(const std::string& config) { return extractSingle(config, R"(ssl_certificate\s+([^;]+);)"); }
std::string NginxParser::extractSSLCertificateKey(const std::string& config) { return extractSingle(config, R"(ssl_certificate_key\s+([^;]+);)"); }
