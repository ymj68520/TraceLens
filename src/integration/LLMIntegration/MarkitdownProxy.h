#pragma once
#ifndef MARKITDOWN_PROXY_H
#define MARKITDOWN_PROXY_H

#include <string>
#include <nlohmann/json.hpp>

namespace forensics {
namespace llm {

/**
 * @brief Proxy for calling the Python markitdown service via HTTP.
 *
 * Converts files to markdown by calling the Python FastAPI service's
 * /api/markitdown/convert endpoint. This allows the C++ backend to
 * leverage Microsoft's markitdown library without direct Python bindings.
 *
 * Usage:
 *   auto& proxy = MarkitdownProxy::instance();
 *   std::string markdown = proxy.convertToMarkdown("/path/to/file.pdf");
 */
class MarkitdownProxy {
public:
    /**
     * @brief Get the singleton instance.
     */
    static MarkitdownProxy& instance();

    /**
     * @brief Convert a file to markdown via the Python markitdown service.
     *
     * @param filePath Absolute path to the file to convert.
     * @return Markdown content, or empty string on failure.
     *         On error, the returned string starts with "Error: ".
     */
    std::string convertToMarkdown(const std::string& filePath);

    /**
     * @brief Check if the markitdown service is available.
     *
     * @return true if the Python service responds and markitdown is installed.
     */
    bool isServiceAvailable();

private:
    MarkitdownProxy(const std::string& pythonServiceUrl);

    std::string pythonServiceUrl_;
};

} // namespace llm
} // namespace forensics

#endif // MARKITDOWN_PROXY_H
