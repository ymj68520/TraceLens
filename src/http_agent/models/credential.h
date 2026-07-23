#pragma once

// The client's enrollment credential: its long-lived (30d) JWT, obtained once
// at registration (the Task 9 server endpoint) and stored locally as a file
// (0600). This token is the ONLY secret the agent holds — it never transmits
// the raw disk image anywhere; analysis is local and only derived artifacts
// leave the box. Used as `Authorization: Bearer <token>` on every request.

#include <string>

namespace tracelens {

struct ClientCredential {
    std::string token;   // raw 30d client JWT
    std::string host;    // reported hostname (informational)
};

}  // namespace tracelens
