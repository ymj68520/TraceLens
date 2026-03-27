// LinuxSystemOperations_Part1.cpp
// System-related database operations: shell history, cron jobs, and packages

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
// Shell History Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertShellHistory(const ShellHistoryEntry& entry) {
    const char* sql = LinuxAnalysisSQL::INSERT_SHELL_HISTORY;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        return false;
    }

    BIND_TEXT(stmt, 1, entry.username);
    BIND_TEXT(stmt, 2, entry.shellType);
    BIND_TEXT(stmt, 3, entry.command);
    BIND_INT64(stmt, 4, entry.timestamp);
    BIND_INT(stmt, 5, entry.lineNumber);
    BIND_TEXT(stmt, 6, entry.historyFile);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return success;
}

bool LinuxAnalysisDatabase::insertShellHistories(const std::vector<ShellHistoryEntry>& entries) {
    beginTransaction();
    for (const auto& entry : entries) {
        if (!insertShellHistory(entry)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<ShellHistoryEntry> LinuxAnalysisDatabase::queryShellHistory(const std::string& whereClause) {
    std::vector<ShellHistoryEntry> entries;
    std::string sql = "SELECT username, shell_type, command, timestamp, line_number, history_file FROM linux_shell_history";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        return entries;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        ShellHistoryEntry entry;
        entry.username = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0) ?: (const unsigned char*)"");
        entry.shellType = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1) ?: (const unsigned char*)"");
        entry.command = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2) ?: (const unsigned char*)"");
        entry.timestamp = sqlite3_column_int64(stmt, 3);
        entry.lineNumber = sqlite3_column_int(stmt, 4);
        entry.historyFile = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5) ?: (const unsigned char*)"");
        entries.push_back(entry);
    }

    sqlite3_finalize(stmt);
    return entries;
}

// ============================================================================
// Cron Job Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertCronJob(const CronJobEntry& job) {
    const char* sql = LinuxAnalysisSQL::INSERT_CRON_JOB;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        return false;
    }

    BIND_TEXT(stmt, 1, job.username);
    BIND_TEXT(stmt, 2, job.minute);
    BIND_TEXT(stmt, 3, job.hour);
    BIND_TEXT(stmt, 4, job.dayOfMonth);
    BIND_TEXT(stmt, 5, job.month);
    BIND_TEXT(stmt, 6, job.dayOfWeek);
    BIND_TEXT(stmt, 7, job.command);
    BIND_TEXT(stmt, 8, job.cronFile);
    BIND_TEXT(stmt, 9, job.cronType);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return success;
}

bool LinuxAnalysisDatabase::insertCronJobs(const std::vector<CronJobEntry>& jobs) {
    beginTransaction();
    for (const auto& job : jobs) {
        if (!insertCronJob(job)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<CronJobEntry> LinuxAnalysisDatabase::queryCronJobs(const std::string& whereClause) {
    std::vector<CronJobEntry> jobs;
    std::string sql = "SELECT username, minute, hour, day_of_month, month, day_of_week, command, cron_file, cron_type FROM linux_cron_jobs";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        return jobs;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        CronJobEntry job;
        job.username = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0) ?: (const unsigned char*)"");
        job.minute = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1) ?: (const unsigned char*)"");
        job.hour = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2) ?: (const unsigned char*)"");
        job.dayOfMonth = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3) ?: (const unsigned char*)"");
        job.month = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4) ?: (const unsigned char*)"");
        job.dayOfWeek = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5) ?: (const unsigned char*)"");
        job.command = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6) ?: (const unsigned char*)"");
        job.cronFile = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7) ?: (const unsigned char*)"");
        job.cronType = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 8) ?: (const unsigned char*)"");
        jobs.push_back(job);
    }

    sqlite3_finalize(stmt);
    return jobs;
}

// ============================================================================
// Package Info Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertPackageInfo(const PackageInfo& pkg) {
    const char* sql = LinuxAnalysisSQL::INSERT_PACKAGE_INFO;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        return false;
    }

    BIND_TEXT(stmt, 1, pkg.name);
    BIND_TEXT(stmt, 2, pkg.version);
    BIND_TEXT(stmt, 3, pkg.architecture);
    BIND_INT64(stmt, 4, pkg.installTime);
    BIND_TEXT(stmt, 5, pkg.packageManager);
    BIND_TEXT(stmt, 6, pkg.status);
    BIND_TEXT(stmt, 7, pkg.description);
    BIND_TEXT(stmt, 8, pkg.maintainer);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);
    return success;
}

