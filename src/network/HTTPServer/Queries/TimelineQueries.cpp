#include "../SQLiteHelper.h"
#include <iostream>
#include <algorithm>
#include <ctime>
#include <regex>
#include <sstream>
#include <iomanip>

using json = nlohmann::json;

// ============================================================================
// TIMELINE ANALYSIS IMPLEMENTATION
// ============================================================================

json SQLiteHelper::get_timeline_details(const std::string& events_db,
                                       int64_t time_window,
                                       const std::string& event_type,
                                       const std::string& parent_dir,
                                       int limit, int offset,
                                       const std::string& search) {
    json result;
    sqlite3* events = open_database(events_db, result);
    if (!events) return result;

    // Build query to find all events in this cluster
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
        WHERE (timestamp / 60) = )" + std::to_string(time_window) + R"(
        AND event_type = ')" + event_type + "'";

    if (!parent_dir.empty()) {
        if (parent_dir == "/") {
            sql += " AND (file_path NOT LIKE '%/%' OR file_path LIKE '/%')";
        } else {
            sql += " AND file_path LIKE '" + parent_dir + "%'";
        }
    }

    if (!search.empty()) {
        sql += " AND file_path LIKE '%" + search + "%'";
    }

    sql += " ORDER BY timestamp ASC LIMIT " + std::to_string(limit) + " OFFSET " + std::to_string(offset);

    json events_data = execute_query(events, sql);
    result["events"] = events_data;

    sqlite3_close(events);
    return result;
}

json SQLiteHelper::get_comprehensive_timeline(const std::string& raw_db, const std::string& events_db,
                                               const std::string& start_time, const std::string& end_time,
                                               int limit, int offset, const std::string& event_type,
                                               bool cluster_events) {
    json result;
    sqlite3* raw = open_database(raw_db, result);
    sqlite3* events = open_database(events_db, result);

    if (!raw || !events) {
        if (raw) sqlite3_close(raw);
        if (events) sqlite3_close(events);
        return result;
    }

    // Ensure events table has AI columns (Self-healing)
    const char* ai_cols[] = {"llm_summary", "llm_description", "llm_keywords", "llm_analyzed_at", "llm_model_used", "llm_is_relevant"};
    for (const char* col : ai_cols) {
        std::string type = (std::string(col).find("_at") != std::string::npos || std::string(col).find("_is_") != std::string::npos) ? "INTEGER" : "TEXT";
        std::string alter_sql = "ALTER TABLE events ADD COLUMN " + std::string(col) + " " + type + ";";
        sqlite3_exec(events, alter_sql.c_str(), nullptr, nullptr, nullptr);
    }

    // Build WHERE clause for filters
    std::string where_clause = " WHERE 1=1";
    if (!start_time.empty()) {
        where_clause += " AND timestamp >= " + std::to_string(parse_timestamp(start_time));
    }
    if (!end_time.empty()) {
        where_clause += " AND timestamp <= " + std::to_string(parse_timestamp(end_time));
    }
    if (!event_type.empty()) {
        where_clause += " AND event_type = '" + event_type + "'";
    }

    // Get total count for pagination metadata
    // The count query MUST match the GROUP BY of the main query exactly,
    // otherwise totalPages will be wrong and pagination will break.
    // Main query groups by: parent_directory, (timestamp/60), event_type
    // So the count must count the same groups.
    //
    // parent_dir_expr computes the parent directory of file_path (including
    // the trailing slash). We use RTRIM(file_path, REPLACE(file_path,'/',''))
    // to strip the basename from the end: REPLACE removes every '/', giving the
    // set of "filename characters", and RTRIM strips trailing chars in that set
    // until it hits the last '/'. This correctly handles multi-segment paths
    // (e.g. /etc/ssh/sshd_config -> /etc/ssh/) unlike the previous INSTR-based
    // formula, which only found the FIRST slash and produced bogus directories
    // (e.g. /etc/ssh/sshd_config -> /etc/ssh/sshd_config), defeating clustering.
    const std::string parent_dir_expr =
        "(CASE WHEN file_path LIKE '%/%' THEN RTRIM(file_path, REPLACE(file_path, '/', '')) ELSE '' END)";

    std::string count_sql;
    if (cluster_events) {
        count_sql = "SELECT COUNT(*) FROM (SELECT 1 FROM events" + where_clause +
                    " GROUP BY " + parent_dir_expr + ", (timestamp / 60), event_type)";
    } else {
        count_sql = "SELECT COUNT(*) FROM events" + where_clause;
    }

    sqlite3_stmt* count_stmt;
    int64_t total_count = 0;
    if (sqlite3_prepare_v2(events, count_sql.c_str(), -1, &count_stmt, nullptr) == SQLITE_OK) {
        if (sqlite3_step(count_stmt) == SQLITE_ROW) {
            total_count = sqlite3_column_int64(count_stmt, 0);
        }
        sqlite3_finalize(count_stmt);
    }

    // Build main query
    std::string sql;
    if (cluster_events) {
        // Reuse the parent directory expression (see comment above).
        const std::string& parent_dir_sql = parent_dir_expr;

        sql = R"(
            SELECT
                MIN(timestamp) as timestamp,
                MAX(timestamp) as end_timestamp,
                event_type,
                COUNT(*) as cluster_count,
                file_path, -- Representative file path
                )" + parent_dir_sql + R"( as parent_directory,
                inode,
                description,
                SUM(COALESCE(file_size, 0)) as file_size,
                file_type,
                llm_summary,
                llm_description,
                llm_keywords,
                llm_is_relevant
            FROM events
        )";
        sql += where_clause;
        // Group by parent directory first, then time window and event type
        // This creates separate clusters for different directories
        sql += " GROUP BY parent_directory, (timestamp / 60), event_type";
    } else {
        sql = R"(
            SELECT
                timestamp,
                timestamp as end_timestamp,
                event_type,
                1 as cluster_count,
                file_path,
                inode,
                description,
                file_size,
                file_type
            FROM events
        )";
        sql += where_clause;
    }

    sql += " ORDER BY timestamp DESC LIMIT " + std::to_string(limit) + " OFFSET " + std::to_string(offset);

    json events_data = execute_query(events, sql);

    // Add metadata
    json metadata;
    metadata["total_events"] = total_count;
    metadata["returned_events"] = events_data.is_array() ? events_data.size() : 0;
    metadata["limit"] = limit;
    metadata["offset"] = offset;
    metadata["has_more"] = (offset + limit) < total_count;
    metadata["start_time"] = start_time.empty() ? "all" : start_time;
    metadata["end_time"] = end_time.empty() ? "all" : end_time;
    metadata["event_type_filter"] = event_type.empty() ? "all" : event_type;
    metadata["clustered"] = cluster_events;

    result["metadata"] = metadata;
    result["timeline"] = events_data;

    sqlite3_close(raw);
    sqlite3_close(events);
    return result;
}

