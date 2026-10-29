// test_android_llm_concurrency_gtest.cpp
// Concurrency tests for AndroidLLMAnalysisService::analyzeArtifactType.
//
// Spins up a local OpenAI-compatible stub server and drives the real
// analyzeArtifactType worker pool against a throwaway android.db:
//   1. the ANDROID_ARTIFACT_LLM_CONCURRENCY knob (default 32, clamped 1..64);
//   2. parallel workers actually overlap requests (peak in-flight >= 2);
//   3. every record still lands its llm_* write-back exactly once;
//   4. progress callbacks stay monotonic 1..total under concurrency;
//   5. batch chunks (LLM_ARTIFACT_BATCH_SIZE > 1) also fan out.
//
// Scenarios run as separate processes (see tests/CMakeLists.txt) because the
// dotenv store reads the process environment and is write-once per key.

#include <gtest/gtest.h>
#include <httplib.h>
#include <sqlite3.h>
#include <nlohmann/json.hpp>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <filesystem>
#include <mutex>
#include <set>
#include <thread>
#include <vector>

#include "AndroidLLMAnalysisService.h"
#include "analyzers/AndroidAnalyzer/AndroidAnalysisDatabase.h"

using forensics::AndroidLLMAnalysisService;
namespace fs = std::filesystem;

namespace {

std::string uniqueDbPath(const char* tag) {
    static int counter = 0;
    auto p = fs::temp_directory_path() /
             ("android_llm_conc_" + std::string(tag) + "_" +
              std::to_string(getpid()) + "_" + std::to_string(counter++) + ".db");
    return p.string();
}

bool exec(sqlite3* db, const std::string& sql) {
    char* err = nullptr;
    const int rc = sqlite3_exec(db, sql.c_str(), nullptr, nullptr, &err);
    if (rc != SQLITE_OK) {
        sqlite3_free(err);
        return false;
    }
    return true;
}

int countNotNull(sqlite3* db, const std::string& table, const std::string& column) {
    sqlite3_stmt* stmt = nullptr;
    const std::string sql =
        "SELECT COUNT(*) FROM " + table + " WHERE " + column + " IS NOT NULL;";
    if (sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) return -1;
    int count = 0;
    if (sqlite3_step(stmt) == SQLITE_ROW) count = sqlite3_column_int(stmt, 0);
    sqlite3_finalize(stmt);
    return count;
}

// Minimal OpenAI-compatible chat endpoint. Single prompts get one object,
// batch prompts (recognised by the llmbatch array instruction) get one array
// entry per id found in the request. Tracks peak in-flight requests.
class StubLlm {
public:
    void start() {
        server_.Post("/v1/chat/completions", [&](const httplib::Request& req,
                                                 httplib::Response& res) {
            const int now = inFlight_.fetch_add(1) + 1;
            int observed = maxInFlight_.load();
            while (now > observed &&
                   !maxInFlight_.compare_exchange_weak(observed, now)) {
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(120));
            inFlight_.fetch_sub(1);
            total_.fetch_add(1);

            nlohmann::json content;
            const bool batchRequest =
                req.body.find("Respond with ONLY a JSON array") != std::string::npos;
            if (batchRequest) {
                content = nlohmann::json::array();
                for (const auto& id : extractIds(req.body)) {
                    content.push_back({
                        {"id", id},
                        {"summary", "batch summary"},
                        {"description", "batch description"},
                        {"keywords", {"b1", "b2"}},
                    });
                }
            } else {
                content = {
                    {"summary", "stub summary"},
                    {"description", "stub description"},
                    {"keywords", {"k1", "k2"}},
                };
            }

            nlohmann::json body = {
                {"choices", {{{"message", {{"content", content.dump()}}}}}},
            };
            res.set_content(body.dump(), "application/json");
        });
        port_ = server_.bind_to_any_port("127.0.0.1");
        thread_ = std::thread([this]() { server_.listen_after_bind(); });
    }

    void stop() {
        server_.stop();
        if (thread_.joinable()) thread_.join();
    }

    std::string baseUrl() const {
        return "http://127.0.0.1:" + std::to_string(port_);
    }

