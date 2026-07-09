#pragma once
#include <nlohmann/json.hpp>
class MemoryAnalysisDatabase;
// Parses linux.sockstat (vol3 2.x has no linux.netstat) into
// network_connections.
size_t parseSockstat(const nlohmann::json& arr, MemoryAnalysisDatabase& db);
