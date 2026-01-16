#pragma once

#include <crow.h>
#include <nlohmann/json.hpp>
#include "../TaskManager.h"

namespace forensics {

/**
 * @brief System information and monitoring route handlers
 * Handles: /api/system/*, /api/docs/*, /api/export/*
 */
class SystemRoutes {
public:
    explicit SystemRoutes(crow::App<>& app);
    
private:
    TaskManager& task_manager_;
    
    // System Information
    crow::response handle_system_health(const crow::request& req);
    crow::response handle_system_info(const crow::request& req);
    crow::response handle_system_databases(const crow::request& req);
    crow::response handle_system_database_schema(const crow::request& req, const std::string& db_type);
    
    // Enhanced Health Checks
    crow::response handle_health_live(const crow::request& req);
    crow::response handle_health_ready(const crow::request& req);
    crow::response handle_health_dependencies(const crow::request& req);
    
    // Documentation
    crow::response handle_docs_endpoints(const crow::request& req);
    crow::response handle_docs_database_schema(const crow::request& req);
    crow::response handle_docs_openapi(const crow::request& req);
    
    // Export
    crow::response handle_export_results(const crow::request& req, const std::string& task_id);

    // CORS helper
    static void add_cors_headers(crow::response& res);
    
    // OpenAPI generation
    nlohmann::json generate_openapi_spec();
};

} // namespace forensics
