#include "TaskWatchdog.h"
#include "ConfigManager/ConfigManager.h"
#include <iostream>
#include <thread>
#include <chrono>

namespace forensics {

TaskWatchdog::TaskWatchdog(
    std::map<std::string, AnalysisTask>& tasks,
    const std::atomic<bool>& shutdown,
    std::function<void()> save_callback,
    std::mutex& task_mutex)
    : tasks_(tasks)
    , shutdown_requested_(shutdown)
    , save_callback_(std::move(save_callback))
    , task_mutex_(task_mutex) {
}

void TaskWatchdog::stop() {
    wait_cv_.notify_all();
}

void TaskWatchdog::run() {
    // Stale thresholds are configurable: real-image tasks with local/slow LLM
    // backends can legitimately spend tens of minutes inside a single LLM call
    // without a progress update. TASK_WATCHDOG_STALE_MINUTES / _PENDING_MINUTES.
    const long stale_minutes = []() {
        int v = ConfigManager::instance().getInt("TASK_WATCHDOG_STALE_MINUTES", 30);
        return v > 0 ? static_cast<long>(v) : 30L;
    }();
    const long pending_minutes = []() {
        int v = ConfigManager::instance().getInt("TASK_WATCHDOG_PENDING_MINUTES", 30);
        return v > 0 ? static_cast<long>(v) : 30L;
    }();

    while (!shutdown_requested_) {
        // Run check every 60 seconds. The owner joins this thread before
        // destroying the referenced task map.
        {
            std::unique_lock<std::mutex> waitLock(wait_mutex_);
            wait_cv_.wait_for(waitLock, std::chrono::seconds(1));
        }
        if (shutdown_requested_) break;

        auto now_system = std::chrono::system_clock::now();
        auto now_steady = std::chrono::steady_clock::now();
        bool changed = false;
        std::lock_guard<std::mutex> taskLock(task_mutex_);

        for (auto& [id, task] : tasks_) {
            // Case A: PENDING tasks stuck beyond the pending threshold (scheduler loss)
            if (task.status == TaskStatus::PENDING) {
                auto elapsed = std::chrono::duration_cast<std::chrono::minutes>(
                    now_system - task.created_time).count();
                if (elapsed > pending_minutes) {
                    task.cancellation_requested = true;
                    task.status = TaskStatus::FAILED;
                    task.message = "Stale task detected (Pending timeout)";
                    task.error_details = "The task remained in pending state for over " + std::to_string(pending_minutes) + " minutes. This usually indicates a system scheduling failure.";
                    task.completed_time = now_system;
                    changed = true;
                    std::cout << "[Watchdog] Failed stale pending task: " << id << std::endl;
                }
            }

            // Case B: RUNNING tasks with no progress update beyond the stale
            // threshold (C++ thread hang). LLM-heavy phases emit per-file /
            // per-cluster heartbeats, so this only trips on genuine hangs.
            if (task.status == TaskStatus::RUNNING) {
                auto elapsed = std::chrono::duration_cast<std::chrono::minutes>(
                    now_steady - task.progress.phase_start_time).count();
                if (elapsed > stale_minutes) {
                    task.cancellation_requested = true;
                    task.status = TaskStatus::FAILED;
                    task.message = "Stale task detected (Execution timeout)";
                    task.error_details = "The task did not report any progress for " + std::to_string(stale_minutes) + " minutes. It has been marked as failed due to inactivity.";
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
