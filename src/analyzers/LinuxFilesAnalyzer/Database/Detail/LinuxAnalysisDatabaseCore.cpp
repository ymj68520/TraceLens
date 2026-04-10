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

    // Execute the consolidated CREATE_ALL_TABLES statement
    if (!executeSQL(CREATE_ALL_TABLES)) {
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
