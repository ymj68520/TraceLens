/**
 * @file oss_sql.h
 * @brief OSS分析模块SQL语句定义
 * 
 * 包含OSS对象、访问日志和Bucket信息的数据库模式
 */

#pragma once

namespace SQL::OSS {

// ============================================================================
// 表创建语句
// ============================================================================

constexpr const char* CREATE_OBJECTS_TABLE = R"(
    CREATE TABLE IF NOT EXISTS oss_objects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bucket TEXT NOT NULL,
        key TEXT NOT NULL,
        size INTEGER DEFAULT 0,
        etag TEXT,
        last_modified INTEGER,
        storage_class TEXT,
        content_type TEXT,
        owner TEXT,
        user_metadata TEXT,
        version_id TEXT,
        is_deleted INTEGER DEFAULT 0,
        md5_hash TEXT,
        analyzed_at INTEGER,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT,
        llm_is_relevant INTEGER DEFAULT 1,
        UNIQUE(bucket, key, version_id)
    );
)";

constexpr const char* CREATE_OBJECTS_INDEX = R"(
    CREATE INDEX IF NOT EXISTS idx_oss_objects_bucket ON oss_objects(bucket);
    CREATE INDEX IF NOT EXISTS idx_oss_objects_key ON oss_objects(key);
    CREATE INDEX IF NOT EXISTS idx_oss_objects_last_modified ON oss_objects(last_modified);
    CREATE INDEX IF NOT EXISTS idx_oss_objects_storage_class ON oss_objects(storage_class);
)";

constexpr const char* CREATE_ACCESS_LOGS_TABLE = R"(
    CREATE TABLE IF NOT EXISTS oss_access_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id TEXT,
        timestamp INTEGER,
        operation TEXT,
        bucket TEXT,
        object_key TEXT,
        remote_ip TEXT,
        user_agent TEXT,
        accesser_id TEXT,
        http_status INTEGER,
        bytes_sent INTEGER,
        object_size INTEGER,
        time_taken_ms INTEGER,
        referer TEXT,
        host TEXT,
        signature_version TEXT,
        ssl_enabled INTEGER DEFAULT 0
    );
)";

constexpr const char* CREATE_ACCESS_LOGS_INDEX = R"(
    CREATE INDEX IF NOT EXISTS idx_oss_access_logs_timestamp ON oss_access_logs(timestamp);
    CREATE INDEX IF NOT EXISTS idx_oss_access_logs_operation ON oss_access_logs(operation);
    CREATE INDEX IF NOT EXISTS idx_oss_access_logs_object_key ON oss_access_logs(object_key);
    CREATE INDEX IF NOT EXISTS idx_oss_access_logs_remote_ip ON oss_access_logs(remote_ip);
)";

constexpr const char* CREATE_BUCKETS_TABLE = R"(
    CREATE TABLE IF NOT EXISTS oss_buckets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        region TEXT,
        endpoint TEXT,
        acl TEXT,
        owner TEXT,
        creation_date INTEGER,
        versioning_enabled INTEGER DEFAULT 0,
        logging_enabled INTEGER DEFAULT 0,
        logging_bucket TEXT,
        logging_prefix TEXT,
        storage_class TEXT,
        object_count INTEGER DEFAULT 0,
        total_size INTEGER DEFAULT 0,
        analyzed_at INTEGER
    );
)";

// ============================================================================
// 插入语句
// ============================================================================

constexpr const char* INSERT_OBJECT = R"(
    INSERT OR REPLACE INTO oss_objects 
    (bucket, key, size, etag, last_modified, storage_class, content_type, 
     owner, user_metadata, version_id, is_deleted, md5_hash, analyzed_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
)";

constexpr const char* INSERT_ACCESS_LOG = R"(
    INSERT INTO oss_access_logs 
    (request_id, timestamp, operation, bucket, object_key, remote_ip, 
     user_agent, accesser_id, http_status, bytes_sent, object_size, 
     time_taken_ms, referer, host, signature_version, ssl_enabled)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
)";

constexpr const char* INSERT_BUCKET = R"(
    INSERT OR REPLACE INTO oss_buckets 
    (name, region, endpoint, acl, owner, creation_date, versioning_enabled,
     logging_enabled, logging_bucket, logging_prefix, storage_class,
     object_count, total_size, analyzed_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
)";

// ============================================================================
// 查询语句
// ============================================================================

constexpr const char* SELECT_ALL_OBJECTS = R"(
    SELECT * FROM oss_objects ORDER BY last_modified DESC;
)";

constexpr const char* SELECT_OBJECTS_BY_BUCKET = R"(
    SELECT * FROM oss_objects WHERE bucket = ? ORDER BY key;
)";

