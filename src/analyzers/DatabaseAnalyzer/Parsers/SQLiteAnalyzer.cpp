/**
 * @file SQLiteAnalyzer.cpp
 * @brief SQLite数据库取证分析器实现
 */

#include "SQLiteAnalyzer.h"

#include <filesystem>
#include <fstream>
#include <sstream>
#include <algorithm>
#include <cstring>
#include <regex>

namespace fs = std::filesystem;

namespace ForensicAnalyzer {
namespace Database {
// SQLiteAnalyzer.cpp
// Lifecycle, metadata, and query methods. Forensic analysis lives in SQLiteAnalyzer_Forensics.cpp.

SQLiteAnalyzer::SQLiteAnalyzer() = default;

SQLiteAnalyzer::~SQLiteAnalyzer() {
    close();
}

bool SQLiteAnalyzer::open(const std::string& path) {
    close();
    
    // 检查文件是否存在
    if (!fs::exists(path)) {
        setError("File does not exist: " + path);
        return false;
    }
    
    // 以只读模式打开
    int flags = SQLITE_OPEN_READONLY | SQLITE_OPEN_FULLMUTEX;
    int rc = sqlite3_open_v2(path.c_str(), &db_, flags, nullptr);
    
    if (rc != SQLITE_OK) {
        std::string err = db_ ? sqlite3_errmsg(db_) : "Unknown error";
        setError("Failed to open database: " + err);
        if (db_) {
            sqlite3_close(db_);
            db_ = nullptr;
        }
        return false;
    }
    
    dbPath_ = path;
    clearError();
    return true;
}

void SQLiteAnalyzer::close() {
    if (db_) {
        sqlite3_close(db_);
        db_ = nullptr;
    }
    dbPath_.clear();
}

bool SQLiteAnalyzer::isOpen() const {
    return db_ != nullptr;
}

std::string SQLiteAnalyzer::getVersion() const {
    if (!db_) return "";
    
    sqlite3_stmt* stmt = nullptr;
    std::string version;
    
    if (sqlite3_prepare_v2(db_, "SELECT sqlite_version()", -1, &stmt, nullptr) == SQLITE_OK) {
        if (sqlite3_step(stmt) == SQLITE_ROW) {
            const char* ver = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
            if (ver) version = ver;
        }
    }
    sqlite3_finalize(stmt);
    
    return version;
}

int64_t SQLiteAnalyzer::getFileSize() const {
    if (dbPath_.empty()) return 0;
    
    try {
        return static_cast<int64_t>(fs::file_size(dbPath_));
    } catch (...) {
        return 0;
    }
}

int SQLiteAnalyzer::getPageSize() const {
    if (!db_) return 0;
    
    sqlite3_stmt* stmt = nullptr;
    int pageSize = 0;
    
    if (sqlite3_prepare_v2(db_, "PRAGMA page_size", -1, &stmt, nullptr) == SQLITE_OK) {
        if (sqlite3_step(stmt) == SQLITE_ROW) {
            pageSize = sqlite3_column_int(stmt, 0);
        }
    }
    sqlite3_finalize(stmt);
    
    return pageSize;
}

int64_t SQLiteAnalyzer::getTotalPages() const {
    if (!db_) return 0;
    
    sqlite3_stmt* stmt = nullptr;
    int64_t pages = 0;
    
    if (sqlite3_prepare_v2(db_, "PRAGMA page_count", -1, &stmt, nullptr) == SQLITE_OK) {
        if (sqlite3_step(stmt) == SQLITE_ROW) {
            pages = sqlite3_column_int64(stmt, 0);
        }
    }
    sqlite3_finalize(stmt);
    
    return pages;
}

int64_t SQLiteAnalyzer::getFreelistPages() const {
    if (!db_) return 0;
    
    sqlite3_stmt* stmt = nullptr;
    int64_t pages = 0;
    
    if (sqlite3_prepare_v2(db_, "PRAGMA freelist_count", -1, &stmt, nullptr) == SQLITE_OK) {
        if (sqlite3_step(stmt) == SQLITE_ROW) {
            pages = sqlite3_column_int64(stmt, 0);
        }
    }
    sqlite3_finalize(stmt);
    
    return pages;
}

std::string SQLiteAnalyzer::getEncoding() const {
    if (!db_) return "";
    
    sqlite3_stmt* stmt = nullptr;
    std::string encoding;
    
    if (sqlite3_prepare_v2(db_, "PRAGMA encoding", -1, &stmt, nullptr) == SQLITE_OK) {
        if (sqlite3_step(stmt) == SQLITE_ROW) {
            const char* enc = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
            if (enc) encoding = enc;
        }
    }
    sqlite3_finalize(stmt);
    
    return encoding;
}

std::vector<DBTableInfo> SQLiteAnalyzer::getTables() {
    std::vector<DBTableInfo> tables;
    if (!db_) return tables;
    
    reportProgress("Extracting table list", 0, -1);
    
    // 查询所有表（不包括sqlite_开头的系统表）
    const char* sql = 
        "SELECT name, sql FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name";
    
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError("Failed to query tables: " + std::string(sqlite3_errmsg(db_)));
        return tables;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        DBTableInfo table;
        
        const char* name = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
        const char* createSql = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
        
        if (name) table.name = name;
        if (createSql) table.createStatement = createSql;
        
        table.columns = getTableColumns(table.name);
        table.indexes = getTableIndexes(table.name);
        table.rowCount = estimateRowCount(table.name);
        
        tables.push_back(std::move(table));
    }
    
