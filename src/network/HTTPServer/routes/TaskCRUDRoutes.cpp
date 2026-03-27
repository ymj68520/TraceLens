#include "TaskCRUDRoutes.h"
#include "TaskHelpers.h"
#include "RouteHelpers.h"
#include "../SQLiteHelper.h"
#include "../../Swagger/Swagger.h"
#include "PathManager/PathManager.h"
#include <ctime>

namespace forensics {

using json = nlohmann::json;

TaskCRUDRoutes::TaskCRUDRoutes(crow::App<>& app) : task_manager_(TaskManager::instance()) {
    // Basic task management routes
    CROW_ROUTE(app, "/tasks").methods("GET"_method)([this](const crow::request& req) {
        return handle_list_tasks(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/tasks", "GET",
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

    CROW_ROUTE(app, "/tasks").methods("POST"_method)([this](const crow::request& req) {
        return handle_create_task(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/tasks", "POST",
        "Create task",
        "Create a new forensic analysis task.",
        {"Tasks"},
        {},
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

    // API variants
    CROW_ROUTE(app, "/api/tasks").methods("GET"_method)([this](const crow::request& req) {
        return handle_list_tasks(req);
    });

    CROW_ROUTE(app, "/api/tasks/list").methods("GET"_method)([this](const crow::request& req) {
        return handle_list_tasks(req);
    });

    CROW_ROUTE(app, "/api/tasks").methods("POST"_method)([this](const crow::request& req) {
        return handle_create_task(req);
    });

    CROW_ROUTE(app, "/api/tasks/<string>/results").methods("GET"_method)([this](const crow::request& req, const std::string& task_id) {
        return handle_get_task_results(req, task_id);
    });

    CROW_ROUTE(app, "/api/tasks/<string>").methods("GET"_method, "PUT"_method)([this](const crow::request& req, const std::string& task_id) {
        return handle_get_task(req, task_id);
    });

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
}

crow::response TaskCRUDRoutes::handle_create_task(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    try {
        auto body = json::parse(req.body);
        std::string image_path = body["image_path"];

        // Task priority
        TaskPriority priority = TaskPriority::NORMAL;
        if (body.contains("priority")) {
            priority = TaskHelpers::priority_from_string(body["priority"]);
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
        std::string case_description = body.value("case_description", "");

        // ATOMIC TASK CREATION: All options in one go to prevent lock contention and redundant disk I/O
        std::string task_id = task_manager_.create_task(
            image_path,
            priority,
            metadata,
            dependencies,
            android_analyze,
            xfs_mode,
            db_output_dir,
            llm_analyze,
            llm_mode,
            case_description
        );

        // Check if task can start immediately
        if (task_manager_.can_start_task(task_id)) {
            task_manager_.start_analysis(task_id);
        }

        json response = {
            {"task_id", task_id},
            {"status", "created"},
            {"priority", TaskHelpers::priority_to_string(priority)},
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

crow::response TaskCRUDRoutes::handle_get_task(const crow::request& req, const std::string& task_id) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);

    // CRITICAL: Prevent route collision with static paths like /api/tasks/list
    if (task_id == "list" || task_id == "statistics" || task_id == "cleanup" ||
        task_id == "batch-create" || task_id == "batch-status" || task_id == "batch-cancel") {
        json error = {{"error", "Task not found"}, {"task_id", task_id}};
        res.code = 404;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    AnalysisTask task = task_manager_.get_task(task_id);

    if (task.id.empty()) {
        json error = {{"error", "Task not found"}, {"task_id", task_id}};
        res.code = 404;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    json response = TaskHelpers::task_to_json(task);
    res.set_header("Content-Type", "application/json");
    res.write(response.dump());
    return res;
}

crow::response TaskCRUDRoutes::handle_get_task_results(const crow::request& req, const std::string& task_id) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
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
            {"status", TaskHelpers::status_to_string(task.status)},
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
        if (task.llm_analyze && !task.output_files_db.empty()) {
            auto llm_results = SQLiteHelper::get_llm_results(task.output_files_db);
            response["llm_results"] = llm_results;
            // Frontend might expect output_descriptions_db, alias it to output_files_db
            response["output_descriptions_db"] = task.output_files_db;
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

crow::response TaskCRUDRoutes::handle_list_tasks(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
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
        std::cout << "[DEBUG] handle_list_tasks: Total tasks in manager: " << all_tasks.size() << std::endl;
        std::vector<json> filtered_tasks;

        for (const auto& task : all_tasks) {
            bool matches = true;
            // Skip filtering if value is "all" to show all tasks
            if (!status_filter.empty() && status_filter != "all" && TaskHelpers::status_to_string(task.status) != status_filter) {
                matches = false;
            }
            if (!priority_filter.empty() && priority_filter != "all" && TaskHelpers::priority_to_string(task.priority) != priority_filter) {
                matches = false;
            }
            if (matches) {
                filtered_tasks.push_back(TaskHelpers::task_to_json(task));
            }
        }
        std::cout << "[DEBUG] handle_list_tasks: Tasks after filtering (status=" << status_filter << "): " << filtered_tasks.size() << std::endl;

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

crow::response TaskCRUDRoutes::handle_cancel_task(const crow::request& req, const std::string& task_id) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    try {
        bool success = task_manager_.delete_task(task_id);

        if (success) {
            json response = {
                {"success", true},
                {"task_id", task_id},
                {"message", "Task deleted successfully"}
            };
            res.set_header("Content-Type", "application/json");
            res.write(response.dump());
        } else {
            json error = {
                {"success", false},
                {"task_id", task_id},
                {"message", "Task could not be deleted (not found)"}
            };
            res.code = 404;
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

crow::response TaskCRUDRoutes::handle_cleanup_tasks(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
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

} // namespace forensics
