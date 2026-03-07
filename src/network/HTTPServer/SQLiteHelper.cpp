#include "SQLiteHelper.h"
#include <iostream>
#include <algorithm>
#include <ctime>
#include <regex>
#include <sstream>
#include <iomanip>

using json = nlohmann::json;

// Original function implementation
json SQLiteHelper::get_file_summary(const std::string& db_path) {
    sqlite3* db;
    json result;

    db = open_database(db_path, result);
    if (!db) {
        return result;
    }

    const char* sql = "SELECT * FROM file_summary";
    sqlite3_stmt* stmt;

    if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) == SQLITE_OK) {
        std::vector<json> rows;
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            json row;
            row["category"] = std::string(reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0)));
            row["file_count"] = sqlite3_column_int(stmt, 1);
            row["total_size"] = (long long)sqlite3_column_int64(stmt, 2);
            rows.push_back(std::move(row));
        }
        result["summary"] = std::move(rows);
    } else {
        result["error"] = "Query failed: " + std::string(sqlite3_errmsg(db));
    }

    sqlite3_finalize(stmt);
    sqlite3_close(db);
    return result;
}

// Timeline Analysis Implementation
json SQLiteHelper::get_comprehensive_timeline(const std::string& raw_db, const std::string& events_db,
                                               const std::string& start_time, const std::string& end_time) {
    json result;
    sqlite3* raw = open_database(raw_db, result);
    sqlite3* events = open_database(events_db, result);

    if (!raw || !events) {
        if (raw) sqlite3_close(raw);
        if (events) sqlite3_close(events);
        return result;
    }

    // Build SQL with optional time filters
    std::string sql = R"(
        SELECT
            timestamp,
            event_type,
            file_path,
            inode,
            description,
            file_size,
            file_type
        FROM events
        WHERE 1=1
    )";

    if (!start_time.empty()) {
        sql += " AND timestamp >= " + std::to_string(parse_timestamp(start_time));
    }
    if (!end_time.empty()) {
        sql += " AND timestamp <= " + std::to_string(parse_timestamp(end_time));
    }

    sql += " ORDER BY timestamp DESC LIMIT 1000";

    json events_data = execute_query(events, sql);

    // Add metadata
    json metadata;
    metadata["total_events"] = events_data.is_array() ? events_data.size() : 0;
    metadata["start_time"] = start_time.empty() ? "all" : start_time;
    metadata["end_time"] = end_time.empty() ? "all" : end_time;

    result["metadata"] = metadata;
    result["timeline"] = events_data;

    sqlite3_close(raw);
    sqlite3_close(events);
    return result;
}

json SQLiteHelper::get_file_activity_timeline(const std::string& raw_db, const std::string& events_db,
                                               const std::string& file_path, int64_t inode) {
    json result;
    sqlite3* raw = open_database(raw_db, result);
    sqlite3* events = open_database(events_db, result);

    if (!raw || !events) {
        if (raw) sqlite3_close(raw);
        if (events) sqlite3_close(events);
        return result;
    }

    std::string sql = R"(
        SELECT
            timestamp,
            event_type,
            file_path,
            inode,
            description,
            file_size,
            file_type
        FROM events
        WHERE 1=1
    )";

    if (!file_path.empty()) {
        sql += " AND file_path LIKE '%" + file_path + "%'";
    }
    if (inode != -1) {
        sql += " AND inode = " + std::to_string(inode);
    }

    sql += " ORDER BY timestamp DESC";

    json activities = execute_query(events, sql);

    // Get file metadata
    json file_metadata;
    std::string file_sql = "SELECT * FROM files WHERE ";
    if (inode != -1) {
        file_sql += "inode = " + std::to_string(inode);
    } else if (!file_path.empty()) {
        file_sql += "path LIKE '%" + file_path + "%' LIMIT 1";
    } else {
        file_sql += "1=0";
    }

    json file_info = execute_query(raw, file_sql);
    if (file_info.is_array() && !file_info.empty()) {
        file_metadata = file_info[0];
    }

    result["file_metadata"] = file_metadata;
    result["activities"] = activities;
    result["total_activities"] = activities.is_array() ? activities.size() : 0;

    sqlite3_close(raw);
    sqlite3_close(events);
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

