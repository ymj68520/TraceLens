/**
 * @file OSSAnalysisDatabase.cpp
 * @brief OSS分析数据库操作实现
 */

#include "OSSAnalysisDatabase.h"
#include "DatabaseManager/SQL/oss_sql.h"
#include "Logger/Logger.h"

#include <chrono>
#include <sstream>

namespace ForensicAnalyzer {
namespace OSS {

OSSAnalysisDatabase::OSSAnalysisDatabase(const std::string& dbPath)
    : dbPath_(dbPath) {
}

OSSAnalysisDatabase::~OSSAnalysisDatabase() {
    close();
}

bool OSSAnalysisDatabase::initialize() {
    int rc = sqlite3_open(dbPath_.c_str(), &db_);
    if (rc != SQLITE_OK) {
        LOG_ERROR("Failed to open OSS database: " + dbPath_ + " - " + sqlite3_errmsg(db_));
        return false;
    }
    
    // 创建表
    if (!executeSQL(SQL::OSS::CREATE_OBJECTS_TABLE)) return false;
    if (!executeSQL(SQL::OSS::CREATE_ACCESS_LOGS_TABLE)) return false;
    if (!executeSQL(SQL::OSS::CREATE_BUCKETS_TABLE)) return false;
    
    // 创建索引（分别执行每个索引）
    sqlite3_exec(db_, "CREATE INDEX IF NOT EXISTS idx_oss_objects_bucket ON oss_objects(bucket);", nullptr, nullptr, nullptr);
    sqlite3_exec(db_, "CREATE INDEX IF NOT EXISTS idx_oss_objects_key ON oss_objects(key);", nullptr, nullptr, nullptr);
    sqlite3_exec(db_, "CREATE INDEX IF NOT EXISTS idx_oss_objects_last_modified ON oss_objects(last_modified);", nullptr, nullptr, nullptr);
    sqlite3_exec(db_, "CREATE INDEX IF NOT EXISTS idx_oss_objects_storage_class ON oss_objects(storage_class);", nullptr, nullptr, nullptr);
    
    sqlite3_exec(db_, "CREATE INDEX IF NOT EXISTS idx_oss_access_logs_timestamp ON oss_access_logs(timestamp);", nullptr, nullptr, nullptr);
    sqlite3_exec(db_, "CREATE INDEX IF NOT EXISTS idx_oss_access_logs_operation ON oss_access_logs(operation);", nullptr, nullptr, nullptr);
    sqlite3_exec(db_, "CREATE INDEX IF NOT EXISTS idx_oss_access_logs_object_key ON oss_access_logs(object_key);", nullptr, nullptr, nullptr);
    sqlite3_exec(db_, "CREATE INDEX IF NOT EXISTS idx_oss_access_logs_remote_ip ON oss_access_logs(remote_ip);", nullptr, nullptr, nullptr);
    
    LOG_INFO("OSS database initialized: " + dbPath_);
    return true;
}

void OSSAnalysisDatabase::close() {
    if (db_) {
        sqlite3_close(db_);
        db_ = nullptr;
    }
}

bool OSSAnalysisDatabase::executeSQL(const char* sql) {
    char* errMsg = nullptr;
    int rc = sqlite3_exec(db_, sql, nullptr, nullptr, &errMsg);
    if (rc != SQLITE_OK) {
        LOG_ERROR("SQL error: " + std::string(errMsg));
        sqlite3_free(errMsg);
        return false;
    }
    return true;
}

// ========== 对象操作 ==========

bool OSSAnalysisDatabase::insertObject(const OSSObjectInfo& object) {
    sqlite3_stmt* stmt;
    int rc = sqlite3_prepare_v2(db_, SQL::OSS::INSERT_OBJECT, -1, &stmt, nullptr);
    if (rc != SQLITE_OK) {
        LOG_ERROR("Failed to prepare insert object statement");
        return false;
    }
    
    // 序列化user metadata为JSON
    std::string metaJson = "{";
    bool first = true;
    for (const auto& [key, value] : object.userMeta) {
        if (!first) metaJson += ",";
        metaJson += "\"" + key + "\":\"" + value + "\"";
        first = false;
    }
    metaJson += "}";
    
    sqlite3_bind_text(stmt, 1, object.bucket.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, object.key.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 3, object.size);
    sqlite3_bind_text(stmt, 4, object.etag.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 5, object.lastModified);
    sqlite3_bind_text(stmt, 6, object.storageClass.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 7, object.contentType.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 8, object.owner.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 9, metaJson.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 10, object.versionId.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 11, object.isDeleted ? 1 : 0);
    sqlite3_bind_text(stmt, 12, object.md5Hash.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 13, object.analyzedAt);
    
    rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    
    return rc == SQLITE_DONE;
}

int OSSAnalysisDatabase::insertObjects(const std::vector<OSSObjectInfo>& objects) {
    beginTransaction();
    int count = 0;
    for (const auto& obj : objects) {
        if (insertObject(obj)) count++;
    }
    commitTransaction();
    return count;
}

OSSObjectInfo OSSAnalysisDatabase::parseObjectRow(sqlite3_stmt* stmt) {
    OSSObjectInfo obj;
    obj.bucket = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
    obj.key = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
    obj.size = sqlite3_column_int64(stmt, 3);

    const char* etag = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4));
    if (etag) obj.etag = etag;

