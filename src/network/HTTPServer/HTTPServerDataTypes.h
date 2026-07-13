#pragma once
#ifndef HTTP_SERVER_DATA_TYPES_H
#define HTTP_SERVER_DATA_TYPES_H

#include <string>
#include <vector>
#include <map>
#include <chrono>
#include <atomic>
#include <coroutine>
#include <optional>
#include <algorithm>

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
    PLATFORM_ANALYSIS,   // Platform-specific analysis (Android/Windows/Linux/Server)
    FINALIZING
};

/**
 * @brief Forensic analysis scenario types
 * Supports multi-scenario tasks where multiple platform analyzers run sequentially.
 */
enum class ForensicScenario {
    ANDROID,        // Android device forensics (SMS, contacts, call logs, apps)
    WINDOWS,        // Windows system forensics (registry, event logs, prefetch)
    LINUX,          // Linux system forensics (logs, users, shell history, SSH)
    SERVER_CLOUD    // Server/Cloud environment (Docker, K8s, Nginx, cloud configs)
};

/**
 * @brief Convert ForensicScenario enum to string
 */
inline std::string scenario_to_string(ForensicScenario scenario) {
    switch (scenario) {
        case ForensicScenario::ANDROID: return "android";
        case ForensicScenario::WINDOWS: return "windows";
        case ForensicScenario::LINUX: return "linux";
        case ForensicScenario::SERVER_CLOUD: return "server_cloud";
        default: return "unknown";
    }
}

/**
 * @brief Convert string to ForensicScenario enum
 * Returns std::nullopt if the string is not a valid scenario.
 */
inline std::optional<ForensicScenario> string_to_scenario(const std::string& str) {
    if (str == "android") return ForensicScenario::ANDROID;
    if (str == "windows") return ForensicScenario::WINDOWS;
    if (str == "linux") return ForensicScenario::LINUX;
    if (str == "server_cloud") return ForensicScenario::SERVER_CLOUD;
    return std::nullopt;
}

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
    // Scene configuration per scenario
    struct SceneConfig {
        bool enabled = false;
        int priorityThreshold = 50;
        bool autoDetect = false;
        std::vector<std::string> customRules;
    };

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
    std::vector<ForensicScenario> scenarios;  // Selected forensic scenarios
    std::map<ForensicScenario, SceneConfig> sceneConfigs;  // Per-scenario configuration

    // Backward compatibility: computed property
    bool get_android_analyze() const {
        return std::find(scenarios.begin(), scenarios.end(),
                         ForensicScenario::ANDROID) != scenarios.end();
    }
    XFSMode xfs_mode;
    std::string db_output_dir;
    std::atomic<bool> cancellation_requested{false};
    std::string error_details;
    std::map<std::string, std::string> metadata;

    // LLM analysis options
    bool llm_analyze = false;           // Enable LLM file description generation
    std::string llm_mode = "smart";     // "full" or "smart"
    std::string output_descriptions_db; // Database for LLM-generated descriptions
    std::string case_description;       // Case description for LLM analysis
    std::string graphiti_job_id;        // Job ID for Graphiti knowledge graph ingestion

    // File filter options
    std::string filter_profile;         // Filter profile name (e.g., "telecom_fraud")

    // Decryption options (encrypted partitions are auto-detected & unlocked)
    bool enable_decryption = false;     // Auto-decrypt encrypted partitions
    std::string key_file_dir;           // Override dir for sibling .key files
    std::string decrypt_password;       // Explicit password (bypasses .key lookup)

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
          scenarios(other.scenarios), sceneConfigs(other.sceneConfigs),
          xfs_mode(other.xfs_mode),
          db_output_dir(other.db_output_dir),
          cancellation_requested(other.cancellation_requested.load()),
          error_details(other.error_details), metadata(other.metadata),
          llm_analyze(other.llm_analyze), llm_mode(other.llm_mode),
          output_descriptions_db(other.output_descriptions_db),
          case_description(other.case_description),
          graphiti_job_id(other.graphiti_job_id),
          filter_profile(other.filter_profile),
          enable_decryption(other.enable_decryption),
          key_file_dir(other.key_file_dir),
          decrypt_password(other.decrypt_password) {}

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
            scenarios = other.scenarios;
            sceneConfigs = other.sceneConfigs;
            xfs_mode = other.xfs_mode;
            db_output_dir = other.db_output_dir;
            cancellation_requested.store(other.cancellation_requested.load());
            error_details = other.error_details;
            metadata = other.metadata;
            llm_analyze = other.llm_analyze;
            llm_mode = other.llm_mode;
            output_descriptions_db = other.output_descriptions_db;
            case_description = other.case_description;
            graphiti_job_id = other.graphiti_job_id;
            filter_profile = other.filter_profile;
            enable_decryption = other.enable_decryption;
            key_file_dir = other.key_file_dir;
            decrypt_password = other.decrypt_password;
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
          scenarios(std::move(other.scenarios)), sceneConfigs(std::move(other.sceneConfigs)),
          xfs_mode(other.xfs_mode),
          db_output_dir(std::move(other.db_output_dir)),
          cancellation_requested(other.cancellation_requested.load()),
          error_details(std::move(other.error_details)), metadata(std::move(other.metadata)),
          llm_analyze(other.llm_analyze), llm_mode(std::move(other.llm_mode)),
          output_descriptions_db(std::move(other.output_descriptions_db)),
          case_description(std::move(other.case_description)),
          graphiti_job_id(std::move(other.graphiti_job_id)),
          filter_profile(std::move(other.filter_profile)),
          enable_decryption(other.enable_decryption),
          key_file_dir(std::move(other.key_file_dir)),
          decrypt_password(std::move(other.decrypt_password)) {}

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
            scenarios = std::move(other.scenarios);
            sceneConfigs = std::move(other.sceneConfigs);
            xfs_mode = other.xfs_mode;
            db_output_dir = std::move(other.db_output_dir);
            cancellation_requested.store(other.cancellation_requested.load());
            error_details = std::move(other.error_details);
            metadata = std::move(other.metadata);
            llm_analyze = other.llm_analyze;
            llm_mode = std::move(other.llm_mode);
            output_descriptions_db = std::move(other.output_descriptions_db);
            case_description = std::move(other.case_description);
            graphiti_job_id = std::move(other.graphiti_job_id);
            filter_profile = std::move(other.filter_profile);
            enable_decryption = other.enable_decryption;
            key_file_dir = std::move(other.key_file_dir);
            decrypt_password = std::move(other.decrypt_password);
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

