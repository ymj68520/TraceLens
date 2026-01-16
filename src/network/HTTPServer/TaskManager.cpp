#include "TaskManager.h"
#include <fstream>

// JSON serialization helpers
NLOHMANN_JSON_SERIALIZE_ENUM(TaskStatus, {
    {TaskStatus::PENDING, "PENDING"},
    {TaskStatus::RUNNING, "RUNNING"},
    {TaskStatus::COMPLETED, "COMPLETED"},
    {TaskStatus::FAILED, "FAILED"},
    {TaskStatus::CANCELLED, "CANCELLED"}
})

NLOHMANN_JSON_SERIALIZE_ENUM(TaskPriority, {
    {TaskPriority::LOW, "LOW"},
    {TaskPriority::NORMAL, "NORMAL"},
    {TaskPriority::HIGH, "HIGH"},
    {TaskPriority::CRITICAL, "CRITICAL"}
})

NLOHMANN_JSON_SERIALIZE_ENUM(TaskPhase, {
    {TaskPhase::INITIALIZING, "INITIALIZING"},
    {TaskPhase::IMAGE_ANALYSIS, "IMAGE_ANALYSIS"},
    {TaskPhase::EVENT_EXTRACTION, "EVENT_EXTRACTION"},
    {TaskPhase::FILE_CLASSIFICATION, "FILE_CLASSIFICATION"},
    {TaskPhase::LLM_ANALYSIS, "LLM_ANALYSIS"},
    {TaskPhase::ANDROID_ANALYSIS, "ANDROID_ANALYSIS"},
    {TaskPhase::FINALIZING, "FINALIZING"}
})

NLOHMANN_JSON_SERIALIZE_ENUM(XFSMode, {
    {XFSMode::Auto, "Auto"},
    {XFSMode::Native, "Native"},
    {XFSMode::Pure, "Pure"}
})

// Serialization for TaskProgress
void to_json(nlohmann::json& j, const TaskProgress& p) {
    j = nlohmann::json{
        {"current_phase", p.current_phase},
        {"phase_percentage", p.phase_percentage},
        {"overall_percentage", p.overall_percentage},
        {"phase_description", p.phase_description}
    };
    // Timestamps are transient for progress, but we could save them if needed
}

void from_json(const nlohmann::json& j, TaskProgress& p) {
    j.at("current_phase").get_to(p.current_phase);
    j.at("phase_percentage").get_to(p.phase_percentage);
    j.at("overall_percentage").get_to(p.overall_percentage);
    j.at("phase_description").get_to(p.phase_description);
    p.phase_start_time = std::chrono::steady_clock::now(); // Reset on load
}

// Serialization for AnalysisTask
void to_json(nlohmann::json& j, const AnalysisTask& t) {
    j = nlohmann::json{
        {"id", t.id},
        {"image_path", t.image_path},
        {"status", t.status},
        {"message", t.message},
        {"output_files_db", t.output_files_db},
        {"output_raw_db", t.output_raw_db},
        {"output_events_db", t.output_events_db},
        {"priority", t.priority},
        {"progress", t.progress},
        {"result_cache", t.result_cache},
        {"android_analyze", t.android_analyze},
        {"xfs_mode", t.xfs_mode},
        {"db_output_dir", t.db_output_dir},
        {"error_details", t.error_details},
        {"metadata", t.metadata},
        {"llm_analyze", t.llm_analyze},
        {"llm_mode", t.llm_mode},
        {"output_descriptions_db", t.output_descriptions_db}
    };
    
    // Convert timestamps to string/int for storage
    j["created_time"] = std::chrono::duration_cast<std::chrono::seconds>(t.created_time.time_since_epoch()).count();
    j["started_time"] = std::chrono::duration_cast<std::chrono::seconds>(t.started_time.time_since_epoch()).count();
    j["completed_time"] = std::chrono::duration_cast<std::chrono::seconds>(t.completed_time.time_since_epoch()).count();
}

