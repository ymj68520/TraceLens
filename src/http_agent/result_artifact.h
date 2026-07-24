#pragma once

// A single derived artifact the client produced for an analysis task and reports
// to the server (Task 17). Mirrors the server's ResultArtifact schema
// (python_service/server/models/schemas.py:234). This is METADATA ONLY — there
// is no content field, so the raw disk image is never involved: only derived
// SQLite DBs / carved files / analysis metadata are described here.
//
// SECURITY INVARIANT: file_path is the CLIENT-LOCAL path of a *derived*
// artifact (a .db the analyzer produced). It is never the raw image path, and
// no image bytes are ever sent. The server learns the artifact exists and where
// it lives on the client; content transfer (if any) is a separate, forward
// pull mechanism.

#include <cstdint>
#include <optional>
#include <string>

#include "json.hpp"

namespace tracelens {

struct ResultArtifact {
    std::string result_type;  // "database" | "file" | "metadata" (server-validated)
    std::string file_path;    // client-local path of the derived artifact (may be empty
                              // for metadata-only artifacts)
    std::optional<uint64_t> file_size;          // bytes, when known
    std::string storage_location;               // label, e.g. client hostname / "client-local"
    nlohmann::json result_metadata = nlohmann::json::object();  // extra key/value
};

inline void to_json(nlohmann::json& j, const ResultArtifact& a) {
    j = nlohmann::json::object();
    j["result_type"] = a.result_type;
    if (!a.file_path.empty()) j["file_path"] = a.file_path;
    if (a.file_size.has_value()) j["file_size"] = *a.file_size;
    if (!a.storage_location.empty()) j["storage_location"] = a.storage_location;
    j["result_metadata"] =
        a.result_metadata.is_object() ? a.result_metadata : nlohmann::json::object();
}

}  // namespace tracelens