/**
 * @brief File extraction mode
 */
enum class ExtractionMode { 
    ALL,        // Extract all files
    EXTENSION,  // Extract by extension
    NAME,       // Extract by name pattern
    DELETED     // Extract deleted files only
};

/**
 * @brief Extraction job status
 */
enum class ExtractionStatus { 
    PENDING, 
    RUNNING, 
    COMPLETED, 
    FAILED, 
    CANCELLED 
};

/**
 * @brief Extraction job configuration
 * Extensible structure for future limit options
 */
struct ExtractionConfig {
    ExtractionMode mode = ExtractionMode::ALL;
    std::string pattern;              // For NAME or EXTENSION mode
    std::string output_dir = "extracted_files";
    bool include_deleted = false;
    bool overwrite = false;           // If false, skip existing files
    
    // Future extensibility - limits (currently unused, reserved for future)
    int max_files = 0;                // 0 = no limit
    int64_t max_total_size = 0;       // 0 = no limit (bytes)
    int64_t max_file_size = 0;        // 0 = no limit per file (bytes)
};

/**
 * @brief Extraction job information
 */
struct ExtractionJob {
    std::string id;
    std::string task_id;              // Related analysis task
    ExtractionStatus status = ExtractionStatus::PENDING;
    ExtractionConfig config;
    
    // Progress tracking
    int total_files = 0;
    int extracted_files = 0;
    int skipped_files = 0;
    int failed_files = 0;
    std::string current_file;
    std::string message;
    std::string error_details;
    
    // Timing
    std::chrono::system_clock::time_point created_time;
    std::chrono::system_clock::time_point started_time;
    std::chrono::system_clock::time_point completed_time;
    
    // Output location
    std::string output_path;          // Final output directory path
};

// ─────────────────────────────────────────────────────────────────────────────
// ForensicCase — groups multiple AnalysisTasks under one investigation
// ─────────────────────────────────────────────────────────────────────────────

/**
 * @brief Case status (derived from contained tasks + cross-image analysis state)
 */
enum class CaseStatus {
    OPEN,           ///< Tasks still running or not yet analysed
    ANALYSING,      ///< Cross-image LLM analysis in progress (Python job)
    COMPLETED,      ///< Cross-image report generated
    FAILED          ///< Cross-image analysis failed
};

/**
 * @brief Task analysis state for incremental case analysis
 */
enum class TaskAnalysisState {
    PENDING,        ///< Task not yet analyzed
    ANALYZED,       ///< Task has been analyzed (file_descriptions exist)
    NEEDS_UPDATE,   ///< Task data changed, needs re-analysis
    FAILED          ///< Task analysis failed
};

/**
 * @brief A ForensicCase bundles N disk-image tasks under one investigation.
 *
 * The cross-image analysis (multi-image LLM aggregation) is triggered by the
 * Python service after all contained tasks reach COMPLETED status.
 *
 * Extended with incremental analysis support:
 * - Tracks analysis state of each task
 * - Maintains case-level database for status persistence
 * - Enables incremental addition of new tasks without re-analyzing all
 */
struct ForensicCase {
    std::string id;                           ///< UUID
    std::string name;                         ///< Human-readable case title
    std::string description;                  ///< Case description (shared with LLM)
    std::vector<std::string> task_ids;        ///< Ordered list of contained task IDs
    CaseStatus status = CaseStatus::OPEN;
    std::string cross_analysis_job_id;        ///< Python background job ID

    std::chrono::system_clock::time_point created_at;
    std::chrono::system_clock::time_point updated_at;

    // Incremental analysis fields
    std::string case_db_path;                 ///< Path to case-level status database
    int total_files_analyzed = 0;             ///< Total files analyzed across all tasks
    std::map<std::string, TaskAnalysisState> task_analysis_states;  ///< Per-task analysis state

    // Copy / move — trivially default-constructible
    ForensicCase() = default;
};

#endif // HTTP_SERVER_DATA_TYPES_H
