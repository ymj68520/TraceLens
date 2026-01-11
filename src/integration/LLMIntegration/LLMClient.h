#pragma once

#include "LLMDataTypes.h"
#include <memory>
#include <mutex>
#include <functional>

// Forward declarations for httplib
namespace httplib {
    class Client;
}

namespace forensics {
namespace llm {

/**
 * @brief OpenAI-compatible API client for LM Studio
 * 
 * Connects to LM Studio or any OpenAI-compatible API endpoint.
 * Supports chat completions, model listing, and tool calling.
 */
class LLMClient {
public:
    /**
     * @brief Construct with configuration
     */
    explicit LLMClient(const LLMConfig& config);
    
    /**
     * @brief Construct with base URL only (uses defaults)
     */
    explicit LLMClient(const std::string& baseUrl);
    
    ~LLMClient();
    
    // Non-copyable
    LLMClient(const LLMClient&) = delete;
    LLMClient& operator=(const LLMClient&) = delete;
    
    /**
     * @brief Test connection to the LLM server
     * @return true if server is reachable
     */
    bool testConnection();
    
    /**
     * @brief Send chat completion request
     * @param messages Conversation history
     * @param tools Optional tool definitions for function calling
     * @return LLM response with content or tool calls
     */
    LLMResponse chat(const std::vector<ChatMessage>& messages,
                     const std::string& toolsJson = "");
    
    /**
     * @brief Simple single-message chat
     * @param prompt User prompt
     * @param systemPrompt Optional system prompt
     * @return Response content or error
     */
    LLMResponse chat(const std::string& prompt, 
                     const std::string& systemPrompt = "");
    
    /**
     * @brief List available models from the server
     * @return Vector of model information
     */
    std::vector<ModelInfo> listModels();
    
    /**
     * @brief Set the active model
     */
    void setModel(const std::string& model);
    
    /**
     * @brief Get current model name
     */
    std::string getModel() const;
    
    /**
     * @brief Update configuration
     */
    void setConfig(const LLMConfig& config);
    
    /**
     * @brief Get current configuration
     */
    const LLMConfig& getConfig() const;
    
    /**
     * @brief Check if client is ready for requests
     */
    bool isReady() const;
    
    /**
     * @brief Get last error message
     */
    std::string getLastError() const;

private:
    LLMConfig config_;
    std::unique_ptr<httplib::Client> httpClient_;
    std::string lastError_;
    mutable std::mutex mutex_;
    bool ready_ = false;
    
    void initHttpClient();
    std::string buildRequestBody(const std::vector<ChatMessage>& messages,
                                  const std::string& toolsJson);
    LLMResponse parseResponse(const std::string& responseBody);
};

} // namespace llm
} // namespace forensics
