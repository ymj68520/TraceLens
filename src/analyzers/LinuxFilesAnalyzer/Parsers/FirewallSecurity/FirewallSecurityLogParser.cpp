// FirewallSecurityLogParser.cpp
// Parser for firewall and security product logs (UFW, firewalld, fail2ban, ClamAV, rkhunter, OSSEC, AIDE)
// Phase 11: Database, Email, VPN, DNS, Firewall & Security Product Logs

#include "FirewallSecurityLogParser.h"
#include <sstream>
#include <algorithm>
#include <regex>
#include <map>
#include <set>

namespace forensics {
namespace linux {

// ============================================================================
// Auto-detection
// ============================================================================

SecurityToolType FirewallSecurityLogParser::detectToolType(const std::string& filePath) {
    std::string lower = filePath;
    std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);

    if (lower.find("ufw") != std::string::npos) return SecurityToolType::UFW;
    if (lower.find("firewalld") != std::string::npos) return SecurityToolType::Firewalld;
    if (lower.find("fail2ban") != std::string::npos) return SecurityToolType::Fail2Ban;
    if (lower.find("clamav") != std::string::npos || lower.find("freshclam") != std::string::npos) return SecurityToolType::ClamAV;
    if (lower.find("rkhunter") != std::string::npos) return SecurityToolType::RKHunter;
    if (lower.find("chkrootkit") != std::string::npos) return SecurityToolType::Chkrootkit;
    if (lower.find("ossec") != std::string::npos) return SecurityToolType::OSSEC;
    if (lower.find("aide") != std::string::npos) return SecurityToolType::AIDE;
    return SecurityToolType::Unknown;
}

// ============================================================================
// UFW Log Parser
// ============================================================================

// UFW format: Jan 15 10:30:00 hostname kernel: [UFW BLOCK] IN=eth0 OUT= MAC=... SRC=1.2.3.4 DST=5.6.7.8 LEN=... TTL=... PROTO=TCP SPT=12345 DPT=22
std::vector<FirewallLogEntry> FirewallSecurityLogParser::parseUFWLog(
    const std::string& content, const std::string& filePath) {
    std::vector<FirewallLogEntry> entries;
    std::istringstream stream(content);
    std::string line;
    int lineNum = 0;

    while (std::getline(stream, line)) {
        lineNum++;
        if (line.empty() || line.find("UFW") == std::string::npos) continue;

        FirewallLogEntry entry;
        entry.sourceFile = filePath;
        entry.lineNumber = lineNum;
        entry.toolType = SecurityToolType::UFW;
        entry.provenance.parserName = "FirewallSecurityLogParser";
        entry.provenance.parserVersion = "1.0.0";
        entry.provenance.sourceFile = filePath;

        // Extract timestamp
        static std::regex tsRegex(R"(^(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}))");
        std::smatch tsMatch;
        if (std::regex_search(line, tsMatch, tsRegex)) {
            entry.timestamp = tsMatch[1].str();
        }

        // Extract action
        if (line.find("[UFW BLOCK]") != std::string::npos) entry.action = "BLOCK";
        else if (line.find("[UFW ALLOW]") != std::string::npos) entry.action = "ALLOW";
        else if (line.find("[UFW AUDIT]") != std::string::npos) entry.action = "AUDIT";

        // Extract IN interface
        static std::regex inRegex(R"(IN=(\S+))");
        std::smatch inMatch;
        if (std::regex_search(line, inMatch, inRegex)) {
            entry.interface = inMatch[1].str();
        }

        // Extract SRC
        static std::regex srcRegex(R"(SRC=([\d.]+))");
        std::smatch srcMatch;
        if (std::regex_search(line, srcMatch, srcRegex)) {
            entry.srcAddr = srcMatch[1].str();
        }

        // Extract DST
        static std::regex dstRegex(R"(DST=([\d.]+))");
        std::smatch dstMatch;
        if (std::regex_search(line, dstMatch, dstRegex)) {
            entry.dstAddr = dstMatch[1].str();
        }

        // Extract PROTO
        static std::regex protoRegex(R"(PROTO=(\w+))");
        std::smatch protoMatch;
        if (std::regex_search(line, protoMatch, protoRegex)) {
            entry.protocol = protoMatch[1].str();
        }

        // Extract SPT
        static std::regex sptRegex(R"(SPT=(\d+))");
        std::smatch sptMatch;
        if (std::regex_search(line, sptMatch, sptRegex)) {
            entry.srcPort = std::stoi(sptMatch[1].str());
        }

        // Extract DPT
        static std::regex dptRegex(R"(DPT=(\d+))");
        std::smatch dptMatch;
        if (std::regex_search(line, dptMatch, dptRegex)) {
            entry.dstPort = std::stoi(dptMatch[1].str());
        }

        entry.severity = (entry.action == "BLOCK") ? "info" : "info";
        entry.message = line;

        entries.push_back(entry);
    }

    return entries;
}

// ============================================================================
// Firewalld Log Parser
// ============================================================================

// Firewalld format in syslog: Jan 15 10:30:00 hostname firewalld: ... zone=public ... interface=eth0 ...
std::vector<FirewallLogEntry> FirewallSecurityLogParser::parseFirewalldLog(
    const std::string& content, const std::string& filePath) {
    std::vector<FirewallLogEntry> entries;
    std::istringstream stream(content);
    std::string line;
    int lineNum = 0;

    while (std::getline(stream, line)) {
        lineNum++;
        if (line.empty() || line.find("firewalld") == std::string::npos) continue;

        FirewallLogEntry entry;
        entry.sourceFile = filePath;
        entry.lineNumber = lineNum;
        entry.toolType = SecurityToolType::Firewalld;
        entry.provenance.parserName = "FirewallSecurityLogParser";
        entry.provenance.parserVersion = "1.0.0";
        entry.provenance.sourceFile = filePath;

        // Extract timestamp
        static std::regex tsRegex(R"(^(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}))");
        std::smatch tsMatch;
        if (std::regex_search(line, tsMatch, tsRegex)) {
            entry.timestamp = tsMatch[1].str();
        }

        // Extract zone
        static std::regex zoneRegex(R"(zone=(\w+))");
        std::smatch zoneMatch;
        if (std::regex_search(line, zoneMatch, zoneRegex)) {
            entry.chain = zoneMatch[1].str();
        }

        // Extract interface
        static std::regex ifaceRegex(R"(interface=(\w+))");
        std::smatch ifaceMatch;
        if (std::regex_search(line, ifaceMatch, ifaceRegex)) {
            entry.interface = ifaceMatch[1].str();
        }

        // Extract source
        static std::regex srcRegex(R"(source=([\d.]+))");
        std::smatch srcMatch;
        if (std::regex_search(line, srcMatch, srcRegex)) {
            entry.srcAddr = srcMatch[1].str();
        }

        // Extract destination
        static std::regex dstRegex(R"(destination=([\d.]+))");
        std::smatch dstMatch;
        if (std::regex_search(line, dstMatch, dstRegex)) {
            entry.dstAddr = dstMatch[1].str();
        }

        // Extract port
        static std::regex portRegex(R"(port=(\d+))");
        std::smatch portMatch;
        if (std::regex_search(line, portMatch, portRegex)) {
            entry.dstPort = std::stoi(portMatch[1].str());
        }

        // Extract protocol
        static std::regex protoRegex(R"(protocol=(\w+))");
        std::smatch protoMatch;
        if (std::regex_search(line, protoMatch, protoRegex)) {
            entry.protocol = protoMatch[1].str();
        }

        // Determine action from message
        std::string lower = line;
        std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);
        if (lower.find("reject") != std::string::npos) entry.action = "REJECT";
        else if (lower.find("drop") != std::string::npos) entry.action = "DROP";
        else if (lower.find("accept") != std::string::npos) entry.action = "ALLOW";
        else entry.action = "LOG";

        entry.severity = "info";
        entry.message = line;

        entries.push_back(entry);
    }

