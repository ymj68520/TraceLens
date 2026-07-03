#include "RouteHelpers.h"
#include "../TaskManager.h"
#include "../../core/PathManager/PathManager.h"
#include <random>
#include <sstream>
#include <stdexcept>
#include <cstdlib>

namespace forensics {

void RouteHelpers::add_cors_headers(crow::response& res) {
    // Origin is configurable via CORS_ALLOW_ORIGIN so deployments can restrict
    // it (e.g. to a specific dashboard host). Defaults to "*" for backward
    // compatibility / local development.
    const char* origin = std::getenv("CORS_ALLOW_ORIGIN");
    res.set_header("Access-Control-Allow-Origin", (origin && *origin) ? origin : "*");
    res.set_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
    res.set_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With");
}

std::string RouteHelpers::generate_job_id() {
    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_int_distribution<> dis(0, 15);
    const char* hex = "0123456789abcdef";
    std::stringstream ss;
    ss << "ext-";
    for (int i = 0; i < 8; i++) {
        ss << hex[dis(gen)];
    }
    return ss.str();
}

std::string RouteHelpers::get_database_path(const std::string& task_id, const std::string& db_type) {
    auto& task_manager = TaskManager::instance();
    AnalysisTask task = task_manager.get_task(task_id);
    if (task.id.empty()) {
        throw std::runtime_error("Task not found: " + task_id);
    }

    if (db_type == "raw") {
        return task.output_raw_db;
    } else if (db_type == "events") {
        return task.output_events_db;
    } else if (db_type == "files") {
        return task.output_files_db;
    } else if (db_type == "android") {
        if (task.metadata.find("android_db") != task.metadata.end()) {
            return task.metadata.at("android_db");
        }
        return task.output_raw_db.substr(0, task.output_raw_db.find_last_of('.')) + "_android.db";
    } else if (db_type == "dll") {
        if (task.metadata.find("dll_db") != task.metadata.end()) {
            return task.metadata.at("dll_db");
        }
        return task.output_raw_db.substr(0, task.output_raw_db.find_last_of('.')) + "_dll.db";
    } else if (db_type == "memory") {
        if (task.metadata.find("memory_db") != task.metadata.end()) {
            return task.metadata.at("memory_db");
        }
        // The MemoryAnalyzer (CLI + runMemoryAnalysis) writes "<base>_memory.db",
        // deriving <base> from the image stem — NOT from the "_raw.db" artifact.
        // Strip a trailing "_raw" so the fallback matches that file, e.g.
        // "/t/img_raw.db" -> "/t/img_memory.db" (not "/t/img_raw_memory.db").
        std::string stem = task.output_raw_db.substr(0, task.output_raw_db.find_last_of('.'));
        const std::string rawSuffix = "_raw";
        if (stem.size() >= rawSuffix.size() &&
            stem.compare(stem.size() - rawSuffix.size(), rawSuffix.size(), rawSuffix) == 0) {
            stem.erase(stem.size() - rawSuffix.size());
        }
        return stem + "_memory.db";
    } else {
        throw std::runtime_error("Unknown database type: " + db_type);
    }
}

std::string RouteHelpers::get_image_path_for_task(const std::string& task_id) {
    auto& task_manager = TaskManager::instance();
    AnalysisTask task = task_manager.get_task(task_id);
    if (task.id.empty()) {
        throw std::runtime_error("Task not found: " + task_id);
    }
    return task.image_path;
}

} // namespace forensics