void from_json(const nlohmann::json& j, AnalysisTask& t) {
    j.at("id").get_to(t.id);
    j.at("image_path").get_to(t.image_path);
    j.at("status").get_to(t.status);
    j.at("message").get_to(t.message);
    j.at("output_files_db").get_to(t.output_files_db);
    j.at("output_raw_db").get_to(t.output_raw_db);
    j.at("output_events_db").get_to(t.output_events_db);
    j.at("priority").get_to(t.priority);
    j.at("progress").get_to(t.progress);
    if(j.contains("result_cache")) j.at("result_cache").get_to(t.result_cache);
    if(j.contains("android_analyze")) j.at("android_analyze").get_to(t.android_analyze);
    if(j.contains("xfs_mode")) j.at("xfs_mode").get_to(t.xfs_mode);
    if(j.contains("db_output_dir")) j.at("db_output_dir").get_to(t.db_output_dir);
    if(j.contains("error_details")) j.at("error_details").get_to(t.error_details);
    if(j.contains("metadata")) j.at("metadata").get_to(t.metadata);
    if(j.contains("llm_analyze")) j.at("llm_analyze").get_to(t.llm_analyze);
    if(j.contains("llm_mode")) j.at("llm_mode").get_to(t.llm_mode);
    if(j.contains("output_descriptions_db")) j.at("output_descriptions_db").get_to(t.output_descriptions_db);

    // Restore timestamps
    if (j.contains("created_time")) {
        auto secs = j["created_time"].get<long long>();
        t.created_time = std::chrono::system_clock::time_point(std::chrono::seconds(secs));
    }
    if (j.contains("started_time")) {
        auto secs = j["started_time"].get<long long>();
        t.started_time = std::chrono::system_clock::time_point(std::chrono::seconds(secs));
    }
    if (j.contains("completed_time")) {
        auto secs = j["completed_time"].get<long long>();
        t.completed_time = std::chrono::system_clock::time_point(std::chrono::seconds(secs));
    }
    
    // Reset execution times
    t.execution_start_time = std::chrono::steady_clock::now();
    t.cancellation_requested = false;
}

TaskManager::TaskManager() {
    load_tasks();
}

void TaskManager::save_tasks() {
    // We don't lock here because this is usually called from within locked methods
    // OR we should verify call sites. 
    // Ideally we should make a helper that doesn't lock, or lock inside.
    // Given the simplicity, let's assume the public method locks, but for internal usage 
    // we might need to be careful. 
    // Actually, for safety, let's serialize to a local object then write to file outside lock if possible,
    // or just lock while writing.
    
    // Since this is called from methods that already lock, we should NOT lock again if we call it internally.
    // BUT we declared it as public, so it might be called externally.
    // Let's create a private helper `save_tasks_internal`? 
    // Or just putting the logic here.
    
    // FOR NOW: Let's assume we simply write to "tasks.json".
    // WARNING: Concurrent writes? The mutex `mtx_` protects memory state.
    // File writing should also be protected. Since all updates to `tasks_` are protected by `mtx_`,
    // if we put the save logic inside the locked sections, it's safe serialized.
    // However, writing to disk with lock held is bad for performance.
    // Optimization: Snapshot basic data, then write.
    
    // Let's implement it to write directly for now, but we need to call it from existing methods.
    
    nlohmann::json j = nlohmann::json::array();
    for(const auto& pair : tasks_) {
        j.push_back(pair.second);
    }
    
    std::ofstream out("tasks.json");
    if(out.is_open()) {
        out << j.dump(4);
    }
}

void TaskManager::load_tasks() {
    std::lock_guard<std::mutex> lock(mtx_);
    std::ifstream in("tasks.json");
    if(in.is_open()) {
        try {
            nlohmann::json j;
            in >> j;
            for(const auto& element : j) {
                AnalysisTask task = element;
                
                // Fix up state for restarted tasks
                if(task.status == TaskStatus::RUNNING) {
                    task.status = TaskStatus::FAILED;
                    task.message = "Interrupted by server restart";
                    task.error_details = "Server restarted during execution";
                }
                
                tasks_[task.id] = task;
            }
            std::cout << "Loaded " << tasks_.size() << " tasks from storage." << std::endl;
        } catch(const std::exception& e) {
            std::cerr << "Failed to load tasks: " << e.what() << std::endl;
        }
    }
}

