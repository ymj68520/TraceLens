#pragma once

#include <string>
#include <functional>
#include "TaskManager.h"

namespace forensics {

class TaskManager;

/**
 * @brief Task analysis execution runner
 * Handles the execution of forensic analysis tasks with progress tracking
 */
class TaskAnalysisRunner {
public:
    /**
     * @brief Constructor
     * @param manager Reference to TaskManager for callbacks
     */
    explicit TaskAnalysisRunner(TaskManager& manager);

    /**
     * @brief Execute analysis task
     * @param task_id ID of task to execute
     */
    void start_analysis(const std::string& task_id);

    /**
     * @brief Check if task is cancelled
     * @param task_id ID of task to check
     * @return true if task cancellation requested
     */
    bool is_task_cancelled(const std::string& task_id) const;

private:
    TaskManager& manager_;

    /**
     * @brief Calculate overall percentage from phase progress
     */
    int calculate_overall_percentage(TaskPhase phase, int phase_percentage);
};

} // namespace forensics
