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
    // NOTE: declaration order == registration order (C++ member init order).
    // Crow's router keeps the FIRST-registered matching rule, so static
    // segments (GET /api/tasks/statistics here) must register BEFORE the
    // dynamic GET/PUT /api/tasks/<string> in TaskCRUDRoutes — otherwise the
    // dynamic rule permanently shadows the statistics endpoint (observed as
    // an inexplicable 404 {"error":"Task not found","task_id":"statistics"}).
    TaskMonitoringRoutes monitoring_routes_;
    TaskCRUDRoutes crud_routes_;
    TaskBatchRoutes batch_routes_;

    /**
     * @brief Register CORS OPTIONS handlers for all task routes
     */
    void register_cors_handlers(crow::App<>& app);
};

} // namespace forensics
