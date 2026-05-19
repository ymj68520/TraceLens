// LinuxDatabaseLogOperations.cpp
// Database operations for database service logs (Phase 11)

#include <sstream>

using forensics::linux::DatabaseLogEntry;
using forensics::linux::DatabaseSecurityFinding;
using forensics::linux::DatabaseType;

// ============================================================================
// Database Log Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertDatabaseLog(const DatabaseLogEntry& entry) {
    std::lock_guard<std::mutex> lock(mutex_);

    const char* sql = R"(
        INSERT INTO linux_database_logs
        (timestamp, timestamp_unix, db_type, severity, component, message, source_file,
         line_number, username, database_name, client_addr, query_text, error_code,
         parser_name, parser_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    )";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, "Failed to prepare database log insert");
        return false;
    }

    std::string dbTypeStr;
    switch (entry.dbType) {
        case DatabaseType::MySQL: dbTypeStr = "mysql"; break;
        case DatabaseType::MariaDB: dbTypeStr = "mariadb"; break;
        case DatabaseType::PostgreSQL: dbTypeStr = "postgresql"; break;
        case DatabaseType::MongoDB: dbTypeStr = "mongodb"; break;
        case DatabaseType::Redis: dbTypeStr = "redis"; break;
        default: dbTypeStr = "unknown"; break;
    }

    int idx = 1;
    sqlite3_bind_text(stmt, idx++, entry.timestamp.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, idx++, entry.timestampUnix);
    sqlite3_bind_text(stmt, idx++, dbTypeStr.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.severity.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.component.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.message.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.sourceFile.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, idx++, entry.lineNumber);
    sqlite3_bind_text(stmt, idx++, entry.username.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.database.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.clientAddr.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.query.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, idx++, entry.errorCode);
    sqlite3_bind_text(stmt, idx++, entry.provenance.parserName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, entry.provenance.parserVersion.c_str(), -1, SQLITE_TRANSIENT);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);

    if (!success) {
        setError(ErrorCode::DATABASE_INSERT_FAILED, "Failed to insert database log");
    }
    return success;
}

bool LinuxAnalysisDatabase::insertDatabaseLogs(const std::vector<DatabaseLogEntry>& entries) {
    if (entries.empty()) return true;
    if (!beginTransaction()) return false;

    bool allSuccess = true;
    for (const auto& entry : entries) {
        if (!insertDatabaseLog(entry)) {
            allSuccess = false;
            break;
        }
    }

    if (allSuccess) return commitTransaction();
    rollbackTransaction();
    return false;
}

// ============================================================================
// Database Security Finding Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertDatabaseSecurityFinding(const DatabaseSecurityFinding& finding) {
    std::lock_guard<std::mutex> lock(mutex_);

    const char* sql = R"(
        INSERT INTO linux_database_security_findings
        (finding_type, severity, description, evidence, source_file, db_type,
         username, client_addr, parser_name, parser_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    )";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, "Failed to prepare database security finding insert");
        return false;
    }

    std::string dbTypeStr;
    switch (finding.dbType) {
        case DatabaseType::MySQL: dbTypeStr = "mysql"; break;
        case DatabaseType::MariaDB: dbTypeStr = "mariadb"; break;
        case DatabaseType::PostgreSQL: dbTypeStr = "postgresql"; break;
        case DatabaseType::MongoDB: dbTypeStr = "mongodb"; break;
        case DatabaseType::Redis: dbTypeStr = "redis"; break;
        default: dbTypeStr = "unknown"; break;
    }

    int idx = 1;
    sqlite3_bind_text(stmt, idx++, finding.findingType.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, finding.severity.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, finding.description.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, finding.evidence.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, finding.sourceFile.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, dbTypeStr.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, finding.username.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, finding.clientAddr.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, finding.provenance.parserName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, idx++, finding.provenance.parserVersion.c_str(), -1, SQLITE_TRANSIENT);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);

    if (!success) {
        setError(ErrorCode::DATABASE_INSERT_FAILED, "Failed to insert database security finding");
    }
    return success;
}

bool LinuxAnalysisDatabase::insertDatabaseSecurityFindings(const std::vector<DatabaseSecurityFinding>& findings) {
    if (findings.empty()) return true;
    if (!beginTransaction()) return false;

    bool allSuccess = true;
    for (const auto& finding : findings) {
        if (!insertDatabaseSecurityFinding(finding)) {
            allSuccess = false;
            break;
        }
    }

    if (allSuccess) return commitTransaction();
    rollbackTransaction();
    return false;
}
