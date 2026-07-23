#pragma once

#include "command_executor.h"
#include "poller.h"
#include "status_reporter.h"

#include <atomic>
#include <string>

namespace tracelens {

// Minimal logger sink so the loop is testable without touching stdout/cerr
// semantics. A ConsoleLogger is provided in the .cpp for main.
class ILogger {
public:
    virtual ~ILogger() = default;
    virtual void info(const std::string& msg) = 0;
    virtual void warn(const std::string& msg) = 0;
    virtual void error(const std::string& msg) = 0;
};

// Set by the SIGINT/SIGTERM handler in main (async-signal-safe: a lock-free
// atomic store). The loop checks this alongside its own stop flag so a ctrl-C
// exits within a fraction of the poll interval.
extern std::atomic<bool> g_request_stop;

// The agent loop: poll -> report in_progress -> execute -> report
// completed/failed. One iteration handles all commands claimed in that poll.
// Robust by design: transport errors and per-command failures are logged and
// the loop continues — a single bad request never brings the agent down.
class HttpAgentService {
public:
    HttpAgentService(Poller& poller,
                     StatusReporter& reporter,
                     ICommandExecutor& executor,
                     int poll_interval_seconds,
                     ILogger& logger);

    // Runs until stop is requested (request_stop() / g_request_stop / SIGINT).
    // Returns 0 on a clean stop, non-zero only if the loop never started.
    // single_iteration=true performs exactly one poll cycle then returns — for
    // the unit test (no sleeping).
    int run(bool single_iteration = false);

    void request_stop() { stop_requested_.store(true); }

private:
    Poller& poller_;
    StatusReporter& reporter_;
    ICommandExecutor& executor_;
    int interval_;
    ILogger& logger_;
    std::atomic<bool> stop_requested_{false};

    bool stop_requested() const {
        return stop_requested_.load() || g_request_stop.load();
    }
};

class ConsoleLogger : public ILogger {
public:
    void info(const std::string& msg) override;
    void warn(const std::string& msg) override;
    void error(const std::string& msg) override;
};

}  // namespace tracelens
