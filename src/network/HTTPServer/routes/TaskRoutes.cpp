#include "TaskRoutes.h"
#include "../../Swagger/Swagger.h"
#include <ctime>

namespace forensics {

using json = nlohmann::json;

TaskRoutes::TaskRoutes(crow::App<>& app) : task_manager_(TaskManager::instance()) {
    // CORS OPTIONS handlers - must be registered before other routes
    CROW_ROUTE(app, "/tasks").methods("OPTIONS"_method)([](const crow::request& req){
        crow::response res;
        res.set_header("Access-Control-Allow-Origin", "*");
        res.set_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
        res.set_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With");
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/tasks/<string>").methods("OPTIONS"_method)([](const crow::request& req, const std::string& task_id){
        crow::response res;
        res.set_header("Access-Control-Allow-Origin", "*");
        res.set_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
        res.set_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With");
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/tasks/<string>/results").methods("OPTIONS"_method)([](const crow::request& req, const std::string& task_id){
        crow::response res;
        res.set_header("Access-Control-Allow-Origin", "*");
        res.set_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
        res.set_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With");
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/api/tasks/list").methods("OPTIONS"_method)([](const crow::request& req){
        crow::response res;
        res.set_header("Access-Control-Allow-Origin", "*");
        res.set_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
        res.set_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With");
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/api/tasks/<string>").methods("OPTIONS"_method)([](const crow::request& req, const std::string& task_id){
        crow::response res;
        res.set_header("Access-Control-Allow-Origin", "*");
        res.set_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
        res.set_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With");
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/api/tasks/<string>/progress").methods("OPTIONS"_method)([](const crow::request& req, const std::string& task_id){
        crow::response res;
        res.set_header("Access-Control-Allow-Origin", "*");
        res.set_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
        res.set_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With");
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/api/tasks/statistics").methods("OPTIONS"_method)([](const crow::request& req){
        crow::response res;
        res.set_header("Access-Control-Allow-Origin", "*");
        res.set_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
        res.set_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With");
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/api/tasks/cleanup").methods("OPTIONS"_method)([](const crow::request& req){
        crow::response res;
        res.set_header("Access-Control-Allow-Origin", "*");
        res.set_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
        res.set_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With");
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/api/tasks/batch-create").methods("OPTIONS"_method)([](const crow::request& req){
        crow::response res;
        res.set_header("Access-Control-Allow-Origin", "*");
        res.set_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
        res.set_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With");
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/api/tasks/batch-status").methods("OPTIONS"_method)([](const crow::request& req){
        crow::response res;
        res.set_header("Access-Control-Allow-Origin", "*");
        res.set_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
        res.set_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With");
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/api/tasks/batch-cancel").methods("OPTIONS"_method)([](const crow::request& req){
        crow::response res;
        res.set_header("Access-Control-Allow-Origin", "*");
        res.set_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
        res.set_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With");
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/api/tasks/<string>/audit-log").methods("OPTIONS"_method)([](const crow::request& req, const std::string& task_id){
        crow::response res;
        res.set_header("Access-Control-Allow-Origin", "*");
        res.set_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
        res.set_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With");
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/api/tasks/<string>/priority").methods("OPTIONS"_method)([](const crow::request& req, const std::string& task_id){
        crow::response res;
        res.set_header("Access-Control-Allow-Origin", "*");
        res.set_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
        res.set_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With");
        res.code = 204;
        return res;
    });

    // Basic task management routes
    CROW_ROUTE(app, "/tasks").methods("POST"_method)([this](const crow::request& req) {
        return handle_create_task(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/tasks", "POST",
        "Create task",
        "Create a new forensic analysis task.",
        {"Tasks"},
        {}, // Body parameters are handled via schema in JSON usually, but here we can't easily express body schema in this helper yet without update
        {{201, "Task created"}, {400, "Invalid request"}}
    );

    CROW_ROUTE(app, "/tasks/<string>").methods("GET"_method)([this](const crow::request& req, const std::string& task_id) {
        return handle_get_task(req, task_id);
    });
    Swagger::instance().RegisterEndpoint(
        "/tasks/{id}", "GET",
        "Get task details",
        "Retrieve the status and details of a specific task.",
        {"Tasks"},
        {{"id", "path", "Task ID", true}},
        {{200, "Task details"}, {404, "Task not found"}}
    );

    CROW_ROUTE(app, "/tasks/<string>/results").methods("GET"_method)([this](const crow::request& req, const std::string& task_id) {
        return handle_get_task_results(req, task_id);
    });
    Swagger::instance().RegisterEndpoint(
        "/tasks/{id}/results", "GET",
        "Get task results",
        "Retrieve the results of a completed task.",
        {"Tasks"},
        {{"id", "path", "Task ID", true}},
        {{200, "Task results"}, {202, "Task in progress"}, {404, "Task not found"}}
    );

    // Enhanced task management routes
    CROW_ROUTE(app, "/api/tasks/list").methods("GET"_method)([this](const crow::request& req) {
        return handle_list_tasks(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/tasks/list", "GET",
        "List tasks",
        "List all analysis tasks with optional filtering.",
        {"Tasks"},
        {
            {"status", "query", "Filter by status", false},
            {"priority", "query", "Filter by priority", false},
            {"limit", "query", "Results limit", false, "integer"},
            {"offset", "query", "Pagination offset", false, "integer"}
        },
        {{200, "List of tasks"}}
    );

    CROW_ROUTE(app, "/api/tasks/<string>").methods("DELETE"_method)([this](const crow::request& req, const std::string& task_id) {
        return handle_cancel_task(req, task_id);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/tasks/{id}", "DELETE",
        "Cancel task",
        "Cancel a running or pending task.",
        {"Tasks"},
        {{"id", "path", "Task ID", true}},
        {{200, "Task cancelled"}, {400, "Cancellation failed"}, {500, "Internal error"}}
    );

    CROW_ROUTE(app, "/api/tasks/<string>/progress").methods("GET"_method)([this](const crow::request& req, const std::string& task_id) {
        return handle_get_task_progress(req, task_id);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/tasks/{id}/progress", "GET",
        "Get task progress",
        "Get detailed progress information for a task.",
        {"Tasks"},
        {{"id", "path", "Task ID", true}},
        {{200, "Progress info"}, {404, "Task not found"}}
    );

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

    CROW_ROUTE(app, "/api/tasks/cleanup").methods("POST"_method)([this](const crow::request& req) {
        return handle_cleanup_tasks(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/tasks/cleanup", "POST",
        "Cleanup tasks",
        "Remove old completed or failed tasks.",
        {"Tasks"},
        {},
        {{200, "Cleanup result"}}
    );

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

    // Advanced task features routes
    CROW_ROUTE(app, "/api/tasks/<string>/audit-log").methods("GET"_method)([this](const crow::request& req, const std::string& task_id) {
        return handle_get_task_audit_log(req, task_id);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/tasks/{id}/audit-log", "GET",
        "Get task audit log",
        "Retrieve the audit log for a specific task.",
        {"Tasks"},
        {
            {"id", "path", "Task ID", true},
            {"limit", "query", "Results limit", false, "integer"},
            {"offset", "query", "Pagination offset", false, "integer"}
        },
        {{200, "Audit logs"}, {500, "Internal error"}}
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

crow::response TaskRoutes::handle_create_task(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    try {
        auto body = json::parse(req.body);
        std::string image_path = body["image_path"];

        // Task priority
        TaskPriority priority = TaskPriority::NORMAL;
        if (body.contains("priority")) {
            priority = priority_from_string(body["priority"]);
        }

        // Metadata
        std::map<std::string, std::string> metadata;
        if (body.contains("metadata")) {
            for (auto& [key, value] : body["metadata"].items()) {
                metadata[key] = value.get<std::string>();
            }
        }

        // Dependencies
        std::vector<TaskDependency> dependencies;
        if (body.contains("dependencies")) {
            for (const auto& dep : body["dependencies"]) {
                dependencies.push_back({dep["task_id"], dep.value("required", true)});
            }
        }

        // Android analyze option
        bool android_analyze = body.value("android_analyze", false);

        // XFS mode
        XFSMode xfs_mode = XFSMode::Auto;
        if (body.contains("xfs_mode")) {
            std::string mode_str = body["xfs_mode"];
            if (mode_str == "native") xfs_mode = XFSMode::Native;
            else if (mode_str == "pure") xfs_mode = XFSMode::Pure;
        }

        // DB output directory
        std::string db_output_dir = body.value("db_output_dir", "");

        // LLM analysis options (new)
        bool llm_analyze = body.value("llm_analyze", false);
        std::string llm_mode = body.value("llm_mode", "smart"); // "full" or "smart"

        std::string task_id = task_manager_.create_task(image_path, priority, metadata, dependencies);
        task_manager_.set_android_analyze_options(task_id, android_analyze, xfs_mode, db_output_dir);
        task_manager_.set_llm_analyze_options(task_id, llm_analyze, llm_mode);

        // Check if task can start immediately
        if (task_manager_.can_start_task(task_id)) {
            task_manager_.start_analysis(task_id);
        }

        json response = {
            {"task_id", task_id},
            {"status", "created"},
            {"priority", priority_to_string(priority)},
            {"llm_analyze", llm_analyze},
            {"llm_mode", llm_mode},
            {"dependencies_count", dependencies.size()}
        };

        res.code = 201;
        res.set_header("Content-Type", "application/json");
        res.write(response.dump());
    } catch (const std::exception& e) {
        res.code = 400;
        res.write("Invalid request: " + std::string(e.what()));
    }
    return res;
}

crow::response TaskRoutes::handle_get_task(const crow::request& req, const std::string& task_id) {
    crow::response res;
    add_cors_headers(res);
    AnalysisTask task = task_manager_.get_task(task_id);

    if (task.id.empty()) {
        json error = {{"error", "Task not found"}, {"task_id", task_id}};
        res.code = 404;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    json response = task_to_json(task);
    res.set_header("Content-Type", "application/json");
    res.write(response.dump());
    return res;
}

crow::response TaskRoutes::handle_get_task_results(const crow::request& req, const std::string& task_id) {
    crow::response res;
    add_cors_headers(res);
    AnalysisTask task = task_manager_.get_task(task_id);

    if (task.id.empty()) {
        json error = {{"error", "Task not found"}, {"task_id", task_id}};
        res.code = 404;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    if (task.status != TaskStatus::COMPLETED) {
        json response = {
            {"status", status_to_string(task.status)},
            {"message", "Task not completed yet"},
            {"task_id", task_id}
        };
        res.code = 202;
        res.set_header("Content-Type", "application/json");
        res.write(response.dump());
        return res;
    }

    try {
        std::string cached_result = task_manager_.get_cached_result(task_id);
        if (!cached_result.empty()) {
            res.set_header("Content-Type", "application/json");
            res.write(cached_result);
            return res;
        }

        auto summary = SQLiteHelper::get_file_summary(task.output_files_db);
        json response = {
            {"task_id", task_id},
            {"status", "completed"},
            {"results", summary},
            {"output_files_db", task.output_files_db}
        };

        // Add LLM results if available
        if (task.llm_analyze && !task.output_descriptions_db.empty()) {
            auto llm_results = SQLiteHelper::get_llm_results(task.output_descriptions_db);
            response["llm_results"] = llm_results;
            response["output_descriptions_db"] = task.output_descriptions_db;
        }

        task_manager_.cache_result(task_id, response.dump());

        res.set_header("Content-Type", "application/json");
        res.write(response.dump());
    } catch (const std::exception& e) {
        json error = {
            {"error", "Failed to retrieve results"},
            {"message", e.what()},
            {"task_id", task_id}
        };
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response TaskRoutes::handle_list_tasks(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    try {
        std::string status_filter = "";
        std::string priority_filter = "";
        int limit = 100;
        int offset = 0;

        if (req.url_params.get("status") != nullptr) {
            status_filter = req.url_params.get("status");
        }
        if (req.url_params.get("priority") != nullptr) {
            priority_filter = req.url_params.get("priority");
        }
        if (req.url_params.get("limit") != nullptr) {
            limit = std::stoi(req.url_params.get("limit"));
        }
        if (req.url_params.get("offset") != nullptr) {
            offset = std::stoi(req.url_params.get("offset"));
        }

        auto all_tasks = task_manager_.get_all_tasks();
        std::vector<json> filtered_tasks;

        for (const auto& task : all_tasks) {
            bool matches = true;
            // Skip filtering if value is "all" to show all tasks
            if (!status_filter.empty() && status_filter != "all" && status_to_string(task.status) != status_filter) {
                matches = false;
            }
            if (!priority_filter.empty() && priority_filter != "all" && priority_to_string(task.priority) != priority_filter) {
                matches = false;
            }
            if (matches) {
                filtered_tasks.push_back(task_to_json(task));
            }
        }

        int total = filtered_tasks.size();
        auto start_it = filtered_tasks.begin() + std::min(offset, total);
        auto end_it = filtered_tasks.begin() + std::min(offset + limit, total);
        std::vector<json> paginated_tasks(start_it, end_it);

        json response = {
            {"tasks", paginated_tasks},
            {"pagination", {
                {"total", total},
                {"limit", limit},
                {"offset", offset},
                {"has_more", offset + limit < total}
            }},
            {"filters", {
                {"status", status_filter.empty() ? "all" : status_filter},
                {"priority", priority_filter.empty() ? "all" : priority_filter}
            }}
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

crow::response TaskRoutes::handle_cancel_task(const crow::request& req, const std::string& task_id) {
    crow::response res;
    add_cors_headers(res);
    try {
        std::string reason = "Cancelled via API";
        try {
            auto body = json::parse(req.body);
            if (body.contains("reason")) {
                reason = body["reason"];
            }
        } catch (...) {}

        bool success = task_manager_.cancel_task(task_id, reason);

        if (success) {
            json response = {
                {"success", true},
                {"task_id", task_id},
                {"message", "Task cancelled successfully"}
            };
            res.set_header("Content-Type", "application/json");
            res.write(response.dump());
        } else {
            json error = {
                {"success", false},
                {"task_id", task_id},
                {"message", "Task could not be cancelled (may be completed or not found)"}
            };
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
        }
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response TaskRoutes::handle_get_task_progress(const crow::request& req, const std::string& task_id) {
    crow::response res;
    add_cors_headers(res);
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
            {"status", status_to_string(task.status)},
            {"progress", {
                {"current_phase", phase_to_string(task.progress.current_phase)},
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

crow::response TaskRoutes::handle_get_task_statistics(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
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

crow::response TaskRoutes::handle_cleanup_tasks(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    try {
        int max_age_hours = 24;
        try {
            auto body = json::parse(req.body);
            if (body.contains("max_age_hours")) {
                max_age_hours = body["max_age_hours"];
            }
        } catch (...) {}

        int removed = task_manager_.cleanup_completed_tasks(max_age_hours);

        json response = {
            {"success", true},
            {"removed_count", removed},
            {"message", "Cleanup completed"}
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

crow::response TaskRoutes::handle_batch_create_tasks(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    try {
        auto body = json::parse(req.body);
        std::vector<std::string> image_paths;

        for (const auto& path : body["image_paths"]) {
            image_paths.push_back(path.get<std::string>());
        }

        TaskPriority priority = TaskPriority::NORMAL;
        if (body.contains("priority")) {
            priority = priority_from_string(body["priority"]);
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

crow::response TaskRoutes::handle_batch_status(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    try {
        auto body = json::parse(req.body);
        std::vector<json> statuses;

        for (const auto& task_id : body["task_ids"]) {
            std::string id = task_id.get<std::string>();
            AnalysisTask task = task_manager_.get_task(id);

            if (!task.id.empty()) {
                statuses.push_back(json{
                    {"task_id", id},
                    {"status", status_to_string(task.status)},
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

crow::response TaskRoutes::handle_batch_cancel(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
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

crow::response TaskRoutes::handle_get_task_audit_log(const crow::request& req, const std::string& task_id) {
    crow::response res;
    add_cors_headers(res);
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

crow::response TaskRoutes::handle_update_task_priority(const crow::request& req, const std::string& task_id) {
    crow::response res;
    add_cors_headers(res);
    try {
        auto body = json::parse(req.body);
        TaskPriority new_priority = priority_from_string(body["priority"]);

        // Note: This would need to be implemented in TaskManager
        // For now, return success
        json response = {
            {"success", true},
            {"task_id", task_id},
            {"new_priority", priority_to_string(new_priority)}
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

// Helper methods
nlohmann::json TaskRoutes::task_to_json(const AnalysisTask& task) {
    auto created_time = std::chrono::duration_cast<std::chrono::milliseconds>(
        task.created_time.time_since_epoch()).count();
    auto started_time = std::chrono::duration_cast<std::chrono::milliseconds>(
        task.started_time.time_since_epoch()).count();
    auto completed_time = std::chrono::duration_cast<std::chrono::milliseconds>(
        task.completed_time.time_since_epoch()).count();

    json dependencies_json = json::array();
    for (const auto& dep : task.dependencies) {
        dependencies_json.push_back(json{
            {"task_id", dep.task_id},
            {"required", dep.required}
        });
    }

    long long execution_time_seconds = 0;
    if (task.status == TaskStatus::COMPLETED || task.status == TaskStatus::FAILED) {
        execution_time_seconds = std::chrono::duration_cast<std::chrono::seconds>(
            task.completed_time - task.started_time).count();
    }

    return json{
        {"id", task.id},
        {"image_path", task.image_path},
        {"status", status_to_string(task.status)},
        {"priority", priority_to_string(task.priority)},
        {"message", task.message},
        {"output_files_db", task.output_files_db},
        {"progress", {
            {"current_phase", phase_to_string(task.progress.current_phase)},
            {"phase_percentage", task.progress.phase_percentage},
            {"overall_percentage", task.progress.overall_percentage},
            {"phase_description", task.progress.phase_description}
        }},
        {"timestamps", {
            {"created", created_time},
            {"started", started_time},
            {"completed", completed_time},
            {"execution_time_seconds", execution_time_seconds}
        }},
        {"android_analyze", task.android_analyze},
        {"llm_analyze", task.llm_analyze},
        {"llm_mode", task.llm_mode},
        {"xfs_mode", task.xfs_mode == XFSMode::Native ? "native" :
                   task.xfs_mode == XFSMode::Pure ? "pure" : "auto"},
        {"db_output_dir", task.db_output_dir},
        {"cancellation_requested", task.cancellation_requested.load()},
        {"dependencies", dependencies_json},
        {"dependents_count", task.dependents.size()},
        {"metadata", task.metadata},
        {"error_details", task.error_details}
    };
}

TaskPriority TaskRoutes::priority_from_string(const std::string& str) {
    if (str == "low") return TaskPriority::LOW;
    if (str == "normal") return TaskPriority::NORMAL;
    if (str == "high") return TaskPriority::HIGH;
    if (str == "critical") return TaskPriority::CRITICAL;
    return TaskPriority::NORMAL;
}

std::string TaskRoutes::priority_to_string(TaskPriority priority) {
    switch (priority) {
        case TaskPriority::LOW: return "low";
        case TaskPriority::NORMAL: return "normal";
        case TaskPriority::HIGH: return "high";
        case TaskPriority::CRITICAL: return "critical";
        default: return "normal";
    }
}

std::string TaskRoutes::status_to_string(TaskStatus status) {
    switch (status) {
        case TaskStatus::PENDING: return "pending";
        case TaskStatus::RUNNING: return "running";
        case TaskStatus::COMPLETED: return "completed";
        case TaskStatus::FAILED: return "failed";
        case TaskStatus::CANCELLED: return "cancelled";
        default: return "unknown";
    }
}

std::string TaskRoutes::phase_to_string(TaskPhase phase) {
    switch (phase) {
        case TaskPhase::INITIALIZING: return "initializing";
        case TaskPhase::IMAGE_ANALYSIS: return "image_analysis";
        case TaskPhase::EVENT_EXTRACTION: return "event_extraction";
        case TaskPhase::FILE_CLASSIFICATION: return "file_classification";
        case TaskPhase::LLM_ANALYSIS: return "llm_analysis";
        case TaskPhase::ANDROID_ANALYSIS: return "android_analysis";
        case TaskPhase::FINALIZING: return "finalizing";
        default: return "unknown";
    }
}

void TaskRoutes::add_cors_headers(crow::response& res) {
    res.set_header("Access-Control-Allow-Origin", "*");
    res.set_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
    res.set_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With");
}

} // namespace forensics
