// TraceLens client HTTP agent — entry point.
//
// Wires the full client loop (Tasks 16 + 17): loads config + the 30d client
// JWT, builds the TLS transport, and runs poll -> execute (local analysis via
// the forensics_analyzer binary) -> upload artifacts -> report status.
//
// Usage:
//   tracelens_agent --config /etc/tracelens/agent.conf [--once]
//   (or TRACELENS_SERVER_URL / TRACELENS_TOKEN_PATH / TRACELENS_POLL_INTERVAL /
//    TRACELENS_HOSTNAME / TRACELENS_ANALYZER_PATH / TRACELENS_WORK_DIR env vars)

#include "client_config.h"
#include "command_executor.h"
#include "command_store.h"
#include "http_agent_service.h"
#include "http_client.h"
#include "image_indexer.h"
#include "index_uploader.h"
#include "jwt_client.h"
#include "poller.h"
#include "process_runner.h"
#include "result_uploader.h"
#include "status_reporter.h"

#include <csignal>
#include <filesystem>
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

    // Default the work dir to a "tracelens_work" folder in the cwd if the
    // config did not set one. Production deployments set work_base_dir explicitly.
    std::string work_dir = cfg.work_base_dir;
    if (work_dir.empty()) {
        work_dir = (std::filesystem::current_path() / "tracelens_work").string();
    }

    // Default the in-flight state DB alongside the work dir if not set.
    std::string state_db = cfg.state_db_path;
    if (state_db.empty()) {
        state_db = (std::filesystem::path(work_dir) / "tracelens_state.db").string();
    }
    std::error_code mkec;
    std::filesystem::create_directories(std::filesystem::path(state_db).parent_path(),
                                        mkec);

    // HttpLibClient prepends "Bearer " itself (http_client.cpp), so pass the RAW
    // token, not bearer_value() (which is already "Bearer <token>") — otherwise
    // the header becomes "Authorization: Bearer Bearer <token>" and every call
    // 401s. (Reviewer-found Task 16 wiring bug.)
    tracelens::HttpLibClient transport(cfg.server_base_url, jwt.token());
    tracelens::Poller poller(transport);
    tracelens::StatusReporter reporter(transport);
    tracelens::ResultUploader uploader(transport);
    tracelens::SqliteCommandStore store(state_db);
    tracelens::PosixProcessRunner runner;
    tracelens::AnalyzeDiskExecutor executor(runner, cfg.analyzer_path, work_dir,
                                            cfg.hostname);
    tracelens::ConsoleLogger logger;

    // Extract client_id for indexing (both one-shot and periodic). Must be
    // present for indexing to work (else we can't form the API path).
    const std::string cid = jwt.client_id();
    tracelens::DiskImageIndexer indexer(cfg.image_dirs);
    tracelens::IndexUploader index_uploader(transport, cid);

    // One-shot local image index at startup (Task 19): tell the server which
    // disk images exist on this client so an analyze_disk command can later
    // target a real image. Best effort — a failure here is logged, never fatal
    // (brief D6): the command loop below still serves.
    if (cfg.image_dirs.empty()) {
        std::cerr << "image_dirs not configured; skipping local image index\n";
    } else {
        if (cid.empty()) {
            std::cerr << "warning: no client_id in token; skipping image index\n";
        } else {
            std::string scan_err;
            auto entries = indexer.scan(scan_err);
            if (!scan_err.empty()) std::cerr << "warning: index scan: " << scan_err << "\n";
            std::string up_err;
            if (!index_uploader.upload(entries, up_err)) {
                std::cerr << "warning: image index upload: " << up_err << "\n";
            } else {
                std::cerr << "indexed " << entries.size() << " local image(s)\n";
            }
        }
    }

    // Signal handler: async-signal-safe atomic store -> loop notices within ~200ms.
    std::signal(SIGINT,  [](int) { tracelens::g_request_stop.store(true); });
    std::signal(SIGTERM, [](int) { tracelens::g_request_stop.store(true); });

    tracelens::HttpAgentService service(poller, reporter, executor, uploader, store,
                                        indexer, index_uploader, cfg.poll_interval_seconds,
                                        cfg.reindex_interval_seconds, cid, logger);
    try {
        return service.run(/*single_iteration=*/once);
    } catch (const std::exception& e) {
        std::cerr << "fatal: " << e.what() << "\n";
        return 1;
    }
}
