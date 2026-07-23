#include "status_reporter.h"

namespace tracelens {

bool StatusReporter::report(const std::string& command_id,
                            const StatusUpdate& update,
                            std::string& out_error) {
    out_error.clear();
    const std::string path = "/api/commands/" + command_id + "/status";
    const std::string body = nlohmann::json(update).dump();
    const auto res = client_.post(path, body);
    if (!res.ok()) {
        out_error = res.error.empty()
                        ? ("status report failed: HTTP " + std::to_string(res.status))
                        : ("status report transport error: " + res.error);
        return false;
    }
    return true;
}

}  // namespace tracelens