// File Analysis Implementation
json SQLiteHelper::get_largest_files(const std::string& files_db, int limit) {
    json result;
    sqlite3* db = open_database(files_db, result);
    if (!db) return result;

    std::string sql = "SELECT * FROM files WHERE size > 0 ORDER BY size DESC LIMIT " + std::to_string(limit);
    result["largest_files"] = execute_query(db, sql);
    result["limit"] = limit;

    sqlite3_close(db);
    return result;
}

json SQLiteHelper::get_recent_files(const std::string& files_db, const std::string& hours) {
    json result;
    sqlite3* db = open_database(files_db, result);
    if (!db) return result;

    int hours_int = std::stoi(hours);
    int64_t time_threshold = time(nullptr) - (hours_int * 3600);

    std::string sql = "SELECT * FROM files WHERE mtime > " + std::to_string(time_threshold) +
                     " OR ctime > " + std::to_string(time_threshold) +
                     " ORDER BY mtime DESC, ctime DESC LIMIT 200";

    result["recent_files"] = execute_query(db, sql);
    result["time_filter_hours"] = hours;

    sqlite3_close(db);
    return result;
}

json SQLiteHelper::get_suspicious_files(const std::string& raw_db, const std::string& files_db) {
    json result;
    sqlite3* raw = open_database(raw_db, result);
    sqlite3* files = open_database(files_db, result);

    if (!raw || !files) {
        if (raw) sqlite3_close(raw);
        if (files) sqlite3_close(files);
        return result;
    }

    std::vector<json> suspicious_categories;

    // Hidden files
    std::string hidden_sql = "SELECT * FROM files WHERE name LIKE '.%' AND is_deleted = 0 LIMIT 100";
    json hidden_files = execute_query(files, hidden_sql);
    if (hidden_files.is_array() && !hidden_files.empty()) {
        suspicious_categories.push_back({
            {"category", "hidden_files"},
            {"files", hidden_files}
        });
    }

    // Executable files in user directories
    std::string exec_sql = R"(
        SELECT * FROM files
        WHERE (category = 'executable' OR extension IN ('exe', 'bat', 'cmd', 'scr', 'vbs', 'js'))
          AND (path LIKE '/home/%' OR path LIKE '/Users/%' OR path LIKE 'C:\\Users\\%')
          AND is_deleted = 0
        ORDER BY size DESC
        LIMIT 50
    )";

    json exec_files = execute_query(files, exec_sql);
    if (exec_files.is_array() && !exec_files.empty()) {
        suspicious_categories.push_back({
            {"category", "executables_in_user_dirs"},
            {"files", exec_files}
        });
    }

    // Recently deleted files
    std::string deleted_sql = "SELECT * FROM files WHERE is_deleted = 1 ORDER BY ctime DESC LIMIT 100";
    json deleted_files = execute_query(files, deleted_sql);
    if (deleted_files.is_array() && !deleted_files.empty()) {
        suspicious_categories.push_back({
            {"category", "recently_deleted"},
            {"files", deleted_files}
        });
    }

    result["suspicious_files"] = suspicious_categories;

    sqlite3_close(raw);
    sqlite3_close(files);
    return result;
}

json SQLiteHelper::get_duplicate_files(const std::string& files_db) {
    json result;
    sqlite3* db = open_database(files_db, result);
    if (!db) return result;

    std::string sql = R"(
        SELECT md5, COUNT(*) as duplicate_count, GROUP_CONCAT(path, ' | ') as file_paths,
               SUM(size) as total_size, size as individual_size
        FROM files
        WHERE md5 != '' AND md5 IS NOT NULL
        GROUP BY md5
        HAVING duplicate_count > 1
        ORDER BY duplicate_count DESC, total_size DESC
        LIMIT 100
    )";

    result["duplicates"] = execute_query(db, sql);

    sqlite3_close(db);
    return result;
}