    int totalRequests() const { return total_.load(); }
    int peakInFlight() const { return maxInFlight_.load(); }

private:
    // llmbatch serialises the envelope ids as quoted strings ("id":"12");
    // record payloads embed a numeric id (unquoted) so the quoted form is
    // unique to the batch envelope. The ids are extracted from the DECODED
    // prompt — the raw HTTP body escapes the quotes.
    static std::vector<std::string> extractIds(const std::string& body) {
        std::vector<std::string> ids;
        try {
            auto parsed = nlohmann::json::parse(body);
            if (!parsed.is_object() || !parsed.contains("messages")) return ids;
            std::string prompt;
            for (const auto& msg : parsed["messages"]) {
                if (msg.is_object() &&
                    msg.value("content", "").find(
                        "Respond with ONLY a JSON array") != std::string::npos) {
                    prompt = msg.value("content", "");
                    break;
                }
            }
            const std::string marker = "\"id\":\"";
            for (size_t pos = prompt.find(marker); pos != std::string::npos;
                 pos = prompt.find(marker, pos + marker.size())) {
                const size_t start = pos + marker.size();
                const size_t end = prompt.find('"', start);
                if (end != std::string::npos && end > start) {
                    ids.push_back(prompt.substr(start, end - start));
                }
            }
        } catch (...) {
        }
        return ids;
    }

    httplib::Server server_;
    std::thread thread_;
    int port_ = 0;
    std::atomic<int> inFlight_{0};
    std::atomic<int> maxInFlight_{0};
    std::atomic<int> total_{0};
};

struct ProgressLog {
    std::mutex mutex;
    std::vector<int> currents;
    int lastTotal = 0;
};

// Prepare the per-process environment: point the text model at the stub and
// pin the knobs the scenario needs. Values ride the process environment so
// they beat any .env the ConfigManager discovers (dotenv never overwrites).
void pinEnv(const StubLlm& stub, const char* concurrency, const char* batchSize) {
    setenv("LLM_TEXT_BASE_URL", stub.baseUrl().c_str(), 1);
    setenv("LLM_TEXT_MODEL", "stub-model", 1);
    setenv("LLM_TEXT_API_KEY", "test-key", 1);
    setenv("LLM_ENDPOINT", "/v1/chat/completions", 1);
    setenv("LLM_TIMEOUT_SECONDS", "10", 1);
    setenv("LLM_MAX_RETRIES", "1", 1);
    setenv("LLM_MAX_ARTIFACTS", "0", 1);
    setenv("LLM_ARTIFACT_BATCH_SIZE", batchSize, 1);
    setenv("ANDROID_ARTIFACT_LLM_CONCURRENCY", concurrency, 1);
}

std::string makeDb(const char* tag, int rows) {
    const std::string path = uniqueDbPath(tag);
    {
        AndroidAnalysisDatabase adb(path, false);
        if (!adb.initialize()) return "";
    }
    sqlite3* db = nullptr;
    if (sqlite3_open(path.c_str(), &db) != SQLITE_OK) return "";
    for (int i = 0; i < rows; ++i) {
        const std::string sql =
            "INSERT INTO system_logs (timestamp, log_level, tag, process, pid, "
            "message, log_file, log_source) VALUES (" +
            std::to_string(1700000000 + i) + ", 'I', 'ActivityManager', 'system', " +
            std::to_string(1000 + i) + ", 'log message " + std::to_string(i) +
            "', '/logs/main', 'logcat');";
        if (!exec(db, sql)) {
            sqlite3_close(db);
            return "";
        }
    }
    sqlite3_close(db);
    return path;
}

// Runs analyzeArtifactType over SYSTEM_LOG and returns {analyzed, peak}.
int runAnalysis(const std::string& dbPath, ProgressLog& progress) {
    AndroidLLMAnalysisService service;
    if (!service.initialize()) return -1;
    return service.analyzeArtifactType(
        dbPath, AndroidLLMAnalysisService::ArtifactType::SYSTEM_LOG, 500,
        [&](const std::string&, int current, int total, const std::string&) {
            std::lock_guard<std::mutex> lock(progress.mutex);
            progress.currents.push_back(current);
            progress.lastTotal = total;
        });
}

} // namespace

// ─── knob semantics (no server needed; reads live environment) ──────────────

TEST(AndroidArtifactConcurrencyKnob, DefaultIs32AndClampedTo64) {
    unsetenv("ANDROID_ARTIFACT_LLM_CONCURRENCY");
    forensics::ConfigManager& config = forensics::ConfigManager::instance();
    EXPECT_EQ(config.getAndroidArtifactLLMConcurrency(), 32);

    setenv("ANDROID_ARTIFACT_LLM_CONCURRENCY", "999", 1);
    EXPECT_EQ(config.getAndroidArtifactLLMConcurrency(), 64);

    setenv("ANDROID_ARTIFACT_LLM_CONCURRENCY", "0", 1);
    EXPECT_EQ(config.getAndroidArtifactLLMConcurrency(), 1);

    setenv("ANDROID_ARTIFACT_LLM_CONCURRENCY", "8", 1);
    EXPECT_EQ(config.getAndroidArtifactLLMConcurrency(), 8);
    unsetenv("ANDROID_ARTIFACT_LLM_CONCURRENCY");
}

