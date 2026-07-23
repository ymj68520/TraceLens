#include "poller.h"

#include "json.hpp"

namespace tracelens {

std::vector<Command> Poller::poll(std::string& out_error) {
    out_error.clear();
    const auto res = client_.get("/api/commands/poll");
    if (!res.ok()) {
        out_error = res.error.empty()
                        ? ("poll failed: HTTP " + std::to_string(res.status))
                        : ("poll transport error: " + res.error);
        return {};
    }
    std::vector<Command> commands;
    nlohmann::json doc;
    try {
        doc = nlohmann::json::parse(res.body.empty() ? "{}" : res.body);
    } catch (const std::exception& e) {
        out_error = std::string("poll: unparseable response: ") + e.what();
        return {};
    }
    if (!doc.is_object() || !doc.contains("commands")) {
        out_error = "poll: response missing 'commands'";
        return {};
    }
    for (const auto& item : doc["commands"]) {
        try {
            commands.push_back(item.get<Command>());
        } catch (const std::exception& e) {
            // Skip a malformed command rather than failing the whole batch.
            out_error = std::string("poll: skipped malformed command: ") + e.what();
        }
    }
    return commands;
}

}  // namespace tracelens
