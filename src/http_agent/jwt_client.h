#pragma once

// Holds the client's long-lived (30d) JWT and produces the Bearer value.
//
// No refresh in Task 16: a 30d token outlasts any agent session, and
// re-enrollment (the Task 9 server endpoint) is the refresh path when it
// expires. The token is loaded once from a file at startup; the file must be
// 0600 — a group/other-readable secret is a hard error, not a warning.

#include <string>

namespace tracelens {

class JwtClient {
public:
    // Wraps an already-loaded token. Throws std::runtime_error if the token is
    // empty/whitespace-only — the agent cannot poll without one.
    explicit JwtClient(const std::string& token);

    // Loads the token from a file: rejects a missing file and a
    // group/other-readable file (must be 0600). Trims trailing whitespace.
    static JwtClient load_from_file(const std::string& path);

    // "Bearer <token>" — the Authorization header value.
    std::string bearer_value() const;

    const std::string& token() const { return token_; }

private:
    std::string token_;
};

}  // namespace tracelens
