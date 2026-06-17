#include "EventClusterRoutes.h"
#include "RouteHelpers.h"
#include "../SQLiteHelper.h"
#include "../EventClusterAnalyzer.h"
#include "../../Swagger/Swagger.h"
#include <sqlite3.h>

namespace forensics {

using json = nlohmann::json;

EventClusterRoutes::EventClusterRoutes(crow::App<>& app) {
    CROW_ROUTE(app, "/api/forensics/timeline/clusters/analyze").methods("POST"_method, "OPTIONS"_method)([this](const crow::request& req) {
        if (req.method == "OPTIONS"_method) {
            crow::response res;
            RouteHelpers::add_cors_headers(res);
            res.code = 204;
            return res;
        }
        return handle_analyze_event_cluster(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/timeline/clusters/analyze", "POST",
        "Analyze event cluster",
        "Analyze a single event cluster with AI and generate description.",
        {"Forensics", "Timeline", "AI"},
        {},
        {{200, "Cluster analyzed successfully"}, {400, "Invalid request"}}
    );

    CROW_ROUTE(app, "/api/forensics/timeline/clusters/batch-analyze").methods("POST"_method, "OPTIONS"_method)([this](const crow::request& req) {
        if (req.method == "OPTIONS"_method) {
            crow::response res;
            RouteHelpers::add_cors_headers(res);
            res.code = 204;
            return res;
        }
        return handle_batch_analyze_event_clusters(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/timeline/clusters/batch-analyze", "POST",
        "Batch analyze event clusters",
        "Analyze multiple event clusters with AI.",
        {"Forensics", "Timeline", "AI"},
        {},
        {{200, "Batch analysis started"}, {400, "Invalid request"}}
    );

    CROW_ROUTE(app, "/api/forensics/timeline/clusters/reanalyze").methods("POST"_method, "OPTIONS"_method)([this](const crow::request& req) {
        if (req.method == "OPTIONS"_method) {
            crow::response res;
            RouteHelpers::add_cors_headers(res);
            res.code = 204;
            return res;
        }
        return handle_reanalyze_event_cluster(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/timeline/clusters/reanalyze", "POST",
        "Reanalyze event cluster",
        "Reanalyze an event cluster with AI.",
        {"Forensics", "Timeline", "AI"},
        {},
        {{200, "Cluster reanalyzed successfully"}, {400, "Invalid request"}}
    );

    CROW_ROUTE(app, "/api/forensics/timeline/clusters/analyzed").methods("GET"_method)([this](const crow::request& req) {
        return handle_get_analyzed_clusters(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/timeline/clusters/analyzed", "GET",
        "Get analyzed clusters",
        "Retrieve event clusters that have been analyzed by AI.",
        {"Forensics", "Timeline", "AI"},
        {{"task_id", "query", "Task ID", true}},
        {{200, "Analyzed clusters retrieved"}, {400, "Invalid request"}}
    );
}

crow::response EventClusterRoutes::handle_analyze_event_cluster(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    res.set_header("Content-Type", "application/json");

    json response = {
        {"success", false},
        {"message", "DEPRECATED: Please use Python API /api/llm/analyze-event-cluster (Port 8090) instead."}
    };
    res.code = 410;
    res.write(response.dump());
    return res;
}

crow::response EventClusterRoutes::handle_batch_analyze_event_clusters(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    res.set_header("Content-Type", "application/json");

    try {
        json body = json::parse(req.body);

        if (!body.contains("task_id") || body["task_id"].get<std::string>().empty()) {
            json error = {{"error", "task_id is required"}};
            res.code = 400;
            res.write(error.dump());
            return res;
        }
        if (!body.contains("clusters") || !body["clusters"].is_array()) {
            json error = {{"error", "clusters array is required"}};
            res.code = 400;
            res.write(error.dump());
            return res;
        }

        std::string task_id = body["task_id"].get<std::string>();
        auto clusters_json = body["clusters"];

        std::vector<std::tuple<int64_t, std::string, std::string>> clusters;
        for (const auto& cluster : clusters_json) {
            if (cluster.contains("time_window") && cluster.contains("event_type")) {
                int64_t time_window = cluster["time_window"].get<int64_t>();
                std::string event_type = cluster["event_type"].get<std::string>();
                std::string parent_directory = cluster.value("parent_directory", "");
                clusters.emplace_back(time_window, event_type, parent_directory);
            }
        }

        if (clusters.empty()) {
            json error = {{"error", "No valid clusters provided"}};
            res.code = 400;
            res.write(error.dump());
            return res;
        }

        std::string events_db = RouteHelpers::get_database_path(task_id, "events");

        EventClusterAnalyzer analyzer;
        int analyzed = analyzer.analyzeEventClusters(events_db, clusters);

        json response = {
            {"success", true},
            {"message", "Batch analysis completed"},
            {"analyzed_count", analyzed},
            {"total_count", clusters.size()}
        };
        res.write(response.dump());
    } catch (const json::exception& e) {
        json error = {{"error", std::string("Invalid JSON: ") + e.what()}};
        res.code = 400;
        res.write(error.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.write(error.dump());
    }

    return res;
}

crow::response EventClusterRoutes::handle_reanalyze_event_cluster(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    res.set_header("Content-Type", "application/json");

    try {
        json body = json::parse(req.body);

        if (!body.contains("task_id") || body["task_id"].get<std::string>().empty()) {
            json error = {{"error", "task_id is required"}};
            res.code = 400;
            res.write(error.dump());
            return res;
        }
        if (!body.contains("time_window")) {
            json error = {{"error", "time_window is required"}};
            res.code = 400;
            res.write(error.dump());
            return res;
        }
        if (!body.contains("event_type") || body["event_type"].get<std::string>().empty()) {
            json error = {{"error", "event_type is required"}};
            res.code = 400;
            res.write(error.dump());
            return res;
        }

        std::string task_id = body["task_id"].get<std::string>();
        int64_t time_window = body["time_window"].get<int64_t>();
        std::string event_type = body["event_type"].get<std::string>();
        std::string parent_directory = body.value("parent_directory", "");

        std::string events_db = RouteHelpers::get_database_path(task_id, "events");

        EventClusterAnalyzer analyzer;
        bool success = analyzer.analyzeEventCluster(events_db, time_window, event_type, parent_directory);

        if (success) {
            json response = {{"success", true}, {"message", "Event cluster reanalyzed successfully"}};
            res.write(response.dump());
        } else {
            json error = {{"error", "Failed to reanalyze event cluster"}};
            res.code = 500;
            res.write(error.dump());
        }
    } catch (const json::exception& e) {
        json error = {{"error", std::string("Invalid JSON: ") + e.what()}};
        res.code = 400;
        res.write(error.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.write(error.dump());
    }

    return res;
}

crow::response EventClusterRoutes::handle_get_analyzed_clusters(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    res.set_header("Content-Type", "application/json");

    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.write(error.dump());
        return res;
    }

    try {
        std::string events_db = RouteHelpers::get_database_path(task_id, "events");

        sqlite3* db = nullptr;
        int rc = sqlite3_open(events_db.c_str(), &db);
        if (rc != SQLITE_OK) {
            json error = {{"error", "Failed to open database"}};
            res.code = 500;
            res.write(error.dump());
            return res;
        }

        std::string sql = R"(
            SELECT
                (timestamp / 60) as time_window,
                event_type,
                CASE WHEN file_path LIKE '%/%' THEN RTRIM(file_path, REPLACE(file_path, '/', '')) ELSE '' END as parent_directory,
                MIN(timestamp) as timestamp,
                MAX(timestamp) as end_timestamp,
                COUNT(*) as cluster_count,
                file_path,
                SUM(COALESCE(file_size, 0)) as file_size,
                MAX(llm_summary) as llm_summary,
                MAX(llm_description) as llm_description,
                MAX(llm_keywords) as llm_keywords,
                MAX(llm_analyzed_at) as llm_analyzed_at,
                MAX(llm_model_used) as llm_model_used,
                MAX(llm_is_relevant) as llm_is_relevant
            FROM events
            WHERE llm_analyzed_at IS NOT NULL
            GROUP BY time_window, event_type, parent_directory
            ORDER BY llm_analyzed_at DESC
        )";

        sqlite3_stmt* stmt = nullptr;
        rc = sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr);
        if (rc != SQLITE_OK) {
            sqlite3_close(db);
            json error = {{"error", "Failed to prepare query"}};
            res.code = 500;
            res.write(error.dump());
            return res;
        }

        json clusters = json::array();
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            json cluster;
            cluster["time_window"] = sqlite3_column_int64(stmt, 0);
            cluster["event_type"] = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
            cluster["parent_directory"] = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
            // Frontend (CaseIntelligence) reads these fields off each cluster:
            //   timestamp     -> displayed via new Date(timestamp*1000)
            //   cluster_count -> "N 个事件" badge
            //   file_path     -> representative file
            // Expose them so the evidence list renders correctly.
            cluster["timestamp"] = sqlite3_column_int64(stmt, 3);
            cluster["end_timestamp"] = sqlite3_column_int64(stmt, 4);
            cluster["cluster_count"] = sqlite3_column_int64(stmt, 5);
            const char* fp = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6));
            cluster["file_path"] = fp ? fp : "";
            cluster["file_size"] = sqlite3_column_int64(stmt, 7);
            cluster["llm_summary"] = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 8));
            cluster["llm_description"] = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 9));
            cluster["llm_keywords"] = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 10));
            cluster["llm_analyzed_at"] = sqlite3_column_int64(stmt, 11);
            cluster["llm_model_used"] = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 12));
            cluster["llm_is_relevant"] = sqlite3_column_int(stmt, 13);
            clusters.push_back(cluster);
        }

        sqlite3_finalize(stmt);
        sqlite3_close(db);

        json response = {{"clusters", clusters}, {"total_count", clusters.size()}};
        res.write(response.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.write(error.dump());
    }

    return res;
}

} // namespace forensics
