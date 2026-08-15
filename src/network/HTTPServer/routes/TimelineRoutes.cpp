#include "TimelineRoutes.h"
#include "RouteHelpers.h"
#include "../SQLiteHelper.h"
#include "../../Swagger/Swagger.h"

namespace forensics {

using json = nlohmann::json;

TimelineRoutes::TimelineRoutes(crow::App<>& app) {
    CROW_ROUTE(app, "/api/forensics/timeline/comprehensive").methods("GET"_method)([this](const crow::request& req) {
        return handle_timeline_comprehensive(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/timeline/comprehensive", "GET",
        "Get comprehensive timeline",
        "Retrieve a comprehensive timeline of events combined from multiple sources.",
        {"Forensics", "Timeline"},
        {{"task_id", "query", "Task ID", true}, {"start_time", "query", "Start timestamp (ISO)", false}, {"end_time", "query", "End timestamp (ISO)", false}},
        {{200, "Timeline data retrieved"}}
    );

    CROW_ROUTE(app, "/api/forensics/timeline/details").methods("GET"_method)([this](const crow::request& req) {
        return handle_timeline_details(req);
    });

    CROW_ROUTE(app, "/api/forensics/timeline/distribution").methods("GET"_method)([this](const crow::request& req) {
        return handle_timeline_distribution(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/timeline/distribution", "GET",
        "Get timeline distribution",
        "Retrieve a chronological distribution of timeline events.",
        {"Forensics", "Timeline"},
        {{"task_id", "query", "Task ID", true}},
        {{200, "Timeline distribution retrieved"}}
    );

    CROW_ROUTE(app, "/api/forensics/timeline/file-activity").methods("GET"_method)([this](const crow::request& req) {
        return handle_timeline_file_activity(req);
    });

    CROW_ROUTE(app, "/api/forensics/timeline/suspicious-patterns").methods("GET"_method)([this](const crow::request& req) {
        return handle_timeline_suspicious_patterns(req);
    });

    CROW_ROUTE(app, "/api/forensics/timeline/user-activity").methods("GET"_method)([this](const crow::request& req) {
        return handle_timeline_user_activity(req);
    });

    CROW_ROUTE(app, "/api/forensics/timeline/by-type").methods("GET"_method)([this](const crow::request& req) {
        return handle_timeline_by_type(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/timeline/by-type", "GET",
        "Get timeline by event type",
        "Retrieve timeline events filtered by event type (CREATED, MODIFIED, ACCESSED, CHANGED, DELETED).",
        {"Forensics", "Timeline"},
        {{"task_id", "query", "Task ID", true}, {"event_type", "query", "Event type filter", false}, {"limit", "query", "Number of events to return", false, "integer"}},
        {{200, "Timeline events by type retrieved"}}
    );

    CROW_ROUTE(app, "/api/forensics/timeline/by-time-range").methods("GET"_method)([this](const crow::request& req) {
        return handle_timeline_by_time_range(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/timeline/by-time-range", "GET",
        "Get timeline by time range",
        "Retrieve timeline events within a specific time range.",
        {"Forensics", "Timeline"},
        {{"task_id", "query", "Task ID", true}, {"start_time", "query", "Start timestamp", false}, {"end_time", "query", "End timestamp", false}, {"limit", "query", "Number of events to return", false, "integer"}},
        {{200, "Timeline events in time range retrieved"}}
    );

    CROW_ROUTE(app, "/api/forensics/timeline/by-file").methods("GET"_method)([this](const crow::request& req) {
        return handle_timeline_by_file(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/timeline/by-file", "GET",
        "Get timeline by file",
        "Retrieve timeline events for a specific file.",
        {"Forensics", "Timeline"},
        {{"task_id", "query", "Task ID", true}, {"file_path", "query", "File path to filter", false}, {"limit", "query", "Number of events to return", false, "integer"}},
        {{200, "Timeline events for file retrieved"}}
    );

    CROW_ROUTE(app, "/api/forensics/timeline/full").methods("GET"_method)([this](const crow::request& req) {
        return handle_timeline_full(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/timeline/full", "GET",
        "Get full timeline",
        "Retrieve full timeline with pagination support.",
        {"Forensics", "Timeline"},
        {{"task_id", "query", "Task ID", true}, {"limit", "query", "Number of events to return", false, "integer"}, {"offset", "query", "Number of events to skip", false, "integer"}},
        {{200, "Full timeline retrieved"}}
    );

    CROW_ROUTE(app, "/api/forensics/timeline/statistics-by-period").methods("GET"_method)([this](const crow::request& req) {
        return handle_event_statistics_by_period(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/forensics/timeline/statistics-by-period", "GET",
        "Get event statistics by period",
        "Retrieve event statistics grouped by time period (hour, day, week, month).",
        {"Forensics", "Timeline"},
        {{"task_id", "query", "Task ID", true}, {"period", "query", "Time period (hour/day/week/month)", false}},
        {{200, "Event statistics by period retrieved"}}
    );
}

crow::response TimelineRoutes::handle_timeline_comprehensive(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";
    std::string start_time = params.get("start_time") ? params.get("start_time") : "";
    std::string end_time = params.get("end_time") ? params.get("end_time") : "";
    std::string event_type = params.get("event_type") ? params.get("event_type") : "";
    int limit = params.get("limit") ? std::stoi(params.get("limit")) : 1000;
    int offset = params.get("offset") ? std::stoi(params.get("offset")) : 0;
    bool cluster = params.get("cluster") ? (std::string(params.get("cluster")) == "true") : false;
    // Clustering time window in seconds. Default 60 (backward compatible).
    // Clamped to [1, 86400] inside the query layer.
    int bucket_seconds = params.get("bucket") ? std::stoi(params.get("bucket")) : 60;

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    try {
        std::string raw_db = RouteHelpers::get_database_path(task_id, "raw");
        std::string events_db = RouteHelpers::get_database_path(task_id, "events");
        json result = SQLiteHelper::get_comprehensive_timeline(raw_db, events_db, start_time, end_time, limit, offset, event_type, cluster, bucket_seconds);
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

crow::response TimelineRoutes::handle_timeline_details(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";
    const bool has_bucket_index = params.get("bucket_index") != nullptr;
    const bool has_window = params.get("window") != nullptr;
    int64_t window = has_bucket_index
        ? std::stoll(params.get("bucket_index"))
        : (has_window ? std::stoll(params.get("window")) : 0);
    if (has_bucket_index && has_window &&
        window != std::stoll(params.get("window"))) {
        json error = {{"error", "bucket_index and window must match"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }
    std::string type = params.get("type") ? params.get("type") : "";
    const bool has_parent = params.get("parent") != nullptr;
    const bool has_dir = params.get("dir") != nullptr;
    std::string parent = has_parent ? params.get("parent") : (has_dir ? params.get("dir") : "");
    if (has_parent && has_dir && parent != std::string(params.get("dir"))) {
        json error = {{"error", "parent and dir must match"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }
    int limit = params.get("limit") ? std::stoi(params.get("limit")) : 1000;
    int offset = params.get("offset") ? std::stoi(params.get("offset")) : 0;
    std::string search = params.get("search") ? params.get("search") : "";
    // Clustering window that was used to produce the cluster; must match it to
    // resolve the same bucket index. Default 60 (backward compatible).
    int bucket_seconds = params.get("bucket") ? std::stoi(params.get("bucket")) : 60;

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    try {
        std::string events_db = RouteHelpers::get_database_path(task_id, "events");
        json result = SQLiteHelper::get_timeline_details(events_db, window, type, parent, limit, offset, search, bucket_seconds);
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

crow::response TimelineRoutes::handle_timeline_distribution(const crow::request& req) {
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
        json result = SQLiteHelper::get_timeline_distribution(events_db);
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

crow::response TimelineRoutes::handle_timeline_file_activity(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";
    std::string file_path = params.get("file_path") ? params.get("file_path") : "";
    int64_t inode = params.get("inode") ? std::stoll(params.get("inode")) : -1;

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    try {
        std::string raw_db = RouteHelpers::get_database_path(task_id, "raw");
        std::string events_db = RouteHelpers::get_database_path(task_id, "events");
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

crow::response TimelineRoutes::handle_timeline_suspicious_patterns(const crow::request& req) {
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
        std::string events_db = RouteHelpers::get_database_path(task_id, "events");
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

crow::response TimelineRoutes::handle_timeline_user_activity(const crow::request& req) {
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
        std::string events_db = RouteHelpers::get_database_path(task_id, "events");
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

crow::response TimelineRoutes::handle_timeline_by_type(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";
    std::string type = params.get("type") ? params.get("type") : "";

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    try {
        std::string raw_db = RouteHelpers::get_database_path(task_id, "raw");
        std::string events_db = RouteHelpers::get_database_path(task_id, "events");
        json result = SQLiteHelper::get_comprehensive_timeline(raw_db, events_db, "", "", 1000, 0, type);
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

crow::response TimelineRoutes::handle_timeline_by_time_range(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";
    std::string start = params.get("start") ? params.get("start") : "";
    std::string end = params.get("end") ? params.get("end") : "";

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    try {
        std::string raw_db = RouteHelpers::get_database_path(task_id, "raw");
        std::string events_db = RouteHelpers::get_database_path(task_id, "events");
        json result = SQLiteHelper::get_comprehensive_timeline(raw_db, events_db, start, end);
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

crow::response TimelineRoutes::handle_timeline_by_file(const crow::request& req) {
    return handle_timeline_file_activity(req);
}

crow::response TimelineRoutes::handle_timeline_full(const crow::request& req) {
    return handle_timeline_comprehensive(req);
}

crow::response TimelineRoutes::handle_event_statistics_by_period(const crow::request& req) {
    return handle_timeline_distribution(req);
}

} // namespace forensics
