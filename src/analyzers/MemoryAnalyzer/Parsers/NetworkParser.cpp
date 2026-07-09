#include "NetworkParser.h"
#include "VolJson.h"
#include "../Database/MemoryAnalysisDatabase.h"
#include <string>

// vol3 2.x has no linux.netstat plugin; the network view is derived from
// linux.sockstat, whose columns are: "NetNS", "Process Name", "PID", "TID",
// "FD", "Sock Offset", "Family", "Type", "Proto", "Source Addr",
// "Source Port", "Destination Addr", "Destination Port", "State", "Filter".
// Ports render as strings in sockstat output. Legacy aliases are probed
// second for older fixtures.

size_t parseSockstat(const nlohmann::json& arr, MemoryAnalysisDatabase& db) {
    using namespace VolJson;
    if (!arr.is_array()) return 0;
    size_t n = 0;
    for (const auto& c : arr) {
        db.insertNetworkConnection(
            num(c, {"Sock Offset", "Offset"}),
            static_cast<int>(num(c, {"PID"})),
            static_cast<int>(num(c, {"TID", "PID"})),
            str(c, {"Process Name", "Process"}),
            str(c, {"Family"}),
            str(c, {"Type"}),
            str(c, {"Proto"}),
            str(c, {"Source Addr", "LocalAddr"}),
            str(c, {"Source Port", "LocalPort"}),
            str(c, {"Destination Addr", "ForeignAddr", "RemoteAddr"}),
            str(c, {"Destination Port", "ForeignPort", "RemotePort"}),
            str(c, {"State"}),
            num(c, {"NetNS"}));
        ++n;
    }
    return n;
}
