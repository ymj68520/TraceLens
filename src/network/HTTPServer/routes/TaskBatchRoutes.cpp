#include "TaskBatchRoutes.h"
#include "TaskHelpers.h"
#include "RouteHelpers.h"
#include "../../Swagger/Swagger.h"
#include <ctime>

namespace forensics {

using json = nlohmann::json;

TaskBatchRoutes::TaskBatchRoutes(crow::App<>& app) : task_manager_(TaskManager::instance()) {
    // Batch operations routes
    CROW_ROUTE(app, "/api/tasks/batch-create").methods("POST"_method)([this](const crow::request& req) {
        return handle_batch_create_tasks(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/tasks/batch-create", "POST",
        "Batch create tasks",
        "Create multiple analysis tasks at once.",
        {"Tasks"},
        {},
        {{201, "Batch created"}, {400, "Invalid request"}}
    );

    CROW_ROUTE(app, "/api/tasks/batch-status").methods("POST"_method)([this](const crow::request& req) {
        return handle_batch_status(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/tasks/batch-status", "POST",
        "Batch task status",
        "Get the status of multiple tasks at once.",
        {"Tasks"},
        {},
        {{200, "Batch statuses"}, {400, "Invalid request"}}
    );

    CROW_ROUTE(app, "/api/tasks/batch-cancel").methods("POST"_method)([this](const crow::request& req) {
        return handle_batch_cancel(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/tasks/batch-cancel", "POST",
        "Batch cancel tasks",
        "Cancel multiple tasks at once.",
        {"Tasks"},
        {},
        {{200, "Batch cancellation result"}, {400, "Invalid request"}}
    );
}

crow::response TaskBatchRoutes::handle_batch_create_tasks(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    try {
        auto body = json::parse(req.body);
        std::vector<std::string> image_paths;

        for (const auto& path : body["image_paths"]) {
            image_paths.push_back(path.get<std::string>());
        }

        TaskPriority priority = TaskPriority::NORMAL;
        if (body.contains("priority")) {
            priority = TaskHelpers::priority_from_string(body["priority"]);
        }

        auto task_ids = task_manager_.create_batch_tasks(image_paths, priority);

        // Start all tasks that can start
        for (const auto& task_id : task_ids) {
            if (task_manager_.can_start_task(task_id)) {
                task_manager_.start_analysis(task_id);
            }
        }

        json response = {
            {"success", true},
            {"task_ids", task_ids},
            {"count", task_ids.size()}
        };

        res.code = 201;
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

crow::response TaskBatchRoutes::handle_batch_status(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    try {
        auto body = json::parse(req.body);
        std::vector<json> statuses;

        for (const auto& task_id : body["task_ids"]) {
            std::string id = task_id.get<std::string>();
            AnalysisTask task = task_manager_.get_task(id);

            if (!task.id.empty()) {
                statuses.push_back(json{
                    {"task_id", id},
                    {"status", TaskHelpers::status_to_string(task.status)},
                    {"progress", task.progress.overall_percentage}
                });
            } else {
                statuses.push_back(json{
                    {"task_id", id},
                    {"error", "Task not found"}
                });
            }
        }

        json response = {
            {"statuses", statuses},
            {"count", statuses.size()}
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

crow::response TaskBatchRoutes::handle_batch_cancel(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    try {
        auto body = json::parse(req.body);
        std::vector<std::string> task_ids;

        for (const auto& id : body["task_ids"]) {
            task_ids.push_back(id.get<std::string>());
        }

        std::string reason = body.value("reason", "Batch cancel via API");
        auto cancelled = task_manager_.cancel_multiple_tasks(task_ids, reason);

        json response = {
            {"success", true},
            {"cancelled_task_ids", cancelled},
            {"cancelled_count", cancelled.size()}
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
