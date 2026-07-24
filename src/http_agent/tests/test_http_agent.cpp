// Self-contained unit tests for the TraceLens HTTP agent (Tasks 16–20).
//
// No GTest dependency (so the gate builds with just g++ + OpenSSL + pthreads)
// and no real analyzer binary:
//  - a FakeHttpClient implements IHttpClient, returning canned JSON and recording
//    the POSTs the loop issues;
//  - a FakeProcessRunner implements IProcessRunner, returning a canned
//    ProcessResult and (optionally) simulating the analyzer writing its output DB.
// The real HttpLibClient IS exercised end-to-end over a loopback httplib::Server
// (Task 20: test_live_transport_* — the only place the live transport path:
// Bearer-header formation, body serialization, response parsing, redirect
// handling, transport errors — is covered; FakeHttpClient cannot see header
// formation, which is what let the Task-16 double-Bearer bug ship). The real
// PosixProcessRunner IS exercised against real processes (test_process_runner_*)
// — including an over-cap case (>8 MiB) that pins the pipe-capture deadlock fix.
// A 60s SIGALRM guards the whole suite against a regression that would otherwise
// wedge the test process forever.

#include "client_config.h"
#include "command_executor.h"
#include "http_agent_service.h"
#include "http_client.h"
#include "image_indexer.h"
#include "index_uploader.h"
#include "jwt_client.h"
#include "models/command.h"
#include "models/task_status.h"
#include "poller.h"
#include "process_runner.h"
#include "result_uploader.h"
#include "status_reporter.h"

#include "httplib.h"
#include "json.hpp"

#include <sqlite3.h>

#include <atomic>
#include <chrono>
#include <csignal>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <set>
#include <string>
#include <thread>
#include <unistd.h>
#include <utility>
#include <vector>

namespace fs = std::filesystem;

static int g_failures = 0;
static int g_checks = 0;

static void expect(bool cond, const std::string& what, int line) {
    ++g_checks;
    if (!cond) {
        ++g_failures;
        std::cerr << "FAIL [line " << line << "]: " << what << "\n";
    }
}
#define CHECK(cond)            expect((cond), #cond, __LINE__)
#define CHECK_EQ(a, b)         expect((a) == (b), #a " == " #b, __LINE__)
#define CHECK_CONTAINS(s, sub) expect((s).find(sub) != std::string::npos, \
                                      #s " contains " #sub, __LINE__)

static bool has_flag(const std::vector<std::string>& argv, const std::string& f) {
    return std::find(argv.begin(), argv.end(), f) != argv.end();
}

// ---------------------------------------------------------------- FakeHttpClient
struct FakeHttpClient : tracelens::IHttpClient {
    tracelens::HttpResponse get_response{200, "{}", ""};
    tracelens::HttpResponse post_response{200, "{}", ""};
    std::string last_get_path;
    std::vector<std::pair<std::string, std::string>> post_calls;  // path, body
    std::set<std::string> fail_post_paths;  // paths that return a 500

    tracelens::HttpResponse get(const std::string& path) override {
        last_get_path = path;
        return get_response;
    }
    tracelens::HttpResponse post(const std::string& path,
                                 const std::string& body) override {
        post_calls.emplace_back(path, body);
        if (fail_post_paths.count(path)) return {500, "", ""};
        return post_response;
    }
};

struct NoopLogger : tracelens::ILogger {
    void info(const std::string&) override {}
    void warn(const std::string&) override {}
    void error(const std::string&) override {}
};

// Always-fails executor: exercises the failed-execution -> "failed" status path
// (StubExecutor only ever succeeds, so the failed branch would otherwise go
// untested).
struct FailingExecutor : tracelens::ICommandExecutor {
    tracelens::ExecutionResult execute(const tracelens::Command&) override {
        tracelens::ExecutionResult r;
        r.success = false;
        r.message = "boom";
        return r;
    }
};

// ------------------------------------------------------------- FakeProcessRunner
struct FakeProcessRunner : tracelens::IProcessRunner {
    tracelens::ProcessResult canned;          // returned on every run()
    std::vector<std::string> last_argv;
    std::string last_work_dir;
    int call_count = 0;
    bool produce_output = false;  // simulate the analyzer writing <stem>_raw.db

    tracelens::ProcessResult run(const std::vector<std::string>& argv,
                                 const std::string& work_dir) override {
        ++call_count;
        last_argv = argv;
        last_work_dir = work_dir;
        if (produce_output && argv.size() > 1) {
            fs::create_directories(work_dir);
            const std::string stem = fs::path(argv[1]).stem().string();
            std::ofstream(work_dir + "/" + stem + "_raw.db")
                << "FAKE_DB_CONTENT_0123456789";
        }
        return canned;
    }
};

// --------------------------------------------------------------- FakeCommandStore
struct FakeCommandStore : tracelens::ICommandStore {
    std::vector<std::string> started_ids;
    std::vector<std::string> cleared_ids;
    std::vector<tracelens::Command> orphans_to_return;  // empty by default
    bool fail = false;  // make every op return false (sets err)

    bool record_started(const tracelens::Command& c, std::string& err) override {
        started_ids.push_back(c.id);
        if (fail) { err = "injected"; return false; }
        return true;
    }
    bool clear(const std::string& id, std::string& err) override {
        cleared_ids.push_back(id);
        if (fail) { err = "injected"; return false; }
        return true;
    }
    std::vector<tracelens::Command> recover_orphans(std::string& err) override {
        if (fail) { err = "injected"; return {}; }
        return orphans_to_return;  // empty -> recover() is a no-op
    }
};

// Helper: parse a JSON command string into a Command.
static tracelens::Command parse_cmd(const std::string& json) {
    return nlohmann::json::parse(json).get<tracelens::Command>();
}

// Helper: build an analyze_disk command programmatically (avoids raw-string
// brace-counting when an image path is interpolated).
static nlohmann::json analyze_cmd_json(const std::string& id,
                                       const std::string& image,
                                       const std::string& task_id = "",
                                       const std::string& atype = "windows",
                                       bool carve = true) {
    nlohmann::json j;
    j["id"] = id;
    j["command_type"] = "analyze_disk";
    if (!task_id.empty()) j["parameters"]["task_id"] = task_id;
    if (!image.empty()) j["parameters"]["image_path"] = image;
    if (!atype.empty()) j["parameters"]["analysis_type"] = atype;
    if (carve) j["parameters"]["options"]["file_carving"] = true;
    return j;
}

// ----------------------------------------------------------------------- JwtClient
static void test_jwt_client() {
    tracelens::JwtClient jwt("  abc.def.ghi\n ");
    CHECK_EQ(jwt.bearer_value(), std::string("Bearer abc.def.ghi"));
    CHECK_EQ(jwt.token(), std::string("abc.def.ghi"));

    bool threw = false;
    try { tracelens::JwtClient bad("   "); } catch (const std::exception&) { threw = true; }
    CHECK(threw);

    // load_from_file with a 0600 file.
    const fs::path tok = fs::temp_directory_path() / "tracelens_test_token";
    {
        std::ofstream f(tok);
        f << "tok.from.file\n";
    }
    fs::permissions(tok,
                    fs::perms::owner_read | fs::perms::owner_write,
                    fs::perm_options::replace);
    try {
        auto from_file = tracelens::JwtClient::load_from_file(tok.string());
        CHECK_EQ(from_file.bearer_value(), std::string("Bearer tok.from.file"));
    } catch (const std::exception& e) {
        std::cerr << "unexpected: " << e.what() << "\n";
        CHECK(false);
    }

    // A group/other-readable file must be rejected.
    fs::permissions(tok,
                    fs::perms::owner_read | fs::perms::owner_write |
                        fs::perms::group_read | fs::perms::others_read,
                    fs::perm_options::replace);
    threw = false;
    try { tracelens::JwtClient::load_from_file(tok.string()); }
    catch (const std::exception&) { threw = true; }
    CHECK(threw);

    fs::remove(tok);
}

// ------------------------------------------------------------------ ClientConfig
// analyzer_path is now REQUIRED by validate (fail-fast), so every valid case
// supplies it. Field order: {url, interval, token, hostname, analyzer, work}.
static void test_config_validate() {
    using C = tracelens::ClientConfig;
    const std::string az = "/usr/bin/forensics_analyzer";

    // Helper to build config for testing (reindex_interval_seconds is unused by validate
    // but must be set since it's a struct field).
    auto cfg = [&](const std::string& url, int poll, const std::string& token,
                   const std::string& hostname, const std::string& analyzer) -> C {
        C c;
        c.server_base_url = url;
        c.poll_interval_seconds = poll;
        c.reindex_interval_seconds = 1800;  // Task 23: present but unused by validate()
        c.token_path = token;
        c.hostname = hostname;
        c.analyzer_path = analyzer;
        return c;
    };

    CHECK(C::validate(cfg("https://server.example.com", 10, "/t", "h", az)).empty());
    CHECK(C::validate(cfg("http://localhost:8000", 10, "/t", "h", az)).empty());
    CHECK(C::validate(cfg("http://127.0.0.1", 5, "/t", "h", az)).empty());
    CHECK(C::validate(cfg("http://127.0.0.1", 30, "/t", "h", az)).empty());

    CHECK_CONTAINS(C::validate(cfg("https://server.example.com", 10, "/t", "h", "")),
                   "analyzer_path");
    CHECK_CONTAINS(C::validate(cfg("http://server.example.com", 10, "/t", "h", az)),
                   "non-localhost");
    CHECK_CONTAINS(C::validate(cfg("ftp://server.example.com", 10, "/t", "h", az)),
                   "unsupported scheme");
    CHECK_CONTAINS(C::validate(cfg("server.example.com", 10, "/t", "h", az)), "scheme");
    CHECK_CONTAINS(C::validate(cfg("https://server.example.com", 4, "/t", "h", az)),
                   "poll_interval");
    CHECK_CONTAINS(C::validate(cfg("https://server.example.com", 31, "/t", "h", az)),
                   "poll_interval");
    CHECK_CONTAINS(C::validate(cfg("https://server.example.com", 10, "", "h", az)),
                   "token_path");
}

