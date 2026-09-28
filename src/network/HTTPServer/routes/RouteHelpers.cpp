#include "RouteHelpers.h"
#include "../TaskManager.h"
#include "../../core/PathManager/PathManager.h"
#include <random>
#include <sstream>
#include <stdexcept>
#include <cstdlib>
#include <filesystem>

namespace forensics {

void RouteHelpers::add_cors_headers(crow::response& res) {
    const char* field = std::getenv("TRACELENS_FIELD_AUTH");
    if (field && std::string(field) == "enabled") return; // same-origin field gateway
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

    // Task metadata stores absolute artifact paths.  After a repository or
    // deployment directory is moved, those paths can be stale even though the
    // task-owned databases are present under the current data directory.
    const auto db_paths = PathManager::instance().getTaskDbPaths(task_id);
    const auto resolve_task_db = [](const std::string& recorded,
                                    const std::filesystem::path& current) {
        std::error_code ec;
        if (!recorded.empty() && std::filesystem::is_regular_file(recorded, ec)) {
            return recorded;
        }
        // Preserve legacy artifact names such as raw.db.filtered while moving
        // them under the current task directory.
        if (!recorded.empty()) {
            const auto relocated = current.parent_path()
                / std::filesystem::path(recorded).filename();
            ec.clear();
            if (std::filesystem::is_regular_file(relocated, ec)) {
                return relocated.string();
            }
        }
        ec.clear();
        if (std::filesystem::is_regular_file(current, ec)) {
            return current.string();
        }
        // Preserve the recorded path in the eventual error when there is no
        // local replacement; otherwise report the canonical current location.
        return recorded.empty() ? current.string() : recorded;
    };

    if (db_type == "raw") {
        return resolve_task_db(task.output_raw_db, db_paths.rawDb);
    } else if (db_type == "events") {
        return resolve_task_db(task.output_events_db, db_paths.eventsDb);
    } else if (db_type == "files") {
        return resolve_task_db(task.output_files_db, db_paths.filesDb);
    } else if (db_type == "android") {
        std::error_code ec;
        const auto android_it = task.metadata.find("android_db");
        if (android_it != task.metadata.end()) {
            const auto recorded = resolve_task_db(android_it->second, db_paths.androidDb);
            if (std::filesystem::is_regular_file(recorded, ec)) return recorded;
        }
        ec.clear();
        if (std::filesystem::is_regular_file(db_paths.androidDb, ec)) {
            return db_paths.androidDb.string();
        }
        if (!task.output_files_db.empty()) {
            const auto files_db = resolve_task_db(task.output_files_db, db_paths.androidDb);
            ec.clear();
            if (std::filesystem::is_regular_file(files_db, ec) &&
                std::filesystem::path(files_db).filename() == "android.db") {
                return files_db;
            }
        }
        const auto dot = task.output_raw_db.find_last_of('.');
        const std::string fallback = dot == std::string::npos
            ? task.output_raw_db + "_android.db"
            : task.output_raw_db.substr(0, dot) + "_android.db";
        const auto resolved_fallback = resolve_task_db(fallback, db_paths.androidDb);
        ec.clear();
        if (std::filesystem::is_regular_file(resolved_fallback, ec)) return resolved_fallback;
        ec.clear();
        if (!task.output_files_db.empty() &&
            std::filesystem::is_regular_file(task.output_files_db, ec)) {
            return task.output_files_db;
        }
        return resolved_fallback;
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
