#include "MediaAnalysisProxy.h"
#include "../../core/Logger/Logger.h"
#include "ConfigManager/ConfigManager.h"
#include <httplib.h>
#include <filesystem>
#include <nlohmann/json.hpp>

namespace fs = std::filesystem;

namespace forensics {
namespace llm {

MediaAnalysisProxy::MediaAnalysisProxy(std::string pythonServiceUrl, HttpPoster poster)
    : pythonServiceUrl_(std::move(pythonServiceUrl)),
      http_poster_(std::move(poster)) {}

MediaAnalysisProxy& MediaAnalysisProxy::instance() {
    static MediaAnalysisProxy instance(
        ConfigManager::instance().getPythonServiceUrl()
    );
    return instance;
}

MediaDescriptionResult MediaAnalysisProxy::describe(
    const std::string& endpoint, const std::string& filePath) {
    MediaDescriptionResult result;
    try {
        const auto file = fs::weakly_canonical(fs::path(filePath));
        // Same workspace anchor discipline as markitdown's single-file
        // conversion: the extracted file's own parent anchors the read.
        nlohmann::json body = {
            {"file_path", file.string()},
            {"workspace_root", file.parent_path().string()},
        };
        const std::string payload = body.dump();

        httplib::Result res;
        if (http_poster_) {
            res = http_poster_(endpoint, payload, "application/json");
        } else {
            httplib::Client cli(pythonServiceUrl_);
            cli.set_connection_timeout(10);
            // Media analysis runs serial segment/segment-chunk LLM calls; a
            // sub-cap file takes minutes to tens of minutes. Allow one hour.
            cli.set_read_timeout(3600);

            res = cli.Post(endpoint, payload, "application/json");
        }

        if (!res) {
            result.error = "Service unreachable at " + pythonServiceUrl_;
            return result;
        }
        if (res->status >= 500) {
            result.error = "HTTP " + std::to_string(res->status) + ": " + res->body;
            return result;
        }
        if (res->status >= 400) {
            result.error = "HTTP " + std::to_string(res->status) + ": " + res->body;
            return result;
        }

        const auto response = nlohmann::json::parse(res->body);
        result.ok = response.value("success", false);
        const auto method = response.value("extraction_method", "");
        result.extraction_method = method;
        result.analyzed = method.find("metadata_only") == std::string::npos;
        result.description = response.value("description", "");
        result.summary = response.value("summary", "");
        result.model = response.value("model", "");
        if (!result.ok && result.error.empty()) {
            result.error = "service reported success=false";
        }
        return result;
    } catch (const std::exception& ex) {
        result.error = ex.what();
        return result;
    }
}

MediaDescriptionResult MediaAnalysisProxy::describeVideo(const std::string& filePath) {
    return describe("/api/video-analysis/describe", filePath);
}

MediaDescriptionResult MediaAnalysisProxy::describeAudio(const std::string& filePath) {
    return describe("/api/audio-analysis/transcribe", filePath);
}

} // namespace llm
} // namespace forensics