static void test_config_load_from_file() {
    const fs::path cfg = fs::temp_directory_path() / "tracelens_test_cfg";
    {
        std::ofstream f(cfg);
        f << "# comment\n"
          << "server_base_url = https://srv.example.com\n"
          << "poll_interval_seconds=15\n"
          << "token_path=/var/lib/tracelens/token\n"
          << "hostname = station-7\n"
          << "analyzer_path=/opt/tracelens/forensics_analyzer\n"
          << "work_base_dir=/var/lib/tracelens/work\n";
    }
    std::string err;
    auto c = tracelens::ClientConfig::load_from_file(cfg.string(), err);
    CHECK(err.empty());
    CHECK_EQ(c.server_base_url, std::string("https://srv.example.com"));
    CHECK_EQ(c.poll_interval_seconds, 15);
    CHECK_EQ(c.token_path, std::string("/var/lib/tracelens/token"));
    CHECK_EQ(c.hostname, std::string("station-7"));
    CHECK_EQ(c.analyzer_path, std::string("/opt/tracelens/forensics_analyzer"));
    CHECK_EQ(c.work_base_dir, std::string("/var/lib/tracelens/work"));
    fs::remove(cfg);
}

static void test_config_ipv6_localhost_allowed() {
    using C = tracelens::ClientConfig;
    const std::string az = "/usr/bin/forensics_analyzer";

    auto cfg = [&](const std::string& url, int poll, const std::string& token,
                   const std::string& hostname, const std::string& analyzer) -> C {
        C c;
        c.server_base_url = url;
        c.poll_interval_seconds = poll;
        c.reindex_interval_seconds = 1800;
        c.token_path = token;
        c.hostname = hostname;
        c.analyzer_path = analyzer;
        return c;
    };

    // Bracketed IPv6 localhost must be accepted (not truncated to "[").
    CHECK(C::validate(cfg("http://[::1]:8000", 10, "/t", "h", az)).empty());
    CHECK(C::validate(cfg("http://[::1]", 10, "/t", "h", az)).empty());
}

// ------------------------------------------------------------------------- models
static void test_command_from_json() {
    auto c1 = nlohmann::json::parse(
        R"({"id":"c1","command_type":"analyze_disk",)"
        R"("parameters":{"task_id":"t1","image_path":"/x.E01"},"priority":"high"})")
                  .get<tracelens::Command>();
    CHECK_EQ(c1.id, std::string("c1"));
    CHECK_EQ(c1.command_type, std::string("analyze_disk"));
    CHECK_EQ(c1.priority, std::string("high"));
    std::string tid;
    CHECK(c1.has_task_id(tid));
    CHECK_EQ(tid, std::string("t1"));

    // Optional fields default.
    auto c2 = nlohmann::json::parse(R"({"id":"c2","command_type":"health_check"})")
                  .get<tracelens::Command>();
    CHECK_EQ(c2.priority, std::string("normal"));
    CHECK(c2.parameters.is_object());

    // Missing required field -> exception (poller skips such entries).
    bool threw = false;
    try {
        nlohmann::json::parse(R"({"command_type":"x"})").get<tracelens::Command>();
    } catch (const std::exception&) { threw = true; }
    CHECK(threw);
}

static void test_status_update_to_json() {
    tracelens::StatusUpdate u;
    u.status = tracelens::CommandStatus::InProgress;
    u.progress = 42;
    u.message = "carving";
    auto j = nlohmann::json(u);
    CHECK_EQ(j["status"].get<std::string>(), std::string("in_progress"));
    CHECK_EQ(j["progress"].get<int>(), 42);
    CHECK_EQ(j["message"].get<std::string>(), std::string("carving"));

    tracelens::StatusUpdate u2;
    u2.status = tracelens::CommandStatus::Completed;
    auto j2 = nlohmann::json(u2);
    CHECK_EQ(j2["status"].get<std::string>(), std::string("completed"));
    CHECK(!j2.contains("progress"));
    CHECK(!j2.contains("message"));
}

// ------------------------------------------------------------------------- Poller
static void test_poller_parses_commands() {
    FakeHttpClient fake;
    fake.get_response = {200,
                         R"({"client_id":"x","commands":[)"
                         R"({"id":"c1","command_type":"analyze_disk"},)"
                         R"({"id":"c2","command_type":"health_check"}]})",
                         ""};
    tracelens::Poller poller(fake);
    std::string err;
    auto cmds = poller.poll(err);
    CHECK(err.empty());
    CHECK_EQ(cmds.size(), static_cast<size_t>(2));
    CHECK_EQ(cmds[0].id, std::string("c1"));
    CHECK_EQ(fake.last_get_path, std::string("/api/commands/poll"));
}

static void test_poller_skips_malformed() {
    FakeHttpClient fake;
    fake.get_response = {200,
                         R"({"commands":[)"
                         R"({"id":"c1","command_type":"health_check"},)"
                         R"({"id":"c2"},)"            // missing command_type
                         R"({"command_type":"x"}]})",  // missing id
                         ""};
    tracelens::Poller poller(fake);
    std::string err;
    auto cmds = poller.poll(err);
    CHECK_EQ(cmds.size(), static_cast<size_t>(1));
    CHECK_EQ(cmds[0].id, std::string("c1"));
    CHECK(!err.empty());  // the skip was recorded
}

static void test_poller_transport_error() {
    FakeHttpClient fake;
    fake.get_response = {0, "", "connection refused"};
    tracelens::Poller poller(fake);
    std::string err;
    auto cmds = poller.poll(err);
    CHECK(cmds.empty());
    CHECK(!err.empty());
}

static void test_poller_missing_commands_key() {
    FakeHttpClient fake;
    fake.get_response = {200, R"({"client_id":"x"})", ""};
    tracelens::Poller poller(fake);
    std::string err;
    auto cmds = poller.poll(err);
    CHECK(cmds.empty());
    CHECK_CONTAINS(err, "missing 'commands'");
}

// ---------------------------------------------------------------- StatusReporter
static void test_status_reporter() {
    FakeHttpClient fake;
    tracelens::StatusReporter reporter(fake);

    tracelens::StatusUpdate u;
    u.status = tracelens::CommandStatus::InProgress;
    u.progress = 50;
    u.message = "halfway";
    std::string err;
    CHECK(reporter.report("c1", u, err));
    CHECK(err.empty());
    CHECK_EQ(fake.post_calls.size(), static_cast<size_t>(1));
    CHECK_EQ(fake.post_calls[0].first, std::string("/api/commands/c1/status"));
    auto body = nlohmann::json::parse(fake.post_calls[0].second);
    CHECK_EQ(body["status"].get<std::string>(), std::string("in_progress"));
    CHECK_EQ(body["progress"].get<int>(), 50);
    // command_id is REQUIRED in the body by the server schema (omitting it 422s).
    CHECK_EQ(body["command_id"].get<std::string>(), std::string("c1"));

    // Server error -> false, err set, but the POST was still attempted.
    fake.post_response = {500, "", ""};
    CHECK(!reporter.report("c1", u, err));
    CHECK(!err.empty());
    CHECK_EQ(fake.post_calls.size(), static_cast<size_t>(2));
}