    return entries;
}

std::vector<FirewallLogEntry> FirewallSecurityLogParser::parseFirewallAuto(
    const std::string& content, const std::string& filePath) {
    SecurityToolType type = detectToolType(filePath);

    switch (type) {
        case SecurityToolType::UFW:
            return parseUFWLog(content, filePath);
        case SecurityToolType::Firewalld:
            return parseFirewalldLog(content, filePath);
        default:
            if (content.find("UFW") != std::string::npos) return parseUFWLog(content, filePath);
            if (content.find("firewalld") != std::string::npos) return parseFirewalldLog(content, filePath);
            return {};
    }
}

// ============================================================================
// Fail2Ban Log Parser
// ============================================================================

// Fail2Ban format: 2024-01-15 10:30:00,123 fail2ban.actions [12345]: NOTICE [sshd] Ban 1.2.3.4
std::vector<SecurityProductLogEntry> FirewallSecurityLogParser::parseFail2BanLog(
    const std::string& content, const std::string& filePath) {
    std::vector<SecurityProductLogEntry> entries;
    std::istringstream stream(content);
    std::string line;
    int lineNum = 0;

    static std::regex f2bRegex(R"(^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}),\d+\s+fail2ban\.(\w+)\s+\[(\d+)\]:\s+(\w+)\s+\[(\w+)\]\s+(Ban|Unban|Found|Ignore)\s+(.*)$)");

    while (std::getline(stream, line)) {
        lineNum++;
        if (line.empty()) continue;

        SecurityProductLogEntry entry;
        entry.sourceFile = filePath;
        entry.lineNumber = lineNum;
        entry.toolType = SecurityToolType::Fail2Ban;
        entry.provenance.parserName = "FirewallSecurityLogParser";
        entry.provenance.parserVersion = "1.0.0";
        entry.provenance.sourceFile = filePath;

        std::smatch match;
        if (std::regex_match(line, match, f2bRegex)) {
            entry.timestamp = match[1].str();
            std::string component = match[2].str();
            std::string severityStr = match[4].str();
            std::string jail = match[5].str();
            std::string action = match[6].str();
            std::string details = match[7].str();

            entry.eventType = "ban_action";
            entry.target = jail;

            if (action == "Ban") {
                entry.severity = "high";
                entry.result = "banned";
                entry.message = "IP banned in jail " + jail + ": " + details;
            } else if (action == "Unban") {
                entry.severity = "info";
                entry.result = "unbanned";
                entry.message = "IP unbanned in jail " + jail + ": " + details;
            } else if (action == "Found") {
                entry.severity = "medium";
                entry.result = "found";
                entry.message = "Failed attempt found in jail " + jail + ": " + details;
            } else {
                entry.severity = "info";
                entry.message = line;
            }

            // Extract IP from details
            static std::regex ipRegex(R"((\d+\.\d+\.\d+\.\d+))");
            std::smatch ipMatch;
            if (std::regex_search(details, ipMatch, ipRegex)) {
                entry.message += " [IP: " + ipMatch[1].str() + "]";
            }
        } else {
            continue;
        }

        entries.push_back(entry);
    }

    return entries;
}

