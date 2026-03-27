#include "OSSQueryRoutes.h"
#include "RouteHelpers.h"
#include "../../Swagger/Swagger.h"
#include "OSSRoutes.h"

namespace forensics {

using json = nlohmann::json;

OSSQueryRoutes::OSSQueryRoutes(crow::App<>& app) : task_manager_(TaskManager::instance()) {
    CROW_ROUTE(app, "/api/forensics/oss/objects").methods("GET"_method)([this](const crow::request& req) {
        return handle_get_objects(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/oss/objects", "GET",
        "Get OSS objects",
        "Retrieve analyzed OSS objects from the database.",
        {"Forensics", "OSS"},
        {{"task_id", "query", "Task ID", true}, {"bucket", "query", "Filter by bucket", false}, {"prefix", "query", "Filter by key prefix", false}, {"limit", "query", "Max results", false}},
        {{200, "List of OSS objects"}}
    );

    CROW_ROUTE(app, "/api/forensics/oss/logs").methods("GET"_method)([this](const crow::request& req) {
        return handle_get_access_logs(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/oss/logs", "GET",
        "Get OSS access logs",
        "Retrieve analyzed OSS access log entries.",
        {"Forensics", "OSS"},
        {{"task_id", "query", "Task ID", true}, {"start_time", "query", "Start timestamp", false}, {"end_time", "query", "End timestamp", false}, {"operation", "query", "Filter by operation", false}},
        {{200, "List of access log entries"}}
    );
}

crow::response OSSQueryRoutes::handle_get_objects(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    res.set_header("Content-Type", "application/json");

    try {
        std::string task_id = req.url_params.get("task_id") ? req.url_params.get("task_id") : "";
        std::string bucket = req.url_params.get("bucket") ? req.url_params.get("bucket") : "";
        std::string prefix = req.url_params.get("prefix") ? req.url_params.get("prefix") : "";
        int limit = req.url_params.get("limit") ? std::stoi(req.url_params.get("limit")) : 100;

        if (task_id.empty()) {
            json error = {{"error", "task_id is required"}};
            res.code = 400;
            res.write(error.dump());
            return res;
        }

        // Return placeholder response
        json objects = json::array();
        json response = {
            {"task_id", task_id},
            {"bucket", bucket},
            {"prefix", prefix},
            {"objects", objects},
            {"count", 0},
            {"limit", limit}
        };

        res.write(response.dump());

    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.write(error.dump());
    }

    return res;
}

crow::response OSSQueryRoutes::handle_get_access_logs(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    res.set_header("Content-Type", "application/json");

    try {
        std::string task_id = req.url_params.get("task_id") ? req.url_params.get("task_id") : "";
        std::string start_time = req.url_params.get("start_time") ? req.url_params.get("start_time") : "";
        std::string end_time = req.url_params.get("end_time") ? req.url_params.get("end_time") : "";
        std::string operation = req.url_params.get("operation") ? req.url_params.get("operation") : "";

        if (task_id.empty()) {
            json error = {{"error", "task_id is required"}};
            res.code = 400;
            res.write(error.dump());
            return res;
        }

        // Return placeholder response
        json logs = json::array();
        json response = {
            {"task_id", task_id},
            {"start_time", start_time},
            {"end_time", end_time},
            {"operation", operation},
            {"logs", logs},
            {"count", 0}
        };

        res.write(response.dump());

    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.write(error.dump());
    }

    return res;
}

} // namespace forensics
