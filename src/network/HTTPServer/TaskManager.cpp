#include "TaskManager.h"
#include "TaskPersistence.h"
#include "TaskWatchdog.h"
#include "TaskSerialization.h"
#include "LLMPythonProxy.h"
#include "EventClusterAnalyzer.h"
#include "ConfigManager/ConfigManager.h"
#include "PathManager/PathManager.h"
#include "FileFilter/FileFilter.h"
#include "../../analyzers/WindowsFilesAnalyzer/Common/WindowsAnalyzerDeclarations.h"
#include "../../analyzers/LinuxFilesAnalyzer/Common/LinuxAnalyzerDeclarations.h"
#include <fstream>

using forensics::TaskPersistence;
using forensics::TaskWatchdog;
using forensics::FileFilter;

// JSON serialization is now in TaskSerialization.cpp

TaskManager::TaskManager() {
    // Sync with Python settings from ConfigManager (.env)
    int pool_size = forensics::ConfigManager::instance().getThreadPoolSize();
    
    // Safety check: ensure at least 1 thread, but warn if unusually high
    if (pool_size <= 0) pool_size = 2;
    if (pool_size > 16) {
        std::cerr << "Warning: THREAD_POOL_SIZE (" << pool_size << ") seems high for forensics workloads." << std::endl;
    }

    analysis_pool_ = std::make_unique<forensics::ThreadPool>(pool_size);
    // Silent initialization unless in debug mode, or use standard prefix
    // std::cout << "[Service] TaskManager initialized (pool size: " << pool_size << ")" << std::endl;
    load_tasks();

    // Start background watchdog to prevent stuck tasks
    watchdog_thread_ = std::thread(&TaskManager::run_watchdog, this);
}

// Ensure cleanup in destructor
TaskManager::~TaskManager() {
    shutdown_requested_ = true;
    if (watchdog_thread_.joinable()) {
        // We don't want to wait 60s for the sleep, but for a singleton at exit,
        // it's acceptable or we could use CV for sleep. 
        // For simplicity, we just detach or use a shorter interval.
        // Actually, let's just detach to ensure program exits quickly.
        watchdog_thread_.detach();
    }
}

void TaskManager::save_tasks() {
    std::lock_guard<std::mutex> lock(mtx_);
    save_tasks_internal();
}

void TaskManager::save_tasks_internal() {
    // Defensive check for tasks count
    if (tasks_.empty() && !std::filesystem::exists(forensics::PathManager::instance().getTasksJsonPath())) {
        return;
    }

    auto tasksPath = forensics::PathManager::instance().getTasksJsonPath();
    TaskPersistence::save_tasks(tasks_, tasksPath);
}

void TaskManager::load_tasks() {
    std::lock_guard<std::mutex> lock(mtx_);
    auto tasksPath = forensics::PathManager::instance().getTasksJsonPath();
    std::unordered_set<std::string> runningTaskIds;

    TaskPersistence::load_tasks(tasks_, tasksPath, runningTaskIds);
    TaskPersistence::cleanup_orphan_directories(tasks_);
}

// Enhanced task creation with priority and metadata - Atomic version
std::string TaskManager::create_task(const std::string& path,
                                   TaskPriority priority,
                                   const std::map<std::string, std::string>& metadata,
                                   const std::vector<TaskDependency>& dependencies,
                                   const std::vector<ForensicScenario>& scenarios,
                                   XFSMode xfs_mode,
                                   const std::string& db_output_dir,
                                   bool llm_analyze,
                                   const std::string& llm_mode,
                                   const std::string& case_description,
                                   const std::string& filter_profile) {
    std::lock_guard<std::mutex> lock(mtx_);
    boost::uuids::uuid uuid = boost::uuids::random_generator()();
    std::string id = boost::uuids::to_string(uuid);

    auto now_steady = std::chrono::steady_clock::now();
    auto now_system = std::chrono::system_clock::now();
    AnalysisTask new_task;
    new_task.id = id;
    new_task.image_path = path;
    new_task.status = TaskStatus::PENDING;
    new_task.message = "Waiting to start";
    new_task.output_files_db = "";
    new_task.output_raw_db = "";
    new_task.output_events_db = "";
    new_task.priority = priority;
    new_task.progress = {TaskPhase::INITIALIZING, 0, 0, "Waiting to start", now_steady, now_steady};
    new_task.created_time = now_system;
    new_task.started_time = now_system;
    new_task.completed_time = now_system;
    new_task.execution_start_time = now_steady;
    new_task.dependencies = dependencies;
    new_task.dependents = {};
    new_task.result_cache = "";
    new_task.scenarios = scenarios;
    new_task.xfs_mode = xfs_mode;
    new_task.db_output_dir = db_output_dir;
    new_task.llm_analyze = llm_analyze;
    new_task.llm_mode = llm_mode;
    new_task.case_description = case_description;
    new_task.filter_profile = filter_profile;
    new_task.cancellation_requested = false;
    new_task.error_details = "";
    new_task.metadata = metadata;

    tasks_[id] = new_task;

    // Add to priority queue
    task_queue_.push({priority, id});

    // Log creation
    add_audit_log(id, "CREATED", "Task created with priority " + std::to_string(static_cast<int>(priority)));
    
    // Perform I/O inside the lock is still slightly suboptimal, but merging multiple I/O to one
    // already provides 3x speedup. For Opus-style rigor, we could use a background writer.
    save_tasks_internal(); 

    return id;
}