json SQLiteHelper::get_extensions_analysis(const std::string& files_db) {
    json result;
    sqlite3* db = open_database(files_db, result);
    if (!db) return result;

    // Extension distribution
    std::string ext_sql = R"(
        SELECT
            COALESCE(extension, 'no_extension') as extension,
            COUNT(*) as file_count,
            SUM(size) as total_size,
            AVG(size) as avg_size,
            MAX(size) as max_size
        FROM files
        GROUP BY extension
        ORDER BY file_count DESC
    )";

    json extensions = execute_query(db, ext_sql);

    // Category distribution
    std::string cat_sql = R"(
        SELECT
            category,
            COUNT(*) as file_count,
            SUM(size) as total_size,
            AVG(size) as avg_size
        FROM files
        GROUP BY category
        ORDER BY file_count DESC
    )";

    json categories = execute_query(db, cat_sql);

    result["extension_analysis"] = extensions;
    result["category_analysis"] = categories;

    sqlite3_close(db);
    return result;
}

json SQLiteHelper::get_llm_results(const std::string& descriptions_db) {
    json result;
    sqlite3* db = open_database(descriptions_db, result);
    if (!db) return result;

    // Use COALESCE to handle older databases that might have NULL in is_relevant (default to 1)
    // Also use a subquery check or just select it if the migration logic ensures it exists
    // Given the Python service migration, it should exist.
    result["descriptions"] = execute_query(db, 
        "SELECT file_path, description, summary, keywords, "
        "COALESCE(is_relevant, 1) as is_relevant, created_at "
        "FROM file_descriptions ORDER BY created_at DESC");
    
    // Summary stats
    json stats = execute_query(db, "SELECT COUNT(*) as total_analyzed FROM file_descriptions");
    if (stats.is_array() && !stats.empty()) {
        result["stats"] = stats[0];
    }

    sqlite3_close(db);
    return result;
}

// Android Forensics Implementation
json SQLiteHelper::get_android_communication_summary(const std::string& android_db) {
    json result;
    sqlite3* db = open_database(android_db, result);
    if (!db) return result;

    // SMS summary
    if (table_exists(db, "sms_messages")) {
        result["sms_summary"] = execute_query(db, "SELECT COUNT(*) as total_sms FROM sms_messages");
        result["sms_by_type"] = execute_query(db, "SELECT type, COUNT(*) as count FROM sms_messages GROUP BY type");
    } else {
        result["sms_summary"] = json::array();
        result["sms_by_type"] = json::array();
    }

    // WhatsApp summary
    if (table_exists(db, "whatsapp_messages")) {
        result["whatsapp_summary"] = execute_query(db, "SELECT COUNT(*) as total_messages FROM whatsapp_messages");
        result["whatsapp_by_type"] = execute_query(db, R"(
            SELECT CASE
                WHEN message_from_me = 1 THEN 'sent'
                ELSE 'received'
            END as direction, COUNT(*) as count
            FROM whatsapp_messages
            GROUP BY message_from_me
        )");
    } else {
        result["whatsapp_summary"] = json::array();
        result["whatsapp_by_type"] = json::array();
    }

    // Contacts
    if (table_exists(db, "contacts")) {
        result["contacts_summary"] = execute_query(db, "SELECT COUNT(*) as total_contacts FROM contacts");
    } else {
        result["contacts_summary"] = json::array();
    }

    // Call logs
    if (table_exists(db, "call_logs")) {
        result["call_summary"] = execute_query(db, "SELECT COUNT(*) as total_calls FROM call_logs");
        result["call_by_type"] = execute_query(db, "SELECT type, COUNT(*) as count FROM call_logs GROUP BY type");
    } else {
        result["call_summary"] = json::array();
        result["call_by_type"] = json::array();
    }

    sqlite3_close(db);
    return result;
}

