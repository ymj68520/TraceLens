#include "MarkitdownProxy.h"
#include "../../core/Logger/Logger.h"
#include "ConfigManager/ConfigManager.h"
#include <httplib.h>
#include <utility>

namespace forensics {
namespace llm {

MarkitdownProxy::MarkitdownProxy(std::string pythonServiceUrl, HttpPoster poster)
    : pythonServiceUrl_(std::move(pythonServiceUrl)),
      http_poster_(std::move(poster)) {}

MarkitdownProxy& MarkitdownProxy::instance() {
    static MarkitdownProxy instance(
        ConfigManager::instance().getPythonServiceUrl()
    );
    return instance;
}

static httplib::Result PostJson(httplib::Client& cli,
                                const std::string& path,
                                const std::string& json_body) {
    return cli.Post(path, json_body, "application/json");
}

SingleConversionResult MarkitdownProxy::convertOneToMarkdown(
        const std::string& inputRoot,
        const std::string& inputFile,
        const std::string& outputRoot,
        const std::string& taskId,
        const std::string& workspaceRoot) {
    SingleConversionResult result;
    try {
        nlohmann::json body = {
            {"input_root", inputRoot},
            {"input_file", inputFile},
            {"output_root", outputRoot},
        };
        body["task_id"] = taskId;
        body["workspace_root"] = workspaceRoot;

        const std::string payload = body.dump();
        httplib::Result res;

        if (http_poster_) {
            res = http_poster_("/api/markitdown/convert-one", payload, "application/json");
        } else {
            httplib::Client cli(pythonServiceUrl_);
            cli.set_connection_timeout(10);
            cli.set_read_timeout(120);
            res = PostJson(cli, "/api/markitdown/convert-one", payload);
        }

        if (!res) {
            result.status = SingleConversionStatus::ServiceError;
            result.error = "Service unreachable at " + pythonServiceUrl_;
            return result;
        }
        if (res->status >= 500) {
            result.status = SingleConversionStatus::ServiceError;
            result.error = "HTTP " + std::to_string(res->status) + ": " + res->body;
            return result;
        }
        if (res->status >= 400) {
            result.status = SingleConversionStatus::Failed;
            result.error = "HTTP " + std::to_string(res->status) + ": " + res->body;
            return result;
        }

        const auto response = nlohmann::json::parse(res->body);
        const std::string status = response.value("status", "failed");
        if (status == "converted") {
            result.status = SingleConversionStatus::Converted;
        } else if (status == "skipped") {
            result.status = SingleConversionStatus::Skipped;
        } else {
            result.status = SingleConversionStatus::Failed;
        }
        result.output_path = response.value("output_path", "");
        result.output_bytes = response.value("output_size", uint64_t{0});
        result.error = response.value("error", "");
        return result;
    } catch (const std::exception& ex) {
        result.status = SingleConversionStatus::ServiceError;
        result.error = ex.what();
        return result;
    }
}

std::string MarkitdownProxy::convertToMarkdown(const std::string& filePath,
                                               const std::string& taskId,
                                               const std::string& workspaceRoot) {
    try {
        nlohmann::json body = {{"file_path", filePath},
                              {"task_id", taskId},
            {"workspace_root", workspaceRoot}};
        const std::string payload = body.dump();

        if (http_poster_) {
            auto res = http_poster_("/api/markitdown/convert", payload, "application/json");
            if (res && res->status == 200) {
                auto response = nlohmann::json::parse(res->body);
                if (response.contains("success") && response["success"].get<bool>()) {
                    return response.value("content", "");
                }
                return "Error: " + response.value("error", "Unknown error");
            }

            if (res) {
                std::string detail = "HTTP " + std::to_string(res->status);
                try {
                    auto err = nlohmann::json::parse(res->body);
                    if (err.contains("detail")) detail += ": " + err["detail"].get<std::string>();
                } catch (...) {
                    detail += ": " + res->body;
                }
                return "Error: " + detail;
            }
            return "Error: Service unreachable";
        }

        httplib::Client cli(pythonServiceUrl_);
        cli.set_connection_timeout(10);
        cli.set_read_timeout(120);  // Large files may take time

        auto res = PostJson(cli, "/api/markitdown/convert", payload);

        if (res && res->status == 200) {
            auto response = nlohmann::json::parse(res->body);
            if (response.contains("success") && response["success"].get<bool>()) {
                std::string content = response.value("content", "");
                if (content.empty()) {
                    LOG_WARNING("markitdown returned empty content for: " + filePath);
                    return "";
                }
                LOG_INFO("markitdown converted " + filePath + ": " +
                         std::to_string(content.size()) + " chars");
                return content;
            } else {
                std::string error = response.value("error", "Unknown error");
                LOG_ERROR("markitdown conversion failed for " + filePath + ": " + error);
                return "Error: " + error;
            }
        }

        if (res) {
            LOG_ERROR("markitdown endpoint returned HTTP " +
                      std::to_string(res->status) + " for " + filePath +
                      ": " + res->body);
            return "Error: HTTP " + std::to_string(res->status);
        } else {
            LOG_ERROR("markitdown service unreachable at " + pythonServiceUrl_);
            return "Error: Service unreachable";
        }
    } catch (const std::exception& e) {
        LOG_ERROR("markitdown proxy exception for " + filePath + ": " + e.what());
        return "Error: " + std::string(e.what());
    }
}

bool MarkitdownProxy::isServiceAvailable() {
    try {
        httplib::Client cli(pythonServiceUrl_);
        cli.set_connection_timeout(5);
        cli.set_read_timeout(5);

        auto res = cli.Get("/api/markitdown/status");
        if (res && res->status == 200) {
            auto response = nlohmann::json::parse(res->body);
            return response.value("available", false);
        }
        return false;
    } catch (const std::exception& e) {
        LOG_WARNING("markitdown service check failed: " + std::string(e.what()));
        return false;
    }
}

MarkitdownProxy::BatchResult MarkitdownProxy::batchConvertToMarkdown(
        const std::string& inputDir, const std::string& outputDir,
        const std::string& taskId, const std::string& workspaceRoot) {
    BatchResult result;
    try {
        httplib::Client cli(pythonServiceUrl_);
        cli.set_connection_timeout(10);
        // Batch conversion of a whole directory can take a while.
        cli.set_read_timeout(600);

        nlohmann::json body = {
            {"input_dir", inputDir},
            {"output_dir", outputDir},
            {"task_id", taskId},
            {"workspace_root", workspaceRoot}
        };

        auto res = cli.Post("/api/markitdown/batch-convert",
                            body.dump(), "application/json");

        if (!res) {
            result.error = "Service unreachable at " + pythonServiceUrl_;
            LOG_ERROR("markitdown batch-convert unreachable: " + pythonServiceUrl_);
            return result;
        }

        if (res->status != 200) {
            // Try to extract the detail message from the FastAPI error body.
            std::string detail = "HTTP " + std::to_string(res->status);
            try {
                auto err = nlohmann::json::parse(res->body);
                if (err.contains("detail")) {
                    detail += ": " + err["detail"].get<std::string>();
                }
            } catch (...) {
                detail += ": " + res->body;
            }
            result.error = detail;
            LOG_ERROR("markitdown batch-convert failed: " + detail);
            return result;
        }

        const auto response = nlohmann::json::parse(res->body);
        result.ok = response.value("success", false);
        result.total = response.value("total_files", 0);
        result.converted = response.value("converted", 0);
        result.skipped = response.value("skipped", 0);
        result.failed = response.value("failed", 0);

        LOG_INFO("markitdown batch-convert: " + std::to_string(result.converted) +
                 "/" + std::to_string(result.total) + " converted, " +
                 std::to_string(result.skipped) + " skipped, " +
                 std::to_string(result.failed) + " failed");
        return result;

    } catch (const std::exception& e) {
        result.error = std::string(e.what());
        LOG_ERROR("markitdown batch-convert exception: " + result.error);
        return result;
    }
}

} // namespace llm
} // namespace forensics
