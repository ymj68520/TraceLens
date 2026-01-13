#pragma once

#include <crow.h>
#include <nlohmann/json.hpp>
#include "../TaskManager.h"
#include "../SQLiteHelper.h"

namespace forensics {

/**
 * @brief Task management route handlers
 * Handles: /tasks/*, /api/tasks/*
 */
class TaskRoutes {
public:
    explicit TaskRoutes(crow::App<>& app);
    
private:
    TaskManager& task_manager_;
    
    // Basic task operations
    crow::response handle_create_task(const crow::request& req);
    crow::response handle_get_task(const crow::request& req, const std::string& task_id);
    crow::response handle_get_task_results(const crow::request& req, const std::string& task_id);
    
    // Enhanced task management
    crow::response handle_list_tasks(const crow::request& req);
    crow::response handle_cancel_task(const crow::request& req, const std::string& task_id);
    crow::response handle_get_task_progress(const crow::request& req, const std::string& task_id);
    crow::response handle_get_task_statistics(const crow::request& req);
    crow::response handle_cleanup_tasks(const crow::request& req);
    
    // Batch operations
    crow::response handle_batch_create_tasks(const crow::request& req);
    crow::response handle_batch_status(const crow::request& req);
    crow::response handle_batch_cancel(const crow::request& req);
    
    // Advanced features
    crow::response handle_get_task_audit_log(const crow::request& req, const std::string& task_id);
    crow::response handle_update_task_priority(const crow::request& req, const std::string& task_id);
    
    // Helper methods
    nlohmann::json task_to_json(const AnalysisTask& task);
    TaskPriority priority_from_string(const std::string& str);
    std::string priority_to_string(TaskPriority priority);
    std::string status_to_string(TaskStatus status);
    std::string phase_to_string(TaskPhase phase);
};

} // namespace forensics
