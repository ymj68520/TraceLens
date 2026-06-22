#include "ProcessParser.h"
#include "../Database/MemoryAnalysisDatabase.h"
#include <string>

static std::string s(const nlohmann::json& j, const char* k) {
    if (!j.contains(k) || j[k].is_null()) return "";
    return j[k].is_string() ? j[k].get<std::string>() : j[k].dump();
}

size_t parseProcesses(const nlohmann::json& arr, MemoryAnalysisDatabase& db) {
    if (!arr.is_array()) return 0;
    size_t n = 0;
    for (const auto& p : arr) {
        db.insertProcess(
            p.value("Offset", 0L),
            p.value("PID", 0),
            p.value("PPID", 0),
            p.value("Name", s(p, "Comm")),
            p.value("UID", 0),
            p.value("GID", 0),
            p.value("Start", 0L),
            p.value("Threads", 0),
            s(p, "State"));
        ++n;
    }
    return n;
}
