// Read-path tests: mirror → RocksRawReader → get_largest_files source switch
// (mvp-phase1-acceptance SPEC §8 R3).

#include "KVStore/RocksRawReader.h"
#include "KVStore/SqliteRocksMirror.h"

#include <gtest/gtest.h>

#include <filesystem>
#include <sqlite3.h>

namespace {

namespace fs = std::filesystem;
using forensics::kv::RocksRawReader;

class RocksRawReaderTest : public ::testing::Test {
protected:
    void SetUp() override {
        const std::string test_name =
            ::testing::UnitTest::GetInstance()->current_test_info()->name();
        dir_ = (fs::temp_directory_path() / "rocks_reader_tests" / test_name).string();
        fs::remove_all(dir_);
        fs::create_directories(dir_);
        db_path_ = (fs::path(dir_) / "raw.db").string();
        rocks_path_ = (fs::path(dir_) / "raw.rocks").string();

        sqlite3* db = nullptr;
        ASSERT_EQ(sqlite3_open(db_path_.c_str(), &db), SQLITE_OK);
        char* err = nullptr;
        const char* script =
            "CREATE TABLE files ("
            "  id INTEGER PRIMARY KEY, path TEXT, size INTEGER,"
            "  mtime INTEGER, ctime INTEGER, crtime INTEGER, atime INTEGER,"
            "  llm_summary TEXT, is_deleted INTEGER DEFAULT 0);"
            "INSERT INTO files (path, size, mtime, ctime, crtime, atime, llm_summary) VALUES"
            "  ('/case/small.txt', 10, 100, 100, 100, 100, 's'),"
            "  ('/case/big.bin', 90000, 250, 200, 150, 180, NULL),"
            "  ('/case/mid.log', 5000, 90, 300, 120, 140, 'm'),"
            "  ('/case/zero.tmp', 0, 1, 1, 1, 1, NULL);";
        ASSERT_EQ(sqlite3_exec(db, script, nullptr, nullptr, &err), SQLITE_OK);
        if (err) sqlite3_free(err);
        sqlite3_close(db);

        forensics::kv::SqliteRocksMirror mirror;
        ASSERT_EQ(mirror.run(db_path_, rocks_path_).size(), 1u);
    }
    void TearDown() override { fs::remove_all(dir_); }

    std::string dir_;
    std::string db_path_;
    std::string rocks_path_;
};

TEST_F(RocksRawReaderTest, KeyingMetadataAndHasTable) {
    RocksRawReader reader(rocks_path_);
    EXPECT_TRUE(reader.has_table("files"));
    EXPECT_FALSE(reader.has_table("missing_table"));

    const auto keying = reader.keying("files");
    ASSERT_TRUE(keying.has_value());
    EXPECT_TRUE(keying->rowid_keyed);
    ASSERT_EQ(keying->pk.size(), 1u);
    EXPECT_EQ(keying->pk[0], "id");
    EXPECT_EQ(keying->count, 4u);
    EXPECT_EQ(reader.count_rows("files"), 4u);
}

TEST_F(RocksRawReaderTest, PointLookupAndOrderedScan) {
    RocksRawReader reader(rocks_path_);

    const auto row2 = reader.get_by_rowid("files", 2);
    ASSERT_TRUE(row2.has_value());
    EXPECT_EQ((*row2)["path"].get<std::string>(), "/case/big.bin");
    EXPECT_EQ((*row2)["size"].get<std::int64_t>(), 90000);
    EXPECT_FALSE(reader.get_by_rowid("files", 999).has_value());

    const auto rows = reader.scan_table("files");
    ASSERT_EQ(rows.size(), 4u);
    // Key order == rowid order.
    for (size_t i = 0; i < rows.size(); ++i) {
        EXPECT_EQ(rows[i].rowid, static_cast<std::int64_t>(i + 1));
    }
    EXPECT_EQ(rows[0].value["path"].get<std::string>(), "/case/small.txt");
}

TEST_F(RocksRawReaderTest, ReaderMirrorsLargestFilesSemantics) {
    // The same scan the wired get_largest_files performs: size filter +
    // descending sort + limit. This pins the semantics the HTTP route serves
    // from the mirror (source: rocksdb_mirror).
    RocksRawReader reader(rocks_path_);
    struct SizeRow {
        std::int64_t size;
        nlohmann::json row;
    };
    std::vector<SizeRow> candidates;
    for (const auto& rocks_row : reader.scan_table("files")) {
        const auto size_it = rocks_row.value.find("size");
        const std::int64_t size =
            size_it != rocks_row.value.end() && size_it->is_number()
                ? size_it->get<std::int64_t>() : 0;
        if (size > 0) candidates.push_back({size, rocks_row.value});
    }
    std::sort(candidates.begin(), candidates.end(),
              [](const SizeRow& a, const SizeRow& b) { return a.size > b.size; });
    if (candidates.size() > 2) candidates.resize(2);

    ASSERT_EQ(candidates.size(), 2u);
    EXPECT_EQ(candidates[0].row["path"].get<std::string>(), "/case/big.bin");
    EXPECT_EQ(candidates[1].row["path"].get<std::string>(), "/case/mid.log");
}

TEST_F(RocksRawReaderTest, MissingStoreThrowsForFallback) {
    // A path that is not a RocksDB store must throw, which is the documented
    // trigger for the SQLite fallback in the query layer.
    EXPECT_THROW(RocksRawReader((fs::path(dir_) / "nonexistent.rocks").string()),
                 std::runtime_error);
}

}  // namespace
