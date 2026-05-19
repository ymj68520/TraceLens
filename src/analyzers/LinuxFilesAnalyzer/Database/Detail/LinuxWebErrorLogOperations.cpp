// LinuxWebErrorLogOperations.cpp
// Database operations for web error logs, middleware logs, and ModSecurity logs (Phase 7)

#include <sstream>

// ============================================================================
// Web Error Log Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertWebErrorLog(const WebErrorLogEntry& entry) {
    std::lock_guard<std::mutex> lock(mutex_);

    const char* sql = R"(
        INSERT INTO linux_web_error_logs
        (timestamp, level, source, client_ip, message, module, pid, file_path,
         parser_name, parser_version, source_file, raw_record)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    )";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, "Failed to prepare insertWebErrorLog: " + std::string(sqlite3_errmsg(db_)));
        return false;
    }

    sqlite3_bind_int64(stmt, 1, entry.timestamp);
    sqlite3_bind_text(stmt, 2, entry.level.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, entry.source.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, entry.clientIp.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 5, entry.message.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 6, entry.module.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 7, entry.pid.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 8, entry.filePath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 9, entry.provenance.parserName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 10, entry.provenance.parserVersion.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 11, entry.provenance.sourceFile.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 12, entry.provenance.rawRecord.c_str(), -1, SQLITE_TRANSIENT);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);

    if (!success) {
        setError(ErrorCode::DATABASE_INSERT_FAILED, "Failed to insert web error log: " + std::string(sqlite3_errmsg(db_)));
    }
    return success;
}

bool LinuxAnalysisDatabase::insertWebErrorLogs(const std::vector<WebErrorLogEntry>& entries) {
    if (entries.empty()) return true;

    if (!beginTransaction()) return false;

    bool allSuccess = true;
    for (const auto& entry : entries) {
        if (!insertWebErrorLog(entry)) {
            allSuccess = false;
            break;
        }
    }

    if (allSuccess) {
        return commitTransaction();
    } else {
        rollbackTransaction();
        return false;
    }
}

std::vector<WebErrorLogEntry> LinuxAnalysisDatabase::queryWebErrorLogsSafe(const LinuxAnalysis::QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    std::vector<WebErrorLogEntry> results;

    std::string sql = "SELECT id, timestamp, level, source, client_ip, message, module, pid, file_path, "
                      "parser_name, parser_version, source_file, raw_record FROM linux_web_error_logs";
    std::string whereClause = qb.buildWhereClause();
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }
    sql += " ORDER BY timestamp DESC";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_QUERY_FAILED, "Failed to query web error logs: " + std::string(sqlite3_errmsg(db_)));
        return results;
    }

    qb.bindParameters(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        WebErrorLogEntry entry;
        entry.timestamp = sqlite3_column_int64(stmt, 1);
        entry.level = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
        entry.source = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3));
        entry.clientIp = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4));
        entry.message = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5));
        entry.module = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6));
        entry.pid = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7));
        entry.filePath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 8));
        entry.provenance.parserName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 9));
        entry.provenance.parserVersion = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 10));
        entry.provenance.sourceFile = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 11));
        entry.provenance.rawRecord = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 12));
        results.push_back(entry);
    }

    sqlite3_finalize(stmt);
    return results;
}

// ============================================================================
// Middleware Log Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertMiddlewareLog(const MiddlewareLogEntry& entry) {
    std::lock_guard<std::mutex> lock(mutex_);

    const char* sql = R"(
        INSERT INTO linux_middleware_logs
        (timestamp, level, source, logger, message, thread, exception, pid, file_path,
         parser_name, parser_version, source_file, raw_record)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    )";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, "Failed to prepare insertMiddlewareLog: " + std::string(sqlite3_errmsg(db_)));
        return false;
    }

    sqlite3_bind_int64(stmt, 1, entry.timestamp);
    sqlite3_bind_text(stmt, 2, entry.level.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, entry.source.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, entry.logger.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 5, entry.message.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 6, entry.thread.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 7, entry.exception.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 8, entry.pid.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 9, entry.filePath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 10, entry.provenance.parserName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 11, entry.provenance.parserVersion.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 12, entry.provenance.sourceFile.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 13, entry.provenance.rawRecord.c_str(), -1, SQLITE_TRANSIENT);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);

    if (!success) {
        setError(ErrorCode::DATABASE_INSERT_FAILED, "Failed to insert middleware log: " + std::string(sqlite3_errmsg(db_)));
    }
    return success;
}

bool LinuxAnalysisDatabase::insertMiddlewareLogs(const std::vector<MiddlewareLogEntry>& entries) {
    if (entries.empty()) return true;

    if (!beginTransaction()) return false;

    bool allSuccess = true;
    for (const auto& entry : entries) {
        if (!insertMiddlewareLog(entry)) {
            allSuccess = false;
            break;
        }
    }

    if (allSuccess) {
        return commitTransaction();
    } else {
        rollbackTransaction();
        return false;
    }
}

