#include "FileTextProcessor.h"
#include "LLMDataTypes.h"
#include <iostream>
#include <algorithm>

namespace forensics {
namespace llm {

std::vector<std::string> FileTextProcessor::parseKeywords(const std::string& llmResponse) {
    std::vector<std::string> keywords;

    std::istringstream iss(llmResponse);
    std::string keyword;

    while (std::getline(iss, keyword, ',')) {
        // Trim whitespace
        keyword.erase(0, keyword.find_first_not_of(" \t\n\r"));
        keyword.erase(keyword.find_last_not_of(" \t\n\r") + 1);

        // Remove common prefixes like "- " or numbers
        if (!keyword.empty() && (keyword[0] == '-' || keyword[0] == '*')) {
            keyword = keyword.substr(1);
            keyword.erase(0, keyword.find_first_not_of(" "));
        }

        if (!keyword.empty() && keyword.length() > 1) {
            keywords.push_back(keyword);
        }
    }

    return keywords;
}

size_t FileTextProcessor::estimateTokens(const std::string& content, double charsPerToken) {
    if (content.empty() || charsPerToken <= 0) {
        return 0;
    }
    return static_cast<size_t>(content.size() / charsPerToken);
}

std::string FileTextProcessor::truncateContent(const std::string& content, size_t maxLength) {
    if (content.size() <= maxLength) {
        return content;
    }

    if (maxLength < 100) {
        return content.substr(0, maxLength);
    }

    // Reserve space for indicator
    const std::string indicator = "\n\n[... Content truncated due to context window limit ...]\n\n";
    size_t effectiveMax = maxLength - indicator.size();

    // Split: 70% from beginning, 30% from end
    size_t headSize = static_cast<size_t>(effectiveMax * 0.7);
    size_t tailSize = effectiveMax - headSize;

    // Find smart boundaries
    size_t headEnd = findSmartBoundary(content, headSize);
    size_t tailStart = content.size() - tailSize;

    // Adjust tail start to a smart boundary (look forward)
    for (size_t i = tailStart; i < content.size() && i < tailStart + 200; ++i) {
        char c = content[i];
        if (c == '\n' || c == '.' || c == '!' || c == '?') {
            tailStart = i + 1;
            break;
        }
    }

    std::string result;
    result.reserve(maxLength);
    result += content.substr(0, headEnd);
    result += indicator;
    if (tailStart < content.size()) {
        result += content.substr(tailStart);
    }

    return result;
}

size_t FileTextProcessor::findSmartBoundary(const std::string& content, size_t targetPos) {
    if (targetPos >= content.size()) {
        return content.size();
    }

    // Search window: look back up to 200 chars for a good break point
    size_t searchStart = (targetPos > 200) ? targetPos - 200 : 0;

    // Priority 1: Paragraph break (double newline)
    size_t lastParagraph = std::string::npos;
    for (size_t i = searchStart; i < targetPos - 1 && i < content.size() - 1; ++i) {
        if (content[i] == '\n' && content[i + 1] == '\n') {
            lastParagraph = i + 2;
        }
    }
    if (lastParagraph != std::string::npos && lastParagraph > searchStart) {
        return lastParagraph;
    }

    // Priority 2: Sentence end (. ! ?)
    size_t lastSentence = std::string::npos;
    for (size_t i = searchStart; i < targetPos && i < content.size(); ++i) {
        char c = content[i];
        if ((c == '.' || c == '!' || c == '?') &&
            (i + 1 >= content.size() || content[i + 1] == ' ' || content[i + 1] == '\n')) {
            lastSentence = i + 1;
        }
    }
    if (lastSentence != std::string::npos && lastSentence > searchStart) {
        return lastSentence;
    }

    // Priority 3: Line break
    size_t lastLine = std::string::npos;
    for (size_t i = searchStart; i < targetPos && i < content.size(); ++i) {
        if (content[i] == '\n') {
            lastLine = i + 1;
        }
    }
    if (lastLine != std::string::npos && lastLine > searchStart) {
        return lastLine;
    }

    // Priority 4: Word break (space)
    size_t lastSpace = std::string::npos;
    for (size_t i = searchStart; i < targetPos && i < content.size(); ++i) {
        if (content[i] == ' ') {
            lastSpace = i + 1;
        }
    }
    if (lastSpace != std::string::npos && lastSpace > searchStart) {
        return lastSpace;
    }

    // Fallback: hard cut at target position
    return targetPos;
}

std::vector<std::string> FileTextProcessor::splitIntoChunks(const std::string& content, const ChunkConfig& config) {
    std::vector<std::string> chunks;

    if (content.empty()) {
        return chunks;
    }

    size_t chunkSize = config.chunkSize;
    size_t overlap = config.overlapSize;
    int maxChunks = config.maxChunks;

    if (content.size() <= chunkSize) {
        chunks.push_back(content);
        return chunks;
    }

    size_t pos = 0;
    while (pos < content.size() && static_cast<int>(chunks.size()) < maxChunks) {
        size_t endPos = std::min(pos + chunkSize, content.size());

        // Find smart boundary for chunk end
        if (endPos < content.size() && config.smartBoundary) {
            endPos = findSmartBoundary(content, endPos);
        }

        chunks.push_back(content.substr(pos, endPos - pos));

        // Move position with overlap
        if (endPos >= content.size()) {
            break;
        }
        pos = (endPos > overlap) ? endPos - overlap : endPos;
    }

    return chunks;
}

void FileTextProcessor::sanitizeUTF8(std::string& str) {
    std::string res;
    res.reserve(str.size());

    for (size_t i = 0; i < str.size(); ++i) {
        unsigned char c = static_cast<unsigned char>(str[i]);

        if (c < 0x80) {
            // ASCII character (0-127)
            res += c;
        } else {
            // Multi-byte UTF-8 sequence
            // Determine sequence length
            int len = 0;
            if ((c & 0xE0) == 0xC0) len = 2;
            else if ((c & 0xF0) == 0xE0) len = 3;
            else if ((c & 0xF8) == 0xF0) len = 4;

            // Validate sequence
            bool valid = len > 0 && (i + len <= str.size());
            if (valid) {
                for (int j = 1; j < len; ++j) {
                    if ((static_cast<unsigned char>(str[i+j]) & 0xC0) != 0x80) {
                        valid = false;
                        break;
                    }
                }
            }

            if (valid) {
                res += str.substr(i, len);
                i += len - 1;
            } else {
                // Replace invalid byte with ?
                res += '?';
            }
        }
    }

    str = std::move(res);
}

} // namespace llm
} // namespace forensics
