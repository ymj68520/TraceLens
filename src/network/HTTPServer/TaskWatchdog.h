#pragma once

#include <string>
#include <map>
#include <atomic>
#include <functional>
#include "TaskManager.h"

namespace forensics {

/**
 * @brief Task watchdog for stale task detection
 * Monitors tasks and marks stale tasks as failed
 */
class TaskWatchdog {
public:
    /**
     * @brief Constructor
     * @param tasks Reference to tasks map
     * @param shutdown Flag to signal shutdown
     * @param save_callback Callback to save tasks when state changes
     */
    TaskWatchdog(
        std::map<std::string, AnalysisTask>& tasks,
        const std::atomic<bool>& shutdown,
        std::function<void()> save_callback);

    /**
     * @brief Run watchdog loop
     * Checks for stale tasks every 60 seconds
     */
    void run();

private:
    std::map<std::string, AnalysisTask>& tasks_;
    const std::atomic<bool>& shutdown_requested_;
    std::function<void()> save_callback_;
};

} // namespace forensics
