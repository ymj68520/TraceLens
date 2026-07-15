#include <gtest/gtest.h>
#include <sqlite3.h>
#include <filesystem>
#include <fstream>
#include <chrono>
#include "DatabaseManager/FileExtractor/FileExtractor.h"

namespace fs = std::filesystem;

namespace {

std::string temporarySuffix() {
    return std::to_string(std::chrono::steady_clock::now().time_since_epoch().count());
}

class SQLiteFixture : public ::testing::Test {
protected:
    void SetUp() override {
        ASSERT_EQ(sqlite3_open(":memory:", &db_), SQLITE_OK);
        ASSERT_EQ(sqlite3_exec(db_, R"SQL(
            CREATE TABLE files (
                inode INTEGER, name TEXT, path TEXT, size INTEGER,
                mtime INTEGER, ctime INTEGER, type TEXT,
                is_deleted INTEGER, is_allocated INTEGER, md5 TEXT,
                partition_num INTEGER
            );
            INSERT INTO files VALUES
                (8, 'z', '/z.txt', 1, 0, 0, 'REG', 0, 1, '', 0),
                (9, 'a2', '/a.txt', 1, 0, 0, 'REG', 0, 1, '', 2),
                (3, 'a1', '/a.txt', 1, 0, 0, 'REG', 0, 1, '', 1),
                (2, 'deleted', '/b.txt', 1, 0, 0, 'REG', 1, 1, '', 0),
                (1, 'dir', '/c', 0, 0, 0, 'DIR', 0, 1, '', 0);
        )SQL", nullptr, nullptr, nullptr), SQLITE_OK);
    }
    void TearDown() override { sqlite3_close(db_); }
    sqlite3* db_ = nullptr;
};

TEST_F(SQLiteFixture, OrdersAllocatedRegularFilesDeterministically) {
    std::string error;
    const auto rows = FileExtractor::queryRegularFilesOrdered(db_, &error);
    ASSERT_TRUE(error.empty());
    ASSERT_EQ(rows.size(), 3U);
    EXPECT_EQ(rows[0].path, "/a.txt");
    EXPECT_EQ(rows[0].partitionNum, 1);
    EXPECT_EQ(rows[0].inode, 3);
    EXPECT_EQ(rows[1].partitionNum, 2);
    EXPECT_EQ(rows[2].path, "/z.txt");
}

TEST(FileExtractorTextDumpPath, ResolvesImagePathBeneathRoot) {
    const fs::path root = fs::temp_directory_path() /
        ("tracelens-safe-path-" + temporarySuffix());
    ASSERT_FALSE(fs::exists(root));
    fs::create_directories(root);
    std::string error;
    const auto result = FileExtractor::resolveSafeOutputPath(
        root, "/etc/auth.log", &error);
    ASSERT_TRUE(result.has_value());
    EXPECT_EQ(*result, root / "etc" / "auth.log");
    fs::remove_all(root);
}

TEST(FileExtractorTextDumpPath, RejectsTraversalAndSymlinkComponents) {
    const std::string suffix = temporarySuffix();
    const fs::path root = fs::temp_directory_path() / ("tracelens-unsafe-path-" + suffix);
    const fs::path outside = fs::temp_directory_path() / ("tracelens-outside-" + suffix);
    ASSERT_FALSE(fs::exists(root));
    ASSERT_FALSE(fs::exists(outside));
    fs::create_directories(root);
    fs::create_directories(outside);
    fs::create_directory_symlink(outside, root / "linked");
    std::string error;
    EXPECT_FALSE(FileExtractor::resolveSafeOutputPath(
        root, "../../escape", &error).has_value());
    error.clear();
    EXPECT_FALSE(FileExtractor::resolveSafeOutputPath(
        root, "/linked/file.txt", &error).has_value());
    fs::remove_all(root);
    fs::remove_all(outside);
}

} // namespace
