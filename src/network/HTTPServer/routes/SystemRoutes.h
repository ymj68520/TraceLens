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
    // System Information
    /**
     * @brief Get system health status
     * @param req The HTTP request
     * @return JSON response with health status
     */
    crow::response handle_system_health(const crow::request& req);

    /**
     * @brief Get system information
     * @param req The HTTP request
     * @return JSON response with system info
     */
    crow::response handle_system_info(const crow::request& req);

    /**
     * @brief List available databases for a task
     * @param req The HTTP request
     * @return JSON response with list of databases
     */
    crow::response handle_system_databases(const crow::request& req);

    /**
     * @brief Get schema for a specific database type
     * @param req The HTTP request
     * @param db_type Type of database ("files", "events", etc.)
     * @return JSON response with database schema
     */
    crow::response handle_system_database_schema(const crow::request& req, const std::string& db_type);
    
    // Enhanced Health Checks
    // Enhanced Health Checks
    /**
     * @brief Kubernetes liveness probe
     * @param req The HTTP request
     * @return 200 OK if service is running
     */
    crow::response handle_health_live(const crow::request& req);

    /**
     * @brief Kubernetes readiness probe
     * @param req The HTTP request
     * @return 200 OK if service is ready to accept traffic, 503 otherwise
     */
    crow::response handle_health_ready(const crow::request& req);

    /**
     * @brief Check status of dependent services
     * @param req The HTTP request
     * @return JSON response with dependency statuses
     */
    crow::response handle_health_dependencies(const crow::request& req);
    
    // Documentation
    // Documentation
    /**
     * @brief Get list of available API endpoints
     * @param req The HTTP request
     * @return JSON list of endpoints descriptions
     */
    crow::response handle_docs_endpoints(const crow::request& req);

    /**
     * @brief Get comprehensive database schema documentation
     * @param req The HTTP request
     * @return JSON response with all schemas
     */
    crow::response handle_docs_database_schema(const crow::request& req);

    /**
     * @brief Serve OpenAPI/Swagger JSON spec
     * @param req The HTTP request
     * @return JSON OpenAPI specification
     */
    crow::response handle_docs_openapi(const crow::request& req);

    /**
     * @brief Serve Swagger UI HTML
     * @param req The HTTP request
     * @return HTML page for Swagger UI
     */
    crow::response handle_docs_ui(const crow::request& req);
    
    // Export
    crow::response handle_export_results(const crow::request& req, const std::string& task_id);

    // Logs
    crow::response handle_system_logs(const crow::request& req);

    // CORS helper
    static void add_cors_headers(crow::response& res);
    
    // OpenAPI generation
    nlohmann::json generate_openapi_spec();
};

} // namespace forensics
