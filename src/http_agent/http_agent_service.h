#pragma once

#include "command_executor.h"
#include "command_store.h"
#include "image_indexer.h"
#include "index_uploader.h"
#include "poller.h"
#include "result_uploader.h"
#include "status_reporter.h"

#include <atomic>
#include <ctime>
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

// The agent loop: poll -> report in_progress -> execute -> (upload artifacts)
// -> report completed/failed. One iteration handles all commands claimed in
// that poll. Robust by design: transport errors and per-command failures are
// logged and the loop continues — a single bad request never brings the agent
// down.
class HttpAgentService {
public:
    HttpAgentService(Poller& poller,
                     StatusReporter& reporter,
                     ICommandExecutor& executor,
                     ResultUploader& uploader,
                     ICommandStore& store,
                     DiskImageIndexer& indexer,
                     IndexUploader& index_uploader,
                     int poll_interval_seconds,
                     int reindex_interval_seconds,
                     const std::string& client_id,
                     ILogger& logger);

    // Runs until stop is requested (request_stop() / g_request_stop / SIGINT).
    // Returns 0 on a clean stop, non-zero only if the loop never started.
    // single_iteration=true performs exactly one poll cycle then returns — for
    // the unit test (no sleeping). recover() runs at the top of every run() to
    // report any crash-orphans from a prior run (Task 18); it is idempotent
    // (clear-after-report), so repeated run() calls are safe.
    int run(bool single_iteration = false);

    void request_stop() { stop_requested_.store(true); }

private:
    Poller& poller_;
    StatusReporter& reporter_;
    ICommandExecutor& executor_;
    ResultUploader& uploader_;
    ICommandStore& store_;
    DiskImageIndexer& indexer_;
    IndexUploader& index_uploader_;
    int interval_;
    int reindex_interval_;
    std::string client_id_;
    ILogger& logger_;
    std::atomic<bool> stop_requested_{false};

    // Tracks wall-clock time of the last re-index (Task 23). Initialized to
    // current time so the first poll cycle waits for the interval to elapse
    // before triggering the first periodic re-index (main() already does the
    // startup index). Updated after each successful re-index (or unchanged on
    // failure — retry next period).
    std::time_t last_reindex_time_ = std::time(nullptr);

    bool stop_requested() const {
        return stop_requested_.load() || g_request_stop.load();
    }

    // Reports each in-flight orphan FAILED to the server and clears it. Called
    // once at the top of run() before polling begins.
    void recover();
};

class ConsoleLogger : public ILogger {
public:
    void info(const std::string& msg) override;
    void warn(const std::string& msg) override;
    void error(const std::string& msg) override;
};

}  // namespace tracelens
