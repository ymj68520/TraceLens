// SELinuxAnalyzer.cpp
// Implementation of SELinux analyzer

#include "SELinuxAnalyzer.h"
#include "AuditLog/AuditLog.h"
#include <fstream>
#include <sstream>
#include <regex>
#include <algorithm>

namespace LinuxAnalysis {

SELinuxAnalyzer::AnalysisResult SELinuxAnalyzer::parseStatus(const std::string& configPath) {
    AnalysisResult result;
    result.success = true;

    std::ifstream file(configPath);
    if (!file.is_open()) {
        result.success = false;
        result.error = LinuxAnalyzerError(ErrorCode::SELINUX_NOT_ENABLED,
            "Cannot open SELinux config: " + configPath);
        AuditLog::instance().log("ERROR", "SELINUX_CONFIG_NOT_FOUND",
            "Failed to open " + configPath);
        return result;
    }

    std::string line;
    while (std::getline(file, line)) {
        // Skip comments and empty lines
        if (line.empty() || line[0] == '#') continue;

        SELinuxAnalyzer::parseConfigLine(line, result.status);
    }

    // Determine if SELinux is enabled
    result.status.isEnabled = (result.status.mode != "disabled" &&
                                !result.status.mode.empty());

    AuditLog::instance().log("SUCCESS", "SELINUX_STATUS_PARSED",
        "SELinux mode: " + result.status.mode + ", policy: " + result.status.policyName);

    return result;
}

SELinuxAnalyzer::AnalysisResult SELinuxAnalyzer::parseStatusFromContent(const std::string& configContent) {
    AnalysisResult result;
    result.success = true;

    std::istringstream stream(configContent);
    std::string line;
    while (std::getline(stream, line)) {
        // Skip comments and empty lines
        if (line.empty() || line[0] == '#') continue;

        SELinuxAnalyzer::parseConfigLine(line, result.status);
    }

    // Determine if SELinux is enabled
    result.status.isEnabled = (result.status.mode != "disabled" &&
                                !result.status.mode.empty());

    return result;
}

SELinuxAnalyzer::AnalysisResult SELinuxAnalyzer::extractAVCDenials(const std::string& auditLogPath) {
    AnalysisResult result;
    result.success = true;

    std::ifstream file(auditLogPath);
    if (!file.is_open()) {
        result.success = false;
        result.error = LinuxAnalyzerError(ErrorCode::FILE_NOT_FOUND,
            "Cannot open audit log: " + auditLogPath);
        AuditLog::instance().log("ERROR", "AUDIT_LOG_NOT_FOUND",
            "Failed to open " + auditLogPath);
        return result;
    }

    std::string line;
    int lineNum = 0;
    int denialCount = 0;

    while (std::getline(file, line)) {
        lineNum++;

        // Look for AVC denials
        if (line.find("type=AVC") != std::string::npos &&
            line.find("denied") != std::string::npos) {

            try {
                SELinuxAVCDenial denial = parseAVCDenialLine(line);
                if (!denial.permission.empty()) {
                    result.avcDenials.push_back(denial);
                    denialCount++;
                }
            } catch (const std::exception& e) {
                AuditLog::instance().log("WARNING", "SELINUX_AVC_PARSE_WARNING",
                    "Failed to parse line " + std::to_string(lineNum) + ": " + e.what());
            }
        }
    }

    AuditLog::instance().log("SUCCESS", "SELINUX_AVC_EXTRACTED",
        "Extracted " + std::to_string(denialCount) + " AVC denials from " + auditLogPath);

    return result;
}

SELinuxAnalyzer::AnalysisResult SELinuxAnalyzer::extractAVCDenialsFromContent(const std::string& auditLogContent) {
    AnalysisResult result;
    result.success = true;

    std::istringstream stream(auditLogContent);
    std::string line;
    int lineNum = 0;
    int denialCount = 0;

    while (std::getline(stream, line)) {
        lineNum++;

        // Look for AVC denials
        if (line.find("type=AVC") != std::string::npos &&
            line.find("denied") != std::string::npos) {

            try {
                SELinuxAVCDenial denial = parseAVCDenialLine(line);
                if (!denial.permission.empty()) {
                    result.avcDenials.push_back(denial);
                    denialCount++;
                }
            } catch (const std::exception& e) {
                AuditLog::instance().log("WARNING", "SELINUX_AVC_PARSE_WARNING",
                    "Failed to parse line " + std::to_string(lineNum) + ": " + e.what());
            }
        }
    }

    return result;
}

SELinuxAVCDenial SELinuxAnalyzer::parseAVCDenialLine(const std::string& line) {
    SELinuxAVCDenial denial;

    // Extract timestamp
    denial.timestamp = SELinuxAnalyzer::extractAuditTimestamp(line);

    // Find the AVC message part
    size_t avcPos = line.find("avc:");
    if (avcPos != std::string::npos) {
        std::string avcMessage = line.substr(avcPos);
        SELinuxAnalyzer::parseAVCMessage(avcMessage, denial);
    }

    return denial;
}

bool SELinuxAnalyzer::isEnabled(const SELinuxStatus& status) {
    return status.isEnabled;
}

bool SELinuxAnalyzer::isEnforcing(const SELinuxStatus& status) {
    return (status.mode == "enforcing");
}

void SELinuxAnalyzer::parseConfigLine(const std::string& line, SELinuxStatus& status) {
    // Parse KEY=value format
    std::regex pattern(R"(^(\w+)\s*=\s*(.+)$)");
    std::smatch match;

    if (std::regex_search(line, match, pattern) && match.size() >= 3) {
        std::string key = match[1].str();
        std::string value = match[2].str();

        // Trim value
        size_t start = value.find_first_not_of(" \t\"");
        size_t end = value.find_last_not_of(" \t\"");
        if (start != std::string::npos && end != std::string::npos) {
            value = value.substr(start, end - start + 1);
        }

        if (key == "SELINUX") {
            status.mode = value;
        } else if (key == "SELINUXTYPE") {
            status.policyName = value;
        }
    }
}

int64_t SELinuxAnalyzer::extractAuditTimestamp(const std::string& line) {
    // Extract timestamp from audit message
    // Format: type=AVC msg=audit(1234567890.123:456):
    std::regex pattern(R"(msg=audit\((\d+)\.\d+:\d+\))");
    std::smatch match;

    if (std::regex_search(line, match, pattern) && match.size() >= 2) {
        try {
            return std::stoll(match[1].str());
        } catch (...) {
            return 0;
        }
    }

    return 0;
}

bool SELinuxAnalyzer::parseAVCMessage(const std::string& message, SELinuxAVCDenial& denial) {
    // Extract fields from AVC denial message
    // Example: avc: denied { read } for pid=1234 comm="httpd" path="/var/www/html/secret"
    //          scontext=system_u:system_r:httpd_t:s0 tcontext=system_u:object_r:user_home_t:s0 tclass=file

    denial.sourceContext = extractAVCField(message, "scontext");
    denial.targetContext = extractAVCField(message, "tcontext");
    denial.objectClass = extractAVCField(message, "tclass");
    denial.executablePath = extractAVCField(message, "path");

    // Extract permission (what was denied)
    // Format: denied { read } or denied { open write }
    std::regex permRegex(R"(denied\s*\{\s*([^}]+)\s*\})");
    std::smatch permMatch;
    if (std::regex_search(message, permMatch, permRegex) && permMatch.size() >= 2) {
        denial.permission = permMatch[1].str();
        // Trim trailing spaces
        while (!denial.permission.empty() && denial.permission.back() == ' ') {
            denial.permission.pop_back();
        }
    }

    // Extract comm (executable name) if path not available
    if (denial.executablePath.empty()) {
        denial.executablePath = extractAVCField(message, "comm");
        // Remove quotes if present
        if (!denial.executablePath.empty() && denial.executablePath[0] == '"') {
            denial.executablePath = denial.executablePath.substr(1, denial.executablePath.length() - 2);
        }
    }

    return !denial.permission.empty();
}

std::string SELinuxAnalyzer::extractAVCField(const std::string& message, const std::string& key) {
    // Extract key=value from AVC message
    // e.g., scontext="system_u:system_r:httpd_t:s0"
    std::string patternStr = key + R"DELIM(="([^"]*)")DELIM" + R"DELIM(|)DELIM" + key + R"DELIM(=([^\s]+))DELIM";
    std::regex pattern(patternStr);
    std::smatch match;

    if (std::regex_search(message, match, pattern)) {
        // Return first non-empty capture group
        for (size_t i = 1; i < match.size(); ++i) {
            if (match[i].matched && !match[i].str().empty()) {
                return match[i].str();
            }
        }
    }

    return "";
}

} // namespace LinuxAnalysis
