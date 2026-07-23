#include "command_executor.h"

namespace tracelens {

ExecutionResult StubExecutor::execute(const Command& cmd) {
    // Task 16 stub: acknowledge and succeed. The real analyze_disk bridge lands
    // in Task 17 and replaces this executor in the service wiring.
    ExecutionResult r;
    r.success = true;
    r.message = "stub execution of " + cmd.command_type;
    return r;
}

}  // namespace tracelens
