#pragma once

#include "LLMDataTypes.h"
#include "LLMClient.h"
#include <memory>
#include <vector>
#include <map>
#include <mutex>
#include <atomic>

namespace forensics {
namespace llm {

/**
 * @brief Multi-model router for LLM requests
 * 
 * Routes requests to multiple LLM endpoints based on:
 * - Task capability requirements
 * - Model availability
 * - Priority and load balancing
 */
class ModelRouter {
public:
    ModelRouter();
    ~ModelRouter();
    
    // Non-copyable
    ModelRouter(const ModelRouter&) = delete;
    ModelRouter& operator=(const ModelRouter&) = delete;
    
    /**
     * @brief Add a model endpoint
     * @param name Unique identifier for the model
     * @param config LLM configuration
     * @param info Model metadata
     */
    void addModel(const std::string& name, 
                  const LLMConfig& config,
                  const ModelInfo& info);
    
    /**
     * @brief Remove a model endpoint
     */
    void removeModel(const std::string& name);
    
    /**
     * @brief Set routing strategy
     */
    void setStrategy(RoutingStrategy strategy);
    
    /**
     * @brief Get current routing strategy
     */
    RoutingStrategy getStrategy() const;
    
    /**
     * @brief Route and execute a chat request
     * @param messages Conversation history
     * @param requiredCapability Optional capability filter
     * @return LLM response
     */
    LLMResponse chat(const std::vector<ChatMessage>& messages,
                     ModelCapability requiredCapability = ModelCapability::TextGeneration);
    
    /**
     * @brief Simple chat with automatic routing
     */
    LLMResponse chat(const std::string& prompt, 
                     const std::string& systemPrompt = "");
    
    /**
     * @brief Get list of registered models
     */
    std::vector<std::string> getModelNames() const;
    
    /**
     * @brief Get model information
     */
    ModelInfo getModelInfo(const std::string& name) const;
    
    /**
     * @brief Check if any models are available
     */
    bool hasAvailableModels() const;
    
    /**
     * @brief Refresh model availability by testing connections
     */
    void refreshAvailability();
    
    /**
     * @brief Set preferred model (for Priority strategy)
     */
    void setPreferredModel(const std::string& name);
    
    /**
     * @brief Get last used model name
     */
    std::string getLastUsedModel() const;

private:
    struct ModelEntry {
        std::string name;
        LLMConfig config;
        ModelInfo info;
        std::unique_ptr<LLMClient> client;
        std::atomic<int> currentLoad{0};
        std::atomic<int> failureCount{0};
    };
    
    std::map<std::string, std::unique_ptr<ModelEntry>> models_;
    RoutingStrategy strategy_ = RoutingStrategy::Fallback;
    std::string preferredModel_;
    std::string lastUsedModel_;
    size_t roundRobinIndex_ = 0;
    mutable std::mutex mutex_;
    
    // Routing implementations
    LLMClient* selectByPriority(ModelCapability cap);
    LLMClient* selectByCapability(ModelCapability cap);
    LLMClient* selectByRoundRobin(ModelCapability cap);
    LLMClient* selectByLoadBalance(ModelCapability cap);
    LLMClient* selectByFallback(ModelCapability cap, LLMResponse& response);
    
    LLMClient* getClient(const std::string& name);
    std::vector<ModelEntry*> getAvailableModels(ModelCapability cap);
};

} // namespace llm
} // namespace forensics
