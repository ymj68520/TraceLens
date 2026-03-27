#pragma once

#include <string>
#include <vector>
#include <sstream>
#include <map>

namespace forensics {
namespace llm {

// Forward declaration from LLMDataTypes.h
struct ChunkConfig;

/**
 * @brief Text processing utilities for file analysis
 * Handles keyword parsing, token estimation, content truncation, and chunking
 */
class FileTextProcessor {
public:
    /**
     * @brief Parse keywords from LLM response
     * @param llmResponse LLM response containing keywords
     * @return Vector of parsed keywords
     */
    static std::vector<std::string> parseKeywords(const std::string& llmResponse);

    /**
     * @brief Estimate token count for content
     * @param content Text content
     * @param charsPerToken Characters per token ratio
     * @return Estimated token count
     */
    static size_t estimateTokens(const std::string& content, double charsPerToken);

    /**
     * @brief Truncate content to maximum length with smart boundaries
     * @param content Original content
     * @param maxLength Maximum length
     * @return Truncated content
     */
    static std::string truncateContent(const std::string& content, size_t maxLength);

    /**
     * @brief Find smart boundary for text splitting
     * @param content Text content
     * @param targetPos Target position
     * @return Smart boundary position
     */
    static size_t findSmartBoundary(const std::string& content, size_t targetPos);

    /**
     * @brief Split content into chunks
     * @param content Text content
     * @param config Chunk configuration
     * @return Vector of content chunks
     */
    static std::vector<std::string> splitIntoChunks(const std::string& content, const ChunkConfig& config);

    /**
     * @brief Sanitize UTF-8 string by replacing invalid sequences
     * @param str String to sanitize (modified in place)
     */
    static void sanitizeUTF8(std::string& str);
};

} // namespace llm
} // namespace forensics
