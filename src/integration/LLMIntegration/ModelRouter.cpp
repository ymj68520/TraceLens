#include "ModelRouter.h"
#include "LLMClient.h"
#include <algorithm>
#include <limits>

namespace forensics {
namespace llm {

ModelRouter::ModelRouter() = default;
ModelRouter::~ModelRouter() = default;

void ModelRouter::addModel(const std::string& name,
                           const LLMConfig& config,
                           const ModelInfo& info) {
    std::lock_guard<std::mutex> lock(mutex_);
    
    auto entry = std::make_unique<ModelEntry>();
    entry->name = name;
    entry->config = config;
    entry->info = info;
    entry->client = std::make_unique<LLMClient>(config);
    
    models_[name] = std::move(entry);
    
    // Set as preferred if first model
    if (preferredModel_.empty()) {
        preferredModel_ = name;
    }
}

void ModelRouter::removeModel(const std::string& name) {
    std::lock_guard<std::mutex> lock(mutex_);
    models_.erase(name);
    
    if (preferredModel_ == name) {
        preferredModel_ = models_.empty() ? "" : models_.begin()->first;
    }
}

void ModelRouter::setStrategy(RoutingStrategy strategy) {
    std::lock_guard<std::mutex> lock(mutex_);
    strategy_ = strategy;
}

RoutingStrategy ModelRouter::getStrategy() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return strategy_;
}

LLMResponse ModelRouter::chat(const std::vector<ChatMessage>& messages,
                              ModelCapability requiredCapability) {
    LLMResponse response;
    LLMClient* client = nullptr;
    
    {
        std::lock_guard<std::mutex> lock(mutex_);
        
        if (models_.empty()) {
            response.errorMessage = "No models registered";
            return response;
        }
        
        switch (strategy_) {
            case RoutingStrategy::Priority:
                client = selectByPriority(requiredCapability);
                break;
            case RoutingStrategy::Capability:
                client = selectByCapability(requiredCapability);
                break;
            case RoutingStrategy::RoundRobin:
                client = selectByRoundRobin(requiredCapability);
                break;
            case RoutingStrategy::LoadBalance:
                client = selectByLoadBalance(requiredCapability);
                break;
            case RoutingStrategy::Fallback:
            default:
                client = selectByFallback(requiredCapability, response);
                break;
        }
    }
    
    if (!client) {
        response.errorMessage = "No suitable model available";
        return response;
    }
    
    return client->chat(messages);
}

LLMResponse ModelRouter::chat(const std::string& prompt, 
                              const std::string& systemPrompt) {
    std::vector<ChatMessage> messages;
    if (!systemPrompt.empty()) {
        messages.emplace_back("system", systemPrompt);
    }
    messages.emplace_back("user", prompt);
    return chat(messages);
}

std::vector<std::string> ModelRouter::getModelNames() const {
    std::lock_guard<std::mutex> lock(mutex_);
    std::vector<std::string> names;
    for (const auto& [name, _] : models_) {
        names.push_back(name);
    }
    return names;
}

ModelInfo ModelRouter::getModelInfo(const std::string& name) const {
    std::lock_guard<std::mutex> lock(mutex_);
    auto it = models_.find(name);
    if (it != models_.end()) {
        return it->second->info;
    }
    return ModelInfo{};
}

bool ModelRouter::hasAvailableModels() const {
    std::lock_guard<std::mutex> lock(mutex_);
    for (const auto& [_, entry] : models_) {
        if (entry->info.available) {
            return true;
        }
    }
    return false;
}

void ModelRouter::refreshAvailability() {
    std::lock_guard<std::mutex> lock(mutex_);
    for (auto& [_, entry] : models_) {
        entry->info.available = entry->client->testConnection();
        if (entry->info.available) {
            entry->failureCount = 0;
        }
    }
}

void ModelRouter::setPreferredModel(const std::string& name) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (models_.find(name) != models_.end()) {
        preferredModel_ = name;
    }
}

std::string ModelRouter::getLastUsedModel() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return lastUsedModel_;
}

LLMClient* ModelRouter::selectByPriority(ModelCapability cap) {
    ModelEntry* best = nullptr;
    int highestPriority = std::numeric_limits<int>::min();
    
    for (auto& [_, entry] : models_) {
        if (entry->info.available && 
            entry->info.hasCapability(cap) &&
            entry->info.priority > highestPriority) {
            highestPriority = entry->info.priority;
            best = entry.get();
        }
    }
    
    if (best) {
        lastUsedModel_ = best->name;
        return best->client.get();
    }
    return nullptr;
}

LLMClient* ModelRouter::selectByCapability(ModelCapability cap) {
    // First try preferred model if it has the capability
    if (!preferredModel_.empty()) {
        auto it = models_.find(preferredModel_);
        if (it != models_.end() && 
            it->second->info.available &&
            it->second->info.hasCapability(cap)) {
            lastUsedModel_ = preferredModel_;
            return it->second->client.get();
        }
    }
    
    // Fall back to any model with capability
    return selectByPriority(cap);
}

LLMClient* ModelRouter::selectByRoundRobin(ModelCapability cap) {
    auto available = getAvailableModels(cap);
    if (available.empty()) {
        return nullptr;
    }
    
    roundRobinIndex_ = (roundRobinIndex_ + 1) % available.size();
    auto* entry = available[roundRobinIndex_];
    lastUsedModel_ = entry->name;
    return entry->client.get();
}

LLMClient* ModelRouter::selectByLoadBalance(ModelCapability cap) {
    auto available = getAvailableModels(cap);
    if (available.empty()) {
        return nullptr;
    }
    
    ModelEntry* best = nullptr;
    int lowestLoad = std::numeric_limits<int>::max();
    
    for (auto* entry : available) {
        int load = entry->currentLoad.load();
        if (load < lowestLoad) {
            lowestLoad = load;
            best = entry;
        }
    }
    
    if (best) {
        best->currentLoad++;
        lastUsedModel_ = best->name;
        return best->client.get();
    }
    return nullptr;
}

LLMClient* ModelRouter::selectByFallback(ModelCapability cap, LLMResponse& response) {
    auto available = getAvailableModels(cap);
    
    // Sort by priority (highest first) then by failure count (lowest first)
    std::sort(available.begin(), available.end(), 
        [](const ModelEntry* a, const ModelEntry* b) {
            if (a->info.priority != b->info.priority) {
                return a->info.priority > b->info.priority;
            }
            return a->failureCount.load() < b->failureCount.load();
        });
    
    for (auto* entry : available) {
        lastUsedModel_ = entry->name;
        // Note: In fallback mode, we return nullptr and let the caller handle
        // The actual fallback loop should be in chat() for Fallback strategy
        return entry->client.get();
    }
    
    return nullptr;
}

LLMClient* ModelRouter::getClient(const std::string& name) {
    auto it = models_.find(name);
    if (it != models_.end()) {
        return it->second->client.get();
    }
    return nullptr;
}

std::vector<ModelRouter::ModelEntry*> ModelRouter::getAvailableModels(ModelCapability cap) {
    std::vector<ModelEntry*> result;
    for (auto& [_, entry] : models_) {
        if (entry->info.available && entry->info.hasCapability(cap)) {
            result.push_back(entry.get());
        }
    }
    return result;
}

} // namespace llm
} // namespace forensics