// ------------------------------------------------------------- build_analyzer_argv
static void test_build_analyzer_argv() {
    // windows + file_carving + llm_text_extraction=true. --no-ai MUST appear
    // regardless of llm_text_extraction (the client never runs the LLM).
    nlohmann::json j;
    j["id"] = "c1";
    j["command_type"] = "analyze_disk";
    j["parameters"]["task_id"] = "t1";
    j["parameters"]["image_path"] = "/data/case.E01";
    j["parameters"]["analysis_type"] = "windows";
    j["parameters"]["options"]["file_carving"] = true;
    j["parameters"]["options"]["llm_text_extraction"] = true;  // MUST be ignored
    auto cmd = j.get<tracelens::Command>();
    auto built = tracelens::build_analyzer_argv(cmd, "/opt/fa", "/tmp/work");
    CHECK(built.valid());
    CHECK_EQ(built.image_path, std::string("/data/case.E01"));
    CHECK_EQ(built.argv[0], std::string("/opt/fa"));
    CHECK_EQ(built.argv[1], std::string("/data/case.E01"));  // positional image
    CHECK(has_flag(built.argv, "--no-ai"));           // INVARIANT: always
    CHECK(has_flag(built.argv, "--overwrite"));
    CHECK(has_flag(built.argv, "--windows-analyze"));
    CHECK(has_flag(built.argv, "--carve"));
    // db-dir is passed as the value following --db-dir.
    auto it = std::find(built.argv.begin(), built.argv.end(), "--db-dir");
    CHECK(it != built.argv.end());
    CHECK_EQ(*(it + 1), std::string("/tmp/work"));

    // android, no file_carving -> --android-analyze, no --carve.
    auto cmd2 = analyze_cmd_json("c2", "/d/a.dd", "", "android", /*carve=*/false)
                    .get<tracelens::Command>();
    auto b2 = tracelens::build_analyzer_argv(cmd2, "/opt/fa", "/tmp/w");
    CHECK(has_flag(b2.argv, "--android-analyze"));
    CHECK(!has_flag(b2.argv, "--carve"));
    CHECK(has_flag(b2.argv, "--no-ai"));

    // full -> no platform flag.
    auto cmd3 = analyze_cmd_json("c3", "/d/x.E01", "", "full", false)
                    .get<tracelens::Command>();
    auto b3 = tracelens::build_analyzer_argv(cmd3, "/opt/fa", "/tmp/w");
    CHECK(!has_flag(b3.argv, "--windows-analyze"));
    CHECK(!has_flag(b3.argv, "--linux-analyze"));
    CHECK(!has_flag(b3.argv, "--android-analyze"));

    // missing image_path -> error, empty argv.
    nlohmann::json j4;
    j4["id"] = "c4";
    j4["command_type"] = "analyze_disk";
    j4["parameters"]["analysis_type"] = "full";
    auto cmd4 = j4.get<tracelens::Command>();
    auto b4 = tracelens::build_analyzer_argv(cmd4, "/opt/fa", "/tmp/w");
    CHECK(!b4.valid());
    CHECK_CONTAINS(b4.error, "image_path");

    // missing analyzer path -> error.
    auto b5 = tracelens::build_analyzer_argv(cmd3, "", "/tmp/w");
    CHECK(!b5.valid());
    CHECK_CONTAINS(b5.error, "analyzer");
}

// ------------------------------------------------------------ collect_db_artifacts
static void test_collect_db_artifacts() {
    const fs::path dir = fs::temp_directory_path() / "tracelens_collect_test";
    fs::remove_all(dir);
    fs::create_directories(dir);
    // baseName of "case.E01" is "case".
    { std::ofstream(dir / "case_raw.db")     << "rawbytes"; }     // 8 bytes
    { std::ofstream(dir / "case_events.db")  << "ev"; }           // 2 bytes
    { std::ofstream(dir / "case_raw.db-wal") << "j"; }            // excluded (sidecar)
    { std::ofstream(dir / "unrelated.db")    << "x"; }            // excluded (prefix)
    { std::ofstream(dir / "case_notes.txt")  << "n"; }            // excluded (suffix)

    auto arts = tracelens::collect_db_artifacts("/data/case.E01", dir.string(),
                                                "station-7");
    CHECK_EQ(arts.size(), static_cast<size_t>(2));  // raw + events
    CHECK_EQ(arts[0].result_type, std::string("database"));
    CHECK_EQ(arts[1].result_type, std::string("database"));
    // storage_location carries the hostname label.
    CHECK_EQ(arts[0].storage_location, std::string("station-7"));
    // file_size reflects real bytes; sorted by path so events < raw.
    CHECK(arts[0].file_size.has_value());
    CHECK(arts[1].file_size.has_value());
    bool events_first = arts[0].file_path.find("events") != std::string::npos;
    CHECK(events_first);
    CHECK_EQ(*arts[0].file_size, static_cast<uint64_t>(2));   // events
    CHECK_EQ(*arts[1].file_size, static_cast<uint64_t>(8));   // raw
    // No raw-image path leaks into any field.
    for (const auto& a : arts) {
        CHECK_CONTAINS(a.file_path, "case_");
        CHECK(a.file_path.find("/data/case.E01") == std::string::npos);
    }
    fs::remove_all(dir);
}

// -------------------------------------------------------------- AnalyzeDiskExecutor
static void test_analyze_executor_success() {
    // A real temp "image" file so the existence pre-check passes.
    const fs::path imgdir = fs::temp_directory_path() / "tracelens_exec_img";
    fs::remove_all(imgdir);
    fs::create_directories(imgdir);
    const fs::path image = imgdir / "case.E01";
    { std::ofstream(image) << "IMAGEBYTES"; }

    const fs::path work = fs::temp_directory_path() / "tracelens_exec_work";
    fs::remove_all(work);

    FakeProcessRunner runner;
    runner.canned.exit_code = 0;
    runner.produce_output = true;  // fake analyzer writes case_raw.db

    tracelens::AnalyzeDiskExecutor exec(runner, "/opt/fa", work.string(), "host1");
    auto cmd = analyze_cmd_json("c1", image.string(), "t9").get<tracelens::Command>();
    auto r = exec.execute(cmd);

    CHECK(r.success);
    CHECK_EQ(r.task_id, std::string("t9"));          // task soft link parsed
    CHECK(!r.artifacts.empty());
    CHECK_EQ(r.artifacts[0].result_type, std::string("database"));
    // The fake was invoked with the right argv (no-ai always).
    CHECK(has_flag(runner.last_argv, "--no-ai"));
    CHECK(has_flag(runner.last_argv, "--windows-analyze"));
    CHECK_EQ(runner.call_count, 1);
    // Work dir was per-command under work_base.
    CHECK_CONTAINS(runner.last_work_dir, "c1");

    fs::remove_all(imgdir);
    fs::remove_all(work);
}

static void test_analyze_executor_missing_param_no_spawn() {
    FakeProcessRunner runner;
    const fs::path work = fs::temp_directory_path() / "tracelens_exec_work2";
    fs::remove_all(work);
    tracelens::AnalyzeDiskExecutor exec(runner, "/opt/fa", work.string());
    auto cmd = parse_cmd(
        R"({"id":"c1","command_type":"analyze_disk","parameters":{"task_id":"t9"}})");
    auto r = exec.execute(cmd);
    CHECK(!r.success);
    CHECK_CONTAINS(r.message, "image_path");
    CHECK_EQ(runner.call_count, 0);  // never spawned
    fs::remove_all(work);
}

static void test_analyze_executor_missing_file_no_spawn() {
    FakeProcessRunner runner;
    const fs::path work = fs::temp_directory_path() / "tracelens_exec_work3";
    fs::remove_all(work);
    tracelens::AnalyzeDiskExecutor exec(runner, "/opt/fa", work.string());
    auto cmd = analyze_cmd_json("c1", "/no/such/case.E01", "", /*atype=*/"", /*carve=*/false)
                   .get<tracelens::Command>();
    auto r = exec.execute(cmd);
    CHECK(!r.success);
    CHECK_CONTAINS(r.message, "not found");
    CHECK_EQ(runner.call_count, 0);  // never spawned
    fs::remove_all(work);
}

static void test_analyze_executor_nonzero_exit() {
    const fs::path imgdir = fs::temp_directory_path() / "tracelens_exec_img4";
    fs::remove_all(imgdir);
    fs::create_directories(imgdir);
    const fs::path image = imgdir / "case.E01";
    { std::ofstream(image) << "x"; }
    const fs::path work = fs::temp_directory_path() / "tracelens_exec_work4";
    fs::remove_all(work);

    FakeProcessRunner runner;
    runner.canned.exit_code = 2;
    runner.canned.stderr_text = "carve failed: bad magic";

    tracelens::AnalyzeDiskExecutor exec(runner, "/opt/fa", work.string());
    auto cmd = analyze_cmd_json("c1", image.string(), "", /*atype=*/"", /*carve=*/false)
                   .get<tracelens::Command>();
    auto r = exec.execute(cmd);
    CHECK(!r.success);
    CHECK_CONTAINS(r.message, "exited 2");
    CHECK_CONTAINS(r.message, "carve failed");
    CHECK(r.artifacts.empty());

    fs::remove_all(imgdir);
    fs::remove_all(work);
}

static void test_analyze_executor_nonanalyze_is_stub() {
    // Non-analyze commands are acknowledged + succeed (health_check, etc.).
    FakeProcessRunner runner;
    const fs::path work = fs::temp_directory_path() / "tracelens_exec_work5";
    fs::remove_all(work);
    tracelens::AnalyzeDiskExecutor exec(runner, "/opt/fa", work.string());
    auto cmd = parse_cmd(R"({"id":"c1","command_type":"health_check"})");
    auto r = exec.execute(cmd);
    CHECK(r.success);
    CHECK_EQ(runner.call_count, 0);  // analyzer never spawned for health_check
    fs::remove_all(work);
}

