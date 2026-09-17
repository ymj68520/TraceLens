// KVStore.h
// Abstract key-value storage seam for the SQLite → RocksDB migration
// (mvp-phase1-acceptance SPEC §8, R1). Later phases (R2/R3) back the per-task
// databases with implementations of this interface; the Python side mirrors
// the same column-family/key conventions (python_service/storage/rocksdb_store.py).
//
// Conventions shared with the Python store:
// - one column family per migrated table, plus a "_meta" bookkeeping family;
// - keys are byte strings; rowid-style keys use big-endian fixed width so
//   lexicographic prefix scans read like ordered table scans.

#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace forensics::kv {

struct KVPair {
    std::string key;
    std::string value;
};

struct KVBatchOp {
    std::string cf;
    std::string key;
    std::string value;   // payload; ignored when erase == true
    bool erase = false;  // true → remove the key
};

class KVStore {
public:
    virtual ~KVStore() = default;

    virtual void put(const std::string& cf, const std::string& key,
                     const std::string& value) = 0;
    virtual void erase(const std::string& cf, const std::string& key) = 0;
    virtual std::optional<std::string> get(const std::string& cf,
                                           const std::string& key) = 0;

    // Atomic multi-operation write.
    virtual void write_batch(const std::vector<KVBatchOp>& ops) = 0;

    // Ordered (key ascending) scan of one family limited to keys that start
    // with prefix.
    virtual std::vector<KVPair> scan_prefix(const std::string& cf,
                                            const std::string& prefix) = 0;
    virtual std::uint64_t count_prefix(const std::string& cf,
                                       const std::string& prefix) = 0;

    // Big-endian 8-byte rowid encoding: numeric order == lexicographic order.
    static std::string encode_rowid(std::uint64_t rowid) {
        std::string key(8, '\0');
        for (int i = 7; i >= 0; --i) {
            key[static_cast<size_t>(i)] =
                static_cast<char>((rowid >> (8 * (7 - i))) & 0xFF);
        }
        return key;
    }
};

}  // namespace forensics::kv