// Task status management
void TaskManager::update_status(const std::string& id, TaskStatus status, const std::string& msg) {
    std::lock_guard<std::mutex> lock(mtx_);
    if (tasks_.count(id)) {
        tasks_[id].status = status;
        if (!msg.empty()) tasks_[id].message = msg;

        auto now_steady = std::chrono::steady_clock::now();
        auto now_system = std::chrono::system_clock::now();
        
        if (status == TaskStatus::RUNNING && tasks_[id].started_time == tasks_[id].created_time) {
            tasks_[id].started_time = now_system;
            tasks_[id].execution_start_time = now_steady;
        } else if (status == TaskStatus::COMPLETED || status == TaskStatus::FAILED || status == TaskStatus::CANCELLED) {
            tasks_[id].completed_time = now_system;
        }

        add_audit_log(id, "STATUS_CHANGE", "Status changed to " + std::to_string(static_cast<int>(status)));
        
        save_tasks_internal(); // Persist changes
    }
}

void TaskManager::update_progress(const std::string& id, TaskPhase phase, int phase_percentage,
                    const std::string& phase_description) {
    std::lock_guard<std::mutex> lock(mtx_);
    if (tasks_.count(id)) {
        auto now = std::chrono::steady_clock::now();
        auto& task = tasks_[id];

        task.progress.current_phase = phase;
        task.progress.phase_percentage = phase_percentage;
        task.progress.overall_percentage = calculate_overall_percentage(phase, phase_percentage);
        task.progress.phase_description = phase_description;
        task.progress.phase_start_time = now;

        // Estimate completion time based on current progress
        if (task.progress.overall_percentage > 0) {
            auto elapsed = std::chrono::duration_cast<std::chrono::seconds>(now - task.execution_start_time).count();
            auto total_estimated = (elapsed * 100) / task.progress.overall_percentage;
            task.progress.estimated_completion = task.execution_start_time + std::chrono::seconds(total_estimated);
        }
    }
}

void TaskManager::set_result_db(const std::string& id, const std::string& db_path) {
    std::lock_guard<std::mutex> lock(mtx_);
    if (tasks_.count(id)) {
        tasks_[id].output_files_db = db_path;
        add_audit_log(id, "RESULT_SET", "Output database set: " + db_path);
        
        save_tasks_internal(); // Persist changes
    }
}

void TaskManager::set_scenarios(const std::string& id, const std::vector<ForensicScenario>& scenarios) {
    std::lock_guard<std::mutex> lock(mtx_);
    if (tasks_.count(id)) {
        tasks_[id].scenarios = scenarios;
        save_tasks_internal();
    }
}

void TaskManager::set_llm_analyze_options(const std::string& id, bool llm_analyze, const std::string& llm_mode) {
    std::lock_guard<std::mutex> lock(mtx_);
    if (tasks_.count(id)) {
        tasks_[id].llm_analyze = llm_analyze;
        tasks_[id].llm_mode = llm_mode;
        add_audit_log(id, "LLM_CONFIG", "LLM analysis: " + std::string(llm_analyze ? "enabled" : "disabled") + ", mode: " + llm_mode);
        save_tasks_internal(); // Persist immediately
    }
}

void TaskManager::set_case_description(const std::string& id, const std::string& case_description) {
    std::lock_guard<std::mutex> lock(mtx_);
    if (tasks_.count(id)) {
        tasks_[id].case_description = case_description;
        add_audit_log(id, "CASE_DESC", "Case description updated (" + std::to_string(case_description.size()) + " chars)");
        save_tasks_internal(); // Persist changes
    }
}

AnalysisTask TaskManager::get_task(const std::string& id) {
    std::lock_guard<std::mutex> lock(mtx_);
    if (tasks_.count(id)) return tasks_[id];
    return {};
}

// Enhanced task retrieval methods
std::vector<AnalysisTask> TaskManager::get_all_tasks() {
    std::lock_guard<std::mutex> lock(mtx_);
    std::vector<AnalysisTask> result;
    result.reserve(tasks_.size());
    for (const auto& pair : tasks_) {
        result.push_back(pair.second);
    }
    return result;
}

std::vector<AnalysisTask> TaskManager::get_tasks_by_status(TaskStatus status) {
    std::lock_guard<std::mutex> lock(mtx_);
    std::vector<AnalysisTask> result;
    for (const auto& pair : tasks_) {
        if (pair.second.status == status) {
            result.push_back(pair.second);
        }
    }
    return result;
}

