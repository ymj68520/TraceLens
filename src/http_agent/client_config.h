#pragma once

// Lightweight client configuration for the HTTP agent. This is deliberately
// separate from the analyzer's core ConfigManager (LLM/DB/HTTP-server-centric)
// — the agent only needs to know where the server is, how often to poll, and
// where its token lives.

#include <string>
#include <vector>

namespace tracelens {

struct ClientConfig {
    std::string server_base_url;       // https://host[:port]
    int poll_interval_seconds = 10;    // 5..30 (plan: 10s default, 5-30 range)
    int reindex_interval_seconds = 1800;  // 0 disables periodic re-indexing (Task 23); default 30m
    std::string token_path;            // path to the 30d client JWT file
    std::string hostname;              // informational (reported hostname)
    std::string analyzer_path;         // path to the local forensics_analyzer binary
    std::string work_base_dir;         // parent of per-command work dirs (analyzer --db-dir)
    std::string state_db_path;         // SQLite in-flight command store (Task 18); optional here
    std::vector<std::string> image_dirs;  // local dirs to index for disk images (Task 19); optional

    // Returns an empty string if valid, else a human-readable error. Enforces:
    //  - token_path required
    //  - analyzer_path required (fail-fast: a misconfigured agent that can run
    //    no analysis should refuse to start, not fail per-command)
    //  - https:// required, EXCEPT http:// to localhost/127.0.0.1/::1 (dev)
    //    (raw-derived data must never leave the box over an unencrypted channel)
    //  - poll interval 5..30
    //  work_base_dir is optional here; main applies a default if empty.
    static std::string validate(const ClientConfig& c);

    // Reads key=value lines (blank/# lines ignored). Sets `err` on failure.
    static ClientConfig load_from_file(const std::string& path, std::string& err);

    // Reads TRACELENS_SERVER_URL / TRACELENS_POLL_INTERVAL /
    // TRACELENS_TOKEN_PATH / TRACELENS_HOSTNAME / TRACELENS_ANALYZER_PATH /
    // TRACELENS_WORK_DIR / TRACELENS_STATE_DB / TRACELENS_IMAGE_DIRS. Sets `err`
    // on failure.
    static ClientConfig load_from_env(std::string& err);
};

}  // namespace tracelens
