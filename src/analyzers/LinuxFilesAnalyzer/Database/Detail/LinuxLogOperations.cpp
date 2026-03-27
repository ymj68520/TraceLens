// LinuxLogOperations.cpp
// Log entry and audit log database operations

#include "LinuxAnalysisDatabase.h"
#include "LinuxQueryBuilder.h"
#include "DatabaseManager/SQL/linux_analysis_sql.h"
#include <iostream>
#include <sstream>
#include <mutex>

using namespace LinuxAnalysis;

// Helper macros for binding
#define BIND_TEXT(stmt, index, text) \
    sqlite3_bind_text(stmt, index, text.c_str(), -1, SQLITE_TRANSIENT)

#define BIND_INT64(stmt, index, val) \
    sqlite3_bind_int64(stmt, index, val)

#define BIND_INT(stmt, index, val) \
    sqlite3_bind_int(stmt, index, val)

// ============================================================================
// Log Entry Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertLogEntry(const LinuxLogEntry& entry) {
    const char* sql = LinuxAnalysisSQL::INSERT_LOG_ENTRY;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        return false;
    }

    BIND_TEXT(stmt, 1, entry.logFile);
    BIND_TEXT(stmt, 2, entry.timestamp);
    BIND_INT64(stmt, 3, entry.unixTimestamp);
    BIND_TEXT(stmt, 4, entry.hostname);
    BIND_TEXT(stmt, 5, entry.process);
    BIND_INT(stmt, 6, entry.pid);
    BIND_TEXT(stmt, 7, entry.message);
    BIND_TEXT(stmt, 8, entry.level);
    BIND_TEXT(stmt, 9, entry.facility);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return success;
}

bool LinuxAnalysisDatabase::insertLogEntries(const std::vector<LinuxLogEntry>& entries) {
    beginTransaction();
    for (const auto& entry : entries) {
        if (!insertLogEntry(entry)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<LinuxLogEntry> LinuxAnalysisDatabase::queryLogEntries(const std::string& whereClause) {
    std::vector<LinuxLogEntry> entries;
    std::string sql = "SELECT log_file, timestamp, unix_timestamp, hostname, process, pid, message, level, facility FROM linux_log_entries";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        return entries;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        LinuxLogEntry entry;
        entry.logFile = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0) ?: (const unsigned char*)"");
        entry.timestamp = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1) ?: (const unsigned char*)"");
        entry.unixTimestamp = sqlite3_column_int64(stmt, 2);
        entry.hostname = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3) ?: (const unsigned char*)"");
        entry.process = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4) ?: (const unsigned char*)"");
        entry.pid = sqlite3_column_int(stmt, 5);
        entry.message = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6) ?: (const unsigned char*)"");
        entry.level = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7) ?: (const unsigned char*)"");
        entry.facility = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 8) ?: (const unsigned char*)"");
        entries.push_back(entry);
    }

    sqlite3_finalize(stmt);
    return entries;
}

// ============================================================================
// Audit Log Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertAuditLog(const LinuxAuditLogEntry& entry) {
    const char* sql = LinuxAnalysisSQL::INSERT_AUDIT_LOG;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        return false;
    }

    BIND_INT64(stmt, 1, entry.timestamp);
    BIND_INT(stmt, 2, entry.serialNumber);
    BIND_TEXT(stmt, 3, entry.type);
    BIND_TEXT(stmt, 4, entry.message);
    BIND_TEXT(stmt, 5, entry.subject);
    BIND_TEXT(stmt, 6, entry.object);
    BIND_TEXT(stmt, 7, entry.action);
    BIND_TEXT(stmt, 8, entry.result);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return success;
}

bool LinuxAnalysisDatabase::insertAuditLogs(const std::vector<LinuxAuditLogEntry>& entries) {
    beginTransaction();
    for (const auto& entry : entries) {
        if (!insertAuditLog(entry)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<LinuxAuditLogEntry> LinuxAnalysisDatabase::queryAuditLogs(const std::string& whereClause) {
    std::vector<LinuxAuditLogEntry> entries;
    std::string sql = "SELECT timestamp, serial_number, type, message, subject, object, action, result FROM linux_audit_logs";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        return entries;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        LinuxAuditLogEntry entry;
        entry.timestamp = sqlite3_column_int64(stmt, 0);
        entry.serialNumber = sqlite3_column_int(stmt, 1);
        entry.type = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2) ?: (const unsigned char*)"");
        entry.message = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3) ?: (const unsigned char*)"");
        entry.subject = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4) ?: (const unsigned char*)"");
        entry.object = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5) ?: (const unsigned char*)"");
        entry.action = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6) ?: (const unsigned char*)"");
        entry.result = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7) ?: (const unsigned char*)"");
        entries.push_back(entry);
    }

    sqlite3_finalize(stmt);
    return entries;
}

// ============================================================================
// Safe Query Methods (using QueryBuilder for SQL injection protection)
// ============================================================================

std::vector<LinuxLogEntry> LinuxAnalysisDatabase::queryLogEntriesSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<LinuxLogEntry> entries;

    std::string sql = "SELECT log_file, timestamp, unix_timestamp, hostname, process, pid, message, level, facility FROM linux_log_entries";
    sql += qb.buildFullClause();

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return entries;
    }

    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        sqlite3_finalize(stmt);
        return entries;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        LinuxLogEntry entry;
        entry.logFile = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0) ?: (const unsigned char*)"");
        entry.timestamp = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1) ?: (const unsigned char*)"");
        entry.unixTimestamp = sqlite3_column_int64(stmt, 2);
        entry.hostname = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3) ?: (const unsigned char*)"");
        entry.process = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4) ?: (const unsigned char*)"");
        entry.pid = sqlite3_column_int(stmt, 5);
        entry.message = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6) ?: (const unsigned char*)"");
        entry.level = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7) ?: (const unsigned char*)"");
        entry.facility = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 8) ?: (const unsigned char*)"");
        entries.push_back(entry);
    }

    sqlite3_finalize(stmt);
    return entries;
}

std::vector<LinuxAuditLogEntry> LinuxAnalysisDatabase::queryAuditLogsSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<LinuxAuditLogEntry> entries;

    std::string sql = "SELECT timestamp, serial_number, type, message, subject, object, action, result FROM linux_audit_logs";
    sql += qb.buildFullClause();

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return entries;
    }

    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        sqlite3_finalize(stmt);
        return entries;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        LinuxAuditLogEntry entry;
        entry.timestamp = sqlite3_column_int64(stmt, 0);
        entry.serialNumber = sqlite3_column_int(stmt, 1);
        entry.type = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2) ?: (const unsigned char*)"");
        entry.message = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3) ?: (const unsigned char*)"");
        entry.subject = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4) ?: (const unsigned char*)"");
        entry.object = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5) ?: (const unsigned char*)"");
        entry.action = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6) ?: (const unsigned char*)"");
        entry.result = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7) ?: (const unsigned char*)"");
        entries.push_back(entry);
    }

    sqlite3_finalize(stmt);
    return entries;
}
