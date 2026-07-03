#include "NetworkParser.h"
#include "VolJson.h"
#include "../Database/MemoryAnalysisDatabase.h"
#include <string>

// Both network_connections and sockets are sourced from linux.sockstat, whose
// vol3 2.x columns are: "NetNS", "Process Name", "PID", "TID", "FD",
// "Sock Offset", "Family", "Type", "Proto", "Source Addr", "Source Port",
// "Destination Addr", "Destination Port", "State", "Filter".
// (linux.netstat is not a real vol3 plugin, so the connection view is derived
// from sockstat here.) Legacy aliases are probed second for older fixtures.

size_t parseNetstat(const nlohmann::json& arr, MemoryAnalysisDatabase& db) {
    using namespace VolJson;
    if (!arr.is_array()) return 0;
    size_t n = 0;
    for (const auto& c : arr) {
        db.insertNetworkConnection(
            num(c, {"Sock Offset", "Offset"}),
            static_cast<int>(num(c, {"PID"})),
            str(c, {"Process Name", "Process"}),
            str(c, {"Proto"}),
            str(c, {"Source Addr", "LocalAddr"}),
            static_cast<int>(num(c, {"Source Port", "LocalPort"})),
            str(c, {"Destination Addr", "ForeignAddr"}),
            static_cast<int>(num(c, {"Destination Port", "ForeignPort"})),
            str(c, {"State"}));
        ++n;
    }
    return n;
}

size_t parseSockstat(const nlohmann::json& arr, MemoryAnalysisDatabase& db) {
    using namespace VolJson;
    if (!arr.is_array()) return 0;
    size_t n = 0;
    for (const auto& c : arr) {
        db.insertSocket(
            num(c, {"Sock Offset", "Offset"}),
            static_cast<int>(num(c, {"PID"})),
            str(c, {"Process Name", "Process"}),
            str(c, {"Family"}),
            str(c, {"Type"}),
            str(c, {"Source Addr", "LocalAddr"}),
            str(c, {"Destination Addr", "RemoteAddr"}),
            str(c, {"State"}));
        ++n;
    }
    return n;
}
