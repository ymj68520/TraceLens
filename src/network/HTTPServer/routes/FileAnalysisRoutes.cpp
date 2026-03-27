#include "FileAnalysisRoutes.h"
#include "RouteHelpers.h"
#include "../SQLiteHelper.h"
#include "../../Swagger/Swagger.h"

namespace forensics {

using json = nlohmann::json;

FileAnalysisRoutes::FileAnalysisRoutes(crow::App<>& app) {
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
}

crow::response FileAnalysisRoutes::handle_files_largest(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
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
        std::string files_db = RouteHelpers::get_database_path(task_id, "files");
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

crow::response FileAnalysisRoutes::handle_files_recent(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
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
        std::string files_db = RouteHelpers::get_database_path(task_id, "files");
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

crow::response FileAnalysisRoutes::handle_files_suspicious(const crow::request& req) {
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

crow::response FileAnalysisRoutes::handle_files_duplicates(const crow::request& req) {
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

crow::response FileAnalysisRoutes::handle_files_extensions_analysis(const crow::request& req) {
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


} // namespace forensics
