#include "ExportRoutes.h"
#include "RouteHelpers.h"
#include "../SQLiteHelper.h"
#include "TOONExporter/TOONExporter.h"
#include "../../Swagger/Swagger.h"
#include <sqlite3.h>
#include <sstream>

namespace forensics {

using json = nlohmann::json;

ExportRoutes::ExportRoutes(crow::App<>& app) {
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
}

crow::response ExportRoutes::handle_export_toon(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);

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
        std::string files_db = RouteHelpers::get_database_path(task_id, "files");

        sqlite3* db = nullptr;
        int rc = sqlite3_open_v2(files_db.c_str(), &db, SQLITE_OPEN_READONLY, nullptr);
        if (rc != SQLITE_OK) {
            json error = {{"error", "Failed to open database: " + files_db}};
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        TOONExportConfig config;
        config.whereClause = filter;

        if (!fields_param.empty()) {
            std::stringstream ss(fields_param);
            std::string field;
            while (std::getline(ss, field, ',')) {
                size_t start = field.find_first_not_of(" \t");
                size_t end = field.find_last_not_of(" \t");
                if (start != std::string::npos) {
                    config.fields.push_back(field.substr(start, end - start + 1));
                }
            }
        }

        TOONExporter exporter;
        std::string toon_content = exporter.exportToTOON(db, config);

        sqlite3_close(db);

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

crow::response ExportRoutes::handle_export_events_json(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
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
        std::string events_db = RouteHelpers::get_database_path(task_id, "events");
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

crow::response ExportRoutes::handle_export_events_csv(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
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
        std::string events_db = RouteHelpers::get_database_path(task_id, "events");
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

crow::response ExportRoutes::handle_export_events_visualization(const crow::request& req) {
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

} // namespace forensics