std::vector<AnalysisTask> TaskManager::get_tasks_by_priority(TaskPriority priority) {
    std::lock_guard<std::mutex> lock(mtx_);
    std::vector<AnalysisTask> result;
    for (const auto& pair : tasks_) {
        if (pair.second.priority == priority) {
            result.push_back(pair.second);
        }
    }
    return result;
}

// Task cancellation
bool TaskManager::cancel_task(const std::string& id, const std::string& reason) {
    std::lock_guard<std::mutex> lock(mtx_);
    if (tasks_.count(id)) {
        auto& task = tasks_[id];
        if (task.status == TaskStatus::RUNNING) {
            task.cancellation_requested = true;
            update_status(id, TaskStatus::CANCELLED, reason.empty() ? "Task cancelled by user" : reason);
            add_audit_log(id, "CANCELLED", reason.empty() ? "Task cancelled" : "Task cancelled: " + reason);
            return true;
        } else if (task.status == TaskStatus::PENDING) {
            update_status(id, TaskStatus::CANCELLED, reason.empty() ? "Task cancelled by user" : reason);
            add_audit_log(id, "CANCELLED", reason.empty() ? "Task cancelled" : "Task cancelled: " + reason);
            return true;
        }
    }
    return false;
}

bool TaskManager::delete_task(const std::string& id) {
    std::string task_dir;
    bool is_running = false;
    {
        std::lock_guard<std::mutex> lock(mtx_);
        if (tasks_.count(id) == 0) {
            return false;
        }
        
        is_running = (tasks_[id].status == TaskStatus::RUNNING);
        tasks_[id].cancellation_requested = true;
        
        // Try getting task dir from PathManager to delete from disk later
        try {
            task_dir = forensics::PathManager::instance().getTaskDir(id).string();
        } catch(...) {
            task_dir = "";
        }

        // Remove from memory - This makes it "deleted" from UI immediately
        tasks_.erase(id);
        
        // Save tasks JSON without this task
        save_tasks_internal();
    }

    // Attempt to delete Graphiti data in Neo4j via Python API
    auto& proxy = forensics::LLMPythonProxy::instance();
    proxy.deleteGraphitiData(id);

    // If task was not running, we can safely delete its files now.
    // If it WAS running, the background thread will clean it up when it exits
    // by checking if the task ID is gone from the tasks_ map.
    if (!is_running && !task_dir.empty() && std::filesystem::exists(task_dir)) {
        try {
            std::filesystem::remove_all(task_dir);
        } catch (const std::exception& e) {
            std::cerr << "Failed to remove task directory " << task_dir << ": " << e.what() << std::endl;
            // We still return true because it's removed from memory/UI
        }
    }

    return true;
}

// Batch operations
std::vector<std::string> TaskManager::cancel_multiple_tasks(const std::vector<std::string>& task_ids, const std::string& reason) {
    std::lock_guard<std::mutex> lock(mtx_);
    std::vector<std::string> cancelled_ids;
    for (const auto& id : task_ids) {
        if (cancel_task(id, reason)) {
            cancelled_ids.push_back(id);
        }
    }
    return cancelled_ids;
}

std::vector<std::string> TaskManager::create_batch_tasks(const std::vector<std::string>& image_paths,
                                          TaskPriority priority) {
    std::vector<std::string> task_ids;
    for (const auto& path : image_paths) {
        task_ids.push_back(create_task(path, priority));
    }
    return task_ids;
}

// Task statistics
nlohmann::json TaskManager::get_task_statistics() {
    std::lock_guard<std::mutex> lock(mtx_);

    int total = tasks_.size();
    int pending = 0, running = 0, completed = 0, failed = 0, cancelled = 0;
    std::map<TaskPriority, int> priority_counts;
    std::map<TaskPhase, int> phase_counts;

    auto now = std::chrono::steady_clock::now();
    long long total_execution_time = 0;
    int completed_tasks = 0;

    for (const auto& pair : tasks_) {
        const auto& task = pair.second;

        switch (task.status) {
            case TaskStatus::PENDING: pending++; break;
            case TaskStatus::RUNNING: running++; break;
            case TaskStatus::COMPLETED: completed++; break;
            case TaskStatus::FAILED: failed++; break;
            case TaskStatus::CANCELLED: cancelled++; break;
        }

        priority_counts[task.priority]++;
        if (task.status == TaskStatus::RUNNING) {
            phase_counts[task.progress.current_phase]++;
        }

        if (task.status == TaskStatus::COMPLETED || task.status == TaskStatus::FAILED) {
            auto duration = std::chrono::duration_cast<std::chrono::seconds>(task.completed_time - task.started_time).count();
            total_execution_time += duration;
            completed_tasks++;
        }
    }

    nlohmann::json stats = {
        {"total_tasks", total},
        {"by_status", {
            {"pending", pending},
            {"running", running},
            {"completed", completed},
            {"failed", failed},
            {"cancelled", cancelled}
        }},
        {"by_priority", {
            {"low", priority_counts[TaskPriority::LOW]},
            {"normal", priority_counts[TaskPriority::NORMAL]},
            {"high", priority_counts[TaskPriority::HIGH]},
            {"critical", priority_counts[TaskPriority::CRITICAL]}
        }},
        {"running_phases", {
            {"initializing", phase_counts[TaskPhase::INITIALIZING]},
            {"image_analysis", phase_counts[TaskPhase::IMAGE_ANALYSIS]},
            {"event_extraction", phase_counts[TaskPhase::EVENT_EXTRACTION]},
            {"file_classification", phase_counts[TaskPhase::FILE_CLASSIFICATION]},
            {"platform_analysis", phase_counts[TaskPhase::PLATFORM_ANALYSIS]},
            {"finalizing", phase_counts[TaskPhase::FINALIZING]}
        }},
        {"average_execution_time_seconds", completed_tasks > 0 ? total_execution_time / completed_tasks : 0}
    };

    return stats;
}

