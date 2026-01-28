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

std::vector<DBRecordInfo> SQLiteAnalyzer::getRecords(
    const std::string& tableName, 
    int limit,
    int offset) {
    
    std::vector<DBRecordInfo> records;
    if (!db_) return records;
    
    // 构建查询
    std::string sql = "SELECT rowid, * FROM \"" + tableName + "\"";
    if (limit > 0) {
        sql += " LIMIT " + std::to_string(limit);
        if (offset > 0) {
            sql += " OFFSET " + std::to_string(offset);
        }
    }
    
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        // 表可能没有rowid，尝试不带rowid
        sql = "SELECT * FROM \"" + tableName + "\"";
        if (limit > 0) {
            sql += " LIMIT " + std::to_string(limit);
            if (offset > 0) {
                sql += " OFFSET " + std::to_string(offset);
            }
        }
        if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
            setError("Failed to query table: " + std::string(sqlite3_errmsg(db_)));
            return records;
        }
    }
    
    int colCount = sqlite3_column_count(stmt);
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        DBRecordInfo record;
        record.tableName = tableName;
        
        for (int i = 0; i < colCount; i++) {
            const char* colName = sqlite3_column_name(stmt, i);
            std::string name = colName ? colName : ("col" + std::to_string(i));
            
            int type = sqlite3_column_type(stmt, i);
            std::string value;
            
            switch (type) {
                case SQLITE_INTEGER:
                    value = std::to_string(sqlite3_column_int64(stmt, i));
                    if (name == "rowid") {
                        record.rowId = sqlite3_column_int64(stmt, i);
                    }
                    break;
                case SQLITE_FLOAT:
                    value = std::to_string(sqlite3_column_double(stmt, i));
                    break;
                case SQLITE_TEXT: {
                    const char* text = reinterpret_cast<const char*>(sqlite3_column_text(stmt, i));
                    value = text ? text : "";
                    break;
                }
                case SQLITE_BLOB: {
                    int bytes = sqlite3_column_bytes(stmt, i);
                    value = "[BLOB " + std::to_string(bytes) + " bytes]";
                    break;
                }
                case SQLITE_NULL:
                default:
                    value = "[NULL]";
                    break;
            }
            
            record.values[name] = value;
        }
        
        records.push_back(std::move(record));
    }
    
    sqlite3_finalize(stmt);
    return records;
}

std::vector<DBRecordInfo> SQLiteAnalyzer::executeQuery(const std::string& query) {
    std::vector<DBRecordInfo> records;
    if (!db_) return records;
    
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db_, query.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError("Query failed: " + std::string(sqlite3_errmsg(db_)));
        return records;
    }
    
    int colCount = sqlite3_column_count(stmt);
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        DBRecordInfo record;
        record.tableName = "query_result";
        
        for (int i = 0; i < colCount; i++) {
            const char* colName = sqlite3_column_name(stmt, i);
            std::string name = colName ? colName : ("col" + std::to_string(i));
            
            const char* text = reinterpret_cast<const char*>(sqlite3_column_text(stmt, i));
            record.values[name] = text ? text : "[NULL]";
        }
        
        records.push_back(std::move(record));
    }
    
    sqlite3_finalize(stmt);
    return records;
}

