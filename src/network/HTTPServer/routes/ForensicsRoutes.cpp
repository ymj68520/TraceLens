#include "ForensicsRoutes.h"
#include "../../Swagger/Swagger.h"
#include "DatabaseManager/FileExtractor/FileExtractor.h"
#include "TOONExporter/TOONExporter.h"
#include "../../core/PathManager/PathManager.h"
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
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/timeline/comprehensive", "GET", 
        "Get comprehensive timeline", 
        "Retrieve a comprehensive timeline of events combined from multiple sources.",
        {"Forensics", "Timeline"},
        {{"task_id", "query", "Task ID", true}, {"start_time", "query", "Start timestamp (ISO)", false}, {"end_time", "query", "End timestamp (ISO)", false}},
        {{200, "Timeline data retrieved"}}
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

// Timeline Analysis Endpoints
crow::response ForensicsRoutes::handle_timeline_comprehensive(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id");
    std::string start_time = params.get("start_time") ? params.get("start_time") : "";
    std::string end_time = params.get("end_time") ? params.get("end_time") : "";

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
        json result = SQLiteHelper::get_comprehensive_timeline(raw_db, events_db, start_time, end_time);
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
    std::string task_id = params.get("task_id");
    std::string file_path = params.get("file_path") ? params.get("file_path") : "";
    std::string inode_str = params.get("inode") ? params.get("inode") : "";

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
        int64_t inode = inode_str.empty() ? -1 : std::stoll(inode_str);
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
    std::string task_id = params.get("task_id");

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
    std::string task_id = params.get("task_id");

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

// File Analysis Endpoints
crow::response ForensicsRoutes::handle_files_largest(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id");
    std::string limit_str = params.get("limit") ? params.get("limit") : "50";

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    try {
        std::string files_db = get_database_path(task_id, "files");
        int limit = std::stoi(limit_str);
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
    std::string task_id = params.get("task_id");
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
    std::string task_id = params.get("task_id");

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
    std::string task_id = params.get("task_id");

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
    std::string task_id = params.get("task_id");

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

// Android Forensics Endpoints
crow::response ForensicsRoutes::handle_android_communication_summary(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id");

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
    std::string task_id = params.get("task_id");

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
    std::string task_id = params.get("task_id");

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
    std::string task_id = params.get("task_id");

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

// Statistics Endpoints
crow::response ForensicsRoutes::handle_statistics_overview(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id");

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
    std::string task_id = params.get("task_id");

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
    std::string task_id = params.get("task_id");

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
    std::string task_id = params.get("task_id");

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

} // namespace forensics