constexpr const char* SELECT_OBJECTS_BY_PREFIX = R"(
    SELECT * FROM oss_objects WHERE bucket = ? AND key LIKE ? ORDER BY key;
)";

constexpr const char* SELECT_OBJECTS_BY_EXTENSION = R"(
    SELECT * FROM oss_objects WHERE key LIKE ? ORDER BY last_modified DESC;
)";

constexpr const char* SELECT_ACCESS_LOGS_BY_TIMERANGE = R"(
    SELECT * FROM oss_access_logs 
    WHERE timestamp >= ? AND timestamp <= ? 
    ORDER BY timestamp;
)";

constexpr const char* SELECT_ACCESS_LOGS_BY_OPERATION = R"(
    SELECT * FROM oss_access_logs 
    WHERE operation = ? 
    ORDER BY timestamp DESC;
)";

constexpr const char* SELECT_ACCESS_LOGS_BY_OBJECT = R"(
    SELECT * FROM oss_access_logs 
    WHERE object_key = ? 
    ORDER BY timestamp;
)";

constexpr const char* SELECT_ALL_BUCKETS = R"(
    SELECT * FROM oss_buckets ORDER BY name;
)";

// ============================================================================
// LLM分析查询语句
// ============================================================================

constexpr const char* UPDATE_OSS_OBJECT_LLM_ANALYSIS = R"(
    UPDATE oss_objects SET
        llm_summary = ?,
        llm_description = ?,
        llm_keywords = ?,
        llm_analyzed_at = ?,
        llm_model_used = ?,
        llm_is_relevant = ?
    WHERE id = ?
)";

constexpr const char* SELECT_OSS_OBJECTS_FOR_FILTERING = R"(
    SELECT id, bucket, key, size, last_modified, content_type, storage_class
    FROM oss_objects
    WHERE llm_analyzed_at IS NULL
    ORDER BY last_modified DESC
    LIMIT ?
)";

constexpr const char* SELECT_OSS_OBJECTS_BY_IDS = R"(
    SELECT id, bucket, key, size, content_type, storage_class
    FROM oss_objects
    WHERE id IN ({})
    ORDER BY last_modified DESC
)";

constexpr const char* SELECT_OSS_ANALYZED_OBJECTS = R"(
    SELECT * FROM oss_objects
    WHERE llm_analyzed_at IS NOT NULL AND llm_analyzed_at > 0
    ORDER BY llm_analyzed_at DESC
)";

// ============================================================================
// 统计语句
// ============================================================================

constexpr const char* COUNT_OBJECTS_BY_STORAGE_CLASS = R"(
    SELECT storage_class, COUNT(*) as count, SUM(size) as total_size
    FROM oss_objects 
    GROUP BY storage_class;
)";

constexpr const char* COUNT_OBJECTS_BY_EXTENSION = R"(
    SELECT 
        CASE 
            WHEN INSTR(key, '.') > 0 THEN LOWER(SUBSTR(key, INSTR(key, '.') + 1))
            ELSE 'no_extension'
        END as extension,
        COUNT(*) as count,
        SUM(size) as total_size
    FROM oss_objects 
    GROUP BY extension
    ORDER BY count DESC;
)";

constexpr const char* COUNT_OPERATIONS = R"(
    SELECT operation, COUNT(*) as count
    FROM oss_access_logs 
    GROUP BY operation
    ORDER BY count DESC;
)";

constexpr const char* GET_ANALYSIS_SUMMARY = R"(
    SELECT 
        (SELECT COUNT(*) FROM oss_objects) as total_objects,
        (SELECT SUM(size) FROM oss_objects) as total_size,
        (SELECT COUNT(*) FROM oss_objects WHERE is_deleted = 1) as deleted_objects,
        (SELECT COUNT(*) FROM oss_access_logs) as log_entries;
)";

// ============================================================================
// 视图创建语句
// ============================================================================

constexpr const char* CREATE_VIEWS = R"(
    CREATE VIEW IF NOT EXISTS oss_objects_summary AS
    SELECT 
        bucket,
        COUNT(*) as object_count,
        SUM(size) as total_size,
        MIN(last_modified) as oldest_modified,
        MAX(last_modified) as newest_modified
    FROM oss_objects
    GROUP BY bucket;

    CREATE VIEW IF NOT EXISTS oss_access_timeline AS
    SELECT 
        DATE(timestamp, 'unixepoch') as date,
        operation,
        COUNT(*) as operation_count,
        SUM(bytes_sent) as total_bytes
    FROM oss_access_logs
    GROUP BY date, operation
    ORDER BY date, operation;
)";

} // namespace SQL::OSS
