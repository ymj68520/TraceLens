#pragma once

#include <crow.h>
#include <nlohmann/json.hpp>
#include "../TaskManager.h"

namespace forensics {

/**
 * @brief Task management route handlers
 * Splits responsibilities into:
 * - TaskCRUDRoutes: Basic CRUD operations
 * - TaskBatchRoutes: Batch operations
 * - TaskMonitoringRoutes: Monitoring and statistics
 * Handles: /tasks/*, /api/tasks/*
 */
class TaskRoutes {
public:
    explicit TaskRoutes(crow::App<>& app);

private:
    TaskManager& task_manager_;

    /**
     * @brief Register CORS OPTIONS handlers for all task routes
     */
    void register_cors_handlers(crow::App<>& app);

    /**
     * @brief Add CORS headers to response
     */
    static void add_cors_headers(crow::response& res);
};

} // namespace forensics
