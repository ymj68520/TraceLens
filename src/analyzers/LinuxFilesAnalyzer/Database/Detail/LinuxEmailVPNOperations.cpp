// LinuxEmailVPNOperations.cpp
// Database operations for email and VPN logs (Phase 11)

#include <sstream>

using forensics::linux::EmailLogEntry;
using forensics::linux::VPNLogEntry;
using forensics::linux::EmailSecurityFinding;
using forensics::linux::VPNSecurityFinding;
using forensics::linux::EmailServiceType;
using forensics::linux::VPNServiceType;

// ============================================================================
// Email Log Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertEmailLog(const EmailLogEntry& entry) {
    std::lock_guard<std::mutex> lock(mutex_);

    const char* sql = R"(
        INSERT INTO linux_email_logs
        (timestamp, timestamp_unix, service_type, severity, component, message_id, message,
         source_file, line_number, sender, recipient, client_addr, relay_host, message_size,
         status, parser_name, parser_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    )";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, "Failed to prepare email log insert");
        return false;
    }

    std::string svcType;
    switch (entry.serviceType) {
        case EmailServiceType::Postfix: svcType = "postfix"; break;
        case EmailServiceType::Exim: svcType = "exim"; break;
        case EmailServiceType::Dovecot: svcType = "dovecot"; break;
        case EmailServiceType::Sendmail: svcType = "sendmail"; break;
        default: svcType = "unknown"; break;
    }

    int idx = 1;
    sqlite3_bind_text(stmt, idx++, entry.timestamp.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, idx++, entry.timestampUnix);
    sqlite3_bind_text(stmt, idx++, svcType.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.severity.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.component.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.messageId.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.message.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.sourceFile.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, idx++, entry.lineNumber);
    sqlite3_bind_text(stmt, idx++, entry.sender.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.recipient.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.clientAddr.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.relayHost.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, idx++, entry.size);
    sqlite3_bind_text(stmt, idx++, entry.status.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.provenance.parserName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.provenance.parserVersion.c_str(), -1, SQLITE_TRANSIENT);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);

    if (!success) {
        setError(ErrorCode::DATABASE_INSERT_FAILED, "Failed to insert email log");
    }
    return success;
}

bool LinuxAnalysisDatabase::insertEmailLogs(const std::vector<EmailLogEntry>& entries) {
    if (entries.empty()) return true;
    if (!beginTransaction()) return false;

    bool allSuccess = true;
    for (const auto& entry : entries) {
        if (!insertEmailLog(entry)) {
            allSuccess = false;
            break;
        }
    }

    if (allSuccess) return commitTransaction();
    rollbackTransaction();
    return false;
}

// ============================================================================
// Email Security Finding Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertEmailSecurityFinding(const EmailSecurityFinding& finding) {
    std::lock_guard<std::mutex> lock(mutex_);

    const char* sql = R"(
        INSERT INTO linux_email_security_findings
        (finding_type, severity, description, evidence, source_file, service_type,
         client_addr, parser_name, parser_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    )";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, "Failed to prepare email security finding insert");
        return false;
    }

    std::string svcType;
    switch (finding.serviceType) {
        case EmailServiceType::Postfix: svcType = "postfix"; break;
        case EmailServiceType::Exim: svcType = "exim"; break;
        case EmailServiceType::Dovecot: svcType = "dovecot"; break;
        default: svcType = "unknown"; break;
    }

    int idx = 1;
    sqlite3_bind_text(stmt, idx++, finding.findingType.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, finding.severity.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, finding.description.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, finding.evidence.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, finding.sourceFile.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, svcType.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, finding.clientAddr.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, finding.provenance.parserName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, finding.provenance.parserVersion.c_str(), -1, SQLITE_TRANSIENT);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);

    if (!success) {
        setError(ErrorCode::DATABASE_INSERT_FAILED, "Failed to insert email security finding");
    }
    return success;
}

bool LinuxAnalysisDatabase::insertEmailSecurityFindings(const std::vector<EmailSecurityFinding>& findings) {
    if (findings.empty()) return true;
    if (!beginTransaction()) return false;

    bool allSuccess = true;
    for (const auto& finding : findings) {
        if (!insertEmailSecurityFinding(finding)) {
            allSuccess = false;
            break;
        }
    }

    if (allSuccess) return commitTransaction();
    rollbackTransaction();
    return false;
}

