// WindowsParsers.cpp
#include "WindowsParsers.h"
#include "VolJson.h"
#include "../Database/MemoryAnalysisDatabase.h"

namespace WindowsParsers {

size_t parseProcessList(const nlohmann::json& arr, MemoryAnalysisDatabase& db) {
    using namespace VolJson;
    if (!arr.is_array()) return 0;
    size_t n = 0;
    for (const auto& p : arr) {
        // Windows has no uid/gid in pslist; store 0. tid is not in pslist;
        // use PID as a stand-in so the NOT NULL column is populated.
        int pid = static_cast<int>(num(p, {"PID"}));
        db.insertProcess(
            num(p, {"OFFSET (V)", "Offset(V)", "Offset"}),
            pid,
            pid,                                   // tid (none in pslist)
            static_cast<int>(num(p, {"PPID"})),
            str(p, {"ImageFileName", "Name", "COMM"}),
            static_cast<int>(num(p, {"UID", "SID"})), 0, 0, 0,
            str(p, {"CreateTime", "CREATION TIME"}));
        ++n;
    }
    return n;
}

size_t parseCmdline(const nlohmann::json& arr, MemoryAnalysisDatabase& db) {
    using namespace VolJson;
    if (!arr.is_array()) return 0;
    size_t n = 0;
    for (const auto& c : arr) {
        db.insertCmdline(
            static_cast<int>(num(c, {"PID"})),
            str(c, {"Process", "ImageFileName"}),
            str(c, {"Args", "CommandLine"}));
        ++n;
    }
    return n;
}

size_t parseNetstat(const nlohmann::json& arr, MemoryAnalysisDatabase& db) {
    using namespace VolJson;
    if (!arr.is_array()) return 0;
    size_t n = 0;
    for (const auto& c : arr) {
        int pid = static_cast<int>(num(c, {"PID"}));
        db.insertNetworkConnection(
            num(c, {"Offset"}),
            pid,
            pid,                                    // tid
            str(c, {"Owner", "Process Name"}),
            "",                                     // family (not in netstat)
            "",                                     // type
            str(c, {"Proto"}),
            str(c, {"LocalAddr", "Source Addr"}),
            str(c, {"LocalPort", "Source Port"}),
            str(c, {"ForeignAddr", "Destination Addr", "RemoteAddr"}),
            str(c, {"ForeignPort", "Destination Port", "RemotePort"}),
            str(c, {"State"}),
            0);                                     // netns (Windows)
        ++n;
    }
    return n;
}

size_t parseHivelist(const nlohmann::json& arr, MemoryAnalysisDatabase& db) {
    using namespace VolJson;
    if (!arr.is_array()) return 0;
    size_t n = 0;
    for (const auto& h : arr) {
        // Store each hive path as a boot_info key/value so it surfaces without a
        // dedicated table. Key "hive:<n>", value the full path.
        db.setBootInfo("hive:" + std::to_string(n), str(h, {"FileFullPath", "File output"}));
        ++n;
    }
    return n;
}

} // namespace WindowsParsers