json SQLiteHelper::get_android_app_usage(const std::string& android_db) {
    json result;
    sqlite3* db = open_database(android_db, result);
    if (!db) return result;

    // Installed apps
    if (table_exists(db, "installed_packages")) {
        result["installed_apps"] = execute_query(db, R"(
            SELECT package_name, app_name, version_code, version_name,
                   first_install_time, last_update_time
            FROM installed_packages
            ORDER BY last_update_time DESC
        )");
    } else {
        result["installed_apps"] = json::array();
    }

    // Usage stats
    if (table_exists(db, "usage_stats")) {
        result["usage_statistics"] = execute_query(db, R"(
            SELECT package_name, total_time_in_foreground, last_time_used,
                   total_time_in_foreground / 1000 as seconds_used
            FROM usage_stats
            WHERE total_time_in_foreground > 0
            ORDER BY total_time_in_foreground DESC
            LIMIT 100
        )");
    } else {
        result["usage_statistics"] = json::array();
    }

    // System apps
    if (table_exists(db, "system_apps")) {
        result["system_apps_count"] = execute_query(db, "SELECT COUNT(*) as system_app_count FROM system_apps");
    } else {
        result["system_apps_count"] = json::array();
    }

    // App database files
    if (table_exists(db, "app_database_files")) {
        result["app_database_files"] = execute_query(db, R"(
            SELECT package_name, file_name, file_path, file_size
            FROM app_database_files
            ORDER BY package_name, file_name
        )");
    } else {
        result["app_database_files"] = json::array();
    }

    sqlite3_close(db);
    return result;
}

json SQLiteHelper::get_android_device_info(const std::string& android_db) {
    json result;
    sqlite3* db = open_database(android_db, result);
    if (!db) return result;

    // Build properties
    if (table_exists(db, "system_build_properties")) {
        result["build_properties"] = execute_query(db, "SELECT property_name, property_value FROM system_build_properties");
    } else {
        result["build_properties"] = json::array();
    }

    // WiFi networks
    if (table_exists(db, "wifi_networks")) {
        result["wifi_networks"] = execute_query(db, R"(
            SELECT ssid, bssid, frequency, level, capabilities
            FROM wifi_networks
            ORDER BY level DESC
        )");
    } else {
        result["wifi_networks"] = json::array();
    }

    // Chrome history
    if (table_exists(db, "chrome_history")) {
        result["chrome_history"] = execute_query(db, R"(
            SELECT url, title, visit_count, last_visit_time
            FROM chrome_history
            ORDER BY visit_count DESC
            LIMIT 50
        )");
    } else {
        result["chrome_history"] = json::array();
    }

    sqlite3_close(db);
    return result;
}

json SQLiteHelper::get_android_media_analysis(const std::string& android_db) {
    json result;
    sqlite3* db = open_database(android_db, result);
    if (!db) return result;

    // Framework media files
    if (table_exists(db, "framework_files")) {
        json media_files = execute_query(db, R"(
            SELECT file_path, file_size, mime_type
            FROM framework_files
            WHERE mime_type LIKE 'image/%' OR mime_type LIKE 'video/%' OR mime_type LIKE 'audio/%'
            ORDER BY file_size DESC
            LIMIT 100
        )");

        // Media files by type
        json media_by_type = execute_query(db, R"(
            SELECT
                CASE
                    WHEN mime_type LIKE 'image/%' THEN 'images'
                    WHEN mime_type LIKE 'video/%' THEN 'videos'
                    WHEN mime_type LIKE 'audio/%' THEN 'audio'
                    ELSE 'other'
                END as media_type,
                COUNT(*) as file_count,
                SUM(file_size) as total_size
            FROM framework_files
            WHERE mime_type IS NOT NULL
            GROUP BY media_type
        )");

        result["media_files"] = media_files;
        result["media_by_type"] = media_by_type;
    } else {
        result["media_files"] = json::array();
        result["media_by_type"] = json::array();
    }

    sqlite3_close(db);
    return result;
}