// Enhanced task creation with priority and metadata
std::string TaskManager::create_task(const std::string& path, TaskPriority priority,
                       const std::map<std::string, std::string>& metadata,
                       const std::vector<TaskDependency>& dependencies) {
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
    new_task.android_analyze = false;
    new_task.xfs_mode = XFSMode::Auto;
    new_task.db_output_dir = "";
    new_task.cancellation_requested = false;
    new_task.error_details = "";
    new_task.metadata = metadata;

    tasks_[id] = new_task;

    // Add to priority queue
    task_queue_.push({priority, id});

    // Log creation
    add_audit_log(id, "CREATED", "Task created with priority " + std::to_string(static_cast<int>(priority)));
    
    save_tasks(); // Persist changes

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
        
        save_tasks(); // Persist changes
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
        
        save_tasks(); // Persist changes
    }
}

void TaskManager::set_android_analyze_options(const std::string& id, bool android_analyze, XFSMode xfs_mode, const std::string& db_output_dir) {
    std::lock_guard<std::mutex> lock(mtx_);
    if (tasks_.count(id)) {
        tasks_[id].android_analyze = android_analyze;
        tasks_[id].xfs_mode = xfs_mode;
        tasks_[id].db_output_dir = db_output_dir;
        
        save_tasks(); // Persist changes
    }
}

