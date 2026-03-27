#pragma once

#include <string>
#include <map>
#include <vector>

namespace forensics {
namespace llm {

/**
 * @brief File content extraction and type detection utilities
 * Handles reading file content and detecting file types
 */
class FileContentExtractor {
public:
    /**
     * @brief Read file content with optional size limit
     * @param path Path to the file
     * @param maxBytes Maximum bytes to read (0 = unlimited)
     * @return File content as string
     */
    static std::string readFileContent(const std::string& path, size_t maxBytes = 0);

    /**
     * @brief Detect file type based on extension and content
     * @param path Path to the file
     * @return Detected file type as string
     */
    static std::string detectFileType(const std::string& path);

    /**
     * @brief Get the extension-to-type mapping
     * @return Reference to the type map
     */
    static const std::map<std::string, std::string>& getTypeMap();

private:
    /**
     * @brief Check if file is binary by reading first bytes
     * @param path Path to the file
     * @return true if file appears to be binary
     */
    static bool isBinaryFile(const std::string& path);
};

} // namespace llm
} // namespace forensics
