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
#include "LLMPythonProxy.h"



#include "../../core/ThreadPool/ThreadPool.h"
#include "TaskPersistence.h"
#include "TaskWatchdog.h"

class TaskManager {
public:
    static TaskManager& instance() {
        static TaskManager instance;
        return instance;
    }

    ~TaskManager();

    // Enhanced task creation with priority and metadata
    /**
     * @brief Create a new analysis task with full configuration (atomic)
     * @param path Path to the disk image file
     * @param priority Task execution priority
     * @param metadata Optional key-value metadata map
     * @param dependencies Optional list of task dependencies
     * @param scenarios Selected forensic scenarios (multi-select)
     * @param xfs_mode XFS handling mode
     * @param db_output_dir Directory for database output
     * @param llm_analyze Enable LLM analysis
     * @param llm_mode LLM analysis mode ("smart" or "full")
     * @param case_description Case description for LLM
     * @param filter_profile File filter profile name
     * @param enable_decryption Auto-detect and decrypt encrypted partitions
     * @param key_file_dir Override directory for decryption key files
     * @param decrypt_password Runtime-only explicit decryption password
     * @param android_source Android data source backend: "tsk" (default, uses the
     *                       TSK disk-image pipeline), "dir", "zip", or
     *                       "miui-backup" (the latter three short-circuit the
     *                       TSK pipeline and run the Android analyzer directly).
     * @param backup_password Runtime-only MIUI/Android backup AES-256 password.
     * @return The unique ID of the created task
     */
    std::string create_task(const std::string& path,
                           TaskPriority priority = TaskPriority::NORMAL,
                           const std::map<std::string, std::string>& metadata = {},
                           const std::vector<TaskDependency>& dependencies = {},
                           const std::vector<ForensicScenario>& scenarios = {},
                           XFSMode xfs_mode = XFSMode::Auto,
                           const std::string& db_output_dir = "",
                           bool llm_analyze = false,
                           const std::string& llm_mode = "smart",
                           const std::string& case_description = "",
                           const std::string& filter_profile = "",
                           bool enable_decryption = false,
                           const std::string& key_file_dir = "",
                           const std::string& decrypt_password = "",
                           const std::string& android_source = "tsk",
                           const std::string& backup_password = "");

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
     * @brief Set forensic scenarios for a task
     * @param id Task ID
     * @param scenarios List of forensic scenarios to apply
     */
    void set_scenarios(const std::string& id, const std::vector<ForensicScenario>& scenarios);

    /**
     * @brief Configure LLM analysis options
     * @param id Task ID
     * @param llm_analyze Enable LLM analysis
     * @param llm_mode Analysis mode ("smart" or "full")
     */
    void set_llm_analyze_options(const std::string& id, bool llm_analyze, const std::string& llm_mode);

    /**
     * @brief Set case description for LLM analysis
     * @param id Task ID
     * @param case_description Case description text
     */
    void set_case_description(const std::string& id, const std::string& case_description);

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

    // Task cancellation & deletion
    /**
     * @brief Cancel a specific task
     * @param id Task ID
     * @param reason Reason for cancellation
     * @return true if cancellation was initiated/successful
     */
    bool cancel_task(const std::string& id, const std::string& reason = "");

    /**
     * @brief Delete a specific task and its data
     * @param id Task ID
     * @return true if the task was successfully deleted
     */
    bool delete_task(const std::string& id);

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

    /**
     * @brief Check if a task has been requested to be cancelled
     * @param id Task ID
     * @return true if cancellation requested or task not found
     */
    bool is_task_cancelled(const std::string& id);

private:
    TaskManager();

    // Internal save without locking
    void save_tasks_internal();

    // Remove the runtime-only decryption password after analyzer handoff.
    void clear_decryption_password(const std::string& id);

    // Remove the runtime-only MIUI/Android backup password after analyzer handoff.
    void clear_backup_password(const std::string& id);

    // Logical Android analysis (dir / zip / miui-backup). Short-circuits the
    // TSK disk-image pipeline — runs the Android analyzer directly against the
    // given data source. Returns true on success.
    bool runLogicalAndroidAnalysis(const AnalysisTask& task,
                                   const std::string& baseName);

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

    // Use a controlled thread pool instead of uncontrolled detaching
    std::unique_ptr<forensics::ThreadPool> analysis_pool_;

    // Watchdog for stale/stuck tasks
    std::thread watchdog_thread_;
    void run_watchdog();
};
