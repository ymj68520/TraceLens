/**
 * @file DBAnalysisDatabase.cpp
 * @brief 数据库分析结果存储模块实现
 *
 * Construction, schema, sessions, write ops, transactions, JSON helpers.
 * Read-only queries live in DBAnalysisDatabase_Queries.cpp.
 */

#include "DBAnalysisDatabase.h"

#include <sstream>
#include <chrono>

namespace ForensicAnalyzer {
namespace Database {

DBAnalysisDatabase::DBAnalysisDatabase(const std::string& dbPath)
    : dbPath_(dbPath) {}

DBAnalysisDatabase::~DBAnalysisDatabase() {
    if (db_) {
        sqlite3_close(db_);
        db_ = nullptr;
    }
}

bool DBAnalysisDatabase::initialize() {
    if (db_) {
        sqlite3_close(db_);
        db_ = nullptr;
    }
    
    int rc = sqlite3_open(dbPath_.c_str(), &db_);
    if (rc != SQLITE_OK) {
        setError("Failed to open database: " + std::string(sqlite3_errmsg(db_)));
        return false;
    }
    
    // 启用外键约束
    sqlite3_exec(db_, "PRAGMA foreign_keys = ON", nullptr, nullptr, nullptr);
    
    return createTables();
}

bool DBAnalysisDatabase::createTables() {
    const char* sql = R"(
        -- 分析会话表
        CREATE TABLE IF NOT EXISTS db_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_path TEXT NOT NULL,
            database_type INTEGER NOT NULL,
            version TEXT,
            file_size INTEGER DEFAULT 0,
            table_count INTEGER DEFAULT 0,
            total_records INTEGER DEFAULT 0,
            deleted_records INTEGER DEFAULT 0,
            user_count INTEGER DEFAULT 0,
            artifact_count INTEGER DEFAULT 0,
            started_at INTEGER NOT NULL,
            completed_at INTEGER,
            last_error TEXT
        );
        
