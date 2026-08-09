#include "TaskHelpers.h"
#include "../TaskManager.h"
#include "../../core/PathManager/PathManager.h"
#include <chrono>
#include <filesystem>

namespace forensics {

using json = nlohmann::json;

nlohmann::json TaskHelpers::task_to_json(const AnalysisTask& task) {
    auto created_time = std::chrono::duration_cast<std::chrono::milliseconds>(
        task.created_time.time_since_epoch()).count();
    auto started_time = std::chrono::duration_cast<std::chrono::milliseconds>(
        task.started_time.time_since_epoch()).count();
    auto completed_time = std::chrono::duration_cast<std::chrono::milliseconds>(
        task.completed_time.time_since_epoch()).count();

    json dependencies_json = json::array();
    for (const auto& dep : task.dependencies) {
        dependencies_json.push_back(json{
            {"task_id", dep.task_id},
            {"required", dep.required}
        });
    }

    long long execution_time_seconds = 0;
    if (task.status == TaskStatus::COMPLETED || task.status == TaskStatus::FAILED) {
        execution_time_seconds = std::chrono::duration_cast<std::chrono::seconds>(
            task.completed_time - task.started_time).count();
    }

    // Build scenario_databases map
    json scenario_databases = json::object();
    auto& pm = forensics::PathManager::instance();
    auto dbPaths = pm.getTaskDbPaths(task.id);
    for (auto scenario : task.scenarios) {
        std::string key = scenario_to_string(scenario);
        std::string db_path;
        switch (scenario) {
            case ForensicScenario::ANDROID: db_path = dbPaths.androidDb.string(); break;
            case ForensicScenario::WINDOWS: db_path = dbPaths.windowsDb.string(); break;
            case ForensicScenario::LINUX: db_path = dbPaths.linuxDb.string(); break;
            case ForensicScenario::SERVER_CLOUD: db_path = dbPaths.ossDb.string(); break;
        }
        if (std::filesystem::exists(db_path)) {
            scenario_databases[key] = db_path;
        }
    }

    // Scenarios as string array for API
    json scenarios_json = json::array();
    for (auto s : task.scenarios) {
        scenarios_json.push_back(scenario_to_string(s));
    }

    return json{
        {"id", task.id},
        {"image_path", task.image_path},
        {"status", status_to_string(task.status)},
        {"priority", priority_to_string(task.priority)},
        {"message", task.message},
        {"output_files_db", task.output_files_db},
        {"output_raw_db", task.output_raw_db},
        {"output_events_db", task.output_events_db},
        {"progress", {
            {"current_phase", phase_to_string(task.progress.current_phase)},
            {"phase_percentage", task.progress.phase_percentage},
            {"overall_percentage", task.progress.overall_percentage},
            {"phase_description", task.progress.phase_description}
        }},
        {"timestamps", {
            {"created", created_time},
            {"started", started_time},
            {"completed", completed_time},
            {"execution_time_seconds", execution_time_seconds}
        }},
        {"scenarios", scenarios_json},
        {"scenario_databases", scenario_databases},
        {"android_analyze", task.get_android_analyze()},  // Backward compat
        {"android_source", task.android_source},
        {"llm_analyze", task.llm_analyze},
        {"llm_mode", task.llm_mode},
        {"case_description", task.case_description},
        {"xfs_mode", task.xfs_mode == XFSMode::Native ? "native" :
                   task.xfs_mode == XFSMode::Pure ? "pure" : "auto"},
        {"db_output_dir", task.db_output_dir},
        {"extraction_directory", forensics::PathManager::instance().getTaskExtractDir(task.id).string()},
        {"cancellation_requested", task.cancellation_requested.load()},
        {"dependencies", dependencies_json},
        {"dependents_count", task.dependents.size()},
        {"metadata", task.metadata},
        {"error_details", task.error_details}
    };
}

TaskPriority TaskHelpers::priority_from_string(const std::string& str) {
    if (str == "low") return TaskPriority::LOW;
    if (str == "normal") return TaskPriority::NORMAL;
    if (str == "high") return TaskPriority::HIGH;
    if (str == "critical") return TaskPriority::CRITICAL;
    return TaskPriority::NORMAL;
}

std::string TaskHelpers::priority_to_string(TaskPriority priority) {
    switch (priority) {
        case TaskPriority::LOW: return "low";
        case TaskPriority::NORMAL: return "normal";
        case TaskPriority::HIGH: return "high";
        case TaskPriority::CRITICAL: return "critical";
        default: return "normal";
    }
}

std::string TaskHelpers::status_to_string(TaskStatus status) {
    switch (status) {
        case TaskStatus::PENDING: return "pending";
        case TaskStatus::RUNNING: return "running";
        case TaskStatus::COMPLETED: return "completed";
        case TaskStatus::FAILED: return "failed";
        case TaskStatus::CANCELLED: return "cancelled";
        default: return "unknown";
    }
}

std::string TaskHelpers::phase_to_string(TaskPhase phase) {
    switch (phase) {
        case TaskPhase::INITIALIZING: return "initializing";
        case TaskPhase::IMAGE_ANALYSIS: return "image_analysis";
        case TaskPhase::EVENT_EXTRACTION: return "event_extraction";
        case TaskPhase::FILE_CLASSIFICATION: return "file_classification";
        case TaskPhase::LLM_ANALYSIS: return "llm_analysis";
        case TaskPhase::PLATFORM_ANALYSIS: return "platform_analysis";
        case TaskPhase::FINALIZING: return "finalizing";
        default: return "unknown";
    }
}

} // namespace forensics
