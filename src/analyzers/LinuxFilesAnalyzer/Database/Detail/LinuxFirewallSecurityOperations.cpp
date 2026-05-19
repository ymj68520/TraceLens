// LinuxFirewallSecurityOperations.cpp
// Database operations for firewall and security product logs (Phase 11)

#include <sstream>

using forensics::linux::FirewallLogEntry;
using forensics::linux::SecurityProductLogEntry;
using forensics::linux::SecurityProductFinding;
using forensics::linux::SecurityToolType;

// ============================================================================
// Firewall Log Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertFirewallLogEntry(const FirewallLogEntry& entry) {
    std::lock_guard<std::mutex> lock(mutex_);

    const char* sql = R"(
        INSERT INTO linux_firewall_logs
        (timestamp, timestamp_unix, tool_type, severity, message, source_file,
         line_number, action, protocol, src_addr, src_port, dst_addr, dst_port,
         interface_name, chain_name, parser_name, parser_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    )";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, "Failed to prepare firewall log insert");
        return false;
    }

    std::string toolType;
    switch (entry.toolType) {
        case SecurityToolType::UFW: toolType = "ufw"; break;
        case SecurityToolType::Firewalld: toolType = "firewalld"; break;
        default: toolType = "unknown"; break;
    }

    int idx = 1;
    sqlite3_bind_text(stmt, idx++, entry.timestamp.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, idx++, entry.timestampUnix);
    sqlite3_bind_text(stmt, idx++, toolType.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.severity.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.message.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.sourceFile.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, idx++, entry.lineNumber);
    sqlite3_bind_text(stmt, idx++, entry.action.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.protocol.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.srcAddr.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, idx++, entry.srcPort);
    sqlite3_bind_text(stmt, idx++, entry.dstAddr.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, idx++, entry.dstPort);
    sqlite3_bind_text(stmt, idx++, entry.interface.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.chain.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.provenance.parserName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.provenance.parserVersion.c_str(), -1, SQLITE_TRANSIENT);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);

    if (!success) {
        setError(ErrorCode::DATABASE_INSERT_FAILED, "Failed to insert firewall log");
    }
    return success;
}

bool LinuxAnalysisDatabase::insertFirewallLogEntries(const std::vector<FirewallLogEntry>& entries) {
    if (entries.empty()) return true;
    if (!beginTransaction()) return false;

    bool allSuccess = true;
    for (const auto& entry : entries) {
        if (!insertFirewallLogEntry(entry)) {
            allSuccess = false;
            break;
        }
    }

    if (allSuccess) return commitTransaction();
    rollbackTransaction();
    return false;
}

// ============================================================================
// Security Product Log Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertSecurityProductLog(const SecurityProductLogEntry& entry) {
    std::lock_guard<std::mutex> lock(mutex_);

    const char* sql = R"(
        INSERT INTO linux_security_product_logs
        (timestamp, timestamp_unix, tool_type, severity, message, source_file,
         line_number, event_type, target_file, result, parser_name, parser_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    )";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, "Failed to prepare security product log insert");
        return false;
    }

    std::string toolType;
    switch (entry.toolType) {
        case SecurityToolType::Fail2Ban: toolType = "fail2ban"; break;
        case SecurityToolType::ClamAV: toolType = "clamav"; break;
        case SecurityToolType::RKHunter: toolType = "rkhunter"; break;
        case SecurityToolType::Chkrootkit: toolType = "chkrootkit"; break;
        case SecurityToolType::OSSEC: toolType = "ossec"; break;
        case SecurityToolType::AIDE: toolType = "aide"; break;
        default: toolType = "unknown"; break;
    }

    int idx = 1;
    sqlite3_bind_text(stmt, idx++, entry.timestamp.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, idx++, entry.timestampUnix);
    sqlite3_bind_text(stmt, idx++, toolType.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.severity.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.message.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.sourceFile.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, idx++, entry.lineNumber);
    sqlite3_bind_text(stmt, idx++, entry.eventType.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.target.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.result.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.provenance.parserName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.provenance.parserVersion.c_str(), -1, SQLITE_TRANSIENT);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);

    if (!success) {
        setError(ErrorCode::DATABASE_INSERT_FAILED, "Failed to insert security product log");
    }
    return success;
}

bool LinuxAnalysisDatabase::insertSecurityProductLogs(const std::vector<SecurityProductLogEntry>& entries) {
    if (entries.empty()) return true;
    if (!beginTransaction()) return false;

    bool allSuccess = true;
    for (const auto& entry : entries) {
        if (!insertSecurityProductLog(entry)) {
            allSuccess = false;
            break;
        }
    }

    if (allSuccess) return commitTransaction();
    rollbackTransaction();
    return false;
}

// ============================================================================
// Security Product Finding Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertSecurityProductFinding(const SecurityProductFinding& finding) {
    std::lock_guard<std::mutex> lock(mutex_);

    const char* sql = R"(
        INSERT INTO linux_security_product_findings
        (finding_type, severity, description, evidence, source_file, tool_type,
         target_file, parser_name, parser_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    )";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, "Failed to prepare security product finding insert");
        return false;
    }

    std::string toolType;
    switch (finding.toolType) {
        case SecurityToolType::Fail2Ban: toolType = "fail2ban"; break;
        case SecurityToolType::ClamAV: toolType = "clamav"; break;
        case SecurityToolType::RKHunter: toolType = "rkhunter"; break;
        case SecurityToolType::OSSEC: toolType = "ossec"; break;
        case SecurityToolType::AIDE: toolType = "aide"; break;
        default: toolType = "unknown"; break;
    }

    int idx = 1;
    sqlite3_bind_text(stmt, idx++, finding.findingType.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, finding.severity.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, finding.description.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, finding.evidence.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, finding.sourceFile.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, toolType.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, finding.target.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, finding.provenance.parserName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, finding.provenance.parserVersion.c_str(), -1, SQLITE_TRANSIENT);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);

    if (!success) {
        setError(ErrorCode::DATABASE_INSERT_FAILED, "Failed to insert security product finding");
    }
    return success;
}

bool LinuxAnalysisDatabase::insertSecurityProductFindings(const std::vector<SecurityProductFinding>& findings) {
    if (findings.empty()) return true;
    if (!beginTransaction()) return false;

    bool allSuccess = true;
    for (const auto& finding : findings) {
        if (!insertSecurityProductFinding(finding)) {
            allSuccess = false;
            break;
        }
    }

    if (allSuccess) return commitTransaction();
    rollbackTransaction();
    return false;
}
