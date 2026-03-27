#pragma once

#include <string>
#include <map>
#include <unordered_set>
#include "TaskManager.h"

namespace forensics {

/**
 * @brief Task persistence operations
 * Handles saving and loading tasks from JSON storage
 */
class TaskPersistence {
public:
    /**
     * @brief Save tasks to JSON file
     * @param tasks Map of task IDs to tasks
     * @param tasksPath Path to tasks JSON file
     */
    static void save_tasks(const std::map<std::string, AnalysisTask>& tasks,
                          const std::string& tasksPath);

    /**
     * @brief Load tasks from JSON file
     * @param tasks Map to populate with loaded tasks
     * @param tasksPath Path to tasks JSON file
     * @param runningTaskIds Set to populate with IDs of running/pending tasks (for recovery)
     */
    static void load_tasks(std::map<std::string, AnalysisTask>& tasks,
                          const std::string& tasksPath,
                          std::unordered_set<std::string>& runningTaskIds);

    /**
     * @brief Clean up orphan task directories
     * @param tasks Map of active tasks
     */
    static void cleanup_orphan_directories(
        const std::map<std::string, AnalysisTask>& tasks);
};

} // namespace forensics
