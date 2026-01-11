#pragma once

#include <string>
#include <vector>
#include <set>
#include <cstdint>

namespace forensics {

/**
 * @brief File metadata extracted from filesystem
 */
struct ExtractedMetadata {
    std::string path;
    std::string extension;
    std::string filename;
    int64_t size = 0;
    int64_t mtime = 0;       // Modification time (Unix timestamp)
    int64_t ctime = 0;       // Creation time (Unix timestamp)
    bool isText = false;     // Whether file is likely text-based
};

/**
 * @brief Helper class to extract text content from files
 * 
 * Supports basic text files and performs string extraction on binary files.
 * Future extension: Integration with poppler for PDF, etc.
 */
class TextExtractor {
public:
    /**
     * @brief Extract text from a file
     * 
     * @param path File path to extract content from
     * @return Extracted content string
     */
    static std::string extract(const std::string& path);
    
    /**
     * @brief Extract text with a size limit
     * 
     * @param path File path to extract content from
     * @param maxBytes Maximum bytes to extract (0 = unlimited)
     * @return Extracted content string
     */
    static std::string extract(const std::string& path, size_t maxBytes);

    /**
     * @brief Check if file is likely to contain text based on extension
     */
    static bool isTextFile(const std::string& extension);
    
    /**
     * @brief Extract file metadata from filesystem
     * 
     * @param path File path to get metadata from
     * @return ExtractedMetadata structure
     */
    static ExtractedMetadata extractMetadata(const std::string& path);
    
    /**
     * @brief Get the list of supported text extensions
     */
    static const std::set<std::string>& getSupportedExtensions();
    
private:
    static std::string extractFromTextFile(const std::string& path, size_t maxBytes = 0);
    static std::string extractStrings(const std::string& path, size_t minLength = 4, size_t maxBytes = 0);
    
    static const std::set<std::string> textExtensions;
};

}
