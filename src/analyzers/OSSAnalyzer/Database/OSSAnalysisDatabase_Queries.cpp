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

// Access-log, bucket, summary, and statistics operations. Split from OSSAnalysisDatabase.cpp.

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


} // namespace OSS
} // namespace ForensicAnalyzer
