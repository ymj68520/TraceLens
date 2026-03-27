#include "TaskPersistence.h"
#include "TaskSerialization.h"
#include "PathManager/PathManager.h"
#include <fstream>
#include <filesystem>
#include <iostream>

namespace forensics {

namespace fs = std::filesystem;

void TaskPersistence::save_tasks(
    const std::map<std::string, AnalysisTask>& tasks,
    const std::string& tasksPath) {

    nlohmann::json j = nlohmann::json::array();
    for (const auto& pair : tasks) {
        nlohmann::json task_json;
        to_json(task_json, pair.second);
        j.push_back(task_json);
    }

    std::ofstream out(tasksPath);
    if (out.is_open()) {
        out << j.dump(4);
    } else {
        std::cerr << "CRITICAL: Failed to save tasks to " << tasksPath << std::endl;
    }
}

void TaskPersistence::load_tasks(
    std::map<std::string, AnalysisTask>& tasks,
    const std::string& tasksPath,
    std::unordered_set<std::string>& runningTaskIds) {

    std::ifstream in(tasksPath);
    if (!in.is_open()) {
        return; // File doesn't exist yet, that's ok
    }

    try {
        nlohmann::json j;
        in >> j;

        if (!j.is_array()) {
            std::cerr << "Invalid tasks JSON format" << std::endl;
            return;
        }

        for (const auto& element : j) {
            AnalysisTask task;
            from_json(element, task);

            // Fix up state for restarted tasks (Recovery Logic)
            if (task.status == TaskStatus::RUNNING || task.status == TaskStatus::PENDING) {
                task.status = TaskStatus::FAILED;
                task.message = "Interrupted by server restart";
                task.error_details = "The server was restarted while this task was in queue or running. Please delete and recreate if necessary.";

                // Reset timestamps to current for visibility
                task.completed_time = std::chrono::system_clock::now();
            }

            tasks[task.id] = task;
        }

        std::cout << "Loaded " << tasks.size() << " tasks from storage." << std::endl;

    } catch (const std::exception& e) {
        std::cerr << "Failed to load tasks: " << e.what() << std::endl;
    }
}

void TaskPersistence::cleanup_orphan_directories(
    const std::map<std::string, AnalysisTask>& tasks) {

    try {
        auto& pm = PathManager::instance();
        auto tasksDir = pm.getDataDir() / "tasks";

        if (!fs::exists(tasksDir)) {
            return;
        }

        for (const auto& entry : fs::directory_iterator(tasksDir)) {
            if (entry.is_directory()) {
                std::string dirName = entry.path().filename().string();

                // If directory name is a UUID (common for tasks) and not in tasks_ map
                if (tasks.count(dirName) == 0) {
                    std::cout << "[TaskPersistence] Cleaning up orphan task directory: " << dirName << std::endl;
                    fs::remove_all(entry.path());
                }
            }
        }
    } catch (...) {
        // Ignore errors during cleanup
    }
}

} // namespace forensics