// ============================================================================
// ClamAV Log Parser
// ============================================================================

// ClamAV freshclam format: Mon Jan 15 10:30:00 2024 -> ClamAV update process started
// ClamAV clamd scan format: /path/to/file: OK / FOUND / ERROR
std::vector<SecurityProductLogEntry> FirewallSecurityLogParser::parseClamAVLog(
    const std::string& content, const std::string& filePath) {
    std::vector<SecurityProductLogEntry> entries;
    std::istringstream stream(content);
    std::string line;
    int lineNum = 0;

    // freshclam format
    static std::regex freshclamRegex(R"(^(\w{3}\s+\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+\d{4})\s*->\s+(.*)$)");
    // clamd scan format: /path/to/file: OK or /path/to/file: VirusName FOUND
    static std::regex scanRegex(R"(^(\S+):\s+(?:.*\s+)?(OK|FOUND|ERROR)\s*$)");

    while (std::getline(stream, line)) {
        lineNum++;
        if (line.empty()) continue;

        SecurityProductLogEntry entry;
        entry.sourceFile = filePath;
        entry.lineNumber = lineNum;
        entry.toolType = SecurityToolType::ClamAV;
        entry.provenance.parserName = "FirewallSecurityLogParser";
        entry.provenance.parserVersion = "1.0.0";
        entry.provenance.sourceFile = filePath;

        std::smatch match;
        if (std::regex_match(line, match, freshclamRegex)) {
            entry.timestamp = match[1].str();
            entry.message = match[2].str();
            entry.eventType = "update";

            std::string lower = entry.message;
            std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);
            if (lower.find("error") != std::string::npos || lower.find("failed") != std::string::npos) {
                entry.severity = "error";
                entry.result = "error";
            } else if (lower.find("updated") != std::string::npos || lower.find("up to date") != std::string::npos) {
                entry.severity = "info";
                entry.result = "ok";
            } else {
                entry.severity = "info";
            }
        } else if (std::regex_match(line, match, scanRegex)) {
            entry.eventType = "scan";
            entry.target = match[1].str();
            std::string result = match[2].str();

            if (result == "FOUND") {
                entry.severity = "critical";
                entry.result = "infected";
                entry.message = "Malware detected: " + entry.target;
            } else if (result == "ERROR") {
                entry.severity = "error";
                entry.result = "error";
                entry.message = "Scan error: " + entry.target;
            } else {
                entry.severity = "info";
                entry.result = "clean";
                entry.message = "Clean: " + entry.target;
            }
        } else {
            continue;
        }

        entries.push_back(entry);
    }

    return entries;
}

