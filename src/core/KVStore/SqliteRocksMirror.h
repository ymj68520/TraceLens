// SqliteRocksMirror.h
// Whole-database SQLite → RocksDB mirror for the dual-run migration window
// (mvp-phase1-acceptance SPEC §8, R2).
//
// Instead of hooking every analyzer's INSERT site (TSK, native XFS mounts and
// the OSS/Android analyzers each have their own writers), the finished SQLite
// file is mirrored once into a RocksDB store next to it: every table becomes a
// column family, every row is keyed by its big-endian rowid (or `pk:` JSON
// key for WITHOUT ROWID tables) and stored as a RowCodec-canonical JSON row.
// The run is idempotent and read-only on the source, so the SQLite pipeline
// stays the source of truth while the RocksDB twin catches up.
//
// The `_meta` bookkeeping entries match the Python migration tool
// (python_service/storage/sqlite_migrate.py), which is also the acceptance
// verifier: `scripts/migrate_sqlite_to_rocksdb.py --verify` must pass against
// a C++-mirrored store.

#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace forensics::kv {

struct MirrorResult {
    std::string table;
    std::uint64_t count = 0;
    bool rowid_keyed = true;
};

// Engine note (SPEC §8): stores written by this class use the standard
// leveldb.BytewiseComparator and are readable by the C++ side (and any
// standard rocksdb build). The Python rocksdict binding pins a custom
// comparator named "rocksdict" and cannot open them — verification of
// C++-mirrored stores therefore lives here, not in the Python tool. The
// cross-language contract is the row BYTE FORMAT (RowCodec == python
// encode_value, pinned golden tests on both sides).
class SqliteRocksMirror {
public:
    // Mirrors the given tables (empty → every non-internal table) from
    // sqlite_path into a RocksDB store at rocks_path (created/updated).
    // Throws std::runtime_error on any sqlite/rocksdb failure; the source
    // database is only ever opened read-only.
    std::vector<MirrorResult> run(const std::string& sqlite_path,
                                  const std::string& rocks_path,
                                  const std::vector<std::string>& only_tables = {});

    // Per-table parity check of a previously mirrored store against its
    // sqlite source: row counts must match and the order-independent
    // per-row digest (XOR of per-row SHA-256 over key and canonical value)
    // must be identical. Return maps table → ok.
    std::vector<std::pair<std::string, bool>> verify(
        const std::string& sqlite_path,
        const std::string& rocks_path,
        const std::vector<std::string>& only_tables = {});
};

}  // namespace forensics::kv
