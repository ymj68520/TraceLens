#include "../SQLiteHelper.h"
#include <iostream>
#include <algorithm>
#include <ctime>
#include <regex>
#include <sstream>
#include <iomanip>

using json = nlohmann::json;

// ============================================================================
// STATISTICAL ANALYSIS IMPLEMENTATION
// ============================================================================

json SQLiteHelper::get_overview_statistics(const std::string& raw_db, const std::string& files_db, const std::string& events_db) {
    json result;
    sqlite3* raw = open_database(raw_db, result);
    sqlite3* files = open_database(files_db, result);
    sqlite3* events = open_database(events_db, result);

    if (!raw || !files || !events) {
        if (raw) sqlite3_close(raw);
        if (files) sqlite3_close(files);
        if (events) sqlite3_close(events);
        return result;
    }

    // Raw DB stats
    json raw_stats = execute_query(raw, R"(
        SELECT
            COUNT(*) as total_files,
            COUNT(CASE WHEN is_deleted = 1 THEN 1 END) as deleted_files,
            COUNT(CASE WHEN is_allocated = 1 THEN 1 END) as allocated_files,
            SUM(size) as total_size,
            AVG(size) as avg_file_size,
            MAX(mtime) as latest_modification
        FROM files
    )");

    // Events DB stats
    json events_stats = execute_query(events, R"(
        SELECT
            COUNT(*) as total_events,
            COUNT(DISTINCT event_type) as event_types,
            COUNT(DISTINCT file_path) as unique_files_affected,
            MIN(timestamp) as earliest_event,
            MAX(timestamp) as latest_event
        FROM events
    )");

    // Files DB stats
    json files_stats = execute_query(files, R"(
        SELECT
            COUNT(*) as categorized_files,
            COUNT(DISTINCT category) as categories,
            COUNT(DISTINCT extension) as unique_extensions
        FROM files
    )");

    result["raw_database_stats"] = raw_stats;
    result["events_database_stats"] = events_stats;
    result["files_database_stats"] = files_stats;

    sqlite3_close(raw);
    sqlite3_close(files);
    sqlite3_close(events);
    return result;
}

json SQLiteHelper::get_file_distribution_analysis(const std::string& files_db) {
    json result;
    sqlite3* db = open_database(files_db, result);
    if (!db) return result;

    // File size distribution
    std::string size_dist_sql = R"(
        SELECT
            CASE
                WHEN size = 0 THEN 'empty'
                WHEN size < 1024 THEN 'small_1KB'
                WHEN size < 1048576 THEN 'medium_1MB'
                WHEN size < 1073741824 THEN 'large_1GB'
                ELSE 'very_large'
            END as size_category,
            COUNT(*) as file_count,
            SUM(size) as total_size
        FROM files
        GROUP BY size_category
        ORDER BY
            CASE size_category
                WHEN 'empty' THEN 1
                WHEN 'small_1KB' THEN 2
                WHEN 'medium_1MB' THEN 3
                WHEN 'large_1GB' THEN 4
                ELSE 5
            END
    )";

    json size_distribution = execute_query(db, size_dist_sql);

    // Top 10 largest directories
    std::string dir_size_sql = R"(
        SELECT
            SUBSTR(path, 1, INSTR(SUBSTR(path, 2), '/') + 1) as directory,
            COUNT(*) as file_count,
            SUM(size) as total_size
        FROM files
        WHERE path != ''
        GROUP BY directory
        ORDER BY total_size DESC
        LIMIT 20
    )";

    json directory_sizes = execute_query(db, dir_size_sql);

    result["size_distribution"] = size_distribution;
    result["directory_sizes"] = directory_sizes;

    sqlite3_close(db);
    return result;
}

json SQLiteHelper::get_activity_patterns(const std::string& events_db) {
    json result;
    sqlite3* db = open_database(events_db, result);
    if (!db) return result;

    // Daily activity patterns
    json daily_pattern = execute_query(db, R"(
        SELECT
            CAST((timestamp % 86400) / 3600 AS INTEGER) as hour,
            COUNT(*) as activity_count
        FROM events
        WHERE timestamp > 0
        GROUP BY hour
        ORDER BY hour
    )");

    // Weekly activity patterns
    json weekly_pattern = execute_query(db, R"(
        SELECT
            CAST((timestamp / 86400) % 7 AS INTEGER) as day_of_week,
            COUNT(*) as activity_count
        FROM events
        WHERE timestamp > 0
        GROUP BY day_of_week
        ORDER BY day_of_week
    )");

    // Event type distribution
    json event_types = execute_query(db, R"(
        SELECT event_type, COUNT(*) as count
        FROM events
        GROUP BY event_type
        ORDER BY count DESC
    )");

    result["daily_pattern"] = daily_pattern;
    result["weekly_pattern"] = weekly_pattern;
    result["event_type_distribution"] = event_types;

    sqlite3_close(db);
    return result;
}

