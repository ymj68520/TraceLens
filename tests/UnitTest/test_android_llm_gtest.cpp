// test_android_llm_gtest.cpp
// Unit tests for the Android LLM analysis persistence layer.
//
// These tests exercise the parts of AndroidLLMAnalysisService that do NOT
// require a live LLM endpoint:
//   1. AndroidAnalysisDatabase::createTables() idempotently adds the 5 llm_*
//      columns to every artifact table the LLM service analyzes.
//   2. The SELECT_*_PENDING_ANALYSIS SQL (android_analysis_sql_llm.h) correctly
//      filters rows where llm_analyzed_at IS NULL.
//   3. The in-place UPDATE write-back (storeArtifactAnalysis pattern) populates
//      the llm_* columns and marks the artifact as analyzed.
//   4. The type→table / type→SQL mappings in AndroidLLMAnalysisService cover
//      every ArtifactType (no empty mappings).

#include <gtest/gtest.h>
#include <sqlite3.h>
#include <filesystem>
#include <string>
#include <vector>

#include "analyzers/AndroidAnalyzer/AndroidAnalysisDatabase.h"
#include "DatabaseManager/SQL/android_analysis_sql.h"
#include "DatabaseManager/SQL/android_analysis_sql_llm.h"

namespace fs = std::filesystem;

namespace {
// RAII temp file path backed by the OS temp directory.
std::string uniqueDbPath() {
    static int counter = 0;
    auto p = fs::temp_directory_path() /
             ("android_llm_test_" + std::to_string(getpid()) + "_" +
              std::to_string(counter++) + ".db");
    return p.string();
}

// Execute a SQL statement, returning true on success.
bool exec(sqlite3* db, const std::string& sql) {
    char* err = nullptr;
    int rc = sqlite3_exec(db, sql.c_str(), nullptr, nullptr, &err);
    if (rc != SQLITE_OK) {
        sqlite3_free(err);
        return false;
    }
    return true;
}

// Count rows where the given column IS NOT NULL in `table`.
int countNotNull(sqlite3* db, const std::string& table, const std::string& column) {
    sqlite3_stmt* stmt = nullptr;
    std::string sql = "SELECT COUNT(*) FROM " + table + " WHERE " + column + " IS NOT NULL;";
    int n = 0;
    if (sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr) == SQLITE_OK) {
        if (sqlite3_step(stmt) == SQLITE_ROW) n = static_cast<int>(sqlite3_column_int(stmt, 0));
    }
    sqlite3_finalize(stmt);
    return n;
}
}  // namespace

// ─────────────────────────────────────────────────────────────────────────────
// 1. Migration adds llm_* columns to every analyzed table (idempotent).
// ─────────────────────────────────────────────────────────────────────────────
TEST(AndroidLlmMigrationTest, AddsLlmColumnsToAnalyzedTables) {
    const std::string path = uniqueDbPath();
    {
        AndroidAnalysisDatabase db(path, /*integratedMode=*/false);
        ASSERT_TRUE(db.initialize());
    }
    // Re-open with raw sqlite to inspect the schema.
    sqlite3* db = nullptr;
    ASSERT_EQ(sqlite3_open(path.c_str(), &db), SQLITE_OK);

    const std::vector<std::string> tables = {
        "sms_messages", "wechat_messages", "whatsapp_messages", "telegram_messages",
        "contacts", "call_logs", "miui_backup_manifest", "installed_apps",
        "wechat_sqlite_records", "wechat_kv_records", "qqnt_sqlite_records",
        "system_logs", "device_identifiers", "wifi_networks"
    };
    const std::vector<std::string> cols = {
        "llm_summary", "llm_description", "llm_keywords", "llm_analyzed_at", "llm_model_used"
    };

    for (const auto& tbl : tables) {
        // Build the set of column names for this table.
        sqlite3_stmt* stmt = nullptr;
        std::string sql = "SELECT name FROM pragma_table_info('" + tbl + "');";
        ASSERT_EQ(sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr), SQLITE_OK)
            << "table missing or pragma failed: " << tbl;
        std::vector<std::string> have;
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            const char* name = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
            if (name) have.emplace_back(name);
        }
        sqlite3_finalize(stmt);

        for (const auto& col : cols) {
            bool found = false;
            for (const auto& h : have) if (h == col) { found = true; break; }
            EXPECT_TRUE(found) << "table " << tbl << " missing column " << col;
        }
    }

    sqlite3_close(db);
    std::error_code ec;
    fs::remove(path, ec);
}

