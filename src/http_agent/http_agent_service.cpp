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
                                   ICommandStore& store,
                                   int poll_interval_seconds,
                                   ILogger& logger)
    : poller_(poller),
      reporter_(reporter),
      executor_(executor),
      uploader_(uploader),
      store_(store),
      interval_(poll_interval_seconds),
      logger_(logger) {}

void HttpAgentService::recover() {
    // Report any in-flight command left over from a prior (crashed) run as
    // FAILED, then clear it. We do NOT re-run the analysis: a crash leaves
    // on-disk state of unknown integrity, so re-execution would be unreliable.
    // The terminal transition is idempotent (Task 15b guard), so re-reporting on
    // a crash-during-recovery is harmless, and clear()-after-report (not before)
    // means we never drop a failure signal.
    std::string err;
    auto orphans = store_.recover_orphans(err);
    if (!err.empty()) {
        logger_.warn("recover: could not read local in-flight store: " + err);
        return;  // unreadable store: don't guess; let normal polling proceed
    }
    for (const auto& cmd : orphans) {
        StatusUpdate u;
        u.status = CommandStatus::Failed;
        u.message =
            "agent restarted; command interrupted — local status uncertain";
        std::string e;
        if (!reporter_.report(cmd.id, u, e)) {
            // Do NOT clear: the failure signal never reached the server. Leaving
            // the row lets the next restart retry the report (D3 — never lose a
            // failure signal by deleting before it is communicated). Re-reporting
            // is bounded (one row per orphan) and idempotent (Task 15b terminal
            // guard); if the server stays down the agent can't do useful work
            // anyway (polling fails too).
            logger_.warn("recover: could not report orphan " + cmd.id +
                         " failed: " + e + " (left in store for next restart)");
            continue;
        }
        std::string ce;
        if (!store_.clear(cmd.id, ce)) {
            // Report landed but the local clear failed: the row will be
            // re-reported next restart (harmless — terminal guard). Log only.
            logger_.warn("recover: reported orphan " + cmd.id +
                         " but could not clear it: " + ce);
        }
    }
    if (!orphans.empty()) {
        logger_.info("recovered " + std::to_string(orphans.size()) +
                     " orphaned command(s) from a prior run");
    }
}

int HttpAgentService::run(bool single_iteration) {
    recover();  // once, before polling: surface crash-orphans from a prior run

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

            // Persist the in-flight marker BEFORE doing anything else, so a crash
            // at any later point (even before the in_progress report lands) is
            // recoverable. Best-effort: a store failure is logged, not fatal.
            {
                std::string se;
                if (!store_.record_started(cmd, se)) {
                    logger_.warn("could not persist in-flight record for " +
                                 cmd.id + ": " + se);
                }
            }

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
            // remain on disk for manual recovery).
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

            // Reached a terminal state: clear the in-flight marker so it is not
            // mistaken for an orphan on the next startup.
            std::string ce;
            if (!store_.clear(cmd.id, ce)) {
                logger_.warn("could not clear in-flight record for " + cmd.id +
                             ": " + ce);
            }
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