json SQLiteHelper::get_deleted_files_analysis(const std::string& raw_db) {
    json result;
    sqlite3* db = open_database(raw_db, result);
    if (!db) return result;

    // Deleted files summary
    json deleted_summary = execute_query(db, R"(
        SELECT
            COUNT(*) as total_deleted,
            SUM(size) as total_deleted_size,
            AVG(size) as avg_deleted_size,
            COUNT(CASE WHEN size > 1048576 THEN 1 END) as large_deleted_files
        FROM files
        WHERE is_deleted = 1
    )");

    // Recently deleted files
    json recently_deleted = execute_query(db, R"(
        SELECT * FROM files
        WHERE is_deleted = 1
        ORDER BY ctime DESC, mtime DESC
        LIMIT 100
    )");

    // Deleted files by type
    json deleted_by_type = execute_query(db, R"(
        SELECT type, COUNT(*) as count, SUM(size) as total_size
        FROM files
        WHERE is_deleted = 1 AND type != ''
        GROUP BY type
        ORDER BY count DESC
    )");

    result["deleted_summary"] = deleted_summary;
    result["recently_deleted"] = recently_deleted;
    result["deleted_by_type"] = deleted_by_type;

    sqlite3_close(db);
    return result;
}

json SQLiteHelper::get_suspicious_patterns(const std::string& raw_db, const std::string& events_db) {
    json result;
    sqlite3* raw = open_database(raw_db, result);
    sqlite3* events = open_database(events_db, result);

    if (!raw || !events) {
        if (raw) sqlite3_close(raw);
        if (events) sqlite3_close(events);
        return result;
    }

    // Suspicious patterns
    std::vector<json> suspicious_activities;

    // Pattern 1: Files in suspicious locations
    std::string suspicious_sql = R"(
        SELECT file_path, COUNT(*) as activity_count, MAX(timestamp) as last_activity
        FROM events
        WHERE file_path LIKE '%/temp/%'
           OR file_path LIKE '%/tmp/%'
           OR file_path LIKE '%/system32/%'
           OR file_path LIKE '%recycle%'
           OR file_path LIKE '%$Recycle%'
        GROUP BY file_path
        HAVING activity_count > 5
        ORDER BY activity_count DESC
    )";

    json suspicious_paths = execute_query(events, suspicious_sql);
    if (suspicious_paths.is_array()) {
        for (const auto& path : suspicious_paths) {
            suspicious_activities.push_back({
                {"pattern", "high_activity_suspicious_path"},
                {"details", path}
            });
        }
    }

    // Pattern 2: Files created and deleted quickly
    std::string quick_delete_sql = R"(
        SELECT e1.file_path, e1.timestamp as created, e2.timestamp as deleted,
               (e2.timestamp - e1.timestamp) as lifetime_seconds
        FROM events e1
        JOIN events e2 ON e1.file_path = e2.file_path
        WHERE e1.event_type = 'created'
          AND e2.event_type = 'deleted'
          AND e2.timestamp > e1.timestamp
          AND (e2.timestamp - e1.timestamp) < 3600
        ORDER BY lifetime_seconds ASC
        LIMIT 100
    )";

    json quick_deletes = execute_query(events, quick_delete_sql);
    if (quick_deletes.is_array() && !quick_deletes.empty()) {
        suspicious_activities.push_back({
            {"pattern", "quick_create_delete"},
            {"details", quick_deletes}
        });
    }

    // Pattern 3: Suspicious file extensions in raw DB
    std::string suspicious_ext_sql = R"(
        SELECT name, path, size, mtime, ctime
        FROM files
        WHERE (LOWER(name) LIKE '%.bat%'
           OR LOWER(name) LIKE '%.cmd%'
           OR LOWER(name) LIKE '%.scr%'
           OR LOWER(name) LIKE '%.vbs%'
           OR LOWER(name) LIKE '%.js%'
           OR LOWER(name) LIKE '%.jar%'
           OR LOWER(name) LIKE '%.exe%'
           OR LOWER(name) LIKE '%.com%')
           AND is_deleted = 0
        ORDER BY size DESC
        LIMIT 50
    )";

    json suspicious_files = execute_query(raw, suspicious_ext_sql);
    if (suspicious_files.is_array() && !suspicious_files.empty()) {
        suspicious_activities.push_back({
            {"pattern", "suspicious_executable_extensions"},
            {"details", suspicious_files}
        });
    }

    result["suspicious_patterns"] = suspicious_activities;
    result["total_patterns_detected"] = suspicious_activities.size();

    sqlite3_close(raw);
    sqlite3_close(events);
    return result;
}

