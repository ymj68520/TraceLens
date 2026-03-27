// LinuxAnalysisDatabaseCore.cpp
// Core database operations: initialization, transactions, and error handling

#include "LinuxAnalysisDatabase.h"
#include "LinuxQueryBuilder.h"
#include <iostream>
#include "DatabaseManager/SQL/linux_analysis_sql.h"
#include <sstream>
#include <mutex>

using namespace LinuxAnalysis;

// ============================================================================
// Constructor and Destructor
// ============================================================================

LinuxAnalysisDatabase::LinuxAnalysisDatabase(const std::string& dbPath)
    : dbPath_(dbPath), db_(nullptr), lastError_() {
}

LinuxAnalysisDatabase::~LinuxAnalysisDatabase() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (db_) {
        sqlite3_close(db_);
        db_ = nullptr;
    }
}

// ============================================================================
// Database Initialization
// ============================================================================

bool LinuxAnalysisDatabase::initialize() {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();

    int rc = sqlite3_open(dbPath_.c_str(), &db_);
    if (rc != SQLITE_OK) {
        setError(ErrorCode::DATABASE_OPEN_FAILED, sqlite3_errmsg(db_));
        std::cerr << "Cannot open database: " << sqlite3_errmsg(db_) << std::endl;
        return false;
    }
    return createTables();
}

bool LinuxAnalysisDatabase::createTables() {
    using namespace LinuxAnalysisSQL;

    // Execute all create statements
    if (!executeSQL(CREATE_LOG_ENTRIES_TABLE) ||
        !executeSQL(CREATE_USERS_TABLE) ||
        !executeSQL(CREATE_GROUPS_TABLE) ||
        !executeSQL(CREATE_LOGIN_RECORDS_TABLE) ||
        !executeSQL(CREATE_SHELL_HISTORY_TABLE) ||
        !executeSQL(CREATE_CRON_JOBS_TABLE) ||
        !executeSQL(CREATE_SSH_KEYS_TABLE) ||
        !executeSQL(CREATE_SSH_KNOWN_HOSTS_TABLE) ||
        !executeSQL(CREATE_PACKAGES_TABLE) ||
        !executeSQL(CREATE_NETWORK_CONNECTIONS_TABLE) ||
        !executeSQL(CREATE_SYSTEMD_SERVICES_TABLE) ||
        !executeSQL(CREATE_KERNEL_MODULES_TABLE) ||
        !executeSQL(CREATE_FIREWALL_RULES_TABLE) ||
        !executeSQL(CREATE_AUDIT_LOGS_TABLE) ||
        !executeSQL(CREATE_BROWSER_PROFILES_TABLE)) {
        setError(ErrorCode::DATABASE_CREATE_TABLE_FAILED);
        return false;
    }
    return true;
}

bool LinuxAnalysisDatabase::executeSQL(const std::string& sql) {
    char* errMsg = nullptr;
    int rc = sqlite3_exec(db_, sql.c_str(), nullptr, nullptr, &errMsg);
    if (rc != SQLITE_OK) {
        std::string errorStr = errMsg ? errMsg : "Unknown SQL error";
        std::cerr << "SQL error: " << errorStr << std::endl;
        sqlite3_free(errMsg);
        setError(ErrorCode::DATABASE_EXECUTE_FAILED, errorStr);
        return false;
    }
    return true;
}

// ============================================================================
// Error Handling
// ============================================================================

void LinuxAnalysisDatabase::setError(ErrorCode code, const std::string& details) {
    lastError_ = LinuxAnalyzerError(code, details);
}

void LinuxAnalysisDatabase::setError(const LinuxAnalyzerError& error) {
    lastError_ = error;
}

LinuxAnalyzerError LinuxAnalysisDatabase::getSQLiteError(ErrorCode code) const {
    const char* errMsg = sqlite3_errmsg(db_);
    return LinuxAnalyzerError(code, errMsg ? errMsg : "Unknown SQLite error");
}

// ============================================================================
// Transaction Management
// ============================================================================

bool LinuxAnalysisDatabase::beginTransaction() {
    std::lock_guard<std::mutex> lock(mutex_);
    return executeSQL("BEGIN TRANSACTION");
}

bool LinuxAnalysisDatabase::commitTransaction() {
    std::lock_guard<std::mutex> lock(mutex_);
    return executeSQL("COMMIT");
}

bool LinuxAnalysisDatabase::rollbackTransaction() {
    std::lock_guard<std::mutex> lock(mutex_);
    return executeSQL("ROLLBACK");
}
