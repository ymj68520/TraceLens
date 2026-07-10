// WindowsParsers.h
// Parsers for Volatility3 windows.* plugin JSON output.
#pragma once
#include <nlohmann/json.hpp>
class MemoryAnalysisDatabase;

namespace WindowsParsers {
// windows.pslist -> processes table.
// Fields: CreateTime, ExitTime, Handles, ImageFileName, Offset(V), PID, PPID,
//         SessionId, Threads, Wow64.
size_t parseProcessList(const nlohmann::json& arr, MemoryAnalysisDatabase& db);

// windows.cmdline -> cmdline table.
// Fields: PID, Process, Args.
size_t parseCmdline(const nlohmann::json& arr, MemoryAnalysisDatabase& db);

// windows.netstat -> network_connections table.
// Fields: Created, ForeignAddr, ForeignPort, LocalAddr, LocalPort, Offset,
//         Owner, PID, Proto, State.
size_t parseNetstat(const nlohmann::json& arr, MemoryAnalysisDatabase& db);

// windows.registry.hivelist -> boot_info (as "registry_hive" rows) — stored as
// metadata key/values because there is no dedicated table.
// Fields: File output, FileFullPath, Offset.
size_t parseHivelist(const nlohmann::json& arr, MemoryAnalysisDatabase& db);
} // namespace WindowsParsers
