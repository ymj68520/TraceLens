#include "ForensicsRoutes.h"
#include "../../Swagger/Swagger.h"
#include "DatabaseManager/FileExtractor/FileExtractor.h"
#include "TOONExporter/TOONExporter.h"
#include "../../core/PathManager/PathManager.h"
#include "../EventClusterAnalyzer.h"
#include <filesystem>
#include <random>
#include <sstream>
#include <iomanip>

namespace forensics {

using json = nlohmann::json;

// Generate unique job ID
static std::string generate_job_id() {
    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_int_distribution<> dis(0, 15);
    const char* hex = "0123456789abcdef";
    std::stringstream ss;
    ss << "ext-";
    for (int i = 0; i < 8; i++) {
        ss << hex[dis(gen)];
    }
    return ss.str();
}

ForensicsRoutes::ForensicsRoutes(crow::App<>& app) : task_manager_(TaskManager::instance()) {
    // Timeline Analysis Routes
    CROW_ROUTE(app, "/api/forensics/timeline/comprehensive").methods("GET"_method)([this](const crow::request& req) {
        return handle_timeline_comprehensive(req);
    });

    CROW_ROUTE(app, "/api/forensics/timeline/details").methods("GET"_method)([this](const crow::request& req) {
        return handle_timeline_details(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/timeline/comprehensive", "GET",
        "Get comprehensive timeline",
        "Retrieve a comprehensive timeline of events combined from multiple sources.",
        {"Forensics", "Timeline"},
        {{"task_id", "query", "Task ID", true}, {"start_time", "query", "Start timestamp (ISO)", false}, {"end_time", "query", "End timestamp (ISO)", false}},
        {{200, "Timeline data retrieved"}}
    );

    CROW_ROUTE(app, "/api/forensics/timeline/distribution").methods("GET"_method)([this](const crow::request& req) {
        return handle_timeline_distribution(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/timeline/distribution", "GET",
        "Get timeline distribution",
        "Retrieve a chronological distribution of timeline events.",
        {"Forensics", "Timeline"},
        {{"task_id", "query", "Task ID", true}},
        {{200, "Timeline distribution retrieved"}}
    );

    CROW_ROUTE(app, "/api/forensics/timeline/file-activity").methods("GET"_method)([this](const crow::request& req) {
        return handle_timeline_file_activity(req);
    });

    CROW_ROUTE(app, "/api/forensics/timeline/suspicious-patterns").methods("GET"_method)([this](const crow::request& req) {
        return handle_timeline_suspicious_patterns(req);
    });

    CROW_ROUTE(app, "/api/forensics/timeline/user-activity").methods("GET"_method)([this](const crow::request& req) {
        return handle_timeline_user_activity(req);
    });

    // System Event Routes
    CROW_ROUTE(app, "/api/forensics/system/events").methods("GET"_method)([this](const crow::request& req) {
        return handle_system_events(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/system/events", "GET",
        "Get system events",
        "Retrieve system events with filtering and pagination.",
        {"Forensics", "System Events"},
        {{"task_id", "query", "Task ID", true}, {"start_time", "query", "Start timestamp (ISO)", false}, {"end_time", "query", "End timestamp (ISO)", false}, {"limit", "query", "Number of events to return", false, "integer"}, {"offset", "query", "Number of events to skip", false, "integer"}},
        {{200, "System events retrieved"}}
    );

    CROW_ROUTE(app, "/api/forensics/system/summary").methods("GET"_method)([this](const crow::request& req) {
        return handle_system_event_summary(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/system/summary", "GET",
        "Get system event summary",
        "Retrieve summary statistics for system events.",
        {"Forensics", "System Events"},
        {{"task_id", "query", "Task ID", true}},
        {{200, "System event summary retrieved"}}
    );

    // Enhanced Timeline Analysis Routes
    CROW_ROUTE(app, "/api/forensics/timeline/by-type").methods("GET"_method)([this](const crow::request& req) {
        return handle_timeline_by_type(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/timeline/by-type", "GET",
        "Get timeline by event type",
        "Retrieve timeline events filtered by event type (CREATED, MODIFIED, ACCESSED, CHANGED, DELETED).",
        {"Forensics", "Timeline"},
        {{"task_id", "query", "Task ID", true}, {"event_type", "query", "Event type filter", false}, {"limit", "query", "Number of events to return", false, "integer"}},
        {{200, "Timeline events by type retrieved"}}
    );

    CROW_ROUTE(app, "/api/forensics/timeline/by-time-range").methods("GET"_method)([this](const crow::request& req) {
        return handle_timeline_by_time_range(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/timeline/by-time-range", "GET",
        "Get timeline by time range",
        "Retrieve timeline events within a specific time range.",
        {"Forensics", "Timeline"},
        {{"task_id", "query", "Task ID", true}, {"start_time", "query", "Start timestamp", false}, {"end_time", "query", "End timestamp", false}, {"limit", "query", "Number of events to return", false, "integer"}},
        {{200, "Timeline events in time range retrieved"}}
    );

    CROW_ROUTE(app, "/api/forensics/timeline/by-file").methods("GET"_method)([this](const crow::request& req) {
        return handle_timeline_by_file(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/timeline/by-file", "GET",
        "Get timeline by file",
        "Retrieve timeline events for a specific file.",
        {"Forensics", "Timeline"},
        {{"task_id", "query", "Task ID", true}, {"file_path", "query", "File path to filter", false}, {"limit", "query", "Number of events to return", false, "integer"}},
        {{200, "Timeline events for file retrieved"}}
    );

    CROW_ROUTE(app, "/api/forensics/timeline/full").methods("GET"_method)([this](const crow::request& req) {
        return handle_timeline_full(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/timeline/full", "GET",
        "Get full timeline",
        "Retrieve full timeline with pagination support.",
        {"Forensics", "Timeline"},
        {{"task_id", "query", "Task ID", true}, {"limit", "query", "Number of events to return", false, "integer"}, {"offset", "query", "Number of events to skip", false, "integer"}},
        {{200, "Full timeline retrieved"}}
    );

    CROW_ROUTE(app, "/api/forensics/timeline/statistics-by-period").methods("GET"_method)([this](const crow::request& req) {
        return handle_event_statistics_by_period(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/timeline/statistics-by-period", "GET",
        "Get event statistics by period",
        "Retrieve event statistics grouped by time period (hour, day, week, month).",
        {"Forensics", "Timeline"},
        {{"task_id", "query", "Task ID", true}, {"period", "query", "Time period (hour/day/week/month)", false}},
        {{200, "Event statistics by period retrieved"}}
    );

    // File Analysis Routes
    CROW_ROUTE(app, "/api/forensics/files/largest").methods("GET"_method)([this](const crow::request& req) {
        return handle_files_largest(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/files/largest", "GET",
        "Get largest files",
        "Retrieve a list of the largest files found in the image.",
        {"Forensics", "Files"},
        {{"task_id", "query", "Task ID", true}, {"limit", "query", "Number of files to return", false, "integer"}},
        {{200, "List of largest files"}}
    );

    CROW_ROUTE(app, "/api/forensics/files/recent").methods("GET"_method)([this](const crow::request& req) {
        return handle_files_recent(req);
    });

    CROW_ROUTE(app, "/api/forensics/files/suspicious").methods("GET"_method)([this](const crow::request& req) {
        return handle_files_suspicious(req);
    });

    CROW_ROUTE(app, "/api/forensics/files/duplicates").methods("GET"_method)([this](const crow::request& req) {
        return handle_files_duplicates(req);
    });

    CROW_ROUTE(app, "/api/forensics/files/extensions-analysis").methods("GET"_method)([this](const crow::request& req) {
        return handle_files_extensions_analysis(req);
    });

    // Android Forensics Routes
    CROW_ROUTE(app, "/api/forensics/android/communication-summary").methods("GET"_method)([this](const crow::request& req) {
        return handle_android_communication_summary(req);
    });

    CROW_ROUTE(app, "/api/forensics/android/app-usage").methods("GET"_method)([this](const crow::request& req) {
        return handle_android_app_usage(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/android/app-usage", "GET",
        "Get Android app usage",
        "Retrieve usage statistics for installed Android applications.",
        {"Forensics", "Android"},
        {{"task_id", "query", "Task ID", true}},
        {{200, "App usage statistics"}}
    );

    CROW_ROUTE(app, "/api/forensics/android/device-info").methods("GET"_method)([this](const crow::request& req) {
        return handle_android_device_info(req);
    });

    CROW_ROUTE(app, "/api/forensics/android/media-analysis").methods("GET"_method)([this](const crow::request& req) {
        return handle_android_media_analysis(req);
    });

    // Statistics Routes
    CROW_ROUTE(app, "/api/forensics/statistics/overview").methods("GET"_method)([this](const crow::request& req) {
        return handle_statistics_overview(req);
    });

    CROW_ROUTE(app, "/api/forensics/statistics/file-distribution").methods("GET"_method)([this](const crow::request& req) {
        return handle_statistics_file_distribution(req);
    });

    CROW_ROUTE(app, "/api/forensics/statistics/activity-patterns").methods("GET"_method)([this](const crow::request& req) {
        return handle_statistics_activity_patterns(req);
    });

    CROW_ROUTE(app, "/api/forensics/statistics/deleted-files-analysis").methods("GET"_method)([this](const crow::request& req) {
        return handle_statistics_deleted_files_analysis(req);
    });

    // File Extraction Routes
    CROW_ROUTE(app, "/api/forensics/extract").methods("POST"_method, "OPTIONS"_method)([this](const crow::request& req) {
        if (req.method == "OPTIONS"_method) {
            crow::response res;
            add_cors_headers(res);
            res.code = 204;
            return res;
        }
        return handle_extract_files(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/extract", "POST",
        "Extract files",
        "Start a background job to extract files from the image.",
        {"Forensics", "Extraction"},
        {},
        {{202, "Extraction job started"}, {400, "Invalid request"}}
    );

    CROW_ROUTE(app, "/api/forensics/extract/<string>").methods("GET"_method)([this](const crow::request& req, const std::string& job_id) {
        // Create a modified request to pass job_id
        crow::request mod_req = req;
        // We'll parse job_id from URL in the handler
        return handle_extraction_status(req);
    });

    CROW_ROUTE(app, "/api/forensics/extract/status").methods("GET"_method)([this](const crow::request& req) {
        return handle_extraction_status(req);
    });

    // Export Routes
    CROW_ROUTE(app, "/api/forensics/export/toon").methods("GET"_method)([this](const crow::request& req) {
        return handle_export_toon(req);
    });

    CROW_ROUTE(app, "/api/forensics/export/events/json").methods("GET"_method)([this](const crow::request& req) {
        return handle_export_events_json(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/export/events/json", "GET",
        "Export events to JSON",
        "Export timeline events to JSON format.",
        {"Forensics", "Export"},
        {{"task_id", "query", "Task ID", true}, {"query", "query", "Optional SQL query for filtering", false}},
        {{200, "Export completed"}}
    );

    CROW_ROUTE(app, "/api/forensics/export/events/csv").methods("GET"_method)([this](const crow::request& req) {
        return handle_export_events_csv(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/export/events/csv", "GET",
        "Export events to CSV",
        "Export timeline events to CSV format.",
        {"Forensics", "Export"},
        {{"task_id", "query", "Task ID", true}, {"query", "query", "Optional SQL query for filtering", false}},
        {{200, "Export completed"}}
    );

    CROW_ROUTE(app, "/api/forensics/export/events/visualization").methods("GET"_method)([this](const crow::request& req) {
        return handle_export_events_visualization(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/export/events/visualization", "GET",
        "Export events for visualization",
        "Export timeline events in a format optimized for visualization.",
        {"Forensics", "Export"},
        {{"task_id", "query", "Task ID", true}},
        {{200, "Export completed"}}
    );

    // Event Cluster AI Analysis Routes
    CROW_ROUTE(app, "/api/forensics/timeline/clusters/analyze").methods("POST"_method, "OPTIONS"_method)([this](const crow::request& req) {
        if (req.method == "OPTIONS"_method) {
            crow::response res;
            add_cors_headers(res);
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
            add_cors_headers(res);
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
            add_cors_headers(res);
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

std::string ForensicsRoutes::get_database_path(const std::string& task_id, const std::string& db_type) {
    AnalysisTask task = task_manager_.get_task(task_id);
    if (task.id.empty()) {
        throw std::runtime_error("Task not found: " + task_id);
    }

    if (db_type == "raw") {
        return task.output_raw_db;
    } else if (db_type == "events") {
        return task.output_events_db;
    } else if (db_type == "files") {
        return task.output_files_db;
    } else if (db_type == "android") {
        if (task.metadata.find("android_db") != task.metadata.end()) {
            return task.metadata.at("android_db");
        }
        return task.output_raw_db.substr(0, task.output_raw_db.find_last_of('.')) + "_android.db";
    } else {
        throw std::runtime_error("Unknown database type: " + db_type);
    }
}

void ForensicsRoutes::add_cors_headers(crow::response& res) {
    res.set_header("Access-Control-Allow-Origin", "*");
    res.set_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
    res.set_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With");
}

std::string ForensicsRoutes::get_image_path_for_task(const std::string& task_id) {
    AnalysisTask task = task_manager_.get_task(task_id);
    if (task.id.empty()) {
        throw std::runtime_error("Task not found: " + task_id);
    }
    return task.image_path;
}

// Event Cluster AI Analysis Endpoints
crow::response ForensicsRoutes::handle_analyze_event_cluster(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    res.set_header("Content-Type", "application/json");

    // Architecture Shift: C++ backend no longer handles LLM analysis requests directly.
    // All AI/LLM logic has been migrated to the Python Service (Port 8090).
    json response = {
        {"success", false},
        {"message", "DEPRECATED: Please use Python API /api/llm/analyze-event-cluster (Port 8090) instead."}
    };
    res.code = 410; // Gone / Deprecated
    res.write(response.dump());
    return res;
}

crow::response ForensicsRoutes::handle_batch_analyze_event_clusters(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    res.set_header("Content-Type", "application/json");

    try {
        json body = json::parse(req.body);

        // Validate required fields
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

        // Parse clusters
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

        // Get events database path
        std::string events_db = get_database_path(task_id, "events");

        // Analyze event clusters
        EventClusterAnalyzer analyzer;
        int analyzed = analyzer.analyzeEventClusters(events_db, clusters);

        json response = {{
            "success", true,
            "message", "Batch analysis completed",
            "analyzed_count", analyzed,
            "total_count", clusters.size()
        }};
        res.write(response.dump());
    } catch (const json::exception& e) {
        json error = {{
            "error", std::string("Invalid JSON: ") + e.what()
        }};
        res.code = 400;
        res.write(error.dump());
    } catch (const std::exception& e) {
        json error = {{
            "error", e.what()
        }};
        res.code = 500;
        res.write(error.dump());
    }

    return res;
}

crow::response ForensicsRoutes::handle_reanalyze_event_cluster(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    res.set_header("Content-Type", "application/json");

    try {
        json body = json::parse(req.body);

        // Validate required fields
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

        // Get events database path
        std::string events_db = get_database_path(task_id, "events");

        // Reanalyze event cluster
        EventClusterAnalyzer analyzer;
        bool success = analyzer.analyzeEventCluster(events_db, time_window, event_type, parent_directory);

        if (success) {
            json response = {{
                "success", true,
                "message", "Event cluster reanalyzed successfully"
            }};
            res.write(response.dump());
        } else {
            json error = {{
                "error", "Failed to reanalyze event cluster"
            }};
            res.code = 500;
            res.write(error.dump());
        }
    } catch (const json::exception& e) {
        json error = {{
            "error", std::string("Invalid JSON: ") + e.what()
        }};
        res.code = 400;
        res.write(error.dump());
    } catch (const std::exception& e) {
        json error = {{
            "error", e.what()
        }};
        res.code = 500;
        res.write(error.dump());
    }

    return res;
}

crow::response ForensicsRoutes::handle_get_analyzed_clusters(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
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
        std::string events_db = get_database_path(task_id, "events");

        // Query analyzed clusters
        sqlite3* db = nullptr;
        int rc = sqlite3_open(events_db.c_str(), &db);
        if (rc != SQLITE_OK) {
            json error = {{"error", "Failed to open database"}};
            res.code = 500;
            res.write(error.dump());
            return res;
        }

        std::string sql = R"(
            SELECT DISTINCT
                (timestamp / 60) as time_window,
                event_type,
                CASE WHEN file_path LIKE '%/%' THEN SUBSTR(file_path, 1, LENGTH(file_path) - INSTR(REPLACE(file_path, '/', char(1)), char(1)) + 1) ELSE '' END as parent_directory,
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
            cluster["llm_summary"] = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3));
            cluster["llm_description"] = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4));
            cluster["llm_keywords"] = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5));
            cluster["llm_analyzed_at"] = sqlite3_column_int64(stmt, 6);
            cluster["llm_model_used"] = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7));
            cluster["llm_is_relevant"] = sqlite3_column_int(stmt, 8);
            clusters.push_back(cluster);
        }

        sqlite3_finalize(stmt);
        sqlite3_close(db);

        json response = {{
            "clusters", clusters,
            "total_count", clusters.size()
        }};
        res.write(response.dump());
    } catch (const std::exception& e) {
        json error = {{
            "error", e.what()
        }};
        res.code = 500;
        res.write(error.dump());
    }

    return res;
}

// File Extraction Endpoints
crow::response ForensicsRoutes::handle_extract_files(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    res.set_header("Content-Type", "application/json");

    try {
        json body = json::parse(req.body);

        // Validate required fields
        if (!body.contains("task_id") || body["task_id"].get<std::string>().empty()) {
            json error = {{"error", "task_id is required"}};
            res.code = 400;
            res.write(error.dump());
            return res;
        }

        std::string task_id = body["task_id"].get<std::string>();

        // Create extraction job
        ExtractionJob job;
        job.id = generate_job_id();
        job.task_id = task_id;
        job.status = ExtractionStatus::PENDING;
        job.created_time = std::chrono::system_clock::now();

        // Parse extraction config
        if (body.contains("mode")) {
            std::string mode = body["mode"].get<std::string>();
            if (mode == "all") job.config.mode = ExtractionMode::ALL;
            else if (mode == "extension") job.config.mode = ExtractionMode::EXTENSION;
            else if (mode == "name") job.config.mode = ExtractionMode::NAME;
            else if (mode == "deleted") job.config.mode = ExtractionMode::DELETED;
        }

        if (body.contains("pattern")) {
            job.config.pattern = body["pattern"].get<std::string>();
        }

        if (body.contains("output_dir")) {
            job.config.output_dir = body["output_dir"].get<std::string>();
        }

        std::filesystem::path task_extract_dir = PathManager::instance().getTaskExtractDir(task_id);
        if (!job.config.output_dir.empty() && job.config.output_dir != "extracted_files") {
            std::filesystem::path user_path(job.config.output_dir);
            if (user_path.is_absolute()) {
                task_extract_dir = user_path;
            } else {
                task_extract_dir = std::filesystem::absolute(user_path);
            }
        }
        job.config.output_dir = task_extract_dir.string();
        job.output_path = task_extract_dir.string();

        if (body.contains("include_deleted")) {
            job.config.include_deleted = body["include_deleted"].get<bool>();
        }

        if (body.contains("overwrite")) {
            job.config.overwrite = body["overwrite"].get<bool>();
        }

        // Future extensibility: parse limits if provided
        if (body.contains("max_files")) {
            job.config.max_files = body["max_files"].get<int>();
        }
        if (body.contains("max_total_size")) {
            job.config.max_total_size = body["max_total_size"].get<int64_t>();
        }

        // Store job
        {
            std::lock_guard<std::mutex> lock(extraction_mutex_);
            extraction_jobs_[job.id] = job;
        }

        // Start async extraction
        std::string job_id = job.id;
        std::thread([this, job_id]() {
            run_extraction_job(job_id);
        }).detach();

        // Return job info
        json response = {
            {"success", true},
            {"message", "Extraction job started"},
            {"job_id", job.id},
            {"status", "pending"}
        };
        res.code = 202; // Accepted
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

crow::response ForensicsRoutes::handle_extraction_status(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    res.set_header("Content-Type", "application/json");

    auto params = crow::query_string(req.url_params);
    std::string job_id = params.get("job_id") ? params.get("job_id") : "";

    if (job_id.empty()) {
        // Try to get from URL path
        std::string url = req.url;
        size_t pos = url.find("/api/forensics/extract/");
        if (pos != std::string::npos) {
            job_id = url.substr(pos + 23);
            // Remove trailing slash if present
            if (!job_id.empty() && job_id.back() == '/') {
                job_id.pop_back();
            }
        }
    }

    if (job_id.empty()) {
        json error = {{"error", "job_id parameter is required"}};
        res.code = 400;
        res.write(error.dump());
        return res;
    }

    std::lock_guard<std::mutex> lock(extraction_mutex_);
    auto it = extraction_jobs_.find(job_id);
    if (it == extraction_jobs_.end()) {
        json error = {{"error", "Job not found: " + job_id}};
        res.code = 404;
        res.write(error.dump());
        return res;
    }

    const ExtractionJob& job = it->second;

    std::string status_str;
    switch (job.status) {
        case ExtractionStatus::PENDING: status_str = "pending"; break;
        case ExtractionStatus::RUNNING: status_str = "running"; break;
        case ExtractionStatus::COMPLETED: status_str = "completed"; break;
        case ExtractionStatus::FAILED: status_str = "failed"; break;
        case ExtractionStatus::CANCELLED: status_str = "cancelled"; break;
    }

    std::string mode_str;
    switch (job.config.mode) {
        case ExtractionMode::ALL: mode_str = "all"; break;
        case ExtractionMode::EXTENSION: mode_str = "extension"; break;
        case ExtractionMode::NAME: mode_str = "name"; break;
        case ExtractionMode::DELETED: mode_str = "deleted"; break;
    }

    int progress = 0;
    if (job.total_files > 0) {
        progress = (job.extracted_files + job.failed_files) * 100 / job.total_files;
    }

    json response = {
        {"job_id", job.id},
        {"task_id", job.task_id},
        {"status", status_str},
        {"mode", mode_str},
        {"pattern", job.config.pattern},
        {"output_dir", job.config.output_dir},
        {"total_files", job.total_files},
        {"extracted_files", job.extracted_files},
        {"skipped_files", job.skipped_files},
        {"failed_files", job.failed_files},
        {"progress", progress},
        {"current_file", job.current_file},
        {"message", job.message},
        {"error_details", job.error_details},
        {"output_path", job.output_path}
    };

    res.write(response.dump());
    return res;
}

void ForensicsRoutes::run_extraction_job(const std::string& job_id) {
    ExtractionJob* job_ptr = nullptr;
    std::string task_id;
    ExtractionConfig config;

    // Get job info
    {
        std::lock_guard<std::mutex> lock(extraction_mutex_);
        auto it = extraction_jobs_.find(job_id);
        if (it == extraction_jobs_.end()) return;

        job_ptr = &it->second;
        job_ptr->status = ExtractionStatus::RUNNING;
        job_ptr->started_time = std::chrono::system_clock::now();
        job_ptr->message = "Initializing extraction...";
        task_id = job_ptr->task_id;
        config = job_ptr->config;
    }

    try {
        // Get image and database paths
        std::string image_path = get_image_path_for_task(task_id);
        std::string raw_db = get_database_path(task_id, "raw");

        // Initialize FileExtractor
        auto extractor = std::make_unique<FileExtractor>(image_path, raw_db);
        if (!extractor->initialize()) {
            std::lock_guard<std::mutex> lock(extraction_mutex_);
            job_ptr->status = ExtractionStatus::FAILED;
            job_ptr->error_details = "Failed to initialize file extractor";
            job_ptr->completed_time = std::chrono::system_clock::now();
            return;
        }

        // Update job status
        {
            std::lock_guard<std::mutex> lock(extraction_mutex_);
            job_ptr->message = "Extracting files...";
            job_ptr->output_path = config.output_dir;
        }

        // Run extraction based on mode
        int extracted = 0;
        int skipped = 0;
        switch (config.mode) {
            case ExtractionMode::ALL:
                extracted = extractor->extractAll(config.output_dir, config.include_deleted, config.overwrite, &skipped);
                break;
            case ExtractionMode::EXTENSION:
                extracted = extractor->extractByExtension(config.pattern, config.output_dir, config.overwrite, &skipped);
                break;
            case ExtractionMode::NAME:
                extracted = extractor->extractByName(config.pattern, config.output_dir, config.overwrite, &skipped);
                break;
            case ExtractionMode::DELETED:
                extracted = extractor->extractDeleted(config.output_dir, config.overwrite, &skipped);
                break;
        }

        // Update final status
        {
            std::lock_guard<std::mutex> lock(extraction_mutex_);
            job_ptr->extracted_files = extracted;
            job_ptr->skipped_files = skipped;
            job_ptr->total_files = extracted + skipped; // Approximation
            job_ptr->status = ExtractionStatus::COMPLETED;

            std::stringstream msg;
            msg << "Extraction completed: " << extracted << " extracted, " << skipped << " skipped";
            job_ptr->message = msg.str();

            job_ptr->completed_time = std::chrono::system_clock::now();
        }

    } catch (const std::exception& e) {
        std::lock_guard<std::mutex> lock(extraction_mutex_);
        job_ptr->status = ExtractionStatus::FAILED;
        job_ptr->error_details = e.what();
        job_ptr->message = "Extraction failed";
        job_ptr->completed_time = std::chrono::system_clock::now();
    }
}

// TOON Export Endpoint
crow::response ForensicsRoutes::handle_export_toon(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);

    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";
    std::string fields_param = params.get("fields") ? params.get("fields") : "";
    std::string filter = params.get("filter") ? params.get("filter") : "";

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    try {
        std::string files_db = get_database_path(task_id, "files");

        // Open database
        sqlite3* db = nullptr;
        int rc = sqlite3_open_v2(files_db.c_str(), &db, SQLITE_OPEN_READONLY, nullptr);
        if (rc != SQLITE_OK) {
            json error = {{"error", "Failed to open database: " + files_db}};
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        // Configure export
        TOONExportConfig config;
        config.whereClause = filter;

        // Parse fields parameter (comma-separated)
        if (!fields_param.empty()) {
            std::stringstream ss(fields_param);
            std::string field;
            while (std::getline(ss, field, ',')) {
                // Trim whitespace
                size_t start = field.find_first_not_of(" \t");
                size_t end = field.find_last_not_of(" \t");
                if (start != std::string::npos) {
                    config.fields.push_back(field.substr(start, end - start + 1));
                }
            }
        }

        // Export to TOON
        TOONExporter exporter;
        std::string toon_content = exporter.exportToTOON(db, config);

        sqlite3_close(db);

        // Return TOON content
        res.code = 200;
        res.set_header("Content-Type", "text/toon; charset=utf-8");
        res.set_header("Content-Disposition", "attachment; filename=\"files_export.toon\"");
        res.write(toon_content);

    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }

    return res;
}

crow::response ForensicsRoutes::handle_export_events_json(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";
    std::string query = params.get("query") ? params.get("query") : "";

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    try {
        std::string events_db = get_database_path(task_id, "events");
        std::string output_file = task_id + "_events.json";
        json result = SQLiteHelper::export_events_to_json(events_db, output_file, query);
        res.set_header("Content-Type", "application/json");
        res.write(result.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response ForensicsRoutes::handle_export_events_csv(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";
    std::string query = params.get("query") ? params.get("query") : "";

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    try {
        std::string events_db = get_database_path(task_id, "events");
        std::string output_file = task_id + "_events.csv";
        json result = SQLiteHelper::export_events_to_csv(events_db, output_file, query);
        res.set_header("Content-Type", "application/json");
        res.write(result.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response ForensicsRoutes::handle_export_events_visualization(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    try {
        std::string events_db = get_database_path(task_id, "events");
        std::string output_file = task_id + "_events_viz.json";
        json result = SQLiteHelper::export_events_for_visualization(events_db, output_file);
        res.set_header("Content-Type", "application/json");
        res.write(result.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}


// ============================================================================
// Missing Implementations
// ============================================================================

crow::response ForensicsRoutes::handle_timeline_comprehensive(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";
    std::string start_time = params.get("start_time") ? params.get("start_time") : "";
    std::string end_time = params.get("end_time") ? params.get("end_time") : "";
    std::string event_type = params.get("event_type") ? params.get("event_type") : "";
    int limit = params.get("limit") ? std::stoi(params.get("limit")) : 1000;
    int offset = params.get("offset") ? std::stoi(params.get("offset")) : 0;
    bool cluster = params.get("cluster") ? (std::string(params.get("cluster")) == "true") : false;

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    try {
        std::string raw_db = get_database_path(task_id, "raw");
        std::string events_db = get_database_path(task_id, "events");
        json result = SQLiteHelper::get_comprehensive_timeline(raw_db, events_db, start_time, end_time, limit, offset, event_type, cluster);
        res.set_header("Content-Type", "application/json");
        res.write(result.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response ForensicsRoutes::handle_timeline_details(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";
    int64_t window = params.get("window") ? std::stoll(params.get("window")) : 300;
    std::string type = params.get("type") ? params.get("type") : "";
    std::string parent = params.get("parent") ? params.get("parent") : "";
    int limit = params.get("limit") ? std::stoi(params.get("limit")) : 1000;
    int offset = params.get("offset") ? std::stoi(params.get("offset")) : 0;
    std::string search = params.get("search") ? params.get("search") : "";

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    try {
        std::string events_db = get_database_path(task_id, "events");
        json result = SQLiteHelper::get_timeline_details(events_db, window, type, parent, limit, offset, search);
        res.set_header("Content-Type", "application/json");
        res.write(result.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response ForensicsRoutes::handle_timeline_distribution(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    try {
        std::string events_db = get_database_path(task_id, "events");
        json result = SQLiteHelper::get_timeline_distribution(events_db);
        res.set_header("Content-Type", "application/json");
        res.write(result.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response ForensicsRoutes::handle_timeline_file_activity(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";
    std::string file_path = params.get("file_path") ? params.get("file_path") : "";
    int64_t inode = params.get("inode") ? std::stoll(params.get("inode")) : -1;

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    try {
        std::string raw_db = get_database_path(task_id, "raw");
        std::string events_db = get_database_path(task_id, "events");
        json result = SQLiteHelper::get_file_activity_timeline(raw_db, events_db, file_path, inode);
        res.set_header("Content-Type", "application/json");
        res.write(result.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response ForensicsRoutes::handle_timeline_suspicious_patterns(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    try {
        std::string raw_db = get_database_path(task_id, "raw");
        std::string events_db = get_database_path(task_id, "events");
        json result = SQLiteHelper::get_suspicious_patterns(raw_db, events_db);
        res.set_header("Content-Type", "application/json");
        res.write(result.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response ForensicsRoutes::handle_timeline_user_activity(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    try {
        std::string raw_db = get_database_path(task_id, "raw");
        std::string events_db = get_database_path(task_id, "events");
        json result = SQLiteHelper::get_user_activity_analysis(raw_db, events_db);
        res.set_header("Content-Type", "application/json");
        res.write(result.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response ForensicsRoutes::handle_system_events(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";
    std::string start_time = params.get("start_time") ? params.get("start_time") : "";
    std::string end_time = params.get("end_time") ? params.get("end_time") : "";
    int limit = params.get("limit") ? std::stoi(params.get("limit")) : 1000;
    int offset = params.get("offset") ? std::stoi(params.get("offset")) : 0;

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    try {
        std::string events_db = get_database_path(task_id, "events");
        json result = SQLiteHelper::get_system_events(events_db, start_time, end_time, limit, offset);
        res.set_header("Content-Type", "application/json");
        res.write(result.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response ForensicsRoutes::handle_system_event_summary(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    try {
        std::string events_db = get_database_path(task_id, "events");
        json result = SQLiteHelper::get_system_event_summary(events_db);
        res.set_header("Content-Type", "application/json");
        res.write(result.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response ForensicsRoutes::handle_timeline_by_type(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";
    std::string type = params.get("type") ? params.get("type") : "";

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    try {
        std::string raw_db = get_database_path(task_id, "raw");
        std::string events_db = get_database_path(task_id, "events");
        json result = SQLiteHelper::get_comprehensive_timeline(raw_db, events_db, "", "", 1000, 0, type);
        res.set_header("Content-Type", "application/json");
        res.write(result.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response ForensicsRoutes::handle_timeline_by_time_range(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";
    std::string start = params.get("start") ? params.get("start") : "";
    std::string end = params.get("end") ? params.get("end") : "";

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    try {
        std::string raw_db = get_database_path(task_id, "raw");
        std::string events_db = get_database_path(task_id, "events");
        json result = SQLiteHelper::get_comprehensive_timeline(raw_db, events_db, start, end);
        res.set_header("Content-Type", "application/json");
        res.write(result.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response ForensicsRoutes::handle_timeline_by_file(const crow::request& req) {
    return handle_timeline_file_activity(req);
}

crow::response ForensicsRoutes::handle_timeline_full(const crow::request& req) {
    return handle_timeline_comprehensive(req);
}

crow::response ForensicsRoutes::handle_event_statistics_by_period(const crow::request& req) {
    return handle_timeline_distribution(req);
}

crow::response ForensicsRoutes::handle_files_largest(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";
    int limit = params.get("limit") ? std::stoi(params.get("limit")) : 50;

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    try {
        std::string files_db = get_database_path(task_id, "files");
        json result = SQLiteHelper::get_largest_files(files_db, limit);
        res.set_header("Content-Type", "application/json");
        res.write(result.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response ForensicsRoutes::handle_files_recent(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";
    std::string hours = params.get("hours") ? params.get("hours") : "24";

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    try {
        std::string files_db = get_database_path(task_id, "files");
        json result = SQLiteHelper::get_recent_files(files_db, hours);
        res.set_header("Content-Type", "application/json");
        res.write(result.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response ForensicsRoutes::handle_files_suspicious(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    try {
        std::string raw_db = get_database_path(task_id, "raw");
        std::string files_db = get_database_path(task_id, "files");
        json result = SQLiteHelper::get_suspicious_files(raw_db, files_db);
        res.set_header("Content-Type", "application/json");
        res.write(result.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response ForensicsRoutes::handle_files_duplicates(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    try {
        std::string files_db = get_database_path(task_id, "files");
        json result = SQLiteHelper::get_duplicate_files(files_db);
        res.set_header("Content-Type", "application/json");
        res.write(result.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response ForensicsRoutes::handle_files_extensions_analysis(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    try {
        std::string files_db = get_database_path(task_id, "files");
        json result = SQLiteHelper::get_extensions_analysis(files_db);
        res.set_header("Content-Type", "application/json");
        res.write(result.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response ForensicsRoutes::handle_android_communication_summary(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    try {
        std::string android_db = get_database_path(task_id, "android");
        json result = SQLiteHelper::get_android_communication_summary(android_db);
        res.set_header("Content-Type", "application/json");
        res.write(result.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response ForensicsRoutes::handle_android_app_usage(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    try {
        std::string android_db = get_database_path(task_id, "android");
        json result = SQLiteHelper::get_android_app_usage(android_db);
        res.set_header("Content-Type", "application/json");
        res.write(result.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response ForensicsRoutes::handle_android_device_info(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    try {
        std::string android_db = get_database_path(task_id, "android");
        json result = SQLiteHelper::get_android_device_info(android_db);
        res.set_header("Content-Type", "application/json");
        res.write(result.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response ForensicsRoutes::handle_android_media_analysis(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    try {
        std::string android_db = get_database_path(task_id, "android");
        json result = SQLiteHelper::get_android_media_analysis(android_db);
        res.set_header("Content-Type", "application/json");
        res.write(result.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response ForensicsRoutes::handle_statistics_overview(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    try {
        std::string raw_db = get_database_path(task_id, "raw");
        std::string files_db = get_database_path(task_id, "files");
        std::string events_db = get_database_path(task_id, "events");
        json result = SQLiteHelper::get_overview_statistics(raw_db, files_db, events_db);
        res.set_header("Content-Type", "application/json");
        res.write(result.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response ForensicsRoutes::handle_statistics_file_distribution(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    try {
        std::string files_db = get_database_path(task_id, "files");
        json result = SQLiteHelper::get_file_distribution_analysis(files_db);
        res.set_header("Content-Type", "application/json");
        res.write(result.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response ForensicsRoutes::handle_statistics_activity_patterns(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    try {
        std::string events_db = get_database_path(task_id, "events");
        json result = SQLiteHelper::get_activity_patterns(events_db);
        res.set_header("Content-Type", "application/json");
        res.write(result.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response ForensicsRoutes::handle_statistics_deleted_files_analysis(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    try {
        std::string raw_db = get_database_path(task_id, "raw");
        json result = SQLiteHelper::get_deleted_files_analysis(raw_db);
        res.set_header("Content-Type", "application/json");
        res.write(result.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

} // namespace forensics

