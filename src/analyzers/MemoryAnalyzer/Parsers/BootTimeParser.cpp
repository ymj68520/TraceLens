#include "BootTimeParser.h"
#include "../Database/MemoryAnalysisDatabase.h"
#include <string>

static std::string s(const nlohmann::json& j, const char* k) {
    if (!j.contains(k) || j[k].is_null()) return "";
    return j[k].is_string() ? j[k].get<std::string>() : j[k].dump();
}

void parseBootTime(const nlohmann::json& arr, MemoryAnalysisDatabase& db) {
    if (!arr.is_array() || arr.empty()) return;
    const auto& o = arr[0];
    std::string bt = s(o, "BootTime");
    if (!bt.empty()) db.setBootInfo("boot_time", bt);
}
