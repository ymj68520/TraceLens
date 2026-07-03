#include "../SQLiteHelper.h"
#include <iostream>
#include <algorithm>
#include <ctime>
#include <regex>
#include <sstream>
#include <iomanip>

using json = nlohmann::json;

// ============================================================================
// FILE ANALYSIS IMPLEMENTATION
// ============================================================================

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

json SQLiteHelper::get_largest_files(const std::string& files_db, int limit) {
    json result;
    sqlite3* db = open_database(files_db, result);
    if (!db) return result;

    limit = clamp_limit(limit, 50);
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

    int hours_int = 24;
    try { hours_int = std::stoi(hours); } catch (...) { hours_int = 24; }
    if (hours_int <= 0 || hours_int > 24 * 3650) hours_int = 24;  // guard bad/huge input
    int64_t time_threshold = time(nullptr) - (static_cast<int64_t>(hours_int) * 3600);

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
