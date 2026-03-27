#include "TaskWatchdog.h"
#include <iostream>
#include <thread>
#include <chrono>

namespace forensics {

TaskWatchdog::TaskWatchdog(
    std::map<std::string, AnalysisTask>& tasks,
    const std::atomic<bool>& shutdown,
    std::function<void()> save_callback)
    : tasks_(tasks)
    , shutdown_requested_(shutdown)
    , save_callback_(std::move(save_callback)) {
}

void TaskWatchdog::run() {
    while (!shutdown_requested_) {
        // Run check every 60 seconds
        std::this_thread::sleep_for(std::chrono::seconds(60));
        if (shutdown_requested_) break;

        auto now_system = std::chrono::system_clock::now();
        auto now_steady = std::chrono::steady_clock::now();
        bool changed = false;

        for (auto& [id, task] : tasks_) {
            // Case A: PENDING tasks stuck for more than 30 minutes (Scheduler loss)
            if (task.status == TaskStatus::PENDING) {
                auto elapsed = std::chrono::duration_cast<std::chrono::minutes>(
                    now_system - task.created_time).count();
                if (elapsed > 30) {
                    task.status = TaskStatus::FAILED;
                    task.message = "Stale task detected (Pending timeout)";
                    task.error_details = "The task remained in pending state for over 30 minutes. This usually indicates a system scheduling failure.";
                    task.completed_time = now_system;
                    changed = true;
                    std::cout << "[Watchdog] Failed stale pending task: " << id << std::endl;
                }
            }

            // Case B: RUNNING tasks with no progress update for 15 minutes (C++ thread hang)
            if (task.status == TaskStatus::RUNNING) {
                auto elapsed = std::chrono::duration_cast<std::chrono::minutes>(
                    now_steady - task.progress.phase_start_time).count();
                if (elapsed > 15) {
                    task.status = TaskStatus::FAILED;
                    task.message = "Stale task detected (Execution timeout)";
                    task.error_details = "The task did not report any progress for 15 minutes. It has been marked as failed due to inactivity.";
                    task.completed_time = now_system;
                    changed = true;
                    std::cout << "[Watchdog] Failed hung running task: " << id << std::endl;
                }
            }
        }

        if (changed && save_callback_) {
            save_callback_();
        }
    }
}

} // namespace forensics