    obj.lastModified = sqlite3_column_int64(stmt, 5);

    const char* storageClass = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6));
    if (storageClass) obj.storageClass = storageClass;

    const char* contentType = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7));
    if (contentType) obj.contentType = contentType;

    const char* owner = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 8));
    if (owner) obj.owner = owner;

    const char* versionId = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 10));
    if (versionId) obj.versionId = versionId;

    obj.isDeleted = sqlite3_column_int(stmt, 11) != 0;

    const char* md5 = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 12));
    if (md5) obj.md5Hash = md5;

    obj.analyzedAt = sqlite3_column_int64(stmt, 13);

    // Parse LLM analysis fields (columns 14-19)
    const char* llmSummary = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 14));
    if (llmSummary) obj.llmSummary = llmSummary;

    const char* llmDescription = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 15));
    if (llmDescription) obj.llmDescription = llmDescription;

    const char* llmKeywords = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 16));
    if (llmKeywords) obj.llmKeywords = llmKeywords;

    obj.llmAnalyzedAt = sqlite3_column_int64(stmt, 17);

    const char* llmModelUsed = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 18));
    if (llmModelUsed) obj.llmModelUsed = llmModelUsed;

    obj.llmIsRelevant = sqlite3_column_int(stmt, 19);

    return obj;
}

std::vector<OSSObjectInfo> OSSAnalysisDatabase::getAllObjects() {
    std::vector<OSSObjectInfo> results;
    sqlite3_stmt* stmt;
    
    if (sqlite3_prepare_v2(db_, SQL::OSS::SELECT_ALL_OBJECTS, -1, &stmt, nullptr) == SQLITE_OK) {
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            results.push_back(parseObjectRow(stmt));
        }
        sqlite3_finalize(stmt);
    }
    
    return results;
}

std::vector<OSSObjectInfo> OSSAnalysisDatabase::getObjectsByBucket(const std::string& bucket) {
    std::vector<OSSObjectInfo> results;
    sqlite3_stmt* stmt;
    
    if (sqlite3_prepare_v2(db_, SQL::OSS::SELECT_OBJECTS_BY_BUCKET, -1, &stmt, nullptr) == SQLITE_OK) {
        sqlite3_bind_text(stmt, 1, bucket.c_str(), -1, SQLITE_TRANSIENT);
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            results.push_back(parseObjectRow(stmt));
        }
        sqlite3_finalize(stmt);
    }
    
    return results;
}

std::vector<OSSObjectInfo> OSSAnalysisDatabase::getObjectsByPrefix(const std::string& bucket, const std::string& prefix) {
    std::vector<OSSObjectInfo> results;
    sqlite3_stmt* stmt;
    
    if (sqlite3_prepare_v2(db_, SQL::OSS::SELECT_OBJECTS_BY_PREFIX, -1, &stmt, nullptr) == SQLITE_OK) {
        sqlite3_bind_text(stmt, 1, bucket.c_str(), -1, SQLITE_TRANSIENT);
        std::string pattern = prefix + "%";
        sqlite3_bind_text(stmt, 2, pattern.c_str(), -1, SQLITE_TRANSIENT);
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            results.push_back(parseObjectRow(stmt));
        }
        sqlite3_finalize(stmt);
    }
    
    return results;
}

std::vector<OSSObjectInfo> OSSAnalysisDatabase::getObjectsByExtension(const std::string& extension) {
    std::vector<OSSObjectInfo> results;
    sqlite3_stmt* stmt;
    
    if (sqlite3_prepare_v2(db_, SQL::OSS::SELECT_OBJECTS_BY_EXTENSION, -1, &stmt, nullptr) == SQLITE_OK) {
        std::string pattern = "%" + extension;
        sqlite3_bind_text(stmt, 1, pattern.c_str(), -1, SQLITE_TRANSIENT);
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            results.push_back(parseObjectRow(stmt));
        }
        sqlite3_finalize(stmt);
    }
    
    return results;
}

