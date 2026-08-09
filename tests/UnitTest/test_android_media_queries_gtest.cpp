#include <gtest/gtest.h>

#include <filesystem>

#include <sqlite3.h>

#include "HTTPServer/SQLiteHelper.h"

namespace fs = std::filesystem;

class AndroidMediaQueriesTest : public ::testing::Test {
protected:
    void SetUp() override {
        dbPath_ = fs::temp_directory_path() / "tracelens_android_media_queries.db";
        fs::remove(dbPath_);

        sqlite3* db = nullptr;
        ASSERT_EQ(sqlite3_open(dbPath_.c_str(), &db), SQLITE_OK);
        ASSERT_EQ(sqlite3_exec(db, R"SQL(
            CREATE TABLE framework_files (
                id INTEGER PRIMARY KEY,
                file_name TEXT NOT NULL,
                file_path TEXT NOT NULL UNIQUE,
                file_type TEXT,
                file_size INTEGER
            );
            INSERT INTO framework_files (file_name, file_path, file_type, file_size)
            VALUES ('framework.jar', '/system/framework/framework.jar', 'jar', 1024);
        )SQL", nullptr, nullptr, nullptr), SQLITE_OK);
        sqlite3_close(db);
    }

    void TearDown() override {
        fs::remove(dbPath_);
    }

    fs::path dbPath_;
};

TEST_F(AndroidMediaQueriesTest, DoesNotClassifyFrameworkArtifactsAsMedia) {
    const auto result = SQLiteHelper::get_android_media_analysis(dbPath_.string());

    ASSERT_TRUE(result.contains("media_files"));
    ASSERT_TRUE(result.contains("media_by_type"));
    EXPECT_TRUE(result["media_files"].is_array());
    EXPECT_TRUE(result["media_by_type"].is_array());
    EXPECT_TRUE(result["media_files"].empty());
    EXPECT_TRUE(result["media_by_type"].empty());
}
