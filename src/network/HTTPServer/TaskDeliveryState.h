#pragma once
#include "HTTPServerDataTypes.h"
#include <optional>

namespace forensics {
inline std::optional<long long> completed_timestamp(const AnalysisTask& task, bool milliseconds = false) {
    const bool terminal = task.status == TaskStatus::COMPLETED || task.status == TaskStatus::FAILED || task.status == TaskStatus::CANCELLED;
    if (!terminal || task.interrupted_by_restart || task.completed_time <= std::chrono::system_clock::time_point{} || task.completed_time == task.created_time) return std::nullopt;
    if (milliseconds) return std::chrono::duration_cast<std::chrono::milliseconds>(task.completed_time.time_since_epoch()).count();
    return std::chrono::duration_cast<std::chrono::seconds>(task.completed_time.time_since_epoch()).count();
}
}
