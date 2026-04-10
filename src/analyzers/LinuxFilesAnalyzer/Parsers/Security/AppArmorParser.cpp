// AppArmorParser.cpp
// Implementation of AppArmor parser

#include "AppArmorParser.h"
#include "AuditLog/AuditLog.h"
#include <fstream>
#include <sstream>
#include <regex>
#include <algorithm>
#include <dirent.h>
#include <sys/stat.h>

namespace LinuxAnalysis {

AppArmorParser::ParseResult AppArmorParser::parseProfiles(const std::string& apparmorDir) {
    ParseResult result;
    result.success = true;

    DIR* dir = opendir(apparmorDir.c_str());
    if (!dir) {
        result.success = false;
        result.error = LinuxAnalyzerError(ErrorCode::APPARMOR_NOT_ENABLED,
            "Cannot open AppArmor directory: " + apparmorDir);
        AuditLog::instance().log("ERROR", "APPARMOR_DIR_NOT_FOUND",
            "Failed to open " + apparmorDir);
        return result;
    }

    struct dirent* entry;
    while ((entry = readdir(dir)) != nullptr) {
        std::string filename = entry->d_name;

        // Skip hidden files, ., .., and cache directory
        if (filename.empty() || filename[0] == '.' ||
            filename == "cache" || filename == "disable") {
            continue;
        }

        std::string fullPath = apparmorDir + "/" + filename;

        // Check if it's a regular file
        struct stat fileStat;
        if (stat(fullPath.c_str(), &fileStat) == 0 && S_ISREG(fileStat.st_mode)) {
            try {
                AppArmorProfile profile = parseProfileFile(fullPath);
                if (!profile.profileName.empty()) {
                    result.profiles.push_back(profile);
                }
            } catch (const std::exception& e) {
                AuditLog::instance().log("WARNING", "APPARMOR_PARSE_WARNING",
                    "Failed to parse " + fullPath + ": " + e.what());
            }
        }
    }

    closedir(dir);

    AuditLog::instance().log("SUCCESS", "APPARMOR_PROFILES_PARSED",
        "Parsed " + std::to_string(result.profiles.size()) + " AppArmor profiles");

    return result;
}

AppArmorProfile AppArmorParser::parseProfileFile(const std::string& profilePath) {
    std::ifstream file(profilePath);
    if (!file.is_open()) {
        AppArmorProfile profile;
        return profile;
    }

    std::stringstream buffer;
    buffer << file.rdbuf();
    return parseProfileContent(buffer.str(), profilePath);
}

AppArmorProfile AppArmorParser::parseProfileContent(const std::string& content,
                                                     const std::string& filePath) {
    AppArmorProfile profile;
    profile.filePath = filePath;
    profile.isEnabled = true;

    std::istringstream stream(content);
    std::string line;
    bool inProfile = false;

    while (std::getline(stream, line)) {
        // Trim leading whitespace
        size_t start = line.find_first_not_of(" \t");
        if (start != std::string::npos) {
            line = line.substr(start);
        }

        // Skip comments and empty lines
        if (line.empty() || line[0] == '#') continue;

        // Skip include directives
        if (line.find("#include") == 0 || line.find("include") == 0) {
            continue;
        }

        // Check for profile declaration
        if (line.find("profile") == 0) {
            profile.profileName = AppArmorParser::parseProfileDeclaration(line);
            profile.mode = AppArmorParser::parseProfileFlags(line);
            inProfile = true;
            continue;
        }

        // Parse file access rules if we're in a profile
        if (inProfile && !line.empty()) {
            if (line[0] == '}') {
                // End of profile
                inProfile = false;
            } else if (line[0] == '/' || line.find("deny") == 0) {
                AppArmorParser::parseFileRule(line, profile);
            }
        }
    }

    return profile;
}

AppArmorParser::ParseResult AppArmorParser::extractViolations(const std::string& logPath) {
    ParseResult result;
    result.success = true;

    std::ifstream file(logPath);
    if (!file.is_open()) {
        result.success = false;
        result.error = LinuxAnalyzerError(ErrorCode::FILE_NOT_FOUND,
            "Cannot open log file: " + logPath);
        AuditLog::instance().log("ERROR", "APPARMOR_LOG_NOT_FOUND",
            "Failed to open " + logPath);
        return result;
    }

    std::string line;
    int lineNum = 0;
    int violationCount = 0;

    while (std::getline(file, line)) {
        lineNum++;

        // Look for AppArmor DENIED messages
        if (line.find("apparmor=") != std::string::npos &&
            line.find("DENIED") != std::string::npos) {

            try {
                AppArmorViolation violation = AppArmorParser::parseViolationLine(line);
                if (!violation.profile.empty()) {
                    result.violations.push_back(violation);
                    violationCount++;
                }
            } catch (const std::exception& e) {
                AuditLog::instance().log("WARNING", "APPARMOR_VIOLATION_PARSE_WARNING",
                    "Failed to parse line " + std::to_string(lineNum) + ": " + e.what());
            }
        }
    }

    AuditLog::instance().log("SUCCESS", "APPARMOR_VIOLATIONS_EXTRACTED",
        "Extracted " + std::to_string(violationCount) + " AppArmor violations from " + logPath);

    return result;
}

AppArmorViolation AppArmorParser::parseViolationLine(const std::string& line) {
    AppArmorViolation violation;

    violation.timestamp = extractLogTimestamp(line);
    parseViolationMessage(line, violation);

    return violation;
}

std::string AppArmorParser::parseProfileDeclaration(const std::string& line) {
    // Format: profile name { or profile name flags {
    std::regex pattern(R"(profile\s+(\S+))");
    std::smatch match;

    if (std::regex_search(line, match, pattern) && match.size() >= 2) {
        return match[1].str();
    }

    return "";
}

void AppArmorParser::parseFileRule(const std::string& rule, AppArmorProfile& profile) {
    // Format: /path/to/file permissions, or deny /path/to/file permissions,
    std::string ruleCopy = rule;

    // Check for deny rule
    bool isDeny = (ruleCopy.find("deny") == 0);
    if (isDeny) {
        size_t firstSpace = ruleCopy.find(' ');
        if (firstSpace != std::string::npos) {
            ruleCopy = ruleCopy.substr(firstSpace + 1);
        }
    }

    // Extract path (first word or quoted string)
    std::regex pathRegex(R"(^([\"\']?)([^\"\']+)\1\s+)");
    std::smatch match;
    if (std::regex_search(ruleCopy, match, pathRegex) && match.size() >= 3) {
        std::string path = match[2].str();

        if (isDeny) {
            profile.deniedPaths.push_back(path);
        } else {
            profile.allowedPaths.push_back(path);
        }
    }
}

std::string AppArmorParser::parseProfileFlags(const std::string& declaration) {
    // Extract flags from profile declaration
    // Common flags: enforce, complain, attach_disconnected, etc.
    std::vector<std::string> flags;
    std::regex flagRegex(R"(flags=\(([^)]+)\))");
    std::smatch match;

    if (std::regex_search(declaration, match, flagRegex) && match.size() >= 2) {
        return match[1].str();
    }

    // Default to enforce if no flags specified
    return "enforce";
}

bool AppArmorParser::parseViolationMessage(const std::string& line, AppArmorViolation& violation) {
    // Parse AppArmor violation message
    // Format: apparmor="DENIED" operation="open" profile="/usr/bin/foo"
    //         name="/var/log/syslog" pid=1234 comm="foo" requested_mask="w" denied_mask="w"

    std::regex profileRegex(R"DELIM(profile="([^"]+)")DELIM");
    std::smatch match;
    if (std::regex_search(line, match, profileRegex) && match.size() >= 2) {
        violation.profile = match[1].str();
    }

    std::regex operationRegex(R"DELIM(operation="([^"]+)")DELIM");
    if (std::regex_search(line, match, operationRegex) && match.size() >= 2) {
        violation.operation = match[1].str();
    }

    std::regex nameRegex(R"DELIM(name="([^"]+)")DELIM");
    if (std::regex_search(line, match, nameRegex) && match.size() >= 2) {
        violation.targetPath = match[1].str();
    }

    std::regex commRegex(R"DELIM(comm="([^"]+)")DELIM");
    if (std::regex_search(line, match, commRegex) && match.size() >= 2) {
        violation.executable = match[1].str();
    }

    violation.status = "DENIED";

    return !violation.profile.empty();
}

int64_t AppArmorParser::extractLogTimestamp(const std::string& line) {
    // Parse syslog timestamp
    // Format: Jan  1 12:00:00 hostname kernel: ...
    // Or: 2024-01-01T12:00:00.000000+00:00 hostname ...

    // Try ISO 8601 format first
    std::regex isoRegex(R"(^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}))");
    std::smatch match;

    if (std::regex_search(line, match, isoRegex) && match.size() >= 2) {
        // This is simplified - full ISO 8601 parsing would be more complex
        return 0; // Would need proper datetime parsing
    }

    // Try syslog format
    // For now, return 0 as timestamp parsing from syslog is complex
    // In production, you'd use a proper datetime library
    return 0;
}

} // namespace LinuxAnalysis
