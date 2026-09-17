// Unit tests for the RocksDB-backed KVStore (mvp-phase1-acceptance SPEC §8 R1).

#include "KVStore/RocksKVStore.h"

#include <gtest/gtest.h>

#include <algorithm>
#include <filesystem>
#include <stdexcept>

namespace {

namespace fs = std::filesystem;
using forensics::kv::KVBatchOp;
using forensics::kv::KVPair;
using forensics::kv::RocksKVStore;

class RocksKVStoreTest : public ::testing::Test {
protected:
    void SetUp() override {
        const std::string test_name =
            ::testing::UnitTest::GetInstance()->current_test_info()->name();
        db_path_ = (fs::temp_directory_path() / "kvstore_tests" / test_name).string();
        fs::remove_all(db_path_);
    }
    void TearDown() override { fs::remove_all(db_path_); }

    std::string db_path_;
};

TEST_F(RocksKVStoreTest, RowidEncodingIsOrderPreserving) {
    const std::uint64_t ids[] = {0, 1, 9, 255, 256, 65535, 1ull << 32, 1ull << 63};
    std::vector<std::string> keys;
    for (const auto id : ids) keys.push_back(forensics::kv::KVStore::encode_rowid(id));
    EXPECT_TRUE(std::is_sorted(keys.begin(), keys.end()));
    EXPECT_EQ(forensics::kv::KVStore::encode_rowid(1 << 20)[7], static_cast<char>(1 << 20 & 0xFF));
}

TEST_F(RocksKVStoreTest, PutGetDeleteRoundtrip) {
    RocksKVStore store(db_path_, {"files"});
    store.put("files", "\x00\x01", R"({"a":1})");
    ASSERT_TRUE(store.get("files", "\x00\x01").has_value());
    EXPECT_EQ(*store.get("files", "\x00\x01"), R"({"a":1})");
    store.erase("files", "\x00\x01");
    EXPECT_FALSE(store.get("files", "\x00\x01").has_value());
}

TEST_F(RocksKVStoreTest, UnknownColumnFamilyRejected) {
    RocksKVStore store(db_path_, {});
    EXPECT_THROW(store.put("nope", "k", "v"), std::out_of_range);
    EXPECT_THROW(store.get("nope", "k"), std::out_of_range);
}

TEST_F(RocksKVStoreTest, BatchIsAtomicAndSupportsDeletes) {
    RocksKVStore store(db_path_, {"files", "events"});
    store.write_batch({
        {"files", "\x01", "a", false},
        {"events", "\x02", "b", false},
    });
    EXPECT_EQ(*store.get("files", "\x01"), "a");
    EXPECT_EQ(*store.get("events", "\x02"), "b");
    store.write_batch({
        {"files", "\x01", "", true},     // erase
        {"files", "\x03", "c", false},
    });
    EXPECT_FALSE(store.get("files", "\x01").has_value());
    EXPECT_EQ(*store.get("files", "\x03"), "c");
}

TEST_F(RocksKVStoreTest, ScanPrefixIsOrderedAndFiltered) {
    RocksKVStore store(db_path_, {"files", "events"});
    store.write_batch({
        {"files", std::string("row:\x01", 5), "row1", false},
        {"files", std::string("row:\x02", 5), "row2", false},
        {"files", std::string("row:\x03", 5), "row3", false},
        {"files", "meta:count", "3", false},
        {"events", std::string("row:\x01", 5), "other-cf", false},
    });

    const auto rows = store.scan_prefix("files", "row:");
    ASSERT_EQ(rows.size(), 3u);
    EXPECT_EQ(rows[0].value, "row1");
    EXPECT_EQ(rows[2].value, "row3");
    EXPECT_EQ(store.count_prefix("files", "meta:"), 1u);
}

TEST_F(RocksKVStoreTest, ReopenAttachesToExistingFamiliesAndPersists) {
    {
        RocksKVStore store(db_path_, {"files"});
        store.put("files", forensics::kv::KVStore::encode_rowid(7), "payload");
        store.put(forensics::kv::kMetaCF, "migrated", "yes");
        store.flush();
    }
    RocksKVStore reopened(db_path_, {"files"});
    ASSERT_TRUE(reopened.get("files", forensics::kv::KVStore::encode_rowid(7)).has_value());
    EXPECT_EQ(*reopened.get("files", forensics::kv::KVStore::encode_rowid(7)), "payload");
    EXPECT_EQ(*reopened.get(forensics::kv::kMetaCF, "migrated"), "yes");
}

}  // namespace