// ============================================================================
// RKHunter Log Parser
// ============================================================================

// RKHunter format: [15:30:00] Checking 'xxx'... [ OK ] / [ Warning ] / [ Not found ]
std::vector<SecurityProductLogEntry> FirewallSecurityLogParser::parseRKHunterLog(
    const std::string& content, const std::string& filePath) {
    std::vector<SecurityProductLogEntry> entries;
    std::istringstream stream(content);
    std::string line;
    int lineNum = 0;

    // RKHunter check result
    static std::regex rkhRegex(R"(^\[(\d{2}:\d{2}:\d{2})\]\s+Checking\s+'([^']+)'\s*\.\.\.\s*\[(.+?)\]$)");
    // RKHunter warning
    static std::regex rkhWarnRegex(R"(^\[(\d{2}:\d{2}:\d{2})\]\s+Warning:\s+(.*)$)");

    while (std::getline(stream, line)) {
        lineNum++;
        if (line.empty()) continue;

        SecurityProductLogEntry entry;
        entry.sourceFile = filePath;
        entry.lineNumber = lineNum;
        entry.toolType = SecurityToolType::RKHunter;
        entry.provenance.parserName = "FirewallSecurityLogParser";
        entry.provenance.parserVersion = "1.0.0";
        entry.provenance.sourceFile = filePath;

        std::smatch match;
        if (std::regex_match(line, match, rkhRegex)) {
            entry.timestamp = match[1].str();
            entry.target = match[2].str();
            std::string result = match[3].str();
            entry.eventType = "integrity_check";

            // Trim whitespace from result
            result.erase(0, result.find_first_not_of(" \t"));
            result.erase(result.find_last_not_of(" \t") + 1);

            if (result == "OK" || result == "Not found") {
                entry.severity = "info";
                entry.result = "ok";
                entry.message = "Check passed: " + entry.target;
            } else if (result == "Warning") {
                entry.severity = "high";
                entry.result = "warning";
                entry.message = "Check warning: " + entry.target;
            } else if (result.find("Infected") != std::string::npos) {
                entry.severity = "critical";
                entry.result = "infected";
                entry.message = "Rootkit indicator: " + entry.target;
            } else {
                entry.severity = "medium";
                entry.result = result;
                entry.message = "Check result: " + entry.target + " [" + result + "]";
            }
        } else if (std::regex_match(line, match, rkhWarnRegex)) {
            entry.timestamp = match[1].str();
            entry.message = match[2].str();
            entry.severity = "high";
            entry.eventType = "alert";
        } else {
            continue;
        }

        entries.push_back(entry);
    }

    return entries;
}

