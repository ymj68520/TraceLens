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

// Email log parsers (postfix/exim/dovecot) + email security analysis.
// Split from EmailVPNLogParser.cpp. Methods belong to
// forensics::linux::EmailVPNLogParser (EmailVPNLogParser.h).

EmailServiceType EmailVPNLogParser::detectEmailType(const std::string& filePath) {
    std::string lower = filePath;
    std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);

    if (lower.find("postfix") != std::string::npos) return EmailServiceType::Postfix;
    if (lower.find("exim") != std::string::npos) return EmailServiceType::Exim;
    if (lower.find("dovecot") != std::string::npos) return EmailServiceType::Dovecot;
    if (lower.find("sendmail") != std::string::npos) return EmailServiceType::Sendmail;
    if (lower.find("mail.log") != std::string::npos || lower.find("maillog") != std::string::npos) {
        return EmailServiceType::Postfix; // Default for generic mail log
    }
    return EmailServiceType::Unknown;
}

std::vector<EmailLogEntry> EmailVPNLogParser::parseEmailAuto(
    const std::string& content, const std::string& filePath) {
    EmailServiceType type = detectEmailType(filePath);

    switch (type) {
        case EmailServiceType::Postfix:
        case EmailServiceType::Sendmail:
            return parsePostfixLog(content, filePath);
        case EmailServiceType::Exim:
            return parseEximLog(content, filePath);
        case EmailServiceType::Dovecot:
            return parseDovecotLog(content, filePath);
        default:
            // Try to detect from content
            if (content.find("postfix/") != std::string::npos) return parsePostfixLog(content, filePath);
            if (content.find("exim[") != std::string::npos) return parseEximLog(content, filePath);
            if (content.find("dovecot[") != std::string::npos) return parseDovecotLog(content, filePath);
            return {};
    }
}

// ============================================================================
// Postfix Log Parser
// ============================================================================

// Postfix format: Jan 15 10:30:00 hostname postfix/smtpd[12345]: ABCDEF0123: client=...

std::vector<EmailLogEntry> EmailVPNLogParser::parsePostfixLog(
    const std::string& content, const std::string& filePath) {
    std::vector<EmailLogEntry> entries;
    std::istringstream stream(content);
    std::string line;
    int lineNum = 0;

    // Syslog-style timestamp: Jan 15 10:30:00
    static std::regex postfixRegex(R"(^(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+\S+\s+(postfix/\w+)\[(\d+)\]:\s+(.*)$)");
    // Generic syslog with message ID: Jan 15 10:30:00 hostname postfix/smtpd[PID]: queueid: ...
    static std::regex queueRegex(R"(^(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+\S+\s+(postfix/\w+)\[(\d+)\]:\s+([A-F0-9]{10,12}):\s+(.*)$)");

    while (std::getline(stream, line)) {
        lineNum++;
        if (line.empty()) continue;

        EmailLogEntry entry;
        entry.sourceFile = filePath;
        entry.lineNumber = lineNum;
        entry.serviceType = EmailServiceType::Postfix;
        entry.provenance.parserName = "EmailVPNLogParser";
        entry.provenance.parserVersion = "1.0.0";
        entry.provenance.sourceFile = filePath;

        std::smatch match;
        if (std::regex_match(line, match, queueRegex)) {
            entry.timestamp = match[1].str();
            entry.component = match[2].str();
            entry.messageId = match[4].str();
            std::string details = match[5].str();

            // Parse details
            // client=hostname[IP]
            static std::regex clientRegex(R"(client=\S+\[([\d.]+)\])");
            std::smatch clientMatch;
            if (std::regex_search(details, clientMatch, clientRegex)) {
                entry.clientAddr = clientMatch[1].str();
            }

            // from=<sender>
            static std::regex fromRegex(R"(from=<([^>]*)>)");
            std::smatch fromMatch;
            if (std::regex_search(details, fromMatch, fromRegex)) {
                entry.sender = fromMatch[1].str();
            }

            // to=<recipient>
            static std::regex toRegex(R"(to=<([^>]*)>)");
            std::smatch toMatch;
            if (std::regex_search(details, toMatch, toRegex)) {
                entry.recipient = toMatch[1].str();
            }

            // relay=host[IP]:port
            static std::regex relayRegex(R"(relay=\S+\[([\d.]+)\])");
            std::smatch relayMatch;
            if (std::regex_search(details, relayMatch, relayRegex)) {
                entry.relayHost = relayMatch[1].str();
            }

            // size=N
            static std::regex sizeRegex(R"(size=(\d+))");
            std::smatch sizeMatch;
            if (std::regex_search(details, sizeMatch, sizeRegex)) {
                entry.size = std::stoi(sizeMatch[1].str());
            }

            // status=sent/bounced/deferred/rejected
            static std::regex statusRegex(R"(status=(\w+))");
            std::smatch statusMatch;
            if (std::regex_search(details, statusMatch, statusRegex)) {
                entry.status = statusMatch[1].str();
            }

            entry.message = details;
        } else if (std::regex_match(line, match, postfixRegex)) {
            entry.timestamp = match[1].str();
            entry.component = match[2].str();
            entry.message = match[4].str();

            // Determine severity from message
            std::string lower = entry.message;
            std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);
            if (lower.find("error") != std::string::npos || lower.find("fatal") != std::string::npos) {
                entry.severity = "error";
            } else if (lower.find("warning") != std::string::npos || lower.find("reject") != std::string::npos) {
                entry.severity = "warning";
            } else if (lower.find("warning") != std::string::npos) {
                entry.severity = "warning";
            } else {
                entry.severity = "info";
            }

            // Extract client from message
            static std::regex clientRegex(R"(client=\S+\[([\d.]+)\])");
            std::smatch clientMatch;
            if (std::regex_search(entry.message, clientMatch, clientRegex)) {
                entry.clientAddr = clientMatch[1].str();
            }
        } else {
            continue;
        }

        entries.push_back(entry);
    }

    return entries;
}