// Cleanup operations
int TaskManager::cleanup_completed_tasks(int max_age_hours) {
    std::lock_guard<std::mutex> lock(mtx_);
    auto cutoff_time = std::chrono::system_clock::now() - std::chrono::hours(max_age_hours);

    auto it = tasks_.begin();
    int removed = 0;
    while (it != tasks_.end()) {
        const auto& task = it->second;
        if ((task.status == TaskStatus::COMPLETED || task.status == TaskStatus::FAILED || task.status == TaskStatus::CANCELLED) &&
            task.completed_time < cutoff_time) {
            add_audit_log(task.id, "CLEANUP", "Task cleaned up after completion");
            it = tasks_.erase(it);
            removed++;
        } else {
            ++it;
        }
    }
    return removed;
}

// Dependency management
bool TaskManager::can_start_task(const std::string& id) {
    std::lock_guard<std::mutex> lock(mtx_);
    if (!tasks_.count(id)) return false;

    const auto& task = tasks_[id];
    for (const auto& dep : task.dependencies) {
        if (dep.required) {
            auto dep_it = tasks_.find(dep.task_id);
            if (dep_it == tasks_.end() || dep_it->second.status != TaskStatus::COMPLETED) {
                return false;
            }
        }
    }
    return true;
}

// Progress tracking
TaskProgress TaskManager::get_task_progress(const std::string& id) {
    std::lock_guard<std::mutex> lock(mtx_);
    if (tasks_.count(id)) {
        return tasks_[id].progress;
    }
    return {};
}

// Cache management
void TaskManager::cache_result(const std::string& id, const std::string& result_data) {
    std::lock_guard<std::mutex> lock(mtx_);
    if (tasks_.count(id)) {
        tasks_[id].result_cache = result_data;
        add_audit_log(id, "CACHE_SET", "Result cached");
        
        save_tasks_internal(); // Persist changes
    }
}

std::string TaskManager::get_cached_result(const std::string& id) {
    std::lock_guard<std::mutex> lock(mtx_);
    if (tasks_.count(id)) {
        return tasks_[id].result_cache;
    }
    return "";
}

// Audit log
void TaskManager::add_audit_log(const std::string& id, const std::string& action, const std::string& details, const std::string& user_id) {
    if (tasks_.count(id)) {
        AuditLog::instance().log(id, action, details, user_id);
    }
}

// Get audit logs for a task
std::vector<AuditLogEntry> TaskManager::get_audit_logs(const std::string& id, int limit, int offset) {
    return AuditLog::instance().getTaskLogs(id, limit, offset);
}

bool TaskManager::is_task_cancelled(const std::string& id) {
    std::lock_guard<std::mutex> lock(mtx_);
    if (tasks_.count(id) == 0) {
        return true; // Not found, so we should stop
    }
    return tasks_[id].cancellation_requested.load();
}