// ============================================================================
// OSSEC Log Parser
// ============================================================================

// OSSEC format: 2024/01/15 10:30:00 ossec: Alert Level: 3; Rule: 1001 - ...
std::vector<SecurityProductLogEntry> FirewallSecurityLogParser::parseOSSECLog(
    const std::string& content, const std::string& filePath) {
    std::vector<SecurityProductLogEntry> entries;
    std::istringstream stream(content);
    std::string line;
    int lineNum = 0;

    // OSSEC alert format
    static std::regex ossecRegex(R"(^(\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2})\s+ossec:\s+Alert\s+Level:\s+(\d+);\s+Rule:\s+(\d+)\s+-\s+(.*)$)");
    // OSSEC syscheck format
    static std::regex syscheckRegex(R"(^(\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2})\s+ossec-syscheck:\s+(.*)$)");

    while (std::getline(stream, line)) {
        lineNum++;
        if (line.empty()) continue;

        SecurityProductLogEntry entry;
        entry.sourceFile = filePath;
        entry.lineNumber = lineNum;
        entry.toolType = SecurityToolType::OSSEC;
        entry.provenance.parserName = "FirewallSecurityLogParser";
        entry.provenance.parserVersion = "1.0.0";
        entry.provenance.sourceFile = filePath;

        std::smatch match;
        if (std::regex_match(line, match, ossecRegex)) {
            entry.timestamp = match[1].str();
            int level = std::stoi(match[2].str());
            entry.message = match[4].str();
            entry.eventType = "alert";

            if (level >= 10) entry.severity = "critical";
            else if (level >= 7) entry.severity = "high";
            else if (level >= 4) entry.severity = "medium";
            else entry.severity = "low";
        } else if (std::regex_match(line, match, syscheckRegex)) {
            entry.timestamp = match[1].str();
            entry.message = match[2].str();
            entry.eventType = "integrity_check";

            // Detect file changes
            if (entry.message.find("Integrity checksum changed") != std::string::npos ||
                entry.message.find("added") != std::string::npos ||
                entry.message.find("deleted") != std::string::npos) {
                entry.severity = "high";
                entry.result = "modified";
            } else {
                entry.severity = "info";
                entry.result = "ok";
            }
        } else {
            continue;
        }

        entries.push_back(entry);
    }

    return entries;
}

// ============================================================================
// AIDE Log Parser
// ============================================================================

// AIDE format: AIDE found differences between database and filesystem
// Added: /path/to/file
// Removed: /path/to/file
// Changed: /path/to/file
std::vector<SecurityProductLogEntry> FirewallSecurityLogParser::parseAIDELog(
    const std::string& content, const std::string& filePath) {
    std::vector<SecurityProductLogEntry> entries;
    std::istringstream stream(content);
    std::string line;
    int lineNum = 0;

    while (std::getline(stream, line)) {
        lineNum++;
        if (line.empty()) continue;

        SecurityProductLogEntry entry;
        entry.sourceFile = filePath;
        entry.lineNumber = lineNum;
        entry.toolType = SecurityToolType::AIDE;
        entry.provenance.parserName = "FirewallSecurityLogParser";
        entry.provenance.parserVersion = "1.0.0";
        entry.provenance.sourceFile = filePath;

        // AIDE summary line
        if (line.find("AIDE found differences") != std::string::npos) {
            entry.timestamp = "";
            entry.eventType = "integrity_check";
            entry.severity = "high";
            entry.message = line;
            entries.push_back(entry);
            continue;
        }

        // Added files
        if (line.find("Added:") == 0 || line.find("Added :") != std::string::npos) {
            entry.eventType = "integrity_check";
            entry.severity = "high";
            entry.result = "added";
            entry.target = line.substr(line.find(':') + 1);
            // Trim whitespace
            entry.target.erase(0, entry.target.find_first_not_of(" \t"));
            entry.message = "File added: " + entry.target;
            entries.push_back(entry);
            continue;
        }

        // Removed files
        if (line.find("Removed:") == 0 || line.find("Removed :") != std::string::npos) {
            entry.eventType = "integrity_check";
            entry.severity = "high";
            entry.result = "removed";
            entry.target = line.substr(line.find(':') + 1);
            entry.target.erase(0, entry.target.find_first_not_of(" \t"));
            entry.message = "File removed: " + entry.target;
            entries.push_back(entry);
            continue;
        }

        // Changed files
        if (line.find("Changed:") == 0 || line.find("Changed :") != std::string::npos) {
            entry.eventType = "integrity_check";
            entry.severity = "high";
            entry.result = "modified";
            entry.target = line.substr(line.find(':') + 1);
            entry.target.erase(0, entry.target.find_first_not_of(" \t"));
            entry.message = "File changed: " + entry.target;
            entries.push_back(entry);
            continue;
        }

        // Detailed change lines (size, mtime, etc.)
        if (line.find("Size") != std::string::npos || line.find("Mtime") != std::string::npos ||
            line.find("Ctime") != std::string::npos || line.find("Perm") != std::string::npos) {
            entry.eventType = "integrity_check";
            entry.severity = "medium";
            entry.result = "detail";
            entry.message = line;
            entries.push_back(entry);
        }
    }

    return entries;
}

