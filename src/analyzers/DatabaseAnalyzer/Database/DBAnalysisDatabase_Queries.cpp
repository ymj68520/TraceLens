/**
 * @file DBAnalysisDatabase_Queries.cpp
 * @brief 数据库分析结果存储 — 从 DBAnalysisDatabase.cpp 拆分
 */

#include "DBAnalysisDatabase.h"

#include <sstream>
#include <chrono>

namespace ForensicAnalyzer {
namespace Database {

std::vector<DBTableInfo> DBAnalysisDatabase::getTables(int64_t sessionId) {
    std::vector<DBTableInfo> tables;
    if (!db_) return tables;
    
    const char* sql = 
        "SELECT name, schema_name, row_count, size_bytes, create_statement, "
        "engine, collation FROM db_tables WHERE session_id = ?";
    
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        return tables;
    }
    
    sqlite3_bind_int64(stmt, 1, sessionId);
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        DBTableInfo table;
        
        const char* name = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
        const char* schema = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
        const char* createSql = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4));
        const char* engine = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5));
        const char* collation = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6));
        
        if (name) table.name = name;
        if (schema) table.schema = schema;
        table.rowCount = sqlite3_column_int64(stmt, 2);
        table.sizeBytes = sqlite3_column_int64(stmt, 3);
        if (createSql) table.createStatement = createSql;
        if (engine) table.engine = engine;
        if (collation) table.collation = collation;
        
        tables.push_back(std::move(table));
    }
    
    sqlite3_finalize(stmt);
    return tables;
}

std::vector<DBRecordInfo> DBAnalysisDatabase::getRecords(int64_t sessionId, 
                                                         const std::string& tableName,
                                                         int limit, int offset) {
    std::vector<DBRecordInfo> records;
    if (!db_) return records;
    
    std::string sql = 
        "SELECT table_name, row_id, values_json, is_deleted, page_number, cell_offset "
        "FROM db_records WHERE session_id = ? AND table_name = ?";
    
    if (limit > 0) {
        sql += " LIMIT " + std::to_string(limit);
        if (offset > 0) {
            sql += " OFFSET " + std::to_string(offset);
        }
    }
    
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        return records;
    }
    
    sqlite3_bind_int64(stmt, 1, sessionId);
    sqlite3_bind_text(stmt, 2, tableName.c_str(), -1, SQLITE_STATIC);
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        DBRecordInfo record;
        
        const char* table = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
        const char* valuesJson = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
        
        if (table) record.tableName = table;
        record.rowId = sqlite3_column_int64(stmt, 1);
        if (valuesJson) record.values = jsonToMap(valuesJson);
        record.isDeleted = sqlite3_column_int(stmt, 3) != 0;
        record.pageNumber = sqlite3_column_int64(stmt, 4);
        record.cellOffset = sqlite3_column_int64(stmt, 5);
        
        records.push_back(std::move(record));
    }
    
    sqlite3_finalize(stmt);
    return records;
}

std::vector<DBArtifact> DBAnalysisDatabase::getArtifacts(int64_t sessionId) {
    std::vector<DBArtifact> artifacts;
    if (!db_) return artifacts;
    
    const char* sql = 
        "SELECT type, source, description, data_json, page_number, offset, timestamp, raw_data "
        "FROM db_artifacts WHERE session_id = ?";
    
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        return artifacts;
    }
    
    sqlite3_bind_int64(stmt, 1, sessionId);
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        DBArtifact artifact;
        
        artifact.type = static_cast<ArtifactType>(sqlite3_column_int(stmt, 0));
        
        const char* source = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
        const char* desc = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
        const char* dataJson = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3));
        const char* rawData = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7));
        
        if (source) artifact.source = source;
        if (desc) artifact.description = desc;
        if (dataJson) artifact.data = jsonToMap(dataJson);
        artifact.pageNumber = sqlite3_column_int64(stmt, 4);
        artifact.offset = sqlite3_column_int64(stmt, 5);
        artifact.timestamp = sqlite3_column_int64(stmt, 6);
        if (rawData) artifact.rawData = rawData;
        
        artifacts.push_back(std::move(artifact));
    }
    
    sqlite3_finalize(stmt);
    return artifacts;
}

