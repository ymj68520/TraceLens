#pragma once

// Lightweight client configuration for the HTTP agent. This is deliberately
// separate from the analyzer's core ConfigManager (LLM/DB/HTTP-server-centric)
// — the agent only needs to know where the server is, how often to poll, and
// where its token lives.

#include <string>

namespace tracelens {

struct ClientConfig {
    std::string server_base_url;       // https://host[:port]
    int poll_interval_seconds = 10;    // 5..30 (plan: 10s default, 5-30 range)
    std::string token_path;            // path to the 30d client JWT file
    std::string hostname;              // informational (reported hostname)

    // Returns an empty string if valid, else a human-readable error. Enforces:
    //  - token_path required
    //  - https:// required, EXCEPT http:// to localhost/127.0.0.1/::1 (dev)
    //    (raw-derived data must never leave the box over an unencrypted channel)
    //  - poll interval 5..30
    static std::string validate(const ClientConfig& c);

    // Reads key=value lines (blank/# lines ignored). Sets `err` on failure.
    static ClientConfig load_from_file(const std::string& path, std::string& err);

    // Reads TRACELENS_SERVER_URL / TRACELENS_POLL_INTERVAL /
    // TRACELENS_TOKEN_PATH / TRACELENS_HOSTNAME. Sets `err` on failure.
    static ClientConfig load_from_env(std::string& err);
};

}  // namespace tracelens
