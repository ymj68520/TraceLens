#pragma once

// A command claimed from the server's poll endpoint. Mirrors the server's
// CommandResponse / CommandPollResponse (Tasks 3/11). The client executes it
// locally and reports status back via POST /api/commands/{id}/status.

#include <string>

#include "json.hpp"

namespace tracelens {

struct Command {
    std::string id;            // server UUID (path-authoritative for /status)
    std::string command_type;  // analyze_disk | health_check | extract_file | ...
    nlohmann::json parameters; // command-specific payload (analyze_disk carries
                               // image_path/analysis_type + the task_id soft link)
    std::string priority = "normal";  // low|normal|high|critical

    bool has_task_id(std::string& out) const {
        // The task_id soft link stamped by create_analysis_task (Task 12).
        if (parameters.is_object() && parameters.contains("task_id")) {
            const auto& v = parameters["task_id"];
            if (v.is_string()) { out = v.get<std::string>(); return true; }
        }
        return false;
    }
};

// Strict on the required fields (id, command_type), lenient on optional ones.
// A command missing either required field is unparseable and the poller skips
// it rather than aborting the whole poll batch.
inline void from_json(const nlohmann::json& j, Command& c) {
    j.at("id").get_to(c.id);
    j.at("command_type").get_to(c.command_type);
    if (j.contains("parameters") && !j["parameters"].is_null()) {
        c.parameters = j["parameters"];
    } else {
        c.parameters = nlohmann::json::object();
    }
    if (j.contains("priority") && j["priority"].is_string()) {
        c.priority = j["priority"].get<std::string>();
    }
}

}  // namespace tracelens
