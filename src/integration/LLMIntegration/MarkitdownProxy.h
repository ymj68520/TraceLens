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
     * @brief Result of a batch directory conversion.
     */
    struct BatchResult {
        int total = 0;      ///< total files scanned
        int converted = 0;  ///< files successfully converted to .md
        int skipped = 0;    ///< files with no matching extractor
        int failed = 0;     ///< files that errored during conversion
        bool ok = false;    ///< whether the HTTP call itself succeeded
        std::string error;  ///< error message if !ok
    };

    /**
     * @brief Convert every file in a directory to markdown.
     *
     * Calls the Python service's /api/markitdown/batch-convert endpoint,
     * which walks inputDir recursively, routes each file through the
     * ExtractorLocator (so specialized extractors for evtx, registry, PE,
     * archives, etc. are used), and writes one .md file per source file
     * under outputDir, mirroring the directory structure.
     *
     * @param inputDir  Absolute path to the directory of files to convert.
     * @param outputDir Absolute path to the output directory for .md files.
     * @return BatchResult with per-status counts. If the HTTP call fails,
     *         BatchResult::ok is false and .error describes the problem.
     */
    BatchResult batchConvertToMarkdown(const std::string& inputDir,
                                        const std::string& outputDir);

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
