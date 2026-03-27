#include "SystemEventRoutes.h"
#include "RouteHelpers.h"
#include "../SQLiteHelper.h"
#include "../../Swagger/Swagger.h"

namespace forensics {

using json = nlohmann::json;

SystemEventRoutes::SystemEventRoutes(crow::App<>& app) {
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
}

crow::response SystemEventRoutes::handle_system_events(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
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
        std::string events_db = RouteHelpers::get_database_path(task_id, "events");
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

crow::response SystemEventRoutes::handle_system_event_summary(const crow::request& req) {
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

} // namespace forensics
