#include "AndroidForensicsRoutes.h"
#include "RouteHelpers.h"
#include "../SQLiteHelper.h"
#include "../../Swagger/Swagger.h"

namespace forensics {

using json = nlohmann::json;

AndroidForensicsRoutes::AndroidForensicsRoutes(crow::App<>& app) {
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
}

crow::response AndroidForensicsRoutes::handle_android_communication_summary(const crow::request& req) {
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
        std::string android_db = RouteHelpers::get_database_path(task_id, "android");
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

crow::response AndroidForensicsRoutes::handle_android_app_usage(const crow::request& req) {
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
        std::string android_db = RouteHelpers::get_database_path(task_id, "android");
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

crow::response AndroidForensicsRoutes::handle_android_device_info(const crow::request& req) {
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
        std::string android_db = RouteHelpers::get_database_path(task_id, "android");
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

crow::response AndroidForensicsRoutes::handle_android_media_analysis(const crow::request& req) {
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
        std::string android_db = RouteHelpers::get_database_path(task_id, "android");
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

} // namespace forensics
