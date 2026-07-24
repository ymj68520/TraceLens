#include "command_store.h"

#include <sqlite3.h>

#include <ctime>
#include <utility>

#include "json.hpp"

namespace tracelens {

namespace {

// Wraps a prepared statement so step/reset/finalize is exception- and
// early-return-safe. finalizes on destruction.
struct StmtGuard {
    sqlite3_stmt* s = nullptr;
    explicit StmtGuard(sqlite3_stmt* stmt) : s(stmt) {}
    ~StmtGuard() { if (s) sqlite3_finalize(s); }
    StmtGuard(const StmtGuard&) = delete;
    StmtGuard& operator=(const StmtGuard&) = delete;
};

// Appends "<sql>: <sqlite errmsg>" to err and returns false.
bool fail(sqlite3* db, std::string& err, const std::string& sql) {
    err = sql;
    if (db) { err += ": "; err += sqlite3_errmsg(db); }
    return false;
}

}  // namespace

void SqliteCommandStore::sqlite3_deleter::operator()(void* db) const {
    if (db) sqlite3_close(static_cast<sqlite3*>(db));
}

SqliteCommandStore::SqliteCommandStore(const std::string& path) {
    sqlite3* raw = nullptr;
    // READWRITE|CREATE makes a missing file. We deliberately do NOT pass
    // SQLITE_OPEN_URI: the path is a plain filesystem path, and URI parsing
    // would misread any '?'/'#' in a filename as a query/fragment.
    int rc = sqlite3_open_v2(path.c_str(), &raw,
                             SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE,
                             nullptr);
    if (rc != SQLITE_OK) {
        // On open failure sqlite3_open_v2 still allocates `raw` (a handle that
        // carries the errmsg); close it so we don't leak, then leave db_ null.
        if (raw) sqlite3_close(raw);
        return;  // db_ stays null; methods will report "not open".
    }
    db_.reset(raw);

    // Cheap insurance against a transient lock from a prior unclean exit;
    // single-connection today, so this rarely matters, but a stale -journal /
    // -wal from a crashed peer could otherwise busy-loop.
    (void)sqlite3_busy_timeout(raw, 5000);

    std::string err;
    if (!ensure_schema(err)) {
        // Could not initialize: drop the handle so the store reports unusable
        // rather than operating on a schemaless DB.
        db_.reset();
    }
}

SqliteCommandStore::~SqliteCommandStore() = default;

bool SqliteCommandStore::ensure_schema(std::string& err) {
    auto* db = static_cast<sqlite3*>(db_.get());
    if (!db) return fail(nullptr, err, "store not open");
    const char* kSchema =
        "CREATE TABLE IF NOT EXISTS in_flight_commands ("
        "  command_id   TEXT PRIMARY KEY,"
        "  command_type TEXT NOT NULL,"
        "  parameters   TEXT NOT NULL,"       // JSON blob
        "  priority     TEXT NOT NULL DEFAULT 'normal',"
        "  started_epoch INTEGER NOT NULL"    // UTC seconds, diagnostics only
        ")";
    char* zmsg = nullptr;
    int rc = sqlite3_exec(db, kSchema, nullptr, nullptr, &zmsg);
    if (rc != SQLITE_OK) {
        err = std::string("create table: ") + (zmsg ? zmsg : sqlite3_errmsg(db));
        sqlite3_free(zmsg);
        return false;
    }
    return true;
}

bool SqliteCommandStore::record_started(const Command& cmd, std::string& err) {
    err.clear();
    auto* db = static_cast<sqlite3*>(db_.get());
    if (!db) return fail(nullptr, err, "store not open");

    // The `parameters` column holds ONLY the parameters object (id/type/priority
    // have their own columns); recover_orphans parses it back as-is, so the
    // task_id soft link nested inside parameters round-trips at the same depth.
    const nlohmann::json& params = cmd.parameters.is_object()
                                       ? cmd.parameters
                                       : nlohmann::json::object();
    const std::string params_json = params.dump();

    sqlite3_stmt* stmt = nullptr;
    const char* kSql =
        "INSERT OR REPLACE INTO in_flight_commands "
        "(command_id, command_type, parameters, priority, started_epoch) "
        "VALUES (?1, ?2, ?3, ?4, ?5)";
    int rc = sqlite3_prepare_v2(db, kSql, -1, &stmt, nullptr);
    if (rc != SQLITE_OK) return fail(db, err, "prepare record_started");
    StmtGuard g(stmt);

    const std::string priority = cmd.priority.empty() ? std::string("normal")
                                                      : cmd.priority;
    // (INSERT OR REPLACE is atomic + autocommitted -> fsynced at commit with the
    //  default synchronous=FULL, so this row survives a crash.)
    sqlite3_bind_text(stmt, 1, cmd.id.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, cmd.command_type.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, params_json.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, priority.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 5, static_cast<sqlite3_int64>(std::time(nullptr)));

    rc = sqlite3_step(stmt);
    if (rc != SQLITE_DONE) return fail(db, err, "step record_started");
    return true;
}

bool SqliteCommandStore::clear(const std::string& command_id, std::string& err) {
    err.clear();
    auto* db = static_cast<sqlite3*>(db_.get());
    if (!db) return fail(nullptr, err, "store not open");

    sqlite3_stmt* stmt = nullptr;
    const char* kSql = "DELETE FROM in_flight_commands WHERE command_id = ?1";
    int rc = sqlite3_prepare_v2(db, kSql, -1, &stmt, nullptr);
    if (rc != SQLITE_OK) return fail(db, err, "prepare clear");
    StmtGuard g(stmt);

    sqlite3_bind_text(stmt, 1, command_id.c_str(), -1, SQLITE_TRANSIENT);
    rc = sqlite3_step(stmt);
    if (rc != SQLITE_DONE) return fail(db, err, "step clear");
    // Affecting zero rows (already cleared) is not an error — terminal is
    // idempotent by design.
    return true;
}

std::vector<Command> SqliteCommandStore::recover_orphans(std::string& err) {
    err.clear();
    std::vector<Command> out;
    auto* db = static_cast<sqlite3*>(db_.get());
    if (!db) { fail(nullptr, err, "store not open"); return out; }

    sqlite3_stmt* stmt = nullptr;
    const char* kSql =
        "SELECT command_id, command_type, parameters, priority "
        "FROM in_flight_commands ORDER BY started_epoch ASC";
    int rc = sqlite3_prepare_v2(db, kSql, -1, &stmt, nullptr);
    if (rc != SQLITE_OK) { fail(db, err, "prepare recover_orphans"); return out; }
    StmtGuard g(stmt);

    while ((rc = sqlite3_step(stmt)) == SQLITE_ROW) {
        const char* id = reinterpret_cast<const char*>(
            sqlite3_column_text(stmt, 0));
        const char* type = reinterpret_cast<const char*>(
            sqlite3_column_text(stmt, 1));
        const char* params = reinterpret_cast<const char*>(
            sqlite3_column_text(stmt, 2));
        const char* prio = reinterpret_cast<const char*>(
            sqlite3_column_text(stmt, 3));
        if (!id || !type || !params) continue;  // NOT NULL columns; skip paranoia

        // Reconstruct via the same wire shape record_started wrote, then parse
        // through from_json so a future Command field change is picked up once.
        nlohmann::json row = nlohmann::json::object();
        row["id"] = std::string(id);
        row["command_type"] = std::string(type);
        row["parameters"] = nlohmann::json::parse(params, nullptr, false);
        if (row["parameters"].is_discarded()) {
            row["parameters"] = nlohmann::json::object();  // corrupt blob -> empty
        }
        if (prio) row["priority"] = std::string(prio);

        try {
            out.push_back(row.get<Command>());
        } catch (const std::exception&) {
            // A row we can't reconstruct is left in place (still an orphan);
            // best-effort skip rather than aborting recovery.
            continue;
        }
    }
    if (rc != SQLITE_DONE) fail(db, err, "step recover_orphans");
    return out;
}

}  // namespace tracelens