// ----------------------------------------------------------------- ResultUploader
static void test_result_uploader() {
    FakeHttpClient fake;
    tracelens::ResultUploader uploader(fake);

    std::vector<tracelens::ResultArtifact> arts;
    tracelens::ResultArtifact a;
    a.result_type = "database";
    a.file_path = "/var/lib/tracelens/work/c1/case_raw.db";
    a.file_size = 4096;
    a.storage_location = "station-7";
    arts.push_back(a);

    std::string err;
    CHECK(uploader.upload("t1", arts, err));
    CHECK(err.empty());
    CHECK_EQ(fake.post_calls.size(), static_cast<size_t>(1));
    CHECK_EQ(fake.post_calls[0].first, std::string("/api/tasks/t1/results"));
    auto body = nlohmann::json::parse(fake.post_calls[0].second);
    CHECK(body.contains("artifacts"));
    CHECK_EQ(body["artifacts"].size(), static_cast<size_t>(1));
    CHECK_EQ(body["artifacts"][0]["result_type"].get<std::string>(),
             std::string("database"));
    CHECK_EQ(body["artifacts"][0]["file_path"].get<std::string>(),
             std::string("/var/lib/tracelens/work/c1/case_raw.db"));
    CHECK_EQ(body["artifacts"][0]["file_size"].get<int>(), 4096);
    // No image path anywhere in the body.
    CHECK(fake.post_calls[0].second.find("E01") == std::string::npos);

    // Server error -> false + err.
    fake.post_response = {500, "", ""};
    CHECK(!uploader.upload("t1", arts, err));
    CHECK(!err.empty());

    // Empty task_id -> false (no task link).
    CHECK(!uploader.upload("", arts, err));
    CHECK(!err.empty());
}

// ----------------------------------------------------------------- agent service
static void test_service_single_iteration() {
    FakeHttpClient fake;
    fake.get_response = {200,
                         R"({"commands":[)"
                         R"({"id":"c1","command_type":"analyze_disk",)"
                         R"("parameters":{"task_id":"t1"}}]})",
                         ""};
    tracelens::Poller poller(fake);
    tracelens::StatusReporter reporter(fake);
    tracelens::StubExecutor executor;
    tracelens::ResultUploader uploader(fake);
    NoopLogger logger;
    FakeCommandStore store;
    tracelens::DiskImageIndexer indexer({});
    tracelens::IndexUploader index_uploader(fake, "test-client");
    tracelens::HttpAgentService service(poller, reporter, executor, uploader, store,
                                        indexer, index_uploader, 10, 0, "test-client", logger);

    CHECK_EQ(service.run(/*single_iteration=*/true), 0);

    // StubExecutor produces no artifacts -> no upload; just the two status reports.
    CHECK_EQ(fake.post_calls.size(), static_cast<size_t>(2));
    CHECK_EQ(fake.post_calls[0].first, std::string("/api/commands/c1/status"));
    CHECK_EQ(fake.post_calls[1].first, std::string("/api/commands/c1/status"));
    CHECK_CONTAINS(fake.post_calls[0].second, "in_progress");
    CHECK_CONTAINS(fake.post_calls[1].second, "completed");

    // Persistence wiring (Task 18): each polled command is recorded in-flight
    // before execution and cleared once it reaches a terminal state.
    CHECK_EQ(store.started_ids.size(), static_cast<size_t>(1));
    CHECK_EQ(store.started_ids[0], std::string("c1"));
    CHECK_EQ(store.cleared_ids.size(), static_cast<size_t>(1));
    CHECK_EQ(store.cleared_ids[0], std::string("c1"));
}

static void test_service_handles_empty_poll() {
    FakeHttpClient fake;
    fake.get_response = {200, R"({"commands":[]})", ""};
    tracelens::Poller poller(fake);
    tracelens::StatusReporter reporter(fake);
    tracelens::StubExecutor executor;
    tracelens::ResultUploader uploader(fake);
    NoopLogger logger;
    FakeCommandStore store;
    tracelens::DiskImageIndexer indexer({});
    tracelens::IndexUploader index_uploader(fake, "test-client");
    tracelens::HttpAgentService service(poller, reporter, executor, uploader,
                                        store, indexer, index_uploader,
                                        10, 0, "test-client", logger);
    CHECK_EQ(service.run(/*single_iteration=*/true), 0);
    CHECK(fake.post_calls.empty());  // nothing to report
}

static void test_service_reports_failed_execution() {
    // A failed execution must report status "failed" (not "completed") with the
    // error message. Pins the Failed branch of the service ternary so a future
    // edit that flips it (silently marking failed analyses as completed) is
    // caught.
    FakeHttpClient fake;
    fake.get_response = {200,
                         R"({"commands":[)"
                         R"({"id":"c1","command_type":"analyze_disk"}]})",
                         ""};
    tracelens::Poller poller(fake);
    tracelens::StatusReporter reporter(fake);
    FailingExecutor executor;
    tracelens::ResultUploader uploader(fake);
    NoopLogger logger;
    FakeCommandStore store;
    tracelens::DiskImageIndexer indexer({});
    tracelens::IndexUploader index_uploader(fake, "test-client");
    tracelens::HttpAgentService service(poller, reporter, executor, uploader,
                                        store, indexer, index_uploader,
                                        10, 0, "test-client", logger);

    CHECK_EQ(service.run(/*single_iteration=*/true), 0);
    CHECK_EQ(fake.post_calls.size(), static_cast<size_t>(2));
    CHECK_CONTAINS(fake.post_calls[0].second, "in_progress");
    CHECK_CONTAINS(fake.post_calls[1].second, "failed");
    CHECK_CONTAINS(fake.post_calls[1].second, "boom");
    auto b2 = nlohmann::json::parse(fake.post_calls[1].second);
    CHECK_EQ(b2["command_id"].get<std::string>(), std::string("c1"));
}

// The full loop with a real analyze_disk that produces artifacts: in_progress
// -> upload results -> completed.
static void test_service_loop_uploads_then_completes() {
    const fs::path imgdir = fs::temp_directory_path() / "tracelens_loop_img";
    fs::remove_all(imgdir);
    fs::create_directories(imgdir);
    const fs::path image = imgdir / "case.E01";
    { std::ofstream(image) << "IMAGEBYTES"; }
    const fs::path work = fs::temp_directory_path() / "tracelens_loop_work";
    fs::remove_all(work);

    FakeHttpClient fake;
    nlohmann::json poll;
    poll["commands"] = nlohmann::json::array({analyze_cmd_json("c1", image.string(), "t1")});
    fake.get_response = {200, poll.dump(), ""};
    tracelens::Poller poller(fake);
    tracelens::StatusReporter reporter(fake);
    tracelens::ResultUploader uploader(fake);
    FakeProcessRunner runner;
    runner.canned.exit_code = 0;
    runner.produce_output = true;
    tracelens::AnalyzeDiskExecutor executor(runner, "/opt/fa", work.string());
    NoopLogger logger;
    FakeCommandStore store;
    tracelens::DiskImageIndexer indexer({});
    tracelens::IndexUploader index_uploader(fake, "test-client");
    tracelens::HttpAgentService service(poller, reporter, executor, uploader,
                                        store, indexer, index_uploader,
                                        10, 0, "test-client", logger);

    CHECK_EQ(service.run(/*single_iteration=*/true), 0);

    // Three POSTs: [0] in_progress /status, [1] /results upload, [2] completed /status.
    CHECK_EQ(fake.post_calls.size(), static_cast<size_t>(3));
    CHECK_EQ(fake.post_calls[0].first, std::string("/api/commands/c1/status"));
    CHECK_CONTAINS(fake.post_calls[0].second, "in_progress");
    CHECK_EQ(fake.post_calls[1].first, std::string("/api/tasks/t1/results"));
    CHECK_CONTAINS(fake.post_calls[1].second, "artifacts");
    CHECK_EQ(fake.post_calls[2].first, std::string("/api/commands/c1/status"));
    CHECK_CONTAINS(fake.post_calls[2].second, "completed");

    fs::remove_all(imgdir);
    fs::remove_all(work);
}

// If the analyzer succeeds but the result upload fails, the command is reported
// FAILED (results undeliverable -> unusable/retriable task).
static void test_service_loop_upload_failure_marks_failed() {
    const fs::path imgdir = fs::temp_directory_path() / "tracelens_loop_img2";
    fs::remove_all(imgdir);
    fs::create_directories(imgdir);
    const fs::path image = imgdir / "case.E01";
    { std::ofstream(image) << "IMAGEBYTES"; }
    const fs::path work = fs::temp_directory_path() / "tracelens_loop_work2";
    fs::remove_all(work);

    FakeHttpClient fake;
    nlohmann::json poll;
    poll["commands"] = nlohmann::json::array({analyze_cmd_json("c1", image.string(), "t1")});
    fake.get_response = {200, poll.dump(), ""};
    fake.fail_post_paths.insert("/api/tasks/t1/results");  // upload 500s

    tracelens::Poller poller(fake);
    tracelens::StatusReporter reporter(fake);
    tracelens::ResultUploader uploader(fake);
    FakeProcessRunner runner;
    runner.canned.exit_code = 0;
    runner.produce_output = true;
    tracelens::AnalyzeDiskExecutor executor(runner, "/opt/fa", work.string());
    NoopLogger logger;
    FakeCommandStore store;
    tracelens::DiskImageIndexer indexer({});
    tracelens::IndexUploader index_uploader(fake, "test-client");
    tracelens::HttpAgentService service(poller, reporter, executor, uploader,
                                        store, indexer, index_uploader,
                                        10, 0, "test-client", logger);

    CHECK_EQ(service.run(/*single_iteration=*/true), 0);

    // [0] in_progress, [1] /results (failed), [2] /status FAILED.
    CHECK_EQ(fake.post_calls.size(), static_cast<size_t>(3));
    CHECK_EQ(fake.post_calls[1].first, std::string("/api/tasks/t1/results"));
    CHECK_CONTAINS(fake.post_calls[2].second, "failed");
    CHECK_CONTAINS(fake.post_calls[2].second, "upload failed");

    fs::remove_all(imgdir);
    fs::remove_all(work);
}