// ============================================================================
// Exim Log Parser
// ============================================================================

// Exim format: 2024-01-15 10:30:00 1rABCD-000000-00 <= sender@domain H=host [IP] P=esmtp S=1234

std::vector<EmailLogEntry> EmailVPNLogParser::parseEximLog(
    const std::string& content, const std::string& filePath) {
    std::vector<EmailLogEntry> entries;
    std::istringstream stream(content);
    std::string line;
    int lineNum = 0;

    static std::regex eximRegex(R"(^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+(\S+)\s+(.*)$)");

    while (std::getline(stream, line)) {
        lineNum++;
        if (line.empty()) continue;

        EmailLogEntry entry;
        entry.sourceFile = filePath;
        entry.lineNumber = lineNum;
        entry.serviceType = EmailServiceType::Exim;
        entry.provenance.parserName = "EmailVPNLogParser";
        entry.provenance.parserVersion = "1.0.0";
        entry.provenance.sourceFile = filePath;

        std::smatch match;
        if (!std::regex_match(line, match, eximRegex)) continue;

        entry.timestamp = match[1].str();
        entry.messageId = match[2].str();
        std::string details = match[3].str();
        entry.message = details;

        // Parse direction: <= (incoming), => (outgoing), ** (bounce), == (deferred)
        if (details.find("<=") != std::string::npos) {
            entry.status = "incoming";
        } else if (details.find("=>") != std::string::npos) {
            entry.status = "sent";
        } else if (details.find("**") != std::string::npos) {
            entry.status = "bounced";
        } else if (details.find("==") != std::string::npos) {
            entry.status = "deferred";
        }

        // Extract sender: <= sender@domain
        static std::regex senderRegex(R"(<=\s*(\S+))");
        std::smatch senderMatch;
        if (std::regex_search(details, senderMatch, senderRegex)) {
            entry.sender = senderMatch[1].str();
        }

        // Extract recipient: => recipient@domain or ** recipient@domain
        static std::regex recipRegex(R"([=*]+\s*(\S+@\S+))");
        std::smatch recipMatch;
        if (std::regex_search(details, recipMatch, recipRegex)) {
            entry.recipient = recipMatch[1].str();
        }

        // Extract client IP: H=hostname [IP]
        static std::regex clientRegex(R"(H=\S+\s+\[([\d.]+)\])");
        std::smatch clientMatch;
        if (std::regex_search(details, clientMatch, clientRegex)) {
            entry.clientAddr = clientMatch[1].str();
        }

        // Extract size: S=N
        static std::regex sizeRegex(R"(S=(\d+))");
        std::smatch sizeMatch;
        if (std::regex_search(details, sizeMatch, sizeRegex)) {
            entry.size = std::stoi(sizeMatch[1].str());
        }

        // Severity
        if (entry.status == "bounced" || details.find("failed") != std::string::npos) {
            entry.severity = "error";
        } else if (entry.status == "deferred" || details.find("frozen") != std::string::npos) {
            entry.severity = "warning";
        } else {
            entry.severity = "info";
        }

        entries.push_back(entry);
    }

    return entries;
}

