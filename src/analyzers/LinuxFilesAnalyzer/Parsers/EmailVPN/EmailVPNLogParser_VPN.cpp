// EmailVPNLogParser.cpp
// Parser for email and VPN service logs (postfix, exim, dovecot, OpenVPN, WireGuard)
// Phase 11: Database, Email, VPN, DNS, Firewall & Security Product Logs

#include "EmailVPNLogParser.h"
#include <sstream>
#include <algorithm>
#include <regex>
#include <map>
#include <set>

namespace forensics {
namespace linux {

// VPN log parsers (openvpn/wireguard) + VPN security analysis.
// Split from EmailVPNLogParser.cpp. Methods belong to
// forensics::linux::EmailVPNLogParser (EmailVPNLogParser.h).

VPNServiceType EmailVPNLogParser::detectVPNType(const std::string& filePath) {
    std::string lower = filePath;
    std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);

    if (lower.find("openvpn") != std::string::npos) return VPNServiceType::OpenVPN;
    if (lower.find("wireguard") != std::string::npos || lower.find("wg") != std::string::npos) return VPNServiceType::WireGuard;
    if (lower.find("ppp") != std::string::npos) return VPNServiceType::PPP;
    if (lower.find("ipsec") != std::string::npos || lower.find("strongswan") != std::string::npos) return VPNServiceType::IPSec;
    return VPNServiceType::Unknown;
}

std::vector<VPNLogEntry> EmailVPNLogParser::parseVPNAuto(
    const std::string& content, const std::string& filePath) {
    VPNServiceType type = detectVPNType(filePath);

    switch (type) {
        case VPNServiceType::OpenVPN:
            return parseOpenVPNLog(content, filePath);
        case VPNServiceType::WireGuard:
            return parseWireGuardLog(content, filePath);
        default:
            // Try to detect from content
            if (content.find("openvpn") != std::string::npos || content.find("OpenVPN") != std::string::npos) {
                return parseOpenVPNLog(content, filePath);
            }
            if (content.find("wireguard") != std::string::npos || content.find("WireGuard") != std::string::npos) {
                return parseWireGuardLog(content, filePath);
            }
            return {};
    }
}

// ============================================================================
// OpenVPN Log Parser
// ============================================================================

// OpenVPN format: Jan 15 10:30:00 hostname openvpn[PID]: PID/user IP:PORT MULTI: ...

std::vector<VPNLogEntry> EmailVPNLogParser::parseOpenVPNLog(
    const std::string& content, const std::string& filePath) {
    std::vector<VPNLogEntry> entries;
    std::istringstream stream(content);
    std::string line;
    int lineNum = 0;

    while (std::getline(stream, line)) {
        lineNum++;
        if (line.empty()) continue;

        VPNLogEntry entry;
        entry.sourceFile = filePath;
        entry.lineNumber = lineNum;
        entry.serviceType = VPNServiceType::OpenVPN;
        entry.provenance.parserName = "EmailVPNLogParser";
        entry.provenance.parserVersion = "1.0.0";
        entry.provenance.sourceFile = filePath;

        // Syslog timestamp
        static std::regex syslogRegex(R"(^(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+\S+\s+openvpn\[(\d+)\]:\s+(.*)$)");
        std::smatch match;
        if (!std::regex_match(line, match, syslogRegex)) continue;

        entry.timestamp = match[1].str();
        entry.message = match[3].str();

        // Extract username: .../username ...
        size_t slashPos = entry.message.find('/');
        if (slashPos != std::string::npos && slashPos < 20) {
            size_t spacePos = entry.message.find(' ', slashPos);
            if (spacePos != std::string::npos) {
                entry.username = entry.message.substr(slashPos + 1, spacePos - slashPos - 1);
            }
        }

        // Extract client IP:PORT
        static std::regex clientRegex(R"(^(\d+)/(\S+)\s+([\d.]+):(\d+))");
        std::smatch clientMatch;
        if (std::regex_match(entry.message, clientMatch, clientRegex)) {
            entry.clientAddr = clientMatch[3].str() + ":" + clientMatch[4].str();
            entry.username = clientMatch[2].str();
        }

        // Extract virtual IP
        static std::regex vipRegex(R"(ifconfig_pool_set\(\S+,\s*([\d.]+)\))");
        std::smatch vipMatch;
        if (std::regex_search(entry.message, vipMatch, vipRegex)) {
            entry.virtualAddr = vipMatch[1].str();
        }

        // Extract bytes
        static std::regex bytesRegex(R"(bytes sent/recv = (\d+)/(\d+))");
        std::smatch bytesMatch;
        if (std::regex_search(entry.message, bytesMatch, bytesRegex)) {
            entry.bytesSent = std::stoi(bytesMatch[1].str());
            entry.bytesReceived = std::stoi(bytesMatch[2].str());
        }

        // Severity
        std::string lower = entry.message;
        std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);
        if (lower.find("error") != std::string::npos || lower.find("fatal") != std::string::npos) {
            entry.severity = "error";
        } else if (lower.find("warning") != std::string::npos || lower.find("auth failure") != std::string::npos) {
            entry.severity = "warning";
        } else if (lower.find("peer connection initiated") != std::string::npos ||
                   lower.find("connect") != std::string::npos) {
            entry.severity = "info";
        } else {
            entry.severity = "info";
        }

        entries.push_back(entry);
    }

    return entries;
}

// ============================================================================
// WireGuard Log Parser
// ============================================================================

// WireGuard format (kernel): Jan 15 10:30:00 hostname kernel: [12345.678] wg0: Handshake for peer 1 (IP:PORT) did not complete after 5 seconds, retrying
// WireGuard format (userspace): Jan 15 10:30:00 hostname wg: interface: wg0 peer(1): handshake complete

