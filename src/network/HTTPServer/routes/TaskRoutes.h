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
    // Basic task operations
    /**
     * @brief Create a new analysis task
     * @param req The HTTP request containing task details
     * @return JSON response with created task ID
     */
    crow::response handle_create_task(const crow::request& req);

    /**
     * @brief Get details of a specific task
     * @param req The HTTP request
     * @param task_id The ID of the task to retrieve
     * @return JSON response with task details
     */
    crow::response handle_get_task(const crow::request& req, const std::string& task_id);

    /**
     * @brief Get results of a completed task
     * @param req The HTTP request
     * @param task_id The ID of the task
     * @return JSON response with analysis results
     */
    crow::response handle_get_task_results(const crow::request& req, const std::string& task_id);
    
    // Enhanced task management
    /**
     * @brief List all tasks with optional filtering
     * @param req The HTTP request containing filter parameters
     * @return JSON response with list of tasks
     */
    crow::response handle_list_tasks(const crow::request& req);

    /**
     * @brief Cancel a running or pending task
     * @param req The HTTP request
     * @param task_id The ID of the task to cancel
     * @return JSON response with cancellation status
     */
    crow::response handle_cancel_task(const crow::request& req, const std::string& task_id);

    /**
     * @brief Get detailed progress of a task
     * @param req The HTTP request
     * @param task_id The ID of the task
     * @return JSON response with progress information
     */
    crow::response handle_get_task_progress(const crow::request& req, const std::string& task_id);

    /**
     * @brief Get system-wide task statistics
     * @param req The HTTP request
     * @return JSON response with task statistics
     */
    crow::response handle_get_task_statistics(const crow::request& req);

    /**
     * @brief Cleanup old completed or failed tasks
     * @param req The HTTP request
     * @return JSON response with cleanup results
     */
    crow::response handle_cleanup_tasks(const crow::request& req);
    
    // Batch operations
    /**
     * @brief Create multiple tasks in a batch
     * @param req The HTTP request containing list of image paths
     * @return JSON response with created task IDs
     */
    crow::response handle_batch_create_tasks(const crow::request& req);

    /**
     * @brief Get status for multiple tasks
     * @param req The HTTP request containing list of task IDs
     * @return JSON response with task statuses
     */
    crow::response handle_batch_status(const crow::request& req);

    /**
     * @brief Cancel multiple tasks
     * @param req The HTTP request containing list of task IDs
     * @return JSON response with cancellation results
     */
    crow::response handle_batch_cancel(const crow::request& req);
    
    // Advanced features
    /**
     * @brief Get audit log for a task
     * @param req The HTTP request
     * @param task_id The ID of the task
     * @return JSON response with audit logs
     */
    crow::response handle_get_task_audit_log(const crow::request& req, const std::string& task_id);

    /**
     * @brief Update priority of a task
     * @param req The HTTP request
     * @param task_id The ID of the task
     * @return JSON response with update status
     */
    crow::response handle_update_task_priority(const crow::request& req, const std::string& task_id);
    
    // Helper methods
    nlohmann::json task_to_json(const AnalysisTask& task);
    TaskPriority priority_from_string(const std::string& str);
    std::string priority_to_string(TaskPriority priority);
    std::string status_to_string(TaskStatus status);
    std::string phase_to_string(TaskPhase phase);

    // CORS helper
    static void add_cors_headers(crow::response& res);
};

} // namespace forensics
