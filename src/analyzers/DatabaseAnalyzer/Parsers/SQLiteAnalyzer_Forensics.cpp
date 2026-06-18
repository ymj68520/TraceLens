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
// Forensic analysis: records/artifacts/WAL/deleted-recovery/app-type.
// Split from SQLiteAnalyzer.cpp. Methods belong to SQLiteAnalyzer.

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


} // namespace Database
} // namespace ForensicAnalyzer