std::vector<MiddlewareLogEntry> LinuxAnalysisDatabase::queryMiddlewareLogsSafe(const LinuxAnalysis::QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    std::vector<MiddlewareLogEntry> results;

    std::string sql = "SELECT id, timestamp, level, source, logger, message, thread, exception, pid, file_path, "
                      "parser_name, parser_version, source_file, raw_record FROM linux_middleware_logs";
    std::string whereClause = qb.buildWhereClause();
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }
    sql += " ORDER BY timestamp DESC";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_QUERY_FAILED, "Failed to query middleware logs: " + std::string(sqlite3_errmsg(db_)));
        return results;
    }

    qb.bindParameters(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        MiddlewareLogEntry entry;
        entry.timestamp = sqlite3_column_int64(stmt, 1);
        entry.level = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
        entry.source = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3));
        entry.logger = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4));
        entry.message = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5));
        entry.thread = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6));
        const char* exc = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7));
        entry.exception = exc ? exc : "";
        const char* pid = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 8));
        entry.pid = pid ? pid : "";
        entry.filePath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 9));
        entry.provenance.parserName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 10));
        entry.provenance.parserVersion = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 11));
        entry.provenance.sourceFile = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 12));
        const char* raw = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 13));
        entry.provenance.rawRecord = raw ? raw : "";
        results.push_back(entry);
    }

    sqlite3_finalize(stmt);
    return results;
}

// ============================================================================
// ModSecurity Audit Log Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertModSecurityLog(const ModSecurityAuditEntry& entry) {
    std::lock_guard<std::mutex> lock(mutex_);

    const char* sql = R"(
        INSERT INTO linux_modsecurity_logs
        (timestamp, client_ip, method, uri, rule_id, rule_message, severity, action, file_path,
         parser_name, parser_version, source_file, raw_record)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    )";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, "Failed to prepare insertModSecurityLog: " + std::string(sqlite3_errmsg(db_)));
        return false;
    }

    sqlite3_bind_int64(stmt, 1, entry.timestamp);
    sqlite3_bind_text(stmt, 2, entry.clientIp.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, entry.method.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, entry.uri.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 5, entry.ruleId.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 6, entry.ruleMessage.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 7, entry.severity.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 8, entry.action.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 9, entry.filePath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 10, entry.provenance.parserName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 11, entry.provenance.parserVersion.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 12, entry.provenance.sourceFile.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 13, entry.provenance.rawRecord.c_str(), -1, SQLITE_TRANSIENT);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);

    if (!success) {
        setError(ErrorCode::DATABASE_INSERT_FAILED, "Failed to insert ModSecurity log: " + std::string(sqlite3_errmsg(db_)));
    }
    return success;
}

bool LinuxAnalysisDatabase::insertModSecurityLogs(const std::vector<ModSecurityAuditEntry>& entries) {
    if (entries.empty()) return true;

    if (!beginTransaction()) return false;

    bool allSuccess = true;
    for (const auto& entry : entries) {
        if (!insertModSecurityLog(entry)) {
            allSuccess = false;
            break;
        }
    }

    if (allSuccess) {
        return commitTransaction();
    } else {
        rollbackTransaction();
        return false;
    }
}

std::vector<ModSecurityAuditEntry> LinuxAnalysisDatabase::queryModSecurityLogsSafe(const LinuxAnalysis::QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    std::vector<ModSecurityAuditEntry> results;

    std::string sql = "SELECT id, timestamp, client_ip, method, uri, rule_id, rule_message, severity, action, file_path, "
                      "parser_name, parser_version, source_file, raw_record FROM linux_modsecurity_logs";
    std::string whereClause = qb.buildWhereClause();
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }
    sql += " ORDER BY timestamp DESC";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_QUERY_FAILED, "Failed to query ModSecurity logs: " + std::string(sqlite3_errmsg(db_)));
        return results;
    }

    qb.bindParameters(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        ModSecurityAuditEntry entry;
        entry.timestamp = sqlite3_column_int64(stmt, 1);
        entry.clientIp = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
        entry.method = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3));
        entry.uri = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4));
        entry.ruleId = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5));
        entry.ruleMessage = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6));
        const char* sev = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7));
        entry.severity = sev ? sev : "";
        const char* act = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 8));
        entry.action = act ? act : "";
        entry.filePath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 9));
        entry.provenance.parserName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 10));
        entry.provenance.parserVersion = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 11));
        entry.provenance.sourceFile = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 12));
        const char* raw = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 13));
        entry.provenance.rawRecord = raw ? raw : "";
        results.push_back(entry);
    }

    sqlite3_finalize(stmt);
    return results;
}