        -- 表信息
        CREATE TABLE IF NOT EXISTS db_tables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            schema_name TEXT,
            row_count INTEGER DEFAULT 0,
            size_bytes INTEGER DEFAULT 0,
            create_statement TEXT,
            engine TEXT,
            collation TEXT,
            columns_json TEXT,
            indexes_json TEXT,
            FOREIGN KEY (session_id) REFERENCES db_sessions(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_db_tables_session ON db_tables(session_id);
        
        -- 记录
        CREATE TABLE IF NOT EXISTS db_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            table_name TEXT NOT NULL,
            row_id INTEGER,
            values_json TEXT NOT NULL,
            is_deleted INTEGER DEFAULT 0,
            page_number INTEGER,
            cell_offset INTEGER,
            FOREIGN KEY (session_id) REFERENCES db_sessions(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_db_records_session ON db_records(session_id);
        CREATE INDEX IF NOT EXISTS idx_db_records_table ON db_records(session_id, table_name);
        
        -- 工件
        CREATE TABLE IF NOT EXISTS db_artifacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            type INTEGER NOT NULL,
            source TEXT,
            description TEXT,
            data_json TEXT,
            page_number INTEGER,
            offset INTEGER,
            timestamp INTEGER,
            raw_data TEXT,
            FOREIGN KEY (session_id) REFERENCES db_sessions(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_db_artifacts_session ON db_artifacts(session_id);
        CREATE INDEX IF NOT EXISTS idx_db_artifacts_type ON db_artifacts(session_id, type);
        
        -- 用户
        CREATE TABLE IF NOT EXISTS db_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            host TEXT,
            auth_method TEXT,
            password_hash TEXT,
            privileges_json TEXT,
            is_locked INTEGER DEFAULT 0,
            created_at INTEGER,
            last_login INTEGER,
            FOREIGN KEY (session_id) REFERENCES db_sessions(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_db_users_session ON db_users(session_id);
    )";
    
    char* errMsg = nullptr;
    int rc = sqlite3_exec(db_, sql, nullptr, nullptr, &errMsg);
    
    if (rc != SQLITE_OK) {
        std::string error = errMsg ? errMsg : "Unknown error";
        sqlite3_free(errMsg);
        setError("Failed to create tables: " + error);
        return false;
    }
    
    return true;
}

int64_t DBAnalysisDatabase::beginSession(const std::string& sourcePath, DatabaseType type) {
    if (!db_) return -1;
    
    const char* sql = 
        "INSERT INTO db_sessions (source_path, database_type, started_at) VALUES (?, ?, ?)";
    
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError("Failed to prepare statement: " + std::string(sqlite3_errmsg(db_)));
        return -1;
    }
    
    int64_t now = std::chrono::duration_cast<std::chrono::seconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
    
    sqlite3_bind_text(stmt, 1, sourcePath.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_int(stmt, 2, static_cast<int>(type));
    sqlite3_bind_int64(stmt, 3, now);
    
    int rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    
    if (rc != SQLITE_DONE) {
        setError("Failed to insert session: " + std::string(sqlite3_errmsg(db_)));
        return -1;
    }
    
    return sqlite3_last_insert_rowid(db_);
}

bool DBAnalysisDatabase::endSession(int64_t sessionId, const DBAnalysisSummary& summary) {
    if (!db_) return false;
    
    const char* sql = 
        "UPDATE db_sessions SET "
        "version = ?, file_size = ?, table_count = ?, total_records = ?, "
        "deleted_records = ?, user_count = ?, artifact_count = ?, "
        "completed_at = ?, last_error = ? "
        "WHERE id = ?";
    
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError("Failed to prepare statement: " + std::string(sqlite3_errmsg(db_)));
        return false;
    }
    
    int64_t now = std::chrono::duration_cast<std::chrono::seconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
    
    sqlite3_bind_text(stmt, 1, summary.version.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_int64(stmt, 2, summary.fileSizeBytes);
    sqlite3_bind_int64(stmt, 3, summary.tableCount);
    sqlite3_bind_int64(stmt, 4, summary.totalRecords);
    sqlite3_bind_int64(stmt, 5, summary.deletedRecords);
    sqlite3_bind_int64(stmt, 6, summary.userCount);
    sqlite3_bind_int64(stmt, 7, summary.artifactCount);
    sqlite3_bind_int64(stmt, 8, now);
    sqlite3_bind_text(stmt, 9, summary.lastError.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_int64(stmt, 10, sessionId);
    
    int rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    
    return rc == SQLITE_DONE;
}

bool DBAnalysisDatabase::insertTable(int64_t sessionId, const DBTableInfo& table) {
    if (!db_) return false;
    
    const char* sql = 
        "INSERT INTO db_tables "
        "(session_id, name, schema_name, row_count, size_bytes, create_statement, "
        "engine, collation, columns_json, indexes_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)";
    
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        return false;
    }
    
    // 序列化列信息
    std::string columnsJson = "[";
    for (size_t i = 0; i < table.columns.size(); i++) {
        const auto& col = table.columns[i];
        if (i > 0) columnsJson += ",";
        columnsJson += "{\"name\":\"" + col.name + "\","
                      "\"type\":\"" + col.dataType + "\","
                      "\"nullable\":" + (col.nullable ? "true" : "false") + ","
                      "\"isPrimaryKey\":" + (col.isPrimaryKey ? "true" : "false") + "}";
    }
    columnsJson += "]";
    
    // 序列化索引信息
    std::string indexesJson = "[";
    for (size_t i = 0; i < table.indexes.size(); i++) {
        const auto& idx = table.indexes[i];
        if (i > 0) indexesJson += ",";
        indexesJson += "{\"name\":\"" + idx.name + "\","
                      "\"unique\":" + (idx.isUnique ? "true" : "false") + "}";
    }
    indexesJson += "]";
    
    sqlite3_bind_int64(stmt, 1, sessionId);
    sqlite3_bind_text(stmt, 2, table.name.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 3, table.schema.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_int64(stmt, 4, table.rowCount);
    sqlite3_bind_int64(stmt, 5, table.sizeBytes);
    sqlite3_bind_text(stmt, 6, table.createStatement.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 7, table.engine.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 8, table.collation.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 9, columnsJson.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 10, indexesJson.c_str(), -1, SQLITE_TRANSIENT);
    
    int rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    
    return rc == SQLITE_DONE;
}

int DBAnalysisDatabase::insertTables(int64_t sessionId, const std::vector<DBTableInfo>& tables) {
    beginTransaction();
    int count = 0;
    
    for (const auto& table : tables) {
        if (insertTable(sessionId, table)) {
            count++;
        }
    }
    
    commit();
    return count;
}

bool DBAnalysisDatabase::insertRecord(int64_t sessionId, const DBRecordInfo& record) {
    if (!db_) return false;
    
    const char* sql = 
        "INSERT INTO db_records "
        "(session_id, table_name, row_id, values_json, is_deleted, page_number, cell_offset) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)";
    
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        return false;
    }
    
    std::string valuesJson = mapToJson(record.values);
    
    sqlite3_bind_int64(stmt, 1, sessionId);
    sqlite3_bind_text(stmt, 2, record.tableName.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_int64(stmt, 3, record.rowId);
    sqlite3_bind_text(stmt, 4, valuesJson.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 5, record.isDeleted ? 1 : 0);
    sqlite3_bind_int64(stmt, 6, record.pageNumber);
    sqlite3_bind_int64(stmt, 7, record.cellOffset);
    
    int rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    
    return rc == SQLITE_DONE;
}

int DBAnalysisDatabase::insertRecords(int64_t sessionId, const std::vector<DBRecordInfo>& records) {
    beginTransaction();
    int count = 0;
    
    for (const auto& record : records) {
        if (insertRecord(sessionId, record)) {
            count++;
        }
    }
    
    commit();
    return count;
}

bool DBAnalysisDatabase::insertArtifact(int64_t sessionId, const DBArtifact& artifact) {
    if (!db_) return false;
    
    const char* sql = 
        "INSERT INTO db_artifacts "
        "(session_id, type, source, description, data_json, page_number, offset, timestamp, raw_data) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)";
    
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        return false;
    }
    
    std::string dataJson = mapToJson(artifact.data);
    
    sqlite3_bind_int64(stmt, 1, sessionId);
    sqlite3_bind_int(stmt, 2, static_cast<int>(artifact.type));
    sqlite3_bind_text(stmt, 3, artifact.source.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 4, artifact.description.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 5, dataJson.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 6, artifact.pageNumber);
    sqlite3_bind_int64(stmt, 7, artifact.offset);
    sqlite3_bind_int64(stmt, 8, artifact.timestamp);
    sqlite3_bind_text(stmt, 9, artifact.rawData.c_str(), -1, SQLITE_STATIC);
    
    int rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    
    return rc == SQLITE_DONE;
}

int DBAnalysisDatabase::insertArtifacts(int64_t sessionId, const std::vector<DBArtifact>& artifacts) {
    beginTransaction();
    int count = 0;
    
    for (const auto& artifact : artifacts) {
        if (insertArtifact(sessionId, artifact)) {
            count++;
        }
    }
    
    commit();
    return count;
}

bool DBAnalysisDatabase::insertUser(int64_t sessionId, const DBUserInfo& user) {
    if (!db_) return false;
    
    const char* sql = 
        "INSERT INTO db_users "
        "(session_id, username, host, auth_method, password_hash, privileges_json, "
        "is_locked, created_at, last_login) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)";
    
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        return false;
    }
    
    std::string privilegesJson = vectorToJson(user.privileges);
    
    sqlite3_bind_int64(stmt, 1, sessionId);
    sqlite3_bind_text(stmt, 2, user.username.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 3, user.host.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 4, user.authMethod.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 5, user.passwordHash.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 6, privilegesJson.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 7, user.isLocked ? 1 : 0);
    sqlite3_bind_int64(stmt, 8, user.createdAt);
    sqlite3_bind_int64(stmt, 9, user.lastLogin);
    
    int rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    
    return rc == SQLITE_DONE;
}

bool DBAnalysisDatabase::beginTransaction() {
    if (!db_) return false;
    return sqlite3_exec(db_, "BEGIN TRANSACTION", nullptr, nullptr, nullptr) == SQLITE_OK;
}

bool DBAnalysisDatabase::commit() {
    if (!db_) return false;
    return sqlite3_exec(db_, "COMMIT", nullptr, nullptr, nullptr) == SQLITE_OK;
}

bool DBAnalysisDatabase::rollback() {
    if (!db_) return false;
    return sqlite3_exec(db_, "ROLLBACK", nullptr, nullptr, nullptr) == SQLITE_OK;
}

void DBAnalysisDatabase::setError(const std::string& error) {
    lastError_ = error;
}

std::string DBAnalysisDatabase::mapToJson(const std::map<std::string, std::string>& m) {
    std::ostringstream oss;
    oss << "{";
    bool first = true;
    for (const auto& [key, value] : m) {
        if (!first) oss << ",";
        first = false;
        // 简单转义
        std::string escapedValue = value;
        size_t pos = 0;
        while ((pos = escapedValue.find('"', pos)) != std::string::npos) {
            escapedValue.replace(pos, 1, "\\\"");
            pos += 2;
        }
        oss << "\"" << key << "\":\"" << escapedValue << "\"";
    }
    oss << "}";
    return oss.str();
}

std::map<std::string, std::string> DBAnalysisDatabase::jsonToMap(const std::string& json) {
    std::map<std::string, std::string> m;
    // 简单解析（不处理嵌套）
    // 格式: {"key1":"value1","key2":"value2"}
    
    if (json.size() < 2 || json[0] != '{') return m;
    
    size_t pos = 1;
    while (pos < json.size() - 1) {
        // 查找key
        size_t keyStart = json.find('"', pos);
        if (keyStart == std::string::npos) break;
        size_t keyEnd = json.find('"', keyStart + 1);
        if (keyEnd == std::string::npos) break;
        
        std::string key = json.substr(keyStart + 1, keyEnd - keyStart - 1);
        
        // 查找:
        size_t colonPos = json.find(':', keyEnd);
        if (colonPos == std::string::npos) break;
        
        // 查找value
        size_t valStart = json.find('"', colonPos);
        if (valStart == std::string::npos) break;
        
        // 处理转义
        size_t valEnd = valStart + 1;
        while (valEnd < json.size()) {
            if (json[valEnd] == '"' && json[valEnd - 1] != '\\') break;
            valEnd++;
        }
        
        std::string value = json.substr(valStart + 1, valEnd - valStart - 1);
        
        m[key] = value;
        
        pos = json.find(',', valEnd);
        if (pos == std::string::npos) break;
        pos++;
    }
    
    return m;
}

std::string DBAnalysisDatabase::vectorToJson(const std::vector<std::string>& v) {
    std::ostringstream oss;
    oss << "[";
    for (size_t i = 0; i < v.size(); i++) {
        if (i > 0) oss << ",";
        oss << "\"" << v[i] << "\"";
    }
    oss << "]";
    return oss.str();
}

std::vector<std::string> DBAnalysisDatabase::jsonToVector(const std::string& json) {
    std::vector<std::string> v;
    // 简单解析 ["a","b","c"]
    
    size_t pos = 0;
    while ((pos = json.find('"', pos)) != std::string::npos) {
        size_t endPos = json.find('"', pos + 1);
        if (endPos == std::string::npos) break;
        v.push_back(json.substr(pos + 1, endPos - pos - 1));
        pos = endPos + 1;
    }
    
    return v;
}


} // namespace Database
} // namespace ForensicAnalyzer