// ========== LLM分析操作 ==========

bool OSSAnalysisDatabase::updateLLMAnalysis(
    int64_t objectId,
    const std::string& summary,
    const std::string& description,
    const std::string& keywords,
    int64_t analyzedAt,
    const std::string& modelUsed,
    int isRelevant
) {
    sqlite3_stmt* stmt = nullptr;

    if (sqlite3_prepare_v2(db_, SQL::OSS::UPDATE_OSS_OBJECT_LLM_ANALYSIS, -1, &stmt, nullptr) != SQLITE_OK) {
        LOG_ERROR("Failed to prepare update LLM analysis statement");
        return false;
    }

    sqlite3_bind_text(stmt, 1, summary.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, description.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, keywords.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 4, analyzedAt);
    sqlite3_bind_text(stmt, 5, modelUsed.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 6, isRelevant);
    sqlite3_bind_int64(stmt, 7, objectId);

    bool result = (sqlite3_step(stmt) == SQLITE_DONE);
    sqlite3_finalize(stmt);
    return result;
}

std::vector<OSSObjectInfo> OSSAnalysisDatabase::getObjectsForFiltering(
    int limit,
    const std::string& bucket
) {
    std::vector<OSSObjectInfo> objects;
    sqlite3_stmt* stmt = nullptr;

    std::string sql = SQL::OSS::SELECT_OSS_OBJECTS_FOR_FILTERING;
    if (!bucket.empty()) {
        sql = "SELECT id, bucket, key, size, last_modified, content_type, storage_class "
              "FROM oss_objects WHERE bucket = ? AND llm_analyzed_at IS NULL "
              "ORDER BY last_modified DESC LIMIT ?";
    }

    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) == SQLITE_OK) {
        if (!bucket.empty()) {
            sqlite3_bind_text(stmt, 1, bucket.c_str(), -1, SQLITE_TRANSIENT);
            sqlite3_bind_int(stmt, 2, limit);
        } else {
            sqlite3_bind_int(stmt, 1, limit);
        }

        while (sqlite3_step(stmt) == SQLITE_ROW) {
            objects.push_back(parseObjectRow(stmt));
        }
    }

    sqlite3_finalize(stmt);
    return objects;
}

std::vector<OSSObjectInfo> OSSAnalysisDatabase::getObjectsByIds(
    const std::vector<int64_t>& objectIds
) {
    std::vector<OSSObjectInfo> objects;
    if (objectIds.empty()) return objects;

    // Build IN clause
    std::string inClause;
    for (size_t i = 0; i < objectIds.size(); ++i) {
        inClause += "?";
        if (i < objectIds.size() - 1) inClause += ",";
    }

    std::string sql = "SELECT id, bucket, key, size, last_modified, storage_class, content_type, "
                      "etag, owner, version_id, is_deleted, md5_hash, analyzed_at, "
                      "llm_summary, llm_description, llm_keywords, llm_analyzed_at, llm_model_used "
                      "FROM oss_objects WHERE id IN (" + inClause + ") ORDER BY last_modified DESC";

    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) == SQLITE_OK) {
        for (size_t i = 0; i < objectIds.size(); ++i) {
            sqlite3_bind_int64(stmt, static_cast<int>(i + 1), objectIds[i]);
        }

        while (sqlite3_step(stmt) == SQLITE_ROW) {
            objects.push_back(parseObjectRow(stmt));
        }
    }

    sqlite3_finalize(stmt);
    return objects;
}

std::vector<OSSObjectInfo> OSSAnalysisDatabase::getAnalyzedObjects() {
    std::vector<OSSObjectInfo> objects;
    sqlite3_stmt* stmt = nullptr;

    if (sqlite3_prepare_v2(db_, SQL::OSS::SELECT_OSS_ANALYZED_OBJECTS, -1, &stmt, nullptr) == SQLITE_OK) {
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            objects.push_back(parseObjectRow(stmt));
        }
    }

    sqlite3_finalize(stmt);
    return objects;
}

// ========== 访问日志操作 ==========



void OSSAnalysisDatabase::beginTransaction() {
    executeSQL("BEGIN TRANSACTION;");
}

void OSSAnalysisDatabase::commitTransaction() {
    executeSQL("COMMIT;");
}

void OSSAnalysisDatabase::rollbackTransaction() {
    executeSQL("ROLLBACK;");
}

} // namespace OSS
} // namespace ForensicAnalyzer
