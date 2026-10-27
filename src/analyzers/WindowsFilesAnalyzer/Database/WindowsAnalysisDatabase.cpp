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
    if (db_) return integratedMode_ ? createArtifactsTable() : createTables();
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
    if (!executeSQL(WindowsAnalysisSQL::CREATE_ALL_TABLES)) return false;
    if (!executeSQL("CREATE TABLE IF NOT EXISTS parser_outcomes (id INTEGER PRIMARY KEY, source_path TEXT NOT NULL, parser TEXT NOT NULL, status TEXT NOT NULL, diagnostic TEXT, record_count INTEGER, recovered_count INTEGER);")) return false;
    // Additive upgrade only: old parser values remain labelled legacy_unverified.
    const std::vector<std::pair<std::string, std::string>> columns = {
        {"prefetch_files", "parse_status TEXT NOT NULL DEFAULT 'legacy_unverified'"},
        {"prefetch_files", "parse_error TEXT"}, {"prefetch_files", "parser_version TEXT"},
        {"prefetch_files", "all_run_times TEXT"}, {"prefetch_files", "raw_run_times TEXT"},
        {"event_logs", "parse_status TEXT NOT NULL DEFAULT 'legacy_unverified'"},
        {"event_logs", "parse_error TEXT"}, {"event_logs", "parser_version TEXT"},
        {"event_logs", "raw_timestamp TEXT"}, {"event_logs", "source_path TEXT"},
        {"event_logs", "is_recovered INTEGER"}
    };
    if (!executeSQL("SAVEPOINT parser_schema;")) return false;
    for (const auto& column : columns) {
        const auto name=column.second.substr(0,column.second.find(' '));
        sqlite3_stmt* stmt=nullptr;
        bool present=false;
        const auto query="PRAGMA table_info("+column.first+");";
        if (sqlite3_prepare_v2(db_,query.c_str(),-1,&stmt,nullptr)==SQLITE_OK) {
            while (sqlite3_step(stmt)==SQLITE_ROW) {
                const auto value=sqlite3_column_text(stmt,1);
                if (value && name==reinterpret_cast<const char*>(value)) present=true;
            }
        } else { executeSQL("ROLLBACK TO parser_schema; RELEASE parser_schema;"); return false; }
        sqlite3_finalize(stmt);
        if (!present && !executeSQL("ALTER TABLE "+column.first+" ADD COLUMN "+column.second+";")) {
            executeSQL("ROLLBACK TO parser_schema; RELEASE parser_schema;"); return false;
        }
    }
    return executeSQL("RELEASE parser_schema;");
}

bool WindowsAnalysisDatabase::recordParserOutcome(const std::string& path, const std::string& parser,
    const std::string& status, const std::string& diagnostic,
    std::optional<int64_t> count, int64_t recovered) {
    sqlite3_stmt* stmt=nullptr;
    if (sqlite3_prepare_v2(db_,"INSERT INTO parser_outcomes(source_path,parser,status,diagnostic,record_count,recovered_count) VALUES(?,?,?,?,?,?)",-1,&stmt,nullptr)!=SQLITE_OK) return false;
    sqlite3_bind_text(stmt,1,path.c_str(),-1,SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt,2,parser.c_str(),-1,SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt,3,status.c_str(),-1,SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt,4,diagnostic.c_str(),-1,SQLITE_TRANSIENT);
    if(count) sqlite3_bind_int64(stmt,5,*count); else sqlite3_bind_null(stmt,5);
    sqlite3_bind_int64(stmt,6,recovered);
    const bool ok=sqlite3_step(stmt)==SQLITE_DONE;
    sqlite3_finalize(stmt);
    return ok;
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