std::vector<VPNLogEntry> EmailVPNLogParser::parseWireGuardLog(
    const std::string& content, const std::string& filePath) {
    std::vector<VPNLogEntry> entries;
    std::istringstream stream(content);
    std::string line;
    int lineNum = 0;

    while (std::getline(stream, line)) {
        lineNum++;
        if (line.empty()) continue;

        VPNLogEntry entry;
        entry.sourceFile = filePath;
        entry.lineNumber = lineNum;
        entry.serviceType = VPNServiceType::WireGuard;
        entry.provenance.parserName = "EmailVPNLogParser";
        entry.provenance.parserVersion = "1.0.0";
        entry.provenance.sourceFile = filePath;

        // Kernel log format
        static std::regex kernelRegex(R"(^(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+\S+\s+kernel:\s+\[[\d.]+\]\s+(\S+):\s+(.*)$)");
        // Userspace format
        static std::regex userspaceRegex(R"(^(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+\S+\s+wg:\s+(\S+).*?peer\((\d+)\):\s+(.*)$)");

        std::smatch match;
        if (std::regex_match(line, match, kernelRegex)) {
            entry.timestamp = match[1].str();
            std::string iface = match[2].str();
            entry.message = match[3].str();

            // Extract client IP:PORT from message
            static std::regex ipRegex(R"((\d+\.\d+\.\d+\.\d+):(\d+))");
            std::smatch ipMatch;
            if (std::regex_search(entry.message, ipMatch, ipRegex)) {
                entry.clientAddr = ipMatch[1].str() + ":" + ipMatch[2].str();
            }
        } else if (std::regex_match(line, match, userspaceRegex)) {
            entry.timestamp = match[1].str();
            entry.message = match[4].str();
        } else {
            continue;
        }

        // Severity
        std::string lower = entry.message;
        std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);
        if (lower.find("error") != std::string::npos || lower.find("did not complete") != std::string::npos) {
            entry.severity = "warning";
        } else if (lower.find("handshake") != std::string::npos && lower.find("complete") != std::string::npos) {
            entry.severity = "info";
        } else if (lower.find("allowedips") != std::string::npos) {
            entry.severity = "info";
        } else {
            entry.severity = "info";
        }

        entries.push_back(entry);
    }

    return entries;
}

// ============================================================================
// Email Security Analysis
// ============================================================================

std::vector<VPNSecurityFinding> EmailVPNLogParser::analyzeVPNSecurity(
    const std::vector<VPNLogEntry>& entries) {
    std::vector<VPNSecurityFinding> findings;

    // Track connections per user
    std::map<std::string, int> connectionCount;
    // Track unique client IPs per user
    std::map<std::string, std::set<std::string>> userClientIPs;

    for (const auto& entry : entries) {
        std::string lower = entry.message;
        std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);

        // Auth failures
        if (lower.find("auth failed") != std::string::npos ||
            lower.find("authentication failed") != std::string::npos ||
            lower.find("peer certificate verification failed") != std::string::npos) {
            VPNSecurityFinding f;
            f.findingType = "auth_failure";
            f.severity = "high";
            f.description = "VPN authentication failure";
            f.evidence = entry.message;
            f.sourceFile = entry.sourceFile;
            f.serviceType = entry.serviceType;
            f.username = entry.username;
            f.clientAddr = entry.clientAddr;
            f.provenance.parserName = "EmailVPNLogParser";
            f.provenance.parserVersion = "1.0.0";
            f.provenance.sourceFile = entry.sourceFile;
            findings.push_back(f);
        }

        // Track connections
        if (!entry.username.empty() && (lower.find("connect") != std::string::npos || lower.find("login") != std::string::npos)) {
            connectionCount[entry.username]++;
            if (!entry.clientAddr.empty()) {
                userClientIPs[entry.username].insert(entry.clientAddr);
            }
        }

        // Handshake failures (WireGuard)
        if (lower.find("handshake") != std::string::npos && lower.find("did not complete") != std::string::npos) {
            VPNSecurityFinding f;
            f.findingType = "handshake_failure";
            f.severity = "medium";
            f.description = "VPN handshake failure";
            f.evidence = entry.message;
            f.sourceFile = entry.sourceFile;
            f.serviceType = entry.serviceType;
            f.clientAddr = entry.clientAddr;
            f.provenance.parserName = "EmailVPNLogParser";
            f.provenance.parserVersion = "1.0.0";
            f.provenance.sourceFile = entry.sourceFile;
            findings.push_back(f);
        }

        // Config warnings
        if (lower.find("warning") != std::string::npos && lower.find("deprecated") != std::string::npos) {
            VPNSecurityFinding f;
            f.findingType = "config_weakness";
            f.severity = "medium";
            f.description = "VPN using deprecated configuration";
            f.evidence = entry.message;
            f.sourceFile = entry.sourceFile;
            f.serviceType = entry.serviceType;
            f.provenance.parserName = "EmailVPNLogParser";
            f.provenance.parserVersion = "1.0.0";
            f.provenance.sourceFile = entry.sourceFile;
            findings.push_back(f);
        }
    }

    // Unusual connection patterns: user connecting from many IPs
    for (const auto& [user, ips] : userClientIPs) {
        if (ips.size() >= 3) {
            VPNSecurityFinding f;
            f.findingType = "unusual_connection";
            f.severity = "high";
            f.description = "VPN user connecting from " + std::to_string(ips.size()) + " different IPs";
            f.evidence = "User: " + user;
            for (const auto& ip : ips) {
                f.evidence += ", IP: " + ip;
            }
            f.username = user;
            f.provenance.parserName = "EmailVPNLogParser";
            f.provenance.parserVersion = "1.0.0";
            findings.push_back(f);
        }
    }

    return findings;
}

} // namespace linux
} // namespace forensics

