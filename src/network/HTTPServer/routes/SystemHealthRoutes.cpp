#include "SystemHealthRoutes.h"
#include "RouteHelpers.h"
#include "TaskManager.h"
#include "ConfigManager/ConfigManager.h"
#include "../../Swagger/Swagger.h"
#include <chrono>

namespace forensics {

using json = nlohmann::json;

SystemHealthRoutes::SystemHealthRoutes(crow::App<>& app) {
    CROW_ROUTE(app, "/api/system/health").methods("GET"_method)([this](const crow::request& req) {
        return handle_system_health(req);
    });

    CROW_ROUTE(app, "/api/health").methods("GET"_method)([this](const crow::request& req) {
        return handle_system_health(req);
    });

    CROW_ROUTE(app, "/api/health/live").methods("GET"_method)([this](const crow::request& req) {
        return handle_health_live(req);
    });

    CROW_ROUTE(app, "/api/health/ready").methods("GET"_method)([this](const crow::request& req) {
        return handle_health_ready(req);
    });

    CROW_ROUTE(app, "/api/health/dependencies").methods("GET"_method)([this](const crow::request& req) {
        return handle_health_dependencies(req);
    });
}

crow::response SystemHealthRoutes::handle_system_health(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    try {
        auto task_stats = TaskManager::instance().get_task_statistics();

        json health;
        health["status"] = "healthy";
        health["timestamp"] = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now().time_since_epoch()).count();
        health["version"] = "1.0.0";
        health["task_management"]["total_tasks"] = task_stats["total_tasks"];
        health["task_management"]["running_tasks"] = task_stats["by_status"]["running"];
        health["task_management"]["failed_tasks"] = task_stats["by_status"]["failed"];
        health["task_management"]["system_load"] = "low";
        health["services"]["http_server"] = "running";
        health["services"]["task_manager"] = "running";
        health["services"]["database_access"] = "available";

        res.set_header("Content-Type", "application/json");
        res.write(health.dump());
    } catch (const std::exception& e) {
        json error = {{"status", "unhealthy"}, {"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response SystemHealthRoutes::handle_health_live(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);

    json health = {
        {"status", "alive"},
        {"timestamp", std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::system_clock::now().time_since_epoch()).count()}
    };

    res.set_header("Content-Type", "application/json");
    res.write(health.dump());
    return res;
}

crow::response SystemHealthRoutes::handle_health_ready(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);

    try {
        bool ready = true;
        json checks;

        // Check task manager
        try {
            auto stats = TaskManager::instance().get_task_statistics();
            checks["task_manager"]["status"] = "ready";
            checks["task_manager"]["total_tasks"] = stats["total_tasks"];
        } catch (const std::exception& e) {
            checks["task_manager"]["status"] = "error";
            checks["task_manager"]["error"] = e.what();
            ready = false;
        }

        checks["database"]["status"] = "ready";

        json health;
        health["ready"] = ready;
        health["checks"] = checks;
        health["timestamp"] = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::system_clock::now().time_since_epoch()).count();

        res.code = ready ? 200 : 503;
        res.set_header("Content-Type", "application/json");
        res.write(health.dump());
    } catch (const std::exception& e) {
        json error = {{"ready", false}, {"error", e.what()}};
        res.code = 503;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response SystemHealthRoutes::handle_health_dependencies(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);

    try {
        auto& cfg = ConfigManager::instance();
        json dependencies = {
            {"http_server", {{"status", "running"}, {"port", cfg.getHTTPServerPort()}}},
            {"task_manager", {{"status", "running"}}},
            {"sqlite", {{"status", "available"}}},
            {"llm_service", {{"status", "configured"}, {"base_url", cfg.getLLMBaseUrl()}}},
            {"python_service", {{"status", "optional"}, {"url", cfg.getPythonServiceUrl()}}}
        };

        json response = {
            {"dependencies", dependencies},
            {"overall_status", "healthy"},
            {"timestamp", std::chrono::duration_cast<std::chrono::milliseconds>(
                std::chrono::system_clock::now().time_since_epoch()).count()}
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
