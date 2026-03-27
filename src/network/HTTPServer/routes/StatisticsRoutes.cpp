#include "StatisticsRoutes.h"
#include "RouteHelpers.h"
#include "../SQLiteHelper.h"
#include "../../Swagger/Swagger.h"

namespace forensics {

using json = nlohmann::json;

StatisticsRoutes::StatisticsRoutes(crow::App<>& app) {
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

crow::response StatisticsRoutes::handle_statistics_overview(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
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
        std::string raw_db = RouteHelpers::get_database_path(task_id, "raw");
        std::string files_db = RouteHelpers::get_database_path(task_id, "files");
        std::string events_db = RouteHelpers::get_database_path(task_id, "events");
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

crow::response StatisticsRoutes::handle_statistics_file_distribution(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
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
        std::string files_db = RouteHelpers::get_database_path(task_id, "files");
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

crow::response StatisticsRoutes::handle_statistics_activity_patterns(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
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
        std::string events_db = RouteHelpers::get_database_path(task_id, "events");
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

crow::response StatisticsRoutes::handle_statistics_deleted_files_analysis(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
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
        std::string raw_db = RouteHelpers::get_database_path(task_id, "raw");
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
