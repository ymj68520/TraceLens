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

// ========== 访问日志操作 ==========

bool OSSAnalysisDatabase::insertAccessLog(const OSSAccessLogEntry& entry) {
    sqlite3_stmt* stmt;
    int rc = sqlite3_prepare_v2(db_, SQL::OSS::INSERT_ACCESS_LOG, -1, &stmt, nullptr);
    if (rc != SQLITE_OK) return false;
    
    sqlite3_bind_text(stmt, 1, entry.requestId.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 2, entry.timestamp);
    sqlite3_bind_text(stmt, 3, entry.operation.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, entry.bucket.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 5, entry.objectKey.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 6, entry.remoteIP.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 7, entry.userAgent.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 8, entry.accesserId.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 9, entry.httpStatus);
    sqlite3_bind_int64(stmt, 10, entry.bytesSent);
    sqlite3_bind_int64(stmt, 11, entry.objectSize);
    sqlite3_bind_int64(stmt, 12, entry.timeTakenMs);
    sqlite3_bind_text(stmt, 13, entry.referer.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 14, entry.host.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 15, entry.signatureVersion.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 16, entry.sslEnabled ? 1 : 0);
    
    rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    
    return rc == SQLITE_DONE;
}

int OSSAnalysisDatabase::insertAccessLogs(const std::vector<OSSAccessLogEntry>& entries) {
    beginTransaction();
    int count = 0;
    for (const auto& entry : entries) {
        if (insertAccessLog(entry)) count++;
    }
    commitTransaction();
    return count;
}

OSSAccessLogEntry OSSAnalysisDatabase::parseAccessLogRow(sqlite3_stmt* stmt) {
    OSSAccessLogEntry entry;
    
    const char* requestId = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
    if (requestId) entry.requestId = requestId;
    
    entry.timestamp = sqlite3_column_int64(stmt, 2);
    
    const char* operation = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3));
    if (operation) entry.operation = operation;
    
    const char* bucket = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4));
    if (bucket) entry.bucket = bucket;
    
    const char* objectKey = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5));
    if (objectKey) entry.objectKey = objectKey;
    
    const char* remoteIP = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6));
    if (remoteIP) entry.remoteIP = remoteIP;
    
    const char* userAgent = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7));
    if (userAgent) entry.userAgent = userAgent;
    
    const char* accesserId = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 8));
    if (accesserId) entry.accesserId = accesserId;
    
    entry.httpStatus = sqlite3_column_int(stmt, 9);
    entry.bytesSent = sqlite3_column_int64(stmt, 10);
    entry.objectSize = sqlite3_column_int64(stmt, 11);
    entry.timeTakenMs = sqlite3_column_int64(stmt, 12);
    
    const char* referer = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 13));
    if (referer) entry.referer = referer;
    
    const char* host = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 14));
    if (host) entry.host = host;
    
    const char* sigVer = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 15));
    if (sigVer) entry.signatureVersion = sigVer;
    
    entry.sslEnabled = sqlite3_column_int(stmt, 16) != 0;
    
    return entry;
}

std::vector<OSSAccessLogEntry> OSSAnalysisDatabase::getAccessLogsByTimeRange(int64_t startTime, int64_t endTime) {
    std::vector<OSSAccessLogEntry> results;
    sqlite3_stmt* stmt;
    
    if (sqlite3_prepare_v2(db_, SQL::OSS::SELECT_ACCESS_LOGS_BY_TIMERANGE, -1, &stmt, nullptr) == SQLITE_OK) {
        sqlite3_bind_int64(stmt, 1, startTime);
        sqlite3_bind_int64(stmt, 2, endTime);
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            results.push_back(parseAccessLogRow(stmt));
        }
        sqlite3_finalize(stmt);
    }
    
    return results;
}

std::vector<OSSAccessLogEntry> OSSAnalysisDatabase::getAccessLogsByOperation(const std::string& operation) {
    std::vector<OSSAccessLogEntry> results;
    sqlite3_stmt* stmt;
    
    if (sqlite3_prepare_v2(db_, SQL::OSS::SELECT_ACCESS_LOGS_BY_OPERATION, -1, &stmt, nullptr) == SQLITE_OK) {
        sqlite3_bind_text(stmt, 1, operation.c_str(), -1, SQLITE_TRANSIENT);
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            results.push_back(parseAccessLogRow(stmt));
        }
        sqlite3_finalize(stmt);
    }
    
    return results;
}

std::vector<OSSAccessLogEntry> OSSAnalysisDatabase::getAccessLogsByObject(const std::string& objectKey) {
    std::vector<OSSAccessLogEntry> results;
    sqlite3_stmt* stmt;
    
    if (sqlite3_prepare_v2(db_, SQL::OSS::SELECT_ACCESS_LOGS_BY_OBJECT, -1, &stmt, nullptr) == SQLITE_OK) {
        sqlite3_bind_text(stmt, 1, objectKey.c_str(), -1, SQLITE_TRANSIENT);
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            results.push_back(parseAccessLogRow(stmt));
        }
        sqlite3_finalize(stmt);
    }
    
    return results;
}

// ========== Bucket操作 ==========