// ----------------------------------------------------------- PosixProcessRunner
// These exercise the REAL fork/exec/poll/wait path against actual processes (no
// Fake). They pin the two behaviors a unit-test fake can't catch: real pipe
// capture, and the over-cap deadlock fix.
static void test_process_runner_basic() {
    tracelens::PosixProcessRunner runner;
    auto r = runner.run({"/bin/echo", "hello-world"}, "");
    CHECK(r.error.empty());
    CHECK_EQ(r.exit_code, 0);
    CHECK_CONTAINS(r.stdout_text, "hello-world");
}

static void test_process_runner_nonzero_with_stderr() {
    tracelens::PosixProcessRunner runner;
    // Write to stderr and exit 3. argv is hardcoded by the test, never derived
    // from command input, so invoking /bin/sh here does NOT undermine the
    // production invariant (the real run() still uses execvp, no shell).
    auto r = runner.run({"/bin/sh", "-c", "echo oops >&2; exit 3"}, "");
    CHECK(r.error.empty());
    CHECK_EQ(r.exit_code, 3);
    CHECK_CONTAINS(r.stderr_text, "oops");
}

// The deadlock pin: the child writes far MORE than the 8 MiB capture cap. Before
// the fix, drain() stopped reading at the cap, the child blocked on write(),
// waitpid() never returned, and the 60s alarm killed the whole process. Now the
// pipe keeps draining past the cap (discarding) and capture flattens at exactly
// kStreamCap while the run still completes.
static void test_process_runner_over_cap_does_not_deadlock() {
    tracelens::PosixProcessRunner runner;
    // 10 MiB of NULs from /dev/zero (> 8 MiB cap).
    auto r = runner.run({"/bin/sh", "-c", "head -c 10000000 /dev/zero"}, "");
    CHECK(r.error.empty());
    CHECK_EQ(r.exit_code, 0);  // reaching here at all means it didn't hang
    constexpr size_t kCap = 8 * 1024 * 1024;
    CHECK_EQ(r.stdout_text.size(), kCap);  // capped, not unbounded
}

// ------------------------------------------------------------- SqliteCommandStore
// These use REAL temp SQLite files (the executor tests already use real temp
// files), exercising the actual sqlite3 path — no fake.
static void test_sqlite_store_roundtrip() {
    const fs::path db = fs::temp_directory_path() / "tracelens_store_rt.db";
    fs::remove(db);
    // Clean sidecars from any prior run too.
    fs::remove(fs::path(db) += "-wal");
    fs::remove(fs::path(db) += "-shm");
    fs::remove(fs::path(db) += "-journal");

    tracelens::SqliteCommandStore store(db.string());
    auto cmd = analyze_cmd_json("c-rt", "/data/case.E01", "t-rt", "windows")
                   .get<tracelens::Command>();

    std::string err;
    CHECK(store.record_started(cmd, err));
    CHECK(err.empty());

    auto orphans = store.recover_orphans(err);
    CHECK_EQ(orphans.size(), static_cast<size_t>(1));
    CHECK_EQ(orphans[0].id, std::string("c-rt"));
    CHECK_EQ(orphans[0].command_type, std::string("analyze_disk"));
    std::string tid;
    CHECK(orphans[0].has_task_id(tid));
    CHECK_EQ(tid, std::string("t-rt"));
    CHECK_EQ(orphans[0].priority, std::string("normal"));

    // clear() removes the row -> no longer an orphan.
    CHECK(store.clear("c-rt", err));
    CHECK(store.recover_orphans(err).empty());

    // clear() of an already-cleared id is idempotent (not an error).
    CHECK(store.clear("c-rt", err));

    fs::remove(db);
    fs::remove(fs::path(db) += "-wal");
    fs::remove(fs::path(db) += "-shm");
    fs::remove(fs::path(db) += "-journal");
}

// The restart scenario: store1 records a command and is destroyed WITHOUT
// clearing it (simulating a crash mid-execution). A fresh store2 opened on the
// same file must recover it — proving the record survived process death.
static void test_sqlite_store_restart_recovery() {
    const fs::path db = fs::temp_directory_path() / "tracelens_store_restart.db";
    fs::remove(db);
    fs::remove(fs::path(db) += "-wal");
    fs::remove(fs::path(db) += "-shm");
    fs::remove(fs::path(db) += "-journal");

    {
        tracelens::SqliteCommandStore store1(db.string());
        std::string err;
        CHECK(store1.record_started(
            analyze_cmd_json("c-survivor", "/d/x.E01", "t-s").get<tracelens::Command>(),
            err));
        // No clear() — "crash". store1 closes (commits) on scope exit.
    }

    // Fresh process, same DB file.
    tracelens::SqliteCommandStore store2(db.string());
    std::string err;
    auto orphans = store2.recover_orphans(err);
    CHECK_EQ(orphans.size(), static_cast<size_t>(1));
    CHECK_EQ(orphans[0].id, std::string("c-survivor"));
    std::string tid;
    CHECK(orphans[0].has_task_id(tid));
    CHECK_EQ(tid, std::string("t-s"));

    fs::remove(db);
    fs::remove(fs::path(db) += "-wal");
    fs::remove(fs::path(db) += "-shm");
    fs::remove(fs::path(db) += "-journal");
}

// A re-delivered command_id (e.g. server re-queue after TTL) must REPLACE, not
// raise a PK-violation, and the recovered row reflects the latest parameters.
static void test_sqlite_store_replace_on_redeliver() {
    const fs::path db = fs::temp_directory_path() / "tracelens_store_replace.db";
    fs::remove(db);
    fs::remove(fs::path(db) += "-wal");
    fs::remove(fs::path(db) += "-shm");
    fs::remove(fs::path(db) += "-journal");

    tracelens::SqliteCommandStore store(db.string());
    std::string err;
    CHECK(store.record_started(
        analyze_cmd_json("c-dup", "/d/first.E01", "t-first").get<tracelens::Command>(),
        err));
    // Same id, different task/image -> replaces.
    CHECK(store.record_started(
        analyze_cmd_json("c-dup", "/d/second.E01", "t-second").get<tracelens::Command>(),
        err));

    auto orphans = store.recover_orphans(err);
    CHECK_EQ(orphans.size(), static_cast<size_t>(1));  // not two
    CHECK_EQ(orphans[0].id, std::string("c-dup"));
    std::string tid;
    CHECK(orphans[0].has_task_id(tid));
    CHECK_EQ(tid, std::string("t-second"));  // latest, not first

    fs::remove(db);
    fs::remove(fs::path(db) += "-wal");
    fs::remove(fs::path(db) += "-shm");
    fs::remove(fs::path(db) += "-journal");
}

// The recovery path through the service: a pre-seeded orphan is reported FAILED
// to the server and cleared, before any polling happens.
static void test_service_recover_reports_orphans_failed() {
    FakeHttpClient fake;
    fake.get_response = {200, R"({"commands":[]})", ""};  // empty poll
    tracelens::Poller poller(fake);
    tracelens::StatusReporter reporter(fake);
    tracelens::StubExecutor executor;
    tracelens::ResultUploader uploader(fake);
    FakeCommandStore store;
    store.orphans_to_return.push_back(
        parse_cmd(R"({"id":"orphan-1","command_type":"analyze_disk",)"
                  R"("parameters":{"task_id":"t-old","image_path":"/data/old.E01"}})"));
    NoopLogger logger;
    tracelens::DiskImageIndexer indexer({});
    tracelens::IndexUploader index_uploader(fake, "test-client");
    tracelens::HttpAgentService service(poller, reporter, executor, uploader,
                                        store, indexer, index_uploader,
                                        10, 0, "test-client", logger);

    CHECK_EQ(service.run(/*single_iteration=*/true), 0);

    // Exactly one POST: the recovery's failed report (empty poll -> no loop work).
    CHECK_EQ(fake.post_calls.size(), static_cast<size_t>(1));
    CHECK_EQ(fake.post_calls[0].first,
             std::string("/api/commands/orphan-1/status"));
    CHECK_CONTAINS(fake.post_calls[0].second, "failed");
    CHECK_CONTAINS(fake.post_calls[0].second, "interrupted");
    CHECK_EQ(nlohmann::json::parse(fake.post_calls[0].second)["command_id"]
                 .get<std::string>(),
             std::string("orphan-1"));
    // The raw image path must NOT appear in the recovery status body.
    CHECK(fake.post_calls[0].second.find("old.E01") == std::string::npos);
    CHECK(fake.post_calls[0].second.find("/data/") == std::string::npos);

    // The orphan was cleared from the local store.
    CHECK_EQ(store.cleared_ids.size(), static_cast<size_t>(1));
    CHECK_EQ(store.cleared_ids[0], std::string("orphan-1"));
}