std::vector<SecurityProductLogEntry> FirewallSecurityLogParser::parseSecurityAuto(
    const std::string& content, const std::string& filePath) {
    SecurityToolType type = detectToolType(filePath);

    switch (type) {
        case SecurityToolType::Fail2Ban:
            return parseFail2BanLog(content, filePath);
        case SecurityToolType::ClamAV:
            return parseClamAVLog(content, filePath);
        case SecurityToolType::RKHunter:
            return parseRKHunterLog(content, filePath);
        case SecurityToolType::OSSEC:
            return parseOSSECLog(content, filePath);
        case SecurityToolType::AIDE:
            return parseAIDELog(content, filePath);
        default:
            // Try to detect from content
            if (content.find("fail2ban") != std::string::npos) return parseFail2BanLog(content, filePath);
            if (content.find("ClamAV") != std::string::npos || content.find("freshclam") != std::string::npos) return parseClamAVLog(content, filePath);
            if (content.find("rkhunter") != std::string::npos || content.find("Rootkit Hunter") != std::string::npos) return parseRKHunterLog(content, filePath);
            if (content.find("ossec") != std::string::npos) return parseOSSECLog(content, filePath);
            if (content.find("AIDE") != std::string::npos) return parseAIDELog(content, filePath);
            return {};
    }
}

// ============================================================================
// Firewall Security Analysis
// ============================================================================

std::vector<SecurityProductFinding> FirewallSecurityLogParser::analyzeFirewallSecurity(
    const std::vector<FirewallLogEntry>& entries) {
    std::vector<SecurityProductFinding> findings;

    // Track blocked IPs
    std::map<std::string, int> blockedIPCount;
    // Track port scan indicators (many different dst ports from same src)
    std::map<std::string, std::set<int>> srcPorts;

    for (const auto& entry : entries) {
        if (entry.action == "BLOCK" || entry.action == "DROP" || entry.action == "REJECT") {
            if (!entry.srcAddr.empty()) {
                blockedIPCount[entry.srcAddr]++;
                if (entry.dstPort > 0) {
                    srcPorts[entry.srcAddr].insert(entry.dstPort);
                }
            }
        }
    }

    // Port scan detection: same source hitting many ports
    for (const auto& [src, ports] : srcPorts) {
        if (ports.size() >= 10) {
            SecurityProductFinding f;
            f.findingType = "port_scan";
            f.severity = "high";
            f.description = "Possible port scan from " + src + " (" + std::to_string(ports.size()) + " ports)";
            f.evidence = "Source: " + src + ", Ports scanned: " + std::to_string(ports.size());
            f.toolType = SecurityToolType::UFW;
            f.provenance.parserName = "FirewallSecurityLogParser";
            f.provenance.parserVersion = "1.0.0";
            findings.push_back(f);
        }
    }

    // High block count from single IP
    for (const auto& [ip, count] : blockedIPCount) {
        if (count >= 50) {
            SecurityProductFinding f;
            f.findingType = "high_block_count";
            f.severity = "medium";
            f.description = "IP " + ip + " blocked " + std::to_string(count) + " times";
            f.evidence = "IP: " + ip + ", Blocks: " + std::to_string(count);
            f.toolType = SecurityToolType::UFW;
            f.provenance.parserName = "FirewallSecurityLogParser";
            f.provenance.parserVersion = "1.0.0";
            findings.push_back(f);
        }
    }

    return findings;
}

