// Unit tests for RowCodec + SqliteRocksMirror (mvp-phase1-acceptance SPEC §8 R2).
//
// The codec goldens are the exact bytes python sqlite_migrate.encode_value
// produces for the same cells (json.dumps(sort_keys, compact, ensure_ascii)),
// which is what makes the C++-mirrored stores verifiable by
// scripts/migrate_sqlite_to_rocksdb.py --verify.

#include "KVStore/KVStore.h"
#include "KVStore/RowCodec.h"
#include "KVStore/RocksKVStore.h"
#include "KVStore/SqliteRocksMirror.h"

#include <gtest/gtest.h>

#include <cstdlib>

#include <filesystem>
#include <sqlite3.h>
#include <string>
#include <vector>

namespace {

namespace fs = std::filesystem;
using forensics::kv::SqliteCell;

class RowCodecTest : public ::testing::Test {};

TEST_F(RowCodecTest, Base64MatchesPython) {
    // base64.b64encode(bytes([0x00, 0xFF, 0x10])) == "AP8Q"
    EXPECT_EQ(forensics::kv::base64_encode(std::string("\x00\xFF\x10", 3)), "AP8Q");
    EXPECT_EQ(forensics::kv::base64_encode(""), "");
    EXPECT_EQ(forensics::kv::base64_encode("a"), "YQ==");
    EXPECT_EQ(forensics::kv::base64_encode("ab"), "YWI=");
    EXPECT_EQ(forensics::kv::base64_encode("abc"), "YWJj");
}

TEST_F(RowCodecTest, MixedCellGoldenBytes) {
    const std::vector<std::pair<std::string, SqliteCell>> cells = {
        {"a", SqliteCell::from_integer(1)},
        {"b", SqliteCell::null()},
        {"c", SqliteCell::from_text("中文 path/x")},
        {"d", SqliteCell::from_blob(std::string("\x00\xFF\x10", 3))},
        {"e", SqliteCell::from_integer(1)},  // bools are integers in sqlite
        {"f", SqliteCell::from_text("quote\"back\\slash\n")},
    };
    // python: encode_value({'a':1,'b':None,'c':'中文 path/x',
    //                       'd':b'\x00\xff\x10','e':True,
    //                       'f':'quote"back\\slash\n'})
    EXPECT_EQ(forensics::kv::encode_row(cells),
              R"({"a":1,"b":null,"c":"\u4e2d\u6587 path/x","d":{"__blob_b64__":"AP8Q"},"e":1,"f":"quote\"back\\slash\n"})");
}

TEST_F(RowCodecTest, RowidCellGoldenBytes) {
    const std::vector<std::string> columns = {"path", "size", "llm_summary"};
    const std::vector<SqliteCell> cells = {
        SqliteCell::from_text("/case/中文.txt"),
        SqliteCell::from_integer(12345),
        SqliteCell::null(),
    };
    // python: encode_value({'path':'/case/中文.txt','size':12345,'llm_summary':None})
    EXPECT_EQ(forensics::kv::encode_row(columns, cells),
              R"({"llm_summary":null,"path":"/case/\u4e2d\u6587.txt","size":12345})");
}

TEST_F(RowCodecTest, KeyOrderIndependent) {
    const std::vector<std::pair<std::string, SqliteCell>> cells = {
        {"zebra", SqliteCell::from_integer(1)},
        {"alpha", SqliteCell::from_integer(2)},
    };
    EXPECT_EQ(forensics::kv::encode_row(cells), R"({"alpha":2,"zebra":1})");
}

class SqliteRocksMirrorTest : public ::testing::Test {
protected:
    void SetUp() override {
        const std::string test_name =
            ::testing::UnitTest::GetInstance()->current_test_info()->name();
        dir_ = (fs::temp_directory_path() / "rocks_mirror_tests" / test_name).string();
        fs::remove_all(dir_);
        fs::create_directories(dir_);
        db_path_ = (fs::path(dir_) / "raw.db").string();
        rocks_path_ = (fs::path(dir_) / "raw.rocks").string();
        build_source_db();
    }
    void TearDown() override {
        // TRACELENS_KEEP_MIRROR_FIXTURE=1 keeps the sqlite+rocks pair on disk
        // for cross-language checks, e.g.:
        //   python scripts/migrate_sqlite_to_rocksdb.py <dir>/raw.db \
        //       --out <dir>/raw.rocks --verify
        if (::getenv("TRACELENS_KEEP_MIRROR_FIXTURE") == nullptr) {
            fs::remove_all(dir_);
        }
    }

    void build_source_db() {
        sqlite3* db = nullptr;
        ASSERT_EQ(sqlite3_open(db_path_.c_str(), &db), SQLITE_OK);
        char* err = nullptr;
        const char* script =
            "CREATE TABLE files ("
            "  id INTEGER PRIMARY KEY, path TEXT, size INTEGER,"
            "  mtime INTEGER, ctime INTEGER, crtime INTEGER, atime INTEGER,"
            "  llm_summary TEXT, raw BLOB, partition_num INTEGER DEFAULT 0);"
            "CREATE TABLE partitions ("
            "  id INTEGER PRIMARY KEY, partition_num INTEGER, start_offset INTEGER,"
            "  length INTEGER, description TEXT, fs_type TEXT);"
            "CREATE TABLE case_keys (path TEXT, depth INTEGER, PRIMARY KEY (path)) WITHOUT ROWID;"
            "INSERT INTO files (path, size, mtime, ctime, crtime, atime, llm_summary, raw, partition_num) VALUES"
            "  ('/case/a.txt', 10, 100, 100, 100, 100, 'sum-a', X'00FF10', 0),"
            "  ('/case/中文.bin', 20, 250, 200, 150, 180, NULL, NULL, 1);"
            "INSERT INTO partitions (partition_num, start_offset, length, description, fs_type)"
            "  VALUES (0, 1048576, 999, 'p0', 'ext4');"
            "INSERT INTO case_keys VALUES ('/case/a.txt', 2);";
        ASSERT_EQ(sqlite3_exec(db, script, nullptr, nullptr, &err), SQLITE_OK);
        if (err) sqlite3_free(err);
        sqlite3_close(db);
    }