std::vector<DBArtifact> SQLiteAnalyzer::extractArtifacts(const DBAnalysisOptions& options) {
    std::vector<DBArtifact> artifacts;
    if (!db_) return artifacts;
    
    reportProgress("Extracting artifacts", 0, -1);
    
    // 提取freelist信息
    int64_t freelistPages = getFreelistPages();
    if (freelistPages > 0) {
        DBArtifact artifact;
        artifact.type = ArtifactType::FREELIST_PAGE;
        artifact.source = dbPath_;
        artifact.description = "SQLite freelist contains " + std::to_string(freelistPages) + " pages";
        artifact.data["freelist_pages"] = std::to_string(freelistPages);
        artifact.data["potential_deleted_data"] = "true";
        artifacts.push_back(std::move(artifact));
    }
    
    // 检测WAL文件
    if (options.parseWAL) {
        std::string walPath = dbPath_ + "-wal";
        if (fs::exists(walPath)) {
            auto walArtifacts = analyzeWAL(walPath);
            artifacts.insert(artifacts.end(), walArtifacts.begin(), walArtifacts.end());
        }
    }
    
    // 尝试恢复删除的记录
    if (options.extractDeletedRecords) {
        auto deletedRecords = recoverDeletedRecords(options.maxDeletedRecords);
        for (const auto& record : deletedRecords) {
            DBArtifact artifact;
            artifact.type = ArtifactType::DELETED_RECORD;
            artifact.source = record.tableName;
            artifact.description = "Recovered deleted record from " + record.tableName;
            artifact.data = record.values;
            artifact.pageNumber = record.pageNumber;
            artifact.offset = record.cellOffset;
            artifacts.push_back(std::move(artifact));
        }
    }
    
    reportProgress("Extracting artifacts", artifacts.size(), artifacts.size());
    return artifacts;
}

std::vector<DBRecordInfo> SQLiteAnalyzer::recoverDeletedRecords(int maxRecords) {
    // 基础实现：分析freelist页
    // 注意：完整的删除记录恢复需要对SQLite文件格式进行深入解析
    // 这里提供一个基本框架，具体实现需要对SQLite B-Tree结构进行解析
    
    std::vector<DBRecordInfo> recovered;
    if (!db_ || maxRecords == 0) return recovered;
    
    (void)maxRecords;  // 未来实现使用
    
    // TODO: 实现完整的freelist解析和记录恢复
    // 这需要直接读取数据库文件并解析SQLite页面结构
    
    return recovered;
}

std::vector<DBArtifact> SQLiteAnalyzer::analyzeWAL(const std::string& walPath) {
    std::vector<DBArtifact> artifacts;
    
    std::string path = walPath.empty() ? (dbPath_ + "-wal") : walPath;
    
    if (!fs::exists(path)) {
        return artifacts;
    }
    
    // WAL文件头: 32字节
    // 每个帧: 24字节帧头 + 页面数据
    
    std::ifstream wal(path, std::ios::binary);
    if (!wal.is_open()) {
        return artifacts;
    }
    
    // 读取WAL头
    char header[32];
    wal.read(header, 32);
    
    if (wal.gcount() == 32) {
        DBArtifact artifact;
        artifact.type = ArtifactType::WAL_ENTRY;
        artifact.source = path;
        artifact.description = "SQLite WAL file found";
        artifact.data["file_size"] = std::to_string(fs::file_size(path));
        
        // 解析WAL头
        uint32_t magic = 0;
        std::memcpy(&magic, header, 4);
        artifact.data["magic"] = std::to_string(magic);
        
        artifacts.push_back(std::move(artifact));
    }
    
    return artifacts;
}

std::string SQLiteAnalyzer::detectApplicationType() const {
    if (!db_) return "Unknown";
    
    // Chrome/Chromium History
    if (hasTable("urls") && hasTable("visits") && hasTable("segments")) {
        return "Chrome/Chromium History";
    }
    
    // Firefox Places
    if (hasTable("moz_places") && hasTable("moz_historyvisits")) {
        return "Firefox Places";
    }
    
    // Android SMS
    if (hasTable("sms") && hasColumn("sms", "address")) {
        return "Android SMS Database";
    }
    
    // Android Contacts
    if (hasTable("contacts") && hasTable("raw_contacts")) {
        return "Android Contacts Database";
    }
    
    // WhatsApp
    if (hasTable("messages") && hasTable("chat_list")) {
        return "WhatsApp Messages";
    }
    
    // Telegram
    if (hasTable("messages") && hasTable("dialogs") && hasTable("users")) {
        return "Telegram Messages";
    }
    
    // WeChat
    if (hasTable("message") && hasTable("rcontact")) {
        return "WeChat Messages";
    }
    
    // iOS Notes
    if (hasTable("ZICCLOUDSYNCINGOBJECT") || hasTable("ZICNOTEDATA")) {
        return "iOS Notes";
    }
    
    return "Generic SQLite Database";
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
