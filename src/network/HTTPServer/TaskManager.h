#pragma once
#include <string>
#include <map>
#include <mutex>
#include <thread>
#include <filesystem>
#include <iostream>
#include <chrono>
#include <vector>
#include <queue>
#include <condition_variable>
#include <atomic>
#include <memory>
#include <set>
#include <boost/uuid/uuid.hpp>
#include <boost/uuid/uuid_generators.hpp>
#include <boost/uuid/uuid_io.hpp>
#include <nlohmann/json.hpp>

#include "HTTPServerDataTypes.h"
#include "ImageAnalyzer/ImageAnalyzer.h"
#include "DatabaseManager/EventExtractor/EventExtractor.h"
#include "DatabaseManager/FileClassifier/FileClassifier.h"
#include "AndroidAnalyzer/AndroidAnalyzer.h"
#include "AuditLog/AuditLog.h"
#include "LLMAnalysisService.h"



class TaskManager {
public:
    static TaskManager& instance() {
        static TaskManager instance;
        return instance;
    }

    // Enhanced task creation with priority and metadata
    /**
     * @brief Create a new analysis task
     * @param path Path to the disk image file
     * @param priority Task execution priority (default: NORMAL)
     * @param metadata Optional key-value metadata map
     * @param dependencies Optional list of task dependencies
     * @return The unique ID of the created task
     */
    std::string create_task(const std::string& path, TaskPriority priority = TaskPriority::NORMAL,
                           const std::map<std::string, std::string>& metadata = {},
                           const std::vector<TaskDependency>& dependencies = {});

    // Task status management
    /**
     * @brief Update task status
     * @param id Task ID
     * @param status New status enum
     * @param msg Optional status message
     */
    void update_status(const std::string& id, TaskStatus status, const std::string& msg = "");

    /**
     * @brief Update task progress
     * @param id Task ID
     * @param phase Current processing phase
     * @param phase_percentage Percentage completion of current phase (0-100)
     * @param phase_description Description of current operation
     */
    void update_progress(const std::string& id, TaskPhase phase, int phase_percentage,
                        const std::string& phase_description = "");

    /**
     * @brief Set path to result database
     * @param id Task ID
     * @param db_path Absolute path to output database
     */
    void set_result_db(const std::string& id, const std::string& db_path);

    /**
     * @brief Configure Android analysis options
     * @param id Task ID
     * @param android_analyze Enable Android analysis
     * @param xfs_mode XFS handling mode
     * @param db_output_dir Directory for database output
     */
    void set_android_analyze_options(const std::string& id, bool android_analyze, XFSMode xfs_mode, const std::string& db_output_dir);

    /**
     * @brief Configure LLM analysis options
     * @param id Task ID
     * @param llm_analyze Enable LLM analysis
     * @param llm_mode Analysis mode ("smart" or "full")
     */
    void set_llm_analyze_options(const std::string& id, bool llm_analyze, const std::string& llm_mode);

    /**
     * @brief Retrieve task by ID
     * @param id Task ID
     * @return AnalysisTask object (empty ID if not found)
     */
    AnalysisTask get_task(const std::string& id);

    // Enhanced task retrieval methods
    /**
     * @brief Get all tasks
     * @return Vector of all AnalysisTask objects
     */
    std::vector<AnalysisTask> get_all_tasks();

    /**
     * @brief Get tasks filtered by status
     * @param status TaskStatus to filter by
     * @return Vector of matching tasks
     */
    std::vector<AnalysisTask> get_tasks_by_status(TaskStatus status);

    /**
     * @brief Get tasks filtered by priority
     * @param priority TaskPriority to filter by
     * @return Vector of matching tasks
     */
    std::vector<AnalysisTask> get_tasks_by_priority(TaskPriority priority);

    // Task cancellation
    /**
     * @brief Cancel a specific task
     * @param id Task ID
     * @param reason Reason for cancellation
     * @return true if cancellation was initiated/successful
     */
    bool cancel_task(const std::string& id, const std::string& reason = "");

    // Batch operations
    /**
     * @brief Cancel multiple tasks
     * @param task_ids List of task IDs to cancel
     * @param reason Reason for cancellation
     * @return List of successfully cancelled task IDs
     */
    std::vector<std::string> cancel_multiple_tasks(const std::vector<std::string>& task_ids, const std::string& reason = "");

    /**
     * @brief Create multiple tasks from image paths
     * @param image_paths List of paths to disk images
     * @param priority Priority for all tasks
     * @return List of created task IDs
     */
    std::vector<std::string> create_batch_tasks(const std::vector<std::string>& image_paths,
                                              TaskPriority priority = TaskPriority::NORMAL);

    // Task statistics
    /**
     * @brief Get comprehensive task statistics
     * @return JSON object with statistics
     */
    nlohmann::json get_task_statistics();

    // Cleanup operations
    /**
     * @brief Remove old tasks
     * @param max_age_hours Maximum age in hours for completed/failed tasks before removal
     * @return Number of tasks removed
     */
    int cleanup_completed_tasks(int max_age_hours = 24);

    // Dependency management
    /**
     * @brief Check if a task can start (dependencies met)
     * @param id Task ID
     * @return true if task can start
     */
    bool can_start_task(const std::string& id);

    // Progress tracking
    /**
     * @brief Get current progress structure for a task
     * @param id Task ID
     * @return TaskProgress object
     */
    TaskProgress get_task_progress(const std::string& id);

    // Cache management
    /**
     * @brief Cache result JSON string
     * @param id Task ID
     * @param result_data JSON string of results
     */
    void cache_result(const std::string& id, const std::string& result_data);

    /**
     * @brief Retrieve cached result
     * @param id Task ID
     * @return Cached JSON string or empty
     */
    std::string get_cached_result(const std::string& id);

    // Audit log
    /**
     * @brief Add an entry to the audit log
     * @param id Task ID
     * @param action Action performed
     * @param details Details of the action
     * @param user_id User performing the action (optional)
     */
    void add_audit_log(const std::string& id, const std::string& action, const std::string& details, const std::string& user_id = "");

    // Get audit logs for a task
    /**
     * @brief Retrieve audit logs for a task
     * @param id Task ID
     * @param limit Maximum number of entries
     * @param offset Pagination offset
     * @return Vector of AuditLogEntry objects
     */
    std::vector<AuditLogEntry> get_audit_logs(const std::string& id, int limit = 0, int offset = 0);

    // Enhanced start_analysis with progress tracking and cancellation support
    /**
     * @brief Start analysis job for a task (async)
     * @param task_id Task ID
     */
    void start_analysis(const std::string& task_id);

    // Persistence
    void save_tasks();
    void load_tasks();

private:
    TaskManager();

    // Helper methods
    int calculate_overall_percentage(TaskPhase phase, int phase_percentage);

    // Task queue for priority-based execution
    struct QueueItem {
        TaskPriority priority;
        std::string task_id;

        bool operator<(const QueueItem& other) const {
            return priority < other.priority; // Higher priority items come first
        }
    };

    std::map<std::string, AnalysisTask> tasks_;
    std::priority_queue<QueueItem> task_queue_;
    std::mutex mtx_;
    std::condition_variable cv_;
    std::atomic<bool> shutdown_requested_{false};
};
