#include "TaskSerialization.h"
#include "../../analyzers/ImageAnalyzer/ImageAnalyzerDataTypes.h"
#include "PathManager/PathManager.h"

namespace forensics {

// Enum serialization
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

NLOHMANN_JSON_SERIALIZE_ENUM(ForensicScenario, {
    {ForensicScenario::ANDROID, "ANDROID"},
    {ForensicScenario::WINDOWS, "WINDOWS"},
    {ForensicScenario::LINUX, "LINUX"},
    {ForensicScenario::SERVER_CLOUD, "SERVER_CLOUD"}
})

void to_json(nlohmann::json& j, const TaskProgress& p) {
    j = nlohmann::json{
        {"current_phase", p.current_phase},
        {"phase_percentage", p.phase_percentage},
        {"overall_percentage", p.overall_percentage},
        {"phase_description", p.phase_description}
    };
}

void from_json(const nlohmann::json& j, TaskProgress& p) {
    j.at("current_phase").get_to(p.current_phase);
    j.at("phase_percentage").get_to(p.phase_percentage);
    j.at("overall_percentage").get_to(p.overall_percentage);
    j.at("phase_description").get_to(p.phase_description);
    p.phase_start_time = std::chrono::steady_clock::now();
}

void to_json(nlohmann::json& j, const AnalysisTask& t) {
    j["id"] = t.id;
    j["image_path"] = t.image_path;
    j["status"] = t.status;
    j["message"] = t.message;
    j["output_files_db"] = t.output_files_db;
    j["output_raw_db"] = t.output_raw_db;
    j["output_events_db"] = t.output_events_db;
    j["priority"] = t.priority;
    to_json(j["progress"], t.progress);
    j["result_cache"] = t.result_cache;
    j["scenarios"] = t.scenarios;
    j["android_analyze"] = t.get_android_analyze();  // Backward compat
    j["xfs_mode"] = t.xfs_mode;
    j["db_output_dir"] = t.db_output_dir;
    j["error_details"] = t.error_details;
    j["metadata"] = t.metadata;
    j["llm_analyze"] = t.llm_analyze;
    j["llm_mode"] = t.llm_mode;
    j["output_descriptions_db"] = t.output_descriptions_db;
    j["case_description"] = t.case_description;
    j["filter_profile"] = t.filter_profile;

    j["extraction_directory"] = forensics::PathManager::instance().getTaskExtractDir(t.id).string();

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
    from_json(j.at("progress"), t.progress);
    if(j.contains("result_cache")) j.at("result_cache").get_to(t.result_cache);
    // Backward compat: handle scenarios field
    if (j.contains("scenarios")) {
        j.at("scenarios").get_to(t.scenarios);
    } else if (j.contains("android_analyze") && j["android_analyze"].get<bool>()) {
        // Old format: convert android_analyze: true → scenarios: [ANDROID]
        t.scenarios = {ForensicScenario::ANDROID};
    }
    if(j.contains("xfs_mode")) j.at("xfs_mode").get_to(t.xfs_mode);
    if(j.contains("db_output_dir")) j.at("db_output_dir").get_to(t.db_output_dir);
    if(j.contains("error_details")) j.at("error_details").get_to(t.error_details);
    if(j.contains("metadata")) j.at("metadata").get_to(t.metadata);
    if(j.contains("llm_analyze")) j.at("llm_analyze").get_to(t.llm_analyze);
    if(j.contains("llm_mode")) j.at("llm_mode").get_to(t.llm_mode);
    if(j.contains("output_descriptions_db")) j.at("output_descriptions_db").get_to(t.output_descriptions_db);
    if(j.contains("case_description")) j.at("case_description").get_to(t.case_description);
    if(j.contains("filter_profile")) j.at("filter_profile").get_to(t.filter_profile);

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
    
    t.execution_start_time = std::chrono::steady_clock::now();
    t.cancellation_requested = false;
}

} // namespace forensics
