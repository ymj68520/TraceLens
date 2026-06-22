/**
 * @file test_sqlcipher_database_gtest.cpp
 * @brief Unit tests for the generic SqlCipherDatabase helper.
 *
 * Builds a real SQLCipher-encrypted database with the `sqlcipher` CLI (if
 * available) and verifies that SqlCipherDatabase can open it with the right
 * passphrase, and correctly reports failure on a wrong key. Falls back to
 * synthetic checks when the CLI is absent.
 */

#include <gtest/gtest.h>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <string>

#include "SqlCipherDatabase.h"

namespace fs = std::filesystem;

namespace {

bool haveSqlcipherCli() {
    return std::system("command -v sqlcipher >/dev/null 2>&1") == 0;
}

// Create a SQLCipher 4 DB with a known passphrase and a sample table.
bool makeCipherDb(const fs::path& dbPath, const std::string& passphrase) {
    // Remove any prior file so sqlcipher starts clean.
    std::error_code ec;
    fs::remove(dbPath, ec);

    std::string cmd =
        "sqlcipher '" + dbPath.string() + "' \""\
        "PRAGMA key='" + passphrase + "'; "\
        "CREATE TABLE notes(id INTEGER PRIMARY KEY, body TEXT);"\
        "INSERT INTO notes(body) VALUES('hello');"\
        "\" >/dev/null 2>&1";
    return std::system(cmd.c_str()) == 0 && fs::exists(dbPath);
}

}  // namespace

#ifdef HAVE_SQLCIPHER

TEST(SqlCipherDatabaseTest, OpensCorrectPassphrase) {
    if (!haveSqlcipherCli()) GTEST_SKIP() << "sqlcipher CLI unavailable";

    auto dir = fs::temp_directory_path() / "sqlcipher_test_correct";
    fs::create_directories(dir);
    fs::path db = dir / "enc.db";
    ASSERT_TRUE(makeCipherDb(db, "correct-pass"));

    SqlCipherDatabase c;
    ASSERT_TRUE(c.openWithPassphrase(db.string(), "correct-pass"));
    sqlite3* handle = c.get();
    ASSERT_NE(handle, nullptr);

    sqlite3_stmt* st = nullptr;
    ASSERT_EQ(sqlite3_prepare_v2(handle, "SELECT body FROM notes;", -1, &st, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(st), SQLITE_ROW);
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(st, 0)), "hello");
    sqlite3_finalize(st);

    c.close();
    std::error_code ec;
    fs::remove_all(dir, ec);
}

TEST(SqlCipherDatabaseTest, RejectsWrongPassphrase) {
    if (!haveSqlcipherCli()) GTEST_SKIP() << "sqlcipher CLI unavailable";

    auto dir = fs::temp_directory_path() / "sqlcipher_test_wrong";
    fs::create_directories(dir);
    fs::path db = dir / "enc.db";
    ASSERT_TRUE(makeCipherDb(db, "right-pass"));

    SqlCipherDatabase c;
    EXPECT_FALSE(c.openWithPassphrase(db.string(), "wrong-pass"));
    EXPECT_FALSE(c.lastError().empty());

    std::error_code ec;
    fs::remove_all(dir, ec);
}

TEST(SqlCipherDatabaseTest, RejectsEmptyPassphrase) {
    SqlCipherDatabase c;
    EXPECT_FALSE(c.openWithPassphrase("/tmp/whatever.db", ""));
}

#else  // !HAVE_SQLCIPHER

// When built without SQLCipher, the helper still must fail gracefully (no crash).
TEST(SqlCipherDatabaseTest, GracefulFailureWithoutSqlcipherBuild) {
    SqlCipherDatabase c;
    // These will use the standard sqlite3 which lacks cipher pragmas; they
    // must return false rather than crash.
    EXPECT_FALSE(c.openWithPassphrase("/nonexistent/path.db", "pass"));
    EXPECT_FALSE(c.openWithRawKey("/nonexistent/path.db",
                                  "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff"));
}

#endif  // HAVE_SQLCIPHER

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