    sqlite3_finalize(stmt);
    
    reportProgress("Extracting table list", tables.size(), tables.size());
    return tables;
}

DBTableInfo SQLiteAnalyzer::getTableInfo(const std::string& tableName) {
    DBTableInfo table;
    if (!db_) return table;
    
    table.name = tableName;
    
    // 获取CREATE语句
    std::string sql = "SELECT sql FROM sqlite_master WHERE type='table' AND name=?";
    sqlite3_stmt* stmt = nullptr;
    
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) == SQLITE_OK) {
        sqlite3_bind_text(stmt, 1, tableName.c_str(), -1, SQLITE_STATIC);
        if (sqlite3_step(stmt) == SQLITE_ROW) {
            const char* createSql = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
            if (createSql) table.createStatement = createSql;
        }
    }
    sqlite3_finalize(stmt);
    
    table.columns = getTableColumns(tableName);
    table.indexes = getTableIndexes(tableName);
    table.rowCount = estimateRowCount(tableName);
    
    return table;
}

std::vector<DBColumnInfo> SQLiteAnalyzer::getTableColumns(const std::string& tableName) {
    std::vector<DBColumnInfo> columns;
    if (!db_) return columns;
    
    std::string sql = "PRAGMA table_info(" + tableName + ")";
    sqlite3_stmt* stmt = nullptr;
    
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        return columns;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        DBColumnInfo col;
        
        col.ordinalPosition = sqlite3_column_int(stmt, 0);
        
        const char* name = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
        const char* type = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
        const char* defVal = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4));
        
        if (name) col.name = name;
        if (type) {
            col.dataType = type;
            col.type = parseColumnType(type);
        }
        if (defVal) col.defaultValue = defVal;
        
        col.nullable = (sqlite3_column_int(stmt, 3) == 0);
        col.isPrimaryKey = (sqlite3_column_int(stmt, 5) != 0);
        
        columns.push_back(std::move(col));
    }
    
    sqlite3_finalize(stmt);
    return columns;
}

std::vector<DBIndexInfo> SQLiteAnalyzer::getTableIndexes(const std::string& tableName) {
    std::vector<DBIndexInfo> indexes;
    if (!db_) return indexes;
    
    std::string sql = "PRAGMA index_list(" + tableName + ")";
    sqlite3_stmt* stmt = nullptr;
    
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        return indexes;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        DBIndexInfo idx;
        
        const char* name = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
        if (name) idx.name = name;
        
        idx.tableName = tableName;
        idx.isUnique = (sqlite3_column_int(stmt, 2) != 0);
        
        const char* origin = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3));
        if (origin && std::string(origin) == "pk") {
            idx.isPrimaryKey = true;
        }
        
        // 获取索引列
        std::string colSql = "PRAGMA index_info(" + idx.name + ")";
        sqlite3_stmt* colStmt = nullptr;
        if (sqlite3_prepare_v2(db_, colSql.c_str(), -1, &colStmt, nullptr) == SQLITE_OK) {
            while (sqlite3_step(colStmt) == SQLITE_ROW) {
                const char* colName = reinterpret_cast<const char*>(sqlite3_column_text(colStmt, 2));
                if (colName) idx.columns.push_back(colName);
            }
        }
        sqlite3_finalize(colStmt);
        
        indexes.push_back(std::move(idx));
    }
    
    sqlite3_finalize(stmt);
    return indexes;
}

