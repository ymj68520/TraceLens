#pragma once

#include <string>
#include <vector>
#include <map>
#include <cstdint>

namespace forensics {
namespace llm {

/**
 * @brief LLM connection configuration
 */
struct LLMConfig {
    std::string baseUrl = "http://localhost:1234";  // LM Studio default
    std::string endpoint = "/v1/chat/completions";
    std::string apiKey = "";  // Optional for local LM Studio
    std::string model = "";   // Model name, empty for auto-select
    int maxTokens = 2048;
    double temperature = 0.7;
    int timeoutSeconds = 60;
    int maxRetries = 3;
};

/**
 * @brief Model capability types
 */
enum class ModelCapability {
    TextGeneration,
    CodeGeneration,
    Summarization,
    Analysis,
    Translation,
    Vision,           // Image/video understanding
    ImageAnalysis     // Specialized image analysis
};

/**
 * @brief Content type for routing decisions
 */
enum class ContentType {
    Text,
    Image,
    Video,
    Audio,
    Mixed  // Contains both text and media
};

/**
 * @brief Image content for vision models
 */
struct ImageContent {
    std::string url;           // URL or base64 data URL
    std::string base64Data;    // Raw base64 encoded image
    std::string mimeType;      // e.g., "image/png", "image/jpeg"
    std::string detail = "auto"; // "low", "high", or "auto"
    
    bool isBase64() const { return !base64Data.empty(); }
    bool isUrl() const { return !url.empty() && base64Data.empty(); }
};

/**
 * @brief Model metadata for routing decisions
 */
struct ModelInfo {
    std::string name;
    std::string description;
    std::vector<ModelCapability> capabilities;
    int priority = 0;  // Higher = preferred
    bool available = true;
    int contextLength = 4096;
    bool supportsVision = false;  // Whether model can process images
    
    bool hasCapability(ModelCapability cap) const {
        for (const auto& c : capabilities) {
            if (c == cap) return true;
        }
        return false;
    }
};

/**
 * @brief Chat message structure (OpenAI format with vision support)
 */
struct ChatMessage {
    std::string role;     // "system", "user", "assistant", "tool"
    std::string content;  // Text content
    std::string name;     // Optional: function name for tool messages
    std::string toolCallId;  // Optional: for tool responses
    
    // Vision support
    std::vector<ImageContent> images;  // Images to include with the message
    ContentType contentType = ContentType::Text;
    
    ChatMessage() = default;
    ChatMessage(const std::string& r, const std::string& c) 
        : role(r), content(c), contentType(ContentType::Text) {}
    
    // Constructor with image
    ChatMessage(const std::string& r, const std::string& c, const ImageContent& img)
        : role(r), content(c), contentType(ContentType::Image) {
        images.push_back(img);
    }
    
    bool hasImages() const { return !images.empty(); }
};

/**
 * @brief Tool call from LLM response
 */
struct ToolCall {
    std::string id;
    std::string name;
    std::string arguments;  // JSON string
};

/**
 * @brief LLM response structure
 */
struct LLMResponse {
    std::string content;
    std::vector<ToolCall> toolCalls;
    std::string finishReason;  // "stop", "tool_calls", "length"
    int promptTokens = 0;
    int completionTokens = 0;
    bool success = false;
    std::string errorMessage;
};

/**
 * @brief File analysis result
 */
struct AnalysisResult {
    std::string filePath;
    std::string summary;
    std::string description;
    std::vector<std::string> keywords;
    std::string fileType;
    int64_t fileSize = 0;
    bool success = false;
    std::string errorMessage;
    
    // Analysis metadata
    std::string modelUsed;
    int tokensUsed = 0;
    double analysisTimeMs = 0;
};

/**
 * @brief Batch analysis request
 */
struct BatchAnalysisRequest {
    std::vector<std::string> filePaths;
    bool generateSummary = true;
    bool generateDescription = true;
    bool extractKeywords = true;
    int maxContentLength = 10000;  // Max chars to send to LLM per file
};

/**
 * @brief Routing strategy for multi-model
 */
enum class RoutingStrategy {
    RoundRobin,     // Distribute evenly
    Priority,       // Use highest priority available
    Capability,     // Match by capability
    LoadBalance,    // Balance by current load
    Fallback        // Try in order until success
};

} // namespace llm
} // namespace forensics
