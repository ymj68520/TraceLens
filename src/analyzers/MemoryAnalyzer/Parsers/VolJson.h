// VolJson.h — helpers for reading Volatility3 JSON rows.
//
// vol3's JSON renderer (cli/text_renderer.py, JsonRenderer) emits row keys
// named EXACTLY like the plugin's TreeGrid column headers — e.g. linux.pslist
// produces "OFFSET (V)", "COMM", "CREATION TIME"; linux.sockstat produces
// "Sock Offset", "Process Name", "Source Addr". Absent values render as null,
// datetimes as ISO-8601 strings, Hex columns as integers, and every row also
// carries a "__children" array.
//
// Parsers therefore probe an ordered list of candidate keys: the current vol3
// column name first, legacy/alternative spellings after.
#pragma once
#include <nlohmann/json.hpp>
#include <initializer_list>
#include <string>

namespace VolJson {

// First candidate key that exists with a non-null value, else nullptr.
inline const nlohmann::json* find(const nlohmann::json& row,
                                  std::initializer_list<const char*> keys) {
    if (!row.is_object()) return nullptr;
    for (const char* k : keys) {
        auto it = row.find(k);
        if (it != row.end() && !it->is_null()) return &*it;
    }
    return nullptr;
}

inline std::string str(const nlohmann::json& row,
                       std::initializer_list<const char*> keys) {
    const nlohmann::json* v = find(row, keys);
    if (!v) return "";
    return v->is_string() ? v->get<std::string>() : v->dump();
}

// Integer field that may arrive as a JSON number or a numeric string
// (e.g. sockstat renders ports as strings).
inline long num(const nlohmann::json& row,
                std::initializer_list<const char*> keys, long def = 0) {
    const nlohmann::json* v = find(row, keys);
    if (!v) return def;
    if (v->is_number_integer()) return v->get<long>();
    if (v->is_number()) return static_cast<long>(v->get<double>());
    if (v->is_string()) {
        try { return std::stol(v->get<std::string>()); }
        catch (...) { return def; }
    }
    return def;
}

} // namespace VolJson
