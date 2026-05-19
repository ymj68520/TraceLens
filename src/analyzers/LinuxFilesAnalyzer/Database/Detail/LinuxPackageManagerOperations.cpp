// LinuxPackageManagerOperations.cpp
// Database operations for package manager logs and suspicious package findings (Phase 9)

#include <sstream>

using forensics::linux::PackageLogEntry;
using forensics::linux::SuspiciousPackageFinding;
using forensics::linux::PackageOperation;

// ============================================================================
// Package Log Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertPackageLog(const PackageLogEntry& entry) {
    std::lock_guard<std::mutex> lock(mutex_);

    const char* sql = R"(
        INSERT INTO linux_package_logs
        (timestamp, package_manager, package_name, package_version, architecture,
         operation, operation_detail, status, user_name, command_line, file_path,
         parser_name, parser_version, source_file, raw_record)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    )";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, "Failed to prepare package log insert");
        return false;
    }

    sqlite3_bind_int64(stmt, 1, entry.timestamp);
    sqlite3_bind_text(stmt, 2, entry.packageManager.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, entry.packageName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, entry.packageVersion.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 5, entry.architecture.c_str(), -1, SQLITE_TRANSIENT);

    std::string opStr;
    switch (entry.operation) {
        case PackageOperation::INSTALL: opStr = "install"; break;
        case PackageOperation::REMOVE: opStr = "remove"; break;
        case PackageOperation::UPGRADE: opStr = "upgrade"; break;
        case PackageOperation::DOWNGRADE: opStr = "downgrade"; break;
        case PackageOperation::PURGE: opStr = "purge"; break;
        case PackageOperation::REINSTALL: opStr = "reinstall"; break;
        case PackageOperation::HOLD: opStr = "hold"; break;
        case PackageOperation::UNHOLD: opStr = "unhold"; break;
        case PackageOperation::CONFIGURE: opStr = "configure"; break;
        case PackageOperation::TRIGGERS: opStr = "triggers"; break;
        default: opStr = "unknown"; break;
    }
    sqlite3_bind_text(stmt, 6, opStr.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 7, entry.operationDetail.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 8, entry.status.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 9, entry.user.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 10, entry.commandLine.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 11, entry.filePath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 12, entry.provenance.parserName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 13, entry.provenance.parserVersion.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 14, entry.provenance.sourceFile.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 15, entry.provenance.rawRecord.c_str(), -1, SQLITE_TRANSIENT);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);

    if (!success) {
        setError(ErrorCode::DATABASE_INSERT_FAILED, "Failed to insert package log");
    }
    return success;
}

bool LinuxAnalysisDatabase::insertPackageLogs(const std::vector<PackageLogEntry>& entries) {
    if (entries.empty()) return true;
    if (!beginTransaction()) return false;

    bool allSuccess = true;
    for (const auto& entry : entries) {
        if (!insertPackageLog(entry)) {
            allSuccess = false;
            break;
        }
    }

    if (allSuccess) return commitTransaction();
    rollbackTransaction();
    return false;
}

// ============================================================================
// Suspicious Package Finding Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertSuspiciousPackageFinding(const SuspiciousPackageFinding& finding) {
    std::lock_guard<std::mutex> lock(mutex_);

    const char* sql = R"(
        INSERT INTO linux_suspicious_packages
        (finding_type, severity, package_name, package_version, description, evidence,
         file_path, parser_name, parser_version, source_file)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    )";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, "Failed to prepare suspicious package finding insert");
        return false;
    }

    sqlite3_bind_text(stmt, 1, finding.findingType.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, finding.severity.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, finding.packageName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, finding.packageVersion.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 5, finding.description.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 6, finding.evidence.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 7, finding.filePath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 8, finding.provenance.parserName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 9, finding.provenance.parserVersion.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 10, finding.provenance.sourceFile.c_str(), -1, SQLITE_TRANSIENT);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);

    if (!success) {
        setError(ErrorCode::DATABASE_INSERT_FAILED, "Failed to insert suspicious package finding");
    }
    return success;
}

bool LinuxAnalysisDatabase::insertSuspiciousPackageFindings(const std::vector<SuspiciousPackageFinding>& findings) {
    if (findings.empty()) return true;
    if (!beginTransaction()) return false;

    bool allSuccess = true;
    for (const auto& finding : findings) {
        if (!insertSuspiciousPackageFinding(finding)) {
            allSuccess = false;
            break;
        }
    }

    if (allSuccess) return commitTransaction();
    rollbackTransaction();
    return false;
}

// ============================================================================
// Package Log Query Operations
// ============================================================================

std::vector<PackageLogEntry> LinuxAnalysisDatabase::queryPackageLogsSafe(const LinuxAnalysis::QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    std::vector<PackageLogEntry> results;

    std::string whereClause = qb.buildWhereClause();
    std::string sql = "SELECT id, timestamp, package_manager, package_name, package_version, "
                      "architecture, operation, operation_detail, status, user_name, command_line, "
                      "file_path, parser_name, parser_version, source_file, raw_record "
                      "FROM linux_package_logs";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }
    sql += " ORDER BY timestamp DESC";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, "Failed to prepare package logs query");
        return results;
    }

    qb.bindParameters(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        PackageLogEntry entry;
        int idx = 0;
        // skip id
        idx++;
        entry.timestamp = sqlite3_column_int64(stmt, idx++);
        entry.packageManager = reinterpret_cast<const char*>(sqlite3_column_text(stmt, idx++));
        entry.packageName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, idx++));
        entry.packageVersion = reinterpret_cast<const char*>(sqlite3_column_text(stmt, idx++));
        entry.architecture = reinterpret_cast<const char*>(sqlite3_column_text(stmt, idx++));

        std::string opStr = reinterpret_cast<const char*>(sqlite3_column_text(stmt, idx++));
        if (opStr == "install") entry.operation = PackageOperation::INSTALL;
        else if (opStr == "remove") entry.operation = PackageOperation::REMOVE;
        else if (opStr == "upgrade") entry.operation = PackageOperation::UPGRADE;
        else if (opStr == "downgrade") entry.operation = PackageOperation::DOWNGRADE;
        else if (opStr == "purge") entry.operation = PackageOperation::PURGE;
        else if (opStr == "reinstall") entry.operation = PackageOperation::REINSTALL;
        else entry.operation = PackageOperation::UNKNOWN;

        entry.operationDetail = reinterpret_cast<const char*>(sqlite3_column_text(stmt, idx++));
        entry.status = reinterpret_cast<const char*>(sqlite3_column_text(stmt, idx++));
        entry.user = reinterpret_cast<const char*>(sqlite3_column_text(stmt, idx++));
        entry.commandLine = reinterpret_cast<const char*>(sqlite3_column_text(stmt, idx++));
        entry.filePath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, idx++));
        entry.provenance.parserName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, idx++));
        entry.provenance.parserVersion = reinterpret_cast<const char*>(sqlite3_column_text(stmt, idx++));
        entry.provenance.sourceFile = reinterpret_cast<const char*>(sqlite3_column_text(stmt, idx++));
        entry.provenance.rawRecord = reinterpret_cast<const char*>(sqlite3_column_text(stmt, idx++));

        results.push_back(entry);
    }

    sqlite3_finalize(stmt);
    return results;
}
