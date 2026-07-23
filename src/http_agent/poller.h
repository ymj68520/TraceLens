#pragma once

#include "http_client.h"
#include "models/command.h"

#include <string>
#include <vector>

namespace tracelens {

// Polls GET /api/commands/poll via an injected transport and parses the
// CommandPollResponse into Command objects. The commands are already claimed
// (assigned) server-side at this point (Task 11 poll endpoint claims them);
// the client's job is to execute and report back.
//
// Malformed individual entries are skipped (never thrown): a bad server payload
// must not crash the loop. Transport failures (non-2xx or status 0) return an
// empty vector with out_error set.
class Poller {
public:
    explicit Poller(IHttpClient& client) : client_(client) {}

    std::vector<Command> poll(std::string& out_error);

private:
    IHttpClient& client_;
};

}  // namespace tracelens
