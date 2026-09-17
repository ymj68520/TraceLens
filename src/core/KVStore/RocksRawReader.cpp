// RocksRawReader.cpp
// Read side of the RocksDB dual-run window (SPEC §8 R3). See the header.

#include "RocksRawReader.h"

#include "KVStore.h"
#include "RocksKVStore.h"

#include <sqlite3.h>

#include <nlohmann/json.hpp>

#include <filesystem>
#include <stdexcept>

namespace forensics::kv {

class RocksRawReader::Impl {
public:
    explicit Impl(const std::string& rocks_path) : store(rocks_path, {}) {}

    RocksKVStore store;
};

RocksRawReader::RocksRawReader(const std::string& rocks_path) {
    // A directory that does not look like a mirrored store must fail loudly
    // here — the query layer catches this and falls back to SQLite. The
    // CURRENT file is the marker RocksDB writes on first successful open.
    // Checked BEFORE opening so a missing store is never silently created.
    std::error_code ec;
    const std::filesystem::path dir(rocks_path);
    if (!std::filesystem::exists(dir, ec) || !std::filesystem::is_directory(dir, ec) ||
        !std::filesystem::exists(dir / "CURRENT", ec)) {
        throw std::runtime_error("RocksRawReader: no mirrored store at " + rocks_path);
    }
    impl_ = std::make_unique<Impl>(rocks_path);
}

RocksRawReader::~RocksRawReader() = default;

std::optional<RocksRawReader::Keying> RocksRawReader::keying(const std::string& table) const {
    const auto raw = impl_->store.get(kMetaCF, "table:" + table + ":keying");
    if (!raw) return std::nullopt;
    try {
        const auto parsed = nlohmann::json::parse(*raw);
        Keying keying;
        keying.rowid_keyed = parsed.value("rowid_keyed", true);
        if (parsed.contains("pk") && parsed["pk"].is_array()) {
            for (const auto& col : parsed["pk"]) keying.pk.push_back(col.get<std::string>());
        }
        keying.count = parsed.value("count", static_cast<std::uint64_t>(0));
        return keying;
    } catch (const nlohmann::json::exception&) {
        return std::nullopt;
    }
}

bool RocksRawReader::has_table(const std::string& table) const {
    return keying(table).has_value();
}

std::optional<nlohmann::json> RocksRawReader::get_by_rowid(const std::string& table,
                                                           std::int64_t rowid) const {
    const auto raw = impl_->store.get(table, KVStore::encode_rowid(static_cast<std::uint64_t>(rowid)));
    if (!raw) return std::nullopt;
    try {
        return nlohmann::json::parse(*raw);
    } catch (const nlohmann::json::exception&) {
        return std::nullopt;
    }
}

std::vector<RocksRow> RocksRawReader::scan_table(const std::string& table) const {
    std::vector<RocksRow> rows;
    for (const auto& [key, value] : impl_->store.scan_prefix(table, std::string())) {
        RocksRow row;
        row.key = key;
        if (key.size() == 8 && (key[0] & 0x80) == 0) {
            // Big-endian rowid encoding: top bit clear for our range.
            std::uint64_t id = 0;
            for (const char byte : key) {
                id = (id << 8) | static_cast<unsigned char>(byte);
            }
            row.rowid = static_cast<std::int64_t>(id);
        }
        try {
            row.value = nlohmann::json::parse(value);
        } catch (const nlohmann::json::exception&) {
            continue;  // skip undecodable rows rather than failing the scan
        }
        rows.push_back(std::move(row));
    }
    return rows;
}

std::uint64_t RocksRawReader::count_rows(const std::string& table) const {
    return impl_->store.count_prefix(table, std::string());
}

}  // namespace forensics::kv
