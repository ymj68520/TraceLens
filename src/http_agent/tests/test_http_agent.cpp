// Self-contained unit tests for the TraceLens HTTP agent (Task 16).
//
// No GTest dependency (so the gate builds with just g++ + OpenSSL + pthreads)
// and no live server: a FakeHttpClient implements IHttpClient, returning canned
// JSON and recording the POSTs the loop issues. The real HttpLibClient is
// compiled+linked (TLS path present) but not exercised against a network here.

#include "client_config.h"
#include "command_executor.h"
#include "http_agent_service.h"
#include "http_client.h"
#include "jwt_client.h"
#include "models/command.h"
#include "models/task_status.h"
#include "poller.h"
#include "status_reporter.h"

#include "json.hpp"

#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
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

// ---------------------------------------------------------------- FakeHttpClient
struct FakeHttpClient : tracelens::IHttpClient {
    tracelens::HttpResponse get_response{200, "{}", ""};
    tracelens::HttpResponse post_response{200, "{}", ""};
    std::string last_get_path;
    std::vector<std::pair<std::string, std::string>> post_calls;  // path, body

    tracelens::HttpResponse get(const std::string& path) override {
        last_get_path = path;
        return get_response;
    }
    tracelens::HttpResponse post(const std::string& path,
                                 const std::string& body) override {
        post_calls.emplace_back(path, body);
        return post_response;
    }
};

struct NoopLogger : tracelens::ILogger {
    void info(const std::string&) override {}
    void warn(const std::string&) override {}
    void error(const std::string&) override {}
};

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
static void test_config_validate() {
    using C = tracelens::ClientConfig;
    CHECK(C::validate({"https://server.example.com", 10, "/t", "h"}).empty());
    CHECK(C::validate({"http://localhost:8000", 10, "/t", "h"}).empty());
    CHECK(C::validate({"http://127.0.0.1", 5, "/t", "h"}).empty());
    CHECK(C::validate({"http://127.0.0.1", 30, "/t", "h"}).empty());

    CHECK_CONTAINS(C::validate({"http://server.example.com", 10, "/t", "h"}),
                   "non-localhost");
    CHECK_CONTAINS(C::validate({"ftp://server.example.com", 10, "/t", "h"}),
                   "unsupported scheme");
    CHECK_CONTAINS(C::validate({"server.example.com", 10, "/t", "h"}), "scheme");
    CHECK_CONTAINS(C::validate({"https://server.example.com", 4, "/t", "h"}),
                   "poll_interval");
    CHECK_CONTAINS(C::validate({"https://server.example.com", 31, "/t", "h"}),
                   "poll_interval");
    CHECK_CONTAINS(C::validate({"https://server.example.com", 10, "", "h"}),
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
          << "hostname = station-7\n";
    }
    std::string err;
    auto c = tracelens::ClientConfig::load_from_file(cfg.string(), err);
    CHECK(err.empty());
    CHECK_EQ(c.server_base_url, std::string("https://srv.example.com"));
    CHECK_EQ(c.poll_interval_seconds, 15);
    CHECK_EQ(c.token_path, std::string("/var/lib/tracelens/token"));
    CHECK_EQ(c.hostname, std::string("station-7"));
    fs::remove(cfg);
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

    // Server error -> false, err set, but the POST was still attempted.
    fake.post_response = {500, "", ""};
    CHECK(!reporter.report("c1", u, err));
    CHECK(!err.empty());
    CHECK_EQ(fake.post_calls.size(), static_cast<size_t>(2));
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
    NoopLogger logger;
    tracelens::HttpAgentService service(poller, reporter, executor, 10, logger);

    CHECK_EQ(service.run(/*single_iteration=*/true), 0);

    // One command -> two reports (in_progress, then completed).
    CHECK_EQ(fake.post_calls.size(), static_cast<size_t>(2));
    CHECK_EQ(fake.post_calls[0].first, std::string("/api/commands/c1/status"));
    CHECK_EQ(fake.post_calls[1].first, std::string("/api/commands/c1/status"));
    CHECK_CONTAINS(fake.post_calls[0].second, "in_progress");
    CHECK_CONTAINS(fake.post_calls[1].second, "completed");
}

static void test_service_handles_empty_poll() {
    FakeHttpClient fake;
    fake.get_response = {200, R"({"commands":[]})", ""};
    tracelens::Poller poller(fake);
    tracelens::StatusReporter reporter(fake);
    tracelens::StubExecutor executor;
    NoopLogger logger;
    tracelens::HttpAgentService service(poller, reporter, executor, 10, logger);
    CHECK_EQ(service.run(/*single_iteration=*/true), 0);
    CHECK(fake.post_calls.empty());  // nothing to report
}

int main() {
    test_jwt_client();
    test_config_validate();
    test_config_load_from_file();
    test_command_from_json();
    test_status_update_to_json();
    test_poller_parses_commands();
    test_poller_skips_malformed();
    test_poller_transport_error();
    test_poller_missing_commands_key();
    test_status_reporter();
    test_service_single_iteration();
    test_service_handles_empty_poll();

    std::cout << "checks: " << g_checks << "  failures: " << g_failures << "\n";
    return g_failures == 0 ? 0 : 1;
}
