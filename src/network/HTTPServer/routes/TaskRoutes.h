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
    TaskCRUDRoutes crud_routes_;
    TaskBatchRoutes batch_routes_;
    TaskMonitoringRoutes monitoring_routes_;

    /**
     * @brief Register CORS OPTIONS handlers for all task routes
     */
    void register_cors_handlers(crow::App<>& app);
};

} // namespace forensics
