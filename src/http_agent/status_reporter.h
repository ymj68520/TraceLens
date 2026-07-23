#pragma once

#include "http_client.h"
#include "models/task_status.h"

#include <string>

namespace tracelens {

// POSTs a command status report to /api/commands/{id}/status via an injected
// transport. From the loop's perspective this is best-effort: a failed report
// is surfaced (false + out_error) but does not abort the agent — the server's
// command TTL and the next poll reconcile state.
class StatusReporter {
public:
    explicit StatusReporter(IHttpClient& client) : client_(client) {}

    // Returns true on a 2xx response.
    bool report(const std::string& command_id, const StatusUpdate& update,
                std::string& out_error);

private:
    IHttpClient& client_;
};

}  // namespace tracelens