std::vector<DBArtifact> DBAnalysisDatabase::getArtifactsByType(int64_t sessionId, ArtifactType type) {
    std::vector<DBArtifact> artifacts;
    if (!db_) return artifacts;
    
    const char* sql = 
        "SELECT type, source, description, data_json, page_number, offset, timestamp, raw_data "
        "FROM db_artifacts WHERE session_id = ? AND type = ?";
    
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        return artifacts;
    }
    
    sqlite3_bind_int64(stmt, 1, sessionId);
    sqlite3_bind_int(stmt, 2, static_cast<int>(type));
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        DBArtifact artifact;
        
        artifact.type = static_cast<ArtifactType>(sqlite3_column_int(stmt, 0));
        
        const char* source = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
        const char* desc = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
        const char* dataJson = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3));
        
        if (source) artifact.source = source;
        if (desc) artifact.description = desc;
        if (dataJson) artifact.data = jsonToMap(dataJson);
        artifact.pageNumber = sqlite3_column_int64(stmt, 4);
        artifact.offset = sqlite3_column_int64(stmt, 5);
        artifact.timestamp = sqlite3_column_int64(stmt, 6);
        
        artifacts.push_back(std::move(artifact));
    }
    
    sqlite3_finalize(stmt);
    return artifacts;
}

std::vector<DBUserInfo> DBAnalysisDatabase::getUsers(int64_t sessionId) {
    std::vector<DBUserInfo> users;
    if (!db_) return users;
    
    const char* sql = 
        "SELECT username, host, auth_method, password_hash, privileges_json, "
        "is_locked, created_at, last_login "
        "FROM db_users WHERE session_id = ?";
    
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        return users;
    }
    
    sqlite3_bind_int64(stmt, 1, sessionId);
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        DBUserInfo user;
        
        const char* username = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
        const char* host = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
        const char* authMethod = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
        const char* passHash = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3));
        const char* privJson = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4));
        
        if (username) user.username = username;
        if (host) user.host = host;
        if (authMethod) user.authMethod = authMethod;
        if (passHash) user.passwordHash = passHash;
        if (privJson) user.privileges = jsonToVector(privJson);
        user.isLocked = sqlite3_column_int(stmt, 5) != 0;
        user.createdAt = sqlite3_column_int64(stmt, 6);
        user.lastLogin = sqlite3_column_int64(stmt, 7);
        
        users.push_back(std::move(user));
    }
    
    sqlite3_finalize(stmt);
    return users;
}

std::vector<DBAnalysisSummary> DBAnalysisDatabase::getAllSessions() {
    std::vector<DBAnalysisSummary> sessions;
    if (!db_) return sessions;
    
    const char* sql = 
        "SELECT id, source_path, database_type, version, file_size, table_count, "
        "total_records, deleted_records, user_count, artifact_count, completed_at, last_error "
        "FROM db_sessions ORDER BY started_at DESC";
    
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        return sessions;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        DBAnalysisSummary summary;
        
        const char* path = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
        const char* version = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3));
        const char* error = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 11));
        
        if (path) summary.databasePath = path;
        summary.type = static_cast<DatabaseType>(sqlite3_column_int(stmt, 2));
        if (version) summary.version = version;
        summary.fileSizeBytes = sqlite3_column_int64(stmt, 4);
        summary.tableCount = sqlite3_column_int64(stmt, 5);
        summary.totalRecords = sqlite3_column_int64(stmt, 6);
        summary.deletedRecords = sqlite3_column_int64(stmt, 7);
        summary.userCount = sqlite3_column_int64(stmt, 8);
        summary.artifactCount = sqlite3_column_int64(stmt, 9);
        summary.analyzedAt = sqlite3_column_int64(stmt, 10);
        if (error) summary.lastError = error;
        
        sessions.push_back(std::move(summary));
    }
    
    sqlite3_finalize(stmt);
    return sessions;
}

DBAnalysisSummary DBAnalysisDatabase::getSessionSummary(int64_t sessionId) {
    DBAnalysisSummary summary;
    if (!db_) return summary;
    
    const char* sql = 
        "SELECT source_path, database_type, version, file_size, table_count, "
        "total_records, deleted_records, user_count, artifact_count, completed_at, last_error "
        "FROM db_sessions WHERE id = ?";
    
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        return summary;
    }
    
    sqlite3_bind_int64(stmt, 1, sessionId);
    
    if (sqlite3_step(stmt) == SQLITE_ROW) {
        const char* path = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
        const char* version = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
        const char* error = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 10));
        
        if (path) summary.databasePath = path;
        summary.type = static_cast<DatabaseType>(sqlite3_column_int(stmt, 1));
        if (version) summary.version = version;
        summary.fileSizeBytes = sqlite3_column_int64(stmt, 3);
        summary.tableCount = sqlite3_column_int64(stmt, 4);
        summary.totalRecords = sqlite3_column_int64(stmt, 5);
        summary.deletedRecords = sqlite3_column_int64(stmt, 6);
        summary.userCount = sqlite3_column_int64(stmt, 7);
        summary.artifactCount = sqlite3_column_int64(stmt, 8);
        summary.analyzedAt = sqlite3_column_int64(stmt, 9);
        if (error) summary.lastError = error;
    }
    
    sqlite3_finalize(stmt);
    return summary;
}


} // namespace Database
} // namespace ForensicAnalyzer
