// FirewallSecurityLogParser.h
// Parser for firewall and security product logs (UFW, firewalld, fail2ban, ClamAV, rkhunter, OSSEC, AIDE)
// Phase 11: Database, Email, VPN, DNS, Firewall & Security Product Logs

#pragma once
#ifndef FIREWALL_SECURITY_LOG_PARSER_H
#define FIREWALL_SECURITY_LOG_PARSER_H

#include <string>
#include <vector>
#include <cstdint>
#include "Common/LinuxDataTypes.h"

#ifdef linux
#undef linux
#endif

namespace forensics {
namespace linux {

// Firewall/Security tool types
enum class SecurityToolType {
    UFW,
    Firewalld,
    Fail2Ban,
    ClamAV,
    RKHunter,
    Chkrootkit,
    OSSEC,
    AIDE,
    Unknown
};

// Firewall log entry
struct FirewallLogEntry {
    std::string timestamp;
    int64_t timestampUnix = 0;
    SecurityToolType toolType = SecurityToolType::Unknown;
    std::string severity;
    std::string message;
    std::string sourceFile;
    int lineNumber = 0;
    std::string action;             // BLOCK, ALLOW, DROP, REJECT, DENY
    std::string protocol;           // TCP, UDP, ICMP
    std::string srcAddr;
    int srcPort = 0;
    std::string dstAddr;
    int dstPort = 0;
    std::string interface;
    std::string chain;              // INPUT, OUTPUT, FORWARD
    EvidenceProvenance provenance;
};

// Security product log entry
struct SecurityProductLogEntry {
    std::string timestamp;
    int64_t timestampUnix = 0;
    SecurityToolType toolType = SecurityToolType::Unknown;
    std::string severity;
    std::string message;
    std::string sourceFile;
    int lineNumber = 0;
    std::string eventType;          // scan, detection, alert, integrity_check
    std::string target;             // file, process, user
    std::string result;             // clean, infected, modified, ok
    EvidenceProvenance provenance;
};

// Security finding
struct SecurityProductFinding {
    std::string findingType;        // malware_detected, integrity_violation, rootkit_indicator, ban_action
    std::string severity;           // critical, high, medium, low
    std::string description;
    std::string evidence;
    std::string sourceFile;
    SecurityToolType toolType = SecurityToolType::Unknown;
    std::string target;
    EvidenceProvenance provenance;
};

class FirewallSecurityLogParser {
public:
    // Auto-detect tool type
    static SecurityToolType detectToolType(const std::string& filePath);

    // Firewall log parsing
    static std::vector<FirewallLogEntry> parseUFWLog(const std::string& content, const std::string& filePath = "");
    static std::vector<FirewallLogEntry> parseFirewalldLog(const std::string& content, const std::string& filePath = "");
    static std::vector<FirewallLogEntry> parseFirewallAuto(const std::string& content, const std::string& filePath);

    // Security product log parsing
    static std::vector<SecurityProductLogEntry> parseFail2BanLog(const std::string& content, const std::string& filePath = "");
    static std::vector<SecurityProductLogEntry> parseClamAVLog(const std::string& content, const std::string& filePath = "");
    static std::vector<SecurityProductLogEntry> parseRKHunterLog(const std::string& content, const std::string& filePath = "");
    static std::vector<SecurityProductLogEntry> parseOSSECLog(const std::string& content, const std::string& filePath = "");
    static std::vector<SecurityProductLogEntry> parseAIDELog(const std::string& content, const std::string& filePath = "");
    static std::vector<SecurityProductLogEntry> parseSecurityAuto(const std::string& content, const std::string& filePath);

    // Security analysis
    static std::vector<SecurityProductFinding> analyzeFirewallSecurity(const std::vector<FirewallLogEntry>& entries);
    static std::vector<SecurityProductFinding> analyzeSecurityProduct(const std::vector<SecurityProductLogEntry>& entries);
};

} // namespace linux
} // namespace forensics

#endif // FIREWALL_SECURITY_LOG_PARSER_H
