#include "http_agent_service.h"

#include "models/task_status.h"

#include <chrono>
#include <iostream>
#include <thread>

namespace tracelens {

// Defined here; declared extern in the header. Set by the signal handler.
std::atomic<bool> g_request_stop{false};

HttpAgentService::HttpAgentService(Poller& poller,
                                   StatusReporter& reporter,
                                   ICommandExecutor& executor,
                                   ResultUploader& uploader,
                                   int poll_interval_seconds,
                                   ILogger& logger)
    : poller_(poller),
      reporter_(reporter),
      executor_(executor),
      uploader_(uploader),
      interval_(poll_interval_seconds),
      logger_(logger) {}

int HttpAgentService::run(bool single_iteration) {
    while (!stop_requested()) {
        std::string err;
        auto commands = poller_.poll(err);
        if (!err.empty()) {
            // A non-empty err on a partially-parsed batch is informational
            // (skipped malformed entry); an empty batch with err is a real
            // failure. Either way, keep looping.
            if (commands.empty()) logger_.warn("poll: " + err);
            else                   logger_.warn(err);
        }

        for (const auto& cmd : commands) {
            if (stop_requested()) break;

            // Announce we have started. Best-effort: a failed in_progress report
            // is logged but does not stop us executing locally.
            {
                StatusUpdate u;
                u.status = CommandStatus::InProgress;
                std::string e;
                if (!reporter_.report(cmd.id, u, e)) {
                    logger_.warn("could not report in_progress for " + cmd.id +
                                 ": " + e);
                }
            }

            auto result = executor_.execute(cmd);

            // Upload derived artifacts when execution succeeded and produced
            // some (metadata only; raw image never leaves the box). An upload
            // failure makes the task's results undeliverable -> report FAILED so
            // it is retriable and the operator is alerted (the local artifacts
            // remain on disk for manual recovery; persistence is Task 18).
            if (result.success && !result.task_id.empty() &&
                !result.artifacts.empty()) {
                std::string ue;
                if (!uploader_.upload(result.task_id, result.artifacts, ue)) {
                    result.success = false;
                    result.message =
                        "analysis completed but result upload failed: " + ue;
                    logger_.error("upload failed for command " + cmd.id +
                                  " (task " + result.task_id + "): " + ue);
                }
            }

            StatusUpdate u;
            u.status = result.success ? CommandStatus::Completed
                                      : CommandStatus::Failed;
            u.message = result.message;
            std::string e;
            if (!reporter_.report(cmd.id, u, e)) {
                logger_.error("could not report terminal status for " + cmd.id +
                              ": " + e);
            }
            logger_.info("command " + cmd.id + " (" + cmd.command_type +
                         ") -> " + command_status_string(u.status));
        }

        if (single_iteration) break;

        // Sleep the poll interval, but in small slices so a stop request (or
        // SIGINT) is noticed within ~200ms instead of up to the full interval.
        for (int slept = 0; slept < interval_ * 1000 && !stop_requested();
             slept += 200) {
            std::this_thread::sleep_for(std::chrono::milliseconds(200));
        }
    }
    return 0;
}

void ConsoleLogger::info(const std::string& msg)  { std::cout << "[info]  "  << msg << "\n"; }
void ConsoleLogger::warn(const std::string& msg)  { std::cerr << "[warn]  "  << msg << "\n"; }
void ConsoleLogger::error(const std::string& msg) { std::cerr << "[error] "  << msg << "\n"; }

}  // namespace tracelens
