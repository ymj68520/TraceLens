#pragma once
#include <nlohmann/json.hpp>
class MemoryAnalysisDatabase;
size_t parseProcesses(const nlohmann::json& arr, MemoryAnalysisDatabase& db);
// Parses linux.psaux output into the cmdline table.
size_t parseCmdline(const nlohmann::json& arr, MemoryAnalysisDatabase& db);
