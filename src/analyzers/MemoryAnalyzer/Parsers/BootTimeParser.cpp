#include "BootTimeParser.h"
#include "VolJson.h"
#include "../Database/MemoryAnalysisDatabase.h"
#include <string>

// linux.boottime (vol3 2.x) columns: "TIME NS", "Boot Time" (ISO-8601 string).
void parseBootTime(const nlohmann::json& arr, MemoryAnalysisDatabase& db) {
    if (!arr.is_array() || arr.empty()) return;
    const auto& o = arr[0];
    std::string bt = VolJson::str(o, {"Boot Time", "BootTime"});
    if (!bt.empty()) db.setBootInfo("boot_time", bt);
    std::string ns = VolJson::str(o, {"TIME NS"});
    if (!ns.empty()) db.setBootInfo("boot_time_ns", ns);
}
