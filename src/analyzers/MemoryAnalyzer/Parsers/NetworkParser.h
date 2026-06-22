#pragma once
#include <nlohmann/json.hpp>
class MemoryAnalysisDatabase;
size_t parseNetstat(const nlohmann::json& arr, MemoryAnalysisDatabase& db);
size_t parseSockstat(const nlohmann::json& arr, MemoryAnalysisDatabase& db);
