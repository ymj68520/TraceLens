#include "TaskPersistence.h"
#include "TaskSerialization.h"
#include "PathManager/PathManager.h"
#include <algorithm>
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

            // Fix up state for restarted tasks (Recovery Logic).
            //
            // A task interrupted mid-run is no longer reported as FAILED when it
            // left a stage ledger behind: that ledger is exactly the record of
            // what was finished, so the task is INTERRUPTED — resumable with the
            // same id and directory. Tasks without a ledger (or whose ledger is
            // empty) keep the old, honest FAILED treatment: there is nothing to
            // resume from, so they must be recreated.
            if (task.status == TaskStatus::RUNNING || task.status == TaskStatus::PENDING) {
                const bool hasLedger = std::any_of(
                    task.metadata.begin(), task.metadata.end(),
                    [](const auto& kv) {
                        return kv.first.rfind("stage.", 0) == 0 && !kv.second.empty();
                    });
                task.interrupted_by_restart = true;
                if (hasLedger) {
                    task.status = TaskStatus::INTERRUPTED;
                    task.message = "Interrupted by server restart (resumable)";
                    task.error_details =
                        "The server was restarted while this task was running. Completed stages "
                        "were preserved; use \"continue analysis\" to resume from the last "
                        "finished stage.";
                    runningTaskIds.insert(task.id);
                } else {
                    task.status = TaskStatus::FAILED;
                    task.message = "Interrupted by server restart";
                    task.error_details = "The server was restarted while this task was in queue or running. Please delete and recreate if necessary.";
                }

                // completed_time 记录的是"系统中断于该时刻"（非任务真实运行
                // 时长终点），前端据此以"中断于"语义展示。
                task.completed_time = std::chrono::system_clock::now();
            } else if (task.status == TaskStatus::FAILED && !task.interrupted_by_restart
                       && (task.message.find("Interrupted by server restart") != std::string::npos
                           || task.error_details.find("The server was restarted") != std::string::npos)) {
                // 历史兼容：加标记字段之前被重启中断的任务没有持久化该标志，
                // 依据恢复逻辑写入的特征文案补记，保证前端统一按"中断于"展示。
                task.interrupted_by_restart = true;
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
