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
    std::string create_task(const std::string& path, TaskPriority priority = TaskPriority::NORMAL,
                           const std::map<std::string, std::string>& metadata = {},
                           const std::vector<TaskDependency>& dependencies = {});

    // Task status management
    void update_status(const std::string& id, TaskStatus status, const std::string& msg = "");

    void update_progress(const std::string& id, TaskPhase phase, int phase_percentage,
                        const std::string& phase_description = "");

    void set_result_db(const std::string& id, const std::string& db_path);

    void set_android_analyze_options(const std::string& id, bool android_analyze, XFSMode xfs_mode, const std::string& db_output_dir);

    void set_llm_analyze_options(const std::string& id, bool llm_analyze, const std::string& llm_mode);

    AnalysisTask get_task(const std::string& id);

    // Enhanced task retrieval methods
    std::vector<AnalysisTask> get_all_tasks();

    std::vector<AnalysisTask> get_tasks_by_status(TaskStatus status);

    std::vector<AnalysisTask> get_tasks_by_priority(TaskPriority priority);

    // Task cancellation
    bool cancel_task(const std::string& id, const std::string& reason = "");

    // Batch operations
    std::vector<std::string> cancel_multiple_tasks(const std::vector<std::string>& task_ids, const std::string& reason = "");

    std::vector<std::string> create_batch_tasks(const std::vector<std::string>& image_paths,
                                              TaskPriority priority = TaskPriority::NORMAL);

    // Task statistics
    nlohmann::json get_task_statistics();

    // Cleanup operations
    int cleanup_completed_tasks(int max_age_hours = 24);

    // Dependency management
    bool can_start_task(const std::string& id);

    // Progress tracking
    TaskProgress get_task_progress(const std::string& id);

    // Cache management
    void cache_result(const std::string& id, const std::string& result_data);

    std::string get_cached_result(const std::string& id);

    // Audit log
    void add_audit_log(const std::string& id, const std::string& action, const std::string& details, const std::string& user_id = "");

    // Get audit logs for a task
    std::vector<AuditLogEntry> get_audit_logs(const std::string& id, int limit = 0, int offset = 0);

    // Enhanced start_analysis with progress tracking and cancellation support
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
