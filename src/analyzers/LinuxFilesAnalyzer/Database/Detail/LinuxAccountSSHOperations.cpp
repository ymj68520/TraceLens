// LinuxAccountSSHOperations.cpp
// Database operations for account and SSH security findings (Phase 10)

#include <sstream>

using forensics::linux::AccountSecurityFinding;
using forensics::linux::SSHSecurityFinding;

// ============================================================================
// Account Security Finding Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertAccountSecurityFinding(const AccountSecurityFinding& finding) {
    std::lock_guard<std::mutex> lock(mutex_);

    const char* sql = R"(
        INSERT INTO linux_account_security_findings
        (finding_type, severity, username, description, evidence, file_path,
         parser_name, parser_version, source_file)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    )";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, "Failed to prepare account security finding insert");
        return false;
    }

    sqlite3_bind_text(stmt, 1, finding.findingType.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, finding.severity.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, finding.username.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, finding.description.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 5, finding.evidence.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 6, finding.filePath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 7, finding.provenance.parserName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 8, finding.provenance.parserVersion.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 9, finding.provenance.sourceFile.c_str(), -1, SQLITE_TRANSIENT);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);

    if (!success) {
        setError(ErrorCode::DATABASE_INSERT_FAILED, "Failed to insert account security finding");
    }
    return success;
}

bool LinuxAnalysisDatabase::insertAccountSecurityFindings(const std::vector<AccountSecurityFinding>& findings) {
    if (findings.empty()) return true;
    if (!beginTransaction()) return false;

    bool allSuccess = true;
    for (const auto& finding : findings) {
        if (!insertAccountSecurityFinding(finding)) {
            allSuccess = false;
            break;
        }
    }

    if (allSuccess) return commitTransaction();
    rollbackTransaction();
    return false;
}

// ============================================================================
// SSH Security Finding Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertSSHSecurityFinding(const SSHSecurityFinding& finding) {
    std::lock_guard<std::mutex> lock(mutex_);

    const char* sql = R"(
        INSERT INTO linux_ssh_security_findings
        (finding_type, severity, description, evidence, file_path, username, hostname,
         key_type, parser_name, parser_version, source_file)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    )";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, "Failed to prepare SSH security finding insert");
        return false;
    }

    sqlite3_bind_text(stmt, 1, finding.findingType.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, finding.severity.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, finding.description.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, finding.evidence.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 5, finding.filePath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 6, finding.username.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 7, finding.hostname.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 8, finding.keyType.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 9, finding.provenance.parserName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 10, finding.provenance.parserVersion.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 11, finding.provenance.sourceFile.c_str(), -1, SQLITE_TRANSIENT);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);

    if (!success) {
        setError(ErrorCode::DATABASE_INSERT_FAILED, "Failed to insert SSH security finding");
    }
    return success;
}

bool LinuxAnalysisDatabase::insertSSHSecurityFindings(const std::vector<SSHSecurityFinding>& findings) {
    if (findings.empty()) return true;
    if (!beginTransaction()) return false;

    bool allSuccess = true;
    for (const auto& finding : findings) {
        if (!insertSSHSecurityFinding(finding)) {
            allSuccess = false;
            break;
        }
    }

    if (allSuccess) return commitTransaction();
    rollbackTransaction();
    return false;
}
