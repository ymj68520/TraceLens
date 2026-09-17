// SqliteRocksMirror.cpp
// Whole-database SQLite → RocksDB mirror (SPEC §8 R2). See the header.

#include "SqliteRocksMirror.h"

#include "KVStore.h"
#include "RowCodec.h"
#include "RocksKVStore.h"

#include <sqlite3.h>

#include <nlohmann/json.hpp>

#include <openssl/evp.h>

#include <algorithm>
#include <array>
#include <cstdio>
#include <filesystem>
#include <functional>
#include <stdexcept>

namespace forensics::kv {

namespace {

std::runtime_error sqlite_error(const std::string& what, sqlite3* db) {
    return std::runtime_error(what + ": " +
                              (db ? sqlite3_errmsg(db) : "sqlite not opened"));
}

struct TableInfo {
    std::string name;
    std::string ddl;
    std::vector<std::string> columns;
    std::vector<std::string> pk_columns;  // declared PK columns, pk order
    bool rowid_keyed = true;
};

std::vector<TableInfo> list_tables(sqlite3* db,
                                   const std::vector<std::string>& only) {
    std::vector<TableInfo> tables;
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(
            db, "SELECT name, sql FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name",
            -1, &stmt, nullptr) != SQLITE_OK) {
        throw sqlite_error("list tables", db);
    }
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        TableInfo info;
        info.name = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
        const auto* ddl = sqlite3_column_text(stmt, 1);
        info.ddl = ddl ? reinterpret_cast<const char*>(ddl) : "";
        if (only.empty() ||
            std::find(only.begin(), only.end(), info.name) != only.end()) {
            tables.push_back(std::move(info));
        }
    }
    sqlite3_finalize(stmt);

    for (auto& info : tables) {
        sqlite3_stmt* pragma = nullptr;
        const std::string sql = "PRAGMA table_info(\"" + info.name + "\")";
        if (sqlite3_prepare_v2(db, sql.c_str(), -1, &pragma, nullptr) != SQLITE_OK) {
            throw sqlite_error("table_info " + info.name, db);
        }
        while (sqlite3_step(pragma) == SQLITE_ROW) {
            const auto* col = sqlite3_column_text(pragma, 1);
            info.columns.push_back(col ? reinterpret_cast<const char*>(col) : "");
            const int pk_order = sqlite3_column_int(pragma, 5);
            if (pk_order > 0) {
                // Pad the vector so pk order indexes line up.
                if (static_cast<int>(info.pk_columns.size()) < pk_order) {
                    info.pk_columns.resize(static_cast<size_t>(pk_order));
                }
                info.pk_columns[static_cast<size_t>(pk_order - 1)] =
                    col ? reinterpret_cast<const char*>(col) : "";
            }
        }
        sqlite3_finalize(pragma);
        // WITHOUT ROWID detection: rowid is unreachable on such tables.
        sqlite3_stmt* probe = nullptr;
        const std::string probe_sql = "SELECT rowid FROM \"" + info.name + "\" LIMIT 1";
        info.rowid_keyed =
            sqlite3_prepare_v2(db, probe_sql.c_str(), -1, &probe, nullptr) == SQLITE_OK;
        if (probe) sqlite3_finalize(probe);
    }
    return tables;
}

class SqliteHandle {
public:
    explicit SqliteHandle(const std::string& path) {
        if (sqlite3_open_v2(path.c_str(), &db_, SQLITE_OPEN_READONLY, nullptr) !=
            SQLITE_OK) {
            throw sqlite_error("open " + path, db_);
        }
    }
    ~SqliteHandle() {
        if (db_) sqlite3_close_v2(db_);
    }
    SqliteHandle(const SqliteHandle&) = delete;
    SqliteHandle& operator=(const SqliteHandle&) = delete;
    sqlite3* get() const { return db_; }

private:
    sqlite3* db_ = nullptr;
};

SqliteCell read_cell(sqlite3_stmt* stmt, int index) {
    switch (sqlite3_column_type(stmt, index)) {
        case SQLITE_INTEGER:
            return SqliteCell::from_integer(sqlite3_column_int64(stmt, index));
        case SQLITE_FLOAT:
            return SqliteCell::from_real(sqlite3_column_double(stmt, index));
        case SQLITE_TEXT:
            return SqliteCell::from_text(
                std::string(reinterpret_cast<const char*>(sqlite3_column_text(stmt, index)),
                            static_cast<size_t>(sqlite3_column_bytes(stmt, index))));
        case SQLITE_BLOB:
            return SqliteCell::from_blob(
                std::string(static_cast<const char*>(sqlite3_column_blob(stmt, index)),
                            static_cast<size_t>(sqlite3_column_bytes(stmt, index))));
        default:
            return SqliteCell::null();
    }
}

