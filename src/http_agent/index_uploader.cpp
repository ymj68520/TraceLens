#include "index_uploader.h"

#include "json.hpp"

namespace tracelens {

bool IndexUploader::upload(const std::vector<DiskImageEntry>& entries,
                           std::string& out_error) {
    out_error.clear();
    if (client_id_.empty()) {
        out_error = "index upload: client_id is empty";
        return false;
    }
    if (entries.empty()) {
        return true;  // nothing to report; skip the round trip
    }

    // Bare JSON array — the server param is `images: List[DiskImageCreate]`.
    nlohmann::json arr = nlohmann::json::array();
    for (const auto& e : entries) {
        nlohmann::json o = nlohmann::json::object();
        o["path"] = e.path;
        o["size_bytes"] = e.size_bytes;
        o["format"] = format_string(e.format);
        // md5_hash intentionally omitted (brief D2) -> the server treats a
        // missing field as None. image_metadata defaults to {} on the server.
        o["image_metadata"] = nlohmann::json::object();
        arr.push_back(std::move(o));
    }

    const std::string path = "/api/clients/" + client_id_ + "/index-images";
    const auto res = client_.post(path, arr.dump());
    if (!res.ok()) {
        out_error = res.error.empty()
                        ? ("index upload failed: HTTP " + std::to_string(res.status))
                        : ("index upload transport error: " + res.error);
        return false;
    }
    return true;
}

}  // namespace tracelens
