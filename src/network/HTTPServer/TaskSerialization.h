#pragma once

#include <nlohmann/json.hpp>
#include "HTTPServerDataTypes.h"

namespace forensics {

// Forward declarations for nlohmann::json serialization
// These must be in the same namespace as the types (forensics)
void to_json(nlohmann::json& j, const TaskProgress& p);
void from_json(const nlohmann::json& j, TaskProgress& p);
void to_json(nlohmann::json& j, const AnalysisTask& t);
void from_json(const nlohmann::json& j, AnalysisTask& t);

} // namespace forensics
