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

// Join a base-path prefix (e.g. "/step_plan/v1") with an endpoint path
// (e.g. "/v1/chat/completions"). Endpoints that already carry the "/v1"
// prefix must not duplicate it when the base path ends in "/v1".
static std::string joinEndpoint(const std::string& basePath, const std::string& endpoint) {
    std::string ep = endpoint;
    if (basePath.size() >= 3 && basePath.substr(basePath.size() - 3) == "/v1" &&
        ep.rfind("/v1/", 0) == 0) {
        ep = ep.substr(3);
    }
    return basePath + ep;
}

// Cloud providers require the key; local servers (LM Studio) ignore it.
static httplib::Headers authHeaders(const std::string& apiKey) {
    httplib::Headers h;
    if (!apiKey.empty()) {
        h.emplace("Authorization", "Bearer " + apiKey);
    }
    return h;
}

// Replace bytes that are not part of a valid UTF-8 sequence with '?'.
// Real forensic artifacts (binary logs, wtmp, Cp1252 text) routinely carry
// such bytes, and nlohmann::json dump() throws type_error.316 on them —
// which previously aborted whole analysis stages.
static std::string sanitizeUtf8(const std::string& in) {
    std::string out;
    out.reserve(in.size());
    for (size_t i = 0; i < in.size();) {
        unsigned char c = static_cast<unsigned char>(in[i]);
        size_t need = 0;
        if (c < 0x80) {
            out.push_back(static_cast<char>(c));
            ++i;
            continue;
        } else if ((c & 0xE0) == 0xC0) need = 2;
        else if ((c & 0xF0) == 0xE0) need = 3;
        else if ((c & 0xF8) == 0xF0) need = 4;

        bool valid = need > 0 && i + need <= in.size();
        uint32_t codepoint = 0;
        if (valid) {
            if (need == 2) codepoint = c & 0x1F;
            else if (need == 3) codepoint = c & 0x0F;
            else codepoint = c & 0x07;
            for (size_t k = 1; k < need; ++k) {
                unsigned char continuation = static_cast<unsigned char>(in[i + k]);
                if ((continuation & 0xC0) != 0x80) {
                    valid = false;
                    break;
                }
                codepoint = (codepoint << 6) | (continuation & 0x3F);
            }
            // Reject overlong encodings, UTF-16 surrogate code points, and
            // values above U+10FFFF. Replace the whole invalid sequence below.
            if ((need == 2 && codepoint < 0x80) ||
                (need == 3 && codepoint < 0x800) ||
                (need == 4 && codepoint < 0x10000) ||
                (codepoint >= 0xD800 && codepoint <= 0xDFFF) ||
                codepoint > 0x10FFFF) {
                valid = false;
            }
        }
        if (valid) {
            out.append(in, i, need);
            i += need;
        } else {
            out.push_back('?');
            ++i;
        }
    }
    return out;
}

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
    // Split "scheme://host[:port]/prefix" into a connectable endpoint and a
    // path prefix. httplib's string constructor only accepts scheme://host:port
    // — a URL containing a path fails its regex and is silently treated as a
    // HOSTNAME on port 80, surfacing as "Could not establish connection".
    std::string baseUrl = config_.baseUrl;
    basePath_.clear();
    std::string schemeHostPort = baseUrl;

    size_t searchFrom = 0;
    auto schemePos = baseUrl.find("://");
    if (schemePos != std::string::npos) {
        searchFrom = schemePos + 3;
    }
    auto pathPos = baseUrl.find('/', searchFrom);
    if (pathPos != std::string::npos) {
        basePath_ = baseUrl.substr(pathPos);
        while (!basePath_.empty() && basePath_.back() == '/') {
            basePath_.pop_back();
        }
        schemeHostPort = baseUrl.substr(0, pathPos);
    }

    httpClient_ = std::make_unique<httplib::Client>(schemeHostPort);
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
    auto res = httpClient_->Get(joinEndpoint(basePath_, "/v1/models"), authHeaders(config_.apiKey));
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

    // Cloud providers require the key; local servers (LM Studio) ignore it.
    httplib::Headers requestHeaders;
    if (!config_.apiKey.empty()) {
        requestHeaders.emplace("Authorization", "Bearer " + config_.apiKey);
    }

    int retries = 0;
    while (retries <= config_.maxRetries) {
        std::lock_guard<std::mutex> lock(mutex_);

        auto res = httpClient_->Post(
            joinEndpoint(basePath_, config_.endpoint),
            requestHeaders,
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

    auto res = httpClient_->Get(joinEndpoint(basePath_, "/v1/models"), authHeaders(config_.apiKey));
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

        // Check if message contains images (vision format)
        if (msg.hasImages()) {
            // Use array content format for vision
            json contentArray = json::array();

            // Add text content first
            if (!msg.content.empty()) {
                contentArray.push_back({
                    {"type", "text"},
                    {"text", sanitizeUtf8(msg.content)}
                });
            }
            
            // Add image content
            for (const auto& img : msg.images) {
                json imageObj;
                imageObj["type"] = "image_url";
                
                json imageUrl;
                if (img.isBase64()) {
                    // Format: data:image/jpeg;base64,{base64_data}
                    std::string mimeType = img.mimeType.empty() ? "image/jpeg" : img.mimeType;
                    imageUrl["url"] = "data:" + mimeType + ";base64," + img.base64Data;
                } else if (img.isUrl()) {
                    imageUrl["url"] = img.url;
                }
                
                if (!img.detail.empty()) {
                    imageUrl["detail"] = img.detail;
                }
                
                imageObj["image_url"] = imageUrl;
                contentArray.push_back(imageObj);
            }
            
            msgObj["content"] = contentArray;
        } else {
            // Standard text format
            msgObj["content"] = sanitizeUtf8(msg.content);
        }
        
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

            // Reasoning models (e.g. qwen3.x) can exhaust the token budget on
            // chain-of-thought and return empty content with the answer in
            // reasoning_content. Fall back to it so results are not silently
            // stored as empty text.
            if (response.content.empty() && message.contains("reasoning_content") &&
                !message["reasoning_content"].is_null() &&
                message["reasoning_content"].is_string()) {
                response.content = message["reasoning_content"].get<std::string>();
            }

            // Some reasoning models inline <think>...</think> in content;
            // strip those blocks so stored descriptions stay clean.
            if (response.content.find("<think>") != std::string::npos) {
                std::string& s = response.content;
                size_t start;
                while ((start = s.find("<think>")) != std::string::npos) {
                    size_t end = s.find("</think>", start);
                    if (end == std::string::npos) {
                        s.erase(start);
                        break;
                    }
                    s.erase(start, end - start + 8);
                }
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
