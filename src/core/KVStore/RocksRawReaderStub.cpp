// RocksRawReaderStub.cpp
// No-op build of the raw reader for machines without the rocksdb library
// (mvp-phase1-acceptance SPEC §8). Construction throws so callers fall back
// to the SQLite read path — matching the "unreadable store" contract.

#include "RocksRawReader.h"

#include <stdexcept>

namespace forensics::kv {

RocksRawReader::RocksRawReader(const std::string&) {
    throw std::runtime_error(
        "RocksDB support is not built into this binary (rocksdb library missing)");
}

RocksRawReader::~RocksRawReader() = default;

bool RocksRawReader::has_table(const std::string&) const { return false; }

std::optional<nlohmann::json> RocksRawReader::get_by_rowid(const std::string&, std::int64_t) {
    return std::nullopt;
}

std::vector<RocksRow> RocksRawReader::scan_table(const std::string&) { return {}; }

std::optional<RocksRawReader::Keying> RocksRawReader::keying(const std::string&) const {
    return std::nullopt;
}

std::uint64_t RocksRawReader::count_rows(const std::string&) { return 0; }

}  // namespace forensics::kv
