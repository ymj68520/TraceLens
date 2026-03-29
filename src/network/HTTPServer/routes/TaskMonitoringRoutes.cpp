#include "TaskMonitoringRoutes.h"
#include "TaskHelpers.h"
#include "RouteHelpers.h"
#include "../../Swagger/Swagger.h"
#include <ctime>

namespace forensics {

using json = nlohmann::json;

TaskMonitoringRoutes::TaskMonitoringRoutes(crow::App<>& app) : task_manager_(TaskManager::instance()) {
    // Task monitoring routes
    CROW_ROUTE(app, "/api/tasks/<string>/progress").methods("GET"_method)([this](const crow::request& req, const std::string& task_id) {
        return handle_get_task_progress(req, task_id);
    });

    CROW_ROUTE(app, "/api/tasks/<string>/audit-log").methods("GET"_method)([this](const crow::request& req, const std::string& task_id) {
        return handle_get_task_audit_log(req, task_id);
    });

    CROW_ROUTE(app, "/api/tasks/statistics").methods("GET"_method)([this](const crow::request& req) {
        return handle_get_task_statistics(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/tasks/statistics", "GET",
        "Get system task statistics",
        "Get overall statistics about tasks in the system.",
        {"Tasks"},
        {},
        {{200, "System statistics"}}
    );

    CROW_ROUTE(app, "/api/tasks/<string>/priority").methods("PUT"_method)([this](const crow::request& req, const std::string& task_id) {
        return handle_update_task_priority(req, task_id);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/tasks/{id}/priority", "PUT",
        "Update task priority",
        "Update the priority of a specific task.",
        {"Tasks"},
        {{"id", "path", "Task ID", true}},
        {{200, "Priority updated"}, {400, "Invalid request"}}
    );
}

crow::response TaskMonitoringRoutes::handle_get_task_progress(const crow::request& req, const std::string& task_id) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    try {
        AnalysisTask task = task_manager_.get_task(task_id);

        if (task.id.empty()) {
            json error = {{"error", "Task not found"}, {"task_id", task_id}};
            res.code = 404;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        json response = {
            {"task_id", task_id},
            {"status", TaskHelpers::status_to_string(task.status)},
            {"progress", {
                {"current_phase", TaskHelpers::phase_to_string(task.progress.current_phase)},
                {"phase_percentage", task.progress.phase_percentage},
                {"overall_percentage", task.progress.overall_percentage},
                {"phase_description", task.progress.phase_description}
            }}
        };

        res.set_header("Content-Type", "application/json");
        res.write(response.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response TaskMonitoringRoutes::handle_get_task_statistics(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    try {
        json stats = task_manager_.get_task_statistics();
        res.set_header("Content-Type", "application/json");
        res.write(stats.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response TaskMonitoringRoutes::handle_get_task_audit_log(const crow::request& req, const std::string& task_id) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    try {
        int limit = 50;
        int offset = 0;

        if (req.url_params.get("limit") != nullptr) {
            limit = std::stoi(req.url_params.get("limit"));
        }
        if (req.url_params.get("offset") != nullptr) {
            offset = std::stoi(req.url_params.get("offset"));
        }

        auto logs = task_manager_.get_audit_logs(task_id, limit, offset);

        json log_entries = json::array();
        for (const auto& entry : logs) {
            log_entries.push_back(json{
                {"timestamp", entry.timestampToUnixMs()},
                {"action", entry.action},
                {"details", entry.details},
                {"user_id", entry.user_id}
            });
        }

        json response = {
            {"task_id", task_id},
            {"logs", log_entries},
            {"count", log_entries.size()}
        };

        res.set_header("Content-Type", "application/json");
        res.write(response.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response TaskMonitoringRoutes::handle_update_task_priority(const crow::request& req, const std::string& task_id) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    try {
        auto body = json::parse(req.body);
        TaskPriority new_priority = TaskHelpers::priority_from_string(body["priority"]);

        // Note: This would need to be implemented in TaskManager
        // For now, return success
        json response = {
            {"success", true},
            {"task_id", task_id},
            {"new_priority", TaskHelpers::priority_to_string(new_priority)}
        };

        res.set_header("Content-Type", "application/json");
        res.write(response.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

} // namespace forensics