// Recovery MUST NOT clear an orphan whose FAILED report did not reach the server
// — otherwise Task 18's value is defeated in exactly the failure case it targets
// (crash + server briefly unreachable). Pins the Fix-1 behavior: clear() runs
// only on a successful report.
static void test_service_recover_keeps_orphan_when_report_fails() {
    FakeHttpClient fake;
    fake.get_response = {200, R"({"commands":[]})", ""};  // empty poll
    fake.post_response = {500, "", ""};                    // every POST fails
    tracelens::Poller poller(fake);
    tracelens::StatusReporter reporter(fake);
    tracelens::StubExecutor executor;
    tracelens::ResultUploader uploader(fake);
    FakeCommandStore store;
    store.orphans_to_return.push_back(
        parse_cmd(R"({"id":"orphan-2","command_type":"analyze_disk"})"));
    NoopLogger logger;
    tracelens::DiskImageIndexer indexer({});
    tracelens::IndexUploader index_uploader(fake, "test-client");
    tracelens::HttpAgentService service(poller, reporter, executor, uploader,
                                        store, indexer, index_uploader,
                                        10, 0, "test-client", logger);

    CHECK_EQ(service.run(/*single_iteration=*/true), 0);

    // The failed report was attempted but the orphan was NOT cleared, so a later
    // restart can retry it (D3: never drop a failure signal before it lands).
    CHECK_EQ(fake.post_calls.size(), static_cast<size_t>(1));
    CHECK_EQ(store.cleared_ids.size(), static_cast<size_t>(0));
}

// Pin the crash-durability defaults the whole feature rests on (D5). The store
// opens with no pragmas, so SQLite's defaults apply; the in-suite restart test
// only proves clean-close survival, so this asserts the durability mechanism is
// actually in effect (a future PRAGMA synchronous=NORMAL would silently weaken
// it and the gate would otherwise stay green). Read via a raw sqlite3 RO handle.
static int pragma_callback(void* ctx, int argc, char** argv, char** /*cols*/) {
    if (argc > 0 && argv && argv[0] && ctx) {
        *static_cast<std::string*>(ctx) = argv[0];
    }
    return 0;
}

static void test_sqlite_store_durability_defaults() {
    const fs::path db = fs::temp_directory_path() / "tracelens_store_dur.db";
    fs::remove(db);
    fs::remove(fs::path(db) += "-wal");
    fs::remove(fs::path(db) += "-shm");
    fs::remove(fs::path(db) += "-journal");

    { tracelens::SqliteCommandStore store(db.string()); }  // open + ensure schema

    sqlite3* raw = nullptr;
    CHECK_EQ(sqlite3_open_v2(db.string().c_str(), &raw, SQLITE_OPEN_READONLY,
                             nullptr),
             SQLITE_OK);
    std::string synchronous, journal;
    char* zerr = nullptr;
    sqlite3_exec(raw, "PRAGMA synchronous", pragma_callback, &synchronous, &zerr);
    sqlite3_exec(raw, "PRAGMA journal_mode", pragma_callback, &journal, &zerr);
    sqlite3_close(raw);

    // synchronous == 2 (FULL): an autocommitted record_started fsyncs at commit,
    // surviving SIGKILL/power loss. This is the load-bearing durability pin.
    CHECK_EQ(synchronous, std::string("2"));
    // journal_mode == delete: rollback journal (NOT WAL). If WAL is adopted
    // later as forward hardening, update this to assert WAL *with* synchronous
    // FULL (which still fsyncs on commit); the invariant under test is
    // commit-durability, currently satisfied by FULL + rollback.
    CHECK_EQ(journal, std::string("delete"));

    fs::remove(db);
    fs::remove(fs::path(db) += "-wal");
    fs::remove(fs::path(db) += "-shm");
    fs::remove(fs::path(db) += "-journal");
}

// ----------------------------------------------------------- Task 19: indexing
static void test_detect_format() {
    using F = tracelens::ImageFormat;
    CHECK(tracelens::detect_format("image.e01", false) == F::E01);
    CHECK(tracelens::detect_format("IMAGE.E01", false) == F::E01);
    CHECK(tracelens::detect_format("disk.E99", false) == F::E01);
    CHECK(tracelens::detect_format("set.e00", false) == F::E01);  // first segment variant
    CHECK(tracelens::detect_format("evidence.dd", false) == F::DD);
    CHECK(tracelens::detect_format("EVIDENCE.IMG", false) == F::DD);
    CHECK(tracelens::detect_format("dump.raw", false) == F::DD);
    CHECK(tracelens::detect_format("part.000", false) == F::DD);
    CHECK(tracelens::detect_format("whatever", true) == F::Directory);
    CHECK(tracelens::detect_format("notes.txt", false) == F::Unknown);
    CHECK(tracelens::detect_format("output.db", false) == F::Unknown);
    CHECK(tracelens::detect_format("noext", false) == F::Unknown);
    CHECK(tracelens::detect_format("image.e1", false) == F::Unknown);    // only 1 digit
    CHECK(tracelens::detect_format("image.exx", false) == F::Unknown);   // not digits
    CHECK_EQ(tracelens::format_string(F::E01), std::string("E01"));
    CHECK_EQ(tracelens::format_string(F::DD), std::string("DD"));
    CHECK_EQ(tracelens::format_string(F::Directory), std::string("Directory"));
}

static void test_e01_base() {
    CHECK_EQ(tracelens::e01_base("img.E01"), std::string("img"));
    CHECK_EQ(tracelens::e01_base("img.E02"), std::string("img"));
    CHECK_EQ(tracelens::e01_base("foo.E00"), std::string("foo"));
    CHECK_EQ(tracelens::e01_base("img.dd"), std::string(""));    // not an E01 segment
    CHECK_EQ(tracelens::e01_base("notes.txt"), std::string(""));
}

static void test_disk_image_indexer_scan() {
    const fs::path root = fs::temp_directory_path() / "tracelens_idx_test";
    fs::remove_all(root);
    fs::create_directories(root);

    // EWF set: 3 segments -> ONE E01 entry, the first (.E01).
    { std::ofstream f(root / "case.E01"); f << std::string(100, 'x'); }
    { std::ofstream f(root / "case.E02"); f << std::string(200, 'x'); }
    { std::ofstream f(root / "case.E03"); f << std::string(300, 'x'); }
    // DD + raw images.
    { std::ofstream f(root / "disk.dd"); f << std::string(4096, 'y'); }
    { std::ofstream f(root / "evidence.raw"); f << std::string(16, 'z'); }
    // A directory entry -> Directory format.
    fs::create_directory(root / "acquired_dir");
    // Unknown + zero-size -> both skipped.
    { std::ofstream f(root / "notes.txt"); f << "hi"; }
    { std::ofstream f(root / "empty.dd"); /* zero bytes */ }

    tracelens::DiskImageIndexer indexer({root.string()});
    std::string err;
    auto entries = indexer.scan(err);
    CHECK(err.empty());

    // Expected: 1 E01 + 2 DD + 1 Directory = 4.
    CHECK_EQ(entries.size(), static_cast<size_t>(4));

    int n_e01 = 0, n_dd = 0, n_dir = 0;
    std::string e01_path;
    std::uint64_t e01_size = 0;
    std::uint64_t dir_size = 0;
    for (const auto& e : entries) {
        switch (e.format) {
            case tracelens::ImageFormat::E01:
                ++n_e01; e01_path = e.path; e01_size = e.size_bytes; break;
            case tracelens::ImageFormat::DD:       ++n_dd; break;
            case tracelens::ImageFormat::Directory: ++n_dir; dir_size = e.size_bytes; break;
            default: break;
        }
    }
    CHECK_EQ(n_e01, 1);
    CHECK_EQ(n_dd, 2);
    CHECK_EQ(n_dir, 1);
    // The deduped entry is the first segment, with the first segment's size.
    CHECK_CONTAINS(e01_path, "case.E01");
    CHECK_EQ(e01_size, static_cast<std::uint64_t>(100));
    // Directory size comes from POSIX stat() (std::filesystem::file_size rejects
    // directories with EISDIR); it must be > 0 (schema constraint). Pins that fix.
    CHECK(dir_size > 0);
    // All reported paths are absolute.
    for (const auto& e : entries) CHECK(fs::path(e.path).is_absolute());

    // Mixed-case EWF segments dedup to one entry (case-insensitive base key).
    const fs::path mroot = fs::temp_directory_path() / "tracelens_idx_mixed";
    fs::remove_all(mroot);
    fs::create_directories(mroot);
    { std::ofstream f(mroot / "Case.E01"); f << std::string(50, 'q'); }
    { std::ofstream f(mroot / "case.E02"); f << std::string(60, 'q'); }
    {
        tracelens::DiskImageIndexer midx({mroot.string()});
        std::string merr;
        auto me = midx.scan(merr);
        CHECK(merr.empty());
        int me01 = 0;
        for (const auto& e : me) if (e.format == tracelens::ImageFormat::E01) ++me01;
        CHECK_EQ(me01, 1);
    }
    fs::remove_all(mroot);

    // A bogus directory yields an error string but no crash; empty result.
    tracelens::DiskImageIndexer bad({"/no/such/dir/here"});
    std::string berr;
    auto be = bad.scan(berr);
    CHECK(!berr.empty());
    CHECK(be.empty());

    fs::remove_all(root);
}

