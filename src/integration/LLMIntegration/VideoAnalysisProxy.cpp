#include "VideoAnalysisProxy.h"
#include "../../core/Logger/Logger.h"
#include "ConfigManager/ConfigManager.h"
#include <httplib.h>
#include <filesystem>
#include <nlohmann/json.hpp>

namespace fs = std::filesystem;

namespace forensics {
namespace llm {

VideoAnalysisProxy::VideoAnalysisProxy(std::string pythonServiceUrl, HttpPoster poster)
    : pythonServiceUrl_(std::move(pythonServiceUrl)),
      http_poster_(std::move(poster)) {}

VideoAnalysisProxy& VideoAnalysisProxy::instance() {
    static VideoAnalysisProxy instance(
        ConfigManager::instance().getPythonServiceUrl()
    );
    return instance;
}

VideoDescriptionResult VideoAnalysisProxy::describeVideo(const std::string& filePath) {
    VideoDescriptionResult result;
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
            res = http_poster_("/api/video-analysis/describe", payload, "application/json");
        } else {
            httplib::Client cli(pythonServiceUrl_);
            cli.set_connection_timeout(10);
            // A sub-30min video at the default sampling density takes minutes
            // to tens of minutes of serial segment calls; allow one hour.
            cli.set_read_timeout(3600);

            res = cli.Post("/api/video-analysis/describe", payload, "application/json");
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
        result.analyzed = response.value("extraction_method", "") != "video_metadata_only";
        result.description = response.value("description", "");
        result.summary = response.value("summary", "");
        result.model = response.value("model", "");
        result.extraction_method = response.value("extraction_method", "");
        if (!result.ok && result.error.empty()) {
            result.error = "service reported success=false";
        }
        return result;
    } catch (const std::exception& ex) {
        result.error = ex.what();
        return result;
    }
}

} // namespace llm
} // namespace forensics
