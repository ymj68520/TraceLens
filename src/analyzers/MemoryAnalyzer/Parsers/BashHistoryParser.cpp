#include "BashHistoryParser.h"
#include "../Database/MemoryAnalysisDatabase.h"
#include <string>

static std::string s(const nlohmann::json& j, const char* k) {
    if (!j.contains(k) || j[k].is_null()) return "";
    return j[k].is_string() ? j[k].get<std::string>() : j[k].dump();
}

size_t parseBashHistory(const nlohmann::json& arr, MemoryAnalysisDatabase& db) {
    if (!arr.is_array()) return 0;
    size_t n = 0, idx = 0;
    for (const auto& h : arr) {
        db.insertBashHistory(
            h.value("PID", 0),
            s(h, "Process"),
            s(h, "Command"),
            static_cast<int>(idx++));
        ++n;
    }
    return n;
}