// ─── parallel single-record path ─────────────────────────────────────────────

TEST(AndroidArtifactConcurrencyRun, ParallelWorkersOverlapAndWriteBack) {
    StubLlm stub;
    stub.start();
    pinEnv(stub, "8", "1");

    const std::string dbPath = makeDb("parallel", 12);
    ASSERT_FALSE(dbPath.empty());

    ProgressLog progress;
    const int analyzed = runAnalysis(dbPath, progress);
    stub.stop();

    EXPECT_EQ(analyzed, 12);
    EXPECT_EQ(stub.totalRequests(), 12);
    // 8 workers against a 120 ms stub must overlap; a serial regression
    // reports peak 1 here.
    EXPECT_GE(stub.peakInFlight(), 2);

    EXPECT_EQ(progress.lastTotal, 12);
    std::vector<int> expected;
    for (int i = 1; i <= 12; ++i) expected.push_back(i);
    EXPECT_EQ(progress.currents, expected);

    sqlite3* db = nullptr;
    ASSERT_EQ(sqlite3_open(dbPath.c_str(), &db), SQLITE_OK);
    EXPECT_EQ(countNotNull(db, "system_logs", "llm_analyzed_at"), 12);
    EXPECT_EQ(countNotNull(db, "system_logs", "llm_summary"), 12);
    sqlite3_close(db);

    std::error_code ec;
    fs::remove(dbPath, ec);
}

// ─── serial fallback stays correct ───────────────────────────────────────────

TEST(AndroidArtifactConcurrencyRun, SerialModeAnalyzesAllSequentially) {
    StubLlm stub;
    stub.start();
    pinEnv(stub, "1", "1");

    const std::string dbPath = makeDb("serial", 4);
    ASSERT_FALSE(dbPath.empty());

    ProgressLog progress;
    const int analyzed = runAnalysis(dbPath, progress);
    stub.stop();

    EXPECT_EQ(analyzed, 4);
    EXPECT_EQ(stub.totalRequests(), 4);
    EXPECT_EQ(stub.peakInFlight(), 1);
    EXPECT_EQ(progress.currents, (std::vector<int>{1, 2, 3, 4}));

    sqlite3* db = nullptr;
    ASSERT_EQ(sqlite3_open(dbPath.c_str(), &db), SQLITE_OK);
    EXPECT_EQ(countNotNull(db, "system_logs", "llm_analyzed_at"), 4);
    sqlite3_close(db);

    std::error_code ec;
    fs::remove(dbPath, ec);
}

// ─── batch chunks also fan out ───────────────────────────────────────────────

TEST(AndroidArtifactConcurrencyRun, BatchChunksRunInParallel) {
    StubLlm stub;
    stub.start();
    pinEnv(stub, "8", "4");

    const std::string dbPath = makeDb("batch", 12);
    ASSERT_FALSE(dbPath.empty());

    ProgressLog progress;
    const int analyzed = runAnalysis(dbPath, progress);
    stub.stop();

    // 12 records / batch 4 → 3 chunk requests total, overlapping in flight.
    EXPECT_EQ(analyzed, 12);
    EXPECT_EQ(stub.totalRequests(), 3);
    EXPECT_GE(stub.peakInFlight(), 2);
    EXPECT_EQ(progress.lastTotal, 12);
    EXPECT_EQ(progress.currents.size(), static_cast<size_t>(12));

    sqlite3* db = nullptr;
    ASSERT_EQ(sqlite3_open(dbPath.c_str(), &db), SQLITE_OK);
    EXPECT_EQ(countNotNull(db, "system_logs", "llm_analyzed_at"), 12);
    sqlite3_stmt* stmt = nullptr;
    ASSERT_EQ(sqlite3_prepare_v2(
                  db, "SELECT COUNT(*) FROM system_logs WHERE llm_summary='batch summary';",
                  -1, &stmt, nullptr),
              SQLITE_OK);
    int batchSummaries = 0;
    if (sqlite3_step(stmt) == SQLITE_ROW) batchSummaries = sqlite3_column_int(stmt, 0);
    sqlite3_finalize(stmt);
    EXPECT_EQ(batchSummaries, 12);
    sqlite3_close(db);

    std::error_code ec;
    fs::remove(dbPath, ec);
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