// ============================================================================
// VPN Log Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertVPNLog(const VPNLogEntry& entry) {
    std::lock_guard<std::mutex> lock(mutex_);

    const char* sql = R"(
        INSERT INTO linux_vpn_logs
        (timestamp, timestamp_unix, service_type, severity, message, source_file,
         line_number, username, client_addr, virtual_addr, server_addr, common_name,
         bytes_sent, bytes_received, parser_name, parser_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    )";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, "Failed to prepare VPN log insert");
        return false;
    }

    std::string svcType;
    switch (entry.serviceType) {
        case VPNServiceType::OpenVPN: svcType = "openvpn"; break;
        case VPNServiceType::WireGuard: svcType = "wireguard"; break;
        case VPNServiceType::PPP: svcType = "ppp"; break;
        case VPNServiceType::IPSec: svcType = "ipsec"; break;
        default: svcType = "unknown"; break;
    }

    int idx = 1;
    sqlite3_bind_text(stmt, idx++, entry.timestamp.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, idx++, entry.timestampUnix);
    sqlite3_bind_text(stmt, idx++, svcType.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.severity.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.message.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.sourceFile.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, idx++, entry.lineNumber);
    sqlite3_bind_text(stmt, idx++, entry.username.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.clientAddr.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.virtualAddr.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.serverAddr.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.commonName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, idx++, entry.bytesSent);
    sqlite3_bind_int(stmt, idx++, entry.bytesReceived);
    sqlite3_bind_text(stmt, idx++, entry.provenance.parserName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.provenance.parserVersion.c_str(), -1, SQLITE_TRANSIENT);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);

    if (!success) {
        setError(ErrorCode::DATABASE_INSERT_FAILED, "Failed to insert VPN log");
    }
    return success;
}

bool LinuxAnalysisDatabase::insertVPNLogs(const std::vector<VPNLogEntry>& entries) {
    if (entries.empty()) return true;
    if (!beginTransaction()) return false;

    bool allSuccess = true;
    for (const auto& entry : entries) {
        if (!insertVPNLog(entry)) {
            allSuccess = false;
            break;
        }
    }

    if (allSuccess) return commitTransaction();
    rollbackTransaction();
    return false;
}

// ============================================================================
// VPN Security Finding Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertVPNSecurityFinding(const VPNSecurityFinding& finding) {
    std::lock_guard<std::mutex> lock(mutex_);

    const char* sql = R"(
        INSERT INTO linux_vpn_security_findings
        (finding_type, severity, description, evidence, source_file, service_type,
         username, client_addr, parser_name, parser_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    )";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, "Failed to prepare VPN security finding insert");
        return false;
    }

    std::string svcType;
    switch (finding.serviceType) {
        case VPNServiceType::OpenVPN: svcType = "openvpn"; break;
        case VPNServiceType::WireGuard: svcType = "wireguard"; break;
        default: svcType = "unknown"; break;
    }

    int idx = 1;
    sqlite3_bind_text(stmt, idx++, finding.findingType.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, finding.severity.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, finding.description.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, finding.evidence.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, finding.sourceFile.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, svcType.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, finding.username.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, finding.clientAddr.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, finding.provenance.parserName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, finding.provenance.parserVersion.c_str(), -1, SQLITE_TRANSIENT);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);

    if (!success) {
        setError(ErrorCode::DATABASE_INSERT_FAILED, "Failed to insert VPN security finding");
    }
    return success;
}

bool LinuxAnalysisDatabase::insertVPNSecurityFindings(const std::vector<VPNSecurityFinding>& findings) {
    if (findings.empty()) return true;
    if (!beginTransaction()) return false;

    bool allSuccess = true;
    for (const auto& finding : findings) {
        if (!insertVPNSecurityFinding(finding)) {
            allSuccess = false;
            break;
        }
    }

    if (allSuccess) return commitTransaction();
    rollbackTransaction();
    return false;
}