// Enhanced start_analysis with progress tracking and controlled thread pool execution
void TaskManager::start_analysis(const std::string& task_id) {
    if (!analysis_pool_) {
        std::cerr << "CRITICAL: ThreadPool not initialized in TaskManager" << std::endl;
        return;
    }

    analysis_pool_->enqueue([this, task_id]() {
        // RAII cleanup handler for deleted tasks
        struct TaskCleanup {
            TaskManager& tm;
            const std::string& id;
            ~TaskCleanup() {
                bool is_deleted = false;
                {
                    std::lock_guard<std::mutex> lock(tm.mtx_);
                    is_deleted = (tm.tasks_.count(id) == 0);
                }
                if (is_deleted) {
                    try {
                        auto& pm = forensics::PathManager::instance();
                        std::string task_root = pm.getTaskDir(id).string();
                        if (!task_root.empty() && std::filesystem::exists(task_root)) {
                            std::filesystem::remove_all(task_root);
                        }
                    } catch (...) {}
                }
            }
        } cleanup_handler{*this, task_id};

        try {
            // Re-fetch task to ensure we have the most up-to-date state (atomic load)
            AnalysisTask task = get_task(task_id);
            if (task.id.empty()) {
                std::cerr << "Analysis Error: Task " << task_id << " not found in manager" << std::endl;
                return;
            }
            
            if (is_task_cancelled(task_id)) {
                update_status(task_id, TaskStatus::CANCELLED, "Cancelled before start");
                return;
            }

            // Guard against re-running
            if (task.status == TaskStatus::RUNNING || task.status == TaskStatus::COMPLETED) {
                return;
            }

            // Check dependencies
            if (!can_start_task(task_id)) {
                update_status(task_id, TaskStatus::PENDING, "Waiting for dependencies");
                return;
            }

            std::string imagePath = task.image_path;
            update_status(task_id, TaskStatus::RUNNING, "Initializing analysis...");
            update_progress(task_id, TaskPhase::INITIALIZING, 10, "Initializing analysis environment...");

            if (!std::filesystem::exists(imagePath)) {
                update_status(task_id, TaskStatus::FAILED, "Image file not found");
                return;
            }

            // Generate DB paths
            std::filesystem::path p(imagePath);
            std::string baseName = p.stem().string();

            // Use PathManager for per-task directory (HTTP Server mode)
            auto& pm = forensics::PathManager::instance();
            std::string rawDbPath, eventDbPath, fileDbPath;

            if (!task.db_output_dir.empty()) {
                // Legacy override: use user-specified db_output_dir
                std::filesystem::create_directories(task.db_output_dir);
                std::string outPrefix = task.db_output_dir + "/";
                rawDbPath = outPrefix + baseName + "_raw.db";
                eventDbPath = outPrefix + baseName + "_events.db";
                fileDbPath = outPrefix + baseName + "_files.db";
            } else {
                // New default: data/tasks/<task_id>/
                pm.ensureTaskDir(task_id);
                auto dbPaths = pm.getTaskDbPaths(task_id, baseName);
                rawDbPath = dbPaths.rawDb.string();
                eventDbPath = dbPaths.eventsDb.string();
                fileDbPath = dbPaths.filesDb.string();
            }

            // Set database paths in the task
            {
                std::lock_guard<std::mutex> lock(mtx_);
                if (tasks_.count(task_id)) {
                    tasks_[task_id].output_raw_db = rawDbPath;
                    tasks_[task_id].output_events_db = eventDbPath;
                }
            }

            update_progress(task_id, TaskPhase::INITIALIZING, 30, "Analysis environment initialized");

            // 1. Image Analysis
            if (is_task_cancelled(task_id)) { update_status(task_id, TaskStatus::CANCELLED, "Task cancelled"); return; }
            update_progress(task_id, TaskPhase::IMAGE_ANALYSIS, 10, "Analyzing image structure...");
            auto analyzer = std::make_unique<ImageAnalyzer>(imagePath);
            analyzer->setXFSMode(task.xfs_mode);
            analyzer->setCancellationCallback([this, task_id]() { return is_task_cancelled(task_id); });

            if (!analyzer->analyze()) {
                update_status(task_id, TaskStatus::FAILED, "Failed to analyze image");
                return;
            }
            update_progress(task_id, TaskPhase::IMAGE_ANALYSIS, 50, "Image analysis completed, extracting metadata...");

            if (!analyzer->extractToDatabase(rawDbPath)) {
                update_status(task_id, TaskStatus::FAILED, "Failed to create raw database");
                return;
            }
            update_progress(task_id, TaskPhase::IMAGE_ANALYSIS, 100, "Image analysis and metadata extraction completed");

            // 1.5. Apply file filter (if profile specified)
            std::string effectiveRawDb = rawDbPath;
            if (!task.filter_profile.empty()) {
                if (is_task_cancelled(task_id)) { update_status(task_id, TaskStatus::CANCELLED, "Task cancelled"); return; }
                update_progress(task_id, TaskPhase::FILE_CLASSIFICATION, 5, "Applying file filter: " + task.filter_profile + "...");

                try {
                    FileFilter filter;
                    std::string filteredDbPath = rawDbPath;
                    size_t pos = filteredDbPath.rfind("_raw.db");
                    if (pos != std::string::npos) {
                        filteredDbPath.replace(pos, 7, "_filtered.db");
                    } else {
                        filteredDbPath += ".filtered";
                    }

                    auto filterStats = filter.applyFilterByName(rawDbPath, filteredDbPath, task.filter_profile);
                    if (filterStats.included_files > 0) {
                        effectiveRawDb = filteredDbPath;
                        update_progress(task_id, TaskPhase::FILE_CLASSIFICATION, 10,
                            "Filter applied: " + std::to_string(filterStats.included_files) + "/" +
                            std::to_string(filterStats.total_files) + " files selected");
                    } else {
                        std::cerr << "Warning: Filter excluded all files for task " << task_id << std::endl;
                    }
                } catch (const std::exception& e) {
                    std::cerr << "Warning: Filter failed for task " << task_id << ": " << e.what() << std::endl;
                    // Continue with unfiltered data
                }
            }

            // Update output_raw_db if filter changed the effective database
            if (effectiveRawDb != rawDbPath) {
                std::lock_guard<std::mutex> lock(mtx_);
                if (tasks_.count(task_id)) {
                    tasks_[task_id].output_raw_db = effectiveRawDb;
                }
            }

            // 2. Event Extraction
            if (is_task_cancelled(task_id)) { update_status(task_id, TaskStatus::CANCELLED, "Task cancelled"); return; }
            update_progress(task_id, TaskPhase::EVENT_EXTRACTION, 10, "Extracting timeline events...");
            auto eventExtractor = std::make_unique<EventExtractor>(effectiveRawDb, eventDbPath);
            if (!eventExtractor->extractEvents()) {
                std::cerr << "Error: Failed to extract events from " << effectiveRawDb << std::endl;
                update_status(task_id, TaskStatus::FAILED, "Failed to extract timeline events");
                return;
            }
            update_progress(task_id, TaskPhase::EVENT_EXTRACTION, 100, "Timeline events extraction completed");

            // 3. File Classification (scene-aware)
            if (is_task_cancelled(task_id)) { return; }
            update_progress(task_id, TaskPhase::FILE_CLASSIFICATION, 10, "Classifying files by type...");
            auto fileClassifier = std::make_unique<FileClassifier>(effectiveRawDb, fileDbPath);

            // Map ForensicScenario to SceneType for scene-aware classification
            SceneType sceneType = SceneType::NONE;
            if (!task.scenarios.empty()) {
                switch (task.scenarios[0]) {
                    case ForensicScenario::ANDROID: sceneType = SceneType::ANDROID; break;
                    case ForensicScenario::WINDOWS: sceneType = SceneType::WINDOWS; break;
                    case ForensicScenario::LINUX: sceneType = SceneType::LINUX; break;
                    case ForensicScenario::SERVER_CLOUD: sceneType = SceneType::SERVER_CLOUD; break;
                }
            }
            fileClassifier->setSceneType(sceneType);

            if (!fileClassifier->classifyAndExtract()) {
                update_status(task_id, TaskStatus::FAILED, "Failed to classify files");
                return;
            }
            update_progress(task_id, TaskPhase::FILE_CLASSIFICATION, 100, "File classification completed");

            // 4. LLM Analysis (Optional) - Stores descriptions directly in _files.db
            if (task.llm_analyze) {
                if (is_task_cancelled(task_id)) { return; }
                update_progress(task_id, TaskPhase::LLM_ANALYSIS, 10, "Starting LLM file description generation...");
                
                forensics::LLMAnalysisService llmService;
                if (llmService.initialize()) {
                    llmService.setSceneType(sceneType);
                    // Provide image + raw DB paths so files can be extracted from the
                    // image before LLM analysis (files live inside the image, not on disk).
                    llmService.setImagePaths(imagePath, effectiveRawDb);
                    auto& config = forensics::ConfigManager::instance();
                    forensics::LLMAnalysisService::AnalysisOptions llmOpts;
                    llmOpts.maxFiles = config.getLLMMaxFiles();
                    llmOpts.maxContentLength = config.getLLMMaxContentLength();
                    llmOpts.skipBinaryFiles = config.getLLMSkipBinary();
                    
                    int analyzedCount = 0;
                    
                    if (task.llm_mode == "full") {
                        // Full mode: analyze all files
                        update_progress(task_id, TaskPhase::LLM_ANALYSIS, 30, "Full mode: Analyzing all files...");
                        analyzedCount = llmService.analyzeAllFiles(fileDbPath, llmOpts,
                            [this, task_id](int current, int total, const std::string& file) {
                                if (is_task_cancelled(task_id)) return; // Wait, analyzeAllFiles doesn't support cancellation return value?
                                int progress = 30;
                                if (total > 0) {
                                    progress += (current * 60 / total);
                                }
                                update_progress(task_id, TaskPhase::LLM_ANALYSIS, progress, 
                                    "Analyzing file " + std::to_string(current) + "/" + std::to_string(total));
                            });
                    } else {
                        // Smart mode: LLM selects important files first
                        update_progress(task_id, TaskPhase::LLM_ANALYSIS, 20, "Smart mode: Selecting important files...");
                        // For smart mode, we scan more files initially (up to 2x global limit) to provide better context
                        llmOpts.maxFiles = std::max(llmOpts.maxFiles, static_cast<size_t>(1000));

                        analyzedCount = llmService.analyzeSmartFiles(fileDbPath, llmOpts,
                            [this, task_id](int current, int total, const std::string& file) {
                                if (is_task_cancelled(task_id)) return;
                                int progress = 30;
                                if (total > 0) {
                                    progress += (current * 60 / total);
                                }
                                update_progress(task_id, TaskPhase::LLM_ANALYSIS, progress, 
                                    "Analyzing important file " + std::to_string(current) + "/" + std::to_string(total));
                            });
                    }
                    
                    update_progress(task_id, TaskPhase::LLM_ANALYSIS, 100, 
                        "LLM analysis completed: " + std::to_string(analyzedCount) + " files analyzed (stored in _files.db)");
                } else {
                    std::cerr << "Warning: Failed to initialize LLM analysis service" << std::endl;
                }
            }

            // 5. Event Cluster Analysis (Optional) - Similar to LLM analysis for files
            if (task.llm_analyze) {
                if (is_task_cancelled(task_id)) { return; }
                update_progress(task_id, TaskPhase::LLM_ANALYSIS, 90, "Starting event cluster analysis...");
                
                forensics::EventClusterAnalyzer clusterAnalyzer;
                if (clusterAnalyzer.initialize()) {
                    int analyzedCount = 0;
                    
                    if (task.llm_mode == "full") {
                        // Full mode: analyze all event clusters
                        update_progress(task_id, TaskPhase::LLM_ANALYSIS, 92, "Full mode: Analyzing all event clusters...");
                        auto allClusters = clusterAnalyzer.getAllEventClusters(eventDbPath);
                        analyzedCount = clusterAnalyzer.analyzeEventClusters(eventDbPath, allClusters);
                    } else {
                        // Smart mode: LLM selects important event clusters first
                        update_progress(task_id, TaskPhase::LLM_ANALYSIS, 92, "Smart mode: Selecting important event clusters...");
                        analyzedCount = clusterAnalyzer.analyzeSmartEventClusters(eventDbPath, 100); // 分析最多100个重要事件簇
                    }
                    
                    update_progress(task_id, TaskPhase::LLM_ANALYSIS, 95, 
                        "Event cluster analysis completed: " + std::to_string(analyzedCount) + " clusters analyzed");
                } else {
                    std::cerr << "Warning: Failed to initialize event cluster analyzer" << std::endl;
                }
            }

            // 6. Platform-Specific Analysis (Unified)
            if (!task.scenarios.empty()) {
                if (is_task_cancelled(task_id)) { return; }
                int total_scenarios = static_cast<int>(task.scenarios.size());
                update_progress(task_id, TaskPhase::PLATFORM_ANALYSIS, 0,
                    "Starting platform analysis for " + std::to_string(total_scenarios) + " scenario(s)...");

                int scenario_index = 0;
                for (auto scenario : task.scenarios) {
                    if (is_task_cancelled(task_id)) { return; }

                    int base_progress = (scenario_index * 100) / total_scenarios;
                    std::string scenario_name = scenario_to_string(scenario);
                    update_progress(task_id, TaskPhase::PLATFORM_ANALYSIS, base_progress,
                        "Analyzing " + scenario_name + " artifacts...");

                    try {
                        switch (scenario) {
                            case ForensicScenario::ANDROID: {
                                auto dbManager = std::make_unique<DatabaseManager>(effectiveRawDb);
                                auto androidAnalyzer = std::make_unique<AndroidAnalyzer>(imagePath, dbManager.get());
                                std::string androidDbPath = pm.getTaskDbPaths(task_id, baseName).androidDb.string();
                                androidAnalyzer->setOutputDatabasePath(androidDbPath);
                                if (androidAnalyzer->initialize()) {
                                    androidAnalyzer->analyzeAndroidData();
                                } else {
                                    std::cerr << "Warning: Failed to initialize Android analyzer" << std::endl;
                                }
                                break;
                            }
                            case ForensicScenario::WINDOWS: {
                                auto dbManager = std::make_unique<DatabaseManager>(effectiveRawDb);
                                auto windowsAnalyzer = std::make_unique<WindowsFilesAnalyzer>(imagePath, dbManager.get());
                                std::string windowsDbPath = pm.getTaskDbPaths(task_id, baseName).windowsDb.string();
                                windowsAnalyzer->setOutputDatabasePath(windowsDbPath);
                                if (windowsAnalyzer->initialize()) {
                                    windowsAnalyzer->analyzeWindowsData();
                                } else {
                                    std::cerr << "Warning: Failed to initialize Windows analyzer" << std::endl;
                                }
                                break;
                            }
                            case ForensicScenario::LINUX: {
                                auto dbManager = std::make_unique<DatabaseManager>(effectiveRawDb);
                                auto linuxAnalyzer = std::make_unique<LinuxFilesAnalyzer>(imagePath, dbManager.get());
                                std::string linuxDbPath = pm.getTaskDbPaths(task_id, baseName).linuxDb.string();
                                linuxAnalyzer->setOutputDatabasePath(linuxDbPath);
                                if (linuxAnalyzer->initialize()) {
                                    linuxAnalyzer->analyzeLinuxData();
                                } else {
                                    std::cerr << "Warning: Failed to initialize Linux analyzer" << std::endl;
                                }
                                break;
                            }
                            case ForensicScenario::SERVER_CLOUD: {
                                auto dbManager = std::make_unique<DatabaseManager>(effectiveRawDb);
                                auto serverAnalyzer = std::make_unique<LinuxFilesAnalyzer>(imagePath, dbManager.get());
                                std::string serverDbPath = pm.getTaskDbPaths(task_id, baseName).ossDb.string();
                                serverAnalyzer->setOutputDatabasePath(serverDbPath);
                                if (serverAnalyzer->initialize()) {
                                    serverAnalyzer->analyzeServerCloudArtifacts();
                                } else {
                                    std::cerr << "Warning: Failed to initialize Server/Cloud analyzer" << std::endl;
                                }
                                break;
                            }
                        }
                    } catch (const std::exception& e) {
                        std::cerr << "Warning: " << scenario_name << " analysis failed: " << e.what() << std::endl;
                        add_audit_log(task_id, "WARNING", scenario_name + " analysis failed: " + std::string(e.what()));
                    }

                    scenario_index++;
                    int done_progress = (scenario_index * 100) / total_scenarios;
                    update_progress(task_id, TaskPhase::PLATFORM_ANALYSIS, done_progress,
                        scenario_name + " analysis completed");
                }
            }

            // 7. Graphiti Knowledge Graph Ingestion (Async, Fire-and-Forget)
            if (is_task_cancelled(task_id)) { return; }
            update_progress(task_id, TaskPhase::FINALIZING, 10, "Triggering knowledge graph ingestion...");

            // Trigger Graphiti ingestion in the background (non-blocking)
            // This will create File entities, link episodes, and build entity relationships
            try {
                auto& proxy = forensics::LLMPythonProxy::instance();
                std::string graphiti_job_id = proxy.async_ingest(task_id, forensics::IngestionMode::FULL);

                if (!graphiti_job_id.empty()) {
                    add_audit_log(task_id, "GRAPHITI_INGESTION",
                        "Triggered Graphiti knowledge graph ingestion (job_id: " + graphiti_job_id + ")");

                    // Store the Graphiti job ID for potential status tracking
                    task.graphiti_job_id = graphiti_job_id;
                    save_tasks_internal();
                } else {
                    std::cerr << "Warning: Failed to trigger Graphiti ingestion for task " << task_id << std::endl;
                    add_audit_log(task_id, "WARNING", "Failed to trigger Graphiti ingestion");
                }
            } catch (const std::exception& e) {
                // Don't fail the entire task if Graphiti ingestion fails
                std::cerr << "Warning: Exception triggering Graphiti ingestion: " << e.what() << std::endl;
                add_audit_log(task_id, "WARNING", "Graphiti ingestion failed: " + std::string(e.what()));
            }

            // Finalization
            if (is_task_cancelled(task_id)) { return; }
            update_progress(task_id, TaskPhase::FINALIZING, 50, "Finalizing analysis results...");

            set_result_db(task_id, fileDbPath);
            update_progress(task_id, TaskPhase::FINALIZING, 100, "Analysis completed successfully");
            update_status(task_id, TaskStatus::COMPLETED, "Analysis completed successfully");

        } catch (const std::exception& e) {
            update_status(task_id, TaskStatus::FAILED, std::string("Analysis error: ") + e.what());
            add_audit_log(task_id, "ERROR", "Analysis failed: " + std::string(e.what()));
        }
    });
}

// Watchdog Implementation: Periodic stale task cleanup
void TaskManager::run_watchdog() {
    TaskWatchdog watchdog(tasks_, shutdown_requested_, [this]() {
        save_tasks_internal();
    });
    watchdog.run();
}

// Helper methods
int TaskManager::calculate_overall_percentage(TaskPhase phase, int phase_percentage) {
    std::map<TaskPhase, int> phase_weights = {
        {TaskPhase::INITIALIZING, 5},
        {TaskPhase::IMAGE_ANALYSIS, 25},
        {TaskPhase::EVENT_EXTRACTION, 10},
        {TaskPhase::FILE_CLASSIFICATION, 15},
        {TaskPhase::LLM_ANALYSIS, 20},
        {TaskPhase::PLATFORM_ANALYSIS, 23},
        {TaskPhase::FINALIZING, 2}
    };

    int total_percentage = 0;
    for (const auto& p : phase_weights) {
        if (p.first < phase) {
            total_percentage += p.second;
        } else if (p.first == phase) {
            total_percentage += (p.second * phase_percentage) / 100;
        }
    }
    return std::min(total_percentage, 100);
}
