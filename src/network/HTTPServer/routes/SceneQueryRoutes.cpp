#include "SceneQueryRoutes.h"
#include "RouteHelpers.h"
#include "../SQLiteHelper.h"
#include <sqlite3.h>

namespace forensics {

using json = nlohmann::json;

SceneQueryRoutes::SceneQueryRoutes(crow::App<>& app) {
    // GET /api/tasks/{id}/scene-stats
    CROW_ROUTE(app, "/api/tasks/<string>/scene-stats")
        .methods("GET"_method)
        ([this](const crow::request& req, const std::string& task_id) {
            return handle_get_scene_stats(req, task_id);
        });

    // GET /api/tasks/{id}/scene-artifacts?scene_type=android
    CROW_ROUTE(app, "/api/tasks/<string>/scene-artifacts")
        .methods("GET"_method)
        ([this](const crow::request& req, const std::string& task_id) {
            return handle_get_scene_artifacts(req, task_id);
        });
}

crow::response SceneQueryRoutes::handle_get_scene_stats(const crow::request& req, const std::string& task_id) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    res.set_header("Content-Type", "application/json");

    if (task_id.empty()) {
        json error = {{"error", "task_id is required"}};
        res.code = 400;
        res.write(error.dump());
        return res;
    }

    try {
        std::string files_db = RouteHelpers::get_database_path(task_id, "files");

        sqlite3* db = nullptr;
        if (sqlite3_open(files_db.c_str(), &db) != SQLITE_OK) {
            json error = {{"error", "Failed to open database: " + files_db}};
            res.code = 500;
            res.write(error.dump());
            if (db) sqlite3_close(db);
            return res;
        }

        // Query scene statistics grouped by scene_type
        // Uses the same logic as the scene_file_summary view
        const char* sql =
            "SELECT "
            "  scene_type, "
            "  COUNT(*) as total_files, "
            "  SUM(CASE WHEN scene_relevant = 1 THEN 1 ELSE 0 END) as relevant_files, "
            "  SUM(size) as total_size, "
            "  SUM(CASE WHEN llm_analyzed_at IS NOT NULL AND llm_analyzed_at > 0 THEN 1 ELSE 0 END) as llm_analyzed_files "
            "FROM files "
            "WHERE scene_type IS NOT NULL "
            "GROUP BY scene_type;";

        json scene_stats = json::array();
        sqlite3_stmt* stmt = nullptr;
        int rc = sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr);
        if (rc != SQLITE_OK) {
            json error = {{"error", std::string("SQL prepare failed: ") + sqlite3_errmsg(db)}};
            res.code = 500;
            res.write(error.dump());
            sqlite3_close(db);
            return res;
        }

        while (sqlite3_step(stmt) == SQLITE_ROW) {
            json stat;
            stat["scene_type"] = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
            stat["total_files"] = sqlite3_column_int(stmt, 1);
            stat["relevant_files"] = sqlite3_column_int(stmt, 2);
            stat["total_size"] = sqlite3_column_int64(stmt, 3);
            stat["llm_analyzed_files"] = sqlite3_column_int(stmt, 4);
            scene_stats.push_back(std::move(stat));
        }
        sqlite3_finalize(stmt);

        // Also query artifact counts per scene type
        json artifact_stats = json::array();
        const char* artifact_sql =
            "SELECT "
            "  'android' as scene_type, "
            "  COUNT(*) as artifact_count, "
            "  SUM(CASE WHEN llm_analyzed_at IS NOT NULL AND llm_analyzed_at > 0 THEN 1 ELSE 0 END) as analyzed_count "
            "FROM android_artifacts "
            "UNION ALL "
            "SELECT "
            "  'windows' as scene_type, "
            "  COUNT(*) as artifact_count, "
            "  SUM(CASE WHEN llm_analyzed_at IS NOT NULL AND llm_analyzed_at > 0 THEN 1 ELSE 0 END) as analyzed_count "
            "FROM windows_artifacts "
            "UNION ALL "
            "SELECT "
            "  'linux' as scene_type, "
            "  COUNT(*) as artifact_count, "
            "  SUM(CASE WHEN llm_analyzed_at IS NOT NULL AND llm_analyzed_at > 0 THEN 1 ELSE 0 END) as analyzed_count "
            "FROM linux_artifacts;";

        rc = sqlite3_prepare_v2(db, artifact_sql, -1, &stmt, nullptr);
        if (rc == SQLITE_OK) {
            while (sqlite3_step(stmt) == SQLITE_ROW) {
                json art_stat;
                art_stat["scene_type"] = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
                art_stat["artifact_count"] = sqlite3_column_int(stmt, 1);
                art_stat["analyzed_count"] = sqlite3_column_int(stmt, 2);
                artifact_stats.push_back(std::move(art_stat));
            }
            sqlite3_finalize(stmt);
        }
        // If artifact tables don't exist, just return empty artifact_stats

        sqlite3_close(db);

        json result;
        result["task_id"] = task_id;
        result["scene_stats"] = scene_stats;
        result["artifact_stats"] = artifact_stats;

        res.code = 200;
        res.write(result.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.write(error.dump());
    }
    return res;
}

