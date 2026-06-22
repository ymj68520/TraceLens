#include "NetworkParser.h"
#include "../Database/MemoryAnalysisDatabase.h"
#include <string>

static std::string s(const nlohmann::json& j, const char* k) {
    if (!j.contains(k) || j[k].is_null()) return "";
    return j[k].is_string() ? j[k].get<std::string>() : j[k].dump();
}

size_t parseNetstat(const nlohmann::json& arr, MemoryAnalysisDatabase& db) {
    if (!arr.is_array()) return 0;
    size_t n = 0;
    for (const auto& c : arr) {
        db.insertNetworkConnection(
            c.value("Offset", 0L),
            c.value("PID", 0),
            s(c, "Process"),
            s(c, "Proto"),
            s(c, "LocalAddr"),
            c.value("LocalPort", 0),
            s(c, "ForeignAddr"),
            c.value("ForeignPort", 0),
            s(c, "State"));
        ++n;
    }
    return n;
}

size_t parseSockstat(const nlohmann::json& arr, MemoryAnalysisDatabase& db) {
    if (!arr.is_array()) return 0;
    size_t n = 0;
    for (const auto& c : arr) {
        db.insertSocket(
            c.value("Offset", 0L),
            c.value("PID", 0),
            s(c, "Process"),
            s(c, "Family"),
            s(c, "Type"),
            s(c, "LocalAddr"),
            s(c, "RemoteAddr"),
            s(c, "State"));
        ++n;
    }
    return n;
}