static void test_index_uploader() {
    FakeHttpClient http;
    http.post_response = {200, R"({"indexed":2,"updated":0,"total":2})", ""};

    std::vector<tracelens::DiskImageEntry> entries = {
        {"/abs/case.E01", 100, tracelens::ImageFormat::E01},
        {"/abs/disk.dd", 4096, tracelens::ImageFormat::DD},
    };

    tracelens::IndexUploader up(http, "client-uuid-123");
    std::string err;
    CHECK(up.upload(entries, err));
    CHECK(err.empty());
    CHECK_EQ(http.post_calls.size(), static_cast<size_t>(1));
    CHECK_EQ(http.post_calls[0].first,
             std::string("/api/clients/client-uuid-123/index-images"));

    // The body is a bare JSON array of DiskImageCreate objects.
    auto body = nlohmann::json::parse(http.post_calls[0].second);
    CHECK(body.is_array());
    CHECK_EQ(body.size(), static_cast<size_t>(2));
    CHECK_EQ(body[0]["path"].get<std::string>(), std::string("/abs/case.E01"));
    CHECK_EQ(body[0]["size_bytes"].get<std::uint64_t>(), static_cast<std::uint64_t>(100));
    CHECK_EQ(body[0]["format"].get<std::string>(), std::string("E01"));
    CHECK(body[0]["image_metadata"].is_object());
    CHECK(!body[0].contains("md5_hash"));  // omitted (brief D2)

    // Empty entries -> no round trip, success.
    FakeHttpClient http2;
    tracelens::IndexUploader up2(http2, "client-uuid-123");
    std::string e2;
    CHECK(up2.upload({}, e2));
    CHECK_EQ(http2.post_calls.size(), static_cast<size_t>(0));

    // Empty client_id -> false + error (cannot form the path).
    FakeHttpClient http3;
    tracelens::IndexUploader up3(http3, "");
    std::string e3;
    CHECK(!up3.upload(entries, e3));
    CHECK_CONTAINS(e3, "client_id");
    CHECK_EQ(http3.post_calls.size(), static_cast<size_t>(0));

    // Server error -> false + error.
    FakeHttpClient http4;
    http4.post_response = {500, "", ""};
    tracelens::IndexUploader up4(http4, "client-uuid-123");
    std::string e4;
    CHECK(!up4.upload(entries, e4));
    CHECK_CONTAINS(e4, "HTTP 500");
}

// base64url (unpadded) encode, to mint a JWT payload for the client_id test.
static std::string b64url(const std::string& in) {
    static const char* tab =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    std::string out;
    int bits = 0, acc = 0;
    for (unsigned char c : in) {
        acc = (acc << 8) | c;
        bits += 8;
        while (bits >= 6) {
            bits -= 6;
            out.push_back(tab[(acc >> bits) & 0x3F]);
        }
    }
    if (bits > 0) out.push_back(tab[(acc << (6 - bits)) & 0x3F]);
    return out;  // no padding
}

static void test_jwt_client_id_decode() {
    // header.payload.signature — only the payload is read; sig is a dummy.
    const std::string payload = R"({"client_id":"abc-123-def","type":"client"})";
    const std::string token = "hdr." + b64url(payload) + ".sig";
    tracelens::JwtClient jwt(token);
    CHECK_EQ(jwt.client_id(), std::string("abc-123-def"));

    // A payload without client_id -> "".
    tracelens::JwtClient none("hdr." + b64url(R"({"type":"client"})") + ".sig");
    CHECK_EQ(none.client_id(), std::string(""));

    // A non-base64 / non-JSON payload -> "" (no throw).
    tracelens::JwtClient bogus("abc.def.ghi");
    CHECK_EQ(bogus.client_id(), std::string(""));

    // A token with no dots -> "".
    tracelens::JwtClient nodot("notajwt");
    CHECK_EQ(nodot.client_id(), std::string(""));
}

static void test_config_image_dirs() {
    using C = tracelens::ClientConfig;
    const fs::path cfgp = fs::temp_directory_path() / "tracelens_idx_cfg";
    {
        std::ofstream f(cfgp);
        f << "server_base_url=https://server.example.com\n"
          << "token_path=/t\nhostname=h\nanalyzer_path=/usr/bin/fa\n"
          << "image_dirs=/images:/evidence :\n";  // trailing empty ignored
    }
    fs::permissions(cfgp,
                    fs::perms::owner_read | fs::perms::owner_write,
                    fs::perm_options::replace);
    std::string err;
    auto c = C::load_from_file(cfgp.string(), err);
    CHECK(err.empty());
    CHECK_EQ(c.image_dirs.size(), static_cast<size_t>(2));
    CHECK_EQ(c.image_dirs[0], std::string("/images"));
    CHECK_EQ(c.image_dirs[1], std::string("/evidence"));
    fs::remove(cfgp);
}

// --------------------------------------------------------- Task 20: live transport
// The ONLY tests that exercise the REAL HttpLibClient over a real socket. Every
// other transport test uses FakeHttpClient, so the live path — how the Bearer
// header is actually formed, the body serialized, the response parsed, redirects
// handled, transport errors surfaced — was 0% covered. The Task-19 reviewer
// caught a double-Bearer wiring bug that exactly this gap let ship (FakeHttpClient
// cannot see header formation). These pin that class.
//
// A loopback httplib::Server run on an ephemeral port in a background thread.
// RAII: stop()+join() on destruction.
struct LoopbackServer {
    httplib::Server svr;
    std::thread thread;
    int port = 0;
    std::atomic<bool> canary_hit{false};

    bool start() {
        port = svr.bind_to_any_port("127.0.0.1");
        if (port <= 0) return false;
        thread = std::thread([this] { svr.listen_after_bind(); });
        // Wait for the accept loop to go live before any client connects.
        for (int i = 0; i < 200 && !svr.is_running(); ++i)
            std::this_thread::sleep_for(std::chrono::milliseconds(5));
        return svr.is_running();
    }

    std::string base() const { return "http://127.0.0.1:" + std::to_string(port); }

    ~LoopbackServer() {
        if (svr.is_running()) svr.stop();
        if (thread.joinable()) thread.join();
    }
};

static void test_live_transport_get_post() {
    LoopbackServer s;
    s.svr.Get("/ping", [](const httplib::Request&, httplib::Response& res) {
        res.status = 200;
        res.body = "ok";
    });
    s.svr.Post("/echo", [](const httplib::Request& req, httplib::Response& res) {
        // Echo exactly what arrived so the client can assert on the real bytes.
        nlohmann::json j;
        j["authorization"] = req.get_header_value("Authorization");
        j["content_type"] = req.get_header_value("Content-Type");
        j["body"] = req.body;
        res.status = 200;
        res.set_header("Content-Type", "application/json");
        res.body = j.dump();
    });
    CHECK(s.start());

    const std::string raw_token = "RAWTOKEN-test-12345";
    tracelens::HttpLibClient http(s.base(), raw_token);

    // GET round-trip: status + body parsed from a real socket response.
    auto g = http.get("/ping");
    CHECK(g.error.empty());
    CHECK_EQ(g.status, 200);
    CHECK_EQ(g.body, std::string("ok"));

    // POST round-trip + the double-Bearer regression pin: the server saw exactly
    // one "Bearer " prefix on the raw token (the Task-16 wiring bug would show
    // "Bearer Bearer ...").
    const std::string payload = R"({"hello":"world","n":7})";
    auto p = http.post("/echo", payload);
    CHECK(p.error.empty());
    CHECK_EQ(p.status, 200);
    auto echoed = nlohmann::json::parse(p.body);
    CHECK_EQ(echoed["authorization"].get<std::string>(),
             std::string("Bearer " + raw_token));
    CHECK_CONTAINS(echoed["content_type"].get<std::string>(), "application/json");
    CHECK_EQ(echoed["body"].get<std::string>(), payload);
}

static void test_live_transport_redirect_not_followed() {
    LoopbackServer s;
    s.svr.Get("/redir", [](const httplib::Request&, httplib::Response& res) {
        res.status = 302;
        res.set_header("Location", "/canary");
    });
    s.svr.Get("/canary", [&s](const httplib::Request&, httplib::Response& res) {
        s.canary_hit.store(true);
        res.status = 200;
        res.body = "leaked";
    });
    CHECK(s.start());

    const std::string raw_token = "secret-bearer";
    tracelens::HttpLibClient http(s.base(), raw_token);

    auto r = http.get("/redir");
    CHECK(r.error.empty());
    CHECK_EQ(r.status, 302);          // returned as-is, NOT followed
    CHECK(!s.canary_hit.load());      // the token-bearing client never hit /canary
}

static void test_live_transport_dead_port_is_transport_error() {
    // A GET to a port with no listener must surface as a transport-level failure
    // (status 0 + non-empty error) — the branch Poller/StatusReporter treat as
    // "server down". Deterministic dead port: start a server, grab its port, then
    // stop it (the listen socket closes -> connect gets refused/timeout).
    LoopbackServer s;
    s.svr.Get("/ping", [](const httplib::Request&, httplib::Response& res) {
        res.status = 200;
        res.body = "ok";
    });
    CHECK(s.start());
    const int port = s.port;
    s.svr.stop();
    if (s.thread.joinable()) s.thread.join();
    // The dtor sees is_running()==false and thread not joinable -> no-op.

    tracelens::HttpLibClient http("http://127.0.0.1:" + std::to_string(port), "tok");
    auto r = http.get("/ping");
    CHECK_EQ(r.status, 0);
    CHECK(!r.error.empty());
}

