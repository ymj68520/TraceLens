// SetuidAnalyzer.cpp
// Implementation of setuid/setgid file analyzer

#include "SetuidAnalyzer.h"
#include "AuditLog/AuditLog.h"
#include <fstream>
#include <sstream>
#include <regex>
#include <algorithm>

namespace LinuxAnalysis {

// Known-good setuid/setgid files whitelist
const std::unordered_set<std::string> SetuidAnalyzer::KNOWN_SETUID_FILES = {
    "/bin/su",
    "/bin/ping",
    "/bin/ping6",
    "/bin/mount",
    "/bin/umount",
    "/usr/bin/sudo",
    "/usr/bin/passwd",
    "/usr/bin/gpasswd",
    "/usr/bin/chsh",
    "/usr/bin/chfn",
    "/usr/bin/newgrp",
    "/usr/bin/wall",
    "/usr/bin/write",
    "/usr/sbin/passwd",
    "/usr/sbin/pppd",
    "/usr/sbin/traceroute",
    "/usr/sbin/traceroute6",
    "/usr/sbin/tcpdump",
    "/sbin/pam_timestamp_check",
    "/sbin/unix_chkpwd",
    "/sbin/netreport"
};

SetuidAnalyzer::AnalysisResult SetuidAnalyzer::analyzeSetuidFiles(const std::string& fileListPath) {
    AnalysisResult result;
    result.success = true;

    std::ifstream file(fileListPath);
    if (!file.is_open()) {
        result.success = false;
        result.error = LinuxAnalyzerError(ErrorCode::SETUID_SCAN_FAILED,
            "Cannot open file list: " + fileListPath);
        AuditLog::instance().log("ERROR", "SETUID_SCAN_FAILED",
            "Failed to open " + fileListPath);
        return result;
    }

    std::stringstream buffer;
    buffer << file.rdbuf();
    return parseFindOutput(buffer.str());
}

SetuidAnalyzer::AnalysisResult SetuidAnalyzer::parseFindOutput(const std::string& findOutput) {
    AnalysisResult result;
    result.success = true;

    std::istringstream stream(findOutput);
    std::string line;
    int lineNum = 0;

    while (std::getline(stream, line)) {
        lineNum++;
        if (line.empty() || line[0] == '#') continue;

        try {
            SetuidFileInfo fileInfo = SetuidAnalyzer::parseFindLine(line);
            if (fileInfo.isSetuid) {
                result.setuidFiles.push_back(fileInfo);
            }
            if (fileInfo.isSetgid) {
                result.setgidFiles.push_back(fileInfo);
            }
        } catch (const std::exception& e) {
            AuditLog::instance().log("WARNING", "SETUID_PARSE_WARNING",
                "Failed to parse line " + std::to_string(lineNum) + ": " + e.what());
        }
    }

    result.suspiciousFiles = SetuidAnalyzer::flagSuspiciousFiles(result.setuidFiles);
    // Add any setgid suspicious files
    auto setgidSuspicious = SetuidAnalyzer::flagSuspiciousFiles(result.setgidFiles);
    result.suspiciousFiles.insert(result.suspiciousFiles.end(),
        setgidSuspicious.begin(), setgidSuspicious.end());

    AuditLog::instance().log("SUCCESS", "SETUID_ANALYSIS_COMPLETE",
        "Found " + std::to_string(result.setuidFiles.size()) + " setuid, " +
        std::to_string(result.setgidFiles.size()) + " setgid, " +
        std::to_string(result.suspiciousFiles.size()) + " suspicious files");

    return result;
}

std::vector<SetuidFileInfo> SetuidAnalyzer::flagSuspiciousFiles(std::vector<SetuidFileInfo>& files) {
    std::vector<SetuidFileInfo> suspicious;

    for (auto& file : files) {
        file.isSuspicious = false;
        file.suspiciousReason.clear();

        if (SetuidAnalyzer::isInSuspiciousLocation(file.filePath)) {
            file.isSuspicious = true;
            file.suspiciousReason = "Located in temporary directory";
        } else if (SetuidAnalyzer::hasSuspiciousOwner(file.filePath, file.owner)) {
            file.isSuspicious = true;
            file.suspiciousReason = "Non-root owner in system directory";
        } else if (!SetuidAnalyzer::isKnownGoodFile(file.filePath)) {
            // Not automatically suspicious, but值得investigating
            // Only flag if it's not in a standard bin/sbin directory
            if (file.filePath.find("/bin/") == std::string::npos &&
                file.filePath.find("/sbin/") == std::string::npos &&
                file.filePath.find("/usr/bin/") == std::string::npos &&
                file.filePath.find("/usr/sbin/") == std::string::npos) {
                file.isSuspicious = true;
                file.suspiciousReason = "Not in known-good whitelist and not in standard location";
            }
        }

        if (file.isSuspicious) {
            suspicious.push_back(file);
        }
    }

    return suspicious;
}

bool SetuidAnalyzer::isKnownGoodFile(const std::string& filePath) {
    return KNOWN_SETUID_FILES.find(filePath) != KNOWN_SETUID_FILES.end();
}

SetuidFileInfo SetuidAnalyzer::parseFindLine(const std::string& line) {
    SetuidFileInfo info;

    // Parse find -ls output format
    // Example: 12345 -rwsr-xr-x root root 45000 Jan 1 12:00 /usr/bin/sudo
    std::regex pattern(
        R"(^(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\d+)\s+(\w+\s+\d+\s+[\d:]+)\s+(.+)$)"
    );
    std::smatch match;

    if (std::regex_search(line, match, pattern) && match.size() >= 8) {
        info.filePath = match[7].str();
        info.owner = match[3].str();
        info.groupName = match[4].str();

        try {
            info.size = std::stoll(match[5].str());
        } catch (...) {
            info.size = 0;
        }

        SetuidAnalyzer::parsePermissions(match[2].str(), info.isSetuid, info.isSetgid);

        // Extract permission bits
        std::string perms = match[2].str();
        if (perms.length() >= 10) {
            // Convert rwxrwxrwx to mode_t
            mode_t mode = 0;
            if (perms[1] == 'r') mode |= 0400;
            if (perms[2] == 'w') mode |= 0200;
            if (perms[3] == 'x' || perms[3] == 's' || perms[3] == 'S') mode |= 0100;
            if (perms[4] == 'r') mode |= 0040;
            if (perms[5] == 'w') mode |= 0020;
            if (perms[6] == 'x' || perms[6] == 's' || perms[6] == 'S') mode |= 0010;
            if (perms[7] == 'r') mode |= 0004;
            if (perms[8] == 'w') mode |= 0002;
            if (perms[9] == 'x' || perms[9] == 't' || perms[9] == 'T') mode |= 0001;

            if (perms[3] == 's' || perms[3] == 'S') mode |= 04000; // setuid
            if (perms[6] == 's' || perms[6] == 'S') mode |= 02000; // setgid

            info.permissions = mode;
        }
    }

    return info;
}

void SetuidAnalyzer::parsePermissions(const std::string& permissions, bool& isSetuid, bool& isSetgid) {
    isSetuid = false;
    isSetgid = false;

    if (permissions.length() >= 10) {
        // Check for setuid (s or S in user execute position)
        if (permissions[3] == 's' || permissions[3] == 'S') {
            isSetuid = true;
        }
        // Check for setgid (s or S in group execute position)
        if (permissions[6] == 's' || permissions[6] == 'S') {
            isSetgid = true;
        }
    }
}

bool SetuidAnalyzer::isInSuspiciousLocation(const std::string& filePath) {
    // Check for temporary directories
    static const std::vector<std::string> suspiciousPaths = {
        "/tmp", "/var/tmp", "/dev/shm", "/run/shm"
    };

    for (const auto& path : suspiciousPaths) {
        if (filePath.find(path) == 0) {
            return true;
        }
    }

    // Check for home directory tmp
    if (filePath.find("/home/") == 0) {
        size_t homeEnd = filePath.find('/', 6);
        if (homeEnd != std::string::npos) {
            std::string remaining = filePath.substr(homeEnd);
            if (remaining.find("/tmp") == 0) {
                return true;
            }
        }
    }

    return false;
}

bool SetuidAnalyzer::hasSuspiciousOwner(const std::string& filePath, const std::string& owner) {
    // Skip if owner is root
    if (owner == "root") {
        return false;
    }

    // System directories should only have root-owned setuid files
    static const std::vector<std::string> systemDirs = {
        "/bin", "/sbin", "/usr/bin", "/usr/sbin",
        "/lib", "/usr/lib", "/lib64", "/usr/lib64"
    };

    for (const auto& dir : systemDirs) {
        if (filePath.find(dir) == 0) {
            return true; // Non-root owner in system directory
        }
    }

    return false;
}

} // namespace LinuxAnalysis
