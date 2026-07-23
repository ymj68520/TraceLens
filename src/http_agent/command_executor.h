#pragma once

// The local execution seam. The real bridge to the forensic AnalysisOrchestrator
// (analyze_disk -> carving/parsing -> result upload) is Task 17. Task 16 ships
// this interface plus a stub so the agent loop runs end-to-end and Task 17 has a
// clean place to plug in.
//
// SECURITY INVARIANT (enforced by implementations, documented here): the raw
// disk image (E01/DD) NEVER leaves the client. Execution is local; only derived
// artifacts/metadata are uploaded (Task 17 result_uploader).

#include "models/command.h"

#include <string>

namespace tracelens {

struct ExecutionResult {
    bool success = true;
    std::string message;  // progress/error text (becomes task error_message on failure)
};

class ICommandExecutor {
public:
    virtual ~ICommandExecutor() = default;
    virtual ExecutionResult execute(const Command& cmd) = 0;
};

// No-op executor for Task 16: logs the command and succeeds. Lets the loop run
// without the forensic engine.
class StubExecutor : public ICommandExecutor {
public:
    ExecutionResult execute(const Command& cmd) override;
};

}  // namespace tracelens
