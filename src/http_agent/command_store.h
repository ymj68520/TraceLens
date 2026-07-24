#pragma once

// Local, durable record of in-flight commands — Task 18 (local_queue).
//
// WHY: HttpAgentService (Task 16) executes polled commands in-memory. If the
// agent is killed / crashes mid-execution (an analyze_disk can run for many
// minutes), the interrupted command is lost: no terminal status reaches the
// server until its TTL (24h / 1h-critical) expires, and on restart the agent
// has no record of what it was doing. This store closes that gap.
//
// MODEL (D1): the store holds ONLY in-flight commands. record_started inserts a
// row; reaching a terminal state clear()s it. Therefore recover_orphans() is
// simply "every row" — each is, by construction, a command that was started but
// never finished. The server stays the source of truth for OUTCOMES; this store
// tracks only in-flight-ness.
//
// RECOVERY (D2): on startup the service reports each orphan FAILED to the server
// ("agent restarted; command interrupted — local status uncertain") and clears
// it. We do NOT re-run the analyzer: a crash leaves on-disk state of unknown
// integrity, so re-execution/re-upload would be unreliable. Partial artifacts
// remain on disk for manual recovery; the server may re-queue. The terminal
// transition is idempotent (Task 15b terminal guard), so a double-report is
// harmless.

#include "models/command.h"

#include <memory>
#include <string>
#include <vector>

namespace tracelens {

// DI seam so the service loop is unit-testable with a fake (no file I/O); the
// real impl is SqliteCommandStore. Methods return false + set `err` on failure
// (best-effort: the service logs and continues rather than aborting).
class ICommandStore {
public:
    virtual ~ICommandStore() = default;

    // Record that we have claimed + started a command (status=in-flight).
    // Idempotent on command_id (INSERT OR REPLACE), so a server re-deliver of
    // the same id after a restart is harmless.
    virtual bool record_started(const Command& cmd, std::string& err) = 0;

    // Remove a command's in-flight record once it has reached a terminal state.
    virtual bool clear(const std::string& command_id, std::string& err) = 0;

    // Return all currently in-flight commands (i.e. crash orphans on startup).
    // Read-only: the caller clear()s each after reporting it, so a crash during
    // recovery re-reports (idempotently) rather than dropping a failure signal.
    virtual std::vector<Command> recover_orphans(std::string& err) = 0;
};

// SQLite-backed ICommandStore. One connection for the store's lifetime; the
// agent is single-threaded so no locking is needed beyond sqlite's own. Each
// mutating op is its own autocommitted transaction; with the default
// synchronous=FULL a committed record_started survives SIGKILL/power loss —
// the durability this feature exists to provide.
class SqliteCommandStore : public ICommandStore {
public:
    // Opens (creating if absent) the DB at `path` and ensures the schema. Sets
    // `err` and is unusable on failure (a closed/failed store is safe to dtor).
    explicit SqliteCommandStore(const std::string& path);
    ~SqliteCommandStore() override;
    SqliteCommandStore(const SqliteCommandStore&) = delete;
    SqliteCommandStore& operator=(const SqliteCommandStore&) = delete;

    bool record_started(const Command& cmd, std::string& err) override;
    bool clear(const std::string& command_id, std::string& err) override;
    std::vector<Command> recover_orphans(std::string& err) override;

private:
    bool ensure_schema(std::string& err);

    struct sqlite3_deleter {
        void operator()(void* db) const;  // calls sqlite3_close
    };
    // Opaque handle (void* + custom deleter) so the header need not include
    // sqlite3.h; the .cpp casts back to sqlite3*.
    std::unique_ptr<void, sqlite3_deleter> db_;
};

}  // namespace tracelens
