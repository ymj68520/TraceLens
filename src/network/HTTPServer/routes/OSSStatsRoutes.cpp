#include "OSSStatsRoutes.h"
#include "RouteHelpers.h"
#include "../../Swagger/Swagger.h"
#include "OSSRoutes.h"

namespace forensics {

using json = nlohmann::json;

OSSStatsRoutes::OSSStatsRoutes(crow::App<>& app) : task_manager_(TaskManager::instance()) {
    CROW_ROUTE(app, "/api/forensics/oss/summary").methods("GET"_method)([this](const crow::request& req) {
        return handle_get_summary(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/oss/summary", "GET",
        "Get OSS analysis summary",
        "Get summary statistics of OSS analysis.",
        {"Forensics", "OSS"},
        {{"task_id", "query", "Task ID", true}},
        {{200, "Analysis summary"}}
    );

    CROW_ROUTE(app, "/api/forensics/oss/stats/storage-class").methods("GET"_method)([this](const crow::request& req) {
        return handle_storage_class_stats(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/oss/stats/storage-class", "GET",
        "Get OSS storage class statistics",
        "Get statistics grouped by storage class.",
        {"Forensics", "OSS"},
        {{"task_id", "query", "Task ID", true}},
        {{200, "Storage class statistics"}}
    );

    CROW_ROUTE(app, "/api/forensics/oss/stats/extensions").methods("GET"_method)([this](const crow::request& req) {
        return handle_extension_stats(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/oss/stats/extensions", "GET",
        "Get OSS extension statistics",
        "Get statistics grouped by file extension.",
        {"Forensics", "OSS"},
        {{"task_id", "query", "Task ID", true}},
        {{200, "Extension statistics"}}
    );

    CROW_ROUTE(app, "/api/forensics/oss/buckets").methods("GET"_method)([this](const crow::request& req) {
        return handle_get_buckets(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/oss/buckets", "GET",
        "Get OSS buckets",
        "Get list of OSS buckets for a task.",
        {"Forensics", "OSS"},
        {{"task_id", "query", "Task ID", true}},
        {{200, "List of buckets"}}
    );
}

crow::response OSSStatsRoutes::handle_get_summary(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    res.set_header("Content-Type", "application/json");

    try {
        std::string task_id = req.url_params.get("task_id") ? req.url_params.get("task_id") : "";

        if (task_id.empty()) {
            json error = {{"error", "task_id is required"}};
            res.code = 400;
            res.write(error.dump());
            return res;
        }

        json response = {
            {"task_id", task_id},
            {"total_objects", 0},
            {"total_size", 0},
            {"total_buckets", 0},
            {"analyzed_at", std::chrono::duration_cast<std::chrono::milliseconds>(
                std::chrono::system_clock::now().time_since_epoch()).count()}
        };

        res.write(response.dump());

    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.write(error.dump());
    }

    return res;
}

crow::response OSSStatsRoutes::handle_storage_class_stats(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    res.set_header("Content-Type", "application/json");

    try {
        std::string task_id = req.url_params.get("task_id") ? req.url_params.get("task_id") : "";

        if (task_id.empty()) {
            json error = {{"error", "task_id is required"}};
            res.code = 400;
            res.write(error.dump());
            return res;
        }

        json stats = json::array();
        json response = {
            {"task_id", task_id},
            {"storage_classes", stats}
        };

        res.write(response.dump());

    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.write(error.dump());
    }

    return res;
}

crow::response OSSStatsRoutes::handle_extension_stats(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    res.set_header("Content-Type", "application/json");

    try {
        std::string task_id = req.url_params.get("task_id") ? req.url_params.get("task_id") : "";

        if (task_id.empty()) {
            json error = {{"error", "task_id is required"}};
            res.code = 400;
            res.write(error.dump());
            return res;
        }

        json stats = json::array();
        json response = {
            {"task_id", task_id},
            {"extensions", stats}
        };

        res.write(response.dump());

    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.write(error.dump());
    }

    return res;
}

crow::response OSSStatsRoutes::handle_get_buckets(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    res.set_header("Content-Type", "application/json");

    try {
        std::string task_id = req.url_params.get("task_id") ? req.url_params.get("task_id") : "";

        if (task_id.empty()) {
            json error = {{"error", "task_id is required"}};
            res.code = 400;
            res.write(error.dump());
            return res;
        }

        json buckets = json::array();
        json response = {
            {"task_id", task_id},
            {"buckets", buckets}
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
