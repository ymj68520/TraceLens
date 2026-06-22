#pragma once
#include <nlohmann/json.hpp>
class MemoryAnalysisDatabase;
size_t parseProcesses(const nlohmann::json& arr, MemoryAnalysisDatabase& db);
