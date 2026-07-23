// TraceLens client HTTP agent — entry point.
//
// Wires the network/protocol foundation (Task 16): loads config + the 30d
// client JWT, builds the TLS transport, and runs the poll loop. Analysis
// execution is a stub here (StubExecutor); Task 17 replaces it with the bridge
// to the forensic AnalysisOrchestrator.
//
// Usage:
//   tracelens_agent --config /etc/tracelens/agent.conf [--once]
//   (or TRACELENS_SERVER_URL / TRACELENS_TOKEN_PATH / TRACELENS_POLL_INTERVAL /
//    TRACELENS_HOSTNAME env vars)

#include "client_config.h"
#include "command_executor.h"
#include "http_agent_service.h"
#include "http_client.h"
#include "jwt_client.h"
#include "poller.h"
#include "status_reporter.h"

#include <csignal>
#include <iostream>
#include <string>

static void usage() {
    std::cerr <<
        "Usage: tracelens_agent --config <path> [--once]\n"
        "       tracelens_agent (uses TRACELENS_* env vars)\n"
        "  --config <path>  read settings from a key=value file\n"
        "  --once           run a single poll cycle then exit\n";
}

int main(int argc, char** argv) {
    std::string config_path;
    bool once = false;
    for (int i = 1; i < argc; ++i) {
        const std::string a = argv[i];
        if (a == "--help" || a == "-h") { usage(); return 0; }
        if (a == "--once")              { once = true; }
        else if (a == "--config" && i + 1 < argc) { config_path = argv[++i]; }
        else { std::cerr << "unknown arg: " << a << "\n"; usage(); return 2; }
    }

    tracelens::ClientConfig cfg;
    std::string err;
    if (!config_path.empty()) cfg = tracelens::ClientConfig::load_from_file(config_path, err);
    else                       cfg = tracelens::ClientConfig::load_from_env(err);
    if (!err.empty()) {
        std::cerr << "config load error: " << err << "\n";
        return 2;
    }
    if (const auto v = tracelens::ClientConfig::validate(cfg); !v.empty()) {
        std::cerr << "config invalid: " << v << "\n";
        return 2;
    }

    tracelens::JwtClient jwt =
        tracelens::JwtClient::load_from_file(cfg.token_path);  // throws on bad file/perms

    tracelens::HttpLibClient transport(cfg.server_base_url, jwt.bearer_value());
    tracelens::Poller poller(transport);
    tracelens::StatusReporter reporter(transport);
    tracelens::StubExecutor executor;
    tracelens::ConsoleLogger logger;

    // Signal handler: async-signal-safe atomic store -> loop notices within ~200ms.
    std::signal(SIGINT,  [](int) { tracelens::g_request_stop.store(true); });
    std::signal(SIGTERM, [](int) { tracelens::g_request_stop.store(true); });

    tracelens::HttpAgentService service(poller, reporter, executor,
                                        cfg.poll_interval_seconds, logger);
    try {
        return service.run(/*single_iteration=*/once);
    } catch (const std::exception& e) {
        std::cerr << "fatal: " << e.what() << "\n";
        return 1;
    }
}