json SQLiteHelper::get_user_activity_analysis(const std::string& raw_db, const std::string& events_db) {
    json result;
    sqlite3* raw = open_database(raw_db, result);
    sqlite3* events = open_database(events_db, result);

    if (!raw || !events) {
        if (raw) sqlite3_close(raw);
        if (events) sqlite3_close(events);
        return result;
    }

    // User activity patterns by hour
    std::string hourly_activity_sql = R"(
        SELECT
            CAST((timestamp % 86400) / 3600 AS INTEGER) as hour,
            COUNT(*) as activity_count
        FROM events
        WHERE timestamp > 0
        GROUP BY hour
        ORDER BY hour
    )";

    json hourly_activity = execute_query(events, hourly_activity_sql);

    // Most active directories
    std::string active_dirs_sql = R"(
        SELECT
            SUBSTR(file_path, 1, INSTR(SUBSTR(file_path, 2), '/') + 1) as directory,
            COUNT(*) as activity_count
        FROM events
        WHERE file_path != ''
        GROUP BY directory
        HAVING activity_count > 10
        ORDER BY activity_count DESC
        LIMIT 20
    )";

    json active_dirs = execute_query(events, active_dirs_sql);

    // User home directory activity
    std::string user_dirs_sql = R"(
        SELECT
            file_path,
            COUNT(*) as activity_count
        FROM events
        WHERE file_path LIKE '/home/%'
           OR file_path LIKE '/Users/%'
           OR file_path LIKE 'C:\\Users\\%'
        GROUP BY file_path
        HAVING activity_count > 5
        ORDER BY activity_count DESC
        LIMIT 50
    )";

    json user_dirs = execute_query(events, user_dirs_sql);

    result["hourly_activity_pattern"] = hourly_activity;
    result["most_active_directories"] = active_dirs;
    result["user_directory_activity"] = user_dirs;

    sqlite3_close(raw);
    sqlite3_close(events);
    return result;
}

json SQLiteHelper::get_system_events(const std::string& events_db, const std::string& start_time, const std::string& end_time, int limit, int offset) {
    json result;
    sqlite3* events = open_database(events_db, result);
    if (!events) return result;

    // Build WHERE clause for filters
    std::string where_clause = " WHERE event_type LIKE 'SYSTEM_%' OR event_type LIKE 'WINDOWS_%' OR event_type LIKE 'LINUX_%' OR event_type LIKE 'SERVICE_%' OR event_type LIKE 'PROCESS_%' OR event_type LIKE 'NETWORK_%'";

    if (!start_time.empty()) {
        where_clause += " AND timestamp >= " + std::to_string(parse_timestamp(start_time));
    }
    if (!end_time.empty()) {
        where_clause += " AND timestamp <= " + std::to_string(parse_timestamp(end_time));
    }

    // Get total count for pagination metadata
    std::string count_sql = "SELECT COUNT(*) FROM events" + where_clause;
    sqlite3_stmt* count_stmt;
    int64_t total_count = 0;
    if (sqlite3_prepare_v2(events, count_sql.c_str(), -1, &count_stmt, nullptr) == SQLITE_OK) {
        if (sqlite3_step(count_stmt) == SQLITE_ROW) {
            total_count = sqlite3_column_int64(count_stmt, 0);
        }
        sqlite3_finalize(count_stmt);
    }

    // Build main query
    std::string sql = R"(
        SELECT
            timestamp,
            event_type,
            description,
            file_path,
            inode,
            file_size,
            file_type
        FROM events
    )";
    sql += where_clause;
    sql += " ORDER BY timestamp DESC LIMIT " + std::to_string(limit) + " OFFSET " + std::to_string(offset);

    json events_data = execute_query(events, sql);

    // Add metadata
    json metadata;
    metadata["total_system_events"] = total_count;
    metadata["returned_events"] = events_data.is_array() ? events_data.size() : 0;
    metadata["limit"] = limit;
    metadata["offset"] = offset;
    metadata["has_more"] = (offset + limit) < total_count;
    metadata["start_time"] = start_time.empty() ? "all" : start_time;
    metadata["end_time"] = end_time.empty() ? "all" : end_time;

    result["metadata"] = metadata;
    result["system_events"] = events_data;

    sqlite3_close(events);
    return result;
}

json SQLiteHelper::get_system_event_summary(const std::string& events_db) {
    json result;
    sqlite3* events = open_database(events_db, result);
    if (!events) return result;

    // System event type distribution
    std::string event_type_sql = R"(
        SELECT
            event_type,
            COUNT(*) as count,
            MIN(timestamp) as first_seen,
            MAX(timestamp) as last_seen
        FROM events
        GROUP BY event_type
        ORDER BY count DESC
    )";

    // System event type distribution (all types)
    result["event_type_distribution"] = execute_query(events, event_type_sql);

    // These fields are not available in the current events table schema
    // Returning empty arrays for compatibility
    result["priority_distribution"] = json::array();
    result["severity_distribution"] = json::array();
    result["source_distribution"] = json::array();

    sqlite3_close(events);
    return result;
}
