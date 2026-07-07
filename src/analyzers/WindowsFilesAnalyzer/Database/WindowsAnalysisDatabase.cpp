// WindowsAnalysisDatabase.cpp
// Database manager for storing Windows forensic analysis results

#include "WindowsAnalysisDatabase.h"
#include "DatabaseManager/SQL/windows_analysis_sql.h"
#include "DatabaseManager/SQL/file_classifier_sql.h"
#include <iostream>
#include <sstream>

// Data access operations are now in WindowsDBOperations.cpp
// This file contains only core database management

WindowsAnalysisDatabase::WindowsAnalysisDatabase(const std::string& dbPath, bool integratedMode)
    : dbPath_(dbPath), db_(nullptr), integratedMode_(integratedMode) {
}

WindowsAnalysisDatabase::~WindowsAnalysisDatabase() {
    if (db_) {
        sqlite3_close(db_);
        db_ = nullptr;
    }
}

bool WindowsAnalysisDatabase::initialize() {
    int rc = sqlite3_open(dbPath_.c_str(), &db_);
    if (rc != SQLITE_OK) {
        std::cerr << "Cannot open database: " << sqlite3_errmsg(db_) << std::endl;
        return false;
    }

    // Write-performance pragmas (see LinuxAnalysisDatabase for rationale):
    // without WAL + relaxed sync, every commit fsyncs and stalls on disk.
    sqlite3_exec(db_, "PRAGMA journal_mode=WAL;", nullptr, nullptr, nullptr);
    sqlite3_exec(db_, "PRAGMA synchronous=NORMAL;", nullptr, nullptr, nullptr);
    sqlite3_busy_timeout(db_, 5000);

    if (integratedMode_) {
        return createArtifactsTable();
    }
    return createTables();
}

bool WindowsAnalysisDatabase::createTables() {
    return executeSQL(WindowsAnalysisSQL::CREATE_ALL_TABLES);
}

bool WindowsAnalysisDatabase::createArtifactsTable() {
    std::string sql = FileClassifierSQL::CREATE_ARTIFACT_TABLE_TEMPLATE;
    std::string tableName = "windows_artifacts";
    size_t pos = 0;
    while ((pos = sql.find("%TABLE_NAME%", pos)) != std::string::npos) {
        sql.replace(pos, 12, tableName);
        pos += tableName.length();
    }
    return executeSQL(sql);
}

bool WindowsAnalysisDatabase::executeSQL(const std::string& sql) {
    char* errMsg = nullptr;
    int rc = sqlite3_exec(db_, sql.c_str(), nullptr, nullptr, &errMsg);
    if (rc != SQLITE_OK) {
        std::cerr << "SQL error: " << errMsg << std::endl;
        sqlite3_free(errMsg);
        return false;
    }
    return true;
}

bool WindowsAnalysisDatabase::beginTransaction() {
    return executeSQL("BEGIN TRANSACTION;");
}

bool WindowsAnalysisDatabase::commitTransaction() {
    return executeSQL("COMMIT;");
}

bool WindowsAnalysisDatabase::rollbackTransaction() {
    return executeSQL("ROLLBACK;");
}