crow::response SceneQueryRoutes::handle_get_scene_artifacts(const crow::request& req, const std::string& task_id) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    res.set_header("Content-Type", "application/json");

    if (task_id.empty()) {
        json error = {{"error", "task_id is required"}};
        res.code = 400;
        res.write(error.dump());
        return res;
    }

    auto params = crow::query_string(req.url_params);
    std::string scene_type = params.get("scene_type") ? params.get("scene_type") : "";
    int limit = params.get("limit") ? std::stoi(params.get("limit")) : 100;
    int offset = params.get("offset") ? std::stoi(params.get("offset")) : 0;

    if (scene_type.empty()) {
        json error = {{"error", "scene_type query parameter is required"}};
        res.code = 400;
        res.write(error.dump());
        return res;
    }

    // Validate scene_type to prevent SQL injection
    if (scene_type != "android" && scene_type != "windows" && scene_type != "linux") {
        json error = {{"error", "Invalid scene_type. Must be one of: android, windows, linux"}};
        res.code = 400;
        res.write(error.dump());
        return res;
    }

    try {
        std::string files_db = RouteHelpers::get_database_path(task_id, "files");

        sqlite3* db = nullptr;
        if (sqlite3_open(files_db.c_str(), &db) != SQLITE_OK) {
            json error = {{"error", "Failed to open database: " + files_db}};
            res.code = 500;
            res.write(error.dump());
            if (db) sqlite3_close(db);
            return res;
        }

        // Construct the artifact table name (validated above, safe to concatenate)
        std::string table_name = scene_type + "_artifacts";

        // Check if the table exists
        std::string check_sql = "SELECT name FROM sqlite_master WHERE type='table' AND name='" + table_name + "';";
        sqlite3_stmt* check_stmt = nullptr;
        bool table_exists = false;
        if (sqlite3_prepare_v2(db, check_sql.c_str(), -1, &check_stmt, nullptr) == SQLITE_OK) {
            if (sqlite3_step(check_stmt) == SQLITE_ROW) {
                table_exists = true;
            }
            sqlite3_finalize(check_stmt);
        }

        if (!table_exists) {
            sqlite3_close(db);
            json result;
            result["task_id"] = task_id;
            result["scene_type"] = scene_type;
            result["artifacts"] = json::array();
            result["total"] = 0;
            result["limit"] = limit;
            result["offset"] = offset;
            res.code = 200;
            res.write(result.dump());
            return res;
        }

        // Query artifacts with file info via join
        std::string sql =
            "SELECT a.id, a.file_id, a.artifact_type, a.artifact_data, a.extracted_at, "
            "       a.llm_summary, a.llm_description, a.llm_keywords, a.llm_analyzed_at, a.llm_model_used, "
            "       f.name as file_name, f.path as file_path, f.size as file_size "
            "FROM " + table_name + " a "
            "LEFT JOIN files f ON a.file_id = f.id "
            "ORDER BY a.id ASC "
            "LIMIT ? OFFSET ?;";

        json artifacts = json::array();
        sqlite3_stmt* stmt = nullptr;
        int rc = sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr);
        if (rc != SQLITE_OK) {
            json error = {{"error", std::string("SQL prepare failed: ") + sqlite3_errmsg(db)}};
            res.code = 500;
            res.write(error.dump());
            sqlite3_close(db);
            return res;
        }

        sqlite3_bind_int(stmt, 1, limit);
        sqlite3_bind_int(stmt, 2, offset);

        while (sqlite3_step(stmt) == SQLITE_ROW) {
            json artifact;
            artifact["id"] = sqlite3_column_int(stmt, 0);
            artifact["file_id"] = sqlite3_column_int(stmt, 1);
            artifact["artifact_type"] = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));

            const char* data = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3));
            artifact["artifact_data"] = data ? data : "";

            artifact["extracted_at"] = sqlite3_column_int64(stmt, 4);

            const char* llm_summary = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5));
            artifact["llm_summary"] = llm_summary ? llm_summary : "";

            const char* llm_desc = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6));
            artifact["llm_description"] = llm_desc ? llm_desc : "";

            const char* llm_kw = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7));
            artifact["llm_keywords"] = llm_kw ? llm_kw : "";

            artifact["llm_analyzed_at"] = sqlite3_column_int64(stmt, 8);

            const char* llm_model = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 9));
            artifact["llm_model_used"] = llm_model ? llm_model : "";

            const char* file_name = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 10));
            artifact["file_name"] = file_name ? file_name : "";

            const char* file_path = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 11));
            artifact["file_path"] = file_path ? file_path : "";

            artifact["file_size"] = sqlite3_column_int64(stmt, 12);

            artifacts.push_back(std::move(artifact));
        }
        sqlite3_finalize(stmt);

        // Get total count
        std::string count_sql = "SELECT COUNT(*) FROM " + table_name + ";";
        int total = 0;
        sqlite3_stmt* count_stmt = nullptr;
        if (sqlite3_prepare_v2(db, count_sql.c_str(), -1, &count_stmt, nullptr) == SQLITE_OK) {
            if (sqlite3_step(count_stmt) == SQLITE_ROW) {
                total = sqlite3_column_int(count_stmt, 0);
            }
            sqlite3_finalize(count_stmt);
        }

        sqlite3_close(db);

        json result;
        result["task_id"] = task_id;
        result["scene_type"] = scene_type;
        result["artifacts"] = artifacts;
        result["total"] = total;
        result["limit"] = limit;
        result["offset"] = offset;

        res.code = 200;
        res.write(result.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.write(error.dump());
    }
    return res;
}

} // namespace forensics
