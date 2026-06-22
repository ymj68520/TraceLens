#pragma once
#include <nlohmann/json.hpp>
class MemoryAnalysisDatabase;
size_t parseBashHistory(const nlohmann::json& arr, MemoryAnalysisDatabase& db);