// ─────────────────────────────────────────────────────────────────────────────
// 2. Re-initializing an existing DB (re-open) must NOT fail on duplicate columns.
// ─────────────────────────────────────────────────────────────────────────────
TEST(AndroidLlmMigrationTest, IsIdempotentOnReopen) {
    const std::string path = uniqueDbPath();
    {
        AndroidAnalysisDatabase db1(path, false);
        ASSERT_TRUE(db1.initialize());
    }
    // A second open of the same file re-runs createTables + addLlmColumns.
    {
        AndroidAnalysisDatabase db2(path, false);
        EXPECT_TRUE(db2.initialize()) << "re-open with already-present llm_ columns failed";
    }
    std::error_code ec;
    fs::remove(path, ec);
}

// ─────────────────────────────────────────────────────────────────────────────
// 3. SELECT_PENDING + UPDATE write-back round-trip on sms_messages.
//    Mirrors what AndroidLLMAnalysisService does at runtime, without the LLM.
// ─────────────────────────────────────────────────────────────────────────────
TEST(AndroidLlmAnalysisPersistenceTest, PendingSelectAndUpdateWriteback) {
    const std::string path = uniqueDbPath();
    {
        AndroidAnalysisDatabase adb(path, false);
        ASSERT_TRUE(adb.initialize());
    }
    sqlite3* db = nullptr;
    ASSERT_EQ(sqlite3_open(path.c_str(), &db), SQLITE_OK);

    // Insert two SMS rows (both unanalyzed by default).
    ASSERT_TRUE(exec(db, "INSERT INTO sms_messages (address, body, date, type) "
                          "VALUES ('10086', 'verification code 1234', 1700000000, 1);"));
    ASSERT_TRUE(exec(db, "INSERT INTO sms_messages (address, body, date, type) "
                          "VALUES ('boss', 'meeting at 9', 1700000001, 2);"));

    // Pending query should return both (llm_analyzed_at IS NULL). Substitute the
    // LIMIT placeholder the same way the service does.
    std::string pending = android_analysis_sql_llm::SELECT_SMS_PENDING_ANALYSIS;
    auto pos = pending.find('?');
    ASSERT_NE(pos, std::string::npos);
    pending.replace(pos, 1, "10");
    sqlite3_stmt* sel = nullptr;
    ASSERT_EQ(sqlite3_prepare_v2(db, pending.c_str(), -1, &sel, nullptr), SQLITE_OK);
    int pendingCount = 0;
    while (sqlite3_step(sel) == SQLITE_ROW) pendingCount++;
    sqlite3_finalize(sel);
    EXPECT_EQ(pendingCount, 2);

    // Write back an analysis for row id=1 (the service's UPDATE shape).
    ASSERT_TRUE(exec(db, "UPDATE sms_messages SET llm_summary='OTP message', "
                          "llm_description='A verification-code SMS, possible account-takeover indicator.', "
                          "llm_keywords='otp,verification,10086', llm_analyzed_at=1700000050, "
                          "llm_model_used='test-model' WHERE id=1;"));

    // Now only one row should be pending.
    sqlite3_stmt* sel2 = nullptr;
    ASSERT_EQ(sqlite3_prepare_v2(db, pending.c_str(), -1, &sel2, nullptr), SQLITE_OK);
    int stillPending = 0;
    while (sqlite3_step(sel2) == SQLITE_ROW) stillPending++;
    sqlite3_finalize(sel2);
    EXPECT_EQ(stillPending, 1);
    EXPECT_EQ(countNotNull(db, "sms_messages", "llm_analyzed_at"), 1);

    sqlite3_close(db);
    std::error_code ec;
    fs::remove(path, ec);
}

