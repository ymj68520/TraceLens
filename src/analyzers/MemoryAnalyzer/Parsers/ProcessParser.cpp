#include "ProcessParser.h"
#include "VolJson.h"
#include "../Database/MemoryAnalysisDatabase.h"
#include <string>

// linux.pslist (vol3 2.x) columns: "OFFSET (V)", "PID", "TID", "PPID",
// "COMM", "UID", "GID", "EUID", "EGID", "CREATION TIME", "File output".
// (No thread count / state columns in pslist.) Legacy aliases are probed
// second so older hand-authored fixtures still parse.
size_t parseProcesses(const nlohmann::json& arr, MemoryAnalysisDatabase& db) {
    using namespace VolJson;
    if (!arr.is_array()) return 0;
    size_t n = 0;
    for (const auto& p : arr) {
        db.insertProcess(
            num(p, {"OFFSET (V)", "Offset"}),
            static_cast<int>(num(p, {"PID"})),
            static_cast<int>(num(p, {"PPID"})),
            str(p, {"COMM", "Name", "Comm"}),
            static_cast<int>(num(p, {"UID"})),
            static_cast<int>(num(p, {"GID"})),
            // pslist's "CREATION TIME" is an ISO-8601 string, not a number, so it
            // cannot land in the INTEGER start_time column; only a legacy numeric
            // "Start" fixture value is stored. See report: persist creation time
            // as TEXT in a follow-up.
            static_cast<long>(num(p, {"Start"})),
            static_cast<int>(num(p, {"Threads"})),
            str(p, {"State"}));
        ++n;
    }
    return n;
}

// linux.psaux (vol3 2.x) columns: "PID", "PPID", "COMM", "ARGS".
// Feeds the cmdline table (linux.cmdline is not a real vol3 plugin).
size_t parseCmdline(const nlohmann::json& arr, MemoryAnalysisDatabase& db) {
    using namespace VolJson;
    if (!arr.is_array()) return 0;
    size_t n = 0;
    for (const auto& c : arr) {
        db.insertCmdline(
            static_cast<int>(num(c, {"PID"})),
            str(c, {"COMM", "Process", "Name"}),
            str(c, {"ARGS", "Args", "Command"}));
        ++n;
    }
    return n;
}