    std::string dir_;
    std::string db_path_;
    std::string rocks_path_;
};

TEST_F(SqliteRocksMirrorTest, MirrorsRowidAndPkTables) {
    forensics::kv::SqliteRocksMirror mirror;
    const auto results = mirror.run(db_path_, rocks_path_);

    ASSERT_EQ(results.size(), 3u);
    for (const auto& r : results) {
        if (r.table == "files") EXPECT_EQ(r.count, 2u);
        if (r.table == "partitions") EXPECT_EQ(r.count, 1u);
        if (r.table == "case_keys") {
            EXPECT_EQ(r.count, 1u);
            EXPECT_FALSE(r.rowid_keyed);
        }
    }

    forensics::kv::RocksKVStore store(rocks_path_, {});
    // files rowid 1 encodes to a single 0x01 key byte; the row value must be
    // the canonical bytes python produces for the same cells.
    const std::string key1 = forensics::kv::KVStore::encode_rowid(1);
    const auto row1 = store.get("files", key1);
    ASSERT_TRUE(row1.has_value());
    EXPECT_EQ(*row1,
              R"({"atime":100,"crtime":100,"ctime":100,"id":1,"llm_summary":"sum-a","mtime":100,"partition_num":0,"path":"/case/a.txt","raw":{"__blob_b64__":"AP8Q"},"size":10})");

    // WITHOUT ROWID table keyed by the pk JSON, same as python's "pk:" prefix.
    const std::string pk_key =
        "pk:" + forensics::kv::encode_row(std::vector<std::string>{"path"},
                                          {SqliteCell::from_text("/case/a.txt")});
    EXPECT_TRUE(store.get("case_keys", pk_key).has_value());

    // _meta bookkeeping present for the acceptance verifier.
    EXPECT_TRUE(store.get(forensics::kv::kMetaCF, "table:files:ddl").has_value());
    EXPECT_TRUE(store.get(forensics::kv::kMetaCF, "table:files:keying").has_value());
}

TEST_F(SqliteRocksMirrorTest, RerunIsIdempotentAndPersists) {
    forensics::kv::SqliteRocksMirror mirror;
    ASSERT_EQ(mirror.run(db_path_, rocks_path_).size(), 3u);
    // Re-running over the same (unchanged) source must not duplicate rows.
    ASSERT_EQ(mirror.run(db_path_, rocks_path_).size(), 3u);

    forensics::kv::RocksKVStore store(rocks_path_, {});
    EXPECT_EQ(store.count_prefix("files", ""), 2u);
    EXPECT_EQ(store.count_prefix("partitions", ""), 1u);
    EXPECT_EQ(store.count_prefix("case_keys", "pk:"), 1u);
}

TEST_F(SqliteRocksMirrorTest, OnlyTablesSubset) {
    forensics::kv::SqliteRocksMirror mirror;
    const auto results = mirror.run(db_path_, rocks_path_, {"files"});
    ASSERT_EQ(results.size(), 1u);
    EXPECT_EQ(results[0].table, "files");
    EXPECT_EQ(results[0].count, 2u);
}

TEST_F(SqliteRocksMirrorTest, VerifyPassesThenDetectsCorruption) {
    forensics::kv::SqliteRocksMirror mirror;
    mirror.run(db_path_, rocks_path_);

    for (const auto& [table, passed] : mirror.verify(db_path_, rocks_path_)) {
        EXPECT_TRUE(passed) << table;
    }

    // Flip one byte inside a stored row value: the parity check must fail
    // for that table and stay green for the others.
    {
        forensics::kv::RocksKVStore store(rocks_path_, {"files"});
        const std::string key1 = forensics::kv::KVStore::encode_rowid(1);
        std::string row1 = *store.get("files", key1);
        row1[row1.size() - 1] ^= 0x01;
        store.put("files", key1, row1);
    }
    bool files_failed = false;
    for (const auto& [table, passed] : mirror.verify(db_path_, rocks_path_)) {
        if (table == "files") files_failed = !passed;
        else EXPECT_TRUE(passed) << table;
    }
    EXPECT_TRUE(files_failed);
}

TEST_F(SqliteRocksMirrorTest, PythonGoldenBytesMatchRowCodec) {
    // Cross-language pin (SPEC §8): the value python's encode_value produces
    // for row 2 of the fixture (see build_source_db) must be byte-identical
    // to what the C++ mirror wrote. Row 2 has a NULL blob and a non-ASCII
    // path — the two shapes most likely to diverge between implementations.
    forensics::kv::SqliteRocksMirror mirror;
    mirror.run(db_path_, rocks_path_);
    forensics::kv::RocksKVStore store(rocks_path_, {});
    const auto row2 = store.get("files", forensics::kv::KVStore::encode_rowid(2));
    ASSERT_TRUE(row2.has_value());
    EXPECT_EQ(*row2,
              R"({"atime":180,"crtime":150,"ctime":200,"id":2,"llm_summary":null,"mtime":250,"partition_num":1,"path":"/case/\u4e2d\u6587.bin","raw":null,"size":20})");
}

}  // namespace
