#pragma once

// Command status as reported by the client to the server. These are COMMAND
// statuses (the server's CommandQueue.status vocabulary, Tasks 10/11); the
// server maps them to TASK lifecycle states in Task 15b:
//   in_progress -> running   (progress reported)
//   completed   -> completed
//   failed      -> failed    (message -> task error_message)
// The client only ever reports in_progress / completed / failed — pending and
// assigned are server-internal states it never sends.

#include <optional>
#include <string>

#include "json.hpp"

namespace tracelens {

enum class CommandStatus {
    Pending,
    Assigned,
    InProgress,
    Completed,
    Failed,
};

// Wire string for POST /status (matches the server's free-string status field).
inline const char* command_status_string(CommandStatus s) {
    switch (s) {
        case CommandStatus::Pending:    return "pending";
        case CommandStatus::Assigned:   return "assigned";
        case CommandStatus::InProgress: return "in_progress";
        case CommandStatus::Completed:  return "completed";
        case CommandStatus::Failed:     return "failed";
    }
    return "unknown";
}

// A status report the client POSTs. Fields mirror the server's TaskStatusUpdate
// schema (Task 3): status is required; progress (0-100) and message are
// optional. command_id is omitted — the path id is authoritative (Task 11).
struct StatusUpdate {
    CommandStatus status;
    std::optional<int> progress;
    std::optional<std::string> message;
};

inline void to_json(nlohmann::json& j, const StatusUpdate& u) {
    j = nlohmann::json{{"status", command_status_string(u.status)}};
    if (u.progress) j["progress"] = *u.progress;
    if (u.message)  j["message"]  = *u.message;
}

}  // namespace tracelens