void TaskManager::set_llm_analyze_options(const std::string& id, bool llm_analyze, const std::string& llm_mode) {
    std::lock_guard<std::mutex> lock(mtx_);
    if (tasks_.count(id)) {
        tasks_[id].llm_analyze = llm_analyze;
        tasks_[id].llm_mode = llm_mode;
        add_audit_log(id, "LLM_CONFIG", "LLM analysis: " + std::string(llm_analyze ? "enabled" : "disabled") + ", mode: " + llm_mode);
        
        save_tasks(); // Persist changes
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
            {"android_analysis", phase_counts[TaskPhase::ANDROID_ANALYSIS]},
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
        
        save_tasks(); // Persist changes
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

// Enhanced start_analysis with progress tracking and cancellation support
void TaskManager::start_analysis(const std::string& task_id) {
    std::thread([this, task_id]() {
        try {
            AnalysisTask task = get_task(task_id);
            if (task.id.empty() || task.cancellation_requested) return;

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
            std::string outPrefix = "";
            if (!task.db_output_dir.empty()) {
                std::filesystem::create_directories(task.db_output_dir);
                outPrefix = task.db_output_dir + "/";
            }
            std::string rawDbPath = outPrefix + baseName + "_raw.db";
            std::string eventDbPath = outPrefix + baseName + "_events.db";
            std::string fileDbPath = outPrefix + baseName + "_files.db";

            // Set database paths in the task
            {
                std::lock_guard<std::mutex> lock(mtx_);
                tasks_[task_id].output_raw_db = rawDbPath;
                tasks_[task_id].output_events_db = eventDbPath;
            }

            update_progress(task_id, TaskPhase::INITIALIZING, 30, "Analysis environment initialized");

            // 1. Image Analysis
            if (task.cancellation_requested) { update_status(task_id, TaskStatus::CANCELLED, "Task cancelled"); return; }
            update_progress(task_id, TaskPhase::IMAGE_ANALYSIS, 10, "Analyzing image structure...");
            auto analyzer = std::make_unique<ImageAnalyzer>(imagePath);
            analyzer->setXFSMode(task.xfs_mode);

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

            // 2. Event Extraction
            if (task.cancellation_requested) { update_status(task_id, TaskStatus::CANCELLED, "Task cancelled"); return; }
            update_progress(task_id, TaskPhase::EVENT_EXTRACTION, 10, "Extracting timeline events...");
            auto eventExtractor = std::make_unique<EventExtractor>(rawDbPath, eventDbPath);
            if (!eventExtractor->extractEvents()) {
                std::cerr << "Warning: Failed to extract events" << std::endl;
            }
            update_progress(task_id, TaskPhase::EVENT_EXTRACTION, 100, "Timeline events extraction completed");

            // 3. File Classification
            if (task.cancellation_requested) { update_status(task_id, TaskStatus::CANCELLED, "Task cancelled"); return; }
            update_progress(task_id, TaskPhase::FILE_CLASSIFICATION, 10, "Classifying files by type...");
            auto fileClassifier = std::make_unique<FileClassifier>(rawDbPath, fileDbPath);
            if (!fileClassifier->classifyAndExtract()) {
                update_status(task_id, TaskStatus::FAILED, "Failed to classify files");
                return;
            }
            update_progress(task_id, TaskPhase::FILE_CLASSIFICATION, 100, "File classification completed");

            // 4. LLM Analysis (Optional) - Stores descriptions directly in _files.db
            if (task.llm_analyze) {
                if (task.cancellation_requested) { update_status(task_id, TaskStatus::CANCELLED, "Task cancelled"); return; }
                update_progress(task_id, TaskPhase::LLM_ANALYSIS, 10, "Starting LLM file description generation...");
                
                forensics::LLMAnalysisService llmService;
                if (llmService.initialize()) {
                    forensics::LLMAnalysisService::AnalysisOptions llmOpts;
                    llmOpts.maxFiles = 500;
                    llmOpts.maxContentLength = 10000;
                    llmOpts.skipBinaryFiles = true;
                    
                    int analyzedCount = 0;
                    
                    if (task.llm_mode == "full") {
                        // Full mode: analyze all files
                        update_progress(task_id, TaskPhase::LLM_ANALYSIS, 30, "Full mode: Analyzing all files...");
                        analyzedCount = llmService.analyzeAllFiles(fileDbPath, llmOpts,
                            [this, task_id](int current, int total, const std::string& file) {
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
                        analyzedCount = llmService.analyzeSmartFiles(fileDbPath, llmOpts,
                            [this, task_id](int current, int total, const std::string& file) {
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

            // 5. Android Analysis (Optional)
            if (task.android_analyze) {
                if (task.cancellation_requested) { update_status(task_id, TaskStatus::CANCELLED, "Task cancelled"); return; }
                update_progress(task_id, TaskPhase::ANDROID_ANALYSIS, 10, "Analyzing Android artifacts...");
                auto dbManager = std::make_unique<DatabaseManager>(rawDbPath);
                auto androidAnalyzer = std::make_unique<AndroidAnalyzer>(imagePath, dbManager.get());

                std::string androidDbPath = outPrefix + baseName + "_android.db";
                androidAnalyzer->setOutputDatabasePath(androidDbPath);

                if (androidAnalyzer->initialize()) {
                    androidAnalyzer->analyzeAndroidData();
                    update_progress(task_id, TaskPhase::ANDROID_ANALYSIS, 100, "Android analysis completed");
                } else {
                    std::cerr << "Warning: Failed to initialize Android analyzer" << std::endl;
                }
            }

            // Finalization
            if (task.cancellation_requested) { update_status(task_id, TaskStatus::CANCELLED, "Task cancelled"); return; }
            update_progress(task_id, TaskPhase::FINALIZING, 50, "Finalizing analysis results...");

            set_result_db(task_id, fileDbPath);
            update_progress(task_id, TaskPhase::FINALIZING, 100, "Analysis completed successfully");
            update_status(task_id, TaskStatus::COMPLETED, "Analysis completed successfully");

        } catch (const std::exception& e) {
            update_status(task_id, TaskStatus::FAILED, std::string("Analysis error: ") + e.what());
            add_audit_log(task_id, "ERROR", "Analysis failed: " + std::string(e.what()));
        }
    }).detach();
}

// Helper methods
int TaskManager::calculate_overall_percentage(TaskPhase phase, int phase_percentage) {
    std::map<TaskPhase, int> phase_weights = {
        {TaskPhase::INITIALIZING, 5},
        {TaskPhase::IMAGE_ANALYSIS, 40},
        {TaskPhase::EVENT_EXTRACTION, 20},
        {TaskPhase::FILE_CLASSIFICATION, 25},
        {TaskPhase::ANDROID_ANALYSIS, 8},
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