// ============================================================================
// Dovecot Log Parser
// ============================================================================

// Dovecot format: Jan 15 10:30:00 hostname dovecot: imap-login: Login: user=<user>, method=PLAIN, rip=IP

std::vector<EmailLogEntry> EmailVPNLogParser::parseDovecotLog(
    const std::string& content, const std::string& filePath) {
    std::vector<EmailLogEntry> entries;
    std::istringstream stream(content);
    std::string line;
    int lineNum = 0;

    static std::regex dovecotRegex(R"(^(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+\S+\s+dovecot:\s+(\S+):\s+(.*)$)");

    while (std::getline(stream, line)) {
        lineNum++;
        if (line.empty()) continue;

        EmailLogEntry entry;
        entry.sourceFile = filePath;
        entry.lineNumber = lineNum;
        entry.serviceType = EmailServiceType::Dovecot;
        entry.provenance.parserName = "EmailVPNLogParser";
        entry.provenance.parserVersion = "1.0.0";
        entry.provenance.sourceFile = filePath;

        std::smatch match;
        if (!std::regex_match(line, match, dovecotRegex)) continue;

        entry.timestamp = match[1].str();
        entry.component = match[2].str();
        entry.message = match[3].str();

        // Extract user: user=<user>
        static std::regex userRegex(R"(user=<([^>]+)>)");
        std::smatch userMatch;
        if (std::regex_search(entry.message, userMatch, userRegex)) {
            entry.username = userMatch[1].str();
        }

        // Extract client IP: rip=IP
        static std::regex ripRegex(R"(rip=([\d.]+))");
        std::smatch ripMatch;
        if (std::regex_search(entry.message, ripMatch, ripRegex)) {
            entry.clientAddr = ripMatch[1].str();
        }

        // Severity
        std::string lower = entry.message;
        std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);
        if (lower.find("failed") != std::string::npos || lower.find("error") != std::string::npos) {
            entry.severity = "error";
        } else if (lower.find("disconnected") != std::string::npos) {
            entry.severity = "warning";
        } else if (lower.find("login") != std::string::npos) {
            entry.severity = "info";
        } else {
            entry.severity = "info";
        }

        entries.push_back(entry);
    }

    return entries;
}

// ============================================================================
// VPN Log Auto-detection
// ============================================================================

