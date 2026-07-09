#include "BashHistoryParser.h"
#include "VolJson.h"
#include "../Database/MemoryAnalysisDatabase.h"
#include <string>

// linux.bash (vol3 2.x) columns: "PID", "Process", "Command", "CommandTime".
// CommandTime is an ISO-8601 string; it is the key evidence for the
// "dangerous deletion command time" (Q102) challenge question.
size_t parseBashHistory(const nlohmann::json& arr, MemoryAnalysisDatabase& db) {
    using namespace VolJson;
    if (!arr.is_array()) return 0;
    size_t n = 0, idx = 0;
    for (const auto& h : arr) {
        db.insertBashHistory(
            static_cast<int>(num(h, {"PID"})),
            str(h, {"Process"}),
            str(h, {"Command"}),
            str(h, {"CommandTime"}),
            static_cast<int>(idx++));
        ++n;
    }
    return n;
}
