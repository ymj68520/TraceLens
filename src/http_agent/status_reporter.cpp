#include "status_reporter.h"

namespace tracelens {

bool StatusReporter::report(const std::string& command_id,
                            const StatusUpdate& update,
                            std::string& out_error) {
    out_error.clear();
    const std::string path = "/api/commands/" + command_id + "/status";
    // command_id is REQUIRED in the body by the server's TaskStatusUpdate schema
    // (uuid.UUID, no default) — the path id routes the request, but the body field
    // is validated. Omitting it yields HTTP 422 before the handler runs.
    nlohmann::json body = update;  // {status, progress?, message?}
    body["command_id"] = command_id;
    const auto res = client_.post(path, body.dump());
    if (!res.ok()) {
        out_error = res.error.empty()
                        ? ("status report failed: HTTP " + std::to_string(res.status))
                        : ("status report transport error: " + res.error);
        return false;
    }
    return true;
}

}  // namespace tracelens