bool LinuxAnalysisDatabase::insertPackageInfos(const std::vector<PackageInfo>& pkgs) {
    beginTransaction();
    for (const auto& pkg : pkgs) {
        if (!insertPackageInfo(pkg)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<PackageInfo> LinuxAnalysisDatabase::queryPackages(const std::string& whereClause) {
    std::vector<PackageInfo> packages;
    std::string sql = "SELECT name, version, architecture, install_time, package_manager, status, description, maintainer FROM linux_packages";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        return packages;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        PackageInfo pkg;
        pkg.name = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0) ?: (const unsigned char*)"");
        pkg.version = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1) ?: (const unsigned char*)"");
        pkg.architecture = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2) ?: (const unsigned char*)"");
        pkg.installTime = sqlite3_column_int64(stmt, 3);
        pkg.packageManager = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4) ?: (const unsigned char*)"");
        pkg.status = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5) ?: (const unsigned char*)"");
        pkg.description = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6) ?: (const unsigned char*)"");
        pkg.maintainer = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7) ?: (const unsigned char*)"");
        packages.push_back(pkg);
    }

    sqlite3_finalize(stmt);
    return packages;
}

// ============================================================================
// Safe Query Methods (using QueryBuilder for SQL injection protection)
// ============================================================================

std::vector<ShellHistoryEntry> LinuxAnalysisDatabase::queryShellHistorySafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<ShellHistoryEntry> entries;

    std::string sql = "SELECT username, shell_type, command, timestamp, line_number, history_file FROM linux_shell_history";
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
        ShellHistoryEntry entry;
        entry.username = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0) ?: (const unsigned char*)"");
        entry.shellType = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1) ?: (const unsigned char*)"");
        entry.command = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2) ?: (const unsigned char*)"");
        entry.timestamp = sqlite3_column_int64(stmt, 3);
        entry.lineNumber = sqlite3_column_int(stmt, 4);
        entry.historyFile = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5) ?: (const unsigned char*)"");
        entries.push_back(entry);
    }

    sqlite3_finalize(stmt);
    return entries;
}

std::vector<CronJobEntry> LinuxAnalysisDatabase::queryCronJobsSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<CronJobEntry> jobs;

    std::string sql = "SELECT username, minute, hour, day_of_month, month, day_of_week, command, cron_file, cron_type FROM linux_cron_jobs";
    sql += qb.buildFullClause();

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return jobs;
    }

    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        sqlite3_finalize(stmt);
        return jobs;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        CronJobEntry job;
        job.username = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0) ?: (const unsigned char*)"");
        job.minute = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1) ?: (const unsigned char*)"");
        job.hour = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2) ?: (const unsigned char*)"");
        job.dayOfMonth = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3) ?: (const unsigned char*)"");
        job.month = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4) ?: (const unsigned char*)"");
        job.dayOfWeek = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5) ?: (const unsigned char*)"");
        job.command = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6) ?: (const unsigned char*)"");
        job.cronFile = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7) ?: (const unsigned char*)"");
        job.cronType = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 8) ?: (const unsigned char*)"");
        jobs.push_back(job);
    }

    sqlite3_finalize(stmt);
    return jobs;
}

std::vector<PackageInfo> LinuxAnalysisDatabase::queryPackagesSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<PackageInfo> packages;

    std::string sql = "SELECT name, version, architecture, install_time, package_manager, status, description, maintainer FROM linux_packages";
    sql += qb.buildFullClause();

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return packages;
    }

    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        sqlite3_finalize(stmt);
        return packages;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        PackageInfo pkg;
        pkg.name = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0) ?: (const unsigned char*)"");
        pkg.version = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1) ?: (const unsigned char*)"");
        pkg.architecture = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2) ?: (const unsigned char*)"");
        pkg.installTime = sqlite3_column_int64(stmt, 3);
        pkg.packageManager = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4) ?: (const unsigned char*)"");
        pkg.status = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5) ?: (const unsigned char*)"");
        pkg.description = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6) ?: (const unsigned char*)"");
        pkg.maintainer = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7) ?: (const unsigned char*)"");
        packages.push_back(pkg);
    }

    sqlite3_finalize(stmt);
    return packages;
}
