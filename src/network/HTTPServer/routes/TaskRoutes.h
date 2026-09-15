#pragma once

#include <crow.h>
#include <nlohmann/json.hpp>
#include "../TaskManager.h"
#include "TaskCRUDRoutes.h"
#include "TaskBatchRoutes.h"
#include "TaskMonitoringRoutes.h"

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
    // Registration order == match order in this Crow build: static routes
    // (/tasks/statistics, /tasks/list, /tasks/batch-*) MUST be registered
    // before the parameterized /tasks/<string> catch-all or they 404.
    TaskMonitoringRoutes monitoring_routes_;
    TaskBatchRoutes batch_routes_;
    TaskCRUDRoutes crud_routes_;

    /**
     * @brief Register CORS OPTIONS handlers for all task routes
     */
    void register_cors_handlers(crow::App<>& app);
};

} // namespace forensics
