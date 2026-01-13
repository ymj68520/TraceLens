#pragma once
#ifndef HTTP_SERVER_DATA_TYPES_H
#define HTTP_SERVER_DATA_TYPES_H

#include <string>
#include <vector>
#include <map>
#include <chrono>
#include <atomic>
#include <coroutine>

// Forward declaration for XFSMode (from ImageAnalyzer)
enum class XFSMode;

/**
 * @brief Task execution phases
 */
enum class TaskStatus { PENDING, RUNNING, COMPLETED, FAILED, CANCELLED };
enum class TaskPriority { LOW = 0, NORMAL = 1, HIGH = 2, CRITICAL = 3 };
enum class TaskPhase { 
    INITIALIZING, 
    IMAGE_ANALYSIS, 
    EVENT_EXTRACTION, 
    FILE_CLASSIFICATION, 
    LLM_ANALYSIS,        // LLM file description generation
    ANDROID_ANALYSIS, 
    FINALIZING 
};

/**
 * @brief LLM analysis mode
 * FULL: Analyze all files
 * SMART: LLM selects important files first, then analyzes them
 */
enum class LLMAnalysisMode { OFF, FULL, SMART };

/**
 * @brief Task progress information
 */
struct TaskProgress {
    TaskPhase current_phase;
    int phase_percentage;
    int overall_percentage;
    std::string phase_description;
    std::chrono::steady_clock::time_point phase_start_time;
    std::chrono::steady_clock::time_point estimated_completion;
};

/**
 * @brief Task dependency information
 */
struct TaskDependency {
    std::string task_id;
    bool required;
};

/**
 * @brief Analysis task structure
 */
struct AnalysisTask {
    std::string id;
    std::string image_path;
    TaskStatus status;
    std::string message;
    std::string output_files_db;
    std::string output_raw_db;
    std::string output_events_db;
    TaskPriority priority;
    TaskProgress progress;
    std::chrono::system_clock::time_point created_time;
    std::chrono::system_clock::time_point started_time;
    std::chrono::system_clock::time_point completed_time;
    std::chrono::steady_clock::time_point execution_start_time;
    std::vector<TaskDependency> dependencies;
    std::vector<std::string> dependents;
    std::string result_cache;
    bool android_analyze;
    XFSMode xfs_mode;
    std::string db_output_dir;
    std::atomic<bool> cancellation_requested{false};
    std::string error_details;
    std::map<std::string, std::string> metadata;
    
    // LLM analysis options
    bool llm_analyze = false;           // Enable LLM file description generation
    std::string llm_mode = "smart";     // "full" or "smart"
    std::string output_descriptions_db; // Database for LLM-generated descriptions

    // Make it copyable and movable by handling the atomic properly
    AnalysisTask() = default;
    AnalysisTask(const AnalysisTask& other)
        : id(other.id), image_path(other.image_path), status(other.status),
          message(other.message), output_files_db(other.output_files_db),
          output_raw_db(other.output_raw_db), output_events_db(other.output_events_db),
          priority(other.priority), progress(other.progress),
          created_time(other.created_time), started_time(other.started_time),
          completed_time(other.completed_time), execution_start_time(other.execution_start_time), dependencies(other.dependencies),
          dependents(other.dependents), result_cache(other.result_cache),
          android_analyze(other.android_analyze), xfs_mode(other.xfs_mode),
          db_output_dir(other.db_output_dir),
          cancellation_requested(other.cancellation_requested.load()),
          error_details(other.error_details), metadata(other.metadata),
          llm_analyze(other.llm_analyze), llm_mode(other.llm_mode),
          output_descriptions_db(other.output_descriptions_db) {}

    AnalysisTask& operator=(const AnalysisTask& other) {
        if (this != &other) {
            id = other.id;
            image_path = other.image_path;
            status = other.status;
            message = other.message;
            output_files_db = other.output_files_db;
            output_raw_db = other.output_raw_db;
            output_events_db = other.output_events_db;
            priority = other.priority;
            progress = other.progress;
            created_time = other.created_time;
            started_time = other.started_time;
            completed_time = other.completed_time;
            execution_start_time = other.execution_start_time;
            dependencies = other.dependencies;
            dependents = other.dependents;
            result_cache = other.result_cache;
            android_analyze = other.android_analyze;
            xfs_mode = other.xfs_mode;
            db_output_dir = other.db_output_dir;
            cancellation_requested.store(other.cancellation_requested.load());
            error_details = other.error_details;
            metadata = other.metadata;
            llm_analyze = other.llm_analyze;
            llm_mode = other.llm_mode;
            output_descriptions_db = other.output_descriptions_db;
        }
        return *this;
    }

    AnalysisTask(AnalysisTask&& other) noexcept
        : id(std::move(other.id)), image_path(std::move(other.image_path)),
          status(other.status), message(std::move(other.message)),
          output_files_db(std::move(other.output_files_db)),
          output_raw_db(std::move(other.output_raw_db)),
          output_events_db(std::move(other.output_events_db)),
          priority(other.priority), progress(std::move(other.progress)),
          created_time(other.created_time), started_time(other.started_time),
          completed_time(other.completed_time), execution_start_time(other.execution_start_time), dependencies(std::move(other.dependencies)),
          dependents(std::move(other.dependents)), result_cache(std::move(other.result_cache)),
          android_analyze(other.android_analyze), xfs_mode(other.xfs_mode),
          db_output_dir(std::move(other.db_output_dir)),
          cancellation_requested(other.cancellation_requested.load()),
          error_details(std::move(other.error_details)), metadata(std::move(other.metadata)),
          llm_analyze(other.llm_analyze), llm_mode(std::move(other.llm_mode)),
          output_descriptions_db(std::move(other.output_descriptions_db)) {}

    AnalysisTask& operator=(AnalysisTask&& other) noexcept {
        if (this != &other) {
            id = std::move(other.id);
            image_path = std::move(other.image_path);
            status = other.status;
            message = std::move(other.message);
            output_files_db = std::move(other.output_files_db);
            output_raw_db = std::move(other.output_raw_db);
            output_events_db = std::move(other.output_events_db);
            priority = other.priority;
            progress = std::move(other.progress);
            created_time = other.created_time;
            started_time = other.started_time;
            completed_time = other.completed_time;
            execution_start_time = other.execution_start_time;
            dependencies = std::move(other.dependencies);
            dependents = std::move(other.dependents);
            result_cache = std::move(other.result_cache);
            android_analyze = other.android_analyze;
            xfs_mode = other.xfs_mode;
            db_output_dir = std::move(other.db_output_dir);
            cancellation_requested.store(other.cancellation_requested.load());
            error_details = std::move(other.error_details);
            metadata = std::move(other.metadata);
            llm_analyze = other.llm_analyze;
            llm_mode = std::move(other.llm_mode);
            output_descriptions_db = std::move(other.output_descriptions_db);
        }
        return *this;
    }
};

/**
 * @brief Async coroutine task structure
 */
struct AsyncTask {
    struct promise_type{
        AsyncTask get_return_object(){ return {}; }
        std::suspend_never initial_suspend(){ return {};}
        std::suspend_never final_suspend() noexcept { return {}; }
        void return_void(){}
        void unhandled_expection(){std::terminate();}
    };
};

#endif // HTTP_SERVER_DATA_TYPES_H
