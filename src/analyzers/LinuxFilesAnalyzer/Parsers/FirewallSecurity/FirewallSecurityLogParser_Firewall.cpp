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

// Firewall log parsers (UFW / firewalld) + firewall security analysis.
// Split from FirewallSecurityLogParser.cpp. Methods belong to
// forensics::linux::FirewallSecurityLogParser (FirewallSecurityLogParser.h).

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

} // namespace linux
} // namespace forensics
