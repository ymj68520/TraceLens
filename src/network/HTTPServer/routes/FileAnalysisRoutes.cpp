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

    CROW_ROUTE(app, "/api/forensics/files/paged").methods("GET"_method)([this](const crow::request& req) {
        return handle_files_paged(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/files/paged", "GET",
        "Get files (paginated)",
        "Retrieve files with server-side pagination. View filters: all, analyzed (has LLM description), documents, media.",
        {"Forensics", "Files"},
        {{"task_id", "query", "Task ID", true},
         {"page", "query", "1-based page number", false, "integer"},
         {"page_size", "query", "Rows per page (1-200, default 100)", false, "integer"},
         {"view", "query", "all | analyzed | documents | media", false, "string"},
         {"extension", "query", "Comma-separated extension whitelist", false, "string"},
         {"exclude_extension", "query", "Comma-separated extension blacklist (hidden)", false, "string"},
         {"min_size", "query", "Minimum size in bytes", false, "integer"},
         {"max_size", "query", "Maximum size in bytes", false, "integer"}},
        {{200, "Paged file list with total count"}}
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

crow::response FileAnalysisRoutes::handle_files_paged(const crow::request& req) {
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

    int page = 1;
    int page_size = 100;
    try { if (params.get("page")) page = std::stoi(params.get("page")); } catch (...) { page = 1; }
    try { if (params.get("page_size")) page_size = std::stoi(params.get("page_size")); } catch (...) { page_size = 100; }
    std::string view = params.get("view") ? params.get("view") : "all";
    std::string extension = params.get("extension") ? params.get("extension") : "";
    std::string exclude_extension = params.get("exclude_extension") ? params.get("exclude_extension") : "";
    int64_t min_size = 0;
    int64_t max_size = 0;
    try { if (params.get("min_size")) min_size = std::stoll(params.get("min_size")); } catch (...) { min_size = 0; }
    try { if (params.get("max_size")) max_size = std::stoll(params.get("max_size")); } catch (...) { max_size = 0; }

    try {
        std::string files_db = RouteHelpers::get_database_path(task_id, "files");
        json result = SQLiteHelper::get_files_paged(files_db, page, page_size, view, extension, min_size, max_size, exclude_extension);
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