// ============================================================================
// Security Product Analysis
// ============================================================================

std::vector<SecurityProductFinding> FirewallSecurityLogParser::analyzeSecurityProduct(
    const std::vector<SecurityProductLogEntry>& entries) {
    std::vector<SecurityProductFinding> findings;

    for (const auto& entry : entries) {
        // Malware detections
        if (entry.result == "infected") {
            SecurityProductFinding f;
            f.findingType = "malware_detected";
            f.severity = "critical";
            std::string toolName;
            switch (entry.toolType) {
                case SecurityToolType::ClamAV: toolName = "ClamAV"; break;
                case SecurityToolType::RKHunter: toolName = "rkhunter"; break;
                case SecurityToolType::OSSEC: toolName = "OSSEC"; break;
                default: toolName = "security tool"; break;
            }
            f.description = "Malware detected by " + toolName;
            f.evidence = entry.message;
            f.sourceFile = entry.sourceFile;
            f.toolType = entry.toolType;
            f.target = entry.target;
            f.provenance.parserName = "FirewallSecurityLogParser";
            f.provenance.parserVersion = "1.0.0";
            f.provenance.sourceFile = entry.sourceFile;
            findings.push_back(f);
        }

        // Integrity violations (AIDE, OSSEC syscheck)
        if (entry.result == "modified" || entry.result == "added" || entry.result == "removed") {
            SecurityProductFinding f;
            f.findingType = "integrity_violation";
            f.severity = "high";
            f.description = "File integrity change detected";
            f.evidence = entry.message;
            f.sourceFile = entry.sourceFile;
            f.toolType = entry.toolType;
            f.target = entry.target;
            f.provenance.parserName = "FirewallSecurityLogParser";
            f.provenance.parserVersion = "1.0.0";
            f.provenance.sourceFile = entry.sourceFile;
            findings.push_back(f);
        }

        // Rootkit indicators
        if (entry.result == "warning" && entry.toolType == SecurityToolType::RKHunter) {
            SecurityProductFinding f;
            f.findingType = "rootkit_indicator";
            f.severity = "high";
            f.description = "RKHunter warning: possible rootkit indicator";
            f.evidence = entry.message;
            f.sourceFile = entry.sourceFile;
            f.toolType = entry.toolType;
            f.target = entry.target;
            f.provenance.parserName = "FirewallSecurityLogParser";
            f.provenance.parserVersion = "1.0.0";
            f.provenance.sourceFile = entry.sourceFile;
            findings.push_back(f);
        }

        // Fail2ban bans
        if (entry.result == "banned") {
            SecurityProductFinding f;
            f.findingType = "ban_action";
            f.severity = "medium";
            f.description = "IP banned by fail2ban";
            f.evidence = entry.message;
            f.sourceFile = entry.sourceFile;
            f.toolType = entry.toolType;
            f.provenance.parserName = "FirewallSecurityLogParser";
            f.provenance.parserVersion = "1.0.0";
            f.provenance.sourceFile = entry.sourceFile;
            findings.push_back(f);
        }

        // OSSEC high-level alerts
        if (entry.eventType == "alert" && entry.severity == "critical") {
            SecurityProductFinding f;
            f.findingType = "critical_alert";
            f.severity = "critical";
            f.description = "Critical security alert";
            f.evidence = entry.message;
            f.sourceFile = entry.sourceFile;
            f.toolType = entry.toolType;
            f.provenance.parserName = "FirewallSecurityLogParser";
            f.provenance.parserVersion = "1.0.0";
            f.provenance.sourceFile = entry.sourceFile;
            findings.push_back(f);
        }
    }

    return findings;
}

} // namespace linux
} // namespace forensics
