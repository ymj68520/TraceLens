#include "AndroidForensicsRoutes.h"
#include "RouteHelpers.h"
#include "../SQLiteHelper.h"
#include "../../Swagger/Swagger.h"

#include <cstdlib>

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

    CROW_ROUTE(app, "/api/forensics/android/miui-overview").methods("GET"_method)([this](const crow::request& req) {
        return handle_miui_backup_overview(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/android/miui-overview", "GET",
        "Get MIUI backup manifest overview",
        "Retrieve the MIUI backup manifest (device/version/date/size) and the "
        "app-database decryption status distribution.",
        {"Forensics", "Android"},
        {{"task_id", "query", "Task ID", true}},
        {{200, "MIUI backup overview"}}
    );

    CROW_ROUTE(app, "/api/forensics/android/miui-installed-apps").methods("GET"_method)([this](const crow::request& req) {
        return handle_miui_installed_apps(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/android/miui-installed-apps", "GET",
        "Get MIUI backed-up installed apps",
        "Retrieve the per-package manifest rows of apps contained in a MIUI backup.",
        {"Forensics", "Android"},
        {{"task_id", "query", "Task ID", true}},
        {{200, "MIUI installed apps list"}}
    );

    CROW_ROUTE(app, "/api/forensics/android/miui-db-inventory").methods("GET"_method)([this](const crow::request& req) {
        return handle_miui_db_inventory(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/android/miui-db-inventory", "GET",
        "Get MIUI app database inventory",
        "Retrieve the per-database table/row/column inventory extracted from a MIUI backup.",
        {"Forensics", "Android"},
        {{"task_id", "query", "Task ID", true}},
        {{200, "MIUI app database inventory"}}
    );

    CROW_ROUTE(app, "/api/forensics/android/miui-qqnt-overview").methods("GET"_method)([this](const crow::request& req) {
        return handle_miui_qqnt_overview(req);
    });
    CROW_ROUTE(app, "/api/forensics/android/miui-qqnt-artifacts").methods("GET"_method)([this](const crow::request& req) {
        return handle_miui_qqnt_artifacts(req);
    });
    CROW_ROUTE(app, "/api/forensics/android/miui-qqnt-records").methods("GET"_method)([this](const crow::request& req) {
        return handle_miui_qqnt_records(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/android/miui-qqnt-overview", "GET",
        "Get QQNT backup evidence overview",
        "Retrieve QQ/QQNT artifact category and recovered-record counts from a MIUI backup.",
        {"Forensics", "Android"},
        {{"task_id", "query", "Task ID", true}},
        {{200, "QQNT evidence overview"}}
    );
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

crow::response AndroidForensicsRoutes::handle_miui_backup_overview(const crow::request& req) {
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
        json result = SQLiteHelper::get_miui_backup_overview(android_db);
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

crow::response AndroidForensicsRoutes::handle_miui_installed_apps(const crow::request& req) {
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
        json result = SQLiteHelper::get_miui_installed_apps(android_db);
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

crow::response AndroidForensicsRoutes::handle_miui_db_inventory(const crow::request& req) {
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
        json result = SQLiteHelper::get_miui_db_inventory(android_db);
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

crow::response AndroidForensicsRoutes::handle_miui_qqnt_overview(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    const std::string taskId = params.get("task_id") ? params.get("task_id") : "";
    if (taskId.empty()) {
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(json{{"error", "task_id parameter is required"}}.dump());
        return res;
    }
    try {
        const auto database = RouteHelpers::get_database_path(taskId, "android");
        res.set_header("Content-Type", "application/json");
        res.write(SQLiteHelper::get_miui_qqnt_overview(database).dump());
    } catch (const std::exception& error) {
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(json{{"error", error.what()}}.dump());
    }
    return res;
}

crow::response AndroidForensicsRoutes::handle_miui_qqnt_artifacts(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    const std::string taskId = params.get("task_id") ? params.get("task_id") : "";
    if (taskId.empty()) {
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(json{{"error", "task_id parameter is required"}}.dump());
        return res;
    }
    try {
        const auto database = RouteHelpers::get_database_path(taskId, "android");
        const int limit = params.get("limit") ? std::max(1, std::atoi(params.get("limit"))) : 100;
        const int offset = params.get("offset") ? std::max(0, std::atoi(params.get("offset"))) : 0;
        res.set_header("Content-Type", "application/json");
        res.write(SQLiteHelper::get_miui_qqnt_artifacts(
            database,
            params.get("category") ? params.get("category") : "",
            params.get("status") ? params.get("status") : "",
            params.get("query") ? params.get("query") : "", limit, offset).dump());
    } catch (const std::exception& error) {
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(json{{"error", error.what()}}.dump());
    }
    return res;
}

crow::response AndroidForensicsRoutes::handle_miui_qqnt_records(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    const std::string taskId = params.get("task_id") ? params.get("task_id") : "";
    if (taskId.empty()) {
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(json{{"error", "task_id parameter is required"}}.dump());
        return res;
    }
    const std::string kind = params.get("kind") ? params.get("kind") : "kv";
    if (kind != "kv" && kind != "sqlite" && kind != "logs") {
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(json{{"error", "kind must be one of: kv, sqlite, logs"}}.dump());
        return res;
    }
    try {
        const auto database = RouteHelpers::get_database_path(taskId, "android");
        const int limit = params.get("limit") ? std::max(1, std::atoi(params.get("limit"))) : 100;
        const int offset = params.get("offset") ? std::max(0, std::atoi(params.get("offset"))) : 0;
        const bool revealSensitive = params.get("reveal_sensitive") &&
            std::string(params.get("reveal_sensitive")) == "1";
        res.set_header("Content-Type", "application/json");
        res.write(SQLiteHelper::get_miui_qqnt_records(
            database, kind,
            params.get("query") ? params.get("query") : "", limit, offset,
            revealSensitive).dump());
    } catch (const std::exception& error) {
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(json{{"error", error.what()}}.dump());
    }
    return res;
}

} // namespace forensics
