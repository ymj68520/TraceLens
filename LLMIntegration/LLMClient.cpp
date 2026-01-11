#include "LLMClient.h"

// Use httplib from cpp-mcp
#include "httplib.h"
#include "json.hpp"

#include <chrono>
#include <thread>
#include <sstream>

using json = nlohmann::json;

namespace forensics {
namespace llm {

LLMClient::LLMClient(const LLMConfig& config) : config_(config) {
    initHttpClient();
}

LLMClient::LLMClient(const std::string& baseUrl) {
    config_.baseUrl = baseUrl;
    initHttpClient();
}

LLMClient::~LLMClient() = default;

void LLMClient::initHttpClient() {
    std::lock_guard<std::mutex> lock(mutex_);
    httpClient_ = std::make_unique<httplib::Client>(config_.baseUrl);
    httpClient_->set_connection_timeout(config_.timeoutSeconds);
    httpClient_->set_read_timeout(config_.timeoutSeconds);
    httpClient_->set_write_timeout(config_.timeoutSeconds);
    ready_ = true;
}

bool LLMClient::testConnection() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!httpClient_) {
        lastError_ = "HTTP client not initialized";
        return false;
    }
    
    // Try to list models as a health check
    auto res = httpClient_->Get("/v1/models");
    if (!res) {
        lastError_ = "Connection failed: " + httplib::to_string(res.error());
        return false;
    }
    
    if (res->status != 200) {
        lastError_ = "Server returned status " + std::to_string(res->status);
        return false;
    }
    
    return true;
}

LLMResponse LLMClient::chat(const std::vector<ChatMessage>& messages,
                            const std::string& toolsJson) {
    LLMResponse response;
    
    if (!ready_ || !httpClient_) {
        response.errorMessage = "Client not ready";
        return response;
    }
    
    std::string requestBody = buildRequestBody(messages, toolsJson);
    
    int retries = 0;
    while (retries <= config_.maxRetries) {
        std::lock_guard<std::mutex> lock(mutex_);
        
        auto res = httpClient_->Post(
            config_.endpoint,
            requestBody,
            "application/json"
        );
        
        if (!res) {
            lastError_ = "Request failed: " + httplib::to_string(res.error());
            retries++;
            if (retries <= config_.maxRetries) {
                std::this_thread::sleep_for(std::chrono::milliseconds(500 * retries));
                continue;
            }
            response.errorMessage = lastError_;
            return response;
        }
        
        if (res->status == 200) {
            return parseResponse(res->body);
        }
        
        lastError_ = "Server error: " + std::to_string(res->status) + " - " + res->body;
        retries++;
        if (retries <= config_.maxRetries) {
            std::this_thread::sleep_for(std::chrono::milliseconds(500 * retries));
        }
    }
    
    response.errorMessage = lastError_;
    return response;
}

LLMResponse LLMClient::chat(const std::string& prompt, const std::string& systemPrompt) {
    std::vector<ChatMessage> messages;
    if (!systemPrompt.empty()) {
        messages.emplace_back("system", systemPrompt);
    }
    messages.emplace_back("user", prompt);
    return chat(messages);
}

std::vector<ModelInfo> LLMClient::listModels() {
    std::vector<ModelInfo> models;
    
    std::lock_guard<std::mutex> lock(mutex_);
    if (!httpClient_) {
        return models;
    }
    
    auto res = httpClient_->Get("/v1/models");
    if (!res || res->status != 200) {
        return models;
    }
    
    try {
        auto jsonData = json::parse(res->body);
        if (jsonData.contains("data") && jsonData["data"].is_array()) {
            for (const auto& item : jsonData["data"]) {
                ModelInfo info;
                info.name = item.value("id", "");
                info.description = item.value("object", "model");
                info.available = true;
                // Add default capabilities
                info.capabilities = {
                    ModelCapability::TextGeneration,
                    ModelCapability::Summarization,
                    ModelCapability::Analysis
                };
                models.push_back(info);
            }
        }
    } catch (const std::exception& e) {
        lastError_ = "Failed to parse models: " + std::string(e.what());
    }
    
    return models;
}

void LLMClient::setModel(const std::string& model) {
    std::lock_guard<std::mutex> lock(mutex_);
    config_.model = model;
}

std::string LLMClient::getModel() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return config_.model;
}

void LLMClient::setConfig(const LLMConfig& config) {
    config_ = config;
    initHttpClient();
}

const LLMConfig& LLMClient::getConfig() const {
    return config_;
}

bool LLMClient::isReady() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return ready_ && httpClient_ != nullptr;
}

std::string LLMClient::getLastError() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return lastError_;
}

std::string LLMClient::buildRequestBody(const std::vector<ChatMessage>& messages,
                                         const std::string& toolsJson) {
    json body;
    
    // Set model if specified
    if (!config_.model.empty()) {
        body["model"] = config_.model;
    }
    
    body["max_tokens"] = config_.maxTokens;
    body["temperature"] = config_.temperature;
    
    // Build messages array
    json msgArray = json::array();
    for (const auto& msg : messages) {
        json msgObj;
        msgObj["role"] = msg.role;
        msgObj["content"] = msg.content;
        if (!msg.name.empty()) {
            msgObj["name"] = msg.name;
        }
        if (!msg.toolCallId.empty()) {
            msgObj["tool_call_id"] = msg.toolCallId;
        }
        msgArray.push_back(msgObj);
    }
    body["messages"] = msgArray;
    
    // Add tools if provided
    if (!toolsJson.empty()) {
        try {
            body["tools"] = json::parse(toolsJson);
            body["tool_choice"] = "auto";
        } catch (...) {
            // Invalid tools JSON, skip
        }
    }
    
    return body.dump();
}

LLMResponse LLMClient::parseResponse(const std::string& responseBody) {
    LLMResponse response;
    
    try {
        auto jsonData = json::parse(responseBody);
        
        if (jsonData.contains("choices") && !jsonData["choices"].empty()) {
            const auto& choice = jsonData["choices"][0];
            const auto& message = choice["message"];
            
            // Extract content
            if (message.contains("content") && !message["content"].is_null()) {
                response.content = message["content"].get<std::string>();
            }
            
            // Extract tool calls
            if (message.contains("tool_calls") && message["tool_calls"].is_array()) {
                for (const auto& tc : message["tool_calls"]) {
                    ToolCall toolCall;
                    toolCall.id = tc.value("id", "");
                    if (tc.contains("function")) {
                        toolCall.name = tc["function"].value("name", "");
                        if (tc["function"]["arguments"].is_string()) {
                            toolCall.arguments = tc["function"]["arguments"].get<std::string>();
                        } else {
                            toolCall.arguments = tc["function"]["arguments"].dump();
                        }
                    }
                    response.toolCalls.push_back(toolCall);
                }
            }
            
            response.finishReason = choice.value("finish_reason", "");
            response.success = true;
        }
        
        // Extract usage info
        if (jsonData.contains("usage")) {
            response.promptTokens = jsonData["usage"].value("prompt_tokens", 0);
            response.completionTokens = jsonData["usage"].value("completion_tokens", 0);
        }
        
    } catch (const std::exception& e) {
        response.errorMessage = "Failed to parse response: " + std::string(e.what());
    }
    
    return response;
}

} // namespace llm
} // namespace forensics