json SQLiteHelper::get_timeline_distribution(const std::string& events_db) {
    json result;
    sqlite3* db = open_database(events_db, result);
    if (!db) return result;

    // Use SQLite date function to group by exact date string YYYY-MM-DD
    std::string sql = R"(
        SELECT
            date(timestamp, 'unixepoch', 'localtime') as event_date,
            event_type,
            COUNT(*) as count
        FROM events
        WHERE timestamp > 0
        GROUP BY event_date, event_type
        ORDER BY event_date ASC
    )";

    result["distribution"] = execute_query(db, sql);

    // Add overall counts if needed
    result["metadata"]["total_days"] = 0; // Will be properly computed client-side

    sqlite3_close(db);
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

json SQLiteHelper::get_timeline_by_type(const std::string& events_db, const std::string& event_type, int limit) {
    json result;
    sqlite3* db = open_database(events_db, result);
    if (!db) return result;

    std::string sql = "SELECT * FROM events WHERE event_type = '" + event_type + "' ORDER BY timestamp DESC LIMIT " + std::to_string(limit);
    result["events"] = execute_query(db, sql);
    result["event_type"] = event_type;
    result["limit"] = limit;

    sqlite3_close(db);
    return result;
}

json SQLiteHelper::get_timeline_by_time_range(const std::string& events_db, int64_t start_time, int64_t end_time, int limit) {
    json result;
    sqlite3* db = open_database(events_db, result);
    if (!db) return result;

    std::string sql = "SELECT * FROM events WHERE timestamp >= " + std::to_string(start_time) +
                     " AND timestamp <= " + std::to_string(end_time) +
                     " ORDER BY timestamp DESC LIMIT " + std::to_string(limit);
    result["events"] = execute_query(db, sql);
    result["time_range"] = {
        {"start", start_time},
        {"end", end_time}
    };
    result["limit"] = limit;

    sqlite3_close(db);
    return result;
}

json SQLiteHelper::get_timeline_by_file(const std::string& events_db, const std::string& file_path, int limit) {
    json result;
    sqlite3* db = open_database(events_db, result);
    if (!db) return result;

    std::string sql = "SELECT * FROM events WHERE file_path = '" + file_path + "' ORDER BY timestamp DESC LIMIT " + std::to_string(limit);
    result["events"] = execute_query(db, sql);
    result["file_path"] = file_path;
    result["limit"] = limit;

    sqlite3_close(db);
    return result;
}

json SQLiteHelper::get_timeline_full(const std::string& events_db, int limit, int offset) {
    json result;
    sqlite3* db = open_database(events_db, result);
    if (!db) return result;

    std::string sql = "SELECT * FROM events ORDER BY timestamp DESC LIMIT " + std::to_string(limit) + " OFFSET " + std::to_string(offset);
    result["events"] = execute_query(db, sql);
    result["limit"] = limit;
    result["offset"] = offset;
    result["total"] = get_total_event_count(db);

    sqlite3_close(db);
    return result;
}

json SQLiteHelper::get_event_statistics_by_period(const std::string& events_db, const std::string& period) {
    json result;
    sqlite3* db = open_database(events_db, result);
    if (!db) return result;

    std::string date_format;
    std::string period_label;

    if (period == "hour") {
        date_format = "%Y-%m-%d %H:00:00";
        period_label = "hourly";
    } else if (period == "day") {
        date_format = "%Y-%m-%d";
        period_label = "daily";
    } else if (period == "week") {
        date_format = "%Y-%W";
        period_label = "weekly";
    } else if (period == "month") {
        date_format = "%Y-%m";
        period_label = "monthly";
    } else {
        date_format = "%Y-%m-%d";
        period_label = "daily";
    }

    std::string sql = R"(
        SELECT
            strftime(')" + date_format + R"(', datetime(timestamp, 'unixepoch', 'localtime')) as time_period,
            event_type,
            COUNT(*) as event_count,
            COUNT(DISTINCT file_path) as unique_files
        FROM events
        GROUP BY time_period, event_type
        ORDER BY time_period DESC, event_type
    )";

    result["statistics"] = execute_query(db, sql);
    result["period"] = period_label;

    sqlite3_close(db);
    return result;
}
