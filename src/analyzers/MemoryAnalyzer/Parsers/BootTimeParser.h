#pragma once
#include <nlohmann/json.hpp>
class MemoryAnalysisDatabase;
void parseBootTime(const nlohmann::json& arr, MemoryAnalysisDatabase& db);
