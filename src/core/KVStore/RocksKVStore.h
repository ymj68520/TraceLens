// RocksKVStore.h
// RocksDB-backed KVStore (mvp-phase1-acceptance SPEC §8, R1).

#pragma once

#include "KVStore.h"

#include <rocksdb/db.h>

#include <string>
#include <vector>

namespace forensics::kv {

// Bookkeeping family shared with the Python migration tool.
inline constexpr const char* kMetaCF = "_meta";

class RocksKVStore final : public KVStore {
public:
    // Opens (creating if needed) the database at path. Column families are
    // created on first open; reopening attaches to the existing ones. The
    // "_meta" family is always available.
    RocksKVStore(const std::string& path,
                 const std::vector<std::string>& column_families = {});
    ~RocksKVStore() override;

    RocksKVStore(const RocksKVStore&) = delete;
    RocksKVStore& operator=(const RocksKVStore&) = delete;

    void put(const std::string& cf, const std::string& key,
             const std::string& value) override;
    void erase(const std::string& cf, const std::string& key) override;
    std::optional<std::string> get(const std::string& cf,
                                   const std::string& key) override;
    void write_batch(const std::vector<KVBatchOp>& ops) override;
    std::vector<KVPair> scan_prefix(const std::string& cf,
                                    const std::string& prefix) override;
    std::uint64_t count_prefix(const std::string& cf,
                               const std::string& prefix) override;

    void flush();

private:
    rocksdb::ColumnFamilyHandle* handle_or_throw(const std::string& cf) const;

    rocksdb::DB* db_ = nullptr;  // owned; closed in the destructor
    std::vector<std::string> cf_names_;
    std::vector<rocksdb::ColumnFamilyHandle*> cf_handles_;  // owned by db_
};

}  // namespace forensics::kv