bool OSSAnalysisDatabase::insertBucket(const OSSBucketInfo& bucket) {
    sqlite3_stmt* stmt;
    int rc = sqlite3_prepare_v2(db_, SQL::OSS::INSERT_BUCKET, -1, &stmt, nullptr);
    if (rc != SQLITE_OK) return false;
    
    sqlite3_bind_text(stmt, 1, bucket.name.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, bucket.region.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, bucket.endpoint.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, bucket.acl.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 5, bucket.owner.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 6, bucket.creationDate);
    sqlite3_bind_int(stmt, 7, bucket.versioningEnabled ? 1 : 0);
    sqlite3_bind_int(stmt, 8, bucket.loggingEnabled ? 1 : 0);
    sqlite3_bind_text(stmt, 9, bucket.loggingBucket.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 10, bucket.loggingPrefix.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 11, bucket.storageClass.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 12, bucket.objectCount);
    sqlite3_bind_int64(stmt, 13, bucket.totalSize);
    sqlite3_bind_int64(stmt, 14, bucket.analyzedAt);
    
    rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    
    return rc == SQLITE_DONE;
}

OSSBucketInfo OSSAnalysisDatabase::parseBucketRow(sqlite3_stmt* stmt) {
    OSSBucketInfo bucket;
    
    const char* name = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
    if (name) bucket.name = name;
    
    const char* region = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
    if (region) bucket.region = region;
    
    const char* endpoint = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3));
    if (endpoint) bucket.endpoint = endpoint;
    
    const char* acl = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4));
    if (acl) bucket.acl = acl;
    
    const char* owner = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5));
    if (owner) bucket.owner = owner;
    
    bucket.creationDate = sqlite3_column_int64(stmt, 6);
    bucket.versioningEnabled = sqlite3_column_int(stmt, 7) != 0;
    bucket.loggingEnabled = sqlite3_column_int(stmt, 8) != 0;
    
    const char* loggingBucket = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 9));
    if (loggingBucket) bucket.loggingBucket = loggingBucket;
    
    const char* loggingPrefix = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 10));
    if (loggingPrefix) bucket.loggingPrefix = loggingPrefix;
    
    const char* storageClass = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 11));
    if (storageClass) bucket.storageClass = storageClass;
    
    bucket.objectCount = sqlite3_column_int64(stmt, 12);
    bucket.totalSize = sqlite3_column_int64(stmt, 13);
    bucket.analyzedAt = sqlite3_column_int64(stmt, 14);
    
    return bucket;
}

std::vector<OSSBucketInfo> OSSAnalysisDatabase::getAllBuckets() {
    std::vector<OSSBucketInfo> results;
    sqlite3_stmt* stmt;
    
    if (sqlite3_prepare_v2(db_, SQL::OSS::SELECT_ALL_BUCKETS, -1, &stmt, nullptr) == SQLITE_OK) {
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            results.push_back(parseBucketRow(stmt));
        }
        sqlite3_finalize(stmt);
    }
    
    return results;
}

// ========== 统计操作 ==========

OSSAnalysisSummary OSSAnalysisDatabase::getAnalysisSummary() {
    OSSAnalysisSummary summary;
    sqlite3_stmt* stmt;
    
    if (sqlite3_prepare_v2(db_, SQL::OSS::GET_ANALYSIS_SUMMARY, -1, &stmt, nullptr) == SQLITE_OK) {
        if (sqlite3_step(stmt) == SQLITE_ROW) {
            summary.totalObjects = sqlite3_column_int64(stmt, 0);
            summary.totalSize = sqlite3_column_int64(stmt, 1);
            summary.deletedObjects = sqlite3_column_int64(stmt, 2);
            summary.logEntriesCount = sqlite3_column_int64(stmt, 3);
        }
        sqlite3_finalize(stmt);
    }
    
    // Get additional statistics
    summary.objectsByStorageClass = {};
    auto storageStats = getObjectCountByStorageClass();
    for (const auto& [storageClass, stats] : storageStats) {
        summary.objectsByStorageClass[storageClass] = stats.first;
    }
    
    summary.operationCounts = getOperationCounts();
    
    return summary;
}

std::map<std::string, std::pair<int64_t, int64_t>> OSSAnalysisDatabase::getObjectCountByStorageClass() {
    std::map<std::string, std::pair<int64_t, int64_t>> results;
    sqlite3_stmt* stmt;
    
    if (sqlite3_prepare_v2(db_, SQL::OSS::COUNT_OBJECTS_BY_STORAGE_CLASS, -1, &stmt, nullptr) == SQLITE_OK) {
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            const char* storageClass = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
            if (storageClass) {
                int64_t count = sqlite3_column_int64(stmt, 1);
                int64_t size = sqlite3_column_int64(stmt, 2);
                results[storageClass] = {count, size};
            }
        }
        sqlite3_finalize(stmt);
    }
    
    return results;
}

std::map<std::string, std::pair<int64_t, int64_t>> OSSAnalysisDatabase::getObjectCountByExtension() {
    std::map<std::string, std::pair<int64_t, int64_t>> results;
    sqlite3_stmt* stmt;
    
    if (sqlite3_prepare_v2(db_, SQL::OSS::COUNT_OBJECTS_BY_EXTENSION, -1, &stmt, nullptr) == SQLITE_OK) {
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            const char* ext = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
            if (ext) {
                int64_t count = sqlite3_column_int64(stmt, 1);
                int64_t size = sqlite3_column_int64(stmt, 2);
                results[ext] = {count, size};
            }
        }
        sqlite3_finalize(stmt);
    }
    
    return results;
}

std::map<std::string, int64_t> OSSAnalysisDatabase::getOperationCounts() {
    std::map<std::string, int64_t> results;
    sqlite3_stmt* stmt;
    
    if (sqlite3_prepare_v2(db_, SQL::OSS::COUNT_OPERATIONS, -1, &stmt, nullptr) == SQLITE_OK) {
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            const char* op = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
            if (op) {
                int64_t count = sqlite3_column_int64(stmt, 1);
                results[op] = count;
            }
        }
        sqlite3_finalize(stmt);
    }
    
    return results;
}

// ========== 事务操作 ==========

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
