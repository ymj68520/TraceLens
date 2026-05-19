// EmailVPNLogParser.h
// Parser for email and VPN service logs (postfix, exim, dovecot, OpenVPN, WireGuard)
// Phase 11: Database, Email, VPN, DNS, Firewall & Security Product Logs

#pragma once
#ifndef EMAIL_VPN_LOG_PARSER_H
#define EMAIL_VPN_LOG_PARSER_H

#include <string>
#include <vector>
#include <cstdint>
#include "Common/LinuxDataTypes.h"

#ifdef linux
#undef linux
#endif

namespace forensics {
namespace linux {

// Email service types
enum class EmailServiceType {
    Postfix,
    Exim,
    Dovecot,
    Sendmail,
    Unknown
};

// VPN service types
enum class VPNServiceType {
    OpenVPN,
    WireGuard,
    PPP,
    IPSec,
    Unknown
};

// Email log entry
struct EmailLogEntry {
    std::string timestamp;
    int64_t timestampUnix = 0;
    EmailServiceType serviceType = EmailServiceType::Unknown;
    std::string severity;           // info, warning, error, fatal
    std::string component;          // smtpd, cleanup, qmgr, imap, pop3, etc.
    std::string messageId;          // Postfix queue ID or Message-ID
    std::string message;
    std::string sourceFile;
    int lineNumber = 0;
    std::string sender;             // from address
    std::string recipient;          // to address
    std::string clientAddr;         // client IP
    std::string relayHost;          // relay server
    int size = 0;                   // message size
    std::string status;             // sent, bounced, deferred, rejected
    std::string username;           // authenticated user (Dovecot)
    EvidenceProvenance provenance;
};

// VPN log entry
struct VPNLogEntry {
    std::string timestamp;
    int64_t timestampUnix = 0;
    VPNServiceType serviceType = VPNServiceType::Unknown;
    std::string severity;
    std::string message;
    std::string sourceFile;
    int lineNumber = 0;
    std::string username;
    std::string clientAddr;         // VPN client IP
    std::string virtualAddr;        // assigned VPN IP
    std::string serverAddr;         // VPN server endpoint
    std::string commonName;         // certificate CN
    int bytesSent = 0;
    int bytesReceived = 0;
    EvidenceProvenance provenance;
};

// Email security finding
struct EmailSecurityFinding {
    std::string findingType;        // relay_open, auth_failure, spam_indicator, suspicious_attachment
    std::string severity;
    std::string description;
    std::string evidence;
    std::string sourceFile;
    EmailServiceType serviceType = EmailServiceType::Unknown;
    std::string clientAddr;
    EvidenceProvenance provenance;
};

// VPN security finding
struct VPNSecurityFinding {
    std::string findingType;        // auth_failure, config_weakness, unusual_connection
    std::string severity;
    std::string description;
    std::string evidence;
    std::string sourceFile;
    VPNServiceType serviceType = VPNServiceType::Unknown;
    std::string username;
    std::string clientAddr;
    EvidenceProvenance provenance;
};

class EmailVPNLogParser {
public:
    // Email log parsing
    static EmailServiceType detectEmailType(const std::string& filePath);
    static std::vector<EmailLogEntry> parsePostfixLog(const std::string& content, const std::string& filePath = "");
    static std::vector<EmailLogEntry> parseEximLog(const std::string& content, const std::string& filePath = "");
    static std::vector<EmailLogEntry> parseDovecotLog(const std::string& content, const std::string& filePath = "");
    static std::vector<EmailLogEntry> parseEmailAuto(const std::string& content, const std::string& filePath);

    // VPN log parsing
    static VPNServiceType detectVPNType(const std::string& filePath);
    static std::vector<VPNLogEntry> parseOpenVPNLog(const std::string& content, const std::string& filePath = "");
    static std::vector<VPNLogEntry> parseWireGuardLog(const std::string& content, const std::string& filePath = "");
    static std::vector<VPNLogEntry> parseVPNAuto(const std::string& content, const std::string& filePath);

    // Security analysis
    static std::vector<EmailSecurityFinding> analyzeEmailSecurity(const std::vector<EmailLogEntry>& entries);
    static std::vector<VPNSecurityFinding> analyzeVPNSecurity(const std::vector<VPNLogEntry>& entries);
};

} // namespace linux
} // namespace forensics

#endif // EMAIL_VPN_LOG_PARSER_H
