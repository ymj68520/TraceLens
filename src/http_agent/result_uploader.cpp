#include "result_uploader.h"

namespace tracelens {

bool ResultUploader::upload(const std::string& task_id,
                            const std::vector<ResultArtifact>& artifacts,
                            std::string& out_error) {
    out_error.clear();
    if (task_id.empty()) {
        out_error = "upload: task_id is empty (no task link on this command)";
        return false;
    }
    // Per server ResultUploadRequest { artifacts: List[ResultArtifact] }.
    nlohmann::json body = nlohmann::json::object();
    nlohmann::json arr = nlohmann::json::array();
    for (const auto& a : artifacts) arr.push_back(a);
    body["artifacts"] = arr;

    const std::string path = "/api/tasks/" + task_id + "/results";
    const auto res = client_.post(path, body.dump());
    if (!res.ok()) {
        out_error = res.error.empty()
                        ? ("result upload failed: HTTP " + std::to_string(res.status))
                        : ("result upload transport error: " + res.error);
        return false;
    }
    return true;
}

}  // namespace tracelens