// Statistical Analysis Implementation
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

// Helper methods implementation
sqlite3* SQLiteHelper::open_database(const std::string& db_path, json& error_result) {
    sqlite3* db;
    if (sqlite3_open(db_path.c_str(), &db) != SQLITE_OK) {
        error_result["error"] = "Cannot open database: " + db_path;
        if (db) sqlite3_close(db);
        return nullptr;
    }
    return db;
}

json SQLiteHelper::execute_query(sqlite3* db, const std::string& sql) {
    json result = json::array();
    sqlite3_stmt* stmt;

    if (sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr) == SQLITE_OK) {
        int column_count = sqlite3_column_count(stmt);

        while (sqlite3_step(stmt) == SQLITE_ROW) {
            json row = json::object();

            for (int i = 0; i < column_count; i++) {
                const char* column_name = sqlite3_column_name(stmt, i);

                switch (sqlite3_column_type(stmt, i)) {
                    case SQLITE_INTEGER:
                        row[column_name] = sqlite3_column_int64(stmt, i);
                        break;
                    case SQLITE_FLOAT:
                        row[column_name] = sqlite3_column_double(stmt, i);
                        break;
                    case SQLITE_TEXT:
                        row[column_name] = std::string(reinterpret_cast<const char*>(sqlite3_column_text(stmt, i)));
                        break;
                    case SQLITE_BLOB:
                        row[column_name] = "<BLOB_DATA>";
                        break;
                    case SQLITE_NULL:
                        row[column_name] = nullptr;
                        break;
                }
            }

            result.push_back(row);
        }
    } else {
        std::cerr << "SQL error: " << sqlite3_errmsg(db) << std::endl;
    }

    sqlite3_finalize(stmt);
    return result;
}

bool SQLiteHelper::table_exists(sqlite3* db, const std::string& table_name) {
    std::string sql = "SELECT name FROM sqlite_master WHERE type='table' AND name='" + table_name + "';";
    sqlite3_stmt* stmt;
    bool exists = false;
    
    if (sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr) == SQLITE_OK) {
        if (sqlite3_step(stmt) == SQLITE_ROW) {
            exists = true;
        }
        sqlite3_finalize(stmt);
    }
    return exists;
}

std::string SQLiteHelper::format_timestamp(int64_t timestamp) {
    if (timestamp <= 0) return "Unknown";

    std::time_t time = timestamp;
    std::stringstream ss;
    ss << std::put_time(std::gmtime(&time), "%Y-%m-%d %H:%M:%S UTC");
    return ss.str();
}

int64_t SQLiteHelper::parse_timestamp(const std::string& time_str) {
    if (time_str.empty()) return 0;

    // Simple Unix timestamp parsing
    try {
        return std::stoll(time_str);
    } catch (...) {
        return 0;
    }
}

bool SQLiteHelper::is_suspicious_extension(const std::string& ext) {
    std::string lower_ext = ext;
    std::transform(lower_ext.begin(), lower_ext.end(), lower_ext.begin(), ::tolower);

    std::vector<std::string> suspicious = {
        ".bat", ".cmd", ".scr", ".vbs", ".js", ".jar", ".exe", ".com", ".pif"
    };

    return std::find(suspicious.begin(), suspicious.end(), lower_ext) != suspicious.end();
}

bool SQLiteHelper::is_suspicious_path(const std::string& path) {
    std::string lower_path = path;
    std::transform(lower_path.begin(), lower_path.end(), lower_path.begin(), ::tolower);

    std::vector<std::string> suspicious_patterns = {
        "/temp/", "/tmp/", "recycle", "$recycle", "system32"
    };

    for (const auto& pattern : suspicious_patterns) {
        if (lower_path.find(pattern) != std::string::npos) {
            return true;
        }
    }

    return false;
}