// CapabilityAnalyzer.cpp
// Implementation of Linux capability analyzer

#include "CapabilityAnalyzer.h"
#include "AuditLog/AuditLog.h"
#include <fstream>
#include <sstream>
#include <regex>
#include <algorithm>

namespace LinuxAnalysis {

// Dangerous capabilities that require special attention
const std::unordered_set<std::string> CapabilityAnalyzer::DANGEROUS_CAPABILITIES = {
    "cap_setuid",           // Can change user ID (privilege escalation)
    "cap_setgid",           // Can change group ID (privilege escalation)
    "cap_sys_admin",        // Can perform system administration tasks
    "cap_sys_module",       // Can load kernel modules
    "cap_sys_chroot",       // Can change root directory
    "cap_sys_ptrace",       // Can trace any process
    "cap_sys_boot",         // Can reboot system
    "cap_sys_time",         // Can change system clock
    "cap_net_raw",          // Can use raw sockets (sniffing, spoofing)
    "cap_net_admin",        // Can configure network
    "cap_kill",             // Can send signals to any process
    "cap_sys_nice",         // Can change priority of any process
    "cap_sys_resource",     // Can override resource limits
    "cap_dac_override",     // Can bypass file read/write/execute checks
    "cap_dac_read_search",  // Can bypass file read checks
    "cap_fowner",           // Can bypass permission checks on file ops
    "cap_fsetid",           // Can set setuid/setgid bits
    "cap_lease",            // Can establish leases on files
    "cap_audit_control",    // Can enable/disable kernel auditing
    "cap_audit_write",      // Can write to audit log
    "cap_mac_override",     // Can override MAC access controls
    "cap_mac_admin",        // Can configure MAC
    "cap_mknod",            // Can create special files
    "cap_setfcap",          // Can set file capabilities
    "cap_syslog",           // Can perform privileged syslog operations
    "cap_wake_alarm"        // Can trigger system wake events
};

CapabilityAnalyzer::AnalysisResult CapabilityAnalyzer::parseFileCapabilities(const std::string& getcapOutput) {
    AnalysisResult result;
    result.success = true;

    std::istringstream stream(getcapOutput);
    std::string line;
    int lineNum = 0;

    while (std::getline(stream, line)) {
        lineNum++;
        if (line.empty() || line[0] == '#') continue;

        try {
            FileCapability cap = CapabilityAnalyzer::parseCapLine(line);
            if (!cap.filePath.empty()) {
                result.capabilities.push_back(cap);
            }
        } catch (const std::exception& e) {
            AuditLog::instance().log("WARNING", "CAPABILITY_PARSE_WARNING",
                "Failed to parse line " + std::to_string(lineNum) + ": " + e.what());
        }
    }

    result.dangerousCapabilities = CapabilityAnalyzer::flagDangerousCapabilities(result.capabilities);

    AuditLog::instance().log("SUCCESS", "CAPABILITY_ANALYSIS_COMPLETE",
        "Found " + std::to_string(result.capabilities.size()) + " capabilities, " +
        std::to_string(result.dangerousCapabilities.size()) + " dangerous");

    return result;
}

CapabilityAnalyzer::AnalysisResult CapabilityAnalyzer::parseFileCapabilitiesFromFile(const std::string& filePath) {
    AnalysisResult result;
    result.success = true;

    std::ifstream file(filePath);
    if (!file.is_open()) {
        result.success = false;
        result.error = LinuxAnalyzerError(ErrorCode::CAPABILITY_PARSE_FAILED,
            "Cannot open capability file: " + filePath);
        AuditLog::instance().log("ERROR", "CAPABILITY_PARSE_FAILED",
            "Failed to open " + filePath);
        return result;
    }

    std::stringstream buffer;
    buffer << file.rdbuf();
    return parseFileCapabilities(buffer.str());
}

std::vector<FileCapability> CapabilityAnalyzer::flagDangerousCapabilities(std::vector<FileCapability>& caps) {
    std::vector<FileCapability> dangerous;

    for (auto& cap : caps) {
        cap.isSuspicious = false;

        // Check each capability in the set
        for (const auto& capability : cap.capabilities) {
            if (CapabilityAnalyzer::isDangerousCapability(capability)) {
                cap.isSuspicious = true;
                dangerous.push_back(cap);
                break; // Only add once per file
            }
        }
    }

    return dangerous;
}

bool CapabilityAnalyzer::isDangerousCapability(const std::string& capability) {
    // Convert to lowercase for comparison
    std::string lowerCap = capability;
    std::transform(lowerCap.begin(), lowerCap.end(), lowerCap.begin(), ::tolower);

    return DANGEROUS_CAPABILITIES.find(lowerCap) != DANGEROUS_CAPABILITIES.end();
}

FileCapability CapabilityAnalyzer::parseCapLine(const std::string& line) {
    FileCapability cap;

    // Parse getcap output format
    // Examples:
    // /usr/bin/ping = cap_net_raw+ep
    // /usr/bin/tcpdump = cap_net_raw,cap_net_admin+ep
    std::regex pattern(R"(^(\S+)\s+=\s+(.+)$)");
    std::smatch match;

    if (std::regex_search(line, match, pattern) && match.size() >= 3) {
        cap.filePath = match[1].str();
        std::string capSet = match[2].str();

        // Split into capabilities and flags
        size_t plusPos = capSet.find('+');
        if (plusPos != std::string::npos) {
            std::string capsPart = capSet.substr(0, plusPos);
            std::string flagsPart = capSet.substr(plusPos);

            cap.capabilities = CapabilityAnalyzer::parseCapabilitySet(capsPart);
            cap.capabilitySet = CapabilityAnalyzer::parseCapabilityFlags(flagsPart);

            // Check if inherited (has 'i' flag)
            cap.isInherited = (flagsPart.find('i') != std::string::npos);
        } else {
            // No flags, just capabilities
            cap.capabilities = CapabilityAnalyzer::parseCapabilitySet(capSet);
        }
    }

    return cap;
}

std::vector<std::string> CapabilityAnalyzer::parseCapabilitySet(const std::string& capSet) {
    std::vector<std::string> capabilities;

    // Split by comma
    std::istringstream stream(capSet);
    std::string token;

    while (std::getline(stream, token, ',')) {
        // Trim whitespace
        size_t start = token.find_first_not_of(" \t");
        size_t end = token.find_last_not_of(" \t");

        if (start != std::string::npos && end != std::string::npos) {
            std::string cap = token.substr(start, end - start + 1);
            if (!cap.empty()) {
                capabilities.push_back(cap);
            }
        }
    }

    return capabilities;
}

std::string CapabilityAnalyzer::parseCapabilityFlags(const std::string& flags) {
    // Extract flags from string like "+ep" or "+eip"
    if (!flags.empty() && flags[0] == '+') {
        return flags.substr(1);
    }
    return flags;
}

} // namespace LinuxAnalysis