std::vector<EmailSecurityFinding> EmailVPNLogParser::analyzeEmailSecurity(
    const std::vector<EmailLogEntry>& entries) {
    std::vector<EmailSecurityFinding> findings;

    // Track auth failures per client
    std::map<std::string, int> authFailureCount;

    for (const auto& entry : entries) {
        std::string lower = entry.message;
        std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);

        // Auth failures
        if (lower.find("auth failed") != std::string::npos ||
            lower.find("authentication failed") != std::string::npos ||
            lower.find("sasl_auth_failure") != std::string::npos ||
            lower.find("login failed") != std::string::npos) {
            EmailSecurityFinding f;
            f.findingType = "auth_failure";
            f.severity = "high";
            f.description = "Email service authentication failure";
            f.evidence = entry.message;
            f.sourceFile = entry.sourceFile;
            f.serviceType = entry.serviceType;
            f.clientAddr = entry.clientAddr;
            f.provenance.parserName = "EmailVPNLogParser";
            f.provenance.parserVersion = "1.0.0";
            f.provenance.sourceFile = entry.sourceFile;
            findings.push_back(f);

            if (!entry.clientAddr.empty()) {
                authFailureCount[entry.clientAddr]++;
            }
        }

        // Open relay indicators
        if (lower.find("relay denied") != std::string::npos) {
            // Relay denied is normal - good security
        } else if (lower.find("relay=") != std::string::npos && entry.status == "sent") {
            // Check if relay is to external domain (suspicious if from external)
            if (!entry.sender.empty() && entry.sender.find("@") != std::string::npos) {
                EmailSecurityFinding f;
                f.findingType = "relay_open";
                f.severity = "critical";
                f.description = "Possible open relay: mail relayed from external sender";
                f.evidence = "From: " + entry.sender + ", To: " + entry.recipient;
                f.sourceFile = entry.sourceFile;
                f.serviceType = entry.serviceType;
                f.clientAddr = entry.clientAddr;
                f.provenance.parserName = "EmailVPNLogParser";
                f.provenance.parserVersion = "1.0.0";
                f.provenance.sourceFile = entry.sourceFile;
                findings.push_back(f);
            }
        }

        // Rejected connections
        if (lower.find("reject:") != std::string::npos || lower.find("rejected") != std::string::npos) {
            EmailSecurityFinding f;
            f.findingType = "rejected_connection";
            f.severity = "medium";
            f.description = "Email connection rejected";
            f.evidence = entry.message;
            f.sourceFile = entry.sourceFile;
            f.serviceType = entry.serviceType;
            f.clientAddr = entry.clientAddr;
            f.provenance.parserName = "EmailVPNLogParser";
            f.provenance.parserVersion = "1.0.0";
            f.provenance.sourceFile = entry.sourceFile;
            findings.push_back(f);
        }

        // Spam indicators
        if (lower.find("spam") != std::string::npos || lower.find("blacklist") != std::string::npos ||
            lower.find("rbl") != std::string::npos) {
            EmailSecurityFinding f;
            f.findingType = "spam_indicator";
            f.severity = "medium";
            f.description = "Spam or blacklisting indicator detected";
            f.evidence = entry.message;
            f.sourceFile = entry.sourceFile;
            f.serviceType = entry.serviceType;
            f.clientAddr = entry.clientAddr;
            f.provenance.parserName = "EmailVPNLogParser";
            f.provenance.parserVersion = "1.0.0";
            f.provenance.sourceFile = entry.sourceFile;
            findings.push_back(f);
        }

        // TLS errors
        if (lower.find("tls") != std::string::npos && lower.find("error") != std::string::npos) {
            EmailSecurityFinding f;
            f.findingType = "tls_error";
            f.severity = "medium";
            f.description = "TLS/SSL error in email communication";
            f.evidence = entry.message;
            f.sourceFile = entry.sourceFile;
            f.serviceType = entry.serviceType;
            f.clientAddr = entry.clientAddr;
            f.provenance.parserName = "EmailVPNLogParser";
            f.provenance.parserVersion = "1.0.0";
            f.provenance.sourceFile = entry.sourceFile;
            findings.push_back(f);
        }
    }

    // Brute force detection
    for (const auto& [client, count] : authFailureCount) {
        if (count >= 5) {
            EmailSecurityFinding f;
            f.findingType = "auth_failure";
            f.severity = "critical";
            f.description = "Possible brute force attack: " + std::to_string(count) + " auth failures from " + client;
            f.evidence = "Client: " + client + ", Failures: " + std::to_string(count);
            f.clientAddr = client;
            f.provenance.parserName = "EmailVPNLogParser";
            f.provenance.parserVersion = "1.0.0";
            findings.push_back(f);
        }
    }

    return findings;
}

// ============================================================================
// VPN Security Analysis
// ============================================================================


} // namespace linux
} // namespace forensics
