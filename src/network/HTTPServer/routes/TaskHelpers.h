#pragma once

#include <nlohmann/json.hpp>
#include <string>
#include "../HTTPServerDataTypes.h"

namespace forensics {

/**
 * @brief Task serialization and conversion helpers
 */
class TaskHelpers {
public:
    static nlohmann::json task_to_json(const AnalysisTask& task);
    static std::string status_to_string(TaskStatus status);
    static std::string phase_to_string(TaskPhase phase);
    static std::string priority_to_string(TaskPriority priority);
    static TaskPriority priority_from_string(const std::string& str);
};

} // namespace forensics