int64_t SQLiteAnalyzer::estimateRowCount(const std::string& tableName) {
    if (!db_) return 0;
    
    // 直接COUNT（对于小表）
    std::string sql = "SELECT COUNT(*) FROM \"" + tableName + "\"";
    sqlite3_stmt* stmt = nullptr;
    int64_t count = 0;
    
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) == SQLITE_OK) {
        if (sqlite3_step(stmt) == SQLITE_ROW) {
            count = sqlite3_column_int64(stmt, 0);
        }
    }
    sqlite3_finalize(stmt);
    
    return count;
}

ColumnDataType SQLiteAnalyzer::parseColumnType(const std::string& typeStr) const {
    std::string upper = typeStr;
    std::transform(upper.begin(), upper.end(), upper.begin(), ::toupper);
    
    if (upper.find("INT") != std::string::npos) {
        return ColumnDataType::INTEGER;
    }
    if (upper.find("REAL") != std::string::npos || 
        upper.find("FLOAT") != std::string::npos ||
        upper.find("DOUBLE") != std::string::npos) {
        return ColumnDataType::REAL;
    }
    if (upper.find("CHAR") != std::string::npos || 
        upper.find("TEXT") != std::string::npos ||
        upper.find("CLOB") != std::string::npos) {
        return ColumnDataType::TEXT;
    }
    if (upper.find("BLOB") != std::string::npos) {
        return ColumnDataType::BLOB;
    }
    if (upper.find("BOOL") != std::string::npos) {
        return ColumnDataType::BOOLEAN;
    }
    if (upper.find("DATE") != std::string::npos || 
        upper.find("TIME") != std::string::npos) {
        return ColumnDataType::DATETIME;
    }
    if (upper.find("JSON") != std::string::npos) {
        return ColumnDataType::JSON;
    }
    
    return ColumnDataType::UNKNOWN;
}

bool SQLiteAnalyzer::hasTable(const std::string& tableName) const {
    if (!db_) return false;
    
    std::string sql = "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1";
    sqlite3_stmt* stmt = nullptr;
    bool exists = false;
    
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) == SQLITE_OK) {
        sqlite3_bind_text(stmt, 1, tableName.c_str(), -1, SQLITE_STATIC);
        exists = (sqlite3_step(stmt) == SQLITE_ROW);
    }
    sqlite3_finalize(stmt);
    
    return exists;
}

bool SQLiteAnalyzer::hasColumn(const std::string& tableName, const std::string& columnName) const {
    if (!db_) return false;
    
    std::string sql = "PRAGMA table_info(" + tableName + ")";
    sqlite3_stmt* stmt = nullptr;
    bool exists = false;
    
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) == SQLITE_OK) {
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            const char* name = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
            if (name && std::string(name) == columnName) {
                exists = true;
                break;
            }
        }
    }
    sqlite3_finalize(stmt);
    
    return exists;
}

DBAnalysisSummary SQLiteAnalyzer::getAnalysisSummary() {
    DBAnalysisSummary summary;
    
    summary.databasePath = dbPath_;
    summary.type = DatabaseType::SQLITE;
    summary.version = getVersion();
    summary.fileSizeBytes = getFileSize();
    summary.analyzedAt = std::chrono::duration_cast<std::chrono::seconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
    
    auto tables = getTables();
    summary.tableCount = tables.size();
    
    for (const auto& table : tables) {
        summary.totalRecords += table.rowCount;
        summary.tableRecordCounts[table.name] = table.rowCount;
    }
    
    // 估算删除记录数（基于freelist）
    int64_t freelistPages = getFreelistPages();
    int pageSize = getPageSize();
    if (freelistPages > 0 && pageSize > 0) {
        // 粗略估算：每页可能有10-50条记录
        summary.deletedRecords = freelistPages * 10;  // 保守估计
    }
    
    return summary;
}

} // namespace Database
} // namespace ForensicAnalyzer