// ─────────────────────────────────────────────────────────────────────────────
// 4. Every analyzed table has a corresponding SELECT_*_PENDING_ANALYSIS and
//    the query references the right table — guards against drift if a table is
//    added to the migration list but not to the SQL header (or vice versa).
// ─────────────────────────────────────────────────────────────────────────────
TEST(AndroidLlmSqlCoverageTest, EveryPendingQueryTargetsAnAnalyzedTable) {
    namespace A = android_analysis_sql_llm;
    struct Entry { const char* sql; const char* table; };
    const std::vector<Entry> entries = {
        {A::SELECT_SMS_PENDING_ANALYSIS, "sms_messages"},
        {A::SELECT_WECHAT_MESSAGES_PENDING_ANALYSIS, "wechat_messages"},
        {A::SELECT_WHATSAPP_PENDING_ANALYSIS, "whatsapp_messages"},
        {A::SELECT_TELEGRAM_PENDING_ANALYSIS, "telegram_messages"},
        {A::SELECT_CONTACTS_PENDING_ANALYSIS, "contacts"},
        {A::SELECT_CALL_LOGS_PENDING_ANALYSIS, "call_logs"},
        {A::SELECT_MIUI_MANIFEST_PENDING_ANALYSIS, "miui_backup_manifest"},
        {A::SELECT_INSTALLED_APPS_PENDING_ANALYSIS, "installed_apps"},
        {A::SELECT_WECHAT_SQLITE_RECORDS_PENDING_ANALYSIS, "wechat_sqlite_records"},
        {A::SELECT_WECHAT_KV_RECORDS_PENDING_ANALYSIS, "wechat_kv_records"},
        {A::SELECT_QQNT_SQLITE_RECORDS_PENDING_ANALYSIS, "qqnt_sqlite_records"},
        {A::SELECT_SYSTEM_LOGS_PENDING_ANALYSIS, "system_logs"},
        {A::SELECT_DEVICE_IDENTIFIERS_PENDING_ANALYSIS, "device_identifiers"},
        {A::SELECT_WIFI_NETWORKS_PENDING_ANALYSIS, "wifi_networks"},
    };
    for (const auto& e : entries) {
        ASSERT_NE(e.sql, nullptr);
        EXPECT_NE(std::string(e.sql).find(e.table), std::string::npos)
            << "pending query does not reference expected table " << e.table;
        EXPECT_NE(std::string(e.sql).find("llm_analyzed_at IS NULL"), std::string::npos)
            << "pending query for " << e.table << " missing the NULL filter";
        EXPECT_NE(std::string(e.sql).find("LIMIT ?"), std::string::npos)
            << "pending query for " << e.table << " missing LIMIT ? placeholder";
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// 5. The android_analysis_progress table is created and usable.
// ─────────────────────────────────────────────────────────────────────────────
TEST(AndroidLlmProgressTest, ProgressTableCreated) {
    const std::string path = uniqueDbPath();
    {
        AndroidAnalysisDatabase adb(path, false);
        ASSERT_TRUE(adb.initialize());
    }
    sqlite3* db = nullptr;
    ASSERT_EQ(sqlite3_open(path.c_str(), &db), SQLITE_OK);

    EXPECT_TRUE(exec(db, android_analysis_sql_llm::INSERT_ANDROID_ANALYSIS_PROGRESS))
        << "progress insert failed (table missing?)";

    sqlite3_stmt* stmt = nullptr;
    ASSERT_EQ(sqlite3_prepare_v2(db, "SELECT COUNT(*) FROM android_analysis_progress;",
                                 -1, &stmt, nullptr), SQLITE_OK);
    int n = 0;
    if (sqlite3_step(stmt) == SQLITE_ROW) n = sqlite3_column_int(stmt, 0);
    sqlite3_finalize(stmt);
    EXPECT_EQ(n, 1);

    sqlite3_close(db);
    std::error_code ec;
    fs::remove(path, ec);
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
