#include "ForensicsRoutes.h"

namespace forensics {

using json = nlohmann::json;

ForensicsRoutes::ForensicsRoutes(crow::App<>& app) : task_manager_(TaskManager::instance()) {
    // Timeline Analysis Routes
    CROW_ROUTE(app, "/api/forensics/timeline/comprehensive").methods("GET"_method)([this](const crow::request& req) {
        return handle_timeline_comprehensive(req);
    });

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

} // namespace forensics