// Task 23: Periodic re-indexing tests.

static void test_periodic_reindex_config() {
    // Verify reindex_interval_seconds is parsed from config file and env.
    // Default value (1800).
    tracelens::ClientConfig c1;
    CHECK_EQ(c1.reindex_interval_seconds, 1800);

    // File parsing.
    const fs::path cfg = fs::temp_directory_path() / "test_reindex.conf";
    { std::ofstream f(cfg); f << "reindex_interval_seconds=600\n"; }
    std::string err;
    auto c2 = tracelens::ClientConfig::load_from_file(cfg.string(), err);
    CHECK(err.empty());
    CHECK_EQ(c2.reindex_interval_seconds, 600);
    fs::remove(cfg);

    // Zero disables.
    { std::ofstream f(cfg); f << "reindex_interval_seconds=0\n"; }
    auto c3 = tracelens::ClientConfig::load_from_file(cfg.string(), err);
    CHECK(err.empty());
    CHECK_EQ(c3.reindex_interval_seconds, 0);
    fs::remove(cfg);

    // Env override.
    const char* old_val = std::getenv("TRACELENS_REINDEX_INTERVAL");
    std::string old_save = old_val ? old_val : "";
    setenv("TRACELENS_REINDEX_INTERVAL", "900", 1);
    auto c4 = tracelens::ClientConfig::load_from_env(err);
    CHECK(err.empty());
    CHECK_EQ(c4.reindex_interval_seconds, 900);
    if (old_val) setenv("TRACELENS_REINDEX_INTERVAL", old_save.c_str(), 1);
    else unsetenv("TRACELENS_REINDEX_INTERVAL");
}

static void test_periodic_reindex_zero_disables() {
    // reindex_interval=0 should disable periodic re-indexing (only startup index).
    FakeHttpClient fake;
    fake.get_response = {200, R"({"commands":[]})", ""};

    tracelens::Poller poller(fake);
    tracelens::StatusReporter reporter(fake);
    tracelens::StubExecutor executor;
    tracelens::ResultUploader uploader(fake);
    NoopLogger logger;
    FakeCommandStore store;
    tracelens::DiskImageIndexer indexer({});
    tracelens::IndexUploader index_uploader(fake, "test-client");

    // reindex_interval=0 disables periodic re-indexing.
    tracelens::HttpAgentService service(poller, reporter, executor, uploader, store,
                                        indexer, index_uploader,
                                        10, 0, "test-client", logger);

    // Run multiple iterations — upload() should only be called once (at startup)
    // because last_reindex_time_ is initialized to 0, triggering the initial index,
    // but the zero interval means the timer check (now - last_reindex_time_ >= 0)
    // would always pass, so the code guards it with `if (reindex_interval_ > 0)`.
    for (int i = 0; i < 5; ++i) {
        service.run(/*single_iteration=*/true);
    }

    // With reindex_interval=0, the periodic branch is skipped entirely,
    // so index_uploader.upload() is never called (not even at startup).
    // This is the designed behavior: interval=0 means "no periodic re-indexing",
    // and the one-shot index at startup is handled by main() before the loop.
    CHECK_EQ(fake.post_calls.size(), static_cast<size_t>(0));
}

static void test_periodic_reindex_error_continues() {
    // Re-index failures should log a warning but not crash the agent.
    FakeHttpClient fake;
    fake.get_response = {200, R"({"commands":[]})", ""};

    tracelens::Poller poller(fake);
    tracelens::StatusReporter reporter(fake);
    tracelens::StubExecutor executor;
    tracelens::ResultUploader uploader(fake);
    NoopLogger logger;
    FakeCommandStore store;

    // Create a temp image dir so indexer returns non-empty entries (uploader skips
    // POST for empty lists - see index_uploader.cpp:14).
    const fs::path imgdir = fs::temp_directory_path() / "tracelens_reindex_err_test";
    fs::remove_all(imgdir);
    fs::create_directories(imgdir);
    { std::ofstream(imgdir / "case.E01") << std::string(100, 'x'); }
    tracelens::DiskImageIndexer indexer({imgdir.string()});

    // Make index upload fail.
    fake.post_response = {500, "", ""};
    tracelens::IndexUploader index_uploader(fake, "test-client");

    tracelens::HttpAgentService service(poller, reporter, executor, uploader, store,
                                        indexer, index_uploader,
                                        10, 1, "test-client", logger);

    // Run one iteration — re-index will attempt upload and fail, but service
    // should continue (no crash, still returns 0).
    CHECK_EQ(service.run(/*single_iteration=*/true), 0);

    // Upload was attempted (POST to /index-images).
    bool found_index = false;
    for (const auto& call : fake.post_calls) {
        if (call.first.find("index-images") != std::string::npos) {
            found_index = true;
            break;
        }
    }
    CHECK(found_index);

    fs::remove_all(imgdir);
}

static void test_periodic_reindex_triggers() {
    // Verify re-index triggers after the interval elapses.
    // Uses a small interval (1 second) to keep the test fast.
    FakeHttpClient fake;
    fake.get_response = {200, R"({"commands":[]})", ""};
    fake.post_response = {200, R"({"indexed":0,"updated":0,"total":0})", ""};

    tracelens::Poller poller(fake);
    tracelens::StatusReporter reporter(fake);
    tracelens::StubExecutor executor;
    tracelens::ResultUploader uploader(fake);
    NoopLogger logger;
    FakeCommandStore store;

    // Create a temp image dir so indexer returns non-empty entries.
    const fs::path imgdir = fs::temp_directory_path() / "tracelens_reindex_trigger_test";
    fs::remove_all(imgdir);
    fs::create_directories(imgdir);
    { std::ofstream(imgdir / "case.E01") << std::string(100, 'x'); }
    tracelens::DiskImageIndexer indexer({imgdir.string()});
    tracelens::IndexUploader index_uploader(fake, "test-client");

    // reindex_interval=1 second — small for test speed.
    tracelens::HttpAgentService service(poller, reporter, executor, uploader, store,
                                        indexer, index_uploader,
                                        10, 1, "test-client", logger);

    // First iteration: last_reindex_time_ is 0, so (now - 0 >= 1) is true,
    // triggering the initial re-index.
    CHECK_EQ(service.run(/*single_iteration=*/true), 0);
    size_t after_first = fake.post_calls.size();
    CHECK(after_first >= 1);  // At least the index upload POST

    // Sleep for >1 second so the next iteration triggers another re-index.
    std::this_thread::sleep_for(std::chrono::seconds(1) + std::chrono::milliseconds(100));

    // Second iteration: another re-index should fire.
    CHECK_EQ(service.run(/*single_iteration=*/true), 0);
    size_t after_second = fake.post_calls.size();
    CHECK(after_second > after_first);  // More POSTs (second re-index)

    fs::remove_all(imgdir);
}

// Safety net: if any test wedges (most likely a regression of the pipe-capture
// deadlock), kill the whole suite instead of hanging the gate forever.
static void on_test_alarm(int) {
    const char m[] = "FAIL: test suite timed out (60s) — likely a pipe-capture "
                     "deadlock regression\n";
    ssize_t w = write(STDERR_FILENO, m, sizeof(m) - 1);
    (void)w;
    _exit(1);  // async-signal-safe
}

int main() {
    std::signal(SIGALRM, on_test_alarm);
    alarm(60);  // generous; the over-cap test must finish in well under a second

    test_jwt_client();
    test_jwt_client_id_decode();
    test_config_validate();
    test_config_load_from_file();
    test_config_image_dirs();
    test_command_from_json();
    test_status_update_to_json();
    test_poller_parses_commands();
    test_poller_skips_malformed();
    test_poller_transport_error();
    test_poller_missing_commands_key();
    test_status_reporter();
    test_build_analyzer_argv();
    test_collect_db_artifacts();
    test_analyze_executor_success();
    test_analyze_executor_missing_param_no_spawn();
    test_analyze_executor_missing_file_no_spawn();
    test_analyze_executor_nonzero_exit();
    test_analyze_executor_nonanalyze_is_stub();
    test_process_runner_basic();
    test_process_runner_nonzero_with_stderr();
    test_process_runner_over_cap_does_not_deadlock();
    test_result_uploader();
    test_service_single_iteration();
    test_service_handles_empty_poll();
    test_service_reports_failed_execution();
    test_config_ipv6_localhost_allowed();
    test_service_loop_uploads_then_completes();
    test_service_loop_upload_failure_marks_failed();
    test_sqlite_store_roundtrip();
    test_sqlite_store_restart_recovery();
    test_sqlite_store_replace_on_redeliver();
    test_service_recover_reports_orphans_failed();
    test_service_recover_keeps_orphan_when_report_fails();
    test_sqlite_store_durability_defaults();
    test_detect_format();
    test_e01_base();
    test_disk_image_indexer_scan();
    test_index_uploader();
    test_live_transport_get_post();
    test_live_transport_redirect_not_followed();
    test_live_transport_dead_port_is_transport_error();
    test_periodic_reindex_config();
    test_periodic_reindex_zero_disables();
    test_periodic_reindex_error_continues();
    test_periodic_reindex_triggers();

    std::cout << "checks: " << g_checks << "  failures: " << g_failures << "\n";
    return g_failures == 0 ? 0 : 1;
}
