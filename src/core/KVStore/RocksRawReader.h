// RocksRawReader.h
// Read side of the RocksDB dual-run window (mvp-phase1-acceptance SPEC §8 R3).
//
// Reads the whole-database mirror produced by SqliteRocksMirror / the Python
// migration tool: one column family per table, rows keyed by big-endian
// rowid (or `pk:` JSON key for WITHOUT ROWID tables), values are RowCodec-
// canonical JSON rows, `_meta` carries DDL/columns/keying per table.
//
// This is deliberately a raw row reader, not a SQL engine: it serves the
// point-lookups and ordered scans the report surfaces need (get file by
// rowid, iterate a table in rowid order, filter rows in memory). Aggregations
// stay on the SQLite side until their dedicated index-CF rewrite lands.

#pragma once

#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include <nlohmann/json.hpp>

namespace forensics::kv {

// A decoded mirrored row: key encoding plus the JSON value.
struct RocksRow {
    std::string key;      // raw key bytes (binary rowid or "pk:{...}")
    std::int64_t rowid = -1;  // >= 0 for rowid-keyed tables
    nlohmann::json value;
};

class RocksRawReader {
public:
    // Attaches to an existing mirrored store. Throws std::runtime_error when
    // the directory does not look like a RocksDB store (so callers can fall
    // back to the SQLite read path).
    explicit RocksRawReader(const std::string& rocks_path);
    ~RocksRawReader();
    RocksRawReader(const RocksRawReader&) = delete;
    RocksRawReader& operator=(const RocksRawReader&) = delete;

    // True when the store carries the table's keying metadata (a table is
    // "readable" once its _meta rows exist — written last during mirroring).
    bool has_table(const std::string& table) const;

    // Full row by rowid (rowid-keyed tables only).
    std::optional<nlohmann::json> get_by_rowid(const std::string& table,
                                               std::int64_t rowid) const;

    // Every row of a table in key order, decoded.
    std::vector<RocksRow> scan_table(const std::string& table) const;

    // The `_meta` keying record for a table.
    struct Keying {
        bool rowid_keyed = true;
        std::vector<std::string> pk;
        std::uint64_t count = 0;
    };
    std::optional<Keying> keying(const std::string& table) const;

    // Mirrored-row count (scan size of the family), for cross-checks.
    std::uint64_t count_rows(const std::string& table) const;

private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace forensics::kv
