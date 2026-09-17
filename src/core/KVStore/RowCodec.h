// RowCodec.h
// Canonical row encoding shared by the C++ mirror writer and the Python
// migration/verification tooling (mvp-phase1-acceptance SPEC §8).
//
// The byte format is pinned to Python's
//   json.dumps(cells, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
// so a RocksDB row written by either side verifies against the other:
// keys sorted, compact separators, non-ASCII escaped as lowercase \uXXXX
// (surrogate pairs), and BLOB cells wrapped as {"__blob_b64__": "<base64>"}.

#pragma once

#include <cstdint>
#include <string>
#include <utility>
#include <vector>

namespace forensics::kv {

// A SQLite cell as a tagged value (mirrors sqlite3_column_type semantics —
// SQLite is dynamically typed per value, not per column).
struct SqliteCell {
    enum class Type : int { kNull = 0, kInteger = 1, kReal = 2, kText = 3, kBlob = 4 };

    Type type = Type::kNull;
    std::int64_t integer = 0;  // kInteger
    double real = 0.0;         // kReal
    std::string text;          // kText: UTF-8; kBlob: raw bytes

    static SqliteCell null() { return {}; }
    static SqliteCell from_integer(std::int64_t v) {
        SqliteCell c;
        c.type = Type::kInteger;
        c.integer = v;
        return c;
    }
    static SqliteCell from_real(double v) {
        SqliteCell c;
        c.type = Type::kReal;
        c.real = v;
        return c;
    }
    static SqliteCell from_text(std::string v) {
        SqliteCell c;
        c.type = Type::kText;
        c.text = std::move(v);
        return c;
    }
    static SqliteCell from_blob(std::string v) {
        SqliteCell c;
        c.type = Type::kBlob;
        c.text = std::move(v);
        return c;
    }
};

// Standard base64 (with padding), as used by Python base64.b64encode.
std::string base64_encode(const std::string& bytes);

// Byte-canonical row encoding (see file header). The cells vector may be in
// any key order; the encoding sorts keys, matching Python's sort_keys.
std::string encode_row(const std::vector<std::pair<std::string, SqliteCell>>& cells);

// Same canonical encoding from parallel column/value arrays (the shape a
// sqlite3_stmt yields). columns.size() may be shorter; extras are ignored.
std::string encode_row(const std::vector<std::string>& columns,
                       const std::vector<SqliteCell>& cells);

}  // namespace forensics::kv
