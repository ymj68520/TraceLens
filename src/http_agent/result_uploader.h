#pragma once

// Uploads the metadata of artifacts a client produced for a task, to
// POST /api/tasks/{task_id}/results (client-auth, Task 14 endpoint). Uses an
// injected IHttpClient so it is unit-tested with a FakeHttpClient — no live
// server, same pattern as Poller/StatusReporter.
//
// This is METADATA ONLY (the server's ResultArtifact schema has no content
// field). The raw disk image is never referenced here: only the derived
// artifacts the AnalyzeDiskExecutor collected are described. See result_artifact.h
// for the security invariant.

#include "http_client.h"
#include "result_artifact.h"

#include <string>
#include <vector>

namespace tracelens {

class ResultUploader {
public:
    explicit ResultUploader(IHttpClient& client) : client_(client) {}

    // POSTs the artifact batch for one task. Returns true on a 2xx response.
    // On failure out_error describes the HTTP/transport problem so the loop can
    // fold it into the command's terminal status message.
    bool upload(const std::string& task_id,
                const std::vector<ResultArtifact>& artifacts,
                std::string& out_error);

private:
    IHttpClient& client_;
};

}  // namespace tracelens
