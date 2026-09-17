// RowCodec.cpp
// Canonical row encoding shared with the Python tooling (SPEC §8).

#include "RowCodec.h"

#include <nlohmann/json.hpp>

#include <algorithm>

namespace forensics::kv {

namespace {

constexpr const char* kBlobKey = "__blob_b64__";

nlohmann::json cell_to_json(const SqliteCell& cell) {
    switch (cell.type) {
        case SqliteCell::Type::kNull:
            return nullptr;
        case SqliteCell::Type::kInteger:
            return cell.integer;
        case SqliteCell::Type::kReal:
            return cell.real;
        case SqliteCell::Type::kText:
            return cell.text;
        case SqliteCell::Type::kBlob:
            // Wrapped-object form matches python sqlite_migrate._jsonify.
            return nlohmann::json{{kBlobKey, base64_encode(cell.text)}};
    }
    return nullptr;
}

}  // namespace

std::string base64_encode(const std::string& bytes) {
    static const char kAlphabet[] =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::string out;
    out.reserve(((bytes.size() + 2) / 3) * 4);
    size_t i = 0;
    while (i + 3 <= bytes.size()) {
        const std::uint32_t chunk =
            (static_cast<std::uint8_t>(bytes[i]) << 16) |
            (static_cast<std::uint8_t>(bytes[i + 1]) << 8) |
            static_cast<std::uint8_t>(bytes[i + 2]);
        out.push_back(kAlphabet[(chunk >> 18) & 0x3F]);
        out.push_back(kAlphabet[(chunk >> 12) & 0x3F]);
        out.push_back(kAlphabet[(chunk >> 6) & 0x3F]);
        out.push_back(kAlphabet[chunk & 0x3F]);
        i += 3;
    }
    const size_t rest = bytes.size() - i;
    if (rest == 1) {
        const std::uint32_t chunk = static_cast<std::uint8_t>(bytes[i]) << 16;
        out.push_back(kAlphabet[(chunk >> 18) & 0x3F]);
        out.push_back(kAlphabet[(chunk >> 12) & 0x3F]);
        out.push_back('=');
        out.push_back('=');
    } else if (rest == 2) {
        const std::uint32_t chunk = (static_cast<std::uint8_t>(bytes[i]) << 16) |
                                    (static_cast<std::uint8_t>(bytes[i + 1]) << 8);
        out.push_back(kAlphabet[(chunk >> 18) & 0x3F]);
        out.push_back(kAlphabet[(chunk >> 12) & 0x3F]);
        out.push_back(kAlphabet[(chunk >> 6) & 0x3F]);
        out.push_back('=');
    }
    return out;
}

std::string encode_row(const std::vector<std::pair<std::string, SqliteCell>>& cells) {
    nlohmann::json row = nlohmann::json::object();
    for (const auto& [name, cell] : cells) {
        row[name] = cell_to_json(cell);
    }
    // -1 = compact; ensure_ascii = true → \uXXXX escapes, matching
    // json.dumps(..., ensure_ascii=True). nlohmann objects iterate keys in
    // sorted order, matching sort_keys=True.
    return row.dump(-1, ' ', true);
}

std::string encode_row(const std::vector<std::string>& columns,
                       const std::vector<SqliteCell>& cells) {
    std::vector<std::pair<std::string, SqliteCell>> zipped;
    zipped.reserve(std::min(columns.size(), cells.size()));
    for (size_t i = 0; i < columns.size() && i < cells.size(); ++i) {
        zipped.emplace_back(columns[i], cells[i]);
    }
    return encode_row(zipped);
}

}  // namespace forensics::kv