// Emits every row of the table as its canonical (key, value) pair, in source
// order (rowid ascending, or declared-pk order). Shared by run() and verify().
void walk_table_rows(
    sqlite3* db, const TableInfo& table,
    const std::function<void(const std::string&, const std::string&)>& sink) {
    std::string select;
    if (table.rowid_keyed) {
        select = "SELECT rowid, * FROM \"" + table.name + "\" ORDER BY rowid";
    } else {
        select = "SELECT * FROM \"" + table.name + "\"";
        if (!table.pk_columns.empty()) {
            select += " ORDER BY ";
            for (size_t i = 0; i < table.pk_columns.size(); ++i) {
                if (i) select += ", ";
                select += "\"" + table.pk_columns[i] + "\"";
            }
        }
    }

    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db, select.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        throw sqlite_error("select " + table.name, db);
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        std::vector<SqliteCell> cells;
        cells.reserve(static_cast<size_t>(sqlite3_column_count(stmt) -
                                          (table.rowid_keyed ? 1 : 0)));
        const int first = table.rowid_keyed ? 1 : 0;
        for (int i = first; i < sqlite3_column_count(stmt); ++i) {
            cells.push_back(read_cell(stmt, i));
        }

        std::string key;
        if (table.rowid_keyed) {
            key = KVStore::encode_rowid(
                static_cast<std::uint64_t>(sqlite3_column_int64(stmt, 0)));
        } else {
            std::vector<std::string> pk_cols;
            std::vector<SqliteCell> pk_cells;
            for (const auto& pk_col : table.pk_columns) {
                const auto it =
                    std::find(table.columns.begin(), table.columns.end(), pk_col);
                const size_t idx = static_cast<size_t>(
                    it == table.columns.end() ? -1 : it - table.columns.begin());
                if (idx < cells.size()) {
                    pk_cols.push_back(pk_col);
                    pk_cells.push_back(cells[idx]);
                }
            }
            key = "pk:" + encode_row(pk_cols, pk_cells);
        }
        sink(key, encode_row(table.columns, cells));
    }
    sqlite3_finalize(stmt);
}

// Order-independent per-row digest: XOR of SHA-256(key || canonical value).
// XOR is commutative, so source-vs-store iteration order cannot fake a match.
using RowDigest = std::array<unsigned char, 32>;

void digest_row(RowDigest& acc, const std::string& key, const std::string& value) {
    unsigned char hash[EVP_MAX_MD_SIZE];
    unsigned int hash_len = 0;
    EVP_MD_CTX* ctx = EVP_MD_CTX_new();
    EVP_DigestInit_ex(ctx, EVP_sha256(), nullptr);
    EVP_DigestUpdate(ctx, key.data(), key.size());
    EVP_DigestUpdate(ctx, value.data(), value.size());
    EVP_DigestFinal_ex(ctx, hash, &hash_len);
    EVP_MD_CTX_free(ctx);
    for (unsigned int i = 0; i < hash_len && i < acc.size(); ++i) {
        acc[i] ^= hash[i];
    }
}

std::string digest_hex(const RowDigest& digest) {
    static const char* kHex = "0123456789abcdef";
    std::string out;
    out.reserve(digest.size() * 2);
    for (const unsigned char byte : digest) {
        out.push_back(kHex[byte >> 4]);
        out.push_back(kHex[byte & 0x0F]);
    }
    return out;
}

}  // namespace

std::vector<MirrorResult> SqliteRocksMirror::run(const std::string& sqlite_path,
                                                 const std::string& rocks_path,
                                                 const std::vector<std::string>& only_tables) {
    const SqliteHandle source(sqlite_path);
    sqlite3* db = source.get();

    const auto tables = list_tables(db, only_tables);
    if (tables.empty()) return {};

    std::vector<std::string> families;
    families.reserve(tables.size());
    for (const auto& table : tables) families.push_back(table.name);

    RocksKVStore store(rocks_path, families);
    std::vector<MirrorResult> results;

    for (const auto& table : tables) {
        MirrorResult result;
        result.table = table.name;
        result.rowid_keyed = table.rowid_keyed;

        std::vector<KVBatchOp> batch;
        batch.reserve(1024);
        walk_table_rows(db, table,
                        [&](const std::string& key, const std::string& value) {
                            KVBatchOp op;
                            op.cf = table.name;
                            op.key = key;
                            op.value = value;
                            batch.push_back(std::move(op));
                            ++result.count;
                            if (batch.size() >= 1024) {
                                store.write_batch(batch);
                                batch.clear();
                            }
                        });
        if (!batch.empty()) store.write_batch(batch);

        // _meta bookkeeping, byte-compatible with the Python migration tool.
        const std::string prefix = std::string("table:") + table.name;
        store.put(kMetaCF, prefix + ":ddl", table.ddl);
        {
            nlohmann::json cols = nlohmann::json::array();
            for (const auto& col : table.columns) cols.push_back(col);
            store.put(kMetaCF, prefix + ":columns", cols.dump(-1, ' ', true));
        }
        {
            nlohmann::json keying = nlohmann::json::object();
            keying["rowid_keyed"] = table.rowid_keyed;
            keying["pk"] = table.pk_columns;
            keying["count"] = result.count;
            store.put(kMetaCF, prefix + ":keying", keying.dump(-1, ' ', true));
        }
        results.push_back(std::move(result));
    }

    store.put(kMetaCF, "source_sqlite", sqlite_path);
    store.flush();
    return results;
}

std::vector<std::pair<std::string, bool>> SqliteRocksMirror::verify(
    const std::string& sqlite_path,
    const std::string& rocks_path,
    const std::vector<std::string>& only_tables) {
    const SqliteHandle source(sqlite_path);
    sqlite3* db = source.get();

    const auto tables = list_tables(db, only_tables);
    // Requested-families list empty → the store reopens everything on disk,
    // which is what a previously mirrored store needs.
    RocksKVStore store(rocks_path, {});
    std::vector<std::pair<std::string, bool>> results;

    for (const auto& table : tables) {
        RowDigest source_digest{};
        std::uint64_t source_count = 0;
        walk_table_rows(db, table,
                        [&](const std::string& key, const std::string& value) {
                            digest_row(source_digest, key, value);
                            ++source_count;
                        });

        RowDigest store_digest{};
        std::uint64_t store_count = 0;
        for (const auto& [key, value] : store.scan_prefix(table.name, std::string())) {
            digest_row(store_digest, key, value);
            ++store_count;
        }

        results.emplace_back(table.name,
                             source_count == store_count && source_digest == store_digest);
    }
    return results;
}

}  // namespace forensics::kv
