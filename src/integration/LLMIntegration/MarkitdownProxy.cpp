#include "MarkitdownProxy.h"
#include "../../core/Logger/Logger.h"
#include "ConfigManager/ConfigManager.h"
#include <httplib.h>

namespace forensics {
namespace llm {

MarkitdownProxy::MarkitdownProxy(const std::string& pythonServiceUrl)
    : pythonServiceUrl_(pythonServiceUrl) {}

MarkitdownProxy& MarkitdownProxy::instance() {
    static MarkitdownProxy instance(
        ConfigManager::instance().getPythonServiceUrl()
    );
    return instance;
}

std::string MarkitdownProxy::convertToMarkdown(const std::string& filePath) {
    try {
        httplib::Client cli(pythonServiceUrl_);
        cli.set_connection_timeout(10);
        cli.set_read_timeout(120);  // Large files may take time

        nlohmann::json body = {
            {"file_path", filePath}
        };

        auto res = cli.Post("/api/markitdown/convert", body.dump(), "application/json");

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

} // namespace llm
} // namespace forensics
